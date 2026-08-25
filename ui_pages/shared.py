"""State and small helpers shared by the screens."""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from app.decisions import DecisionStore
from app.operators import OperatorMapping
from app.report import MonthlyReport, build_report
from app.selection import ScopeConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DAILY_DIR = REPO_ROOT / "samples" / "daily"
OUTPUT_DIR = REPO_ROOT / "output"

GENERATE = "Generate"
REVIEW = "Needs Review"
DECISIONS = "Saved decisions"


def store() -> DecisionStore:
    """One decision store per session, so edits are visible across screens."""
    if "store" not in st.session_state:
        st.session_state["store"] = DecisionStore.load()
    return st.session_state["store"]


def report() -> MonthlyReport | None:
    return st.session_state.get("report")


def stage_uploads(uploaded) -> list[Path]:
    """Write uploaded workbooks to a temp folder, keeping their filenames.

    The filename carries the snapshot date, so it has to survive the upload.
    """
    folder = Path(tempfile.mkdtemp(prefix="tao-daily-"))
    paths = []
    for item in uploaded:
        target = folder / item.name
        target.write_bytes(item.getbuffer())
        paths.append(target)
    return paths


def run_report(files: list[Path], year: int, month: int) -> MonthlyReport:
    """Rebuild the month with every decision made so far applied."""
    built = build_report(
        files,
        int(year),
        int(month),
        OperatorMapping.load(),
        ScopeConfig.load(),
        store(),
    )
    st.session_state["report"] = built
    st.session_state["files"] = files
    st.session_state["period"] = (int(year), int(month))
    return built


def rerun_with_decisions() -> None:
    """Re-process after a decision, so its effect is visible immediately."""
    files = st.session_state.get("files")
    period = st.session_state.get("period")
    if files and period:
        run_report(files, *period)


def go(page: str) -> None:
    st.session_state["page"] = page


def moment(value) -> str:
    return value.strftime("%d %b %Y %H:%M") if value else "—"
