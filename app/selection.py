"""Deciding which voyages belong in a given month's report.

Three filters, in order: the berth must be at Qingdao, the departure must fall
in the target month, and the service must be in scope for the report. Anything
rejected is returned alongside its reason so it can be reviewed — a voyage is
never dropped silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.models import VoyageHistory
from app.normalization import is_qingdao, normalize_terminal
from app.operators import OperatorMapping
from app.voyage_history import HistoryIndex

SCOPE_PATH = Path(__file__).resolve().parent.parent / "config" / "report_scope.json"

# Rejection reasons
NOT_QINGDAO = "NOT_A_QINGDAO_BERTH"
NO_ATD = "NO_ATD_RECORDED"
OTHER_MONTH = "DEPARTED_IN_ANOTHER_MONTH"
SERVICE_EXCLUDED = "SERVICE_EXCLUDED_BY_CONFIG"
SERVICE_NOT_STABLE = "SERVICE_NOT_ACTIVE_FOR_WHOLE_PERIOD"
SERVICE_NO_HOUSE_VESSEL = "SERVICE_HAS_NO_WAN_HAI_VESSEL"


@dataclass
class ScopeConfig:
    """Which services the monthly comparison covers."""

    require_house_vessel: bool = True
    require_stable_service: bool = True
    include: list[str] = field(default_factory=list)  # forced in, overrides rules
    exclude: list[str] = field(default_factory=list)  # forced out, overrides rules
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ScopeConfig":
        path = Path(path) if path else SCOPE_PATH
        if not path.exists():
            return cls()
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(
            require_house_vessel=data.get("require_house_vessel", True),
            require_stable_service=data.get("require_stable_service", True),
            include=[s.upper() for s in data.get("include", [])],
            exclude=[s.upper() for s in data.get("exclude", [])],
            notes=data.get("_notes", ""),
        )


@dataclass
class Rejection:
    history: VoyageHistory
    reason: str
    detail: str = ""


@dataclass
class Selection:
    selected: list[VoyageHistory]
    rejected: list[Rejection]
    service_scope: dict[str, str]  # service -> "in" or the reason it is out


def service_scope(
    index: HistoryIndex, mapping: OperatorMapping, config: ScopeConfig
) -> dict[str, str]:
    """Classify every service seen in the Daily files as in or out of scope.

    Two observations drive the default rules, both drawn from the Daily files
    rather than from any particular month's answer:

    * a comparison against WAN HAI needs a WAN HAI vessel on the service —
      services no WAN HAI ship ever calls on have nothing to compare;
    * services that appear part-way through the ingested period, or stop
      appearing before it ends, were not running for the whole period.

    Both are overridable in ``config/report_scope.json``.
    """
    snapshots_by_service: dict[str, set[str]] = {}
    house_vessel: dict[str, bool] = {}
    all_files: set[str] = set()

    for history in index.all():
        for snap in history.snapshots:
            if not snap.svc:
                continue
            all_files.add(snap.source_file)
            snapshots_by_service.setdefault(snap.svc, set()).add(snap.source_file)
            if mapping.resolve(snap.vessel_voyage, snap.tfc).opr == mapping.house_operator:
                house_vessel[snap.svc] = True

    ordered_files = sorted(all_files)
    # With a single snapshot there is no "appeared" or "stopped appearing" to
    # observe, so the stability rule would classify every service identically.
    stable_rule = config.require_stable_service and len(ordered_files) > 1
    first_file = ordered_files[0] if ordered_files else None
    last_file = ordered_files[-1] if ordered_files else None

    scope: dict[str, str] = {}
    for svc, files in snapshots_by_service.items():
        if svc in config.exclude:
            scope[svc] = SERVICE_EXCLUDED
            continue
        if svc in config.include:
            scope[svc] = "in"
            continue
        if config.require_house_vessel and not house_vessel.get(svc):
            scope[svc] = SERVICE_NO_HOUSE_VESSEL
            continue
        if stable_rule and first_file and last_file:
            if first_file not in files or last_file not in files:
                scope[svc] = SERVICE_NOT_STABLE
                continue
        scope[svc] = "in"
    return scope


def select_for_month(
    index: HistoryIndex,
    year: int,
    month: int,
    mapping: OperatorMapping,
    config: ScopeConfig | None = None,
) -> Selection:
    config = config or ScopeConfig()
    scope = service_scope(index, mapping, config)

    selected: list[VoyageHistory] = []
    rejected: list[Rejection] = []

    for history in index.all():
        snap = history.consolidated()

        if not is_qingdao(snap.terminal):
            rejected.append(Rejection(history, NOT_QINGDAO, str(snap.terminal)))
            continue
        if snap.atd is None:
            # Only worth reviewing if the voyage plausibly belongs to this month.
            if _plausibly_in_month(history, year, month):
                rejected.append(
                    Rejection(history, NO_ATD, "no ATD in any ingested Daily file")
                )
            continue
        if (snap.atd.year, snap.atd.month) != (year, month):
            rejected.append(
                Rejection(history, OTHER_MONTH, snap.atd.strftime("ATD %Y-%m-%d %H:%M"))
            )
            continue

        verdict = scope.get(snap.svc or "", "in")
        if verdict != "in":
            rejected.append(Rejection(history, verdict, f"service {snap.svc}"))
            continue

        selected.append(history)

    selected.sort(key=_sort_key)
    return Selection(selected, rejected, scope)


def _plausibly_in_month(history: VoyageHistory, year: int, month: int) -> bool:
    snap = history.consolidated()
    for value in (snap.atb, snap.ata, snap.etd, snap.window_start):
        if value is not None:
            return (value.year, value.month) == (year, month)
    return False


def _sort_key(history: VoyageHistory):
    """SVC, then OPR grouping order, then chronological within the group.

    Operator ordering is applied later, once operators are resolved; berthing
    time is the stable within-group order the historical report uses.
    """
    snap = history.consolidated()
    return (snap.svc or "", snap.atb or snap.ata or snap.atd)


def service_terminals(index: HistoryIndex) -> dict[str, str]:
    """The berth each service is currently working out of.

    The monthly report names the service's terminal, not the individual
    berth a given call happened to use: a ship shifted to a neighbouring
    berth for one call is still that service's window. Services do move
    between terminals over time, so the most recent Daily file wins.
    """
    latest: dict[str, tuple[object, str]] = {}
    for history in index.all():
        for snap in history.snapshots:
            terminal = normalize_terminal(snap.terminal)
            if not snap.svc or not terminal:
                continue
            stamp = (snap.snapshot_date, snap.source.week_label, snap.source.row)
            if snap.svc not in latest or stamp > latest[snap.svc][0]:
                latest[snap.svc] = (stamp, terminal)
    return {svc: terminal for svc, (_, terminal) in latest.items()}
