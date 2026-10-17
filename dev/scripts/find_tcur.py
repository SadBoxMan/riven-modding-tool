"""Scan all MHK archives and .dat files for tCUR / CURS marker bytes."""
import os, struct

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"

targets = [b"tCUR", b"CURS", b"crsr", b"CRSR"]

for fn in sorted(os.listdir(GAME)):
    path = os.path.join(GAME, fn)
    if not os.path.isfile(path):
        continue
    ext = fn.lower().rsplit(".", 1)[-1]
    if ext not in ("mhk", "dat"):
        continue
    with open(path, "rb") as f:
        data = f.read(min(10_000_000, os.path.getsize(path)))  # first 10 MB
    for marker in targets:
        idx = data.find(marker)
        if idx != -1:
            ctx = data[max(0, idx-8):idx+24]
            print(f"{fn}: {marker} at {idx:#x} -> {ctx.hex()}")

# Also check if a_data.mhk has more types by parsing the RSRC section directly
print("\n--- Detailed a_data.mhk type scan ---")
with open(os.path.join(GAME, "a_data.mhk"), "rb") as f:
    raw = f.read()

# Mohawk format: MHWK + RSRC block
if raw[:4] == b"MHWK":
    rsrc_off = raw.find(b"RSRC")
    if rsrc_off != -1:
        rsrc_size, rsrc_abs_off, rsrc_len = struct.unpack_from(">IHH", raw, rsrc_off + 4)
        name_off, type_off = struct.unpack_from(">HH", raw, rsrc_off + 12)
        # Type list offset is relative to RSRC block start
        tl_start = rsrc_off + type_off
        num_types, = struct.unpack_from(">H", raw, tl_start)
        print(f"  RSRC at {rsrc_off:#x}, type count: {num_types}")
        for i in range(num_types):
            te = tl_start + 2 + i * 8
            tag = raw[te:te+4]
            res_off, num_res = struct.unpack_from(">HH", raw, te + 4)
            print(f"  type: {tag} ({tag.decode('latin1','replace')}) res_offset={res_off} count={num_res}")
