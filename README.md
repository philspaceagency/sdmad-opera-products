# sdmad-opera-products

## SST / LST pipeline — Philippine Area of Responsibility

Temperature **and anomaly** maps over the Philippine Area of Responsibility (PAR) for a time range.

| Product | Source | Band | Conversion | Grid | Outputs |
|---|---|---|---|---|---|
| SST | JAXA GCOM-C/SGLI L3 (daily), Google Earth Engine `JAXA/GCOM-C/L3/OCEAN/SST/V3` (project `ee-chriscandido93`) | `SST_AVE` | `DN × 0.0012 − 10` → °C | 1/24° (~4.6 km) | daily + monthly |
| LST | MODIS MOD11A2 (Terra) + MYD11A2 (Aqua) 8-day 1 km, Microsoft Planetary Computer STAC [`modis-11A2-061`](https://planetarycomputer.microsoft.com/api/stac/v1/collections/modis-11A2-061) | `LST_Day_1km` / `LST_Night_1km` + `QC_Day` / `QC_Night` | `DN × 0.02 − 273.15` → °C | 1/96° (~1 km) | monthly |

**Extent.** The PAR polygon (25°N 120°E, 25°N 135°E, 5°N 135°E, 5°N 115°E, 15°N 115°E,
21°N 120°E), EPSG:4326. Pixels outside the PAR are `-9999`.

### Time range, folders and resuming

Give a start and end date (both inclusive). The range is split by calendar month:

```
outputs/<PRODUCT>/<YYYY>/<MM>/daily/     <PRODUCT>_{temperature,anomaly,anomaly1991-2020}_<YYYYMMDD>.{tif,png,json}   (SST)
outputs/<PRODUCT>/<YYYY>/<MM>/monthly/   <PRODUCT>_{temperature,anomaly[,anomaly1991-2020]}_<YYYY-MM>.{tif,png,json}
outputs/<PRODUCT>/animations/            <PRODUCT>_{temperature,anomaly}_<start>_<end>.gif
```

Nothing is processed twice:

- **Daily:** a day whose temperature and anomaly files exist is skipped.
- **Monthly:** the month's JSON records the span it covers. The composite is redone only when the
  range adds days, and then covers the old span plus the new days. Example: 2026-10-01 → 10-15
  writes October (1–15). A later 2026-09-01 → 10-31 writes all of September, only Oct 16–31 daily,
  and redoes October as the full month.
- **Newest data:** days after the newest available image (Earth Engine's GCOM-C lags by a few
  weeks) are reported as *pending*. They are not clamped to the last date. Run the same range
  again later to fill them in.
- **GIF:** one GIF per output over the requested range (daily frames for SST, monthly frames for
  LST), made from all files in the range, including ones written by earlier runs.

### Climatology

**Baseline 2018–2025** by default (`--baseline`). 2026 onwards is never part of the climatology.
For each baseline year the same calendar window is averaged, then the years are averaged, so
cloudy years count the same as clear ones.

- **Monthly:** the same span (full month, or the partial span) in each baseline year.
- **Daily (SST):** the mean of a 15-day window centred on the day (± 7 days,
  `DAILY_CLIM_HALF_WINDOW`). One calendar day across 8 years would be mostly cloud gaps.
- **LST, both platforms:** the anomaly is computed per platform against its own climatology and
  then averaged. Terra (10:30) and Aqua (13:30) overpass at different local times.

### SST anomaly on the 1991–2020 baseline (OISST offset)

GCOM-C only goes back to 2018. To compare with products on the WMO-standard 1991–2020 baseline, SST also gets
`SST_anomaly1991-2020_*`:

```
anomaly(1991–2020) = GCOM-C anomaly(2018–2025) + [OISST clim(2018–2025) − OISST clim(1991–2020)]
```

- **Offset source:** NOAA OISST v2.1 (`NOAA/CDR/OISST/V2_1`, 0.25°, 1981 onwards) supplies how much warmer
  2018–2025 was than 1991–2020, per pixel and for the same window: 15 days around the day for daily maps,
  the same span for monthly maps.
- **Resolution:** GCOM-C keeps its 4.6 km detail. The offset is resampled bilinearly. Coastal pixels where
  OISST is masked take it from a 75 km neighbourhood (`OISST_FILL_RADIUS_M`).
- **Equivalence:** this is the same as rebuilding GCOM-C's climatology for 1991–2020, with OISST giving the
  long-term level and GCOM-C its sensor-specific detail.
- **Assumption:** the GCOM-C vs OISST difference does not change over time.
- **Not fixed by the offset:** the 8-year noise of the GCOM-C climatology, and spreads or percentiles.
- **Options:** `--reference-baseline 1991:2020` (default), `--no-reference` to skip. Notebook:
  `USE_REFERENCE_BASELINE`. Turning it on later only adds the missing files.
- **Check:** notebook cell 10 (`pipeline/reference.py`) compares, for the PAR and Niño 3.4 means, the
  adjusted GCOM-C anomaly with OISST's own 1991–2020 anomaly (and the NOAA ONI). It reports mean difference,
  RMSE and correlation, plus the offset for each calendar month. Outputs go to
  `outputs/SST/reference/`.

### El Niño comparison (Niño 3.4)

El Niño and La Niña are defined from SST in the **Niño 3.4** region (5°N–5°S, 170°W–120°W), not around
the Philippines. Notebook cell 9 (`pipeline/enso.py`, `enso.compare()`) shows how the PAR responds:

- **GCOM-C Niño 3.4:** monthly area mean from the same GCOM-C SST, pass and baseline as the PAR series,
  then a 3-month running mean (ONI-style).
- **NOAA ONI:** the official index, fetched from NOAA CPC, overlaid. If it can't be reached, the GCOM-C
  index is used instead. El Niño and La Niña episodes use NOAA's rule: at least 5 consecutive 3-month
  means beyond ±0.5 °C. The mean offset between the GCOM-C index and the ONI is printed. It comes from
  the short 2018–2025 baseline, so compare the timing, and use the ONI for the official phase.
- **Lagged correlation:** correlation of the PAR 3-month anomaly with Niño 3.4 at 0–12 months later. Both
  series are detrended first, so the shared warming trend doesn't count. With about 8 years of data,
  read it as indicative only.

Outputs: `outputs/SST/enso/SST_PAR_vs_Nino34_<pass>_baseline<years>.{csv,png}`. The CSV has the monthly
PAR and Niño 3.4 anomalies, their 3-month means, the ONI and the ENSO phase of each month.

### Passes and quality

- SST: day + night by default (`--sst-pass D|N|both`).
- LST: day or night (`--lst-pass D|N`, default day), never mixed. Platform `--lst-platform both|terra|aqua`.
- LST QC: mandatory QA "good" or "other" with average LST error ≤ 2 K. 8-day composites that
  overlap the span are used.
- Planetary Computer access follows `sdmad-opera-waterresource` (`ai_water/acquire.py`): retry and
  back-off, URLs signed at read time, `odc-stac` reads, searches cached on disk. MODIS per-year
  results are cached in `cache/`, so reruns are cheap. `PC_SDK_SUBSCRIPTION_KEY` (optional) raises
  rate limits.

### Notebook (Google Colab)

1. Upload this repository to Google Drive as `MyDrive/SDMAD_Products`
   (so `MyDrive/SDMAD_Products/pipeline/` exists).
2. Open `notebooks/SDMAD_SST_LST_Pipeline.ipynb` in Colab and run the cells in order. After
   replacing the code in Drive, use Runtime > Restart session first: Python keeps the old code in
   memory.

The inputs form is the time range plus passes, LST platform, baseline years and GIF options.
After the run it shows the monthly maps, the GIFs, an interactive map and a PAR-mean monthly time
series (anomaly against the baseline).

### Command line

```bash
pip install -r requirements.txt
earthengine authenticate          # once, for SST

python -m pipeline --start 2026-10-01 --end 2026-10-15
python -m pipeline --start 2026-09-01 --end 2026-10-31          # only what is missing is processed
python -m pipeline --start 2026-09-01 --end 2026-09-30 --products SST --sst-pass N
python -m pipeline --start 2026-01-01 --end 2026-09-30 --products LST --lst-platform terra
```

Other options: `--baseline 2018:2025`, `--out`, `--cache`, `--no-png`, `--no-gif`, `--gif-fps`.

### Tests

```bash
pip install pytest && python -m pytest
```

Offline. The runner tests use a fake backend; the MODIS tests read synthetic sinusoidal tiles
through the real `odc-stac` path.
