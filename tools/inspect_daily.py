import openpyxl, glob, os
paths = sorted(glob.glob("samples/daily/*.xlsx"))
for p in paths:
    wb = openpyxl.load_workbook(p, data_only=True, read_only=False)
    print(os.path.basename(p), "->", [(ws.title, ws.dimensions, ws.sheet_state) for ws in wb.worksheets])
