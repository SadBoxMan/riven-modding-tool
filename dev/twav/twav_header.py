"""Read and parse full tWAV DATA header for multiple resources."""
import sys, os, struct, subprocess, tempfile, types
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")

_fake = types.ModuleType("PIL"); _fimg = types.ModuleType("PIL.Image")
sys.modules.setdefault("PIL", _fake); sys.modules.setdefault("PIL.Image", _fimg)
_fake.Image = _fimg

import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

def parse_twav(data):
    """Parse a full tWAV resource. Returns dict with all fields."""
    pos = 12  # skip MHWK outer header
    result = {}
    while pos < len(data):
        tag = data[pos:pos+4]
        if len(tag) < 4:
            break
        chunk_size = struct.unpack_from(">I", data, pos+4)[0]
        if tag == b"ADPC":
            # Seek table
            item_count = struct.unpack_from(">H", data, pos+8)[0]
            channels = struct.unpack_from(">H", data, pos+10)[0]
            result["adpc_items"] = item_count
            result["adpc_channels"] = channels
        elif tag == b"Data":
            # Audio data chunk — 20-byte header
            payload_size = chunk_size  # includes 20-byte header
            hdr = data[pos+8:pos+8+20]
            sample_rate = struct.unpack_from(">H", hdr, 0)[0]
            sample_count = struct.unpack_from(">I", hdr, 2)[0]
            bits_per_sample = hdr[6]
            channels = hdr[7]
            encoding = struct.unpack_from(">H", hdr, 8)[0]
            loop_count = struct.unpack_from(">H", hdr, 10)[0]
            loop_start = struct.unpack_from(">I", hdr, 12)[0]
            loop_end = struct.unpack_from(">I", hdr, 16)[0]
            audio_start = pos + 8 + 20
            audio_size = payload_size - 20
            result.update({
                "sample_rate": sample_rate, "sample_count": sample_count,
                "bits_per_sample": bits_per_sample, "channels": channels,
                "encoding": encoding, "loop_count": loop_count,
                "loop_start": loop_start, "loop_end": loop_end,
                "audio_start": audio_start, "audio_size": audio_size,
                "data_hdr_hex": hdr.hex()
            })
        pos += 8 + chunk_size
    return result

# Encoding constants from ScummVM sound.h
ENCODING_NAMES = {0: "Raw", 1: "ADPCM", 2: "MP2/MPEG2"}

for fn in ["a_data.mhk", "b_data.mhk", "j_sounds.mhk", "a_sounds.mhk"]:
    path = os.path.join(GAME, fn)
    arc = R.Archive(path)
    ids = arc.ids(TWAV)
    print(f"\n=== {fn} ({len(ids)} tWAV) ===")
    shown = set()
    for rid in ids[:10]:
        d = arc.read(TWAV, rid)
        info = parse_twav(d)
        if not info.get("encoding") is None:
            enc = info["encoding"]
            key = (enc, info.get("bits_per_sample"), info.get("channels"))
            if key not in shown:
                shown.add(key)
                enc_name = ENCODING_NAMES.get(enc, f"unknown({enc})")
                blk = info["channels"] * info["bits_per_sample"] // 8 if enc == 1 else 0
                print(f"  rid={rid} rate={info['sample_rate']} samples={info['sample_count']} "
                      f"bps={info['bits_per_sample']} ch={info['channels']} enc={enc}({enc_name}) "
                      f"loop_cnt={info['loop_count']} audio={info['audio_size']}b")
                print(f"  DATA header hex: {info['data_hdr_hex']}")
                if enc == 1:
                    print(f"  blockAlign = {blk} → calling makeADPCMStream(kADPCMDVI, rate={info['sample_rate']}, ch={info['channels']}, blk={blk})")
                dur = info["sample_count"] / info["sample_rate"] if info["sample_rate"] else 0
                print(f"  Duration: {dur:.2f}s")
                print()

# Now try to actually decode one ADPCM sound using ffmpeg
print("=== Attempting ADPCM decode with blockAlign=4 (DVI IMA ADPCM WAV) ===")
arc = R.Archive(os.path.join(GAME, "a_data.mhk"))
d = arc.read(TWAV, arc.ids(TWAV)[0])
info = parse_twav(d)
audio = d[info["audio_start"]:info["audio_start"]+info["audio_size"]]
print(f"Audio: {len(audio)} bytes, expected {info['sample_count']} samples at {info['sample_rate']} Hz {info['channels']}ch")
print(f"First 16 audio bytes: {audio[:16].hex()}")
print()

# ScummVM blockAlign = channels * bitsPerSample / 8 = 2 * 16 / 8 = 4
# This is DVI ADPCM: each "block" = 4 bytes = {int16 predictor, uint16 stepIndex} per-channel interleaved?
# Or: 4-byte IMA block header = predictor(2)+step(1)+reserved(1) for mono, doubled for stereo
# Actually kADPCMDVI with blockAlign=4 in ScummVM = standard IMA ADPCM with 4-byte blocks

# Let's try WAV IMA ADPCM with blockAlign=4, channels=2, rate=22050
# With blockAlign=4 and stereo: each block = 4 bytes, header per channel = 4 bytes each = 8 bytes...
# that doesn't work. Must be mono blockAlign=4.

# For mono IMA ADPCM, blockAlign=512:
# spb = (512 - 4) * 2 + 1 = 1017 samples/block
# For blockAlign=4, mono: spb = (4-4)*2+1 = 1 sample/block — that's just the predictor init!

# ScummVM DVI implementation might use a different interpretation.
# Let me look at how ScummVM's ADPCMStream kADPCMDVI works with blockAlign=4.
# I think blockAlign=4 means 4 bytes of interleaved stereo IMA nibbles = 8 nibbles = 8 samples.

# Actually: the DVI/IMA ADPCM in Mohawk might store data as:
# Continuous nibble stream with per-block header at fixed intervals.
# blockAlign could be the number of bytes per interleaved stereo pair.

ffmpeg = None
for fp in ["ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        ffmpeg = fp; break
    except: pass

OUT = r"C:\Users\lukea\AppData\Local\Temp\claude\C--Users-lukea-Claude-Projects-Guild\2e9e5703-5a4c-4abf-bb86-19d462572726\scratchpad"

if ffmpeg:
    # Try with ScummVM-computed blockAlign = 4, stereo, 22050 Hz
    for rate, channels, block_align in [(22050, 2, 4), (22050, 1, 4), (22050, 2, 512), (22050, 2, 1024)]:
        if block_align < channels * 4:
            continue
        spb_mono = (block_align // channels - 4) * 2 + 1
        if spb_mono < 1:
            continue
        avg = rate * block_align // (spb_mono * channels)
        fmt = struct.pack("<HHIIHHhH", 0x0011, channels, rate, avg, block_align, 4, 2, spb_mono)
        fmtc = b"fmt " + struct.pack("<I", len(fmt)) + fmt
        datac = b"data" + struct.pack("<I", len(audio)) + audio
        body = fmtc + datac
        wav = b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav); inp = f.name
        out = os.path.join(OUT, f"adpcm_ch{channels}_blk{block_align}.wav")
        r = subprocess.run([ffmpeg, "-y", "-i", inp, out], capture_output=True, text=True, timeout=15)
        if os.path.exists(out) and os.path.getsize(out) > 44:
            size = os.path.getsize(out)
            dur = (size-44) / 2 / channels / rate
            print(f"WAV ch={channels} blk={block_align}: OK {size}b → {dur:.2f}s → {out}")
        else:
            print(f"WAV ch={channels} blk={block_align}: FAIL {r.stderr[-100:]}")
        os.unlink(inp)
