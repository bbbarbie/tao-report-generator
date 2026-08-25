"""Check a packaged build before it is handed to anyone.

Run against the folder PyInstaller produced:

    python packaging/verify_build.py "dist/TAO Report Generator"

Three things are checked, in increasing order of usefulness: that the
executable is there, that the folder contains what it needs, and that the
engine inside it actually runs. The last one is the point — an executable that
exists but cannot open a workbook is worse than no build at all.

The user interface is deliberately *not* driven here. Automating a real window
reliably is a separate problem, and reporting a pass we did not earn would be
worse than reporting nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "TAO Report Generator"
# The workflow only ever builds on Windows; the other branch exists so the
# verifier can be exercised on the machine it was written on.
EXE_NAME = f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME
# The self-test does a few seconds of work and carries its own 120s watchdog.
# This is the outer bound: if it is ever hit, something is wrong with the build
# rather than slow, and the job should say so quickly.
SELFTEST_TIMEOUT = int(os.environ.get("TAO_SELFTEST_TIMEOUT", "180"))
RESULT_FILE = "selftest-result.txt"

# Things whose absence would break the application for the end user. Searched
# for by name, because PyInstaller decides where bundled data lands.
REQUIRED_FILES = ["operator_mapping.json", "report_scope.json", "使用說明.txt"]

# Things that must never reach a machine outside the company.
FORBIDDEN_PATTERNS = [
    ("*.xlsx", "company workbooks"),
    ("decisions.json", "saved decisions"),
    ("settings.json", "local settings"),
    ("test_*.py", "test files"),
    ("*.git*", "version-control metadata"),
]

failures: list[str] = []
notes: list[str] = []


def check(condition: bool, passed: str, failed: str) -> bool:
    if condition:
        print(f"  ok    {passed}")
        return True
    print(f"  FAIL  {failed}")
    failures.append(failed)
    return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    folder = Path(args[0] if args else "dist/TAO Report Generator").resolve()

    print(f"Verifying {folder}\n")

    if not check(folder.is_dir(), "build folder exists", f"no build folder at {folder}"):
        return 1

    exe = folder / EXE_NAME
    if not check(exe.is_file(), f"{EXE_NAME} exists", f"{EXE_NAME} was not produced"):
        return 1
    check(exe.stat().st_size > 100_000, f"executable is {exe.stat().st_size:,} bytes",
          f"executable is suspiciously small ({exe.stat().st_size} bytes)")

    everything = list(folder.rglob("*"))
    files = [p for p in everything if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f"  ok    {len(files)} files, {total / 1_000_000:.0f} MB")

    by_name = {p.name for p in files}
    for name in REQUIRED_FILES:
        check(
            name in by_name,
            f"bundled {name}",
            f"{name} is missing from the build",
        )

    internal = folder / "_internal"
    check(
        internal.is_dir() or len(files) > 20,
        "runtime files are present",
        "the folder holds an executable and nothing else",
    )

    for pattern, description in FORBIDDEN_PATTERNS:
        found = [p for p in files if p.match(pattern)]
        check(
            not found,
            f"no {description} in the build",
            f"{description} was bundled: {[str(p.relative_to(folder)) for p in found[:5]]}",
        )

    # The real test: run the engine inside the packaged environment.
    print(f"\n  running {EXE_NAME} --selftest  (limit {SELFTEST_TIMEOUT}s)\n")
    transcript = folder / RESULT_FILE
    transcript.unlink(missing_ok=True)

    started = time.monotonic()
    try:
        result = subprocess.run(
            [str(exe), "--selftest"],
            capture_output=True,
            text=True,
            timeout=SELFTEST_TIMEOUT,
            cwd=folder,
        )
    except subprocess.TimeoutExpired:
        # A windowed build that stalls is almost always waiting on a dialog.
        failures.append(f"the self-test did not finish within {SELFTEST_TIMEOUT}s")
        print(f"  FAIL  the self-test did not finish within {SELFTEST_TIMEOUT}s")
        print("        a windowed build that hangs is usually waiting on a dialog")
    except OSError as exc:
        failures.append(f"the executable would not run: {exc}")
        print(f"  FAIL  the executable would not run: {exc}")
    else:
        elapsed = time.monotonic() - started
        # A windowed Windows build has no console, so stdout is normally empty
        # and the transcript file is where the detail actually is.
        output = result.stdout or ""
        if not output.strip() and transcript.exists():
            output = transcript.read_text(encoding="utf-8", errors="replace")
        for line in output.splitlines():
            print(f"    | {line}")
        if (result.stderr or "").strip():
            for line in result.stderr.splitlines():
                print(f"    ! {line}")

        check(
            result.returncode == 0,
            f"the packaged engine parsed a Daily report and wrote a workbook "
            f"({elapsed:.1f}s)",
            f"the packaged engine failed (exit code {result.returncode})",
        )
        check(
            "engine checks passed" in output,
            "the self-test reported its results",
            "the self-test produced no readable result — neither stdout nor "
            f"{RESULT_FILE}",
        )

    # Not shipped to the user: it is a build artefact, not part of the product.
    transcript.unlink(missing_ok=True)

    notes.append(
        "the window itself was not opened — driving a real GUI in CI is not "
        "reliable, so it is not claimed as tested"
    )

    print("\n" + "=" * 64)
    for note in notes:
        print(f"note: {note}")
    if failures:
        print(f"\nBUILD REJECTED — {len(failures)} problem(s):")
        for failure in failures:
            print(f"  - {failure}")
        print("=" * 64)
        return 1
    print("\nBUILD OK — safe to hand over.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
