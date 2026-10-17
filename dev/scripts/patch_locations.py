"""Apply location reorganization changes to riven_gui.py."""
import sys

P = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven\riven_gui.py"
s = open(P, encoding="utf-8").read()


def rep(old, new, tag=""):
    global s
    cnt = s.count(old)
    assert cnt == 1, f"[{tag}] expected 1 match, got {cnt} for: {old[:80]!r}"
    s = s.replace(old, new)
    print(f"  OK  {tag or old[:60]!r}")


print("=== 1. LOC_RULES ===")

# Temple: remove 'guar' from Intro & cutscenes (guard cards go to Island paths by propagation)
rep('("intr|logo|guar", "Intro & cutscenes")',
    '("intr|logo", "Intro & cutscenes")',
    "t: remove guar from Intro")

# Jungle: rename Frog trap → Entry Cave (From Temple), Ytram trap → Maglev Exterior (From Temple)
rep('("ytr", "Ytram trap")',
    '("ytr", "Maglev Exterior (From Temple)")',
    "j: rename Ytram trap")
rep('("fro", "Frog trap")',
    '("fro", "Entry Cave (From Temple)")',
    "j: rename Frog trap")

# Jungle: capitalise Guard tower → Guard Tower, append dom rule for dome merge
rep('("b(tl|eet|tp)", "Beetles"), ("leve", "Guard tower")],',
    '("b(tl|eet|tp)", "Beetles"), ("leve", "Guard Tower"), ("dom", "Fire Marble Dome")],',
    "j: Guard Tower cap + dom->FMD")

# Boiler: append dom and scopes → Fire Marble Dome
rep('("bal", "Balcony path"), ("ste", "Steam pipes"), ("car|isma", "Maglev"), ("lmbr", "Lumber car")],',
    '("bal", "Balcony path"), ("ste", "Steam pipes"), ("car|isma", "Maglev"), ("lmbr", "Lumber car"), ("dom|sc[op]", "Fire Marble Dome")],',
    "b: dom+scopes->FMD")

print("\n=== 2. CARD_ID_RULES ===")

# Insert CARD_ID_RULES after CARD_NAME_RULES
CARD_ID_BLOCK = '''CARD_NAME_RULES = {"j": [("^jetunnel2village$", "Cave to the village (main path)")]}
# Card-ID-based overrides: highest priority, applied after all name/propagation rules.
# Each stack letter maps to a list of (frozenset_of_card_ids, location_name).
CARD_ID_RULES = {
    "t": [
        (frozenset(range(0, 46)) | frozenset(range(120, 125)), "Temple Cave"),
        (frozenset({97}), "Easter Eggs"),
        (frozenset({364, 480, 492, 657, 665}), "Lore Cards"),
    ],
    "j": [
        (frozenset(range(156, 190)), "Prison"),
        (frozenset({211, 213}) | frozenset(range(215, 249)), "Rebel Puzzle"),
        (frozenset(range(256, 317)), "Gallows"),
        (frozenset(range(317, 333)), "Guard Tower"),
        (frozenset({377}), "Jungle paths"),
        (frozenset({133}), "Easter Eggs"),
        (frozenset({767}), "D\'ni Number Game"),
    ],
}'''
rep('CARD_NAME_RULES = {"j": [("^jetunnel2village$", "Cave to the village (main path)")]}',
    CARD_ID_BLOCK,
    "insert CARD_ID_RULES")

print("\n=== 3. assign_locations override step ===")

# After the final place_cards() call, insert card-ID override
rep('    place_cards()\n\n\ndef tbmp_size',
    '''    place_cards()
    # Card-ID overrides: force specific card IDs (and their resources) to a fixed location.
    id_overrides = {}
    for cids, loc in CARD_ID_RULES.get(stack, []):
        for cid in cids:
            id_overrides[cid] = loc
    if id_overrides:
        for r in resources:
            m2 = re.match(r"([0-9]+)_", r.name)
            if m2 and int(m2.group(1)) in id_overrides:
                r.loc = id_overrides[int(m2.group(1))]
        for cid, c in cards.items():
            if cid in id_overrides:
                c.loc = id_overrides[cid]


def tbmp_size''',
    "assign_locations: add card-ID override")

print("\n=== 4. LOC_ORDER ===")

# Temple: add Temple Cave, Lore Cards, Easter Eggs
rep('    "Temple Island": ["Intro & cutscenes", "Gate Room", "Island paths & views", "Temple", "Old cave", "Tunnels",\n'
    '                      "Waffle iron", "Gehn\'s Imager", "Sub-Temple", "Bridges", "Elevator", "Maglev",\n'
    '                      "Fire Marble Dome", "Dome", "Scopes", "Telescope", "Endings"],',
    '    "Temple Island": ["Intro & cutscenes", "Gate Room", "Island paths & views", "Temple Cave", "Temple", "Old cave", "Tunnels",\n'
    '                      "Waffle iron", "Gehn\'s Imager", "Sub-Temple", "Bridges", "Elevator", "Maglev",\n'
    '                      "Fire Marble Dome", "Dome", "Scopes", "Telescope", "Lore Cards", "Easter Eggs", "Endings"],',
    "LOC_ORDER Temple")

# Jungle: full replacement (renames + adds + removes Dome)
rep('    "Jungle Island": ["Cave to the village (main path)", "Island paths & views", "Village", "Guard tower", "School",\n'
    '                      "Jungle paths", "Lagoon", "Clearcut", "Lumber car", "Submarine", "South path", "Throne",\n'
    '                      "Ytram trap", "Frog trap", "Beetles", "Elevator", "Rebel tunnels",\n'
    '                      "Crystal viewer (Rebel Age book)", "Maglev", "Fire Marble Dome", "Dome", "Scopes"],',
    '    "Jungle Island": ["Cave to the village (main path)", "Entry Cave (From Temple)", "Maglev Exterior (From Temple)",\n'
    '                      "Island paths & views", "Village", "Gallows", "Guard Tower", "Prison", "School",\n'
    '                      "D\'ni Number Game", "Jungle paths", "Lagoon", "Clearcut", "Lumber car", "Submarine",\n'
    '                      "South path", "Throne", "Beetles", "Elevator", "Rebel tunnels", "Rebel Puzzle",\n'
    '                      "Crystal viewer (Rebel Age book)", "Easter Eggs", "Maglev", "Fire Marble Dome", "Scopes"],',
    "LOC_ORDER Jungle")

# Boiler: merge Dome + Scopes into FMD (drop both from list)
rep('    "Boiler Island": ["Maglev", "Island paths & views", "Boiler", "Steam pipes", "Balcony path", "Ytram", "Crater",\n'
    '                      "Gehn\'s Lab", "Gehn", "Book depot", "Bridges", "Bridge to Temple Island", "Lumber car",\n'
    '                      "Fire Marble Dome", "Dome", "Scopes"],',
    '    "Boiler Island": ["Maglev", "Island paths & views", "Boiler", "Steam pipes", "Balcony path", "Ytram", "Crater",\n'
    '                      "Gehn\'s Lab", "Gehn", "Book depot", "Bridges", "Bridge to Temple Island", "Lumber car",\n'
    '                      "Fire Marble Dome"],',
    "LOC_ORDER Boiler")

open(P, "w", encoding="utf-8").write(s)
print("\n=== DONE — wrote", P)
