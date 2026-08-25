"""Turning "the system isn't sure" into a question a person can answer.

Every issue carries the same shape: what is uncertain, the evidence behind it,
the candidate answers, and — where the data supports one — a recommendation
with the reason for it. Nothing here decides anything; it only asks well.

The recommendation is never applied silently. An issue that would leave a
required output field blank is *blocking* for that row and the field stays
empty until someone answers; everything else has a defensible default value in
the report already, and the question is an invitation to disagree with it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.calculations import MonthlyRow, calc_waiting_from_arrival
from app.decisions import DecisionStore
from app.models import VoyageHistory
from app.operators import UNKNOWN, OperatorMapping
from app.voyage_history import HistoryIndex

# Issue kinds
UNKNOWN_OPERATOR = "UNKNOWN_OPERATOR"
AMBIGUOUS_VOYAGE = "AMBIGUOUS_VOYAGE"
MISSING_ATD = "MISSING_ATD"
CONFLICTING_SNAPSHOTS = "CONFLICTING_SNAPSHOTS"
VALUE_DISAGREEMENT = "VALUE_DISAGREEMENT"
UNCERTAIN_WINDOW = "UNCERTAIN_WINDOW"
BERTHED_BEFORE_WINDOW = "BERTHED_BEFORE_WINDOW"

# Which output fields must be present for a row to stand on its own.
REQUIRED_FIELDS = ("svc", "tfc", "opr", "terminal", "ata", "atb")

# A timestamp being sharpened from an estimate to the minute is the board doing
# its job, not a conflict. Only a revision bigger than this — or one made after
# the voyage had already finished — is worth anyone's attention.
MATERIAL_REVISION_HOURS = 2.0


@dataclass
class Option:
    """One answer the user can pick."""

    key: str
    label: str
    value: object
    rationale: str = ""
    recommended: bool = False


@dataclass
class ReviewIssue:
    kind: str
    voyage_key: str
    field: str
    question: str
    options: list[Option] = field(default_factory=list)
    why_recommended: str = ""
    blocking: bool = False
    reusable: bool = False  # answering it creates a rule, not a one-off override

    # Evidence shown alongside the question
    tfc: str | None = None
    svc: str | None = None
    vessel: str | None = None
    timestamps: dict[str, datetime | None] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.target}:{self.field}"

    @property
    def target(self) -> str:
        """What a decision about this issue attaches to."""
        return self.vessel if self.reusable and self.vessel else self.voyage_key

    @property
    def recommended(self) -> Option | None:
        return next((o for o in self.options if o.recommended), None)

    def option(self, key: str) -> Option | None:
        return next((o for o in self.options if o.key == key), None)

    def summary(self) -> str:
        return f"{self.svc or '?'} {self.tfc or self.voyage_key} — {self.question}"


def _stamps(row_or_snap) -> dict:
    return {
        "ATA": getattr(row_or_snap, "ata", None),
        "ATB": getattr(row_or_snap, "atb", None),
        "ATD": getattr(row_or_snap, "atd", None),
        "Window start": getattr(row_or_snap, "window_start", None),
        "Window end": getattr(row_or_snap, "window_end", None),
    }


def _files(history: VoyageHistory) -> list[str]:
    seen: list[str] = []
    for snap in history.snapshots:
        if snap.source_file not in seen:
            seen.append(snap.source_file)
    return seen


# --- individual detectors -----------------------------------------------------


def _operator_issue(
    row: MonthlyRow, history: VoyageHistory, index: HistoryIndex, mapping: OperatorMapping
) -> ReviewIssue | None:
    if row.opr != UNKNOWN:
        return None

    # Offer the operators already seen on this service, most common first —
    # a partner service usually runs the same handful of carriers.
    on_service = Counter(
        mapping.resolve(s.vessel_voyage, s.tfc).opr
        for h in index.all()
        for s in h.snapshots
        if s.svc == row.svc
    )
    on_service.pop(UNKNOWN, None)
    everywhere = Counter(
        mapping.resolve(s.vessel_voyage, s.tfc).opr
        for h in index.all()
        for s in h.snapshots
    )
    everywhere.pop(UNKNOWN, None)

    candidates: list[str] = [opr for opr, _ in on_service.most_common(6)]
    for opr, _ in everywhere.most_common():
        if opr not in candidates and len(candidates) < 8:
            candidates.append(opr)

    options = [
        Option(
            key=opr,
            label=opr,
            value=opr,
            rationale=(
                f"runs {on_service[opr]} of the {sum(on_service.values())} calls "
                f"on {row.svc} in these files"
                if on_service.get(opr)
                else "seen elsewhere in these files"
            ),
        )
        for opr in candidates
    ]

    why = ""
    if on_service:
        # Only recommend when one carrier clearly dominates the service; a
        # two-carrier service is a coin toss and should not be guessed at.
        (top, top_n), *rest = on_service.most_common()
        runner_up = rest[0][1] if rest else 0
        if top_n >= 2 * max(runner_up, 1):
            for option in options:
                option.recommended = option.key == top
            why = (
                f"{top} operates {top_n} of the {sum(on_service.values())} "
                f"{row.svc} calls in these files, more than twice any other "
                "carrier — but the vessel name is what decides it, so check the ship."
            )

    return ReviewIssue(
        kind=UNKNOWN_OPERATOR,
        voyage_key=row.voyage_key,
        field="opr",
        question=f"Which carrier operates {row.vessel_voyage}?",
        options=options,
        why_recommended=why,
        blocking=True,
        reusable=True,
        tfc=row.tfc,
        svc=row.svc,
        vessel=row.vessel_voyage,
        timestamps=_stamps(row),
        source_files=_files(history),
        evidence=[
            "The Daily Berth Report has no operator column, and this vessel is "
            "not in config/operator_mapping.json.",
            "Your answer is saved as a reusable rule and applied automatically "
            "from next month on.",
        ],
    )


def _value_disagreement_issues(
    row: MonthlyRow, history: VoyageHistory
) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for field_name, label, prov in (
        ("arr_delay", "Arr Delay", row.arr_delay),
        ("dep_delay", "Dep Delay", row.dep_delay),
        ("waiting", "W/B", row.waiting),
    ):
        if prov.method != "copied_from_daily":
            continue
        if prov.calculated_value is None or prov.value is None:
            continue
        if abs(prov.calculated_value - prov.value) <= 0.11:
            continue

        issues.append(
            ReviewIssue(
                kind=VALUE_DISAGREEMENT,
                voyage_key=row.voyage_key,
                field=field_name,
                question=(
                    f"{label}: the Daily prints {prov.value}, but this voyage's "
                    f"timestamps give {prov.calculated_value}. Which should the "
                    "report show?"
                ),
                options=[
                    Option(
                        "daily",
                        f"Use the Daily value ({prov.value})",
                        prov.value,
                        "the figure WAN HAI already publishes for this vessel",
                        recommended=True,
                    ),
                    Option(
                        "calculated",
                        f"Use the calculated value ({prov.calculated_value})",
                        prov.calculated_value,
                        "recomputed from the timestamps currently on the row",
                    ),
                    Option("manual", "Enter a value", None, "type the figure yourself"),
                ],
                why_recommended=(
                    "In every case in the historical report where these two "
                    "disagreed, the manual report used the Daily's figure. The "
                    "timestamps on a row are sometimes revised after the delay "
                    "columns were struck, and the published figure is the one "
                    "the business has already stood behind."
                ),
                blocking=False,
                tfc=row.tfc,
                svc=row.svc,
                vessel=row.vessel_voyage,
                timestamps=_stamps(row),
                source_files=_files(history),
                evidence=[
                    f"Daily figure last seen in {prov.source_file}.",
                    f"Formula if recalculated: {prov.formula}.",
                ],
            )
        )
    return issues


def _window_issue(row: MonthlyRow, history: VoyageHistory) -> ReviewIssue | None:
    if "WINDOW_WEEKDAY_MISMATCH" not in row.flags:
        return None
    snap = history.consolidated()
    return ReviewIssue(
        kind=UNCERTAIN_WINDOW,
        voyage_key=row.voyage_key,
        field="window",
        question=(
            "The berthing window's dates fall on a different weekday than this "
            "service's weekly slot. Which window applies?"
        ),
        options=[
            Option(
                "pattern",
                f"Use the weekly slot ({_fmt(row.window_start)} – {_fmt(row.window_end)})",
                [row.window_start, row.window_end],
                f"matches the service's standing slot '{snap.window_pattern}'",
                recommended=True,
            ),
            Option(
                "as_written",
                f"Use the dates as written ({_fmt(snap.window_start)} – {_fmt(snap.window_end)})",
                [snap.window_start, snap.window_end],
                "takes the Daily's Window Time cell at face value",
            ),
        ],
        why_recommended=(
            "Both ends of the written window are out by the same whole number of "
            "days at exactly the right clock times, which is what a mistyped date "
            "looks like. The service's weekly slot is the more reliable of the "
            "two, and the delays are recalculated against it."
        ),
        blocking=False,
        tfc=row.tfc,
        svc=row.svc,
        vessel=row.vessel_voyage,
        timestamps=_stamps(row),
        source_files=_files(history),
        evidence=[
            f"Window Time cell reads '{snap.window_raw}'.",
            f"Weekly slot reads '{snap.window_pattern}'.",
        ],
    )


def _berthed_early_issue(row: MonthlyRow, history: VoyageHistory) -> ReviewIssue | None:
    if "BERTHED_BEFORE_WINDOW_OPENED" not in row.flags:
        return None
    if row.waiting.method == "copied_from_daily":
        return None  # the Daily already published a figure; that is the question below
    from_arrival = calc_waiting_from_arrival(history.consolidated())
    return ReviewIssue(
        kind=BERTHED_BEFORE_WINDOW,
        voyage_key=row.voyage_key,
        field="waiting",
        question=(
            "This ship berthed before its window even opened. Should W/B be zero, "
            "or the time from arrival to berthing?"
        ),
        options=[
            Option(
                "zero", "W/B = 0", 0.0,
                "it never waited for a berth — it was taken early",
                recommended=True,
            ),
            Option(
                "from_arrival", f"W/B = {from_arrival}", from_arrival,
                "counts every hour between arriving and berthing",
            ),
            Option("manual", "Enter a value", None, "type the figure yourself"),
        ],
        why_recommended=(
            "Waiting time measures how long a ship waited for a berth it was "
            "entitled to. This one was berthed before its slot opened, so the "
            "hours before that were not spent waiting for the terminal."
        ),
        blocking=False,
        tfc=row.tfc,
        svc=row.svc,
        vessel=row.vessel_voyage,
        timestamps=_stamps(row),
        source_files=_files(history),
        evidence=[
            f"Berthed {_fmt(row.atb)}, window opened {_fmt(row.window_start)}.",
        ],
    )


def _conflicting_snapshot_issues(
    row: MonthlyRow, history: VoyageHistory
) -> list[ReviewIssue]:
    """Actual timestamps that were materially revised after first being recorded."""
    issues: list[ReviewIssue] = []
    completed = history.first_seen("atd")

    for field_name, label in (("ata", "ATA"), ("atb", "ATB"), ("atd", "ATD")):
        seen: list[tuple[datetime, str, datetime]] = []
        for snap in history.snapshots:
            value = getattr(snap, field_name)
            if value is None:
                continue
            if not seen or seen[-1][0] != value:
                seen.append((value, snap.source_file, snap.snapshot_date))
        if len(seen) < 2:
            continue

        spread = max(
            abs((a[0] - b[0]).total_seconds()) / 3600 for a in seen for b in seen
        )
        revised_after_completion = (
            completed is not None and seen[-1][2] > completed.snapshot_date
        )
        if spread < MATERIAL_REVISION_HOURS and not revised_after_completion:
            continue

        seen = [(value, file) for value, file, _ in seen]
        latest_value, latest_file = seen[-1]
        options = [
            Option(
                key=file,
                label=f"{_fmt(value)}  (from {file})",
                value=value,
                rationale="most recently recorded" if file == latest_file else "recorded earlier",
                recommended=(file == latest_file),
            )
            for value, file in seen
        ]
        issues.append(
            ReviewIssue(
                kind=CONFLICTING_SNAPSHOTS,
                voyage_key=row.voyage_key,
                field=field_name,
                question=(
                    f"{label} was recorded {len(seen)} different ways across the "
                    f"Daily files, {spread:.0f} hours apart. Which is correct?"
                ),
                options=options,
                why_recommended=(
                    f"The most recent file, {latest_file}, is the one the berth "
                    "board was last corrected in, so it normally supersedes what "
                    "came before. Check it against the vessel's own record if the "
                    "difference is large."
                ),
                blocking=False,
                tfc=row.tfc,
                svc=row.svc,
                vessel=row.vessel_voyage,
                timestamps=_stamps(row),
                source_files=_files(history),
                evidence=[f"{label} {_fmt(v)} in {f}" for v, f in seen],
            )
        )
    return issues


def _missing_atd_issue(history: VoyageHistory, period: str) -> ReviewIssue:
    snap = history.consolidated()
    return ReviewIssue(
        kind=MISSING_ATD,
        voyage_key=history.voyage_key,
        field="include",
        question=(
            "This voyage has no departure time in any Daily file, so it cannot be "
            "placed in a month. Should it be in this report?"
        ),
        options=[
            Option(
                "exclude", "Leave it out", False,
                "no departure time means no evidence it belongs to this month",
                recommended=True,
            ),
            Option(
                "include", "Include it in this month", True,
                "you know it departed in this month; delays that need ATD stay blank",
            ),
            Option("manual", "Include it with a departure time I supply", None,
                   "type the ATD from another source"),
        ],
        why_recommended=(
            "Month membership is decided by departure time, and inventing one "
            "would put the voyage in a month on no evidence. It is more likely "
            "still at sea, or departed after the last Daily file was taken "
            f"({history.latest.source_file})."
        ),
        blocking=False,
        tfc=snap.tfc,
        svc=snap.svc,
        vessel=snap.vessel_voyage,
        timestamps=_stamps(snap),
        source_files=_files(history),
        evidence=[
            f"Last seen in {history.latest.source_file}.",
            f"Berthed {_fmt(snap.atb)}." if snap.atb else "Never recorded as berthed.",
        ],
    )


def _ambiguous_voyage_issue(keys: tuple[str, ...], index: HistoryIndex) -> ReviewIssue | None:
    """Two TFC codes that might be one call, kept apart until someone says so."""
    if len(keys) != 2:
        return None
    left, right = (index.resolve(k) for k in keys)
    if left is None or right is None:
        return None
    a, b = left.consolidated(), right.consolidated()

    return ReviewIssue(
        kind=AMBIGUOUS_VOYAGE,
        voyage_key=keys[0],
        field=f"merge_with:{keys[1]}",
        question=(
            f"{keys[0]} and {keys[1]} look like they could be the same call. "
            "Are they?"
        ),
        options=[
            Option(
                "separate", "Treat as two separate voyages", False,
                "keeps both rows, which is what the report does today",
                recommended=True,
            ),
            Option(
                f"use:{keys[0]}", f"One voyage — keep {keys[0]}", keys[0],
                f"merges both records under {keys[0]}",
            ),
            Option(
                f"use:{keys[1]}", f"One voyage — keep {keys[1]}", keys[1],
                f"merges both records under {keys[1]}",
            ),
        ],
        why_recommended=(
            "They share a service and terminal and berthed close together, but "
            "not enough else to be sure. Merging two real calls into one would "
            "silently drop a voyage from the report and skew the service average, "
            "so they are left apart unless you say otherwise."
        ),
        blocking=False,
        tfc=f"{keys[0]} / {keys[1]}",
        svc=a.svc,
        vessel=f"{a.vessel_voyage} / {b.vessel_voyage}",
        timestamps=_stamps(a),
        source_files=sorted(set(_files(left)) | set(_files(right))),
        evidence=[
            f"{keys[0]}: {a.vessel_voyage}, ATA {_fmt(a.ata)}, ATB {_fmt(a.atb)}, "
            f"{len(left.snapshots)} snapshots",
            f"{keys[1]}: {b.vessel_voyage}, ATA {_fmt(b.ata)}, ATB {_fmt(b.atb)}, "
            f"{len(right.snapshots)} snapshots",
        ],
    )


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d %b %H:%M")
    return str(value)


# --- the collector ------------------------------------------------------------


def collect_issues(
    rows: list[MonthlyRow],
    index: HistoryIndex,
    mapping: OperatorMapping,
    rejected_missing_atd: list[VoyageHistory],
    period: str,
    store: DecisionStore | None = None,
    services_in_scope: set[str] | None = None,
) -> list[ReviewIssue]:
    """Every question worth asking about this month, most serious first."""
    issues: list[ReviewIssue] = []

    for row in rows:
        history = index.resolve(row.voyage_key)
        if history is None:
            continue
        operator = _operator_issue(row, history, index, mapping)
        if operator:
            issues.append(operator)
        issues.extend(_value_disagreement_issues(row, history))
        window = _window_issue(row, history)
        if window:
            issues.append(window)
        early = _berthed_early_issue(row, history)
        if early:
            issues.append(early)
        issues.extend(_conflicting_snapshot_issues(row, history))

    for history in rejected_missing_atd:
        # A voyage on a service the report does not cover would not have been
        # included even with a departure time, so there is nothing to decide.
        svc = history.consolidated().svc
        if services_in_scope is not None and svc not in services_in_scope:
            continue
        issues.append(_missing_atd_issue(history, period))

    for note in index.notes:
        if note.kind == "AMBIGUOUS_VOYAGE" and note.keys:
            ambiguous = _ambiguous_voyage_issue(note.keys, index)
            if ambiguous:
                issues.append(ambiguous)

    if store is not None:
        answered = store.resolved_ids(period)
        issues = [i for i in issues if i.id not in answered]

    issues.sort(key=lambda i: (not i.blocking, i.kind, i.svc or "", i.tfc or ""))
    return issues
