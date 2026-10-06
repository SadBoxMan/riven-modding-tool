# Riven mod tools: project notes

The user goes by "Boss", prefers concise, casual replies, and uses ALL CAPS for emphasis.

## Goal
Modify images (and movies) in Riven: The Sequel to Myst, Steam 25th Anniversary edition.
This install IS ScummVM (scummvm.exe, auto-launches target `auto-riven`). Full ScummVM source
is in `source/scummvm-2026.3.0-myst-25.tar.gz`. The relevant code is in `engines/mohawk/`
(resource.cpp, bitmap.cpp, riven.cpp, riven_video.cpp) and `common/formats/quicktime.cpp`.

## Checkpoints (git)
This folder is a git repo that tracks ONLY the tool files (.gitignore is an allowlist: riven_*.py, CLAUDE.md,
realmyst.ico). Game archives, .orig backups and .idlabels.json are never tracked. Checkpoints are commits.
- 04f1e87 (2026-10-05): "Checkpoint: Riven Mod Tool with same-size journal patching", confirmed working in-game.
- List: git log --oneline.  Restore the tool files to a checkpoint: git checkout <hash> -- . (game data unaffected)
- Game DATA isn't in checkpoints: patched archives roll back via .orig / restore, and Boss keeps the edit sources.

## Tool: riven_img.py (this folder)
Single-file Python tool. Needs Pillow; movie patching also needs ffmpeg/ffprobe.
- `list [--movies]`, `extract` (tBMP -> PNG), `extract-movies` (tMOV -> playable .mov), `patch` (images by
  extension, anything else is treated as video and re-encoded), `restore`
- Reusable API: `write_patches(path, {(tag, rid): bytes})`, `current_patches(path)`, `Archive.read_movie()`,
  `encode_movie()`, `find_original()`. These are meant for the planned GUI.
- File names start with the resource id (e.g. `123_x.png`, `12_x.mp4`).

## Key format facts (verified against the source and real data)
- Mohawk archives: big-endian. The resource directory is at the start (absOffset at header byte 20),
  and the file table comes last in the directory. Data offsets are sorted.
- tBMP: Riven files are usually 8bpp + 256-entry BGR palette (always 768 bytes) + Riven pack (0x0400).
  ScummVM also accepts raw 24bpp (format 0x0004, BGR, even bytesPerRow), and Riven converts everything
  to an RGB565 screen anyway. So patches are written as 24bpp raw, with no palette loss.
- tMOV: QuickTime, Cinepak 15fps, sometimes ima4 audio. Its stco chunk offsets are ABSOLUTE archive
  offsets (ScummVM calls setChunkBeginOffset). Its size is IGNORED in the file table: ScummVM uses the
  next file-table entry's offset, or EOF. The tool rebases stco on extract and patch.
- ScummVM's QuickTime codecs: cvid, rle, rpza, smc, raw always; jpeg/SVQ1 are build-dependent.
  No H.264.

## Patch scheme
Layout: [original archive untouched][copy of the directory with extra file-table entries][new blobs].
Replaced resources get NEW file-table indices at the end, in data order, so movie sizes come out exact.
Each patch rebuilds that tail from the `<archive>.mhk.orig` backup, carrying over earlier patches.
Header size fields are not touched.

## Gotchas
- `a_data*.mhk` is fingerprinted by ScummVM detection (exact size plus the md5 of the first 5000 bytes).
  Patching it breaks game detection, so the tool refuses without `--force`. That archive holds the menus
  and the Atrus/Catherine journals. Unsolved: it would need a size-neutral approach.
- English loads no language archive. For other languages, `X_data_<lang>.mhk` loads FIRST and overrides.
- Steam "verify integrity" undoes patches.
- 2026-10-05: image patching CONFIRMED in-game. All 1190 Temple Island tBMPs (t_data1/t_data2) were stamped
  with "T1/T2 #id" labels, and they showed up in the cage with no crashes. Movies are not yet tested in-game.
- 2026-10-05: riven_img.py was rebuilt with the tail scheme plus movie support (it had been an older in-place
  version). Details: the header absOffset (byte 20) and ftOffset (byte 24) point at the new directory. A dummy
  file-table entry at the original EOF keeps the last original movie's size exact. Name-table entries match by FILE
  index, so remapped resources get extra name entries. If an archive was patched by the old in-place version, the
  next patch detects it and starts fresh from .orig.
- Movie encode: ffmpeg cinepak (about 3x real time per movie, single core, so it's slow) plus adpcm_ima_qt,
  matched to the original's size, fps and audio. All Temple Island movies are Cinepak 15fps with ima4 audio at
  22050Hz stereo.
- !! CINEPAK STRIP COUNT MUST BE CONSTANT. ScummVM's CinepakDecoder allocates its strip table from the FIRST frame's
  stripCount and never resizes it, and per-strip codebooks carry over between frames. ffmpeg varies strips per frame
  (1..3) by default. That caused an in-game CRASH (heap overflow) and garbage at the top of the frame (2026-10-05 test).
  Fix: `-min_strips N -max_strips N` with N = the original movie's count (2 or 3; the layout then matches exactly).
  encode_movie() now refuses to output anything that isn't constant.
- !! TIMESCALES. ScummVM's qt_decoder.cpp does `trackDuration * timeScale / movieTimeScale` (and similar) in uint32.
  With ffmpeg's defaults (movie 22050 x video 15360) that overflows after 12.7s: video FREEZES while the audio plays
  on (2026-10-05 test). Fix: `-movie_timescale` and `-video_track_timescale` set to the original's values (usually
  600/600, and 22 movies use video 15).
- !! MATRICES. ScummVM shows a track at frame size / matrix scale (tkhd matrix per track, mvhd matrix per movie).
  77 of the 1057 movies use 0.5 or 0.25 (e.g. t movie 38 has 80x96 frames shown at 20x24). ffmpeg writes 1.0, so the
  movie draws too big and stays on screen. Fix: copy the mvhd and tkhd matrices (and tkhd w/h) from the original.
- !! TRAILING HOLD FRAMES. Some originals end on tiny "no change" Cinepak frames (34 bytes, e.g. 45 frames = a 3s
  still hold on t movie 39). ffmpeg's decoder drops them, so re-encodes and mp4 exports came out short.
  Fix: tpad clone, plus -t set to max(original, new) length.
- encode_movie() verifies the strip count, timescales and matrices, and refuses to output anything that doesn't
  match. 2026-10-05: movie patching CONFIRMED in-game with the 16 test movies (58, 59, 38-44, 51-57): no
  freezing, correct scale.
- Interactable movies (buttons, levers) stay on their LAST frame until the card changes. So a replacement's first
  frame should match the card's current still (its tBMP), and its last frame should match the still for the new
  state, or the edges show.
- Engine behaviour: each card's MLST lists its movies (playback slot, left/top, loop, volume). Movies close when
  the card changes (RivenCard destructor -> closeVideos), which is by design. Scripts may block until a movie ends,
  so keep the lengths.
- The "Unknown DREF type url" warnings in the log are harmless: ffmpeg writes a 'url ' dref, and ScummVM skips it.
- ScummVM log: %APPDATA%\Riven-1997\Logs\scummvm.log
- New game -> tspit card 159 (global 0x6e9a via RMAP): movies 58 = t1.0 (cage scene), 59 = tintro (Atrus),
  60/61 = logos. Star Fissure telescope: card 138 (movies 38-44, plus endings 45-48 t1.4/t1.3/t1.2/t1.x) and
  card 144 (hatch, 51-57).

## GUI: riven_gui.py (Tkinter, same folder)
- Menus: File | Preferences | ID mode | Help. Preferences holds the Dark mode toggle and "Show extra info (file
  paths)" (default OFF, for livestreaming). Both are saved in %APPDATA%\RivenModTool\settings.json (keys dark,
  extra_info). With extra info off the tool shows "Saved" / "Staged: new file" / "Exported N file(s)" instead of
  paths, doesn't open Explorer after an export, and scrub_paths() reduces any drive path in the status bar or an
  error dialog to its file name. Route any new user-visible text containing a path through App.with_path() or
  set_status(). Native open/save dialogs and Explorer can't be scrubbed. Python's own OSError messages DOUBLE the
  backslashes ('C:\\Users\\x'), which DRIVE_PATH handles (separators match runs). Dark mode: ttk 'clam' recoloured
  (the native vista theme can't be recoloured). Light = the theme captured at startup. Also covers the
  combobox popdown listboxes, Treeview tag colours (TAG_COLORS per mode), the help window (riven_help.PALETTES),
  and the DWM dark title bar (attribute 20/19). The native menubar can't be themed from Tk.
  Gotcha: ttk state(["readonly"]) does NOT clear "disabled"; use ["!disabled", "readonly"].
- Help menu / F1: riven_help.py holds the user guide (11 topics, light markup: # / ## / - / > / 4-space code /
  **bold**). Keep it in step when features or import rules change.
- Nav tree: Island > Location. Locations come from codes in resource names ("166_tgr_..." -> Gate Room), see
  LOC_RULES / COMMON_RULES / NAME_RULES (regex matched at the START of the code with the stack letter removed).
  Resources no rule names are placed by assign_locations(): first the card whose id is the number at the START of
  the file name ("15_tdd_mg_1" -> card 15, weight 3), then the cards that list the item (weight 1); a card's
  location is the most common named location of its items. This took unlabelled items from about 35-41% per
  island to about 0-3%, and after Boss explained the last 24 items, to ZERO. Some labels are still educated guesses
  from file names (e.g. Temple 'tsub' = "Submarine", 'ic'/'reb' = "Rebel tunnels"); correct them in LOC_RULES if
  Boss knows better. FACTS FROM BOSS (authoritative): Boiler b2book = the bridge between Boiler and Temple Island;
  Boiler bismagdepot = part of the maglev tram set; Jungle jtngb* = the crystal viewer for the Rebel Age linking
  book; Jungle card jetunnel2village = the cave toward the village on the main path (CARD_NAME_RULES); all j5.*
  movies (j5.0a-d, 5.1, 5.3-5.5) = the Jungle village sentry sirens (they stay with the cards they play on);
  Gehn's Office 9_o6.15x/16x/19 = bad endings (15x: trapping yourself after meeting Gehn, 16x: before meeting him,
  19: freeing Gehn from the trap book); Rebel Age 2_r6.18 (freeing Gehn from the trap book) and 2_r3.6 (trapping
  yourself on Tay) = bad endings; Temple 138_t1.* = the Star Fissure endings. Still unclassified by Boss: Gehn's
  2_o6.10z (now Office) and 79_o6.21d (now Bedroom), which may also be endings/scenes.
  Lookup order: t_data2 before t_data1, j_data2 before j_data1.
- Header-click sorting cycles default -> ASCENDING -> DESCENDING -> default (Boss had asc/desc mixed up at first).
  b2_data is never loaded by the game. extras.mhk holds inventory 100-102, marbles 200-205 and credits 302+.
- Compare: Original / Current / New, with Side-by-side, Swipe, Blink and Difference views. Movies get a scrubber and
  ffplay buttons. Changes are staged, then "Apply staged" writes them per archive (refused while scummvm.exe runs).
- 2026-10-05: image patching through the GUI CONFIRMED in-game (a full-screen replacement).
- "Show on card" and Cards mode composite an item onto one of its cards, like ScummVM's copyImageToScreen: opaque,
  at the image's OWN size (the PLST rect can differ, e.g. j #31 is 40x60 against a 38x62 rect), at the left/top,
  clipped at 608px wide. Positions come from PLST (index, id, l, t, r, b; 12 bytes) and MLST (index, id, slot, l, t,
  ...; 22 bytes), plus drawBitmap commands (type 1: id, l, t, r, b) found in CARD and HSPT scripts. The script
  parser handles all 2322 cards exactly (CARD: s16 name, u16 zip, then scripts; HSPT: u16 count, then per hotspot
  a 22-byte record plus scripts; switch = type 8, stack change = type 27).
  Movies are shown at frame size x track matrix x movie matrix (t #38 shows at 20x24).
  Most PLST entries are full-screen STATES of a view (Temple: 1174 full vs 5 overlays). Images drawn only by engine
  C++ code (dome sliders, marbles, extras) have no card position.
- Each GUI instance uses its own cache: %TEMP%\riven_gui_cache_<pid>, removed on exit.
- WHOLE-CARD LAYERED EDITING (riven_layers.py + App.export_card / import_card_layers / import_card_folder):
  exports every image of a card as a PSD (own writer, raw or RLE, 8-bit RGB with alpha channel), ORA
  (OpenRaster zip) or a folder of PNGs (+ _preview.png, _layout.txt) on a 608x392 canvas; each layer sits at the
  game's draw position and is named "#<id> <name> [Picture N]". Visible by default: the first full-screen
  picture and the first overlay at each spot; script images hidden; optional hidden "REF movie #id" first-frame
  layers (never imported). Import matches layers by the leading "#id", renders each into the image's own rect over
  the CURRENT image (transparent = keep), and stages only images that really changed (PNGs go to
  CACHE_DIR/imports). Ignored with a note: layers without a #id (new layers must be merged down), blend mode,
  opacity, masks, adjustment layers. The reader handles raw/RLE/ZIP, 8/16-bit, luni names, and rejects
  flattened/CMYK files with a clear message. VALIDATED against psd-tools 1.23 both ways (it reads our files, we
  read its files); NOT yet tried with real Photoshop/GIMP files. Tests live in the scratchpad, not the repo.
- Shell gotcha for future sessions: heredocs and python -c mangle backslashes (regexes and Windows paths end up
  with halved or control characters). Write scripts with the Write tool, or build patterns with chr(92).
- ID mode menu: stamps the current island's images (red border, "T1 #469") and optionally its movies (yellow,
  "T1 MOV #58", slow re-encode) to find ids in-game. Labelled keys are tracked in "<archive>.idlabels.json", so
  labels never cover real edits, a real edit or revert replaces a label, and Remove leaves real edits alone.
  The list shows these as "ID label" (purple), and the Patched/Changed filters ignore them.
  Movies shown at 0.25x scale get tiny unreadable text, but the border still shows.
- "Export listed items" writes a .riven_export.json manifest. "Stage changes from folder" skips files whose mtime
  is unchanged since the export.
- ffmpeg comes from winget (Gyan.FFmpeg). The tool falls back to %LOCALAPPDATA%\Microsoft\WinGet\Links when it isn't on PATH.

## a_data same-size mode: IMPLEMENTED 2026-10-05 (riven_pack.py; riven_img.encode_tbmp_inplace / write_inplace /
## inplace_changed; GUI Apply fits all same-size edits before writing anything; CLI patch on a_data uses it)
- Sandbox-tested: a fit applies, a misfit writes nothing and stays staged, revert is byte-identical, and
  movies/ID mode are blocked.
- LIVE TEST applied: a_data.mhk image 4 (Atrus journal page 2) has a line "Edited by the Mod Tool" at the bottom
  right (181,246 of 186,230 bytes). Size and first-5000 md5 verified. a_data.mhk.orig backup exists.
  CONFIRMED IN-GAME 2026-10-05: Riven launches normally and the journal page shows the new line.
  The test line is still in a_data.mhk unless Boss reverts it. Undo: python riven_img.py restore a_data.mhk
- Also confirmed 2026-10-05: Boss's own heavily modified movie edits (through the GUI encoder) work in-game.
### Feasibility notes (from the earlier test)
- Detection = exact size 10218888 plus the md5 of the first 5000 bytes. The directory ends at 3890; journal pages
  start at 346663+. Writing a re-encoded image INTO its original slot (same offset, zero-padded to the same size,
  file table untouched) keeps both checks intact.
- Atrus' journal = card 5 'ajournal', page N = PLST N: tBMP 3 (cover) and 4-12. Catherine's = card 6 (51
  pictures), trap book = card 7. Pages are 8bpp Riven-packed (0x040A) at 76-81% of raw; the cover is 37%.
- Mohawk LZ (0x0100, supported by ScummVM) is too big on paper grain (109-118%). The Riven pack is needed.
- Test code is in Claude's scratchpad (journal/packers.py and optimal.py), not in the game folder.
  The OPTIMAL-PARSE Riven encoder (DP over positions with S/L/T header states, all subcommand forms including
  NDUPLETS with a literal tail and FC) beats Cyan's encoder by about 3%: unchanged pages land at 96.6-97%
  of the slot. A greedy encoder came out 3% OVER. Edits keep the original palette: unchanged pixels keep their
  indices, and changed pixels map to the nearest palette colour.
- Results: pages 4-6 fit with +1 line, a new paragraph, or a rewritten page (+2.8% to +7% headroom).
  Cover: small edits fit, but a big rewrite with synthetic noise was 6.7% over (random grain is less compressible
  than real texture).
- Every encode round-trips exactly through the decoder port. NOT yet tested in-game.

## Pending / offered
- DONE 2026-10-05: sortable columns (on_sort / insert_rows / natural_key in riven_gui.py). Blanks stay last, and the
  sort persists across refresh and mode switches. Direction was flipped later: first click = ascending.
- DONE 2026-10-05: "Intro & cutscenes" location (Temple: tintro/tlogo/tguard and the t1.x cage/ending movies).
- DONE 2026-10-05: Preferences menu, path hiding, location reassessment, whole-card layered export/import.
  These changes are NOT committed yet (last checkpoint: df25f19); .gitignore now also allows riven_layers.py.
- Ideas not started: apply an imported layer's opacity/blend; import new (unnamed) layers by merging them onto the
  layer below; movie reference layers using the LAST frame too.

## Possible next steps
- In-game test of image and movie patches.
- A size-neutral patch option for a_data (e.g. re-encode with the Riven packer into the original slot).
