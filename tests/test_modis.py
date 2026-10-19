"""MODIS LST path, offline: synthetic sinusoidal 8-day tiles served as fake STAC items."""

import datetime as dt

import numpy as np
import pystac
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline import config, modis, mpc
from pipeline.periods import parse_month, shift_years

SINU = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
TILE_M = 1111950.5197665233


def dn(celsius):
    return int(round((celsius - config.LST.offset) / config.LST.scale))


def make_tile(path, h, v, value_dn, qc=0, n=120):
    px = TILE_M / n
    x0, y0 = -20015109.354 + h * TILE_M, 10007554.677 - v * TILE_M
    profile = dict(driver="GTiff", width=n, height=n, count=1, dtype="uint16", crs=SINU,
                   transform=from_origin(x0, y0, px, px), nodata=None)
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(np.full((1, n, n), value_dn, np.uint16))
    return str(path)


def make_item(tmp_path, platform, start, h, v, celsius, qc=0):
    prefix = "MOD11A2" if platform == "terra" else "MYD11A2"
    item_id = f"{prefix}.A{start:%Y%j}.h{h:02d}v{v:02d}.061"
    end = start + dt.timedelta(days=7)
    lst = make_tile(tmp_path / f"{item_id}_lst.tif", h, v, dn(celsius))
    qcp = make_tile(tmp_path / f"{item_id}_qc.tif", h, v, qc)
    item = pystac.Item(item_id, geometry=None, bbox=None, datetime=None, properties={
        "start_datetime": f"{start}T00:00:00Z", "end_datetime": f"{end}T23:59:59Z", "platform": platform})
    # geometry/bbox: lon/lat footprint of the tile
    from pyproj import Transformer
    tr = Transformer.from_crs(SINU, "EPSG:4326", always_xy=True)
    x0, y0 = -20015109.354 + h * TILE_M, 10007554.677 - v * TILE_M
    xs, ys = tr.transform([x0, x0 + TILE_M, x0, x0 + TILE_M], [y0, y0, y0 - TILE_M, y0 - TILE_M])
    item.bbox = [min(xs), min(ys), max(xs), max(ys)]
    item.geometry = {"type": "Polygon", "coordinates": [[[item.bbox[0], item.bbox[1]], [item.bbox[2], item.bbox[1]],
                     [item.bbox[2], item.bbox[3]], [item.bbox[0], item.bbox[3]], [item.bbox[0], item.bbox[1]]]]}
    item.add_asset("LST_Day_1km", pystac.Asset(lst, media_type=pystac.MediaType.COG, roles=["data"]))
    item.add_asset("QC_Day", pystac.Asset(qcp, media_type=pystac.MediaType.COG, roles=["data"]))
    return item


@pytest.fixture
def fake_mpc(monkeypatch, tmp_path):
    items = []

    def search(**query):
        lo, hi = (dt.date.fromisoformat(s[:10]) for s in query["datetime"].split("/"))
        return [i for i in items if modis.item_interval(i)[0] <= hi and modis.item_interval(i)[1] >= lo]

    monkeypatch.setattr(mpc, "search", search)
    monkeypatch.setattr(mpc, "sign_url", lambda href: href)
    mpc.set_cache_dir(tmp_path / "cache")
    yield items
    mpc.set_cache_dir(None)


def test_qc_and_conversion():
    good, other_2k, other_3k, cloudy = 0b00000000, 0b01000001, 0b10000001, 0b00000010
    assert modis.qc_ok([good, other_2k, other_3k, cloudy]).tolist() == [True, True, False, False]
    out = modis.to_celsius([dn(30.0), 0, dn(25.0)], [0, 0, cloudy])
    assert abs(out[0] - 30.0) < 0.02 and np.isnan(out[1]) and np.isnan(out[2])


def test_shift_years_keeps_window():
    assert shift_years(parse_month("2024-02"), -1) == parse_month("2023-02")
    from pipeline.periods import custom_period
    p = shift_years(custom_period("2024-02-29", "2024-03-06"), 1)
    assert p.start == dt.date(2025, 2, 28) and p.length_days == 7


def test_temperature_and_anomaly_end_to_end(fake_mpc, tmp_path):
    # two years of September composites over the tile holding Luzon (h29v07 / h30v07 straddle ~120E at 15N)
    for year, celsius in ((2023, 28.0), (2024, 30.0)):
        for start in (dt.date(year, 9, 6), dt.date(year, 9, 14)):
            for h in (29, 30):
                fake_mpc.append(make_item(tmp_path, "terra", start, h, 7, celsius))
    # one cloudy composite in 2024 that must be ignored
    fake_mpc.append(make_item(tmp_path, "terra", dt.date(2024, 9, 22), 29, 7, 50.0, qc=0b10))

    temp, anom, gbox, info = modis.temperature_and_anomaly(
        parse_month("2024-09"), "D", "terra", latest=dt.date(2024, 12, 31), pixel_deg=0.1, log=None)
    assert info["n_images"] == 3 and info["n_climatology_years"] == 2
    vals = temp[np.isfinite(temp)]
    assert vals.size > 100 and np.allclose(vals, 30.0, atol=0.02)
    assert np.allclose(anom[np.isfinite(anom)], 1.0, atol=0.02)
    # outside the PAR polygon is NaN (north-west corner: 24.9N 115.1E)
    assert np.isnan(temp[0, 0])
    # second run is served from the cache (no reads): break the reader and run again
    import pipeline.modis as m
    orig = m._load
    m._load = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should be cached"))
    try:
        temp2, _, _, _ = modis.temperature_and_anomaly(
            parse_month("2023-09"), "D", "terra", latest=dt.date(2024, 12, 31), pixel_deg=0.1, log=None)
        assert np.allclose(temp2[np.isfinite(temp2)], 28.0, atol=0.02)
    finally:
        m._load = orig


def test_both_platforms_use_their_own_climatology(fake_mpc, tmp_path):
    # Aqua runs 3 degC warmer than Terra every year; climatology includes 2024, so both anomalies are +0.5
    for year, base in ((2023, 28.0), (2024, 29.0)):
        start = dt.date(year, 9, 6)
        fake_mpc.append(make_item(tmp_path, "terra", start, 29, 7, base))
        fake_mpc.append(make_item(tmp_path, "aqua", start, 29, 7, base + 3))
    temp, anom, _, info = modis.temperature_and_anomaly(
        parse_month("2024-09"), "D", "both", latest=dt.date(2024, 12, 31), pixel_deg=0.1, log=None)
    assert set(info["platforms"]) == {"terra", "aqua"}
    assert np.allclose(temp[np.isfinite(temp)], 30.5, atol=0.02)
    assert np.allclose(anom[np.isfinite(anom)], 0.5, atol=0.02)


def test_monthly_series(fake_mpc, tmp_path):
    fake_mpc.append(make_item(tmp_path, "terra", dt.date(2024, 9, 6), 29, 7, 31.0))
    series = modis.monthly_series(dt.date(2024, 1, 1), dt.date(2024, 10, 31), "D", "terra", pixel_deg=0.2, log=None)
    values = dict(series["terra"])
    assert abs(values[dt.date(2024, 9, 1)] - 31.0) < 0.05 and values[dt.date(2024, 8, 1)] is None


def test_runner_writes_lst_temperature_and_anomaly(fake_mpc, tmp_path, monkeypatch):
    import dataclasses

    from pipeline import runner
    for year, celsius in ((2023, 29.0), (2024, 31.0)):
        fake_mpc.append(make_item(tmp_path, "terra", dt.date(year, 9, 6), 29, 7, celsius))
    monkeypatch.setattr(modis, "latest_date", lambda plats: dt.date(2024, 12, 31))
    product = dataclasses.replace(config.LST, pixel_deg=0.1)
    out = tmp_path / "outputs"
    results = runner.run_product(product, [parse_month("2024-09")], platform="terra", out=out,
                                 log=lambda *_: None)
    assert {r["kind"] for r in results} == {"temperature", "anomaly"}
    for kind, expected in (("temperature", 31.0), ("anomaly", 1.0)):
        tif = out / "LST" / kind / f"LST_{kind}_2024-09.tif"
        assert tif.with_suffix(".png").exists() and tif.with_suffix(".json").exists()
        with rasterio.open(tif) as ds:
            data = ds.read(1, masked=True)
            assert ds.crs.to_epsg() == 4326 and ds.nodata == config.NODATA
            assert np.allclose(data.compressed(), expected, atol=0.02)
