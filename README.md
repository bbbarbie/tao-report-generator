# TAO Monthly Report Generator

Builds the monthly `TAO Compare YYYYMM.xlsx` workbook from a batch of daily
`Daily Berth Report` files, reproducing the layout and the calculations of the
report that was previously assembled by hand.

Everything runs on your own machine. The web server is bound to `127.0.0.1`,
so it is reachable only from this computer. No workbook content and no saved
decision leaves the machine, and there is no AI or cloud service involved at
run time.

**First time on Windows?** See **[FIRST_TIME_SETUP.md](FIRST_TIME_SETUP.md)**
(繁體中文) — a step-by-step guide that assumes no technical knowledge.

**The product is a standalone Windows application** — no Python, no browser.
Build one from [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md). The Streamlit interface
below is kept for development only; both drive the same engine.

## For the person running the report

Double-click **TAO Report Generator** (Windows) or **`run.command`** (macOS).
No Terminal, no commands. The first run sets itself up and takes a few minutes;
after that it opens in seconds. Your browser opens on its own once it is ready.

On Windows nothing appears until the browser does — no console window. If you
want to free the memory afterwards, double-click **Stop TAO Report Generator**;
leaving it running is harmless, and starting it again just reopens the browser
rather than launching a second copy.

The tool opens in your browser and works in one direction:

```
Daily files  →  Month  →  Process  →  Review anything uncertain  →  Download
```

1. **Daily files** — drop them in, or point at the folder they live in.
2. **Month** — defaults to the month just gone.
3. **Process** — reads every file and rebuilds each voyage's history.
4. **Needs Review** — appears only when something is genuinely uncertain.
   Answer as many or as few as you like; the report works either way.
5. **Download** — `TAO Compare YYYYMM.xlsx` plus a `review.csv`.

### Nothing is ever guessed

When the tool cannot be confident, it asks instead of picking. Each question
shows the vessel, its timestamps, which Daily files it came from, exactly what
is uncertain, the possible answers, and — where the evidence supports one —
which it suggests and why. You decide.

It asks about: an unrecognised operator, two records that might be one voyage,
a voyage with no departure time, Daily files that disagree with each other, a
calculated figure that differs from the one the Daily printed, and an uncertain
berthing window.

### Your answers are remembered — but only where that is safe

- **Reusable rules.** "This vessel belongs to PIL" is true next month too, so
  it is saved and applied automatically from then on.
- **One-off overrides.** "For this voyage, use the calculated departure delay"
  says nothing about any other voyage, so it applies to that one row in that
  one month and nothing else.

An override is **never** turned into a rule automatically. The **Saved
decisions** screen lists both kinds separately, and either can be undone.

### The report tells you where each row came from

Every row is one of three things, shown on screen and tinted in the workbook:

| | |
| --- | --- |
| **Automatic** | produced by the rules from the Daily files — no tint |
| **Reviewed** | you made a decision about it — green |
| **Unresolved** | an open question remains — amber |

One unresolved voyage never blocks the rest of the month. A row is only left
with an empty field when a required value genuinely cannot be produced safely.

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
| `config/operator_mapping.json` | the starting vessel → carrier list (shipped with the tool) |
| `config/report_scope.json` | which services the report covers |
| `config/decisions.json` | your own saved decisions (created on first use) |

All plain JSON with notes at the top. `decisions.json` stays on your computer
and is never version-controlled — it records one person's decisions about one
company's voyages.

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
  review.py          turns uncertainty into an answerable question
  decisions.py       saved rules and one-off overrides
  cli.py             command line entry point
ui.py                local browser UI — navigation shell
ui_pages/            the three screens: Generate, Needs Review, Saved decisions
launcher/            Windows launcher internals
config/              editable mappings and saved decisions
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
