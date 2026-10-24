"""Deleting a whole study is two steps: move its folder to ``<studies>/.trash/``, then empty the trash.

Trashed studies are invisible to the app (the study list only globs ``*/study.toml``) and can be
restored while they are still in the trash. Only real folders directly under the studies directory
are ever moved, and only folders this module named are ever removed from the trash.
"""
import re
import shutil
import tomllib
from datetime import datetime
from pathlib import Path

TRASH = ".trash"
ENTRY_RE = re.compile(r"^([a-z0-9][a-z0-9_]{1,39})__(\d{8}T\d{6})$")


class TrashError(ValueError):
    """The request cannot be done (HTTP 422 or 409, see ``conflict``)."""

    def __init__(self, message, conflict=False):
        super().__init__(message)
        self.conflict = conflict


def folder_mb(path):
    return round(sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file() and not f.is_symlink()) / 1e6, 1)


def _real_dir(path):
    return path.is_dir() and not path.is_symlink()


def move_to_trash(studies_dir, sid, now=None):
    """Move studies/<sid> to .trash/<sid>__<time>; returns the trash entry name."""
    studies_dir = Path(studies_dir)
    src = studies_dir / sid
    if not _real_dir(src) or src.resolve().parent != studies_dir.resolve() or not (src / "study.toml").is_file():
        raise TrashError(f"'{sid}' is not a study folder")
    entry = f"{sid}__{(now or datetime.now()).strftime('%Y%m%dT%H%M%S')}"
    if not ENTRY_RE.match(entry):
        raise TrashError(f"'{sid}' cannot be trashed")
    dest = studies_dir / TRASH / entry
    if dest.exists():
        raise TrashError("this study was just trashed; try again in a second", conflict=True)
    dest.parent.mkdir(exist_ok=True)
    shutil.move(str(src), str(dest))
    return entry


def list_trash(studies_dir):
    """Trashed studies, newest first: entry, study id, name, size, when."""
    root = Path(studies_dir) / TRASH
    out = []
    for d in root.iterdir() if root.is_dir() else []:
        m = ENTRY_RE.match(d.name)
        if not m or not _real_dir(d):
            continue
        try:
            name = tomllib.loads((d / "study.toml").read_text(encoding="utf-8")).get("name", m.group(1))
        except (OSError, ValueError):
            name = m.group(1)
        out.append({"entry": d.name, "id": m.group(1), "name": name, "mb": folder_mb(d),
                    "trashed": datetime.strptime(m.group(2), "%Y%m%dT%H%M%S").isoformat()})
    return sorted(out, key=lambda r: r["trashed"], reverse=True)


def restore(studies_dir, entry):
    """Move a trashed study back to studies/<id>; refuses if that id is in use again."""
    studies_dir = Path(studies_dir)
    m = ENTRY_RE.match(entry)
    src = studies_dir / TRASH / entry
    if not m or not _real_dir(src):
        raise TrashError("no such study in the trash")
    dest = studies_dir / m.group(1)
    if dest.exists():
        raise TrashError(f"a study with id '{m.group(1)}' exists again; rename or trash that one first", conflict=True)
    shutil.move(str(src), str(dest))
    return m.group(1)


def empty(studies_dir):
    """Permanently delete everything in the trash; returns (studies removed, MB freed)."""
    items = list_trash(studies_dir)
    for it in items:
        shutil.rmtree(Path(studies_dir) / TRASH / it["entry"])
    return len(items), round(sum(it["mb"] for it in items), 1)
