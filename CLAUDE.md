# hrrr-location-analysis

Python tool + studies for HRRR wind climatology at sailing venues (see README.md).

## Layout
- `src/hrrr_wind/` library: `climatology.py` (single-club CLI, presets), `config.py` (study.toml), `cache.py` (only network code), `stats.py`, `validation.py`, `plots.py`, `outputs.py`, `venue_analysis.py` (thin CLI), `api/app.py` (FastAPI, JSON only) and `web/static/` (Preact + htm UI, no build step, vendored libs)
- `tests/` pytest; `legacy/` frozen v1.0/v1.1 + the nine-venue 2028 proposal (do not edit)
- `studies/gtyc_hyc_2028/` the GTYC vs HYC study: `study.toml`, `NOTES.md` (read first), `build_report.py`, `outputs/` (CSVs, figures, wind caches), `data/buoys/`

## Verification (Python project: ignore any npm rules from a parent CLAUDE.md)
- `python -m pytest -q` and `python -m py_compile src/hrrr_wind/*.py`
- Web UI: run `python -m hrrr_wind.api` and check every page in a browser (headless Chrome screenshots work; htm treats a literal `< 5` in a template as a tag, write it as `${"<"} 5`)
- Jobs: downloads/recomputes run as subprocesses (`jobs.py`); never let a request overwrite an existing cache; `HRRR_WIND_READONLY=1` must keep every write endpoint at 403
- Regression: `python -m pytest -m golden` (about 3 min) must pass after any change to stats/validation/cache code

## Where we are
`docs/HANDOFF_new_study_flow.md` describes the current state and the next planned feature (new study / add venue flow).

## Rules learned the hard way
- Long extractions: copy numpy slices (`np.array(..., copy=True)`), checkpoint per year, cap RSS (`--max-rss-gb`), and watch memory, not just logs.
- Bearing/distance sample points are projected FROM the club coordinate: confirm club coordinates (satellite view) before any run.
- Do not push without asking; the remote is public.
