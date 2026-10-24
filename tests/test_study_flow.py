"""New study / add venue: definition validation, TOML writing, API write endpoints, no-buoy pipeline."""
import tomllib

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from hrrr_wind import config
from hrrr_wind.api import app as appmod
from hrrr_wind.config import DefinitionError, dump_toml, validate_definition, write_study

VENUE = {"key": "abc", "name": "ABC Sailing Club", "lat": 43.5, "lon": -82.0,
         "bearing": 90, "offshore_nm": 2.0, "radius_nm": 4.0}
DEFN = {"name": "Test study", "years": [2022, 2023], "race_hours_utc": [14, 20], "utc_offset": -4,
        "tz_abbr": "EDT", "venues": [VENUE],
        "windows": [{"venue": "abc", "season": "sep", "core": ["09-08", "09-14"]}]}
WINDOW = {"venue": "abc", "season": "sep", "core": ["09-08", "09-14"]}


def test_valid_definition_gets_tags_and_defaults():
    c = validate_definition(DEFN)
    assert c["windows"][0]["cache_tag"] == "sep_2022_2023"
    assert c["venues"][0]["sensitivity_bearings"] == [90.0] and c["sensitivity"]["radius_nm"] == [2.0, 4.0, 6.0]
    assert config.buffered_span(["09-08", "09-14"]) == ("09-05", "09-17")


@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": "x\x00y"}, {"name": "a" * 200}, {"years": [2010]}, {"years": [2022.5]},
    {"years": []}, {"years": [True]}, {"race_hours_utc": [20, 14]}, {"utc_offset": 99},
    {"tz_abbr": "E DT\n"}, {"extra": 1}, {"venues": []},
    {"venues": [{**VENUE, "key": "../x"}]}, {"venues": [{**VENUE, "key": "ABC"}]},
    {"venues": [{**VENUE, "lat": float("nan")}]}, {"venues": [{**VENUE, "lat": 80}]},
    {"venues": [{**VENUE, "lon": 10}]}, {"venues": [{**VENUE, "bearing": 360}]},
    {"venues": [{**VENUE, "offshore_nm": 31}]}, {"venues": [{**VENUE, "offshore_nm": 0}]},
    {"venues": [{**VENUE, "radius_nm": 11}]}, {"venues": [VENUE, VENUE]},
    {"venues": [{**VENUE, "name": "x\ny"}]},
    {"windows": []}, {"windows": [{**WINDOW, "venue": "zzz"}]},
    {"windows": [{**WINDOW, "season": "../s"}]}, {"windows": [{**WINDOW, "core": ["09-14", "09-08"]}]},
    {"windows": [{**WINDOW, "core": ["02-30", "03-05"]}]},
    {"windows": [{**WINDOW, "core": ["01-01", "01-05"]}]},       # buffer leaves the year
    {"windows": [{**WINDOW, "core": ["06-01", "08-30"]}]},       # too long
    {"windows": [{**WINDOW, "cache_tag": "../x"}]},
    {"pairs": [{"a": "abc", "b": "abc", "season": "sep"}]},
    {"buoys": [{"venue": "abc", "id": "1", "lat": 1, "lon": 1, "anem_m": 2, "dir": "../..",
                "pattern": "*.txt", "caches": []}]},
])
def test_hostile_definitions_are_rejected(change):
    with pytest.raises(DefinitionError):
        validate_definition({**DEFN, **change})


def _many(n):
    venues = [{**VENUE, "key": f"v{i}", "name": f"Club {i}", "lon": -82.0 - i * 0.1} for i in range(n)]
    return {**DEFN, "venues": venues, "windows": [{**WINDOW, "venue": v["key"]} for v in venues]}


def test_nine_venues_is_the_limit():
    """Nine series colors exist in the UI, so a study holds at most nine venues and nine windows."""
    assert len(validate_definition(_many(9))["venues"]) == 9
    with pytest.raises(DefinitionError, match="at most 9 venues"):
        validate_definition(_many(10))
    extra = {**_many(9), "windows": _many(9)["windows"] + [{**WINDOW, "venue": "v0", "season": "jun", "core": ["06-14", "06-21"]}]}
    with pytest.raises(DefinitionError, match="at most 9 windows"):
        validate_definition(extra)


def test_toml_round_trip_with_hostile_text(tmp_path):
    name = 'Q"uote \\ back # hash [x] = "y" é日本'
    d = {**DEFN, "name": name, "venues": [{**VENUE, "name": 'Club "A"\\\\ ] [[venues]] key = "evil"'}]}
    written = write_study(tmp_path / "s" / "study.toml", d)
    back = tomllib.loads((tmp_path / "s" / "study.toml").read_text(encoding="utf-8"))
    assert back == written and back["name"] == name and len(back["venues"]) == 1
    ref = validate_definition(config.study_dict(config.DEFAULT_STUDY))
    assert tomllib.loads(dump_toml(ref)) == ref


def test_venue_without_preset_needs_position():
    assert config.Venue("gtyc", 20, 3, 4).lat == pytest.approx(44.78034)
    with pytest.raises(ValueError):
        config.Venue("abc", 20, 3, 4)
    with pytest.raises(DefinitionError):
        validate_definition({**DEFN, "venues": [{k: v for k, v in VENUE.items()
                                                 if k not in ("name", "lat", "lon")}]})


def test_write_backup_keeps_previous_file(tmp_path):
    p = tmp_path / "study.toml"
    write_study(p, DEFN)
    first = p.read_text()
    write_study(p, {**DEFN, "name": "Renamed"}, backup=True)
    assert (tmp_path / "study.toml.bak").read_text() == first and "Renamed" in p.read_text()


# -- API -----------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "STUDIES_DIR", tmp_path)
    monkeypatch.setattr(appmod, "try_land_mask", lambda *a: None)
    monkeypatch.delenv("HRRR_WIND_READONLY", raising=False)
    appmod.get_study.cache_clear()
    yield TestClient(appmod.app), tmp_path
    appmod.get_study.cache_clear()


def test_create_study_then_conflict(api):
    c, root = api
    r = c.post("/api/studies", json={"slug": "demo", "definition": DEFN})
    assert r.status_code == 201 and r.json()["venues"][0]["name"] == "ABC Sailing Club"
    assert (root / "demo" / "study.toml").exists()
    assert c.post("/api/studies", json={"slug": "demo", "definition": DEFN}).status_code == 409
    assert c.get("/api/studies/demo/results").json()["summary"] == []
    g = c.get("/api/studies/demo/geometry", params=dict(venue="abc", bearing=90, offshore_nm=2)).json()
    assert g["cells"] == [] and g["has_grid"] is False
    assert c.get("/api/studies/demo/windrose", params=dict(venue="abc", season="sep")).json()["no_data"]
    assert c.get("/api/studies/demo/diurnal").json() == []


@pytest.mark.parametrize("slug", ["../evil", "A", "x", "a/b", "demo.toml", ""])
def test_create_rejects_bad_slug(api, slug):
    c, root = api
    assert c.post("/api/studies", json={"slug": slug, "definition": DEFN}).status_code == 422
    assert list(root.iterdir()) == []


def test_create_rejects_bad_definition(api):
    c, root = api
    r = c.post("/api/studies", json={"slug": "demo", "definition": {**DEFN, "years": [1999]}})
    assert r.status_code == 422 and not (root / "demo").exists()


def test_read_only_blocks_every_write_endpoint(api, monkeypatch):
    c, root = api
    c.post("/api/studies", json={"slug": "demo", "definition": DEFN})
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    body = {"venue": {**VENUE, "key": "two"}, "windows": [{"season": "sep", "core": ["09-08", "09-14"]}]}
    calls = [c.post("/api/studies", json={"slug": "other", "definition": DEFN}),
             c.post("/api/studies/demo/venues", json=body),
             c.post("/api/studies/demo/jobs", json={"kind": "run_study"}),
             c.post("/api/preview/geometry", json=dict(lat=43.5, lon=-82, bearing=90, offshore_nm=2))]
    assert [r.status_code for r in calls] == [403] * 4 and not (root / "other").exists()


def test_add_venue_backs_up_and_leaves_existing_data_alone(api):
    c, root = api
    c.post("/api/studies", json={"slug": "demo", "definition": DEFN})
    out = root / "demo" / "outputs"
    out.mkdir(exist_ok=True)
    (out / "cache_abc_sep_2022_2023.npz").write_bytes(b"precious")
    before = (root / "demo" / "study.toml").read_text()
    body = {"venue": {**VENUE, "key": "two", "name": "Second", "lon": -82.5},
            "windows": [{"season": "sep", "core": ["09-08", "09-14"]}]}
    r = c.post("/api/studies/demo/venues", json=body)
    assert r.status_code == 201 and [v["key"] for v in r.json()["venues"]] == ["abc", "two"]
    assert (root / "demo" / "study.toml.bak").read_text() == before
    assert (out / "cache_abc_sep_2022_2023.npz").read_bytes() == b"precious"
    tags = {w.venue: w for w in appmod.get_study("demo").windows}
    assert tags["two"].cache_tag == "sep_2022_2023_two"       # own tag: never reuses abc's checkpoints
    assert [p["tag"] for p in config.cache_plan(appmod.get_study("demo"))] == ["sep_2022_2023_two"]
    assert c.post("/api/studies/demo/venues", json=body).status_code == 422      # duplicate key


def test_locked_study_cannot_be_extended(api):
    c, root = api
    (root / "gtyc_hyc_2028").mkdir()
    write_study(root / "gtyc_hyc_2028" / "study.toml", DEFN)
    body = {"venue": {**VENUE, "key": "two"}, "windows": [{"season": "sep", "core": ["09-08", "09-14"]}]}
    assert c.post("/api/studies/gtyc_hyc_2028/venues", json=body).status_code == 403


# -- pipeline without buoys ------------------------------------------------------------------------

def fake_cache(out, venue, tag, years):
    rng = np.random.default_rng(0)
    times = pd.DatetimeIndex([t for y in years
                              for t in pd.date_range(f"{y}-09-05", f"{y}-09-17 23:00", freq="h")])
    ny = nx = 12
    lat = 43.3 + 0.02 * np.arange(ny)[:, None] * np.ones((1, nx))
    lon = -82.2 + 0.03 * np.arange(nx)[None, :] * np.ones((ny, 1))
    np.savez(out / f"cache_{venue}_{tag}.npz", time=times.values.astype("datetime64[ns]"),
             u=rng.normal(-3, 2, (len(times), ny, nx)).astype("float32"),
             v=rng.normal(-3, 2, (len(times), ny, nx)).astype("float32"),
             lat=lat, lon=lon, land=np.zeros((ny, nx)))


def test_no_buoy_study_runs_end_to_end(api):
    c, root = api
    d = {**DEFN, "bootstrap_draws": 100,
         "venues": [{**VENUE, "lat": 43.4, "lon": -82.1, "bearing": 45, "offshore_nm": 1.0, "radius_nm": 2.0}]}
    assert c.post("/api/studies", json={"slug": "demo", "definition": d}).status_code == 201
    study = appmod.get_study("demo")
    assert [g["start"] for g in config.cache_plan(study)] == ["09-05"]
    study.out_dir.mkdir(exist_ok=True)
    fake_cache(study.out_dir, "abc", "sep_2022_2023", [2022, 2023])
    assert config.cache_plan(study) == []
    from hrrr_wind import venue_analysis as va
    va.main(["--study", str(root / "demo" / "study.toml"), "run"])
    assert (study.out_dir / "summary_stats.csv").exists()
    assert not (study.out_dir / "validation_metrics.csv").exists()
    r = c.get("/api/studies/demo/results").json()
    assert r["summary"] and r["validation"] == [] and r["adjusted"] == []
    assert c.get("/api/studies/demo/windrose", params=dict(venue="abc", season="sep")).json()["n"] > 0


def test_status_walks_from_no_data_to_stale(api):
    c, root = api
    d = {**DEFN, "bootstrap_draws": 100,
         "venues": [{**VENUE, "lat": 43.4, "lon": -82.1, "bearing": 45, "offshore_nm": 1.0, "radius_nm": 2.0}]}
    c.post("/api/studies", json={"slug": "demo", "definition": d})
    st = c.get("/api/studies/demo").json()["status"]
    assert st["state"] == "no_data" and st["missing_files"] == 2 * 13 * 24 and st["job"] is None
    study = appmod.get_study("demo")
    study.out_dir.mkdir(exist_ok=True)
    fake_cache(study.out_dir, "abc", "sep_2022_2023", [2022, 2023])
    assert c.get("/api/studies/demo").json()["status"]["state"] == "no_results"
    from hrrr_wind import venue_analysis as va
    va.main(["--study", str(root / "demo" / "study.toml"), "run"])
    meta = c.get("/api/studies/demo").json()
    assert meta["status"]["state"] == "ready" and meta["windows"][0]["cache"]["mb"] > 0
    assert [x["state"] for x in c.get("/api/studies").json()] == ["ready"]
    (root / "demo" / "study.toml").touch()                 # a touch (or a rename) is not an analysis change
    assert c.get("/api/studies/demo").json()["status"]["state"] == "ready"
    assert c.patch("/api/studies/demo", json={"name": "Renamed"}).status_code == 200
    assert c.get("/api/studies/demo").json()["status"]["state"] == "ready"
    assert c.patch("/api/studies/demo/venues/abc", json={"bearing": 60}).status_code == 200
    assert c.get("/api/studies/demo").json()["status"]["state"] == "stale"


def test_analysis_explains_a_box_with_no_water(api):
    c, root = api
    d = {**DEFN, "bootstrap_draws": 100,
         "venues": [{**VENUE, "lat": 43.4, "lon": -82.1, "bearing": 45, "offshore_nm": 1.0, "radius_nm": 2.0}]}
    c.post("/api/studies", json={"slug": "demo", "definition": d})
    study = appmod.get_study("demo")
    study.out_dir.mkdir(exist_ok=True)
    fake_cache(study.out_dir, "abc", "sep_2022_2023", [2022, 2023])
    z = dict(np.load(study.out_dir / "cache_abc_sep_2022_2023.npz"))
    z["land"] = np.ones_like(z["land"])                       # all land
    np.savez(study.out_dir / "cache_abc_sep_2022_2023.npz", **z)
    from hrrr_wind.stats import run_analysis
    with pytest.raises(ValueError, match="no water cells"):
        run_analysis(study)


# -- years, several caches per window, edit operations ---------------------------------------------

def study_with_data(c, root, years=(2022, 2023), slug="demo"):
    d = {**DEFN, "bootstrap_draws": 100, "years": list(years),
         "venues": [{**VENUE, "lat": 43.4, "lon": -82.1, "bearing": 45, "offshore_nm": 1.0, "radius_nm": 2.0}]}
    assert c.post("/api/studies", json={"slug": slug, "definition": d}).status_code == 201
    study = appmod.get_study(slug)
    study.out_dir.mkdir(exist_ok=True)
    fake_cache(study.out_dir, "abc", f"sep_{years[0]}_{years[-1]}", list(years))
    return study


def test_cache_years_and_window_info(api):
    c, root = api
    study_with_data(c, root)
    w = c.get("/api/studies/demo").json()["windows"][0]["cache"]
    assert w["years"] == [2022, 2023] and w["missing_years"] == [] and w["excluded_years"] == []
    assert c.get("/api/studies/demo").json()["caches"][0]["years"] == [2022, 2023]


def test_excluding_a_year_changes_stats_and_reinclusion_restores_them(api):
    from hrrr_wind.stats import load_series
    c, root = api
    study = study_with_data(c, root)
    full = load_series(study, "abc", study.windows[0].tags)
    assert set(full["year"]) == {2022, 2023}
    assert c.post("/api/studies/demo/years", json={"years": [2023]}).status_code == 200
    study = appmod.get_study("demo")
    part = load_series(study, "abc", study.windows[0].tags)
    assert set(part["year"]) == {2023} and len(part) == len(full) // 2
    assert config.cache_plan(study) == []                      # excluded data stays; nothing to download
    meta = c.get("/api/studies/demo").json()
    assert meta["windows"][0]["cache"]["excluded_years"] == [2022]
    assert c.post("/api/studies/demo/years", json={"years": [2022, 2023]}).status_code == 200
    again = load_series(appmod.get_study("demo"), "abc", appmod.get_study("demo").windows[0].tags)
    assert again.equals(full)


def test_adding_years_creates_one_pending_cache_and_only_those_years_download(api):
    c, root = api
    study_with_data(c, root)
    r = c.post("/api/studies/demo/years", json={"years": [2022, 2023, 2024]})
    assert r.status_code == 200 and r.json()["years"] == [2022, 2023, 2024]
    w = appmod.get_study("demo").windows[0]
    assert w.more_tags == ("sep_2024_2024_abc",)
    plan = config.cache_plan(appmod.get_study("demo"))
    assert [(g["tag"], g["years"]) for g in plan] == [("sep_2024_2024_abc", [2024])]
    assert r.json()["status"]["state"] == "partial" and r.json()["status"]["missing_files"] == 13 * 24
    # a second edit before downloading reuses the pending tag; reverting drops it
    c.post("/api/studies/demo/years", json={"years": [2022, 2023, 2024, 2025]})
    assert appmod.get_study("demo").windows[0].more_tags == ("sep_2024_2024_abc",)
    c.post("/api/studies/demo/years", json={"years": [2022, 2023]})
    assert appmod.get_study("demo").windows[0].more_tags == ()


def test_two_caches_in_one_window_equal_one_combined_cache(api):
    from hrrr_wind.stats import load_series
    c, root = api
    study = study_with_data(c, root, years=(2022, 2023))
    one = load_series(study, "abc", study.windows[0].tags)
    out = study.out_dir
    z = dict(np.load(out / "cache_abc_sep_2022_2023.npz"))
    yrs = pd.DatetimeIndex(z["time"]).year
    for tag, sel in (("sep_2022_2022", yrs == 2022), ("sep_2023_2023_abc", yrs == 2023)):
        np.savez(out / f"cache_abc_{tag}.npz", **{k: (v[sel] if k in ("time", "u", "v") else v) for k, v in z.items()})
    (out / "cache_abc_sep_2022_2023.npz").unlink()
    c.post("/api/studies/demo/years", json={"years": [2022, 2023]})
    path = root / "demo" / "study.toml"
    d = config.study_dict(path)
    d["windows"][0].update(cache_tag="sep_2022_2022", more_caches=["sep_2023_2023_abc"])
    config.write_study(path, d)
    appmod.get_study.cache_clear()
    study = appmod.get_study("demo")
    assert study.windows[0].tags == ("sep_2022_2022", "sep_2023_2023_abc")
    two = load_series(study, "abc", study.windows[0].tags)
    assert two.equals(one) and config.cache_plan(study) == []


def test_edit_venue_window_and_remove(api):
    c, root = api
    study_with_data(c, root)
    path = root / "demo" / "study.toml"
    r = c.patch("/api/studies/demo/venues/abc", json={"name": "ABC renamed", "bearing": 120, "offshore_nm": 3})
    assert r.status_code == 200
    v = r.json()["venues"][0]
    assert (v["name"], v["bearing"], v["offshore_nm"], v["lat"]) == ("ABC renamed", 120, 3, 43.4)
    assert config.study_dict(path)["venues"][0]["sensitivity_bearings"] == [120.0]
    assert (root / "demo" / "study.toml.bak").exists()
    assert c.patch("/api/studies/demo/venues/abc", json={"offshore_nm": 99}).status_code == 422
    assert c.patch("/api/studies/demo/venues/nope", json={"bearing": 1}).status_code == 404
    # windows: add a june window (re-adding later finds the cache), remove it again
    w = {"venue": "abc", "season": "jun", "core": ["06-14", "06-21"]}
    r = c.post("/api/studies/demo/windows", json=w)
    assert r.status_code == 201 and [x["season"] for x in r.json()["windows"]] == ["sep", "jun"]
    assert r.json()["status"]["state"] == "partial"
    assert c.post("/api/studies/demo/windows", json=w).status_code == 422                 # duplicate
    assert c.post("/api/studies/demo/windows", json={**w, "venue": "zzz"}).status_code == 404
    assert c.delete("/api/studies/demo/windows/abc/jun").status_code == 200
    assert c.delete("/api/studies/demo/windows/abc/sep").status_code == 422               # last window
    # venue removal drops its windows; the last venue cannot go
    assert c.delete("/api/studies/demo/venues/abc").status_code == 422
    out = root / "demo" / "outputs"
    assert (out / "cache_abc_sep_2022_2023.npz").exists()


def test_removing_a_venue_removes_its_pairs_and_buoys_but_not_data(api):
    c, root = api
    d = {**DEFN, "venues": [VENUE, {**VENUE, "key": "two", "name": "Two", "lon": -82.5}],
         "windows": [WINDOW, {**WINDOW, "venue": "two"}], "pairs": [{"a": "abc", "b": "two", "season": "sep"}]}
    c.post("/api/studies", json={"slug": "demo", "definition": d})
    out = root / "demo" / "outputs"
    out.mkdir(exist_ok=True)
    (out / "cache_two_sep_2022_2023.npz").write_bytes(b"keep")
    r = c.delete("/api/studies/demo/venues/two")
    assert r.status_code == 200 and [v["key"] for v in r.json()["venues"]] == ["abc"] and r.json()["pairs"] == []
    assert (out / "cache_two_sep_2022_2023.npz").read_bytes() == b"keep"
    two = [x for x in c.get("/api/studies/demo").json()["caches"] if x["venue"] == "two"]
    assert [(x["in_study"], x["used_by"]) for x in two] == [(False, None)]      # still listed, so it can be deleted


def test_edit_endpoints_respect_read_only_locked_and_running_jobs(api, monkeypatch):
    c, root = api
    study_with_data(c, root)
    calls = lambda: [c.patch("/api/studies/demo", json={"name": "x"}),                                # noqa: E731
                     c.patch("/api/studies/demo/venues/abc", json={"bearing": 10}),
                     c.delete("/api/studies/demo/venues/abc"),
                     c.post("/api/studies/demo/windows", json={"venue": "abc", "season": "jun", "core": ["06-14", "06-21"]}),
                     c.delete("/api/studies/demo/windows/abc/sep"),
                     c.post("/api/studies/demo/years", json={"years": [2022]})]
    before = (root / "demo" / "study.toml").read_text()
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    assert [r.status_code for r in calls()] == [403] * 6
    monkeypatch.delenv("HRRR_WIND_READONLY")
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset({"demo"}))
    assert [r.status_code for r in calls()] == [403] * 6
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset())
    busy = type("J", (), {"study_id": "demo", "public": lambda self: {}})()
    monkeypatch.setattr(appmod.MANAGER, "running", lambda: busy)
    assert [r.status_code for r in calls()] == [409] * 6
    assert (root / "demo" / "study.toml").read_text() == before


def test_rename_rejects_hostile_names(api):
    c, root = api
    study_with_data(c, root)
    for bad_name in ("", "x" * 200, "a\x00b", "line\nbreak"):
        assert c.patch("/api/studies/demo", json={"name": bad_name}).status_code == 422
    r = c.patch("/api/studies/demo", json={"name": 'Q"uote [x]'})
    assert r.status_code == 200 and r.json()["name"] == 'Q"uote [x]' and r.json()["id"] == "demo"


def test_rename_does_not_stale_results_that_predate_fingerprints(api):
    c, root = api
    study = study_with_data(c, root)
    from hrrr_wind import venue_analysis as va
    va.main(["--study", str(root / "demo" / "study.toml"), "run"])
    (study.out_dir / "analysis_state.json").unlink()              # results from before fingerprints existed
    assert c.get("/api/studies/demo").json()["status"]["state"] == "ready"
    c.patch("/api/studies/demo", json={"name": "Renamed"})
    assert c.get("/api/studies/demo").json()["status"]["state"] == "ready"
