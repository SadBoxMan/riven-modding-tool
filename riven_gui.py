#!/usr/bin/env python3
"""
riven_gui.py - browse, compare and replace Riven's images and movies, grouped by island.

  python riven_gui.py [game_folder]

Pick an area, select an image or movie, then compare the Original, the Current game version (if it has
been patched) and a New file you load. Changes are staged first and written in one go with
"Apply staged". All the archive work is done by riven_img.py (same folder).
"""
import atexit
import collections
import concurrent.futures as cf
import ctypes
import io
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = getattr(sys, "_MEIPASS", HERE)  # bundled-data root when frozen by PyInstaller
sys.path.insert(0, HERE)
import riven_img as R  # noqa: E402
import riven_layers as LY  # noqa: E402
import riven_help  # noqa: E402
from riven_help import TOPIC_NAMES, set_help_dark, show_help  # noqa: E402

# Archives per area, in ScummVM's lookup order (engines/mohawk/riven.cpp listExpectedDatafiles).
# b2_data.mhk is not in that list, so the game never loads it.
AREAS = [
    ("Temple Island", ["t_data2.mhk", "t_data1.mhk"], None),
    ("Jungle Island", ["j_data2.mhk", "j_data1.mhk"], None),
    ("Boiler Island", ["b_data.mhk"], None),
    ("Garden Island (Survey Island)", ["g_data.mhk"], None),
    ("Prison Island", ["p_data.mhk"], None),
    ("Gehn's Office (233rd Age)", ["o_data.mhk"], None),
    ("Rebel Age (Tay)", ["r_data.mhk"], None),
    ("Inventory, Marbles & Credits", ["extras.mhk"], None),
    ("Menus & Journals", ["a_data.mhk"],
     "Same-size mode: ScummVM recognises the game by this archive's exact size and first bytes, so an edited "
     "image here is re-encoded into the original's own space, with the original's 256 colours (about 3% to "
     "spare). Images only; movies and ID mode aren't available here."),
]
# Locations inside an area, from the code in resource names ("166_tgr_s1..." -> stack 't', code 'gr').
# A rule is (regex matched at the START of the code with the stack letter removed, location). First match wins.
# Items no rule names are placed by where their card sits (see assign_locations), else listed under "Other".
LOC_RULES = {
    "t": [("gr|bug", "Gate Room"), ("sub", "Sub-Temple"), ("tem|tmp", "Temple"),
          ("tl|tel(?!v)", "Telescope"), ("im[ag]", "Gehn's Imager"),
          ("br|supb|look|pw(r)?v", "Bridges"), ("w(af|ff|i)", "Waffle iron"),
          ("d?elev?|elv|tn(el|lb)", "Elevator"), ("otd|old", "Old cave"),
          ("intr|logo", "Intro & cutscenes"), ("isl|isex|ext", "Island paths & views"), ("tun", "Tunnels")],
    "j": [("tngb", "Crystal viewer (Rebel Age book)"),
          ("v", "Village"), ("sch", "School"), ("lag", "Lagoon"), ("sb|sub|insu", "Submarine"),
          ("ytr", "Maglev Exterior (From Temple)"), ("fro", "Entry Cave (From Temple)"), ("g?thr|th(dn|up)|inth|tgal|tfmd", "Throne"),
          ("sou", "South path"), ("jun", "Jungle paths"), ("is[jl]", "Island paths & views"),
          ("ic|r(eb|tic|tal|teo|twa|prm|bt)", "Rebel tunnels"), ("clea|cc", "Clearcut"),
          ("lum|lcar|lmbr", "Lumber car"), ("ev(s|l|m)|tmel|tmev|totm", "Elevator"),
          ("b(tl|eet|tp)", "Beetles"), ("leve", "Guard Tower"), ("dom", "Fire Marble Dome")],
    "b": [("boi|blr|fl", "Boiler"), ("cra", "Crater"), ("g?lab|lbd", "Gehn's Lab"), ("y(t|c)", "Ytram"),
          ("br", "Bridges"), ("isl", "Island paths & views"), ("geh", "Gehn"), ("ook", "Book depot"),
          ("bal", "Balcony path"), ("ste", "Steam pipes"), ("car|isma", "Maglev"), ("lmbr", "Lumber car"), ("dom|sc[op]", "Fire Marble Dome")],
    "g": [("pla|[a-z]*poolz", "Plateau"), ("lak", "Lake"), ("wha", "Wahrk"), ("el[ev]|sube|ptel", "Elevators"),
          ("pin", "Pin table (topography)"), ("fou|fnt", "Fountain"), ("w(sc|ks)", "Scopes")],
    "p": [("isl", "Island paths & views"), ("el[ev]", "Elevator"), ("pri|cls|opn", "Prison cell")],
    "o": [("[pjgbt](bk|bo|fl)|book|fmd(bo|bk|fl)", "Linking books"), ("off", "Office"), ("bed", "Bedroom"), ("cag", "Cage"),
          ("des|drw", "Desk")],
    "r": [("reb|prm", "Rebel village"), ("ent", "Entrance")],
    "a": [("cat", "Catherine's journal"), ("tra", "Trap book"), ("atr", "Atrus's journal"),
          ("riv|mon|vol", "Main menu & options"), ("bla", "Black screens")],
}
COMMON_RULES = [("fmd|slid", "Fire Marble Dome"), ("[a-z]?(mag|mg(ca|bt|jg|tm|t))|nomg", "Maglev"),
                ("dom|opni|clsi", "Dome"), ("sc[op]", "Scopes")]
# rules on the whole name, for things the code can't tell apart ("159_t1.0" is the cage scene, a cutscene).
# Facts from Boss: b2book = the Boiler-Temple bridge; 9_o6.* = Gehn's office bad endings (trapping yourself, or
# freeing Gehn from the trap book); 2_r* = the Rebel Age bad endings; 138_t1.* = the Star Fissure endings.
NAME_RULES = {
    "t": [("^138_t1[.]", "Endings"), ("^[0-9]+_t1[.][0-9a-z]", "Intro & cutscenes")],
    "b": [("^[0-9]+_b2book", "Bridge to Temple Island")],
    "o": [("^9_o6[.]", "Bad endings")],
    "r": [("^2_r[0-9]", "Bad endings")],
}
# rules on a CARD's own name (the NAME resource), applied to the card itself
CARD_NAME_RULES = {"j": [("^jetunnel2village$", "Cave to the village (main path)")]}
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
        (frozenset({211, 213}) | frozenset(range(215, 226)) | frozenset(range(228, 249)), "Rebel Puzzle"),  # excl 226-227 (crystal tunnel cards)
        (frozenset(range(256, 317)), "Gallows"),
        (frozenset(range(317, 333)), "Guard Tower"),
        (frozenset({377}), "Jungle paths"),
        (frozenset({133}), "Easter Eggs"),
        (frozenset({767}), "D'ni Number Game"),
    ],
}
SHARED = "Shared (linking books, domes, fades)"

# The order locations are listed in (and the Location column sorts by), following a typical playthrough: where
# you arrive or the hub first, then outward through the island, puzzle-heavy and transit places later, endings
# last, shared pieces at the bottom. This is a best guess at a route, not a script: edit the lists to taste.
# Anything not listed goes after the listed ones, alphabetically. Islands themselves are ordered by AREAS.
LOC_ORDER = {
    "Temple Island": ["Intro & cutscenes", "Gate Room", "Island paths & views", "Temple Cave", "Temple", "Old cave", "Tunnels",
                      "Waffle iron", "Gehn's Imager", "Sub-Temple", "Bridges", "Elevator", "Maglev",
                      "Fire Marble Dome", "Dome", "Scopes", "Telescope", "Lore Cards", "Easter Eggs", "Endings"],
    "Jungle Island": ["Cave to the village (main path)", "Entry Cave (From Temple)", "Maglev Exterior (From Temple)",
                      "Island paths & views", "Village", "Gallows", "Guard Tower", "Prison", "School",
                      "D'ni Number Game", "Jungle paths", "Lagoon", "Clearcut", "Lumber car", "Submarine",
                      "South path", "Throne", "Beetles", "Elevator", "Rebel tunnels", "Rebel Puzzle",
                      "Crystal viewer (Rebel Age book)", "Easter Eggs", "Maglev", "Fire Marble Dome", "Scopes"],
    "Boiler Island": ["Maglev", "Island paths & views", "Boiler", "Steam pipes", "Balcony path", "Ytram", "Crater",
                      "Gehn's Lab", "Gehn", "Book depot", "Bridges", "Bridge to Temple Island", "Lumber car",
                      "Fire Marble Dome"],
    "Garden Island (Survey Island)": ["Maglev", "Plateau", "Elevators", "Lake", "Wahrk", "Fountain",
                                      "Pin table (topography)", "Scopes", "Fire Marble Dome", "Dome"],
    "Prison Island": ["Island paths & views", "Elevator", "Prison cell", "Fire Marble Dome", "Dome", "Scopes"],
    "Gehn's Office (233rd Age)": ["Linking books", "Office", "Desk", "Bedroom", "Cage", "Bad endings",
                                  "Fire Marble Dome"],
    "Rebel Age (Tay)": ["Entrance", "Rebel village", "Bad endings"],
    "Inventory, Marbles & Credits": ["Inventory icons", "Marbles", "Credits"],
    "Menus & Journals": ["Main menu & options", "Atrus's journal", "Catherine's journal", "Trap book",
                         "Black screens"],
}


def loc_sort_key(area, loc):
    """Sort key putting an area's locations in playthrough order; shared pieces last of the named ones."""
    order = LOC_ORDER.get(area, [])
    if loc in order:
        return (0, order.index(loc), "")
    if loc == SHARED:
        return (1, 0, "")
    return (0, len(order), loc.lower())
EXTRAS_RANGES = [(100, 199, "Inventory icons"), (200, 299, "Marbles"), (300, 499, "Credits")]
OTHER = "Other: "


def location_of(stack, r):
    if stack == "extras":
        return next((lbl for lo, hi, lbl in EXTRAS_RANGES if lo <= r.rid <= hi), OTHER + "misc")
    m = re.match(r"^\d+_([a-z]+)", r.name.lower())
    if not m:
        return OTHER + "unnamed"
    code = m.group(1)
    for pat, lbl in NAME_RULES.get(stack, []):
        if re.match(pat, r.name.lower()):
            return lbl
    if code[0] == "a" and stack != "a":
        return SHARED
    rest = code[1:] if code[0] == stack else code
    for pat, lbl in LOC_RULES.get(stack, []) + COMMON_RULES:
        if re.match(pat, rest):
            return lbl
    return OTHER + code[:5]


VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".webm", ".mpg", ".mpeg", ".mxf"}
MANIFEST = ".riven_export.json"   # written by "Export area"; unchanged files are skipped when staging a folder
REVERT = "<revert>"
# one cache folder per running instance, so two open copies of the tool never wipe each other's files
CACHE_DIR = os.path.join(tempfile.gettempdir(), f"riven_gui_cache_{os.getpid()}")


def _clean_old_caches():
    """Remove cache folders left behind by instances that crashed (untouched for two days)."""
    base = tempfile.gettempdir()
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if name.startswith("riven_gui_cache") and p != CACHE_DIR:
            try:
                if time.time() - os.path.getmtime(p) > 2 * 86400:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass
KIND_NAMES = {R.TBMP: "image", R.TMOV: "movie"}


# ---------------------------------------------------------------- path hiding (for streaming)
def scrub_paths(text, game_dir=""):
    """Replace file paths in `text` with short names, so nothing identifying shows on screen."""
    return DRIVE_PATH.sub(lambda m: m.group(1), text)   # "C:/any/folders/file.png" -> "file.png"


# A drive path: folders may contain spaces, the last part (the file name) may not. Built from chr() so the
# source has no backslashes to get wrong. SEP matches a backslash or a slash.
_BS, _NO = chr(92), chr(34) + chr(39) + chr(10) + chr(13) + ":*?<>|"
_SEP = "[" + _BS * 2 + "/]+"      # one or more: Python's own error messages double the backslashes
DRIVE_PATH = re.compile("(?<![A-Za-z0-9_])[A-Za-z]:" + _SEP + "(?:[^" + _BS * 2 + "/" + _NO + "]+" + _SEP + ")*([^" + _BS * 2 + "/ " + _NO + "]+)")


# ---------------------------------------------------------------- settings + theme
SETTINGS = os.path.join(os.environ.get("APPDATA", HERE), "RivenModTool", "settings.json")
CUSTOM_NAMES = os.path.join(os.environ.get("APPDATA", HERE), "RivenModTool", "custom_names.json")


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(**changes):
    s = load_settings()
    s.update(changes)
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w") as f:
            json.dump(s, f, indent=1)
    except OSError:
        pass


def load_custom_names():
    try:
        with open(CUSTOM_NAMES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_custom_names(names):
    try:
        os.makedirs(os.path.dirname(CUSTOM_NAMES), exist_ok=True)
        with open(CUSTOM_NAMES, "w") as f:
            json.dump(names, f, indent=1, sort_keys=True)
    except OSError:
        pass


def note_key(r):
    return f"{r.archive}|{r.tag.decode()}|{r.rid}"


CURSOR_PATH = os.path.join(os.environ.get("APPDATA", HERE), "RivenModTool", "riven_cursor.cur")


def _save_cur_file(img, path, hotspot=(0, 0)):
    """Write a PIL RGBA image as a Windows .cur file (32-bit BGRA DIB)."""
    w, h = img.size
    raw = img.tobytes("raw", "RGBA")
    pixels = [tuple(raw[i:i+4]) for i in range(0, len(raw), 4)]
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = pixels[y * w + x]
            xor += bytes([b, g, r, a])
    row_bytes = (w + 31) // 32 * 4
    and_mask = bytearray(row_bytes * h)
    for y in range(h):
        inv_y = h - 1 - y
        for x in range(w):
            if pixels[y * w + x][3] < 128:
                and_mask[inv_y * row_bytes + x // 8] |= 1 << (7 - x % 8)
    bih = struct.pack("<IIiHHIIIIII", 40, w, h * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0)
    img_data = bih + bytes(xor) + bytes(and_mask)
    header = struct.pack("<HHH", 0, 2, 1)
    dir_entry = struct.pack("<BBBBHHIi", min(w, 255), min(h, 255), 0, 0,
                            hotspot[0], hotspot[1], len(img_data), 22)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(header + dir_entry + img_data)


def _create_riven_cursor():
    """Return a path to the Riven cursor .cur file, extracting/copying it once if needed.

    Search order:
      1. cursors/NORMAL.cur alongside this script (user-supplied set)
      2. CURSOR128 extracted from macgui.dat (bundled with ScummVM)
      3. Generated black arrow (PIL fallback)
    """
    if os.path.exists(CURSOR_PATH):
        return CURSOR_PATH
    # 1. User-supplied cursors folder next to this script
    local_cur = os.path.join(DATA_PATH, "cursors", "NORMAL.cur")
    if os.path.exists(local_cur):
        try:
            os.makedirs(os.path.dirname(CURSOR_PATH), exist_ok=True)
            import shutil as _sh
            _sh.copy2(local_cur, CURSOR_PATH)
            return CURSOR_PATH
        except Exception:
            pass
    # 2. Extract from macgui.dat
    import zipfile
    macgui = os.path.join(DATA_PATH, "macgui.dat")
    try:
        if os.path.exists(macgui) and zipfile.is_zipfile(macgui):
            with zipfile.ZipFile(macgui) as z:
                cur_data = z.read("qtvr/CURSOR128_1.cur")
            os.makedirs(os.path.dirname(CURSOR_PATH), exist_ok=True)
            with open(CURSOR_PATH, "wb") as f:
                f.write(cur_data)
            return CURSOR_PATH
    except Exception:
        pass
    # 3. Generate a minimal black arrow cursor
    try:
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        arrow = [(0, 0), (0, 20), (5, 15), (9, 24), (11, 23), (7, 14), (14, 14)]
        d.polygon(arrow, fill=(0, 0, 0, 255))
        d.polygon(arrow, outline=(255, 255, 255, 255))
        _save_cur_file(img, CURSOR_PATH, hotspot=(0, 0))
    except Exception:
        return None
    return CURSOR_PATH


# list colours that stay readable on each background
TAG_COLORS = {
    False: {"patched": "#1060c0", "staged": "#c06000", "label": "#9030a0", "locked": "#a00000",
            "changed": "#1060c0", "warn": "#b00000"},
    True: {"patched": "#6fa8ff", "staged": "#ffa64d", "label": "#d79bff", "locked": "#ff7a7a",
           "changed": "#6fa8ff", "warn": "#ff7a7a"},
}
DARK = {"bg": "#1f2125", "panel": "#2a2d33", "field": "#25282d", "fg": "#e3e5e8", "muted": "#7d838c",
        "sel": "#2f6fb5", "border": "#3a3f46", "hover": "#33373e"}


def set_titlebar_dark(win, dark):
    """Windows 10 (20H1+) / 11: ask DWM for a dark title bar on this toplevel."""
    if os.name != "nt":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10 builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
        if win.state() == "normal":  # nudge the size so the title bar repaints right away
            w, h = win.winfo_width(), win.winfo_height()
            win.geometry(f"{w + 1}x{h}")
            win.update_idletasks()
            win.geometry(f"{w}x{h}")
    except Exception:
        pass


riven_help.titlebar_hook = set_titlebar_dark


def apply_ttk_theme(root, dark, light_theme):
    """Dark: the 'clam' theme recoloured (Windows' native theme can't be recoloured). Light: the native theme."""
    s = ttk.Style(root)
    if not dark:
        s.theme_use(light_theme)
        root.configure(background=s.lookup(".", "background") or "SystemButtonFace")
        return
    c = DARK
    s.theme_use("clam")
    s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"], bordercolor=c["border"],
                lightcolor=c["panel"], darkcolor=c["border"], troughcolor=c["panel"], selectbackground=c["sel"],
                selectforeground="#ffffff", insertcolor=c["fg"], focuscolor=c["sel"], arrowcolor=c["fg"])
    s.map(".", foreground=[("disabled", c["muted"])], background=[("disabled", c["bg"])])
    s.configure("TButton", background=c["panel"], padding=(3, 1))
    s.map("TButton", background=[("pressed", c["border"]), ("active", c["hover"]), ("disabled", c["bg"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, background=c["bg"], indicatorbackground=c["field"], indicatorforeground=c["fg"])
        s.map(w, background=[("active", c["bg"])], indicatorbackground=[("selected", c["sel"]), ("pressed", c["sel"])],
              indicatorforeground=[("selected", "#ffffff")])
    s.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"],
                bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"])
    s.map("Treeview", background=[("selected", c["sel"])], foreground=[("selected", "#ffffff")])
    s.configure("Treeview.Heading", background=c["panel"], foreground=c["fg"], relief="flat",
                bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["panel"])
    s.map("Treeview.Heading", background=[("active", c["hover"])])
    s.configure("TCombobox", fieldbackground=c["field"], background=c["panel"], foreground=c["fg"])
    s.map("TCombobox", fieldbackground=[("readonly", c["field"]), ("disabled", c["bg"])],
          foreground=[("disabled", c["muted"])], background=[("active", c["hover"])],
          selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])])
    s.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"])
    s.configure("TScrollbar", background=c["panel"], troughcolor=c["bg"], bordercolor=c["bg"],
                lightcolor=c["panel"], darkcolor=c["panel"], arrowcolor=c["fg"])
    s.map("TScrollbar", background=[("active", c["hover"])])
    s.configure("TProgressbar", background=c["sel"], troughcolor=c["panel"])
    s.configure("Horizontal.TScale", background=c["panel"], troughcolor=c["field"])
    s.configure("Sash", background=c["border"], sashthickness=6, gripcount=0)
    root.configure(background=c["bg"])


def style_combobox_list(cb, dark):
    """The dropdown list of a combobox is a plain Tk listbox; colour it to match."""
    try:
        lb = f"{cb.tk.call('ttk::combobox::PopdownWindow', cb)}.f.l"
        if dark:
            cb.tk.call(lb, "configure", "-background", DARK["field"], "-foreground", DARK["fg"],
                       "-selectbackground", DARK["sel"], "-selectforeground", "#ffffff")
        else:
            cb.tk.call(lb, "configure", "-background", "SystemWindow", "-foreground", "SystemWindowText",
                       "-selectbackground", "SystemHighlight", "-selectforeground", "SystemHighlightText")
    except tk.TclError:
        pass


class Res:
    __slots__ = ("archive", "tag", "rid", "name", "note", "cards", "card_ids", "patched", "label", "area", "loc")

    def key(self):
        return (self.archive, self.tag, self.rid)


class Card:
    """A card ("screen"): its pictures (PLST) and movies (MLST) with their on-screen positions."""
    __slots__ = ("cid", "name", "pics", "draws", "movs", "area", "loc", "hspts")
    # pics:  [(plst index, tBMP id, (left, top, right, bottom))]   picture list (states of the view)
    # draws: [(tBMP id, (left, top))]                              drawn by card/hotspot scripts
    # movs:  [(mlst index, tMOV id, (left, top))]
    # hspts: [(l, t, r, b, name, enabled, frozenset(jump_card_ids), raw_scripts)]  clickable regions from HSPT


SCREEN_W, SCREEN_H = 608, 392   # Riven's picture area

SCRIPT_EVENTS = {1: "mouseDown", 2: "mouseDrag", 3: "mouseUp", 4: "mouseEnter", 5: "mouseLeave"}
SCRIPT_OPCODES = {1: "drawBitmap", 2: "goToCard", 8: "switch", 27: "changeStack"}


# Riven scripts (engines/mohawk/riven_scripts.cpp): a script list is u16 count + (u16 type, script);
# a script is u16 count + commands; a command is u16 type then
#   8 (switch):        u16 2, u16 variable, u16 branches, each: u16 value + script
#   27 (change stack): u16 argsize, u16 stack, u32 global card id
#   anything else:     u16 argc + argc x u16.   Type 1 = drawBitmap(tBMP id, left, top, right, bottom, ...)
def _script_list(d, p, out):
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        p = _script(d, p + 2, out)
    return p


def _script(d, p, out):
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        t, = struct.unpack_from(">H", d, p)
        p += 2
        if t == 8:
            _, _, branches = struct.unpack_from(">3H", d, p)
            p += 6
            for _ in range(branches):
                p = _script(d, p + 2, out)
        elif t == 27:
            p += 8
        else:
            argc, = struct.unpack_from(">H", d, p)
            args = struct.unpack_from(f">{argc}H", d, p + 2)
            p += 2 + 2 * argc
            if t == 1 and args:
                out.add((args[0], (args[1], args[2]) if argc >= 5 else (0, 0)))
    return p


def _jumps_in_script_list(d, p, out):
    """Walk a script list collecting goToCard (opcode 2) destination card IDs into out."""
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        p = _jumps_in_script(d, p + 2, out)
    return p


def _jumps_in_script(d, p, out):
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        t, = struct.unpack_from(">H", d, p)
        p += 2
        if t == 8:
            _, _, branches = struct.unpack_from(">3H", d, p)
            p += 6
            for _ in range(branches):
                p = _jumps_in_script(d, p + 2, out)
        elif t == 27:
            p += 8
        else:
            argc, = struct.unpack_from(">H", d, p)
            args = struct.unpack_from(f">{argc}H", d, p + 2)
            p += 2 + 2 * argc
            if t == 2 and args:
                out.add(args[0])
    return p


def _fmt_script_list(raw):
    """Decode raw script-list bytes, return list of (event_name, [cmd_line]) pairs."""
    result = []
    try:
        d, p = raw, 0
        n, = struct.unpack_from(">H", d, p); p += 2
        for _ in range(n):
            ev, = struct.unpack_from(">H", d, p); p += 2
            lines, p = _fmt_script(d, p, 0)
            result.append((SCRIPT_EVENTS.get(ev, f"event{ev}"), lines))
    except struct.error:
        pass
    return result


def _fmt_script(d, p, depth):
    """Decode one script body (command count + commands); return (lines, end_pos)."""
    indent = "  " * depth
    lines = []
    try:
        n, = struct.unpack_from(">H", d, p); p += 2
        for _ in range(n):
            t, = struct.unpack_from(">H", d, p); p += 2
            if t == 8:
                _, var_id, branches = struct.unpack_from(">3H", d, p); p += 6
                lines.append(f"{indent}switch(var{var_id}):")
                for _ in range(branches):
                    val, = struct.unpack_from(">H", d, p); p += 2
                    sub, p = _fmt_script(d, p, depth + 1)
                    lines.append(f"{indent}  [{val}]:")
                    lines.extend(sub)
            elif t == 27:
                _, stack_id, gid = struct.unpack_from(">HHI", d, p); p += 8
                lines.append(f"{indent}changeStack(stack={stack_id}, gid=0x{gid:08x})")
            else:
                argc, = struct.unpack_from(">H", d, p)
                args = struct.unpack_from(f">{argc}H", d, p + 2); p += 2 + 2 * argc
                name = SCRIPT_OPCODES.get(t, f"op{t}")
                lines.append(f"{indent}{name}({', '.join(str(a) for a in args)})")
    except struct.error:
        pass
    return lines, p


def parse_hotspots(data, card_names=()):
    """Parse HSPT into [(l, t, r, b, name, enabled, frozenset(jump_card_ids), raw_scripts)] tuples.
    card_names is the NAME resource list; name_rec -1 means no name."""
    if not data:
        return []
    out = []
    try:
        n, = struct.unpack_from(">H", data, 0)
        p = 2
        for _ in range(n):
            # 22-byte record: blst_id(u16), name_rec(s16), l/t/r/b(4xs16), u0/cursor/index/u1/enabled(5xu16)
            blst_id, name_rec, l, t, r, b, _u0, _cur, _idx, _u1, enabled = struct.unpack_from(">HhhhhhHHHHH", data, p)
            name = card_names[name_rec] if 0 <= name_rec < len(card_names) else ""
            script_start = p + 22
            jumps = set()
            p = _jumps_in_script_list(data, script_start, jumps)
            out.append((l, t, r, b, name, bool(enabled), frozenset(jumps), data[script_start:p]))
    except struct.error:
        pass
    return out


def card_script_draws(card_data, hspt_data):
    """{(tBMP id, (left, top))} drawn by a card's own scripts and its hotspots' scripts."""
    out = set()
    try:
        _script_list(card_data, 4, out)  # CARD: s16 name, u16 zip-mode place, scripts
        if hspt_data:
            n, = struct.unpack_from(">H", hspt_data, 0)
            p = 2
            for _ in range(n):  # hotspot: 22-byte record, then its scripts
                p = _script_list(hspt_data, p + 22, out)
    except struct.error:
        pass  # malformed script: keep what was found
    return out


def composite(base, layers):
    """Draw `layers` [(image, (x, y))] over `base` (a full-screen image, or black), like ScummVM's
    copyImageToScreen: opaque, at the image's own size, clipped to the 608px screen width."""
    out = base.copy() if base is not None else Image.new("RGB", (SCREEN_W, SCREEN_H))
    for img, (x, y) in layers:
        if img is not None and x < SCREEN_W:
            out.paste(img.crop((0, 0, min(img.width, SCREEN_W - x), img.height)), (x, y))
    return out


def parse_name_list(data):
    n, = struct.unpack(">H", data[:2])
    offs = struct.unpack(f">{n}H", data[2:2 + 2 * n])
    base = 2 + 4 * n
    out = []
    for o in offs:
        end = data.index(b"\0", base + o)
        s = data[base + o:end].decode("latin-1")
        out.append("".join(ch for ch in s if ch.isprintable() and ch.isascii()).strip())
    return out


def load_area(game_dir, files, title=""):
    """Parse an area's archives: resources, patch state, and which cards use each image/movie."""
    archives, resources = {}, []
    card_name_idx, pic_cards, mov_cards, card_names = {}, {}, {}, []
    card_pics, card_movs, card_draws, card_hspts_raw = {}, {}, {}, {}
    for fn in files:
        path = os.path.join(game_dir, fn)
        if not os.path.exists(path):
            continue
        orig = R.Archive(R.find_original(path))
        cur = R.Archive(path) if os.path.exists(path + ".orig") else orig
        first_new = len(orig.files) + 2 if cur.abs_offset != orig.abs_offset else None
        archives[fn] = (orig, cur)
        labels = load_labels(path)
        inplace = R.inplace_changed(path) if R.is_inplace(fn) else None   # same-size mode: compare slots
        if 1 in cur.types.get(b"NAME", {}):
            card_names = parse_name_list(cur.read(b"NAME", 1))
        for cid in cur.types.get(b"CARD", {}):
            card_data = cur.read(b"CARD", cid)
            card_name_idx[cid], = struct.unpack(">h", card_data[:2])
            hspt = cur.read(b"HSPT", cid) if cid in cur.types.get(b"HSPT", {}) else b""
            if hspt:
                card_hspts_raw[cid] = hspt   # resolved to Card.hspts after card_names is fully built
            for pid, xy in card_script_draws(card_data, hspt):  # images placed by scripts, not the PLST
                pic_cards.setdefault(pid, set()).add(cid)
                card_draws.setdefault(cid, set()).add((pid, xy))
            if cid in cur.types.get(b"PLST", {}):  # records: index, tBMP id, left, top, right, bottom
                d = cur.read(b"PLST", cid)
                for i in range(struct.unpack(">H", d[:2])[0]):
                    idx, pid, l, t, r, b = struct.unpack(">6H", d[2 + i * 12:14 + i * 12])
                    pic_cards.setdefault(pid, set()).add(cid)
                    card_pics.setdefault(cid, []).append((idx, pid, (l, t, r, b)))
            if cid in cur.types.get(b"MLST", {}):  # records: index, tMOV id, slot, left, top, ... (22 bytes)
                d = cur.read(b"MLST", cid)
                for i in range(struct.unpack(">H", d[:2])[0]):
                    idx, mid, _slot, l, t = struct.unpack(">5H", d[2 + i * 22:12 + i * 22])
                    mov_cards.setdefault(mid, set()).add(cid)
                    card_movs.setdefault(cid, []).append((idx, mid, (l, t)))
        for tag in (R.TBMP, R.TMOV):
            for rid in orig.ids(tag):
                r = Res()
                r.archive, r.tag, r.rid = fn, tag, rid
                r.name = orig.names.get((tag, rid), "")
                r.note = ""   # filled in by App.load_all() from custom_names.json
                r.patched = (tag, rid) in inplace if inplace is not None else \
                    bool(first_new and cur.types[tag][rid] >= first_new)
                r.label = r.patched and (tag, rid) in labels
                r.cards = sorted((pic_cards if tag == R.TBMP else mov_cards).get(rid, ()))
                resources.append(r)

    def card_label(cid):
        i = card_name_idx.get(cid, -1)
        return f"{cid} ({card_names[i]})" if 0 <= i < len(card_names) and card_names[i] else str(cid)

    stack = "extras" if files == ["extras.mhk"] else files[0][0]
    for r in resources:  # cards were collected across all archives of the area
        r.card_ids = sorted((pic_cards if r.tag == R.TBMP else mov_cards).get(r.rid, ()))
        r.cards = [card_label(c) for c in r.card_ids]
        r.area, r.loc = title, location_of(stack, r)

    by_id = {(r.tag, r.rid): r for r in resources}
    cards = {}
    for cid in sorted(set(card_pics) | set(card_movs) | set(card_draws) | set(card_name_idx)):
        c = Card()
        c.cid, c.area = cid, title
        c.pics, c.movs = sorted(card_pics.get(cid, [])), sorted(card_movs.get(cid, []))
        c.draws = sorted(card_draws.get(cid, ()))
        i = card_name_idx.get(cid, -1)
        c.name = card_names[i] if 0 <= i < len(card_names) else ""
        c.hspts = parse_hotspots(card_hspts_raw.get(cid, b""), card_names)
        c.loc = OTHER + "empty"
        cards[cid] = c
    assign_locations(resources, cards, by_id, stack)
    return archives, resources, cards


def is_named(loc):
    return loc != SHARED and not loc.startswith(OTHER)


def assign_locations(resources, cards, by_id, stack=""):
    """Give every card a location (what most of its items are, or its own name's rule), then give items the
    rules couldn't name the location of the card their file name points at ("15_tdd_mg_1" -> card 15), else of
    the cards that use them."""
    def items_of(c):
        keys = [(R.TBMP, p) for _, p, _ in c.pics] + [(R.TBMP, p) for p, _ in c.draws] + \
               [(R.TMOV, m) for _, m, _ in c.movs]
        return [by_id[k] for k in dict.fromkeys(keys) if k in by_id]

    def place_cards():
        for c in cards.values():
            locs = [i.loc for i in items_of(c)]
            pick = [x for x in locs if is_named(x)] or locs
            c.loc = collections.Counter(pick).most_common(1)[0][0] if pick else OTHER + "empty"
            for pat, lbl in CARD_NAME_RULES.get(stack, []):
                if re.match(pat, c.name):
                    c.loc = lbl

    for _ in range(3):
        place_cards()
        moved = False
        for r in resources:
            if is_named(r.loc) or r.loc == SHARED:
                continue
            votes = collections.Counter()
            m = re.match(r"([0-9]+)_", r.name)
            home = cards.get(int(m.group(1))) if m else None
            if home and is_named(home.loc):
                votes[home.loc] += 3
            for cid in r.card_ids:
                c = cards.get(cid)
                if c and is_named(c.loc):
                    votes[c.loc] += 1
            if votes:
                r.loc = votes.most_common(1)[0][0]
                moved = True
        if not moved:
            break
    place_cards()
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


def tbmp_size(data):
    w, h = struct.unpack(">HH", data[:4])
    return w & 0x3FFF, h & 0x3FFF


def grab_frame(path, t):
    out = subprocess.run([R._tool("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, **R.NOWIN).stdout
    if not out:  # past the last frame: take the very last one
        out = subprocess.run([R._tool("ffmpeg"), "-v", "error", "-sseof", "-0.2", "-i", path, "-update", "1",
                              "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, **R.NOWIN).stdout
    return Image.open(io.BytesIO(out)).convert("RGB") if out else None


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, **R.NOWIN).stdout
    except OSError:
        return False
    out = out.lower()
    return "scummvm.exe" in out or "riven.exe" in out


# ---------------------------------------------------------------- ID mode
# Stamps every image/movie of an island with its resource id, to find ids in-game. Which resources carry a
# label (rather than a real edit) is kept in "<archive>.idlabels.json", so labels never mix with real edits.

def labels_path(path):
    return path + ".idlabels.json"


def load_labels(path):
    try:
        with open(labels_path(path)) as f:
            return {(t.encode(), int(r)) for t, r in json.load(f)}
    except (OSError, ValueError):
        return set()


def save_labels(path, labels):
    if labels:
        with open(labels_path(path), "w") as f:
            json.dump(sorted([t.decode(), r] for t, r in labels), f)
    elif os.path.exists(labels_path(path)):
        os.remove(labels_path(path))


def label_prefix(archive):
    """'t_data1.mhk' -> 'T1', 'b_data.mhk' -> 'B', 'extras.mhk' -> 'X'."""
    m = re.match(r"([a-z])_data(\d*)\.mhk$", archive)
    return (m.group(1) + m.group(2)).upper() if m else "X"


def stamp(img, text, color):
    """Border + centered id text (text skipped when the image is too small to hold it)."""
    w, h = img.size
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=color, width=max(1, min(w, h) // 60))
    size = min(48, w // 8, h // 3)
    if size >= 8:
        font = ImageFont.truetype(os.path.join(HERE, "FreeSans.ttf"), size)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        x, y = (w - (r - l)) // 2, (h - (b - t)) // 2
        d.rectangle([x - 4, y - 4 + t, x + (r - l) + 4, y + b + 4], fill=(0, 0, 0, 255))
        d.text((x, y), text, font=font, fill=color)
    return img


def _label_image_job(args):  # top level so a process pool can run it
    path, rid, text = args
    try:
        img = R.decode_tbmp(R.Archive(path).read(R.TBMP, rid))
        return rid, R.encode_tbmp_24(stamp(img, text, (255, 40, 40))), None
    except Exception as e:
        return rid, None, str(e)


def _label_movie_job(args):
    path, rid, text = args
    try:
        ref = R.Archive(path).read_movie(rid)
        with tempfile.TemporaryDirectory() as td:
            src, lab, mid = (os.path.join(td, n) for n in ("src.mov", "label.png", "mid.mkv"))
            with open(src, "wb") as f:
                f.write(ref)
            v = R.probe_movie(src)[0]
            stamp(Image.new("RGBA", (v["width"], v["height"]), (0, 0, 0, 0)), text, (255, 220, 0, 255)).save(lab)
            subprocess.run([R._tool("ffmpeg"), "-v", "error", "-y", "-i", src, "-i", lab, "-filter_complex",
                            "[0:v][1:v]overlay=0:0", "-c:v", "ffv1", "-c:a", "pcm_s16le", mid], check=True, **R.NOWIN)
            return rid, R.encode_movie(mid, ref), None
    except Exception as e:
        return rid, None, str(e)


def _export_image(args):  # top level so a process pool can run it
    path, rid, out = args
    R.decode_tbmp(R.Archive(path).read(R.TBMP, rid)).save(out)
    return out


def out_name(r, ext):
    name = os.path.splitext(r.name)[0] if r.name.lower().endswith(".mov") else r.name
    return f"{r.rid}" + (f"_{R._safe(name)}" if name else "") + ext


class App:
    def __init__(self, root, game_dir):
        self.root, self.game_dir = root, game_dir
        self.q = queue.Queue()
        self.pool = cf.ThreadPoolExecutor(max_workers=3)
        self.archives, self.area_res, self.rows = {}, {}, {}   # area_res: area title -> [Res]
        self.area_cards, self.res_by = {}, {}   # area title -> {card id: Card};  (area, tag, rid) -> Res
        self.cur_card = None                    # the Card picked in Cards mode
        self.place_cids, self.place_bgs, self.place_items = [], [], []   # combobox value -> id lists
        self.place_rect = None                  # outline of the item on the composited card (image coords)
        self.pending_card = None                # card to show next time an item is selected
        self.movie_scale_cache = {}
        self.cur_area, self.cur_loc = AREAS[0][0], None         # cur_loc None = whole area
        self.staged = {}          # (archive, tag, rid) -> source file or REVERT
        self.img_cache = {}       # (archive path, rid) -> PIL image
        self.images = {}          # what the compare panel shows: 'orig' / 'cur' / 'new'
        self.sel = None
        self.req = 0
        self.gen = 0              # bumps on every area (re)load, so cached movie files never go stale
        self.busy = False
        self.swipe_x, self.swipe_geom = 0.5, None
        self.card_draw_geom = None          # (x0, y0, s, card) set when hotspot overlay is drawn
        self.custom_names = load_custom_names()
        prefs_nav = load_settings()
        self.area_order: list = prefs_nav.get("area_order", [])      # custom area order (titles)
        self.loc_order_custom: dict = prefs_nav.get("loc_order_custom", {})  # area title → [loc names]
        self.nav_drag_iid = None    # iid being dragged in the nav tree
        self.tree_drag_iid = None   # iid being dragged in the main list
        self._tree_drag_start_y = 0
        self.section_labels: dict = prefs_nav.get("section_labels", {})   # "area|loc" → display label
        self.loc_override: dict = prefs_nav.get("loc_override", {})
        self.blink_on, self.blink_job, self.time_job = False, None, None
        self.duration = 0.0
        self.cache_lock = threading.Lock()
        _clean_old_caches()
        os.makedirs(CACHE_DIR, exist_ok=True)
        atexit.register(shutil.rmtree, CACHE_DIR, True)
        self._build()
        self.apply_theme()
        root.after(50, self._poll)
        self.load_all()

    # ---------------------------------------------------------------- layout
    def _build(self):
        root = self.root
        self.light_theme = ttk.Style(root).theme_use()  # Windows' native theme, for light mode
        root.title("Riven Mod Tool")
        root.geometry("1500x860")
        root.minsize(1000, 600)
        cur_path = _create_riven_cursor()
        if cur_path:
            try:
                root.configure(cursor="@" + cur_path.replace("\\", "/"))
            except Exception:
                pass

        menu = tk.Menu(root)
        fm = tk.Menu(menu, tearoff=0)
        fm.add_command(label="Export listed items (current game state)...", command=lambda: self.export_area(False))
        fm.add_command(label="Export listed items (originals)...", command=lambda: self.export_area(True))
        fm.add_command(label="Stage changes from folder...", command=self.stage_folder)
        fm.add_separator()
        fm.add_command(label="Export card as layers or folder...", command=self.export_card)
        fm.add_command(label="Import card from layered file (PSD / ORA)...", command=self.import_card_layers)
        fm.add_command(label="Import card from folder of images...", command=self.import_card_folder)
        fm.add_separator()
        fm.add_command(label="Open game folder", command=lambda: os.startfile(self.game_dir))
        fm.add_separator()
        fm.add_command(label="Quit", command=root.destroy)
        menu.add_cascade(label="File", menu=fm)
        pm = tk.Menu(menu, tearoff=0)
        prefs = load_settings()
        self.dark = tk.BooleanVar(value=bool(prefs.get("dark", False)))
        pm.add_checkbutton(label="Dark mode", variable=self.dark, command=self.toggle_dark)
        self.extra = tk.BooleanVar(value=bool(prefs.get("extra_info", False)))
        pm.add_checkbutton(label="Show extra info (file paths)", variable=self.extra, command=self.toggle_extra)
        pm.add_separator()
        order = prefs.get("loc_order", "progress")
        self.loc_order = tk.StringVar(value=order if order in ("progress", "alpha") else "progress")
        pm.add_radiobutton(label="Order locations by playthrough progression", variable=self.loc_order,
                           value="progress", command=self.toggle_order)
        pm.add_radiobutton(label="Order locations alphabetically", variable=self.loc_order,
                           value="alpha", command=self.toggle_order)
        pm.add_separator()
        pm.add_command(label="Reset nav panel order to default", command=self.reset_nav_order)
        menu.add_cascade(label="Preferences", menu=pm)
        im = tk.Menu(menu, tearoff=0)
        im.add_command(label="Add ID labels to this island (images)", command=lambda: self.id_labels_add(False))
        im.add_command(label="Add ID labels to this island (images + movies, slow)",
                       command=lambda: self.id_labels_add(True))
        im.add_command(label="Remove ID labels from this island", command=lambda: self.id_labels_remove(False))
        im.add_separator()
        im.add_command(label="Remove ID labels everywhere", command=lambda: self.id_labels_remove(True))
        menu.add_cascade(label="ID mode", menu=im)
        hm = tk.Menu(menu, tearoff=0)
        hm.add_command(label="User guide", accelerator="F1", command=lambda: show_help(root))
        hm.add_separator()
        for name in TOPIC_NAMES:
            hm.add_command(label=name, command=lambda n=name: show_help(root, n))
        menu.add_cascade(label="Help", menu=hm)
        root.bind("<F1>", lambda e: show_help(root))
        root.config(menu=menu)

        top = ttk.Frame(root, padding=(8, 6))
        top.pack(fill="x")
        self.kind = tk.StringVar(value="tBMP")
        ttk.Radiobutton(top, text="Images", variable=self.kind, value="tBMP", command=self.on_kind).pack(side="left")
        ttk.Radiobutton(top, text="Movies", variable=self.kind, value="tMOV", command=self.on_kind).pack(
            side="left", padx=(4, 0))
        ttk.Radiobutton(top, text="Cards", variable=self.kind, value="CARD", command=self.on_kind).pack(
            side="left", padx=(4, 14))
        ttk.Label(top, text="Search").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.refresh_list())
        ttk.Entry(top, textvariable=self.search, width=16).pack(side="left", padx=(4, 14))
        ttk.Label(top, text="Show").pack(side="left")
        self.filter = tk.StringVar(value="All")
        fc = self.filter_cb = ttk.Combobox(top, textvariable=self.filter, state="readonly", width=12,
                          values=["All", "Changed", "Patched", "Staged", "Unchanged", "ID labels"])
        fc.pack(side="left", padx=4)
        fc.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.apply_btn = ttk.Button(top, text="Apply staged (0)", command=self.apply_staged)
        self.apply_btn.pack(side="right")
        ttk.Button(top, text="Discard staged", command=self.discard_staged).pack(side="right", padx=6)

        self.lock_lbl = ttk.Label(root, padding=(8, 0), wraplength=1400)
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x")
        self.status = ttk.Label(bottom, anchor="w", padding=(8, 3))
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=160)

        pw = ttk.PanedWindow(root, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=8, pady=(2, 4))
        self.pw = pw

        nav = ttk.Frame(pw)
        self.nav = ttk.Treeview(nav, columns=("n",), selectmode="browse")
        self.nav.heading("#0", text="Island / location")
        self.nav.heading("n", text="Items")
        self.nav.column("#0", width=230, stretch=True)
        self.nav.column("n", width=50, anchor="e", stretch=False)
        self.nav.tag_configure("area", font=("Segoe UI", 9, "bold"))
        nsb = ttk.Scrollbar(nav, orient="vertical", command=self.nav.yview)
        self.nav.configure(yscrollcommand=nsb.set)
        self.nav.pack(side="left", fill="both", expand=True)
        nsb.pack(side="left", fill="y")
        self.nav.bind("<<TreeviewSelect>>", self.on_nav)
        self.nav.tag_configure("drag_target", background="#4080d0")
        self.nav.bind("<ButtonPress-1>", self._nav_drag_start, add=True)
        self.nav.bind("<B1-Motion>", self._nav_drag_motion, add=True)
        self.nav.bind("<ButtonRelease-1>", self._nav_drag_end, add=True)
        pw.add(nav, weight=1)

        left = ttk.Frame(pw)
        cols = ("id", "loc", "name", "notes", "cards", "status")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        self.sort_col, self.sort_dir = None, None  # click a header: default -> ascending -> descending -> default
        for c, w, t in zip(cols, (55, 130, 130, 150, 90, 130),
                           ("ID", "Location", "Name", "Notes", "Used on cards", "Status")):
            self.tree.heading(c, text=t, command=lambda c=c: self.on_sort(c))
            self.tree.column(c, width=w, stretch=(c in ("loc", "name", "notes", "cards")),
                             anchor="e" if c == "id" else "w")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.tag_configure("section", background="#2a4a60", foreground="#b8d4e4",
                                font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("drag_target", background="#4080d0")
        self.tree.bind("<ButtonPress-1>", self._tree_drag_start, add=True)
        self.tree.bind("<B1-Motion>", self._tree_drag_motion, add=True)
        self.tree.bind("<ButtonRelease-1>", self._tree_drag_end, add=True)
        self.tree.bind("<Double-1>", self._tree_double_click, add=True)
        self.tree.bind("<Button-3>", self._tree_right_click, add=True)
        pw.add(left, weight=2)

        right = ttk.Frame(pw)
        pw.add(right, weight=4)
        ctl = ttk.Frame(right)
        ctl.pack(fill="x", pady=(0, 4))
        ttk.Label(ctl, text="View").pack(side="left")
        self.mode = tk.StringVar(value="side")
        for txt, val in (("Side by side", "side"), ("Swipe", "swipe"), ("Blink", "blink"), ("Difference", "diff")):
            ttk.Radiobutton(ctl, text=txt, variable=self.mode, value=val, command=self.redraw).pack(side="left", padx=3)
        ctl = ttk.Frame(right)  # second row, so nothing gets cut off on narrow windows
        ctl.pack(fill="x", pady=(0, 4))
        ttk.Label(ctl, text="Compare new against").pack(side="left")
        self.ref = tk.StringVar(value="orig")
        ttk.Radiobutton(ctl, text="Original", variable=self.ref, value="orig", command=self.redraw).pack(side="left", padx=3)
        self.ref_cur_btn = ttk.Radiobutton(ctl, text="Current", variable=self.ref, value="cur", command=self.redraw)
        self.ref_cur_btn.pack(side="left", padx=3)

        # third row: show the item in place on one of its cards
        pr = ttk.Frame(right)
        pr.pack(fill="x", pady=(0, 4))
        self.place = tk.BooleanVar(value=False)
        self.place_chk = ttk.Checkbutton(pr, text="Show on card", variable=self.place,
                                         command=lambda: (self.update_place_row(), self.reload_preview()))
        self.place_chk.pack(side="left")
        ttk.Label(pr, text="  Card").pack(side="left")
        self.card_cb = ttk.Combobox(pr, state="readonly", width=17)
        self.card_cb.pack(side="left", padx=3)
        self.card_cb.bind("<<ComboboxSelected>>", lambda e: self.on_card_choice())
        ttk.Label(pr, text="  Background").pack(side="left")
        self.bg_cb = ttk.Combobox(pr, state="readonly", width=17)
        self.bg_cb.pack(side="left", padx=3)
        self.bg_cb.bind("<<ComboboxSelected>>", lambda e: self.reload_preview())
        self.outline = tk.BooleanVar(value=True)
        ttk.Checkbutton(pr, text="Outline", variable=self.outline, command=self.redraw).pack(side="left", padx=6)
        self.show_spots = tk.BooleanVar(value=False)
        ttk.Checkbutton(pr, text="Spots", variable=self.show_spots, command=self.redraw).pack(side="left", padx=6)
        self.spots_nav = tk.BooleanVar(value=True)
        ttk.Checkbutton(pr, text="Navigate", variable=self.spots_nav).pack(side="left", padx=(0, 6))
        self.place_row = pr
        # Cards mode only: which of the card's pictures / movies to show (own row, so nothing gets cut off)
        ir = self.item_row = ttk.Frame(right)
        self.item_lbl = ttk.Label(ir, text="Item")
        self.item_lbl.pack(side="left")
        self.item_cb = ttk.Combobox(ir, state="readonly", width=46)
        self.item_cb.pack(side="left", padx=3)
        self.item_cb.bind("<<ComboboxSelected>>", lambda e: self.on_item_choice())
        ttk.Button(ir, text="Export card...", command=self.export_card).pack(side="left", padx=(8, 2))
        ttk.Button(ir, text="Import card...", command=self.import_card_layers).pack(side="left", padx=2)

        self.canvas = tk.Canvas(right, bg="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_swipe)

        # Script viewer panel (hidden until a hotspot is clicked while Spots is on)
        sb = self.script_bar = ttk.Frame(right)
        self.script_bar_title = ttk.Label(sb, anchor="w", padding=(4, 2))
        self.script_bar_title.pack(fill="x")
        st = ttk.Frame(sb)
        st.pack(fill="both", expand=True)
        self.script_text = tk.Text(st, height=6, wrap="none", font=("Courier New", 8),
                                   state="disabled", relief="flat", bd=0, cursor="arrow")
        sb_sy = ttk.Scrollbar(st, orient="vertical", command=self.script_text.yview)
        sb_sx = ttk.Scrollbar(sb, orient="horizontal", command=self.script_text.xview)
        self.script_text.configure(yscrollcommand=sb_sy.set, xscrollcommand=sb_sx.set)
        sb_sy.pack(side="right", fill="y")
        self.script_text.pack(side="left", fill="both", expand=True)
        sb_sx.pack(fill="x")

        self.movie_bar = ttk.Frame(right)
        ttk.Label(self.movie_bar, text="Time").pack(side="left")
        self.time = tk.DoubleVar(value=0)
        self.time_scale = ttk.Scale(self.movie_bar, from_=0, to=1, variable=self.time, command=self.on_time)
        self.time_scale.pack(side="left", fill="x", expand=True, padx=6)
        self.time_lbl = ttk.Label(self.movie_bar, width=14)
        self.time_lbl.pack(side="left")
        self.play_btns = {}
        for which, txt in (("orig", "Play original"), ("cur", "Play current"), ("new", "Play new")):
            b = ttk.Button(self.movie_bar, text=txt, command=lambda w=which: self.play(w))
            b.pack(side="left", padx=2)
            self.play_btns[which] = b

        self.info = ttk.Label(right, anchor="w", justify="left", padding=(0, 4), wraplength=1000)
        self.info.pack(fill="x")
        nr = self.note_row = ttk.Frame(right)
        ttk.Label(nr, text="Notes:").pack(side="left")
        self.note_var = tk.StringVar()
        self.note_entry = ttk.Entry(nr, textvariable=self.note_var)
        self.note_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.note_entry.bind("<Return>", self.on_note_save)
        self.note_entry.bind("<FocusOut>", self.on_note_save)
        btns = self.btns_row = ttk.Frame(right)
        btns.pack(fill="x")
        self.b_load = ttk.Button(btns, text="Load new...", command=self.load_new)
        self.b_unstage = ttk.Button(btns, text="Unstage", command=self.unstage)
        self.b_revert = ttk.Button(btns, text="Revert to original", command=self.revert)
        self.b_exp_o = ttk.Button(btns, text="Export original...", command=lambda: self.export_one("orig"))
        self.b_exp_c = ttk.Button(btns, text="Export current...", command=lambda: self.export_one("cur"))
        self.b_find = ttk.Button(btns, text="Find in list", command=self.find_in_list)
        for b in (self.b_load, self.b_unstage, self.b_revert, self.b_exp_o, self.b_exp_c, self.b_find):
            b.pack(side="left", padx=(0, 4))

    # ---------------------------------------------------------------- theme
    def apply_theme(self):
        dark = self.dark.get()
        apply_ttk_theme(self.root, dark, self.light_theme)
        col = TAG_COLORS[dark]
        for t in ("patched", "staged", "label"):
            self.tree.tag_configure(t, foreground=col[t])
        self.nav.tag_configure("locked", foreground=col["locked"])
        self.nav.tag_configure("changed", foreground=col["changed"])
        self.lock_lbl.configure(foreground=col["patched"])
        for cb in (self.filter_cb, self.item_cb, self.card_cb, self.bg_cb):
            style_combobox_list(cb, dark)
        set_titlebar_dark(self.root, dark)
        set_help_dark(dark)
        sbg = "#1e1e1e" if dark else "#f0f0f0"
        sfg = "#c8d8e8" if dark else "#1a1a1a"
        self.script_text.configure(bg=sbg, fg=sfg, insertbackground=sfg, selectbackground="#3a5a8a")
        self.nav.tag_configure("drag_target", background="#1a4a8a" if dark else "#4080d0")
        self.tree.tag_configure("section", background="#1e3a50" if dark else "#c4d8e4",
                                foreground="#90c0d8" if dark else "#1a2a38")
        self.tree.tag_configure("drag_target", background="#1a4a8a" if dark else "#4080d0")

    def loc_key(self, area, loc):
        """Sort key for a location: playthrough order, or plain alphabetical (Preferences)."""
        return loc_sort_key(area, loc) if self.loc_order.get() == "progress" else (0, 0, loc.lower())

    def toggle_order(self):
        save_settings(loc_order=self.loc_order.get())
        self.build_nav()
        self.refresh_list()

    def reset_nav_order(self):
        self.area_order, self.loc_order_custom = [], {}
        save_settings(area_order=[], loc_order_custom={})
        self.build_nav()

    def _save_nav_order(self):
        save_settings(area_order=self.area_order, loc_order_custom=self.loc_order_custom)

    def _nav_current_areas(self):
        """Ordered list of area iids currently in the nav tree."""
        return list(self.nav.get_children())

    def _nav_drag_start(self, e):
        iid = self.nav.identify_row(e.y)
        if not iid:
            return
        prefix = iid.split("|")[0]
        if prefix in ("A", "L"):
            self.nav_drag_iid = iid
            self.nav.configure(cursor="sb_v_double_arrow")

    def _nav_drag_motion(self, e):
        if not self.nav_drag_iid:
            return
        target = self.nav.identify_row(e.y)
        for tagged in list(self.nav.tag_has("drag_target")):
            tags = [t for t in self.nav.item(tagged, "tags") if t != "drag_target"]
            self.nav.item(tagged, tags=tags)
        if target and target != self.nav_drag_iid:
            tags = list(self.nav.item(target, "tags")) + ["drag_target"]
            self.nav.item(target, tags=tags)

    def _nav_drag_end(self, e):
        # Clear highlight from any drag_target-tagged items
        for tagged in list(self.nav.tag_has("drag_target")):
            tags = [t for t in self.nav.item(tagged, "tags") if t != "drag_target"]
            self.nav.item(tagged, tags=tags)
        self.nav.configure(cursor="")
        drag_iid = self.nav_drag_iid
        self.nav_drag_iid = None
        if not drag_iid:
            return
        target = self.nav.identify_row(e.y)
        if not target or target == drag_iid:
            return
        drag_prefix = drag_iid.split("|")[0]
        tgt_prefix = target.split("|")[0]
        # Area reorder: drag an "A|..." to another "A|..."
        if drag_prefix == "A" and tgt_prefix == "A":
            self._reorder_area(drag_iid, target, e.y)
        # Location reorder: drag an "L|..." to "L|..." or "A|..." within same parent
        elif drag_prefix == "L":
            drag_parent = self.nav.parent(drag_iid)
            tgt_parent = self.nav.parent(target) if tgt_prefix == "L" else target
            if drag_parent == tgt_parent or (tgt_prefix == "A" and target == drag_parent):
                self._reorder_loc(drag_iid, target, e.y)

    def _reorder_area(self, drag_iid, target_iid, y):
        """Move drag_iid before or after target_iid among top-level areas."""
        children = list(self.nav.get_children())
        if drag_iid not in children or target_iid not in children:
            return
        row_bbox = self.nav.bbox(target_iid)
        insert_after = row_bbox and y > row_bbox[1] + row_bbox[3] // 2
        children.remove(drag_iid)
        idx = children.index(target_iid)
        children.insert(idx + (1 if insert_after else 0), drag_iid)
        # Reorder in tree
        for pos, iid in enumerate(children):
            self.nav.move(iid, "", pos)
        # Persist: convert iids to area titles
        self.area_order = [iid.split("|", 1)[1] for iid in children]
        self._save_nav_order()

    def _reorder_loc(self, drag_iid, target_iid, y):
        """Move drag_iid before or after target_iid within their shared parent area."""
        parent = self.nav.parent(drag_iid)
        if not parent:
            return
        children = [c for c in self.nav.get_children(parent) if not c.startswith("O|")]
        if drag_iid not in children:
            return
        if target_iid not in children:
            # Dropped on the area header — move to end of locations
            children.remove(drag_iid)
            children.append(drag_iid)
        else:
            row_bbox = self.nav.bbox(target_iid)
            insert_after = row_bbox and y > row_bbox[1] + row_bbox[3] // 2
            children.remove(drag_iid)
            idx = children.index(target_iid)
            children.insert(idx + (1 if insert_after else 0), drag_iid)
        # Reorder in tree (keep Other group at the end)
        others = [c for c in self.nav.get_children(parent) if c.startswith("O|")]
        for pos, iid in enumerate(children + others):
            self.nav.move(iid, parent, pos)
        area_title = parent.split("|", 1)[1]
        # loc iid format: "L|area|loc"
        self.loc_order_custom[area_title] = [iid.split("|", 2)[2] for iid in children
                                             if iid.startswith("L|")]
        self._save_nav_order()

    # ---------------------------------------------------------------- main-list drag (move resource to section)
    def _tree_drag_start(self, e):
        iid = self.tree.identify_row(e.y)
        if iid and not iid.startswith("sec|") and iid in self.rows:
            self.tree_drag_iid = iid
            self._tree_drag_start_y = e.y

    def _tree_drag_motion(self, e):
        if not self.tree_drag_iid:
            return
        if abs(e.y - self._tree_drag_start_y) < 5:
            return
        target = self.tree.identify_row(e.y)
        for tagged in list(self.tree.tag_has("drag_target")):
            tags = [t for t in self.tree.item(tagged, "tags") if t != "drag_target"]
            self.tree.item(tagged, tags=tags)
        if target and target.startswith("sec|"):
            self.tree.item(target, tags=list(self.tree.item(target, "tags")) + ["drag_target"])
            self.tree.configure(cursor="sb_v_double_arrow")
        else:
            self.tree.configure(cursor="")

    def _tree_drag_end(self, e):
        for tagged in list(self.tree.tag_has("drag_target")):
            tags = [t for t in self.tree.item(tagged, "tags") if t != "drag_target"]
            self.tree.item(tagged, tags=tags)
        self.tree.configure(cursor="")
        drag_iid = self.tree_drag_iid
        self.tree_drag_iid = None
        if not drag_iid:
            return
        target = self.tree.identify_row(e.y)
        if not target or not target.startswith("sec|"):
            return
        r = self.rows.get(drag_iid)
        if not r or isinstance(r, str):
            return
        new_loc = target[4:]  # strip "sec|" prefix
        if new_loc == r.loc:
            return
        self._move_resource_to_loc(r, new_loc)

    def _move_resource_to_loc(self, r, new_loc):
        r.loc = new_loc
        override_key = f"{r.archive}|{r.tag.decode()}|{r.rid}"
        self.loc_override[override_key] = new_loc
        save_settings(loc_override=self.loc_override)
        self.build_nav()
        self.refresh_list(keep_sel=r.key() if self.sel else None)

    def _tree_double_click(self, e):
        """Double-click the Notes column cell to edit inline."""
        iid = self.tree.identify_row(e.y)
        col = self.tree.identify_column(e.x)
        if not iid or iid.startswith("sec|") or col != "#4":  # "#4" is the "notes" column
            return
        r = self.rows.get(iid)
        if not r or isinstance(r, str):
            return
        # Position a temporary Entry widget over the cell
        bbox = self.tree.bbox(iid, column="notes")
        if not bbox:
            return
        x, y, w, h = bbox
        var = tk.StringVar(value=r.note)
        entry = ttk.Entry(self.tree, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, "end")

        def commit(event=None):
            text = var.get().strip()
            entry.destroy()
            if text == r.note:
                return
            r.note = text
            k = note_key(r)
            if text:
                self.custom_names[k] = text
            else:
                self.custom_names.pop(k, None)
            save_custom_names(self.custom_names)
            self.update_row(r)
            self.update_info()

        def cancel(event=None):
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)

    def _tree_right_click(self, e):
        """Right-click a section header to rename it."""
        iid = self.tree.identify_row(e.y)
        if not iid or not iid.startswith("sec|"):
            return
        loc = iid[4:]
        label = self.section_labels.get(f"{self.cur_area}|{loc}", loc)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"Rename section '{label}'...",
                         command=lambda: self._rename_section(loc, label))
        menu.tk_popup(e.x_root, e.y_root)

    def _rename_section(self, loc, current_label):
        new_label = simpledialog.askstring("Rename section", f"New name for '{current_label}':",
                                           initialvalue=current_label, parent=self.root)
        if new_label is None:
            return
        new_label = new_label.strip()
        key = f"{self.cur_area}|{loc}"
        if new_label and new_label != loc:
            self.section_labels[key] = new_label
        else:
            self.section_labels.pop(key, None)
        save_settings(section_labels=self.section_labels)
        self.refresh_list(keep_sel=self.sel.key() if self.sel else None)

    def toggle_extra(self):
        save_settings(extra_info=self.extra.get())
        self.set_status(self.status.cget("text"))  # re-scrub what's showing
        self.update_info()

    def with_path(self, label, path):
        """'Saved' alone, or 'Saved <path>' when Show extra info is on (for streaming without file paths)."""
        return f"{label} {path}" if self.extra.get() else label

    def toggle_dark(self):
        save_settings(dark=self.dark.get())
        self.apply_theme()

    # ---------------------------------------------------------------- plumbing
    def _poll(self):
        # one failing callback must never stop the loop, or nothing would ever load again
        try:
            while True:
                cb = self.q.get_nowait()
                try:
                    cb()
                except Exception as e:
                    traceback.print_exc()
                    self.show_error(e)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll)

    def run_bg(self, fn, done, fail=None):
        def wrap():
            try:
                res = fn()
            except BaseException as e:  # noqa: B036 - riven_img uses sys.exit for user errors
                traceback.print_exc()
                self.q.put(lambda e=e: (fail or self.show_error)(e))
            else:
                self.q.put(lambda: done(res))
        self.pool.submit(wrap)

    def post_status(self, text):
        self.q.put(lambda: self.set_status(text))

    def set_status(self, text):
        self.status.config(text=text if self.extra.get() else scrub_paths(text, self.game_dir))

    def show_error(self, e):
        self.set_busy(False)
        msg = f"{type(e).__name__}: {e}"
        messagebox.showerror("Riven Mod Tool", msg if self.extra.get() else scrub_paths(msg, self.game_dir))

    def set_busy(self, busy, text=None):
        self.busy = busy
        if busy:
            self.progress.pack(side="right", padx=8)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        if text is not None:
            self.set_status(text)
        self.update_buttons()

    @property
    def locked(self):
        """The current area's restriction note (shown as a banner), or None."""
        return self.area_def()[2]

    @staticmethod
    def can_edit(r):
        """Same-size archives (a_data) take images only; everything else is editable."""
        return r is not None and (r.tag == R.TBMP or not R.is_inplace(r.archive))

    def area_def(self):
        return next(a for a in AREAS if a[0] == self.cur_area)

    @property
    def resources(self):
        return self.area_res.get(self.cur_area, [])

    # ---------------------------------------------------------------- areas + navigation
    def load_all(self, keep_sel=None):
        """(Re)read every area's archives (about a second) and rebuild the navigation tree."""
        self.set_busy(True, "Reading the game archives...")
        game_dir = self.game_dir

        def job():
            return {title: load_area(game_dir, files, title) for title, files, _ in AREAS}

        def done(res):
            self.archives, self.area_res, self.area_cards, self.res_by = {}, {}, {}, {}
            for title, (arcs, resources, cards) in res.items():
                self.archives.update(arcs)
                for r in resources:
                    r.note = self.custom_names.get(note_key(r), "")
                    override_key = f"{r.archive}|{r.tag.decode()}|{r.rid}"
                    if override_key in self.loc_override:
                        r.loc = self.loc_override[override_key]
                self.area_res[title] = resources
                self.area_cards[title] = cards
                self.res_by.update({(title, r.tag, r.rid): r for r in resources})
            if self.cur_card:  # keep the picked card across reloads (it's a new object now)
                self.cur_card = self.area_cards.get(self.cur_card.area, {}).get(self.cur_card.cid)
            self.gen += 1
            self.img_cache.clear()
            self.images = {}
            allr = [r for v in self.area_res.values() for r in v]
            self.set_busy(False, f"{len(allr)} images and movies in {len(AREAS)} areas, "
                                 f"{sum(r.patched and not r.label for r in allr)} patched, {sum(r.label for r in allr)} ID labels")
            self.build_nav()
            self.refresh_list(keep_sel)
        self.run_bg(job, done)

    def nav_iid(self, area, loc):
        return f"A|{area}" if loc is None else f"O|{area}" if loc == OTHER else f"L|{area}|{loc}"

    def build_nav(self):
        """Island > location tree, counted for the current kind (images, movies or cards)."""
        tag = self.kind.get().encode()
        was_open = {iid for iid in self.nav.get_children() if self.nav.item(iid, "open")}
        self.nav.delete(*self.nav.get_children())

        def changed(rs):
            return ("changed",) if any(self.is_changed(r) for r in rs) else ()
        # Apply custom area order: listed areas first, then any new ones in AREAS order
        if self.area_order:
            by_title = {a[0]: a for a in AREAS}
            areas = [by_title[t] for t in self.area_order if t in by_title]
            areas += [a for a in AREAS if a[0] not in {x[0] for x in areas}]
        else:
            areas = list(AREAS)
        for title, files, locked in areas:
            if tag == b"CARD":
                res = list(self.area_cards.get(title, {}).values())
            else:
                res = [r for r in self.area_res.get(title, []) if r.tag == tag]
            aid = f"A|{title}"
            self.nav.insert("", "end", iid=aid, text=title + ("  (same-size mode)" if locked else ""),
                            values=(len(res),), open=aid in was_open,
                            tags=("area",) + changed(res))
            groups = {}
            for r in res:
                groups.setdefault(r.loc, []).append(r)
            named = [k for k in groups if not k.startswith(OTHER)]
            custom = self.loc_order_custom.get(title, [])
            if custom:
                ordered = [l for l in custom if l in groups]
                ordered += sorted([l for l in named if l not in custom], key=lambda k: self.loc_key(title, k))
            else:
                ordered = sorted(named, key=lambda k: self.loc_key(title, k))
            for loc in ordered:
                self.nav.insert(aid, "end", iid=self.nav_iid(title, loc), text=loc,
                                values=(len(groups[loc]),), tags=changed(groups[loc]))
            others = sorted(k for k in groups if k.startswith(OTHER))
            if others:
                oid = self.nav_iid(title, OTHER)
                ores = [r for k in others for r in groups[k]]
                self.nav.insert(aid, "end", iid=oid, text="Other (unlabelled codes)", values=(len(ores),),
                                open=False, tags=changed(ores))
                for loc in others:
                    self.nav.insert(oid, "end", iid=self.nav_iid(title, loc), text=loc[len(OTHER):],
                                    values=(len(groups[loc]),), tags=changed(groups[loc]))
        iid = self.nav_iid(self.cur_area, self.cur_loc)
        if not self.nav.exists(iid):  # e.g. a location with images but no movies
            self.cur_loc, iid = None, f"A|{self.cur_area}"
        self.nav.selection_set(iid)
        self.nav.see(iid)

    def on_nav(self, e=None):
        s = self.nav.selection()
        if not s:
            return
        kind, _, rest = s[0].partition("|")
        if kind == "A":
            area, loc = rest, None
        elif kind == "O":
            area, loc = rest, OTHER
        else:
            area, loc = rest.split("|", 1)
        if (area, loc) == (self.cur_area, self.cur_loc) and self.rows:
            return
        self.cur_area, self.cur_loc = area, loc
        if self.locked:
            self.lock_lbl.config(text=self.locked)
            self.lock_lbl.pack(before=self.pw, fill="x")
        else:
            self.lock_lbl.pack_forget()
        self.refresh_list()

    def on_kind(self):
        self.build_nav()
        self.refresh_list()

    def status_of(self, r):
        st = self.staged.get(r.key())
        s = "ID label" if r.label else "patched" if r.patched else ""
        if st == REVERT:
            return s + " -> revert (staged)"
        if st:
            return (s + " -> " if s else "") + "new (staged)"
        return s

    def row_tags(self, r):
        if isinstance(r, Card):
            items = self.card_items(r)
            return ("staged",) if any(i.key() in self.staged for i in items) else \
                ("patched",) if any(i.patched and not i.label for i in items) else ()
        return ("staged",) if r.key() in self.staged else ("label",) if r.label else ("patched",) if r.patched else ()

    def card_items(self, card):
        """The Res objects (pictures, script images, movies) a card uses."""
        keys = [(R.TBMP, p) for _, p, _ in card.pics] + [(R.TBMP, p) for p, _ in card.draws] + \
               [(R.TMOV, m) for _, m, _ in card.movs]
        out = []
        for tag, rid in dict.fromkeys(keys):
            r = self.res_by.get((card.area, tag, rid))
            if r:
                out.append(r)
        return out

    def is_changed(self, x):
        """Really edited (not just an ID label) or staged; for a card: any of its items."""
        if isinstance(x, Card):
            return any(self.is_changed(i) for i in self.card_items(x))
        return x.patched and not x.label or x.key() in self.staged

    def card_status(self, card):
        items = self.card_items(card)
        n_edit = sum(i.patched and not i.label for i in items)
        n_stage = sum(i.key() in self.staged for i in items)
        parts = ([f"{n_edit} patched"] if n_edit else []) + ([f"{n_stage} staged"] if n_stage else [])
        return ", ".join(parts)

    def card_contents(self, card):
        def n(count, word):
            return f"{count} {word}{'' if count == 1 else 's'}"
        parts = [n(len(card.pics), "picture")]
        if card.draws:
            parts.append(n(len(card.draws), "script image"))
        if card.movs:
            parts.append(n(len(card.movs), "movie"))
        return ", ".join(parts)

    # ---------------------------------------------------------------- column sorting
    SORT_COLS = ("id", "loc", "name", "notes", "cards", "status")

    def on_sort(self, col):
        """Header click: default -> ascending -> descending -> default. Another column starts over."""
        if col != self.sort_col:
            self.sort_col, self.sort_dir = col, "asc"
        elif self.sort_dir == "asc":
            self.sort_dir = "desc"
        else:
            self.sort_col, self.sort_dir = None, None
        self.refresh_list()

    def update_headings(self):
        cards_mode = self.kind.get() == "CARD"
        titles = {"id": "ID", "loc": "Location", "name": "Card name" if cards_mode else "Name",
                  "notes": "Notes", "cards": "Contents" if cards_mode else "Used on cards", "status": "Status"}
        for c, t in titles.items():
            arrow = (" ▼" if self.sort_dir == "desc" else " ▲") if c == self.sort_col else ""
            self.tree.heading(c, text=t + arrow)

    @staticmethod
    def natural_key(value):
        """'card 9' < 'card 10': numbers compare as numbers, text case-insensitively."""
        return tuple((0, int(t), "") if t.isdigit() else (1, 0, t.lower())
                     for t in re.findall(r"\d+|\D+", str(value)))

    def insert_rows(self, rows, with_sections=False):
        """rows: [(iid, obj, tags, values)] in default order; sort by the chosen column, then fill the tree."""
        if self.sort_col:
            i = self.SORT_COLS.index(self.sort_col)
            filled = [r for r in rows if str(r[3][i]).strip()]
            empty = [r for r in rows if not str(r[3][i]).strip()]  # blanks stay last either way
            if self.sort_col == "loc":   # follows the Preferences choice: playthrough order or alphabetical
                key = lambda r: self.loc_key(self.cur_area, str(r[3][i]))  # noqa: E731
            else:
                key = lambda r: self.natural_key(r[3][i])  # noqa: E731
            filled.sort(key=key, reverse=self.sort_dir == "desc")
            rows = filled + empty
            with_sections = False  # sorting breaks location grouping
        if with_sections:
            groups, order = {}, []
            for item in rows:
                loc = item[3][1]  # "loc" is index 1 in the values tuple
                if loc not in groups:
                    groups[loc] = []
                    order.append(loc)
                groups[loc].append(item)
            for loc in order:
                label = self.section_labels.get(f"{self.cur_area}|{loc}", loc)
                sec_iid = f"sec|{loc}"
                self.tree.insert("", "end", iid=sec_iid, tags=("section",),
                                 values=("", "", label, "", "", ""))
                for iid, obj, tags, values in groups[loc]:
                    self.rows[iid] = obj
                    self.tree.insert("", "end", iid=iid, tags=tags, values=values)
        else:
            for iid, obj, tags, values in rows:
                self.rows[iid] = obj
                self.tree.insert("", "end", iid=iid, tags=tags, values=values)

    def refresh_cards(self):
        """Cards mode: one row per card of the current area/location."""
        q = self.search.get().strip().lower()
        flt = self.filter.get()
        loc = self.cur_loc
        keep = self.cur_card
        self.update_headings()
        rows = []
        for c in self.area_cards.get(self.cur_area, {}).values():
            if loc == OTHER and not c.loc.startswith(OTHER) or loc not in (None, OTHER) and c.loc != loc:
                continue
            items = self.card_items(c)
            edited = any(i.patched and not i.label for i in items)
            staged = any(i.key() in self.staged for i in items)
            if flt == "Patched" and not edited or flt == "Staged" and not staged \
                    or flt == "Changed" and not (edited or staged) \
                    or flt == "Unchanged" and (edited or staged) or flt == "ID labels" and not any(i.label for i in items):
                continue
            if q and q not in (f"{c.cid} {c.name} " + " ".join(str(i.rid) for i in items)).lower():
                continue
            rows.append((f"card|{c.cid}", c, self.row_tags(c),
                         (c.cid, c.loc, c.name, "", self.card_contents(c), self.card_status(c))))
        self.insert_rows(rows, with_sections=(self.cur_loc is None and self.sort_col is None))
        self.apply_btn.config(text=f"Apply staged ({len(self.staged)})")
        if keep and f"card|{keep.cid}" in self.rows and keep.area == self.cur_area:
            self.tree.selection_set(f"card|{keep.cid}")  # fires on_select
            self.tree.see(f"card|{keep.cid}")
            return
        self.cur_card, self.sel, self.images = None, None, {}
        self.update_buttons()
        self.update_info()
        self.redraw()

    def refresh_list(self, keep_sel=None):
        tag = self.kind.get().encode()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        self.update_place_row()
        if tag == b"CARD":
            self.refresh_cards()
            return
        self.update_headings()
        keep = keep_sel or (self.sel.key() if self.sel else None)
        q = self.search.get().strip().lower()
        flt = self.filter.get()
        loc = self.cur_loc
        rows = []
        for r in self.resources:
            if r.tag != tag:
                continue
            if loc == OTHER and not r.loc.startswith(OTHER) or loc not in (None, OTHER) and r.loc != loc:
                continue
            staged = r.key() in self.staged
            edited = r.patched and not r.label  # ID labels are test markers, not edits
            if flt == "Patched" and not edited or flt == "Staged" and not staged \
                    or flt == "Changed" and not (edited or staged) \
                    or flt == "Unchanged" and (edited or staged) or flt == "ID labels" and not r.label:
                continue
            cards = ", ".join(r.cards)
            if q and q not in f"{r.rid} {r.note} {r.name} {cards}".lower():
                continue
            rows.append((f"{r.archive}|{r.rid}", r, self.row_tags(r),
                         (r.rid, r.loc, r.name, r.note, cards, self.status_of(r))))
        self.insert_rows(rows, with_sections=(self.cur_loc is None and self.sort_col is None))
        n = len(self.staged)
        self.apply_btn.config(text=f"Apply staged ({n})")
        if keep:
            iid = f"{keep[0]}|{keep[2]}"
            if iid in self.rows and keep[1] == tag:
                self.tree.selection_set(iid)
                self.tree.see(iid)
                return
        self.sel, self.images = None, {}
        self.update_buttons()
        self.update_info()
        self.redraw()

    def update_row(self, r):
        iid = f"{r.archive}|{r.rid}"
        if self.tree.exists(iid):
            self.tree.item(iid, values=(r.rid, r.loc, r.name, r.note, ", ".join(r.cards), self.status_of(r)),
                           tags=self.row_tags(r))
        c = self.cur_card
        if c and self.tree.exists(f"card|{c.cid}"):
            self.tree.item(f"card|{c.cid}", values=(c.cid, c.loc, c.name, "", self.card_contents(c), self.card_status(c)),
                           tags=self.row_tags(c))
        self.apply_btn.config(text=f"Apply staged ({len(self.staged)})")

    def update_buttons(self):
        r, busy = self.sel, self.busy
        st = self.staged.get(r.key()) if r else None

        def s(b, ok):
            b.state(["!disabled"] if ok else ["disabled"])
        s(self.b_load, r and not busy and self.can_edit(r))
        s(self.b_unstage, r and st and not busy)
        s(self.b_revert, r and r.patched and st != REVERT and not busy and self.can_edit(r))
        s(self.b_exp_o, r and not busy)
        s(self.b_exp_c, r and r.patched and not busy)
        s(self.b_find, r and self.kind.get() == "CARD")
        s(self.ref_cur_btn, r and r.patched)
        s(self.apply_btn, self.staged and not busy)
        if r and not r.patched and self.ref.get() == "cur":
            self.ref.set("orig")
        if r and r.tag == R.TMOV:
            s(self.play_btns["cur"], r.patched)
            s(self.play_btns["new"], bool(st))

    def update_info(self):
        r = self.sel
        if not r:
            self.info.config(text="")
            self.note_row.pack_forget()
            return
        self.note_var.set(r.note)
        self.note_row.pack(fill="x", pady=(0, 2), before=self.btns_row)
        parts = [f"{KIND_NAMES[r.tag]} {r.rid}", r.archive]
        if r.note:
            parts.append(f'"{r.note}"')
        if r.name:
            parts.append(r.name)
        size = getattr(self, "item_size", None)
        if size and self.images:
            parts.append(f"{size[0]}x{size[1]}")
        if r.tag == R.TMOV and self.duration:
            parts.append(f"{self.duration:.1f}s")
        parts.append(f"used on cards: {', '.join(r.cards)}" if r.cards else "not drawn by any card (engine code)")
        st = self.staged.get(r.key())
        line2 = ("Staged: revert to original" if st == REVERT else "Staged: " + self.with_path("new file", st) if st
                 else "ID label (test marker, see the ID mode menu)" if r.label
                 else "Patched in game" if r.patched else "Original")
        if self.placed() and self.place_rect and self.images:
            x0, y0, x1, y1 = self.place_rect
            line2 += f"  |  on {self.card_title(self.place_cids[max(0, self.card_cb.current())], r.area)}" \
                     f" at {x0},{y0}"
            if r.tag == R.TMOV and size and (x1 - x0, y1 - y0) != size:
                line2 += f", shown at {x1 - x0}x{y1 - y0} (the movie's display scale)"
        self.info.config(text="  |  ".join(parts) + "\n" + line2)

    # ---------------------------------------------------------------- selection + previews
    def on_select(self, e=None):
        sel = self.tree.selection()
        if not sel:
            return
        if sel[0].startswith("sec|"):
            return
        row = self.rows.get(sel[0])
        if row is None:
            return
        if isinstance(row, Card):
            self.cur_card = row
            self.fill_item_choices(row)
            return
        self.cur_card = None
        if self.sel is row and self.images:
            self.pending_card = None
            return
        self.select_res(row)

    def on_note_save(self, event=None):
        r = self.sel
        if not r:
            return
        text = self.note_var.get().strip()
        if text == r.note:
            return
        r.note = text
        k = note_key(r)
        if text:
            self.custom_names[k] = text
        else:
            self.custom_names.pop(k, None)
        save_custom_names(self.custom_names)
        self.update_row(r)
        self.update_info()

    def select_res(self, r, card_id=None):
        """Show resource r; card_id = the card to show it on (Cards mode / Find in list)."""
        self.sel = r
        self.fill_card_choices(r, card_id if card_id is not None else self.pending_card)
        self.pending_card = None
        self.update_place_row()
        if r.tag == R.TBMP:
            self.movie_bar.pack_forget()
        else:
            self.movie_bar.pack(fill="x", pady=(4, 0), before=self.info)
            self.duration = 0.0
            self.time.set(0)
        self.reload_preview(probe=True)

    def reload_preview(self, probe=False):
        r = self.sel
        if not r:
            self.redraw()
            return
        self.req += 1
        self.images = {}
        self.update_buttons()
        self.update_info()
        self.redraw()
        if r.tag == R.TBMP:
            self.load_image_previews()
        else:
            self.load_movie(probe=probe or not self.duration)

    # ---------------------------------------------------------------- in place on a card
    def placed(self):
        """True when the preview should show the item composited on a card."""
        return bool(self.sel and self.place_cids and (self.place.get() or self.kind.get() == "CARD"))

    def update_place_row(self):
        cards_mode = self.kind.get() == "CARD"
        if cards_mode:
            self.item_row.pack(fill="x", pady=(0, 4), after=self.place_row)
        else:
            self.item_row.pack_forget()
        has_cards = bool(self.sel and self.place_cids)
        self.place_chk.state(["!disabled"] if has_cards and not cards_mode else ["disabled"])
        on = has_cards and (self.place.get() or cards_mode)
        self.card_cb.state(["!disabled", "readonly"] if on and not cards_mode else ["disabled"])
        self.bg_cb.state(["!disabled", "readonly"] if on and len(self.place_bgs) > 1 else ["disabled"])
        if not has_cards:
            self.card_cb.set("(not drawn by any card)" if self.sel else "")
            self.bg_cb.set("")

    def card_title(self, cid, area=None):
        c = self.area_cards.get(area or self.cur_area, {}).get(cid)
        return f"Card {cid}" + (f"  ({c.name})" if c and c.name else "")

    def fill_card_choices(self, r, want=None):
        cids = list(r.card_ids)
        if want is not None and want not in cids:
            cids.insert(0, want)
        self.place_cids = cids
        self.card_cb["values"] = [self.card_title(c, r.area) for c in cids]
        if cids:
            cid = want if want in cids else cids[0]
            self.card_cb.current(cids.index(cid))
            self.fill_bg_choices(r, cid)
        else:
            self.place_bgs = []

    def on_card_choice(self):
        if self.sel and self.place_cids:
            self.fill_bg_choices(self.sel, self.place_cids[self.card_cb.current()])
            self.update_place_row()
            self.reload_preview()

    def fill_bg_choices(self, r, cid):
        """Full-screen pictures of the card (its picture list: one per state of the view), or black."""
        card = self.area_cards[r.area][cid]
        full = [(idx, pid) for idx, pid, rect in card.pics if rect == (0, 0, SCREEN_W, SCREEN_H)]
        bgs = [pid for _, pid in full]
        labels = [f"Picture {idx}: #{pid}" + (" (this item)" if pid == r.rid and r.tag == R.TBMP else "")
                  for idx, pid in full]
        self.place_bgs = bgs + [None]
        self.bg_cb["values"] = labels + ["Black"]
        # default: the card's first picture (what it shows on arrival), unless that's the item itself
        pick = next((i for i, pid in enumerate(bgs) if not (pid == r.rid and r.tag == R.TBMP)), 0 if bgs else len(bgs))
        self.bg_cb.current(pick)

    def place_spec(self):
        """Everything a preview job needs to composite the item on the chosen card (main thread only)."""
        if not self.placed():
            return None
        r = self.sel
        cid = self.place_cids[max(0, self.card_cb.current())]
        card = self.area_cards[r.area][cid]
        if r.tag == R.TBMP:
            pos = next((rect[:2] for _, pid, rect in card.pics if pid == r.rid), None) or \
                next((xy for pid, xy in card.draws if pid == r.rid), (0, 0))
        else:
            pos = next((xy for _, mid, xy in card.movs if mid == r.rid), (0, 0))
        bg_pid = self.place_bgs[max(0, self.bg_cb.current())] if self.place_bgs else None
        bg = self.res_by.get((r.area, R.TBMP, bg_pid)) if bg_pid is not None else None
        return {"card": cid, "pos": pos, "bg": bg, "bg_staged": self.staged.get(bg.key()) if bg else None}

    def base_versions(self, spec):
        """Background image per pane ('orig', 'cur', 'new'), each in the matching state."""
        bg = spec["bg"]
        if bg is None:
            return {}
        out = {"orig": self.get_image(bg, "orig"), "cur": self.get_image(bg, "cur")}
        st = spec["bg_staged"]
        out["new"] = out["orig"] if st == REVERT else Image.open(st).convert("RGB") if st else out["cur"]
        return out

    def movie_display_scale(self, r):
        """How ScummVM scales this movie on screen: track matrix x movie matrix (often 1, sometimes 0.5/0.25)."""
        k = (r.archive, r.rid)
        if k not in self.movie_scale_cache:
            with open(self.movie_file(r, "orig"), "rb") as f:
                lay = R.qt_layout(f.read())
            tk_m = struct.unpack(">9i", lay["vide"][2])
            mv_m = struct.unpack(">9i", lay["mvhd"][2])
            self.movie_scale_cache[k] = (tk_m[0] / 65536 * mv_m[0] / 65536, tk_m[4] / 65536 * mv_m[4] / 65536)
        return self.movie_scale_cache[k]

    def place_images(self, spec, out, scale=(1.0, 1.0)):
        """Composite each pane's item over that pane's background; sets the outline rect."""
        bases = self.base_versions(spec)
        x, y = spec["pos"]
        rect = None
        for k, img in list(out.items()):
            if scale != (1.0, 1.0):  # ScummVM's scaleSurface is nearest-neighbour
                img = img.resize((max(1, round(img.width * scale[0])), max(1, round(img.height * scale[1]))),
                                 Image.NEAREST)
            rect = (x, y, x + img.width, y + img.height)
            out[k] = composite(bases.get(k), [(img, (x, y))])
        return rect

    def fill_item_choices(self, card):
        """Cards mode: list the card's pictures, script images and movies; show the first picture."""
        items, labels = [], []
        for idx, pid, (l, t, r_, b) in card.pics:
            full = (r_ - l, b - t) == (SCREEN_W, SCREEN_H)
            items.append((R.TBMP, pid))
            labels.append(f"Picture {idx}: #{pid}" + (" (full screen)" if full else f" {r_ - l}x{b - t} at {l},{t}"))
        for pid, (x, y) in card.draws:
            items.append((R.TBMP, pid))
            labels.append(f"Script image: #{pid} at {x},{y}")
        for idx, mid, (x, y) in card.movs:
            items.append((R.TMOV, mid))
            labels.append(f"Movie {idx}: #{mid} at {x},{y}")
        keep = [(i, lab) for i, lab in zip(items, labels) if (card.area, i[0], i[1]) in self.res_by]
        self.place_items = [i for i, _ in keep]
        self.item_cb["values"] = [lab for _, lab in keep]
        if not keep:
            self.sel, self.images = None, {}
            self.item_cb.set("(nothing on this card)")
            self.update_buttons()
            self.update_info()
            self.redraw()
            return
        # prefer an overlay or the current item if it's on this card; else the card's first picture
        cur = (self.sel.tag, self.sel.rid) if self.sel and self.sel.area == card.area else None
        pick = self.place_items.index(cur) if cur in self.place_items else 0
        self.item_cb.current(pick)
        self.on_item_choice()

    def on_item_choice(self):
        card = self.cur_card
        if not card or not self.place_items:
            return
        tag, rid = self.place_items[max(0, self.item_cb.current())]
        self.select_res(self.res_by[(card.area, tag, rid)], card_id=card.cid)

    def find_in_list(self):
        """Jump from Cards mode (or a search) to the item in the Images/Movies list."""
        r = self.sel
        if not r:
            return
        self.pending_card = self.cur_card.cid if self.cur_card else None
        self.cur_card = None
        self.kind.set(r.tag.decode())
        self.search.set("")  # triggers a list refresh
        self.cur_area, self.cur_loc = r.area, None
        self.build_nav()
        self.refresh_list(keep_sel=r.key())

    def archive_for(self, r, which):
        orig, cur = self.archives[r.archive]
        return cur if which == "cur" else orig

    def get_image(self, r, which):
        a = self.archive_for(r, which)
        k = (a.path, r.rid)
        if k not in self.img_cache:
            self.img_cache[k] = R.decode_tbmp(a.read(R.TBMP, r.rid))
        return self.img_cache[k]

    def load_image_previews(self):
        r, req, st, spec = self.sel, self.req, self.staged.get(self.sel.key()), self.place_spec()

        def job():
            out = {"orig": self.get_image(r, "orig")}
            if r.patched:
                out["cur"] = self.get_image(r, "cur")
            if st == REVERT:
                out["new"] = out["orig"]
            elif st:
                out["new"] = Image.open(st).convert("RGB")
            size = out["orig"].size
            rect = self.place_images(spec, out) if spec else None
            return out, size, rect
        self.run_bg(job, lambda res: self._set_images(req, *res))

    def _set_images(self, req, out, size=None, rect=None):
        if req != self.req:
            return
        self.images, self.item_size, self.place_rect = out, size, rect
        self.update_info()
        self.redraw()

    def movie_file(self, r, which):
        """The movie as a standalone .mov in the cache folder."""
        a = self.archive_for(r, which)
        tag = "cur" if (which == "cur" and r.patched) else "orig"
        p = os.path.join(CACHE_DIR, f"{r.archive}.{tag}{self.gen if tag == 'cur' else ''}.{r.rid}.mov")
        with self.cache_lock:  # several preview jobs can ask for the same movie at once
            if not os.path.exists(p):
                with open(p + ".tmp", "wb") as f:
                    f.write(a.read_movie(r.rid))
                os.replace(p + ".tmp", p)
        return p

    def load_movie(self, probe=False):
        r, req, st, t = self.sel, self.req, self.staged.get(self.sel.key()), self.time.get()
        spec = self.place_spec()

        def job():
            dur = R.probe_movie(self.movie_file(r, "orig"))[2] if probe else None
            out = {"orig": grab_frame(self.movie_file(r, "orig"), t)}
            if r.patched:
                out["cur"] = grab_frame(self.movie_file(r, "cur"), t)
            if st == REVERT:
                out["new"] = out["orig"]
            elif st:
                new = grab_frame(st, t)
                # the encoder will scale a new movie to the original's frame size
                out["new"] = new.resize(out["orig"].size, Image.LANCZOS) if new and out["orig"] and \
                    new.size != out["orig"].size else new
            out = {k: v for k, v in out.items() if v is not None}
            size = out["orig"].size if "orig" in out else None
            rect = self.place_images(spec, out, self.movie_display_scale(r)) if spec and out else None
            return dur, out, size, rect

        def done(res):
            dur, out, size, rect = res
            if req != self.req:
                return
            if dur is not None:
                self.duration = dur
                self.time_scale.config(to=max(dur, 0.1))
            self.time_lbl.config(text=f"{t:.1f}s / {self.duration:.1f}s")
            self._set_images(req, out, size, rect)
        self.run_bg(job, done)

    def on_time(self, _=None):
        if not self.sel or self.sel.tag != R.TMOV:
            return
        self.time_lbl.config(text=f"{self.time.get():.1f}s / {self.duration:.1f}s")
        if self.time_job:
            self.root.after_cancel(self.time_job)

        def go():
            self.time_job = None
            self.req += 1
            self.load_movie()
        self.time_job = self.root.after(200, go)

    def play(self, which):
        r = self.sel
        if not r:
            return
        st = self.staged.get(r.key())
        if which == "new":
            path = self.movie_file(r, "orig") if st == REVERT else st
        else:
            path = self.movie_file(r, which)
        if path:
            subprocess.Popen([R._tool("ffplay"), "-autoexit", "-loglevel", "error",
                              "-window_title", f"{which}: movie {r.rid}", path], **R.NOWIN)

    # ---------------------------------------------------------------- drawing
    def redraw(self):
        c = self.canvas
        c.delete("all")
        self.tk_imgs, self.swipe_geom, self.card_draw_geom = [], None, None
        if not self.show_spots.get():
            self._hide_script_bar()
            self.canvas.configure(cursor="")
        else:
            self.canvas.configure(cursor="crosshair")
        if self.blink_job:
            self.root.after_cancel(self.blink_job)
            self.blink_job = None
        W, H = c.winfo_width(), c.winfo_height()
        if W < 20 or H < 20:
            return
        if not self.sel:
            c.create_text(W // 2, H // 2, fill="#aaa", text="Select an image or movie on the left")
            return
        imgs = self.images
        if not imgs:
            c.create_text(W // 2, H // 2, fill="#aaa", text="Loading...")
            return
        mode, refk = self.mode.get(), self.ref.get()
        ref = imgs.get(refk) or imgs["orig"]
        ref_lbl = "Current" if refk == "cur" and "cur" in imgs else "Original"
        if "new" in imgs:
            cand, cand_lbl = imgs["new"], ("Original (revert)" if self.staged.get(self.sel.key()) == REVERT else "New")
        elif refk == "orig" and "cur" in imgs:
            cand, cand_lbl = imgs["cur"], "Current"
        else:
            cand = None

        if mode == "side" or cand is None:
            panes = [("Original", imgs["orig"])]
            if "cur" in imgs:
                panes.append(("Current (patched)", imgs["cur"]))
            if "new" in imgs:
                panes.append(("New (staged)", imgs["new"]))
            self._draw_panes(panes, W, H)
            if mode != "side" and cand is None:
                c.create_text(W // 2, H - 10, fill="#e0a040",
                              text="Nothing to compare yet: load a new file, or pick something that's been patched")
            return

        if cand.size != ref.size:
            cand = cand.resize(ref.size, Image.LANCZOS)
        if mode == "swipe":
            sw = int(ref.width * self.swipe_x)
            comp = ref.copy()
            comp.paste(cand.crop((sw, 0, ref.width, ref.height)), (sw, 0))
            x0, y0, iw, ih = self._draw(comp, 0, 0, W, H, f"<  {ref_lbl}   |   {cand_lbl}  >   (drag to move)")
            self.swipe_geom = (x0, iw)
            lx = x0 + int(iw * self.swipe_x)
            c.create_line(lx, y0, lx, y0 + ih, fill="#ffd040", width=2)
        elif mode == "blink":
            shown, lbl = (cand, cand_lbl) if self.blink_on else (ref, ref_lbl)
            self._draw(shown, 0, 0, W, H, f"Blink: showing {lbl}")
            self.blink_job = self.root.after(650, self._blink)
        else:
            d = ImageChops.difference(ref, cand)
            mask = d.convert("L").point(lambda v: 255 if v > 6 else 0)
            pct = 100.0 * mask.histogram()[255] / (ref.width * ref.height)
            self._draw(d.point(lambda v: min(255, v * 4)), 0, 0, W, H,
                       f"Difference {ref_lbl} vs {cand_lbl} (x4 brightness): {pct:.1f}% of pixels changed")

    def _blink(self):
        self.blink_job = None
        self.blink_on = not self.blink_on
        self.redraw()

    def _draw(self, img, x, y, w, h, label):
        lab_h = 22
        s = min(w / img.width, (h - lab_h) / img.height)
        if s <= 0:
            return x, y, 0, 0
        iw, ih = max(1, int(img.width * s)), max(1, int(img.height * s))
        im = img.resize((iw, ih), Image.LANCZOS)
        tkim = ImageTk.PhotoImage(im)
        self.tk_imgs.append(tkim)
        x0, y0 = x + (w - iw) // 2, y + lab_h + (h - lab_h - ih) // 2
        self.canvas.create_text(x + w // 2, y0 - 11, fill="#ddd", text=label)
        self.canvas.create_image(x0, y0, image=tkim, anchor="nw")
        if self.place_rect and self.outline.get() and self.placed() and img.size == (SCREEN_W, SCREEN_H):
            l, t, r, b = self.place_rect  # the item's spot on the card, scaled like the picture
            if (l, t, r, b) != (0, 0, SCREEN_W, SCREEN_H):
                self.canvas.create_rectangle(x0 + l * s - 1, y0 + t * s - 1, x0 + r * s, y0 + b * s,
                                             outline="#ffd040", dash=(4, 3))
        if self.show_spots.get() and img.size == (SCREEN_W, SCREEN_H):
            # Resolve the card whose hotspots to draw (works in both CARD mode and tBMP place mode)
            spot_card = self.cur_card
            if spot_card is None and self.place_cids and self.sel:
                cid = self.place_cids[max(0, self.card_cb.current())]
                spot_card = self.area_cards.get(self.sel.area, {}).get(cid)
            if spot_card:
                self.card_draw_geom = (x0, y0, s, spot_card)
                cv = self.canvas
                for hl, ht, hr, hb, hname, henabled, hjumps, _hraw in spot_card.hspts:
                    col = "#40ff80" if henabled else "#808080"
                    cv.create_rectangle(x0 + hl * s, y0 + ht * s, x0 + hr * s, y0 + hb * s,
                                        outline=col, width=1)
                    if hname:
                        mid_x = x0 + (hl + hr) * s / 2
                        mid_y = y0 + (ht + hb) * s / 2
                        cv.create_text(mid_x, mid_y, fill=col, text=hname,
                                       font=("TkDefaultFont", 8))
        return x0, y0, iw, ih

    def _draw_panes(self, panes, W, H):
        n = len(panes)
        iw, ih = panes[0][1].size
        horiz = min(W / n / iw, H / ih) >= min(W / iw, H / n / ih)
        for i, (lbl, img) in enumerate(panes):
            if horiz:
                self._draw(img, i * W // n, 0, W // n - 6, H, lbl)
            else:
                self._draw(img, 0, i * H // n, W, H // n - 6, lbl)

    def on_swipe(self, e):
        if self.mode.get() != "swipe" or not self.swipe_geom:
            return
        x0, iw = self.swipe_geom
        self.swipe_x = min(1.0, max(0.0, (e.x - x0) / max(1, iw)))
        self.redraw()

    def on_canvas_click(self, e):
        if self.show_spots.get() and self.card_draw_geom is not None:
            x0, y0, s, spot_card = self.card_draw_geom
            if s > 0:
                img_x = (e.x - x0) / s
                img_y = (e.y - y0) / s
                for i, (hl, ht, hr, hb, _hname, _henabled, hjumps, hraw) in enumerate(spot_card.hspts):
                    if hl <= img_x <= hr and ht <= img_y <= hb:
                        self._show_hotspot_script(i, spot_card, hraw)
                        if hjumps and self.spots_nav.get():
                            self._navigate_to_card(min(hjumps), spot_card.area)
                        return
                self._hide_script_bar()
        self.on_swipe(e)

    def _navigate_to_card(self, cid, area):
        """Switch to CARD mode and select card cid in the given area."""
        if self.kind.get() != "CARD":
            self.kind.set("CARD")
            self.on_kind()
        target = self.area_cards.get(area, {}).get(cid)
        if target is None:
            return
        iid = self.nav_iid(area, target.loc)
        if not self.nav.exists(iid):
            iid = f"A|{area}"
        self.nav.selection_set(iid)
        self.nav.see(iid)
        row_iid = f"card|{cid}"
        if row_iid in self.rows:
            self.tree.selection_set(row_iid)
            self.tree.see(row_iid)

    def _show_hotspot_script(self, idx, card, raw_scripts):
        """Decode and display the script panel for hotspot idx on card."""
        hs = card.hspts[idx]
        hl, ht, hr, hb, hname, henabled, hjumps, _ = hs
        title_parts = [f"Hotspot {idx}"]
        if hname:
            title_parts.append(hname)
        title_parts.append(f"rect({hl},{ht},{hr},{hb})")
        title_parts.append("enabled" if henabled else "disabled")
        self.script_bar_title.configure(text="  ·  ".join(title_parts))

        events = _fmt_script_list(raw_scripts)
        lines = []
        if not events:
            lines = ["(no scripts)"]
        for ev_name, cmds in events:
            lines.append(f"on {ev_name}:")
            lines.extend(f"  {c}" for c in cmds) if cmds else lines.append("  (empty)")
        text = "\n".join(lines)

        t = self.script_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", text)
        t.configure(state="disabled")
        self.script_bar.pack(fill="x", pady=(2, 0), before=self.info)

    def _hide_script_bar(self):
        self.script_bar.pack_forget()

    # ---------------------------------------------------------------- staging
    def stage(self, r, src):
        self.staged[r.key()] = src
        self.update_row(r)
        self.req += 1
        self.images = {}
        self.update_buttons()
        if r.tag == R.TBMP:
            self.load_image_previews()
        else:
            self.load_movie()

    def check_new_file(self, r, src):
        """Return an error message, or None if `src` can replace resource r."""
        if r.tag == R.TBMP:
            want = tbmp_size(self.archive_for(r, "orig").read(R.TBMP, r.rid))
            try:
                with Image.open(src) as im:
                    got = im.size
            except Exception as e:
                return f"can't open image: {e}"
            if got != want:
                return f"size is {got[0]}x{got[1]}, must be {want[0]}x{want[1]}"
        return None

    def load_new(self):
        r = self.sel
        if not r:
            return
        if r.tag == R.TBMP:
            types = [("Images", " ".join("*" + e for e in sorted(R.IMAGE_EXTS))), ("All files", "*.*")]
        else:
            types = [("Videos", " ".join("*" + e for e in sorted(VIDEO_EXTS))), ("All files", "*.*")]
        src = filedialog.askopenfilename(title=f"New file for {KIND_NAMES[r.tag]} {r.rid}", filetypes=types)
        if not src:
            return
        err = self.check_new_file(r, src)
        if err:
            messagebox.showerror("Riven Mod Tool", f"{os.path.basename(src)}: {err}")
            return
        self.stage(r, src)

    def unstage(self):
        r = self.sel
        if r and r.key() in self.staged:
            del self.staged[r.key()]
            self.stage_refresh(r)

    def stage_refresh(self, r):
        self.update_row(r)
        self.req += 1
        self.images = {}
        self.update_buttons()
        self.update_info()
        self.load_image_previews() if r.tag == R.TBMP else self.load_movie()

    def revert(self):
        r = self.sel
        if r and r.patched:
            self.stage(r, REVERT)

    def discard_staged(self):
        if self.staged and messagebox.askyesno("Riven Mod Tool", f"Discard {len(self.staged)} staged change(s)?"):
            self.staged.clear()
            self.refresh_list()
            if self.sel:
                self.stage_refresh(self.sel)

    def stage_folder(self):
        folder = filedialog.askdirectory(title="Folder with edited files (named <id>_anything.ext)")
        if not folder:
            return
        try:
            with open(os.path.join(folder, MANIFEST)) as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            manifest = {}
        index = {(r.tag, r.rid): r for r in self.resources}
        found, skipped, unknown, bad = {}, 0, [], []
        for fn in sorted(os.listdir(folder)):
            ext = os.path.splitext(fn)[1].lower()
            tag = R.TBMP if ext in R.IMAGE_EXTS else R.TMOV if ext in VIDEO_EXTS else None
            if not tag:
                continue
            try:
                rid = R._id_from_filename(fn)
            except ValueError:
                unknown.append(fn)
                continue
            r = index.get((tag, rid))
            if not r or not self.can_edit(r):  # e.g. movies in a same-size archive
                unknown.append(fn)
                continue
            p = os.path.join(folder, fn)
            if manifest.get(fn) == os.stat(p).st_mtime_ns:
                skipped += 1
                continue
            if r in found and os.stat(found[r]).st_mtime_ns >= os.stat(p).st_mtime_ns:
                continue  # several edited files for one resource: keep the newest
            found[r] = p
        for r, p in found.items():
            err = self.check_new_file(r, p)
            if err:
                bad.append(f"{os.path.basename(p)}: {err}")
            else:
                self.staged[r.key()] = p
        self.refresh_list()
        if self.sel:
            self.stage_refresh(self.sel)
        msg = f"Staged {len(found) - len(bad)} file(s).\nSkipped {skipped} unchanged since export."
        if unknown:
            msg += f"\n{len(unknown)} file(s) don't match anything in {self.cur_area}: " \
                   + ", ".join(unknown[:8]) + (" ..." if len(unknown) > 8 else "")
        if bad:
            msg += "\n\nRejected:\n" + "\n".join(bad[:12])
        messagebox.showinfo("Riven Mod Tool", msg)

    # ---------------------------------------------------------------- export
    def export_one(self, which):
        r = self.sel
        if not r:
            return
        if r.tag == R.TBMP:
            out = filedialog.asksaveasfilename(initialfile=out_name(r, ".png"), defaultextension=".png",
                                               filetypes=[("PNG", "*.png")])
            if out:
                self.get_image(r, which).save(out)
                self.set_status(self.with_path("Saved", out))
        else:
            out = filedialog.asksaveasfilename(initialfile=out_name(r, ".mp4"), defaultextension=".mp4",
                                               filetypes=[("MP4 for video editors", "*.mp4"),
                                                          ("Original QuickTime (Cinepak)", "*.mov")])
            if not out:
                return
            src = self.movie_file(r, which)

            def job():
                if out.lower().endswith(".mov"):
                    shutil.copyfile(src, out)
                else:
                    R.mov_to_mp4(src, out)
                return out
            self.set_busy(True, f"Exporting {os.path.basename(out)}...")
            self.run_bg(job, lambda o: self.set_busy(False, self.with_path("Saved", o)))

    def export_area(self, originals):
        tag = self.kind.get().encode()
        if tag == b"CARD":
            messagebox.showinfo("Riven Mod Tool", "Switch to Images or Movies to export. In Cards mode, "
                                "\"Export original...\" saves the item picked on the current card.")
            return
        items = list(self.rows.values())  # exactly what the list shows (area, location, filters)
        what = f"{len(items)} {KIND_NAMES[tag]}s"
        folder = filedialog.askdirectory(title=f"Export {what} from {self.cur_area} to...")
        if not folder:
            return
        mp4 = tag == R.TMOV and messagebox.askyesno(
            "Riven Mod Tool", "Also write .mp4 copies for video editors (Vegas etc.)?\nThis takes a bit longer.")
        labelled = set()
        if not originals and any(r.label for r in items):
            ans = messagebox.askyesnocancel(
                "Riven Mod Tool", f"{sum(r.label for r in items)} of these currently carry ID labels.\n\n"
                                  "Export the originals for those instead? (No = export them with the labels)")
            if ans is None:
                return
            if ans:
                labelled = {r.key() for r in items if r.label}

        def src(r):
            return self.archive_for(r, "orig" if originals or r.key() in labelled else "cur")
        jobs = [(src(r).path, r) for r in items]
        movie_paths = {r.key(): src(r) for r in items} if tag == R.TMOV else None

        def job():
            written = []
            if tag == R.TBMP:
                with cf.ProcessPoolExecutor() as ex:
                    args = [(p, r.rid, os.path.join(folder, out_name(r, ".png"))) for p, r in jobs]
                    for i, out in enumerate(ex.map(_export_image, args, chunksize=8), 1):
                        written.append(out)
                        if i % 25 == 0:
                            self.post_status(f"Exported {i}/{len(args)} images...")
            else:
                for i, (_, r) in enumerate(jobs, 1):
                    base = os.path.join(folder, out_name(r, ""))
                    with open(base + ".mov", "wb") as f:
                        f.write(movie_paths[r.key()].read_movie(r.rid))
                    written.append(base + ".mov")
                    if mp4:
                        R.mov_to_mp4(base + ".mov", base + ".mp4")
                        written.append(base + ".mp4")
                    self.post_status(f"Exported {i}/{len(jobs)} movies...")
            mpath = os.path.join(folder, MANIFEST)
            try:
                with open(mpath) as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                manifest = {}
            manifest.update({os.path.basename(p): os.stat(p).st_mtime_ns for p in written})
            with open(mpath, "w") as f:
                json.dump(manifest, f, indent=0)
            return len(written)
        self.set_busy(True, f"Exporting {what}...")
        def done(n):
            self.set_busy(False, self.with_path(f"Exported {n} file(s)", "to " + folder))
            if self.extra.get():  # Explorer would show the folder path on screen
                os.startfile(folder)
        self.run_bg(job, done)

    # ---------------------------------------------------------------- apply
    def apply_staged(self):
        if not self.staged or self.busy:
            return
        if game_running():
            messagebox.showerror("Riven Mod Tool", "Riven (ScummVM) is running. Close it first: "
                                 "the game keeps the archives open while it runs.")
            return
        by_arc = {}
        for (arc, tag, rid), src in sorted(self.staged.items()):
            by_arc.setdefault(arc, []).append((tag, rid, src))
        n_mov = sum(1 for (a, t, r), s in self.staged.items() if t == R.TMOV and s != REVERT)
        msg = f"Write {len(self.staged)} change(s) to:\n" + "\n".join(f"  {a}: {len(v)}" for a, v in by_arc.items())
        if n_mov:
            msg += f"\n\n{n_mov} movie(s) will be re-encoded to Cinepak (about 3x their running time each)."
        if not messagebox.askyesno("Riven Mod Tool", msg):
            return
        game_dir, n_changes = self.game_dir, len(self.staged)

        def job():
            # same-size archives first, and fit everything before writing ANY archive: if a journal page
            # doesn't fit its slot, nothing is written and the staged changes stay staged
            inplace = {}
            misfits = []
            for arc, items in by_arc.items():
                if not R.is_inplace(arc):
                    continue
                orig = R.Archive(R.find_original(os.path.join(game_dir, arc)))
                changes = {}
                for i, (tag, rid, src) in enumerate(items, 1):
                    if src == REVERT:
                        changes[(tag, rid)] = None
                        continue
                    slot = orig.entry(tag, rid).size
                    self.post_status(f"{arc}: fitting image {rid} into its {slot:,}-byte slot ({i}/{len(items)})...")
                    try:
                        changes[(tag, rid)] = R.encode_tbmp_inplace(Image.open(src), orig.read(tag, rid), slot)
                    except R.FitError as e:
                        misfits.append(f"  image {rid}: {e.size:,} bytes for a {slot:,}-byte slot "
                                       f"({100 * (e.size - slot) / slot:.1f}% too big)")
                inplace[arc] = changes
            if misfits:
                raise ValueError("Some Menus & Journals edits don't fit their original space, so nothing was "
                                 "written:\n\n" + "\n".join(misfits) + "\n\nThey stay staged. Smoother edits fit "
                                 "better: avoid adding noise or fine detail, and keep to the page's colours.")
            for arc, changes in inplace.items():
                self.post_status(f"{arc}: writing {len(changes)} image(s) in place...")
                R.write_inplace(os.path.join(game_dir, arc), changes)

            for arc, items in by_arc.items():
                if R.is_inplace(arc):
                    continue
                path = os.path.join(game_dir, arc)
                orig = R.Archive(R.find_original(path))
                self.post_status(f"{arc}: reading existing patches...")
                patches = R.current_patches(path)
                for i, (tag, rid, src) in enumerate(items, 1):
                    if src == REVERT:
                        patches.pop((tag, rid), None)
                    elif tag == R.TBMP:
                        patches[(tag, rid)] = R.encode_tbmp_24(Image.open(src))
                    else:
                        self.post_status(f"{arc}: encoding movie {rid} ({i}/{len(items)})...")
                        patches[(tag, rid)] = R.encode_movie(src, orig.read_movie(rid))
                self.post_status(f"{arc}: writing {len(patches)} patched resource(s)...")
                R.write_patches(path, patches)
                # a real edit (or a revert) replaces any ID label on that resource
                save_labels(path, load_labels(path) - {(tag, rid) for tag, rid, _ in items})
            return n_changes

        def done(n):
            self.staged.clear()
            self.set_busy(False, f"Applied {n} change(s).")
            self.load_all(keep_sel=self.sel.key() if self.sel else None)
        self.set_busy(True, "Applying...")
        self.run_bg(job, done)

    # ---------------------------------------------------------------- whole-card layered editing
    def card_for_io(self):
        """The card to export/import: the one picked in Cards mode, else the one shown for the selected item."""
        if self.cur_card:
            return self.cur_card
        if self.sel and self.place_cids:
            cid = self.place_cids[max(0, self.card_cb.current())]
            return self.area_cards.get(self.sel.area, {}).get(cid)
        return None

    def card_layer_specs(self, card):
        """A card's images, bottom to top, with where the game draws each: [(Res, x, y, label, visible)].
        Full-screen pictures (the card's states) go first, then overlays, then script-drawn images. Only the first
        full-screen picture and the first overlay at each spot start visible; every layer is exported either way."""
        full = (0, 0, SCREEN_W, SCREEN_H)
        ordered = [p for p in card.pics if p[2] == full] + [p for p in card.pics if p[2] != full]
        entries = [(f"Picture {idx}", pid, rect[0], rect[1], rect == full) for idx, pid, rect in ordered]
        entries += [("Script image", pid, xy[0], xy[1], False) for pid, xy in card.draws]
        specs, seen, spots, shown_full = [], set(), set(), False
        for what, pid, x, y, is_full in entries:
            r = self.res_by.get((card.area, R.TBMP, pid))
            if r is None or pid in seen:
                continue
            seen.add(pid)
            if is_full:
                visible, shown_full = not shown_full, True
            elif what == "Script image":
                visible = False
            else:
                visible = (x, y) not in spots
                spots.add((x, y))
            specs.append((r, x, y, f"#{pid} {r.name} [{what}]".replace("  ", " "), visible))
        if specs and not any(sp[4] for sp in specs):
            specs[0] = specs[0][:4] + (True,)
        return specs

    def card_image(self, r):
        """The image as it is in the game now (an ID label counts as the original: labels are only markers)."""
        return self.get_image(r, "cur" if r.patched and not r.label else "orig")

    def ask_card_export(self):
        """Small dialog: which format, and whether to add movie reference layers. Returns (format, movies) or None."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Export card")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.configure(background=ttk.Style().lookup("TFrame", "background") or self.root.cget("background"))
        dlg.geometry(f"+{self.root.winfo_rootx() + 120}+{self.root.winfo_rooty() + 120}")
        fmt, mov, result = tk.StringVar(value="psd"), tk.BooleanVar(value=False), {}
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Save this card's images as:").pack(anchor="w")
        for val, title, note in (
                ("psd", "Photoshop file (.psd)", "Layers at their real positions. Also opens in GIMP, Krita, Affinity."),
                ("ora", "OpenRaster file (.ora)", "GIMP and Krita open it natively."),
                ("folder", "Folder of PNG files", "Works in any editor; each image is its own file.")):
            ttk.Radiobutton(f, text=title, variable=fmt, value=val).pack(anchor="w", pady=(8, 0))
            ttk.Label(f, text=note, foreground=DARK["muted"] if self.dark.get() else "#666666").pack(anchor="w", padx=(24, 0))
        mv = ttk.Checkbutton(f, text="Add the card's movies as hidden reference layers (first frame, not imported back)",
                             variable=mov)
        mv.pack(anchor="w", pady=(12, 0))

        def sync(*_):
            mv.state(["!disabled"] if fmt.get() != "folder" else ["disabled"])
        fmt.trace_add("write", sync)

        def ok():
            result["v"] = (fmt.get(), bool(mov.get()) and fmt.get() != "folder")
            dlg.destroy()
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(16, 0))
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(bar, text="Choose where to save...", command=ok).pack(side="right", padx=6)
        set_titlebar_dark(dlg, self.dark.get())
        dlg.grab_set()
        dlg.wait_window()
        return result.get("v")

    def export_card(self):
        if self.busy:
            return
        card = self.card_for_io()
        if not card:
            messagebox.showinfo("Riven Mod Tool", "Pick a card first: switch to Cards mode and select one, or select "
                                "an image and turn on Show on card.")
            return
        specs = self.card_layer_specs(card)
        if not specs:
            messagebox.showinfo("Riven Mod Tool", "This card has no images to export.")
            return
        opts = self.ask_card_export()
        if not opts:
            return
        fmt, movies = opts
        base = f"card_{card.cid}" + (f"_{R._safe(card.name)}" if card.name else "")
        if fmt == "folder":
            dest = filedialog.askdirectory(title=f"Folder for card {card.cid}'s images")
        else:
            dest = filedialog.asksaveasfilename(
                title=f"Save card {card.cid}", initialfile=base + "." + fmt, defaultextension="." + fmt,
                filetypes=[("Photoshop" if fmt == "psd" else "OpenRaster", "*." + fmt)])
        if not dest:
            return

        def job():
            layers = [{"name": label, "image": self.card_image(r), "x": x, "y": y, "visible": vis}
                      for r, x, y, label, vis in specs]
            if movies:
                for _, mid, (x, y) in card.movs:
                    r = self.res_by.get((card.area, R.TMOV, mid))
                    if not r:
                        continue
                    frame = grab_frame(self.movie_file(r, "orig"), 0.0)
                    if frame is None:
                        continue
                    sx, sy = self.movie_display_scale(r)
                    if (sx, sy) != (1.0, 1.0):
                        frame = frame.resize((max(1, round(frame.width * sx)), max(1, round(frame.height * sy))),
                                             Image.NEAREST)
                    layers.insert(0, {"name": f"REF movie #{mid} {r.name} (not imported)".replace("  ", " "),
                                      "image": frame, "x": x, "y": y, "visible": False})
                layers.sort(key=lambda L: not L["name"].startswith("REF "))   # references go below the images
            size = (SCREEN_W, SCREEN_H)
            if fmt == "psd":
                LY.write_psd(dest, size, layers)
            elif fmt == "ora":
                LY.write_ora(dest, size, layers)
            else:
                lines = [f"Card {card.cid} {card.name}", "id, x, y, width, height, name"]
                for (r, x, y, label, vis), L in zip(specs, layers):
                    L["image"].save(os.path.join(dest, out_name(r, ".png")))
                    lines.append(f"{r.rid}, {x}, {y}, {L['image'].width}, {L['image'].height}, {r.name}")
                LY.flatten(size, layers).save(os.path.join(dest, "_preview.png"))
                with open(os.path.join(dest, "_layout.txt"), "w") as fh:
                    fh.write("\n".join(lines) + "\n")
            return len(specs)
        self.set_busy(True, f"Exporting card {card.cid}...")
        self.run_bg(job, lambda n: (self.set_busy(False, self.with_path(f"Exported {n} images of card {card.cid}",
                                                                          "to " + dest)),
                                    os.startfile(os.path.dirname(dest) if fmt != "folder" else dest)
                                    if self.extra.get() else None))

    def plan_card_import(self, card, layers=None, files=None):
        """Work out which images changed. layers: [layer dict] from a PSD/ORA; files: {id: image path} from a folder.
        Returns (changed [(Res, new image)], report lines). A layer replaces the image it is named for ("#466 ..."),
        positioned relative to where the game draws that image; transparent areas keep what's in the game now."""
        items = {r.rid: (r, x, y) for r, x, y, _, _ in self.card_layer_specs(card)}
        changed, unchanged, report = [], 0, []
        found = {}
        ignored, unknown, notes = [], [], []
        if layers is not None:
            for lay in layers:
                m = re.match(r"\s*#(\d+)\b", lay["name"])
                if not m:
                    if not lay["name"].startswith("REF "):
                        ignored.append(lay["name"])
                    continue
                rid = int(m.group(1))
                if rid not in items:
                    unknown.append(lay["name"])
                    continue
                if rid in found:
                    notes.append(f"two layers are named #{rid}; using the upper one")
                found[rid] = lay
                notes += [f"{lay['name']}: {w}" for w in lay.get("warnings", [])]
        else:
            for rid, path in files.items():
                if rid not in items:
                    unknown.append(os.path.basename(path))
                    continue
                found[rid] = path
        for rid, src in found.items():
            r, px, py = items[rid]
            base = self.card_image(r).convert("RGB")
            if layers is not None:
                canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
                canvas.paste(src["image"].convert("RGBA"), (src["x"] - px, src["y"] - py))
                new = Image.alpha_composite(base.convert("RGBA"), canvas).convert("RGB")
            else:
                new = Image.open(src).convert("RGB")
                if new.size != base.size:
                    notes.append(f"{os.path.basename(src)}: size {new.width}x{new.height}, needs "
                                 f"{base.width}x{base.height} (skipped)")
                    continue
            if new.tobytes() == base.tobytes():
                unchanged += 1
            else:
                changed.append((r, new))
        report.append(f"{len(changed)} changed, {unchanged} unchanged.")
        if ignored:
            report.append(f"{len(ignored)} layer(s) not matched to an image were ignored (new layers aren't imported "
                          "on their own: merge them into the image's layer first): " + ", ".join(ignored[:6])
                          + (" ..." if len(ignored) > 6 else ""))
        if unknown:
            report.append(f"{len(unknown)} item(s) aren't on card {card.cid}: " + ", ".join(unknown[:6])
                          + (" ..." if len(unknown) > 6 else ""))
        report += sorted(set(notes))[:8]
        return changed, report

    def stage_card_import(self, card, source, result):
        changed, report = result
        folder = os.path.join(CACHE_DIR, "imports")
        os.makedirs(folder, exist_ok=True)
        for r, img in changed:
            path = os.path.join(folder, f"card{card.cid}_{r.rid}.png")
            img.save(path)
            self.staged[r.key()] = path
        self.set_busy(False, self.with_path(f"Staged {len(changed)} image(s)", "from " + source))
        self.refresh_list()
        if self.sel:
            self.stage_refresh(self.sel)
        messagebox.showinfo("Riven Mod Tool", f"Card {card.cid}: " + "\n".join(report)
                            + ("\n\nThey're staged: Apply staged writes them to the game." if changed else ""))

    def import_card_layers(self):
        if self.busy:
            return
        card = self.card_for_io()
        if not card:
            messagebox.showinfo("Riven Mod Tool", "Pick the card first: switch to Cards mode and select it.")
            return
        path = filedialog.askopenfilename(title=f"Layered file for card {card.cid}",
                                          filetypes=[("Layered images", "*.psd *.ora"), ("All files", "*.*")])
        if not path:
            return

        def job():
            _, layers = LY.read_layers(path)
            return self.plan_card_import(card, layers=layers)
        self.set_busy(True, self.with_path("Reading the layered file", os.path.basename(path)) + "...")
        self.run_bg(job, lambda res: self.stage_card_import(card, os.path.basename(path), res))

    def import_card_folder(self):
        if self.busy:
            return
        card = self.card_for_io()
        if not card:
            messagebox.showinfo("Riven Mod Tool", "Pick the card first: switch to Cards mode and select it.")
            return
        folder = filedialog.askdirectory(title=f"Folder of images for card {card.cid} (named <id>_anything.png)")
        if not folder:
            return

        def job():
            files = {}
            for fn in sorted(os.listdir(folder)):
                m = re.match(r"(\d+)", fn)
                if m and os.path.splitext(fn)[1].lower() in R.IMAGE_EXTS:
                    files[int(m.group(1))] = os.path.join(folder, fn)
            return self.plan_card_import(card, files=files)
        self.set_busy(True, "Reading the folder...")
        self.run_bg(job, lambda res: self.stage_card_import(card, "the folder", res))

    # ---------------------------------------------------------------- ID mode
    def id_labels_add(self, movies):
        if self.busy:
            return
        title, files, locked = self.area_def()
        if any(R.is_inplace(f) for f in files):
            messagebox.showinfo("Riven Mod Tool", "ID labels aren't available in " + title + ": its images must "
                                "fit their original space, and labels would just get in the way of real edits.")
            return
        if game_running():
            messagebox.showerror("Riven Mod Tool", "Riven (ScummVM) is running. Close it first.")
            return
        kinds = (R.TBMP, R.TMOV) if movies else (R.TBMP,)
        pool = [r for r in self.resources if r.tag in kinds]
        targets = [r for r in pool if not r.patched or r.label]   # never cover a real edit
        n_img = sum(r.tag == R.TBMP for r in targets)
        n_mov = len(targets) - n_img
        msg = (f"Stamp ID labels on {n_img} images" + (f" and {n_mov} movies" if movies else "") + f" in {title}?\n\n"
               "Images get a red border and their id (e.g. T1 #469); movies a yellow border and e.g. T1 MOV #58.")
        if len(pool) > len(targets):
            msg += f"\n\n{len(pool) - len(targets)} item(s) you've edited are left alone."
        if movies:
            msg += ("\n\nMovies are re-encoded, which is slow: about 3x each movie's running time, several at a "
                    f"time on {os.cpu_count()} cores. Long cutscenes can take 10+ minutes on their own.")
        msg += "\n\nRemove them any time with ID mode > Remove."
        if not targets or not messagebox.askyesno("Riven Mod Tool", msg):
            return
        game_dir = self.game_dir

        def job():
            done_n = 0
            for fn in files:
                path = os.path.join(game_dir, fn)
                items = [r for r in targets if r.archive == fn]
                if not items:
                    continue
                src, pre = R.find_original(path), label_prefix(fn)
                imgs = [r.rid for r in items if r.tag == R.TBMP]
                movs = sorted((r.rid for r in items if r.tag == R.TMOV),  # longest first: better packing
                              key=lambda rid: -self.archives[fn][0].span(R.TMOV, rid)[1])
                new, failed = {}, []
                with cf.ProcessPoolExecutor() as ex:
                    self.post_status(f"{fn}: labelling {len(imgs)} images...")
                    for rid, blob, err in ex.map(_label_image_job, [(src, rid, f"{pre} #{rid}") for rid in imgs],
                                                 chunksize=8):
                        (new.__setitem__((R.TBMP, rid), blob) if blob else failed.append(f"image {rid}: {err}"))
                    futs = [ex.submit(_label_movie_job, (src, rid, f"{pre} MOV #{rid}")) for rid in movs]
                    for i, fut in enumerate(cf.as_completed(futs), 1):
                        rid, blob, err = fut.result()
                        (new.__setitem__((R.TMOV, rid), blob) if blob else failed.append(f"movie {rid}: {err}"))
                        self.post_status(f"{fn}: encoded {i}/{len(movs)} labelled movies...")
                for f in failed:
                    print("ID label skipped:", f)
                self.post_status(f"{fn}: writing...")
                patches = R.current_patches(path)
                patches.update(new)
                R.write_patches(path, patches)
                save_labels(path, load_labels(path) | set(new))
                done_n += len(new)
            return done_n

        def done(n):
            self.set_busy(False, f"Added {n} ID labels to {title}.")
            self.load_all(keep_sel=self.sel.key() if self.sel else None)
        self.set_busy(True, f"Adding ID labels to {title}...")
        self.run_bg(job, done)

    def id_labels_remove(self, everywhere):
        if self.busy:
            return
        if game_running():
            messagebox.showerror("Riven Mod Tool", "Riven (ScummVM) is running. Close it first.")
            return
        areas = AREAS if everywhere else [self.area_def()]
        paths = [os.path.join(self.game_dir, fn) for _, files, _ in areas for fn in files]
        found = {p: load_labels(p) for p in paths if load_labels(p)}
        n = sum(len(v) for v in found.values())
        where = "anywhere" if everywhere else f"in {areas[0][0]}"
        if not n:
            messagebox.showinfo("Riven Mod Tool", f"No ID labels {where}.")
            return
        if not messagebox.askyesno("Riven Mod Tool", f"Remove {n} ID label(s) {where}? Your real edits stay."):
            return

        def job():
            for path, labels in found.items():
                self.post_status(f"{os.path.basename(path)}: removing {len(labels)} ID labels...")
                patches = R.current_patches(path)
                for k in labels:
                    patches.pop(k, None)
                R.write_patches(path, patches)
                save_labels(path, set())
            return n

        def done(k):
            self.set_busy(False, f"Removed {k} ID labels.")
            self.load_all(keep_sel=self.sel.key() if self.sel else None)
        self.set_busy(True, "Removing ID labels...")
        self.run_bg(job, done)


def main():
    if len(sys.argv) > 1:
        game_dir = os.path.abspath(sys.argv[1])
    elif getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(exe_dir, "a_data.mhk")):
            game_dir = exe_dir
        else:
            _r = tk.Tk()
            _r.withdraw()
            messagebox.showinfo("Riven Mod Tool",
                                "Riven game files not found next to RivenModTool.exe.\n"
                                "Please choose your Riven game folder "
                                "(the one that contains a_data.mhk).")
            game_dir = filedialog.askdirectory(title="Riven game folder — contains a_data.mhk")
            _r.destroy()
            if not game_dir:
                return
    else:
        game_dir = HERE
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    if os.name == "nt":  # own taskbar entry (with our icon) instead of pythonw's
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RivenModTool")
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    for ico in ("realmyst.ico", "Riven.ico"):
        for search_dir in (game_dir, DATA_PATH):
            try:
                root.iconbitmap(default=os.path.join(search_dir, ico))
                break
            except tk.TclError:
                pass
        else:
            continue
        break
    App(root, game_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
