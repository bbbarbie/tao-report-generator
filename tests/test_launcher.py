"""The launcher's moving parts, tested where they can be tested.

The batch and VBScript wrappers cannot run on this machine. Everything they
depend on that *is* testable lives in ``launcher/open_when_ready.py``, and the
scripts themselves are checked for the mistakes that would break them.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "launcher"))
import open_when_ready as opener  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
START_BAT = REPO_ROOT / "launcher" / "start.bat"
VBS = REPO_ROOT / "TAO Report Generator.vbs"
RUN_COMMAND = REPO_ROOT / "run.command"


@pytest.fixture
def listening_port():
    """A real socket, so the probe is tested against a real listener."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    yield server.getsockname()[1]
    server.close()


@pytest.fixture
def closed_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class TestPortProbe:
    def test_an_open_port_is_detected(self, listening_port):
        assert opener.is_listening(listening_port)

    def test_a_closed_port_is_not(self, closed_port):
        assert not opener.is_listening(closed_port)

    def test_waiting_returns_at_once_when_already_up(self, listening_port):
        calls = []
        assert opener.wait_for_port(
            listening_port, timeout=5, sleep=calls.append
        )
        assert not calls, "should not have slept at all"

    def test_waiting_gives_up_and_says_so(self, closed_port):
        clock = iter([0.0, 1.0, 2.0, 99.0])
        assert not opener.wait_for_port(
            closed_port, timeout=5, sleep=lambda _: None, now=lambda: next(clock)
        )

    def test_waiting_succeeds_when_the_server_arrives_late(self, closed_port):
        """The real case: streamlit takes a few seconds to bind."""
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        started = threading.Event()

        def bind_later(_):
            if not started.is_set():
                server.bind(("127.0.0.1", closed_port))
                server.listen(1)
                started.set()

        try:
            assert opener.wait_for_port(closed_port, timeout=5, sleep=bind_later)
        finally:
            server.close()


class TestBrowserHandoff:
    def test_the_browser_is_opened_on_the_right_url(self, listening_port, monkeypatch):
        opened = []
        monkeypatch.setattr(opener.webbrowser, "open", opened.append)
        assert opener.main([str(listening_port), "5"]) == 0
        assert opened == [f"http://127.0.0.1:{listening_port}"]

    def test_the_browser_is_not_opened_on_a_dead_server(self, closed_port, monkeypatch):
        opened = []
        monkeypatch.setattr(opener.webbrowser, "open", opened.append)
        monkeypatch.setattr(opener, "report_failure", lambda *a, **k: None)
        monkeypatch.setattr(opener.time, "sleep", lambda _: None)
        assert opener.main([str(closed_port), "0.2"]) == 1
        assert not opened

    def test_a_failure_is_reported_not_swallowed(self, closed_port, monkeypatch, capsys):
        monkeypatch.setattr(opener.time, "sleep", lambda _: None)
        opener.main([str(closed_port), "0.2"])
        # Diagnostics in English for whoever supports the user...
        assert "did not finish starting" in capsys.readouterr().err

    def test_what_the_user_actually_sees_is_in_chinese(self, closed_port, monkeypatch):
        """...but the message box itself must be readable by the end user."""
        shown = []
        monkeypatch.setattr(opener, "report_failure", lambda m, **k: shown.append(m))
        monkeypatch.setattr(opener.time, "sleep", lambda _: None)
        opener.main([str(closed_port), "0.2"])
        assert shown and any("\u4e00" <= ch <= "\u9fff" for ch in shown[0])
        assert "TAO Report Generator" in shown[0], "keep the app name recognisable"

    def test_every_launcher_agrees_on_the_port(self):
        """The server, the browser hand-off and the default must not drift apart."""
        bat = START_BAT.read_text()
        assert f'set "PORT={opener.DEFAULT_PORT}"' in bat
        assert "--server.port=%PORT%" in bat
        assert "open_when_ready.py %PORT%" in bat

        run = RUN_COMMAND.read_text()
        assert f"PORT={opener.DEFAULT_PORT}" in run
        assert '--server.port="$PORT"' in run


class TestScriptContents:
    """Checks for the specific mistakes that would break these on Windows."""

    @pytest.fixture
    def bat(self):
        return START_BAT.read_text()

    def test_the_server_runs_in_the_foreground(self, bat):
        """`start /b` would tie the server to a console the launcher then closes."""
        server_lines = [
            line for line in bat.splitlines()
            if "streamlit.exe" in line and "run ui.py" in line
        ]
        assert server_lines, "no line starts the server"
        for line in server_lines:
            assert not line.strip().lower().startswith("start "), (
                "the server must not be started with `start`, or it dies when "
                "the launcher's console closes"
            )

    def test_the_server_is_bound_to_loopback_only(self, bat):
        assert "--server.address=127.0.0.1" in bat
        assert "0.0.0.0" not in bat

    def test_usage_statistics_are_off(self, bat):
        assert "--browser.gatherUsageStats=false" in bat

    def test_no_reliance_on_the_timeout_command(self, bat):
        """`timeout` fails without console input; the wait is done in Python."""
        assert "timeout /t" not in bat

    def test_every_referenced_file_exists(self, bat):
        for name in ("open_when_ready.py",):
            assert name in bat
            assert (REPO_ROOT / "launcher" / name).exists()

    def test_no_dangling_references_to_files_that_are_never_written(self, bat):
        assert "startup.log" not in bat, "referenced a log the launcher never creates"

    def test_every_message_the_user_sees_is_in_chinese(self, bat):
        """The end user is a non-technical Chinese speaker."""
        messages = [
            line.split('"', 1)[1].rsplit('"', 1)[0]
            for line in bat.splitlines()
            if line.strip().startswith("call :say ")
        ]
        assert len(messages) >= 3, "expected messages for setup, no-Python and failure"
        for message in messages:
            assert any("\u4e00" <= ch <= "\u9fff" for ch in message), message

    def test_the_missing_python_message_says_exactly_what_to_install(self, bat):
        assert "python.org" in bat
        assert "Add python.exe to PATH" in bat, "the step everyone forgets"
        assert "FIRST_TIME_SETUP" in bat, "point at the written guide"

    def test_developer_jargon_is_kept_out_of_the_user_messages(self, bat):
        messages = " ".join(
            line for line in bat.splitlines() if line.strip().startswith("call :say ")
        )
        for word in ("Streamlit", "virtual environment", "venv", "pip", "Git", "repository"):
            assert word.lower() not in messages.lower(), f"{word} means nothing to the user"

    def test_the_vbs_launches_the_batch_hidden_and_does_not_wait(self):
        text = VBS.read_text()
        assert "start.bat" in text
        assert ", 0," in text, "window style 0 keeps the console hidden"
        assert "False" in text, "must not block on the server"

    def test_the_stop_script_targets_this_installation(self):
        stop = REPO_ROOT / "Stop TAO Report Generator.vbs"
        assert stop.exists(), "a hidden server needs a way to be stopped"
        assert "stop.bat" in stop.read_text()


class TestFirstTimeSetupGuide:
    """The guide is the fallback when the launcher's own messages are not enough."""

    @pytest.fixture
    def guide(self):
        path = REPO_ROOT / "FIRST_TIME_SETUP.md"
        assert path.exists(), "the non-technical user needs a written guide"
        return path.read_text(encoding="utf-8")

    def test_it_is_written_in_chinese(self, guide):
        chinese = sum(1 for ch in guide if "一" <= ch <= "鿿")
        assert chinese > 400, "the guide must be readable by the person using it"

    def test_it_covers_the_step_everyone_forgets(self, guide):
        assert "Add python.exe to PATH" in guide

    def test_it_names_the_things_the_user_double_clicks(self, guide):
        assert "TAO Report Generator" in guide
        assert "Stop TAO Report Generator" in guide

    def test_it_warns_that_first_run_is_slow(self, guide):
        assert "3 到 5 分鐘" in guide

    def test_it_says_the_data_stays_on_the_machine(self, guide):
        assert "不會上傳" in guide

    def test_developer_terminology_is_kept_out(self, guide):
        """Everything above the note for whoever installs it must be jargon-free."""
        user_section = guide.split("## 給協助安裝的人")[0]
        for word in ("Streamlit", "Git", "GitHub", "pip", "venv", "virtual environment",
                     "repository", "terminal", "command line", "PowerShell"):
            assert word.lower() not in user_section.lower(), f"{word} means nothing to the user"

    def test_the_launcher_points_at_this_guide_by_name(self):
        assert "FIRST_TIME_SETUP" in START_BAT.read_text()
