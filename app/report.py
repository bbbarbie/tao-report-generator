"""End-to-end pipeline: Daily workbooks in, monthly report model out.

This module never looks at the historical TAO Compare workbook. Ground truth
is a test fixture, not an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.calculations import MonthlyRow, attach_group_averages, build_row
from app.operators import OperatorMapping
from app.parser import discover_daily_files, parse_many
from app.selection import (
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
    source_files: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        return f"{self.year:04d}{self.month:02d}"

    @property
    def clean_row_count(self) -> int:
        return sum(1 for r in self.rows if not r.flags)


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
) -> MonthlyReport:
    mapping = mapping or OperatorMapping.load()
    scope = scope or ScopeConfig.load()

    snapshots = parse_many(daily_files)
    index = build_histories(snapshots)
    selection = select_for_month(index, year, month, mapping, scope)

    terminals = service_terminals(index)
    rows = [
        build_row(h, mapping, terminals.get(h.consolidated().svc or ""))
        for h in selection.selected
    ]
    rows.sort(key=_operator_sort_key)
    attach_group_averages(rows)

    review = _collect_review(rows, selection, index)

    return MonthlyReport(
        year=year,
        month=month,
        rows=rows,
        review=review,
        selection=selection,
        index=index,
        source_files=[Path(p).name for p in daily_files],
    )


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
