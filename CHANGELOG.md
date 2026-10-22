# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/): MAJOR for incompatible changes to `study.toml` or output
files, MINOR for new features, PATCH for fixes. The version lives in one place,
`__version__` in `src/hrrr_wind/__init__.py`; the web app shows it in the footer and `/api/health`.

## [Unreleased]

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

[Unreleased]: https://github.com/jrehm/hrrr-location-analysis/compare/v1.3.0...HEAD
