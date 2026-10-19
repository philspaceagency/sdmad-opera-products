"""Static configuration: GEE project, PAR extent and product definitions."""

from dataclasses import dataclass

GEE_PROJECT = "ee-chriscandido93"

# Philippine Area of Responsibility (PAGASA), vertices as (lon, lat):
# 25N 120E -> 25N 135E -> 5N 135E -> 5N 115E -> 15N 115E -> 21N 120E -> 25N 120E
PAR_COORDS = [
    [120.0, 25.0],
    [135.0, 25.0],
    [135.0, 5.0],
    [115.0, 5.0],
    [115.0, 15.0],
    [120.0, 21.0],
    [120.0, 25.0],
]
PAR_BOUNDS = (115.0, 5.0, 135.0, 25.0)  # (west, south, east, north)

# GCOM-C L3 products are on a 1/24 degree (~4.6 km) grid.
PIXEL_DEG = 1.0 / 24.0
CRS = "EPSG:4326"

NODATA = -9999.0


@dataclass(frozen=True)
class Product:
    name: str           # output folder name, e.g. "SST"
    collection: str     # GEE ImageCollection ID
    band: str           # band holding the average value
    scale: float        # DN -> physical units
    offset: float       # added after scaling, already includes K -> degC where needed
    invalid_dn: int     # fill value in the raw band
    default_pass: str   # "D" (day), "N" (night) or "both"
    outputs: tuple      # which outputs to produce by default
    temp_vis: tuple     # (min, max) degC for temperature quicklooks
    long_name: str


SST = Product(
    name="SST",
    collection="JAXA/GCOM-C/L3/OCEAN/SST/V3",
    band="SST_AVE",
    scale=0.0012,
    offset=-10.0,           # degC
    invalid_dn=65535,
    default_pass="both",
    outputs=("temperature", "anomaly"),
    temp_vis=(24.0, 32.0),
    long_name="Sea Surface Temperature",
)

LST = Product(
    name="LST",
    collection="JAXA/GCOM-C/L3/LAND/LST/V3",
    band="LST_AVE",
    scale=0.02,
    offset=-273.15,         # Kelvin -> degC
    invalid_dn=65535,
    # Day and night LST differ by ~10 degC, so never mix them by default.
    default_pass="D",
    outputs=("temperature",),
    temp_vis=(15.0, 45.0),
    long_name="Land Surface Temperature",
)

PRODUCTS = {p.name: p for p in (SST, LST)}

# Anomaly quicklook: diverging, discrete steps (same style as NOAA/Climate Reanalyzer maps).
ANOMALY_VIS = (-3.0, 3.0, 0.5)  # (min, max, step) degC
