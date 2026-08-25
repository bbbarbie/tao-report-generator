"""The desktop application — the end-user product.

Driven offscreen, so these run unattended in CI. They cover wiring and state,
not pixels: whether the views reach the engine correctly, and whether decisions
made in the window reach the store.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.calculations import REVIEWED, UNRESOLVED  # noqa: E402
from app.decisions import DecisionStore  # noqa: E402
from app.settings import Settings  # noqa: E402
from desktop.main import COLUMNS, MainWindow  # noqa: E402
from tests.conftest import DAILY_DIR, requires_samples  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, tmp_path):
    """A window whose settings and decisions go to scratch files."""
    win = MainWindow(
        settings=Settings(path=tmp_path / "settings.json"),
        store=DecisionStore(path=tmp_path / "decisions.json"),
    )
    yield win
    win.close()
    win.deleteLater()
    QApplication.processEvents()


def process(window, year=2026, month=7, timeout=180.0):
    """Run a month and pump the event loop until the result lands.

    Blocking on the worker would stop the queued signal that carries the
    result ever being delivered, so the loop has to keep turning.
    """
    import time

    window.report = None
    window._set_folder(DAILY_DIR)
    window.year_input.setValue(year)
    window.month_input.setCurrentIndex(month - 1)
    window.process()

    deadline = time.monotonic() + timeout
    while window.report is None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert window.report is not None, "processing did not finish"
    QApplication.processEvents()
    return window.report


class TestWindow:
    def test_it_opens(self, window):
        assert window.windowTitle() == "TAO Report Generator"

    def test_processing_is_blocked_until_a_folder_is_chosen(self, window):
        assert not window.process_button.isEnabled()

    def test_choosing_a_folder_finds_the_daily_files(self, window):
        window._set_folder(DAILY_DIR)
        if not window.files:
            pytest.skip("no sample workbooks")
        assert window.process_button.isEnabled()
        assert "找到" in window.folder_label.text()

    def test_a_folder_with_no_daily_files_says_so(self, window, tmp_path):
        window._set_folder(tmp_path)
        assert not window.process_button.isEnabled()
        assert not window.files


class TestSettings:
    def test_the_folder_is_remembered(self, window, tmp_path):
        window._set_folder(DAILY_DIR)
        assert Settings.load(tmp_path / "settings.json").daily_folder == str(DAILY_DIR)

    @requires_samples
    def test_the_month_is_remembered_and_the_next_one_offered(self, window, tmp_path):
        process(window)
        reloaded = Settings.load(tmp_path / "settings.json")
        assert reloaded.last_period == "202607"
        assert reloaded.suggested_period() == (2026, 8)

    def test_a_corrupt_settings_file_does_not_stop_it_starting(self, tmp_path):
        broken = tmp_path / "settings.json"
        broken.write_text("{not json", encoding="utf-8")
        assert Settings.load(broken).daily_folder == ""


@requires_samples
class TestProcessing:
    def test_the_table_shows_every_row(self, window):
        report = process(window)
        assert report is not None
        assert window.table.rowCount() == len(report.rows) == 27

    def test_the_three_row_states_are_visible_in_the_table(self, window):
        process(window)
        statuses = {
            window.table.item(r, 0).text() for r in range(window.table.rowCount())
        }
        assert statuses <= {"自動 Automatic", "已確認 Reviewed", "待確認 Unresolved"}

    def test_unresolved_rows_are_tinted_and_automatic_ones_are_not(self, window):
        from desktop.main import STATUS_COLOUR

        report = process(window)
        unresolved = [
            r for r, row in enumerate(report.rows) if row.resolution == UNRESOLVED
        ]
        assert unresolved, "expected some open questions in July"
        expected = STATUS_COLOUR[UNRESOLVED].name()
        for r in unresolved:
            assert window.table.item(r, 0).background().color().name() == expected
        for r, row in enumerate(report.rows):
            if row.resolution == "auto":
                assert window.table.item(r, 0).background().color().name() != expected

    def test_the_columns_match_the_report(self, window):
        process(window)
        headers = [window.table.horizontalHeaderItem(c).text() for c in range(len(COLUMNS))]
        for expected in ("SVC", "TFC Code", "OPR", "靠泊碼頭", "W/B (hr)", "平均侯泊時間"):
            assert expected in headers

    def test_open_questions_surface_a_review_button(self, window):
        report = process(window)
        assert report.issues
        assert not window.review_button.isHidden()
        assert str(len(report.issues)) in window.review_button.text()

    def test_the_report_can_be_saved_even_with_open_questions(self, window, tmp_path):
        import openpyxl

        report = process(window)
        assert report.issues
        assert window.save_button.isEnabled(), "open questions must not block the report"
        from app.generator import write_workbook

        out = write_workbook(report, tmp_path / "out.xlsx")
        assert openpyxl.load_workbook(out).sheetnames == ["CNTAO", "Review", "Audit"]

    def test_a_month_with_nothing_in_it_is_explained_not_crashed(self, window, monkeypatch):
        shown = []
        monkeypatch.setattr(
            "desktop.main.QMessageBox.information", lambda *a, **k: shown.append(a)
        )
        report = process(window, 2019, 1)
        assert report.rows == []
        assert shown, "the user must be told why the table is empty"


@requires_samples
class TestReviewScreen:
    def test_it_shows_a_card_for_every_open_question(self, window):
        report = process(window)
        window._open_review()
        assert window.stack.currentIndex() == 1
        from desktop.review_view import IssueCard

        cards = window.review.scroll.widget().findChildren(IssueCard)
        assert len(cards) == len(report.issues)

    def test_each_card_carries_the_evidence_and_the_reasoning(self, window):
        report = process(window)
        window._open_review()
        from desktop.review_view import IssueCard

        cards = window.review.scroll.widget().findChildren(IssueCard)
        text = " ".join(
            label.text()
            for card in cards
            for label in card.findChildren(type(card.note).__mro__[0])
            if hasattr(label, "text")
        )
        for issue in report.issues[:3]:
            assert issue.question in text or issue.question in _all_text(cards)

    def test_the_recommendation_is_preselected(self, window):
        process(window)
        window._open_review()
        from desktop.review_view import IssueCard

        for card in window.review.scroll.widget().findChildren(IssueCard):
            recommended = card.issue.recommended
            if recommended:
                assert card._choice() == recommended.key

    def test_answering_applies_it_and_the_question_goes_away(self, window, tmp_path):
        report = process(window)
        issue = next(i for i in report.issues if i.kind == "VALUE_DISAGREEMENT")
        window._open_review()

        window.review._save(issue, "calculated", "", None)
        QApplication.processEvents()

        assert issue.id not in {i.id for i in window.report.issues}
        row = next(r for r in window.report.rows if r.voyage_key == issue.voyage_key)
        assert row.resolution == REVIEWED
        assert getattr(row, issue.field).value == issue.option("calculated").value

    def test_a_value_decision_is_an_override_not_a_rule(self, window, tmp_path):
        report = process(window)
        issue = next(i for i in report.issues if i.kind == "VALUE_DISAGREEMENT")
        window._open_review()
        window.review._save(issue, "calculated", "", None)

        saved = DecisionStore.load(tmp_path / "decisions.json")
        assert saved.override_count == 1
        assert saved.rule_count == 0, "a one-off must never become a global rule"

    def test_a_bad_manual_departure_time_is_rejected_not_stored(
        self, window, tmp_path, monkeypatch
    ):
        warned = []
        monkeypatch.setattr(
            "desktop.review_view.QMessageBox.warning", lambda *a, **k: warned.append(a)
        )
        report = process(window)
        issue = next(i for i in report.issues if i.kind == "MISSING_ATD")
        window._open_review()
        window.review._save(issue, "manual", "", "not a date")

        assert warned, "the user must be told the format was wrong"
        assert DecisionStore.load(tmp_path / "decisions.json").override_count == 0


def _all_text(cards) -> str:
    from PySide6.QtWidgets import QLabel, QRadioButton

    parts = []
    for card in cards:
        parts += [w.text() for w in card.findChildren(QLabel)]
        parts += [w.text() for w in card.findChildren(QRadioButton)]
    return " ".join(parts)


class TestSelfTest:
    def test_the_packaged_self_test_passes(self):
        from desktop.selftest import main as selftest

        assert selftest() == 0

    def test_it_is_reachable_through_the_application_entry_point(self, monkeypatch):
        called = []
        monkeypatch.setattr("desktop.selftest.main", lambda: called.append(True) or 0)
        from desktop.main import main

        assert main(["--selftest"]) == 0
        assert called


class TestSelfTestTerminatesDeterministically:
    """A packaged build is launched by a machine, not a person.

    It has no console on Windows, so nothing may depend on stdout existing,
    and nothing may wait for input. Exit code 0 or 1, always.
    """

    def test_it_never_starts_the_event_loop(self, qt_app, monkeypatch):
        from PySide6.QtWidgets import QApplication as RealApp
        from desktop.main import main

        started = []
        monkeypatch.setattr(RealApp, "exec", lambda self: started.append(True) or 0)
        assert main(["--selftest"]) == 0
        assert not started, "selftest must never enter the Qt event loop"

    def test_it_works_with_no_stdout_at_all(self, monkeypatch):
        """A windowed Windows build has sys.stdout set to None."""
        import desktop.selftest as selftest

        monkeypatch.setattr(selftest.sys, "stdout", None)
        assert selftest.main() == 0

    def test_it_carries_a_watchdog(self):
        import desktop.selftest as selftest

        assert selftest.WATCHDOG_SECONDS <= 300
        timer = selftest.start_watchdog(60)
        try:
            assert timer.daemon, "the watchdog must not keep the process alive"
        finally:
            timer.cancel()

    def test_it_leaves_a_readable_result_even_without_a_console(self, tmp_path):
        import desktop.selftest as selftest

        selftest.TRANSCRIPT.clear()
        selftest.say("hello")
        written = selftest.write_transcript(tmp_path)
        assert written is not None
        assert "hello" in written.read_text(encoding="utf-8")

    def test_writing_the_result_somewhere_unwritable_is_survivable(self, tmp_path):
        import desktop.selftest as selftest

        assert selftest.write_transcript(tmp_path / "nope" / "deeper") is None
