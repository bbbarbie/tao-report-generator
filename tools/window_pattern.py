"""Does the weekday pattern column agree with the concrete window column?"""
import re, collections
from datetime import datetime, timedelta
from app.parser import parse_many, discover_daily_files
from app.normalization import week_monday, round_hours, hours_between

DAYS = {"MON":0,"TUE":1,"TUES":1,"WED":2,"THU":3,"THUR":3,"THURS":3,"FRI":4,"SAT":5,"SUN":6}
TOK = re.compile(r"([A-Z]{3,5})\s*(\d{2})(\d{2})?")

def from_pattern(pat, monday):
    if not pat: return None, None
    parts = re.split(r"\s*-\s*", pat.upper())
    if len(parts) != 2: return None, None
    out=[]
    for p in parts:
        m = TOK.search(p.strip())
        if not m or m.group(1) not in DAYS: return None, None
        d = DAYS[m.group(1)]
        hh = int(m.group(2)); mm = int(m.group(3) or 0)
        if m.group(3) is None:
            hh, mm = int(m.group(2)), 0
        out.append(datetime(monday.year, monday.month, monday.day) + timedelta(days=d, hours=hh, minutes=mm))
    if out[1] < out[0]: out[1] += timedelta(days=7)
    return out[0], out[1]

snaps = parse_many(discover_daily_files("samples/daily"))
agree=disagree=unparsed=0
diffs=collections.Counter()
cases=collections.defaultdict(list)
for s in snaps:
    wk = int(s.source.week_label[2:])
    monday = week_monday(wk, s.snapshot_date.date())
    ps, pe = from_pattern(s.window_pattern, monday)
    if ps is None: unparsed+=1; continue
    if s.window_start is None: continue
    d = (s.window_start - ps).total_seconds()/3600
    if abs(d) < 0.01 and abs((s.window_end-pe).total_seconds()/3600) < 0.01: agree+=1
    else:
        disagree+=1; diffs[round(d,1)]+=1
        cases[(s.svc, s.tfc)].append((s.source_file, s.source.week_label, s.window_raw, s.window_pattern, d))
print("agree",agree,"disagree",disagree,"unparsed",unparsed)
print("start-offset histogram (hrs):", diffs.most_common(20))
print("\ndisagreeing voyages:", len(cases))
for k,v in list(cases.items())[:25]:
    print(" ",k, v[-1])

# Which matches the Daily's own reported Arr Delay better?
okL=okP=n=0
for s in snaps:
    if s.arr_delay_reported is None or s.ata is None: continue
    wk = int(s.source.week_label[2:]); monday = week_monday(wk, s.snapshot_date.date())
    ps, pe = from_pattern(s.window_pattern, monday)
    if ps is None or s.window_start is None: continue
    n+=1
    if abs(round_hours(hours_between(s.ata, s.window_start)) - s.arr_delay_reported) <= 0.11: okL+=1
    if abs(round_hours(hours_between(s.ata, ps)) - s.arr_delay_reported) <= 0.11: okP+=1
print(f"\nArr Delay reproduced from L-window: {okL}/{n};  from pattern-window: {okP}/{n}")

print("\n=== weekday-consistency check (week-agnostic) ===")
bad=collections.defaultdict(list); good=0
for s in snaps:
    wk = int(s.source.week_label[2:]); monday = week_monday(wk, s.snapshot_date.date())
    ps, pe = from_pattern(s.window_pattern, monday)
    if ps is None or s.window_start is None: continue
    same_start = s.window_start.weekday()==ps.weekday() and s.window_start.time()==ps.time()
    same_end = s.window_end is not None and pe is not None and s.window_end.weekday()==pe.weekday() and s.window_end.time()==pe.time()
    if same_start and same_end: good+=1
    else: bad[(s.svc,s.tfc)].append((s.source_file,s.source.week_label,s.window_raw,s.window_pattern))
print("weekday-consistent:",good,"  inconsistent voyages:",len(bad))
for k,v in bad.items(): print("  ",k,len(v),v[-1])
