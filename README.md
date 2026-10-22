# HRRR Location Wind Analysis

Historical wind statistics for sailing venues from the NOAA High-Resolution Rapid Refresh
(HRRR) archive, checked against NDBC buoys. Built to support regatta site selection:
"what wind does this club typically get in the second week of September, during racing
hours, and how sure are we?"

This repo holds the **tool** (`src/hrrr_wind/`), the **frozen earlier versions and
nine-venue screening** (`legacy/`), and the **GTYC vs HYC study** (`studies/gtyc_hyc_2028/`).

> **Status:** v1.2 is the supported version. The first nine-venue screening
> (`legacy/nine_venue_2028/`) used v1.0 and is **superseded**: its box averages included
> land cells, the HRRR data were never checked against observations, and its explanation
> of the Caseville sample count (six missing 2015 files) was wrong. Use it for context only.

---

## What v1.2 does

1. **Projects an offshore sample point** from the club by `bearing` and `offshore_nm`.
   The bearing and distance are measured *from the club coordinate*, so an inaccurate
   coordinate moves the whole analysis. Confirm clubhouse coordinates on satellite view.
2. **Averages only water cells.** HRRR's land/water field masks a ±`radius_nm` box around
   the sample point (default 4 nm), so land cells (rougher, much lighter wind) don't leak in.
   The number of water cells used is logged for every run.
3. **Pulls hourly 10 m wind (analysis hour, F00)** for a calendar window repeated over
   several years, filtered to racing hours (UTC), with a missing-data report
   (expected vs retrieved hours, listing the gaps).
4. **Reports** speed bins (<5, 5–15, ≥15 kt), median/90th percentile, direction (circular
   mean, steadiness R), wind rose, and the hourly time series.

The study driver (`venue_analysis`) adds a sample-point sensitivity grid, year-resampling
confidence intervals, paired venue comparisons, a "usable day" metric, **validation against
NDBC buoys** (bias, correlation, height adjustment to 10 m) and a quantile-mapped
bias-adjusted range.

---

## Install

```bash
git clone https://github.com/jrehm/hrrr-location-analysis.git
cd hrrr-location-analysis
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # or: pip install -r requirements.txt && export PYTHONPATH=src
python -m pytest -q
```

Data are fetched from the public NOAA HRRR archive on AWS through
[Herbie](https://herbie.readthedocs.io). Archive start: **2014-09-30**.

---

## Quick start: one club

```bash
python -m hrrr_wind.climatology \
  --club hyc \
  --start-date 2023-09-08 --end-date 2023-09-14 \
  --years 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 \
  --start-hour 14 --end-hour 20 --utc-offset -4 --tz-abbr EDT \
  --window-buffer-days 3 \
  --output-dir ./output
```

Racing hours 10 AM–4 PM EDT are `--start-hour 14 --end-hour 20` (UTC). Only the month and
day of `--start-date`/`--end-date` matter when `--years` is given. `--window-buffer-days`
also extracts a ± buffer around the window for a robustness check. Outputs: a summary PNG
(wind rose, speed distribution, stats), a stats JSON, and the hourly time-series CSV.

A manual location works too: `--lat 44.78 --lon -85.64 --bearing 20 --offshore-nm 3 --name "My Club"`.

### Venue presets

| Key | Club | Lat | Lon | Bearing | `offshore_nm` default |
|---|---|---|---|---|---|
| `byc` | Bayview Yacht Club | 42.3592 | −82.9596 | 100° | 2.0 |
| `csyc` | Crescent Sail Yacht Club | 42.4021 | −82.8851 | 50° | 2.0 |
| `ncyc` | North Cape Yacht Club | 41.8278 | −83.4085 | 100° | 2.0 |
| `gtyc` | Grand Traverse Yacht Club | 44.78034 | −85.63852 | 20° | 3.0 |
| `lyc` | Ludington Yacht Club | 43.9551 | −86.4515 | 270° | 4.0 |
| `myc` | Muskegon Yacht Club | 43.2205 | −86.3207 | 285° | 4.0 |
| `hyc` | Huron Yacht Club (Caseville) | 43.94475 | −83.27861 | 330° | 2.0 |
| `tbyc` | Tawas Bay Yacht Club | 44.2629 | −83.4423 | 75° | 2.0 |
| `catyc` | Catawba Island Club | 41.534 | −82.862 | 60° | 2.0 |

GTYC and HYC coordinates were confirmed on satellite view (Oct 2026) and their bearing and
distance were chosen from the map. **The other seven are unverified**: check them before
trusting results. To add a club, add an entry to `YACHT_CLUB_PRESETS` in
`src/hrrr_wind/climatology.py`:

```python
"key": {"name": "Club Name", "lat": 44.1234, "lon": -85.6789,
        "bearing": 270,        # degrees TRUE, from the club toward the racing area
        "offshore_nm": 3.0},   # optional
```

---

## Full study workflow (what `studies/gtyc_hyc_2028/` used)

```bash
# 1. Download a wind cache around each club once (±18 nm box, all 24 h), per-year checkpoints
python -m hrrr_wind.venue_analysis cache --venues gtyc hyc --tag sep_2015_2025 \
    --years 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 \
    --start 09-05 --end 09-17 --max-rss-gb 6 --chunk-hours 24
# 2. Sample-point sensitivity grid (offshore distance x radius x bearing), from a cache
python -m hrrr_wind.venue_analysis sensitivity --tag sens3y
# 3. Statistics, CIs, paired comparison, figures, tables (all from caches; no downloads)
python -m hrrr_wind.venue_analysis analyze
# 4. Validate against NDBC buoys and produce the bias-adjusted summary
python -m hrrr_wind.venue_analysis validate
# 5. Build the HTML report
python -m hrrr_wind.report_html
```

Paths default to `studies/gtyc_hyc_2028/`; override with `HRRR_WIND_OUT` (output and cache
directory) and `HRRR_WIND_BUOY_DIR`. The committed `cache_*.npz` files contain the gridded
wind around each club, so steps 2–5 reproduce the study with no downloads, and **changing a
sample point needs no re-download** as long as it stays inside the cached box.

See `studies/gtyc_hyc_2028/NOTES.md` for the decisions, bugs, and lessons from that study.

---

## Method notes and limitations

- **HRRR is a 3 km model analysis, not an observation.** Against buoys it runs low (about
  1.3–1.7 kt for racing hours at the two study venues) and under-produces heavy air. The
  study reports raw HRRR and a bias-adjusted range; treat the adjustment as an estimate.
- **Narrow water is poorly resolved.** Grand Traverse Bay's West Arm is 1–2 grid cells wide.
- **Wind direction** is meteorological (the angle the wind blows *from*); the dominant
  direction is the circular mean of hourly unit vectors; steadiness R is its length.
- **Missing hours are archive gaps**, not code errors. In the study, all gaps were in
  2015–2018 (September 2016 had 24% missing); 2019–2025 are complete. Every run reports
  expected vs retrieved hours.
- **Hourly samples are not independent.** Confidence intervals resample whole years.
- **One calendar week per year** captures year-to-year variability in that window, not the
  whole month.
- **Buoy anemometers are 2–3 m high**; the study scales to 10 m with a neutral log profile
  and shows raw and power-law versions as sensitivity.

---

## Repository layout

```
src/hrrr_wind/         climatology.py (CLI, presets, stats), venue_analysis.py, report_html.py
tests/                 pytest unit tests for the pure functions
studies/gtyc_hyc_2028/ GTYC vs HYC: NOTES.md, outputs/ (CSVs, figures, caches, reports), data/buoys/, slides/
legacy/                v1.0 and v1.1 scripts; nine_venue_2028/ (superseded first screening and its outputs)
```

## Related repositories

- [hrrr-data-retrieval](https://github.com/jrehm/hrrr-data-retrieval): the general HRRR retrieval tool this was forked from
- [hrrr-noaa-buoy-correlation-analysis](https://github.com/jrehm/hrrr-noaa-buoy-correlation-analysis): HRRR vs buoy model comparison
- [buoy-wind-analysis](https://github.com/jrehm/buoy-wind-analysis): NOAA buoy wind analysis

## Data sources

NOAA HRRR via AWS Open Data (`noaa-hrrr-bdp-pds`); NDBC standard meteorological data for
buoys 45020 (Grand Traverse Bay South, 2016–2018) and 45163 (Saginaw Bay, 2015–2025).
