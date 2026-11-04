# MYST-001: Myst Masterpiece Edition vs the Riven Mod Tool, and a Myst-to-Riven link

Date: 2026-11-03. Read-only research: no tool files or game files were changed.
Sources: ScummVM source `Riven\source\scummvm-2026.3.0-myst-25.tar.gz` (`engines/mohawk/`, `engines/engine.h`,
`base/main.cpp`) plus probes against the real install at
`C:\Users\lukea\Games\Steam Library\steamapps\common\Myst Masterpiece` (Steam folder name "Myst Masterpiece").
Probe scripts (scratch, not in the repo): `%APPDATA%\Claude\side-session-notes\local_370f52f7-...\MYST-001_probes\`.

## TL;DR
- Myst ME is the same Mohawk container, so the Riven tool's `Archive` reader opens all 11 Myst archives unchanged.
  Everything inside the container is different, but it is simpler than Riven: images are mostly plain JPEG, sounds
  are plain 16-bit PCM WAV, and movies are loose `.mov` files on disk (no tMOV offset juggling).
- Patching: ScummVM tries to load an optional `<stack>_english.dat` BEFORE `<stack>.dat`, and English has none.
  A small new archive holding only the replaced resources would override them without touching any original file.
  That avoids the detection fingerprint (which covers `myst.dat` and `menu.dat`) and survives a Steam "verify".
  This is the best finding of the card. It is not yet confirmed in-game.
- Myst-to-Riven: each Steam `scummvm.exe` detects and can run the other game. A launcher that starts Riven after
  Myst exits is easy (no C++). A real in-engine hand-off at the end of the credits is about 10 lines of C++
  (`ChainedGamesMan`), but it needs a Windows ScummVM build, which is the expensive, risky part.
  Merging the two into one engine is not worth it.
- Recommendation: YES, start a Myst project. The first cards are below.

## 1. How Myst ME differs from Riven (from the source)

| | Riven (25th, Steam) | Myst ME (25th, Steam) |
|---|---|---|
| Archives | `X_data*.mhk`, `X_sounds.mhk` per island, many loaded at once | ONE stack archive at a time: `myst/channel/mechan/selen/stone/dunny/intro/credits.dat`, plus `help.dat` and `menu.dat` (`loadStackArchives`) |
| Language files | `X_data_<lang>.mhk` loads first; English loads none | `<stack>_<lang>.dat` loads first; **English also tries `<stack>_english.dat`** (suffix "english" in `listLanguages`), which does not exist, so it is free to use as an overlay |
| Container | MHWK/RSRC v1.0, big-endian, directory at the START | Same parser (`MohawkArchive::openStream`), but the directory is at the END of every Myst file (absOffset is near EOF) |
| Resource data endianness | big-endian | **little-endian** inside resources (VIEW, RLST, scripts, MJMP, WDIB size) |
| Images | tBMP (8bpp + Riven pack, or raw 24bpp) | `PICT` (ME) or `WDIB`. PICT = 512-byte header + QuickDraw PICT v2, usually opcode 0x8200 (CompressedQuickTime) wrapping a **JPEG**. A PICT may hold a WDIB instead (detected by the absence of the opcode 0x001102FF at byte 522). WDIB = u32 LE uncompressed size + **Mohawk LZ** BMP; size 0 = raw BMP |
| Screen | 608x392 view (608x436 window) | 544x332 viewport; most images are 544x333. ME needs high colour (converts to true colour) |
| Movies | tMOV inside archives; stco = absolute archive offsets | **Loose files**: `qtw/<stack>/<name>.mov` (`wrapMovieFilename`; Channelwood windmill movies in `qtw/channel2/`); language variants in `<lang>/qtw/...` |
| Sounds | tWAV: MHWK/WAVE, ADPC + Data chunk, DVI ADPCM or MP2 | ME: `MSND` is a **plain RIFF WAV** (`Audio::makeWAVStream`). `MJMP` = 2-byte LE alias id -> MSND id (dedup) |
| Cards | CARD (s16 name, u16 zip, scripts), PLST/MLST/SLST/BLST/HSPT/FLST | `VIEW` (flags, conditional image block keyed on a variable, sound block, script resources, RLST/HINT/INIT/EXIT ids) |
| Hotspots | HSPT 22-byte records + scripts | `RLST` = list of MystAreas: u16 type (0-4 nav, 5 action, 6 video, 7/8 switches, 10 slider, 11 drag, 12 video info, 13 hover), flags, rect, dest card, then type-specific data + scripts |
| Scripts | Data scripts; most logic in data, some engine externals | Opcode lists in data (`readScript`: count, then opcode/var/args, all LE), but **46 generic opcodes plus about 290 stack-specific opcodes in C++** (`myst_stacks/*.cpp`, myst.cpp alone has 133). Puzzle logic lives mostly in C++ |
| Variables | NAME/VARS resources, ~hundreds of named vars | No variable resources. `getVar(n)` per stack is a C++ switch over the `MystGameState` struct (e.g. Myst var 2-9 = marker switches) |
| Saves | `.rvn` = MHWK archive (VARS, ZIPS, VERS, META, THMB) | `myst-NNN.mys`-style: a fixed 664-byte (ME) state blob via `Common::Serializer` (globals + per-age structs), plus a separate metadata/thumbnail file |
| Detection | `a_data.mhk`: exact size + md5 of the first 5000 bytes | md5 of the first 5000 bytes (AD_NO_SIZE) of **`myst.dat`, `myst_<lang>.dat` and `menu.dat`**. The other ages are not fingerprinted |
| Config/saves folder | `%APPDATA%\Riven-1997` | `%APPDATA%\MystME` (empty ini; no saves yet, so Myst ME has apparently never been run) |

## 2. The Riven tool against real Myst data (scratch scripts, read-only)

| Riven tool piece | Result on Myst ME |
|---|---|
| `riven_img.Archive` | **Works on all 11 archives** (myst/channel/mechan/selen/stone/dunny/intro/credits/menu/help/myst_french). Types, ids and names all read correctly. |
| `Archive.read` / `span` | Works (the tMOV sizing quirk is irrelevant; there is no tMOV). |
| `decode_tbmp` | Not applicable (no tBMP). |
| PICT (new code) | 3,060 of the 3,082 PICTs (9 archives) are QuickTime JPEG; a plain slice from FFD8 to FFD9 opens in Pillow (544x333 RGB). At least 1 French PICT has no EOI marker (needs tolerant loading; only 2 per archive were decoded). 3 in STONE are WDIB-in-PICT. 19 are plain QuickDraw PICTs, mostly Photoshop-saved (8BIM LongComment, then DirectBits/PackBits), that need a small QuickDraw decoder. |
| WDIB (new code) | A 30-line Python port of `decompressLZ` decodes them (cursors 15x16, credits 544x333 8bpp). |
| `write_patches` (tail scheme) | **Works structurally**: on a scratch COPY of DUNNY.DAT, PICT 5002 replaced by a raw-BMP WDIB-in-PICT (543 KB) round-tripped and every other resource kept its span. BUT it rewrites header bytes 20-25 (absOffset/ftOffset), which breaks the md5 of `myst.dat`/`menu.dat`. Not tried in-game. |
| `riven_snd.parse_twav` | Silently returns an empty info dict for MSND (not MHWK). Not needed: all 473 MSND are RIFF PCM, mono, 16-bit, 22050 Hz. |
| `encode_movie` / `rebase_qt` | rebase is not needed (loose files). Movie census of the 202 qtw `.mov` files: 158 Cinepak (82 with **QDM2** audio, 1 twos), 18 rpza, ~17 QuickTime RLE, 5 smc, 7 SVQ1 (flybys/intro; 1 ima4, 1 raw, 1 QDM2 audio). |
| Both `scummvm.exe` builds | Engine list: only `mohawk`. The Myst exe detects Riven (25th) and the Riven exe detects Myst ME (25th). |

## 3. Reuse estimate

| Piece | Verdict | Effort |
|---|---|---|
| `Archive` reader | As-is | 0 |
| Directory builder in `write_patches` | Adapt: (a) **overlay writer** (new `<stack>_english.dat` with only patched resources, names and MJMPs copied); (b) tail scheme as-is for non-fingerprinted ages in other languages; (c) for `menu.dat` and non-English `myst.dat`: in-place file-table edit (keep header bytes 0-27, append blobs after the directory, repoint entries), or same-slot JPEG at a quality that fits | 1 session, Opus medium + in-game test |
| `riven_layers.py` (PSD/ORA) | As-is (544x333 canvas) | 0 |
| Image codecs | New: PICT-JPEG extract and write (copy the ~858-byte wrapper, fix the 0x8200 length, idsc dataSize, picSize), WDIB LZ decode, raw-BMP WDIB write, QuickDraw PICT decoder for 19 images | 1 session, Opus medium |
| `riven_pack.py`, a_data same-size packer | Not needed (JPEG has a quality knob; the overlay sidesteps fingerprints) | 0 |
| `riven_snd.py` | Mostly not needed. Import = ffmpeg -> s16le mono 22050 WAV, stored as-is. Export = write the bytes. Keep `_find_ffmpeg`, the winsound playback approach. Show MJMP aliases (replacing a target changes every alias) | 0.5 session, Sonnet/Opus medium |
| Movie pipeline (`encode_movie`, probes) | Adapt. The Cinepak rules (constant strips, timescales, matrices, trailing hold frames) are ScummVM decoder facts and still apply. New: replace the loose file with a `.orig` backup (or a language folder override, to be checked); QDM2 cannot be encoded by ffmpeg, so test ima4 audio in-game; decide whether to keep rpza/rle/smc/SVQ1 or convert to Cinepak; check whether RLE/smc movies rely on transparency | 1 session, Opus medium + in-game test |
| Card/hotspot parsing | New: VIEW, RLST (12 area types), HINT, INIT/EXIT scripts. RLST rects give hotspots directly (simpler than Riven) | 1 session, Opus medium |
| Puzzle/variable flow | Mostly C++, not data: a static map from `myst_stacks/*.cpp` `getVar` switches, rather than a data walk | later, Opus high |
| `riven_gui.py` (3,289 lines) | Heavily Riven-specific (locations, PLST/MLST compositing, script parser). Reusable patterns: compare views, staging/apply, preferences/dark mode, path scrubbing, help window. Either copy and cut down to `myst_gui.py`, or extract a shared core first (riskier to the shipped Riven tool) | 2-4 sessions, Opus medium |
| `riven_help.py` | Structure as-is, new content | Sonnet medium |

Overall: the "browse + replace images/sounds/movies" core is roughly 4-6 sessions to reach parity with the Riven
tool's first shipped version, a little cheaper than Riven was, because the formats are simpler.

## 4. Combining Myst and Riven

What the source says:
- Myst's credits stack ends with `quitGame()` after the 6th image (`myst_stacks/credits.cpp`). The ending type is in
  `_globals.ending` (Dni: kAtrusLeaves / kBooksDestroyed and so on). Riven's new game starts fresh (tspit card 159)
  and reads nothing from Myst. Narratively, Riven picks up right after Myst's good ending, so there is no state to carry.
- ScummVM has `ChainedGamesManager` (`engines/engine.h`; used in `base/main.cpp`): an engine can
  `ChainedGamesMan.push("<target>", saveSlot)` and quit, and ScummVM then launches that target.
- One exe can run both games (cross-detection confirmed). Each Steam build keeps its own config/saves folder
  (`%APPDATA%\MystME` and `%APPDATA%\Riven-1997`), so running Riven from the Myst exe would use a separate save list.

| Option | How | Effort | Risks |
|---|---|---|---|
| A. External launcher (recommended first) | Python/PowerShell (or a small exe): start Myst; when it exits, ask "Continue to Riven?" (exit after credits is the natural cue, but quitting looks the same), then start Riven | 0.5 session, Sonnet medium (Opus medium if it reads the save file to check the ending) | Started outside Steam, SteamAPI_Init fails (the games still run, but achievements are probably lost). Launching via `steam://rungameid/<appid>` keeps Steam but makes "wait for exit" harder (wait for the scummvm.exe process). It could read the Myst autosave (`kAutoSaveSlot`) to continue only on the good ending, if the autosave reliably reflects it. |
| B. Shared config, one exe | Add a Riven target to Myst's ini (or the reverse); the launcher calls the same exe twice | small add-on to A | Saves/achievements split from the normal Riven install |
| C. Engine hand-off | ~10 lines in `Credits::runPersistentScripts`: on the good ending, `ChainedGamesMan.push("riven")` before `quitGame()`; a target pointing at the Riven folder | C++ is tiny; **building ScummVM for Windows** (MSYS2/MinGW, SDL2, libmad for Riven MP2, jpeg, freetype, the Steam integration and the 25th patches in the `source` folders) is 1-2 sessions, Opus high | Toolchain pain; Steam updates overwrite `scummvm.exe`; achievements depend on reproducing the Steam glue; must ship the matching source (GPL) |
| D. Deep integration (one session, shared inventory, a card-to-card transition) | Myst and Riven are separate engine classes with different screens, script VMs and saves | Many sessions | Not worth it. ChainedGames gives the same result for players |

Licensing and distribution:
- ScummVM is GPLv3+ (the file headers say "either version 3"). Distributing a modified `scummvm.exe` means offering
  its full corresponding source, as the Steam build does with its `source` folder. A launcher script and the mod tool
  are our own code and carry no GPL obligation (they only run the exe).
- The game data is Cyan's: never ship archives or extracted assets. The tool patches the user's own copy. An overlay
  `.dat` containing edited Cyan art is a derived work, so sharing those publicly is a fan-mod gray area; ask Cyan's
  fan-content policy before publishing any mod packs.

## Recommendation
Start a Myst project (numbering MYST-NNN as already set up). It is cheap to bootstrap, the formats are friendlier
than Riven's, and the overlay trick may give a cleaner patch path than Riven ever had.

Proposed first cards:
1. **MYST-002: Myst image CLI + overlay proof** (Opus, medium). New `myst_img.py` (importing or copying `Archive`):
   `list`/`extract` for PICT-JPEG, WDIB, WDIB-in-PICT (QuickDraw PICTs may be listed as unsupported for now);
   `patch` that writes `<stack>_english.dat` as an overlay. Done = one Myst Island image changed in-game via
   `myst_english.dat`, Myst still detected, deleting the file restores it. Decide the repo location first (open question 1).
2. **MYST-003: Sounds + movies** (Opus, medium). MSND export/import (PCM 22050 mono, MJMP alias list); movie replacement
   for loose `.mov` with backup, adapting `encode_movie` (Cinepak + ima4 instead of QDM2). Done = one effect and one
   Cinepak movie replaced and confirmed in-game.
3. **MYST-004: Myst-to-Riven launcher (option A/B)** (Sonnet, medium). Script that runs Myst then offers Riven; check the
   Steam appids and achievements behaviour. Done = playing Myst through the credits drops you into Riven's menu.
   Option C (engine build) stays parked until Boss wants it (Opus, high).

## Open questions for Boss
1. Where should the Myst tool live: a new git repo in the `Myst Masterpiece` folder (mirrors Riven; separate exe for
   the friend), or new `myst_*.py` files in the Riven repo sharing code? I would go with a new repo that copies the
   shared modules (`Archive`, `riven_layers`), so the shipped Riven tool stays untouched.
2. Is a launcher (option A) enough, or do you specifically want the in-engine hand-off (option C, own ScummVM build)?
3. Should "continue to Riven" happen only after the good ending, or after any exit?
4. Do Steam achievements matter (they decide whether the launcher must go through Steam)?
5. Which languages matter? The overlay trick is English-only; other languages need the tail scheme or the
   in-place variant for `myst_<lang>.dat`.
6. Myst ME has never been launched on this PC (no saves, empty ini). Run it once from Steam so the in-game tests
   have a baseline.
