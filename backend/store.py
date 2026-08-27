"""
store.py — everything mutable lives here.

Student state and the event log are plain files under one data directory, so
week 3 needs no database: a student is a JSON file you can open, a reset is a
deletion, and the analysis input is one JSONL you can grep.

The directory comes from $NTGEN_DATA_DIR when set (the leak test points it at
a temp dir; production points it OUTSIDE the git tree so a redeploy can never
touch student data) and defaults to <repo>/data for local runs.
"""

import json
import os
import re
import threading
import time
from pathlib import Path


# One lock for every read-modify-write. At 15 students typing at human speed
# contention is zero; per-student locks would be complexity with no payoff.
# RLock because log_event runs inside request handlers that already hold it.
LOCK = threading.RLock()


def data_dir() -> Path:
    root = os.environ.get("NTGEN_DATA_DIR")
    d = Path(root) if root else Path(__file__).resolve().parent.parent / "data"
    (d / "students").mkdir(parents=True, exist_ok=True)
    return d


def slugify(name: str) -> str:
    """'Ava G' -> 'ava_g'. The slug is both the storage key and the API
    identity, so it must never contain path characters."""
    s = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_")
    return s[:32]


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def student_path(key: str) -> Path:
    return data_dir() / "students" / f"{key}.json"


def load_student(key: str):
    p = student_path(key)
    if not key or not p.exists():
        return None
    return json.loads(p.read_text())


def save_student(key: str, state: dict) -> None:
    """Write a temp file, then os.replace — atomic on POSIX, so a crash
    mid-write leaves the previous version intact instead of torn JSON."""
    state["updated"] = timestamp()
    p = student_path(key)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, p)


def jsonable(value):
    """Problem params can carry SymPy Integers (derived values are computed
    by sympy), which json.dumps refuses. Exact integers become plain ints;
    anything else becomes a string rather than silently truncating."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    try:
        i = int(value)
        if value == i:
            return i
    except (TypeError, ValueError):
        pass
    return str(value)


def log_event(event: dict) -> None:
    """Append one line to events.jsonl.

    EVERY submission lands here, including unparseable ones — those are week
    3's analysis input (PROJECT.md 4.3). The line carries params but never
    answers, so leaking the logfile leaks nothing a student could use.
    """
    event = jsonable(dict(event))
    event.setdefault("ts", timestamp())
    with LOCK:
        with open(data_dir() / "events.jsonl", "a") as f:
            f.write(json.dumps(event) + "\n")
