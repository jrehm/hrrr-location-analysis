"""Golden-file regression: re-run the GTYC/HYC study from the committed wind caches and
check every CSV against the committed results. Slow (~2-3 min); run with `pytest -m golden`.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
STUDY_OUT = REPO / "studies" / "gtyc_hyc_2028" / "outputs"
CSVS = ["summary_stats", "per_year_stats", "paired_sep_hyc_minus_gtyc", "sensitivity_band",
        "validation_metrics", "bias_adjusted_summary", "data_quality"]


@pytest.mark.golden
def test_study_reproduces_committed_csvs(tmp_path):
    out = tmp_path / "out"
    shutil.copytree(STUDY_OUT, out)
    for name in CSVS:
        (out / f"{name}.csv").unlink()
    env = {**os.environ, "HRRR_WIND_OUT": str(out), "PYTHONPATH": str(REPO / "src"),
           "MPLBACKEND": "Agg"}
    for cmd in ("analyze", "validate"):
        subprocess.run([sys.executable, "-W", "ignore", "-m", "hrrr_wind.venue_analysis", cmd],
                       env=env, check=True, capture_output=True, timeout=900)
    for name in CSVS:
        new = pd.read_csv(out / f"{name}.csv")
        old = pd.read_csv(STUDY_OUT / f"{name}.csv")
        pd.testing.assert_frame_equal(new, old, rtol=1e-6, atol=1e-9, obj=name)
