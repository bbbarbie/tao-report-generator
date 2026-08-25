"""Voyage histories must survive the board being rewritten every day."""

from __future__ import annotations

from datetime import datetime

from app.models import SourceRef, VoyageHistory, VoyageSnapshot
from app.voyage_history import build_histories


def snap(file: str, day: int, **kwargs) -> VoyageSnapshot:
    defaults = dict(svc="CI5", tfc="W605JTCN", terminal="QQCTN", vessel_voyage="TIGER CHENNAI/W605")
    defaults.update(kwargs)
    return VoyageSnapshot(
        source=SourceRef(file, datetime(2026, 7, day), "Daily Berth Report", 10, "WK30"),
        **defaults,
    )


class TestConsolidation:
    def test_later_values_win(self):
        h = VoyageHistory("X")
        h.add(snap("a.xlsx", 1, atb=datetime(2026, 7, 1)))
        h.add(snap("b.xlsx", 2, atb=datetime(2026, 7, 2)))
        assert h.consolidated().atb == datetime(2026, 7, 2)

    def test_a_value_that_disappears_later_is_not_lost(self):
        """Rows get retyped and lose cells; already-observed facts must survive."""
        h = VoyageHistory("X")
        h.add(snap("a.xlsx", 1, ata=datetime(2026, 7, 1, 6, 0), gph=28.5))
        h.add(snap("b.xlsx", 2, ata=None, gph=None))
        merged = h.consolidated()
        assert merged.ata == datetime(2026, 7, 1, 6, 0)
        assert merged.gph == 28.5

    def test_first_seen_reports_when_a_field_appeared(self):
        h = VoyageHistory("X")
        h.add(snap("a.xlsx", 1))
        h.add(snap("b.xlsx", 5, atd=datetime(2026, 7, 5)))
        assert h.first_seen("atd").source_file == "b.xlsx"
        assert h.first_seen("ata") is None

    def test_changes_are_recorded_rather_than_overwritten(self):
        h = VoyageHistory("X")
        h.add(snap("a.xlsx", 1, window_start=datetime(2026, 7, 5, 18, 0)))
        h.add(snap("b.xlsx", 2, window_start=datetime(2026, 7, 19, 18, 0)))
        changes = h.changes()
        assert [c.field_name for c in changes] == ["window_start"]
        assert changes[0].old == datetime(2026, 7, 5, 18, 0)
        assert changes[0].new == datetime(2026, 7, 19, 18, 0)
        assert changes[0].source_file == "b.xlsx"

    def test_snapshots_are_kept_in_chronological_order(self):
        h = VoyageHistory("X")
        h.add(snap("c.xlsx", 9))
        h.add(snap("a.xlsx", 1))
        assert [s.source_file for s in h.snapshots] == ["a.xlsx", "c.xlsx"]


class TestGrouping:
    def test_snapshots_are_grouped_by_tfc(self):
        index = build_histories([snap("a.xlsx", 1), snap("b.xlsx", 2)])
        assert list(index.histories) == ["W605JTCN"]
        assert len(index.histories["W605JTCN"].snapshots) == 2

    def test_consecutive_voyages_of_one_vessel_stay_separate(self):
        """Voyage codes differ by a digit; only berthing at the same time merges."""
        index = build_histories(
            [
                snap("a.xlsx", 1, tfc="S16459", atb=datetime(2026, 7, 2)),
                snap("a.xlsx", 1, tfc="S16559", atb=datetime(2026, 7, 19)),
            ]
        )
        assert set(index.histories) == {"S16459", "S16559"}
        assert not any(n.kind == "MERGED_TFC" for n in index.notes)

    def test_a_retyped_code_for_the_same_berthing_is_merged(self):
        berthed = datetime(2026, 7, 24, 10, 47)
        index = build_histories(
            [
                snap("a.xlsx", 1, tfc="E026JPMZ", atb=berthed, ata=datetime(2026, 7, 21)),
                snap("b.xlsx", 2, tfc="E026JKMZ", atb=berthed, ata=datetime(2026, 7, 21)),
            ]
        )
        assert len(index.histories) == 1
        assert index.resolve("E026JPMZ") is index.resolve("E026JKMZ")
        assert any(n.kind == "MERGED_TFC" for n in index.notes)

    def test_different_services_are_never_merged(self):
        berthed = datetime(2026, 7, 24, 10, 47)
        index = build_histories(
            [
                snap("a.xlsx", 1, tfc="AAA", svc="CI5", atb=berthed),
                snap("a.xlsx", 1, tfc="AAB", svc="CT1", atb=berthed),
            ]
        )
        assert len(index.histories) == 2

    def test_rows_without_a_tfc_are_reported_not_dropped_silently(self):
        index = build_histories([snap("a.xlsx", 1, tfc=None)])
        assert not index.histories
        assert [n.kind for n in index.notes] == ["NO_TFC"]


class TestRealFiles:
    def test_a_voyage_is_tracked_across_many_snapshots(self, history_index):
        history = history_index.resolve("W605JTCN")
        assert len(history.snapshots) > 5
        assert len({s.source_file for s in history.snapshots}) == len(history.snapshots)

    def test_a_voyage_that_vanishes_from_later_files_is_still_kept(self, history_index):
        """AS1's July call stops being printed once the service leaves the board."""
        history = history_index.resolve("E036369")
        assert history is not None
        assert history.consolidated().atd == datetime(2026, 7, 6, 7, 33)
        assert history.latest.snapshot_date < datetime(2026, 7, 31)

    def test_window_revisions_are_visible_in_the_history(self, history_index):
        history = history_index.resolve("W605JTCN")
        moves = [c for c in history.changes() if c.field_name == "window_start"]
        assert moves, "this voyage's window was rescheduled during the month"

    def test_no_voyage_merges_two_different_berthings(self, history_index):
        for history in history_index.all():
            berths = {s.atb for s in history.snapshots if s.atb}
            assert len(berths) <= 3, f"{history.voyage_key} looks like two voyages"
