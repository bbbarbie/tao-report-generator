import sys
from app.report import build_report, default_daily_files
from app.validation import load_ground_truth, compare
files = default_daily_files("samples/daily")
rep = build_report(files, 2026, 7)
print("service scope:", rep.selection.service_scope)
print("rows:", len(rep.rows), "clean:", rep.clean_row_count)
gt = load_ground_truth("samples/ground_truth/TAO Compare 202607.xlsx")
v = compare(rep, gt)
print(); print(v.summary())
