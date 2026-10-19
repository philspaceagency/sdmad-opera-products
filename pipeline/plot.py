"""PNG quicklooks of the exported GeoTIFFs."""

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402

from . import config  # noqa: E402

NODATA_COLOR = "#4a4f57"


def _read(path: pathlib.Path):
    with rasterio.open(path) as ds:
        data = ds.read(1, masked=True)
        b = ds.bounds
    return np.ma.masked_equal(data, config.NODATA), (b.left, b.right, b.bottom, b.top)


def quicklook(tif: pathlib.Path, png: pathlib.Path, kind: str, product: config.Product, title: str) -> pathlib.Path:
    data, extent = _read(tif)

    if kind == "anomaly":
        vmin, vmax, step = config.ANOMALY_VIS
        levels = np.arange(vmin, vmax + step / 2, step)
        base = plt.get_cmap("RdBu_r", len(levels) + 1)
        cmap = ListedColormap(base(np.arange(1, len(levels)))).with_extremes(
            under=base(0), over=base(len(levels)))
        norm = BoundaryNorm(levels, cmap.N)
        label = f"{product.name} anomaly (°C)"
        extend = "both"
    else:
        vmin, vmax = product.temp_vis
        cmap = plt.get_cmap("turbo")
        norm = plt.Normalize(vmin, vmax)
        label = f"{product.name} (°C)"
        extend = "both"
    cmap = cmap.with_extremes(bad=NODATA_COLOR)

    fig, ax = plt.subplots(figsize=(7, 7.6), dpi=150)
    im = ax.imshow(data, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
    lon, lat = zip(*config.PAR_COORDS)
    ax.plot(lon, lat, color="black", linewidth=1.2)
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_title(title, fontsize=11)
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.08, fraction=0.05, extend=extend)
    cbar.set_label(label)
    if kind == "anomaly":
        cbar.set_ticks(np.arange(vmin, vmax + 0.01, 1.0))
    fig.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png)
    plt.close(fig)
    return png
