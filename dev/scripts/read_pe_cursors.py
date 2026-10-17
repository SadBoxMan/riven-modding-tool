"""Parse riven.exe PE resource section looking for cursor resources."""
import struct, sys

RIVEN_EXE = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven\riven.exe"
RT_CURSOR = 1
RT_GROUP_CURSOR = 12

with open(RIVEN_EXE, "rb") as f:
    data = f.read()

# Find PE header offset
mz = data[:2]
print("Magic:", mz)
pe_offset = struct.unpack_from("<I", data, 0x3c)[0]
pe_sig = data[pe_offset:pe_offset+4]
print("PE sig:", pe_sig, "at offset", hex(pe_offset))

if pe_sig != b"PE\x00\x00":
    print("Not a valid PE file")
    sys.exit(1)

# COFF header
machine, num_sections = struct.unpack_from("<HH", data, pe_offset + 4)
print(f"Machine: {machine:#06x}, sections: {num_sections}")

opt_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
is_pe32_plus = struct.unpack_from("<H", data, pe_offset + 24)[0] == 0x20b
print("PE32+:", is_pe32_plus, "opt_size:", opt_size)

# Data directories
dir_offset = pe_offset + 24 + (112 if not is_pe32_plus else 128)
# Resource directory is data dir #2
res_rva, res_size = struct.unpack_from("<II", data, dir_offset + 2 * 8)
print(f"Resource RVA: {res_rva:#010x}, size: {res_size:#010x}")

if res_rva == 0:
    print("No resource section")
    sys.exit(0)

# Find section headers to map RVA to file offset
sections_offset = pe_offset + 24 + opt_size
sections = []
for i in range(num_sections):
    s = sections_offset + i * 40
    name = data[s:s+8].rstrip(b"\x00").decode("ascii", "replace")
    vsize, vaddr, rawsize, rawoff = struct.unpack_from("<IIII", data, s + 8)
    sections.append((name, vaddr, rawsize, rawoff))

def rva_to_file(rva):
    for name, vaddr, rawsize, rawoff in sections:
        if vaddr <= rva < vaddr + rawsize:
            return rawoff + (rva - vaddr)
    return None

res_file_off = rva_to_file(res_rva)
print(f"Resource section file offset: {res_file_off:#010x}")
if not res_file_off:
    print("Could not resolve resource RVA")
    sys.exit(1)

res_base = res_file_off

def read_dir(offset, depth=0):
    named, ided = struct.unpack_from("<HH", data, res_base + offset + 12)
    entries = named + ided
    result = {}
    for i in range(entries):
        e_off = res_base + offset + 16 + i * 8
        name_id = struct.unpack_from("<I", data, e_off)[0]
        data_offset = struct.unpack_from("<I", data, e_off + 4)[0]
        is_subdir = bool(data_offset & 0x80000000)
        is_name = bool(name_id & 0x80000000)
        key = name_id & 0x7fffffff
        sub_off = data_offset & 0x7fffffff
        if is_subdir:
            result[key] = read_dir(sub_off, depth + 1)
        else:
            leaf_off = res_base + sub_off
            leaf_rva, leaf_size, codepage, _ = struct.unpack_from("<IIII", data, leaf_off)
            file_off = rva_to_file(leaf_rva)
            result[key] = (file_off, leaf_size)
    return result

tree = read_dir(0)
print("Top-level resource type IDs:", list(tree.keys()))

# Check for cursor types
for rt, name in [(RT_CURSOR, "RT_CURSOR"), (RT_GROUP_CURSOR, "RT_GROUP_CURSOR")]:
    if rt in tree:
        print(f"\n{name} resources:")
        for res_id, sub in tree[rt].items():
            print(f"  ID {res_id}: {sub}")
    else:
        print(f"No {name} (id={rt})")
