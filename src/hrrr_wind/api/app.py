"""FastAPI backend: a read-only JSON view of a study's results and cached wind data.

Run locally:  uvicorn hrrr_wind.api.app:app --reload
Set HRRR_WIND_READONLY=1 for a hosted demo (no write/download endpoints are ever exposed in
this module; the flag is reported to the UI so it can hide controls added later).
"""
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from hrrr_wind.cache import box_cells, load_cache
from hrrr_wind.config import REPO_ROOT, load_study
from hrrr_wind.stats import load_series, summarize, windrose_table

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
DOWNLOAD_EXT = {".csv", ".png", ".html", ".md", ".json"}
RESULT_FILES = {"summary": "summary_stats", "per_year": "per_year_stats",
                "band": "sensitivity_band", "quality": "data_quality",
                "validation": "validation_metrics", "adjusted": "bias_adjusted_summary"}

app = FastAPI(title="HRRR Wind Analysis", version="0.1")


def study_paths():
    return {p.parent.name: p for p in sorted((REPO_ROOT / "studies").glob("*/study.toml"))}


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


@app.get("/api/studies")
def list_studies():
    return [{"id": sid, "name": get_study(sid).name} for sid in study_paths()]


@app.get("/api/studies/{sid}")
def study_meta(sid: str):
    s = get_study(sid)
    return {
        "id": sid, "name": s.name, "years": s.years, "race_label": s.race_label,
        "race_utc": [s.race_start, s.race_end], "utc_offset": s.utc_offset,
        "tz_abbr": s.tz_abbr, "readonly": os.environ.get("HRRR_WIND_READONLY") == "1",
        "venues": [{"key": v.key, "name": v.name, "lat": v.preset["lat"],
                    "lon": v.preset["lon"], "bearing": v.bearing,
                    "offshore_nm": v.offshore_nm, "radius_nm": v.radius_nm}
                   for v in s.venues.values()],
        "windows": [{"venue": w.venue, "season": w.season, "core": list(w.core)}
                    for w in s.windows],
        "pairs": [{"a": p.a, "b": p.b, "season": p.season} for p in s.pairs],
        "buoys": [{"venue": b.venue, "id": b.id, "lat": b.lat, "lon": b.lon}
                  for b in s.buoys.values()],
    }


@app.get("/api/studies/{sid}/geometry")
def geometry(sid: str, venue: str, bearing: float, offshore_nm: float = Query(gt=0, le=30),
             radius_nm: float = Query(4.0, gt=0, le=10)):
    """Club, projected sample point, averaging box and the grid cells around it."""
    s = get_study(sid)
    v = check_venue(s, venue)
    lat_c, lon_c = s.sample_point(venue, bearing=bearing, offshore_nm=offshore_nm)
    tag = s.windows_for(venue)[0].cache_tag
    cells = box_cells(load_cache(s.out_dir, venue, tag), lat_c, lon_c, radius_nm)
    dlat = radius_nm / 60.0
    dlon = radius_nm / (60.0 * math.cos(math.radians(lat_c)))
    return {"club": {"lat": v.preset["lat"], "lon": v.preset["lon"], "name": v.name},
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
    d = load_series(s, venue, w.cache_tag, bearing=bearing, offshore_nm=offshore_nm,
                    radius_nm=radius_nm)
    if d is None:
        return {"n_cells": 0}
    r = d[(d["md"] >= w.lo) & (d["md"] <= w.hi) & d["hour"].isin(s.race_utc)]
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
    d = load_series(s, venue, w.cache_tag)
    r = d[(d["md"] >= w.lo) & (d["md"] <= w.hi) & d["hour"].isin(s.race_utc)]
    return windrose_table(r["spd_kt"], r["dir"])


@app.get("/api/studies/{sid}/diurnal")
def diurnal(sid: str):
    """Mean wind by local hour for each core window (all 24 hours)."""
    s = get_study(sid)
    out = []
    for w in s.windows:
        d = load_series(s, w.venue, w.cache_tag)
        d = d[(d["md"] >= w.lo) & (d["md"] <= w.hi)]
        h = d.groupby("hour")["spd_kt"].mean()
        local = pd.Series(h.values, index=(h.index + s.utc_offset) % 24).sort_index()
        out.append({"venue": w.venue, "season": w.season, "hours": local.index.tolist(),
                    "mean_kt": [float(x) for x in local.values]})
    return out


@app.get("/api/studies/{sid}/files")
def list_files(sid: str):
    s = get_study(sid)
    if not s.out_dir.exists():
        return []
    return sorted(p.name for p in s.out_dir.iterdir()
                  if p.is_file() and p.suffix in DOWNLOAD_EXT)


@app.get("/api/studies/{sid}/files/{name}")
def get_file(sid: str, name: str):
    s = get_study(sid)
    path = s.out_dir / name
    if Path(name).name != name or path.suffix not in DOWNLOAD_EXT or not path.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(path)


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
