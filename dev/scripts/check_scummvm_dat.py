"""Scan scummvm.dat for Riven cursor data."""
import struct, sys

DAT = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven\scummvm.dat"

with open(DAT, "rb") as f:
    data = f.read()

print(f"File size: {len(data):#x} ({len(data)} bytes)")
print(f"First 16 bytes: {data[:16].hex()}")
print(f"First 16 as ASCII: {data[:16]}")

# Look for 'Riven' string
idx = 0
riven_offsets = []
while True:
    idx = data.find(b"Riven", idx)
    if idx == -1:
        break
    riven_offsets.append(idx)
    idx += 1

print(f"\n'Riven' found {len(riven_offsets)} times")
for off in riven_offsets[:10]:
    ctx = data[max(0, off-8):off+20]
    print(f"  offset {off:#x}: {ctx}")

# Look for tCUR or CURS markers
for marker in [b"tCUR", b"CURS", b"crsr"]:
    idx = data.find(marker)
    if idx != -1:
        print(f"\n{marker} found at {idx:#x}")
        print(f"  context: {data[max(0,idx-8):idx+32].hex()}")
    else:
        print(f"{marker}: not found")
