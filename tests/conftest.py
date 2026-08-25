from __future__ import annotations

from pathlib import Path

import pytest

from app.operators import OperatorMapping
from app.parser import discover_daily_files, parse_many
from app.report import build_report
from app.selection import ScopeConfig
from app.voyage_history import build_histories

REPO_ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = REPO_ROOT / "samples" / "daily"
GROUND_TRUTH = REPO_ROOT / "samples" / "ground_truth" / "TAO Compare 202607.xlsx"


# The real berth reports are internal company data and are deliberately not
# kept in the repository, so a fresh clone has an empty samples/ directory.
# Tests that need them skip; the rules they exercise are covered by the unit
# tests either way.
SAMPLES_PRESENT = bool(list(DAILY_DIR.glob("Daily *.xlsx")))
GROUND_TRUTH_PRESENT = GROUND_TRUTH.exists()

requires_samples = pytest.mark.skipif(
    not SAMPLES_PRESENT,
    reason="no Daily workbooks in samples/daily (not kept in the repository)",
)
requires_ground_truth = pytest.mark.skipif(
    not GROUND_TRUTH_PRESENT,
    reason="no ground-truth workbook in samples/ground_truth (not kept in the repository)",
)


@pytest.fixture(scope="session")
def daily_files() -> list[Path]:
    files = discover_daily_files(DAILY_DIR)
    if not files:
        pytest.skip("no Daily workbooks in samples/daily")
    return files


@pytest.fixture(scope="session")
def snapshots(daily_files):
    return parse_many(daily_files)


@pytest.fixture(scope="session")
def history_index(snapshots):
    return build_histories(snapshots)


@pytest.fixture(scope="session")
def july_report(daily_files):
    return build_report(
        daily_files, 2026, 7, OperatorMapping.load(), ScopeConfig.load()
    )
