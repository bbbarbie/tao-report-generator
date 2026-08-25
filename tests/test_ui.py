"""The local UI must run end to end without a browser in the loop."""

from __future__ import annotations

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.decisions import DecisionStore  # noqa: E402
from tests.conftest import DAILY_DIR, REPO_ROOT, requires_samples  # noqa: E402


@pytest.fixture
def app(tmp_path):
    at = AppTest.from_file(str(REPO_ROOT / "ui.py"), default_timeout=180)
    at.run()
    # Decisions made in a test go to a scratch file, never to the user's own
    # config/decisions.json.
    at.session_state["store"] = DecisionStore(path=tmp_path / "decisions.json")
    return at


def processed(at):
    """Run the Generate screen against the sample folder for July 2026."""
    at.radio(key="source").set_value("Use a folder on this computer").run()
    at.text_input(key="folder").set_value(str(DAILY_DIR)).run()
    at.number_input(key="year").set_value(2026).run()
    at.selectbox(key="month").set_value(7).run()
    at.button(key="process").click().run()
    return at


def text_of(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [w.value for w in at.warning] + [i.value for i in at.info]
    parts += [s.value for s in at.success]
    return "\n".join(str(p) for p in parts)


class TestNavigation:
    def test_the_page_loads_on_the_generate_screen(self, app):
        assert not app.exception
        assert "TAO Monthly Report Generator" in app.title[0].value

    def test_all_three_screens_render(self, app):
        for screen in ("Needs Review", "Saved decisions", "Generate"):
            app.radio(key="page").set_value(screen).run()
            assert not app.exception, f"{screen} raised"

    def test_review_before_processing_explains_itself(self, app):
        app.radio(key="page").set_value("Needs Review").run()
        assert not app.exception
        assert any("Generate screen first" in str(i.value) for i in app.info)


class TestGenerate:
    @requires_samples
    def test_processing_reports_the_three_row_states(self, app):
        processed(app)
        assert not app.exception
        labels = {m.label: m.value for m in app.metric}
        assert labels["Voyages"] == "27"
        assert (
            int(labels["Automatic"])
            + int(labels["Reviewed"])
            + int(labels["Unresolved"])
            == 27
        )

    @requires_samples
    def test_open_questions_are_surfaced_without_blocking_the_report(self, app):
        processed(app)
        report = app.session_state["report"]
        assert report.issues
        assert any("need review" in str(w.value) for w in app.warning)
        # The workbook is still offered — one open question does not stop the month.
        assert any("Download TAO Compare" in b.label for b in app.download_button)

    def test_a_bad_folder_is_reported_rather_than_crashing(self, app):
        app.radio(key="source").set_value("Use a folder on this computer").run()
        app.text_input(key="folder").set_value("/definitely/not/a/folder").run()
        assert not app.exception
        assert app.error

    def test_process_is_disabled_until_files_are_chosen(self, app):
        app.radio(key="source").set_value("Upload files").run()
        assert app.button(key="process").disabled

    def test_the_month_defaults_to_the_month_just_gone(self, app):
        from datetime import date, timedelta

        previous = date(date.today().year, date.today().month, 1) - timedelta(days=1)
        assert app.number_input(key="year").value == previous.year
        assert app.selectbox(key="month").value == previous.month


@requires_samples
class TestReviewScreen:
    def test_every_open_question_is_shown_with_its_evidence(self, app):
        processed(app)
        report = app.session_state["report"]
        app.radio(key="page").set_value("Needs Review").run()
        assert not app.exception

        body = text_of(app)
        for issue in report.issues:
            assert issue.question in body

    def test_a_recommendation_is_shown_with_its_reasoning(self, app):
        processed(app)
        report = app.session_state["report"]
        app.radio(key="page").set_value("Needs Review").run()
        body = text_of(app)
        recommended = [i for i in report.issues if i.recommended]
        assert recommended
        for issue in recommended[:3]:
            assert issue.recommended.label in body
            assert issue.why_recommended[:40] in body

    def test_rendering_the_screen_changes_nothing(self, app):
        processed(app)
        report = app.session_state["report"]
        before = {r.voyage_key: r.waiting.value for r in report.rows}
        app.radio(key="page").set_value("Needs Review").run()
        after = {
            r.voyage_key: r.waiting.value for r in app.session_state["report"].rows
        }
        assert before == after
        assert app.session_state["store"].override_count == 0


@requires_samples
class TestDecisionRoundTrip:
    def _first_issue(self, app, kind):
        report = app.session_state["report"]
        return next((i for i in report.issues if i.kind == kind), None)

    def test_answering_a_question_applies_it_and_removes_it(self, app):
        processed(app)
        issue = self._first_issue(app, "VALUE_DISAGREEMENT")
        assert issue is not None
        app.radio(key="page").set_value("Needs Review").run()

        app.radio(key=f"choice-{issue.id}").set_value("calculated").run()
        app.button(key=f"FormSubmitter:issue-{issue.id}-Save decision").click().run()
        assert not app.exception

        report = app.session_state["report"]
        row = next(r for r in report.rows if r.voyage_key == issue.voyage_key)
        assert row.resolution == "reviewed"
        assert getattr(row, issue.field).value == issue.option("calculated").value
        assert issue.id not in {i.id for i in report.issues}

    def test_a_value_decision_is_an_override_not_a_rule(self, app):
        processed(app)
        issue = self._first_issue(app, "VALUE_DISAGREEMENT")
        app.radio(key="page").set_value("Needs Review").run()
        app.button(key=f"FormSubmitter:issue-{issue.id}-Save decision").click().run()

        store = app.session_state["store"]
        assert store.override_count == 1
        assert store.rule_count == 0, "a one-off must never become a global rule"

    def test_a_decision_survives_a_reload_of_the_store(self, app, tmp_path):
        processed(app)
        issue = self._first_issue(app, "VALUE_DISAGREEMENT")
        app.radio(key="page").set_value("Needs Review").run()
        app.button(key=f"FormSubmitter:issue-{issue.id}-Save decision").click().run()

        reloaded = DecisionStore.load(tmp_path / "decisions.json")
        assert reloaded.override_count == 1
        assert issue.field in reloaded.overrides_for("202607", issue.voyage_key)

    def test_the_saved_decisions_screen_lists_it_and_can_undo_it(self, app):
        processed(app)
        issue = self._first_issue(app, "VALUE_DISAGREEMENT")
        app.radio(key="page").set_value("Needs Review").run()
        app.button(key=f"FormSubmitter:issue-{issue.id}-Save decision").click().run()

        app.radio(key="page").set_value("Saved decisions").run()
        assert not app.exception

        undo = [b for b in app.button if b.key.startswith("forget-202607-")]
        assert undo
        undo[0].click().run()
        assert app.session_state["store"].override_count == 0
        # The question comes back, because it was never really answered.
        assert issue.id in {i.id for i in app.session_state["report"].issues}
