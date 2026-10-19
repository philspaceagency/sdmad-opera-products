"""PAR area-mean monthly time series over the entire GCOM-C record."""

import datetime as dt

import ee

from . import gee

# Area means do not need the native 4.6 km grid; ~25 km keeps the request light.
REDUCE_SCALE_M = 25000


def monthly_area_mean(coll: ee.ImageCollection, first: dt.date, latest: dt.date) -> list:
    """[(month_start_date, mean_degC or None), ...] for every month of the record."""
    region = gee.par_geometry()
    n_months = (latest.year - first.year) * 12 + latest.month - first.month + 1
    origin = ee.Date(dt.date(first.year, first.month, 1).isoformat())

    def one_month(i):
        start = origin.advance(i, "month")
        sub = coll.filterDate(start, start.advance(1, "month"))
        mean = sub.mean().reduceRegion(ee.Reducer.mean(), region, REDUCE_SCALE_M, bestEffort=True)
        value = ee.Algorithms.If(sub.size().gt(0), mean.values().get(0), None)
        return ee.Feature(None, {"date": start.format("YYYY-MM-dd"), "value": value})

    feats = ee.FeatureCollection(ee.List.sequence(0, n_months - 1).map(one_month)).getInfo()["features"]
    return [(dt.date.fromisoformat(f["properties"]["date"]), f["properties"].get("value")) for f in feats]


def monthly_anomalies(series: list, first_year: int = None, last_year: int = None) -> list:
    """Subtract each calendar month's mean over the baseline years.

    Returns [(date, value, climatology, anomaly), ...]; None where data is missing.
    """
    by_month = {}
    for d, v in series:
        if v is not None and (first_year is None or d.year >= first_year) \
                and (last_year is None or d.year <= last_year):
            by_month.setdefault(d.month, []).append(v)
    clim = {m: sum(vs) / len(vs) for m, vs in by_month.items()}
    rows = []
    for d, v in series:
        c = clim.get(d.month)
        rows.append((d, v, c, None if v is None or c is None else v - c))
    return rows
