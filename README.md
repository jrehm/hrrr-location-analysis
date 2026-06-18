# HRRR Yacht Club Wind Climatology

A tool for extracting historical wind statistics and wind roses at specific sailing venues
from the NOAA High-Resolution Rapid Refresh (HRRR) model archive. Built to support
regatta site selection for the 2028 proposal.

---

## Quick Start

The exact command used for the 2028 regatta proposal analysis (mid-September, 11 years,
racing hours only, Michigan EDT):

```bash
python HRRR_club_wind_climatology_v1.0.py \
  --club gtyc \
  --start-date 2023-09-08 \
  --end-date   2023-09-14 \
  --years 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 \
  --start-hour 14 --end-hour 20 \
  --utc-offset -4 --tz-abbr EDT \
  --offshore-nm 4 \
  --freq 1h \
  --save-csv
```

Replace `--club gtyc` with any preset key (see list below). Run without `--years` for a
single date range. Outputs land in `./club_climatology/`.

---

## How It Works

### The core problem: HRRR land cells are useless for sailing

HRRR resolves at ~3 km. Yacht clubs sit on shore, meaning their nearest grid cell is a
land cell with surface roughness that drastically underestimates on-water wind speed. The
script solves this in two steps:

1. **Offshore projection** — the club's `bearing` (compass direction pointing toward open
   water) is used to project the sample point `--offshore-nm` nautical miles out onto the
   water surface.

2. **Spatial box average** — a `--radius-nm` box of grid cells centered on that sample
   point is averaged together, giving a smoother estimate than a single cell.

The combination means even if the exact bearing or distance is slightly off, the averaged
box captures representative open-water conditions.

### Time filtering

HRRR data is stored in UTC. `--start-hour` and `--end-hour` are UTC integers used to
filter the date range *before* downloading — this keeps run times fast because each
hour = one GRIB2 file fetch.

Michigan is **EDT (UTC−4)** in September and **EST (UTC−5)** in winter. Racing hours
10 AM–4 PM EDT = `--start-hour 14 --end-hour 20`.

`--utc-offset` and `--tz-abbr` are display-only — they convert the UTC hours to local
time in the PNG title and have no effect on data selection.

### Multi-year aggregation

`--years` repeats the same calendar window (month + day from `--start-date`/`--end-date`)
across each listed year and concatenates all records before computing stats. The year in
`--start-date` is irrelevant when `--years` is used — only the month and day matter.

Years whose window start falls before the HRRR archive (2014-09-30) are automatically
warned and skipped. Passing `--years 2014 2015 ...` is therefore safe and self-correcting.

### Wind direction convention

Directions follow the meteorological convention: the angle the wind is blowing **from**,
0° = from the north, 90° = from the east. This matches standard wind roses.

**Dominant direction** is the circular mean of all hourly unit vectors — not a simple
average of angles (which breaks near 0°/360°). **Steadiness R** is the length of that
resultant vector: 0 = completely variable direction, 1 = perfectly steady. Values in the
0.05–0.30 range (seen at all nine candidate venues) indicate a venue with no single
locked-in dominant direction.

---

## Venue Presets

| Key | Club | Body of Water | offshore-nm to use |
|---|---|---|---|
| `byc` | Bayview Yacht Club | Lake St. Clair / Detroit R. | 2 |
| `csyc` | Crescent Sail YC | Lake St. Clair | 2 |
| `ncyc` | North Cape YC | Lake Erie (western basin) | 2 |
| `gtyc` | Grand Traverse YC | Grand Traverse Bay (West Arm) | 4 |
| `lyc` | Ludington YC | Lake Michigan | 4 |
| `myc` | Muskegon YC | Lake Michigan | 4 |
| `hyc` | Huron YC (Caseville) | Saginaw Bay | 3 |
| `tbyc` | Tawas Bay YC | Lake Huron / Tawas Bay | 2 |
| `catyc` | Catawba Island Club | Lake Erie | 2 |

### Why `--offshore-nm` varies

**GTYC, LYC, MYC** sit behind protected harbors or enclosed arms with 1.5–2 nm of
sheltered water between the club and the open racing area. The default 2 nm offset would
land the sample point inside the harbor. Use 4 nm to clear the channel and reach
open-lake conditions. GTYC's West Arm is narrow — 4 nm pushes north up the arm into
the wider section.

**HYC** is on the Pigeon River, which flows ~0.5 nm to the Saginaw Bay mouth. 3 nm
clears the river and puts the sample point on open bay.

All others are directly on open water; 2 nm is sufficient.

### Adding a new club

Add an entry to `YACHT_CLUB_PRESETS` in the script:

```python
"key": {
    "name": "Full Club Name",
    "lat":  44.1234,   # clubhouse latitude
    "lon":  -85.6789,  # clubhouse longitude (negative = west)
    "bearing": 270,    # degrees TRUE pointing from club toward open water
                       # 0=N, 90=E, 180=S, 270=W
},
```

**Finding the bearing:** Open the club in Google Maps or a chart app. Draw a line from the
clubhouse toward the nearest open racing water. Read the compass heading. When in doubt,
err toward deeper/more open water — the offshore offset and box average are forgiving of
small bearing errors.

Coordinate accuracy within ~200 m is sufficient given the 3 km HRRR grid.

---

## Parameters Reference

| Argument | Default | What it does |
|---|---|---|
| `--club` | — | Named preset key (see table above) |
| `--lat / --lon / --bearing` | — | Manual location entry (alternative to `--club`) |
| `--name` | auto | Display name for manual entry |
| `--start-date` | required | Window start date (YYYY-MM-DD). Year is ignored when `--years` is set. |
| `--end-date` | required | Window end date (YYYY-MM-DD) |
| `--years` | — | List of years to repeat the window over, e.g. `2015 2016 ... 2025` |
| `--start-hour` | 0 | First UTC hour to include (0–23) |
| `--end-hour` | 23 | Last UTC hour to include (0–23) |
| `--utc-offset` | 0 | Hours offset from UTC for title display only (e.g. −4 for EDT) |
| `--tz-abbr` | UTC | Timezone label for title display only (e.g. EDT) |
| `--offshore-nm` | 2.0 | nm to project offshore from club along `bearing` |
| `--radius-nm` | 4.0 | Half-width of grid-cell averaging box around sample point |
| `--include-gust` | off | Also fetch and report wind gust |
| `--freq` | 1h | Time step: `1h`, `3h`, or `6h` |
| `--model` | hrrr | Model archive to use (`hrrr` or `gfs`) |
| `--source` | aws | HRRR archive mirror (`aws`, `google`, `azure`, `nomads`) |
| `--max-threads` | 50 | Parallel download threads (reduce if hitting rate limits) |
| `--batch-size` | 168 | Files per Herbie batch (168 = 1 week at 1h) |
| `--output-dir` | ./club_climatology | Where to write PNG, JSON, and CSV |
| `--output-name` | auto | Override the auto-generated output filename base |
| `--save-csv` | off | Also write the full hourly time series as CSV |
| `--verbose` | off | Debug-level logging |

---

## Output Files

All outputs land in `--output-dir` (`./club_climatology/` by default). The filename base
is auto-generated as `{ClubName}_{years}_{mmdd}-{mmdd}_{HH-HHZ}`, e.g.
`Grand_Traverse_Yacht_Club_2015-2025_0908-0914_14-20Z`.

### `*_windrose.png`
Three-panel summary figure:
- **Left** — 16-sector wind rose, bars stacked by speed bin (0–5, 5–10, 10–15, 15–20,
  20–25, 25+ kt), colored light-to-dark by speed.
- **Top right** — Speed distribution histogram with per-bin frequency labels and a
  mean/median annotation box.
- **Bottom right** — Stats table including n, mean/median/90th/max speed, percentage
  breakdowns, dominant direction, steadiness R, and data source.

### `*_stats.json`
Machine-readable stats dictionary including all values shown in the table, plus the sample
point coordinates and radius. Useful for building cross-venue comparison tables without
re-running the analysis.

### `*_timeseries.csv` *(only with `--save-csv`)*
Full hourly time series with columns: `valid_time`, `u10`, `v10`, `wind_speed_ms`,
`wind_dir_from`, `gust_ms`. Wind speed is in m/s — multiply by 1.9438 for knots.
Useful for custom analysis, plotting individual years, or checking specific events.

---

## Data Source & Limitations

### HRRR archive
- **Provider:** NOAA, publicly archived on AWS S3 (`noaa-hrrr-bdp-pds`)
- **Resolution:** ~3 km horizontal, hourly output
- **Archive start:** 2014-09-30 (earlier dates unavailable)
- **Access:** Via the [Herbie](https://herbie.readthedocs.io) Python library
- **Fields used:** `UGRD` and `VGRD` at 10 m above ground (analysis hour, fxx=0)

### What HRRR is and isn't
HRRR is a numerical weather prediction model, not observed data. It assimilates surface
and upper-air observations but fills in where observations are sparse. It captures
synoptic (large-scale) and mesoscale patterns well; localized effects smaller than ~3 km
(a narrow channel, a point of land) may be smoothed or missed.

The offshore projection + box average approach mitigates the land-cell problem but does
not replace observed anemometer data. For final venue decisions, HRRR results should be
validated against any available buoy or station data near each site.

### Known data gaps
- **2015 early archive:** 6 files missing for some venues (Caseville HYC most affected —
  476 obs vs. 523 for others). Stats are reliable but the sample is slightly smaller.
- **Occasional connection resets:** AWS S3 sometimes resets connections under high thread
  load. Herbie retries automatically; these appear as `ERROR: Connection reset` in the
  log but do not affect results if the file is ultimately retrieved.

### Calendar window vs. full-season analysis
This tool analyzes a specific calendar window (e.g. Sep 8–14) repeated across years.
It captures year-to-year variability within that window but does not represent the full
month. A week that trends light or heavy in one year can shift the composite. Widening
to 2–3 weeks (e.g. Sep 1–21) would give a more robust picture at the cost of longer
run time (~3× more files).

---

## Decisions Made for the 2028 Proposal

These are the choices that were made and why — useful context if revisiting the analysis.

**Window: September 8–14**  
Targeting a mid-September championship week. Avoids Labor Day weekend crowds (early
September) and the higher storm probability of late September / October. Could be shifted
to Sept 15–21 for a later-season event.

**`--offshore-nm 4` for GTYC, LYC, MYC**  
These clubs sit behind harbors. 2 nm lands inside sheltered water; 4 nm clears the
harbor mouth and reaches open-lake conditions. Confirmed visually by checking the
projected coordinates on a chart.

**`--radius-nm 4` (default)**  
The default 4 nm averaging box spans roughly 3×3 HRRR grid cells. Larger boxes smooth
more aggressively and can include land cells; smaller boxes increase noise from individual
cells. 4 nm is a reasonable balance for Great Lakes venues.

**`--years 2014 2015 ... 2025`**  
2014 is passed deliberately — the script warns and skips it automatically (Sep 8 precedes
the HRRR archive start of Sep 30, 2014), giving 11 attempted years and 11 actual years
of data starting 2015. This way the command doesn't need updating as time passes — just
add the next year to the list.

**`--start-hour 14 --end-hour 20` (10 AM–4 PM EDT)**  
Standard racing window for a championship event. Full-day stats (00–23 UTC) show
significantly lighter wind at this analysis — morning hours before the thermal builds
drag the mean down by 2–3 kt and inflate the drifter percentage. Racing-hours-only stats
are the relevant comparator for a race committee.

**AWS as source**  
NOAA's AWS S3 bucket is the fastest and most complete mirror for historical HRRR. Google
and Azure mirrors exist but can lag on early-archive years. NOMADS is the operational
server and rate-limits aggressively for bulk requests.

---

## Dependencies

```
herbie-data    # HRRR/GFS data access and GRIB2 subsetting
pandas
numpy
matplotlib
```

Install with:
```bash
pip install herbie-data pandas numpy matplotlib
```

The PDF conversion pipeline also used `markdown` and Chrome headless (already on the
system) — those are not needed to run the climatology script itself.
