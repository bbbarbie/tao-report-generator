# Implementation status

Written so another developer can pick this up cold. Last updated after the
July 2026 regression reached 24/27.

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
| Tests | 213 tests, all passing. |
| Review / decision system | Done — questions with candidates, recommendations and reasons; answers saved as rules or one-off overrides. |
| Local UI | Done — three screens: Generate, Needs Review, Saved decisions. |
| Windows launcher | Done — `TAO Report Generator.vbs` starts the server with no console window and opens the browser. **Not tested on Windows** (built on macOS); the equivalent macOS launcher is verified end to end. |
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
5. **Test the Windows launcher on an actual Windows machine.** It was written
   on macOS and cannot be run here. The parts that were verifiable — the
   Streamlit flags, the loopback binding, the port-readiness probe and the
   browser hand-off — are all confirmed via the macOS launcher, which uses the
   same sequence. What remains unverified is batch/VBScript syntax and the
   first-run `venv` bootstrap on Windows.
6. Package as a double-clickable app (PyInstaller) so Python does not need to
   be installed at all. The launcher currently requires Python 3.10+.

## Repository map

Module responsibilities are listed in `README.md`. `tools/` holds the
throwaway investigation scripts used during reverse engineering — they are not
part of the application and can be deleted.
