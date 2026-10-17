"""Estimate tWAV resource sizes across all Riven .mhk archives (header-only reads)."""
import os, struct

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"


def scan_mhk(path):
    """Return [(rid, size)] for all tWAV resources in a Mohawk archive."""
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        header = f.read(12)
        if header[:4] != b"MHWK":
            return []
        # Skip to RSRC block — it starts right after the MHWK header (offset 12)
        rsrc_hdr = f.read(20)  # RSRC tag + 16 bytes of RSRC header
        if rsrc_hdr[:4] != b"RSRC":
            return []
        # Bytes 8-9 of RSRC: file_table_offset (relative to RSRC block start = offset 12)
        ft_off, = struct.unpack_from(">H", rsrc_hdr, 8)
        # Bytes 16-17: type_list_offset
        type_off, = struct.unpack_from(">H", rsrc_hdr, 16)
        rsrc_abs = 12  # RSRC block starts at file offset 12

        # Read type list
        tl_abs = rsrc_abs + type_off
        f.seek(tl_abs)
        num_types, = struct.unpack(">H", f.read(2))
        type_entries = f.read(num_types * 8)

        # Find tWAV type entry
        wav_res_off = None
        wav_num_res = 0
        for i in range(num_types):
            tag = type_entries[i*8:i*8+4].decode("latin1")
            res_table_off, num_res = struct.unpack_from(">HH", type_entries, i*8+4)
            if tag == "tWAV":
                wav_res_off = res_table_off
                wav_num_res = num_res
                break
        if wav_res_off is None:
            return []

        # Read resource table for tWAV
        rt_abs = tl_abs + wav_res_off
        f.seek(rt_abs)
        res_entries = f.read(wav_num_res * 10)

        # Read file table header (entry count)
        ft_abs = rsrc_abs + ft_off
        f.seek(ft_abs)
        ft_count, = struct.unpack(">H", f.read(2))
        ft_data = f.read(ft_count * 10)

        results = []
        for j in range(wav_num_res):
            rid, = struct.unpack_from(">H", res_entries, j*10)
            file_table_idx, = struct.unpack_from(">H", res_entries, j*10+2)
            fte = (file_table_idx - 1) * 10  # 1-indexed
            data_off, size_low, size_high = struct.unpack_from(">IHH", ft_data, fte)
            data_size = (size_high << 16) | size_low
            results.append((rid, data_size))
        return results


print(f"{'Archive':<22} {'tWAV':>8} {'Total MB':>10} {'Avg KB':>9} {'Min KB':>8} {'Max KB':>8}")
print("-" * 70)

grand_count = 0
grand_bytes = 0
all_sizes = []

for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    path = os.path.join(GAME, fn)
    try:
        wavs = scan_mhk(path)
    except Exception as e:
        print(f"{fn:<22} ERROR: {e}")
        continue
    if not wavs:
        continue
    sizes = [s for _, s in wavs]
    total = sum(sizes)
    grand_count += len(wavs)
    grand_bytes += total
    all_sizes.extend(sizes)
    avg = total / len(sizes) / 1024
    mn = min(sizes) / 1024
    mx = max(sizes) / 1024
    print(f"{fn:<22} {len(wavs):>8,}  {total/1024/1024:>9.2f}  {avg:>8.1f}  {mn:>7.1f}  {mx:>7.1f}")

print("-" * 70)
print(f"{'TOTAL':<22} {grand_count:>8,}  {grand_bytes/1024/1024:>9.2f}")
print()

if all_sizes:
    all_sizes.sort()
    p50 = all_sizes[len(all_sizes)//2] / 1024
    p90 = all_sizes[int(len(all_sizes)*0.9)] / 1024
    p95 = all_sizes[int(len(all_sizes)*0.95)] / 1024
    print(f"Percentiles — p50: {p50:.1f} KB  p90: {p90:.1f} KB  p95: {p95:.1f} KB")
    small = sum(1 for s in all_sizes if s < 10*1024)
    print(f"Under 10 KB: {small} ({100*small//len(all_sizes)}%)")

print()
print("Replacement budget reference:")
print(f"  5 s stereo 44.1kHz 16-bit WAV = {44100*2*2*5//1024} KB")
print(f" 30 s mono   22 kHz 16-bit WAV  = {22050*1*2*30//1024} KB")
print(f" 60 s stereo 22 kHz 16-bit WAV  = {22050*2*2*60//1024} KB")
