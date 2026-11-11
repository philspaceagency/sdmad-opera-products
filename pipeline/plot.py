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


def _draw(fig, ax, tif: pathlib.Path, kind: str, product: config.Product, title: str):
    data, extent = _read(tif)
    cmap, norm, label = _style(kind, product)
    im = ax.imshow(data, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
    lon, lat = zip(*config.PAR_COORDS)
    ax.plot(lon, lat, color="black", linewidth=1.2)
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_title(title, fontsize=11)
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.11, fraction=0.05, extend="both")
    cbar.set_label(label)
    if kind == "anomaly":
        vmin, vmax, _ = config.ANOMALY_VIS
        cbar.set_ticks(np.arange(vmin, vmax + 0.01, 1.0))
    fig.tight_layout()


def quicklook(tif: pathlib.Path, png: pathlib.Path, kind: str, product: config.Product, title: str) -> pathlib.Path:
    fig, ax = plt.subplots(figsize=(7, 7.6), dpi=150)
    _draw(fig, ax, tif, kind, product, title)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png)
    plt.close(fig)
    return png


def make_gif(frames: list, kind: str, product: config.Product, path: pathlib.Path, fps: float = 4,
             subtitle: str = "") -> pathlib.Path:
    """Animated GIF from [(frame label, GeoTIFF), ...], all frames on the same colour scale."""
    from PIL import Image

    name = f"{product.name} {'anomaly' if kind == 'anomaly' else 'temperature'}"
    title = lambda label: f"{name} — {label}" + (f"\n{subtitle}" if subtitle else "")  # noqa: E731
    fig, ax = plt.subplots(figsize=(6, 6.6), dpi=80)
    _draw(fig, ax, frames[0][1], kind, product, title(frames[0][0]))
    im = ax.images[0]
    images = []
    for i, (label, tif) in enumerate(frames):
        if i:                                   # same axes, colour bar and outline: only data and title change
            im.set_data(_read(tif)[0])
            ax.set_title(title(label), fontsize=11)
        fig.canvas.draw()
        images.append(Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB"))
    plt.close(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(path, save_all=True, append_images=images[1:], duration=int(1000 / fps), loop=0)
    return path


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


def overlay_png(tif: pathlib.Path, kind: str, product: config.Product):
    """(PNG data URL, ((south, west), (north, east))) of a GeoTIFF for an ipyleaflet ImageOverlay.

    The raster is reprojected to Web Mercator first so it lines up with the basemap.
    """
    import base64
    import io

    from rasterio.warp import Resampling, calculate_default_transform, reproject

    with rasterio.open(tif) as src:
        dst_crs = "EPSG:3857"
        transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
        dst = np.full((height, width), config.NODATA, np.float32)
        reproject(rasterio.band(src, 1), dst, src_transform=src.transform, src_crs=src.crs, dst_transform=transform,
                  dst_crs=dst_crs, src_nodata=config.NODATA, dst_nodata=config.NODATA,
                  resampling=Resampling.nearest)
        bounds = src.bounds
    data = np.ma.masked_equal(dst, config.NODATA)
    cmap, norm, _ = _style(kind, product)
    rgba = cmap.with_extremes(bad=(0, 0, 0, 0))(norm(data))
    buf = io.BytesIO()
    plt.imsave(buf, rgba, format="png")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return url, ((bounds.bottom, bounds.left), (bounds.top, bounds.right))
