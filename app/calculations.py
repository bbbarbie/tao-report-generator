"""The business rules that turn a voyage history into one monthly report row.

Every rule here was validated against the Daily workbooks' own printed figures
and against the historical TAO Compare workbook; see REVERSE_ENGINEERING.md for
the evidence behind each one and for the cases that do not follow them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.models import VoyageHistory, VoyageSnapshot
from app.normalization import hours_between, normalize_terminal, round_hours
from app.operators import OperatorMapping, OperatorResult

# Review flags. Every value the generator cannot stand behind carries one.
MISSING_ATD = "MISSING_ATD"
MISSING_ATA = "MISSING_ATA"
MISSING_ATB = "MISSING_ATB"
MISSING_WINDOW = "MISSING_WINDOW"
UNKNOWN_OPERATOR = "UNKNOWN_OPERATOR"
REPORTED_DISAGREES = "REPORTED_DISAGREES_WITH_CALCULATION"
WINDOW_CHANGED_LATE = "WINDOW_CHANGED_AFTER_ARRIVAL"
WINDOW_WEEKDAY_MISMATCH = "WINDOW_WEEKDAY_MISMATCH"
TERMINAL_DIFFERS_FROM_SERVICE = "TERMINAL_DIFFERS_FROM_SERVICE"
NEGATIVE_WAITING = "BERTHED_BEFORE_WINDOW_OPENED"

# The Daily prints one decimal; agreement is judged at that resolution.
REPORTED_TOLERANCE = 0.11


@dataclass
class ValueProvenance:
    """How one number in the output was arrived at."""

    value: float | None
    method: str  # "copied_from_daily" | "calculated" | "unavailable"
    formula: str | None = None
    source_file: str | None = None
    snapshot_date: datetime | None = None
    calculated_value: float | None = None


@dataclass
class MonthlyRow:
    svc: str | None
    tfc: str | None
    opr: str
    terminal: str | None
    ata: datetime | None
    atb: datetime | None
    arr_delay: ValueProvenance
    dep_delay: ValueProvenance
    waiting: ValueProvenance
    average_waiting: float | None = None

    voyage_key: str = ""
    vessel_voyage: str | None = None
    atd: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    operator_source: str = ""
    flags: list[str] = field(default_factory=list)
    snapshot_files: list[str] = field(default_factory=list)

    @property
    def group_key(self) -> tuple[str, str]:
        return (self.svc or "", self.opr)

    def flag(self, code: str) -> None:
        if code not in self.flags:
            self.flags.append(code)


# --- Individual metrics -------------------------------------------------------
#
# Arrival and departure delay are measured against the berthing window the
# terminal granted, not against the vessel's own schedule. Waiting time is the
# gap between being able to berth and actually berthing.


def calc_arr_delay(snap: VoyageSnapshot) -> float | None:
    """Hours between actual arrival and the opening of the berthing window."""
    return round_hours(hours_between(snap.ata, snap.window_start))


def calc_dep_delay(snap: VoyageSnapshot) -> float | None:
    """Hours between actual departure and the close of the berthing window."""
    return round_hours(hours_between(snap.atd, snap.window_end))


def calc_waiting(snap: VoyageSnapshot) -> float | None:
    """Hours spent waiting for a berth.

    Waiting starts when the vessel is both present and entitled to the berth,
    so a ship that arrives before its window opens is not credited with the
    time it spent waiting for its own slot. A vessel berthed before its window
    even opened has not waited at all.
    """
    if snap.atb is None:
        return None
    ready = _latest(snap.ata, snap.window_start)
    if ready is None:
        return None
    return round_hours(max(0.0, hours_between(snap.atb, ready)))


def _latest(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


# --- Row assembly -------------------------------------------------------------


def _resolve(
    history: VoyageHistory,
    snap: VoyageSnapshot,
    reported: float | None,
    calculated: float | None,
    field_name: str,
    formula: str,
    use_reported: bool,
) -> tuple[ValueProvenance, str | None]:
    """Choose between the Daily's own figure and a recalculation.

    For WAN HAI's own vessels the Daily figure is the number the business
    already publishes, so it is copied even when a recalculation from the
    current timestamps would differ — those timestamps are sometimes revised
    after the figure was struck. Where the two disagree the row is flagged so
    the difference is visible rather than silent.
    """
    provenance = history.provenance(f"{field_name}_reported")
    if use_reported and reported is not None:
        flag = None
        if calculated is not None and abs(calculated - reported) > REPORTED_TOLERANCE:
            flag = REPORTED_DISAGREES
        return (
            ValueProvenance(
                value=reported,
                method="copied_from_daily",
                formula=f"Daily '{_column_label(field_name)}' column",
                source_file=provenance.source_file if provenance else snap.source_file,
                snapshot_date=provenance.snapshot_date if provenance else snap.snapshot_date,
                calculated_value=calculated,
            ),
            flag,
        )
    if calculated is None:
        return ValueProvenance(None, "unavailable", formula), None
    return (
        ValueProvenance(
            value=calculated,
            method="calculated",
            formula=formula,
            source_file=snap.source_file,
            snapshot_date=snap.snapshot_date,
            calculated_value=calculated,
        ),
        None,
    )


def _column_label(field_name: str) -> str:
    return {
        "arr_delay": "Arr Delay Hrs",
        "dep_delay": "Dep Delay Hrs",
        "waiting": "Waiting",
    }[field_name]


def effective_window(snap: VoyageSnapshot) -> tuple[VoyageSnapshot, bool]:
    """Reconcile the concrete berthing window with the service's weekly slot.

    The Daily prints both the dates of this call's window and the standing
    weekly slot it comes from ("MON 07 - TUE 01"). When both ends of the
    concrete window fall on the wrong weekday by the same number of days, but
    at the right clock times, the dates were typed a day out; the weekly slot
    is the authority and the window is shifted back onto it.

    A whole-week difference is not a typo — it means the row is showing an
    adjacent week's window — and is left alone, as is a disagreement on only
    one end, which points at a stale pattern label rather than a bad date.
    """
    if None in (snap.window_start, snap.window_end, snap.pattern_start, snap.pattern_end):
        return snap, False

    shifts = []
    for actual, nominal in (
        (snap.window_start, snap.pattern_start),
        (snap.window_end, snap.pattern_end),
    ):
        if actual.time() != nominal.time():
            return snap, False
        shifts.append((actual.weekday() - nominal.weekday()) % 7)

    if shifts[0] != shifts[1] or shifts[0] == 0:
        return snap, False

    offset = timedelta(days=shifts[0])
    return (
        replace(
            snap,
            window_start=snap.window_start - offset,
            window_end=snap.window_end - offset,
        ),
        True,
    )


def build_row(
    history: VoyageHistory,
    mapping: OperatorMapping,
    service_terminal: str | None = None,
) -> MonthlyRow:
    snap = history.consolidated()
    own_terminal = normalize_terminal(snap.terminal)
    snap, window_corrected = effective_window(snap)
    op: OperatorResult = mapping.resolve(snap.vessel_voyage, snap.tfc)

    # The Daily's own figures were struck against the window it prints. Once
    # that window is corrected they no longer describe the call, so the row is
    # recalculated even for WAN HAI's own vessels.
    house = op.opr == mapping.house_operator and not window_corrected

    arr_calc = calc_arr_delay(snap)
    dep_calc = calc_dep_delay(snap)
    wait_calc = calc_waiting(snap)

    arr, arr_flag = _resolve(
        history, snap, snap.arr_delay_reported, arr_calc, "arr_delay",
        "ATA - window start", house,
    )
    dep, dep_flag = _resolve(
        history, snap, snap.dep_delay_reported, dep_calc, "dep_delay",
        "ATD - window end", house,
    )
    wait, wait_flag = _resolve(
        history, snap, snap.waiting_reported, wait_calc, "waiting",
        "ATB - max(ATA, window start), floored at 0", house,
    )

    row = MonthlyRow(
        svc=snap.svc,
        tfc=snap.tfc,
        opr=op.opr,
        terminal=service_terminal or own_terminal,
        ata=snap.ata,
        atb=snap.atb,
        arr_delay=arr,
        dep_delay=dep,
        waiting=wait,
        voyage_key=history.voyage_key,
        vessel_voyage=snap.vessel_voyage,
        atd=snap.atd,
        window_start=snap.window_start,
        window_end=snap.window_end,
        operator_source=op.source,
        snapshot_files=[s.source_file for s in history.snapshots],
    )

    for flag in (arr_flag, dep_flag, wait_flag):
        if flag:
            row.flag(flag)
    if not op.is_known:
        row.flag(UNKNOWN_OPERATOR)
    if snap.ata is None:
        row.flag(MISSING_ATA)
    if snap.atb is None:
        row.flag(MISSING_ATB)
    if snap.atd is None:
        row.flag(MISSING_ATD)
    if snap.window_start is None or snap.window_end is None:
        row.flag(MISSING_WINDOW)
    if (
        snap.atb is not None
        and snap.window_start is not None
        and snap.atb < snap.window_start
    ):
        row.flag(NEGATIVE_WAITING)
    if _window_moved_after_arrival(history):
        row.flag(WINDOW_CHANGED_LATE)
    if window_corrected:
        row.flag(WINDOW_WEEKDAY_MISMATCH)
    if service_terminal and own_terminal and service_terminal != own_terminal:
        row.flag(TERMINAL_DIFFERS_FROM_SERVICE)

    return row


def _window_moved_after_arrival(history: VoyageHistory) -> bool:
    """Did the granted window change once the vessel had already arrived?

    When it does, figures struck earlier in the month were measured against a
    different window than the one the report ends up quoting.
    """
    first_ata = history.first_seen("ata")
    if first_ata is None:
        return False
    windows = {
        s.window_start
        for s in history.snapshots
        if s.snapshot_date >= first_ata.snapshot_date and s.window_start is not None
    }
    return len(windows) > 1


def attach_group_averages(rows: list[MonthlyRow]) -> None:
    """Average W/B per SVC + OPR, written against the first row of each group.

    The historical report shows the average once per service/operator block
    rather than repeating it on every row.
    """
    sums: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        if row.waiting.value is not None:
            sums.setdefault(row.group_key, []).append(row.waiting.value)

    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = row.group_key
        if key in seen:
            row.average_waiting = None
            continue
        seen.add(key)
        values = sums.get(key)
        row.average_waiting = round_hours(sum(values) / len(values)) if values else None
