"""Download and read the gridded HRRR wind caches (u/v/land mask around each venue).

``build_cache`` is the only code that touches the network. Everything else in the package
works from the ``cache_<venue>_<tag>.npz`` files it writes.
"""
import gc
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from hrrr_wind import climatology as clim
from hrrr_wind.config import CACHE_HALF_WIDTH_NM, KT

logger = logging.getLogger("hrrr_wind.cache")


def club_xy_slices(lat2d, lon2d, lat0, lon0, half_nm):
    """Index slices (y, x) of the grid covering +/- half_nm around a point."""
    dy = (lat2d - lat0) * 60.0
    dx = (lon2d - lon0) * 60.0 * math.cos(math.radians(lat0))
    inside = (np.abs(dy) <= half_nm) & (np.abs(dx) <= half_nm)
    ys, xs = np.where(inside)
    return slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1)

def current_rss_gb():
    import os
    import subprocess
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]).split()[0]) / 1e6

class MemoryLimitExceeded(RuntimeError):
    """Raised when a download exceeds its resident-memory cap (checkpoints survive)."""


NET_TIMEOUT_S = 45            # no socket may wait longer than this (a dead link must not hang a run)
CHUNK_ATTEMPTS = 3            # tries per chunk before the failure counts as a network problem
RETRY_PAUSE_S = (5, 20)       # pauses between those tries


class NetworkTrouble(RuntimeError):
    """Downloads kept failing with errors (not just absent files); nothing was saved for the year."""


def fetch_with_retry(dates, source, slices, attempts=CHUNK_ATTEMPTS, pause=None):
    """fetch_wind with a few retries on exceptions. Returns (result, failed): result None with
    failed False means the files are absent from the archive; failed True means errors (network)."""
    pause = RETRY_PAUSE_S if pause is None else pause
    for i in range(attempts):
        try:
            return fetch_wind(dates, source, slices), False
        except Exception as e:
            logger.error(f"fetch {len(dates)} hours from {source} failed (try {i + 1}/{attempts}): {e}")
            if i + 1 < attempts:
                time.sleep(pause[min(i, len(pause) - 1)])
    return None, True


def check_memory(limit_gb, where):
    """Abort cleanly (checkpoints survive) rather than let a run eat the machine."""
    gb = current_rss_gb()
    if gb > limit_gb:
        raise MemoryLimitExceeded(f"ABORT at {where}: RSS {gb:.1f} GB exceeds max-rss-gb {limit_gb}")


def _read_cropped(H, slices):
    """Decode one hour's u/v and keep only each venue's box; returns (valid_time, {key: (u, v)})."""
    ds = H.xarray(clim.SEARCH_WIND)
    ds = ds[0] if isinstance(ds, list) else ds
    vt = pd.Timestamp((ds["valid_time"] if "valid_time" in ds.coords else ds["time"]).values.item())
    u = ds["u10"] if "u10" in ds else ds["UGRD"]
    v = ds["v10"] if "v10" in ds else ds["VGRD"]
    # np.array(..., copy=True) is essential: a bare isel(...).values is a VIEW that pins the
    # whole full-CONUS parent array in memory.
    return vt, {key: (np.array(u.isel(y=ys, x=xs).values, dtype="float32", copy=True),
                      np.array(v.isel(y=ys, x=xs).values, dtype="float32", copy=True))
                for key, (ys, xs) in slices.items()}


def fetch_wind(dates, source, slices, max_threads=50):
    """Fetch u/v for `dates` (list of Timestamps), cropped per venue as soon as each file is decoded.

    ``slices`` maps venue key -> (y slice, x slice). Returns (valid_times, {key: (u, v)}) with
    u/v shaped (n, ny, nx) and times ascending, or None if no file exists. Cropping per file
    avoids ever holding a full-CONUS stack of the whole chunk.
    """
    from concurrent.futures import ThreadPoolExecutor
    from herbie import FastHerbie
    FH = FastHerbie(dates, model="hrrr", product="sfc", fxx=[0], source=source,
                    max_threads=max_threads)
    files = FH.file_exists
    if not files:
        return None
    with ThreadPoolExecutor(min(len(files), max_threads)) as exe:
        hours = sorted(exe.map(lambda H: _read_cropped(H, slices), files), key=lambda r: r[0])
    vt = pd.DatetimeIndex([h[0] for h in hours])
    return vt, {key: (np.stack([h[1][key][0] for h in hours]), np.stack([h[1][key][1] for h in hours]))
                for key in slices}

def build_cache(out_dir, venues, years, tag, start, end, start_hour=0, end_hour=23,
                max_rss_gb=6.0, chunk_hours=72, progress=None, clubs=None):
    """Download hourly 10 m u/v around each venue and write cache_<venue>_<tag>.npz.

    Resumable (per-year checkpoints), memory-capped, retries missing hours on alternate
    mirrors, and writes missing_<tag>.json. ``start``/``end`` are "MM-DD". ``progress`` is an
    optional callback ``progress(year, chunk_index, n_chunks)`` for a UI. ``clubs`` maps venue
    key -> (lat, lon); venues not in it use the built-in presets.
    """
    import json
    import socket
    from herbie import Herbie
    socket.setdefaulttimeout(NET_TIMEOUT_S)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start_dt = datetime.strptime(f"2000-{start}", "%Y-%m-%d")
    end_dt = datetime.strptime(f"2000-{end}", "%Y-%m-%d").replace(hour=23)

    # Static grid + land mask from one reference file
    ref = Herbie(f"{years[-1]}-{start} 16:00", model="hrrr", product="sfc", fxx=0,
                 source="aws").xarray(":LAND:surface:")
    ref = ref[0] if isinstance(ref, list) else ref
    lat2d = ref["latitude"].values
    lon2d = clim.normalize_lon(ref["longitude"].values)
    land2d = ref[list(ref.data_vars)[0]].values

    if all((out_dir / f"cache_{k}_{tag}.npz").exists() for k in venues):
        logger.info(f"caches for tag {tag} already exist; nothing to do")   # never overwrite a finished cache
        return
    clubs = clubs or {}
    slices = {k: club_xy_slices(lat2d, lon2d, *(clubs.get(k) or (clim.YACHT_CLUB_PRESETS[k]["lat"],
                                                                 clim.YACHT_CLUB_PRESETS[k]["lon"])),
                                CACHE_HALF_WIDTH_NM)
              for k in venues}
    ckpt_dir = out_dir / f"ckpt_{tag}"
    ckpt_dir.mkdir(exist_ok=True)
    missing_by_year = {}
    per_year = {k: [] for k in venues}      # venue -> list of (time, u, v) per year

    for year in years:
        ck = ckpt_dir / f"year_{year}.npz"
        if ck.exists():                             # resume: reuse finished years
            z = np.load(ck, allow_pickle=True)
            absent = [key for key in venues if f"{key}_time" not in z.files]
            if absent:
                raise RuntimeError(f"checkpoint {ck} has no data for {absent}; use a new tag for new venues")
            for key in venues:
                per_year[key].append((z[f"{key}_time"], z[f"{key}_u"], z[f"{key}_v"]))
            missing_by_year[year] = list(z["missing"])
            logger.info(f"year {year}: loaded checkpoint ({len(missing_by_year[year])} missing)")
            continue
        ranges = clim.build_date_ranges(start_dt, end_dt, [year], "1h", start_hour,
                                        end_hour, min_date=clim.HRRR_START_DATE)
        if not ranges:
            logger.warning(f"year {year}: window precedes HRRR archive, skipped")
            continue
        dr = ranges[0][0]
        yr = {key: {"t": [], "u": [], "v": []} for key in venues}

        def keep(vt, boxes):
            for key in venues:
                yr[key]["t"].append(np.array(vt.values.astype("datetime64[ns]")))
                yr[key]["u"].append(boxes[key][0])
                yr[key]["v"].append(boxes[key][1])

        got = set()
        net_errors = 0
        n_chunks = -(-len(dr) // chunk_hours)
        starts = list(range(0, len(dr), chunk_hours))
        # One chunk is fetched ahead on a worker thread, so the network is busy while the main
        # thread stores the previous chunk.
        with ThreadPoolExecutor(1) as prefetch:
            def submit(i):
                return prefetch.submit(fetch_with_retry, dr[i:i + chunk_hours].tolist(), "aws", slices)
            pending = submit(starts[0]) if starts else None
            for n, i in enumerate(starts):
                if progress:
                    progress(year, n, n_chunks)
                res, failed = pending.result()
                pending = submit(starts[n + 1]) if n + 1 < len(starts) else None
                net_errors += failed
                if res is None:
                    continue
                vt, boxes = res
                keep(vt, boxes)
                got |= set(vt)
                del res, vt, boxes
                gc.collect()
                check_memory(max_rss_gb, f"year {year} chunk {i}")
        if net_errors:                  # don't grind through per-hour retries on a dead link
            raise NetworkTrouble(f"year {year}: {net_errors} chunk(s) failed after {CHUNK_ATTEMPTS} tries, "
                                 f"not saved; check the connection and run again (finished years are kept)")
        miss = [t for t in dr if t not in got]
        # Retry missing timestamps one by one on alternate sources
        for t in list(miss):
            for src in ("aws", "google", "azure"):
                res, failed = fetch_with_retry([t], src, slices, attempts=1)
                net_errors += failed
                if res is not None:
                    keep(*res)
                    got |= set(res[0])
                    miss.remove(t)
                    logger.info(f"year {year}: recovered {t} from {src}")
                    del res
                    break
            gc.collect()
            check_memory(max_rss_gb, f"year {year} retry {t}")
        if net_errors:
            raise NetworkTrouble(f"year {year}: {net_errors} download error(s), not saved; "
                                 f"check the connection and run again (finished years are kept)")
        missing_by_year[year] = [t.isoformat() for t in miss]

        payload = {"missing": np.array(missing_by_year[year], dtype=object)}
        for key in venues:
            if not yr[key]["t"]:
                tt = np.array([], dtype="datetime64[ns]")
                ys, xs = slices[key]
                uu = vv = np.zeros((0, ys.stop - ys.start, xs.stop - xs.start), "float32")
            else:
                tt = np.concatenate(yr[key]["t"])
                uu = np.concatenate(yr[key]["u"])
                vv = np.concatenate(yr[key]["v"])
            payload[f"{key}_time"], payload[f"{key}_u"], payload[f"{key}_v"] = tt, uu, vv
            per_year[key].append((tt, uu, vv))
        np.savez_compressed(ck, **payload)
        logger.info(f"year {year}: retrieved {len(dr) - len(miss)}/{len(dr)}; "
                    f"missing {len(miss)}; checkpoint saved; rss={current_rss_gb():.1f} GB")

    for key in venues:
        ys, xs = slices[key]
        t = np.concatenate([p[0] for p in per_year[key]])
        order = np.argsort(t)
        np.savez_compressed(
            out_dir / f"cache_{key}_{tag}.npz",
            time=t[order],
            u=np.concatenate([p[1] for p in per_year[key]])[order],
            v=np.concatenate([p[2] for p in per_year[key]])[order],
            lat=lat2d[ys, xs], lon=lon2d[ys, xs], land=land2d[ys, xs],
        )
        logger.info(f"saved cache for {key}: {len(t)} times")
    with open(out_dir / f"missing_{tag}.json", "w") as f:
        json.dump(missing_by_year, f, indent=2)
    shutil.rmtree(ckpt_dir)         # the finished caches hold the same data; checkpoints only matter mid-run

def fetch_land_mask(out_dir, key, lat, lon, year=2024):
    """Grid + land mask around a club from one HRRR file, cached as landmask_<key>.npz.

    Lets the new-study map preview show water and land before any wind has been downloaded.
    Needs the ``download`` extra. Returns a dict(lat, lon, land) usable by ``box_cells``.
    """
    path = Path(out_dir) / f"landmask_{key}.npz"
    if path.exists():
        return dict(np.load(path))
    from herbie import Herbie
    ref = Herbie(f"{year}-09-10 16:00", model="hrrr", product="sfc", fxx=0,
                 source="aws").xarray(":LAND:surface:")
    ref = ref[0] if isinstance(ref, list) else ref
    lat2d = ref["latitude"].values
    lon2d = clim.normalize_lon(ref["longitude"].values)
    ys, xs = club_xy_slices(lat2d, lon2d, lat, lon, CACHE_HALF_WIDTH_NM)
    mask = {"lat": np.array(lat2d[ys, xs]), "lon": np.array(lon2d[ys, xs]),
            "land": np.array(ref[list(ref.data_vars)[0]].values[ys, xs])}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **mask)
    return mask


def box_series(cache, lat_c, lon_c, radius_nm, water_only=True, nearest_only=False):
    """Mean u/v over water cells within radius of (lat_c, lon_c); returns DataFrame."""
    lat, lon, land = cache["lat"], cache["lon"], cache["land"]
    dy = (lat - lat_c) * 60.0
    dx = (lon - lon_c) * 60.0 * math.cos(math.radians(lat_c))
    dist = np.hypot(dx, dy)
    sel = (np.abs(dx) <= radius_nm) & (np.abs(dy) <= radius_nm)
    if water_only:
        sel &= land < 0.5
    if nearest_only:
        d = np.where(land < 0.5, dist, np.inf)
        sel = d == d.min()
    n = int(sel.sum())
    if n == 0:
        return None, 0
    u = cache["u"][:, sel].mean(axis=1)
    v = cache["v"][:, sel].mean(axis=1)
    spd = np.hypot(u, v) * KT
    return pd.DataFrame({"time": cache["time"], "spd_kt": spd,
                         "dir": (np.degrees(np.arctan2(-u, -v))) % 360}), n


def box_cells(cache, lat_c, lon_c, radius_nm, context_nm=3.0):
    """Grid cells near a sample point, for drawing on a map.

    Returns dicts {lat, lon, water, in_box}: every cell within radius+context_nm, flagged
    ``in_box`` when inside the averaging box and ``water`` from the land mask.
    """
    lat, lon, land = cache["lat"], cache["lon"], cache["land"]
    dy = (lat - lat_c) * 60.0
    dx = (lon - lon_c) * 60.0 * math.cos(math.radians(lat_c))
    reach = radius_nm + context_nm
    near = (np.abs(dx) <= reach) & (np.abs(dy) <= reach)
    in_box = (np.abs(dx) <= radius_nm) & (np.abs(dy) <= radius_nm)
    return [{"lat": float(lat[i, j]), "lon": float(lon[i, j]), "water": bool(land[i, j] < 0.5),
             "in_box": bool(in_box[i, j])} for i, j in zip(*np.where(near))]


def load_cache(out_dir, venue, tag):
    """Load cache_<venue>_<tag>.npz as a dict of arrays (time, u, v, lat, lon, land)."""
    return dict(np.load(Path(out_dir) / f"cache_{venue}_{tag}.npz"))
