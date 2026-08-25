"""Regression against the manually produced TAO Compare 202607 workbook.

This is the test that matters. The report is built from the Daily files alone;
the historical workbook is only ever read here, to check the answer.

Three ground-truth rows are known not to reproduce. They are listed explicitly
rather than tolerated in bulk, and each one is explained in
REVERSE_ENGINEERING.md. A fourth row disagreeing would fail the test.
"""

from __future__ import annotations

import pytest

from app.validation import (
    CALCULATION_MISMATCH,
    EXACT_MATCH,
    GROUND_TRUTH_INCONSISTENT,
    MATCH_WITH_TOLERANCE,
    compare,
    load_ground_truth,
)
from tests.conftest import GROUND_TRUTH, requires_ground_truth

# TFC -> why the historical workbook cannot be reproduced from the sources.
KNOWN_DIVERGENCES = {
    "E044JKPU": CALCULATION_MISMATCH,
    "S564JCAG": CALCULATION_MISMATCH,
    "S033362": GROUND_TRUTH_INCONSISTENT,
}


@pytest.fixture(scope="module")
def result(july_report):
    if not GROUND_TRUTH.exists():
        pytest.skip("no ground-truth workbook")
    return compare(july_report, load_ground_truth(GROUND_TRUTH))


def test_the_same_voyages_are_selected(result):
    assert result.total_generated == result.total_expected


def test_every_normal_row_agrees_with_the_manual_report(result):
    unexpected = [
        c
        for c in result.comparisons
        if c.outcome not in (EXACT_MATCH, MATCH_WITH_TOLERANCE)
        and KNOWN_DIVERGENCES.get(c.tfc) != c.outcome
    ]
    assert not unexpected, "\n" + result.summary()


def test_the_known_divergences_have_not_quietly_been_fixed_by_a_hack(result):
    """If one of these starts matching, the rule behind it changed — reread it."""
    outcomes = {c.tfc: c.outcome for c in result.comparisons}
    for tfc, expected in KNOWN_DIVERGENCES.items():
        assert outcomes.get(tfc) == expected, (
            f"{tfc} now reports {outcomes.get(tfc)}; confirm the change is a real "
            "rule and not a hardcoded exception, then update KNOWN_DIVERGENCES"
        )


def test_at_least_twenty_four_of_twenty_seven_rows_reproduce(result):
    assert result.matched >= 24


def test_operators_are_all_resolved(july_report):
    assert not [r for r in july_report.rows if r.opr == "OPR_UNKNOWN"]


def test_average_waiting_is_written_once_per_service_and_operator(july_report):
    groups = {}
    for row in july_report.rows:
        groups.setdefault(row.group_key, []).append(row)
    for key, rows in groups.items():
        with_average = [r for r in rows if r.average_waiting is not None]
        assert len(with_average) == 1, f"{key} has {len(with_average)} averages"
        assert with_average[0] is rows[0]
        expected = sum(r.waiting.value for r in rows) / len(rows)
        assert abs(with_average[0].average_waiting - expected) < 0.06


def test_rows_are_grouped_by_service_then_operator(july_report):
    keys = [(r.svc, r.opr) for r in july_report.rows]
    assert keys == sorted(keys)


def test_generation_never_reads_the_ground_truth(july_report):
    assert all("TAO Compare" not in name for name in july_report.source_files)


@requires_ground_truth
def test_ground_truth_row_count_is_what_we_think_it_is():
    assert len(load_ground_truth(GROUND_TRUTH)) == 27
