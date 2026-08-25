import collections
from app.parser import parse_daily_workbook, discover_daily_files
from app.normalization import is_qingdao
files = discover_daily_files("samples/daily")
present = collections.defaultdict(set)   # svc -> set of snapshot dates where svc row exists (any, incl. blank)
import openpyxl, re
for p in files:
    wb=openpyxl.load_workbook(p, data_only=True); ws=wb["Daily Berth Report"]
    seen=set()
    for r in range(1, ws.max_row+1):
        b=ws.cell(r,2).value; e=ws.cell(r,5).value
        if b and e and isinstance(b,str) and 2<=len(b.strip())<=4 and b.strip().upper()==b.strip():
            seen.add(b.strip().upper())
    for s in seen: present[s].add(p.stem[-8:])
GT={"AP2","AS2","CI2","CI5","CS3","CT1","CV1","FM1"}
allf=[p.stem[-8:] for p in files]
for svc in sorted(present):
    d=sorted(present[svc])
    print(f"{svc:5} {'IN ' if svc in GT else 'out'} n={len(d):3} first={d[0]} last={d[-1]}  gaps={len(set(allf)-set(d))}")
