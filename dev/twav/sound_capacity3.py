"""Estimate tWAV resource sizes using riven_img.Archive."""
import sys, os
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

print(f"{'Archive':<24} {'tWAV':>7} {'Total MB':>10} {'Avg KB':>9} {'Max KB':>8}")
print("-" * 63)

grand_count = 0
grand_bytes = 0
all_sizes = []

for fn in sorted(os.listdir(GAME)):
    if not fn.lower().endswith(".mhk"):
        continue
    path = os.path.join(GAME, fn)
    try:
        arc = R.Archive(path)
    except Exception:
        continue
    ids = arc.ids(TWAV)
    if not ids:
        continue
    sizes = [arc.span(TWAV, rid)[1] for rid in ids]
    total = sum(sizes)
    grand_count += len(sizes)
    grand_bytes += total
    all_sizes.extend(sizes)
    avg = total / len(sizes) / 1024
    mx = max(sizes) / 1024
    print(f"{fn:<24} {len(sizes):>7,}  {total/1024/1024:>9.2f}  {avg:>8.1f}  {mx:>7.1f}")

print("-" * 63)
print(f"{'TOTAL':<24} {grand_count:>7,}  {grand_bytes/1024/1024:>9.2f}")
print()

if all_sizes:
    all_sizes.sort()
    p50 = all_sizes[len(all_sizes)//2] / 1024
    p90 = all_sizes[int(len(all_sizes)*0.9)] / 1024
    p95 = all_sizes[int(len(all_sizes)*0.95)] / 1024
    print(f"Percentiles — median: {p50:.1f} KB   p90: {p90:.1f} KB   p95: {p95:.1f} KB")
    small = sum(1 for s in all_sizes if s < 5*1024)
    print(f"Under 5 KB (SFX / ambient hits): {small} ({100*small//len(all_sizes)}%)")
    large = sum(1 for s in all_sizes if s > 100*1024)
    print(f"Over 100 KB (longer clips):       {large} ({100*large//len(all_sizes)}%)")

print()
print("Replacement budget reference:")
print(f"  5 s stereo 44.1 kHz 16-bit PCM = {44100*2*2*5//1024:>5} KB")
print(f" 30 s mono   22 kHz  16-bit PCM  = {22050*1*2*30//1024:>5} KB")
print(f" 60 s stereo 22 kHz  16-bit PCM  = {22050*2*2*60//1024:>5} KB")
print(f"120 s stereo 44.1 kHz 16-bit PCM = {44100*2*2*120//1024:>5} KB")
