"""Compare the PAR SST anomaly with the Nino 3.4 index (El Nino / La Nina).

Nino 3.4 is computed from the same GCOM-C SST and baseline as the PAR series, so the two are directly
comparable. NOAA CPC's official ONI (ERSSTv5, 30-year base periods) is fetched as the reference for
El Nino / La Nina episodes. Our Nino 3.4 uses the short 2018-2025 baseline, so it is offset from the ONI
(the offset is reported); the timing of the swings is what matters for the comparison.
"""

import datetime as dt
import math

from . import config

NOAA_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
# ONI season -> its centre month
SEASONS = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
           "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


# ------------------------------------------------------------------ pure helpers (offline-testable)
def _month_index(d):
    return d.year * 12 + d.month - 1


def running_mean(rows, n=3):
    """Centred n-month mean of [(month date, value or None), ...]; None unless all n months exist."""
    values = {_month_index(d): v for d, v in rows}
    half = n // 2
    out = []
    for d, _ in rows:
        k = _month_index(d)
        window = [values.get(k + i) for i in range(-half, half + 1)]
        out.append((d, None if any(v is None for v in window) else sum(window) / n))
    return out


def episodes(index_rows, threshold=config.ENSO_THRESHOLD, min_seasons=config.ENSO_MIN_SEASONS):
    """Runs of >= `min_seasons` consecutive months at or beyond +/-`threshold` (NOAA's ONI rule).

    Returns [(phase "El Nino" / "La Nina", first month, last month), ...].
    """
    found, run = [], []

    def close():
        if len(run) >= min_seasons:
            found.append((run[0][0], run[0][1], run[-1][1]))

    for d, v in index_rows:
        phase = None if v is None else "El Nino" if v >= threshold else "La Nina" if v <= -threshold else None
        if phase and run and run[-1][0] == phase and _month_index(d) == _month_index(run[-1][1]) + 1:
            run.append((phase, d))
            continue
        close()
        run = [(phase, d)] if phase else []
    close()
    return found


def phase_of(month, eps):
    for phase, first, last in eps:
        if first <= month <= last:
            return phase
    return "Neutral"


def parse_oni(text):
    """NOAA CPC oni.ascii.txt -> [(centre month date, ONI anomaly), ...]."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] in SEASONS:
            try:
                rows.append((dt.date(int(parts[1]), SEASONS[parts[0]], 1), float(parts[3])))
            except ValueError:
                continue
    return rows


def fetch_noaa_oni(timeout=30):
    """Official ONI from NOAA CPC, or None if it cannot be reached."""
    import requests
    try:
        resp = requests.get(NOAA_ONI_URL, timeout=timeout)
        resp.raise_for_status()
        return parse_oni(resp.text) or None
    except requests.RequestException:
        return None


def _detrend(xs):
    n = len(xs)
    t_mean, x_mean = (n - 1) / 2, sum(xs) / n
    denom = sum((t - t_mean) ** 2 for t in range(n))
    slope = sum((t - t_mean) * (x - x_mean) for t, x in enumerate(xs)) / denom if denom else 0.0
    return [x - (x_mean + slope * (t - t_mean)) for t, x in enumerate(xs)]


def _pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else float("nan")


def lag_correlation(index_rows, response_rows, max_lag=12, detrend=True):
    """Correlation of response(t + lag) with index(t), lag = 0..max_lag months (response lagging the index).

    Both series are linearly detrended first (by default), so a shared warming trend does not count as
    co-variability. Returns [(lag, r, number of months), ...].
    """
    index = {_month_index(d): v for d, v in index_rows if v is not None}
    resp = {_month_index(d): v for d, v in response_rows if v is not None}
    out = []
    for lag in range(max_lag + 1):
        keys = sorted(k for k in index if k + lag in resp)
        if len(keys) < 6:
            out.append((lag, float("nan"), len(keys)))
            continue
        a, b = [index[k] for k in keys], [resp[k + lag] for k in keys]
        if detrend:
            a, b = _detrend(a), _detrend(b)
        out.append((lag, _pearson(a, b), len(keys)))
    return out


def offset(ours, reference):
    """Mean of ours - reference over the months both have (None if no overlap)."""
    ref = {d: v for d, v in reference if v is not None}
    diffs = [v - ref[d] for d, v in ours if v is not None and d in ref]
    return sum(diffs) / len(diffs) if diffs else None


# ------------------------------------------------------------------ Earth Engine
def compare(sat_pass="both", baseline=config.BASELINE, include_noaa=True, max_lag=12, log=print):
    """PAR and Nino 3.4 monthly anomalies from GCOM-C (+ NOAA ONI), episodes and lagged correlation."""
    from . import gee, timeseries
    log = log or (lambda *_: None)
    product = config.SST
    par_coll = gee.collection(product, sat_pass)
    nino_coll = gee.collection(product, sat_pass, gee.nino34_geometry())
    first, latest = gee.date_range(par_coll)
    log(f"Monthly PAR and Nino 3.4 means {first} -> {latest}, baseline {baseline[0]}-{baseline[1]}...")
    par = timeseries.monthly_anomalies(timeseries.monthly_area_mean(par_coll, first, latest), *baseline)
    nino = timeseries.monthly_anomalies(
        timeseries.monthly_area_mean(nino_coll, first, latest, gee.nino34_geometry()), *baseline)
    par_anom = [(d, a) for d, _, _, a in par]
    nino_anom = [(d, a) for d, _, _, a in nino]
    nino_3mo = running_mean(nino_anom)
    par_3mo = running_mean(par_anom)

    noaa = fetch_noaa_oni() if include_noaa else None
    if include_noaa and noaa is None:
        log("NOAA ONI could not be fetched; episodes are taken from the GCOM-C Nino 3.4 index instead.")
    window = (dt.date(first.year, first.month, 1), latest)
    noaa = [(d, v) for d, v in (noaa or []) if window[0] <= d <= window[1]] or None
    eps = episodes(noaa or nino_3mo)
    return {
        "first": first, "latest": latest, "baseline": baseline, "sat_pass": sat_pass,
        "par": par_anom, "par_3mo": par_3mo, "nino34": nino_anom, "nino34_3mo": nino_3mo,
        "noaa_oni": noaa, "episodes": eps, "episode_source": "NOAA ONI" if noaa else "GCOM-C Nino 3.4",
        "offset_vs_noaa": offset(nino_3mo, noaa) if noaa else None,
        "lag_correlation": lag_correlation(nino_3mo, par_3mo, max_lag),
    }


def write_csv(result, path):
    import csv
    noaa = dict(result["noaa_oni"] or [])
    cols = {k: dict(result[k]) for k in ("par", "par_3mo", "nino34", "nino34_3mo")}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "par_anomaly_degC", "par_anomaly_3mo_degC", "nino34_anomaly_degC",
                    "nino34_3mo_gcomc_degC", "noaa_oni_degC", "enso_phase"])
        for d, _ in result["par"]:
            vals = [cols["par"].get(d), cols["par_3mo"].get(d), cols["nino34"].get(d), cols["nino34_3mo"].get(d),
                    noaa.get(d)]
            w.writerow([d.strftime("%Y-%m")] + ["" if v is None else round(v, 3) for v in vals]
                       + [phase_of(d, result["episodes"])])
    return path
