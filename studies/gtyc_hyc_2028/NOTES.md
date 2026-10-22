# Session Notes: GTYC / HYC Wind Analysis (October 2026)

**Purpose of this file:** a hand-off record so a future Claude Code session (or a person) can pick up this work without the chat history. It covers what was asked, what was decided and by whom, what was built, what went wrong, and what is still open.

**Session date:** 2026-10-19 (revised 2026-10-20) · **Location:** `studies/gtyc_hyc_2028/` in the `hrrr-location-analysis` repo

> **Moved 2026-10-22.** This work was consolidated from `~/Claude/club_climatology` and `~/Claude/output/venue_gtyc_hyc` into this repo. Code now lives in `src/hrrr_wind/` (`climatology.py` = v1.2, plus the modules listed below), tests in `tests/`, outputs and wind caches in `outputs/`, buoy files in `data/buoys/`, the slide in `slides/`. File names below use the old names; mapping: `HRRR_club_wind_climatology_v1.2.py` -> `climatology.py`, `venue_analysis_gtyc_hyc.py` -> `venue_analysis.py`, `build_report_html.py` -> `build_report.py` (in this folder), `test_climatology_v12.py` -> `tests/test_climatology.py`. On 2026-10-22 the driver was split into `config.py` (reads `study.toml`), `cache.py`, `stats.py`, `validation.py`, `plots.py`, `outputs.py`; `venue_analysis.py` is now a thin CLI. Study parameters (`PRIMARY`, `WINDOWS`, `BUOYS`) live in `study.toml`. Checkpoint folders, logs and superseded outputs were not carried over (they are in `~/Claude/output/venue_gtyc_hyc/`). A rerun from this repo reproduced every CSV byte-for-byte.
**Published report:** https://claude.ai/artifact/Ty4gwWbw1Am3bfnePk9JHt (private; shared only from the page's Share menu)

---

## 0. Revision, 20 Oct 2026 (read this first)

The user checked both clubs on Google Maps satellite view and found the GTYC preset coordinate was wrong: **GTYC is 44.78034, −85.63852** (preset had 44.7481, −85.6358, about 1.9 nm south). HYC was confirmed at **43.94475, −83.27861** (preset 43.9448, −83.2787 was already right to within 10 m). The sample points are projected from the club by bearing and distance, so the GTYC point moved from 44.7951, −85.6117 to **44.8273, −85.6144**. Presets in v1.2 were corrected; GTYC was recomputed from the existing caches (no re-download: both points sit inside the ±18 nm box). Buoy validation was unaffected because it samples HRRR at the buoy, not the club.

**What changed (GTYC Sept, racing hours):** mean 6.3 to 6.4 kt (CI 5.8–7.2); <5 / 5–15 / ≥15 kt 37 / 62 / 0.6% (was 39 / 61 / 0.2%); usable days 67% (was 64%); HYC − GTYC +2.3 kt (CI +1.3 to +3.2), ≥15 kt +10.2 points (CI +5.4 to +15.8), 5–15 kt +1.6 points (CI −7.6 to +10.8); afternoon ramp 5.6 kt at 10 AM to 7.7 kt at 5 PM; bias-adjusted mean 8.0–8.35 kt (five fits), ≥15 kt 5–7.5%; adjusted gap 1.7–2.0 kt. **Conclusions and ranking unchanged.** Buoy 45020 is now ~2.3 nm south of the sample point, not on it. Old outputs are in `output/venue_gtyc_hyc/superseded_gtyc_old_coords/`. Where the figures in §1 and later sections differ from this paragraph, this paragraph is current.

**Lesson:** I had flagged the preset coordinate as unverified but wrongly wrote that it did not matter because the point was map-chosen. The point was derived from the coordinate. Check any input that feeds a projection, and confirm both endpoints of a bearing/distance with the user.

---

## 1. The ask and the outcome

**Ask:** Characterize historical wind at two candidate regatta venues, keeping systemic errors as low as reasonably possible:
- **Grand Traverse Yacht Club (GTYC)**, Sept 8–14
- **Huron Yacht Club, Caseville (HYC)**, Sept 8–14 *and* June 14–21
- Racing hours 10 AM–4 PM EDT (14–20 UTC), years 2015–2025.

The shortlist came from an earlier nine-venue study (`Venue_Wind_Analysis_2028_Proposal.md`). That study is **not** reliable in detail (see §6).

**Outcome (headline):**
- HYC is windier than GTYC in September: **+2.4 kt mean** (95% CI +1.4 to +3.3); heavy air (≥15 kt) **+10.6 points** (CI +5.4 to +16.3).
- Share of hours in the 5–15 kt "sweet spot" is **not distinguishable** between venues (+2.9 points, CI −6.8 to +12.9).
- GTYC is an afternoon-thermal venue: mean wind ~5.2 kt at 10 AM, ~7.6 kt at 5 PM.
- HRRR runs **low against buoys** (about 1.3–1.7 kt for racing hours, height-adjusted) and under-represents heavy air. A bias-adjusted range is reported; the venue ranking is the same either way.

| Racing hours, HRRR as retrieved | GTYC Sept | HYC Sept | HYC June |
|---|---|---|---|
| Mean (kt) | 6.3 | 8.7 | 8.9 |
| < 5 / 5–15 / ≥ 15 kt | 39 / 61 / 0.2% | 25 / 65 / 9.8% | 24 / 65 / 10.7% |
| Bias-adjusted mean (kt) | 7.8–8.2 | 10.0 (upper bound) | 10.2 (upper bound) |

Full detail is in the three deliverables (§5).

---

## 2. Decisions, and who made them

### User decisions (explicit)
| Decision | Detail |
|---|---|
| Venues and windows | GTYC + HYC; Sept 8–14; HYC also June 14–21 (user wrote "say June 14–21") |
| Planning first | "Lets first do some proper planning…" (also required by `CLAUDE.md`: plan mode, approval before implementation) |
| Sample-point approach | **Map-checked + sensitivity grid** (chosen over "keep presets" / "user supplies coordinates") |
| Validate against observations | **Yes** |
| Racing hours | **10 AM–4 PM local for both seasons** |
| Window width | **Core week plus ±3-day buffer** |
| GTYC race area (first answer) | West Arm mid-channel — **later overridden** by the user after viewing the map |
| **HYC sample point** | **bearing 330°, 2 nm offshore** (was 315° in the preset) |
| **GTYC sample point** | **bearing 20°, 3 nm offshore**: "best sailing area… puts a racing circle about halfway between Power Island and GTYC" (the 340° preset was wrong for this) |
| Buoy data | User supplied NDBC **45020** (2016–2018) from `~/Claude/data/Buoy_45020/`; open to other sources → I added **45163** |
| Outputs | A markdown report, then an HTML report with embedded figures, then an artifact; plus this notes file |

### Decisions I made (open to revisit)
| Decision | Rationale |
|---|---|
| Use HRRR **F00 analysis** only | Matches the earlier method; forecast hours not tested |
| Average **water cells only** in a ±4 nm box (HRRR `LAND` field) | The v1.0/v1.1 box included land cells (for HYC: 6 of 25) |
| CIs by **resampling whole years** (2,000 draws, seed 42) | Hourly samples are strongly correlated within a year; independence would overstate precision |
| Paired GTYC vs HYC comparison by **per-day differences**, resampled by year | Same reason |
| "Usable day" = ≥3 consecutive racing hours in 5–15 kt | Closer to race-committee reality than an hourly share |
| Buoy→10 m: **neutral log law, z0 = 0.0002 m** (×1.15–1.16); raw and power-law (×1.23) shown as range | Anemometers are 2.3–2.4 m; this adjustment is the largest single uncertainty |
| Bias adjustment by **empirical quantile mapping**, fit per season on racing-hour pairs | Tested for robustness (GTYC: five fitting choices gave mean 7.8–8.2 kt; year-held-out cross-check within 0.1–0.6 kt) |
| HYC adjusted values labelled **"upper bound"** | Buoy 45163 is ~14 nm from the HYC sample point |
| Sample 24-hour days for the cache, not just racing hours | Gives diurnal curves and allows later start-time analysis without re-downloading |

---

## 3. Chronology

1. **Read the code and the earlier work.** Reviewed `HRRR_club_wind_climatology_v1.0.py`, `v1.1.py`, `HRRR_project_summary.md` (describes an older bulk-download tool, not the climatology script) and the nine-venue proposal. Flagged code issues (longitude-mask ternary precedence, no land mask, `step`/time handling, stale docstring) and report errors (§6).
2. **Plan mode** (per `CLAUDE.md`). Four clarifying questions answered (see §2). Plan saved at `/Users/jrehm/.claude/plans/quirky-scribbling-sparkle.md` and approved.
3. **Built v1.2** (copy of v1.1) with the fixes in §4. Smoke-tested on one HYC day; 7 unit tests.
4. **Mapped the HRRR land/water grid** around both clubs. Finding: GTYC's West Arm is only 1–2 water cells wide.
5. **Sensitivity grid** on a 3-year subset (2019, 2022, 2024) from a one-time cache. GTYC was insensitive; HYC's heavy-air share rose with distance from shore. Note: 3-year numbers (GTYC ~7.0, HYC ~9.7 kt) were windier than the 11-year climatology (6.3 / 8.7), so **do not quote the sensitivity-subset levels as climatology.**
6. **User revised sample points** after viewing the map (GTYC 20°/3 nm, HYC 330°/2 nm). Presets and sensitivity bearings updated; grid re-run.
7. **Full extraction, first attempt: memory blow-up.** Two background jobs reached >100 GB combined; the user killed them (see §6, lesson 1). About 50 minutes of downloads were lost because results were only saved at the end.
8. **Root cause found and fixed**, per-year checkpoints and an RSS guard added, 24-hour chunks adopted. Re-run completed in about 30 minutes with ~1.7 GB per process.
9. **Analysis** (`analyze`): core and ±3-day stats, bootstrap CIs, per-year table, paired comparison, sensitivity band, diurnal curves. Fixed a bootstrap bug (§6, lesson 4) and figure bugs.
10. **Validation** (`validate`) against buoys 45020 and 45163, including a longer GTYC HRRR download (Aug 1–Oct 9, 2016–2018) to get ~960 matched racing hours instead of 162. Bias-adjusted range and its robustness checks.
11. **Deliverables**: markdown report → HTML report with embedded figures → artifact → these notes.

---

## 4. What was built

### Code (`/Users/jrehm/Claude/club_climatology/`)
| File | Role |
|---|---|
| `HRRR_club_wind_climatology_v1.2.py` | Fork of v1.1. Water-mask box average; `valid_time`-based extraction with de-duplication; expected-vs-retrieved report; `--window-buffer-days`; CSV always written; per-club default `offshore_nm`. **GTYC preset now bearing 20°/3 nm; HYC 330°/2 nm.** v1.0 and v1.1 are untouched |
| `venue_analysis_gtyc_hyc.py` | Driver with subcommands `cache`, `sensitivity`, `analyze`, `validate` |
| `build_report_html.py` | Reads the CSVs/PNGs and writes the HTML report (standalone and artifact variants) |
| `test_climatology_v12.py` | 7 pytest unit tests (longitude wrap, projection, water mask, window builder, circular stats) |

### Outputs (`/Users/jrehm/Claude/output/venue_gtyc_hyc/`)
| File | Contents |
|---|---|
| `Venue_Wind_Analysis_GTYC_HYC.md` | Markdown report |
| `Venue_Wind_Report_GTYC_HYC.html` | Standalone HTML report (figures embedded) |
| `Venue_Wind_Report_artifact.html` | Same report without the `<html>` wrapper, as published |
| `summary_stats.csv`, `per_year_stats.csv`, `paired_sep_hyc_minus_gtyc.csv`, `sensitivity_band.csv`, `data_quality.csv` | Analysis tables |
| `validation_metrics.csv`, `bias_adjusted_summary.csv`, `validation_scatter.png` | Validation |
| `summary_*.png`, `diurnal.png` | Figures |
| `cache_{venue}_{tag}.npz` | **Raw gridded wind**, reusable for new questions (see below) |
| `ckpt_*/year_YYYY.npz` | Per-year checkpoints (a rerun of `cache` resumes from these) |
| `missing_*.json` | Missing timestamps per year |
| `cache_*.log` | Download logs (contain harmless `'href'` tracebacks for missing archive files) |

**Cache tags:** `sep_2015_2025` (Sept 5–17, all 24 h, GTYC + HYC), `jun_2015_2025` (June 11–24, HYC), `val_gtyc` (Aug 1–Oct 9, 2016–2018, GTYC only, for buoy validation), `sens3y` (3-year subset, racing hours only; used for sensitivity).

**Cache format:** `time` (datetime64), `u`, `v` (time × y × x, float32, m/s), `lat`, `lon`, `land` (y × x). The box is ±18 nm around the club. `box_series()` in the driver turns this into a speed/direction series for any sample point and radius.

### Data outside the repo
- `~/Claude/data/Buoy_45020/45020h2016–2018.txt` (user-supplied; NDBC has no other 45020 years).
- `~/Claude/data/Buoy_45163_ndbc/45163h2015–2025.txt.gz` (downloaded from NDBC `data/historical/stdmet/`).
- Herbie's GRIB cache: `~/data/hrrr` (~64 MB).

### How to re-run
```bash
# from the repo root (pip install -e ".[dev]" or export PYTHONPATH=src)
# Download (resumes from checkpoints; ~30 min for Sept+June; keep memory capped)
python -W ignore -m hrrr_wind.venue_analysis cache --venues gtyc hyc --years 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 \
    --start 09-05 --end 09-17 --tag sep_2015_2025 --chunk-hours 24 --max-rss-gb 4
python -W ignore -m hrrr_wind.venue_analysis cache --venues hyc --years 2015 ... 2025 --start 06-11 --end 06-24 --tag jun_2015_2025 --chunk-hours 24 --max-rss-gb 4
python -W ignore -m hrrr_wind.venue_analysis cache --venues gtyc --years 2016 2017 2018 --start 08-01 --end 10-09 --tag val_gtyc --chunk-hours 24 --max-rss-gb 4
# Analysis from the committed caches (fast; no network)
python -W ignore -m hrrr_wind.venue_analysis analyze
python -W ignore -m hrrr_wind.venue_analysis validate
python studies/gtyc_hyc_2028/build_report.py
python -m pytest -q
```
To change a sample point, edit the venue's `bearing`/`offshore_nm` in `study.toml` (and the preset in `climatology.py`) and re-run `analyze`, `validate`, `build_report.py`; no re-download is needed as long as the point is inside the ±18 nm cache box.

**Environment:** `python3` is 3.14 (the shell aliases `python`), herbie-data 2025.11.3, xarray 2025.11.0, pandas 2.3.3, cfgrib and pytest present. HRRR data from AWS (`noaa-hrrr-bdp-pds`); HRRR archive starts 2014-09-30.

---

## 5. Deliverables for readers
1. **Artifact (interactive, private):** https://claude.ai/artifact/Ty4gwWbw1Am3bfnePk9JHt. Update by republishing `Venue_Wind_Report_artifact.html` (same path keeps the URL), after re-running `build_report.py`.
2. **HTML file:** `Venue_Wind_Report_GTYC_HYC.html` (self-contained, opens offline).
3. **Markdown report:** `Venue_Wind_Analysis_GTYC_HYC.md`. This was written by hand from the CSVs; if the analysis is re-run, the HTML regenerates automatically but the markdown does **not**, so check its numbers.

---

## 6. Problems, bugs and lessons

1. **Memory blow-up (>100 GB).** `u.isel(y=slice, x=slice).values` on an in-memory array is a **view**, so each stored 60 KB slice pinned its entire 183 MB full-CONUS parent array. Fix: `np.array(..., dtype="float32", copy=True)` (comment in `keep()`). Also added per-year checkpoints, `check_memory()` (aborts above `--max-rss-gb`), and 24-hour chunks. *Lesson:* when running long background jobs, monitor **memory**, not just progress and errors; save results incrementally.
2. **Missing HRRR hours are real archive gaps**, not code errors. All three sources (AWS, Google, Azure) return nothing. Gaps occur only in 2015–2018 (Sept 2016: 24% missing); 2019–2025 are complete. The `'href'` tracebacks in the logs come from Herbie probing for those missing files.
3. **A background-task "completed" notification can mean only that the launching shell exited**, not that the job finished (the job was started with `nohup … &`). Check the process and output files.
4. **Bootstrap bug:** when a year was drawn twice, its dates were grouped together and the consecutive-hour counter inflated "usable day" CIs. Fixed by tagging each bootstrap copy (`draw`). Means and shares were unaffected.
5. **Earlier proposal errors** (`Venue_Wind_Analysis_2028_Proposal.md`): (a) Tawas Bay's 17.3 kt maximum is *not* the lowest of nine venues (Grand Traverse's is 16.4); (b) the 476-observation HYC count was blamed on six missing 2015 files, which cannot explain it; the cause was never identified, and the same window now gives 523. The file was written with v1.0/1.1 methods (land cells included), so its absolute numbers are not comparable to the new ones.
6. **HRRR is low against buoys** (§1). The size of the bias depends on the buoy 10 m adjustment, which cannot be resolved with the data on hand.
7. **A numeric typo** (HYC June steadiness R printed as 0.10; the data say 0.14) was fixed in the markdown. *Lesson:* copy figures from unrounded output.
8. **Tooling notes:** macOS has no `timeout`; BSD `sed -i` needs a suffix argument (use the Edit tool or Python); headless Chrome has a ~500 px minimum window width (use an iframe for narrow-width checks); headless Chrome's `preferredColorScheme` flag did not switch dark mode, so a `data-theme="dark"` copy was used to check dark rendering.

---

## 7. Caveats on the results (carry these forward)
- HRRR 3 km analysis, not observations; narrow water (GTYC West Arm) is poorly resolved.
- **The GTYC clubhouse coordinate in the preset was wrong and has been corrected (see §0).**
- Buoy 45020 (GTYC) data exist only for 2016–2018 and are ~2.3 nm south of the corrected sample point, in the same bay; buoy 45163 (HYC) is mid-bay, ~14 nm from the sample point.
- Eleven seasons, one week per year; CIs are wide and a few years drive HYC's heavy-air share.
- No gusts. No forecast hours. Course layout, logistics and fleet preferences are out of scope.

---

## 8. Open items and ideas
- **GTYC start-time analysis** (e.g., 12–6 PM windows): the cached 24-hour data supports it directly. Suggested because of the strong ramp (5.2 → 7.6 kt).
- A **closer HYC reference observation** (candidates found but not downloaded: NDBC HRBM4 Harbor Beach, NDBC 45008). Would tighten the HYC bias adjustment.
- Sensitivity of the bias adjustment to roughness length / atmospheric stability.
- Whether to add **gusts** (HRRR gust is a surface field; reliability at F00 uncertain).
- Share the artifact with the committee (the link is private until shared via its Share menu).
- Optional housekeeping: the `ckpt_*` folders and `cache_*.log` files can be deleted once the `cache_*.npz` files are safe; `sens3y` caches are only needed to reproduce the sensitivity table.
- `CLAUDE.md` lists npm-based test/typecheck commands that do not apply to this Python subproject; pytest and `py_compile` were used instead. Consider adding a Python section.

---

## 9. Prompt to resume in a new session
> Read `studies/gtyc_hyc_2028/NOTES.md` in `~/Documents/GitHub/hrrr-location-analysis`. The GTYC/HYC wind analysis is complete and the data caches are in `studies/gtyc_hyc_2028/outputs/`. I want to [new question, e.g. test later GTYC start times using the cached hourly data]. Start in plan mode, per CLAUDE.md, and watch memory use on any download.
