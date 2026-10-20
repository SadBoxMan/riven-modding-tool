# HANDOFF: Riven Mod Tool

TASK-CARD RULE: task cards for this project come from the session titled "Riven Modding Tool dispatcher" (it owns the
queue below and does no project work itself; its id is in the memory note `dispatcher.md`). When a work session
finishes its task: update this file, commit the files it changed by explicit path (other sessions may share the
checkout), push, send the dispatcher a short completion message (send_message), and tell Boss to go back to the
dispatcher for the next card. Follow-ups found during the work go into the queue below, not into new cards.

Read this at the start of every session, and update it before the session ends.
Last updated: 2026-10-17. Project notes and format facts live in `CLAUDE.md` (same folder); this file is the
"where are we now" layer on top of it.

Where things live: the code and this repo are in `C:\Users\lukea\Games\Steam Library\steamapps\common\Riven`
(a git repo). Claude sessions start in `C:\Users\lukea\Claude\Projects\Guild`, which is EMPTY and not a repo, so
CLAUDE.md here is NOT auto-loaded. Read it by path.

GitHub: `origin` = https://github.com/SadBoxMan/riven-modding-tool (migrated 2026-10-20; `main` tracks `origin/main`).
Push with plain `git push` (Git for Windows' stored sign-in works). The `gh` CLI is installed but was never logged in.

## State right now
- Working and shipped to a friend: image, movie and (new) sound browsing/patching, hotspot viewer, notes column,
  nav drag-reorder, bundled cursors, PyInstaller exes.
- Sounds (riven_snd.py + GUI "Sounds" mode): list, play/stop (winsound), export as WAV, import replacement
  (ffmpeg-decoded, re-encoded to the original's codec: ADPCM for effects, MP2 for ambient), stage, apply.
  NOT YET CONFIRMED IN-GAME. Only round-trip tested outside the game. First thing to do with sounds: replace one
  short effect and one ambient track, launch the game, listen.
- Friend confirmed the 2026-10-17 no-ffmpeg build works (the `NameError: sys` crash and the cramped rows are fixed).

## Work queue (proposed order, Boss to confirm or reorder)
1. In-game test of sound replacement (see above). Fix whatever breaks (loop points, MP2 frame/size limits).
2. Update docs for sounds: add a Sounds topic to `riven_help.py` (CLAUDE.md says keep help in step with features),
   and add a Sounds section plus the riven_snd.py format facts to `CLAUDE.md` (tWAV layout is in the riven_snd.py
   docstring).
3. Tidy CLAUDE.md: its "Pending / offered" section is stale (says changes uncommitted, last checkpoint df25f19).
4. Puzzle logic / event-flag flow (VAR resources, which flags gate which transitions). Not started. Skeleton:
   `dev/scripts/walk_graph.py`.
5. Ideas not started (from CLAUDE.md): imported layer opacity/blend, merge new unnamed layers down, movie
   reference layers using the LAST frame.
6. Layered PSD/ORA export has never been tried with real Photoshop/GIMP files (only psd-tools).

## Unfinished threads and findings that only existed in chat
- Sound capacity estimate was done in an earlier session; the numbers were not written down. Scripts are in
  `dev/twav/sound_capacity*.py` (they stub PIL and need the game folder; run WITHOUT `python -I`, which broke
  the stub). Re-run them if capacity matters. Known sizes: 312 tWAV resources over 8 areas;
  `*_sounds.mhk` = long ambient MP2, `*_data*.mhk` = short ADPCM effects.
- tWAV facts (verified): outer MHWK header, optional ADPC seek table, then Data chunk with a 20-byte format header.
  DVI ADPCM is a continuous nibble stream with no block headers (high nibble = left, low nibble = right), initial
  predictor/step per channel come from the ADPC table. Details in `riven_snd.py` and `dev/twav/`.
- The `a_data.mhk` test line ("Edited by the Mod Tool", journal page 2) is still applied unless Boss reverted it.
  Undo: `python riven_img.py restore a_data.mhk`.
- The friend's first report said "a probe error". The screenshot actually showed `NameError: name 'sys' is not
  defined` (missing `import sys` in riven_snd.py, only hit by MP2 ambient tracks). Fixed. If a REAL ffprobe error
  ever shows up, look at `_tool()` in riven_img.py (bundled-ffmpeg lookup via `sys._MEIPASS`).
- Old session scratchpads are temporary. Everything useful from them was copied to `dev/` on 2026-10-17.

## Questions waiting on Boss
- Priority order above OK? Anything to add (more sound features, e.g. batch import/export of sounds)?
- Is the test line in a_data.mhk still wanted?

## Build, run, test
- Run from source: `python riven_gui.py "<game folder>"` (needs Pillow; ffmpeg on PATH, or the WinGet Links
  fallback, for movies and sounds). Game/ScummVM must be closed to apply patches.
- Build exes (from the Riven folder; needs PyInstaller; `cursors/` (tracked in git since 2026-10-20) and
  `realmyst.ico` must exist):
  - `python -m PyInstaller RivenModTool.spec --noconfirm` -> full build with ffmpeg bundled (~103 MB). The spec
    hardcodes the WinGet ffmpeg path (`_FFMPEG`); update it if ffmpeg moves or its version changes.
  - `python -m PyInstaller RivenModTool-noffmpeg.spec --noconfirm` -> ~19 MB, relies on ffmpeg on PATH.
  - Both write `dist\RivenModTool.exe`, so RENAME after each build (we used `RivenModTool-full.exe` and
    `RivenModTool-noffmpeg.exe`) or the second overwrites the first.
  - PowerShell quirk: piping PyInstaller output through `Select-Object` makes `$?` report failure even when the
    build succeeded. Check that the exe exists instead.
- Tests: there is no automated suite. Past tests were sandbox scripts in temp folders (now in `dev/`). Verify
  behaviour with the GUI plus an in-game launch. Dev scripts live in `dev/scripts/` (research, one-offs) and
  `dev/twav/` (sound format research).
- Shell gotcha: heredocs and `python -c` mangle backslashes. Write scripts with the Write tool.
- Git: this repo's `.gitignore` is an allowlist. New tool files must be added to it explicitly. Never track game
  archives or `.orig` backups. Checkpoints are commits; list them with `git log --oneline`.
