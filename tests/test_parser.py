"""The parser must survive rows and columns moving between files."""

from __future__ import annotations

from datetime import datetime

import openpyxl
import pytest

from app.parser import (
    ParseError,
    _match_header,
    parse_daily_workbook,
    snapshot_date_from_name,
)
from pathlib import Path

from tests.conftest import DAILY_DIR, requires_samples


def test_snapshot_date_comes_from_the_filename():
    assert snapshot_date_from_name(Path("Daily 20260731.xlsx")) == datetime(2026, 7, 31)
    assert snapshot_date_from_name(Path("Daily_2026-07-31.xlsx")) == datetime(2026, 7, 31)
    with pytest.raises(ParseError):
        snapshot_date_from_name(Path("Daily.xlsx"))


def test_header_detection_is_by_label_not_position():
    shifted = [None, None, None, "SVC", "VSL/VOY", "TFC", "TML", "ETA", "ATA",
               "ETB", "ATB", "ETD", "ATD", "Window Time (ETA-ETD)", None,
               "Arr Delay Hrs", "Dep Delay Hrs", "Waiting", "GPH", "Delay Reason"]
    columns = _match_header(shifted)
    assert columns is not None
    assert columns["svc"] == 4  # three columns further right than the real file
    assert columns["atd"] == 13


def test_header_detection_tolerates_label_variants():
    columns = _match_header(
        ["SVC", "VSL / VOY", "TFC Code", "Terminal", "ETA", "ATA", "ETB", "ATB",
         "ETD", "ATD", "Window Time", "Arr. Delay (hr)", "Dep. Delay (Hr)",
         "W/B (hr)", "GPH", "Remark"]
    )
    assert columns is not None
    assert columns["waiting"] == 14


def test_a_row_that_is_not_a_header_is_not_mistaken_for_one():
    assert _match_header(["CT1", "WAN HAI 509/S164", "S16459", "QQCTU"]) is None


@requires_samples
@pytest.mark.parametrize("name", sorted(p.name for p in DAILY_DIR.glob("Daily *.xlsx")))
def test_every_daily_file_parses_into_records(name):
    snapshots = parse_daily_workbook(DAILY_DIR / name)
    assert snapshots, f"{name} produced no records"
    # Each file shows several weekly sections and a dozen-odd services.
    assert len({s.source.week_label for s in snapshots}) >= 3
    assert all(s.svc for s in snapshots)
    assert all(s.source.source_file == name for s in snapshots)


@requires_samples
def test_row_counts_differ_between_files_but_all_are_read(daily_files):
    counts = {p.name: len(parse_daily_workbook(p)) for p in daily_files}
    assert len(set(counts.values())) > 1, "expected the board to change size over time"


@requires_samples
def test_slot_rows_with_no_vessel_are_skipped():
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    assert all(
        (s.vessel_voyage or "").strip().upper() != "BLANK" for s in snapshots
    )


@requires_samples
def test_timestamps_resolve_to_the_right_month(daily_files):
    """A voyage 19 days past its window must not be read as 11 days early."""
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    late = next(s for s in snapshots if s.tfc == "E02762A")
    assert late.window_start == datetime(2026, 7, 6, 13, 0)
    assert late.ata == datetime(2026, 7, 25, 12, 18)
    assert late.atb == datetime(2026, 7, 28, 8, 24)
    assert late.atd == datetime(2026, 7, 29, 0, 45)


@requires_samples
def test_early_arrival_is_not_pushed_into_the_next_month():
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    early = next(s for s in snapshots if s.tfc == "W02762B" and s.ata)
    assert early.ata == datetime(2026, 7, 20, 17, 28)
    assert early.ata < early.window_start


@requires_samples
def test_reported_columns_are_read_when_present():
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    row = next(s for s in snapshots if s.tfc == "S16559")
    assert (row.arr_delay_reported, row.dep_delay_reported, row.waiting_reported) == (
        66.6,
        117.1,
        60.4,
    )
    assert row.gph == 30.1


@requires_samples
def test_rows_without_reported_columns_are_left_empty():
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    row = next(s for s in snapshots if s.tfc == "E105JEXP")
    assert row.arr_delay_reported is None
    assert row.waiting_reported is None
    assert row.ata is not None  # the timestamps are still there


@requires_samples
def test_weekly_sections_are_labelled_and_ordered():
    snapshots = parse_daily_workbook(DAILY_DIR / "Daily 20260731.xlsx")
    labels = []
    for s in snapshots:
        if s.source.week_label not in labels:
            labels.append(s.source.week_label)
    assert labels == ["WK28", "WK29", "WK30", "WK31", "WK32"]


@requires_samples
def test_parser_survives_an_unexpected_sheet_name(tmp_path):
    src = DAILY_DIR / "Daily 20260731.xlsx"
    wb = openpyxl.load_workbook(src)
    wb["Daily Berth Report"].title = "CNTAO Berth Report v2"
    out = tmp_path / "Daily 20260731.xlsx"
    wb.save(out)
    assert parse_daily_workbook(out)


@requires_samples
def test_parser_survives_extra_rows_inserted_above_the_table(tmp_path):
    src = DAILY_DIR / "Daily 20260731.xlsx"
    wb = openpyxl.load_workbook(src)
    ws = wb["Daily Berth Report"]
    ws.insert_rows(1, 7)
    out = tmp_path / "Daily 20260731.xlsx"
    wb.save(out)
    shifted = parse_daily_workbook(out)
    original = parse_daily_workbook(src)
    assert [s.tfc for s in shifted] == [s.tfc for s in original]
