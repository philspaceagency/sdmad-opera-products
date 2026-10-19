import numpy as np
import rasterio
from rasterio.transform import from_origin

from pipeline import config, plot


def test_quicklook_writes_png(tmp_path):
    tif = tmp_path / "a.tif"
    data = np.random.default_rng(0).normal(0, 1.5, (480, 480)).astype("float32")
    data[:50] = config.NODATA
    with rasterio.open(tif, "w", driver="GTiff", width=480, height=480, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(115, 25, config.PIXEL_DEG, config.PIXEL_DEG),
                       nodata=config.NODATA) as ds:
        ds.write(data, 1)
    for kind in ("anomaly", "temperature"):
        png = plot.quicklook(tif, tmp_path / f"{kind}.png", kind, config.SST, "test")
        assert png.stat().st_size > 0


def test_results_panel_and_timeseries(tmp_path):
    import datetime as dt

    from pipeline.periods import parse_month
    from pipeline.timeseries import monthly_anomalies

    test_quicklook_writes_png(tmp_path)
    period = parse_month("2026-09")
    results = [{"product": "SST", "kind": k, "period": period, "tif": tmp_path / "a.tif"}
               for k in ("temperature", "anomaly")]
    plot.results_panel(results).savefig(tmp_path / "panel.png")

    series = [(dt.date(2018 + i // 12, i % 12 + 1, 1), None if i == 5 else 28 + (i % 12) / 6)
              for i in range(36)]
    plot.timeseries_figure(monthly_anomalies(series), config.SST).savefig(tmp_path / "ts.png")
    assert (tmp_path / "panel.png").exists() and (tmp_path / "ts.png").exists()


def test_overlay_png(tmp_path):
    test_quicklook_writes_png(tmp_path)
    url, ((s, w), (n, e)) = plot.overlay_png(tmp_path / "a.tif", "anomaly", config.SST)
    assert url.startswith("data:image/png;base64,") and (s, w, n, e) == (5.0, 115.0, 25.0, 135.0)


def test_combine_platforms():
    import datetime as dt

    from pipeline.timeseries import combine_platforms
    d = dt.date(2024, 9, 1)
    rows = combine_platforms({"terra": [(d, 30.0, 29.0, 1.0)], "aqua": [(d, 33.0, 32.0, 1.0), (dt.date(2024, 10, 1), None, 31.0, None)]})
    assert rows[0] == (d, 31.5, 30.5, 1.0) and rows[1][1] is None and rows[1][2] == 31.0
