from datetime import date, datetime

import pytest

from app.normalization import (
    is_blank,
    is_qingdao,
    normalize_terminal,
    parse_daytime,
    parse_number,
    parse_window,
    parse_window_pattern,
    round_hours,
    week_label,
    week_monday,
)


class TestDayTimeTokens:
    def test_resolves_to_the_month_nearest_the_anchor(self):
        anchor = datetime(2026, 7, 20)
        assert parse_daytime("24/0142", anchor) == datetime(2026, 7, 24, 1, 42)

    def test_crosses_into_the_next_month(self):
        anchor = datetime(2026, 7, 27)
        assert parse_daytime("01/0110", anchor) == datetime(2026, 8, 1, 1, 10)

    def test_crosses_back_into_the_previous_month(self):
        anchor = datetime(2026, 8, 3)
        assert parse_daytime("28/1500", anchor) == datetime(2026, 7, 28, 15, 0)

    def test_crosses_a_year_boundary(self):
        assert parse_daytime("02/0900", datetime(2025, 12, 29)) == datetime(
            2026, 1, 2, 9, 0
        )

    def test_single_digit_day(self):
        assert parse_daytime("3/0754", datetime(2026, 7, 1)) == datetime(2026, 7, 3, 7, 54)

    def test_2400_is_midnight_ending_that_day(self):
        assert parse_daytime("15/2400", datetime(2026, 7, 14)) == datetime(2026, 7, 16, 0, 0)

    def test_skips_days_that_do_not_exist_in_the_nearer_month(self):
        # 31 September does not exist; the token must land on a real date.
        assert parse_daytime("31/0800", datetime(2026, 9, 20)) == datetime(2026, 8, 31, 8, 0)

    def test_passes_through_real_datetimes(self):
        moment = datetime(2026, 7, 5, 6, 30)
        assert parse_daytime(moment, datetime(2026, 1, 1)) == moment

    @pytest.mark.parametrize("value", [None, "", "BLANK", "-", "n/a", "not a date", "99/9999"])
    def test_rejects_non_timestamps(self, value):
        assert parse_daytime(value, datetime(2026, 7, 1)) is None


class TestWindows:
    def test_parses_a_window(self):
        start, end = parse_window("15/1800 - 16/1700", datetime(2026, 7, 13))
        assert start == datetime(2026, 7, 15, 18, 0)
        assert end == datetime(2026, 7, 16, 17, 0)

    def test_window_spanning_a_month_end_does_not_run_backwards(self):
        start, end = parse_window("31/1600 - 01/0800", datetime(2026, 7, 27))
        assert start == datetime(2026, 7, 31, 16, 0)
        assert end == datetime(2026, 8, 1, 8, 0)
        assert end > start

    def test_ignores_unparseable_text(self):
        assert parse_window("Window Time (ETA-ETD)", datetime(2026, 7, 1)) == (None, None)


class TestWindowPattern:
    def test_resolves_a_weekday_slot_into_a_week(self):
        assert parse_window_pattern("MON 07 - TUE 01", date(2026, 7, 27)) == (
            datetime(2026, 7, 27, 7, 0),
            datetime(2026, 7, 28, 1, 0),
        )

    def test_handles_four_digit_times_and_missing_spaces(self):
        assert parse_window_pattern("THU 2130-FRI 2130", date(2026, 6, 29)) == (
            datetime(2026, 7, 2, 21, 30),
            datetime(2026, 7, 3, 21, 30),
        )
        assert parse_window_pattern("MON 08 - TUE09", date(2026, 7, 6))[1] == datetime(
            2026, 7, 7, 9, 0
        )

    def test_rejects_text_that_is_not_a_pattern(self):
        assert parse_window_pattern("15/1800 - 16/1700", date(2026, 7, 13)) == (None, None)


class TestWeeks:
    def test_reads_a_week_banner(self):
        assert week_label("WK30船舶動態：") == "WK30"
        assert week_label("nothing here") is None

    def test_picks_the_iso_year_nearest_the_snapshot(self):
        assert week_monday(30, date(2026, 7, 31)) == date(2026, 7, 20)
        # A file dated in early January still shows the previous year's weeks.
        assert week_monday(52, date(2027, 1, 4)) == date(2026, 12, 21)


class TestMisc:
    @pytest.mark.parametrize(
        "raw,expected",
        [("QQCT-2", "QQCT"), ("QQCTN", "QQCTN"), ("qqctu", "QQCTU"), ("RZH", "RZH")],
    )
    def test_terminal_normalization(self, raw, expected):
        assert normalize_terminal(raw) == expected

    def test_qingdao_detection(self):
        assert is_qingdao("QQCT-2") and is_qingdao("QQCTN")
        assert not is_qingdao("RZH")
        assert not is_qingdao(None)

    def test_rounding_matches_the_workbooks(self):
        assert round_hours(25.766666) == 25.8
        assert round_hours(-0.001) == 0.0
        assert round_hours(None) is None

    def test_blank_tokens(self):
        assert is_blank("BLANK") and is_blank(None) and is_blank("  ")
        assert not is_blank("QQCTN")

    def test_numbers(self):
        assert parse_number("28.5") == 28.5
        assert parse_number(30) == 30.0
        assert parse_number("n/a") is None
        assert parse_number(True) is None
