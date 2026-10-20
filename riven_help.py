"""
riven_help.py - the built-in user guide for riven_gui.py (Help menu / F1).

Topics use a tiny markup:  "# " title, "## " heading, "- " bullet, "> " note box,
4-space indent = code/example line, **bold** inline. Blank line = paragraph break.
"""
import re
import tkinter as tk
from tkinter import ttk

HELP_TOPICS = [
("Quick start", """
# Quick start
Riven Mod Tool lets you browse every image and movie in Riven (25th Anniversary, Steam), compare versions side by side, and swap in your own files. The original game data is never overwritten: every change can be undone.

## The five-step loop
- **Find** the image or movie: pick an island and location on the left, or switch to **Cards** to browse screen by screen.
- **Export original...** to get an exact-size file to edit.
- Edit it (Photoshop, GIMP, DaVinci Resolve, Vegas...). See the import guides in this help.
- **Load new...** to stage your file. Compare it against the original with Side by side / Swipe / Blink / Difference, and tick **Show on card** to see it in place.
- **Apply staged** writes all staged changes into the game. Close Riven first, then launch it and look.

> Riven must be closed while you Apply. The tool refuses to write while ScummVM is running.

## Colours in the lists
- **Blue**: patched (your change is in the game).
- **Orange**: staged (waiting for Apply staged).
- **Purple**: ID label (a test marker from the ID mode menu, not a real edit).

## Preferences
- **Dark mode** switches the whole tool, this help included, to a dark theme.
- **Show extra info (file paths)** is **off by default**. Off, the tool says just "Saved", "Staged", "Exported 12 file(s)" and so on, hides folder names in the status bar, info line and error messages, and doesn't open Explorer after an export. On, it shows the full path of what was saved, loaded or staged. Off is the one to use when streaming.
- **Order locations by playthrough progression / alphabetically** chooses how the locations in the left panel, and the Location column when you sort it, are ordered. Progression (the default) follows a typical route through each island; alphabetical is plain A to Z.
All of these are remembered for next time.

> Windows draws the menu bar and the file open/save windows itself. They follow your Windows dark/light setting, and the file windows will show folder names whatever this setting is.
"""),

("Finding images and movies", """
# Finding images and movies
## Islands and locations (left panel)
Every island (and the menus, inventory and credits) is listed with its locations, grouped from codes in Riven's own file names: Gate Room, Temple, Village, Fire Marble Dome and so on. Items whose code isn't recognised take the location of the card their file name points at (for example the Gehn's Imager chair movies), and only a handful of leftovers remain under **Other (unlabelled codes)**, by their raw code. The grouping is inferred from names and may not match what you'd call a place. Within an island the locations are listed in a **typical playthrough order**: where you arrive or the hub first, then outward, with transit, domes and endings later and shared pieces last (sorting the Location column uses the same order; **Preferences** can switch to alphabetical instead). It's a best-guess route, not a strict one. Click an island to see all of it, or a location to narrow it down. The numbers are item counts.

## Images / Movies / Cards (top bar)
- **Images** and **Movies** list resources by id, with the cards (screens) that use them.
- **Cards** lists the game's screens. Pick a card, then pick any of its pictures, script images or movies from the **Item** box. **Find in list** jumps from there to the item in the Images or Movies list.

## Sorting
Click a column header (ID, Location, Name, Used on cards / Contents, Status) to sort by it. The first click sorts **ascending (▲, smallest or A first)**, the next **descending (▼)**, and the third goes back to the **default order**. Numbers sort as numbers (card 9 before card 10), and empty cells always go last. The sort stays while you search, filter or switch between Images, Movies and Cards. Clicking a different header starts that one fresh.

## Search and Show
- **Search** matches ids, names and card numbers (in Cards mode: card ids, names and the ids of everything on the card).
- **Show** filters by state: Changed (patched or staged), Patched, Staged, Unchanged, ID labels.

## The info line
Under the preview: id, archive, name, real size, the cards that use it, and its state. With Show on card on, it also gives the position on the card, and for movies the size the game really shows them at.
"""),

("Comparing and in-place preview", """
# Comparing and in-place preview
## The three versions
- **Original**: the untouched game file.
- **Current**: what's in the game now (only for patched items).
- **New**: the file you've staged, or the original again if you've staged a revert.

## Views
- **Side by side**: all available versions next to each other.
- **Swipe**: one picture split by a draggable line. Click or drag on it to move the line.
- **Blink**: flips between the two versions about every 0.65 seconds, which is the fastest way to spot small changes.
- **Difference**: shows only what changed (brightened 4x), plus the percentage of pixels that differ.

**Compare new against** picks the reference for Swipe, Blink and Difference: Original or Current.

## Show on card
Tick **Show on card** to see the item exactly where the game draws it: on one of its cards, at its real position, over a background of your choice. Everything is drawn the way ScummVM draws it: opaque, at the image's own size, and movies at their real display scale.
- **Card**: which card to view it on (if it's used on several).
- **Background**: the card's full-screen pictures. A card often has several, one per state of the view (door open/closed, lights on/off...). **Black** shows the item alone.
- **Outline**: a dashed box around the item's spot.

> A few images are drawn by the engine's own code (dome sliders, marbles, inventory icons, credits), not by any card. They say "not drawn by any card" and can't be shown in place.

## Movies
Movies get a **Time** slider to scrub through frames, and **Play original / current / new** buttons that open the movie in a player window (ffplay; close it or press Q/Esc when done).
"""),

("Importing images", """
# Importing images
## The rules (the tool checks the first one)
- **Exact same width and height** as the original. Start from **Export original...** and never resize the canvas.
- **No transparency.** The game draws every image as a solid rectangle. Transparent areas are dropped on import and show whatever colour data is underneath, often black. Flatten before exporting.
- **Any common format works**: PNG (best), BMP, TIFF, JPG, GIF. Use PNG: it's lossless. JPG adds compression artifacts before the game's own colour reduction.
- **Name the file starting with its id** (e.g. 469_gate.png) if you want to use Stage changes from folder.

## What the game does with your image
- It's stored at full 24-bit quality, but **shown in 16-bit colour (65,536 colours)**. Smooth gradients (sky, fog, dark falloff) can band slightly. A touch of noise in large gradients hides it. Most originals are 256-colour, so you're still ahead.
- **Overlays**: many small images are patches drawn over a full-screen picture (a door, a lever, a light). Their edges must blend into the background behind them. Use **Show on card** with Blink to check the seams.
- **States**: one view often exists as several full-screen pictures (e.g. 166_tgr_s1.15 and 166_tgr_s1_dooropen_brup.15). Change one state but not the others and things will visibly pop when the state changes. Search the name stem to find the family.
- **Movies played over a view** start and end on its stills. If you repaint a view, the movies on that card won't match it any more.
- **Animated water** ripples by shifting the picture's own pixels around, so your edits ripple too. That's fine for water, but anything else in the water area will wobble.

## Photoshop
- **Image > Mode > RGB Color** and **8 Bits/Channel**.
- **Layer > Flatten Image** (no transparency left).
- Smooth big gradients: **Filter > Noise > Add Noise**, around 1-2%, Uniform, Monochromatic.
- Save: **File > Export > Export As...**, format **PNG**, untick **Transparency**, tick **Convert to sRGB**. Or File > Save a Copy... as PNG.

## Overlays and states: edit the whole card at once
Overlays have to blend into the picture behind them, and a view often has several states. The easy way is to export the **whole card as a layered file**, where every image sits at its real position, edit the layers together, and import it back. See **Editing a whole card (layers)**.

## Menus & Journals pages (same-size mode)
Images in Menus & Journals must fit the **exact space** the original used (see Safety for why). The tool handles it:
- Your image is mapped onto **the original page's 256 colours**. Pixels you didn't change keep their exact original values, so untouched areas compress as before. Ink and paper reproduce well. A colour the page doesn't contain (say, a red drawing) is approximated by the nearest one it has.
- It's compressed with an encoder that beats the original by about **3%**. That's your room for changes.
- **What fits easily**: new or replaced handwriting, small drawings in ink, erasing text. Rewriting text often makes a page *smaller*.
- **What may not fit**: lots of new fine detail, grain or noise, or big colourful additions.
- At **Apply staged**, every journal edit is fitted first. If any doesn't fit, **nothing is written**, you're told which page and by how much, and your changes stay staged. Smooth the edit (less noise and fine detail) and try again.
- Revert puts the original bytes back exactly.

## GIMP / Affinity / Krita
Same rules: keep the canvas size, flatten (GIMP: **Image > Flatten Image**), export a PNG without an alpha channel (GIMP: **File > Export As...**, and in the PNG options untick saving background or transparency data if offered).
"""),

("Editing a whole card (layers)", """
# Editing a whole card (layers)
A card is one screen: its full-screen pictures (the states of the view), the overlays that sit on them (a lever, a door, a light) and any script-drawn images. They have to line up, so you can export all of a card's images **together** as one layered file, edit them in place, and import the lot back.

## Export
- In **Cards** mode pick the card, then **Export card...** (or **File > Export card as layers or folder...**). It also works from an image with **Show on card** on.
- Pick a format:
- **Photoshop (.psd)**: also opens in GIMP, Krita and Affinity Photo.
- **OpenRaster (.ora)**: GIMP and Krita open it natively. Paint.NET needs a free plugin for PSD or ORA.
- **Folder of PNG files**: works in any editor, one file per image, plus a _preview.png and a _layout.txt listing where each image sits.
- You get a **608 x 392 canvas** (the game screen) with **one layer per image**, at the position the game draws it, named like **#468 166_tgr_s1_brup.15 [Picture 3]**. The full-screen states are stacked (only the first starts visible; switch the others on to see them), overlays sit above them, and script-drawn images start hidden.
- Tick **Add the card's movies as hidden reference layers** to also get each movie's first frame (named REF movie ...), placed and scaled as the game shows it. They help you line things up and are never imported back.
- It exports the game as it is now, your earlier edits included (ID labels count as the originals).

## Edit
- Paint on the layers. **Keep every layer's name starting with its #id**: that is how the tool knows which image a layer belongs to. Don't delete or rename them.
- Paint across an overlay and its background so they blend.
- **Don't resize the canvas.** You may paint anywhere; each image is cut to the exact area the game draws it in.
- **Transparent areas keep what's in the game**, so you can erase a layer to leave part of it alone.
- **Ignored**: blend modes, layer opacity, layer masks and styles, adjustment layers, and any layer you add whose name doesn't start with a #id. **Merge new layers down into the image's layer** (Photoshop: Ctrl+E; GIMP: Layer > Merge Down), or the tool lists them as ignored.
- Save as **PSD** (8 or 16 bits, RGB, layers kept) or **ORA**. Photoshop: File > Save As, Photoshop format, with Maximize Compatibility on.

## Import
- In **Cards** mode select the same card, then **Import card...** and choose the file, or use **File > Import card from folder of images...** for a folder of PNGs (named with the id first, like 468_anything.png).
- Only images that **really changed** are staged. A summary tells you how many changed, how many didn't, and what was ignored. Then **Apply staged** as usual.
- Wrong-sized or unknown files in a folder are skipped and listed.
- In **Menus & Journals** the same-size rules apply when you Apply (see Importing images).
"""),

("Importing movies", """
# Importing movies
## What the tool does for you
When you Apply a movie, it's re-encoded into the game's format (Cinepak video with IMA4 audio inside a QuickTime file), matched to the original:
- **Frame size**: scaled to the original's exact size. It's **stretched**, not cropped, so keep the **same aspect ratio**.
- **Frame rate**: converted to the original's (Riven uses 15 fps).
- **Audio**: converted to the original's sample rate and channels. If the original movie is silent, audio is dropped.
- **Length**: never shorter than the original. A shorter movie holds its last frame until the original's length, because game scripts may wait for a movie to end. A longer movie plays longer.
- **Timing and display scale** settings are copied from the original, and every frame is checked, so the game can't freeze or mis-scale (both happened in testing before these fixes).

## The rules for a good result
- **Start from the original.** In Movies mode, **Export original...** and pick **MP4 for video editors**. Put it on your timeline as a reference for size, timing and the first and last frames.
- **Same length** as the original. The info line shows it.
- **Interactive movies** (buttons, levers, valves) stay on their **last frame** until you leave the card, and they start on the card's current still. Match the first and last frames to the stills, or the edges show. Check with **Show on card** and the Time slider.
- **Movies close when the card changes.** That's how the engine works, not a bug.
- **Some movies are shown smaller than their frames** (½ or ¼ size, e.g. the Star Fissure buttons are 80x96 frames shown at 20x24). Author at the frame size; the info line tells you the size on screen.

## Cinepak's limits
Cinepak is a 1990s codec. It handles moderate detail and smooth motion well, but **fine grain, noise, heavy blur and dark gradients turn blocky**. Denoise rather than add film grain, and test in-game.

## Encoding time
About **3x the movie's running time**, per movie. A 5-second clip takes seconds; a 2-minute cutscene takes around 7 minutes. Applying several movies encodes them one after another.

## Sony Vegas Pro
- **Project > Properties**: width and height = the original's frame size (e.g. 608x392), **frame rate 15**, **Progressive**, **pixel aspect 1.0 (square)**.
- Render: **Video for Windows (.avi) Uncompressed** (best), or **MAGIX AVC/AAC (.mp4)** with a custom template: the same size, 15 fps, high bitrate (20+ Mbps). Audio stereo, 44.1 or 48 kHz.

## DaVinci Resolve
- **Project Settings > Master Settings**: Timeline resolution **Custom** = the original's frame size, pixel aspect **Square**. Set the **timeline frame rate before adding any clips** (Resolve locks it afterwards): 15 if it's offered, else 30 (the tool drops back to 15).
- **Deliver** page: Custom export. Format **QuickTime** with **DNxHR HQ** (near-lossless, big files), or **MP4 / H.264** at a high quality setting. Resolution = your timeline size. Audio: stereo, Linear PCM or AAC.

## Premiere, Shotcut, HandBrake and others
The same idea: the original's frame size (or at least its aspect ratio), any frame rate, high quality, and the same length. H.264 MP4, ProRes/DNx .mov, or uncompressed AVI all work.
"""),

("Sounds", """
# Sounds
Switch the top bar to **Sounds** to browse, listen to, export and replace the game's audio.

## Listing
- Each area has two kinds of sound, shown as the location: **Sound effects** (short clips from the `*_data*.mhk` archives) and **Ambient tracks** (long background loops from the `*_sounds.mhk` archives).
- The **Info** column shows the codec and length of each sound.
- Sounds have no card positions or previews, so the compare views, Show on card and Cards mode don't apply to them.

## Play and stop
- **Play** decodes the selected sound and plays it through Windows. If the sound is staged or already patched you hear the new version; otherwise the original.
- **Stop** ends playback. Playback also stops when you pick another sound or switch mode.

## Export WAV
**Export original...** and **Export current...** save the selected sound as a standard **.wav** file you can edit in Audacity or similar. Sounds export one at a time; batch export isn't available for them.

## Import a replacement
- **Load new...** accepts wav, mp3, ogg, flac, aiff, m4a and mp2 files.
- **ffmpeg is needed.** It decodes your file, converts it to the original's sample rate and channel count, and re-encodes it to the **original's codec**: **ADPCM** for effects, **MP2** for ambient tracks. You can't change the codec.
- The original's loop settings are kept.
- The result is staged (orange), like an image or movie.

> Sound replacement is new and has not yet been confirmed in the game. Try one short effect first.

## Stage, apply, restore
- A staged sound can be played, unstaged or discarded like any other change.
- **Apply staged** writes it into the archive with the same scheme as images and movies. Close Riven first.
- **Revert to original** stages putting a sound back. From a command prompt in the game folder this also works:

    python riven_img.py restore t_data1.mhk
"""),

("Batch editing (export / stage folder)", """
# Batch editing
## Export listed items
**File > Export listed items** writes exactly what the list shows (island, location, Show filter and search all apply) to a folder you pick:
- **(current game state)**: what's in the game now, your edits included. If any listed item carries an ID label, you're offered the originals for those instead.
- **(originals)**: the untouched files.
- For movies you can add **.mp4 copies** for video editors.

Files are named by id (e.g. 469_166_tgr_s1_dooropen.15.png), and the folder gets a small **.riven_export.json** file recording what was exported.

## Stage changes from folder
**File > Stage changes from folder...** scans a folder and stages every file whose name starts with an id in the current island. Thanks to .riven_export.json, files you **didn't touch since exporting are skipped**, so you can export a whole location, edit a handful, and stage the folder. If several edited files share an id, the newest wins. Files with the wrong size are listed and rejected.

> Ids are only unique within an island. Stage a folder while that island is selected.
"""),

("ID mode", """
# ID mode
A test tool for finding which id is on screen in-game. **ID mode > Add ID labels to this island** stamps every image of the selected island with a red border and its id (e.g. **T1 #469**: archive t_data1, image 469). The **images + movies** option also stamps movies with a yellow border (**T1 MOV #58**). That's slow: every movie is re-encoded.

Walk around in-game, note the ids you want, then **ID mode > Remove ID labels** (per island or everywhere).

## It never touches your real edits
- Items you've changed are skipped when labelling.
- Applying a real edit or a revert to a labelled item replaces its label.
- Removing labels leaves your edits in place.
- Labels show in **purple**, and the Patched/Changed filters ignore them.
- Labels are tracked in a small <archive>.idlabels.json file next to the archive.

> Movies shown at ½ or ¼ size get unreadably small text, but the border still shows. Menus & Journals can't be labelled (see Safety).
"""),

("Safety, undo and backups", """
# Safety, undo and backups
## Nothing original is ever overwritten
The first time an archive is patched, the tool makes a full backup next to it (e.g. **t_data1.mhk.orig**). Your changes are added at the end of the archive; the original data is never touched. Every Apply rebuilds that added part from the backup, keeping your other changes.

## Undoing
- **Unstage**: drop a staged change before applying.
- **Discard staged**: drop them all.
- **Revert to original**: stages putting one item back; Apply to make it happen.
- Whole archive back to stock, from a command prompt in the game folder:

    python riven_img.py restore t_data1.mhk

- **Steam > Riven > Properties > Installed Files > Verify integrity** also restores everything, and **undoes all your patches**. Keep your edited source files somewhere safe.

## Menus & Journals (same-size mode)
ScummVM identifies the game by the exact size of **a_data.mhk** (menus, Atrus' and Catherine's journals, the trap book) and by its first 5,000 bytes. The normal patching method would change both and stop Riven from launching. So images in this area are patched **in place** instead: the edited image is re-encoded with Riven's own compression into the original's exact space, and the file's size and first bytes never change. See Importing images for what that means for your edits. Movies and ID mode aren't available here.

## Languages
English loads no language archive. Other languages load **X_data_<language>.mhk** first, and it overrides the main archives, so a picture with text may come from there instead.
"""),

("How the game uses images and movies", """
# How the game uses images and movies
Riven runs on ScummVM's Mohawk engine. Knowing how it draws things explains most of the import rules.
- **Cards** are the screens you stand on. Each card has a **picture list** (full-screen pictures, one per state of the view, plus the odd overlay with a position), a **movie list** (each movie's position, loop and volume), and **scripts** that pick which picture to show, draw extra images at given positions, and play movies.
- **Images** are copied to the screen as solid rectangles at their own size and position. There's no transparency and no blending. The screen is 608x392 in 16-bit colour.
- **Movies** play inside their card at a fixed position, sometimes scaled down by the movie's own settings. When a movie ends, its **last frame stays** until the card changes. Leaving the card closes all its movies.
- **Water** animation copies rows of the picture's own pixels around.
- **Transitions** between cards (wipes and dissolves) work on whatever pictures are showing, so replaced images just work with them.
- Resources are looked up by id within an island. On Temple and Jungle Island the _data2 archive is searched before _data1. Ids never repeat between the two, so it doesn't matter which one an item lives in.
"""),

("Troubleshooting and files", """
# Troubleshooting and files
## Riven won't start after a change
You probably patched an archive ScummVM fingerprints, or something went wrong mid-write. Restore that archive (see Safety) or verify the game files in Steam.

## A movie freezes, mis-scales or garbles
Movies applied by this tool are checked against the original's settings. If you made one another way, re-apply it through the tool. ScummVM's log is at:

    %APPDATA%\\Riven-1997\\Logs\\scummvm.log

## Files the tool creates in the game folder
- **<archive>.mhk.orig**: the one-time backup of an archive you've patched.
- **<archive>.mhk.idlabels.json**: which items carry ID labels (only while labels exist).

## Command line (riven_img.py)
The GUI is built on riven_img.py, which also works on its own:

    python riven_img.py list t_data1.mhk [--movies]
    python riven_img.py extract t_data1.mhk out_folder [ids...]
    python riven_img.py extract-movies t_data1.mhk out_folder [ids...] [--mp4]
    python riven_img.py patch t_data1.mhk 469_new.png 58_cage.mp4
    python riven_img.py restore t_data1.mhk

## Requirements
Python 3 with Pillow; ffmpeg/ffprobe/ffplay for movies (installed with winget: Gyan.FFmpeg).
"""),

("About", """
# About Riven Mod Tool
A browser, comparer and patcher for the images and movies of **Riven: The Sequel to Myst**, 25th Anniversary edition (Steam), which runs on ScummVM.

Built from ScummVM's own source (engines/mohawk, common/formats/quicktime, video/qt_decoder, image/codecs/cinepak), so what you see in the tool matches how the game reads and draws its files.

Riven (c) Cyan Worlds. This is an unofficial fan tool; keep backups of your work.
"""),
]

TOPIC_NAMES = [t for t, _ in HELP_TOPICS]

_win = None
_dark = False
titlebar_hook = None  # riven_gui sets this to its set_titlebar_dark(window, dark)

PALETTES = {
    False: {"bg": "SystemWindow", "fg": "SystemWindowText", "list_bg": "SystemWindow", "sel": "#2f6fb5",
            "head": "#1d3d63", "code": "#eef1f5", "note": "#fff6d8", "note_fg": "SystemWindowText"},
    True: {"bg": "#1f2125", "fg": "#e3e5e8", "list_bg": "#25282d", "sel": "#2f6fb5",
           "head": "#8cb8ff", "code": "#2b2f35", "note": "#3a3424", "note_fg": "#f1e3b8"},
}


def _help_open():
    """True if the help window exists (False once it, or the whole application, has been closed)."""
    try:
        return _win is not None and bool(_win.top.winfo_exists())
    except tk.TclError:
        return False


def set_help_dark(dark):
    """Called by the main window's theme toggle; restyles an open help window too."""
    global _dark
    _dark = dark
    if _help_open():
        _win.apply_colors()


def show_help(root, topic=None):
    """Open (or raise) the help window, optionally at a topic."""
    global _win
    if not _help_open():
        _win = HelpWindow(root)
    _win.top.deiconify()
    _win.top.lift()
    _win.top.focus_set()
    _win.show(topic or _win.current or TOPIC_NAMES[0])


class HelpWindow:
    def __init__(self, root):
        self.current = None
        top = self.top = tk.Toplevel(root)
        top.title("Riven Mod Tool - Help")
        top.geometry("1000x720")
        top.minsize(640, 400)
        top.bind("<Escape>", lambda e: top.destroy())

        pw = ttk.PanedWindow(top, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(pw)
        self.topics = tk.Listbox(left, activestyle="none", exportselection=False, font=("Segoe UI", 10), width=36,
                                 borderwidth=0, highlightthickness=0, selectbackground="#2f6fb5")
        for name in TOPIC_NAMES:
            self.topics.insert("end", "  " + name)
        self.topics.pack(fill="both", expand=True)
        self.topics.bind("<<ListboxSelect>>", self._on_topic)
        pw.add(left, weight=0)

        right = ttk.Frame(pw)
        self.text = tk.Text(right, wrap="word", padx=18, pady=12, borderwidth=0, highlightthickness=0,
                            font=("Segoe UI", 10), spacing1=2, spacing3=2, cursor="arrow")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        pw.add(right, weight=4)

        t = self.text
        t.tag_configure("h1", font=("Segoe UI", 17, "bold"), spacing1=4, spacing3=10, foreground="#1d3d63")
        t.tag_configure("h2", font=("Segoe UI", 12, "bold"), spacing1=14, spacing3=4, foreground="#1d3d63")
        t.tag_configure("p", spacing3=6)
        t.tag_configure("bullet", lmargin1=12, lmargin2=30, spacing3=3)
        t.tag_configure("code", font=("Consolas", 10), background="#eef1f5", lmargin1=24, lmargin2=24)
        t.tag_configure("note", background="#fff6d8", lmargin1=12, lmargin2=12, rmargin=12, spacing1=6, spacing3=8)
        t.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        self.apply_colors()

    def apply_colors(self):
        p = PALETTES[_dark]
        self.text.configure(background=p["bg"], foreground=p["fg"], insertbackground=p["fg"])
        self.topics.configure(background=p["list_bg"], foreground=p["fg"], selectbackground=p["sel"],
                              selectforeground="#ffffff")
        self.text.tag_configure("h1", foreground=p["head"])
        self.text.tag_configure("h2", foreground=p["head"])
        self.text.tag_configure("code", background=p["code"])
        self.text.tag_configure("note", background=p["note"], foreground=p["note_fg"])
        if titlebar_hook:  # same dark title bar as the main window (set by riven_gui)
            titlebar_hook(self.top, _dark)

    def _on_topic(self, e=None):
        sel = self.topics.curselection()
        if sel:
            self.show(TOPIC_NAMES[sel[0]])

    def show(self, topic):
        if topic not in TOPIC_NAMES:
            topic = TOPIC_NAMES[0]
        self.current = topic
        i = TOPIC_NAMES.index(topic)
        self.topics.selection_clear(0, "end")
        self.topics.selection_set(i)
        self.topics.see(i)
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        render(t, HELP_TOPICS[i][1])
        t.config(state="disabled")
        t.yview_moveto(0)


def _inline(t, text, base):
    """Insert text, turning **bold** spans into bold."""
    for k, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            t.insert("end", part, (base, "bold") if k % 2 else (base,))


def render(t, markup):
    para = []

    def flush():
        if para:
            _inline(t, " ".join(para) + "\n", "p")
            para.clear()
    for line in markup.strip("\n").splitlines():
        if line.startswith("# "):
            flush()
            t.insert("end", line[2:] + "\n", "h1")
        elif line.startswith("## "):
            flush()
            t.insert("end", line[3:] + "\n", "h2")
        elif line.startswith("- "):
            flush()
            t.insert("end", "•  ", "bullet")
            _inline(t, line[2:] + "\n", "bullet")
        elif line.startswith("> "):
            flush()
            _inline(t, line[2:] + "\n", "note")
        elif line.startswith("    "):
            flush()
            t.insert("end", line[4:] + "\n", "code")
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
