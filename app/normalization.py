"""Turning the Daily workbook's shipping shorthand into real Python values.

The Daily report writes timestamps as ``dd/HHMM`` — day-of-month and a
24h clock, with no month and no year. The month/year has to be recovered
from context: the weekly section the row sits in, plus the previously
resolved timestamps on the same row (a voyage's own timeline is ordered).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# "24/0142", "3/0754", "24 / 0142"
_DAYTIME = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})[:.]?(\d{2})\s*$")
# "15/1800 - 16/1700"
_WINDOW = re.compile(
    r"^\s*(\d{1,2}\s*/\s*\d{1,2}[:.]?\d{2})\s*[-–~]\s*(\d{1,2}\s*/\s*\d{1,2}[:.]?\d{2})\s*$"
)
_WEEK_LABEL = re.compile(r"WK\s*(\d{1,2})")

# Placeholders the Daily uses for "no vessel nominated yet".
BLANK_TOKENS = {"", "-", "--", "n/a", "na", "tbd", "tba", "blank", "vacant", "none"}

MAX_DAY_DRIFT = 21  # days a resolved timestamp may sit from its anchor


def is_blank(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in BLANK_TOKENS


def clean_str(value) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s or None


def week_label(value) -> str | None:
    """``'WK30船舶動態：'`` -> ``'WK30'``."""
    if value is None:
        return None
    m = _WEEK_LABEL.search(str(value))
    return f"WK{int(m.group(1))}" if m else None


def week_monday(iso_week: int, near: date) -> date:
    """Monday of ISO week ``iso_week``, in whichever ISO year sits nearest ``near``.

    Weekly sections carry no year. A file dated early January can legitimately
    show WK52 of the previous year, so the year is chosen by proximity rather
    than assumed from the filename.
    """
    candidates = []
    for year in (near.year - 1, near.year, near.year + 1):
        try:
            candidates.append(date.fromisocalendar(year, iso_week, 1))
        except ValueError:
            continue  # week 53 does not exist in every year
    if not candidates:
        raise ValueError(f"cannot place ISO week {iso_week} near {near}")
    return min(candidates, key=lambda d: abs((d - near).days))


def parse_daytime(value, anchor: datetime) -> datetime | None:
    """Resolve a ``dd/HHMM`` token to the occurrence nearest ``anchor``.

    Also accepts values Excel already stored as real datetimes.
    """
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)

    m = _DAYTIME.match(str(value))
    if not m:
        return None
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= day <= 31 and hour <= 24 and minute < 60):
        return None

    # "2400" is midnight ending that day.
    rollover = timedelta(days=1) if hour == 24 else timedelta()
    if hour == 24:
        hour, minute = 0, minute

    best: datetime | None = None
    for offset in (-2, -1, 0, 1, 2):
        year, month = anchor.year, anchor.month + offset
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1
        try:
            cand = datetime(year, month, day, hour, minute) + rollover
        except ValueError:
            continue  # e.g. 31 September
        if best is None or abs(cand - anchor) < abs(best - anchor):
            best = cand
    if best is None or abs(best - anchor) > timedelta(days=MAX_DAY_DRIFT):
        return None
    return best


def parse_window(value, anchor: datetime) -> tuple[datetime | None, datetime | None]:
    """Parse ``'15/1800 - 16/1700'`` into (start, end).

    The end is resolved relative to the start so a window that straddles a
    month boundary (``'31/1600 - 01/0800'``) lands on the following month.
    """
    if is_blank(value):
        return None, None
    if isinstance(value, str):
        m = _WINDOW.match(value)
        if not m:
            return None, None
        start = parse_daytime(m.group(1), anchor)
        if start is None:
            return None, None
        end = parse_daytime(m.group(2), start)
        if end is not None and end < start:
            # A window never runs backwards; nudge to the next occurrence.
            end = parse_daytime(m.group(2), start + timedelta(days=15))
        return start, end
    return None, None


def parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --- Terminals ---------------------------------------------------------------
#
# The Daily distinguishes berth groups inside a terminal (QQCT-2, QQCTUA);
# the monthly report names only the terminal itself.

_TERMINAL_SUFFIX = re.compile(r"[-\s]*\d+$")


def normalize_terminal(value) -> str | None:
    s = clean_str(value)
    if s is None:
        return None
    s = s.upper().replace(" ", "")
    s = _TERMINAL_SUFFIX.sub("", s)
    return s or None


def is_qingdao(terminal: str | None) -> bool:
    """CNTAO berths. RZH (Rizhao) rows share the Daily but not the report."""
    if not terminal:
        return False
    return normalize_terminal(terminal).startswith("QQCT")


def hours_between(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).total_seconds() / 3600.0


def round_hours(value: float | None) -> float | None:
    """The Daily and the monthly report both print hours to one decimal."""
    if value is None:
        return None
    r = round(value + 1e-9, 1)
    return 0.0 if r == 0 else r


# --- Nominal weekly window ----------------------------------------------------
#
# Beside the concrete window the Daily also prints the service's standing
# weekly slot ("MON 18 - TUE 17"). The two should describe the same weekday
# and clock time; where they do not, one of them was mistyped.

_WEEKDAYS = {
    "MON": 0, "TUE": 1, "TUES": 1, "WED": 2, "WEDS": 2,
    "THU": 3, "THUR": 3, "THURS": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}
_PATTERN_TOKEN = re.compile(r"([A-Z]{3,5})\s*(\d{2})(\d{2})?")


def parse_window_pattern(
    pattern, monday: date
) -> tuple[datetime | None, datetime | None]:
    """``'MON 18 - TUE 17'`` -> the concrete window in the week starting ``monday``."""
    if is_blank(pattern):
        return None, None
    halves = re.split(r"\s*[-–]\s*", str(pattern).upper())
    if len(halves) != 2:
        return None, None

    resolved: list[datetime] = []
    base = datetime(monday.year, monday.month, monday.day)
    for half in halves:
        m = _PATTERN_TOKEN.search(half.strip())
        if not m or m.group(1) not in _WEEKDAYS:
            return None, None
        hour = int(m.group(2))
        minute = int(m.group(3)) if m.group(3) else 0
        if hour > 24 or minute > 59:
            return None, None
        resolved.append(
            base + timedelta(days=_WEEKDAYS[m.group(1)], hours=hour, minutes=minute)
        )
    start, end = resolved
    if end < start:
        end += timedelta(days=7)
    return start, end
