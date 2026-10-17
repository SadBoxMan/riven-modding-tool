import collections
import re
import sys

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
sys.path.insert(0, GAME)
import riven_gui as G

checks = [
    ("Boiler Island", r"b2book", "Bridge to Temple Island"),
    ("Boiler Island", r"bismagdepot", "Maglev"),
    ("Jungle Island", r"jtngb", "Crystal viewer (Rebel Age book)"),
    ("Jungle Island", r"^678_", "Cave to the village (main path)"),
    ("Gehn's Office", r"^9_o6[.]", "Bad endings"),
    ("Rebel Age", r"^2_r", "Bad endings"),
    ("Temple Island", r"^138_t1[.]", "Endings"),
    ("Temple Island", r"^159_t1[.]", "Intro & cutscenes"),
]
bad = 0
cache = {}
for area, pat, want in checks:
    title, files, _ = next(a for a in G.AREAS if a[0].startswith(area))
    if title not in cache:
        cache[title] = G.load_area(GAME, files, title)
    arcs, res, cards = cache[title]
    hits = [r for r in res if re.search(pat, r.name.lower())]
    wrong = [r for r in hits if r.loc != want]
    bad += bool(wrong) or not hits
    print(("OK   " if hits and not wrong else "FAIL ") + f"{area:14s} {pat:16s} -> {want}  ({len(hits)} items)"
          + ("" if not wrong else "  WRONG: " + str([(r.name, r.loc) for r in wrong][:4])))

# neighbours that must NOT have moved
t_arcs, t_res, t_cards = cache["Temple Island"]
by = {r.name: r.loc for r in t_res}
for r in t_res:
    if r.name.startswith("40_t1.") or r.name.startswith("322_t2500"):
        print("   neighbour:", r.name, "->", r.loc)
g = cache["Gehn's Office (233rd Age)"][1]
print("   other o6.* movies:", [(r.name, r.loc) for r in g if re.search(r"^[0-9]+_o6[.]", r.name) and not r.name.startswith("9_")])
rb = cache["Rebel Age (Tay)"][1]
print("   other rebel r*.* movies (sample):", collections.Counter(r.loc for r in rb if re.search(r"^[0-9]+_r[0-9]", r.name) and not r.name.startswith("2_")))
j = cache["Jungle Island"][1]
print("   j5.* sirens stay with their cards:", collections.Counter(r.loc for r in j if re.search(r"^[0-9]+_j5[.]", r.name)))
print("   card 678 location:", cache["Jungle Island"][2][678].loc)
print("\nFAILURES:", bad)
