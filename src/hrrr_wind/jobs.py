"""Background jobs for the web app: download wind data, recompute analysis or validation.

Every job runs ``python -m hrrr_wind.venue_analysis ...`` as a separate process. That keeps
the web server light, lets a job be cancelled by killing it (download checkpoints survive and
a rerun resumes), and means the per-process memory cap (``--max-rss-gb``) protects the machine.
One job runs at a time. Job state lives in memory; logs are written to ``<out_dir>/jobs/``.
"""
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from hrrr_wind.config import cache_plan, FIRST_YEAR, MAX_WINDOW_DAYS, MAX_YEARS  # noqa: F401

KINDS = ("cache", "analyze", "validate", "run_study")
TAG_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
FILES_PER_SECOND = 1.9                 # observed download rate, used only for the estimate
STALL_SECONDS = 600                    # no output this long = hung connection: stop the job so it can resume
MIN_RSS_GB, MAX_RSS_GB, DEFAULT_RSS_GB = 1.0, 8.0, 4.0


class JobError(ValueError):
    """The request is invalid (HTTP 422)."""


class JobConflict(RuntimeError):
    """The request conflicts with current state: a job is running, or data would be overwritten (HTTP 409)."""


@dataclass
class Job:
    id: str
    study_id: str
    kind: str
    params: dict
    status: str = "queued"             # queued | running | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    returncode: int | None = None
    log_path: Path | None = None
    last_output: float = field(default_factory=time.time)
    stalled: bool = False

    def public(self):
        return {"id": self.id, "study_id": self.study_id, "kind": self.kind, "params": self.params,
                "status": self.status, "progress": self.progress, "message": self.message,
                "created": self.created, "started": self.started, "finished": self.finished,
                "returncode": self.returncode}


def _mmdd(text, name):
    try:
        return datetime.strptime(f"2001-{text}", "%Y-%m-%d")   # 2001: not a leap year
    except (TypeError, ValueError):
        raise JobError(f"{name} must be MM-DD, got {text!r}")


def estimate(params):
    """Rough size of a download: hourly files and minutes."""
    days = (_mmdd(params["end"], "end") - _mmdd(params["start"], "start")).days + 1
    hours = int(params.get("end_hour", 23)) - int(params.get("start_hour", 0)) + 1
    files = len(params["years"]) * days * hours
    return {"files": files, "minutes": round(files / FILES_PER_SECOND / 60, 1)}


def validate_cache_params(study, p):
    """Check and normalize the parameters of a download job; raises JobError / JobConflict."""
    venues = p.get("venues") or list(study.venues)
    unknown = [v for v in venues if v not in study.venues]
    if unknown:
        raise JobError(f"unknown venue(s): {unknown}")
    years = sorted({int(y) for y in p.get("years", [])})
    if not years or years[0] < FIRST_YEAR or years[-1] > date.today().year or len(years) > MAX_YEARS:
        raise JobError(f"years must be {FIRST_YEAR}-{date.today().year}, at most {MAX_YEARS} of them")
    start, end = p.get("start"), p.get("end")
    d0, d1 = _mmdd(start, "start"), _mmdd(end, "end")
    if d1 < d0 or (d1 - d0).days + 1 > MAX_WINDOW_DAYS:
        raise JobError(f"window must run forward within one year and span at most {MAX_WINDOW_DAYS} days")
    tag = str(p.get("tag", ""))
    if not TAG_RE.match(tag):
        raise JobError("tag must be 1-40 letters, digits or underscores")
    sh, eh = int(p.get("start_hour", 0)), int(p.get("end_hour", 23))
    if not (0 <= sh <= eh <= 23):
        raise JobError("hours must satisfy 0 <= start_hour <= end_hour <= 23")
    rss = float(p.get("max_rss_gb", DEFAULT_RSS_GB))
    if not (MIN_RSS_GB <= rss <= MAX_RSS_GB):
        raise JobError(f"max_rss_gb must be between {MIN_RSS_GB} and {MAX_RSS_GB}")
    existing = [v for v in venues if (study.out_dir / f"cache_{v}_{tag}.npz").exists()]
    if existing:
        raise JobConflict(f"cache_{existing[0]}_{tag}.npz already exists; choose a new tag so existing data is never overwritten")
    return {"venues": venues, "years": years, "start": start, "end": end, "tag": tag,
            "start_hour": sh, "end_hour": eh, "max_rss_gb": rss}


def validate_run_params(study, p):
    """Check a run_study job: only the memory cap is user-chosen; the plan comes from study.toml."""
    rss = float(p.get("max_rss_gb", DEFAULT_RSS_GB))
    if not (MIN_RSS_GB <= rss <= MAX_RSS_GB):
        raise JobError(f"max_rss_gb must be between {MIN_RSS_GB} and {MAX_RSS_GB}")
    return {"max_rss_gb": rss, "downloads": cache_plan(study)}


def build_command(study_path, kind, params):
    cmd = [sys.executable, "-W", "ignore", "-m", "hrrr_wind.venue_analysis",
           "--progress-lines", "--study", str(study_path), "run" if kind == "run_study" else kind]
    if kind == "run_study":
        cmd += ["--max-rss-gb", str(params["max_rss_gb"])]
    elif kind == "cache":
        cmd += ["--venues", *params["venues"], "--tag", params["tag"],
                "--years", *map(str, params["years"]), "--start", params["start"],
                "--end", params["end"], "--start-hour", str(params["start_hour"]),
                "--end-hour", str(params["end_hour"]), "--max-rss-gb", str(params["max_rss_gb"]),
                "--chunk-hours", "24"]
    return cmd


class JobManager:
    def __init__(self, command_builder=build_command):
        self._jobs: dict[str, Job] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._command_builder = command_builder

    # -- queries --------------------------------------------------------------------------
    def get(self, job_id):
        return self._jobs.get(job_id)

    def list(self, study_id):
        return sorted((j for j in self._jobs.values() if j.study_id == study_id),
                      key=lambda j: j.created, reverse=True)

    def log_tail(self, job_id, lines=60):
        job = self._jobs.get(job_id)
        if not job or not job.log_path or not job.log_path.exists():
            return ""
        return "".join(job.log_path.read_text(errors="replace").splitlines(keepends=True)[-lines:])

    def running(self):
        return next((j for j in self._jobs.values() if j.status in ("queued", "running")), None)

    # -- commands -------------------------------------------------------------------------
    def submit(self, study_id, study, study_path, kind, params=None):
        if kind not in KINDS:
            raise JobError(f"kind must be one of {KINDS}")
        params = validate_cache_params(study, params or {}) if kind == "cache" else {}
        if kind == "run_study":
            params = validate_run_params(study, params or {})
        with self._lock:
            busy = self.running()
            if busy:
                raise JobConflict(f"job {busy.id} ({busy.kind}) is still running")
            job = Job(id=uuid.uuid4().hex[:10], study_id=study_id, kind=kind, params=params)
            log_dir = study.out_dir / "jobs"
            log_dir.mkdir(parents=True, exist_ok=True)
            job.log_path = log_dir / f"{job.id}.log"
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, self._command_builder(study_path, kind, params)),
                         daemon=True).start()
        return job

    def cancel(self, job_id):
        job = self._jobs.get(job_id)
        if not job:
            return None
        proc = self._procs.get(job_id)
        if job.status in ("queued", "running") and proc and proc.poll() is None:
            job.status = "cancelled"
            proc.terminate()
        return job

    # -- worker ---------------------------------------------------------------------------
    def _run(self, job, cmd):
        job.status, job.started = "running", time.time()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as e:
            job.status, job.message, job.finished = "failed", str(e), time.time()
            return
        self._procs[job.id] = proc
        job.last_output = time.time()
        threading.Thread(target=self._watch, args=(job, proc), daemon=True).start()
        with open(job.log_path, "w") as log:
            for line in proc.stdout:
                job.last_output = time.time()
                log.write(line)
                log.flush()
                if line.startswith("PROGRESS "):
                    _, frac, *msg = line.rstrip("\n").split(" ", 2)
                    try:
                        job.progress = float(frac)
                    except ValueError:
                        continue
                    job.message = msg[0] if msg else ""
        job.returncode = proc.wait()
        job.finished = time.time()
        if job.status != "cancelled":
            job.status = "done" if job.returncode == 0 else "failed"
            if job.stalled:
                job.message = "stalled (no network activity); press Try again to resume"
            elif job.status == "done":
                job.progress, job.message = 1.0, "finished"
            else:
                job.message = (self.log_tail(job.id, 3).strip().splitlines() or ["failed"])[-1][:200]
        self._procs.pop(job.id, None)

    def _watch(self, job, proc, stall=None, poll=5):
        """Stop a job that has printed nothing for ``stall`` seconds (a hung connection)."""
        stall = STALL_SECONDS if stall is None else stall
        while proc.poll() is None:
            time.sleep(poll)
            if proc.poll() is None and time.time() - job.last_output > stall:
                job.stalled = True
                proc.terminate()
                return
