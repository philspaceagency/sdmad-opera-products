"""Run the pipeline for one product. Shared by the CLI and the notebook.

SST comes from Earth Engine (GCOM-C), LST from the Planetary Computer (MODIS MOD11A2/MYD11A2).
"""

import json
import pathlib

from . import config, periods, plot


def resolve_targets(latest, months=None, start=None, end=None, as_of=None, window_days=None):
    """Turn user input into a list of Periods.

    Exactly one of: `months` (list of 'YYYY-MM'), `start`+`end`, or `as_of`/`window_days`.
    With nothing given, the last complete calendar month is used.
    """
    if months:
        return [periods.parse_month(m) for m in months]
    if start or end:
        if not (start and end):
            raise ValueError("start and end must be given together")
        return [periods.custom_period(start, end)]
    if as_of is not None or window_days:
        return [periods.as_of_period(as_of or latest, window_days or 30, latest)]
    return [periods.last_complete_month(latest)]


def run_product(product, targets, sat_pass=None, baseline=None, platform=None, export_mode="local",
                out=pathlib.Path("outputs"), png=True, log=print):
    """Produce the outputs of `product` for each target period.

    `targets` is a list of Periods, or a callable taking the latest data date and returning one.
    `platform` (LST only): "terra", "aqua" or "both". Returns a list of dicts describing what was written.
    """
    sat_pass = sat_pass or product.default_pass
    if sat_pass not in product.passes:
        raise ValueError(f"{product.name} pass must be one of {product.passes}, got {sat_pass!r}")
    if product.source == "mpc":
        return _run_mpc(product, targets, sat_pass, baseline, platform or config.MODIS_DEFAULT_PLATFORM,
                        pathlib.Path(out), png, log)
    return _run_gee(product, targets, sat_pass, baseline, export_mode, pathlib.Path(out), png, log)


def _base_meta(product, sat_pass, period, first, latest, clim_years):
    return {
        "product": product.long_name,
        "collection": product.collection,
        "satellite_pass": sat_pass,
        "period_start": period.start.isoformat(),
        "period_end_exclusive": period.end.isoformat(),
        "record_first": first.isoformat(),
        "record_latest": latest.isoformat(),
        "climatology_years": clim_years,
        "units": "degC",
        "extent": "Philippine Area of Responsibility",
    }


def _finish_local(product, kind, period, meta, tif, png, subtitle, log):
    """Sidecar JSON + quicklook for a GeoTIFF that was just written."""
    tif.with_suffix(".json").write_text(json.dumps({**meta, "output": kind}, indent=2, default=str))
    result = {"product": product.name, "kind": kind, "period": period, "meta": meta, "tif": tif}
    msg = f"[{product.name}] wrote {tif}"
    if png:
        title = f"{product.long_name} {'anomaly ' if kind == 'anomaly' else ''}— {period.label}\n{subtitle}"
        if kind == "anomaly":
            title += f", vs {meta['climatology_years']} climatology"
        result["png"] = plot.quicklook(tif, tif.with_suffix(".png"), kind, product, title)
        msg += f" (+ {result['png'].name})"
    log(msg)
    return result


def _iter_periods(targets, latest, product, log):
    for period in (targets(latest) if callable(targets) else targets):
        if period.start > latest:
            log(f"[{product.name}] {period.label}: no data yet (latest {latest}), skipping")
            continue
        yield period


def _run_gee(product, targets, sat_pass, baseline, export_mode, out, png, log):
    import ee

    from . import export, gee

    coll = gee.collection(product, sat_pass)
    first, latest = gee.date_range(coll)
    first_year, last_year = baseline or (first.year, latest.year)
    log(f"[{product.name}] {product.collection} pass={sat_pass} record {first} -> {latest}, "
        f"baseline {first_year}-{last_year}")

    results = []
    for period in _iter_periods(targets, latest, product, log):
        temp, n_images = gee.composite(coll, period)
        clim, n_years = gee.climatology(coll, period, first_year, last_year)
        images = {"temperature": temp, "anomaly": gee.anomaly(temp, clim)}
        meta = _base_meta(product, sat_pass, period, first, latest, f"{first_year}-{last_year}")
        meta.update(ee.Dictionary({"n_images": n_images, "n_climatology_years": n_years}).getInfo())
        if meta["n_images"] == 0:
            log(f"[{product.name}] {period.label}: no images, skipping")
            continue
        if period.end > latest + periods.ONE_DAY:
            meta["note"] = f"partial period: data available up to {latest}"

        for kind in product.outputs:
            name = f"{product.name}_{kind}_{period.label}"
            band = f"{product.name}_{kind}"
            if export_mode == "drive":
                task = export.export_to_drive(images[kind], band, f"PAR_{product.name}_{kind}", name)
                log(f"[{product.name}] started Drive export {name} (task {task.id})")
                results.append({"product": product.name, "kind": kind, "period": period, "meta": meta,
                                "image": images[kind], "task": task})
                continue
            tif = export.download_geotiff(images[kind], band, out / product.name / kind / f"{name}.tif",
                                          {**meta, "output": kind})
            result = _finish_local(product, kind, period, meta, tif, png, f"GCOM-C/SGLI, pass={sat_pass}", log)
            results.append({**result, "image": images[kind]})
    return results


def _run_mpc(product, targets, sat_pass, baseline, platform, out, png, log):
    from . import export, modis

    plats = modis.platforms_for(platform)
    latest = modis.latest_date(plats)
    first = min(modis.RECORD_START[p] for p in plats)
    clim_years = f"{baseline[0]}-{baseline[1]}" if baseline else f"{first.year}-{latest.year}"
    log(f"[{product.name}] Planetary Computer {product.collection} ({'+'.join(plats)}) pass={sat_pass} "
        f"record {first} -> {latest}, baseline {clim_years}")

    results = []
    for period in _iter_periods(targets, latest, product, log):
        temp, anom, gbox, info = modis.temperature_and_anomaly(
            period, sat_pass, platform, baseline=baseline, latest=latest, pixel_deg=product.pixel_deg, log=log)
        if temp is None:
            log(f"[{product.name}] {period.label}: no composites, skipping")
            continue
        meta = _base_meta(product, sat_pass, period, first, latest, clim_years)
        meta.update({"platform": platform, "n_images": info["n_images"],
                     "n_climatology_years": info["n_climatology_years"], "per_platform": info["platforms"],
                     "qc": f"mandatory QA good/other, LST error <= {config.MODIS_MAX_LST_ERROR + 1} K"})
        if period.end > latest + periods.ONE_DAY:
            meta["note"] = f"partial period: data available up to {latest}"
        arrays = {"temperature": temp, "anomaly": anom}
        for kind in product.outputs:
            name = f"{product.name}_{kind}_{period.label}"
            tif = export.write_geotiff(arrays[kind], gbox, f"{product.name}_{kind}",
                                       out / product.name / kind / f"{name}.tif",
                                       {**meta, "output": kind, "per_platform": json.dumps(info["platforms"])})
            subtitle = f"MODIS {'+'.join(p.capitalize() for p in plats)} MOD11A2/MYD11A2, " \
                       f"{'day' if sat_pass == 'D' else 'night'}"
            results.append(_finish_local(product, kind, period, meta, tif, png, subtitle, log))
    return results
