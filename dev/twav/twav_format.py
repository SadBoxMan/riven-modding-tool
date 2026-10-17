import sys, struct, os
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

for fname in ["a_sounds.mhk", "a_data.mhk", "j_sounds.mhk", "b_data.mhk"]:
    path = os.path.join(GAME, fname)
    arc = R.Archive(path)
    ids = arc.ids(TWAV)
    if not ids:
        continue
    for rid in ids[:2]:
        data = arc.read(TWAV, rid)
        # MHWK(4) + fileSize(4) + WAVE(4) = 12 bytes
        # Then subtag chunk: tag(4) + chunkDataSize(4) + numSamples(4) + rate(2) + channels(1) + bps(1) = 16
        subtag = data[12:16].decode("latin1")
        chunk_data_size = struct.unpack_from(">I", data, 16)[0]
        num_samples, rate = struct.unpack_from(">IH", data, 20)
        channels = data[26]
        bps = data[27]
        audio_start = 28
        audio_bytes = len(data) - audio_start
        dur = num_samples / rate if rate else 0
        print(f"{fname:<22} rid={rid:<4} tag={subtag!r:<7} total={len(data):<8} "
              f"chunkSize={chunk_data_size:<8} nSamples={num_samples:<8} rate={rate:<6} "
              f"ch={channels} bps={bps} audio_bytes={audio_bytes} dur={dur:.2f}s")
