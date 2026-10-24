"""Deleting a whole study: move to trash, restore, empty with a typed confirmation."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from hrrr_wind import trash
from hrrr_wind.api import app as appmod
from tests.test_study_flow import DEFN


def make(root, sid="demo", name="Test study"):
    (root / sid / "outputs").mkdir(parents=True)
    (root / sid / "study.toml").write_text(f'name = "{name}"\n')
    (root / sid / "outputs" / "cache_abc_x.npz").write_bytes(b"x" * 1000)


def test_move_list_restore_empty_roundtrip(tmp_path):
    make(tmp_path)
    entry = trash.move_to_trash(tmp_path, "demo", now=datetime(2026, 10, 24, 12, 0, 0))
    assert entry == "demo__20261024T120000" and not (tmp_path / "demo").exists()
    [item] = trash.list_trash(tmp_path)
    assert (item["id"], item["name"], item["trashed"]) == ("demo", "Test study", "2026-10-24T12:00:00")
    assert trash.restore(tmp_path, entry) == "demo" and (tmp_path / "demo" / "outputs" / "cache_abc_x.npz").exists()
    trash.move_to_trash(tmp_path, "demo", now=datetime(2026, 10, 24, 12, 5, 0))
    assert trash.empty(tmp_path)[0] == 1 and trash.list_trash(tmp_path) == [] and not (tmp_path / "demo").exists()


def test_only_real_study_folders_are_moved_and_only_trash_entries_removed(tmp_path):
    (tmp_path / "plain").mkdir()                                  # no study.toml
    outside = tmp_path.parent / "outside_study"
    make(outside.parent, "outside_study")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    for bad in ("plain", "link", "../x", "missing", ""):
        with pytest.raises(trash.TrashError):
            trash.move_to_trash(tmp_path, bad)
    assert (outside / "study.toml").exists()
    t = tmp_path / ".trash"
    (t / "keep_me").mkdir(parents=True)                           # not named by this module
    (t / "demo__20260101T000000").symlink_to(outside, target_is_directory=True)
    assert trash.empty(tmp_path) == (0, 0.0) and (outside / "study.toml").exists() and (t / "keep_me").exists()


def test_restore_refuses_taken_id_and_bad_entries(tmp_path):
    make(tmp_path)
    entry = trash.move_to_trash(tmp_path, "demo", now=datetime(2026, 1, 1))
    make(tmp_path)
    with pytest.raises(trash.TrashError) as e:
        trash.restore(tmp_path, entry)
    assert e.value.conflict
    for bad in ("../demo", "nope__20260101T000000", "demo"):
        with pytest.raises(trash.TrashError):
            trash.restore(tmp_path, bad)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "STUDIES_DIR", tmp_path)
    monkeypatch.setattr(appmod, "try_land_mask", lambda *a: None)
    monkeypatch.delenv("HRRR_WIND_READONLY", raising=False)
    appmod.get_study.cache_clear()
    c = TestClient(appmod.app)
    c.post("/api/studies", json={"slug": "demo", "definition": DEFN})
    yield c, tmp_path
    appmod.get_study.cache_clear()


def test_api_trash_restore_empty(api):
    c, root = api
    assert c.post("/api/studies/demo/trash", json={"name": "wrong"}).status_code == 422 and (root / "demo").exists()
    r = c.post("/api/studies/demo/trash", json={"name": "Test study"})
    assert r.status_code == 200 and not (root / "demo").exists()
    assert [s["id"] for s in c.get("/api/studies").json()] == [] and c.get("/api/studies/demo").status_code == 404
    [item] = c.get("/api/trash").json()
    assert item["id"] == "demo" and item["name"] == "Test study"
    assert c.post("/api/trash/empty", json={}).status_code == 422 and c.post("/api/trash/empty", json={"confirm": "yes"}).status_code == 422
    assert c.get("/api/trash").json() != []
    assert c.post(f"/api/trash/{item['entry']}/restore").json() == {"restored": "demo"}
    assert c.get("/api/studies/demo").status_code == 200
    c.post("/api/studies/demo/trash", json={"name": "Test study"})
    r = c.post("/api/trash/empty", json={"confirm": "empty trash"})
    assert r.json()["removed"] == 1 and c.get("/api/trash").json() == []
    assert c.post("/api/trash/demo__20260101T000000/restore").status_code == 422


def test_api_refuses_locked_read_only_and_busy(api, monkeypatch):
    c, root = api
    body = {"name": "Test study"}
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    calls = [c.post("/api/studies/demo/trash", json=body), c.get("/api/trash"), c.post("/api/trash/empty", json={"confirm": "empty trash"}),
             c.post("/api/trash/demo__20260101T000000/restore")]
    assert [r.status_code for r in calls] == [403] * 4
    monkeypatch.delenv("HRRR_WIND_READONLY")
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset({"demo"}))
    assert c.post("/api/studies/demo/trash", json=body).status_code == 403
    monkeypatch.setattr(appmod, "LOCKED_STUDIES", frozenset())
    busy = type("J", (), {"study_id": "demo", "public": lambda self: {}})()
    monkeypatch.setattr(appmod.MANAGER, "running", lambda: busy)
    assert c.post("/api/studies/demo/trash", json=body).status_code == 409
    assert c.post("/api/trash/empty", json={"confirm": "empty trash"}).status_code == 409
    assert (root / "demo" / "study.toml").exists()
