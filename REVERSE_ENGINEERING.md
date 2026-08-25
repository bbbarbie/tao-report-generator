# Reverse engineering the TAO Compare report

How the monthly `TAO Compare YYYYMM.xlsx` workbook is derived from the daily
`Daily Berth Report` files. Nothing here was supplied as a specification — every
rule below was inferred from the workbooks and then checked against them.

Evidence base: 23 Daily workbooks (2026-07-01 … 2026-08-26, 1013 parsed voyage
rows) and the hand-made `TAO Compare 202607.xlsx` (27 rows on sheet `CNTAO`).

Current state: **24 of 27 ground-truth rows reproduced from the Daily files
alone.** One of the remaining three is a provable typo in the hand-made
workbook; two are genuine unexplained exceptions, described at the bottom.

---

## 1. Source structure

`Daily Berth Report` is a snapshot of a berthing board, not a log. Each file
contains 3–6 weekly sections, each introduced by a banner (`WK30船舶動態：`) and a
header row, followed by one row per service.

| Column | Meaning |
| --- | --- |
| SVC | service code (`AP2`, `CI5`, …) |
| VSL/VOY | vessel name and voyage number; `BLANK` when no ship is nominated yet |
| TFC | voyage code — the primary identifier |
| TML | berth group (`QQCTN`, `QQCTU`, `QQCTUA`, `QQCT-2`, `RZH`) |
| ETA / ATA / ETB / ATB / ETD / ATD | estimated and actual arrival, berthing, departure |
| Window Time | the granted berthing window, as `dd/HHMM - dd/HHMM` |
| *(unlabelled, right of Window Time)* | the service's standing weekly slot, e.g. `MON 07 - TUE 01` |
| Arr Delay Hrs / Dep Delay Hrs / Waiting | figures the Daily computes — **only filled in for some rows** |
| GPH, Delay Reason | not used by the monthly report |

Structural facts confirmed across all 23 files:

- Row counts change constantly (93 → 119 rows); **row numbers are never usable**.
- The header layout was identical in all 97 weekly sections observed, but the
  parser matches on labels anyway, so a shift would not break it.
- Every timestamp cell is a **string**, never an Excel date serial.
- Voyages move between weekly sections as they slip, and drop off the board
  entirely once they scroll out — reading only the month-end file loses rows.
  Measured: the 31 July file alone yields 23 rows and reproduces 12 of the 27
  ground-truth rows; all 23 files yield 27 rows and reproduce 24. This is the
  single strongest argument for ingesting every snapshot, and it is asserted in
  `tests/test_selection.py` rather than left as a claim.

### Dates: `dd/HHMM`

Day-of-month and a 24-hour clock, with no month and no year. Recovered from the
weekly section's Monday and from the voyage's own chronology
(window → ETA → ATA → ETB → ATB → ETD → ATD), each timestamp anchored to the
previous one.

Nearest-match alone is not enough. `E02762A` in the WK28 section shows ATA
`25/1218` against a 6 July window: 25 June is 11 days earlier, 25 July is 19 days
later, and the correct answer is **July** (the ship was 455 hours late). Where
the Daily already prints a delay figure, that figure is used to pin the month —
as an anchor only, never as the value. Ships also arrive genuinely early
(`W02762B` arrived 7.5 days before its window), so a "must be after" rule would
be wrong.

---

## 2. Confirmed rules

### 2.1 The three metrics

Delays are measured against the **berthing window**, not the vessel's schedule:

```
Arr Delay = ATA - window start
Dep Delay = ATD - window end
W/B       = max(0, ATB - max(ATA, window start))
```

Checked against every figure the Daily prints for itself (260 rows):

| Rule | Agreement |
| --- | --- |
| `Arr Delay = ATA - window start` | 251/260 (96.5%) |
| `Arr Delay = ATA - ETA` | 0/49 |
| `Dep Delay = ATD - window end` | 259/260 (99.6%) |
| `Dep Delay = ATD - ETD` | 0/236 |
| `W/B = max(0, ATB - max(ATA, window start))` | 231/260 (88.8%) |
| `W/B = ATB - ATA` | 204/260 (78.5%) |
| `W/B = ATB - ETB` | 14/236 |

The residual disagreements are stale figures: a Daily row's timestamps get
revised without the delay columns being recomputed. Every one traced back to a
value that matched when it was struck.

### 2.2 W/B is not simply `ATB - ATA`

The employee's stated rule is `W/B = ATB - ATA`. That is right whenever the ship
arrives after its window opens, which is the common case, but the ground truth
shows it is not the rule when a ship arrives **early**:

| Voyage | ATA | Window opens | ATB | `ATB - ATA` | Ground truth |
| --- | --- | --- | --- | --- | --- |
| `S092JEBU` | 21 Jul 10:24 | 21 Jul 19:00 | 26 Jul 15:53 | 125.5 | **116.9** |
| `E076JONR` | 06 Jul 08:00 | 06 Jul 20:00 | 06 Jul 19:07 | 11.1 | **0** |

Both are reproduced exactly by `max(0, ATB - max(ATA, window start))`. This is
also the business-sensible reading: time spent waiting for your own slot to open
is not time spent waiting for a berth, and a ship berthed before its window even
opened has not waited at all.

### 2.3 WAN HAI rows are copied; everyone else is calculated

The Daily fills in Arr Delay / Dep Delay / Waiting **only for WAN HAI-operated
vessels**. For those rows the monthly report copies the printed figure verbatim;
for every other operator the columns are blank and the figures are calculated.

The two are not always the same number, and where they differ the ground truth
follows the Daily, not the recalculation:

| Voyage | Daily prints | Recalculation | Ground truth |
| --- | --- | --- | --- |
| `S033362` W/B | 1.0 | 0.0 | **1.0** |
| `S024377` W/B | 63.6 | 67.2 | **63.6** |

So the copy is deliberate, not incidental. Both cases are flagged
`REPORTED_DISAGREES_WITH_CALCULATION` so the difference stays visible.

In July: 12 rows copied, 15 calculated.

### 2.4 Month membership is by ATD

A voyage belongs to the month it **departed** in, regardless of when it arrived
or berthed. `W056JIHN` arrived 28 June and berthed 30 June but departed 1 July,
and appears in the July report. A voyage with no ATD is never invented — it is
flagged `NO_ATD_RECORDED`.

### 2.5 靠泊碼頭 is the service's terminal, not the call's berth

The column names the terminal the **service** works out of, taken from the most
recent Daily snapshot — not the berth group the individual call happened to use.
Three ground-truth rows only make sense this way:

| Voyage | Berth in the Daily | Ground truth |
| --- | --- | --- |
| `W0766C` (CI2) | QQCTUA | QQCTN |
| `W001903` (FM1) | QQCTU | QQCTN |
| `W02762B` (FM1) | QQCTU | QQCTN |

CI2 shows the mechanism directly: `W0766C` is `QQCTN` in the first nine
snapshots and `QQCTUA` from 21 July onward, and the report says `QQCTN`. FM1
moved from QQCTU to QQCTN during the period, and the report uses the new
terminal for both of its July calls. Berth-group suffixes are normalised away
(`QQCT-2` → `QQCT`). Applying this rule reproduces **27/27** terminal values;
using the per-call berth reproduces 24/27. Rows where the two differ are flagged
`TERMINAL_DIFFERS_FROM_SERVICE`.

### 2.6 平均侯泊時間 is the mean W/B per SVC + OPR

Written **once, on the first row of each service/operator block**, and left blank
on the rest. Verified on all 18 groups in July; e.g. CI5/WHL = mean(0.9, 1.0,
75.4) = 25.8.

### 2.7 Row order

Sorted by SVC ascending, then OPR ascending, then ATB ascending within the
group. Reproduces the ground truth's row order exactly.

### 2.8 Window integrity: the weekday pattern outranks a mistyped date

The Daily prints both the concrete window and the service's standing weekly slot.
When **both ends** of the concrete window fall on the wrong weekday **by the same
number of days** at the **right clock times**, the dates were typed a day out and
the weekly slot wins.

`W02762B` (FM1, WK31, week beginning Mon 27 July) shows `28/0700 - 29/0100`
against a slot of `MON 07 - TUE 01`. Monday is the 27th, so the window should be
`27/0700 - 28/0100`. Correcting it reproduces the ground truth exactly
(-157.5 / -9.8 rather than the Daily's own -181.5 / -33.8), and it is the only
row in July where the report disagrees with a figure the Daily printed for a
WAN HAI vessel. The Daily's figures were struck against the bad window, so a
corrected row is recalculated even for a WAN HAI vessel, and always flagged
`WINDOW_WEEKDAY_MISMATCH`.

Deliberately narrow, because two lookalike cases must **not** be corrected:

- **One end only** disagrees (20 voyages, mostly CS3 `TUE 19 - THU 03` against a
  Tue→Wed window). Here the *pattern label* is stale, not the dates — the Daily's
  own figures confirm the concrete window. Left alone.
- **A whole week** apart: the row is showing an adjacent week's window, which is
  normal. Same weekday, so it never triggers.

---

## 3. Report scope

Not every Qingdao voyage appears. July's 33 candidates reduce to the ground
truth's 27 through two service-level rules, both derived from the Daily files:

1. **The service must have a WAN HAI vessel.** `WS3` is worked exclusively by
   COSCO/CSCL ships in all 23 files — there is nothing to compare against.
2. **The service must have been running for the whole ingested period.**
   `AMX` first appears on 7 July, `PMX` on 8 July, `INX` on 23 July and `AA1` on
   29 July — all introduced mid-month. `AS1` runs the other way: it is on the
   board until 31 July and gone from 3 August onward.

Together these reproduce the ground truth's service list exactly:
`AP2 AS2 CI2 CI5 CS3 CT1 CV1 FM1`. `NCT` and `NT2` are excluded earlier, by
port — they berth at `RZH` (Rizhao), not Qingdao.

**Confidence: moderate.** Rule 1 is business-obvious. Rule 2 fits the evidence
but is sensitive to which files are ingested: with only July files supplied,
`AS1` would qualify. Both are switchable in `config/report_scope.json`, which
also takes explicit include/exclude lists, and every voyage dropped by scope is
listed in `review.csv` rather than disappearing. **This is the rule most worth
confirming with the report's author.**

---

## 4. Voyage identity

Keyed on TFC. Two codes are merged into one voyage only on combined evidence —
same service, same terminal, same vessel name or a one-character TFC difference,
**and** an arrival or berthing within 12 hours. Timestamp proximity alone is
never enough.

The timing requirement does the real work: a vessel's consecutive voyages share
service, terminal and name, and their TFC codes differ by exactly one digit
(`S16459` / `S16559` / `S16659`). Without it, every service's whole season
collapses into one voyage. Ambiguous pairs that clear some tests but not all are
logged rather than merged; the July run produces one such note.

Two ground-truth TFC codes do not match the Daily files:

| Ground truth | Daily files | Note |
| --- | --- | --- |
| `E026JKMZ` | `E026JPMZ` | KOTA MANZANILLO; sister ships use `JK__` (`E044JKPU`, `E102JKCT`), so the Daily looks wrong |
| `S092JEBU` | `S095JEBU` | EVER BURLY; the Daily's own VSL/VOY cell says `EVER BURLY/S092` |

Both are single-character differences on the same call. The generator emits what
the Daily says; the validator matches them and reports the difference.

---

## 5. Operators (OPR)

The Daily has no operator column — the person writing the report knows the
fleets. That knowledge is in `config/operator_mapping.json`: exact vessel names
first, then ordered keyword rules, then `OPR_UNKNOWN`. The mapping was seeded
from the vessel names in the Daily files and the OPR codes in the ground truth,
and resolves all 27 July rows.

`WAN HAI → WHL`, `NYK`/`MOL`/`BAY BRIDGE → ONE`, `KOTA → PIL`, `EVER`/`ITAL →
EMC`, `YM → YML`, `XIN`/`COSCO`/`CSCL`/`CA GUANGZHOU → COS`, `OOCL → OOL`,
`KMTC → KMTC`, `INTERASIA → IAL`, `TIGER → BTL`.

Worth noting: WAN HAI's own TFC codes never contain a `J` after the voyage
digits (`E1115B`, `W26751`), while partners' codes do (`E076JONR`, `W605JTCN`).
That distinguishes house from non-house vessels but not *which* carrier, so it
is not used.

---

## 6. Known exceptions

Three ground-truth rows are not reproduced. None is worked around in code.

### `S033362` — a typo in the hand-made workbook

Ground truth records ATA as **2026-08-08** 05:36 and ATB as 2026-07-08 06:36 —
berthing a month before arriving. The Daily says ATA 2026-07-08 05:36, which is
consistent with the row's own W/B of 1.0. The generated value is correct; the
validator classifies this as `GROUND_TRUTH_INCONSISTENT` by detecting the
impossible ordering, not by naming the voyage.

### `E044JKPU` — Dep Delay unexplained (ground truth 174.6, calculated 187.2)

The Daily records ATD `08/0510` in all six snapshots that carry it, and a window
ending `30/1000`, giving 187.2. Reproducing 174.6 needs an ATD of 7 July 16:36,
which appears in no supplied file. ETD (`07/2300`), ATB and the July port-closure
log were all checked and none produces it. Most likely the figure was struck from
a Daily snapshot that is not in the sample set — the voyage's last appearance is
17 July, well before the report was written.

### `S564JCAG` — Arr and Dep Delay off by 1h and 2h

Ground truth: Arr **-41.5**, Dep **18.7**. Calculated: -40.5, 20.7. These imply a
window of `22/1500 - 23/1300`; all 14 snapshots say `22/1400 - 23/1100`, with no
revision. The row's own W/B (24.3) *is* reproduced, and only by the Daily's
window — so the ground-truth row uses one window for W/B and a different one for
the two delays. Reads like a manual arithmetic slip, but there is no source
evidence either way.

---

## 7. Rejected hypotheses

| Hypothesis | Why it was rejected |
| --- | --- |
| `Arr Delay = ATA - ETA` | 0/49 agreement |
| `Dep Delay = ATD - ETD` | 0/236 agreement |
| `W/B = ATB - ETB` | 14/236 agreement |
| `W/B = ATB - ATA` unconditionally | fails `S092JEBU` (125.5 vs 116.9) and `E076JONR` (11.1 vs 0) |
| Derive all windows from the weekday pattern | worse overall: reproduces 211/248 Daily figures against 239/248 for the concrete window |
| 靠泊碼頭 = the call's own berth | 24/27; the service-level rule gives 27/27 |
| 靠泊碼頭 = the service's most common berth | FM1 is QQCTU in 93 rows against 13 QQCTN, but the report says QQCTN |
| Scope = services with more than one Qingdao call | AMX has two July calls and is still excluded |
| Scope = services with both WAN HAI and partner vessels | CI2 and FM1 are WAN HAI-only in July and are included |
| Read only the month-end Daily file | loses voyages — `E036369` (AS1) leaves the board on 17 July, `E044JKPU` on 17 July |
| Merge voyages on timestamp proximity | collapses each vessel's consecutive voyages into one |
| Delays adjusted for port closures | the July closure log does not account for either exception |

---

## 8. Open questions

1. **Service scope (§3)** — the highest-value question. Is `AS1` excluded from
   July because it stopped calling at Qingdao, or for another reason? Should
   `AMX`/`PMX`/`INX`/`AA1` appear in the August report now that they are running?
2. **`E044JKPU` and `S564JCAG` (§6)** — was a Daily snapshot used that is not in
   the sample set, or were these adjusted by hand?
3. **TFC corrections (§4)** — should the generator prefer the voyage number in
   the VSL/VOY cell over the TFC cell when they disagree, as the ground truth did
   for `S092JEBU`?
4. Should a row with no ATD ever be carried into the report, given the note that
   non-WAN HAI vessels have historically appeared without a visible ATD? It is
   currently excluded and flagged.
