# Deployment options: desktop app and hosting

Summary of a design discussion (2026-10-28). Nothing here is implemented yet.

## Starting point

- Local FastAPI server (`python -m hrrr_wind.api`, default port 8123) serving a no-build Preact UI.
- Core deps (numpy, pandas, matplotlib, fastapi, uvicorn) are plain pip. The download stack (`herbie-data`, `xarray`, `cfgrib`) is optional and needs the eccodes C library.
- `HRRR_WIND_READONLY=1` keeps every write endpoint at 403. A `Dockerfile` exists. `studies/` is about 60 MB.
- `jobs.py` runs downloads and recomputes as `[sys.executable, "-m", "hrrr_wind.venue_analysis", ...]` subprocesses.
- `config.STUDIES_DIR` defaults to `REPO_ROOT / "studies"` (override with `HRRR_WIND_STUDIES`).

## 1. Local desktop app (Mac / Windows)

Mostly packaging, not re-architecture.

Required changes:
1. Per-user data directory (`~/Library/Application Support/HRRR Wind`, `%APPDATA%\HRRR Wind`, e.g. via `platformdirs`) instead of the repo path. Copy the sample study on first run.
2. A `hrrr-wind` entry point that starts uvicorn on 127.0.0.1 and opens the browser. Optionally wrap in `pywebview`.
3. Frozen builds (PyInstaller/Briefcase): `sys.executable` is the app itself, so job subprocesses need a `--run-job` dispatch mode.
4. eccodes: the hard part, especially on Windows. conda-forge solves it; bundling it by hand is fiddly.
5. Cross-platform testing (Windows job cancellation, paths, Agg backend, golden test) via a GitHub Actions matrix.

Distribution options, easiest first: `pipx install`; conda env + launcher; PyInstaller/Briefcase `.app`/`.exe` (150-300 MB, signing/notarization costs); Tauri/Electron shell (highest effort); Docker (works today, needs Docker Desktop).

Key scoping question: if users only view existing studies, eccodes is not needed and this gets much easier. Ship a viewer bundle and make downloads an optional component.

## 2. Public hosted web app

- **Read-only viewer (easy, hours):** deploy the Dockerfile with `HRRR_WIND_READONLY=1` and studies baked into the image on Fly.io, Railway, Render, Cloud Run, Hugging Face Spaces, or a small VPS. A static export (pre-rendered JSON on Pages/Netlify) is an option for zero running cost, at 1-3 days of work.
- **Accounts and self-serve studies (hard, about 10x):** needs persistent per-user storage (the code assumes a local filesystem), auth and multi-tenancy, a job queue with workers (extractions use several GB of RAM and hours), cost and abuse control, and hardened write endpoints. Only worth it with real demand.
- **Curated middle path:** public read-only viewer; new studies are run locally and published by redeploying.

## 3. Small group on a spare Mac (the chosen direction)

Audience: a few trusted people experimenting, so they need the write endpoints. READONLY is all-or-nothing and cannot be the safety net.

Avoid a raw router port-forward: the app has no auth, no TLS, uvicorn is not hardened for the internet, and residential IPs change or sit behind CGNAT.

Preferred options:

| Option | Effort | Notes |
|---|---|---|
| Tailscale (recommended) | ~30 min | Private encrypted network, no open ports. Each tester installs the client. |
| Cloudflare Tunnel + Access | ~1 hour | Public HTTPS URL behind an email allow-list login. Needs a domain (~$10/yr). |
| Tailscale Funnel | ~15 min | Public URL with no login layer, so same no-auth problem. |
| Port-forward + Caddy (TLS + basic auth) | A few hours | Works, but you maintain it. Bind uvicorn to 127.0.0.1. |

Mac setup regardless of access method:
- Disable sleep, auto-restart after power failure, static LAN IP or DHCP reservation.
- Run under `launchd` so it starts at boot and restarts on crash.
- Use a dedicated `HRRR_WIND_STUDIES` directory so experiments don't touch real studies (check `LOCKED_STUDIES` coverage).
- Cap concurrent jobs (one or two) and use `--max-rss-gb`. A single extraction can use several GB.
- Back up the studies folder (Time Machine or nightly rsync).
- Be aware testers can see, modify and delete each other's studies. Whole-study delete goes to `studies/.trash/`.

## Suggested next steps

1. Write a `launchd` plist, a start script (studies dir, bind address), and a short setup doc for the spare Mac.
2. Check whether `jobs.py` limits concurrent jobs, and add a cap if not.
3. Later, if wanted: platformdirs data directory and a `hrrr-wind` entry point (desktop Stage 1), plus a CI matrix on macOS and Windows.
