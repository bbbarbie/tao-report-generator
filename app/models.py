"""Normalized data model shared by the whole pipeline.

Everything downstream of the parser works on these structures; nothing
downstream re-opens a workbook.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    """Where a value came from — the backbone of the audit trail."""

    source_file: str
    snapshot_date: datetime
    sheet: str
    row: int
    week_label: str  # e.g. "WK30"


@dataclass
class VoyageSnapshot:
    """One row of one weekly section of one Daily workbook."""

    source: SourceRef

    svc: str | None = None
    vessel_voyage: str | None = None
    tfc: str | None = None
    terminal: str | None = None

    eta: datetime | None = None
    ata: datetime | None = None
    etb: datetime | None = None
    atb: datetime | None = None
    etd: datetime | None = None
    atd: datetime | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None
    window_pattern: str | None = None
    window_raw: str | None = None
    # The standing weekly slot the pattern column describes, resolved into
    # this section's week. Used to spot a mistyped concrete window.
    pattern_start: datetime | None = None
    pattern_end: datetime | None = None

    # Values as printed in the Daily workbook (may be blank for non-WHL rows).
    arr_delay_reported: float | None = None
    dep_delay_reported: float | None = None
    waiting_reported: float | None = None
    gph: float | None = None
    delay_reason: str | None = None

    # Raw cell text, kept for diagnostics.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def snapshot_date(self) -> datetime:
        return self.source.snapshot_date

    @property
    def source_file(self) -> str:
        return self.source.source_file


@dataclass
class FieldChange:
    field_name: str
    old: Any
    new: Any
    at_snapshot: datetime
    source_file: str


@dataclass
class VoyageHistory:
    """All appearances of one physical voyage across every ingested Daily file."""

    voyage_key: str
    snapshots: list[VoyageSnapshot] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def add(self, snap: VoyageSnapshot) -> None:
        self.snapshots.append(snap)
        self.snapshots.sort(key=lambda s: (s.snapshot_date, s.source.row))

    @property
    def latest(self) -> VoyageSnapshot:
        return self.snapshots[-1]

    @property
    def first(self) -> VoyageSnapshot:
        return self.snapshots[0]

    def changes(self) -> list[FieldChange]:
        """Field-by-field diff across consecutive snapshots."""
        out: list[FieldChange] = []
        names = [
            "svc",
            "vessel_voyage",
            "tfc",
            "terminal",
            "eta",
            "ata",
            "etb",
            "atb",
            "etd",
            "atd",
            "window_start",
            "window_end",
            "arr_delay_reported",
            "dep_delay_reported",
            "waiting_reported",
            "gph",
        ]
        for prev, cur in zip(self.snapshots, self.snapshots[1:]):
            for name in names:
                a, b = getattr(prev, name), getattr(cur, name)
                if a != b:
                    out.append(
                        FieldChange(name, a, b, cur.snapshot_date, cur.source_file)
                    )
        return out

    def first_seen(self, field_name: str) -> VoyageSnapshot | None:
        """The earliest snapshot in which ``field_name`` had a value."""
        for s in self.snapshots:
            if getattr(s, field_name) is not None:
                return s
        return None

    def latest_value(self, field_name: str) -> tuple[Any, VoyageSnapshot | None]:
        """Most recent non-null value of ``field_name`` and the snapshot it came from."""
        for s in reversed(self.snapshots):
            v = getattr(s, field_name)
            if v is not None:
                return v, s
        return None, None

    def consolidated(self) -> VoyageSnapshot:
        """Latest non-null value of every field, merged into one snapshot.

        A voyage's row can lose values in later Daily files (rows get retyped,
        weeks scroll off). Consolidating forward-fills so nothing already
        observed is thrown away, while newer values still win.
        """
        base = replace(self.latest)
        for name in (
            "svc",
            "vessel_voyage",
            "tfc",
            "terminal",
            "eta",
            "ata",
            "etb",
            "atb",
            "etd",
            "atd",
            "window_start",
            "window_end",
            "window_pattern",
            "window_raw",
            "pattern_start",
            "pattern_end",
            "arr_delay_reported",
            "dep_delay_reported",
            "waiting_reported",
            "gph",
            "delay_reason",
        ):
            if getattr(base, name) is None:
                value, _ = self.latest_value(name)
                setattr(base, name, value)
        return base

    def provenance(self, field_name: str) -> VoyageSnapshot | None:
        _, snap = self.latest_value(field_name)
        return snap
