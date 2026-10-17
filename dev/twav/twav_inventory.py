"""Quick inventory of tWAV sounds across all archives."""
import sys, os, struct, types
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
_f = types.ModuleType("PIL"); _g = types.ModuleType("PIL.Image")
sys.modules.setdefault("PIL", _f); sys.modules.setdefault("PIL.Image", _g); _f.Image = _g
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

ENC = {0: "PCM", 1: "ADPC", 2: "MP2"}

for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    path = os.path.join(GAME, fn)
    try:
        arc = R.Archive(path)
    except Exception as e:
        continue
    ids = arc.ids(TWAV)
    if not ids:
        continue
    # Quick parse of first resource to get encoding
    d = arc.read(TWAV, ids[0])
    # Find DATA chunk
    pos = 12
    enc = "?"
    rate, ch, scount = 0, 0, 0
    while pos < len(d) - 8:
        tag = d[pos:pos+4]
        csz = struct.unpack_from(">I", d, pos+4)[0]
        if tag == b"Data":
            if pos+28 <= len(d):
                rate = struct.unpack_from(">H", d, pos+8)[0]
                scount = struct.unpack_from(">I", d, pos+10)[0]
                ch = d[pos+15]
                enc_code = struct.unpack_from(">H", d, pos+16)[0]
                enc = ENC.get(enc_code, f"?{enc_code}")
                break
        pos += 8 + csz
    dur = scount / rate if rate else 0
    total_size = sum(arc.read(TWAV, rid).__len__() for rid in ids)
    print(f"{fn:<25} {len(ids):3} sounds  enc={enc}  rate={rate}  ch={ch}  "
          f"dur~{dur:.1f}s  total={total_size//1024}KB")
