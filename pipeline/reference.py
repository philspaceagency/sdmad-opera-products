"""Check the OISST offset ("method A") that moves GCOM-C anomalies to a reference baseline (1991-2020).

For the PAR and Nino 3.4 area means, per calendar month:
    offset            = OISST mean(baseline years) - OISST mean(reference years)
    GCOM-C adjusted   = GCOM-C anomaly (baseline) + offset
and compare that with OISST's own anomaly against the reference baseline (and, for Nino 3.4, the NOAA ONI).
If the method works, the adjusted GCOM-C series lies on top of the OISST one: the remaining difference is
the GCOM-C vs OISST sensor difference that is not constant in time.
"""

import datetime as dt
import math

from . import config


# ------------------------------------------------------------------ pure helpers (offline-testable)
def _monthly_means(series, years):
    by_month = {}
    for d, v in series:
        if v is not None and years[0] <= d.year <= years[1]:
            by_month.setdefault(d.month, []).append(v)
    return {m: sum(vs) / len(vs) for m, vs in by_month.items()}


def calendar_month_offsets(series, baseline, reference):
    """{month: mean(baseline years) - mean(reference years)} from a long monthly series."""
    recent, standard = _monthly_means(series, baseline), _monthly_means(series, reference)
    return {m: recent[m] - standard[m] for m in recent if m in standard}


def apply_offsets(anomaly_rows, offsets):
    return [(d, None if a is None or d.month not in offsets else a + offsets[d.month]) for d, a in anomaly_rows]


def agreement(ours, reference):
    """(mean difference, RMSE, correlation, n) over the months both series have."""
    ref = {d: v for d, v in reference if v is not None}
    pairs = [(v, ref[d]) for d, v in ours if v is not None and d in ref]
    n = len(pairs)
    if n < 3:
        return None
    diffs = [a - b for a, b in pairs]
    mean = sum(diffs) / n
    rmse = math.sqrt(sum(x * x for x in diffs) / n)
    ma, mb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    sa = math.sqrt(sum((a - ma) ** 2 for a, _ in pairs))
    sb = math.sqrt(sum((b - mb) ** 2 for _, b in pairs))
    r = sum((a - ma) * (b - mb) for a, b in pairs) / (sa * sb) if sa and sb else float("nan")
    return {"mean_diff": mean, "rmse": rmse, "r": r, "n": n}


# ------------------------------------------------------------------ Earth Engine
def validate(sat_pass="both", baseline=config.BASELINE, reference=config.REFERENCE_BASELINE, include_noaa=True,
             log=print):
    from . import enso, gee, timeseries
    log = log or (lambda *_: None)
    gcomc_par = gee.collection(config.SST, sat_pass)
    first, latest = gee.date_range(gcomc_par)
    regions = {"PAR": (gee.par_geometry(), gcomc_par),
               "Nino 3.4": (gee.nino34_geometry(), gee.collection(config.SST, sat_pass, gee.nino34_geometry()))}
    result = {"baseline": baseline, "reference": reference, "first": first, "latest": latest, "regions": {}}
    for name, (region, gcomc) in regions.items():
        log(f"{name}: GCOM-C monthly means {first} -> {latest}, OISST monthly means {reference[0]} -> {latest}...")
        g = timeseries.monthly_anomalies(timeseries.monthly_area_mean(gcomc, first, latest, region), *baseline)
        oisst_series = timeseries.monthly_area_mean(gee.oisst_collection(region), dt.date(reference[0], 1, 1),
                                                    latest, region)
        offsets = calendar_month_offsets(oisst_series, baseline, reference)
        oisst_ref = timeseries.monthly_anomalies(oisst_series, *reference)
        window = (dt.date(first.year, first.month, 1), latest)
        gcomc_anom = [(d, a) for d, _, _, a in g]
        adjusted = apply_offsets(gcomc_anom, offsets)
        oisst_anom = [(d, a) for d, _, _, a in oisst_ref if window[0] <= d <= window[1]]
        result["regions"][name] = {
            "gcomc": gcomc_anom, "gcomc_adjusted": adjusted, "oisst": oisst_anom, "offsets": offsets,
            "agreement_vs_oisst": agreement(adjusted, oisst_anom),
        }
    nino = result["regions"]["Nino 3.4"]
    noaa = enso.fetch_noaa_oni() if include_noaa else None
    nino["noaa_oni"] = [(d, v) for d, v in (noaa or []) if window[0] <= d <= window[1]] or None
    if nino["noaa_oni"]:
        nino["agreement_vs_oni"] = agreement(enso.running_mean(nino["gcomc_adjusted"]), nino["noaa_oni"])
    return result
