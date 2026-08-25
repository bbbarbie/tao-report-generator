"""Builds one ``VoyageHistory`` per physical voyage from all Daily snapshots.

A Daily file is a snapshot, not a log: rows are edited in place, voyages move
between weekly sections as they slip, and a voyage drops off the board once it
scrolls out of the visible window. Reading only the month-end file therefore
loses voyages. This module stitches every snapshot together and keeps the
whole trail.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from app.models import VoyageHistory, VoyageSnapshot
from app.normalization import normalize_terminal

# How close two berthings must be to be considered the same call when the TFC
# code itself has been retyped between snapshots.
ATA_PROXIMITY = timedelta(hours=12)
ATB_PROXIMITY = timedelta(hours=12)


@dataclass
class MergeNote:
    kind: str
    detail: str
    keys: tuple[str, ...] = ()


@dataclass
class HistoryIndex:
    histories: dict[str, VoyageHistory] = field(default_factory=dict)
    notes: list[MergeNote] = field(default_factory=list)
    alias_of: dict[str, str] = field(default_factory=dict)

    def resolve(self, tfc: str | None) -> VoyageHistory | None:
        if not tfc:
            return None
        key = self.alias_of.get(tfc, tfc)
        return self.histories.get(key)

    def all(self) -> list[VoyageHistory]:
        return list(self.histories.values())


def build_histories(snapshots: list[VoyageSnapshot]) -> HistoryIndex:
    """Group snapshots into voyages, keyed on TFC and reconciled for retypes."""
    index = HistoryIndex()

    by_tfc: dict[str, list[VoyageSnapshot]] = defaultdict(list)
    orphans: list[VoyageSnapshot] = []
    for snap in snapshots:
        if snap.tfc:
            by_tfc[snap.tfc].append(snap)
        else:
            orphans.append(snap)

    for tfc, snaps in by_tfc.items():
        history = VoyageHistory(voyage_key=tfc)
        for s in snaps:
            history.add(s)
        index.histories[tfc] = history

    for snap in orphans:
        index.notes.append(
            MergeNote(
                "NO_TFC",
                f"{snap.source_file} row {snap.source.row}: "
                f"{snap.svc}/{snap.vessel_voyage} has no TFC code",
            )
        )

    _merge_retyped_codes(index)
    return index


def _identity_evidence(a: VoyageHistory, b: VoyageHistory) -> list[str]:
    """Evidence that two TFC codes describe the same physical call.

    Timestamps alone are never enough — two vessels can berth minutes apart —
    so a match needs the service, the terminal and the vessel to line up too.
    """
    ca, cb = a.consolidated(), b.consolidated()
    evidence: list[str] = []

    if not ca.svc or ca.svc != cb.svc:
        return []
    evidence.append("SVC")

    if normalize_terminal(ca.terminal) != normalize_terminal(cb.terminal):
        return []
    evidence.append("TML")

    if _vessel_root(ca.vessel_voyage) and _vessel_root(ca.vessel_voyage) == _vessel_root(
        cb.vessel_voyage
    ):
        evidence.append("VESSEL")

    if ca.ata and cb.ata and abs(ca.ata - cb.ata) <= ATA_PROXIMITY:
        evidence.append("ATA")
    if ca.atb and cb.atb and abs(ca.atb - cb.atb) <= ATB_PROXIMITY:
        evidence.append("ATB")

    if _tfc_near(a.voyage_key, b.voyage_key):
        evidence.append("TFC_NEAR")

    return evidence


def _vessel_root(vessel: str | None) -> str | None:
    """'KOTA MANZANILLO/E026' -> 'KOTAMANZANILLO'."""
    if not vessel:
        return None
    head = vessel.split("/")[0]
    return "".join(ch for ch in head.upper() if ch.isalnum()) or None


def _tfc_near(a: str, b: str) -> bool:
    """True when two TFC codes differ by at most one character in place."""
    if len(a) != len(b):
        return False
    return sum(1 for x, y in zip(a, b) if x != y) == 1


def _merge_retyped_codes(index: HistoryIndex) -> None:
    """Fold TFC codes that were retyped mid-month into a single voyage.

    Only merges on strong, multi-signal evidence, and records every merge —
    and every near-miss — so an operator can audit the decision.
    """
    keys = sorted(index.histories)
    merged: set[str] = set()

    for i, ka in enumerate(keys):
        if ka in merged:
            continue
        for kb in keys[i + 1 :]:
            if kb in merged or ka in merged:
                continue
            a, b = index.histories[ka], index.histories[kb]
            evidence = _identity_evidence(a, b)
            timing = "ATA" in evidence or "ATB" in evidence
            if not timing:
                # A vessel's consecutive voyages share service, terminal and
                # name and their TFC codes differ by one digit. Only berthings
                # at the same time can be the same call.
                continue
            strong = {"SVC", "TML"}.issubset(evidence) and (
                "VESSEL" in evidence or "TFC_NEAR" in evidence
            )
            if strong:
                target, source = (a, b) if len(a.snapshots) >= len(b.snapshots) else (b, a)
                for s in source.snapshots:
                    target.add(s)
                target.aliases.add(source.voyage_key)
                target.notes.append(
                    f"merged TFC {source.voyage_key} into {target.voyage_key} "
                    f"on evidence {'+'.join(evidence)}"
                )
                index.alias_of[source.voyage_key] = target.voyage_key
                index.histories.pop(source.voyage_key)
                merged.add(source.voyage_key)
                index.notes.append(
                    MergeNote(
                        "MERGED_TFC",
                        f"{source.voyage_key} -> {target.voyage_key} ({'+'.join(evidence)})",
                        (source.voyage_key, target.voyage_key),
                    )
                )
            else:
                index.notes.append(
                    MergeNote(
                        "AMBIGUOUS_VOYAGE",
                        f"{ka} and {kb} share {'+'.join(evidence)} but were not merged",
                        (ka, kb),
                    )
                )
