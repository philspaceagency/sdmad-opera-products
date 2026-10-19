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
