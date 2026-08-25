"""Vessel -> operator (OPR) resolution, driven by an editable local mapping.

The Daily Berth Report has no operator column: the person writing the monthly
report knows which carrier runs which ship. That knowledge lives in
``config/operator_mapping.json`` so it can be corrected and extended without
touching code — an unrecognised vessel is reported as ``OPR_UNKNOWN`` and
surfaced for review rather than guessed at.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app import paths

CONFIG_FILE = "operator_mapping.json"
# The shipped list in a source checkout; the user's own copy once they edit it.
CONFIG_PATH = paths.resolve_config(CONFIG_FILE)

UNKNOWN = "OPR_UNKNOWN"
WHL = "WHL"


@dataclass(frozen=True)
class OperatorResult:
    opr: str
    source: str  # "vessel_exact" | "vessel_keyword" | "tfc_pattern" | "unknown"
    matched_on: str | None = None

    @property
    def is_known(self) -> bool:
        return self.opr != UNKNOWN


def normalize_vessel_name(vessel: str | None) -> str:
    """'WAN HAI 511/E111' -> 'WAN HAI 511'; collapses spacing and case."""
    if not vessel:
        return ""
    head = str(vessel).split("/")[0]
    return re.sub(r"\s+", " ", head).strip().upper()


class OperatorMapping:
    def __init__(self, data: dict):
        self.vessels: dict[str, str] = {
            normalize_vessel_name(k): v for k, v in data.get("vessels", {}).items()
        }
        # Ordered: the first keyword contained in the vessel name wins, so
        # longer/more specific keywords must be listed first.
        self.keywords: list[tuple[str, str]] = [
            (str(k).upper(), v) for k, v in data.get("keywords", [])
        ]
        self.house_operator: str = data.get("house_operator", WHL)
        self.notes: str = data.get("_notes", "")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "OperatorMapping":
        path = Path(path) if path else paths.resolve_config(CONFIG_FILE)
        if not path.exists():
            return cls({})
        with path.open(encoding="utf-8") as fh:
            return cls(json.load(fh))

    def save(self, path: str | Path | None = None) -> Path:
        # Always written where the user's own files live, never back into a
        # read-only application folder.
        path = Path(path) if path else paths.user_file(CONFIG_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_notes": self.notes,
            "house_operator": self.house_operator,
            "vessels": dict(sorted(self.vessels.items())),
            "keywords": [list(k) for k in self.keywords],
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return path

    def resolve(self, vessel: str | None, tfc: str | None = None) -> OperatorResult:
        name = normalize_vessel_name(vessel)
        if name and name in self.vessels:
            return OperatorResult(self.vessels[name], "vessel_exact", name)
        for keyword, opr in self.keywords:
            if keyword and keyword in name:
                return OperatorResult(opr, "vessel_keyword", keyword)
        return OperatorResult(UNKNOWN, "unknown", name or tfc)

    def learn(self, vessel: str | None, opr: str) -> None:
        """Record a user's decision so the next report resolves it automatically."""
        name = normalize_vessel_name(vessel)
        if name:
            self.vessels[name] = opr


def is_house_vessel(opr: str, mapping: OperatorMapping) -> bool:
    """True for WAN HAI's own vessels, whose Daily figures are authoritative."""
    return opr == mapping.house_operator
