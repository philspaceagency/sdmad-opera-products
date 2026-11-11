"""Month folders, skip/resume and GIFs, offline (fake backend instead of Earth Engine)."""

import datetime as dt
import json

import numpy as np
import pytest

from pipeline import config, modis, runner
from pipeline.periods import Period


class FakeBackend:
    subtitle = "fake"

    def __init__(self, latest):
        self._latest = latest
        self.calls = []
        self.gbox = modis.geobox(1.0)

    def latest(self):
        return self._latest

    def compute(self, period, clim_window):
        self.calls.append((period, clim_window))
        temp = np.full(self.gbox.shape, 29.0, np.float32)
        return {"temperature": temp, "anomaly": temp - 28.5}, {"n_images": period.length_days,
                                                               "n_climatology_years": 8}

    def write(self, value, band, path, tags):
        from pipeline import export
        return export.write_geotiff(value, self.gbox, band, path, tags)


def run(tmp_path, backend, start, end, **kw):
    return runner.run_range(config.SST, start, end, out=tmp_path, backend=backend, png=False, log=None, **kw)


def daily_calls(backend):
    return [p.start for p, _ in backend.calls if p.length_days == 1]


def monthly_calls(backend):
    return [p for p, _ in backend.calls if p.length_days > 1]


def test_layout_and_climatology_windows(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    s = run(tmp_path, b, "2026-10-01", "2026-10-15")
    oct_dir = tmp_path / "SST" / "2026" / "10"
    assert sorted(p.name for p in (oct_dir / "daily").glob("*.tif"))[:2] == [
        "SST_anomaly_20261001.tif", "SST_anomaly_20261002.tif"]
    assert len(list((oct_dir / "daily").glob("*.tif"))) == 30
    assert {p.name for p in (oct_dir / "monthly").glob("*.tif")} == {"SST_temperature_2026-10.tif",
                                                                     "SST_anomaly_2026-10.tif"}
    # daily: 15-day centred climatology window; monthly: the span itself
    day, clim = b.calls[0]
    assert day.start == dt.date(2026, 10, 1) and clim.start == dt.date(2026, 9, 24) and clim.length_days == 15
    meta = json.loads((oct_dir / "monthly" / "SST_anomaly_2026-10.json").read_text())
    assert meta["period_start"] == "2026-10-01" and meta["period_end_exclusive"] == "2026-10-16"
    assert meta["climatology_years"] == "2018-2025" and meta["complete_month"] is False
    assert s["pending"] is None and len(s["gifs"]) == 2


def test_second_range_only_processes_what_is_missing(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    run(tmp_path, b, "2026-10-01", "2026-10-15", gif=False)
    b.calls.clear()
    s = run(tmp_path, b, "2026-09-01", "2026-10-31", gif=False)
    days = daily_calls(b)
    assert days[0] == dt.date(2026, 9, 1) and dt.date(2026, 10, 15) not in days
    assert len(days) == 30 + 16                          # all of September + Oct 16-31
    assert monthly_calls(b) == [Period(dt.date(2026, 9, 1), dt.date(2026, 10, 1)),
                                Period(dt.date(2026, 10, 1), dt.date(2026, 11, 1))]   # Oct grows to full month
    assert (tmp_path / "SST" / "2026" / "09" / "monthly" / "SST_temperature_2026-09.tif").exists()
    meta = json.loads((tmp_path / "SST/2026/10/monthly/SST_temperature_2026-10.json").read_text())
    assert meta["complete_month"] is True
    # a third identical run computes nothing
    b.calls.clear()
    s = run(tmp_path, b, "2026-09-01", "2026-10-31")
    assert b.calls == [] and not s["written"]
    gif = tmp_path / "SST" / "animations" / "SST_anomaly_20260901_20261031.gif"
    from PIL import Image
    assert gif.exists() and Image.open(gif).n_frames == 61


def test_range_inside_existing_month_is_skipped(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    run(tmp_path, b, "2026-10-01", "2026-10-31", gif=False)
    b.calls.clear()
    run(tmp_path, b, "2026-10-10", "2026-10-12", gif=False)
    assert b.calls == []


def test_days_after_newest_data_are_left_for_later(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 10, 14))
    s = run(tmp_path, b, "2026-10-01", "2026-10-31", gif=False)
    assert s["pending"] == Period(dt.date(2026, 10, 15), dt.date(2026, 11, 1))
    assert max(daily_calls(b)) == dt.date(2026, 10, 14)
    assert monthly_calls(b) == [Period(dt.date(2026, 10, 1), dt.date(2026, 10, 15))]
    # newer data arrives: only Oct 15-31 is processed, and the month is completed
    b._latest = dt.date(2026, 11, 5)
    b.calls.clear()
    run(tmp_path, b, "2026-10-01", "2026-10-31", gif=False)
    assert daily_calls(b) == [dt.date(2026, 10, d) for d in range(15, 32)]
    assert monthly_calls(b) == [Period(dt.date(2026, 10, 1), dt.date(2026, 11, 1))]


def test_interrupted_monthly_is_rewritten(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    run(tmp_path, b, "2026-10-01", "2026-10-15", gif=False)
    (tmp_path / "SST/2026/10/monthly/SST_anomaly_2026-10.json").unlink()
    b.calls.clear()
    run(tmp_path, b, "2026-10-01", "2026-10-15", gif=False)
    assert daily_calls(b) == [] and monthly_calls(b) == [Period(dt.date(2026, 10, 1), dt.date(2026, 10, 16))]


def test_product_without_daily_writes_monthly_only(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    s = runner.run_range(config.LST, "2026-09-15", "2026-10-31", out=tmp_path, backend=b, png=False, log=None)
    assert daily_calls(b) == [] and len(monthly_calls(b)) == 2
    assert not (tmp_path / "LST" / "2026" / "10" / "daily").exists()
    assert (tmp_path / "LST" / "2026" / "09" / "monthly" / "LST_anomaly_2026-09.tif").exists()
    assert len(s["gifs"]) == 2


def test_rejects_mixed_lst_pass(tmp_path):
    with pytest.raises(ValueError):
        runner.run_range(config.LST, "2026-10-01", "2026-10-02", sat_pass="both", out=tmp_path,
                         backend=FakeBackend(dt.date(2026, 11, 1)), log=None)


class FakeReferenceBackend(FakeBackend):
    kinds = runner.KINDS + (runner.reference_kind((1991, 2020)),)

    def compute(self, period, clim_window):
        values, info = super().compute(period, clim_window)
        values["anomaly1991-2020"] = values["anomaly"] + 0.3
        return values, {**info, "reference_offset_par_mean_degC": 0.3}


def test_reference_kind_is_added_without_redoing_existing_outputs(tmp_path):
    b = FakeBackend(latest=dt.date(2026, 11, 5))
    run(tmp_path, b, "2026-10-01", "2026-10-03", gif=False)
    r = FakeReferenceBackend(latest=dt.date(2026, 11, 5))
    s = run(tmp_path, r, "2026-10-01", "2026-10-03", gif=False)
    assert s["written"] and all("anomaly1991-2020" in t.name for t in s["written"])
    assert len(s["written"]) == 4                                   # 3 daily + 1 monthly
    tif = tmp_path / "SST/2026/10/daily/SST_anomaly1991-2020_20261002.tif"
    meta = json.loads(tif.with_suffix(".json").read_text())
    assert meta["anomaly_baseline"] == "1991-2020" and "OISST" in meta["method"]
    import rasterio
    with rasterio.open(tif) as ds:
        assert np.allclose(ds.read(1, masked=True).compressed(), 0.8)
        assert ds.descriptions[0] == "SST_anomaly1991_2020"
    # nothing left to do on a rerun
    r.calls.clear()
    assert not run(tmp_path, r, "2026-10-01", "2026-10-03", gif=False)["written"] and r.calls == []
