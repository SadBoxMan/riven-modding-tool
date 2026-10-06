"""
riven_layers.py - read and write layered image files for editing a whole card at once.

  PSD  (Photoshop; also opens in GIMP, Krita, Affinity, and Paint.NET with a plugin)
  ORA  (OpenRaster; GIMP and Krita read and write it natively)

A layer is a dict:  {"name": str, "image": PIL image, "x": int, "y": int, "visible": bool}
Layer lists run BOTTOM to TOP. Readers also report "opacity", "blend" and "warnings" for settings that
Riven can't use (the game draws plain opaque rectangles), so the caller can tell the user.

Everything is written and parsed here (no extra libraries), following the published PSD and OpenRaster specs.
"""
import io
import struct
import zipfile
import zlib
import xml.etree.ElementTree as ET

from PIL import Image


class LayerFileError(ValueError):
    """The file can't be used as a layered card (with a message fit to show the user)."""


# ---------------------------------------------------------------------------- shared helpers
def flatten(size, layers, background=(0, 0, 0, 255)):
    """Composite the visible layers (bottom to top) onto a canvas and return it as RGB."""
    out = Image.new("RGBA", size, background)
    for L in layers:
        if not L.get("visible", True):
            continue
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(L["image"].convert("RGBA"), (int(L.get("x", 0)), int(L.get("y", 0))))
        opacity = float(L.get("opacity", 1.0))
        if opacity < 1.0:
            canvas.putalpha(canvas.getchannel("A").point(lambda v: int(v * opacity)))
        out = Image.alpha_composite(out, canvas)
    return out.convert("RGB")


def _pascal(name):
    b = name.encode("latin-1", "replace")[:255]
    s = bytes([len(b)]) + b
    return s + b"\0" * ((-len(s)) % 4)


def packbits(data, width):
    """PackBits-compress `data` row by row (each row `width` bytes). Returns (row byte counts, stream)."""
    counts, out = [], bytearray()
    for r in range(0, len(data), width):
        row = data[r:r + width]
        enc = bytearray()
        i, n = 0, len(row)
        while i < n:
            j = i
            while j + 1 < n and j - i < 127 and row[j + 1] == row[i]:
                j += 1
            if j > i:                                   # a run of j-i+1 equal bytes
                enc += bytes([257 - (j - i + 1), row[i]])
                i = j + 1
            else:                                       # literals until the next run
                k = i
                while k < n and k - i < 128 and not (k + 1 < n and row[k + 1] == row[k]):
                    k += 1
                k = max(k, i + 1)
                enc += bytes([k - i - 1]) + row[i:k]
                i = k
        counts.append(len(enc))
        out += enc
    return counts, bytes(out)


def unpackbits(src, expect):
    out = bytearray()
    i, n = 0, len(src)
    while i < n and len(out) < expect:
        c = src[i]
        i += 1
        if c < 128:
            out += src[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += src[i:i + 1] * (257 - c)
            i += 1
    if len(out) < expect:
        out += bytes(expect - len(out))
    return bytes(out[:expect])


# ---------------------------------------------------------------------------- PSD writer
def write_psd(path, size, layers, rle=False):
    """Write a layered 8-bit RGB Photoshop file. Layers keep their position and visibility."""
    W, H = size
    recs, data = bytearray(), bytearray()
    for L in layers:
        im = L["image"].convert("RGBA")
        w, h = im.size
        x, y = int(L.get("x", 0)), int(L.get("y", 0))
        r, g, b, a = im.split()
        planes = [(-1, a.tobytes()), (0, r.tobytes()), (1, g.tobytes()), (2, b.tobytes())]
        blobs = []
        for cid, raw in planes:
            if rle:
                counts, stream = packbits(raw, w)
                blobs.append(struct.pack(">H", 1) + struct.pack(">%dH" % h, *counts) + stream)
            else:
                blobs.append(struct.pack(">H", 0) + raw)
        recs += struct.pack(">iiiiH", y, x, y + h, x + w, 4)
        for (cid, _), blob in zip(planes, blobs):
            recs += struct.pack(">hI", cid, len(blob))
        recs += b"8BIM" + b"norm" + bytes([255, 0, 8 if L.get("visible", True) else 10, 0])
        extra = struct.pack(">II", 0, 0) + _pascal(L["name"])      # no mask data, no blending ranges
        recs += struct.pack(">I", len(extra)) + extra
        for blob in blobs:
            data += blob
    info = struct.pack(">h", len(layers)) + bytes(recs) + bytes(data)
    if len(info) % 2:
        info += b"\0"
    section = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)   # then an empty global mask block
    resources = b"8BIM" + struct.pack(">H", 0x03ED) + b"\0\0" + struct.pack(">I", 16) + \
        struct.pack(">IHHIHH", 0x00480000, 1, 1, 0x00480000, 1, 1)         # 72 dpi
    cr, cg, cb = flatten(size, layers).split()
    out = b"8BPS" + struct.pack(">H", 1) + bytes(6) + struct.pack(">HIIHH", 3, H, W, 8, 3)
    out += struct.pack(">I", 0)                                           # no colour mode data
    out += struct.pack(">I", len(resources)) + resources
    out += struct.pack(">I", len(section)) + section
    out += struct.pack(">H", 0) + cr.tobytes() + cg.tobytes() + cb.tobytes()   # flattened preview
    with open(path, "wb") as f:
        f.write(out)


# ---------------------------------------------------------------------------- PSD reader
def _channel(buf, w, h, depth):
    """Decode one channel to w*h bytes (8-bit)."""
    comp, = struct.unpack(">H", buf[:2])
    body = buf[2:]
    bpp = depth // 8
    if comp == 0:
        raw = body[:w * h * bpp]
    elif comp == 1:
        counts = struct.unpack(">%dH" % h, body[:2 * h])
        p = 2 * h
        rows = []
        for c in counts:
            rows.append(unpackbits(body[p:p + c], w * bpp))
            p += c
        raw = b"".join(rows)
    elif comp in (2, 3):
        raw = zlib.decompress(body)
        if comp == 3:
            if bpp != 1:
                raise LayerFileError("16-bit layers saved with ZIP prediction aren't supported; save with "
                                     "8 bits per channel (Image > Mode > 8 Bits/Channel)")
            rows = bytearray(raw)
            for r in range(h):
                base = r * w
                for i in range(1, w):
                    rows[base + i] = (rows[base + i] + rows[base + i - 1]) & 255
            raw = bytes(rows)
    else:
        raise LayerFileError(f"unknown channel compression {comp}")
    if len(raw) < w * h * bpp:
        raw += bytes(w * h * bpp - len(raw))
    return raw[0::2] if bpp == 2 else raw        # 16-bit: keep the high byte of each big-endian sample


def read_psd(path):
    """Return (canvas size, layers bottom to top) from a Photoshop file."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"8BPS":
        raise LayerFileError("this isn't a Photoshop (.psd) file")
    version, = struct.unpack(">H", d[4:6])
    if version != 1:
        raise LayerFileError("large-document (.psb) files aren't supported; save as a normal .psd")
    _, H, W, depth, mode = struct.unpack(">HIIHH", d[12:26])
    if mode != 3:
        raise LayerFileError("the file isn't in RGB mode (Photoshop: Image > Mode > RGB Color)")
    if depth not in (8, 16):
        raise LayerFileError("the file must be 8 or 16 bits per channel")
    p = 26
    for _ in range(2):                         # colour mode data, image resources
        n, = struct.unpack(">I", d[p:p + 4])
        p += 4 + n
    lm_len, = struct.unpack(">I", d[p:p + 4])
    p += 4
    if lm_len == 0:
        raise LayerFileError("the file has no layers (it was flattened); keep the layers when saving")
    p += 4                                     # layer info length
    count, = struct.unpack(">h", d[p:p + 2])
    p += 2
    recs = []
    for _ in range(abs(count)):
        top, left, bottom, right, nch = struct.unpack(">iiiiH", d[p:p + 18])
        p += 18
        chans = []
        for _ in range(nch):
            cid, ln = struct.unpack(">hI", d[p:p + 6])
            p += 6
            chans.append((cid, ln))
        blend = d[p + 4:p + 8]
        opacity, _clip, flags, _ = d[p + 8:p + 12]
        p += 12
        extra_len, = struct.unpack(">I", d[p:p + 4])
        p += 4
        extra_end = p + extra_len
        mlen, = struct.unpack(">I", d[p:p + 4])
        p += 4 + mlen
        blen, = struct.unpack(">I", d[p:p + 4])
        p += 4 + blen
        nlen = d[p]
        name = d[p + 1:p + 1 + nlen].decode("latin-1")
        p += ((1 + nlen + 3) // 4) * 4
        q = p
        while q + 12 <= extra_end:             # tagged blocks: look for the unicode name
            key = d[q + 4:q + 8]
            ln, = struct.unpack(">I", d[q + 8:q + 12])
            body = d[q + 12:q + 12 + ln]
            if key == b"luni" and len(body) >= 4:
                cnt, = struct.unpack(">I", body[:4])
                name = body[4:4 + cnt * 2].decode("utf-16-be", "replace").rstrip("\0")
            q += 12 + ln
            for pad in range(4):               # tolerate padding after a block
                if d[q + pad:q + pad + 4] in (b"8BIM", b"8B64"):
                    q += pad
                    break
            else:
                break
        p = extra_end
        recs.append({"name": name, "x": left, "y": top, "w": right - left, "h": bottom - top, "chans": chans,
                     "blend": blend, "opacity": opacity, "visible": not (flags & 2), "mask": mlen > 0})
    layers = []
    for rec in recs:
        planes = {}
        for cid, ln in rec["chans"]:
            blob = d[p:p + ln]
            p += ln
            w, h = rec["w"], rec["h"]
            if cid in (-1, 0, 1, 2) and w > 0 and h > 0:
                planes[cid] = Image.frombytes("L", (w, h), _channel(blob, w, h, depth))
        if rec["w"] <= 0 or rec["h"] <= 0 or not all(c in planes for c in (0, 1, 2)):
            continue                           # groups, empty layers, adjustment layers: nothing to import
        a = planes.get(-1) or Image.new("L", (rec["w"], rec["h"]), 255)
        warnings = []
        if rec["blend"] not in (b"norm", b"pass"):
            warnings.append("blend mode " + rec["blend"].decode("latin-1").strip() + " (ignored)")
        if rec["opacity"] < 255:
            warnings.append(f"opacity {100 * rec['opacity'] // 255}% (ignored)")
        if rec["mask"]:
            warnings.append("layer mask (ignored)")
        layers.append({"name": rec["name"], "x": rec["x"], "y": rec["y"], "visible": rec["visible"],
                       "opacity": 1.0, "image": Image.merge("RGBA", (planes[0], planes[1], planes[2], a)),
                       "warnings": warnings})
    return (W, H), layers


# ---------------------------------------------------------------------------- OpenRaster
def write_ora(path, size, layers):
    """Write an OpenRaster (.ora) file: a zip with stack.xml and one PNG per layer."""
    W, H = size
    image = ET.Element("image", {"version": "0.0.5", "w": str(W), "h": str(H)})
    stack = ET.SubElement(image, "stack")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)   # must be first, uncompressed
        for i, L in enumerate(layers):
            buf = io.BytesIO()
            L["image"].convert("RGBA").save(buf, "PNG")
            z.writestr(f"data/layer{i}.png", buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED)
        for i in range(len(layers) - 1, -1, -1):   # stack.xml lists the TOP layer first
            L = layers[i]
            ET.SubElement(stack, "layer", {
                "name": L["name"], "src": f"data/layer{i}.png", "x": str(int(L.get("x", 0))),
                "y": str(int(L.get("y", 0))), "opacity": "1.0", "composite-op": "svg:src-over",
                "visibility": "visible" if L.get("visible", True) else "hidden"})
        z.writestr("stack.xml", b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(image),
                   compress_type=zipfile.ZIP_DEFLATED)
        merged = flatten(size, layers)
        buf = io.BytesIO()
        merged.save(buf, "PNG")
        z.writestr("mergedimage.png", buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED)
        thumb = merged.copy()
        thumb.thumbnail((256, 256))
        buf = io.BytesIO()
        thumb.save(buf, "PNG")
        z.writestr("Thumbnails/thumbnail.png", buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED)


def read_ora(path):
    """Return (canvas size, layers bottom to top) from an OpenRaster file."""
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("stack.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise LayerFileError("this isn't a valid OpenRaster (.ora) file")
    size = (int(root.get("w", 0)), int(root.get("h", 0)))
    found = []

    def walk(el, dx, dy):                      # document order is top to bottom; stacks may nest
        for child in el:
            if child.tag == "stack":
                walk(child, dx + int(child.get("x", 0)), dy + int(child.get("y", 0)))
            elif child.tag == "layer":
                found.append((child, dx, dy))
    walk(root.find("stack"), 0, 0)
    layers = []
    for el, dx, dy in reversed(found):
        try:
            img = Image.open(io.BytesIO(z.read(el.get("src")))).convert("RGBA")
        except KeyError:
            continue
        warnings = []
        if el.get("composite-op", "svg:src-over") != "svg:src-over":
            warnings.append("blend mode " + el.get("composite-op") + " (ignored)")
        if float(el.get("opacity", "1")) < 1.0:
            warnings.append("opacity below 100% (ignored)")
        layers.append({"name": el.get("name", ""), "x": dx + int(el.get("x", 0)), "y": dy + int(el.get("y", 0)),
                       "visible": el.get("visibility", "visible") != "hidden", "opacity": 1.0, "image": img,
                       "warnings": warnings})
    return size, layers


def read_layers(path):
    """Read a layered file by extension (.psd or .ora)."""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "psd":
        return read_psd(path)
    if ext == "ora":
        return read_ora(path)
    raise LayerFileError("choose a .psd or .ora file")
