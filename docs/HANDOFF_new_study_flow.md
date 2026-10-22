# Handoff: "New study / add venue" flow (written 2026-10-22)

Read this first in a fresh session, then `CLAUDE.md`, then `studies/gtyc_hyc_2028/NOTES.md`.
Start in plan mode (project rule) and get the plan approved before coding.

## State of the repo
- `main` is pushed and CI is green (unit 3.11-3.13, slim install, golden reproduction).
- Library: `src/hrrr_wind/` (`config`, `cache`, `stats`, `validation`, `plots`, `outputs`, `jobs`, `api/`, `web/static/`).
- Web app: `python -m hrrr_wind.api` (Preact + htm, no build step). Pages: Sample point, Results, Compare,
  Validation, Files, Jobs (local mode only). Jobs = download/analyze/validate subprocesses with progress,
  cancel, resume, memory cap, never overwrite caches.
- Old `~/Claude/club_climatology` and `~/Claude/output/venue_gtyc_hyc` were deleted; archive at
  `~/Claude/archive/hrrr_gtyc_hyc_pre_repo_2026-10-22.tar.gz`. The repo is the only copy.
- Not done: the Docker image was never built (daemon was off); no hosted demo exists; phone widths below 500 px unchecked.

## Goal of this step
Let someone who does not touch code create a study for their own venue(s): name, club position (click on the
satellite map), bearing/distance, windows and years, optionally a buoy; then run download -> analysis -> view.

## Why it is not trivial (verified facts)
1. **Venues are hard-wired to the preset dict.** Places that read `clim.YACHT_CLUB_PRESETS` / `Venue.preset`:
   `cache.py:85-86` (`build_cache` takes club lat/lon from presets), `config.py:32,36,122` (`Venue.preset`,
   `.name`, `sample_point`), `api/app.py:100,101,123` (meta + geometry). Fix: let `[[venues]]` in `study.toml`
   carry optional `name`, `lat`, `lon` (falling back to the preset) and pass coordinates into `build_cache`.
2. **Studies with no buoys crash validation plotting**: `run_validation` returns empty frames but
   `plots.validation_figure({})` raises `ValueError: Number of columns must be a positive integer`.
   Make validation optional (skip figure/CSV, UI hides the page, `bias_adjusted_summary` absent).
3. **The map preview needs a land mask, which only exists after a download.** `/geometry` reads cached cells. For a
   brand-new venue, fetch one HRRR file's `LAND` field (a few seconds; needs the `[download]` extra, local mode only)
   and cache it, or the preview shows only the box without water/land cells.
4. **Pages assume results exist.** A new study has no CSVs until its jobs finish. `/results` already returns empty
   lists, but `useStudyData` fetches windrose/diurnal per window and will 500/throw on missing caches. Add empty states.
5. **No TOML writer.** Add `tomli_w` (or hand-format). Never string-concatenate user text into TOML.
6. **Cache window convention**: the cache covers core window +/- 3 days (the "buffer" statistics). The wizard must compute
   this (see `studies/gtyc_hyc_2028/NOTES.md`) and the job params (`start`/`end`, `tag`).

## Proposed design (to confirm in plan mode)
- API: `POST /api/studies` {name, tz/race hours, years, venues[{key,name,lat,lon,bearing,offshore_nm,radius_nm}],
  windows[{venue,season,core:[MM-DD,MM-DD]}], pairs?, buoys?} -> validates (slug unique, key chars, lat/lon ranges,
  years >= 2015, <= N venues/windows, bearing 0-359, offshore <= 30) and writes `studies/<slug>/study.toml` + `outputs/`.
  403 in read-only mode. No deleting or editing existing studies in this step (create only).
- A pipeline job kind `run_study` that chains cache (per window) -> analyze -> validate, reusing `jobs.py` (one at a time,
  same memory cap, same progress lines).
- UI: a "New study" page (map click sets club position, bearing/distance preview, window rows, years), then redirect to
  Jobs with the pipeline running; study picker in the header (the app currently always opens the first study).
- Keep the library pure: validation of a study definition lives in `config.py` (`Study` validation) so CLI and API share it.

## Acceptance
- Create a one-venue, one-window, one-year study through the API in a temp `HRRR_WIND_STUDIES`, run the pipeline for real
  (about 25 s for 24 files), and see Results render. Add tests: definition validation (hostile inputs), TOML round-trip,
  no-buoy study end to end, read-only 403. Keep the golden test green. Verify pages in real Chrome.

## Environment facts and gotchas
- Run the app against a throwaway copy of outputs when testing jobs: `HRRR_WIND_OUT=/tmp/x python -m hrrr_wind.api --port 8766`.
- htm treats a literal `< 5` in a template as a tag: write `${"<"} 5`.
- Headless Chrome cannot go below 500 px wide and nested iframes stall virtual time; the Claude-in-Chrome extension works
  when connected and is the right tool for real clicks.
- Long jobs: watch memory (cap with `--max-rss-gb`), checkpoint per year, never run uncapped (a 100 GB leak happened once).
- Ask before `git push` (remote is public) unless the user's current instruction explicitly includes it.
- `build_cache` once shadowed its `start` argument and no test caught it until a real download ran; keep the fake-source
  test in `tests/test_cache.py` strict.

## Resume prompt
> Read `docs/HANDOFF_new_study_flow.md` in `~/Documents/GitHub/hrrr-location-analysis`, then plan the "new study / add venue"
> flow (plan mode first). Confirm the design choices with me before coding.
