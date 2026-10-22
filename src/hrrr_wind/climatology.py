#!/usr/bin/env python
"""
HRRR Yacht Club Wind Climatology v1.2

Fork of HRRR_historical_data_retrieval for quickly evaluating historical wind
patterns at specific yacht club locations over a date range. Instead of bulk
GRIB2 downloads, this extracts a point time series (offshore of the club) and
produces summary statistics plus a wind rose.

Key design notes:
- Yacht clubs are on shore; HRRR land grid cells are not representative of
  on-water wind. Each club entry includes a bearing (degrees TRUE, pointing
  offshore) so the sample point is offset out onto the water before the
  surrounding grid cells are averaged.
- Sample point = club lat/lon projected `--offshore-nm` along `bearing`.
- Stats are computed from a small box of grid cells centered on that sample
  point (`--radius-nm`), giving a spatial average rather than a single cell.

v1.2 changes (vs v1.1):
- Box is built from an explicit 2-D water mask (HRRR LAND field) instead of a
  lat/lon `where(..., drop=True)`; fixes the longitude-bound ternary precedence
  bug and keeps land cells out of the spatial average.
- Timestamps come from `valid_time`, are de-duplicated, and every run reports
  expected vs. retrieved timestamps (missing ones listed per year).
- `--window-buffer-days` widens the calendar window; rows are tagged `core`.
- Time series CSV is always written so stats can be recomputed offline.
- Per-club default `offshore_nm` in the presets (CLI value still overrides).

Author: Claude (fork of HRRR_historical_data_retrieval_v1.0)
"""

from herbie import Herbie, FastHerbie
import pandas as pd
import numpy as np
from datetime import datetime
import argparse
import os
import sys
import time
import logging
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('hrrr_club_climatology')

# HRRR data availability start date
HRRR_START_DATE = datetime(2014, 9, 30)

# Search string for 10m wind (and optional gust)
SEARCH_WIND = ":(?:UGRD|VGRD):10 m above ground:"
SEARCH_WIND_GUST = ":(?:UGRD|VGRD):10 m above ground:|:GUST:surface:"

# ---------------------------------------------------------------------------
# Yacht club presets
#
# Each entry: lat/lon of the clubhouse, and `bearing` = compass direction
# (degrees TRUE, 0=N, 90=E) pointing OUT onto open water from the club.
# Add new clubs here as needed - this is meant to grow over time.
# ---------------------------------------------------------------------------
YACHT_CLUB_PRESETS = {
    # --- Southeast Michigan / Lake St. Clair / Lake Erie ---
    "byc": {
        "name": "Bayview Yacht Club",
        "lat": 42.3592,
        "lon": -82.9596,
        "bearing": 100,  # ESE into Detroit River / Lake St. Clair approach
    },
    "csyc": {
        "name": "Crescent Sail Yacht Club",
        "lat": 42.4021,
        "lon": -82.8851,
        "bearing": 50,   # NE into Lake St. Clair (Grosse Pointe Farms)
    },
    "ncyc": {
        "name": "North Cape Yacht Club",
        "lat": 41.8278,
        "lon": -83.4085,
        "bearing": 100,  # ESE into western Lake Erie (La Salle Township)
    },

    # --- Lake Michigan (east shore) ---
    "gtyc": {
        "name": "Grand Traverse Yacht Club",
        "lat": 44.78034,   # satellite-confirmed clubhouse (user, 2026-10-20); was 44.7481/-85.6358
        "lon": -85.63852,
        "bearing": 20,   # NNE toward the racing circle midway between the club and Power Island
        "offshore_nm": 3.0,
    },
    "lyc": {
        "name": "Ludington Yacht Club",
        "lat": 43.9551,
        "lon": -86.4515,
        "bearing": 270,  # W through Pere Marquette Lake channel to Lake Michigan
        "offshore_nm": 4.0,  # channel adds ~2 nm of protected water
    },
    "myc": {
        "name": "Muskegon Yacht Club",
        "lat": 43.2205,
        "lon": -86.3207,
        "bearing": 285,  # WNW via Muskegon Lake channel to Lake Michigan
        "offshore_nm": 4.0,  # channel adds ~1.5 nm of protected water
    },

    # --- Lake Huron / Saginaw Bay ---
    "hyc": {
        "name": "Huron Yacht Club (Caseville)",
        "lat": 43.94475,   # satellite-confirmed (user, 2026-10-20)
        "lon": -83.27861,
        "bearing": 330,  # NNW out of Pigeon River into Saginaw Bay
        "offshore_nm": 2.0,
    },
    "tbyc": {
        "name": "Tawas Bay Yacht Club",
        "lat": 44.2629,
        "lon": -83.4423,
        "bearing": 75,   # ENE into Tawas Bay / Lake Huron (East Tawas)
    },

    # --- Lake Erie (Ohio shore, Catawba Island area) ---
    "catyc": {
        "name": "Catawba Island Club",
        "lat": 41.5340,
        "lon": -82.8620,
        "bearing": 60,   # ENE into Lake Erie from Catawba Island peninsula
    },
}

NM_PER_DEG_LAT = 60.0  # nautical miles per degree of latitude (constant)
DEFAULT_OFFSHORE_NM = 2.0

DF_COLUMNS = ["valid_time", "u10", "v10", "wind_speed_ms", "wind_dir_from", "gust_ms"]


def get_yacht_club_presets():
    """Return yacht club presets for UI integration."""
    return YACHT_CLUB_PRESETS


def project_point(lat, lon, bearing_deg, distance_nm):
    """
    Project a new lat/lon from a starting point given a bearing (degrees
    TRUE, 0=N/90=E) and distance in nautical miles. Simple flat-earth
    approximation - fine for the short distances (a few nm) used here.
    """
    bearing_rad = math.radians(bearing_deg)
    dlat = (distance_nm / NM_PER_DEG_LAT) * math.cos(bearing_rad)
    nm_per_deg_lon = NM_PER_DEG_LAT * math.cos(math.radians(lat))
    dlon = (distance_nm / nm_per_deg_lon) * math.sin(bearing_rad)
    return lat + dlat, lon + dlon


def nm_radius_to_bbox(center_lat, center_lon, radius_nm):
    """Build a [west, east, south, north] bbox of +/- radius_nm around a point."""
    dlat = radius_nm / NM_PER_DEG_LAT
    nm_per_deg_lon = NM_PER_DEG_LAT * math.cos(math.radians(center_lat))
    dlon = radius_nm / nm_per_deg_lon
    return [center_lon - dlon, center_lon + dlon, center_lat - dlat, center_lat + dlat]


def parse_date(date_str):
    """Parse date string in various formats"""
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: {date_str}. Use YYYY-MM-DD format.")


def resolve_sample_point(args):
    """
    Determine the club location, bearing, and resulting offshore sample
    point from either a preset or manual arguments.
    Returns dict with club_lat, club_lon, bearing, sample_lat, sample_lon, name.
    """
    if args.club:
        preset = YACHT_CLUB_PRESETS[args.club]
        club_lat, club_lon, bearing = preset["lat"], preset["lon"], preset["bearing"]
        name = preset["name"]
        default_offshore = preset.get("offshore_nm", DEFAULT_OFFSHORE_NM)
    elif args.lat is not None and args.lon is not None and args.bearing is not None:
        club_lat, club_lon, bearing = args.lat, args.lon, args.bearing
        name = args.name or f"Custom ({club_lat:.4f}, {club_lon:.4f})"
        default_offshore = DEFAULT_OFFSHORE_NM
    else:
        raise ValueError(
            "Specify either --club, or all of --lat/--lon/--bearing for a custom location."
        )

    offshore_nm = args.offshore_nm if args.offshore_nm is not None else default_offshore
    sample_lat, sample_lon = project_point(club_lat, club_lon, bearing, offshore_nm)

    return {
        "name": name,
        "club_lat": club_lat,
        "club_lon": club_lon,
        "bearing": bearing,
        "offshore_nm": offshore_nm,
        "sample_lat": sample_lat,
        "sample_lon": sample_lon,
    }


def normalize_lon(lon):
    """Wrap longitudes to -180..180 (HRRR/cfgrib returns 0..360)."""
    return ((np.asarray(lon) + 180.0) % 360.0) - 180.0


def build_water_box_mask(ref_ds, bbox, land_da=None):
    """
    Boolean (y, x) mask: True where a grid cell is inside `bbox`
    ([west, east, south, north]) and is water (LAND == 0) when a land field is given.
    """
    west, east, south, north = bbox
    lat = np.asarray(ref_ds["latitude"].values)
    lon = normalize_lon(ref_ds["longitude"].values)
    in_box = (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
    if land_da is not None:
        in_box &= np.asarray(land_da.values) < 0.5
    return in_box


def load_water_mask_inputs(ref_time, model, source, bbox):
    """
    Fetch the LAND field for one reference time and return (mask, n_box, n_water).
    n_box counts all cells in the bbox, n_water counts the cells kept.
    """
    H = Herbie(ref_time, model=model, product="sfc", fxx=0, source=source)
    ds = H.xarray(":LAND:surface:")
    ds = ds[0] if isinstance(ds, list) else ds
    land_name = "lsm" if "lsm" in ds else "landn" if "landn" in ds else list(ds.data_vars)[0]
    land_da = ds[land_name]
    in_box_only = build_water_box_mask(ds, bbox, land_da=None)
    mask = build_water_box_mask(ds, bbox, land_da=land_da)
    return mask, int(in_box_only.sum()), int(mask.sum())


def extract_point_series(date_range, point_info, radius_nm, model, source,
                          include_gust, max_threads, batch_size, save_dir):
    """
    Use FastHerbie + xarray to extract a wind time series averaged over the
    water grid cells inside a small box around the sample point.

    Returns (df, report):
      df     - DataFrame with columns DF_COLUMNS, one row per valid_time
      report - dict(expected, retrieved, missing [ISO strings], n_box_cells, n_water_cells)
    """
    search_string = SEARCH_WIND_GUST if include_gust else SEARCH_WIND
    bbox = nm_radius_to_bbox(point_info["sample_lat"], point_info["sample_lon"], radius_nm)

    report = {"expected": len(date_range), "retrieved": 0, "missing": [],
              "n_box_cells": 0, "n_water_cells": 0}
    records = []

    # Water mask built once from the first timestamp (grid is static)
    try:
        mask, n_box, n_water = load_water_mask_inputs(date_range[0], model, source, bbox)
    except Exception as e:
        logger.error(f"Could not build water mask ({e}); aborting this range")
        report["missing"] = [t.isoformat() for t in date_range]
        return pd.DataFrame(columns=DF_COLUMNS), report
    report["n_box_cells"], report["n_water_cells"] = n_box, n_water
    if n_water == 0:
        raise RuntimeError(
            f"No water grid cells within +/-{radius_nm} nm of the sample point "
            f"({point_info['sample_lat']:.4f}, {point_info['sample_lon']:.4f}); "
            f"move the sample point or increase --radius-nm."
        )
    logger.info(f"Box has {n_box} cells, {n_water} water cells kept")

    if batch_size == 0 or batch_size >= len(date_range):
        batches = [date_range]
    else:
        batches = [date_range[i:i + batch_size] for i in range(0, len(date_range), batch_size)]

    logger.info(f"Processing {len(date_range)} time points in {len(batches)} batch(es)")
    logger.info(f"Sample point: {point_info['sample_lat']:.4f}, {point_info['sample_lon']:.4f} "
                f"(box +/-{radius_nm} nm)")

    for batch_num, batch_dates in enumerate(batches):
        batch_start = time.time()
        logger.info(f"=== Batch {batch_num + 1}/{len(batches)}: {len(batch_dates)} files ===")

        try:
            FH = FastHerbie(
                batch_dates.tolist(),
                model=model,
                product="sfc",
                fxx=[0],
                source=source,
                max_threads=max_threads
            )

            existing = FH.file_exists
            logger.info(f"Found {len(existing)}/{len(batch_dates)} files available")
            if not existing:
                logger.warning(f"No files found for batch {batch_num + 1}, skipping")
                continue

            # xarray() pulls cloud-filtered subsets and opens them directly -
            # avoids writing GRIB2 to disk at all for this use case.
            ds = FH.xarray(search_string, max_threads=max_threads)

        except Exception as e:
            logger.error(f"Batch {batch_num + 1} failed: {e}")
            continue

        # ds may be a single Dataset or a list of Datasets depending on Herbie
        # version / whether UGRD+VGRD+GUST landed in separate hypercubes.
        datasets = ds if isinstance(ds, list) else [ds]

        try:
            merged = datasets[0]
            for extra in datasets[1:]:
                merged = merged.merge(extra, compat="override")
        except Exception as e:
            logger.warning(f"Could not merge datasets cleanly ({e}); using first only")
            merged = datasets[0]

        try:
            # Collapse a length-1 step dim so the leading dim is a single time axis
            if "step" in merged.dims and merged.sizes["step"] == 1:
                merged = merged.isel(step=0)

            u = merged["u10"] if "u10" in merged else merged["UGRD"]
            v = merged["v10"] if "v10" in merged else merged["VGRD"]
            spatial = [d for d in u.dims if d in ("y", "x")]
            water = xr_mask(mask, u, spatial)

            u_mean = u.where(water).mean(dim=spatial)
            v_mean = v.where(water).mean(dim=spatial)

            gust_mean = None
            if include_gust:
                gust_var = merged["gust"] if "gust" in merged else merged.get("GUST")
                if gust_var is not None:
                    gust_mean = gust_var.where(water).mean(dim=spatial)

            # valid_time follows the leading time dim; scalar when a single file
            vt = merged["valid_time"] if "valid_time" in merged.coords else merged["time"]
            valid_times = np.atleast_1d(pd.to_datetime(vt.values))
            u_vals = np.atleast_1d(u_mean.values)
            v_vals = np.atleast_1d(v_mean.values)
            gust_vals = (np.atleast_1d(gust_mean.values) if gust_mean is not None
                         else [None] * len(valid_times))
            if not (len(valid_times) == len(u_vals) == len(v_vals) == len(gust_vals)):
                raise ValueError(
                    f"length mismatch: times={len(valid_times)} u={len(u_vals)} "
                    f"v={len(v_vals)} gust={len(gust_vals)}"
                )

            for t, uu, vv, gg in zip(valid_times, u_vals, v_vals, gust_vals):
                speed = math.hypot(uu, vv)
                # Meteorological "from" direction
                wind_dir_from = (math.degrees(math.atan2(-uu, -vv))) % 360
                records.append({
                    "valid_time": t,
                    "u10": uu,
                    "v10": vv,
                    "wind_speed_ms": speed,
                    "wind_dir_from": wind_dir_from,
                    "gust_ms": gg,
                })

        except Exception as e:
            logger.error(f"Failed to extract point data for batch {batch_num + 1}: {e}")
            continue

        batch_time = time.time() - batch_start
        logger.info(f"Batch {batch_num + 1} completed in {batch_time:.1f}s")

    if records:
        df = (pd.DataFrame.from_records(records)
              .drop_duplicates(subset="valid_time")
              .sort_values("valid_time").reset_index(drop=True))
    else:
        df = pd.DataFrame(columns=DF_COLUMNS)

    got = set(pd.to_datetime(df["valid_time"]))
    report["retrieved"] = len(df)
    report["missing"] = [t.isoformat() for t in date_range if t not in got]
    if report["missing"]:
        logger.warning(f"{len(report['missing'])}/{report['expected']} timestamps missing")
    return df, report


def xr_mask(mask, like, spatial_dims):
    """Wrap a numpy (y, x) mask as a DataArray aligned with `like`'s spatial dims."""
    import xarray as xr
    if mask.shape != tuple(like.sizes[d] for d in spatial_dims):
        raise ValueError(f"mask shape {mask.shape} != grid {[like.sizes[d] for d in spatial_dims]}")
    return xr.DataArray(mask, dims=spatial_dims)


def ms_to_knots(ms):
    return ms * 1.9438445


def compute_stats(df):
    """Compute summary statistics from the extracted wind time series (knots)."""
    if df.empty:
        return {}

    speed_kt = ms_to_knots(df["wind_speed_ms"])
    stats = {
        "n_obs": int(len(df)),
        "date_range": (df["valid_time"].min().isoformat(), df["valid_time"].max().isoformat()),
        "mean_speed_kt": float(speed_kt.mean()),
        "median_speed_kt": float(speed_kt.median()),
        "max_speed_kt": float(speed_kt.max()),
        "p90_speed_kt": float(speed_kt.quantile(0.9)),
        "pct_under_5kt": float((speed_kt < 5).mean() * 100),
        "pct_5_to_15kt": float(((speed_kt >= 5) & (speed_kt < 15)).mean() * 100),
        "pct_over_15kt": float((speed_kt >= 15).mean() * 100),
    }

    if df["gust_ms"].notna().any():
        gust_kt = ms_to_knots(df["gust_ms"].dropna())
        stats["mean_gust_kt"] = float(gust_kt.mean())
        stats["max_gust_kt"] = float(gust_kt.max())

    # Dominant direction via circular mean of unit vectors
    rad = np.radians(df["wind_dir_from"])
    sin_mean = np.sin(rad).mean()
    cos_mean = np.cos(rad).mean()
    dominant_dir = math.degrees(math.atan2(sin_mean, cos_mean)) % 360
    resultant_length = math.hypot(sin_mean, cos_mean)  # 0=highly variable, 1=very steady
    stats["dominant_direction_deg"] = float(dominant_dir)
    stats["direction_steadiness_R"] = float(resultant_length)

    return stats


def make_summary_figure(df, stats, title, output_path=None, source_label=""):
    """
    Three-panel summary figure:
      left  — wind rose (polar, full height)
      top-right  — speed histogram with per-bin % labels
      bottom-right — stats table
    """
    speed_kt  = ms_to_knots(df["wind_speed_ms"])
    direction = df["wind_dir_from"].values

    speed_bins   = [0, 5, 10, 15, 20, 25, np.inf]
    speed_labels = ["0-5", "5-10", "10-15", "15-20", "20-25", "25+"]
    colors = plt.cm.viridis(np.linspace(0.1, 0.95, len(speed_labels)))

    fig = plt.figure(figsize=(14, 7))
    gs  = fig.add_gridspec(
        2, 2,
        width_ratios=[1.15, 1],
        left=0.04, right=0.97, top=0.88, bottom=0.09,
        hspace=0.50, wspace=0.28,
    )

    # ── Wind rose ──────────────────────────────────────────────────────────
    n_sectors    = 16
    sector_width = 360.0 / n_sectors
    sector_centers = np.arange(0, 360, sector_width) + sector_width / 2

    shifted_dir = (direction + sector_width / 2) % 360
    sector_idx  = np.floor(shifted_dir / sector_width).astype(int) % n_sectors

    freq_table = np.zeros((n_sectors, len(speed_labels)))
    for s in range(n_sectors):
        mask = sector_idx == s
        if not mask.any():
            continue
        binned = pd.cut(speed_kt[mask], bins=speed_bins, labels=speed_labels, right=False)
        for b, lbl in enumerate(speed_labels):
            freq_table[s, b] = (binned == lbl).sum()
    freq_table_pct = 100 * freq_table / max(len(direction), 1)

    ax_rose = fig.add_subplot(gs[:, 0], projection="polar")
    ax_rose.set_theta_zero_location("N")
    ax_rose.set_theta_direction(-1)
    theta  = np.radians(sector_centers)
    bottom = np.zeros(n_sectors)
    for b, lbl in enumerate(speed_labels):
        ax_rose.bar(
            theta, freq_table_pct[:, b],
            width=np.radians(sector_width * 0.9),
            bottom=bottom, color=colors[b], label=f"{lbl} kt",
            edgecolor="white", linewidth=0.3,
        )
        bottom += freq_table_pct[:, b]
    ax_rose.set_title(title, pad=20, fontsize=11, fontweight="bold")
    ax_rose.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=6,
        fontsize=8, title="Speed (kt)", title_fontsize=8, frameon=False,
    )

    # ── Speed histogram ────────────────────────────────────────────────────
    ax_hist = fig.add_subplot(gs[0, 1])
    binned_all = pd.cut(speed_kt, bins=speed_bins, labels=speed_labels, right=False)
    pct_vals   = [100 * (binned_all == lbl).sum() / max(len(speed_kt), 1)
                  for lbl in speed_labels]
    bars = ax_hist.bar(range(len(speed_labels)), pct_vals, color=colors,
                       edgecolor="white", linewidth=0.5, zorder=3)
    ax_hist.set_xticks(range(len(speed_labels)))
    ax_hist.set_xticklabels(speed_labels, fontsize=8)
    ax_hist.set_ylabel("Frequency (%)", fontsize=8)
    ax_hist.set_xlabel("Wind Speed (kt)", fontsize=8)
    ax_hist.set_title("Speed Distribution", fontsize=9, fontweight="bold")
    ax_hist.tick_params(labelsize=8)
    ax_hist.yaxis.grid(True, alpha=0.3, zorder=0)
    ax_hist.set_axisbelow(True)
    for bar, pct in zip(bars, pct_vals):
        if pct >= 1.5:
            ax_hist.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.4,
                f"{pct:.0f}%", ha="center", va="bottom", fontsize=7.5,
            )
    ax_hist.text(
        0.97, 0.96,
        f"mean {stats['mean_speed_kt']:.1f} kt\nmedian {stats['median_speed_kt']:.1f} kt",
        transform=ax_hist.transAxes, ha="right", va="top", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#bbbbbb", alpha=0.9),
    )

    # ── Stats table ────────────────────────────────────────────────────────
    ax_stats = fig.add_subplot(gs[1, 1])
    ax_stats.axis("off")

    rows = [
        ("Observations",  str(stats["n_obs"])),
        ("Mean speed",    f"{stats['mean_speed_kt']:.1f} kt"),
        ("Median speed",  f"{stats['median_speed_kt']:.1f} kt"),
        ("90th pct",      f"{stats['p90_speed_kt']:.1f} kt"),
        ("Max speed",     f"{stats['max_speed_kt']:.1f} kt"),
        ("< 5 kt",        f"{stats['pct_under_5kt']:.0f}%"),
        ("5-15 kt",       f"{stats['pct_5_to_15kt']:.0f}%"),
        (">= 15 kt",      f"{stats['pct_over_15kt']:.0f}%"),
        ("Dom. dir.",     f"{stats['dominant_direction_deg']:.0f} deg"),
        ("Steadiness R",  f"{stats['direction_steadiness_R']:.2f}  (0=variable, 1=steady)"),
    ]
    if "mean_gust_kt" in stats:
        rows.insert(5, ("Mean gust", f"{stats['mean_gust_kt']:.1f} kt"))
        rows.insert(6, ("Max gust",  f"{stats['max_gust_kt']:.1f} kt"))
    if source_label:
        rows.append(("Data source", source_label))

    tbl = ax_stats.table(cellText=rows, loc="center", cellLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.0, 1.35)
    source_row_idx = len(rows) - 1 if source_label else -1
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor("none")
        if row == source_row_idx:
            cell.set_facecolor("#e8e8e8")
            cell.set_text_props(color="#555555", style="italic")
        else:
            cell.set_facecolor("#f0f0f0" if row % 2 == 0 else "white")
            if col == 0:
                cell.set_text_props(fontweight="bold", color="#333333")
    ax_stats.set_title("Summary Statistics", fontsize=9, fontweight="bold", pad=14)

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    return fig


def print_stats_summary(stats, point_info, radius_nm):
    print("\n===== WIND CLIMATOLOGY SUMMARY =====")
    print(f"Location: {point_info['name']}")
    print(f"Club coords: {point_info['club_lat']:.4f}, {point_info['club_lon']:.4f}")
    print(f"Sample point: {point_info['sample_lat']:.4f}, {point_info['sample_lon']:.4f} "
          f"(bearing {point_info['bearing']}°, +/-{radius_nm} nm box)")
    if not stats:
        print("No data extracted - check date range / region / network access.")
        return
    print(f"Observations: {stats['n_obs']}")
    print(f"Date range: {stats['date_range'][0]} to {stats['date_range'][1]}")
    print(f"\nWind Speed (knots):")
    print(f"  Mean: {stats['mean_speed_kt']:.1f}  Median: {stats['median_speed_kt']:.1f}  "
          f"Max: {stats['max_speed_kt']:.1f}  90th pct: {stats['p90_speed_kt']:.1f}")
    print(f"  < 5kt: {stats['pct_under_5kt']:.1f}%   5-15kt: {stats['pct_5_to_15kt']:.1f}%   "
          f">=15kt: {stats['pct_over_15kt']:.1f}%")
    if "mean_gust_kt" in stats:
        print(f"\nGust (knots): Mean {stats['mean_gust_kt']:.1f}  Max {stats['max_gust_kt']:.1f}")
    print(f"\nDominant direction: {stats['dominant_direction_deg']:.0f}° "
          f"(steadiness R={stats['direction_steadiness_R']:.2f}, 0=variable, 1=steady)")


def print_data_report(reports, start_date, end_date):
    """Print expected vs. retrieved timestamps per year, and the missing ones."""
    if not reports:
        return
    print("\n===== DATA COMPLETENESS (incl. buffer days) =====")
    tot_e = tot_r = 0
    for year, r in sorted(reports.items()):
        tot_e += r["expected"]
        tot_r += r["retrieved"]
        line = f"  {year}: {r['retrieved']}/{r['expected']}"
        if r["missing"]:
            line += f"  missing: {', '.join(m[5:16] for m in r['missing'][:8])}"
            if len(r["missing"]) > 8:
                line += f" (+{len(r['missing']) - 8} more)"
        print(line)
    print(f"  Total: {tot_r}/{tot_e}")


def fmt_local_hour(utc_hour, utc_offset):
    """Convert a UTC hour integer to a 12-hour AM/PM string in local time."""
    h = (utc_hour + utc_offset) % 24
    if h == 0:
        return "12AM"
    if h < 12:
        return f"{h}AM"
    if h == 12:
        return "12PM"
    return f"{h - 12}PM"


def build_date_ranges(start_date, end_date, years, freq, start_hour, end_hour,
                      min_date=None, buffer_days=0):
    """
    Return a list of (DatetimeIndex, year_int) tuples.
    When years is given, the month+day window from start/end_date is applied to
    each requested year. The window is widened by `buffer_days` on each side
    (callers tag the core window separately via `in_core_window`). Hour
    filtering is applied to every range. Years whose (unbuffered) window start
    falls before min_date are warned and skipped.
    """
    year_list = sorted(years) if years else [start_date.year]
    pad = pd.Timedelta(days=buffer_days)
    result = []
    for year in year_list:
        yr_start = start_date.replace(year=year)
        yr_end = end_date.replace(year=year)
        if min_date and yr_start < min_date:
            logger.warning(
                f"Year {year}: window starts {yr_start.date()} before data availability "
                f"({min_date.date()}) - skipping"
            )
            continue
        dr = pd.date_range(yr_start - pad, yr_end + pad, freq=freq)
        if start_hour > 0 or end_hour < 23:
            dr = dr[dr.hour.isin(range(start_hour, end_hour + 1))]
        result.append((dr, year))
    return result


def in_core_window(times, start_date, end_date):
    """Boolean array: True where month/day of each time lies within the core window."""
    t = pd.DatetimeIndex(times)
    md = t.month * 100 + t.day
    lo = start_date.month * 100 + start_date.day
    hi = end_date.month * 100 + end_date.day
    return np.asarray((md >= lo) & (md <= hi))


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate historical HRRR wind climatology at a yacht club location",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")

    # Location - preset or manual
    parser.add_argument("--club", choices=list(YACHT_CLUB_PRESETS.keys()),
                        help="Named yacht club preset")
    parser.add_argument("--lat", type=float, help="Club latitude (manual entry)")
    parser.add_argument("--lon", type=float, help="Club longitude (manual entry)")
    parser.add_argument("--bearing", type=float,
                        help="Compass bearing (deg TRUE) pointing offshore from club (manual entry)")
    parser.add_argument("--name", type=str, help="Display name for manual location")

    parser.add_argument("--offshore-nm", type=float, default=None,
                        help="Distance offshore (nm) along bearing to sample "
                             "(default: club preset value, else 2.0)")
    parser.add_argument("--radius-nm", type=float, default=4.0,
                        help="Radius (nm) of grid-cell box to average around the sample point")

    parser.add_argument("--include-gust", action="store_true",
                        help="Include wind gust data in stats")

    parser.add_argument("--freq", default="1h", choices=["1h", "3h", "6h"],
                        help="Time frequency")
    parser.add_argument("--model", default="hrrr", choices=["hrrr", "gfs"], help="Model to use")
    parser.add_argument("--source", default="aws",
                        choices=["aws", "google", "azure", "nomads"], help="Data source")
    parser.add_argument("--max-threads", type=int, default=50, help="Max download threads")
    parser.add_argument("--batch-size", type=int, default=168,
                        help="Hours per batch (0=all at once)")
    parser.add_argument("--save-dir", default=None, help="Directory for Herbie cache")

    parser.add_argument("--output-dir", default="./output",
                        help="Directory for output plot and CSV")
    parser.add_argument("--output-name", type=str, default=None,
                        help="Base name for output files (without extension)")
    parser.add_argument("--save-csv", action="store_true",
                        help="Deprecated: the time series CSV is now always written")

    parser.add_argument("--start-hour", type=int, default=0, metavar="UTC_HOUR",
                        help="First UTC hour to include (0-23). Michigan EDT=UTC-4: 10 AM local = 14 UTC")
    parser.add_argument("--end-hour", type=int, default=23, metavar="UTC_HOUR",
                        help="Last UTC hour to include (0-23). 4 PM local = 20 UTC")
    parser.add_argument("--utc-offset", type=int, default=0,
                        help="Local timezone offset from UTC (e.g. -4 for EDT, -5 for EST). "
                             "Used for display only — does not shift data selection.")
    parser.add_argument("--tz-abbr", type=str, default="UTC",
                        help="Timezone abbreviation for display (e.g. EDT, EST, CDT).")
    parser.add_argument("--years", type=int, nargs="+", default=None, metavar="YEAR",
                        help="Repeat the same calendar window (month+day from --start/end-date) "
                             "over each listed year and aggregate. "
                             "E.g.: --years 2019 2020 2021 2022 2023")

    parser.add_argument("--window-buffer-days", type=int, default=0,
                        help="Widen the calendar window by this many days on each side. "
                             "Stats are reported for the core window and the buffered window.")

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date).replace(hour=23, minute=0, second=0)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    if start_date > end_date:
        logger.error("Start date must be before end date")
        sys.exit(1)

    min_date = HRRR_START_DATE if args.model == "hrrr" else None

    try:
        point_info = resolve_sample_point(args)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    year_ranges = build_date_ranges(start_date, end_date, args.years, args.freq,
                                    args.start_hour, args.end_hour, min_date=min_date,
                                    buffer_days=args.window_buffer_days)
    total_points = sum(len(dr) for dr, _ in year_ranges)
    years_used = [y for _, y in year_ranges]
    year_label = (f"{min(years_used)}-{max(years_used)}" if len(years_used) > 1
                  else str(years_used[0]))
    hour_tag = (f"_{args.start_hour:02d}-{args.end_hour:02d}Z"
                if (args.start_hour != 0 or args.end_hour != 23) else "")
    logger.info(
        f"Evaluating {point_info['name']}: {total_points} time points across "
        f"{len(year_ranges)} year(s), window "
        f"{start_date.strftime('%m-%d')} to {end_date.strftime('%m-%d')}"
        + (f", hours {args.start_hour:02d}-{args.end_hour:02d} UTC" if hour_tag else "")
    )

    all_dfs, reports = [], {}
    for dr, year in year_ranges:
        if not len(dr):
            logger.warning(f"No time points for year {year} after hour filtering - skipping")
            continue
        logger.info(f"--- Year {year}: {len(dr)} time points ---")
        df_year, report = extract_point_series(
            dr, point_info, args.radius_nm, args.model, args.source,
            args.include_gust, args.max_threads, args.batch_size, args.save_dir
        )
        all_dfs.append(df_year)
        reports[year] = report

    df = (pd.concat(all_dfs, ignore_index=True).sort_values("valid_time").reset_index(drop=True)
          if all_dfs else pd.DataFrame(columns=DF_COLUMNS))
    if not df.empty:
        df["core"] = in_core_window(df["valid_time"], start_date, end_date)

    df_core = df[df["core"]] if not df.empty else df
    stats = compute_stats(df_core)
    print_stats_summary(stats, point_info, args.radius_nm)
    print_data_report(reports, start_date, end_date)

    if df.empty:
        logger.error("No data extracted - skipping plot/CSV output")
        return

    base_name = args.output_name or (
        f"{point_info['name'].replace(' ', '_')}_"
        f"{year_label}_{start_date.strftime('%m%d')}-{end_date.strftime('%m%d')}{hour_tag}"
    )

    plot_path = output_dir / f"{base_name}_windrose.png"
    window_str = f"{start_date.strftime('%b %-d')}–{end_date.strftime('%-d')}"
    if hour_tag:
        local_start = fmt_local_hour(args.start_hour, args.utc_offset)
        local_end   = fmt_local_hour(args.end_hour,   args.utc_offset)
        hour_str = f" {local_start}–{local_end} {args.tz_abbr}"
    else:
        hour_str = ""
    title = f"{point_info['name']}\n{year_label}  {window_str}{hour_str}  (n={len(df_core)})"
    source_label = f"{args.model.upper()} (NOAA) via {args.source.upper()}"
    make_summary_figure(df_core, stats, title, str(plot_path), source_label=source_label)
    logger.info(f"Summary figure saved: {plot_path}")

    stats_path = output_dir / f"{base_name}_stats.json"
    out = {
        "location": point_info,
        "radius_nm": args.radius_nm,
        "water_cells": {str(y): [r["n_water_cells"], r["n_box_cells"]] for y, r in reports.items()},
        "window_core": f"{start_date:%m-%d} to {end_date:%m-%d}",
        "stats": stats,
        "data_report": reports,
    }
    if args.window_buffer_days:
        out["window_buffer_days"] = args.window_buffer_days
        out["stats_buffered"] = compute_stats(df)
    with open(stats_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    logger.info(f"Stats JSON saved: {stats_path}")

    # Always write the series (core + buffer rows, tagged) so stats can be recomputed offline
    csv_path = output_dir / f"{base_name}_timeseries.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"Time series CSV saved: {csv_path}")

    print(f"\nOutputs in: {output_dir}")


if __name__ == "__main__":
    main()
