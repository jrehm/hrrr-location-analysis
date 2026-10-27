"""NDBC buoy stations and historical observations (network code, together with cache.py).

``stations`` reads NOAA's station metadata (retired stations too, since their archived years remain usable); ``download_stdmet`` fetches one standard
meteorological file per year into a study's ``data/buoys/<dir>`` folder. Files already on disk are
never replaced. ``validation.load_ndbc`` reads what lands here.
"""
import gzip
import json
import math
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

STATIONS_URL = "https://www.ndbc.noaa.gov/metadata/stationmetadata.xml"   # most stations, with their location history
ACTIVE_URL = "https://www.ndbc.noaa.gov/activestations.xml"                # also lists some the metadata lacks (e.g. Marine METAR sites)
STDMET_URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/{id}h{year}.txt.gz"
ARCHIVE_URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/"
STATION_CACHE = Path.home() / ".cache" / "hrrr_wind" / "ndbc_station_metadata.json"
STATION_MAX_AGE_S = 86400
ARCHIVE_CACHE = Path.home() / ".cache" / "hrrr_wind" / "ndbc_archive_years.json"
ARCHIVE_MAX_AGE_S = 7 * 86400
ID_RE = re.compile(r"^[A-Za-z0-9]{4,8}$")
TIMEOUT_S = 30
STATION_PAGE_URL = "https://www.ndbc.noaa.gov/station_page.php?station={id}"
DEFAULT_ANEM_M = 4.0                      # used only when the station page gives no height
KNOWN_ANEM_M = {"45020": 2.4, "45163": 2.3}   # offline fallback (the two buoys the reference study uses)
ANEM_RE = re.compile(r"Anemometer height:</b>\s*([0-9.]+)\s*m", re.I)


def urlopen(url, timeout=TIMEOUT_S):
    """urllib's urlopen, trusting certifi's CA bundle when it is installed (python.org builds on macOS ship none)."""
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    return urllib.request.urlopen(url, timeout=timeout, context=ctx)


def bearing_distance(lat0, lon0, lat, lon):
    """(distance in nm, compass bearing in degrees) from point 0 to point 1; flat-earth is fine at buoy range."""
    dy = (lat - lat0) * 60.0
    dx = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))
    return math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360


def parse_stations(xml_text):
    """Stations that have reported meteorology, active or retired: [{id, name, lat, lon, type, owner, retired, ended}].

    A station can have several location histories; the latest one that reported meteorology gives its position
    (a moored buoy that was moved is placed where it last measured wind). ``retired`` is true when that
    history has ended, and ``ended`` is the year it did.
    """
    out = []
    for s in ET.fromstring(xml_text).iter("station"):
        a = s.attrib
        met = [h.attrib for h in s.iter("history") if h.get("met") == "y"]
        if not met:
            continue
        h = max(met, key=lambda x: x.get("start", ""))
        stop = h.get("stop", "")
        out.append({"id": a["id"].lower(), "name": a.get("name", ""), "lat": float(h["lat"]), "lon": float(h["lng"]),
                    "type": a.get("type", ""), "owner": a.get("owner", ""),
                    "retired": bool(stop), "ended": stop[:4] if stop else ""})
    return out


def parse_active_stations(xml_text):
    """The active-station list's wind reporters, in the same shape as ``parse_stations``."""
    return [{"id": a["id"].lower(), "name": a.get("name", ""), "lat": float(a["lat"]), "lon": float(a["lon"]),
             "type": a.get("type", ""), "owner": a.get("owner", ""), "retired": False, "ended": ""}
            for s in ET.fromstring(xml_text).iter("station") if (a := s.attrib).get("met") == "y"]


def stations(opener=urlopen, cache_path=STATION_CACHE, max_age_s=STATION_MAX_AGE_S):
    """The met stations, retired ones included. The 1 MB list is kept for a day in ``cache_path``;
    when a fresh download fails, an older copy is used."""
    import time
    if max_age_s and cache_path.exists() and time.time() - cache_path.stat().st_mtime < max_age_s:
        return json.loads(cache_path.read_text())
    try:
        with opener(STATIONS_URL, timeout=120) as r:
            found = parse_stations(r.read())
        try:                         # stations only the active list knows about are added; its failure is not fatal
            with opener(ACTIVE_URL, timeout=TIMEOUT_S) as r:
                have = {s["id"] for s in found}
                found += [s for s in parse_active_stations(r.read()) if s["id"] not in have]
        except (OSError, ET.ParseError):
            pass
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(found))
        return found
    except (OSError, ET.ParseError) as e:
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        raise ConnectionError(f"could not load the NDBC station list: {e}")


def anemometer_height(buoy_id, opener=urlopen):
    """Anemometer height in m above site elevation from the station's NDBC page, or None if it lists none."""
    if not ID_RE.match(buoy_id):
        raise ValueError(f"bad buoy id {buoy_id!r}")
    try:
        with opener(STATION_PAGE_URL.format(id=buoy_id), timeout=TIMEOUT_S) as r:
            m = ANEM_RE.search(r.read().decode("utf-8", "replace"))
    except OSError as e:
        raise ConnectionError(f"could not load the NDBC page for {buoy_id}: {e}")
    return float(m.group(1)) if m else None


def archive_years(opener=urlopen, cache_path=ARCHIVE_CACHE, now=None):
    """{station id (lower case): [years with a historical stdmet file]} from NDBC's archive index.

    The index is one 4 MB page, so the result is kept for a week in ``cache_path``; offline, a stale copy is used.
    """
    import time
    now = time.time() if now is None else now
    if cache_path.exists() and now - cache_path.stat().st_mtime < ARCHIVE_MAX_AGE_S:
        return json.loads(cache_path.read_text())
    try:
        with opener(ARCHIVE_URL, timeout=120) as r:
            text = r.read().decode("utf-8", "replace")
    except OSError as e:
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        raise ConnectionError(f"could not load the NDBC archive index: {e}")
    found = {}
    for m in re.finditer(r'href="([A-Za-z0-9]+)h(\d{4})\.txt\.gz"', text):
        found.setdefault(m.group(1).lower(), []).append(int(m.group(2)))
    if not found:
        raise ConnectionError("the NDBC archive index had no files in it")
    found = {k: sorted(set(v)) for k, v in found.items()}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(found))
    return found


def stations_near(found, lat, lon, radius_nm):
    """Stations within radius of a point, nearest first, with distance and bearing from the point."""
    out = []
    for s in found:
        d, brg = bearing_distance(lat, lon, s["lat"], s["lon"])
        if d <= radius_nm:
            out.append({**s, "distance_nm": round(d, 1), "bearing": round(brg)})
    return sorted(out, key=lambda s: s["distance_nm"])


def buoy_dir_name(buoy_id):
    return f"Buoy_{buoy_id}"


def buoy_pattern(buoy_id):
    return f"{buoy_id}h*.txt.gz"


def file_years(paths):
    """Years of NDBC files named <id>h<year>.txt[.gz]."""
    return sorted({int(m.group(1)) for p in paths if (m := re.search(r"h(\d{4})\.txt", Path(p).name))})


def download_stdmet(buoy_id, years, dest, opener=urlopen):
    """Fetch <id>h<year>.txt.gz for each year into dest; returns {saved, existing, missing} year lists.

    A year NDBC has no file for (404, or the current year, which is archived after it ends) is
    reported in ``missing``. Anything else, such as a dropped connection, raises.
    """
    if not ID_RE.match(buoy_id):
        raise ValueError(f"bad buoy id {buoy_id!r}")
    dest = Path(dest)
    got = {"saved": [], "existing": [], "missing": []}
    for y in sorted(years):
        path = dest / f"{buoy_id}h{y}.txt.gz"
        if path.exists() or (dest / f"{buoy_id}h{y}.txt").exists():
            got["existing"].append(y)
            continue
        try:
            with opener(STDMET_URL.format(id=buoy_id, year=y), timeout=TIMEOUT_S) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                got["missing"].append(y)
                continue
            raise
        dest.mkdir(parents=True, exist_ok=True)
        gzip.decompress(data)               # reject a truncated or HTML error body before keeping it
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        got["saved"].append(y)
    return got
