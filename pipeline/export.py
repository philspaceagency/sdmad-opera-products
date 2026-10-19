"""Export Earth Engine images as GeoTIFFs on the PAR grid."""

import pathlib

import ee
import rasterio
import requests

from . import config
from .gee import par_geometry


def _grid() -> dict:
    west, south, east, north = config.PAR_BOUNDS
    px = config.PIXEL_DEG
    return {
        "crs": config.CRS,
        "crs_transform": [px, 0, west, 0, -px, north],
        "dimensions": [round((east - west) / px), round((north - south) / px)],
    }


def _prepare(image: ee.Image, band: str) -> ee.Image:
    return image.rename(band).clip(par_geometry()).unmask(config.NODATA).toFloat()


def download_geotiff(image: ee.Image, band: str, path: pathlib.Path, tags: dict = None) -> pathlib.Path:
    """Download `image` directly (PAR at 1/24 deg is ~480x480 px, well under GEE limits)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    url = _prepare(image, band).getDownloadURL({**_grid(), "format": "GEO_TIFF"})
    resp = requests.get(url, timeout=600)
    resp.raise_for_status()
    path.write_bytes(resp.content)

    with rasterio.open(path, "r+") as ds:
        ds.nodata = config.NODATA
        ds.set_band_description(1, band)
        ds.update_tags(**{k: str(v) for k, v in (tags or {}).items()})
    return path


def export_to_drive(image: ee.Image, band: str, folder: str, name: str) -> ee.batch.Task:
    grid = _grid()
    task = ee.batch.Export.image.toDrive(
        image=_prepare(image, band),
        description=name[:100],
        folder=folder,
        fileNamePrefix=name,
        crs=grid["crs"],
        crsTransform=grid["crs_transform"],
        dimensions=f"{grid['dimensions'][0]}x{grid['dimensions'][1]}",
        fileFormat="GeoTIFF",
        maxPixels=int(1e9),
    )
    task.start()
    return task
