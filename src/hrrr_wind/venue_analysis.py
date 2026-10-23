"""Command-line interface for a study: cache | sensitivity | analyze | validate.

    python -m hrrr_wind.venue_analysis [--study path/to/study.toml] <command> ...

All computation lives in the library modules (cache, stats, validation, plots); this file
only parses arguments, calls them, writes outputs and prints summaries.
"""
import argparse
import logging
import warnings
from datetime import datetime

import matplotlib
import pandas as pd

from hrrr_wind import outputs
from hrrr_wind.cache import MemoryLimitExceeded, build_cache, fetch_land_mask
from hrrr_wind.config import cache_plan, load_study
from hrrr_wind.stats import run_analysis, sensitivity_grid
from hrrr_wind.validation import run_validation

logger = logging.getLogger("hrrr_wind.cli")


def emit(args):
    """Progress reporter: machine-readable lines when --progress-lines is set (used by the web app)."""
    if not args.progress_lines:
        return None

    def report(frac, msg=""):
        print(f"PROGRESS {min(max(frac, 0.0), 1.0):.4f} {msg}", flush=True)
    return report


def download(study, venues, years, tag, start, end, start_hour, end_hour, max_rss_gb, chunk_hours,
             report=None):
    """Download one cache group; ``report(fraction, message)`` is the optional progress reporter."""
    years = list(years)

    def progress(year, chunk, n_chunks):
        if report:
            report((years.index(year) + chunk / n_chunks) / len(years),
                   f"downloading {tag}: {year}, part {chunk + 1} of {n_chunks}")
    try:
        build_cache(study.out_dir, venues, years, tag, start, end, start_hour=start_hour,
                    end_hour=end_hour, max_rss_gb=max_rss_gb, chunk_hours=chunk_hours,
                    progress=progress, clubs={k: (study.venues[k].lat, study.venues[k].lon) for k in venues})
    except MemoryLimitExceeded as e:
        raise SystemExit(str(e))


def cmd_cache(study, args):
    download(study, args.venues, args.years, args.tag, args.start, args.end, args.start_hour,
             args.end_hour, args.max_rss_gb, args.chunk_hours, emit(args))


def scaled(report, lo, hi):
    """Map a sub-task's 0..1 progress onto the lo..hi slice of the whole run."""
    return (lambda frac, msg="": report(lo + (hi - lo) * frac, msg)) if report else None


def cmd_run(study, args):
    """Whole pipeline: every missing cache, then analyze, then validate (if the study has buoys)."""
    report = emit(args)
    plan = cache_plan(study)
    per_file = lambda g: len(g["years"]) * g["span_days"]             # noqa: E731  (relative weight)
    for g in plan:
        g["span_days"] = (datetime.strptime(f"2001-{g['end']}", "%Y-%m-%d")
                          - datetime.strptime(f"2001-{g['start']}", "%Y-%m-%d")).days + 1
    total = sum(per_file(g) for g in plan) or 1
    done, dl_end = 0, 0.85 if plan else 0.0
    for g in plan:
        w = per_file(g)
        download(study, g["venues"], g["years"], g["tag"], g["start"], g["end"], 0, 23,
                 args.max_rss_gb, args.chunk_hours,
                 scaled(report, dl_end * done / total, dl_end * (done + w) / total))
        done += w
    a_end = dl_end + (1 - dl_end) * (0.7 if study.buoys else 1.0)
    res = run_analysis(study, progress=scaled(report, dl_end, a_end))
    outputs.write_analysis(study, res)
    if study.buoys:
        outputs.write_validation(study, run_validation(study, progress=scaled(report, a_end, 1.0)))


def cmd_sensitivity(study, args):
    out = sensitivity_grid(study, args.tag, args.venues)
    path = study.out_dir / f"sensitivity_{args.tag}.csv"
    out.to_csv(path, index=False)
    logger.info(f"saved {path} ({len(out)} rows)")
    pd.set_option("display.width", 200)
    print(out.round(1).to_string(index=False))


def cmd_analyze(study, args):
    res = run_analysis(study, progress=emit(args))
    outputs.write_analysis(study, res)
    pd.set_option("display.width", 220, "display.max_columns", 40)
    print(res.summary[["venue", "season", "scope", "n", "mean", "mean_lo", "mean_hi", "median",
                       "p90", "pct_lt5", "pct_5_20", "pct_5_20_lo", "pct_5_20_hi",
                       "pct_ge20_lo", "pct_ge20_hi", "pct_ge20",
                       "usable_day_pct", "dom_dir", "R"]].round(1).to_string(index=False))
    for df in res.paired.values():
        print("\n", df.round(2).to_string(index=False))
    print("\n", res.quality.to_string(index=False))


def cmd_validate(study, args):
    if not study.buoys:
        print("No buoys defined for this study; skipping validation.")
        return
    val = run_validation(study, progress=emit(args))
    outputs.write_validation(study, val)
    m, a = val.metrics, val.adjusted
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(m[["venue", "hrrr_sampling", "height_adj", "subset", "n", "obs_mean_kt",
             "hrrr_mean_kt", "bias_kt", "rmse_kt", "corr_r", "same_category_pct",
             "dir_bias_deg", "dir_mae_deg"]].round(2).to_string(index=False))
    print()
    print(m[m["height_adj"].str.startswith("log")][
        ["venue", "hrrr_sampling", "subset", "obs_pct_lt5", "obs_pct_5_20", "obs_pct_ge20",
         "hrrr_pct_lt5", "hrrr_pct_5_20", "hrrr_pct_ge20"]].round(1).to_string(index=False))
    print()
    print(a.round(1).to_string(index=False))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    warnings.filterwarnings("ignore")
    matplotlib.use("Agg")
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", help="path to study.toml (default: the GTYC/HYC study)")
    ap.add_argument("--progress-lines", action="store_true",
                    help="print PROGRESS <fraction> <message> lines (for the web app)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="download whatever is missing, then analyze and validate")
    run.add_argument("--max-rss-gb", type=float, default=4.0)
    run.add_argument("--chunk-hours", type=int, default=24)
    for name in ("cache", "sensitivity", "analyze", "validate"):
        sp = sub.add_parser(name)
        sp.add_argument("--venues", nargs="+", default=None)
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
    mask = sub.add_parser("landmask", help="fetch and cache the land mask around a position (for map previews)")
    mask.add_argument("--out", required=True)
    mask.add_argument("--key", required=True)
    mask.add_argument("--lat", type=float, required=True)
    mask.add_argument("--lon", type=float, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "landmask":              # needs no study
        fetch_land_mask(args.out, args.key, args.lat, args.lon)
        return
    study = load_study(args.study)
    if getattr(args, "venues", None) is None:
        args.venues = list(study.venues)
    {"run": cmd_run, "cache": cmd_cache, "sensitivity": cmd_sensitivity,
     "analyze": cmd_analyze, "validate": cmd_validate}[args.cmd](study, args)


if __name__ == "__main__":
    main()
