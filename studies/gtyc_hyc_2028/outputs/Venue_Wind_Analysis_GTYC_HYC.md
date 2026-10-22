# GTYC vs. HYC (Caseville) — Historical Wind Characterization

**Prepared:** October 2026
**Venues:** Grand Traverse Yacht Club (GTYC), Huron Yacht Club, Caseville (HYC)
**Windows (core):** Sept 8–14 (both venues); June 14–21 (HYC only)
**Racing hours:** 10 AM–4 PM EDT (14–20 UTC) · **Years:** 2015–2025 (11 seasons)
**Data:** NOAA HRRR 3 km analysis (F00), 10 m wind, water cells only; checked against NDBC buoys 45020 and 45163

> **Revised 20 Oct 2026.** The first version measured GTYC's bearing and distance from a club position about 1.9 nm too far south (44.7481 N, 85.6358 W). The satellite-confirmed position is 44.78034 N, 85.63852 W (HYC's was already correct to within 10 m). The GTYC sample point moved north by the same amount and all GTYC figures were recomputed from the same cached data. Conclusions are unchanged; GTYC's mean rose 0.1 kt (6.3 to 6.4). The earlier outputs are kept in `superseded_gtyc_old_coords/`.

---

## 1. Bottom line

1. **HYC is the windier venue in September, and that holds up.** After accounting for year-to-year variability, HYC averages **+2.3 kt** more than GTYC (95% CI +1.3 to +3.2) and has more heavy-air hours (+10.2 points at ≥15 kt, CI +5.4 to +15.8).
2. **The two venues are not distinguishable on the share of racing hours in the 5–15 kt sweet spot** (+1.6 points for HYC, CI −7.6 to +10.8). Neither is clearly better for "moderate" wind. They differ in how they fail: GTYC fails on light air, HYC on heavy air.
3. **GTYC is an afternoon-thermal venue.** Mean wind rises from about 5.6 kt at 10 AM to 7.7 kt at 5 PM. A 10 AM start catches the lightest part of the day; later starts should help (see §6).
4. **HYC's mid-June window looks like September** (8.9 vs 8.7 kt mean, similar speed mix), but June has a stronger afternoon build (8.4 kt at 10 AM to 9.8 kt at 5 PM).
5. **HRRR reads low against the buoys, so treat §4 numbers as a lower bound for wind.** Against on-water buoys, HRRR is about 1.3–1.7 kt low for racing hours (height-adjusted) and under-represents heavy air. A bias-adjusted range is given in §5. **The venue ranking is the same either way; the absolute levels are not.**
6. **Year-to-year variability dominates.** Yearly September means range 4.6–9.2 kt (GTYC) and 5.0–12.3 kt (HYC). Eleven seasons give useful but wide intervals; do not read small differences as real.

---

## 2. Method (and what was done to limit systemic error)

| Issue in the earlier nine-venue study | What was done here |
|---|---|
| Box average included land cells | Averages **only HRRR water cells** inside the box (HRRR land/water field). For HYC, 6 of 25 cells in the old default box were land |
| One unvalidated sample point | **Sensitivity grid** over offshore distance (1–6 nm), box radius (2/4/6 nm) and bearing; results in §3 |
| HRRR never checked against observations | **Buoy validation** (§4) and a bias-adjusted range (§5) |
| Sample counts that didn't reconcile | Expected vs. retrieved hours are tracked per year; missing hours listed in `missing_*.json` (§7) |
| Hourly samples treated as independent | Confidence intervals come from **resampling whole years** (2,000 draws), which respects within-year correlation. Paired comparisons use per-day differences |
| One 7-day window | Reported for the core week **and** a ±3-day buffer window |
| Code defects (longitude mask precedence, stale docstring) | Fixed in `src/hrrr_wind/climatology.py`; 7 unit tests |

**Sample points** (as chosen by the user from the map):

| Venue | Bearing / offshore | Point | Water cells in ±4 nm box |
|---|---|---|---|
| GTYC | 20° / 3 nm from the club at 44.78034 N, 85.63852 W (racing circle roughly midway to Power Island) | 44.8273 N, 85.6144 W | 11 |
| HYC | 330° / 2 nm from the club at 43.94475 N, 83.27861 W | 43.9737 N, 83.3018 W | 19 |

**Wind speed bins:** <5 kt (light), 5–15 kt (sweet spot), ≥15 kt (heavy). **"Usable day"** = at least 3 consecutive racing hours in 5–15 kt.

---

## 3. Results — HRRR as retrieved (core windows, racing hours)

Intervals are 95% year-resampling CIs.

| | GTYC Sept 8–14 | HYC Sept 8–14 | HYC June 14–21 |
|---|---|---|---|
| Racing-hour samples | 523 | 523 | 588 |
| **Mean (kt)** | **6.4** (5.8–7.2) | **8.7** (7.4–10.1) | **8.9** (8.1–9.6) |
| Median / 90th pct (kt) | 6.4 / 10.7 | 8.1 / 14.9 | 8.8 / 15.2 |
| Maximum (kt) | 20.0 | 19.4 | 26.5 |
| **< 5 kt** | **37%** (27–46) | 25% (16–35) | 24% (20–29) |
| **5–15 kt** | 62% (54–72) | 65% (56–73) | 65% (59–71) |
| **≥ 15 kt** | **0.6%** (0–1.5) | **9.8%** (5.0–15.4) | **10.7%** (5.5–16.1) |
| Usable days (≥3 h in 5–15 kt) | 67% (57–79) | 77% (63–90) | 73% (65–82) |
| Wind from N / E / S / W quadrant | 37 / 18 / 28 / 17% | 39 / 11 / 22 / 29% | 40 / 14 / 27 / 19% |
| Direction steadiness R (0 = variable) | 0.11 | 0.21 | 0.14 |

Wind direction is highly variable at both venues (R ≈ 0.1–0.2). The most common quadrant is north (37–40%) in every window, with HYC in September showing more westerly flow (29%).

**Robustness to the ±3-day buffer window:** GTYC 6.9 kt (6.4–7.4); HYC Sept 8.7 (8.0–9.5); HYC June 9.0 (8.5–9.4). Conclusions do not change.

**Robustness to the sample point** (primary bearing, offshore 1–6 nm, radius 2–6 nm):

| | Mean (kt) | < 5 kt | 5–15 kt | ≥ 15 kt |
|---|---|---|---|---|
| GTYC Sept | 6.3–6.7 | 34–38% | 62–65% | 0.2–0.8% |
| HYC Sept | 8.5–8.9 | 23–28% | 61–68% | 8.6–13.0% |
| HYC June | 8.7–9.1 | 22–26% | 63–67% | 9.9–11.9% |

Sample-point choice moves the numbers far less than year-to-year variability does. The exception is HYC's heavy-air share, which rises the further the sample point is from shore.

**Paired comparison, September (77 days, differences resampled by year):**

| HYC minus GTYC | Difference | 95% CI |
|---|---|---|
| Mean wind (kt) | +2.3 | +1.3 to +3.2 |
| Share in 5–15 kt (points) | +1.6 | −7.6 to +10.8 |
| Share ≥ 15 kt (points) | +10.2 | +5.4 to +15.8 |

### Year by year (racing-hour mean, kt; share ≥15 kt in brackets)

| Year | GTYC Sept | HYC Sept | HYC June |
|---|---|---|---|
| 2015 | 7.1 (0%) | 9.1 (5%) | 6.1 (0%) |
| 2016 | 8.1 (2%) | 7.8 (2%) | 9.5 (24%) |
| 2017 | 4.6 (0%) | 6.1 (8%) | 8.7 (15%) |
| 2018 | 6.3 (0%) | 9.7 (28%) | 7.9 (0%) |
| 2019 | 9.2 (4%) | 12.3 (25%) | 8.7 (0%) |
| 2020 | 6.7 (0%) | 11.5 (10%) | 6.4 (0%) |
| 2021 | 6.1 (0%) | 10.7 (14%) | 9.9 (21%) |
| 2022 | 6.2 (0%) | 7.9 (6%) | 10.5 (20%) |
| 2023 | 5.3 (0%) | 6.3 (0%) | 9.7 (18%) |
| 2024 | 6.1 (0%) | 8.7 (8%) | 10.5 (5%) |
| 2025 | 5.2 (0%) | 5.0 (0%) | 9.2 (14%) |

HYC's heavy air is concentrated in a few years (e.g. 2018, 2019): in Sept, 4 of 11 years had ≥10% heavy-air hours (2018–2021), and 2 had none (2023, 2025). GTYC reaches 15 kt in HRRR only in 2016 and 2019 (2% and 4% of racing hours).

---

## 4. Validation against buoys

| | GTYC | HYC |
|---|---|---|
| Buoy | NDBC 45020, Grand Traverse Bay South (44.789 N, 85.604 W) | NDBC 45163, Saginaw Bay (43.983 N, 83.600 W) |
| Distance from sample point | about 2.3 nm (buoy is south of the racing area, same bay) | about 14 nm (mid-bay, WSW) |
| Data used | 2016–2018, Aug 1–Oct 9 (provided by user; seasonal buoy, decommissioned after 2018) | 2015–2025 inside the Sept and June windows |
| Anemometer height | 2.4 m | 2.3 m |
| Matched racing hours | 960 | 1,796 |

Buoy winds are scaled to 10 m with a neutral log profile (roughly ×1.15). The raw and power-law (×1.23) versions are shown because the adjustment is the largest single uncertainty.

| Racing hours, HRRR minus buoy | GTYC | HYC |
|---|---|---|
| Bias, log-adjusted (kt) | −1.6 to −1.7 | −1.3 |
| Bias, raw buoy (kt) | −0.5 | +0.1 |
| Bias, power-law adjusted (kt) | −2.2 | −2.0 |
| Correlation of hourly speeds | 0.64–0.67 | 0.79–0.80 |
| RMSE, log-adjusted (kt) | 3.8–3.9 | 3.4 |
| HRRR in same speed bin as buoy | 68% | 72–73% |
| Direction bias / mean abs. error | −15° / 32° | −10° / 20° |

| Racing hours: share in bin | Buoy (10 m-adj.) | HRRR at buoy |
|---|---|---|
| GTYC < 5 / 5–15 / ≥15 kt | 24.5 / 66.7 / 8.9% | 30–31 / 67–68 / 1.7–2.0% |
| HYC < 5 / 5–15 / ≥15 kt | 14.9 / 66.6 / 18.4% | 19–20 / 70 / 10% |

**Reading:** HRRR gets the timing of wind changes right (HYC especially) but runs low, is too light-air-heavy, and almost never produces the heavy-air events the buoys record. Directions are rotated by 10–15° on average. GTYC's correlation is the weaker of the two, consistent with a narrow bay that a 3 km grid represents with only a few water cells.

---

## 5. Bias-adjusted range

HRRR was **quantile-mapped** to the height-adjusted buoy winds, fitted separately by season on the matched racing-hour pairs, and applied to the venue series. This is an adjustment, not a measurement; the right number likely lies between the raw HRRR (§3) and the adjusted values.

| Racing hours | Version | Mean (kt) | < 5 kt | 5–15 kt | ≥ 15 kt |
|---|---|---|---|---|---|
| GTYC Sept | HRRR raw | 6.4 | 37% | 62% | 0.6% |
| | Bias-adjusted | **8.0–8.35** | 29–33% | 62–65% | **5–7.5%** |
| HYC Sept | HRRR raw | 8.7 | 25% | 65% | 9.8% |
| | Bias-adjusted | 10.0 | 19% | 58% | 23% |
| HYC June | HRRR raw | 8.9 | 24% | 65% | 10.7% |
| | Bias-adjusted | 10.2 | 18% | 63% | 19% |

How much to trust the adjustment:
- **GTYC:** the buoy is about 2 nm south of the sample point, in the same bay, and 337 September pairs support the fit. The result was stable across five fitting choices (quantile mapping fitted on Sept only, Aug–Oct, or Sept+Oct, and two linear scalings): mean 8.0–8.35 kt, ≥15 kt 5–7.5%. A cross-check fitted on one year and tested on the others predicted 8.28 vs. an observed 8.39 kt (fit 2016) and 9.29 vs. 8.65 kt (fit 2018). **Moderate confidence.**
- **HYC:** the buoy is 14 nm from the sample point in open bay, so the adjustment may overstate wind near the Caseville shore, particularly heavy air (23%). **Treat as an upper bound.**
- The adjusted GTYC-vs-HYC gap is about 1.7–2.0 kt, so the ranking is unchanged.

---

## 6. Time of day

Mean wind by local hour in the core windows (HRRR raw, kt):

| Local hour | 9 | 10 | 11 | 12 | 1 PM | 2 PM | 3 PM | 4 PM | 5 PM | 6 PM |
|---|---|---|---|---|---|---|---|---|---|---|
| GTYC Sept | 5.2 | 5.6 | 5.8 | 5.9 | 6.3 | 6.7 | 7.2 | 7.4 | 7.7 | 7.6 |
| HYC Sept | 9.0 | 9.0 | 9.1 | 8.7 | 8.6 | 8.3 | 8.3 | 8.7 | 8.8 | 8.8 |
| HYC June | 8.5 | 8.4 | 8.5 | 8.7 | 8.6 | 9.2 | 9.2 | 9.6 | 9.8 | 9.6 |

- **GTYC** shows a strong diurnal cycle (about 5 kt overnight, peak around 5 PM). The 10 AM–4 PM window straddles the ramp-up.
- **HYC in September** is nearly flat through the day (synoptic-driven), with a slight afternoon dip.
- **HYC in June** builds through the afternoon.

See `diurnal.png`.

---

## 7. Data quality

| | GTYC Sept | HYC Sept | HYC June |
|---|---|---|---|
| Racing hours present / expected (core) | 523 / 539 | 523 / 539 | 588 / 595 |
| Full-day hours present / expected (core) | 1,785 / 1,848 | 1,785 / 1,848 | 2,018 / 2,088 |

All missing hours fall in **2015–2018**; 2019–2025 are complete. Missing hours across the extended (buffer) download:

| | 2015 | 2016 | 2017 | 2018 |
|---|---|---|---|---|
| Sept 5–17 (312 h/yr) | 19 | 74 | 10 | 19 |
| June 11–24 (336 h/yr) | 48 | 57 | 7 | 6 |

The gaps are archive gaps (checked against AWS, Google and Azure). 2016 is the weakest year (24% of September hours absent). The earlier proposal's "six missing 2015 files" explanation for HYC's lower count does not reconcile with the data.

**Corrections to the earlier proposal** (`Venue_Wind_Analysis_2028_Proposal.md`): Tawas Bay's 17.3 kt maximum is *not* the lowest of the nine venues (Grand Traverse's 16.4 kt is lower); and the cause of the 476-observation HYC count was never identified (the explanation given, six missing 2015 files, does not account for it). The same window now returns 523 racing hours for HYC, with all 16 missing hours in 2015–2018.

---

## 8. Caveats

- HRRR is a 3 km model analysis, not an observation. It is low-biased against the buoys and handles narrow water (GTYC's West Arm is 1–2 grid cells wide) poorly.
- Buoy wind at 2.3–2.4 m must be scaled to 10 m. The result is sensitive to the method (§4), and stability effects are not modeled.
- The GTYC buoy record is only 2016–2018 and the HYC buoy is 14 nm from the sample point.
- Eleven seasons; one calendar week per year. Intervals are wide, and a few years drive the HYC heavy-air share.
- Race-course layout, shoreline effects inside the bay, safety, logistics and fleet preferences are not captured.

---

## 9. Files (all in `studies/gtyc_hyc_2028/outputs/`)

| File | Contents |
|---|---|
| `summary_stats.csv`, `per_year_stats.csv`, `paired_sep_hyc_minus_gtyc.csv` | Section 3 tables |
| `sensitivity_band.csv`, `sensitivity_sens3y.csv` | Sample-point sensitivity |
| `validation_metrics.csv`, `bias_adjusted_summary.csv`, `validation_scatter.png` | Sections 4–5 |
| `data_quality.csv`, `missing_*.json` | Completeness |
| `summary_gtyc_sep.png`, `summary_hyc_sep.png`, `summary_hyc_jun.png`, `diurnal.png` | Figures |
| `cache_*.npz` | Raw gridded wind around each venue (reusable for new questions) |

Code: `src/hrrr_wind/climatology.py`, `src/hrrr_wind/venue_analysis.py` (subcommands `cache`, `sensitivity`, `analyze`, `validate`), `tests/test_climatology.py`.
