import sys
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"

for fname in ["extras.mhk", "a_sounds.mhk"]:
    path = R.find_original(GAME + "\\" + fname)
    if not path:
        print(fname, "not found")
        continue
    arc = R.Archive(path)
    types = list(arc.types.keys())
    print(fname, "types:", [t.decode("latin1", "replace") for t in types])
    for tag, ids_dict in arc.types.items():
        label = tag.decode("latin1", "replace")
        ids = list(ids_dict.keys())
        print(f"  {label}: {ids[:20]}")
