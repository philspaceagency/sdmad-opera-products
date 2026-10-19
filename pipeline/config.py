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
# MODIS 1 km LST is resampled to 1/96 degree (~1.04 km), which nests 4x4 inside the SST grid.
MODIS_PIXEL_DEG = 1.0 / 96.0
CRS = "EPSG:4326"

NODATA = -9999.0


@dataclass(frozen=True)
class Product:
    name: str           # output folder name, e.g. "SST"
    collection: str     # GEE ImageCollection ID, or Planetary Computer STAC collection
    band: str           # band holding the average value (for MODIS: the day band; see modis.py)
    scale: float        # DN -> physical units
    offset: float       # added after scaling, already includes K -> degC where needed
    invalid_dn: int     # fill value in the raw band
    default_pass: str   # "D" (day), "N" (night) or "both"
    outputs: tuple      # which outputs to produce by default
    temp_vis: tuple     # (min, max) degC for temperature quicklooks
    long_name: str
    source: str = "gee"         # "gee" (Earth Engine) or "mpc" (Microsoft Planetary Computer)
    pixel_deg: float = PIXEL_DEG
    passes: tuple = ("D", "N", "both")


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
    collection="modis-11A2-061",     # MOD11A2 (Terra) + MYD11A2 (Aqua) 8-day 1 km, Planetary Computer
    band="LST_Day_1km",
    scale=0.02,
    offset=-273.15,         # Kelvin -> degC
    invalid_dn=0,
    # Day and night LST differ by ~10 degC: one or the other, never mixed.
    default_pass="D",
    outputs=("temperature", "anomaly"),
    temp_vis=(15.0, 45.0),
    long_name="Land Surface Temperature",
    source="mpc",
    pixel_deg=MODIS_PIXEL_DEG,
    passes=("D", "N"),
)

# MODIS platforms on modis-11A2-061. "both" averages per-platform results, each against its own
# climatology, so Terra (10:30/22:30) and Aqua (13:30/01:30) overpass times never bias the anomaly.
MODIS_PLATFORMS = ("terra", "aqua")
MODIS_DEFAULT_PLATFORM = "both"
# MODIS QC: keep mandatory QA 00 (good) / 01 (other) with average LST error <= this level
# (bits 6-7: 0 = <=1 K, 1 = <=2 K, 2 = <=3 K, 3 = >3 K).
MODIS_MAX_LST_ERROR = 1

PRODUCTS = {p.name: p for p in (SST, LST)}

# Anomaly quicklook: diverging, discrete steps (same style as NOAA/Climate Reanalyzer maps).
ANOMALY_VIS = (-3.0, 3.0, 0.5)  # (min, max, step) degC

# Interactive (geemap) palettes.
TEMP_PALETTE = ["#30123b", "#4669db", "#26bce1", "#43f087", "#c2f234", "#fdad35", "#e34a0e", "#7a0403"]
ANOMALY_PALETTE = ["#053061", "#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7",
                   "#fddbc7", "#f4a582", "#d6604d", "#b2182b", "#67001f"]
