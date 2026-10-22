"""Command-line interface for a study: cache | sensitivity | analyze | validate.

    python -m hrrr_wind.venue_analysis [--study path/to/study.toml] <command> ...

All computation lives in the library modules (cache, stats, validation, plots); this file
only parses arguments, calls them, writes outputs and prints summaries.
"""
import argparse
import logging
import warnings

import matplotlib
import pandas as pd

from hrrr_wind import outputs
from hrrr_wind.cache import MemoryLimitExceeded, build_cache
from hrrr_wind.config import load_study
from hrrr_wind.stats import run_analysis, sensitivity_grid
from hrrr_wind.validation import run_validation

logger = logging.getLogger("hrrr_wind.cli")


def cmd_cache(study, args):
    try:
        build_cache(study.out_dir, args.venues, args.years, args.tag, args.start, args.end,
                    start_hour=args.start_hour, end_hour=args.end_hour,
                    max_rss_gb=args.max_rss_gb, chunk_hours=args.chunk_hours)
    except MemoryLimitExceeded as e:
        raise SystemExit(str(e))


def cmd_sensitivity(study, args):
    out = sensitivity_grid(study, args.tag, args.venues)
    path = study.out_dir / f"sensitivity_{args.tag}.csv"
    out.to_csv(path, index=False)
    logger.info(f"saved {path} ({len(out)} rows)")
    pd.set_option("display.width", 200)
    print(out.round(1).to_string(index=False))


def cmd_analyze(study, args):
    res = run_analysis(study)
    outputs.write_analysis(study, res)
    pd.set_option("display.width", 220, "display.max_columns", 40)
    print(res.summary[["venue", "season", "scope", "n", "mean", "mean_lo", "mean_hi", "median",
                       "p90", "pct_lt5", "pct_5_15", "pct_5_15_lo", "pct_5_15_hi",
                       "pct_ge15_lo", "pct_ge15_hi", "pct_15_20", "pct_ge20",
                       "usable_day_pct", "dom_dir", "R"]].round(1).to_string(index=False))
    for df in res.paired.values():
        print("\n", df.round(2).to_string(index=False))
    print("\n", res.quality.to_string(index=False))


def cmd_validate(study, args):
    val = run_validation(study)
    outputs.write_validation(study, val)
    m, a = val.metrics, val.adjusted
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(m[["venue", "hrrr_sampling", "height_adj", "subset", "n", "obs_mean_kt",
             "hrrr_mean_kt", "bias_kt", "rmse_kt", "corr_r", "same_category_pct",
             "dir_bias_deg", "dir_mae_deg"]].round(2).to_string(index=False))
    print()
    print(m[m["height_adj"].str.startswith("log")][
        ["venue", "hrrr_sampling", "subset", "obs_pct_lt5", "obs_pct_5_15", "obs_pct_ge15",
         "hrrr_pct_lt5", "hrrr_pct_5_15", "hrrr_pct_ge15"]].round(1).to_string(index=False))
    print()
    print(a.round(1).to_string(index=False))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    warnings.filterwarnings("ignore")
    matplotlib.use("Agg")
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", help="path to study.toml (default: the GTYC/HYC study)")
    sub = ap.add_subparsers(dest="cmd", required=True)
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
    args = ap.parse_args(argv)
    study = load_study(args.study)
    if args.venues is None:
        args.venues = list(study.venues)
    {"cache": cmd_cache, "sensitivity": cmd_sensitivity,
     "analyze": cmd_analyze, "validate": cmd_validate}[args.cmd](study, args)


if __name__ == "__main__":
    main()
