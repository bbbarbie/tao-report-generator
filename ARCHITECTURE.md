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
| Remembered Daily Reports folder | Not built — the folder is typed each time |
| Saved OPR mappings | Built (`config/operator_mapping.json` + learned rules) |
| One-off overrides, kept apart from reusable rules | Built (`app/decisions.py`) |
| Report history | Not built — output is overwritten per month |
| Audit trail | Built (Audit sheet, per-value provenance) |
| Anomaly detection across Daily snapshots | Partly built (`CONFLICTING_SNAPSHOTS`, window integrity) |
| All corporate data local | Built, and enforced: server binds to `127.0.0.1`, nothing is uploaded |

### Current state: an interim interface

The interface today is a local Streamlit app, launched by a double-click
wrapper that hides the console. It is deliberately **temporary** — it exists so
the calculation engine could be validated against real data before any effort
went into packaging.

It still falls short of the target in three ways: it needs Python installed, it
opens in a browser, and the first run downloads libraries. The launcher hides
as much of that as a script can, but it cannot remove it.

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

### Sequence when the time comes

1. `app/` is already the engine. No changes expected.
2. Add `app/settings.py` — the remembered Daily folder, the last month used,
   and the output location. Same JSON-file pattern as `decisions.py`.
3. Add `app/history.py` — write each generated report to a dated folder rather
   than overwriting, and keep an index. The audit trail already carries the
   provenance; this gives it somewhere to live.
4. Build `desktop/` with PySide6: three views mirroring the current three
   screens, over the same engine calls.
5. Package with PyInstaller. Bundle a `.ico`, sign if the company has a
   certificate — unsigned executables draw SmartScreen warnings, which is
   exactly the sort of thing that stops a non-technical user.
6. Retire `ui.py`, `ui_pages/` and the launcher scripts. `app/`, `config/` and
   `tests/` are untouched by the whole exercise.

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

ui.py, ui_pages/        interim interface — replaceable
launcher/               interim Windows launcher — replaceable
config/                 mappings, scope, saved decisions
tools/                  investigation and validation scripts
tests/                  including test_architecture.py, which enforces the above
```
