# sdmad-opera-products

## SST / LST pipeline — Philippine Area of Responsibility

Builds Sea Surface Temperature (SST) and Land Surface Temperature (LST) products for the
Philippine Area of Responsibility (PAR) from JAXA **GCOM-C/SGLI Level-3** data on Google
Earth Engine (project `ee-chriscandido93`).

| Product | GEE collection | Band | Conversion | Outputs |
|---|---|---|---|---|
| SST | `JAXA/GCOM-C/L3/OCEAN/SST/V3` | `SST_AVE` | `DN × 0.0012 − 10` → °C | temperature, anomaly |
| LST | `JAXA/GCOM-C/L3/LAND/LST/V3` | `LST_AVE` | `DN × 0.02 − 273.15` → °C | temperature (anomaly with `--lst-anomaly`) |

**Extent.** The PAR polygon (25°N 120°E, 25°N 135°E, 5°N 135°E, 5°N 115°E, 15°N 115°E,
21°N 120°E). Rasters are on the native 1/24° grid (480 × 480 px, EPSG:4326); pixels outside
the PAR are `-9999`.

**Anomaly.** `anomaly = mean(target period) − climatology`. The climatology uses the **entire
GCOM-C record** (2018 → latest image) by default: the same calendar window is composited for
every year, then the yearly composites are averaged so cloudier years count the same as
clear ones. Use `--baseline 2018:2025` to pin a fixed baseline instead.

**Satellite pass.** SST uses day + night passes by default; LST uses daytime only, because day
and night LST differ by ~10 °C. Override with `--pass D|N|both` (the climatology always uses
the same pass as the target).

### Setup

```bash
pip install -r requirements.txt
earthengine authenticate          # once; the pipeline also prompts if needed
```

### Usage

```bash
python -m pipeline                                   # last complete month, SST + LST
python -m pipeline --month 2026-09                   # one month (repeat --month for more)
python -m pipeline --months 2026-01:2026-09 --products SST
python -m pipeline --start 2026-10-01 --end 2026-10-07   # custom window (≤ 1 year)
python -m pipeline --month 2026-09 --export drive    # run as GEE tasks to Google Drive
```

### Output layout

```
outputs/
├── SST/
│   ├── temperature/SST_temperature_2026-09.{tif,png,json}
│   └── anomaly/SST_anomaly_2026-09.{tif,png,json}
└── LST/
    └── temperature/LST_temperature_2026-09.{tif,png,json}
```

Each GeoTIFF has a PNG quicklook (skip with `--no-png`) and a JSON sidecar with the
period, pass, number of daily images, and climatology years. With `--export drive` the same
files go to the Drive folders `PAR_SST_temperature`, `PAR_SST_anomaly` and `PAR_LST_temperature`.

### Tests

```bash
pip install pytest && python -m pytest
```
