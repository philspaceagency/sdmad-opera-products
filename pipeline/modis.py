"""MODIS LST (MOD11A2 Terra + MYD11A2 Aqua, 8-day 1 km) from the Planetary Computer `modis-11A2-061` collection.

Each 8-day composite is read with odc-stac onto a lon/lat grid over the PAR, masked with its QC band, and averaged
over the target window. The climatology is built the same way for the same calendar window in every year of the
record (2000 -> latest): each year is averaged first, then the years, so cloudy years count the same as clear ones.
With both platforms, the anomaly is computed per platform against its own climatology and then averaged, because
Terra and Aqua overpass at different local times. Per-year window means are cached on disk, so the second run of
the same window (or the same month next year) only reads the new composites.
"""

import datetime as dt
import hashlib
import os
import time

import numpy as np

from . import config, mpc
from .periods import ONE_DAY, Period, shift_years

COLLECTION = config.LST.collection
BANDS = {"D": ("LST_Day_1km", "QC_Day"), "N": ("LST_Night_1km", "QC_Night")}
RECORD_START = {"terra": dt.date(2000, 2, 18), "aqua": dt.date(2002, 7, 4)}
# MOD11A2 appears ~1-2 weeks after a composite ends; younger windows are not cached.
LATENCY_DAYS = 16
DATE_BATCH = 8   # composites read per odc-stac call
# Fill for pixels outside a tile. Not 0: forcing nodata=0 makes GDAL rewrite QC 0 (= good quality) to 1.
# 65535 is invalid for both bands (QC bits 0-1 = 3: not produced).
FILL = 65535


# ------------------------------------------------------------------ pure helpers (offline-testable)
def _quiet(*_):
    pass


def item_platform(item):
    pid = item.id.upper()
    if pid.startswith("MOD"):
        return "terra"
    if pid.startswith("MYD"):
        return "aqua"
    plat = str(item.properties.get("platform", "")).lower()
    return "terra" if "terra" in plat else "aqua" if "aqua" in plat else None


def _as_date(value):
    return dt.date.fromisoformat(str(value)[:10])


def item_interval(item):
    """(first day, last day) of the 8-day composite, both inclusive."""
    p = item.properties
    start = p.get("start_datetime") or p.get("datetime")
    end = p.get("end_datetime") or start
    return _as_date(start), _as_date(end)


def overlaps(item, period: Period) -> bool:
    first, last = item_interval(item)
    return first < period.end and last >= period.start


def qc_ok(qc, max_error=config.MODIS_MAX_LST_ERROR):
    """MOD11 QC: bits 0-1 mandatory QA (0 good, 1 other, 2-3 not produced), bits 6-7 average LST error."""
    qc = np.asarray(qc).astype(np.uint16)
    return ((qc & 0b11) <= 1) & (((qc >> 6) & 0b11) <= max_error)


def to_celsius(dn, qc, max_error=config.MODIS_MAX_LST_ERROR):
    dn = np.asarray(dn)
    valid = (dn != config.LST.invalid_dn) & (dn != FILL) & qc_ok(qc, max_error)
    return np.where(valid, dn.astype(np.float32) * config.LST.scale + config.LST.offset, np.nan).astype(np.float32)


class Accumulator:
    """Running pixel-wise sum / count, NaN-aware."""

    def __init__(self, shape):
        self.sum = np.zeros(shape, np.float64)
        self.n = np.zeros(shape, np.uint16)

    def add(self, values):
        ok = np.isfinite(values)
        self.sum[ok] += values[ok]
        self.n += ok

    def mean(self):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.n > 0, self.sum / self.n, np.nan).astype(np.float32)


def nanmean_stack(arrays):
    arrays = [a for a in arrays if a is not None]
    if not arrays:
        return None
    acc = Accumulator(arrays[0].shape)
    for a in arrays:
        acc.add(a)
    return acc.mean()


def geobox(pixel_deg=config.MODIS_PIXEL_DEG):
    from affine import Affine
    from odc.geo.geobox import GeoBox
    west, south, east, north = config.PAR_BOUNDS
    shape = (round((north - south) / pixel_deg), round((east - west) / pixel_deg))
    return GeoBox(shape, Affine(pixel_deg, 0, west, 0, -pixel_deg, north), config.CRS)


def par_mask(gbox):
    """True inside the PAR polygon."""
    from rasterio.features import geometry_mask
    geom = {"type": "Polygon", "coordinates": [config.PAR_COORDS]}
    return geometry_mask([geom], out_shape=gbox.shape, transform=gbox.affine, invert=True)


# ------------------------------------------------------------------ STAC
def search_items(period: Period, platform: str, sat_pass: str):
    last = period.end - ONE_DAY
    # 8-day composites start up to 7 days before the window and still overlap it
    query_start = period.start - dt.timedelta(days=7)
    items = mpc.search(collections=[COLLECTION], bbox=list(config.PAR_BOUNDS),
                       datetime=f"{query_start.isoformat()}/{last.isoformat()}")
    lst_band, qc_band = BANDS[sat_pass]
    return [i for i in items if item_platform(i) == platform and overlaps(i, period)
            and lst_band in i.assets and qc_band in i.assets]


def latest_date(platforms=config.MODIS_PLATFORMS, today=None):
    """Last day covered by the newest composite of any of `platforms`."""
    today = today or dt.date.today()
    for lookback in (120, 730):
        items = mpc.search(collections=[COLLECTION], bbox=list(config.PAR_BOUNDS),
                           datetime=f"{(today - dt.timedelta(days=lookback)).isoformat()}/{today.isoformat()}")
        ends = [item_interval(i)[1] for i in items if item_platform(i) in platforms]
        if ends:
            return max(ends)
    raise RuntimeError(f"No {COLLECTION} items found in the last 2 years for {platforms}")


# ------------------------------------------------------------------ reading
def _load(items, bands, gbox, log):
    import odc.stac
    from rasterio.errors import RasterioError
    last = None
    for attempt in range(4):
        try:
            return odc.stac.load(items, bands=list(bands), geobox=gbox, groupby="solar_day", resampling="nearest",
                                 chunks=None, nodata=FILL, dtype="uint16", patch_url=mpc.sign_url)
        except (RasterioError, AssertionError, OSError) as e:
            last = e
            if log:
                log(f"    read retry {attempt + 1}/3 ({e.__class__.__name__})")
            time.sleep(2 ** attempt)
    raise last


def iter_composites(items, sat_pass, gbox, max_error=config.MODIS_MAX_LST_ERROR, log=print):
    """Yield (start date, degC array) for each 8-day composite in `items`, tiles mosaicked."""
    lst_band, qc_band = BANDS[sat_pass]
    by_date = {}
    for it in items:
        by_date.setdefault(item_interval(it)[0], []).append(it)
    dates = sorted(by_date)
    for k in range(0, len(dates), DATE_BATCH):
        batch = [it for d in dates[k:k + DATE_BATCH] for it in by_date[d]]
        ds = _load(batch, (lst_band, qc_band), gbox, log)
        for t in range(ds.sizes.get("time", 0)):
            day = _as_date(np.datetime_as_string(ds["time"].values[t], unit="D"))
            yield day, to_celsius(ds[lst_band].values[t], ds[qc_band].values[t], max_error)


def window_mean(period, platform, sat_pass, gbox, max_error=config.MODIS_MAX_LST_ERROR, log=print):
    """(mean degC, number of composites) over `period`; (None, 0) when there is no data."""
    items = search_items(period, platform, sat_pass)
    if not items:
        return None, 0
    acc, n = Accumulator(gbox.shape), 0
    for _, values in iter_composites(items, sat_pass, gbox, max_error, log):
        acc.add(values)
        n += 1
    return (acc.mean(), n) if n else (None, 0)


def _cache_file(period, platform, sat_pass, gbox, max_error):
    root = mpc.cache_dir()
    if not root:
        return None
    grid = hashlib.md5(f"{gbox.affine}{gbox.shape}".encode()).hexdigest()[:8]
    name = f"{platform}_{sat_pass}_qc{max_error}_{grid}_{period.start:%Y%m%d}_{period.end:%Y%m%d}.npz"
    return os.path.join(root, "modis", name)


def cached_window_mean(period, platform, sat_pass, gbox, max_error=config.MODIS_MAX_LST_ERROR, log=print,
                       today=None):
    path = _cache_file(period, platform, sat_pass, gbox, max_error)
    if path and os.path.exists(path):
        with np.load(path) as z:
            n = int(z["n"])
            return (z["mean"] if n else None), n
    mean, n = window_mean(period, platform, sat_pass, gbox, max_error, log)
    settled = period.end + dt.timedelta(days=LATENCY_DAYS) <= (today or dt.date.today())
    if path and settled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part.npz"
        np.savez_compressed(tmp, mean=mean if mean is not None else np.zeros((0,), np.float32), n=n)
        os.replace(tmp, path)
    return mean, n


# ------------------------------------------------------------------ products
def platforms_for(choice):
    return config.MODIS_PLATFORMS if choice in (None, "both") else (choice,)


def temperature_and_anomaly(period, sat_pass="D", platform="both", baseline=None, latest=None,
                            max_error=config.MODIS_MAX_LST_ERROR, pixel_deg=config.MODIS_PIXEL_DEG, log=print):
    """Target-window LST and its anomaly over the PAR, as float32 arrays (NaN = no data / outside PAR)."""
    if sat_pass not in BANDS:
        raise ValueError(f"MODIS LST pass must be 'D' or 'N' (day and night are never mixed), got {sat_pass!r}")
    log = log or _quiet
    gbox = geobox(pixel_deg)
    inside = par_mask(gbox)
    latest = latest or latest_date(platforms_for(platform))
    temps, anoms, info = [], [], {"n_images": 0, "n_climatology_years": 0, "platforms": {}}
    for plat in platforms_for(platform):
        first_year = baseline[0] if baseline else RECORD_START[plat].year
        last_year = baseline[1] if baseline else latest.year
        target, n_target = cached_window_mean(period, plat, sat_pass, gbox, max_error, log)
        log(f"[LST] {plat}: {n_target} composite(s) in {period.label}")
        if target is None:
            continue
        years = Accumulator(gbox.shape)
        n_years = 0
        for year in range(first_year, last_year + 1):
            window = shift_years(period, year - period.start.year)
            if window.end <= RECORD_START[plat] or window.start > latest:
                continue
            mean = target if window == period else cached_window_mean(window, plat, sat_pass, gbox, max_error, log)[0]
            if mean is not None:
                years.add(mean)
                n_years += 1
        log(f"[LST] {plat}: climatology from {n_years} year(s), {first_year}-{last_year}")
        clim = years.mean()
        temps.append(target)
        anoms.append(target - clim)
        info["n_images"] += n_target
        info["n_climatology_years"] = max(info["n_climatology_years"], n_years)
        info["platforms"][plat] = {"n_images": n_target, "n_climatology_years": n_years,
                                   "climatology_years": f"{first_year}-{last_year}"}
    if not temps:
        return None, None, gbox, info
    temperature = np.where(inside, nanmean_stack(temps), np.nan).astype(np.float32)
    anomaly = np.where(inside, nanmean_stack(anoms), np.nan).astype(np.float32)
    return temperature, anomaly, gbox, info


def monthly_series(first, latest, sat_pass="D", platform="both", pixel_deg=0.05,
                   max_error=config.MODIS_MAX_LST_ERROR, log=print):
    """PAR-land mean LST per month and platform: {platform: [(month start, degC or None), ...]}.

    Read on a coarse grid (COG overviews), one year at a time; finished years are cached on disk.
    """
    import json
    log = log or _quiet
    gbox = geobox(pixel_deg)
    inside = par_mask(gbox)
    out = {}
    for plat in platforms_for(platform):
        series = []
        for year in range(max(first.year, RECORD_START[plat].year), latest.year + 1):
            path = _cache_file(Period(dt.date(year, 1, 1), dt.date(year + 1, 1, 1)), plat, sat_pass, gbox,
                               max_error)
            path = path and path.replace(".npz", "_monthly.json")
            if path and os.path.exists(path):
                values = json.load(open(path))
            else:
                months = [Accumulator(gbox.shape) for _ in range(12)]
                items = search_items(Period(dt.date(year, 1, 1), dt.date(year + 1, 1, 1)), plat, sat_pass)
                for day, values_c in iter_composites(items, sat_pass, gbox, max_error, log):
                    if day.year == year:
                        months[day.month - 1].add(np.where(inside, values_c, np.nan))
                values = []
                for acc in months:
                    m = acc.mean()
                    values.append(float(np.nanmean(m)) if np.isfinite(m).any() else None)
                log(f"[LST] {plat} {year}: {sum(v is not None for v in values)} month(s)")
                if path and dt.date(year + 1, 1, 1) + dt.timedelta(days=LATENCY_DAYS) <= dt.date.today():
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    json.dump(values, open(path, "w"))
            for m, v in enumerate(values, start=1):
                d = dt.date(year, m, 1)
                if RECORD_START[plat] <= dt.date(year, m, 28) and d <= latest:
                    series.append((d, v))
        out[plat] = series
    return out
