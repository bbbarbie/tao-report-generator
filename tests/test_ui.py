"""The local UI must run end to end without a browser in the loop."""

from __future__ import annotations

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.conftest import DAILY_DIR, REPO_ROOT, requires_samples  # noqa: E402


@pytest.fixture
def app():
    at = AppTest.from_file(str(REPO_ROOT / "ui.py"), default_timeout=120)
    at.run()
    return at


def test_the_page_loads(app):
    assert not app.exception
    assert "TAO Monthly Report Generator" in app.title[0].value


@requires_samples
def test_generating_a_report_from_a_folder(app):
    app.radio[0].set_value("Use a folder on this computer").run()
    app.text_input[0].set_value(str(DAILY_DIR)).run()
    assert not app.exception

    # Set the month explicitly rather than relying on today's date.
    app.number_input[0].set_value(2026).run()
    app.selectbox[0].set_value(7).run()
    app.button[0].click().run()
    assert not app.exception

    labels = {m.label: m.value for m in app.metric}
    assert labels["Voyages in report"] == "27"
    assert int(labels["Complete"]) + int(labels["Need review"]) == 27


def test_a_bad_folder_is_reported_rather_than_crashing(app):
    app.radio[0].set_value("Use a folder on this computer").run()
    app.text_input[0].set_value("/definitely/not/a/folder").run()
    assert not app.exception
    assert app.error


def test_generate_is_disabled_until_files_are_chosen(app):
    app.radio[0].set_value("Upload files").run()
    assert app.button[0].disabled


def test_the_month_defaults_to_the_month_just_gone(app):
    """Reports are written after a month closes."""
    from datetime import date, timedelta

    previous = date(date.today().year, date.today().month, 1) - timedelta(days=1)
    assert app.number_input[0].value == previous.year
    assert app.selectbox[0].value == previous.month
