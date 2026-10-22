import pytest
from fastapi.testclient import TestClient

from hrrr_wind.api.app import app
from hrrr_wind.stats import windrose_table

SID = "gtyc_hyc_2028"
client = TestClient(app)


def test_study_listing_and_meta():
    listed = {x["id"]: x for x in client.get("/api/studies").json()}
    assert listed[SID]["name"] == "GTYC vs HYC, 2028 regatta" and listed[SID]["state"] == "ready"
    assert listed[SID]["years"] == [2015, 2025] and listed[SID]["locked"]
    m = client.get(f"/api/studies/{SID}").json()
    assert m["race_label"] == "10AM-4PM EDT" and [v["key"] for v in m["venues"]] == ["gtyc", "hyc"]
    assert client.get("/api/studies/nope").status_code == 404


def test_geometry_projects_from_club_and_counts_water():
    g = client.get(f"/api/studies/{SID}/geometry",
                   params=dict(venue="gtyc", bearing=20, offshore_nm=3, radius_nm=4)).json()
    assert g["club"]["lat"] == pytest.approx(44.78034)
    assert g["sample"]["lat"] == pytest.approx(44.8273, abs=1e-3)
    assert g["n_water"] == 11


def test_quick_stats_match_committed_study():
    q = client.get(f"/api/studies/{SID}/quick", params=dict(
        venue="hyc", season="sep", bearing=330, offshore_nm=2, radius_nm=4)).json()
    assert q["n"] == 523 and q["mean"] == pytest.approx(8.67, abs=0.01)


def test_quick_rejects_bad_input_and_handles_no_water():
    bad = client.get(f"/api/studies/{SID}/quick", params=dict(
        venue="hyc", season="sep", bearing=330, offshore_nm=-1))
    assert bad.status_code == 422
    # 4 nm west of the club is a few miles inland: all land, so no water cells
    inland = client.get(f"/api/studies/{SID}/quick", params=dict(
        venue="gtyc", season="sep", bearing=270, offshore_nm=4, radius_nm=2))
    assert inland.status_code == 200 and inland.json() == {"n_cells": 0}


def test_results_and_windrose_and_diurnal():
    r = client.get(f"/api/studies/{SID}/results").json()
    assert len(r["summary"]) == 6 and r["paired"][0]["a"] == "hyc"
    w = client.get(f"/api/studies/{SID}/windrose", params=dict(venue="hyc", season="sep")).json()
    assert sum(w["distribution"]) == pytest.approx(100.0) and w["n"] == 523
    d = client.get(f"/api/studies/{SID}/diurnal").json()
    assert len(d) == 3 and len(d[0]["hours"]) == 24


def test_file_download_is_confined_to_the_output_folder():
    assert client.get(f"/api/studies/{SID}/files/summary_stats.csv").status_code == 200
    assert client.get(f"/api/studies/{SID}/files/..%2Fstudy.toml").status_code == 404
    assert client.get(f"/api/studies/{SID}/files/cache_gtyc_sep_2015_2025.npz").status_code == 404


def test_windrose_table_bins_and_sectors():
    t = windrose_table([2, 7, 12, 17, 25], [0, 90, 180, 270, 359])
    assert t["distribution"] == [20.0] * 5
    assert t["values"][0][0] == 20.0 and t["values"][4][0] == 20.0   # 359 deg rounds to north
