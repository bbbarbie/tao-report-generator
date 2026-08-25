"""For each ground-truth row: was the value copied from the Daily or calculated?"""
from app.report import build_report, default_daily_files
from app.validation import load_ground_truth
rep = build_report(default_daily_files("samples/daily"), 2026, 7)
gt = {r.tfc: r for r in load_ground_truth("samples/ground_truth/TAO Compare 202607.xlsx")}
copied=calc=0
for row in rep.rows:
    methods = {row.arr_delay.method, row.dep_delay.method, row.waiting.method}
    tag = "copied" if "copied_from_daily" in methods else "calculated"
    if tag=="copied": copied+=1
    else: calc+=1
print(f"{copied} rows copied from the Daily's own columns, {calc} recalculated")
print("\nWHL rows where the Daily's figure differs from a recalculation:")
for row in rep.rows:
    for name, p in (("Arr",row.arr_delay),("Dep",row.dep_delay),("W/B",row.waiting)):
        if p.method=="copied_from_daily" and p.calculated_value is not None and abs(p.calculated_value-p.value)>0.11:
            g = gt.get(row.tfc)
            gtv = {"Arr":g.arr_delay,"Dep":g.dep_delay,"W/B":g.waiting}[name] if g else None
            print(f"  {row.tfc:9} {name:4} daily={p.value:8} recalc={p.calculated_value:8} ground_truth={gtv}")
