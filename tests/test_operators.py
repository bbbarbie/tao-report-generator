from __future__ import annotations

import json

import pytest

from app.operators import UNKNOWN, OperatorMapping, normalize_vessel_name


def test_voyage_suffix_is_stripped_from_the_vessel_name():
    assert normalize_vessel_name("WAN HAI 511/E111") == "WAN HAI 511"
    assert normalize_vessel_name("  ital  bonny /S103 ") == "ITAL BONNY"
    assert normalize_vessel_name(None) == ""


class TestResolution:
    mapping = OperatorMapping.load()

    @pytest.mark.parametrize(
        "vessel,expected",
        [
            ("WAN HAI 511/E111", "WHL"),
            ("NYK RUMINA/E076", "ONE"),
            ("MOL EXPERIENCE/E105", "ONE"),
            ("KOTA PURI/E044", "PIL"),
            ("KOTA MANZANILLO/E026", "PIL"),
            ("TIGER CHENNAI/W605", "BTL"),
            ("INTERASIA HORIZON/W056", "IAL"),
            ("KMTC JEBEL ALI/W605", "KMTC"),
            ("ITAL BONNY/S103", "EMC"),
            ("EVER BURLY/S092", "EMC"),
            ("YM CENTENNIAL/S069", "YML"),
            ("XIN QING DAO/S256", "COS"),
            ("XIN CHI WAN/S100", "COS"),
            ("OOCL AMERICA/S199", "OOL"),
            ("CA GUANGZHOU/S564", "COS"),
        ],
    )
    def test_known_vessels(self, vessel, expected):
        assert self.mapping.resolve(vessel).opr == expected

    def test_an_unknown_vessel_is_reported_not_guessed(self):
        result = self.mapping.resolve("SOMETHING NEW/X001")
        assert result.opr == UNKNOWN
        assert not result.is_known

    def test_an_exact_entry_beats_a_keyword(self):
        mapping = OperatorMapping(
            {"vessels": {"XIN HONG KONG": "SPECIAL"}, "keywords": [["XIN ", "COS"]]}
        )
        assert mapping.resolve("XIN HONG KONG/E082").opr == "SPECIAL"
        assert mapping.resolve("XIN SOMETHING/E001").opr == "COS"

    def test_the_source_of_each_decision_is_reported(self):
        assert self.mapping.resolve("WAN HAI 511/E111").source == "vessel_keyword"
        assert self.mapping.resolve("NYK RUMINA/E076").source == "vessel_exact"
        assert self.mapping.resolve("???").source == "unknown"


class TestEditing:
    def test_a_learned_vessel_survives_a_round_trip(self, tmp_path):
        mapping = OperatorMapping.load()
        mapping.learn("BRAND NEW SHIP/X9", "NEW")
        path = mapping.save(tmp_path / "operator_mapping.json")
        reloaded = OperatorMapping.load(path)
        assert reloaded.resolve("BRAND NEW SHIP/X9").opr == "NEW"

    def test_the_shipped_config_is_valid_and_human_editable(self):
        from app.operators import CONFIG_PATH

        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert data["house_operator"] == "WHL"
        assert isinstance(data["vessels"], dict)
        assert all(len(pair) == 2 for pair in data["keywords"])
        assert data["_notes"]

    def test_a_missing_config_file_does_not_crash(self, tmp_path):
        mapping = OperatorMapping.load(tmp_path / "nope.json")
        assert mapping.resolve("WAN HAI 511").opr == UNKNOWN


def test_every_vessel_in_the_july_report_resolves(july_report):
    unresolved = {r.vessel_voyage for r in july_report.rows if r.opr == UNKNOWN}
    assert not unresolved
