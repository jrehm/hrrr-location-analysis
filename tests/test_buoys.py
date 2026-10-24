"""Buoy setup: NDBC station search and file download (mocked network), cache coverage, API endpoints."""
import gzip
import io
import urllib.error

import pytest
from fastapi.testclient import TestClient

from hrrr_wind import ndbc
from hrrr_wind.api import app as appmod
from hrrr_wind.config import Buoy, buoy_caches, load_study
from tests.test_study_flow import DEFN, VENUE

XML = b"""<?xml version="1.0"?><stations>
<station id="45020" lat="43.60" lon="-82.00" name="Near" type="buoy" met="y" owner="X"/>
<station id="45999" lat="43.50" lon="-80.00" name="Far" type="buoy" met="y" owner="X"/>
<station id="99999" lat="43.51" lon="-82.00" name="NoWind" type="buoy" met="n" owner="X"/></stations>"""


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def fake_open(body_for):
    def opener(url, timeout=None):
        body = body_for(url)
        if body is None:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return Resp(body)
    return opener


def test_stations_keep_wind_reporters_and_sort_by_distance(tmp_path):
    found = ndbc.stations(fake_open(lambda u: XML), tmp_path / "s.json")
    assert [s["id"] for s in found] == ["45020", "45999"]
    near = ndbc.stations_near(found, 43.5, -82.0, 60)
    assert [s["id"] for s in near] == ["45020"] and near[0]["distance_nm"] == pytest.approx(6.0, abs=0.1)


def test_station_list_falls_back_to_saved_copy_offline(tmp_path):
    cache = tmp_path / "s.json"
    ndbc.stations(fake_open(lambda u: XML), cache)
    def down(url, timeout=None):
        raise OSError("offline")
    assert len(ndbc.stations(down, cache)) == 2
    with pytest.raises(ConnectionError):
        ndbc.stations(down, tmp_path / "none.json")


def test_download_skips_missing_years_and_never_overwrites(tmp_path):
    body = gzip.compress(b"#YY MM DD hh mm\n")
    opener = fake_open(lambda u: body if "h2022" in u else None)
    (tmp_path / "45020h2021.txt.gz").write_bytes(b"mine")
    got = ndbc.download_stdmet("45020", [2021, 2022, 2023], tmp_path, opener)
    assert got == {"saved": [2022], "existing": [2021], "missing": [2023]}
    assert (tmp_path / "45020h2021.txt.gz").read_bytes() == b"mine" and not list(tmp_path.glob("*.part"))
    assert ndbc.file_years(tmp_path.glob("45020h*.txt.gz")) == [2021, 2022]


def test_download_rejects_bad_id_and_truncated_body(tmp_path):
    with pytest.raises(ValueError):
        ndbc.download_stdmet("../x", [2022], tmp_path)
    with pytest.raises(Exception):
        ndbc.download_stdmet("45020", [2022], tmp_path, fake_open(lambda u: b"<html>oops"))
    assert list(tmp_path.iterdir()) == []


def test_archive_index_lists_years_per_station_and_is_cached(tmp_path):
    page = b'<a href="45020h2016.txt.gz">x</a><a href="45020h2017.txt.gz">x</a><a href="CLSM4h2022.txt.gz">x</a><a href="junk.txt">'
    cache = tmp_path / "a.json"
    assert ndbc.archive_years(fake_open(lambda u: page), cache) == {"45020": [2016, 2017], "clsm4": [2022]}
    def down(url, timeout=None):
        raise OSError("offline")
    assert ndbc.archive_years(down, cache)["45020"] == [2016, 2017]                      # fresh copy: no request
    assert ndbc.archive_years(down, cache, now=cache.stat().st_mtime + 9 * 86400)["clsm4"] == [2022]   # stale copy, offline
    with pytest.raises(ConnectionError):
        ndbc.archive_years(down, tmp_path / "none.json")


def test_anemometer_height_is_read_from_the_station_page():
    page = b"<b>Site elevation:</b> 175 m<br>\n\t\t<b>Anemometer height:</b> 10 m above site elevation<br>"
    assert ndbc.anemometer_height("clsm4", fake_open(lambda u: page)) == 10.0
    assert ndbc.anemometer_height("45020", fake_open(lambda u: b"<b>Anemometer height:</b> 2.4 m above")) == 2.4
    assert ndbc.anemometer_height("zzzz9", fake_open(lambda u: b"<html>no height</html>")) is None
    with pytest.raises(ValueError):
        ndbc.anemometer_height("../x")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "STUDIES_DIR", tmp_path)
    monkeypatch.setattr(appmod, "try_land_mask", lambda *a: None)
    monkeypatch.setattr(ndbc, "stations", lambda *a, **k: ndbc.parse_stations(XML))
    monkeypatch.setattr(ndbc, "archive_years", lambda *a, **k: {"45020": [2021, 2022], "45999": [2023]})
    monkeypatch.delenv("HRRR_WIND_READONLY", raising=False)
    appmod.get_study.cache_clear()
    c = TestClient(appmod.app)
    c.post("/api/studies", json={"slug": "demo", "definition": DEFN})
    yield c, tmp_path
    appmod.get_study.cache_clear()


def test_coverage_inside_and_outside_the_venue_box(api):
    c, root = api
    s = load_study(root / "demo" / "study.toml")
    inside = buoy_caches(s, "abc", "45020", 43.6, -82.0)
    assert [x["extra"] for x in inside] == [False] and inside[0]["tag"] == "sep_2022_2023"
    outside = buoy_caches(s, "abc", "45999", 43.5, -80.0)
    assert outside == [{"tag": "val_45999_0905_0917", "start": "09-05", "end": "09-17", "extra": True}]


def test_nearby_lists_coverage_and_extra_download_size(api):
    c, _ = api
    r = c.get("/api/studies/demo/venues/abc/buoys", params={"radius_nm": 150}).json()
    by = {s["id"]: s for s in r["stations"]}
    assert by["45020"]["years"] == [2022] and by["45999"]["years"] == [2023]
    assert by["45020"]["covered"] and by["45020"]["extra_files"] == 0 and by["45020"]["anem_known"]
    assert not by["45999"]["covered"] and by["45999"]["extra_files"] == 2 * 24 * 13


def test_set_buoy_writes_study_and_starts_job_remove_keeps_files(api, monkeypatch):
    c, root = api
    started = []
    monkeypatch.setattr(appmod.MANAGER, "submit", lambda *a: started.append(a[3:]) or type("J", (), {"public": lambda s: {"id": "j"}})())
    r = c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2.4})
    assert r.status_code == 202 and started == [("buoy", {"venue": "abc"})]
    b = c.get("/api/studies/demo").json()["buoys"][0]
    assert (b["id"], b["anem_m"]) == ("45020", 2.4)
    assert b["sample_distance_nm"] == pytest.approx(6.3, abs=0.1)    # sample point 2 nm east of the club, buoy 6 nm north: hypot(2, 6)
    s = load_study(root / "demo" / "study.toml")
    assert s.buoys["abc"].caches == ("sep_2022_2023",) and s.buoys["abc"].dir == "Buoy_45020"
    assert s.fingerprint() == load_study(root / "demo" / "study.toml").fingerprint()
    (root / "demo" / "data" / "buoys" / "Buoy_45020").mkdir(parents=True)
    keep = root / "demo" / "data" / "buoys" / "Buoy_45020" / "45020h2022.txt.gz"
    keep.write_bytes(b"x")
    assert c.delete("/api/studies/demo/buoys/abc").json()["buoys"] == [] and keep.exists()


def test_set_buoy_rejects_unknown_station_venue_and_write_modes(api, monkeypatch):
    c, _ = api
    assert c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "00000", "anem_m": 2}).status_code == 422
    assert c.post("/api/studies/demo/buoys", json={"venue": "zzz", "id": "45020", "anem_m": 2}).status_code == 404
    assert c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": -1}).status_code == 422
    monkeypatch.setattr(ndbc, "archive_years", lambda *a, **k: {"45020": [2001]})
    assert c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2}).status_code == 422
    monkeypatch.setattr(ndbc, "archive_years", lambda *a, **k: {"45020": [2022]})
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    calls = [c.get("/api/studies/demo/venues/abc/buoys"), c.delete("/api/studies/demo/buoys/abc"),
             c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2})]
    assert [r.status_code for r in calls] == [403] * 3
    monkeypatch.delenv("HRRR_WIND_READONLY")
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset({"demo"}))
    assert c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2}).status_code == 403


def test_buoy_job_needs_a_buoy_for_the_venue(api):
    c, _ = api
    assert c.post("/api/studies/demo/jobs", json={"kind": "buoy", "params": {"venue": "abc"}}).status_code == 422


def test_buoy_job_builds_the_buoy_command(api, monkeypatch):
    c, root = api
    monkeypatch.setattr(appmod.MANAGER, "submit", lambda *a: type("J", (), {"public": lambda s: {}})())
    c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2.4}) 
    study = appmod.get_study("demo")
    from hrrr_wind.jobs import JobManager, build_command
    cmds = []
    m = JobManager(command_builder=lambda *a: cmds.append(build_command(*a)) or ["true"])
    m.submit("demo", study, root / "demo" / "study.toml", "buoy", {"venue": "abc"})
    assert cmds[0][-3:] == ["buoy", "--venue", "abc"]


def test_results_made_before_buoys_were_added_stay_current(api):
    c, root = api
    s0 = appmod.get_study("demo")
    old = s0.fingerprint(buoys=[])                       # what older code stored for a study without buoys
    out = root / "demo" / "outputs"
    out.mkdir(exist_ok=True)
    (out / "summary_stats.csv").write_text("pct_5_20\n")
    (out / "analysis_state.json").write_text('{"fingerprint": "%s"}' % old)
    assert not appmod.is_stale("demo", s0, out / "summary_stats.csv")
    s1 = load_study(root / "demo" / "study.toml")
    s1.buoys["abc"] = Buoy("abc", "45020", 43.6, -82.0, 2.4, "d", "p", ("t",))
    assert not appmod.is_stale("demo", s1, out / "summary_stats.csv")


def test_anemometer_endpoint_page_known_default_and_read_only(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(ndbc, "anemometer_height", lambda sid: 10.0)
    assert c.get("/api/ndbc/clsm4/anemometer").json() == {"anem_m": 10.0, "source": "page"}
    monkeypatch.setattr(ndbc, "anemometer_height", lambda sid: None)
    assert c.get("/api/ndbc/45020/anemometer").json() == {"anem_m": 2.4, "source": "known"}
    assert c.get("/api/ndbc/agcm4/anemometer").json() == {"anem_m": 4.0, "source": "default"}
    def down(sid):
        raise ConnectionError("offline")
    monkeypatch.setattr(ndbc, "anemometer_height", down)
    assert c.get("/api/ndbc/agcm4/anemometer").json()["source"] == "default"
    assert c.get("/api/ndbc/..%2Fx/anemometer").status_code in (404, 405, 422)
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    assert c.get("/api/ndbc/clsm4/anemometer").status_code == 403


def test_unused_caches_and_buoy_folders_can_be_deleted_used_ones_cannot(api, monkeypatch):
    c, root = api
    out, buoys = root / "demo" / "outputs", root / "demo" / "data" / "buoys"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("cache_abc_sep_2022_2023.npz", "cache_gone_sep_x.npz", "cache_abc_val_45020_0905_0917.npz"):
        (out / name).write_bytes(b"x" * 10)
    for d in ("Buoy_45020", "Buoy_old"):
        (buoys / d).mkdir(parents=True)
        (buoys / d / "f.txt.gz").write_bytes(b"x")
    monkeypatch.setattr(appmod.MANAGER, "submit", lambda *a: type("J", (), {"public": lambda s: {}})())
    c.post("/api/studies/demo/buoys", json={"venue": "abc", "id": "45020", "anem_m": 2.4})   # uses the window cache + Buoy_45020
    meta = c.get("/api/studies/demo").json()
    by = {x["file"]: x for x in meta["caches"]}
    assert by["cache_abc_sep_2022_2023.npz"]["used_by"] == "a window"
    assert by["cache_gone_sep_x.npz"]["used_by"] is None and not by["cache_gone_sep_x.npz"]["in_study"]
    assert {b["dir"]: b["used"] for b in meta["buoy_data"]} == {"Buoy_45020": True, "Buoy_old": False}

    assert c.delete("/api/studies/demo/caches/cache_abc_sep_2022_2023.npz").status_code == 409
    assert c.delete("/api/studies/demo/caches/cache_nope_x.npz").status_code == 404
    assert c.delete("/api/studies/demo/caches/..%2Fstudy.toml").status_code in (404, 405, 422)
    assert c.delete("/api/studies/demo/buoy-data/Buoy_45020").status_code == 409
    assert c.delete("/api/studies/demo/buoy-data/..").status_code in (404, 405, 422)
    assert (root / "demo" / "study.toml").exists() and (out / "cache_abc_sep_2022_2023.npz").exists()

    assert c.delete("/api/studies/demo/caches/cache_gone_sep_x.npz").json()["deleted"] == "cache_gone_sep_x.npz"
    assert c.delete("/api/studies/demo/buoy-data/Buoy_old").status_code == 200
    assert not (out / "cache_gone_sep_x.npz").exists() and not (buoys / "Buoy_old").exists() and (buoys / "Buoy_45020").exists()


def test_data_delete_refused_when_read_only_locked_or_busy(api, monkeypatch):
    c, root = api
    out = root / "demo" / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cache_gone_sep_x.npz").write_bytes(b"x")
    url = "/api/studies/demo/caches/cache_gone_sep_x.npz"
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    assert c.delete(url).status_code == 403
    monkeypatch.delenv("HRRR_WIND_READONLY")
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset({"demo"}))
    assert c.delete(url).status_code == 403
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset())
    busy = type("J", (), {"study_id": "demo", "public": lambda self: {}})()
    monkeypatch.setattr(appmod.MANAGER, "running", lambda: busy)
    assert c.delete(url).status_code == 409 and (out / "cache_gone_sep_x.npz").exists()


def test_buoy_folder_outside_the_study_is_never_listed(api, monkeypatch, tmp_path_factory):
    c, root = api
    shared = tmp_path_factory.mktemp("shared") / "buoys"
    (shared / "Buoy_x").mkdir(parents=True)
    monkeypatch.setenv("HRRR_WIND_BUOY_DIR", str(shared))
    appmod.get_study.cache_clear()
    assert c.get("/api/studies/demo").json()["buoy_data"] == []
    assert c.delete("/api/studies/demo/buoy-data/Buoy_x").status_code == 404 and (shared / "Buoy_x").exists()
