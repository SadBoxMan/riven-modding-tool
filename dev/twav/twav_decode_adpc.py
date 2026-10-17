"""Decode a tWAV ADPC resource to WAV and save it, trying different block sizes."""
import sys, os, struct, subprocess, tempfile, types
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")

# Silence PIL check
_fake = types.ModuleType("PIL"); _fimg = types.ModuleType("PIL.Image")
sys.modules.setdefault("PIL", _fake); sys.modules.setdefault("PIL.Image", _fimg)
_fake.Image = _fimg

import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"
OUT = r"C:\Users\lukea\AppData\Local\Temp\claude\C--Users-lukea-Claude-Projects-Guild\2e9e5703-5a4c-4abf-bb86-19d462572726\scratchpad"

ffmpeg = None
for fp in ["ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        ffmpeg = fp; break
    except: pass
if not ffmpeg:
    sys.exit("ffmpeg not found")

arc = R.Archive(os.path.join(GAME, "a_data.mhk"))
ids = arc.ids(TWAV)
rid = ids[0]
data = arc.read(TWAV, rid)
chunk_sz = struct.unpack_from(">I", data, 16)[0]
meta = data[20:20+chunk_sz]
data_off = 20 + chunk_sz
audio_chunk_sz = struct.unpack_from(">I", data, data_off+4)[0]
audio_start = data_off + 8
audio = data[audio_start:audio_start+audio_chunk_sz]

channels = struct.unpack_from(">H", meta, 0)[0]
print(f"rid={rid} total={len(data)} channels_from_meta={channels} audio={len(audio)} bytes")
print(f"audio[0:8] = {audio[:8].hex()}")
print()

def ima_wav(audio_bytes, rate, channels, block_align):
    spb = (block_align // channels - 4) * 2 + 1
    avg = rate * block_align // spb
    fmt = struct.pack("<HHIIHHhH", 0x0011, channels, rate, avg, block_align, 4, 2, spb)
    fmtc = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    datac = b"data" + struct.pack("<I", len(audio_bytes)) + audio_bytes
    body = fmtc + datac
    return b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body

# Try single-block (block_align = entire audio)
print("=== Single-block IMA ADPCM (full audio as one block) ===")
ba = len(audio)
spb = (ba - 4) * 2 + 1
avg = 22050 * ba // spb
fmt = struct.pack("<HHIIHHhH", 0x0011, 1, 22050, avg, ba, 4, 2, spb)
fmtc = b"fmt " + struct.pack("<I", len(fmt)) + fmt
datac = b"data" + struct.pack("<I", len(audio)) + audio
body = fmtc + datac
wav = b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=OUT) as f:
    f.write(wav); inp = f.name
out = os.path.join(OUT, f"adpc_single_block_{rid}.wav")
r = subprocess.run([ffmpeg, "-y", "-i", inp, out], capture_output=True, text=True, timeout=15)
if os.path.exists(out) and os.path.getsize(out) > 44:
    size = os.path.getsize(out)
    samples = (size - 44) // 2
    dur = samples / 22050
    print(f"Single block: OK, {size} bytes, ~{dur:.1f}s mono at 22050 Hz")
    print(f"Output: {out}")
else:
    print(f"Single block: FAIL — {r.stderr[-200:]}")
os.unlink(inp)

print()

# Try also with the raw "pipe" approach — feed audio as raw s16be or s8
# ScummVM Mohawk sound.cpp approach: IMA ADPCM streaming
# Also try ffmpeg raw input
print("=== Raw ffmpeg -f ima_adpcm direct decode attempt ===")
with tempfile.NamedTemporaryFile(suffix=".bin", delete=False, dir=OUT) as f:
    f.write(audio); inp = f.name
out2 = os.path.join(OUT, f"adpc_raw_{rid}.wav")
r2 = subprocess.run([ffmpeg, "-y",
    "-f", "s16le", "-ar", "22050", "-ac", "1", "-i", inp, out2],
    capture_output=True, text=True, timeout=10)
if os.path.exists(out2) and os.path.getsize(out2) > 44:
    size = os.path.getsize(out2)
    print(f"s16le direct: {size} bytes → {(size-44)//2/22050:.1f}s")
    os.unlink(out2)
else:
    print(f"s16le direct failed")
os.unlink(inp)

# Try: dump whole tWAV to file and let ffprobe sniff it
print()
print("=== ffprobe raw tWAV sniff ===")
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=OUT) as f:
    f.write(data); inp = f.name
ffprobe = None
for fp in ["ffprobe", r"C:\ffmpeg\bin\ffprobe.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        ffprobe = fp; break
    except: pass
if ffprobe:
    r3 = subprocess.run([ffprobe, "-v", "quiet", "-show_streams", "-of", "csv=p=0", inp],
                        capture_output=True, text=True, timeout=10)
    print(f"ffprobe: {r3.stdout.strip() or r3.stderr.strip()[-100:]}")
os.unlink(inp)

# Also dump ScummVM-compatible WAVE header approach
# ScummVM reads ADPC → IMA ADPCM with chunkSize from the header
# Check if block_align should come from meta[8:12]
ba_from_meta_le = struct.unpack_from("<I", meta, 8)[0]  # LE
ba_from_meta_be = struct.unpack_from(">I", meta, 8)[0]  # BE
print(f"\nmeta[8:12] as LE={ba_from_meta_le} BE={ba_from_meta_be}")
# LE = 0x00004000 = 16384, BE = 0x00400000 = 4194304

# Try block_align = 0x4000 = 16384 (assuming LE)
for ba in [16384, 2048, 4096, 8192]:
    if len(audio) % ba == 0:
        print(f"block_align={ba}: DIVIDES EVENLY ({len(audio)//ba} blocks)")
    else:
        print(f"block_align={ba}: remainder={len(audio) % ba}")
