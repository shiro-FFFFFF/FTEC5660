"""Filesystem path helpers.

The Streamlit app is installed under ``streamlit_app/`` inside the repo root.
All data files (``scam_db.csv``, scenario JSONs, eval reports) live at the
repo root so they can be shared with the legacy Flutter tree if needed.
"""

from __future__ import annotations

from pathlib import Path

# streamlit_app/guardian/paths.py  ->  repo root is three parents up.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

DATA_DIR: Path = REPO_ROOT / "data"
SCAM_DB_CSV: Path = DATA_DIR / "scam_db.csv"
SCAM_DB_RUNTIME_CSV: Path = DATA_DIR / "scam_db_runtime.csv"

SCENARIOS_DIR: Path = REPO_ROOT / "scenarios"

REPORTS_DIR: Path = REPO_ROOT / "reports"
