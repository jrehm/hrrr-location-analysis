"""build_cache end-to-end with the network replaced by fakes (needs xarray)."""
import sys
import types

import numpy as np
import pandas as pd
import pytest

xr = pytest.importorskip("xarray")

from hrrr_wind import cache as cachemod  # noqa: E402


class FakeHerbie:
    """Stands in for herbie.Herbie: serves a tiny grid around Caseville with one land column."""
    def __init__(self, ref_time, *a, **k):
        pd.Timestamp(ref_time)      # the real Herbie parses its date argument; garbage must fail

    def xarray(self, search):
        lat = 43.94 + 0.03 * np.arange(8)[:, None] * np.ones((1, 8))
        lon = (-83.28 + 0.04 * np.arange(8)[None, :] * np.ones((8, 1))) % 360   # 0..360 like cfgrib
        land = np.zeros((8, 8)); land[:, :2] = 1
        return xr.Dataset({"lsm": (("y", "x"), land)},
                          coords={"latitude": (("y", "x"), lat), "longitude": (("y", "x"), lon)})


def fake_fetch(dates, source, max_threads=50):
    vt = pd.DatetimeIndex(dates)
    n = len(vt)
    return vt, xr.DataArray(np.full((n, 8, 8), 3.0, "float32"), dims=("time", "y", "x")), \
        xr.DataArray(np.zeros((n, 8, 8), "float32"), dims=("time", "y", "x"))


def test_build_cache_writes_cache_checkpoint_and_progress(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "herbie", types.SimpleNamespace(Herbie=FakeHerbie))
    monkeypatch.setattr(cachemod, "fetch_wind", fake_fetch)
    seen = []
    cachemod.build_cache(tmp_path, ["hyc"], [2020, 2021], "t", "09-08", "09-09", chunk_hours=24,
                         progress=lambda y, i, n: seen.append((y, i, n)))
    c = cachemod.load_cache(tmp_path, "hyc", "t")
    assert len(c["time"]) == 2 * 2 * 24 and c["u"].shape[1:] == c["land"].shape
    assert (tmp_path / "ckpt_t" / "year_2020.npz").exists()
    assert (tmp_path / "missing_t.json").read_text().count("[]") == 2     # nothing missing
    assert seen == [(2020, 0, 2), (2020, 1, 2), (2021, 0, 2), (2021, 1, 2)]
    # rerun resumes entirely from checkpoints and gives the same cache
    cachemod.build_cache(tmp_path, ["hyc"], [2020, 2021], "t", "09-08", "09-09", chunk_hours=24)
    assert len(cachemod.load_cache(tmp_path, "hyc", "t")["time"]) == 96


def test_memory_cap_aborts_cleanly(monkeypatch):
    monkeypatch.setattr(cachemod, "current_rss_gb", lambda: 9.0)
    with pytest.raises(cachemod.MemoryLimitExceeded):
        cachemod.check_memory(4.0, "unit test")
