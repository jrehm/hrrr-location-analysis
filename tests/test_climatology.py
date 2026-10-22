from datetime import datetime

import numpy as np
import pandas as pd

from hrrr_wind import climatology as clim


def test_normalize_lon_wraps_0_360():
    out = clim.normalize_lon([277.0, 10.0, 180.0])
    assert np.allclose(out, [-83.0, 10.0, -180.0])


def test_project_point_due_east_and_north():
    lat, lon = clim.project_point(43.0, -83.0, 90, 6.0)
    assert abs(lat - 43.0) < 1e-9 and lon > -83.0
    lat, lon = clim.project_point(43.0, -83.0, 0, 6.0)
    assert abs(lat - 43.1) < 1e-9 and abs(lon + 83.0) < 1e-9


def test_bbox_order_and_size():
    w, e, s, n = clim.nm_radius_to_bbox(43.0, -83.0, 4.0)
    assert w < -83.0 < e and s < 43.0 < n
    assert abs((n - s) - 2 * 4.0 / 60.0) < 1e-9


def test_water_box_mask_excludes_land_and_outside():
    import xarray as xr
    lat = np.array([[43.0, 43.0, 43.0], [43.05, 43.05, 43.05]])
    lon = np.array([[-83.1, -83.0, -82.9]] * 2) % 360  # 0..360 like cfgrib
    ds = xr.Dataset(coords={"latitude": (("y", "x"), lat), "longitude": (("y", "x"), lon)})
    land = xr.DataArray(np.array([[0, 0, 1], [0, 1, 0]]), dims=("y", "x"))
    bbox = [-83.05, -82.85, 42.99, 43.06]  # excludes the -83.1 column
    m = clim.build_water_box_mask(ds, bbox, land_da=land)
    assert m.tolist() == [[False, True, False], [False, False, True]]
    assert clim.build_water_box_mask(ds, bbox).sum() == 4


def test_build_date_ranges_hours_and_buffer():
    start, end = datetime(2024, 9, 8), datetime(2024, 9, 14, 23)
    (dr, yr), = clim.build_date_ranges(start, end, [2024], "1h", 14, 20)
    assert yr == 2024 and len(dr) == 7 * 7
    (dr_b, _), = clim.build_date_ranges(start, end, [2024], "1h", 14, 20, buffer_days=3)
    assert len(dr_b) == 13 * 7
    assert in_core_count(dr_b, start, end) == 49


def in_core_count(times, start, end):
    return int(clim.in_core_window(times, start, end).sum())


def test_build_date_ranges_skips_pre_archive_year():
    start, end = datetime(2014, 9, 8), datetime(2014, 9, 14, 23)
    out = clim.build_date_ranges(start, end, [2014, 2015], "1h", 14, 20,
                                 min_date=clim.HRRR_START_DATE)
    assert [y for _, y in out] == [2015]


def test_compute_stats_circular_mean_wraps_north():
    df = pd.DataFrame({
        "valid_time": pd.date_range("2024-09-08 14:00", periods=2, freq="1h"),
        "wind_speed_ms": [4.0, 4.0],
        "wind_dir_from": [350.0, 10.0],
        "gust_ms": [None, None],
    })
    st = clim.compute_stats(df)
    d = st["dominant_direction_deg"]
    assert min(d, 360 - d) < 1e-6
    assert st["direction_steadiness_R"] > 0.98
