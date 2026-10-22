import numpy as np
import pandas as pd
import pytest

from hrrr_wind import stats, validation
from hrrr_wind.cache import box_series
from hrrr_wind.config import load_study


def test_study_config_loads():
    s = load_study()
    assert list(s.venues) == ["gtyc", "hyc"]
    assert s.race_utc == range(14, 21) and s.race_label == "10AM-4PM EDT"
    assert [w.fit_label for w in s.windows] == ["Sep", "Sep", "Jun"]
    lat, lon = s.sample_point("gtyc")
    assert 44.82 < lat < 44.83 and -85.62 < lon < -85.61


def test_summarize_bins_and_direction():
    d = stats.summarize([2, 6, 10, 16, 21], [0, 0, 0, 0, 0])
    assert d["pct_lt5"] == 20 and d["pct_5_15"] == 40 and d["pct_15_20"] == 20
    assert d["pct_ge20"] == 20 and d["R"] == pytest.approx(1.0) and d["dom_dir"] % 360 == 0


def _day(speeds, date="2020-09-08"):
    return pd.DataFrame({"spd_kt": speeds, "hour": range(14, 14 + len(speeds)),
                         "date": pd.Timestamp(date)})


def test_usable_day_needs_three_consecutive_sweet_spot_hours():
    good = _day([4, 6, 7, 8, 3, 3, 3])
    bad = _day([6, 7, 3, 8, 9, 3, 3], "2020-09-09")
    pct, n = stats.usable_day_share(pd.concat([good, bad]), race_hours=7)
    assert (pct, n) == (50.0, 2)
    assert stats.usable_day_share(_day([6, 7, 8]), race_hours=7)[1] == 0   # incomplete day


def test_box_series_water_only_and_nearest():
    lat = np.array([[44.0, 44.0]]); lon = np.array([[-85.0, -85.0]])
    cache = {"lat": lat, "lon": lon, "land": np.array([[1.0, 0.0]]),
             "u": np.array([[[3.0, -6.0]]]), "v": np.zeros((1, 1, 2)),
             "time": np.array(["2020-09-08T14"], dtype="datetime64[ns]")}
    df, n = box_series(cache, 44.0, -85.0, 4.0)
    assert n == 1 and df["spd_kt"].iloc[0] == pytest.approx(6 * 1.9438445)
    assert box_series(dict(cache, land=np.ones((1, 2))), 44.0, -85.0, 4.0)[0] is None


def test_quantile_map_and_height_factor():
    x = np.linspace(1, 10, 200)
    assert np.allclose(validation.quantile_map(x, x * 1.5, x), x * 1.5, atol=0.2)
    assert validation.height_factor(10.0) == pytest.approx(1.0)
    assert 1.1 < validation.height_factor(2.4) < 1.2
