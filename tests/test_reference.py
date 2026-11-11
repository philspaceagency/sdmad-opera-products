import datetime as dt

from pipeline import plot, reference


def monthly(years, f):
    return [(dt.date(y, m, 1), f(y, m)) for y in years for m in range(1, 13)]


def test_offsets_per_calendar_month():
    # warming of 0.02 degC/yr plus a seasonal cycle: 2018-2025 vs 1991-2020 differ by 0.02 * (21.5 - 5.5) = 0.32
    series = monthly(range(1991, 2026), lambda y, m: 28 + 0.02 * (y - 1991) + (1.0 if m in (5, 6) else 0.0))
    offsets = reference.calendar_month_offsets(series, (2018, 2025), (1991, 2020))
    assert set(offsets) == set(range(1, 13))
    assert all(abs(v - 0.32) < 1e-9 for v in offsets.values())


def test_apply_offsets_and_agreement():
    rows = [(dt.date(2024, m, 1), 0.1 * m) for m in range(1, 7)] + [(dt.date(2024, 7, 1), None)]
    adjusted = reference.apply_offsets(rows, {m: 0.3 for m in range(1, 13)})
    assert abs(adjusted[0][1] - 0.4) < 1e-9 and adjusted[-1][1] is None
    stats = reference.agreement(adjusted, [(d, v + 0.3) for d, v in rows if v is not None])
    assert abs(stats["mean_diff"]) < 1e-9 and stats["rmse"] < 1e-9 and abs(stats["r"] - 1) < 1e-9
    assert stats["n"] == 6


def test_reference_figure(tmp_path):
    ms = monthly(range(2018, 2027), lambda y, m: 0.0)
    g = [(d, 0.2 * ((d.month % 6) - 3) / 3) for d, _ in ms]
    offs = {m: 0.3 for m in range(1, 13)}
    region = {"gcomc": g, "gcomc_adjusted": reference.apply_offsets(g, offs),
              "oisst": [(d, v + 0.32) for d, v in g], "offsets": offs,
              "agreement_vs_oisst": reference.agreement(reference.apply_offsets(g, offs), [(d, v + 0.32) for d, v in g])}
    result = {"baseline": (2018, 2025), "reference": (1991, 2020),
              "regions": {"PAR": region, "Nino 3.4": {**region, "noaa_oni": g}}}
    plot.reference_figure(result).savefig(tmp_path / "ref.png")
    assert (tmp_path / "ref.png").exists()
