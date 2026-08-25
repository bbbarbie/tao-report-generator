"""Where the user's answers to review questions are kept.

Two kinds of answer, deliberately kept apart:

* **Rules** are reusable. "The vessel KOTA CANTIK belongs to PIL" is true next
  month too, so it is remembered and applied automatically from then on.
* **Overrides** apply to exactly one voyage in one month. "For this call, use
  the calculated departure delay rather than the one the Daily printed" says
  nothing about any other call.

An override is never promoted to a rule. Answering the same kind of question
about a different voyage asks again, because the answer genuinely might differ.

The file lives outside version control: it records one person's decisions about
one company's voyages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DECISIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "decisions.json"

# Rule kinds. Only add a kind here if the answer really does generalise.
VESSEL_OPERATOR = "vessel_operator"
REUSABLE_KINDS = (VESSEL_OPERATOR,)


@dataclass
class Decision:
    """One answer, with enough context to explain itself later."""

    issue_kind: str
    target: str  # vessel name for a rule, voyage key for an override
    field: str  # which output field it sets — "opr", "dep_delay", "include", …
    value: object
    option_key: str = ""
    note: str = ""
    decided_at: str = ""
    period: str = ""  # overrides only

    def as_dict(self) -> dict:
        return {
            "issue_kind": self.issue_kind,
            "target": self.target,
            "field": self.field,
            "value": self.value,
            "option_key": self.option_key,
            "note": self.note,
            "decided_at": self.decided_at,
        }


@dataclass
class DecisionStore:
    rules: dict[str, dict[str, Decision]] = field(default_factory=dict)
    overrides: dict[str, dict[str, dict[str, Decision]]] = field(default_factory=dict)
    path: Path | None = None

    # --- loading and saving -------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DecisionStore":
        path = Path(path) if path else DECISIONS_PATH
        store = cls(path=path)
        if not path.exists():
            return store
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        for kind, entries in data.get("rules", {}).items():
            for target, raw in entries.items():
                store.rules.setdefault(kind, {})[target] = _decision_from(raw, kind, target)

        for period, voyages in data.get("overrides", {}).items():
            for voyage, fields in voyages.items():
                for field_name, raw in fields.items():
                    decision = _decision_from(raw, raw.get("issue_kind", ""), voyage)
                    decision.field = field_name
                    decision.period = period
                    store.overrides.setdefault(period, {}).setdefault(voyage, {})[
                        field_name
                    ] = decision
        return store

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else (self.path or DECISIONS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_notes": (
                "Decisions made on the Review page. 'rules' are reusable and apply "
                "to every future month; 'overrides' apply to one voyage in one "
                "month only. Nothing here is ever promoted from an override to a "
                "rule automatically. Safe to edit or delete by hand."
            ),
            "rules": {
                kind: {t: d.as_dict() for t, d in sorted(entries.items())}
                for kind, entries in sorted(self.rules.items())
            },
            "overrides": {
                period: {
                    voyage: {f: d.as_dict() for f, d in sorted(fields.items())}
                    for voyage, fields in sorted(voyages.items())
                }
                for period, voyages in sorted(self.overrides.items())
            },
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
            fh.write("\n")
        self.path = path
        return path

    # --- recording ----------------------------------------------------------

    def record_rule(
        self,
        kind: str,
        target: str,
        field_name: str,
        value: object,
        option_key: str = "",
        note: str = "",
    ) -> Decision:
        if kind not in REUSABLE_KINDS:
            raise ValueError(
                f"{kind!r} is not a reusable rule kind; record it as an override "
                "so one voyage's answer is not applied to every future month"
            )
        decision = Decision(
            issue_kind=kind,
            target=target,
            field=field_name,
            value=value,
            option_key=option_key,
            note=note,
            decided_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.rules.setdefault(kind, {})[target] = decision
        return decision

    def record_override(
        self,
        period: str,
        voyage_key: str,
        field_name: str,
        value: object,
        issue_kind: str = "",
        option_key: str = "",
        note: str = "",
    ) -> Decision:
        decision = Decision(
            issue_kind=issue_kind,
            target=voyage_key,
            field=field_name,
            value=value,
            option_key=option_key,
            note=note,
            decided_at=datetime.now().isoformat(timespec="seconds"),
            period=period,
        )
        self.overrides.setdefault(period, {}).setdefault(voyage_key, {})[
            field_name
        ] = decision
        return decision

    def forget_rule(self, kind: str, target: str) -> None:
        self.rules.get(kind, {}).pop(target, None)

    def forget_override(self, period: str, voyage_key: str, field_name: str) -> None:
        self.overrides.get(period, {}).get(voyage_key, {}).pop(field_name, None)

    # --- reading ------------------------------------------------------------

    def operator_rules(self) -> dict[str, str]:
        """Vessel name -> OPR, for folding into the operator mapping."""
        return {t: str(d.value) for t, d in self.rules.get(VESSEL_OPERATOR, {}).items()}

    def overrides_for(self, period: str, voyage_key: str) -> dict[str, Decision]:
        return dict(self.overrides.get(period, {}).get(voyage_key, {}))

    def resolved_ids(self, period: str) -> set[str]:
        """Issue ids already answered, either by a rule or by an override."""
        answered = {
            f"{d.issue_kind}:{d.target}:{d.field}"
            for entries in self.rules.values()
            for d in entries.values()
        }
        for voyage, fields in self.overrides.get(period, {}).items():
            for field_name, d in fields.items():
                answered.add(f"{d.issue_kind}:{voyage}:{field_name}")
        return answered

    @property
    def rule_count(self) -> int:
        return sum(len(entries) for entries in self.rules.values())

    @property
    def override_count(self) -> int:
        return sum(
            len(fields)
            for voyages in self.overrides.values()
            for fields in voyages.values()
        )


def _decision_from(raw: dict, kind: str, target: str) -> Decision:
    return Decision(
        issue_kind=raw.get("issue_kind") or kind,
        target=raw.get("target") or target,
        field=raw.get("field", ""),
        value=raw.get("value"),
        option_key=raw.get("option_key", ""),
        note=raw.get("note", ""),
        decided_at=raw.get("decided_at", ""),
    )
