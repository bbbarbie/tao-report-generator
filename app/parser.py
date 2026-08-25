"""Reads a Daily Berth Report workbook into ``VoyageSnapshot`` records.

Nothing here depends on fixed row numbers. Weekly sections are found by
their ``WKnn ... 動態`` banner, and columns by matching the header labels
that follow it, so rows and columns can move between files.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl

from app.models import SourceRef, VoyageSnapshot
from app.normalization import (
    clean_str,
    is_blank,
    parse_daytime,
    parse_number,
    parse_window,
    parse_window_pattern,
    week_label,
    week_monday,
)

DEFAULT_SHEET_CANDIDATES = ("Daily Berth Report",)
SHEET_HINT = re.compile(r"berth\s*report", re.I)

_FILENAME_DATE = re.compile(r"(20\d{2})[-_ ]?(\d{2})[-_ ]?(\d{2})")

# Header label -> snapshot field. Matching is case/whitespace insensitive and
# prefix-based, so "Arr Delay Hrs" and "Arr Delay (hr)" both land on arr_delay.
COLUMN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("svc", re.compile(r"^svc$", re.I)),
    ("vessel_voyage", re.compile(r"^vsl\s*/?\s*voy", re.I)),
    ("tfc", re.compile(r"^tfc", re.I)),
    ("terminal", re.compile(r"^tml$|^terminal$", re.I)),
    ("eta", re.compile(r"^eta$", re.I)),
    ("ata", re.compile(r"^ata$", re.I)),
    ("etb", re.compile(r"^etb$", re.I)),
    ("atb", re.compile(r"^atb$", re.I)),
    ("etd", re.compile(r"^etd$", re.I)),
    ("atd", re.compile(r"^atd$", re.I)),
    ("window", re.compile(r"^window\s*time", re.I)),
    ("arr_delay", re.compile(r"^arr\.?\s*delay", re.I)),
    ("dep_delay", re.compile(r"^dep\.?\s*delay", re.I)),
    ("waiting", re.compile(r"^waiting|^w\s*/\s*b", re.I)),
    ("gph", re.compile(r"^gph$", re.I)),
    ("delay_reason", re.compile(r"^delay\s*reason|^remark", re.I)),
]

REQUIRED_COLUMNS = {"svc", "tfc", "ata", "atb", "atd", "window"}


class ParseError(Exception):
    pass


def snapshot_date_from_name(path: Path) -> datetime:
    m = _FILENAME_DATE.search(path.stem)
    if not m:
        raise ParseError(
            f"cannot read a snapshot date from filename {path.name!r}; "
            "expected something like 'Daily 20260731.xlsx'"
        )
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _pick_sheet(wb) -> str:
    for name in DEFAULT_SHEET_CANDIDATES:
        if name in wb.sheetnames:
            return name
    for name in wb.sheetnames:
        if SHEET_HINT.search(name):
            return name
    raise ParseError(f"no berth-report sheet found in {wb.sheetnames}")


def _row_values(ws, row: int) -> list:
    return [ws.cell(row, c).value for c in range(1, ws.max_column + 1)]


def _match_header(values: list) -> dict[str, int] | None:
    """Map field name -> 1-based column index, if this row is a section header."""
    mapping: dict[str, int] = {}
    for idx, value in enumerate(values, start=1):
        label = clean_str(value)
        if not label:
            continue
        label = label.replace("\n", " ")
        for field_name, pattern in COLUMN_PATTERNS:
            if field_name in mapping:
                continue
            if pattern.match(label):
                mapping[field_name] = idx
                break
    if REQUIRED_COLUMNS.issubset(mapping):
        return mapping
    return None


def _is_section_banner(values: list) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value)
        if "動態" in text or "动态" in text:
            label = week_label(text)
            if label:
                return label
    return None


def parse_daily_workbook(
    path: str | Path, sheet: str | None = None
) -> list[VoyageSnapshot]:
    """Parse every weekly section of one Daily workbook."""
    path = Path(path)
    snap_date = snapshot_date_from_name(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    sheet_name = sheet or _pick_sheet(wb)
    ws = wb[sheet_name]

    snapshots: list[VoyageSnapshot] = []
    row = 1
    max_row = ws.max_row
    current_label: str | None = None
    columns: dict[str, int] | None = None
    anchor: datetime | None = None

    while row <= max_row:
        values = _row_values(ws, row)

        banner = _is_section_banner(values)
        if banner:
            current_label = banner
            columns = None
            anchor = _anchor_for(banner, snap_date)
            row += 1
            continue

        header = _match_header(values)
        if header:
            columns = header
            row += 1
            continue

        if columns and current_label and anchor:
            snap = _parse_row(
                values,
                columns,
                anchor,
                SourceRef(path.name, snap_date, sheet_name, row, current_label),
            )
            if snap is not None:
                snapshots.append(snap)
        row += 1

    wb.close()
    return snapshots


def _anchor_for(label: str, snap_date: datetime) -> datetime:
    """Mid-week datetime used to disambiguate bare day-of-month tokens."""
    iso_week = int(label[2:])
    monday = week_monday(iso_week, snap_date.date())
    return datetime(monday.year, monday.month, monday.day)


def _get(values: list, columns: dict[str, int], field_name: str):
    idx = columns.get(field_name)
    if idx is None or idx > len(values):
        return None
    return values[idx - 1]


def _resolve_times(
    values: list,
    columns: dict[str, int],
    anchor: datetime,
    window_start: datetime | None,
    window_end: datetime | None,
    arr_delay: float | None,
    dep_delay: float | None,
    waiting: float | None,
) -> dict[str, datetime | None]:
    """Resolve one row's ``dd/HHMM`` timestamps to full datetimes.

    A bare day-of-month is ambiguous: "25/1218" in a week whose window is
    6 July could be 25 June (11 days early) or 25 July (19 days late), and
    both happen in practice. Two things break the tie:

    * where the Daily already prints a delay figure, that figure pins the
      month exactly — it is used as the anchor, never as the value;
    * otherwise the voyage's own chronology (window -> arrival -> berth ->
      departure) anchors each timestamp to the one before it.
    """

    def cell(name: str):
        return _get(values, columns, name)

    def at(name: str, cursor: datetime | None, hint: datetime | None = None):
        return parse_daytime(cell(name), hint or cursor or anchor)

    def offset(base: datetime | None, hours: float | None) -> datetime | None:
        if base is None or hours is None:
            return None
        return base + timedelta(hours=hours)

    ata = at("ata", window_start, offset(window_start, arr_delay))
    atb = at("atb", ata or window_start, offset(ata, waiting))
    atd = at("atd", atb or ata or window_start, offset(window_end, dep_delay))

    # Estimates sit beside their actual counterparts; fall back along the
    # same chronological chain when an actual is missing.
    eta = at("eta", ata or window_start)
    etb = at("etb", atb or ata or window_start)
    etd = at("etd", atd or atb or window_end or window_start)

    return {"eta": eta, "ata": ata, "etb": etb, "atb": atb, "etd": etd, "atd": atd}


def _parse_row(
    values: list, columns: dict[str, int], anchor: datetime, source: SourceRef
) -> VoyageSnapshot | None:
    svc = clean_str(_get(values, columns, "svc"))
    tfc = clean_str(_get(values, columns, "tfc"))
    vessel = clean_str(_get(values, columns, "vessel_voyage"))
    if is_blank(vessel):
        vessel = None

    # A slot row with no vessel nominated yet carries no voyage.
    if not tfc and not vessel:
        return None
    if not svc:
        return None

    raw_window = _get(values, columns, "window")
    window_start, window_end = parse_window(raw_window, anchor)

    arr_delay = parse_number(_get(values, columns, "arr_delay"))
    dep_delay = parse_number(_get(values, columns, "dep_delay"))
    waiting = parse_number(_get(values, columns, "waiting"))

    times = _resolve_times(
        values, columns, anchor, window_start, window_end, arr_delay, dep_delay, waiting
    )

    window_pattern = None
    win_idx = columns.get("window")
    if win_idx and win_idx < len(values):
        # The Daily merges the window header across two columns; the second
        # holds the nominal weekday pattern ("MON 18 - TUE 17").
        window_pattern = clean_str(values[win_idx])

    raw = {}
    for field_name in ("eta", "ata", "etb", "atb", "etd", "atd"):
        raw[field_name] = clean_str(_get(values, columns, field_name))
    raw["window"] = clean_str(raw_window)

    pattern_start, pattern_end = parse_window_pattern(window_pattern, anchor.date())

    return VoyageSnapshot(
        source=source,
        svc=svc.upper(),
        vessel_voyage=vessel,
        tfc=tfc.upper() if tfc else None,
        terminal=clean_str(_get(values, columns, "terminal")),
        eta=times["eta"],
        ata=times["ata"],
        etb=times["etb"],
        atb=times["atb"],
        etd=times["etd"],
        atd=times["atd"],
        window_start=window_start,
        window_end=window_end,
        window_pattern=window_pattern,
        window_raw=clean_str(raw_window),
        pattern_start=pattern_start,
        pattern_end=pattern_end,
        arr_delay_reported=arr_delay,
        dep_delay_reported=dep_delay,
        waiting_reported=waiting,
        gph=parse_number(_get(values, columns, "gph")),
        delay_reason=clean_str(_get(values, columns, "delay_reason")),
        raw=raw,
    )


def parse_many(paths) -> list[VoyageSnapshot]:
    out: list[VoyageSnapshot] = []
    for p in sorted(paths, key=lambda p: snapshot_date_from_name(Path(p))):
        out.extend(parse_daily_workbook(p))
    return out


def discover_daily_files(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    files = [
        p
        for p in sorted(folder.glob("*.xlsx"))
        if not p.name.startswith("~$") and _FILENAME_DATE.search(p.stem)
    ]
    return files
