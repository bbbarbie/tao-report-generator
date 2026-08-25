# TAO Monthly Report Generator

Builds the monthly `TAO Compare YYYYMM.xlsx` workbook from a batch of daily
`Daily Berth Report` files, reproducing the layout and the calculations of the
report that was previously assembled by hand.

Everything runs on your own machine. No workbook content leaves the computer,
and there is no AI or cloud service involved at run time.

## For the person running the report

1. Double-click **`run.command`** (macOS) or **`run.bat`** (Windows).
   The first run takes a minute to set itself up; after that it is quick.
2. The tool opens in your browser.
3. Drop in the Daily files (or point it at the folder they live in).
4. Choose the month.
5. Click **Generate TAO Compare**, then **Download**.

You get three things:

- **`TAO Compare YYYYMM.xlsx`** — sheet `CNTAO` in the usual layout, plus a
  `Review` sheet and an `Audit` sheet.
- **`review.csv`** — every row the tool could not complete on its own, and why.
- The figures on screen before you download anything.

Nothing is ever guessed. If a vessel's operator is unknown, or a departure time
is missing, the tool says so instead of filling something in. Unrecognised
vessels can be assigned an operator once, in the app, and are remembered.

## Supplying the Daily files

The filename must contain the snapshot date, e.g. `Daily 20260731.xlsx`, since
that is how the tool knows which day each snapshot describes.

**Supply the whole month, not just the last file.** Voyages drop off the berthing
board as they scroll out of view, so the month-end file does not contain every
voyage of the month. The tool reads every file you give it, builds a history for
each voyage, and keeps whatever it saw — including from files whose data has
since disappeared.

## From the command line

```bash
python -m app.cli --daily samples/daily --month 2026-07
python -m app.cli --daily samples/daily --month 2026-07 \
    --validate-against "samples/ground_truth/TAO Compare 202607.xlsx"
```

Reports land in `output/`.

## Things you can change without touching code

| File | What it controls |
| --- | --- |
| `config/operator_mapping.json` | which carrier (OPR) each vessel belongs to |
| `config/report_scope.json` | which services the report covers |

Both are plain JSON with notes at the top.

## How the numbers are worked out

```
Arr Delay = ATA - berthing window start
Dep Delay = ATD - berthing window end
W/B       = max(0, ATB - max(ATA, window start))
平均侯泊時間 = mean W/B per SVC + OPR, shown on the first row of each group
```

A voyage belongs to the month it **departed** in. For WAN HAI's own vessels the
figures the Daily already publishes are used as-is; for other operators, where
the Daily leaves those columns blank, they are calculated.

`REVERSE_ENGINEERING.md` sets out the evidence for each rule, the cases that do
not follow them, and the questions still open.

## Layout

```
app/
  parser.py          reads a Daily workbook into records
  normalization.py   shipping date formats, terminals, rounding
  models.py          VoyageSnapshot / VoyageHistory
  voyage_history.py  stitches snapshots into voyages
  selection.py       month membership and report scope
  calculations.py    the business rules
  operators.py       vessel -> OPR
  report.py          the pipeline
  generator.py       writes the workbook
  validation.py      compares against a known-good workbook (tests only)
  cli.py             command line entry point
ui.py                local browser UI
config/              editable mappings
samples/             Daily inputs and the historical report used as a fixture
tests/               unit tests and the July 2026 regression
output/              generated reports
```

## A note on the sample workbooks

`samples/daily/` and `samples/ground_truth/` are **empty in the repository**.
The real berth reports are internal company data — vessel schedules, terminal
windows and berth negotiations — and are deliberately not pushed to a hosting
service. They live only on the machines that need them.

Put your Daily files in `samples/daily/` locally and everything works. Without
them the test suite still runs: the tests that need the workbooks skip, and the
114 that exercise the rules themselves pass.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

`tests/test_july_2026_regression.py` is the test that matters: it rebuilds July
2026 from the Daily files alone and compares every field against the hand-made
workbook. The generator never reads the historical report — it is a fixture, not
an input.

Current result, with the workbooks present: **24 of 27 rows reproduced**, one ground-truth typo the tool gets
right, and two rows the source files do not explain. All three are listed in
`REVERSE_ENGINEERING.md` and asserted individually in the test, so a fourth
divergence fails the build.
