"""Blind validation: do the rules hold on a month they were never fitted to?

Every rule in this project was derived by looking at July 2026 — the one month
with a hand-made TAO Compare to compare against. That makes any July result
partly self-confirming. This script holds out everything that departed *after*
July and re-tests the rules against figures nobody involved in deriving them
ever looked at.

The held-out evidence is the Daily Berth Report's own Arr Delay / Dep Delay /
Waiting columns. Those are typed by the same person who writes the monthly
report, so reproducing them from raw timestamps is a genuine test of whether
the rules describe what the business actually does.

    python tools/blind_validation.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime

from app.calculations import (
    calc_arr_delay,
    calc_dep_delay,
    calc_waiting,
    calc_waiting_from_arrival,
    effective_window,
)
from app.parser import discover_daily_files, parse_many

TOLERANCE = 0.11  # the workbooks print one decimal
FIT_PERIOD_END = datetime(2026, 8, 1)  # July and earlier is what the rules were fitted to

RULES = {
    "arr_delay": ("Arr Delay = ATA - window start", calc_arr_delay),
    "dep_delay": ("Dep Delay = ATD - window end", calc_dep_delay),
    "waiting": ("W/B = max(0, ATB - max(ATA, window start))", calc_waiting),
}


def anchor(snap) -> datetime | None:
    """When this voyage happened, for splitting fitted from held-out."""
    return snap.atd or snap.atb or snap.ata or snap.window_start


def departs_deliberately(snap, corrected, field) -> str:
    """Is this a row where the monthly report is *meant* to differ from the Daily?

    Two documented rules make the monthly figure diverge from the Daily's own
    arithmetic. Counting those as failures would be measuring the wrong thing:
    the July ground truth shows the report author making exactly these
    departures.
    """
    if corrected.window_start != snap.window_start:
        return "window corrected onto the service's weekly slot"
    if (
        field == "waiting"
        and snap.ata is not None
        and snap.window_start is not None
        and snap.ata < snap.window_start
    ):
        # The Daily counts W/B from arrival; the monthly report counts it from
        # whichever is later of arrival and the window opening. The two only
        # diverge when the ship arrived early, and July's ground truth settles
        # which one the report uses (S092JEBU: 116.9, not 125.5).
        return "arrived before its window opened, so W/B is not counted from arrival"
    return ""


def evaluate(snapshots, predicate):
    """Agreement between each rule and the figures the Daily prints itself."""
    totals = defaultdict(int)
    hits = defaultdict(int)
    misses = defaultdict(list)
    departures = defaultdict(list)

    seen: set[tuple] = set()
    for snap in snapshots:
        when = anchor(snap)
        if when is None or not predicate(when):
            continue
        corrected, _ = effective_window(snap)
        # One voyage appears in many files; judge each distinct row once.
        fingerprint = (
            snap.tfc,
            snap.ata,
            snap.atb,
            snap.atd,
            corrected.window_start,
            snap.arr_delay_reported,
            snap.dep_delay_reported,
            snap.waiting_reported,
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        for field, (_, rule) in RULES.items():
            reported = getattr(snap, f"{field}_reported")
            if reported is None:
                continue
            calculated = rule(corrected)
            if calculated is None:
                continue

            agrees = abs(calculated - reported) <= TOLERANCE
            reason = "" if agrees else departs_deliberately(snap, corrected, field)
            if reason:
                departures[field].append((snap, reported, calculated, reason))
                continue

            totals[field] += 1
            if agrees:
                hits[field] += 1
            else:
                misses[field].append((snap, reported, calculated))
    return totals, hits, misses, departures


def describe(title: str, totals, hits, misses, departures, show_detail: bool) -> bool:
    print(f"\n{title}")
    print("-" * len(title))
    if not totals:
        print("  no figures to test")
        return True

    for field, (description, _) in RULES.items():
        n, ok = totals[field], hits[field]
        if not n:
            continue
        pct = 100 * ok / n
        print(f"  {description:52} {ok:3}/{n:<3} ({pct:5.1f}%)")

    counted = sum(len(v) for v in departures.values())
    n_all = sum(totals.values()) + counted
    ok_all = sum(hits.values())
    print(
        f"\n  Raw agreement with the Daily, counting everything: "
        f"{ok_all}/{n_all} ({100 * ok_all / n_all:.1f}%)"
    )
    if counted:
        print(
            f"  {counted} of those are rows where the monthly report is *meant* "
            "to differ:"
        )
        if show_detail:
            for field in RULES:
                for snap, reported, calculated, reason in departures[field]:
                    print(
                        f"    ~ {snap.svc:4} {str(snap.tfc):10} {field:10} "
                        f"Daily {reported:>8}, report {calculated:>8}  — {reason}"
                    )

    if show_detail:
        for field in RULES:
            for snap, reported, calculated in misses[field]:
                print(
                    f"    ! {snap.svc:4} {str(snap.tfc):10} {field:10} "
                    f"Daily says {reported:>8}, rules give {calculated:>8}  "
                    f"[{snap.source_file}]"
                )
                explain(snap, field, reported, calculated)
    return True


def explain(snap, field, reported, calculated) -> None:
    """Why a disagreement happened, where the history can say."""
    if field == "waiting":
        from_arrival = calc_waiting_from_arrival(snap)
        if from_arrival is not None and abs(from_arrival - reported) <= TOLERANCE:
            print(
                "        the Daily counted from arrival rather than from the "
                "window opening; the ship berthed before its slot"
            )
            return
    print(
        f"        ATA {snap.raw.get('ata')}  ATB {snap.raw.get('atb')}  "
        f"ATD {snap.raw.get('atd')}  window {snap.window_raw!r}"
    )


def main() -> int:
    files = discover_daily_files("samples/daily")
    if not files:
        print("no Daily workbooks in samples/daily")
        return 1
    snapshots = parse_many(files)

    print("=" * 72)
    print("BLIND VALIDATION — rules fitted on July 2026, tested on what came after")
    print("=" * 72)
    print(f"{len(files)} Daily files, {len(snapshots)} voyage rows parsed")
    print(
        "\nHeld-out evidence: the Arr Delay / Dep Delay / Waiting figures the "
        "Daily\nprints for WAN HAI vessels. The rules are re-derived from raw "
        "timestamps\nand compared against them."
    )

    fitted = evaluate(snapshots, lambda when: when < FIT_PERIOD_END)
    describe(
        "FITTED PERIOD (July 2026 and earlier) — expected to agree",
        *fitted,
        show_detail=True,
    )

    held_out = evaluate(snapshots, lambda when: when >= FIT_PERIOD_END)
    describe(
        "HELD OUT (departed August 2026 or later) — never used to derive anything",
        *held_out,
        show_detail=True,
    )

    fit_totals, fit_hits, _, _ = fitted
    totals, hits, misses, _ = held_out
    n, ok = sum(totals.values()), sum(hits.values())
    fit_n, fit_ok = sum(fit_totals.values()), sum(fit_hits.values())

    print("\n" + "=" * 72)
    if not n:
        print("VERDICT: no held-out figures available — add later Daily files")
        return 1
    fitted_pct = 100 * fit_ok / fit_n if fit_n else 0.0
    held_pct = 100 * ok / n
    print(f"VERDICT: {ok}/{n} held-out figures reproduced ({held_pct:.1f}%)")
    print(f"         {fit_ok}/{fit_n} on the fitted period ({fitted_pct:.1f}%)")
    gap = fitted_pct - held_pct
    print(
        f"         gap of {gap:+.1f} points — a large positive gap would mean "
        "the rules\n         were fitted to July rather than describing the "
        "business."
    )
    if n < 30:
        print(
            f"\n         Caveat: only {n} held-out figures. Enough to catch gross "
            "overfitting,\n         not enough to be a precise estimate. Rerun as "
            "more Daily files arrive."
        )
    if sum(len(v) for v in misses.values()):
        print("\n         Unexplained disagreements above need a look.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
