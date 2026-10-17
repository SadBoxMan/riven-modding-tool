"""Audit all tWAV resources: format, rate, channels, duration."""
import sys, os, struct, subprocess, tempfile
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

# Find ffprobe
FFPROBE = None
for fp in ["ffprobe", r"C:\ffmpeg\bin\ffprobe.exe",
           r"C:\Program Files\ffmpeg\bin\ffprobe.exe"]:
    try:
        subprocess.run([fp, "-version"], capture_output=True, timeout=3)
        FFPROBE = fp
        break
    except Exception:
        pass

def probe(data):
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(data); tmp = f.name
    try:
        r = subprocess.run(
            [FFPROBE, "-v","error","-show_entries",
             "stream=codec_name,sample_rate,channels,duration",
             "-of","csv=p=0", tmp],
            capture_output=True, text=True, timeout=5)
        line = r.stdout.strip()
        return line if line else None
    except Exception:
        return None
    finally:
        os.unlink(tmp)

adpc_samples = []
data_samples = []

for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    arc = R.Archive(os.path.join(GAME, fn))
    ids = arc.ids(TWAV)
    for rid in ids:
        data = arc.read(TWAV, rid)
        tag = data[12:16].decode("latin1", "replace")
        size = len(data)
        # Bytes 16-31 — the sub-header
        hdr = data[16:48].hex() if len(data) >= 48 else data[16:].hex()
        if tag == "ADPC":
            adpc_samples.append((fn, rid, size, hdr))
        elif tag == "Data":
            data_samples.append((fn, rid, size, hdr))

print(f"ADPC sounds: {len(adpc_samples)}")
print(f"Data sounds: {len(data_samples)}")
print()

print("=== ADPC sub-header patterns (bytes 16-47) ===")
seen = set()
for fn, rid, sz, hdr in adpc_samples[:20]:
    if hdr not in seen:
        seen.add(hdr)
        print(f"  {fn} rid={rid} size={sz}: {hdr}")
        # Try to interpret: uint16 rate, uint8 channels, uint8 bps at different offsets
        raw = bytes.fromhex(hdr)
        for off in range(0, min(12, len(raw)-1)):
            r16 = struct.unpack_from(">H", raw, off)[0]
            if r16 in (8000, 11025, 22050, 44100, 16000, 24000, 32000):
                print(f"    possible sampleRate={r16} at sub-hdr offset +{off}")

print()
print("=== Data sub-header patterns (bytes 16-47) ===")
seen = set()
for fn, rid, sz, hdr in data_samples[:10]:
    if hdr not in seen:
        seen.add(hdr)
        print(f"  {fn} rid={rid} size={sz}: {hdr}")
        raw = bytes.fromhex(hdr)
        for off in range(0, min(12, len(raw)-1)):
            r16 = struct.unpack_from(">H", raw, off)[0]
            if r16 in (8000, 11025, 22050, 44100, 16000, 24000, 32000):
                print(f"    possible sampleRate={r16} at sub-hdr offset +{off}")

if FFPROBE and data_samples:
    print()
    print("=== ffprobe on Data sounds ===")
    fn, rid, sz, _ = data_samples[0]
    arc = R.Archive(os.path.join(GAME, fn))
    data = arc.read(TWAV, rid)
    result = probe(data)
    print(f"  {fn} rid={rid}: {result}")
    # Also probe skipping the 20-byte MHWK wrapper (just the MP2 bytes)
    mp2_data = data[20:]
    result2 = probe(mp2_data)
    print(f"  {fn} rid={rid} (raw MP2 skip 20): {result2}")
    # Try skipping different header sizes
    for skip in [12, 16, 20, 24, 28]:
        result3 = probe(data[skip:])
        if result3:
            print(f"  skip={skip}: {result3}")
