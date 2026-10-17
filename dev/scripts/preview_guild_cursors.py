"""Preview all cursors in the guild/cursors folder as PNGs."""
import struct, os, io
from PIL import Image

SRC = r"C:\Users\lukea\Claude\Projects\Guild\cursors"
OUT = r"C:\Users\lukea\AppData\Local\Temp\claude\C--Users-lukea-Claude-Projects-Guild\1d2ef8db-f5fa-4996-9c42-e843e2d74117\scratchpad\guild_cursors"
os.makedirs(OUT, exist_ok=True)

def decode_cur(data):
    if len(data) < 6:
        return []
    reserved, img_type, count = struct.unpack_from("<HHH", data, 0)
    if img_type not in (1, 2):  # 1=icon, 2=cursor
        return []
    results = []
    for i in range(count):
        off = 6 + i * 16
        w, h, cc, res, hx, hy, size, file_off = struct.unpack_from("<BBBBHHIi", data, off)
        w = w or 256; h = h or 256
        chunk = data[file_off:file_off + size]
        if len(chunk) < 8:
            continue
        if chunk[:8] == b'\x89PNG\r\n\x1a\n':
            img = Image.open(io.BytesIO(chunk)).convert("RGBA")
        else:
            if len(chunk) < 40:
                continue
            bih_size, bw, bh, planes, bpp = struct.unpack_from("<IiiHH", chunk, 0)
            real_h = abs(bh) // 2
            real_w = bw
            if bpp == 32:
                xor_size = real_w * real_h * 4
                xor = chunk[40:40 + xor_size]
                px = []
                for y in range(real_h - 1, -1, -1):
                    for x in range(real_w):
                        idx = (y * real_w + x) * 4
                        b, g, r, a = xor[idx:idx+4]
                        px.append((r, g, b, a))
                img = Image.new("RGBA", (real_w, real_h))
                img.putdata(px)
            elif bpp in (1, 4, 8):
                row_bytes = (real_w + 31) // 32 * 4
                if bpp == 1:
                    xor_data = chunk[40:40 + row_bytes * real_h]
                    and_data = chunk[40 + row_bytes * real_h:40 + 2 * row_bytes * real_h]
                    px = []
                    for y in range(real_h - 1, -1, -1):
                        for x in range(real_w):
                            bi = y * row_bytes + x // 8
                            bit = 7 - (x % 8)
                            xb = (xor_data[bi] >> bit) & 1 if bi < len(xor_data) else 0
                            ab = (and_data[bi] >> bit) & 1 if bi < len(and_data) else 1
                            if ab == 1:
                                px.append((0, 0, 0, 0))
                            elif xb == 0:
                                px.append((0, 0, 0, 255))
                            else:
                                px.append((255, 255, 255, 255))
                    img = Image.new("RGBA", (real_w, real_h))
                    img.putdata(px)
                else:
                    continue
            else:
                continue
        results.append((img, hx, hy))
    return results

for fn in sorted(os.listdir(SRC)):
    path = os.path.join(SRC, fn)
    if not fn.lower().endswith(".cur"):
        continue
    with open(path, "rb") as f:
        data = f.read()
    results = decode_cur(data)
    if results:
        img, hx, hy = results[0]
        big = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
        out_path = os.path.join(OUT, fn.replace(".cur", ".png"))
        big.save(out_path)
        print(f"{fn}: {img.size} hotspot=({hx},{hy})")
    else:
        print(f"{fn}: could not decode")
