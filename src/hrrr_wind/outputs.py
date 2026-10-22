"""Write analysis and validation results to the study's output folder (CSV + PNG)."""
import matplotlib.pyplot as plt

from hrrr_wind import plots


def _save(fig, path, **kw):
    fig.savefig(path, dpi=150, bbox_inches="tight", **kw)
    plt.close(fig)


def write_analysis(study, res):
    out = study.out_dir
    out.mkdir(parents=True, exist_ok=True)
    res.summary.to_csv(out / "summary_stats.csv", index=False)
    res.per_year.to_csv(out / "per_year_stats.csv", index=False)
    res.quality.to_csv(out / "data_quality.csv", index=False)
    for (season, a, b), df in res.paired.items():
        df.to_csv(out / f"paired_{season}_{a}_minus_{b}.csv", index=False)
    res.band.to_csv(out / "sensitivity_band.csv", index=False)
    for (venue, season), race in res.series.items():
        fig = plots.summary_figure(study, venue, season, race)
        fig.savefig(out / f"summary_{venue}_{season}.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    _save(plots.diurnal_figure(study, res.diurnal), out / "diurnal.png")


def write_validation(study, val):
    out = study.out_dir
    out.mkdir(parents=True, exist_ok=True)
    _save(plots.validation_figure(val.scatter), out / "validation_scatter.png")
    val.metrics.to_csv(out / "validation_metrics.csv", index=False)
    val.adjusted.to_csv(out / "bias_adjusted_summary.csv", index=False)
