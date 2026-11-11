"""Process a time range into month folders. Shared by the CLI and the notebook.

    outputs/<PRODUCT>/<YYYY>/<MM>/daily/<PRODUCT>_<kind>_<YYYYMMDD>.{tif,png,json}   (SST only: GCOM-C is daily)
    outputs/<PRODUCT>/<YYYY>/<MM>/monthly/<PRODUCT>_<kind>_<YYYY-MM>.{tif,png,json}
    outputs/<PRODUCT>/animations/<PRODUCT>_<kind>_<start>_<end>.gif

A range is split by calendar month. Nothing is computed twice:
  * a day whose temperature and anomaly files already exist is skipped;
  * a month's composite is recomputed only when the range adds days to what it already covers
    (its JSON records the covered span); the new composite covers the old span plus the new days;
  * days after the newest available image are left for a later run, which picks them up.
SST comes from Earth Engine (GCOM-C), LST from the Planetary Computer (MODIS MOD11A2/MYD11A2).
"""

import datetime as dt
import json
import pathlib

from . import config, periods, plot
from .periods import ONE_DAY, Period

KINDS = ("temperature", "anomaly")


# ------------------------------------------------------------------ layout
def month_dir(out, product, day, cadence):
    return pathlib.Path(out) / product.name / f"{day:%Y}" / f"{day:%m}" / cadence


def daily_tif(out, product, day, kind):
    return month_dir(out, product, day, "daily") / f"{product.name}_{kind}_{day:%Y%m%d}.tif"


def monthly_tif(out, product, day, kind):
    return month_dir(out, product, day, "monthly") / f"{product.name}_{kind}_{day:%Y-%m}.tif"


def gif_path(out, product, kind, request: Period):
    return pathlib.Path(out) / product.name / "animations" / \
        f"{product.name}_{kind}_{request.start:%Y%m%d}_{request.last:%Y%m%d}.gif"


def _done(tif):
    return tif.exists() and tif.with_suffix(".json").exists()


def _coverage(tif):
    """Span a written output covers, from its JSON sidecar."""
    if not _done(tif):
        return None
    meta = json.loads(tif.with_suffix(".json").read_text())
    return Period(dt.date.fromisoformat(meta["period_start"]), dt.date.fromisoformat(meta["period_end_exclusive"]))


# ------------------------------------------------------------------ backends
class GeeBackend:
    """GCOM-C/SGLI daily L3 on Earth Engine."""

    def __init__(self, product, sat_pass, baseline):
        from . import gee
        self.product, self.sat_pass, self.baseline = product, sat_pass, baseline
        self.coll = gee.collection(product, sat_pass)
        self.first, self._latest = gee.date_range(self.coll)
        self.subtitle = f"GCOM-C/SGLI, pass={sat_pass}"

    def latest(self):
        return self._latest

    def compute(self, period, clim_window):
        import ee

        from . import gee
        temp, n_images = gee.composite(self.coll, period)
        clim, n_years = gee.climatology(self.coll, clim_window, *self.baseline)
        info = ee.Dictionary({"n_images": n_images, "n_climatology_years": n_years}).getInfo()
        if info["n_images"] == 0:
            return None, info
        return {"temperature": temp, "anomaly": temp.subtract(clim)}, info

    def write(self, value, band, path, tags):
        from . import export
        return export.download_geotiff(value, band, path, tags)


class MpcBackend:
    """MODIS 8-day LST on the Planetary Computer (monthly outputs only)."""

    def __init__(self, product, sat_pass, baseline, platform, log):
        from . import modis
        self.product, self.sat_pass, self.baseline, self.platform, self.log = \
            product, sat_pass, baseline, platform, log
        plats = modis.platforms_for(platform)
        self.first = min(modis.RECORD_START[p] for p in plats)
        self._latest = modis.latest_date(plats)
        self.subtitle = f"MODIS {'+'.join(p.capitalize() for p in plats)}, {'day' if sat_pass == 'D' else 'night'}"
        self.gbox = None

    def latest(self):
        return self._latest

    def compute(self, period, clim_window):
        from . import modis
        temp, anom, self.gbox, info = modis.temperature_and_anomaly(
            period, self.sat_pass, self.platform, baseline=self.baseline, latest=self._latest,
            pixel_deg=self.product.pixel_deg, log=self.log)
        info = {"n_images": info["n_images"], "n_climatology_years": info["n_climatology_years"],
                "platform": self.platform, "per_platform": info["platforms"],
                "qc": f"mandatory QA good/other, LST error <= {config.MODIS_MAX_LST_ERROR + 1} K"}
        if temp is None:
            return None, info
        return {"temperature": temp, "anomaly": anom}, info

    def write(self, value, band, path, tags):
        from . import export
        return export.write_geotiff(value, self.gbox, band, path, tags)


def make_backend(product, sat_pass, baseline, platform, log):
    if product.source == "mpc":
        return MpcBackend(product, sat_pass, baseline, platform or config.MODIS_DEFAULT_PLATFORM, log)
    return GeeBackend(product, sat_pass, baseline)


# ------------------------------------------------------------------ run
def run_range(product, start, end, sat_pass=None, baseline=None, platform=None, out="outputs", png=True,
              gif=True, gif_fps=4, log=print, backend=None):
    """Process `start`..`end` (inclusive) for `product`. Returns a summary dict."""
    log = log or (lambda *_: None)
    sat_pass = sat_pass or product.default_pass
    if sat_pass not in product.passes:
        raise ValueError(f"{product.name} pass must be one of {product.passes}, got {sat_pass!r}")
    baseline = tuple(baseline or config.BASELINE)
    out = pathlib.Path(out)
    request = periods.time_range(start, end)
    backend = backend or make_backend(product, sat_pass, baseline, platform, log)
    latest = backend.latest()
    summary = {"product": product.name, "request": request, "latest": latest, "written": [], "skipped": [],
               "no_data": [], "pending": None, "gifs": []}
    log(f"[{product.name}] {request.start} -> {request.last}, pass={sat_pass}, "
        f"baseline {baseline[0]}-{baseline[1]}, newest data {latest}")

    if request.last > latest:
        pending = Period(max(request.start, latest + ONE_DAY), request.end)
        summary["pending"] = pending
        log(f"[{product.name}] no data yet for {pending.start} -> {pending.last} "
            f"(newest image {latest}); run again later to fill them in")
    ctx = dict(product=product, sat_pass=sat_pass, baseline=baseline, out=out, png=png, backend=backend,
               latest=latest, summary=summary, log=log)

    if request.start <= latest:
        available = Period(request.start, min(request.end, latest + ONE_DAY))
        for chunk in periods.split_by_month(available):
            if product.daily:
                for day in periods.days(chunk):
                    _daily(day, **ctx)
            _monthly(chunk, **ctx)

    if gif:
        summary["gifs"] = _gifs(product, request, out, backend.subtitle, gif_fps, log)
    log(f"[{product.name}] done: {len(summary['written'])} written, {len(summary['skipped'])} already there, "
        f"{len(summary['no_data'])} without images")
    return summary


def _meta(product, sat_pass, period, clim_window, baseline, latest, info, cadence):
    return {
        "product": product.long_name,
        "collection": product.collection,
        "cadence": cadence,
        "satellite_pass": sat_pass,
        "period_start": period.start.isoformat(),
        "period_end_exclusive": period.end.isoformat(),
        "climatology_years": f"{baseline[0]}-{baseline[1]}",
        "climatology_window": f"{clim_window.start:%m-%d} -> {clim_window.last:%m-%d} in each baseline year",
        "newest_data_at_processing": latest.isoformat(),
        "units": "degC",
        "extent": "Philippine Area of Responsibility",
        **info,
    }


def _write(tifs, values, meta, title, product, png, backend, summary, log):
    for kind, tif in tifs.items():
        band = f"{product.name}_{kind}"
        tags = {**meta, "output": kind}
        backend.write(values[kind], band, tif, {k: json.dumps(v) if isinstance(v, dict) else v
                                                for k, v in tags.items()})
        tif.with_suffix(".json").write_text(json.dumps(tags, indent=2, default=str))
        if png:
            heading = f"{product.long_name} {'anomaly ' if kind == 'anomaly' else ''}— {title}"
            plot.quicklook(tif, tif.with_suffix(".png"), kind, product,
                           f"{heading}\n{backend.subtitle}"
                           + (f", vs {meta['climatology_years']}" if kind == "anomaly" else ""))
        summary["written"].append(tif)
        log(f"[{product.name}] wrote {tif}")


def _daily(day, product, sat_pass, baseline, out, png, backend, latest, summary, log):
    tifs = {k: daily_tif(out, product, day, k) for k in KINDS}
    if all(_done(t) for t in tifs.values()):
        summary["skipped"].extend(tifs.values())
        return
    period = Period(day, day + ONE_DAY)
    clim_window = periods.centered_window(day, config.DAILY_CLIM_HALF_WINDOW)
    values, info = backend.compute(period, clim_window)
    if values is None:
        summary["no_data"].append(day)
        log(f"[{product.name}] {day}: no images")
        return
    meta = _meta(product, sat_pass, period, clim_window, baseline, latest, info, "daily")
    _write(tifs, values, meta, f"{day:%Y-%m-%d}", product, png, backend, summary, log)


def _monthly(chunk, product, sat_pass, baseline, out, png, backend, latest, summary, log):
    tifs = {k: monthly_tif(out, product, chunk.start, k) for k in KINDS}
    covered = [_coverage(t) for t in tifs.values()]
    old = None
    for c in covered:          # an interrupted run may have written only one of the two files
        if c is not None:
            old = periods.union(old, c)
    span = periods.union(old, chunk)
    if all(c == span for c in covered):
        summary["skipped"].extend(tifs.values())
        log(f"[{product.name}] {chunk.start:%Y-%m} monthly already covers {old.start} -> {old.last}")
        return
    values, info = backend.compute(span, span)
    if values is None:
        summary["no_data"].append(span)
        log(f"[{product.name}] {span.label}: no images")
        return
    month = periods.month_period(chunk.start.year, chunk.start.month)
    meta = _meta(product, sat_pass, span, span, baseline, latest, info, "monthly")
    meta["complete_month"] = span == month
    title = f"{chunk.start:%B %Y}" + ("" if span == month else f" ({span.start:%d}–{span.last:%d})")
    _write(tifs, values, meta, title, product, png, backend, summary, log)


def _gifs(product, request, out, subtitle, fps, log):
    """One GIF per output kind over the requested range: daily frames (SST), else monthly frames."""
    made = []
    for kind in KINDS:
        if product.daily:
            frames = [(f"{d:%Y-%m-%d}", daily_tif(out, product, d, kind)) for d in periods.days(request)]
        else:
            frames = [(f"{c.start:%B %Y}", monthly_tif(out, product, c.start, kind))
                      for c in periods.split_by_month(request)]
        frames = [(label, tif) for label, tif in frames if tif.exists()]
        if not frames:
            continue
        path = plot.make_gif(frames, kind, product, gif_path(out, product, kind, request), fps, subtitle)
        log(f"[{product.name}] GIF ({len(frames)} frames): {path}")
        made.append(path)
    return made
