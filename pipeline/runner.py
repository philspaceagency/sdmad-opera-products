"""Run the pipeline for one product. Shared by the CLI and the notebook."""

import json
import pathlib

import ee

from . import config, export, gee, periods, plot


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


def run_product(product, targets, sat_pass=None, baseline=None, lst_anomaly=False,
                export_mode="local", out=pathlib.Path("outputs"), png=True, log=print):
    """Produce the outputs of `product` for each target period.

    `targets` is a list of Periods, or a callable taking the latest data date and returning one.
    Returns a list of dicts describing what was written.
    """
    sat_pass = sat_pass or product.default_pass
    out = pathlib.Path(out)
    coll = gee.collection(product, sat_pass)
    first, latest = gee.date_range(coll)
    first_year, last_year = baseline or (first.year, latest.year)
    log(f"[{product.name}] {product.collection} pass={sat_pass} record {first} -> {latest}, "
        f"baseline {first_year}-{last_year}")

    kinds = list(product.outputs)
    if product.name == "LST" and lst_anomaly and "anomaly" not in kinds:
        kinds.append("anomaly")

    results = []
    for period in (targets(latest) if callable(targets) else targets):
        if period.start > latest:
            log(f"[{product.name}] {period.label}: no data yet (latest {latest}), skipping")
            continue
        temp, n_images = gee.composite(coll, period)
        clim, n_years = gee.climatology(coll, period, first_year, last_year)
        images = {"temperature": temp, "anomaly": gee.anomaly(temp, clim)}

        meta = {
            "product": product.long_name,
            "collection": product.collection,
            "satellite_pass": sat_pass,
            "period_start": period.start.isoformat(),
            "period_end_exclusive": period.end.isoformat(),
            "record_first": first.isoformat(),
            "record_latest": latest.isoformat(),
            "climatology_years": f"{first_year}-{last_year}",
            "units": "degC",
            "extent": "Philippine Area of Responsibility",
        }
        counts = {"n_images": n_images}
        if "anomaly" in kinds:
            counts["n_climatology_years"] = n_years
        meta.update(ee.Dictionary(counts).getInfo())
        if meta["n_images"] == 0:
            log(f"[{product.name}] {period.label}: no images, skipping")
            continue
        if period.end > latest + periods.ONE_DAY:
            meta["note"] = f"partial period: data available up to {latest}"

        for kind in kinds:
            name = f"{product.name}_{kind}_{period.label}"
            band = f"{product.name}_{kind}"
            result = {"product": product.name, "kind": kind, "period": period, "image": images[kind],
                      "meta": meta}
            if export_mode == "drive":
                task = export.export_to_drive(images[kind], band, f"PAR_{product.name}_{kind}", name)
                log(f"[{product.name}] started Drive export {name} (task {task.id})")
                results.append({**result, "task": task})
                continue
            out_dir = out / product.name / kind
            tif = export.download_geotiff(images[kind], band, out_dir / f"{name}.tif", {**meta, "output": kind})
            (out_dir / f"{name}.json").write_text(json.dumps({**meta, "output": kind}, indent=2))
            result["tif"] = tif
            msg = f"[{product.name}] wrote {tif}"
            if png:
                title = f"{product.long_name} {'anomaly ' if kind == 'anomaly' else ''}— {period.label}\n" \
                        f"GCOM-C/SGLI, pass={sat_pass}"
                if kind == "anomaly":
                    title += f", vs {first_year}-{last_year} climatology"
                result["png"] = plot.quicklook(tif, tif.with_suffix(".png"), kind, product, title)
                msg += f" (+ {result['png'].name})"
            log(msg)
            results.append(result)
    return results
