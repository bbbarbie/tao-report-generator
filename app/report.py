"""End-to-end pipeline: Daily workbooks in, monthly report model out.

This module never looks at the historical TAO Compare workbook. Ground truth
is a test fixture, not an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.calculations import (
    UNRESOLVED,
    MonthlyRow,
    attach_group_averages,
    build_row,
)
from app.decisions import DecisionStore
from app.operators import OperatorMapping
from app.review import ReviewIssue, collect_issues
from app.parser import discover_daily_files, parse_many
from app.selection import (
    NO_ATD,
    ScopeConfig,
    Selection,
    select_for_month,
    service_terminals,
)
from app.voyage_history import HistoryIndex, build_histories


@dataclass
class ReviewItem:
    tfc: str | None
    svc: str | None
    vessel: str | None
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "TFC": self.tfc or "",
            "SVC": self.svc or "",
            "Vessel": self.vessel or "",
            "Reason": self.reason,
            "Detail": self.detail,
        }


@dataclass
class MonthlyReport:
    year: int
    month: int
    rows: list[MonthlyRow]
    review: list[ReviewItem]
    selection: Selection
    index: HistoryIndex
    issues: list[ReviewIssue] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        return f"{self.year:04d}{self.month:02d}"

    @property
    def clean_row_count(self) -> int:
        return sum(1 for r in self.rows if not r.flags)

    def rows_by_resolution(self, state: str) -> list[MonthlyRow]:
        return [r for r in self.rows if r.resolution == state]

    @property
    def open_issue_count(self) -> int:
        return len(self.issues)

    @property
    def blocking_issues(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.blocking]

    @property
    def is_complete(self) -> bool:
        """True when nothing is left to ask. The report generates either way."""
        return not self.issues


def _operator_sort_key(row: MonthlyRow) -> tuple:
    return (
        row.svc or "",
        row.opr or "",
        row.atb or row.ata or row.atd or datetime.max,
    )


def build_report(
    daily_files: list[str | Path],
    year: int,
    month: int,
    mapping: OperatorMapping | None = None,
    scope: ScopeConfig | None = None,
    store: DecisionStore | None = None,
) -> MonthlyReport:
    mapping = mapping or OperatorMapping.load()
    scope = scope or ScopeConfig.load()
    store = store if store is not None else DecisionStore.load()
    period = f"{year:04d}{month:02d}"

    # Reusable rules the user has already set are part of the mapping from here
    # on; they are not a review question any more.
    for vessel, opr in store.operator_rules().items():
        mapping.learn(vessel, opr)

    snapshots = parse_many(daily_files)
    index = build_histories(snapshots)
    selection = select_for_month(index, year, month, mapping, scope)

    selected, readmitted = _apply_inclusion_decisions(selection, store, period)

    terminals = service_terminals(index)
    rows = [
        build_row(
            h,
            mapping,
            terminals.get(h.consolidated().svc or ""),
            store.overrides_for(period, h.voyage_key),
        )
        for h in selected
    ]
    rows.sort(key=_operator_sort_key)

    missing_atd = [
        r.history
        for r in selection.rejected
        if r.reason == NO_ATD and r.history.voyage_key not in readmitted
    ]
    in_scope = {
        svc for svc, verdict in selection.service_scope.items() if verdict == "in"
    }
    issues = collect_issues(
        rows, index, mapping, missing_atd, period, store, in_scope
    )
    _mark_unresolved(rows, issues)

    attach_group_averages(rows)
    review = _collect_review(rows, selection, index)

    return MonthlyReport(
        year=year,
        month=month,
        rows=rows,
        review=review,
        selection=selection,
        index=index,
        issues=issues,
        source_files=[Path(p).name for p in daily_files],
    )


def _apply_inclusion_decisions(selection: Selection, store: DecisionStore, period: str):
    """Let a decision put back a voyage the rules left out, or take one out.

    Only voyages rejected for a missing departure time can be readmitted — the
    port and month filters are facts, not judgement calls.
    """
    selected = list(selection.selected)
    readmitted: set[str] = set()

    for rejection in selection.rejected:
        if rejection.reason != NO_ATD:
            continue
        decision = store.overrides_for(period, rejection.history.voyage_key).get("include")
        if decision and decision.value:
            selected.append(rejection.history)
            readmitted.add(rejection.history.voyage_key)

    for row_key, fields in store.overrides.get(period, {}).items():
        decision = fields.get("include")
        if decision is not None and decision.value is False:
            selected = [h for h in selected if h.voyage_key != row_key]

    return selected, readmitted


def _mark_unresolved(rows: list[MonthlyRow], issues: list[ReviewIssue]) -> None:
    """A row with an open question is never passed off as settled.

    Only a question that would leave a required output field empty makes a row
    unresolved. The rest already carry a defensible value, so the row stands
    and the question is recorded against it.
    """
    open_by_voyage: dict[str, list[ReviewIssue]] = {}
    for issue in issues:
        open_by_voyage.setdefault(issue.voyage_key, []).append(issue)

    for row in rows:
        open_issues = open_by_voyage.get(row.voyage_key, [])
        if not open_issues:
            continue
        # A row with an open question is not "automatically resolved", even
        # when it already carries a defensible value. Only a blocking question
        # actually leaves a field empty.
        row.resolution = UNRESOLVED
        row.flag("OPEN_REVIEW_QUESTION")


ONE_SNAPSHOT_WARNING = "ONLY_ONE_DAILY_FILE_SUPPLIED"


def _collect_review(
    rows: list[MonthlyRow], selection: Selection, index: HistoryIndex
) -> list[ReviewItem]:
    review: list[ReviewItem] = []

    snapshot_files = {s.source_file for h in index.all() for s in h.snapshots}
    if len(snapshot_files) < 2:
        review.append(
            ReviewItem(
                None, None, None, ONE_SNAPSHOT_WARNING,
                "a Daily file is a snapshot, not a log — voyages that had already "
                "scrolled off the board are missing from this report. Supply every "
                "Daily file covering the month.",
            )
        )

    for row in rows:
        for flag in row.flags:
            review.append(
                ReviewItem(row.tfc, row.svc, row.vessel_voyage, flag, _explain(row, flag))
            )

    for rejection in selection.rejected:
        snap = rejection.history.consolidated()
        # Voyages at other ports or in other months are routine, not exceptions.
        if rejection.reason in ("NOT_A_QINGDAO_BERTH", "DEPARTED_IN_ANOTHER_MONTH"):
            continue
        review.append(
            ReviewItem(
                rejection.history.voyage_key,
                snap.svc,
                snap.vessel_voyage,
                rejection.reason,
                rejection.detail,
            )
        )

    for note in index.notes:
        if note.kind in ("AMBIGUOUS_VOYAGE", "NO_TFC"):
            review.append(ReviewItem(None, None, None, note.kind, note.detail))

    return review


def _explain(row: MonthlyRow, flag: str) -> str:
    if flag == "REPORTED_DISAGREES_WITH_CALCULATION":
        parts = []
        for name, prov in (
            ("Arr Delay", row.arr_delay),
            ("Dep Delay", row.dep_delay),
            ("W/B", row.waiting),
        ):
            if (
                prov.method == "copied_from_daily"
                and prov.calculated_value is not None
                and prov.value is not None
                and abs(prov.calculated_value - prov.value) > 0.11
            ):
                parts.append(
                    f"{name}: Daily reports {prov.value}, timestamps give "
                    f"{prov.calculated_value}"
                )
        return "; ".join(parts)
    if flag == "UNKNOWN_OPERATOR":
        return (
            f"vessel {row.vessel_voyage!r} is not in config/operator_mapping.json"
        )
    if flag == "WINDOW_CHANGED_AFTER_ARRIVAL":
        return (
            f"berthing window was revised after the vessel arrived; "
            f"report uses {row.window_start} - {row.window_end}"
        )
    if flag == "BERTHED_BEFORE_WINDOW_OPENED":
        return f"ATB {row.atb} precedes window start {row.window_start}; W/B recorded as 0"
    if flag == "WINDOW_WEEKDAY_MISMATCH":
        return (
            "the Daily's window dates fell on the wrong weekday for this service's "
            f"weekly slot; recalculated against {row.window_start} - {row.window_end}"
        )
    if flag == "TERMINAL_DIFFERS_FROM_SERVICE":
        return (
            f"this call berthed at a different berth group than the service's "
            f"current terminal ({row.terminal})"
        )
    if flag.startswith("MISSING_"):
        return "not present in any ingested Daily file"
    return ""


def default_daily_files(folder: str | Path = "samples/daily") -> list[Path]:
    return discover_daily_files(folder)
