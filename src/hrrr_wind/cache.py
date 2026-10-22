"""Download and read the gridded HRRR wind caches (u/v/land mask around each venue).

``build_cache`` is the only code that touches the network. Everything else in the package
works from the ``cache_<venue>_<tag>.npz`` files it writes.
"""
import gc
import logging
import math
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


def check_memory(limit_gb, where):
    """Abort cleanly (checkpoints survive) rather than let a run eat the machine."""
    gb = current_rss_gb()
    if gb > limit_gb:
        raise MemoryLimitExceeded(f"ABORT at {where}: RSS {gb:.1f} GB exceeds max-rss-gb {limit_gb}")


def fetch_wind(dates, source, max_threads=50):
    """Fetch u/v for `dates` (list of Timestamps); returns (valid_times, u_da, v_da) or None."""
    from herbie import FastHerbie
    FH = FastHerbie(dates, model="hrrr", product="sfc", fxx=[0], source=source,
                    max_threads=max_threads)
    if not FH.file_exists:
        return None
    ds = FH.xarray(clim.SEARCH_WIND, max_threads=max_threads)
    ds = ds[0] if isinstance(ds, list) else ds
    if "step" in ds.dims and ds.sizes["step"] == 1:
        ds = ds.isel(step=0)
    vt = pd.to_datetime(np.atleast_1d((ds["valid_time"] if "valid_time" in ds.coords
                                       else ds["time"]).values))
    u = ds["u10"] if "u10" in ds else ds["UGRD"]
    v = ds["v10"] if "v10" in ds else ds["VGRD"]
    return vt, u, v

def build_cache(out_dir, venues, years, tag, start, end, start_hour=0, end_hour=23,
                max_rss_gb=6.0, chunk_hours=72, progress=None):
    """Download hourly 10 m u/v around each venue and write cache_<venue>_<tag>.npz.

    Resumable (per-year checkpoints), memory-capped, retries missing hours on alternate
    mirrors, and writes missing_<tag>.json. ``start``/``end`` are "MM-DD". ``progress`` is an
    optional callback ``progress(year, chunk_index, n_chunks)`` for a UI.
    """
    import json
    from herbie import Herbie
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.strptime(start, "%m-%d").replace(year=2000)
    end = datetime.strptime(end, "%m-%d").replace(year=2000, hour=23)

    # Static grid + land mask from one reference file
    ref = Herbie(f"{years[-1]}-{start} 16:00", model="hrrr", product="sfc", fxx=0,
                 source="aws").xarray(":LAND:surface:")
    ref = ref[0] if isinstance(ref, list) else ref
    lat2d = ref["latitude"].values
    lon2d = clim.normalize_lon(ref["longitude"].values)
    land2d = ref[list(ref.data_vars)[0]].values

    slices = {k: club_xy_slices(lat2d, lon2d, clim.YACHT_CLUB_PRESETS[k]["lat"],
                                clim.YACHT_CLUB_PRESETS[k]["lon"], CACHE_HALF_WIDTH_NM)
              for k in venues}
    ckpt_dir = out_dir / f"ckpt_{tag}"
    ckpt_dir.mkdir(exist_ok=True)
    missing_by_year = {}
    per_year = {k: [] for k in venues}      # venue -> list of (time, u, v) per year

    for year in years:
        ck = ckpt_dir / f"year_{year}.npz"
        if ck.exists():                             # resume: reuse finished years
            z = np.load(ck, allow_pickle=True)
            for key in venues:
                per_year[key].append((z[f"{key}_time"], z[f"{key}_u"], z[f"{key}_v"]))
            missing_by_year[year] = list(z["missing"])
            logger.info(f"year {year}: loaded checkpoint ({len(missing_by_year[year])} missing)")
            continue
        ranges = clim.build_date_ranges(start, end, [year], "1h", start_hour,
                                        end_hour, min_date=clim.HRRR_START_DATE)
        if not ranges:
            logger.warning(f"year {year}: window precedes HRRR archive, skipped")
            continue
        dr = ranges[0][0]
        yr = {key: {"t": [], "u": [], "v": []} for key in venues}

        def keep(vt, u, v):
            # np.array(..., copy=True) is essential: a bare isel(...).values is a VIEW
            # that pins the whole full-CONUS parent array in memory.
            for key in venues:
                ys, xs = slices[key]
                n = len(vt)
                yr[key]["t"].append(np.array(vt.values.astype("datetime64[ns]")))
                yr[key]["u"].append(np.array(u.isel(y=ys, x=xs).values, dtype="float32",
                                             copy=True).reshape(n, ys.stop - ys.start, -1))
                yr[key]["v"].append(np.array(v.isel(y=ys, x=xs).values, dtype="float32",
                                             copy=True).reshape(n, ys.stop - ys.start, -1))

        got = set()
        n_chunks = -(-len(dr) // chunk_hours)
        for i in range(0, len(dr), chunk_hours):
            if progress:
                progress(year, i // chunk_hours, n_chunks)
            chunk = dr[i:i + chunk_hours]
            try:
                res = fetch_wind(chunk.tolist(), "aws")
            except Exception as e:
                logger.error(f"year {year} chunk {i}: {e}")
                continue
            if res is None:
                continue
            vt, u, v = res
            keep(vt, u, v)
            got |= set(vt)
            del res, vt, u, v
            gc.collect()
            check_memory(max_rss_gb, f"year {year} chunk {i}")
        miss = [t for t in dr if t not in got]
        # Retry missing timestamps one by one on alternate sources
        for t in list(miss):
            for src in ("aws", "google", "azure"):
                try:
                    res = fetch_wind([t], src)
                except Exception:
                    res = None
                if res is not None:
                    keep(*res)
                    got |= set(res[0])
                    miss.remove(t)
                    logger.info(f"year {year}: recovered {t} from {src}")
                    del res
                    break
            gc.collect()
            check_memory(max_rss_gb, f"year {year} retry {t}")
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


def load_cache(out_dir, venue, tag):
    """Load cache_<venue>_<tag>.npz as a dict of arrays (time, u, v, lat, lon, land)."""
    return dict(np.load(Path(out_dir) / f"cache_{venue}_{tag}.npz"))
