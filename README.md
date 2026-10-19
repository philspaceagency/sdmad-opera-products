# sdmad-opera-products

## SST / LST pipeline — Philippine Area of Responsibility

Temperature **and anomaly** products for the Philippine Area of Responsibility (PAR):

| Product | Source | Band | Conversion | Grid | Outputs |
|---|---|---|---|---|---|
| SST | JAXA GCOM-C/SGLI L3, Google Earth Engine `JAXA/GCOM-C/L3/OCEAN/SST/V3` (project `ee-chriscandido93`) | `SST_AVE` | `DN × 0.0012 − 10` → °C | 1/24° (~4.6 km) | temperature, anomaly |
| LST | MODIS MOD11A2 (Terra) + MYD11A2 (Aqua) 8-day 1 km, Microsoft Planetary Computer STAC [`modis-11A2-061`](https://planetarycomputer.microsoft.com/api/stac/v1/collections/modis-11A2-061) | `LST_Day_1km` / `LST_Night_1km` + `QC_Day` / `QC_Night` | `DN × 0.02 − 273.15` → °C | 1/96° (~1 km) | temperature, anomaly |

**Extent.** The PAR polygon (25°N 120°E, 25°N 135°E, 5°N 135°E, 5°N 115°E, 15°N 115°E,
21°N 120°E), EPSG:4326. Pixels outside the PAR are `-9999`.

**Anomaly.** `anomaly = mean(target period) − climatology`. The climatology uses the **entire
record** by default (GCOM-C 2018 → latest, MODIS 2000 → latest): the same calendar window is
averaged in every year, then the yearly results are averaged, so cloudier years count the same as
clear ones. Use `--baseline 2003:2025` to pin fixed years instead.

**SST pass.** Day + night by default (`--sst-pass D|N|both`).

**LST (MODIS).**
- Day or night (`--lst-pass D|N`, default day); never mixed, as they differ by ~10 °C.
- Platforms (`--lst-platform both|terra|aqua`, default both). With both, the anomaly is computed
  per platform against its own climatology and then averaged, because Terra (10:30) and Aqua
  (13:30) overpass at different local times. The temperature map is the mean of the two.
- QC: mandatory QA "good" or "other quality" with average LST error ≤ 2 K.
- 8-day composites that overlap the target window are used, so a short "as of" window can draw on
  up to 7 days before it.
- Planetary Computer access follows `sdmad-opera-waterresource` (`ai_water/acquire.py`):
  `pystac-client` with retry/back-off, URLs signed at read time with `planetary-computer`,
  reads with `odc-stac`, STAC searches cached on disk. Set `PC_SDK_SUBSCRIPTION_KEY` (optional)
  to raise rate limits.
- The first run of a window reads that window in every year since 2000. Per-year results are
  cached in `cache/` (`--cache`), so reruns and later dates only read what is new.

### Notebook (Google Colab)

1. Upload this repository to Google Drive as `MyDrive/SDMAD_Products`
   (so `MyDrive/SDMAD_Products/pipeline/` exists).
2. Open `notebooks/SDMAD_SST_LST_Pipeline.ipynb` in Colab and run the cells in order.

The notebook mounts Drive, installs the requirements and imports the pipeline from
`/content/drive/MyDrive/SDMAD_Products`. The inputs form offers:

- **As of** — a window of `WINDOW_DAYS` days ending on a date, or on the newest image (`USE_LATEST`)
- **Time range** — inclusive start/end dates (up to a year)
- **Month(s)** — one map per calendar month in a range

plus SST pass, LST pass and platform, baseline years, an optional Planetary Computer key and the
SST output mode. Outputs go to `MyDrive/SDMAD_Products/outputs/`, the cache to
`MyDrive/SDMAD_Products/cache/`. After the run it shows the output maps, an interactive map
(layer toggles, PAR outline, SST value inspector) and a PAR-mean monthly time series of the whole
record with anomaly bars (saved as CSV + PNG under `outputs/<product>/timeseries/`).

### Command line

#### Setup

```bash
pip install -r requirements.txt
earthengine authenticate          # once, for SST; the pipeline also prompts if needed
```

#### Usage

```bash
python -m pipeline                                   # last complete month, SST + LST
python -m pipeline --month 2026-09                   # one month (repeat --month for more)
python -m pipeline --months 2026-01:2026-09 --products SST
python -m pipeline --start 2026-10-01 --end 2026-10-07   # custom window (≤ 1 year)
python -m pipeline --as-of 2026-10-15 --window-days 7    # 7 days ending 2026-10-15
python -m pipeline --as-of latest                        # 30 days ending at the newest image
python -m pipeline --products LST --lst-platform terra --lst-pass N
python -m pipeline --month 2026-09 --export drive    # SST as GEE tasks to Google Drive
```

### Output layout

```
outputs/
├── SST/
│   ├── temperature/SST_temperature_2026-09.{tif,png,json}
│   └── anomaly/SST_anomaly_2026-09.{tif,png,json}
└── LST/
    ├── temperature/LST_temperature_2026-09.{tif,png,json}
    └── anomaly/LST_anomaly_2026-09.{tif,png,json}
```

Each GeoTIFF has a PNG quicklook (skip with `--no-png`) and a JSON sidecar with the period, pass,
number of images/composites, climatology years and, for LST, the per-platform counts. With
`--export drive`, SST goes to the Drive folders `PAR_SST_temperature` and `PAR_SST_anomaly`.

### Tests

```bash
pip install pytest && python -m pytest
```

Offline. The MODIS tests read synthetic sinusoidal tiles through the real `odc-stac` path.
