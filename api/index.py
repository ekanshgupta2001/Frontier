"""
api/index.py — the Vercel entry point.

Vercel's Python runtime looks for a WSGI callable named `app` in this file and
routes every request to it (see vercel.json's catch-all rewrite), so Flask
keeps serving both the API and the frontend exactly as it does locally. There
is no second code path to keep in sync.

Two things differ from `python3 backend/app.py`, both forced by the platform:

1. The filesystem is READ-ONLY except /tmp. store.data_dir() calls
   mkdir(parents=True) on every call, so it must be pointed at /tmp before
   anything imports store — otherwise the first student write raises
   OSError: Read-only file system and returns a 500.

2. /tmp is per-instance and ephemeral. Student progress and events.jsonl
   survive only as long as one warm instance, and two concurrent instances
   cannot see each other's writes. This is a KNOWN and ACCEPTED tradeoff of
   deploying to Vercel: it is fine for a walkthrough demo, and it means this
   deploy cannot host the testing week (CLAUDE.md section 5) — that needs a
   host with a persistent disk, where store.py works unchanged.

Nothing about the three rules in CLAUDE.md section 3 changes here: grading is
still server-side, problem_payload() is still the only Problem serializer, and
the answer still never enters a response.
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Set before backend.app is imported, because that import chain reaches store.
# vercel.json sets this too; this line keeps the file correct on its own.
os.environ.setdefault("NTGEN_DATA_DIR", "/tmp/ntgen-data")

# backend/app.py adds backend/ and backend/ntgen/ to sys.path itself, but it
# has to be importable first.
sys.path.insert(0, str(_ROOT / "backend"))

from app import app  # noqa: E402,F401  — the name Vercel's runtime looks for
