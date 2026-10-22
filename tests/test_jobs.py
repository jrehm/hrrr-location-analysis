import sys
import time

import pytest
from fastapi.testclient import TestClient

from hrrr_wind import jobs
from hrrr_wind.api import app as appmod

SID = "gtyc_hyc_2028"
GOOD = {"venues": ["hyc"], "years": [2020], "start": "09-08", "end": "09-10", "tag": "t_new"}


def fake(script):
    """Command builder that ignores the real command and runs a tiny Python script."""
    return lambda *_: [sys.executable, "-c", script]


@pytest.fixture
def api(tmp_path, monkeypatch):
    study = appmod.get_study(SID)
    monkeypatch.setattr(study, "out_dir", tmp_path)          # keep logs/caches out of the repo
    monkeypatch.delenv("HRRR_WIND_READONLY", raising=False)
    mgr = jobs.JobManager(command_builder=fake("print('PROGRESS 0.5 half way', flush=True)"))
    monkeypatch.setattr(appmod, "MANAGER", mgr)
    return TestClient(appmod.app), mgr, tmp_path


def wait(client, jid, want, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in want:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job stuck: {j}")


def test_job_runs_reports_progress_and_finishes(api):
    c, _, _ = api
    r = c.post(f"/api/studies/{SID}/jobs", json={"kind": "cache", "params": GOOD})
    assert r.status_code == 202
    j = wait(c, r.json()["id"], {"done", "failed"})
    assert j["status"] == "done" and j["progress"] == 1.0
    assert "PROGRESS 0.5 half way" in c.get(f"/api/jobs/{j['id']}/log").json()["log"]
    assert [x["id"] for x in c.get(f"/api/studies/{SID}/jobs").json()] == [j["id"]]


def test_failed_job_reports_last_log_line(api):
    c, mgr, _ = api
    mgr._command_builder = fake("import sys; print('boom: no data'); sys.exit(3)")
    jid = c.post(f"/api/studies/{SID}/jobs", json={"kind": "analyze"}).json()["id"]
    j = wait(c, jid, {"done", "failed"})
    assert j["status"] == "failed" and j["returncode"] == 3 and "boom" in j["message"]


def test_only_one_job_at_a_time_and_cancel(api):
    c, mgr, _ = api
    mgr._command_builder = fake("import time; time.sleep(30)")
    first = c.post(f"/api/studies/{SID}/jobs", json={"kind": "validate"}).json()
    assert c.post(f"/api/studies/{SID}/jobs", json={"kind": "analyze"}).status_code == 409
    assert c.post(f"/api/jobs/{first['id']}/cancel").json()["status"] == "cancelled"
    assert wait(c, first["id"], {"cancelled"})["finished"] is not None
    assert c.post(f"/api/studies/{SID}/jobs", json={"kind": "analyze"}).status_code == 202


@pytest.mark.parametrize("change", [
    {"years": [2010]}, {"years": []}, {"years": list(range(2015, 2031))}, {"tag": "bad tag!"},
    {"tag": ""}, {"start": "13-01"}, {"end": "08-01"}, {"start": "01-01", "end": "12-31"},
    {"venues": ["nowhere"]}, {"max_rss_gb": 64}, {"start_hour": 20, "end_hour": 5},
])
def test_download_parameters_are_validated(api, change):
    c, _, _ = api
    r = c.post(f"/api/studies/{SID}/jobs", json={"kind": "cache", "params": {**GOOD, **change}})
    assert r.status_code == 422, r.text


def test_existing_cache_is_never_overwritten(api):
    c, _, tmp = api
    (tmp / "cache_hyc_t_new.npz").write_bytes(b"x")
    r = c.post(f"/api/studies/{SID}/jobs", json={"kind": "cache", "params": GOOD})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]


def test_unknown_kind_and_readonly_mode(api, monkeypatch):
    c, _, _ = api
    assert c.post(f"/api/studies/{SID}/jobs", json={"kind": "rm -rf"}).status_code == 422
    monkeypatch.setenv("HRRR_WIND_READONLY", "1")
    assert c.post(f"/api/studies/{SID}/jobs", json={"kind": "analyze"}).status_code == 403
    assert c.post("/api/jobs/abc/cancel").status_code == 403
    assert c.get(f"/api/studies/{SID}").json()["readonly"] is True


def test_meta_lists_caches_and_build_command_shape(api):
    c, _, tmp = api
    (tmp / "cache_gtyc_sep_x.npz").write_bytes(b"x" * 10)
    assert {"venue": "gtyc", "tag": "sep_x", "mb": 0.0, "years": [], "used": False} in c.get(f"/api/studies/{SID}").json()["caches"]
    cmd = jobs.build_command("/s/study.toml", "cache", {**GOOD, "start_hour": 0, "end_hour": 23, "max_rss_gb": 4.0})
    assert cmd[4:7] == ["hrrr_wind.venue_analysis", "--progress-lines", "--study"] and "--max-rss-gb" in cmd
    assert jobs.estimate({"years": [2020, 2021], "start": "09-08", "end": "09-14"})["files"] == 2 * 7 * 24


def test_run_study_command_uses_the_run_subcommand():
    from hrrr_wind.jobs import build_command
    cmd = build_command("s.toml", "run_study", {"max_rss_gb": 4.0})
    assert cmd[cmd.index("--study") + 2:] == ["run", "--max-rss-gb", "4.0"]
