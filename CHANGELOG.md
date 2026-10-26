# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/): MAJOR for incompatible changes to `study.toml` or output
files, MINOR for new features, PATCH for fixes. The version lives in one place,
`__version__` in `src/hrrr_wind/__init__.py`; the web app shows it in the footer and `/api/health`.

## [Unreleased]
### Changed
- The web app's default port is now 8123 (was 8000, which clashed with other local apps); the Dockerfile and README follow. `--port` still overrides it.

### Added
- Files tab: a **Buoy data on disk** section (venue, buoy, years, files, size) and a totals row or line at the bottom of every section. The `/api/studies/{id}/files` list now carries file sizes.
- Delete a whole study in two steps. **Delete this study** (bottom of the Inputs page; the study's name must be typed) moves it to `studies/.trash/`; a **Trash** card (on the Inputs and New study pages) restores a trashed study or empties the trash, which needs a second confirmation where `empty trash` is typed. The locked reference study, read-only servers and studies with a running job are refused.
- Set up validation from the Validation tab: choose a nearby NDBC buoy for each venue on a satellite map (stations within
  60 nm that archived wind in the study's years), confirm the anemometer height, and a `buoy` job downloads the
  observations, fetches HRRR around the buoy when it lies outside the venue's cache box (with a size estimate up front),
  and validates. Buoys can be changed or removed; downloaded files stay on disk. New `ndbc.py` holds the NOAA network code. The anemometer height is read from the buoy's NDBC station page. An (i) button on the Buoys card explains the steps, and the search radius can be widened (30 to 150 nm).
- Day / Night / Auto theme toggle at the right of the study tab bar (remembered in the browser).
- An (i) button on the Validation page opens a dismissable explanation of how HRRR is compared with the buoys.

### Changed
- Files tab lists every wind cache on disk, including those of venues removed from the study (marked "removed"), and says what uses each (a window, a buoy or nothing). New **Unused data** card deletes caches and buoy-data folders that nothing uses, after a confirmation that states the size. Used data, locked studies, read-only servers, running jobs and folders outside the study are refused.
- Validation tab: buoy ids link to their NDBC station pages, and the table has a column with the distance from each buoy to the venue's sample point.
- Buoys no longer count toward the analysis fingerprint, so adding or changing one does not mark results out of date.
- The study header and tabs stay fixed while the page content scrolls; inactive study tabs contrast more with the background.
- The wind-rose explanation appears once under the venue cards instead of on every card.
- Charts have nine distinct series colors (and marker shapes) instead of three that repeated. A study may now hold
  up to 9 venues and 9 windows (was 4 and 6); that is the hard limit.

## [2.0.0] - 2026-10-23
### Fixed
- The Advanced downloads table on the Venues page failed to render (a missing import after the cache tags were hidden).
- Only the last 3 job logs are kept in a study's `jobs/` folder (older ones are deleted when a new job starts).
- Checkpoint folders (`ckpt_<tag>`) are deleted once a download finishes and its caches are written, and
  rerunning a finished tag does nothing instead of refetching. The Files page no longer shows cache tags.
- The web app sends `Cache-Control: no-cache` for its static files, so browsers pick up edited scripts and styles
  instead of mixing old and new versions.

### Changed
- Study page layout: the Venues tab is now **Inputs** and comes first, with a Years section (the year picker, always
  shown; read-only for locked studies) above a Venues section. The Compare tab is gone: its tables now sit at the
  bottom of Overview. Rename is a small pencil icon, and the header's "Edit years" link is removed. Old
  `#/s/<id>/venues` and `/compare` links still work.
- **Breaking:** the sweet spot is now 5–20 kt (was 5–15) everywhere: stats, usable days, validation bins, the
  single-club CLI and the UI. Output columns are renamed `pct_5_15` -> `pct_5_20` and `pct_ge15` -> `pct_ge20`
  (also `_lo`/`_hi`, `obs_`/`hrrr_` and per-year/paired/sensitivity files); `pct_15_20` is removed. Existing
  results should be recomputed (the app flags them as out of date). The GTYC/HYC reference study's CSVs,
  figures and report were regenerated, and its sweet-spot conclusion changed (see its NOTES.md).
- Wind roses and speed-mix bars: blue below 5 kt, three greens for 5–10, 10–15 and 15–20 kt, amber for 20 kt and up.
- Studies are now tabs across the top of every page, with a `+` tab for a new study (extra studies wrap to another
  row); the home page is gone and the app opens on the first study.
- Faster downloads: each hour is cropped to the venue boxes as soon as it is decoded (no full-CONUS
  stack per chunk), and the next chunk downloads while the previous one is stored.

## [1.3.1] - 2026-10-22
### Fixed
- Downloads no longer hang on a dropped connection: network calls time out (45 s), chunks are retried,
  and a year hit by download errors is not saved (a rerun resumes) instead of being stored with gaps.
- A job that prints nothing for 10 minutes is stopped and shown as failed with a "Try again" hint.

## [1.3.0] - 2026-10-22
### Added
- New study / add venue from the web app: click the club on the map, set windows and years, and a
  single `run_study` job downloads, analyzes and validates. Caches are never overwritten.
- Studies home page, per-study tabs (Overview, Venues, Compare, Validation, Files) and a status strip
  that always shows the study's state and the next action.
- Editing after creation: rename (display name only), edit a sample point, add or remove windows and
  venues, add or exclude years (new years download into separate caches and merge). Edits keep
  `study.toml.bak` and never delete data from disk.
- Years of data shown per window, per study and in the Files tab.
- Studies without buoys skip validation; venues may carry their own name and coordinates.
- Version shown in the page footer; `CHANGELOG.md`.
### Changed
- Results are "out of date" when the analysis-relevant study definition changes (fingerprint), not by file time.
- `Study` windows may list `more_caches`; `load_series` concatenates them and keeps only `study.years`.
### Fixed
- Server crash when the map preview loaded the land mask (PROJ fork handler); it now runs in a child process.
- Analysis of a venue whose sample box has no water now fails with a clear message.
- The job log panel can be closed after a run finishes.

## [1.2.0] - 2026-10-22
### Added
- Background jobs (download, analyze, validate) with progress, cancel, resume and a memory cap;
  slim install, Docker image, CI; optional PowerPoint slide generator.

## [1.1.0] and [1.0.0]
- Single-club climatology CLI and the GTYC vs HYC 2028 study (frozen under `legacy/`).

[Unreleased]: https://github.com/jrehm/hrrr-location-analysis/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/jrehm/hrrr-location-analysis/compare/v1.3.1...v2.0.0
[1.3.1]: https://github.com/jrehm/hrrr-location-analysis/compare/v1.3.0...v1.3.1
