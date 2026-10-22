#!/usr/bin/env python
"""
GTYC / HYC venue wind analysis driver (uses hrrr_wind.climatology).

Subcommands:
  cache        Download 10 m wind once and save a +/-CACHE_NM box of raw grid cells
               (u, v, lat, lon, water mask) per venue, so any sample-point /
               radius combination can be evaluated offline.
  sensitivity  Evaluate offshore-distance x radius x bearing combinations from
               the cache and write a summary CSV.

Cache files:   <out>/cache_<venue>_<tag>.npz
"""
import argparse
import gc
import logging
import os
import math
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hrrr_wind import climatology as clim
logger = logging.getLogger("venue_analysis")

# Defaults point at the bundled GTYC/HYC study; override with HRRR_WIND_OUT / HRRR_WIND_BUOY_DIR
REPO_ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = REPO_ROOT / "studies" / "gtyc_hyc_2028"
OUT_DIR = Path(os.environ.get("HRRR_WIND_OUT", STUDY_DIR / "outputs"))
CACHE_NM = 18.0           # half-width of the cached box around the club
KT = 1.9438445

# Venue definitions used by the analysis (club coords from the v1.2 presets)
VENUES = {"gtyc": {"bearings": [0, 20, 40]},
          "hyc": {"bearings": [300, 315, 330, 345]}}
OFFSHORE_NM = [1.0, 2.0, 3.0, 4.0, 6.0]
RADIUS_NM = [2.0, 4.0, 6.0]


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


def check_memory(limit_gb, where):
    """Abort cleanly (checkpoints survive) rather than let a run eat the machine."""
    gb = current_rss_gb()
    if gb > limit_gb:
        raise SystemExit(f"ABORT at {where}: RSS {gb:.1f} GB exceeds --max-rss-gb {limit_gb}")


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


def cache_command(args):
    import json
    from herbie import Herbie
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = datetime.strptime(args.start, "%m-%d").replace(year=2000)
    end = datetime.strptime(args.end, "%m-%d").replace(year=2000, hour=23)

    # Static grid + land mask from one reference file
    ref = Herbie(f"{args.years[-1]}-{args.start} 16:00", model="hrrr", product="sfc", fxx=0,
                 source="aws").xarray(":LAND:surface:")
    ref = ref[0] if isinstance(ref, list) else ref
    lat2d = ref["latitude"].values
    lon2d = clim.normalize_lon(ref["longitude"].values)
    land2d = ref[list(ref.data_vars)[0]].values

    slices = {k: club_xy_slices(lat2d, lon2d, clim.YACHT_CLUB_PRESETS[k]["lat"],
                                clim.YACHT_CLUB_PRESETS[k]["lon"], CACHE_NM)
              for k in args.venues}
    ckpt_dir = OUT_DIR / f"ckpt_{args.tag}"
    ckpt_dir.mkdir(exist_ok=True)
    missing_by_year = {}
    per_year = {k: [] for k in args.venues}      # venue -> list of (time, u, v) per year

    for year in args.years:
        ck = ckpt_dir / f"year_{year}.npz"
        if ck.exists():                             # resume: reuse finished years
            z = np.load(ck, allow_pickle=True)
            for key in args.venues:
                per_year[key].append((z[f"{key}_time"], z[f"{key}_u"], z[f"{key}_v"]))
            missing_by_year[year] = list(z["missing"])
            logger.info(f"year {year}: loaded checkpoint ({len(missing_by_year[year])} missing)")
            continue
        ranges = clim.build_date_ranges(start, end, [year], "1h", args.start_hour,
                                        args.end_hour, min_date=clim.HRRR_START_DATE)
        if not ranges:
            logger.warning(f"year {year}: window precedes HRRR archive, skipped")
            continue
        dr = ranges[0][0]
        yr = {key: {"t": [], "u": [], "v": []} for key in args.venues}

        def keep(vt, u, v):
            # np.array(..., copy=True) is essential: a bare isel(...).values is a VIEW
            # that pins the whole full-CONUS parent array in memory.
            for key in args.venues:
                ys, xs = slices[key]
                n = len(vt)
                yr[key]["t"].append(np.array(vt.values.astype("datetime64[ns]")))
                yr[key]["u"].append(np.array(u.isel(y=ys, x=xs).values, dtype="float32",
                                             copy=True).reshape(n, ys.stop - ys.start, -1))
                yr[key]["v"].append(np.array(v.isel(y=ys, x=xs).values, dtype="float32",
                                             copy=True).reshape(n, ys.stop - ys.start, -1))

        got = set()
        for i in range(0, len(dr), args.chunk_hours):
            chunk = dr[i:i + args.chunk_hours]
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
            check_memory(args.max_rss_gb, f"year {year} chunk {i}")
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
            check_memory(args.max_rss_gb, f"year {year} retry {t}")
        missing_by_year[year] = [t.isoformat() for t in miss]

        payload = {"missing": np.array(missing_by_year[year], dtype=object)}
        for key in args.venues:
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

    for key in args.venues:
        ys, xs = slices[key]
        t = np.concatenate([p[0] for p in per_year[key]])
        order = np.argsort(t)
        np.savez_compressed(
            OUT_DIR / f"cache_{key}_{args.tag}.npz",
            time=t[order],
            u=np.concatenate([p[1] for p in per_year[key]])[order],
            v=np.concatenate([p[2] for p in per_year[key]])[order],
            lat=lat2d[ys, xs], lon=lon2d[ys, xs], land=land2d[ys, xs],
        )
        logger.info(f"saved cache for {key}: {len(t)} times")
    with open(OUT_DIR / f"missing_{args.tag}.json", "w") as f:
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


def sensitivity_command(args):
    rows = []
    for key in args.venues:
        cache = dict(np.load(OUT_DIR / f"cache_{key}_{args.tag}.npz"))
        p = clim.YACHT_CLUB_PRESETS[key]
        for brg in VENUES[key]["bearings"]:
            for off in OFFSHORE_NM:
                lat_c, lon_c = clim.project_point(p["lat"], p["lon"], brg, off)
                combos = [(r, False) for r in RADIUS_NM] + [(RADIUS_NM[0], True)]
                for rad, nearest in combos:
                    df, n = box_series(cache, lat_c, lon_c, rad, nearest_only=nearest)
                    if df is None:
                        rows.append({"venue": key, "bearing": brg, "offshore_nm": off,
                                     "radius_nm": "nearest" if nearest else rad,
                                     "n_cells": 0})
                        continue
                    s = df["spd_kt"]
                    rows.append({
                        "venue": key, "bearing": brg, "offshore_nm": off,
                        "radius_nm": "nearest" if nearest else rad, "n_cells": n,
                        "n_obs": len(df), "mean_kt": s.mean(), "median_kt": s.median(),
                        "p90_kt": s.quantile(0.9),
                        "pct_lt5": 100 * (s < 5).mean(),
                        "pct_5_15": 100 * ((s >= 5) & (s < 15)).mean(),
                        "pct_ge15": 100 * (s >= 15).mean(),
                    })
    out = pd.DataFrame(rows)
    path = OUT_DIR / f"sensitivity_{args.tag}.csv"
    out.to_csv(path, index=False)
    logger.info(f"saved {path} ({len(out)} rows)")
    pd.set_option("display.width", 200)
    print(out.round(1).to_string(index=False))


# ---------------------------------------------------------------------------
# Analysis (statistics, uncertainty, figures)
# ---------------------------------------------------------------------------
PRIMARY = {"gtyc": {"bearing": 20, "offshore_nm": 3.0, "radius_nm": 4.0},
           "hyc": {"bearing": 330, "offshore_nm": 2.0, "radius_nm": 4.0}}
# (venue, season tag, cache tag, core MM-DD range, buffer days)
WINDOWS = [("gtyc", "sep", "sep_2015_2025", ("09-08", "09-14")),
           ("hyc", "sep", "sep_2015_2025", ("09-08", "09-14")),
           ("hyc", "jun", "jun_2015_2025", ("06-14", "06-21"))]
RACE_UTC = range(14, 21)   # 10 AM-4 PM EDT
BUFFER_DAYS = 3
B_BOOT = 2000


def md_key(t):
    return t.month * 100 + t.day


def load_series(venue, cache_tag, bearing=None, offshore_nm=None, radius_nm=None):
    """Hourly speed/direction at the primary (or overridden) sample point."""
    prm = dict(PRIMARY[venue])
    if bearing is not None:
        prm["bearing"] = bearing
    if offshore_nm is not None:
        prm["offshore_nm"] = offshore_nm
    if radius_nm is not None:
        prm["radius_nm"] = radius_nm
    cache = dict(np.load(OUT_DIR / f"cache_{venue}_{cache_tag}.npz"))
    p = clim.YACHT_CLUB_PRESETS[venue]
    lat_c, lon_c = clim.project_point(p["lat"], p["lon"], prm["bearing"], prm["offshore_nm"])
    df, n = box_series(cache, lat_c, lon_c, prm["radius_nm"])
    if df is None:
        return None
    df["time"] = pd.to_datetime(df["time"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df["year"] = df["time"].dt.year
    df["date"] = df["time"].dt.normalize()
    df["hour"] = df["time"].dt.hour
    df["md"] = df["time"].dt.month * 100 + df["time"].dt.day
    df.attrs.update(n_cells=n, sample=(lat_c, lon_c), **prm)
    return df


def summarize(spd, direction):
    """Core statistics for arrays of speed (kt) and direction-from (deg)."""
    spd = np.asarray(spd)
    rad = np.radians(np.asarray(direction))
    sm, cm = np.sin(rad).mean(), np.cos(rad).mean()
    return {
        "n": int(len(spd)), "mean": spd.mean(), "median": np.median(spd),
        "p10": np.quantile(spd, 0.1), "p90": np.quantile(spd, 0.9), "max": spd.max(),
        "pct_lt5": 100 * (spd < 5).mean(),
        "pct_5_15": 100 * ((spd >= 5) & (spd < 15)).mean(),
        "pct_15_20": 100 * ((spd >= 15) & (spd < 20)).mean(),
        "pct_ge20": 100 * (spd >= 20).mean(),
        "dom_dir": math.degrees(math.atan2(sm, cm)) % 360,
        "R": math.hypot(sm, cm),
    }


def usable_day_share(df, min_run=3):
    """Share of days with >= min_run consecutive racing hours in 5-15 kt."""
    ok = 0
    days = 0
    keys = ["draw", "date"] if "draw" in df.columns else ["date"]   # draw: bootstrap copy id
    for _, g in df.groupby(keys):
        g = g.sort_values("hour")
        if len(g) < len(RACE_UTC):      # incomplete day: skip rather than bias
            continue
        days += 1
        flag = ((g["spd_kt"] >= 5) & (g["spd_kt"] < 15)).values
        run = best = 0
        for f in flag:
            run = run + 1 if f else 0
            best = max(best, run)
        ok += best >= min_run
    return 100 * ok / days if days else float("nan"), days


def stat_fns():
    return {
        "mean": lambda d: d["spd_kt"].mean(),
        "pct_lt5": lambda d: 100 * (d["spd_kt"] < 5).mean(),
        "pct_5_15": lambda d: 100 * ((d["spd_kt"] >= 5) & (d["spd_kt"] < 15)).mean(),
        "pct_ge15": lambda d: 100 * (d["spd_kt"] >= 15).mean(),
        "usable_day": lambda d: usable_day_share(d)[0],
    }


def year_bootstrap(df, rng, B=B_BOOT):
    """Resample whole years with replacement (keeps within-year correlation)."""
    by_year = {y: g for y, g in df.groupby("year")}
    years = list(by_year)
    fns = stat_fns()
    out = {k: [] for k in fns}
    for _ in range(B):
        pick = rng.choice(years, size=len(years), replace=True)
        d = pd.concat([by_year[y].assign(draw=i) for i, y in enumerate(pick)],
                      ignore_index=True)
        for k, f in fns.items():
            out[k].append(f(d))
    return {k: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5)))
            for k, v in out.items()}


def analyze_command(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rng = np.random.default_rng(42)
    rows, yearrows, diurnal, quality, series_store = [], [], {}, [], {}
    for venue, season, ctag, (c0, c1) in WINDOWS:
        base = load_series(venue, ctag)
        lo, hi = int(c0.replace("-", "")), int(c1.replace("-", ""))
        for scope, a, b in (("core", lo, hi), ("buffer", None, None)):
            d = base if scope == "buffer" else base[(base["md"] >= a) & (base["md"] <= b)]
            race = d[d["hour"].isin(RACE_UTC)].reset_index(drop=True)
            st = summarize(race["spd_kt"], race["dir"])
            ci = year_bootstrap(race, rng)
            ud, nd = usable_day_share(race)
            rows.append({"venue": venue, "season": season, "scope": scope,
                         "n_cells": base.attrs["n_cells"], **st,
                         "usable_day_pct": ud, "n_days": nd,
                         **{f"{k}_lo": v[0] for k, v in ci.items()},
                         **{f"{k}_hi": v[1] for k, v in ci.items()}})
            if scope == "core":
                series_store[(venue, season)] = race
                for y, g in race.groupby("year"):
                    s = summarize(g["spd_kt"], g["dir"])
                    yearrows.append({"venue": venue, "season": season, "year": y,
                                     "n": s["n"], "mean": s["mean"],
                                     "pct_5_15": s["pct_5_15"],
                                     "pct_ge15": 100 * (g["spd_kt"] >= 15).mean(),
                                     "pct_lt5": s["pct_lt5"]})
                diurnal[(venue, season)] = d.groupby("hour")["spd_kt"].mean()
                exp = len(d.groupby("date")) * 24
                quality.append({"venue": venue, "season": season,
                                "hours_present_24h": len(d), "hours_expected_24h": exp,
                                "race_hours_present": len(race),
                                "race_hours_expected": len(race.groupby('date')) * 7})
    summary = pd.DataFrame(rows)
    peryear = pd.DataFrame(yearrows)
    summary.to_csv(OUT_DIR / "summary_stats.csv", index=False)
    peryear.to_csv(OUT_DIR / "per_year_stats.csv", index=False)
    pd.DataFrame(quality).to_csv(OUT_DIR / "data_quality.csv", index=False)

    # Paired GTYC vs HYC (September core), day-level, bootstrap by year
    g = series_store[("gtyc", "sep")].groupby("date").agg(
        year=("year", "first"), g_mean=("spd_kt", "mean"),
        g_5_15=("spd_kt", lambda s: 100 * ((s >= 5) & (s < 15)).mean()),
        g_ge15=("spd_kt", lambda s: 100 * (s >= 15).mean()))
    h = series_store[("hyc", "sep")].groupby("date").agg(
        h_mean=("spd_kt", "mean"),
        h_5_15=("spd_kt", lambda s: 100 * ((s >= 5) & (s < 15)).mean()),
        h_ge15=("spd_kt", lambda s: 100 * (s >= 15).mean()))
    pair = g.join(h, how="inner")
    paired = []
    for m, (a, b) in {"mean_kt": ("h_mean", "g_mean"), "pct_5_15": ("h_5_15", "g_5_15"),
                      "pct_ge15": ("h_ge15", "g_ge15")}.items():
        diff = pair[a] - pair[b]
        years = pair["year"].unique()
        boots = []
        for _ in range(B_BOOT):
            pick = rng.choice(years, size=len(years), replace=True)
            boots.append(np.mean(np.concatenate([diff[pair["year"] == y].values for y in pick])))
        paired.append({"metric": f"HYC - GTYC {m}", "diff": diff.mean(),
                       "lo": np.percentile(boots, 2.5), "hi": np.percentile(boots, 97.5),
                       "n_days": len(diff)})
    pd.DataFrame(paired).to_csv(OUT_DIR / "paired_sep_hyc_minus_gtyc.csv", index=False)

    # Sample-point sensitivity band at the primary bearing (racing hours, core window)
    band = []
    for venue, season, ctag, (c0, c1) in WINDOWS:
        lo, hi = int(c0.replace("-", "")), int(c1.replace("-", ""))
        for off in OFFSHORE_NM:
            for rad in (2.0, 4.0, 6.0):
                d = load_series(venue, ctag, offshore_nm=off, radius_nm=rad)
                if d is None:
                    continue
                r = d[(d["md"] >= lo) & (d["md"] <= hi) & d["hour"].isin(RACE_UTC)]
                st = summarize(r["spd_kt"], r["dir"])
                band.append({"venue": venue, "season": season, "offshore_nm": off,
                             "radius_nm": rad, "n_cells": d.attrs["n_cells"],
                             "mean": st["mean"], "pct_lt5": st["pct_lt5"],
                             "pct_5_15": st["pct_5_15"],
                             "pct_ge15": st["pct_15_20"] + st["pct_ge20"]})
    pd.DataFrame(band).to_csv(OUT_DIR / "sensitivity_band.csv", index=False)

    # Figures: per-venue summary (rose + hist + table) and diurnal curves
    for (venue, season), race in series_store.items():
        df_ = pd.DataFrame({"wind_speed_ms": race["spd_kt"] / KT, "wind_dir_from": race["dir"],
                            "gust_ms": np.nan})
        st = clim.compute_stats(df_.assign(valid_time=race["time"]))
        title = (f"{clim.YACHT_CLUB_PRESETS[venue]['name']}\n{season.upper()} core window, "
                 f"2015-2025, 10AM-4PM EDT (n={len(race)})")
        clim.make_summary_figure(df_, st, title,
                                 str(OUT_DIR / f"summary_{venue}_{season}.png"),
                                 source_label="HRRR F00 via AWS")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for (venue, season), ser in diurnal.items():
        local = pd.Series(ser.values, index=(ser.index - 4) % 24).sort_index()
        ax.plot(local.index, local.values, marker="o", label=f"{venue.upper()} {season}")
    ax.axvspan(10, 16, color="grey", alpha=0.12, label="racing hours")
    ax.set_xlabel("Local hour (EDT)"); ax.set_ylabel("Mean wind (kt)")
    ax.set_xticks(range(0, 24, 3)); ax.set_xlim(-0.5, 23.5)
    ax.set_title("Diurnal mean wind, core windows 2015-2025"); ax.grid(alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4, frameon=False)
    fig.savefig(OUT_DIR / "diurnal.png", dpi=150, bbox_inches="tight"); plt.close(fig)

    pd.set_option("display.width", 220, "display.max_columns", 40)
    print(summary[["venue", "season", "scope", "n", "mean", "mean_lo", "mean_hi", "median",
                   "p90", "pct_lt5", "pct_5_15", "pct_5_15_lo", "pct_5_15_hi", "pct_ge15_lo",
                   "pct_ge15_hi", "pct_15_20", "pct_ge20", "usable_day_pct", "dom_dir", "R"]]
          .round(1).to_string(index=False))
    print("\n", pd.DataFrame(paired).round(2).to_string(index=False))
    print("\n", pd.DataFrame(quality).to_string(index=False))


# ---------------------------------------------------------------------------
# Validation against buoy observations
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("HRRR_WIND_BUOY_DIR", STUDY_DIR / "data" / "buoys"))
# NDBC stations: lat/lon and anemometer height from the NDBC station pages
BUOYS = {
    "gtyc": {"id": "45020", "lat": 44.789, "lon": -85.604, "anem_m": 2.4,
             "files": sorted((DATA_DIR / "Buoy_45020").glob("45020h*.txt")),
             "caches": ["sep_2015_2025", "val_gtyc"]},
    "hyc": {"id": "45163", "lat": 43.983, "lon": -83.600, "anem_m": 2.3,
            "files": sorted((DATA_DIR / "Buoy_45163_ndbc").glob("45163h*.txt.gz")),
            "caches": ["sep_2015_2025", "jun_2015_2025"]},
}
Z0_WATER_M = 0.0002   # neutral open-water roughness length for the log-law height adjustment


def height_factor(z_anem, z0=Z0_WATER_M, method="log"):
    """Multiplier converting wind measured at z_anem to 10 m."""
    if method == "power":
        return (10.0 / z_anem) ** (1.0 / 7.0)
    return math.log(10.0 / z0) / math.log(z_anem / z0)


def load_ndbc(paths):
    """Parse NDBC stdmet files (.txt or .txt.gz); return DataFrame time, wspd_ms, wdir."""
    import gzip
    frames = []
    for p in paths:
        opener = gzip.open if str(p).endswith(".gz") else open
        with opener(p, "rt") as f:
            lines = f.read().splitlines()
        hdr = next(l for l in lines if l.startswith("#")).lstrip("#").split()
        rows = [l.split() for l in lines if not l.startswith("#") and l.strip()]
        d = pd.DataFrame(rows).iloc[:, :len(hdr)]
        d.columns = [h.upper() for h in hdr]
        d = d.apply(pd.to_numeric, errors="coerce")
        yy = d.iloc[:, 0]
        yy = np.where(yy < 100, yy + 2000, yy)
        d["time"] = pd.to_datetime(dict(year=yy, month=d.iloc[:, 1], day=d.iloc[:, 2],
                                        hour=d.iloc[:, 3], minute=d.iloc[:, 4]))
        frames.append(d[["time", "WDIR", "WSPD", "GST"]])
    d = pd.concat(frames, ignore_index=True)
    bad = (d["WSPD"] >= 99) | (d["WDIR"] >= 999) | \
          ((d["WSPD"] == 0) & (d["GST"] == 0) & (d["WDIR"] == 0))   # logger-reset artefact
    d = d[~bad].drop_duplicates("time").sort_values("time")
    return d.rename(columns={"WSPD": "wspd_ms", "WDIR": "wdir"})[["time", "wspd_ms", "wdir"]]


def hourly_obs(obs, tol_min=10):
    """Observation nearest each top-of-hour within tol_min minutes."""
    o = obs.set_index("time")
    hours = pd.date_range(o.index.min().ceil("h"), o.index.max().floor("h"), freq="1h")
    idx = o.index.get_indexer(hours, method="nearest", tolerance=pd.Timedelta(minutes=tol_min))
    keep = idx >= 0
    out = o.iloc[idx[keep]].copy()
    out.index = hours[keep]
    return out.rename_axis("time").reset_index()


def hrrr_at(venue, lat_c, lon_c, radius_nm, nearest=False):
    """HRRR hourly speed/dir at an arbitrary point, concatenated across the buoy's caches."""
    out = []
    for ctag in BUOYS[venue]["caches"]:
        path = OUT_DIR / f"cache_{venue}_{ctag}.npz"
        if not path.exists():
            continue
        cache = dict(np.load(path))
        df, n = box_series(cache, lat_c, lon_c, radius_nm, nearest_only=nearest)
        if df is not None:
            out.append(df)
    h = pd.concat(out).drop_duplicates("time").sort_values("time")
    h["time"] = pd.to_datetime(h["time"])
    return h.rename(columns={"spd_kt": "hrrr_kt", "dir": "hrrr_dir"})


def circ_diff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def category(kt):
    return np.where(kt < 5, 0, np.where(kt < 15, 1, 2))


def pair_metrics(p, label):
    d = circ_diff(p["hrrr_dir"].values, p["obs_dir"].values)
    strong = p["obs_kt"] >= 6
    cat_o, cat_h = category(p["obs_kt"].values), category(p["hrrr_kt"].values)
    return {
        "subset": label, "n": len(p),
        "obs_mean_kt": p["obs_kt"].mean(), "hrrr_mean_kt": p["hrrr_kt"].mean(),
        "bias_kt": (p["hrrr_kt"] - p["obs_kt"]).mean(),
        "rmse_kt": float(np.sqrt(((p["hrrr_kt"] - p["obs_kt"]) ** 2).mean())),
        "corr_r": float(np.corrcoef(p["hrrr_kt"], p["obs_kt"])[0, 1]),
        "same_category_pct": 100 * float((cat_o == cat_h).mean()),
        "dir_bias_deg": float(d[strong].mean()) if strong.any() else np.nan,
        "dir_mae_deg": float(np.abs(d[strong]).mean()) if strong.any() else np.nan,
        "obs_pct_lt5": 100 * float((cat_o == 0).mean()),
        "obs_pct_5_15": 100 * float((cat_o == 1).mean()),
        "obs_pct_ge15": 100 * float((cat_o == 2).mean()),
        "hrrr_pct_lt5": 100 * float((cat_h == 0).mean()),
        "hrrr_pct_5_15": 100 * float((cat_h == 1).mean()),
        "hrrr_pct_ge15": 100 * float((cat_h == 2).mean()),
    }


def quantile_map(fit_hrrr, fit_obs, x, n_q=101):
    """Empirical quantile mapping HRRR -> obs; linear extrapolation by end-quantile offset."""
    qs = np.linspace(0, 100, n_q)
    hq, oq = np.percentile(fit_hrrr, qs), np.percentile(fit_obs, qs)
    out = np.interp(x, hq, oq)
    out = np.where(x > hq[-1], x + (oq[-1] - hq[-1]), out)
    return np.maximum(out, 0.0)


def validate_command(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metric_rows, adj_rows = [], []
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, venue in zip(axes, ("gtyc", "hyc")):
        b = BUOYS[venue]
        obs = hourly_obs(load_ndbc(b["files"]))
        fac = height_factor(b["anem_m"])
        fac_pow = height_factor(b["anem_m"], method="power")
        obs["obs_kt"] = obs["wspd_ms"] * KT * fac
        obs["obs_kt_raw"] = obs["wspd_ms"] * KT
        obs["obs_dir"] = obs["wdir"]
        for mode, kw in (("nearest water cell", dict(radius_nm=2.0, nearest=True)),
                         ("2 nm water box", dict(radius_nm=2.0, nearest=False))):
            h = hrrr_at(venue, b["lat"], b["lon"], **kw)
            p = obs.merge(h, on="time", how="inner")
            p["hour"] = p["time"].dt.hour
            p["month"] = p["time"].dt.month
            subsets = {"all pairs": p, "racing hrs (14-20 UTC)": p[p["hour"].isin(RACE_UTC)]}
            for sname, sub in subsets.items():
                if len(sub) < 30:
                    continue
                r = pair_metrics(sub, sname)
                metric_rows.append({"venue": venue, "buoy": b["id"], "hrrr_sampling": mode,
                                    "height_adj": f"log x{fac:.2f}", **r})
            # sensitivity: raw (unadjusted) and power-law adjustment, racing hours
            rh = p[p["hour"].isin(RACE_UTC)]
            if len(rh) >= 30:
                for nm, col in (("raw (no height adj)", rh["obs_kt_raw"]),
                                (f"power-law x{fac_pow:.2f}", rh["wspd_ms"] * KT * fac_pow)):
                    q = rh.assign(obs_kt=col)
                    metric_rows.append({"venue": venue, "buoy": b["id"],
                                        "hrrr_sampling": mode, "height_adj": nm,
                                        **pair_metrics(q, "racing hrs (14-20 UTC)")})
            if mode == "2 nm water box":
                sub = subsets["racing hrs (14-20 UTC)"]
                ax.scatter(sub["obs_kt"], sub["hrrr_kt"], s=6, alpha=0.35)
                lim = max(sub["obs_kt"].max(), sub["hrrr_kt"].max()) + 1
                ax.plot([0, lim], [0, lim], "k--", lw=1)
                ax.set_xlim(0, lim); ax.set_ylim(0, lim)
                ax.set_xlabel(f"Buoy {b['id']} wind adj. to 10 m (kt)")
                ax.set_ylabel("HRRR F00 (kt)")
                ax.set_title(f"{venue.upper()}: racing hours, n={len(sub)}")
                ax.grid(alpha=0.3)
                pairs_for_qm = p
        fig.tight_layout()

        # Bias-adjusted venue statistics (quantile mapping fitted on racing-hour pairs,
        # separately per season where both seasons have data)
        for season, ctag, (c0, c1) in [(s, c, w) for (v, s, c, w) in WINDOWS if v == venue]:
            ser = load_series(venue, ctag)
            lo, hi = int(c0.replace("-", "")), int(c1.replace("-", ""))
            core = ser[(ser["md"] >= lo) & (ser["md"] <= hi) & ser["hour"].isin(RACE_UTC)]
            months = (9,) if season == "sep" else (6,)
            fit = pairs_for_qm[pairs_for_qm["hour"].isin(RACE_UTC) &
                               pairs_for_qm["month"].isin(months)]
            if len(fit) < 100:
                fit = pairs_for_qm[pairs_for_qm["hour"].isin(RACE_UTC)]
                fit_note = "all months (too few in season)"
            else:
                fit_note = f"{'Sep' if season == 'sep' else 'Jun'} pairs"
            raw = core["spd_kt"].values
            adj = quantile_map(fit["hrrr_kt"].values, fit["obs_kt"].values, raw)
            for lab, v in (("HRRR raw", raw), ("HRRR quantile-mapped to buoy", adj)):
                adj_rows.append({
                    "venue": venue, "season": season, "version": lab, "fit_data": fit_note,
                    "n_fit_pairs": len(fit), "n": len(v), "mean": v.mean(),
                    "median": np.median(v), "p90": np.percentile(v, 90),
                    "pct_lt5": 100 * (v < 5).mean(),
                    "pct_5_15": 100 * ((v >= 5) & (v < 15)).mean(),
                    "pct_ge15": 100 * (v >= 15).mean()})
    fig.savefig(OUT_DIR / "validation_scatter.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    m = pd.DataFrame(metric_rows)
    a = pd.DataFrame(adj_rows)
    m.to_csv(OUT_DIR / "validation_metrics.csv", index=False)
    a.to_csv(OUT_DIR / "bias_adjusted_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(m[["venue", "hrrr_sampling", "height_adj", "subset", "n", "obs_mean_kt",
             "hrrr_mean_kt", "bias_kt", "rmse_kt", "corr_r", "same_category_pct",
             "dir_bias_deg", "dir_mae_deg"]].round(2).to_string(index=False))
    print()
    print(m[m["height_adj"].str.startswith("log")][["venue", "hrrr_sampling", "subset",
          "obs_pct_lt5", "obs_pct_5_15", "obs_pct_ge15", "hrrr_pct_lt5", "hrrr_pct_5_15",
          "hrrr_pct_ge15"]].round(1).to_string(index=False))
    print()
    print(a.round(1).to_string(index=False))



def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("cache", "sensitivity", "analyze", "validate"):
        sp = sub.add_parser(name)
        sp.add_argument("--venues", nargs="+", default=["gtyc", "hyc"])
        sp.add_argument("--tag", required=(name not in ("analyze", "validate")))
        if name == "cache":
            sp.add_argument("--years", type=int, nargs="+", required=True)
            sp.add_argument("--start", default="09-08", help="MM-DD")
            sp.add_argument("--end", default="09-14", help="MM-DD")
            sp.add_argument("--start-hour", type=int, default=0)
            sp.add_argument("--end-hour", type=int, default=23)
            sp.add_argument("--max-rss-gb", type=float, default=6.0,
                            help="Abort if this process exceeds this resident memory")
            sp.add_argument("--chunk-hours", type=int, default=72,
                            help="Timestamps fetched per FastHerbie call (memory control)")
    args = ap.parse_args()
    {"cache": cache_command, "sensitivity": sensitivity_command,
     "analyze": analyze_command, "validate": validate_command}[args.cmd](args)


if __name__ == "__main__":
    main()
