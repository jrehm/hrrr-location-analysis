# hrrr-location-analysis

Python tool + studies for HRRR wind climatology at sailing venues (see README.md).

## Layout
- `src/hrrr_wind/` library: `climatology.py` (v1.2 CLI/presets/stats), `venue_analysis.py` (cache / sensitivity / analyze / validate), `report_html.py`
- `tests/` pytest; `legacy/` frozen v1.0/v1.1 + the nine-venue 2028 proposal (do not edit)
- `studies/gtyc_hyc_2028/` the GTYC vs HYC study: `NOTES.md` (read first), `outputs/` (CSVs, figures, wind caches), `data/buoys/`

## Verification (Python project: ignore any npm rules from a parent CLAUDE.md)
- `python -m pytest -q` and `python -m py_compile src/hrrr_wind/*.py`
- Regression: `python -m hrrr_wind.venue_analysis analyze` must reproduce `studies/gtyc_hyc_2028/outputs/summary_stats.csv`

## Rules learned the hard way
- Long extractions: copy numpy slices (`np.array(..., copy=True)`), checkpoint per year, cap RSS (`--max-rss-gb`), and watch memory, not just logs.
- Bearing/distance sample points are projected FROM the club coordinate: confirm club coordinates (satellite view) before any run.
- Do not push without asking; the remote is public.
