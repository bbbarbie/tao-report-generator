"""Guards against the rules being fitted to July rather than describing the job.

Every rule was derived by looking at July 2026, the only month with a hand-made
report to check against. This holds out everything that departed later and
re-tests the rules against figures that played no part in deriving them.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
import blind_validation as blind  # noqa: E402

from tests.conftest import requires_samples  # noqa: E402


@pytest.fixture(scope="module")
def snapshots(request):
    from app.parser import discover_daily_files, parse_many

    files = discover_daily_files(REPO_ROOT / "samples" / "daily")
    if not files:
        pytest.skip("no Daily workbooks")
    return parse_many(files)


@pytest.fixture(scope="module")
def fitted(snapshots):
    return blind.evaluate(snapshots, lambda when: when < blind.FIT_PERIOD_END)


@pytest.fixture(scope="module")
def held_out(snapshots):
    return blind.evaluate(snapshots, lambda when: when >= blind.FIT_PERIOD_END)


def rate(result) -> float:
    totals, hits, _, _ = result
    n = sum(totals.values())
    return sum(hits.values()) / n if n else 0.0


@requires_samples
def test_there_is_something_held_out_to_test_against(held_out):
    totals, _, _, _ = held_out
    assert sum(totals.values()) >= 10, (
        "not enough held-out evidence for this test to mean anything; add Daily "
        "files covering a month after the one the rules were derived from"
    )


@requires_samples
def test_the_rules_hold_on_data_they_were_never_fitted_to(held_out):
    assert rate(held_out) >= 0.9, (
        "the rules do not reproduce the Daily's own figures on the held-out "
        "month; they may describe July rather than the business"
    )


@requires_samples
def test_the_rules_do_not_do_markedly_better_on_the_month_they_came_from(
    fitted, held_out
):
    """The overfitting check: a large fitted-minus-held-out gap is the symptom."""
    gap = rate(fitted) - rate(held_out)
    assert gap <= 0.15, (
        f"the rules score {gap:.1%} higher on July than on the held-out month, "
        "which is what fitting to one month's answers looks like"
    )


@requires_samples
def test_every_held_out_disagreement_is_either_explained_or_absent(held_out):
    _, _, misses, _ = held_out
    unexplained = [
        (snap.tfc, field, reported, calculated)
        for field, entries in misses.items()
        for snap, reported, calculated in entries
    ]
    assert not unexplained, (
        "unexplained disagreements on held-out data — run "
        f"tools/blind_validation.py: {unexplained}"
    )


@requires_samples
def test_deliberate_departures_are_the_documented_two_and_nothing_else(held_out):
    """Set-aside rows must be justified by a rule, not used to hide failures."""
    _, _, _, departures = held_out
    reasons = {
        reason
        for entries in departures.values()
        for _, _, _, reason in entries
    }
    allowed = {
        "window corrected onto the service's weekly slot",
        "arrived before its window opened, so W/B is not counted from arrival",
    }
    assert reasons <= allowed, f"undocumented reason for setting a row aside: {reasons - allowed}"


class TestDepartureClassifier:
    """The classifier must not be able to excuse an arbitrary disagreement."""

    def _snap(self, **kwargs):
        from app.models import SourceRef, VoyageSnapshot

        defaults = dict(
            svc="AP2", tfc="X", terminal="QQCTN",
            window_start=datetime(2026, 7, 20, 20, 0),
            window_end=datetime(2026, 7, 21, 12, 0),
            ata=datetime(2026, 7, 20, 23, 0),
            atb=datetime(2026, 7, 22, 0, 13),
        )
        defaults.update(kwargs)
        return VoyageSnapshot(
            source=SourceRef("f.xlsx", datetime(2026, 7, 31), "s", 1, "WK30"),
            **defaults,
        )

    def test_an_ordinary_row_is_never_set_aside(self):
        snap = self._snap()
        for field in ("arr_delay", "dep_delay", "waiting"):
            assert not blind.departs_deliberately(snap, snap, field)

    def test_an_early_arrival_only_excuses_the_waiting_figure(self):
        snap = self._snap(ata=datetime(2026, 7, 20, 10, 0))
        assert blind.departs_deliberately(snap, snap, "waiting")
        assert not blind.departs_deliberately(snap, snap, "arr_delay")
        assert not blind.departs_deliberately(snap, snap, "dep_delay")

    def test_a_corrected_window_excuses_every_figure_on_that_row(self):
        from dataclasses import replace

        snap = self._snap()
        corrected = replace(snap, window_start=datetime(2026, 7, 19, 20, 0))
        for field in ("arr_delay", "dep_delay", "waiting"):
            assert blind.departs_deliberately(snap, corrected, field)
