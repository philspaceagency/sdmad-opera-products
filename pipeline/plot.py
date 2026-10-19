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
    cmap, norm, label = _style(kind, product)

    fig, ax = plt.subplots(figsize=(7, 7.6), dpi=150)
    im = ax.imshow(data, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
    lon, lat = zip(*config.PAR_COORDS)
    ax.plot(lon, lat, color="black", linewidth=1.2)
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_title(title, fontsize=11)
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.08, fraction=0.05, extend="both")
    cbar.set_label(label)
    if kind == "anomaly":
        vmin, vmax, _ = config.ANOMALY_VIS
        cbar.set_ticks(np.arange(vmin, vmax + 0.01, 1.0))
    fig.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png)
    plt.close(fig)
    return png


def _style(kind: str, product: config.Product):
    if kind == "anomaly":
        vmin, vmax, step = config.ANOMALY_VIS
        levels = np.arange(vmin, vmax + step / 2, step)
        base = plt.get_cmap("RdBu_r", len(levels) + 1)
        cmap = ListedColormap(base(np.arange(1, len(levels)))).with_extremes(
            under=base(0), over=base(len(levels)), bad=NODATA_COLOR)
        return cmap, BoundaryNorm(levels, cmap.N), f"{product.name} anomaly (°C)"
    cmap = plt.get_cmap("turbo").with_extremes(bad=NODATA_COLOR)
    return cmap, plt.Normalize(*product.temp_vis), f"{product.name} (°C)"


def results_panel(results: list):
    """Side-by-side maps of every GeoTIFF the runner wrote, one row per product/period."""
    rows = {}
    for r in results:
        if "tif" in r:
            rows.setdefault((r["product"], r["period"].label), []).append(r)
    if not rows:
        return None
    ncols = max(len(v) for v in rows.values())
    fig, axes = plt.subplots(len(rows), ncols, figsize=(6 * ncols, 6.4 * len(rows)), squeeze=False, dpi=100)
    for i, ((name, label), items) in enumerate(rows.items()):
        for j in range(ncols):
            ax = axes[i][j]
            if j >= len(items):
                ax.axis("off")
                continue
            r = items[j]
            data, extent = _read(r["tif"])
            cmap, norm, cbar_label = _style(r["kind"], config.PRODUCTS[name])
            im = ax.imshow(data, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
            lon, lat = zip(*config.PAR_COORDS)
            ax.plot(lon, lat, color="black", linewidth=1)
            ax.set_title(f"{name} {r['kind']} — {label}")
            fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.06, fraction=0.05,
                         extend="both").set_label(cbar_label)
            if data.count():
                ax.text(0.01, 0.01, f"PAR mean {data.mean():+.2f} °C" if r["kind"] == "anomaly"
                        else f"PAR mean {data.mean():.2f} °C", transform=ax.transAxes, fontsize=9,
                        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
    fig.tight_layout()
    return fig


def timeseries_figure(rows: list, product: config.Product):
    """Monthly PAR-mean temperature (top) and anomaly bars (bottom)."""
    dates = [r[0] for r in rows]
    values = np.array([np.nan if r[1] is None else r[1] for r in rows])
    clim = np.array([np.nan if r[2] is None else r[2] for r in rows])
    anom = np.array([np.nan if r[3] is None else r[3] for r in rows])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, dpi=100,
                                   gridspec_kw={"height_ratios": [3, 2]})
    ax1.plot(dates, values, color="#1f4e79", linewidth=1.6, label="Monthly mean")
    ax1.plot(dates, clim, color="#888888", linewidth=1, linestyle="--", label="Climatology")
    ax1.set_ylabel(f"{product.name} (°C)")
    ax1.set_title(f"{product.long_name}, Philippine Area of Responsibility mean (GCOM-C/SGLI)")
    ax1.legend(frameon=False, loc="upper left")
    ax1.grid(alpha=0.3)

    colors = np.where(anom >= 0, "#c0392b", "#2b6cb0")
    ax2.bar(dates, np.nan_to_num(anom), width=25, color=colors)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_ylabel("Anomaly (°C)")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    return fig
