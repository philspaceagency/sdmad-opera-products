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


def collection(product: config.Product, sat_pass: str = None) -> ee.ImageCollection:
    """Full GCOM-C time series for `product`, converted to degC and bounded to PAR."""
    sat_pass = sat_pass or product.default_pass
    coll = ee.ImageCollection(product.collection).filterBounds(par_geometry())
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
    """Mean of the same calendar window across every year of the record.

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


def anomaly(temperature: ee.Image, clim: ee.Image) -> ee.Image:
    return temperature.subtract(clim)
