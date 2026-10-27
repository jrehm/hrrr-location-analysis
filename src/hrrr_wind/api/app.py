"""FastAPI backend: a read-only JSON view of a study's results and cached wind data.

Run locally:  uvicorn hrrr_wind.api.app:app --reload
Set HRRR_WIND_READONLY=1 for a hosted demo (no write/download endpoints are ever exposed in
this module; the flag is reported to the UI so it can hide controls added later).
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hrrr_wind import __version__, ndbc, trash
from hrrr_wind.cache import box_cells, load_cache
from hrrr_wind.config import (_years_of, FIRST_YEAR, LOCKED_STUDIES, SLUG_RE, STUDIES_DIR, DefinitionError, buoy_caches, cache_plan,
                              cache_years, derive_season, load_study, set_years, study_dict, validate_definition, window_tag,
                              write_study)
from hrrr_wind.climatology import project_point
from hrrr_wind.jobs import JobConflict, JobError, JobManager
from hrrr_wind.stats import load_series, summarize, windrose_table

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
DOWNLOAD_EXT = {".csv", ".png", ".html", ".md", ".json"}
RESULT_FILES = {"summary": "summary_stats", "per_year": "per_year_stats",
                "band": "sensitivity_band", "quality": "data_quality",
                "validation": "validation_metrics", "adjusted": "bias_adjusted_summary"}

app = FastAPI(title="HRRR Wind Analysis", version=__version__)
MANAGER = JobManager()


CACHE_FILE_RE = re.compile(r"^cache_([a-z][a-z0-9]{0,11})_([A-Za-z0-9_]{1,60})\.npz$")
BUOY_DIR_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}$")


def is_readonly():
    return os.environ.get("HRRR_WIND_READONLY") == "1"


def require_writable():
    if is_readonly():
        raise HTTPException(403, "this server is read-only")


def study_paths():
    return {p.parent.name: p for p in sorted(STUDIES_DIR.glob("*/study.toml"))}


@lru_cache(maxsize=8)
def get_study(sid):
    paths = study_paths()
    if sid not in paths:
        raise HTTPException(404, f"unknown study '{sid}'")
    return load_study(paths[sid])


def records(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


def read_csv(study, name):
    path = study.out_dir / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else None


def check_venue(study, venue):
    if venue not in study.venues:
        raise HTTPException(404, f"unknown venue '{venue}'")
    return study.venues[venue]


def window_for(study, venue, season):
    for w in study.windows_for(venue):
        if w.season == season:
            return w
    raise HTTPException(404, f"no {season} window for {venue}")


FILES_PER_SECOND = 1.9                  # observed download rate, for estimates only


def is_stale(sid, s, summary):
    """Results older than the study's definition. Uses the fingerprint stored with the results (so a
    rename does not count); older outputs without one fall back to comparing file times."""
    state = s.out_dir / "analysis_state.json"
    if "pct_5_20" not in summary.read_text().split("\n", 1)[0]:
        return True                     # written before the 5-20 kt sweet spot: columns are missing
    if state.exists():
        try:
            return json.loads(state.read_text()).get("fingerprint") not in (s.fingerprint(), s.fingerprint(buoys=[]),
                                                                         s.fingerprint(buoys=s.buoys.values()))
        except ValueError:
            return True
    return study_paths()[sid].stat().st_mtime > summary.stat().st_mtime


def study_status(sid, s):
    """Where a study stands: no_data | partial | running | no_results | stale | ready.

    Includes what a download would still fetch (files, minutes) so the UI can say so up front.
    """
    plan = cache_plan(s)
    files = sum(len(g["years"]) * 24 * ((datetime.strptime(f"2001-{g['end']}", "%Y-%m-%d")
                                       - datetime.strptime(f"2001-{g['start']}", "%Y-%m-%d")).days + 1)
                for g in plan)
    summary = s.out_dir / "summary_stats.csv"
    job = MANAGER.running()
    job = job if job and job.study_id == sid else None
    have_any = any(s.has_data(w) for w in s.windows)
    if job:
        state = "running"
    elif plan:
        state = "partial" if have_any else "no_data"
    elif not summary.exists():
        state = "no_results"
    elif sid not in LOCKED_STUDIES and is_stale(sid, s, summary):
        state = "stale"
    else:
        state = "ready"
    return {"state": state, "missing_files": files, "missing_minutes": round(files / FILES_PER_SECOND / 60, 1),
            "job": job.public() if job else None}


@app.get("/api/studies")
def list_studies():
    out = []
    for sid in study_paths():
        s = get_study(sid)
        out.append({"id": sid, "name": s.name, "years": [min(s.years), max(s.years)],
                    "venues": [v.name for v in by_name(s.venues.values())], "locked": sid in LOCKED_STUDIES,
                    "state": study_status(sid, s)["state"]})
    return out


def list_caches(study):
    """Every wind cache in the study's output folder: venue, tag, size, years inside, and what uses it.

    Venue keys have no underscores, so cache_<venue>_<tag>.npz splits cleanly even for a venue that was
    removed from the study (``in_study`` false). ``used_by`` is "a window", "a buoy" or None.
    """
    win = {(w.venue, t) for w in study.windows for t in w.tags}
    buoy = {(b.venue, t) for b in study.buoys.values() for t in b.caches}
    out = []
    for p in sorted(study.out_dir.glob("cache_*.npz")) if study.out_dir.exists() else []:
        m = CACHE_FILE_RE.match(p.name)
        if not m:
            continue
        v, tag = m.groups()
        out.append({"file": p.name, "venue": v, "tag": tag, "mb": round(p.stat().st_size / 1e6, 1),
                    "years": sorted(_years_of(str(p), p.stat().st_mtime_ns)), "in_study": v in study.venues,
                    "used_by": "a window" if (v, tag) in win else "a buoy" if (v, tag) in buoy else None,
                    "used": (v, tag) in win})
    return out


def list_buoy_data(study):
    """Downloaded buoy observation folders under the study's own data/buoys, and whether a buoy uses each.

    A folder outside the study (HRRR_WIND_BUOY_DIR may share one) is never listed, so it is never offered for deletion.
    """
    root = study.buoy_dir
    if not root.is_dir() or study.root.resolve() not in root.resolve().parents:
        return []
    used = {b.dir for b in study.buoys.values()}
    return [{"dir": d.name, "files": sum(1 for f in d.iterdir() if f.is_file()),
             "mb": round(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6, 1), "used": d.name in used}
            for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith(".")]


def window_info(s, w):
    """Per-window data status: size, years on disk, years the study wants but lacks, years on disk but excluded."""
    present = s.present_tags(w)
    if not present:
        return None
    have = s.window_years(w)
    return {"mb": round(sum(s.cache_path(w.venue, t).stat().st_size for t in present) / 1e6, 1),
            "years": sorted(have), "missing_years": [y for y in s.years if y not in have],
            "excluded_years": sorted(have - set(s.years))}


def year_chips(s):
    """For the years editor: every selectable year, whether it is in the study, and how many windows hold it."""
    infos = [window_info(s, w) for w in s.windows]
    out = []
    for y in range(FIRST_YEAR, datetime.now().year + 1):
        out.append({"year": y, "in_study": y in s.years,
                    "on_disk": sum(1 for i in infos if i and y in i["years"]), "windows": len(s.windows)})
    return out


def by_name(venues):
    """Venues in alphabetical order of their names (case-insensitive), as every list in the UI shows them."""
    return sorted(venues, key=lambda v: v.name.casefold())


def sorted_windows(s):
    """Windows grouped by venue in alphabetical order, earliest dates first within a venue."""
    rank = {v.key: i for i, v in enumerate(by_name(s.venues.values()))}
    return sorted(s.windows, key=lambda w: (rank[w.venue], w.core))


@app.get("/api/studies/{sid}")
def study_meta(sid: str):
    s = get_study(sid)
    return {
        "id": sid, "name": s.name, "years": s.years, "race_label": s.race_label,
        "race_utc": [s.race_start, s.race_end], "utc_offset": s.utc_offset,
        "tz_abbr": s.tz_abbr, "readonly": is_readonly(), "caches": list_caches(s), "buoy_data": list_buoy_data(s),
        "locked": sid in LOCKED_STUDIES, "plan": cache_plan(s), "status": study_status(sid, s),
        "has_results": (s.out_dir / "summary_stats.csv").exists(),
        "venues": [{"key": v.key, "name": v.name, "lat": v.lat,
                    "lon": v.lon, "short": v.label, "bearing": v.bearing,
                    "utc_offset": s.offset_for(v.key), "tz_abbr": s.tz_for(v.key),
                    "offshore_nm": v.offshore_nm, "radius_nm": v.radius_nm}
                   for v in by_name(s.venues.values())],
        "windows": [{"venue": w.venue, "season": w.season, "core": list(w.core), "cache_tag": w.cache_tag,
                     "cache": window_info(s, w)} for w in sorted_windows(s)],
        "year_chips": year_chips(s),
        "pairs": [{"a": p.a, "b": p.b, "season": p.season} for p in s.pairs],
        "buoys": [{"venue": b.venue, "id": b.id, "lat": b.lat, "lon": b.lon, "anem_m": b.anem_m,
                   "years": ndbc.file_years(s.buoy_files(b.venue)), "files": len(s.buoy_files(b.venue)),
                   "mb": round(sum(f.stat().st_size for f in s.buoy_files(b.venue)) / 1e6, 2),
                   "sample_distance_nm": round(ndbc.bearing_distance(*s.sample_point(b.venue), b.lat, b.lon)[0], 1)}
                  for b in s.buoys.values()],
    }


def venue_grid(study, venue):
    """Lat/lon/land grid for a venue: from a wind cache if one exists, else a saved land mask, else None."""
    for w in study.windows_for(venue):
        for tag in study.present_tags(w):
            return load_cache(study.out_dir, venue, tag)
    mask = study.out_dir / f"landmask_{venue}.npz"
    return dict(np.load(mask)) if mask.exists() else None


@app.get("/api/studies/{sid}/geometry")
def geometry(sid: str, venue: str, bearing: float, offshore_nm: float = Query(gt=0, le=30),
             radius_nm: float = Query(4.0, gt=0, le=10)):
    """Club, projected sample point, averaging box and the grid cells around it."""
    s = get_study(sid)
    v = check_venue(s, venue)
    lat_c, lon_c = s.sample_point(venue, bearing=bearing, offshore_nm=offshore_nm)
    grid = venue_grid(s, venue)
    cells = box_cells(grid, lat_c, lon_c, radius_nm) if grid else []
    dlat = radius_nm / 60.0
    dlon = radius_nm / (60.0 * math.cos(math.radians(lat_c)))
    return {"club": {"lat": v.lat, "lon": v.lon, "name": v.name}, "has_grid": grid is not None,
            "sample": {"lat": lat_c, "lon": lon_c},
            "box": [[lat_c - dlat, lon_c - dlon], [lat_c + dlat, lon_c + dlon]],
            "cells": cells, "n_water": sum(c["water"] and c["in_box"] for c in cells)}


@app.get("/api/studies/{sid}/quick")
def quick_stats(sid: str, venue: str, season: str, bearing: float,
                offshore_nm: float = Query(gt=0, le=30), radius_nm: float = Query(4.0, gt=0, le=10)):
    """Core-window racing-hour statistics (no confidence intervals) for any sample point."""
    s = get_study(sid)
    check_venue(s, venue)
    w = window_for(s, venue, season)
    if not s.has_data(w):
        return {"n_cells": 0, "no_data": True}
    d = load_series(s, venue, w.tags, bearing=bearing, offshore_nm=offshore_nm,
                    radius_nm=radius_nm)
    if d is None:
        return {"n_cells": 0}
    r = d[(d["md"] >= w.lo) & (d["md"] <= w.hi) & d["hour"].isin(s.race_utc_for(venue))]
    st = summarize(r["spd_kt"], r["dir"])
    return {"n_cells": d.attrs["n_cells"], **{k: float(v) for k, v in st.items()}}


@app.get("/api/studies/{sid}/results")
def results(sid: str):
    """Everything the study produced, from its committed CSVs."""
    s = get_study(sid)
    out = {}
    for key, name in RESULT_FILES.items():
        df = read_csv(s, name)
        out[key] = records(df) if df is not None else []
    out["paired"] = []
    for p in s.pairs:
        df = read_csv(s, f"paired_{p.season}_{p.a}_minus_{p.b}")
        if df is not None:
            out["paired"].append({"a": p.a, "b": p.b, "season": p.season, "rows": records(df)})
    return out


@app.get("/api/studies/{sid}/windrose")
def windrose(sid: str, venue: str, season: str):
    s = get_study(sid)
    check_venue(s, venue)
    w = window_for(s, venue, season)
    if not s.has_data(w):
        return {"n": 0, "no_data": True}
    d = load_series(s, venue, w.tags)
    r = d[(d["md"] >= w.lo) & (d["md"] <= w.hi) & d["hour"].isin(s.race_utc_for(venue))]
    return windrose_table(r["spd_kt"], r["dir"])


@app.get("/api/studies/{sid}/diurnal")
def diurnal(sid: str):
    """Mean wind by local hour for each core window (all 24 hours)."""
    s = get_study(sid)
    out = []
    for w in s.windows:
        if not s.has_data(w):
            continue
        d = load_series(s, w.venue, w.tags)
        d = d[(d["md"] >= w.lo) & (d["md"] <= w.hi)]
        h = d.groupby("hour")["spd_kt"].mean()
        local = pd.Series(h.values, index=(h.index + s.offset_for(w.venue)) % 24).sort_index()
        out.append({"venue": w.venue, "season": w.season, "hours": local.index.tolist(),
                    "mean_kt": [float(x) for x in local.values]})
    return out


@app.get("/api/studies/{sid}/files")
def list_files(sid: str):
    s = get_study(sid)
    if not s.out_dir.exists():
        return []
    return sorted(({"name": p.name, "kb": round(p.stat().st_size / 1e3)} for p in s.out_dir.iterdir()
                   if p.is_file() and p.suffix in DOWNLOAD_EXT), key=lambda f: f["name"])


@app.get("/api/studies/{sid}/files/{name}")
def get_file(sid: str, name: str):
    s = get_study(sid)
    path = s.out_dir / name
    if Path(name).name != name or path.suffix not in DOWNLOAD_EXT or not path.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(path)


class NewStudy(BaseModel):
    slug: str
    definition: dict


class NewVenue(BaseModel):
    venue: dict
    windows: list[dict]


class Preview(BaseModel):
    lat: float
    lon: float
    bearing: float
    offshore_nm: float = Field(gt=0, le=30)
    radius_nm: float = Field(4.0, gt=0, le=10)


def preview_key(lat, lon):
    return f"{round(lat * 20) / 20:.2f}_{round(lon * 20) / 20:.2f}".replace("-", "m")


def preview_dir():
    return STUDIES_DIR / ".preview"        # not a study (no study.toml); holds land masks fetched for maps


def try_land_mask(out_dir, key, lat, lon):
    """Land mask for a position, fetched in a child process.

    The server must never import herbie/pyproj itself: once PROJ is loaded, a later fork() (starting
    a job) can segfault in PROJ's atfork handler on macOS and kill the whole server.
    """
    path = Path(out_dir) / f"landmask_{key}.npz"
    if not path.exists():
        cmd = [sys.executable, "-W", "ignore", "-m", "hrrr_wind.venue_analysis", "landmask",
               "--out", str(out_dir), "--key", key, "--lat", str(lat), "--lon", str(lon)]
        try:                                # no [download] extra, offline, archive hiccup: preview degrades
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
    return dict(np.load(path)) if path.exists() else None


@app.post("/api/preview/geometry")
def preview_geometry(req: Preview):
    """Map preview for a position that is not in any study yet (needs network once per area)."""
    require_writable()
    if not (21 <= req.lat <= 53 and -135 <= req.lon <= -60):
        raise HTTPException(422, "position is outside the HRRR (continental US) domain")
    lat_c, lon_c = project_point(req.lat, req.lon, req.bearing, req.offshore_nm)
    grid = try_land_mask(preview_dir(), preview_key(req.lat, req.lon), req.lat, req.lon)
    cells = box_cells(grid, lat_c, lon_c, req.radius_nm) if grid else []
    dlat = req.radius_nm / 60.0
    dlon = req.radius_nm / (60.0 * math.cos(math.radians(lat_c)))
    return {"club": {"lat": req.lat, "lon": req.lon}, "sample": {"lat": lat_c, "lon": lon_c},
            "box": [[lat_c - dlat, lon_c - dlon], [lat_c + dlat, lon_c + dlon]], "has_grid": grid is not None,
            "cells": cells, "n_water": sum(c["water"] and c["in_box"] for c in cells)}


def save_preview_masks(study, out_dir):
    """Copy any previewed land masks into a new study so its map works before the first download."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for v in study.venues.values():
        src = preview_dir() / f"landmask_{preview_key(v.lat, v.lon)}.npz"
        if src.exists():
            (out_dir / f"landmask_{v.key}.npz").write_bytes(src.read_bytes())


@app.post("/api/studies", status_code=201)
def create_study(req: NewStudy):
    """Create studies/<slug>/study.toml from a definition (never overwrites an existing study)."""
    require_writable()
    if not SLUG_RE.match(req.slug):
        raise HTTPException(422, "study id must be 2-40 lowercase letters, digits or underscores")
    path = STUDIES_DIR / req.slug / "study.toml"
    if path.parent.exists():
        raise HTTPException(409, f"study '{req.slug}' already exists")
    try:
        write_study(path, req.definition)
    except DefinitionError as e:
        raise HTTPException(422, str(e))
    get_study.cache_clear()
    study = get_study(req.slug)
    save_preview_masks(study, study.out_dir)
    return study_meta(req.slug)


def trash_error(e):
    return HTTPException(409 if e.conflict else 422, str(e))


class TrashStudy(BaseModel):
    name: str


@app.post("/api/studies/{sid}/trash")
def trash_study(sid: str, req: TrashStudy):
    """Move a whole study to the trash (restorable until the trash is emptied). The study's name must be typed."""
    require_writable()
    study = get_study(sid)
    if sid in LOCKED_STUDIES:
        raise HTTPException(403, f"study '{sid}' is the locked reference study and cannot be deleted")
    busy = MANAGER.running()
    if busy and busy.study_id == sid:
        raise HTTPException(409, "a job is running for this study; wait for it or cancel it first")
    if req.name != study.name:
        raise HTTPException(422, "type the study's name exactly to confirm")
    mb = trash.folder_mb(study_paths()[sid].parent)
    try:
        entry = trash.move_to_trash(STUDIES_DIR, sid)
    except trash.TrashError as e:
        raise trash_error(e)
    get_study.cache_clear()
    return {"trashed": entry, "mb": mb}


@app.get("/api/trash")
def list_trash():
    require_writable()
    return trash.list_trash(STUDIES_DIR)


@app.post("/api/trash/empty")
def empty_trash(req: dict):
    """Permanently delete everything in the trash. Needs {"confirm": "empty trash"}."""
    require_writable()
    if req.get("confirm") != "empty trash":
        raise HTTPException(422, 'send {"confirm": "empty trash"} to empty the trash')
    if MANAGER.running():
        raise HTTPException(409, "a job is running; wait for it or cancel it first")
    n, mb = trash.empty(STUDIES_DIR)
    return {"removed": n, "mb": mb}


@app.post("/api/trash/{entry}/restore")
def restore_study(entry: str):
    require_writable()
    try:
        sid = trash.restore(STUDIES_DIR, entry)
    except trash.TrashError as e:
        raise trash_error(e)
    get_study.cache_clear()
    return {"restored": sid}


@app.post("/api/studies/{sid}/venues", status_code=201)
def add_venue(sid: str, req: NewVenue):
    """Add a venue and its windows to a study; its other data is never touched (study.toml.bak kept)."""
    require_writable()
    study = get_study(sid)
    if sid in LOCKED_STUDIES:
        raise HTTPException(403, f"study '{sid}' is the locked reference study; copy it to extend it")
    try:
        d = study_dict(study_paths()[sid])
        years = validate_definition(d)["years"]
        d["venues"].append(req.venue)
        for w in req.windows:
            season = w.get("season") or derive_season(d["windows"], w.get("core"))
            d["windows"].append({**w, "season": season, "venue": req.venue.get("key"),
                                 "cache_tag": window_tag(season, years, req.venue.get("key"))})
        write_study(study_paths()[sid], d, backup=True)
    except DefinitionError as e:
        raise HTTPException(422, str(e))
    get_study.cache_clear()
    study = get_study(sid)
    save_preview_masks(study, study.out_dir)
    return study_meta(sid)


def baseline_state(sid, study):
    """Results made before fingerprints existed: record the pre-edit fingerprint, so an edit that does not
    change the analysis (a rename) does not make them look out of date."""
    summary, state = study.out_dir / "summary_stats.csv", study.out_dir / "analysis_state.json"
    if summary.exists() and not state.exists() and not is_stale(sid, study, summary):
        state.write_text(json.dumps({"fingerprint": study.fingerprint()}))


def edit_study(sid, mutate):
    """Apply an edit to a study's study.toml (validated, backed up); refused when read-only, locked or busy."""
    require_writable()
    study = get_study(sid)
    if sid in LOCKED_STUDIES:
        raise HTTPException(403, f"study '{sid}' is the locked reference study; copy it to change it")
    busy = MANAGER.running()
    if busy and busy.study_id == sid:
        raise HTTPException(409, "a job is running for this study; wait for it or cancel it first")
    path = study_paths()[sid]
    baseline_state(sid, study)
    try:
        d = study_dict(path)
        mutate(d, study)
        write_study(path, d, backup=True)
    except DefinitionError as e:
        raise HTTPException(422, str(e))
    get_study.cache_clear()
    return study_meta(sid)


def find_row(rows, **match):
    for r in rows:
        if all(r.get(k) == v for k, v in match.items()):
            return r
    raise HTTPException(404, "no such venue or window in this study")


class Rename(BaseModel):
    name: str


class VenuePatch(BaseModel):
    name: str | None = None
    short: str | None = None    # "" resets to the default (the key in capitals)
    utc_offset: int | None = None   # with tz_abbr: the venue's time zone (the same as the study's clears it)
    tz_abbr: str | None = None
    bearing: float | None = None
    offshore_nm: float | None = None
    radius_nm: float | None = None


class NewWindow(BaseModel):
    venue: str
    season: str | None = None    # internal id; derived from the dates when absent
    core: list[str]


class YearList(BaseModel):
    years: list[int]


@app.patch("/api/studies/{sid}")
def rename_study(sid: str, req: Rename):
    """Change the display name only; the folder id and URL stay the same."""
    return edit_study(sid, lambda d, s: d.update(name=req.name))


@app.patch("/api/studies/{sid}/venues/{key}")
def edit_venue(sid: str, key: str, req: VenuePatch):
    """Change a venue's name or sample point (not the club position, which defines the cache box)."""
    def mutate(d, study):
        v = find_row(d["venues"], key=key)
        old = v.get("bearing")
        if req.name is not None:
            v.update(name=req.name, lat=study.venues[key].lat, lon=study.venues[key].lon)
        if req.short is not None:
            if req.short.strip():
                v["short"] = req.short
            else:
                v.pop("short", None)
        if req.utc_offset is not None and req.tz_abbr:
            v["utc_offset"], v["tz_abbr"] = req.utc_offset, req.tz_abbr
        for k in ("bearing", "offshore_nm", "radius_nm"):
            if getattr(req, k) is not None:
                v[k] = getattr(req, k)
        if req.bearing is not None and v.get("sensitivity_bearings", [old]) == [old]:
            v["sensitivity_bearings"] = [req.bearing]
    return edit_study(sid, mutate)


@app.delete("/api/studies/{sid}/venues/{key}")
def remove_venue(sid: str, key: str):
    """Remove a venue with its windows, pairs and buoys from the study. Data on disk is kept."""
    def mutate(d, study):
        find_row(d["venues"], key=key)
        d["venues"] = [v for v in d["venues"] if v["key"] != key]
        d["windows"] = [w for w in d["windows"] if w["venue"] != key]
        d["pairs"] = [p for p in d.get("pairs", []) if key not in (p["a"], p["b"])]
        d["buoys"] = [b for b in d.get("buoys", []) if b["venue"] != key]
    return edit_study(sid, mutate)


@app.post("/api/studies/{sid}/windows", status_code=201)
def add_window(sid: str, req: NewWindow):
    def mutate(d, study):
        find_row(d["venues"], key=req.venue)
        season = req.season or derive_season(d["windows"], req.core)
        d["windows"].append({"venue": req.venue, "season": season, "core": req.core,
                             "cache_tag": window_tag(season, d["years"], req.venue)})
        set_years(d, d["years"], study.out_dir)          # a re-added window may need years its old cache lacks
    return edit_study(sid, mutate)


@app.delete("/api/studies/{sid}/windows/{venue}/{season}")
def remove_window(sid: str, venue: str, season: str):
    def mutate(d, study):
        find_row(d["windows"], venue=venue, season=season)
        d["windows"] = [w for w in d["windows"] if not (w["venue"] == venue and w["season"] == season)]
        d["pairs"] = [p for p in d.get("pairs", []) if not (p["season"] == season and venue in (p["a"], p["b"]))]
    return edit_study(sid, mutate)


@app.post("/api/studies/{sid}/years")
def edit_years(sid: str, req: YearList):
    """Set the study's years. New years are downloaded next; removed years stay on disk (excluded)."""
    return edit_study(sid, lambda d, study: set_years(d, req.years, study.out_dir))


BUOY_SEARCH_NM = 60.0


def stations_or_502():
    try:
        return ndbc.stations()
    except ConnectionError as e:
        raise HTTPException(502, str(e))


def archive_or_502():
    try:
        return ndbc.archive_years()
    except ConnectionError as e:
        raise HTTPException(502, str(e))


@app.get("/api/studies/{sid}/venues/{key}/buoys")
def nearby_buoys(sid: str, key: str, radius_nm: float = Query(BUOY_SEARCH_NM, gt=0, le=150)):
    """NDBC stations near a venue, each with whether the venue's HRRR download already covers it
    and, if not, how big an extra download would be."""
    require_writable()
    study = get_study(sid)
    if key not in study.venues:
        raise HTTPException(404, "no such venue")
    v = study.venues[key]
    out, archive = [], archive_or_502()
    for st in ndbc.stations_near(stations_or_502(), v.lat, v.lon, radius_nm):
        extra = [c for c in buoy_caches(study, key, st["id"], st["lat"], st["lon"]) if c["extra"]]
        files = sum(len(study.years) * 24 * ((datetime.strptime(f"2001-{c['end']}", "%Y-%m-%d")
                                              - datetime.strptime(f"2001-{c['start']}", "%Y-%m-%d")).days + 1) for c in extra)
        have = [y for y in archive.get(st["id"].lower(), []) if y in study.years]
        out.append({**st, "years": have, "covered": not extra, "extra_files": files,
                    "extra_minutes": round(files / FILES_PER_SECOND / 60, 1),
                    "anem_m": ndbc.KNOWN_ANEM_M.get(st["id"], ndbc.DEFAULT_ANEM_M),
                    "anem_known": st["id"] in ndbc.KNOWN_ANEM_M})
    return {"venue": {"key": key, "name": v.name, "lat": v.lat, "lon": v.lon}, "stations": out}


@app.get("/api/ndbc/{station}/anemometer")
def station_anemometer(station: str):
    """Anemometer height read from the station's NDBC page: {anem_m, source}; falls back to a typical value."""
    require_writable()
    if not ndbc.ID_RE.match(station):
        raise HTTPException(422, "bad station id")
    try:
        h = ndbc.anemometer_height(station)
    except ConnectionError:
        h = None
    if h is not None:
        return {"anem_m": h, "source": "page"}
    known = ndbc.KNOWN_ANEM_M.get(station)
    return {"anem_m": known or ndbc.DEFAULT_ANEM_M, "source": "known" if known else "default"}


class NewBuoy(BaseModel):
    venue: str
    id: str
    anem_m: float


@app.post("/api/studies/{sid}/buoys", status_code=202)
def set_buoy(sid: str, req: NewBuoy):
    """Give a venue a validation buoy (replacing any it had), then fetch its data and validate in a job."""
    require_writable()
    study = get_study(sid)
    if req.venue not in study.venues:
        raise HTTPException(404, "no such venue")
    st = next((x for x in stations_or_502() if x["id"] == req.id), None)
    if st is None:
        raise HTTPException(422, f"{req.id} is not an active NDBC station that reports wind")
    if not any(y in study.years for y in archive_or_502().get(st["id"].lower(), [])):
        raise HTTPException(422, f"NDBC has no archived observations for {st['id']} in this study's years")
    plan = buoy_caches(study, req.venue, st["id"], st["lat"], st["lon"])
    row = {"venue": req.venue, "id": st["id"], "lat": st["lat"], "lon": st["lon"], "anem_m": req.anem_m,
           "dir": ndbc.buoy_dir_name(st["id"]), "pattern": ndbc.buoy_pattern(st["id"]), "caches": [c["tag"] for c in plan]}
    edit_study(sid, lambda d, _s: d.__setitem__("buoys", [*(b for b in d.get("buoys", []) if b["venue"] != req.venue), row]))
    try:
        return MANAGER.submit(sid, get_study(sid), study_paths()[sid], "buoy", {"venue": req.venue}).public()
    except JobConflict as e:
        raise HTTPException(409, str(e))


def guard_data_delete(sid):
    """A data file may only be deleted from a writable, unlocked study with no job running on it."""
    require_writable()
    study = get_study(sid)
    if sid in LOCKED_STUDIES:
        raise HTTPException(403, f"study '{sid}' is the locked reference study; its data is kept")
    busy = MANAGER.running()
    if busy and busy.study_id == sid:
        raise HTTPException(409, "a job is running for this study; wait for it or cancel it first")
    return study


@app.delete("/api/studies/{sid}/caches/{name}")
def delete_cache(sid: str, name: str):
    """Delete a wind cache that no window or buoy uses (frees disk space; it can be downloaded again)."""
    study = guard_data_delete(sid)
    row = next((c for c in list_caches(study) if c["file"] == name), None)
    if row is None:
        raise HTTPException(404, "no such cache")
    if row["used_by"]:
        raise HTTPException(409, f"{name} is used by {row['used_by']}; remove that first")
    (study.out_dir / name).unlink()
    return {"deleted": name, "mb": row["mb"]}


@app.delete("/api/studies/{sid}/buoy-data/{name}")
def delete_buoy_data(sid: str, name: str):
    """Delete a downloaded buoy-observation folder that no buoy of the study uses."""
    study = guard_data_delete(sid)
    row = next((b for b in list_buoy_data(study) if b["dir"] == name and BUOY_DIR_RE.match(name)), None)
    if row is None:
        raise HTTPException(404, "no such buoy data folder")
    if row["used"]:
        raise HTTPException(409, f"{name} is used by a buoy; remove the buoy first")
    shutil.rmtree(study.buoy_dir / name)
    return {"deleted": name, "mb": row["mb"]}


@app.delete("/api/studies/{sid}/buoys/{venue}")
def remove_buoy(sid: str, venue: str):
    """Stop validating a venue against its buoy. Downloaded files stay on disk."""
    get_study(sid)
    return edit_study(sid, lambda d, _s: d.__setitem__("buoys", [b for b in d.get("buoys", []) if b["venue"] != venue]))


class JobRequest(BaseModel):
    kind: str
    params: dict = {}


@app.post("/api/studies/{sid}/jobs", status_code=202)
def submit_job(sid: str, req: JobRequest):
    """Start a download (kind=cache), or recompute the analysis or validation."""
    require_writable()
    study = get_study(sid)
    try:
        return MANAGER.submit(sid, study, study_paths()[sid], req.kind, req.params).public()
    except JobError as e:
        raise HTTPException(422, str(e))
    except JobConflict as e:
        raise HTTPException(409, str(e))


@app.get("/api/studies/{sid}/jobs")
def list_jobs(sid: str):
    get_study(sid)
    return [j.public() for j in MANAGER.list(sid)]


def find_job(jid):
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    return find_job(jid).public()


@app.get("/api/jobs/{jid}/log")
def job_log(jid: str, lines: int = Query(60, ge=1, le=500)):
    find_job(jid)
    return {"log": MANAGER.log_tail(jid, lines)}


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    require_writable()
    find_job(jid)
    return MANAGER.cancel(jid).public()


@app.get("/api/health")
def health():
    return {"ok": True, "readonly": is_readonly(), "version": __version__}


class RevalidatedStaticFiles(StaticFiles):
    """Static files that browsers must revalidate (ETag), so an edited .js/.css is never served stale."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", RevalidatedStaticFiles(directory=STATIC, html=True), name="static")
