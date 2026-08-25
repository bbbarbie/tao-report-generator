"""The delay and waiting rules, and how the Daily's own figures are used."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.calculations import (
    REPORTED_DISAGREES,
    UNKNOWN_OPERATOR,
    WINDOW_WEEKDAY_MISMATCH,
    attach_group_averages,
    build_row,
    calc_arr_delay,
    calc_dep_delay,
    calc_waiting,
    effective_window,
)
from app.models import SourceRef, VoyageHistory, VoyageSnapshot
from app.normalization import round_hours
from app.operators import OperatorMapping


def make_snapshot(**kwargs) -> VoyageSnapshot:
    defaults = dict(
        svc="AP2",
        tfc="E1115B",
        terminal="QQCTN",
        vessel_voyage="WAN HAI 511/E111",
        window_start=datetime(2026, 7, 13, 20, 0),
        window_end=datetime(2026, 7, 14, 12, 0),
    )
    defaults.update(kwargs)
    return VoyageSnapshot(
        source=SourceRef("Daily 20260731.xlsx", datetime(2026, 7, 31), "s", 1, "WK29"),
        **defaults,
    )


def history_of(*snapshots) -> VoyageHistory:
    h = VoyageHistory(snapshots[0].tfc or "X")
    for s in snapshots:
        h.add(s)
    return h


class TestArrivalAndDeparture:
    def test_arrival_is_measured_from_the_window_opening(self):
        snap = make_snapshot(ata=datetime(2026, 7, 14, 6, 18))
        assert calc_arr_delay(snap) == 10.3

    def test_arriving_early_gives_a_negative_delay(self):
        snap = make_snapshot(ata=datetime(2026, 7, 13, 8, 0))
        assert calc_arr_delay(snap) == -12.0

    def test_departure_is_measured_from_the_window_closing(self):
        snap = make_snapshot(atd=datetime(2026, 7, 15, 14, 45))
        assert calc_dep_delay(snap) == 26.8

    def test_a_missing_timestamp_yields_no_figure(self):
        assert calc_arr_delay(make_snapshot(ata=None)) is None
        assert calc_dep_delay(make_snapshot(atd=None)) is None
        assert calc_arr_delay(make_snapshot(ata=datetime(2026, 7, 14), window_start=None)) is None


class TestWaiting:
    def test_waiting_runs_from_arrival_when_the_ship_arrives_inside_its_window(self):
        snap = make_snapshot(
            ata=datetime(2026, 7, 14, 6, 18), atb=datetime(2026, 7, 14, 17, 12)
        )
        assert calc_waiting(snap) == 10.9

    def test_waiting_runs_from_the_window_when_the_ship_arrives_early(self):
        """Time spent waiting for your own slot to open is not waiting for a berth."""
        snap = make_snapshot(
            window_start=datetime(2026, 7, 21, 19, 0),
            ata=datetime(2026, 7, 21, 10, 24),
            atb=datetime(2026, 7, 26, 15, 53),
        )
        assert calc_waiting(snap) == 116.9

    def test_berthing_before_the_window_opens_counts_as_no_wait(self):
        snap = make_snapshot(
            window_start=datetime(2026, 7, 6, 20, 0),
            ata=datetime(2026, 7, 6, 8, 0),
            atb=datetime(2026, 7, 6, 19, 7),
        )
        assert calc_waiting(snap) == 0.0

    def test_no_berthing_yields_no_figure(self):
        assert calc_waiting(make_snapshot(ata=datetime(2026, 7, 14), atb=None)) is None


class TestWindowIntegrity:
    def test_a_window_typed_a_day_out_is_moved_onto_its_weekly_slot(self):
        snap = make_snapshot(
            window_start=datetime(2026, 7, 28, 7, 0),   # a Tuesday
            window_end=datetime(2026, 7, 29, 1, 0),
            pattern_start=datetime(2026, 7, 27, 7, 0),  # slot says Monday
            pattern_end=datetime(2026, 7, 28, 1, 0),
        )
        fixed, corrected = effective_window(snap)
        assert corrected
        assert fixed.window_start == datetime(2026, 7, 27, 7, 0)
        assert fixed.window_end == datetime(2026, 7, 28, 1, 0)

    def test_a_stale_label_on_one_end_only_is_left_alone(self):
        snap = make_snapshot(
            window_start=datetime(2026, 7, 7, 19, 0),
            window_end=datetime(2026, 7, 8, 3, 0),      # Wednesday
            pattern_start=datetime(2026, 7, 7, 19, 0),
            pattern_end=datetime(2026, 7, 9, 3, 0),     # label says Thursday
        )
        assert effective_window(snap)[1] is False

    def test_a_whole_week_apart_is_a_different_week_not_a_typo(self):
        snap = make_snapshot(
            window_start=datetime(2026, 7, 27, 18, 0),
            window_end=datetime(2026, 7, 28, 17, 0),
            pattern_start=datetime(2026, 8, 3, 18, 0),
            pattern_end=datetime(2026, 8, 4, 17, 0),
        )
        assert effective_window(snap)[1] is False

    def test_differing_clock_times_are_not_treated_as_a_typo(self):
        snap = make_snapshot(
            window_start=datetime(2026, 7, 2, 21, 30),
            window_end=datetime(2026, 7, 3, 22, 30),
            pattern_start=datetime(2026, 7, 2, 21, 30),
            pattern_end=datetime(2026, 7, 3, 21, 30),
        )
        assert effective_window(snap)[1] is False


class TestRowAssembly:
    mapping = OperatorMapping.load()

    def test_wan_hai_rows_use_the_figures_the_daily_publishes(self):
        """Timestamps are sometimes revised after the figure was struck."""
        snap = make_snapshot(
            ata=datetime(2026, 7, 16, 3, 24),
            atb=datetime(2026, 7, 18, 22, 36),
            atd=datetime(2026, 7, 19, 15, 24),
            waiting_reported=63.6,
            arr_delay_reported=13.4,
            dep_delay_reported=76.4,
        )
        row = build_row(history_of(snap), self.mapping)
        assert row.opr == "WHL"
        assert row.waiting.value == 63.6
        assert row.waiting.method == "copied_from_daily"
        assert row.waiting.calculated_value == round_hours(67.2)
        assert REPORTED_DISAGREES in row.flags

    def test_other_operators_are_calculated_because_the_daily_leaves_them_blank(self):
        snap = make_snapshot(
            tfc="E105JEXP",
            vessel_voyage="MOL EXPERIENCE/E105",
            window_start=datetime(2026, 7, 20, 20, 0),
            window_end=datetime(2026, 7, 21, 12, 0),
            ata=datetime(2026, 7, 20, 23, 0),
            atb=datetime(2026, 7, 22, 0, 13),
            atd=datetime(2026, 7, 22, 22, 50),
        )
        row = build_row(history_of(snap), self.mapping)
        assert row.opr == "ONE"
        assert (row.arr_delay.value, row.dep_delay.value, row.waiting.value) == (3.0, 34.8, 25.2)
        assert row.arr_delay.method == "calculated"
        assert not row.flags

    def test_a_corrected_window_forces_recalculation_even_for_wan_hai(self):
        snap = make_snapshot(
            tfc="W02762B",
            vessel_voyage="WAN HAI 622/W027",
            window_start=datetime(2026, 7, 28, 7, 0),
            window_end=datetime(2026, 7, 29, 1, 0),
            pattern_start=datetime(2026, 7, 27, 7, 0),
            pattern_end=datetime(2026, 7, 28, 1, 0),
            ata=datetime(2026, 7, 20, 17, 28),
            atb=datetime(2026, 7, 27, 3, 30),
            atd=datetime(2026, 7, 27, 15, 10),
            arr_delay_reported=-181.5,
            dep_delay_reported=-33.8,
            waiting_reported=0.0,
        )
        row = build_row(history_of(snap), self.mapping)
        assert WINDOW_WEEKDAY_MISMATCH in row.flags
        assert row.arr_delay.value == -157.5
        assert row.dep_delay.value == -9.8
        assert row.arr_delay.method == "calculated"

    def test_an_unrecognised_vessel_is_flagged_not_guessed(self):
        snap = make_snapshot(vessel_voyage="MYSTERY STAR/X001", tfc="X001ABC")
        row = build_row(history_of(snap), self.mapping)
        assert row.opr == "OPR_UNKNOWN"
        assert UNKNOWN_OPERATOR in row.flags

    def test_the_terminal_column_names_the_service_not_the_berth(self):
        snap = make_snapshot(terminal="QQCTUA")
        row = build_row(history_of(snap), self.mapping, service_terminal="QQCTN")
        assert row.terminal == "QQCTN"
        assert "TERMINAL_DIFFERS_FROM_SERVICE" in row.flags

    def test_provenance_names_the_file_a_value_came_from(self):
        snap = make_snapshot(ata=datetime(2026, 7, 14, 6, 18), atb=datetime(2026, 7, 14, 17, 12))
        row = build_row(history_of(snap), self.mapping)
        assert row.waiting.source_file == "Daily 20260731.xlsx"
        assert row.waiting.formula


class TestGroupAverages:
    def test_average_is_per_service_and_operator_on_the_first_row(self):
        rows = [
            build_row(
                history_of(
                    make_snapshot(
                        svc="AP2",
                        tfc=f"T{i}",
                        vessel_voyage="NYK RUMINA/E076",
                        ata=datetime(2026, 7, 20, 20, 0),
                        atb=datetime(2026, 7, 20, 20, 0) + timedelta(hours=hours),
                    )
                ),
                OperatorMapping.load(),
            )
            for i, hours in enumerate((0, 25.2))
        ]
        attach_group_averages(rows)
        assert rows[0].average_waiting == 12.6
        assert rows[1].average_waiting is None

    def test_separate_operators_on_one_service_average_separately(self):
        one = build_row(history_of(make_snapshot(
            tfc="A", vessel_voyage="NYK RUMINA/E076",
            ata=datetime(2026, 7, 14, 0, 0), atb=datetime(2026, 7, 14, 10, 0))),
            OperatorMapping.load())
        whl = build_row(history_of(make_snapshot(
            tfc="B", vessel_voyage="WAN HAI 511/E111",
            ata=datetime(2026, 7, 14, 0, 0), atb=datetime(2026, 7, 14, 20, 0))),
            OperatorMapping.load())
        rows = [one, whl]
        attach_group_averages(rows)
        assert one.average_waiting == 10.0
        assert whl.average_waiting == 20.0

    def test_rows_without_a_waiting_figure_do_not_drag_the_average(self):
        with_value = build_row(history_of(make_snapshot(
            tfc="A", ata=datetime(2026, 7, 14, 0, 0), atb=datetime(2026, 7, 14, 10, 0))),
            OperatorMapping.load())
        without = build_row(history_of(make_snapshot(tfc="B", atb=None)), OperatorMapping.load())
        rows = [with_value, without]
        attach_group_averages(rows)
        assert with_value.average_waiting == 10.0
