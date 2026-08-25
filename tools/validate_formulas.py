"""Test candidate delay formulas against every value the Daily itself prints."""
from app.parser import parse_many, discover_daily_files
from app.normalization import hours_between, round_hours
import collections, itertools

snaps = parse_many(discover_daily_files("samples/daily"))
print(len(snaps), "snapshots")

def cand_arr(s):
    return {
        "ATA-winstart": hours_between(s.ata, s.window_start),
        "ATA-ETA": hours_between(s.ata, s.eta),
        "ATB-winstart": hours_between(s.atb, s.window_start),
    }
def cand_dep(s):
    return {
        "ATD-winend": hours_between(s.atd, s.window_end),
        "ATD-ETD": hours_between(s.atd, s.etd),
    }
def cand_wb(s):
    ws = s.window_start
    eff = max(x for x in [s.ata, ws] if x is not None) if (s.ata or ws) else None
    raw = hours_between(s.atb, s.ata)
    clamped = hours_between(s.atb, eff)
    return {
        "ATB-ATA": raw,
        "ATB-max(ATA,ws)": clamped,
        "max(0,ATB-max(ATA,ws))": None if clamped is None else max(0.0, clamped),
        "max(0,ATB-ATA)": None if raw is None else max(0.0, raw),
        "ATB-ETB": hours_between(s.atb, s.etb),
    }

for label, reported_attr, cands in [
    ("ARR", "arr_delay_reported", cand_arr),
    ("DEP", "dep_delay_reported", cand_dep),
    ("W/B", "waiting_reported", cand_wb),
]:
    tot = collections.Counter(); ok = collections.Counter(); miss = collections.defaultdict(list)
    for s in snaps:
        rep = getattr(s, reported_attr)
        if rep is None: continue
        for name, val in cands(s).items():
            if val is None:
                continue
            tot[name] += 1
            if abs(round_hours(val) - rep) <= 0.11: ok[name] += 1
            else: miss[name].append(s)
    print(f"\n=== {label} (n reported = {sum(1 for s in snaps if getattr(s,reported_attr) is not None)}) ===")
    for name in tot:
        print(f"  {name:26} {ok[name]}/{tot[name]}  ({100*ok[name]/tot[name]:.1f}%)")
    best = max(tot, key=lambda n: ok[n]/max(tot[n],1))
    print(f"  -- misses for best rule {best!r}: {len(miss[best])}")
    for s in miss[best][:12]:
        print(f"     {s.source_file} r{s.source.row} {s.source.week_label} {s.svc} {s.tfc} "
              f"rep={getattr(s,reported_attr)} calc={round_hours(cands(s)[best])} raw={s.raw}")
