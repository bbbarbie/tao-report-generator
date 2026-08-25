"""Wait for the local server to answer, then open it in the browser.

This runs alongside the server rather than after it, so the launcher script
can keep the server in the foreground. On Windows that matters: a background
child started with ``start /b`` shares its parent's console, and when the
launcher exits the console is destroyed and the server goes with it.

Kept in Python rather than in the batch file because batch has no reliable
sleep without a console, and because this way it can be tested.
"""

from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser

DEFAULT_PORT = 8501
DEFAULT_TIMEOUT = 180.0
POLL_SECONDS = 0.5


def is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def wait_for_port(
    port: int,
    timeout: float = DEFAULT_TIMEOUT,
    host: str = "127.0.0.1",
    sleep=time.sleep,
    now=time.monotonic,
) -> bool:
    """Poll until the port answers. True if it came up inside the timeout."""
    deadline = now() + timeout
    while now() < deadline:
        if is_listening(port, host):
            return True
        sleep(POLL_SECONDS)
    return is_listening(port, host)


# Shown to the end user, who reads Chinese and is not technical. The English
# line beside it is for whoever supports them.
STARTUP_FAILED = (
    "程式沒有順利打開。\n\n"
    "請照著做：\n"
    "1. 等 10 秒鐘\n"
    "2. 重新點一下「TAO Report Generator」\n\n"
    "如果試了兩次還是不行，請把這個訊息拍照傳給您的家人協助。"
)


def someone_can_dismiss_a_dialog() -> bool:
    """Is there a person at this machine to close a message box?

    A message box is modal: it blocks until somebody clicks OK. That is what
    makes it the right way to reach a user whose application has no console,
    and exactly what makes it a trap anywhere unattended — on a build machine
    it simply waits forever.

    Kept deliberately conservative: anything that looks automated gets no
    dialog. A missed message on a build server costs nothing; a blocked one
    costs the whole job.
    """
    if sys.platform != "win32":
        return False
    if os.environ.get("TAO_NO_DIALOGS"):
        return False
    # CI, GITHUB_ACTIONS and TF_BUILD are set by the common build services.
    return not any(
        os.environ.get(name) for name in ("CI", "GITHUB_ACTIONS", "TF_BUILD")
    )


def show_dialog(message: str) -> None:  # pragma: no cover - Windows only
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, message, "TAO 報表產生器", 0x10)


def report_failure(message: str, detail: str = "") -> None:
    """Tell the user, even when there is no console to print to.

    The Windows launcher deliberately runs without a visible window, so a
    failure that only reached stderr would be invisible to the person who
    needs to know about it. Unattended machines get the text and no dialog.
    """
    print(detail or message, file=sys.stderr)
    if someone_can_dismiss_a_dialog():
        try:
            show_dialog(message)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    port = int(args[0]) if args else DEFAULT_PORT
    timeout = float(args[1]) if len(args) > 1 else DEFAULT_TIMEOUT

    url = f"http://127.0.0.1:{port}"
    if not wait_for_port(port, timeout):
        report_failure(
            STARTUP_FAILED,
            detail=(
                "The TAO Report Generator did not finish starting: nothing "
                f"answered on {url} after {timeout:.0f} seconds."
            ),
        )
        return 1

    webbrowser.open(url)
    print(f"opened {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
