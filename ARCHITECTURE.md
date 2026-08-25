# Architecture and roadmap

Where this is heading, and the one structural rule that gets it there.

## Production target

A **standalone Windows desktop application** for a non-technical WAN HAI
employee. Not a permanently deployed web app, and not a hosted service.

The finished experience requires none of: a Python installation, a terminal, a
browser, Git, any knowledge of how it was built, or any cloud service. The
employee opens an application, and all corporate data stays on their machine.

The intended monthly workflow:

```
Open TAO Report Generator
  → select month
  → the Daily files for that month are found automatically
  → Process
  → review only the items the engine is unsure about
  → Generate TAO Compare.xlsx
```

Everything before "select month" happens once, at setup.

### What it has to carry over

| Capability | State today |
| --- | --- |
| Remembered Daily Reports folder | Built (`app/settings.py`) |
| Saved OPR mappings | Built (`config/operator_mapping.json` + learned rules) |
| One-off overrides, kept apart from reusable rules | Built (`app/decisions.py`) |
| Report history | **Not built** — the last outstanding item |
| Audit trail | Built (Audit sheet, per-value provenance) |
| Anomaly detection across Daily snapshots | Partly built (`CONFLICTING_SNAPSHOTS`, window integrity) |
| All corporate data local | Built. The desktop app makes no network call at all; the dev server binds to `127.0.0.1` |

### Current state

The desktop application exists (`desktop/`) and is built and verified by
`.github/workflows/build-windows.yml` on every manual trigger and version tag.
See [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) for how to produce a release.

Still to do from the list above: report history. The remembered Daily folder
landed with `app/settings.py`.

### The interim web interface

The Streamlit app is now **development only**. It exists because it let the
engine be validated against real data long before any effort went into
packaging, and it remains the quickest way to try a change. It is not what the
employee runs.

## The rule that makes the swap cheap

**Nothing under `app/` may know what the user interface is.**

The engine imports `openpyxl` and the standard library, and nothing else. It has
no notion of Streamlit, of a browser, or of a window. Every screen is a thin
layer over `build_report()`, and every decision the user makes is a plain
dataclass written to JSON.

This is enforced, not merely intended — `tests/test_architecture.py` parses every
module under `app/` and fails the build if any of them imports a UI toolkit,
imports `ui_pages`, or so much as mentions Streamlit in a string. A further test
imports the whole pipeline in a bare Python process and asserts `streamlit` never
enters `sys.modules`.

So replacing the interface means writing new views against the same three calls:

```python
report = build_report(files, year, month, mapping, scope, store)   # app/report.py
store.record_rule(...) / store.record_override(...)                # app/decisions.py
write_workbook(report, path)                                       # app/generator.py
```

No business logic moves.

## Recommended packaging approach

**PySide6 + PyInstaller**, as proposed. Having built the interim version, the
reasoning holds up:

- PySide6 gives a native window, a real folder picker and a proper table widget —
  the three things the browser version fakes.
- PyInstaller with `--onedir` produces a folder the employee can be handed
  directly. `--onefile` is tempting but unpacks to a temp directory on every
  launch, which is slow and trips corporate antivirus more often.
- LGPL licensing is fine for internal use.

Two alternatives were considered and rejected:

- **Keep Streamlit, wrap it in a webview.** Cheapest, but still ships a web
  server and a browser engine to avoid writing a window, and the console-hiding
  problems stay.
- **Tkinter.** In the standard library, so no packaging risk, but the table
  widget is poor and this report is a table.

### Sequence

1. ~~`app/` is already the engine.~~ Unchanged, as expected.
2. ~~`app/settings.py` — remembered Daily folder, last month, output location.~~ Done.
3. `app/history.py` — write each generated report to a dated folder rather than
   overwriting, and keep an index. **Still to do.**
4. ~~Build `desktop/` with PySide6 over the same engine calls.~~ Done.
5. ~~Package with PyInstaller.~~ Done — `packaging/tao_report_generator.spec`,
   built by GitHub Actions. Still worth adding: a `.ico`, and code signing if
   the company has a certificate. Unsigned executables draw a SmartScreen
   warning, which is exactly the sort of thing that stops a non-technical user.
6. Retire `ui.py`, `ui_pages/` and the launcher scripts once the desktop app has
   been used for a real month. `app/`, `config/` and `tests/` are untouched.

### Where files live in a packaged build

`app/paths.py` keeps two directories apart, which matters once the application
is installed rather than checked out:

* the **seed** operator list and report scope ship inside the bundle and are
  replaced by every new version;
* the user's **decisions and settings** go to `%APPDATA%\TAO Report Generator\`,
  so upgrading the application never discards them, and so nothing is written
  into a folder the user may not have permission for.

In a source checkout both resolve to `config/`, leaving development unchanged.

## Before any of that

Correctness first. Two things are still open, both recorded in
`IMPLEMENTATION_STATUS.md`:

1. **Confirm the service-scope rule** with whoever writes the report. It is the
   one rule fitted to a single month's answer that could plausibly be wrong.
2. **Widen the blind validation.** `tools/blind_validation.py` currently holds
   out 42 figures and reproduces all of them, against 96.6% on the fitted
   period — good evidence of no overfitting, but a small sample. Each new month
   of Daily files makes it stronger. A second hand-made TAO Compare would make
   it conclusive.

## Module map

```
app/                    the engine — no interface dependencies, ever
  parser.py             Daily workbook -> records
  normalization.py      shipping date formats, terminals, rounding
  models.py             VoyageSnapshot / VoyageHistory
  voyage_history.py     snapshots -> voyages
  selection.py          month membership and report scope
  calculations.py       the business rules
  operators.py          vessel -> OPR
  review.py             uncertainty -> answerable questions
  decisions.py          saved rules and one-off overrides
  report.py             the pipeline
  generator.py          writes the workbook
  validation.py         compares against a known-good workbook (tests only)
  cli.py                command line entry point

  settings.py           remembered folder, month and output location
  paths.py              where files live in a checkout vs a packaged build

desktop/                the product — PySide6 views over the engine
  main.py               window, table, settings
  review_view.py        the Needs Review screen
  selftest.py           proves a packaged build works, run by CI

packaging/              PyInstaller spec, end-user guide, build verifier
.github/workflows/      build-windows.yml — the release pipeline

ui.py, ui_pages/        development web interface only
launcher/               launcher for the development interface
config/                 mappings, scope, saved decisions
tools/                  investigation and validation scripts
tests/                  including test_architecture.py, which enforces the above
```
