"""Validation of HRRR against NDBC buoy observations, and quantile-mapping bias adjustment."""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from hrrr_wind.cache import box_series, load_cache
from hrrr_wind.config import KT
from hrrr_wind.stats import load_series

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


def hrrr_at(study, venue, lat_c, lon_c, radius_nm, nearest=False):
    """HRRR hourly speed/dir at an arbitrary point, concatenated across the buoy's caches."""
    out = []
    for ctag in study.buoys[venue].caches:
        if not (study.out_dir / f"cache_{venue}_{ctag}.npz").exists():
            continue
        cache = load_cache(study.out_dir, venue, ctag)
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


@dataclass
class ValidationResults:
    metrics: pd.DataFrame
    adjusted: pd.DataFrame
    scatter: dict = field(default_factory=dict)   # venue -> (racing-hour pairs, buoy id)


def run_validation(study):
    """Compare HRRR with each venue's buoy; return metrics, bias-adjusted stats, scatter data."""
    race = study.race_utc
    race_label = f"racing hrs ({study.race_start}-{study.race_end} UTC)"
    metric_rows, adj_rows, scatter = [], [], {}
    for venue, b in study.buoys.items():
        obs = hourly_obs(load_ndbc(study.buoy_files(venue)))
        fac = height_factor(b.anem_m)
        fac_pow = height_factor(b.anem_m, method="power")
        obs["obs_kt"] = obs["wspd_ms"] * KT * fac
        obs["obs_kt_raw"] = obs["wspd_ms"] * KT
        obs["obs_dir"] = obs["wdir"]
        for mode, kw in (("nearest water cell", dict(radius_nm=2.0, nearest=True)),
                         ("2 nm water box", dict(radius_nm=2.0, nearest=False))):
            h = hrrr_at(study, venue, b.lat, b.lon, **kw)
            p = obs.merge(h, on="time", how="inner")
            p["hour"] = p["time"].dt.hour
            p["month"] = p["time"].dt.month
            subsets = {"all pairs": p, race_label: p[p["hour"].isin(race)]}
            for sname, sub in subsets.items():
                if len(sub) < 30:
                    continue
                metric_rows.append({"venue": venue, "buoy": b.id, "hrrr_sampling": mode,
                                    "height_adj": f"log x{fac:.2f}",
                                    **pair_metrics(sub, sname)})
            # sensitivity: raw (unadjusted) and power-law adjustment, racing hours
            rh = p[p["hour"].isin(race)]
            if len(rh) >= 30:
                for nm, col in (("raw (no height adj)", rh["obs_kt_raw"]),
                                (f"power-law x{fac_pow:.2f}", rh["wspd_ms"] * KT * fac_pow)):
                    metric_rows.append({"venue": venue, "buoy": b.id, "hrrr_sampling": mode,
                                        "height_adj": nm,
                                        **pair_metrics(rh.assign(obs_kt=col), race_label)})
            if mode == "2 nm water box":
                scatter[venue] = (subsets[race_label], b.id)
                pairs_for_qm = p

        # Bias-adjusted venue statistics (quantile mapping fitted on racing-hour pairs,
        # separately per season where both seasons have data)
        for w in study.windows_for(venue):
            ser = load_series(study, venue, w.cache_tag)
            core = ser[(ser["md"] >= w.lo) & (ser["md"] <= w.hi) & ser["hour"].isin(race)]
            fit = pairs_for_qm[pairs_for_qm["hour"].isin(race) &
                               (pairs_for_qm["month"] == w.fit_month)]
            if len(fit) < 100:
                fit = pairs_for_qm[pairs_for_qm["hour"].isin(race)]
                fit_note = "all months (too few in season)"
            else:
                fit_note = f"{w.fit_label} pairs"
            raw = core["spd_kt"].values
            adj = quantile_map(fit["hrrr_kt"].values, fit["obs_kt"].values, raw)
            for lab, v in (("HRRR raw", raw), ("HRRR quantile-mapped to buoy", adj)):
                adj_rows.append({
                    "venue": venue, "season": w.season, "version": lab, "fit_data": fit_note,
                    "n_fit_pairs": len(fit), "n": len(v), "mean": v.mean(),
                    "median": np.median(v), "p90": np.percentile(v, 90),
                    "pct_lt5": 100 * (v < 5).mean(),
                    "pct_5_15": 100 * ((v >= 5) & (v < 15)).mean(),
                    "pct_ge15": 100 * (v >= 15).mean()})
    return ValidationResults(pd.DataFrame(metric_rows), pd.DataFrame(adj_rows), scatter)
