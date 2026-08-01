import os
import sys

# Vercel's Python runtime auto-detects entrypoints under /api, but the real
# app lives in backend/app.py (a `from src....` import structure that assumes
# backend/ itself is on sys.path — exactly like running `python app.py` or
# `uvicorn app:app` locally from inside backend/). This shim reproduces that
# without touching any of backend/app.py's existing imports or local dev flow.
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import app  # noqa: E402 — backend/app.py's FastAPI instance; this IS the Vercel Function
