import datetime as dt
import math

from pipeline import enso


def months(n, start=dt.date(2018, 1, 1)):
    out, y, m = [], start.year, start.month
    for _ in range(n):
        out.append(dt.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_parse_oni_maps_seasons_to_centre_month():
    text = """ SEAS  YR   TOTAL   ANOM
  DJF 2023  25.95  -0.68
  JFM 2023  26.28  -0.43
  NDJ 2023  28.72   1.95
"""
    assert enso.parse_oni(text) == [(dt.date(2023, 1, 1), -0.68), (dt.date(2023, 2, 1), -0.43),
                                    (dt.date(2023, 12, 1), 1.95)]


def test_running_mean_needs_full_window():
    rows = list(zip(months(4), [1.0, 2.0, None, 4.0]))
    assert enso.running_mean(rows) == [(rows[0][0], None), (rows[1][0], None), (rows[2][0], None),
                                       (rows[3][0], None)]
    rows = list(zip(months(3), [1.0, 2.0, 3.0]))
    assert enso.running_mean(rows)[1] == (rows[1][0], 2.0)


def test_episodes_need_five_consecutive_months():
    vals = [0.6, 0.7, 0.8, 0.9, 0.6, 0.2, -0.6, -0.7, -0.8, -0.6, 0.0]
    rows = list(zip(months(len(vals)), vals))
    eps = enso.episodes(rows)
    assert eps == [("El Nino", rows[0][0], rows[4][0])]          # La Nina run is only 4 months
    assert enso.phase_of(rows[2][0], eps) == "El Nino" and enso.phase_of(rows[7][0], eps) == "Neutral"


def test_lag_correlation_recovers_known_lag_despite_trend():
    ms = months(96)
    index = [math.sin(2 * math.pi * i / 40) for i in range(96)]
    # response follows the index 4 months later, sign-flipped, on top of a warming trend
    resp = [(-index[i - 4] if i >= 4 else 0.0) + 0.01 * i for i in range(96)]
    corr = enso.lag_correlation(list(zip(ms, index)), list(zip(ms, resp)), max_lag=8)
    best = min(corr, key=lambda c: c[1])
    assert best[0] == 4 and best[1] < -0.95


def test_offset_and_figure(tmp_path):
    ms = months(36)
    nino = [(d, 0.6 + 0.1 * (i % 5)) for i, d in enumerate(ms)]      # El Nino throughout
    noaa = [(d, 0.3 + 0.1 * (i % 5)) for i, d in enumerate(ms)]
    assert abs(enso.offset(nino, noaa) - 0.3) < 1e-9
    par = [(d, 0.2 * math.sin(i / 3)) for i, d in enumerate(ms)]
    result = {"par": par, "par_3mo": enso.running_mean(par), "nino34": nino, "nino34_3mo": enso.running_mean(nino),
              "noaa_oni": noaa, "episodes": enso.episodes(nino), "episode_source": "NOAA ONI",
              "baseline": (2018, 2025), "lag_correlation": enso.lag_correlation(nino, par, 12)}
    from pipeline import plot
    plot.enso_figure(result).savefig(tmp_path / "enso.png")
    enso.write_csv(result, tmp_path / "enso.csv")
    lines = (tmp_path / "enso.csv").read_text().splitlines()
    assert lines[0].startswith("month,par_anomaly_degC") and len(lines) == 37 and lines[1].endswith("El Nino")
