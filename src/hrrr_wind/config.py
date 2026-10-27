"""Study definitions: which venues, windows, buoys and parameters an analysis uses.

A study lives in a folder with a ``study.toml``; outputs default to ``<study>/outputs`` and
buoy files to ``<study>/data/buoys`` (override with HRRR_WIND_OUT / HRRR_WIND_BUOY_DIR).
"""
import calendar
import hashlib
import json
import math
import os
import re
import tempfile
import tomllib
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

from hrrr_wind import climatology as clim

KT = 1.9438445                 # knots per m/s
CACHE_HALF_WIDTH_NM = 18.0     # half-width of the gridded cache around each club
REPO_ROOT = Path(__file__).resolve().parents[2]
# Folder holding one sub-folder per study (each with a study.toml). Override for installed/containerized use.
STUDIES_DIR = Path(os.environ.get("HRRR_WIND_STUDIES", REPO_ROOT / "studies"))
DEFAULT_STUDY = STUDIES_DIR / "gtyc_hyc_2028" / "study.toml"
LOCKED_STUDIES = frozenset({"gtyc_hyc_2028"})   # reference study: never rewritten (copy it to extend)

FIRST_YEAR = 2015              # HRRR archive starts 2014-09-30
MAX_YEARS, MAX_WINDOW_DAYS = 15, 45
MAX_VENUES, MAX_WINDOWS = 9, 9     # one chart color per window (web/static/style.css has 9 series colors)
BUOY_MARGIN_NM = 3.0           # a buoy this close to the edge of a cache box is treated as outside it
BUFFER_DAYS = 3                # cache covers the core window +/- this many days
CONUS_LAT, CONUS_LON = (21.0, 53.0), (-135.0, -60.0)   # HRRR domain (rough bounds)


@dataclass(frozen=True)
class Venue:
    key: str
    bearing: float
    offshore_nm: float
    radius_nm: float
    sensitivity_bearings: tuple = ()
    # Club position and display name; a venue without them must be one of the built-in presets.
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    # Display label for tables and figures; defaults to the key in capitals. Left out of repr (and so of the
    # study fingerprint) because it never changes the analysis.
    short: str | None = field(default=None, repr=False)
    # Time zone of the venue when it differs from the study's (UTC offset in hours and its abbreviation).
    # Racing hours are local, so this moves the venue's UTC racing hours. Fingerprinted separately.
    utc_offset: int | None = field(default=None, repr=False)
    tz_abbr: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.name is None or self.lat is None or self.lon is None:
            p = self.preset
            for attr in ("name", "lat", "lon"):
                if getattr(self, attr) is None:
                    object.__setattr__(self, attr, p[attr])

    @property
    def label(self):
        return self.short or self.key.upper()

    @property
    def preset(self):
        try:
            return clim.YACHT_CLUB_PRESETS[self.key]
        except KeyError:
            raise ValueError(f"venue '{self.key}' has no name/lat/lon and is not a built-in preset") from None


@dataclass(frozen=True)
class Window:
    venue: str
    season: str
    cache_tag: str
    core: tuple            # ("MM-DD", "MM-DD")
    more_tags: tuple = ()  # extra caches (added years); all share the venue's grid

    @property
    def tags(self):
        return (self.cache_tag, *self.more_tags)

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
        """Racing hours in UTC for the study's own time zone (venues with another zone: race_utc_for)."""
        return range(self.race_start, self.race_end + 1)

    @property
    def race_local(self):
        """First and last racing hour in the study's own time zone."""
        return self.race_start + self.utc_offset, self.race_end + self.utc_offset

    def offset_for(self, venue):
        v = self.venues[venue]
        return self.utc_offset if v.utc_offset is None else v.utc_offset

    def tz_for(self, venue):
        return self.venues[venue].tz_abbr or self.tz_abbr

    def race_utc_for(self, venue):
        """The UTC hours that are racing hours at a venue: the same local hours everywhere."""
        a, b = self.race_local
        off = self.offset_for(venue)
        return range(a - off, b - off + 1)

    @property
    def race_label(self):
        def f(h):
            h = (h + self.utc_offset) % 24
            return f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}"
        zones = {self.tz_for(k) for k in self.venues} or {self.tz_abbr}
        return f"{f(self.race_start)}-{f(self.race_end)} {zones.pop() if len(zones) == 1 else 'local time'}"

    def cache_path(self, venue, tag):
        return self.out_dir / f"cache_{venue}_{tag}.npz"

    def present_tags(self, w):
        """The window's cache tags whose file exists."""
        return [t for t in w.tags if self.cache_path(w.venue, t).exists()]

    def has_data(self, w):
        return bool(self.present_tags(w))

    def window_years(self, w):
        """Years found in the window's cache files, whether or not they are in the study."""
        found = set()
        for t in self.present_tags(w):
            found |= cache_years(self.out_dir, w.venue, t)
        return found

    def fingerprint(self, buoys=None):
        """Hash of everything that changes the analysis (not the study's display name, and not the
        buoys, which only affect validation). Passing a buoy list reproduces the hash older results carry."""
        parts = (self.years, self.race_start, self.race_end, self.utc_offset, self.tz_abbr,
                 self.bootstrap_draws, self.seed, self.sens_offshore_nm, self.sens_radius_nm,
                 list(self.venues.values()), self.windows, self.pairs)
        zones = [(v.key, v.utc_offset, v.tz_abbr) for v in self.venues.values() if v.utc_offset is not None]
        if zones:                       # only when set, so studies without per-venue zones keep their old hash
            parts += (zones,)
        if buoys is not None:
            parts += (list(buoys),)
        return hashlib.sha256(repr(parts).encode()).hexdigest()

    def buoy_files(self, venue):
        b = self.buoys[venue]
        return sorted((self.buoy_dir / b.dir).glob(b.pattern))

    def window(self, venue, season):
        return next(w for w in self.windows if w.venue == venue and w.season == season)

    def window_label(self, venue, season):
        """Display label for a window: the venue label, plus the dates when the venue has several."""
        v, ws = self.venues[venue], self.windows_for(venue)
        if len(ws) < 2:
            return v.label
        return f"{v.label} {dates_label(self.window(venue, season).core)}"

    def windows_for(self, venue):
        return [w for w in self.windows if w.venue == venue]

    def sample_point(self, venue, bearing=None, offshore_nm=None):
        v = self.venues[venue]
        return clim.project_point(v.lat, v.lon,
                                  v.bearing if bearing is None else bearing,
                                  v.offshore_nm if offshore_nm is None else offshore_nm)


@lru_cache(maxsize=256)
def _years_of(path, mtime_ns):
    try:
        with np.load(path) as z:
            return frozenset(int(y) + 1970 for y in np.unique(z["time"].astype("datetime64[Y]").astype(int)))
    except Exception:           # unreadable or partly written file: report no years rather than fail the page
        return frozenset()


def cache_years(out_dir, venue, tag):
    """Years present in a wind cache file (read from its time axis; cached by file mtime)."""
    path = Path(out_dir) / f"cache_{venue}_{tag}.npz"
    return set(_years_of(str(path), path.stat().st_mtime_ns))


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
                                tuple(v.get("sensitivity_bearings", [v["bearing"]])),
                                v.get("name"), v.get("lat"), v.get("lon"), v.get("short"),
                                v.get("utc_offset"), v.get("tz_abbr"))
                for v in t["venues"]},
        windows=[Window(w["venue"], w["season"], w["cache_tag"], tuple(w["core"]),
                        tuple(w.get("more_caches", [])))
                 for w in t["windows"]],
        pairs=[Pair(p["a"], p["b"], p["season"]) for p in t.get("pairs", [])],
        buoys={b["venue"]: Buoy(b["venue"], b["id"], b["lat"], b["lon"], b["anem_m"],
                                b["dir"], b["pattern"], tuple(b["caches"]))
               for b in t.get("buoys", [])},
    )


# -- study definitions: validation and writing --------------------------------------------------

class DefinitionError(ValueError):
    """A study definition is invalid (HTTP 422 in the API)."""


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,39}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9]{0,11}$")          # venue key: used in file names
SEASON_RE = re.compile(r"^[a-z][a-z0-9]{0,11}$")
TAG_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
TOP_KEYS = {"name", "years", "race_hours_utc", "utc_offset", "tz_abbr", "bootstrap_draws", "seed",
            "sensitivity", "venues", "windows", "pairs", "buoys"}


def _text(value, what, max_len):
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise DefinitionError(f"{what} must be 1-{max_len} characters of text")
    if any(unicodedata.category(c) in ("Cc", "Cs", "Co", "Cn") for c in value):
        raise DefinitionError(f"{what} contains control or unassigned characters")
    return value.strip()


def _number(value, what, lo, hi, lo_open=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DefinitionError(f"{what} must be a number")
    if value < lo or value > hi or (lo_open and value == lo):
        raise DefinitionError(f"{what} must be {'>' if lo_open else '>='} {lo} and <= {hi}")
    return float(value)


def _int(value, what, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise DefinitionError(f"{what} must be a whole number from {lo} to {hi}")
    return value


def _mmdd(value, what):
    try:
        return datetime.strptime(f"2001-{value}", "%Y-%m-%d")      # 2001: not a leap year
    except (TypeError, ValueError):
        raise DefinitionError(f"{what} must be MM-DD, got {value!r}") from None


def buffered_span(core, days=BUFFER_DAYS):
    """The ("MM-DD", "MM-DD") range the cache must cover for a core window."""
    d0, d1 = _mmdd(core[0], "core start"), _mmdd(core[1], "core end")
    lo, hi = d0 - timedelta(days=days), d1 + timedelta(days=days)
    if lo.year != 2001 or hi.year != 2001:
        raise DefinitionError(f"core window {core[0]}..{core[1]} is too close to the start or end of the year")
    return lo.strftime("%m-%d"), hi.strftime("%m-%d")


def cache_plan(study):
    """Downloads a study still needs: [{tag, start, end, years, venues}], one per (tag, span, years).

    A cache file is cache_<venue>_<tag>.npz. For each window, a missing file must supply the study
    years that the window's other caches do not hold, so a re-run (an added venue, added years)
    only fetches what is missing and never overwrites anything.
    """
    groups = {}
    for w in study.windows:
        have = study.window_years(w)
        for tag in w.tags:
            if study.cache_path(w.venue, tag).exists():
                continue
            years = [y for y in study.years if y not in have]
            if not years:
                continue
            start, end = buffered_span(w.core)
            groups.setdefault((tag, start, end, tuple(years)), []).append(w.venue)
    return [{"tag": t, "start": a, "end": b, "years": list(y), "venues": v} for (t, a, b, y), v in groups.items()]


def buoy_caches(study, venue, buoy_id, lat, lon):
    """Cache tags that supply HRRR at a buoy, as [{tag, start, end, extra}].

    A venue's window caches cover the buoy when it sits well inside their box (the 2 nm sampling
    box plus a margin). Otherwise one extra cache per distinct window span is centered on the buoy
    (``extra``: tag ``val_<id>_<MMDD>_<MMDD>``, filed under the venue key).
    """
    v = study.venues[venue]
    dy, dx = (lat - v.lat) * 60.0, (lon - v.lon) * 60.0 * math.cos(math.radians(v.lat))
    wins = study.windows_for(venue)
    if max(abs(dx), abs(dy)) <= CACHE_HALF_WIDTH_NM - BUOY_MARGIN_NM:
        return [{"tag": t, "start": None, "end": None, "extra": False} for t in dict.fromkeys(t for w in wins for t in w.tags)]
    spans = dict.fromkeys(buffered_span(w.core) for w in wins)
    return [{"tag": f"val_{buoy_id}_{a.replace('-', '')}_{b.replace('-', '')}", "start": a, "end": b, "extra": True}
            for a, b in spans]


def set_years(d, years, out_dir):
    """Set a raw study definition's years; give each window with a gap one pending cache tag.

    Years that leave the list stay on disk (excluded); a pending tag whose gap has closed is dropped.
    """
    d["years"] = sorted({int(y) for y in years})
    out_dir = Path(out_dir)
    for w in d["windows"]:
        tags = [w["cache_tag"], *w.get("more_caches", [])]
        present = [t for t in tags if (out_dir / f"cache_{w['venue']}_{t}.npz").exists()]
        have = set().union(*(cache_years(out_dir, w["venue"], t) for t in present)) if present else set()
        missing = [y for y in d["years"] if y not in have]
        pending = [t for t in tags if t not in present]
        if missing and not pending:
            new = f"{w['season']}_{min(missing)}_{max(missing)}_{w['venue']}"
            while new in tags or (out_dir / f"cache_{w['venue']}_{new}.npz").exists():
                new += "_b"
            w["more_caches"] = [*w.get("more_caches", []), new]
        elif not missing and pending:
            keep = [t for t in w.get("more_caches", []) if t in present]
            if keep:
                w["more_caches"] = keep
            else:
                w.pop("more_caches", None)


def dates_label(core):
    """("09-08", "09-14") -> "Sep 8-14"; across months "Sep 28-Oct 2"."""
    (m0, d0), (m1, d1) = ((int(x) for x in c.split("-")) for c in core)
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[m0 - 1]} {d0}\u2013{d1}" if m0 == m1 else f"{names[m0 - 1]} {d0}\u2013{names[m1 - 1]} {d1}"


def derive_season(windows, core):
    """Internal window id for new dates: reuse the id of an existing window with the same dates
    (so venues racing the same week pair up), else the start month, numbered if already taken."""
    for w in windows:
        if list(w["core"]) == list(core):
            return w["season"]
    month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"][_mmdd(core[0], "core start").month - 1]
    taken = {w["season"] for w in windows}
    return next(s for s in (month, *(f"{month}{n}" for n in range(2, 99))) if s not in taken)


def window_tag(season, years, venue=None):
    """Cache tag for a window: shared by venues of a new study, venue-suffixed for added venues."""
    tag = f"{season}_{min(years)}_{max(years)}"
    return f"{tag}_{venue}" if venue else tag


def validate_definition(d):
    """Check a study definition (the study.toml structure as a dict); return a normalized copy.

    Shared by the CLI and the API. Raises DefinitionError with a message fit to show a user.
    """
    if not isinstance(d, dict):
        raise DefinitionError("study definition must be an object")
    unknown = set(d) - TOP_KEYS
    if unknown:
        raise DefinitionError(f"unknown field(s): {sorted(unknown)}")
    out = {"name": _text(d.get("name"), "study name", 80)}
    years = d.get("years")
    if not isinstance(years, list) or not years:
        raise DefinitionError("years must be a list")
    years = sorted({_int(y, "year", FIRST_YEAR, date.today().year) for y in years})
    if len(years) > MAX_YEARS:
        raise DefinitionError(f"at most {MAX_YEARS} years")
    out["years"] = years
    hours = d.get("race_hours_utc", [14, 20])
    if not isinstance(hours, list) or len(hours) != 2:
        raise DefinitionError("race_hours_utc must be [first, last]")
    h0, h1 = _int(hours[0], "first race hour", 0, 23), _int(hours[1], "last race hour", 0, 23)
    if h0 > h1:
        raise DefinitionError("first race hour must not be after the last")
    out["race_hours_utc"] = [h0, h1]
    out["utc_offset"] = _int(d.get("utc_offset", 0), "utc_offset", -12, 14)
    tz = d.get("tz_abbr", "UTC")
    if not isinstance(tz, str) or not re.fullmatch(r"[A-Za-z0-9]{1,6}", tz):
        raise DefinitionError("tz_abbr must be 1-6 letters or digits")
    out["tz_abbr"] = tz
    out["bootstrap_draws"] = _int(d.get("bootstrap_draws", 2000), "bootstrap_draws", 100, 20000)
    out["seed"] = _int(d.get("seed", 42), "seed", 0, 2**31 - 1)
    sens = d.get("sensitivity", {"offshore_nm": [1.0, 2.0, 3.0, 4.0, 6.0], "radius_nm": [2.0, 4.0, 6.0]})
    if not isinstance(sens, dict) or set(sens) != {"offshore_nm", "radius_nm"}:
        raise DefinitionError("sensitivity needs offshore_nm and radius_nm lists")
    out["sensitivity"] = {
        k: [_number(x, f"sensitivity {k}", 0, 30 if k == "offshore_nm" else 10, lo_open=True)
            for x in sens[k][:10]] if isinstance(sens[k], list) and sens[k] else _fail(f"sensitivity {k} must be a list")
        for k in ("offshore_nm", "radius_nm")}

    venues, seen = [], set()
    raw_venues = d.get("venues")
    if not isinstance(raw_venues, list) or not raw_venues:
        raise DefinitionError("at least one venue is required")
    if len(raw_venues) > MAX_VENUES:
        raise DefinitionError(f"at most {MAX_VENUES} venues per study")
    for v in raw_venues:
        if not isinstance(v, dict):
            raise DefinitionError("each venue must be an object")
        if set(v) - {"key", "name", "lat", "lon", "short", "utc_offset", "tz_abbr", "bearing", "offshore_nm", "radius_nm", "sensitivity_bearings"}:
            raise DefinitionError(f"unknown venue field(s): {sorted(set(v) - {'key', 'name', 'lat', 'lon', 'short', 'utc_offset', 'tz_abbr', 'bearing', 'offshore_nm', 'radius_nm', 'sensitivity_bearings'})}")
        key = v.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise DefinitionError("venue key must be 1-12 lowercase letters/digits, starting with a letter")
        if key in seen:
            raise DefinitionError(f"duplicate venue key '{key}'")
        seen.add(key)
        bearing = _number(v.get("bearing"), f"{key} bearing", 0, 359.999)
        row = {"key": key}
        if "name" in v or "lat" in v or "lon" in v or key not in clim.YACHT_CLUB_PRESETS:
            row["name"] = _text(v.get("name"), f"{key} name", 60)
            row["lat"] = _number(v.get("lat"), f"{key} latitude", *CONUS_LAT)
            row["lon"] = _number(v.get("lon"), f"{key} longitude", *CONUS_LON)
        if v.get("short") not in (None, ""):
            row["short"] = _text(v["short"], f"{key} short name", 12)
        if v.get("utc_offset") is not None or v.get("tz_abbr") is not None:
            row["utc_offset"] = _int(v.get("utc_offset"), f"{key} utc_offset", -12, 14)
            tzv = v.get("tz_abbr")
            if not isinstance(tzv, str) or not re.fullmatch(r"[A-Za-z0-9]{1,6}", tzv):
                raise DefinitionError(f"{key} tz_abbr must be 1-6 letters or digits")
            row["tz_abbr"] = tzv
            if row["utc_offset"] == out["utc_offset"] and tzv == out["tz_abbr"]:
                del row["utc_offset"], row["tz_abbr"]     # same as the study's: nothing to record
        local0, local1 = h0 + out["utc_offset"], h1 + out["utc_offset"]
        off = row.get("utc_offset", out["utc_offset"])
        if local0 - off < 0 or local1 - off > 23:
            raise DefinitionError(f"{key}: the racing hours ({local0}:00-{local1}:00 local) fall outside one UTC day in its time zone")
        row["bearing"] = bearing
        row["offshore_nm"] = _number(v.get("offshore_nm"), f"{key} offshore distance", 0, 30, lo_open=True)
        row["radius_nm"] = _number(v.get("radius_nm", 4.0), f"{key} radius", 0, 10, lo_open=True)
        sb = v.get("sensitivity_bearings", [bearing])
        if not isinstance(sb, list) or not sb or len(sb) > 8:
            raise DefinitionError(f"{key} sensitivity_bearings must be a list of up to 8 bearings")
        row["sensitivity_bearings"] = [_number(b, f"{key} sensitivity bearing", 0, 359.999) for b in sb]
        venues.append(row)
    out["venues"] = venues

    windows, seen_w, season_core = [], set(), {}
    raw_windows = d.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise DefinitionError("at least one window is required")
    if len(raw_windows) > MAX_WINDOWS:
        raise DefinitionError(f"at most {MAX_WINDOWS} windows per study")
    for w in raw_windows:
        if not isinstance(w, dict) or set(w) - {"venue", "season", "core", "cache_tag", "more_caches"}:
            raise DefinitionError("each window needs venue, season, core (and optionally cache_tag)")
        venue, season, core = w.get("venue"), w.get("season"), w.get("core")
        if venue not in seen:
            raise DefinitionError(f"window refers to unknown venue {venue!r}")
        if not isinstance(season, str) or not SEASON_RE.match(season):
            raise DefinitionError("season must be 1-12 lowercase letters/digits, starting with a letter")
        if not isinstance(core, list) or len(core) != 2:
            raise DefinitionError("core must be [MM-DD, MM-DD]")
        d0, d1 = _mmdd(core[0], "core start"), _mmdd(core[1], "core end")
        if d1 < d0:
            raise DefinitionError("core window must run forward within one year")
        lo, hi = buffered_span(core)
        if (_mmdd(hi, "") - _mmdd(lo, "")).days + 1 > MAX_WINDOW_DAYS:
            raise DefinitionError(f"core window plus {BUFFER_DAYS}-day buffers may span at most {MAX_WINDOW_DAYS} days")
        if (venue, season) in seen_w:
            raise DefinitionError(f"duplicate {season} window for {venue}")
        seen_w.add((venue, season))
        if season_core.setdefault(season, tuple(core)) != tuple(core):
            raise DefinitionError(f"all '{season}' windows must use the same dates")
        tag = w.get("cache_tag") or window_tag(season, years)
        if not isinstance(tag, str) or not TAG_RE.match(tag):
            raise DefinitionError("cache_tag must be 1-40 letters, digits or underscores")
        row = {"venue": venue, "season": season, "cache_tag": tag, "core": list(core)}
        more = w.get("more_caches", [])
        if not isinstance(more, list) or len(more) > 5 or not all(isinstance(t, str) and TAG_RE.match(t) for t in more) \
                or len({tag, *more}) != len(more) + 1:
            raise DefinitionError("more_caches must be a list of distinct cache tags")
        if more:
            row["more_caches"] = list(more)
        windows.append(row)
    out["windows"] = windows

    pairs = []
    for p in d.get("pairs", []):
        if (not isinstance(p, dict) or set(p) != {"a", "b", "season"} or p["a"] == p["b"]
                or (p["a"], p["season"]) not in seen_w or (p["b"], p["season"]) not in seen_w):
            raise DefinitionError("a pair needs two different venues that both have a window in that season")
        pairs.append({"a": p["a"], "b": p["b"], "season": p["season"]})
    if pairs:
        out["pairs"] = pairs

    buoys = []
    for b in d.get("buoys", []):
        need = {"venue", "id", "lat", "lon", "anem_m", "dir", "pattern", "caches"}
        if not isinstance(b, dict) or set(b) != need or b["venue"] not in seen:
            raise DefinitionError("each buoy needs " + ", ".join(sorted(need)) + " and a known venue")
        for k in ("id", "dir", "pattern"):
            _text(b[k], f"buoy {k}", 80)
        if "/" in b["dir"] or ".." in b["dir"] or b["pattern"].startswith("/") or ".." in b["pattern"]:
            raise DefinitionError("buoy dir and pattern must stay inside the buoy folder")
        if (not isinstance(b["caches"], list) or not all(isinstance(c, str) and TAG_RE.match(c) for c in b["caches"])):
            raise DefinitionError("buoy caches must be a list of cache tags")
        buoys.append({**b, "lat": _number(b["lat"], "buoy lat", -90, 90),
                      "lon": _number(b["lon"], "buoy lon", -180, 180),
                      "anem_m": _number(b["anem_m"], "anemometer height", 0, 100, lo_open=True)})
    if buoys:
        out["buoys"] = buoys
    return out


def _fail(msg):
    raise DefinitionError(msg)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)      # JSON escapes are valid TOML basic-string escapes
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def dump_toml(d):
    """Serialize a validated definition to study.toml text (strings always escaped)."""
    def block(header, row):
        return "\n".join([header] + [f"{k} = {_toml_value(x)}" for k, x in row.items()])
    parts = ["\n".join(f"{k} = {_toml_value(d[k])}" for k in
                       ("name", "years", "race_hours_utc", "utc_offset", "tz_abbr", "bootstrap_draws", "seed"))]
    parts.append(block("[sensitivity]", d["sensitivity"]))
    for table in ("venues", "windows", "pairs", "buoys"):
        parts += [block(f"[[{table}]]", row) for row in d.get(table, [])]
    return "\n\n".join(parts) + "\n"


def study_dict(path):
    """Raw dict of an existing study.toml (the input to validate_definition)."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def write_study(path, definition, *, backup=False):
    """Validate and atomically write a study.toml; with backup, keep the old file as study.toml.bak."""
    clean = validate_definition(definition)
    text = dump_toml(clean)
    if tomllib.loads(text) != clean:                 # round-trip guard: never write what we cannot read back
        raise DefinitionError("internal error: study definition did not round-trip")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        path.with_suffix(".toml.bak").write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".study-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return clean
