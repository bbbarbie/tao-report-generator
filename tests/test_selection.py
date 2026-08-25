"""Month membership and report scope."""

from __future__ import annotations

from datetime import datetime

from app.models import SourceRef, VoyageSnapshot
from app.operators import OperatorMapping
from app.selection import (
    NO_ATD,
    NOT_QINGDAO,
    OTHER_MONTH,
    SERVICE_EXCLUDED,
    ScopeConfig,
    select_for_month,
    service_terminals,
)
from app.voyage_history import build_histories

MAPPING = OperatorMapping.load()


def snap(file: str, day: int, **kwargs) -> VoyageSnapshot:
    defaults = dict(
        svc="CI5",
        tfc="W605JTCN",
        terminal="QQCTN",
        vessel_voyage="WAN HAI 501/W267",
        window_start=datetime(2026, 7, 19, 18, 0),
        window_end=datetime(2026, 7, 20, 8, 0),
    )
    defaults.update(kwargs)
    return VoyageSnapshot(
        source=SourceRef(file, datetime(2026, 7, day), "s", 10, "WK30"), **defaults
    )


def index_of(*snapshots):
    return build_histories(list(snapshots))


class TestMonthMembership:
    def test_a_voyage_belongs_to_the_month_it_departed_in(self):
        june = snap("a.xlsx", 1, tfc="A", atd=datetime(2026, 6, 30, 23, 59))
        july = snap("a.xlsx", 1, tfc="B", atd=datetime(2026, 7, 1, 0, 1))
        result = select_for_month(index_of(june, july), 2026, 7, MAPPING)
        assert [h.voyage_key for h in result.selected] == ["B"]
        assert any(r.reason == OTHER_MONTH for r in result.rejected)

    def test_the_last_day_of_the_month_is_included(self):
        late = snap("a.xlsx", 1, atd=datetime(2026, 7, 31, 23, 59))
        assert select_for_month(index_of(late), 2026, 7, MAPPING).selected

    def test_arrival_and_berthing_in_the_previous_month_do_not_matter(self):
        spanning = snap(
            "a.xlsx", 1,
            ata=datetime(2026, 6, 28, 10, 18),
            atb=datetime(2026, 6, 30, 8, 10),
            atd=datetime(2026, 7, 1, 1, 10),
        )
        assert select_for_month(index_of(spanning), 2026, 7, MAPPING).selected

    def test_a_missing_departure_is_never_invented(self):
        pending = snap("a.xlsx", 1, ata=datetime(2026, 7, 20), atb=datetime(2026, 7, 21), atd=None)
        result = select_for_month(index_of(pending), 2026, 7, MAPPING)
        assert not result.selected
        assert [r.reason for r in result.rejected] == [NO_ATD]

    def test_rizhao_berths_are_a_different_port(self):
        rzh = snap("a.xlsx", 1, terminal="RZH", atd=datetime(2026, 7, 10))
        result = select_for_month(index_of(rzh), 2026, 7, MAPPING)
        assert not result.selected
        assert [r.reason for r in result.rejected] == [NOT_QINGDAO]

    def test_berth_groups_within_qingdao_all_count(self):
        for terminal in ("QQCT-2", "QQCTU", "QQCTUA", "QQCTN"):
            row = snap("a.xlsx", 1, terminal=terminal, atd=datetime(2026, 7, 10))
            assert select_for_month(index_of(row), 2026, 7, MAPPING).selected, terminal


class TestScope:
    def test_a_service_with_no_wan_hai_vessel_is_out_of_scope(self):
        cosco = snap(
            "a.xlsx", 1, svc="WS3", tfc="E098JJEF",
            vessel_voyage="COSCO AMERICA/E098", atd=datetime(2026, 7, 12),
        )
        result = select_for_month(index_of(cosco), 2026, 7, MAPPING)
        assert not result.selected
        assert result.service_scope["WS3"] == "SERVICE_HAS_NO_WAN_HAI_VESSEL"

    def test_that_rule_can_be_turned_off(self):
        cosco = snap(
            "a.xlsx", 1, svc="WS3", tfc="E098JJEF",
            vessel_voyage="COSCO AMERICA/E098", atd=datetime(2026, 7, 12),
        )
        config = ScopeConfig(require_house_vessel=False, require_stable_service=False)
        assert select_for_month(index_of(cosco), 2026, 7, MAPPING, config).selected

    def test_a_service_that_starts_mid_period_is_out_of_scope(self):
        old = snap("a.xlsx", 1, tfc="OLD", atd=datetime(2026, 7, 5))
        new_early = snap("b.xlsx", 9, svc="AMX", tfc="NEW", atd=datetime(2026, 7, 18))
        result = select_for_month(index_of(old, new_early), 2026, 7, MAPPING)
        assert result.service_scope["AMX"] == "SERVICE_NOT_ACTIVE_FOR_WHOLE_PERIOD"

    def test_config_can_force_a_service_in_or_out(self):
        row = snap("a.xlsx", 1, atd=datetime(2026, 7, 10))
        forced_out = ScopeConfig(exclude=["CI5"])
        result = select_for_month(index_of(row), 2026, 7, MAPPING, forced_out)
        assert not result.selected
        assert [r.reason for r in result.rejected] == [SERVICE_EXCLUDED]

        forced_in = ScopeConfig(include=["CI5"], require_house_vessel=True)
        assert select_for_month(index_of(row), 2026, 7, MAPPING, forced_in).selected

    def test_the_shipped_scope_config_loads(self):
        config = ScopeConfig.load()
        assert config.require_house_vessel and config.require_stable_service


class TestServiceTerminal:
    def test_the_most_recent_file_decides_a_services_terminal(self):
        old = snap("a.xlsx", 1, tfc="A", terminal="QQCTU")
        new = snap("b.xlsx", 9, tfc="B", terminal="QQCTN")
        assert service_terminals(index_of(old, new))["CI5"] == "QQCTN"

    def test_berth_group_suffixes_are_normalised_away(self):
        row = snap("a.xlsx", 1, svc="CS3", terminal="QQCT-2")
        assert service_terminals(index_of(row))["CS3"] == "QQCT"


class TestRealFiles:
    def test_july_scope_matches_the_services_the_report_covers(self, july_report):
        in_scope = {
            svc for svc, verdict in july_report.selection.service_scope.items()
            if verdict == "in"
        }
        qingdao = {r.svc for r in july_report.rows}
        assert qingdao <= in_scope
        assert "WS3" not in qingdao and "AS1" not in qingdao

    def test_nothing_is_dropped_without_a_recorded_reason(self, july_report):
        for rejection in july_report.selection.rejected:
            assert rejection.reason


class TestDegradedInput:
    def test_a_single_snapshot_disables_the_stability_rule(self):
        """With one file there is no appearing or disappearing to observe."""
        only = snap("a.xlsx", 31, svc="AMX", atd=datetime(2026, 7, 18))
        result = select_for_month(index_of(only), 2026, 7, MAPPING)
        assert result.service_scope["AMX"] == "in"

    def test_reading_only_the_month_end_file_loses_voyages(self, daily_files):
        """The justification for ingesting every snapshot, asserted rather than assumed."""
        from app.report import build_report

        month_end = [p for p in daily_files if p.name == "Daily 20260731.xlsx"]
        assert month_end
        partial = build_report(month_end, 2026, 7)
        full = build_report(daily_files, 2026, 7)
        assert len(partial.rows) < len(full.rows)
        assert any(i.reason == "ONLY_ONE_DAILY_FILE_SUPPLIED" for i in partial.review)
