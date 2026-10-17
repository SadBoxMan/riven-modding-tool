"""Probe tWAV ADPC format without importing PIL."""
import sys, os, struct, subprocess, tempfile

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

# Minimal Mohawk archive reader (no PIL dependency)
def read_mhk(path):
    """Yield (type4, rid, data) for all resources in a Mohawk archive."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"MHWK":
        return
    # MHWK + fileSize(4) + RSRC(4) + version(2) + compaction(2) + RSRCSize(4)
    # + absOffset(4) + fileTableOffset(2) + fileTableSize(2)
    rsrc_off = raw.index(b"RSRC")
    ver, _, rsrc_size, abs_off, ft_off, ft_size = struct.unpack_from(">HHIIHH", raw, rsrc_off+4)
    name_list_off, type_count = struct.unpack_from(">HH", raw, abs_off)
    type_table_off = abs_off + 4
    for i in range(type_count):
        tag_off = type_table_off + i * 8
        tag = raw[tag_off:tag_off+4]
        res_table_off, name_table_off = struct.unpack_from(">HH", raw, tag_off+4)
        rt_abs = abs_off + res_table_off
        count = struct.unpack_from(">H", raw, rt_abs)[0]
        for j in range(count):
            e = rt_abs + 2 + j * 8
            rid, idx = struct.unpack_from(">HH", raw, e)
            ft_abs = abs_off + ft_off + (idx - 1) * 10
            res_off = struct.unpack_from(">I", raw, ft_abs)[0] & 0xFFFFFF
            res_size = struct.unpack_from(">I", raw, ft_abs+4)[0] & 0xFFFFFF
            res_flags = raw[ft_abs+3]
            # actual offset is 3 bytes (the high byte of the uint32 is flags)
            # re-read properly
            val = struct.unpack_from(">I", raw, ft_abs)[0]
            res_off = val & 0xFFFFFFFF
            # Wait — let me check Mohawk file table format
            # Each file table entry: offset(3 bytes big-endian), size(3 bytes big-endian), flags(2 bytes)?
            # Actually from ScummVM source: uint32 offset, uint16 size_hi, uint16 size_lo... let me just try
            res_off = struct.unpack_from(">I", raw, ft_abs)[0]
            hi16, lo16 = struct.unpack_from(">HH", raw, ft_abs+4)
            res_size = lo16 | (hi16 << 16)
            if res_off < len(raw):
                yield tag, rid, raw[res_off:res_off+res_size]

# Find tWAV resources
samples = []
for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    path = os.path.join(GAME, fn)
    try:
        for tag, rid, data in read_mhk(path):
            if tag == TWAV:
                samples.append((fn, rid, data))
    except Exception as e:
        print(f"Error reading {fn}: {e}")

print(f"Found {len(samples)} tWAV resources")

# Analyze first few ADPC ones
adpc = [(fn,rid,d) for fn,rid,d in samples if len(d)>16 and d[12:16]==b"ADPC"]
datap = [(fn,rid,d) for fn,rid,d in samples if len(d)>16 and d[12:16]==b"Data"]
print(f"ADPC: {len(adpc)}, Data: {len(datap)}")
print()

# Show unique ADPC header patterns
seen = set()
for fn, rid, data in adpc[:50]:
    h = data[:48].hex()
    if h not in seen:
        seen.add(h)
        chunk_size = struct.unpack_from(">I", data, 16)[0]
        data_tag_off = 20 + chunk_size
        data_chunk_size = struct.unpack_from(">I", data, data_tag_off+4)[0] if data_tag_off+8 <= len(data) else 0
        audio_start = data_tag_off + 8
        print(f"ADPC {fn} rid={rid} total={len(data)}")
        print(f"  chunk_size={chunk_size} data_tag_off={data_tag_off} data_chunk_size={data_chunk_size} audio_start={audio_start}")
        print(f"  header hex: {data[:48].hex()}")
        if audio_start < len(data):
            print(f"  first audio bytes: {data[audio_start:audio_start+8].hex()}")
        print()

# Try ffmpeg on ADPC audio
print("=== Trying to decode first ADPC as IMA ADPCM ===")
fn, rid, raw_data = adpc[0]
chunk_size = struct.unpack_from(">I", raw_data, 16)[0]
data_tag_off = 20 + chunk_size
data_chunk_size = struct.unpack_from(">I", raw_data, data_tag_off+4)[0]
audio_start = data_tag_off + 8
audio = raw_data[audio_start:audio_start + data_chunk_size]
print(f"Audio: {len(audio)} bytes from {fn} rid={rid}")

# Build a WAV container for IMA ADPCM
def make_ima_wav(audio_bytes, rate, channels, block_align):
    samples_per_block = (block_align // channels - 4) * 2 + 1
    num_blocks = len(audio_bytes) // block_align
    num_samples = num_blocks * samples_per_block * channels

    fmt = struct.pack("<HHIIHHh",
        0x0011, channels, rate,
        rate * block_align // (samples_per_block * channels * 2 // 8 * 8),
        block_align, 4, 2) + struct.pack("<H", samples_per_block)
    # Actually simpler:
    avg_bytes = rate * block_align // samples_per_block
    fmt = struct.pack("<HHIIHHh", 0x0011, channels, rate, avg_bytes, block_align, 4, 2)
    fmt += struct.pack("<H", samples_per_block)

    fact = b"fact" + struct.pack("<II", 4, num_samples)
    fmtc = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    datac = b"data" + struct.pack("<I", len(audio_bytes)) + audio_bytes
    body = fmtc + fact + datac
    return b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body

# Brute-force: try all combinations
ffmpeg = None
for fp in ["ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        ffmpeg = fp; break
    except: pass

if ffmpeg:
    best = None
    for rate in [22050, 11025]:
        for channels in [1, 2]:
            for block_align in [512, 1024, 256]:
                wav = make_ima_wav(audio, rate, channels, block_align)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(wav); tmp_in = f.name
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    tmp_out = f.name
                r = subprocess.run([ffmpeg, "-y", "-i", tmp_in, tmp_out],
                                   capture_output=True, text=True, timeout=10)
                ok = os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 44
                if ok:
                    with open(tmp_out, "rb") as f:
                        f.seek(44); pcm = f.read(2000)
                    nz = sum(1 for i in range(0, len(pcm)-1, 2)
                             if struct.unpack_from("<h", pcm, i)[0] not in (0, -1))
                    sz = os.path.getsize(tmp_out)
                    print(f"rate={rate} ch={channels} block={block_align}: OK sz={sz} nonzero={nz}")
                    if nz > 100 and best is None:
                        best = (rate, channels, block_align, tmp_out)
                        tmp_out = None  # keep it
                if tmp_out and os.path.exists(tmp_out):
                    os.unlink(tmp_out)
                os.unlink(tmp_in)
    if best:
        print(f"\nBest: rate={best[0]} ch={best[1]} block={best[2]}")
        print(f"Saved to: {best[3]}")
else:
    print("ffmpeg not found")
