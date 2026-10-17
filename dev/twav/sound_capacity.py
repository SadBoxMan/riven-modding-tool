"""Estimate tWAV resource sizes across all Riven .mhk archives."""
import os, struct

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"


def read_mohawk_resources(path):
    """Parse a Mohawk archive and return {tag: [(rid, offset, size), ...]}."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"MHWK":
        return {}
    rsrc_off = raw.find(b"RSRC")
    if rsrc_off == -1:
        return {}
    # RSRC block: 4-byte tag, 4-byte size, 2-byte file_table_offset, 2-byte file_table_size,
    #             4-byte ?, 2-byte name_list_offset, 2-byte type_list_offset
    type_off, = struct.unpack_from(">H", raw, rsrc_off + 16)
    tl_start = rsrc_off + type_off
    num_types, = struct.unpack_from(">H", raw, tl_start)
    result = {}
    for i in range(num_types):
        te = tl_start + 2 + i * 8
        tag = raw[te:te + 4].decode("latin1")
        res_table_off, num_res = struct.unpack_from(">HH", raw, te + 4)
        resources = []
        for j in range(num_res):
            re = tl_start + res_table_off + j * 10
            rid, = struct.unpack_from(">H", raw, re)
            file_table_idx, = struct.unpack_from(">H", raw, re + 2)
            # File table: at rsrc_off + file_table_offset (bytes 8-9 of RSRC header)
            ft_off, = struct.unpack_from(">H", raw, rsrc_off + 8)
            ft_base = rsrc_off + ft_off
            ft_entry = ft_base + 2 + (file_table_idx - 1) * 10  # 1-indexed
            data_off, data_size = struct.unpack_from(">IH", raw, ft_entry)
            resources.append((rid, data_off, data_size * (1 << struct.unpack_from(">H", raw, ft_entry + 6)[0]
                                                          if False else 1)))
            # Actually data_size in file table is just low 16 bits; flags are separate
        result[tag] = resources
    return result


def read_mohawk_simple(path):
    """Simpler: just scan for tWAV by looking at name-type pairs."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"MHWK":
        return {}
    rsrc_off = raw.find(b"RSRC")
    if rsrc_off == -1:
        return {}
    # offsets from RSRC block start:
    #   +4  size (4)
    #   +8  file_table_offset (2, relative to RSRC start)
    #   +10 file_table_size (2)
    #   +12 ??? (2)
    #   +14 name_list_offset (2, relative to RSRC start)
    #   +16 type_list_offset (2, relative to RSRC start)
    ft_off, = struct.unpack_from(">H", raw, rsrc_off + 8)
    type_off, = struct.unpack_from(">H", raw, rsrc_off + 16)

    ft_base = rsrc_off + ft_off
    tl_start = rsrc_off + type_off

    num_types, = struct.unpack_from(">H", raw, tl_start)
    result = {}
    for i in range(num_types):
        te = tl_start + 2 + i * 8
        tag = raw[te:te + 4].decode("latin1")
        res_table_off, num_res = struct.unpack_from(">HH", raw, te + 4)
        resources = []
        for j in range(num_res):
            re_off = tl_start + res_table_off + j * 10
            rid, = struct.unpack_from(">H", raw, re_off)
            file_table_idx, = struct.unpack_from(">H", raw, re_off + 2)
            # File table entry (1-indexed, each entry is 10 bytes):
            #   offset (4), size_low (2), size_high (2), flags (2)
            fte = ft_base + 2 + (file_table_idx - 1) * 10
            data_off, size_low, size_high = struct.unpack_from(">IHH", raw, fte)
            data_size = (size_high << 16) | size_low
            resources.append((rid, data_off, data_size))
        result[tag] = resources
    return result


print(f"{'Archive':<20} {'tWAV count':>12} {'Total MB':>10} {'Avg KB':>9}")
print("-" * 56)

grand_count = 0
grand_bytes = 0

for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    path = os.path.join(GAME, fn)
    try:
        res = read_mohawk_simple(path)
    except Exception as e:
        print(f"{fn:<20} ERROR: {e}")
        continue
    wavs = res.get("tWAV", [])
    total = sum(s for _, _, s in wavs)
    grand_count += len(wavs)
    grand_bytes += total
    if wavs:
        avg = total / len(wavs) / 1024
        print(f"{fn:<20} {len(wavs):>12,}  {total/1024/1024:>9.2f}  {avg:>8.1f}")

print("-" * 56)
print(f"{'TOTAL':<20} {grand_count:>12,}  {grand_bytes/1024/1024:>9.2f}")
print()

# Also check what a replacement WAV might look like size-wise
# A 44.1kHz stereo 16-bit 5-second clip = 44100*2*2*5 = ~882 KB raw PCM
# Mohawk stores WAV as raw PCM (no header) after a small tWAV header
print(f"Reference: 5s stereo 44.1kHz 16-bit ≈ {44100*2*2*5/1024:.0f} KB")
print(f"Reference: 30s mono 22kHz 16-bit      ≈ {22050*1*2*30/1024:.0f} KB")
print(f"Reference: 60s stereo 22kHz 8-bit     ≈ {22050*2*1*60/1024:.0f} KB")
