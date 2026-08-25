"""Saved decisions: what is remembered, and what deliberately is not."""

from __future__ import annotations

import json

import pytest

from app.decisions import VESSEL_OPERATOR, DecisionStore


@pytest.fixture
def store(tmp_path):
    return DecisionStore(path=tmp_path / "decisions.json")


class TestRules:
    def test_a_vessel_operator_rule_round_trips(self, store, tmp_path):
        store.record_rule(VESSEL_OPERATOR, "KOTA CANTIK", "opr", "PIL", "PIL", "asked ops")
        store.save()
        reloaded = DecisionStore.load(tmp_path / "decisions.json")
        assert reloaded.operator_rules() == {"KOTA CANTIK": "PIL"}
        assert reloaded.rules[VESSEL_OPERATOR]["KOTA CANTIK"].note == "asked ops"

    def test_a_rule_records_when_it_was_made(self, store):
        decision = store.record_rule(VESSEL_OPERATOR, "X", "opr", "PIL")
        assert decision.decided_at

    def test_only_genuinely_reusable_kinds_may_become_rules(self, store):
        """A voyage's departure delay says nothing about any other voyage."""
        with pytest.raises(ValueError, match="not a reusable rule kind"):
            store.record_rule("VALUE_DISAGREEMENT", "W02762B", "dep_delay", -9.8)

    def test_a_rule_can_be_forgotten(self, store):
        store.record_rule(VESSEL_OPERATOR, "X", "opr", "PIL")
        store.forget_rule(VESSEL_OPERATOR, "X")
        assert store.operator_rules() == {}


class TestOverrides:
    def test_an_override_round_trips(self, store, tmp_path):
        store.record_override("202607", "W02762B", "dep_delay", -9.8, "VALUE_DISAGREEMENT")
        store.save()
        reloaded = DecisionStore.load(tmp_path / "decisions.json")
        saved = reloaded.overrides_for("202607", "W02762B")
        assert saved["dep_delay"].value == -9.8
        assert saved["dep_delay"].issue_kind == "VALUE_DISAGREEMENT"

    def test_an_override_is_scoped_to_one_month(self, store):
        store.record_override("202607", "W02762B", "dep_delay", -9.8)
        assert store.overrides_for("202608", "W02762B") == {}

    def test_an_override_is_scoped_to_one_voyage(self, store):
        store.record_override("202607", "W02762B", "dep_delay", -9.8)
        assert store.overrides_for("202607", "W001903") == {}

    def test_an_override_never_becomes_a_rule(self, store):
        store.record_override("202607", "W02762B", "dep_delay", -9.8)
        assert store.rule_count == 0
        assert store.operator_rules() == {}

    def test_an_override_can_be_undone(self, store):
        store.record_override("202607", "W02762B", "dep_delay", -9.8)
        store.forget_override("202607", "W02762B", "dep_delay")
        assert store.override_count == 0


class TestFile:
    def test_a_missing_file_loads_as_an_empty_store(self, tmp_path):
        store = DecisionStore.load(tmp_path / "nothing.json")
        assert store.rule_count == 0 and store.override_count == 0

    def test_the_written_file_is_readable_and_explains_itself(self, store, tmp_path):
        store.record_rule(VESSEL_OPERATOR, "KOTA CANTIK", "opr", "PIL")
        store.record_override("202607", "W02762B", "dep_delay", -9.8)
        path = store.save()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "rules" in data and "overrides" in data
        # The file has to explain itself: someone may open it in a year's time.
        notes = data["_notes"]
        assert "reusable" in notes and "one voyage in one month" in notes
        assert "never promoted from an override to a rule" in notes.replace(
            "is ever promoted", "never promoted"
        )

    def test_resolved_ids_cover_both_kinds(self, store):
        store.record_rule(VESSEL_OPERATOR, "KOTA CANTIK", "opr", "PIL")
        store.record_override("202607", "W02762B", "dep_delay", -9.8, "VALUE_DISAGREEMENT")
        ids = store.resolved_ids("202607")
        assert "vessel_operator:KOTA CANTIK:opr" in ids
        assert "VALUE_DISAGREEMENT:W02762B:dep_delay" in ids

    def test_resolved_ids_for_another_month_keep_the_rules_only(self, store):
        store.record_rule(VESSEL_OPERATOR, "KOTA CANTIK", "opr", "PIL")
        store.record_override("202607", "W02762B", "dep_delay", -9.8, "VALUE_DISAGREEMENT")
        ids = store.resolved_ids("202608")
        assert "vessel_operator:KOTA CANTIK:opr" in ids
        assert "VALUE_DISAGREEMENT:W02762B:dep_delay" not in ids
