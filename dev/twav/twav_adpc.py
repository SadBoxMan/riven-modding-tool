"""Crack the ADPC sub-format and try to decode to audio."""
import sys, os, struct, subprocess, tempfile
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

arc = R.Archive(os.path.join(GAME, "a_data.mhk"))
data = arc.read(TWAV, 0)

print(f"Total size: {len(data)}")
print(f"Bytes 0-63 hex: {data[:64].hex()}")
print()

# Parse the known structure
mhwk_filesize = struct.unpack_from(">I", data, 4)[0]
print(f"MHWK inner filesize: {mhwk_filesize}")
subtag = data[12:16].decode("latin1")
adpc_chunk_size = struct.unpack_from(">I", data, 16)[0]
print(f"ADPC subtag={subtag!r} chunkSize={adpc_chunk_size}")

# After ADPC chunk header (12 bytes: tag+size), we have chunkSize bytes of ADPC metadata
adpc_meta_start = 20
adpc_meta = data[adpc_meta_start:adpc_meta_start + adpc_chunk_size]
print(f"ADPC metadata ({adpc_chunk_size} bytes): {adpc_meta.hex()}")

# Then comes the Data sub-chunk
data_tag_off = 20 + adpc_chunk_size
data_tag = data[data_tag_off:data_tag_off+4].decode("latin1")
data_chunk_size = struct.unpack_from(">I", data, data_tag_off+4)[0]
audio_start = data_tag_off + 8
print(f"Data tag={data_tag!r} at offset {data_tag_off}, chunkSize={data_chunk_size}, audioStart={audio_start}")
print(f"Remaining after audio: {len(data) - audio_start - data_chunk_size}")
print(f"First 16 audio bytes: {data[audio_start:audio_start+16].hex()}")
print()

# Try to interpret ADPC metadata bytes as parameters
# Known: most ADPC are 16 bytes, b_data.mhk rid=15 is 12 bytes
# 16-byte pattern: 0001 0002 00000000 00400000 00400000
# 12-byte pattern: 0001 0001 00000000 00400000
meta = adpc_meta
print("ADPC metadata interpretation:")
print(f"  uint16[0] = {struct.unpack_from('>H', meta, 0)[0]}")  # channels?
print(f"  uint16[1] = {struct.unpack_from('>H', meta, 2)[0]}")
print(f"  uint32[1] = {struct.unpack_from('>I', meta, 4)[0]}")
print(f"  uint32[2] = {struct.unpack_from('>I', meta, 8)[0]}")
if len(meta) >= 16:
    print(f"  uint32[3] = {struct.unpack_from('>I', meta, 12)[0]}")
print()

# Try decoding the Data chunk audio as IMA ADPCM WAV at various sample rates
# IMA ADPCM WAV header for mono 22050 Hz, block align = len(audio)//1 or 512
audio_bytes = data[audio_start:audio_start + data_chunk_size]
print(f"Audio data size: {len(audio_bytes)} bytes")

def try_decode_adpcm(audio_bytes, rate, channels, block_align):
    """Write a WAV container for IMA ADPCM and try ffprobe/ffmpeg on it."""
    num_samples = (len(audio_bytes) // block_align) * (block_align - 4*channels) * 2 + channels*2
    # RIFF WAVE header for IMA ADPCM (format code 0x0011)
    fact_chunk = b"fact" + struct.pack("<I", num_samples)
    fmt_chunk_data = struct.pack("<HHIIHHh",
        0x0011,        # wFormatTag: IMA ADPCM
        channels,      # nChannels
        rate,          # nSamplesPerSec
        rate * block_align // ((block_align - 4*channels) * 2 + 1),  # nAvgBytesPerSec approx
        block_align,   # nBlockAlign
        4,             # wBitsPerSample
        2              # cbSize: extra bytes (SamplesPerBlock)
    )
    samples_per_block = (block_align - 4*channels) * 2 + 1
    fmt_chunk_data += struct.pack("<H", samples_per_block)
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt_chunk_data)) + fmt_chunk_data
    data_chunk = b"data" + struct.pack("<I", len(audio_bytes)) + audio_bytes
    riff_body = fmt_chunk + fact_chunk + data_chunk
    wav = b"RIFF" + struct.pack("<I", len(riff_body)) + b"WAVE" + riff_body

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav); tmp_in = f.name
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_out = f.name

    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_in, "-ar", str(rate), tmp_out],
            capture_output=True, text=True, timeout=10
        )
        if os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 44:
            size_out = os.path.getsize(tmp_out)
            # Check if output has any non-zero samples
            with open(tmp_out, "rb") as f:
                f.seek(44)
                pcm = f.read(1000)
            nonzero = sum(1 for b in pcm if b != 0 and b != 128)
            return f"OK size={size_out} nonzero_samples={nonzero}"
        return f"FAIL: {r.stderr[-200:]}"
    except Exception as e:
        return f"ERR: {e}"
    finally:
        for t in [tmp_in, tmp_out]:
            try: os.unlink(t)
            except: pass

for rate in [22050, 11025, 44100]:
    for channels in [1, 2]:
        for block_align in [512, 256, 1024, 16384]:
            result = try_decode_adpcm(audio_bytes[:min(len(audio_bytes), 512*100)], rate, channels, block_align)
            if "OK" in result and "nonzero_samples=0" not in result:
                print(f"rate={rate} ch={channels} block={block_align}: {result}")
