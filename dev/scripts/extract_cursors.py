"""Extract cursors from macgui.dat and preview them as PNG images."""
import zipfile, struct, os
from PIL import Image

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
OUT = r"C:\Users\lukea\AppData\Local\Temp\claude\C--Users-lukea-Claude-Projects-Guild\1d2ef8db-f5fa-4996-9c42-e843e2d74117\scratchpad\cursors"
os.makedirs(OUT, exist_ok=True)

def decode_cur(data):
    """Decode Windows .cur file, return list of (image, hotspot_x, hotspot_y)."""
    if len(data) < 6:
        return []
    reserved, img_type, count = struct.unpack_from("<HHH", data, 0)
    if img_type != 2:  # 2 = cursor
        return []
    results = []
    for i in range(count):
        off = 6 + i * 16
        w, h, cc, res, hx, hy, size, file_off = struct.unpack_from("<BBBBHHIi", data, off)
        w = w or 256
        h = h or 256
        chunk = data[file_off:file_off + size]
        if len(chunk) < 40:
            continue
        # Check for PNG cursor
        if chunk[:8] == b'\x89PNG\r\n\x1a\n':
            img = Image.open(__import__("io").BytesIO(chunk)).convert("RGBA")
        else:
            # DIB cursor
            bih_size, bw, bh, planes, bpp = struct.unpack_from("<IiiHH", chunk, 0)
            # height is doubled (includes AND mask)
            real_h = abs(bh) // 2
            real_w = bw
            if bpp == 32:
                xor_size = real_w * real_h * 4
                xor_data = chunk[40:40 + xor_size]
                pixels = []
                for y in range(real_h - 1, -1, -1):
                    for x in range(real_w):
                        idx = (y * real_w + x) * 4
                        b, g, r, a = xor_data[idx:idx+4]
                        pixels.append((r, g, b, a))
                img = Image.new("RGBA", (real_w, real_h))
                img.putdata(pixels)
            elif bpp == 1:
                # 1-bit cursor with AND mask
                row_bytes = (real_w + 31) // 32 * 4
                xor_start = 40
                xor_size = row_bytes * real_h
                and_start = xor_start + xor_size
                xor_data = chunk[xor_start:xor_start + xor_size]
                and_data = chunk[and_start:and_start + xor_size]
                pixels = []
                for y in range(real_h - 1, -1, -1):
                    for x in range(real_w):
                        byte_idx = y * row_bytes + x // 8
                        bit = 7 - (x % 8)
                        xor_bit = (xor_data[byte_idx] >> bit) & 1 if byte_idx < len(xor_data) else 0
                        and_bit = (and_data[byte_idx] >> bit) & 1 if byte_idx < len(and_data) else 1
                        # AND=0 opaque, AND=1 transparent; XOR=0 black, XOR=1 white (or screen)
                        if and_bit == 1 and xor_bit == 0:
                            pixels.append((0, 0, 0, 0))    # transparent
                        elif and_bit == 0 and xor_bit == 0:
                            pixels.append((0, 0, 0, 255))  # black
                        elif and_bit == 0 and xor_bit == 1:
                            pixels.append((255, 255, 255, 255))  # white
                        else:
                            pixels.append((128, 128, 128, 128))  # invert (approximate)
                img = Image.new("RGBA", (real_w, real_h))
                img.putdata(pixels)
            else:
                continue
        results.append((img, hx, hy))
    return results

# Extract and preview several cursors
interesting_ids = [128, 500, 501, 502, 503, 504, 505, 480, 481, 482,
                   133, 134, 135, 136, 137, 138, 139, 140,
                   209, 210, 211, 212, 213, 214, 215, 216]

with zipfile.ZipFile(os.path.join(GAME, "macgui.dat")) as z:
    names = z.namelist()
    cur_files = {int(n.split("/CURSOR")[1].split("_")[0]): n
                 for n in names if "/CURSOR" in n and n.endswith(".cur")}

    print(f"Total cursor files: {len(cur_files)}")
    print(f"ID range: {min(cur_files.keys())} - {max(cur_files.keys())}")

    for cid in sorted(interesting_ids):
        if cid not in cur_files:
            continue
        data = z.read(cur_files[cid])
        results = decode_cur(data)
        for i, (img, hx, hy) in enumerate(results):
            out_path = os.path.join(OUT, f"cursor_{cid:04d}_hs{hx}_{hy}.png")
            # Scale up 4x for visibility
            big = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
            big.save(out_path)
        print(f"  CURSOR{cid}: {cur_files[cid]}, decoded {len(results)} image(s), hotspot=({results[0][1]},{results[0][2]}) size={results[0][0].size}" if results else f"  CURSOR{cid}: failed")

print(f"\nPreviews saved to {OUT}")
