import sys
from app.parser import parse_many, discover_daily_files
from app.voyage_history import build_histories
snaps = parse_many(discover_daily_files("samples/daily"))
idx = build_histories(snaps)
print(len(idx.histories), "voyages")
for n in idx.notes: print("NOTE", n.kind, n.detail)
for key in sys.argv[1:]:
    h = idx.resolve(key)
    if not h: print("no history for", key); continue
    print("="*90); print("VOYAGE", h.voyage_key, "aliases", h.aliases)
    for s in h.snapshots:
        print(f"  {s.source_file[6:14]} r{s.source.row:3} {s.source.week_label:5} {s.svc:4} {str(s.tfc):10} {str(s.terminal):8}"
              f" ATA={s.raw['ata']!s:9} ATB={s.raw['atb']!s:9} ATD={s.raw['atd']!s:9} WIN={s.window_raw!s:19} PAT={str(s.window_pattern):22}"
              f" N={s.arr_delay_reported} O={s.dep_delay_reported} P={s.waiting_reported}")
