from app.parser import parse_daily_workbook, discover_daily_files
import collections
files = discover_daily_files("samples/daily")
print(len(files), "files")
snaps = parse_daily_workbook(files[-3])
print(len(snaps), "snapshots from", files[-3].name)
for s in snaps[:14]:
    print(f"{s.source.week_label:5} {s.svc:4} {str(s.tfc):10} {str(s.terminal):8} "
          f"ATA={s.ata} ATB={s.atb} ATD={s.atd} WIN={s.window_start}..{s.window_end} "
          f"N={s.arr_delay_reported} O={s.dep_delay_reported} P={s.waiting_reported}")
