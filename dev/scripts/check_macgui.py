"""Examine macgui.dat and look for .cur files in the game directory."""
import os, struct, zipfile

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
DAT = os.path.join(GAME, "macgui.dat")

print("=== macgui.dat ===")
with open(DAT, "rb") as f:
    header = f.read(8)
print("Header:", header.hex(), repr(header))

# Check if it's a ZIP
if zipfile.is_zipfile(DAT):
    print("It IS a ZIP file!")
    with zipfile.ZipFile(DAT) as z:
        for name in z.namelist():
            print(" ", name)
else:
    print("Not a ZIP. Scanning for paths...")
    with open(DAT, "rb") as f:
        data = f.read()
    # Look for .cur references
    import re
    for m in re.finditer(rb'[\x20-\x7e]{5,}', data):
        s = m.group().decode("ascii", "replace")
        if ".cur" in s.lower() or "cursor" in s.lower():
            print(f"  offset {m.start():#x}: {s!r}")

print("\n=== .cur files in game folder ===")
for root_dir, dirs, files in os.walk(GAME):
    for fn in files:
        if fn.lower().endswith(".cur") or fn.lower().endswith(".ani"):
            print(os.path.join(root_dir, fn))

print("\n=== gui-icons.dat header ===")
gui = os.path.join(GAME, "gui-icons.dat")
with open(gui, "rb") as f:
    h = f.read(16)
print(h.hex(), repr(h))
if zipfile.is_zipfile(gui):
    print("gui-icons.dat is a ZIP!")
    with zipfile.ZipFile(gui) as z:
        cur_files = [n for n in z.namelist() if ".cur" in n.lower() or "cursor" in n.lower()]
        print("Cursor files:", cur_files[:20])
