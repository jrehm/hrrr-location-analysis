"""Statistics, uncertainty and venue comparison, computed from cached wind data.

Nothing here reads or writes anything except the ``cache_*.npz`` files, and nothing prints:
functions take a ``Study`` and return DataFrames, so a CLI, a notebook or a web API can all
call them.
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from hrrr_wind.cache import box_series, load_cache


def load_series(study, venue, cache_tag, bearing=None, offshore_nm=None, radius_nm=None):
    """Hourly speed (kt) / direction at the venue's sample point (or an overridden one).

    Returns None if the box contains no water cells. ``attrs`` carries n_cells, the sample
    point and the bearing/offshore/radius used.
    """
    v = study.venues[venue]
    prm = {"bearing": v.bearing if bearing is None else bearing,
           "offshore_nm": v.offshore_nm if offshore_nm is None else offshore_nm,
           "radius_nm": v.radius_nm if radius_nm is None else radius_nm}
    # one tag (a str) must exist; several (a window's caches) use whichever exist, as they share a grid
    tags = [cache_tag] if isinstance(cache_tag, str) else [t for t in cache_tag if study.cache_path(venue, t).exists()]
    if not tags:
        raise FileNotFoundError(f"no wind cache for {venue}: {cache_tag}")
    lat_c, lon_c = study.sample_point(venue, bearing=prm["bearing"],
                                      offshore_nm=prm["offshore_nm"])
    frames = []
    for t in tags:
        part, n = box_series(load_cache(study.out_dir, venue, t), lat_c, lon_c, prm["radius_nm"])
        if part is None:
            return None
        frames.append(part)
    df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df["year"] = df["time"].dt.year
    df = df[df["year"].isin(study.years)].reset_index(drop=True)      # years left out of the study stay on disk
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


SECTOR_NAMES = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
SPEED_BIN_EDGES = [0, 5, 10, 15, 20, np.inf]
SPEED_BIN_NAMES = ["0-5", "5-10", "10-15", "15-20", "20+"]


def windrose_table(spd, direction):
    """16-sector wind rose: % of all hours per (speed bin, sector), plus the speed distribution.

    ``values[b][s]`` is the percent of hours in speed bin b and direction sector s (sector 0
    is centered on north; direction is where the wind blows FROM).
    """
    spd = np.asarray(spd, dtype=float)
    sector = (((np.asarray(direction, dtype=float) + 11.25) % 360) // 22.5).astype(int) % 16
    b = np.clip(np.digitize(spd, SPEED_BIN_EDGES[1:-1], right=False), 0, 4)
    n = len(spd)
    values = np.zeros((5, 16))
    np.add.at(values, (b, sector), 1)
    values = 100 * values / n
    return {"sectors": SECTOR_NAMES, "bins": SPEED_BIN_NAMES, "values": values.tolist(),
            "distribution": values.sum(axis=1).tolist(), "n": n}


def usable_day_share(df, race_hours, min_run=3):
    """Share of days with >= min_run consecutive racing hours in 5-15 kt.

    Days with fewer than ``race_hours`` hours present are skipped rather than counted.
    """
    ok = 0
    days = 0
    keys = ["draw", "date"] if "draw" in df.columns else ["date"]   # draw: bootstrap copy id
    for _, g in df.groupby(keys):
        g = g.sort_values("hour")
        if len(g) < race_hours:
            continue
        days += 1
        flag = ((g["spd_kt"] >= 5) & (g["spd_kt"] < 15)).values
        run = best = 0
        for f in flag:
            run = run + 1 if f else 0
            best = max(best, run)
        ok += best >= min_run
    return 100 * ok / days if days else float("nan"), days


def stat_fns(race_hours):
    return {
        "mean": lambda d: d["spd_kt"].mean(),
        "pct_lt5": lambda d: 100 * (d["spd_kt"] < 5).mean(),
        "pct_5_15": lambda d: 100 * ((d["spd_kt"] >= 5) & (d["spd_kt"] < 15)).mean(),
        "pct_ge15": lambda d: 100 * (d["spd_kt"] >= 15).mean(),
        "usable_day": lambda d: usable_day_share(d, race_hours)[0],
    }


def year_bootstrap(df, rng, B, race_hours):
    """95% CIs by resampling whole years with replacement (keeps within-year correlation)."""
    by_year = {y: g for y, g in df.groupby("year")}
    years = list(by_year)
    fns = stat_fns(race_hours)
    out = {k: [] for k in fns}
    for _ in range(B):
        pick = rng.choice(years, size=len(years), replace=True)
        d = pd.concat([by_year[y].assign(draw=i) for i, y in enumerate(pick)],
                      ignore_index=True)
        for k, f in fns.items():
            out[k].append(f(d))
    return {k: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5)))
            for k, v in out.items()}


def sensitivity_grid(study, tag, venues=None):
    """Mean/bin shares across bearing x offshore distance x box radius (+ nearest water cell)."""
    rows = []
    for key in venues or list(study.venues):
        cache = load_cache(study.out_dir, key, tag)
        for brg in study.venues[key].sensitivity_bearings:
            for off in study.sens_offshore_nm:
                lat_c, lon_c = study.sample_point(key, bearing=brg, offshore_nm=off)
                combos = [(r, False) for r in study.sens_radius_nm] + \
                         [(study.sens_radius_nm[0], True)]
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
    return pd.DataFrame(rows)


@dataclass
class AnalysisResults:
    summary: pd.DataFrame
    per_year: pd.DataFrame
    quality: pd.DataFrame
    band: pd.DataFrame
    paired: dict = field(default_factory=dict)    # (season, a, b) -> DataFrame
    series: dict = field(default_factory=dict)    # (venue, season) -> racing-hour DataFrame
    diurnal: dict = field(default_factory=dict)   # (venue, season) -> Series by UTC hour


def _day_table(race, prefix):
    return race.groupby("date").agg(**{
        "year": ("year", "first"),
        f"{prefix}_mean": ("spd_kt", "mean"),
        f"{prefix}_5_15": ("spd_kt", lambda s: 100 * ((s >= 5) & (s < 15)).mean()),
        f"{prefix}_ge15": ("spd_kt", lambda s: 100 * (s >= 15).mean())})


def paired_comparison(race_a, race_b, a_name, b_name, rng, B):
    """Day-level a-minus-b differences with a year-resampling bootstrap CI."""
    pa = _day_table(race_a, "a")
    pb = _day_table(race_b, "b").drop(columns="year")
    pair = pa.join(pb, how="inner")
    rows = []
    for m, (x, y) in {"mean_kt": ("a_mean", "b_mean"), "pct_5_15": ("a_5_15", "b_5_15"),
                      "pct_ge15": ("a_ge15", "b_ge15")}.items():
        diff = pair[x] - pair[y]
        years = pair["year"].unique()
        boots = []
        for _ in range(B):
            pick = rng.choice(years, size=len(years), replace=True)
            boots.append(np.mean(np.concatenate([diff[pair["year"] == yr].values
                                                 for yr in pick])))
        rows.append({"metric": f"{a_name.upper()} - {b_name.upper()} {m}",
                     "diff": diff.mean(), "lo": np.percentile(boots, 2.5),
                     "hi": np.percentile(boots, 97.5), "n_days": len(diff)})
    return pd.DataFrame(rows)


def run_analysis(study, progress=None):
    """Full statistical analysis of every window in the study (racing hours, core + buffer).

    ``progress(fraction, message)`` is an optional callback for a UI.
    """
    step = [0]
    total = 2 * len(study.windows) + len(study.pairs)

    def tick(msg):
        if progress:
            progress(step[0] / total, msg)
        step[0] += 1

    rng = np.random.default_rng(study.seed)
    B = study.bootstrap_draws
    n_race = len(study.race_utc)
    rows, yearrows, quality = [], [], []
    res = AnalysisResults(None, None, None, None)
    for w in study.windows:
        tick(f"statistics and confidence intervals: {w.venue} {w.season}")
        base = load_series(study, w.venue, w.tags)
        if base is None:
            raise ValueError(f"{w.venue}: the sample-point box has no water cells; "
                             "move the sample point offshore or widen the box, then rerun")
        for scope, a, b in (("core", w.lo, w.hi), ("buffer", None, None)):
            d = base if scope == "buffer" else base[(base["md"] >= a) & (base["md"] <= b)]
            race = d[d["hour"].isin(study.race_utc)].reset_index(drop=True)
            st = summarize(race["spd_kt"], race["dir"])
            ci = year_bootstrap(race, rng, B, n_race)
            ud, nd = usable_day_share(race, n_race)
            rows.append({"venue": w.venue, "season": w.season, "scope": scope,
                         "n_cells": base.attrs["n_cells"], **st,
                         "usable_day_pct": ud, "n_days": nd,
                         **{f"{k}_lo": v[0] for k, v in ci.items()},
                         **{f"{k}_hi": v[1] for k, v in ci.items()}})
            if scope == "core":
                res.series[(w.venue, w.season)] = race
                for y, g in race.groupby("year"):
                    s = summarize(g["spd_kt"], g["dir"])
                    yearrows.append({"venue": w.venue, "season": w.season, "year": y,
                                     "n": s["n"], "mean": s["mean"],
                                     "pct_5_15": s["pct_5_15"],
                                     "pct_ge15": 100 * (g["spd_kt"] >= 15).mean(),
                                     "pct_lt5": s["pct_lt5"]})
                res.diurnal[(w.venue, w.season)] = d.groupby("hour")["spd_kt"].mean()
                exp = len(d.groupby("date")) * 24
                quality.append({"venue": w.venue, "season": w.season,
                                "hours_present_24h": len(d), "hours_expected_24h": exp,
                                "race_hours_present": len(race),
                                "race_hours_expected": len(race.groupby("date")) * n_race})
    res.summary = pd.DataFrame(rows)
    res.per_year = pd.DataFrame(yearrows)
    res.quality = pd.DataFrame(quality)

    for p in study.pairs:
        tick(f"paired comparison: {p.a} vs {p.b} ({p.season})")
        res.paired[(p.season, p.a, p.b)] = paired_comparison(
            res.series[(p.a, p.season)], res.series[(p.b, p.season)], p.a, p.b, rng, B)

    # Sample-point sensitivity band at the primary bearing (racing hours, core window)
    band = []
    for w in study.windows:
        tick(f"sample-point sensitivity: {w.venue} {w.season}")
        for off in study.sens_offshore_nm:
            for rad in study.sens_radius_nm:
                d = load_series(study, w.venue, w.tags, offshore_nm=off, radius_nm=rad)
                if d is None:
                    continue
                r = d[(d["md"] >= w.lo) & (d["md"] <= w.hi) & d["hour"].isin(study.race_utc)]
                st = summarize(r["spd_kt"], r["dir"])
                band.append({"venue": w.venue, "season": w.season, "offshore_nm": off,
                             "radius_nm": rad, "n_cells": d.attrs["n_cells"],
                             "mean": st["mean"], "pct_lt5": st["pct_lt5"],
                             "pct_5_15": st["pct_5_15"],
                             "pct_ge15": st["pct_15_20"] + st["pct_ge20"]})
    res.band = pd.DataFrame(band)
    return res
