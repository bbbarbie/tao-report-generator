# Implementation status

Written so another developer can pick this up cold. Last updated after the
July 2026 regression reached 24/27.

> **Production target: a standalone Windows desktop application** (PySide6 +
> PyInstaller), not a deployed web app. The Streamlit interface is interim. See
> [ARCHITECTURE.md](ARCHITECTURE.md). The engine under `app/` is already free of
> any interface dependency, and `tests/test_architecture.py` fails the build if
> that ever stops being true.

## Where things stand

| Area | State |
| --- | --- |
| Daily workbook parser | Done. Structure-driven, no fixed rows or columns. 23/23 sample files parse. |
| Date normalisation (`dd/HHMM`) | Done, including month/year recovery and the ambiguous cases. |
| Voyage histories across snapshots | Done. 1013 snapshots → 128 voyages, with change tracking. |
| Voyage identity / TFC retypes | Done. Conservative merge, ambiguity logged. |
| Month membership (by ATD) | Done. |
| Report scope (which services) | Done, **rule confidence moderate** — see below. |
| Operator mapping | Done, editable, resolves all July vessels. |
| Delay / waiting calculations | Done and validated against 260 Daily-supplied figures. |
| SVC + OPR average waiting | Done, verified on all 18 July groups. |
| Excel generation | Done. Layout, fonts, number formats and widths match the original. |
| Review output | Done — `review.csv` and a `Review` sheet. |
| Audit trail | Done — an `Audit` sheet with per-value provenance. |
| Ground-truth validation | Done — machine-readable JSON and a readable summary. |
| Blind validation | Done — held-out month reproduces 42/42 against 96.6% on the fitted period. |
| Engine / interface separation | Done and enforced by test. |
| End-user setup guide (Chinese) | Done — `FIRST_TIME_SETUP.md`, plus Chinese messages in the launcher. |
| Standalone desktop app | Built — `desktop/`, PySide6, 22 tests driving it offscreen. |
| Windows packaging | Built — PyInstaller `--onedir`, GitHub Actions, verified before upload. See [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md). |
| Report history | Not built. The one remaining item from the production target. |
| Tests | 373 tests, all passing. Any single test is capped at 90s by `pytest-timeout`. |
| Review / decision system | Done — questions with candidates, recommendations and reasons; answers saved as rules or one-off overrides. |
| Local UI | Done — three screens: Generate, Needs Review, Saved decisions. |
| Windows launcher | Done — hidden console, browser opens itself, idempotent, with a Stop script. The fragile parts live in `launcher/open_when_ready.py` and are unit-tested; the batch is checked by assertion. **The .bat/.vbs themselves are untested on Windows** (built on macOS). |
| Packaged executable | Not done. The launcher still needs Python installed. See "Next steps". |

## Verified result

```
27 ground-truth rows, 27 generated rows
24 reproduced
 1 ground truth inconsistent   (S033362 — a typo in the manual workbook; ours is right)
 2 calculation mismatch        (E044JKPU, S564JCAG — unexplained by the source files)
```

Reproduce it with:

```bash
python -m app.cli --daily samples/daily --month 2026-07 \
    --validate-against "samples/ground_truth/TAO Compare 202607.xlsx"
```

## Blind validation

Every rule was derived from July 2026, the only month with a hand-made report to
check against, so a good July score is partly self-confirming.
`tools/blind_validation.py` holds out everything that departed after July and
re-tests the rules against the Daily's own printed figures — numbers that played
no part in deriving anything.

```
HELD OUT (departed August 2026 or later)
  Arr Delay = ATA - window start                14/14  (100.0%)
  Dep Delay = ATD - window end                  14/14  (100.0%)
  W/B = max(0, ATB - max(ATA, window start))    14/14  (100.0%)

VERDICT: 42/42 held out, 113/117 on the fitted period, gap -3.4 points
```

The rules do slightly *better* on data they never saw, which is the opposite of
what overfitting looks like. Six figures are set aside as rows where the monthly
report is *meant* to differ from the Daily — a corrected window, or a ship that
arrived before its slot opened — and the classifier for those is itself tested,
so it cannot be used to excuse an arbitrary failure.

Caveat: 42 held-out figures is enough to rule out gross overfitting, not enough
to be a precise estimate. It strengthens with every month of Daily files.

## The one thing to confirm with the report's author

**Service scope** (`app/selection.py`, `config/report_scope.json`). The report
covers 8 of the 14 Qingdao services. Two derived rules reproduce that exactly:
a service needs a WAN HAI vessel, and it must have been running across the whole
ingested period. The first is solid. The second fits the data but depends on
which files are ingested — feed it only July files and `AS1` would come back in.

Rules 1 and 2 can each be switched off, and services can be forced in or out by
name. Nothing is silently dropped: every excluded voyage is in `review.csv`.

Ask: is `AS1` out because it stopped calling at Qingdao? Should the new services
(`AMX`, `PMX`, `INX`, `AA1`) be in the August report?

## The review system

Uncertainty is never resolved silently. `app/review.py` turns each uncertain
case into a question carrying the voyage, its timestamps, the Daily files it
came from, the candidate answers, and a recommendation with its reasoning where
the evidence supports one. Seven kinds are detected: unknown operator,
ambiguous voyage match, missing ATD, conflicting snapshots, value disagreement,
uncertain window, and berthing before the window opened.

`app/decisions.py` stores the answers, in two deliberately separate categories:

* **rules** — reusable, currently only vessel → operator, applied to every
  future month;
* **overrides** — one voyage in one month, applied nowhere else.

`record_rule` raises on any kind not in `REUSABLE_KINDS`, so an override cannot
become a rule by accident. That guarantee is asserted in `tests/test_decisions.py`.

Detection is tuned to be worth reading rather than exhaustive: a timestamp
revision under two hours is the berth board sharpening an estimate, not a
conflict, and a missing departure on a service the report does not cover is not
a decision anyone needs to make. Without that filtering July raised 18
questions; with it, 10 — including a genuine 10-day date correction in the
Daily files that would otherwise have been buried.

Row states are `auto`, `reviewed` and `unresolved`. A row with any open
question is `unresolved` even when it already carries a defensible value; only
a *blocking* question (one that would leave a required column empty) actually
holds a value back. The month always generates.

## The launcher

`TAO Report Generator.vbs` runs `launcher/start.bat` with window style 0, so no
console is ever visible. Three things in that script are load-bearing and were
got wrong first time round:

* **The server runs in the foreground of the batch.** A child started with
  `start /b` shares its parent's console; when the batch exits, that console is
  destroyed and the server dies with it. Keeping the server in the foreground
  keeps the console alive for as long as it runs. `tests/test_launcher.py`
  asserts the server line is not prefixed with `start`.
* **The wait-and-open step is Python, not batch.** `timeout /t` needs console
  input and is unreliable when there is no console. `launcher/open_when_ready.py`
  polls the port and opens the browser, and is unit-tested — including the case
  where the server binds late.
* **Starting it twice is safe.** The script probes the port first; if something
  is already answering it just reopens the browser and exits.

`Stop TAO Report Generator.vbs` kills only processes running out of this
folder's own `.venv`, so another Python program on the machine is untouched.

## Design decisions worth knowing

- **The generator never reads the ground truth.** `app/validation.py` is only
  imported by tests and by the CLI's optional `--validate-against`.
- **No voyage-specific logic anywhere.** Every rule is general. The three
  divergences are documented in `REVERSE_ENGINEERING.md` and asserted
  individually in the regression test, so a fourth one fails the build rather
  than sliding past.
- **Snapshots are never overwritten.** `VoyageHistory.consolidated()`
  forward-fills, so a value that disappears from a later file is not lost.
- **Flags rather than guesses.** Fifteen review codes; anything the tool cannot
  stand behind carries one.
- **The historical workbook has defects.** The validator detects an impossible
  ATA/ATB ordering structurally instead of naming voyages.

## Known limitations

- Only the `CNTAO` sheet is generated. The historical workbook also carries a
  legacy `1` sheet (2023–24 WAN HAI-only log), a `Sheet2` of weekly commentary,
  and a `Sheet3` (July 2024). None is derivable from the Daily files; if the
  employee wants them preserved, the generator would need to open an existing
  workbook and write into it rather than creating a fresh one.
- Rizhao (`RZH`) voyages are parsed but excluded — there is no `CNRZH` report in
  the sample set. The port filter is in `app/normalization.is_qingdao`.
- The service-scope rule needs a snapshot from either side of the target month
  to be meaningful.
- `config/operator_mapping.json` was seeded from the observed fleets. Carriers
  not in the sample data will surface as `OPR_UNKNOWN` on first sight, which is
  the intended behaviour.

## Next steps, in order of value

1. Confirm the service-scope rule with the report's author (above).
2. Run August 2026 and check it by eye — the sample set already has the files.
3. Ask about `E044JKPU` and `S564JCAG`; if an unsampled Daily file explains them,
   the rules are already right and the sample set is just incomplete.
4. Decide whether the generated workbook should preserve the other sheets.
5. **Run the Windows launcher once on a real Windows machine.** It was written
   on macOS. What is verified: the port probe, the browser hand-off, the
   timeout path and the failure message (unit tests in
   `tests/test_launcher.py`), plus the whole start-to-browser sequence via
   `run.command`, which now shares the same Python opener. What is *not*
   verified: batch and VBScript syntax, the first-run `venv` bootstrap, and
   `stop.bat`'s WMI process match. Those are the things to watch on the first
   real run.
6. Add report history (`app/history.py`) — the last outstanding item from the
   production target in [ARCHITECTURE.md](ARCHITECTURE.md).
7. Run the packaged application on a real Windows machine before handing it
   over. CI verifies the engine inside the build but deliberately does not
   drive the window.

## Repository map

Module responsibilities are listed in `README.md`. `tools/` holds the
throwaway investigation scripts used during reverse engineering — they are not
part of the application and can be deleted.
