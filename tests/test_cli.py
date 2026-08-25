from __future__ import annotations

import csv

import pytest

from app.cli import main, parse_month
from tests.conftest import DAILY_DIR, GROUND_TRUTH, requires_samples


@pytest.mark.parametrize("text", ["2026-07", "202607", "2026/07", " 2026-7 "])
def test_month_forms_all_parse(text):
    assert parse_month(text) == (2026, 7)


@pytest.mark.parametrize("text", ["july", "2026-13", "26-07-01-02"])
def test_bad_months_are_rejected(text):
    with pytest.raises(Exception):
        parse_month(text)


@requires_samples
def test_cli_writes_a_workbook_and_a_review_file(tmp_path, capsys):
    exit_code = main(
        ["--daily", str(DAILY_DIR), "--month", "2026-07", "--output-dir", str(tmp_path)]
    )
    assert exit_code == 0
    assert (tmp_path / "TAO Compare 202607.xlsx").exists()

    review = tmp_path / "review 202607.csv"
    rows = list(csv.DictReader(review.read_text(encoding="utf-8-sig").splitlines()))
    assert rows and set(rows[0]) == {"TFC", "SVC", "Vessel", "Reason", "Detail"}
    assert all(row["Reason"] for row in rows)

    out = capsys.readouterr().out
    assert "27 voyages in 202607" in out
    # The three row states and the open questions are reported, not just a total.
    for state in ("automatic", "reviewed", "unresolved"):
        assert state in out
    assert "open questions" in out
    assert "suggested:" in out


@requires_samples
def test_cli_can_validate_against_a_known_good_workbook(tmp_path, capsys):
    if not GROUND_TRUTH.exists():
        pytest.skip("no ground-truth workbook")
    main(
        [
            "--daily", str(DAILY_DIR),
            "--month", "202607",
            "--output-dir", str(tmp_path),
            "--validate-against", str(GROUND_TRUTH),
        ]
    )
    assert (tmp_path / "validation 202607.json").exists()
    assert "reproduced" in capsys.readouterr().out


@requires_samples
def test_individual_files_can_be_passed_instead_of_a_folder(tmp_path):
    files = sorted(DAILY_DIR.glob("Daily 20260*.xlsx"))[:3]
    assert main(
        ["--daily", *map(str, files), "--month", "2026-07", "--output-dir", str(tmp_path)]
    ) == 0


def test_a_missing_input_path_is_reported_clearly(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["--daily", str(tmp_path / "nope"), "--month", "2026-07"])
    assert "no such file or folder" in str(excinfo.value)
