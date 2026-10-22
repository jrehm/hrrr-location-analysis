import re
from pathlib import Path

from hrrr_wind import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_has_current_version():
    text = (ROOT / "CHANGELOG.md").read_text()
    first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
    assert first and first.group(1) == __version__


def test_health_reports_version():
    from fastapi.testclient import TestClient
    from hrrr_wind.api.app import app
    assert TestClient(app).get("/api/health").json()["version"] == __version__
