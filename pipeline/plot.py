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
    if kind.startswith("anomaly"):
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

    name = f"{product.name} {kind_name(kind)}"
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


def kind_name(kind: str) -> str:
    """'temperature', 'anomaly' or 'anomaly vs 1991-2020' (OISST-adjusted reference baseline)."""
    if kind.startswith("anomaly") and kind != "anomaly":
        return f"anomaly vs {kind[len('anomaly'):]}"
    return kind


def _style(kind: str, product: config.Product):
    if kind.startswith("anomaly"):
        vmin, vmax, step = config.ANOMALY_VIS
        levels = np.arange(vmin, vmax + step / 2, step)
        base = plt.get_cmap("RdBu_r", len(levels) + 1)
        cmap = ListedColormap(base(np.arange(1, len(levels)))).with_extremes(
            under=base(0), over=base(len(levels)), bad=NODATA_COLOR)
        return cmap, BoundaryNorm(levels, cmap.N), f"{product.name} {kind_name(kind)} (°C)"
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
            ax.set_title(f"{name} {kind_name(r['kind'])} — {label}")
            fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.06, fraction=0.05,
                         extend="both").set_label(cbar_label)
            if data.count():
                ax.text(0.01, 0.01, f"PAR mean {data.mean():+.2f} °C" if r["kind"].startswith("anomaly")
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


ENSO_COLORS = {"El Nino": "#f4b6a8", "La Nina": "#a9c8ea"}


def enso_figure(result):
    """Nino 3.4 index, PAR anomaly with El Nino / La Nina shading, and the lagged correlation."""
    import datetime as dt

    def series(rows):
        return [d for d, _ in rows], np.array([np.nan if v is None else v for _, v in rows])

    def shade(ax):
        for phase, first, last in result["episodes"]:
            ax.axvspan(first, last + dt.timedelta(days=30), color=ENSO_COLORS[phase], alpha=0.6, lw=0)

    fig = plt.figure(figsize=(12, 10), dpi=100)
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 3, 2], hspace=0.35)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2])

    shade(ax1)
    d, v = series(result["nino34_3mo"])
    ax1.plot(d, v, color="#1f4e79", lw=1.8, label="Niño 3.4, GCOM-C (3-month mean)")
    if result["noaa_oni"]:
        d, v = series(result["noaa_oni"])
        ax1.plot(d, v, color="black", lw=1.2, ls="--", label="NOAA ONI (official)")
    for y in (config.ENSO_THRESHOLD, -config.ENSO_THRESHOLD):
        ax1.axhline(y, color="#777777", lw=0.8, ls=":")
    ax1.axhline(0, color="black", lw=0.8)
    ax1.set_ylabel("Niño 3.4 anomaly (°C)")
    b = result["baseline"]
    ax1.set_title(f"El Niño / La Niña (Niño 3.4) vs Philippine Area of Responsibility SST anomaly — "
                  f"GCOM-C baseline {b[0]}–{b[1]}", fontsize=11)
    from matplotlib.patches import Patch
    handles, _ = ax1.get_legend_handles_labels()
    handles += [Patch(color=ENSO_COLORS["El Nino"], label=f"El Niño ({result['episode_source']})"),
                Patch(color=ENSO_COLORS["La Nina"], label=f"La Niña ({result['episode_source']})")]
    ax1.legend(handles=handles, frameon=False, loc="upper left", fontsize=8, ncol=2)
    ax1.grid(alpha=0.3)

    shade(ax2)
    d, v = series(result["par"])
    ax2.bar(d, np.nan_to_num(v), width=25, color=np.where(v >= 0, "#c0392b", "#2b6cb0"), alpha=0.8,
            label="PAR monthly anomaly")
    d, v = series(result["par_3mo"])
    ax2.plot(d, v, color="black", lw=1.4, label="PAR 3-month mean")
    ax2.axhline(0, color="black", lw=0.8)
    ax2.set_ylabel("PAR SST anomaly (°C)")
    ax2.legend(frameon=False, loc="upper left", fontsize=8)
    ax2.grid(alpha=0.3)

    lags = [lag for lag, _, _ in result["lag_correlation"]]
    rs = np.array([r for _, r, _ in result["lag_correlation"]])
    ax3.bar(lags, np.nan_to_num(rs), color=np.where(rs >= 0, "#c0392b", "#2b6cb0"))
    n = max((k for _, _, k in result["lag_correlation"]), default=0)
    if n > 3:
        ax3.axhline(2 / np.sqrt(n), color="#777777", lw=0.8, ls=":")
        ax3.axhline(-2 / np.sqrt(n), color="#777777", lw=0.8, ls=":")
    ax3.axhline(0, color="black", lw=0.8)
    ax3.set_xticks(lags)
    ax3.set_ylim(-1, 1)
    ax3.set_xlabel("PAR lags Niño 3.4 by (months)")
    ax3.set_ylabel("Correlation r")
    ax3.set_title("Lagged correlation, detrended 3-month means (dotted: ±2/√n, rough 95% level)", fontsize=10)
    ax3.grid(alpha=0.3)
    return fig


def reference_figure(result):
    """GCOM-C anomaly (short baseline), the OISST-adjusted version and OISST's own reference anomaly."""
    from . import enso

    def series(rows):
        return [d for d, _ in rows], np.array([np.nan if v is None else v for _, v in rows])

    b, ref = result["baseline"], result["reference"]
    names = list(result["regions"])
    fig, axes = plt.subplots(len(names) + 1, 1, figsize=(12, 4.2 * len(names) + 2.6), dpi=100,
                             gridspec_kw={"height_ratios": [3] * len(names) + [2]})
    for ax, name in zip(axes, names):
        r = result["regions"][name]
        smooth = name.startswith("Nino")
        prep = enso.running_mean if smooth else (lambda rows: rows)
        d, v = series(prep(r["gcomc"]))
        ax.plot(d, v, color="#9aa5b1", lw=1.2, label=f"GCOM-C vs {b[0]}–{b[1]}")
        d, v = series(prep(r["gcomc_adjusted"]))
        ax.plot(d, v, color="#1f4e79", lw=1.8, label=f"GCOM-C adjusted to {ref[0]}–{ref[1]} (OISST offset)")
        d, v = series(prep(r["oisst"]))
        ax.plot(d, v, color="#c0392b", lw=1.2, ls="--", label=f"OISST vs {ref[0]}–{ref[1]}")
        if smooth and r.get("noaa_oni"):
            d, v = series(r["noaa_oni"])
            ax.plot(d, v, color="black", lw=1.0, ls=":", label="NOAA ONI")
        ax.axhline(0, color="black", lw=0.8)
        stats = r["agreement_vs_oisst"]
        text = "" if not stats else (f"adjusted − OISST: mean {stats['mean_diff']:+.2f} °C, "
                                     f"RMSE {stats['rmse']:.2f} °C, r = {stats['r']:.2f}")
        ax.set_title(f"{name}{' (3-month means)' if smooth else ''} — {text}", fontsize=10)
        ax.set_ylabel("Anomaly (°C)")
        ax.legend(frameon=False, loc="upper left", fontsize=8, ncol=2)
        ax.grid(alpha=0.3)

    ax = axes[-1]
    months = np.arange(1, 13)
    width = 0.8 / len(names)
    for i, name in enumerate(names):
        offs = result["regions"][name]["offsets"]
        ax.bar(months + (i - (len(names) - 1) / 2) * width, [offs.get(m, np.nan) for m in months], width,
               label=name)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(months)
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_ylabel("Offset (°C)")
    ax.set_title(f"OISST offset per calendar month: mean {b[0]}–{b[1]} minus mean {ref[0]}–{ref[1]}", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig
