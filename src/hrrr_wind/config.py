"""Study definitions: which venues, windows, buoys and parameters an analysis uses.

A study lives in a folder with a ``study.toml``; outputs default to ``<study>/outputs`` and
buoy files to ``<study>/data/buoys`` (override with HRRR_WIND_OUT / HRRR_WIND_BUOY_DIR).
"""
import calendar
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hrrr_wind import climatology as clim

KT = 1.9438445                 # knots per m/s
CACHE_HALF_WIDTH_NM = 18.0     # half-width of the gridded cache around each club
REPO_ROOT = Path(__file__).resolve().parents[2]
# Folder holding one sub-folder per study (each with a study.toml). Override for installed/containerized use.
STUDIES_DIR = Path(os.environ.get("HRRR_WIND_STUDIES", REPO_ROOT / "studies"))
DEFAULT_STUDY = STUDIES_DIR / "gtyc_hyc_2028" / "study.toml"


@dataclass(frozen=True)
class Venue:
    key: str
    bearing: float
    offshore_nm: float
    radius_nm: float
    sensitivity_bearings: tuple = ()

    @property
    def preset(self):
        return clim.YACHT_CLUB_PRESETS[self.key]

    @property
    def name(self):
        return self.preset["name"]


@dataclass(frozen=True)
class Window:
    venue: str
    season: str
    cache_tag: str
    core: tuple            # ("MM-DD", "MM-DD")

    @property
    def lo(self):
        return int(self.core[0].replace("-", ""))

    @property
    def hi(self):
        return int(self.core[1].replace("-", ""))

    @property
    def fit_month(self):
        return int(self.core[0][:2])

    @property
    def fit_label(self):
        return calendar.month_abbr[self.fit_month]


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    season: str


@dataclass(frozen=True)
class Buoy:
    venue: str
    id: str
    lat: float
    lon: float
    anem_m: float
    dir: str
    pattern: str
    caches: tuple


@dataclass
class Study:
    name: str
    root: Path
    out_dir: Path
    buoy_dir: Path
    years: list
    race_start: int
    race_end: int
    utc_offset: int
    tz_abbr: str
    bootstrap_draws: int
    seed: int
    sens_offshore_nm: list
    sens_radius_nm: list
    venues: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    pairs: list = field(default_factory=list)
    buoys: dict = field(default_factory=dict)

    @property
    def race_utc(self):
        return range(self.race_start, self.race_end + 1)

    @property
    def race_label(self):
        def f(h):
            h = (h + self.utc_offset) % 24
            return f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}"
        return f"{f(self.race_start)}-{f(self.race_end)} {self.tz_abbr}"

    def buoy_files(self, venue):
        b = self.buoys[venue]
        return sorted((self.buoy_dir / b.dir).glob(b.pattern))

    def windows_for(self, venue):
        return [w for w in self.windows if w.venue == venue]

    def sample_point(self, venue, bearing=None, offshore_nm=None):
        v = self.venues[venue]
        p = v.preset
        return clim.project_point(p["lat"], p["lon"],
                                  v.bearing if bearing is None else bearing,
                                  v.offshore_nm if offshore_nm is None else offshore_nm)


def load_study(path=None):
    path = Path(path or DEFAULT_STUDY)
    with open(path, "rb") as f:
        t = tomllib.load(f)
    root = path.parent
    return Study(
        name=t["name"], root=root,
        out_dir=Path(os.environ.get("HRRR_WIND_OUT", root / "outputs")),
        buoy_dir=Path(os.environ.get("HRRR_WIND_BUOY_DIR", root / "data" / "buoys")),
        years=list(t["years"]),
        race_start=t["race_hours_utc"][0], race_end=t["race_hours_utc"][1],
        utc_offset=t.get("utc_offset", 0), tz_abbr=t.get("tz_abbr", "UTC"),
        bootstrap_draws=t.get("bootstrap_draws", 2000), seed=t.get("seed", 42),
        sens_offshore_nm=list(t["sensitivity"]["offshore_nm"]),
        sens_radius_nm=list(t["sensitivity"]["radius_nm"]),
        venues={v["key"]: Venue(v["key"], v["bearing"], v["offshore_nm"], v["radius_nm"],
                                tuple(v.get("sensitivity_bearings", [v["bearing"]])))
                for v in t["venues"]},
        windows=[Window(w["venue"], w["season"], w["cache_tag"], tuple(w["core"]))
                 for w in t["windows"]],
        pairs=[Pair(p["a"], p["b"], p["season"]) for p in t.get("pairs", [])],
        buoys={b["venue"]: Buoy(b["venue"], b["id"], b["lat"], b["lon"], b["anem_m"],
                                b["dir"], b["pattern"], tuple(b["caches"]))
               for b in t.get("buoys", [])},
    )
