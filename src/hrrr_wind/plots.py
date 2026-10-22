"""Figures. Each function returns a matplotlib Figure; callers decide whether to save or show."""
import numpy as np
import pandas as pd

from hrrr_wind import climatology as clim
from hrrr_wind.config import KT


def summary_figure(study, venue, season, race):
    """Wind rose + speed histogram + stats table for one venue/season (racing hours)."""
    df = pd.DataFrame({"wind_speed_ms": race["spd_kt"] / KT, "wind_dir_from": race["dir"],
                       "gust_ms": np.nan})
    st = clim.compute_stats(df.assign(valid_time=race["time"]))
    y0, y1 = min(study.years), max(study.years)
    title = (f"{study.venues[venue].name}\n{season.upper()} core window, "
             f"{y0}-{y1}, {study.race_label} (n={len(race)})")
    return clim.make_summary_figure(df, st, title, None, source_label="HRRR F00 via AWS")


def diurnal_figure(study, diurnal):
    """Mean wind by local hour for each (venue, season) series."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for (venue, season), ser in diurnal.items():
        local = pd.Series(ser.values, index=(ser.index + study.utc_offset) % 24).sort_index()
        ax.plot(local.index, local.values, marker="o", label=f"{venue.upper()} {season}")
    ax.axvspan(study.race_start + study.utc_offset, study.race_end + study.utc_offset,
               color="grey", alpha=0.12, label="racing hours")
    ax.set_xlabel(f"Local hour ({study.tz_abbr})"); ax.set_ylabel("Mean wind (kt)")
    ax.set_xticks(range(0, 24, 3)); ax.set_xlim(-0.5, 23.5)
    ax.set_title(f"Diurnal mean wind, core windows {min(study.years)}-{max(study.years)}")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4, frameon=False)
    return fig


def validation_figure(scatter):
    """HRRR vs buoy scatter (racing hours) per venue; ``scatter`` = {venue: (pairs, buoy_id)}."""
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(scatter), figsize=(11, 5), squeeze=False)
    for ax, (venue, (sub, buoy_id)) in zip(axes[0], scatter.items()):
        ax.scatter(sub["obs_kt"], sub["hrrr_kt"], s=6, alpha=0.35)
        lim = max(sub["obs_kt"].max(), sub["hrrr_kt"].max()) + 1
        ax.plot([0, lim], [0, lim], "k--", lw=1)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_xlabel(f"Buoy {buoy_id} wind adj. to 10 m (kt)")
        ax.set_ylabel("HRRR F00 (kt)")
        ax.set_title(f"{venue.upper()}: racing hours, n={len(sub)}")
        ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig
