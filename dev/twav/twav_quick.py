"""Quick tWAV ADPC analysis using proper Archive class."""
import sys, os, struct, subprocess, tempfile
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")

# Patch PIL check — we know PIL is available
import importlib, types
_fake_pil = types.ModuleType("PIL")
_fake_img = types.ModuleType("PIL.Image")
sys.modules.setdefault("PIL", _fake_pil)
sys.modules.setdefault("PIL.Image", _fake_img)
_fake_pil.Image = _fake_img

import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

# Look at a few ADPC tWAV resources
for fn in ["a_data.mhk", "b_data.mhk", "j_sounds.mhk"]:
    arc = R.Archive(os.path.join(GAME, fn))
    ids = arc.ids(TWAV)
    for rid in ids[:3]:
        data = arc.read(TWAV, rid)
        subtag = data[12:16]
        if subtag != b"ADPC":
            continue
        chunk_sz = struct.unpack_from(">I", data, 16)[0]
        meta = data[20:20+chunk_sz]
        data_off = 20 + chunk_sz
        data_tag = data[data_off:data_off+4]
        audio_chunk_sz = struct.unpack_from(">I", data, data_off+4)[0] if data_off+8 <= len(data) else 0
        audio_start = data_off + 8

        print(f"{fn} rid={rid} total={len(data)} ADPC_meta={chunk_sz}b data_tag={data_tag}")
        print(f"  meta hex: {meta.hex()}")
        print(f"  audio_chunk_sz={audio_chunk_sz} audio_start={audio_start}")
        print(f"  first 8 audio bytes: {data[audio_start:audio_start+8].hex()}")
        # Possible: channels at meta[0:2], rate somewhere
        for off in range(0, len(meta)-1, 2):
            v = struct.unpack_from(">H", meta, off)[0]
            if v in (8000, 11025, 22050, 44100):
                print(f"  ** rate candidate {v} at meta+{off}")
        print()

# Now try to decode one ADPC as IMA ADPCM with ffmpeg
arc = R.Archive(os.path.join(GAME, "a_data.mhk"))
ids = arc.ids(TWAV)
rid = ids[0]
data = arc.read(TWAV, rid)
chunk_sz = struct.unpack_from(">I", data, 16)[0]
audio_start = 20 + chunk_sz + 8
audio_chunk_sz = struct.unpack_from(">I", data, 20+chunk_sz+4)[0]
audio = data[audio_start:audio_start+audio_chunk_sz]
meta = data[20:20+chunk_sz]
channels_guess = struct.unpack_from(">H", meta, 0)[0]
print(f"Channels from meta[0:2] = {channels_guess}")

ffmpeg = None
for fp in ["ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        ffmpeg = fp; break
    except: pass

if not ffmpeg:
    print("ffmpeg not found — trying to use ffprobe only")
    sys.exit(0)

print(f"\nTesting ADPC decode ({len(audio)} bytes) with ffmpeg:")

def ima_wav(audio_bytes, rate, channels, block_align):
    spb = (block_align // channels - 4) * 2 + 1
    avg = rate * block_align // spb
    fmt = struct.pack("<HHIIHHhH", 0x0011, channels, rate, avg, block_align, 4, 2, spb)
    fmtc = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    datac = b"data" + struct.pack("<I", len(audio_bytes)) + audio_bytes
    body = fmtc + datac
    return b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body

for rate in [22050, 11025]:
    for channels in [1, 2]:
        for block_align in [512, 1024]:
            wav = ima_wav(audio[:512*20], rate, channels, block_align)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav); inp = f.name
            out = inp + "_out.wav"
            r = subprocess.run([ffmpeg, "-y", "-i", inp, out],
                               capture_output=True, text=True, timeout=8)
            ok = os.path.exists(out) and os.path.getsize(out) > 100
            if ok:
                with open(out, "rb") as f:
                    f.seek(44); pcm = f.read(4000)
                nz = sum(1 for i in range(0,len(pcm)-1,2) if struct.unpack_from("<h",pcm,i)[0] not in range(-5,6))
                print(f"  rate={rate} ch={channels} blk={block_align}: OK sz={os.path.getsize(out)} nz={nz}")
                os.unlink(out)
            else:
                err = (r.stderr or "")[-100:]
                print(f"  rate={rate} ch={channels} blk={block_align}: FAIL {err.strip()[-60:]}")
            os.unlink(inp)
