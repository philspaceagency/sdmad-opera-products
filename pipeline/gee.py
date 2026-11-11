"""Earth Engine processing: collections, composites, climatology and anomaly."""

import datetime as dt

import ee

from . import config
from .periods import Period


def initialize(project: str = config.GEE_PROJECT) -> None:
    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)


def par_geometry() -> ee.Geometry:
    return ee.Geometry.Polygon([config.PAR_COORDS], proj=config.CRS, geodesic=False)


def nino34_geometry() -> ee.Geometry:
    return ee.Geometry.Rectangle(list(config.NINO34_BOUNDS), proj=config.CRS, geodesic=False)


def collection(product: config.Product, sat_pass: str = None, region: ee.Geometry = None) -> ee.ImageCollection:
    """Full GCOM-C time series for `product`, converted to degC and bounded to `region` (default PAR)."""
    sat_pass = sat_pass or product.default_pass
    coll = ee.ImageCollection(product.collection).filterBounds(region or par_geometry())
    if sat_pass != "both":
        coll = coll.filter(ee.Filter.eq("SATELLITE_DIRECTION", sat_pass))

    def to_celsius(img):
        raw = img.select(product.band)
        value = raw.updateMask(raw.neq(product.invalid_dn)).multiply(product.scale).add(product.offset)
        return value.rename(product.name).copyProperties(img, ["system:time_start"])

    return coll.map(to_celsius)


def date_range(coll: ee.ImageCollection) -> tuple:
    """(first, latest) acquisition dates of the collection."""
    info = ee.Dictionary({
        "first": ee.Date(coll.aggregate_min("system:time_start")).format("YYYY-MM-dd"),
        "latest": ee.Date(coll.aggregate_max("system:time_start")).format("YYYY-MM-dd"),
    }).getInfo()
    return dt.date.fromisoformat(info["first"]), dt.date.fromisoformat(info["latest"])


def _ee_date(d: dt.date) -> ee.Date:
    return ee.Date(d.isoformat())


def composite(coll: ee.ImageCollection, period: Period) -> tuple:
    """Mean temperature over `period` and the number of daily images used."""
    sub = coll.filterDate(_ee_date(period.start), _ee_date(period.end))
    return sub.mean(), sub.size()


def climatology(coll: ee.ImageCollection, period: Period, first_year: int, last_year: int) -> tuple:
    """Mean of the same calendar window across the baseline years `first_year`..`last_year`.

    Each year is composited first and the yearly composites are then averaged, so
    years with more clear-sky days do not dominate the baseline.
    """
    start, end = _ee_date(period.start), _ee_date(period.end)
    yearly = []
    for year in range(first_year, last_year + 1):
        offset = year - period.start.year
        sub = coll.filterDate(start.advance(offset, "year"), end.advance(offset, "year"))
        yearly.append(sub.mean().set("year", year, "n", sub.size()))
    years = ee.ImageCollection.fromImages(yearly).filter(ee.Filter.gt("n", 0))
    return years.mean(), years.size()


def oisst_collection(region: ee.Geometry = None) -> ee.ImageCollection:
    """NOAA OISST v2.1 daily SST in degC, bilinear-resampled so it can be added to the finer GCOM-C grid."""
    def to_celsius(img):
        return (img.select(config.OISST_BAND).multiply(config.OISST_SCALE).resample("bilinear")
                .rename("SST").copyProperties(img, ["system:time_start"]))

    return ee.ImageCollection(config.OISST_COLLECTION).filterBounds(region or par_geometry()).map(to_celsius)


def reference_offset(window: Period, baseline: tuple, reference: tuple) -> tuple:
    """OISST clim(baseline) - clim(reference) for `window`, gaps near the coast filled from neighbours.

    Same per-year-then-across-years averaging as the GCOM-C climatology. Returns (offset image,
    number of baseline years, number of reference years).
    """
    oisst = oisst_collection()
    recent, n_base = climatology(oisst, window, *baseline)
    standard, n_ref = climatology(oisst, window, *reference)
    delta = recent.subtract(standard)
    filled = delta.unmask(delta.focalMean(config.OISST_FILL_RADIUS_M, "circle", "meters"))
    return filled.rename("offset"), n_base, n_ref


def area_mean(image: ee.Image, region: ee.Geometry = None, scale_m: float = 25000) -> ee.Number:
    return ee.Number(image.reduceRegion(ee.Reducer.mean(), region or par_geometry(), scale_m,
                                        bestEffort=True).values().get(0))
