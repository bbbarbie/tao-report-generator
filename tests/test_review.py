"""What the system asks about, and what it refuses to guess."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.decisions import VESSEL_OPERATOR, DecisionStore
from app.report import build_report
from app.review import (
    BERTHED_BEFORE_WINDOW,
    CONFLICTING_SNAPSHOTS,
    MISSING_ATD,
    UNCERTAIN_WINDOW,
    UNKNOWN_OPERATOR,
    VALUE_DISAGREEMENT,
)


@pytest.fixture
def fresh_store(tmp_path):
    """A store with nothing in it, so the user's own file is never touched."""
    return DecisionStore(path=tmp_path / "decisions.json")


@pytest.fixture
def report(daily_files, fresh_store):
    return build_report(daily_files, 2026, 7, store=fresh_store)


class TestIssueShape:
    def test_every_issue_can_be_acted_on(self, report):
        for issue in report.issues:
            assert issue.question.strip().endswith("?")
            assert len(issue.options) >= 2, f"{issue.id} offers no choice"
            assert issue.voyage_key and issue.field
            assert issue.source_files, f"{issue.id} cites no source file"

    def test_every_issue_shows_the_voyage_and_its_timestamps(self, report):
        for issue in report.issues:
            assert issue.svc or issue.tfc
            assert set(issue.timestamps) >= {"ATA", "ATB", "ATD"}

    def test_a_recommendation_always_comes_with_a_reason(self, report):
        for issue in report.issues:
            if issue.recommended is not None:
                assert issue.why_recommended, f"{issue.id} recommends without saying why"

    def test_at_most_one_option_is_recommended(self, report):
        for issue in report.issues:
            assert sum(1 for o in issue.options if o.recommended) <= 1

    def test_ids_are_stable_across_runs(self, daily_files, fresh_store):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        assert [i.id for i in first.issues] == [i.id for i in second.issues]


class TestWhatIsAsked:
    def test_the_expected_kinds_are_raised_for_july(self, report):
        kinds = {i.kind for i in report.issues}
        assert VALUE_DISAGREEMENT in kinds
        assert UNCERTAIN_WINDOW in kinds
        assert BERTHED_BEFORE_WINDOW in kinds
        assert MISSING_ATD in kinds

    def test_a_ten_day_correction_in_the_daily_is_surfaced(self, report):
        """One Daily file typed a berthing as the 13th, the next as the 23rd."""
        conflicts = [i for i in report.issues if i.kind == CONFLICTING_SNAPSHOTS]
        assert any(i.tfc == "S564JCAG" and i.field == "atb" for i in conflicts)

    def test_minute_level_refinements_are_not_raised_as_conflicts(self, report):
        """A timestamp sharpened by a few minutes is the board doing its job."""
        conflicts = {(i.tfc, i.field) for i in report.issues if i.kind == CONFLICTING_SNAPSHOTS}
        assert ("W001903", "atb") not in conflicts  # 3 minutes
        assert ("E1115B", "ata") not in conflicts  # 18 minutes

    def test_missing_departures_are_only_raised_for_services_in_the_report(self, report):
        in_scope = {
            svc for svc, verdict in report.selection.service_scope.items()
            if verdict == "in"
        }
        for issue in report.issues:
            if issue.kind == MISSING_ATD:
                assert issue.svc in in_scope

    def test_nothing_is_blocking_in_july(self, report):
        """Every vessel resolves, so no required field is left empty."""
        assert report.blocking_issues == []

    def test_unrecognised_vessels_block_their_rows(self, daily_files, fresh_store):
        """OPR is a required column, so an unknown carrier leaves a row unfinished."""
        from app.operators import OperatorMapping

        house_only = OperatorMapping(
            {"house_operator": "WHL", "keywords": [["WAN HAI", "WHL"]]}
        )
        blind = build_report(
            daily_files, 2026, 7, mapping=house_only, store=fresh_store
        )
        blocking = blind.blocking_issues
        assert blocking
        assert all(i.kind == UNKNOWN_OPERATOR for i in blocking)
        assert all(i.reusable for i in blocking)
        # The month still generates; only the unfinished rows are held back.
        assert blind.rows
        blocked = {i.voyage_key for i in blocking}
        for row in blind.rows:
            if row.voyage_key in blocked:
                assert row.resolution == "unresolved"

    def test_a_mapping_that_knows_nothing_produces_no_report_rather_than_guesses(
        self, daily_files, fresh_store
    ):
        """With no WAN HAI vessel recognisable, no service qualifies at all."""
        from app.operators import OperatorMapping

        empty = OperatorMapping({"house_operator": "WHL"})
        blind = build_report(daily_files, 2026, 7, mapping=empty, store=fresh_store)
        assert blind.rows == []
        assert all(
            verdict != "in" for verdict in blind.selection.service_scope.values()
        )

    def test_an_unknown_operator_offers_the_carriers_on_that_service(
        self, daily_files, fresh_store
    ):
        from app.operators import OperatorMapping

        partial = OperatorMapping.load()
        partial.vessels.pop("NYK RUMINA", None)
        partial.keywords = [k for k in partial.keywords if k[0] != "NYK"]
        blind = build_report(daily_files, 2026, 7, mapping=partial, store=fresh_store)
        issue = next(i for i in blind.issues if i.kind == UNKNOWN_OPERATOR)
        assert "WHL" in {o.key for o in issue.options}
        assert issue.blocking and issue.reusable


class TestResolution:
    def test_rows_are_split_three_ways_and_add_up(self, report):
        total = sum(
            len(report.rows_by_resolution(s)) for s in ("auto", "reviewed", "unresolved")
        )
        assert total == len(report.rows)

    def test_a_row_with_an_open_question_is_not_called_automatic(self, report):
        with_questions = {i.voyage_key for i in report.issues}
        for row in report.rows:
            if row.voyage_key in with_questions:
                assert row.resolution == "unresolved"

    def test_a_row_with_no_question_is_automatic(self, report):
        with_questions = {i.voyage_key for i in report.issues}
        for row in report.rows:
            if row.voyage_key not in with_questions:
                assert row.resolution == "auto"


class TestApplyingDecisions:
    def test_an_answered_question_stops_being_asked(self, daily_files, fresh_store):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        issue = next(i for i in first.issues if i.kind == VALUE_DISAGREEMENT)
        fresh_store.record_override(
            "202607", issue.voyage_key, issue.field,
            issue.option("calculated").value, issue.kind, "calculated",
        )
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        assert issue.id not in {i.id for i in second.issues}

    def test_an_answer_changes_the_figure_and_marks_the_row_reviewed(
        self, daily_files, fresh_store
    ):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        issue = next(i for i in first.issues if i.kind == VALUE_DISAGREEMENT)
        chosen = issue.option("calculated").value
        fresh_store.record_override(
            "202607", issue.voyage_key, issue.field, chosen, issue.kind, "calculated"
        )
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        row = next(r for r in second.rows if r.voyage_key == issue.voyage_key)
        assert getattr(row, issue.field).value == chosen
        assert getattr(row, issue.field).method == "chosen_in_review"
        assert row.resolution == "reviewed"
        assert row.decisions

    def test_an_operator_rule_applies_without_being_asked_again(
        self, daily_files, fresh_store
    ):
        from app.operators import OperatorMapping

        partial = OperatorMapping.load()
        partial.vessels.pop("NYK RUMINA", None)
        partial.keywords = [k for k in partial.keywords if k[0] != "NYK"]
        blind = build_report(daily_files, 2026, 7, mapping=partial, store=fresh_store)
        issue = next(i for i in blind.issues if i.kind == UNKNOWN_OPERATOR)

        fresh_store.record_rule(VESSEL_OPERATOR, issue.target, "opr", "ONE", "ONE")
        again = build_report(
            daily_files, 2026, 7, mapping=partial, store=fresh_store
        )
        assert issue.id not in {i.id for i in again.issues}
        row = next(r for r in again.rows if r.voyage_key == issue.voyage_key)
        assert row.opr == "ONE"

    def test_a_missing_departure_can_be_supplied_and_the_voyage_admitted(
        self, daily_files, fresh_store
    ):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        issue = next(i for i in first.issues if i.kind == MISSING_ATD)
        assert issue.voyage_key not in {r.voyage_key for r in first.rows}

        fresh_store.record_override(
            "202607", issue.voyage_key, "atd",
            datetime(2026, 7, 30, 12, 0).isoformat(), issue.kind, "manual",
        )
        fresh_store.record_override(
            "202607", issue.voyage_key, "include", True, issue.kind, "manual"
        )
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        row = next((r for r in second.rows if r.voyage_key == issue.voyage_key), None)
        assert row is not None
        assert row.atd == datetime(2026, 7, 30, 12, 0)
        assert row.resolution == "reviewed"

    def test_a_voyage_can_be_taken_out_of_the_month(self, daily_files, fresh_store):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        victim = first.rows[0].voyage_key
        fresh_store.record_override("202607", victim, "include", False, "", "exclude")
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        assert victim not in {r.voyage_key for r in second.rows}
        assert len(second.rows) == len(first.rows) - 1

    def test_choosing_the_window_as_written_undoes_the_correction(
        self, daily_files, fresh_store
    ):
        first = build_report(daily_files, 2026, 7, store=fresh_store)
        issue = next(i for i in first.issues if i.kind == UNCERTAIN_WINDOW)
        as_written = issue.option("as_written").value
        fresh_store.record_override(
            "202607", issue.voyage_key, "window",
            [v.isoformat() for v in as_written], issue.kind, "as_written",
        )
        second = build_report(daily_files, 2026, 7, store=fresh_store)
        row = next(r for r in second.rows if r.voyage_key == issue.voyage_key)
        assert row.window_start == as_written[0]
        # With the written window restored, the Daily's own figures apply again.
        assert row.arr_delay.value == -181.5
