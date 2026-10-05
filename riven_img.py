#!/usr/bin/env python3
"""
riven_img.py - extract and replace images (tBMP) and movies (tMOV) in Riven's Mohawk (.mhk) archives.

Works with the 25th Anniversary / Steam release (ScummVM-based) and the original CD/DVD data.

Commands:
  python riven_img.py list           <archive.mhk> [--movies]
  python riven_img.py extract        <archive.mhk> <out_folder> [id ...]
  python riven_img.py extract-movies <archive.mhk> <out_folder> [id ...] [--mp4]
                      (--mp4 also writes H.264 .mp4 copies for video editors like Vegas)
  python riven_img.py patch          <archive.mhk> <file> [file ...]
  python riven_img.py restore        <archive.mhk>

File names must start with the resource id, e.g. "123.png" or "12_anything.mp4".
Extracted files are already named that way, so: extract -> edit -> patch.
  .png/.bmp/.jpg/.tif   -> replaces tBMP <id>  (size must match the original)
  any video file        -> replaces tMOV <id>  (re-encoded with ffmpeg to Cinepak at the
                           original size/frame rate, with ima4 audio if the original has audio)

a_data*.mhk (menus, journals) is fingerprinted by ScummVM, so images there are patched in SAME-SIZE mode:
re-encoded with the original palette into the original slot, keeping the file size and its first 5000 bytes
unchanged. An edit that won't compress into its slot is refused. Movies there can't be patched.

Patching never touches original data. Layout of a patched archive:
  [original archive][new directory][new resource data]
Replaced resources get new file-table entries; each patch rebuilds that tail from the one-time
backup (<archive>.mhk.orig), keeping earlier patches. 'restore' puts the backup back.

Requires Pillow (pip install pillow); movie patching also needs ffmpeg + ffprobe.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required:  pip install pillow")

TBMP = b"tBMP"
TMOV = b"tMOV"
IMAGE_EXTS = {".png", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff", ".gif"}
# keep ffmpeg from flashing console windows when called from the GUI
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}

# ---------------------------------------------------------------------------
# Mohawk archive
# ---------------------------------------------------------------------------

class FileEntry:
    __slots__ = ("pos", "offset", "size", "flags", "unknown")


class Archive:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.file_size = os.fstat(f.fileno()).st_size
            hdr = f.read(28)
            if hdr[0:4] != b"MHWK" or hdr[8:12] != b"RSRC":
                raise ValueError(f"{path}: not a Mohawk archive")
            version, = struct.unpack(">H", hdr[12:14])
            if version != 0x100:
                raise ValueError(f"{path}: unsupported Mohawk version {version:#x}")
            self.abs_offset, self.ft_offset = struct.unpack(">IH", hdr[20:26])

            # File table
            ft_pos = self.abs_offset + self.ft_offset
            f.seek(ft_pos)
            count, = struct.unpack(">I", f.read(4))
            raw = f.read(count * 10)
            self.dir_end = ft_pos + 4 + count * 10
            self.files = []
            for i in range(count):
                e = FileEntry()
                e.pos = ft_pos + 4 + i * 10
                e.offset, lo, hi, e.flags, e.unknown = struct.unpack(">IHBBH", raw[i * 10:i * 10 + 10])
                e.size = lo | (hi << 16) | ((e.flags & 7) << 24)
                self.files.append(e)

            # Type table
            f.seek(self.abs_offset)
            name_list_off, type_count = struct.unpack(">HH", f.read(4))
            types = [struct.unpack(">4sHH", f.read(8)) for _ in range(type_count)]

            self.type_order = []  # [(tag, [(id, idx)], [(name, idx)])] as stored, for rebuilding
            self.types = {}       # tag -> {id: file index (1-based)}
            self.names = {}       # (tag, id) -> name
            for tag, res_off, name_off in types:
                f.seek(self.abs_offset + name_off)
                n, = struct.unpack(">H", f.read(2))
                name_entries = [struct.unpack(">HH", f.read(4)) for _ in range(n)]
                names = []
                for off, idx in name_entries:
                    f.seek(self.abs_offset + name_list_off + off)
                    s = bytearray()
                    while True:
                        c = f.read(1)
                        if not c or c == b"\0":
                            break
                        s += c
                    names.append((s.decode("latin-1"), idx))
                names_by_index = {}
                for s, idx in names:
                    names_by_index.setdefault(idx, s)

                f.seek(self.abs_offset + res_off)
                n, = struct.unpack(">H", f.read(2))
                res_list = [struct.unpack(">HH", f.read(4)) for _ in range(n)]
                res = {}
                for rid, idx in res_list:
                    res[rid] = idx
                    if idx in names_by_index:
                        self.names[(tag, rid)] = names_by_index[idx]
                self.types[tag] = res
                self.type_order.append((tag, res_list, names))

    def ids(self, tag=TBMP):
        return sorted(self.types.get(tag, {}))

    def entry(self, tag, rid):
        return self.files[self.types[tag][rid] - 1]

    def span(self, tag, rid):
        """(offset, size) the way ScummVM computes it."""
        idx = self.types[tag][rid]
        e = self.files[idx - 1]
        if tag != TMOV:
            return e.offset, e.size
        # tMOV: size = distance to the next file-table entry with a different offset (or EOF)
        nxt = idx
        while nxt < len(self.files):
            if self.files[nxt].offset != e.offset:
                return e.offset, self.files[nxt].offset - e.offset
            nxt += 1
        return e.offset, self.file_size - e.offset

    def read(self, tag, rid):
        off, size = self.span(tag, rid)
        with open(self.path, "rb") as f:
            f.seek(off)
            return f.read(size)

    def read_movie(self, rid):
        """tMOV as a standalone QuickTime file (chunk offsets made relative)."""
        off, _ = self.span(TMOV, rid)
        return rebase_qt(self.read(TMOV, rid), -off)

    def users_of_index(self, idx):
        return [(t, r) for t, m in self.types.items() for r, i in m.items() if i == idx]


def find_original(path):
    """The pristine archive: the backup if one exists, else the archive itself."""
    return path + ".orig" if os.path.exists(path + ".orig") else path


# ---------------------------------------------------------------------------
# QuickTime chunk offsets (tMOV stco offsets are absolute archive offsets)
# ---------------------------------------------------------------------------

QT_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}


def qt_atoms(buf, start=0, end=None, path=()):
    """Yield (path, payload_start, payload_end) for every atom, descending into containers."""
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        hdr = 8
        if size == 1:
            size, = struct.unpack(">Q", buf[pos + 8:pos + 16]); hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            break
        p = path + (typ,)
        yield p, pos + hdr, pos + size
        if typ in QT_CONTAINERS or typ in (b"edts", b"dinf"):
            yield from qt_atoms(buf, pos + hdr, pos + size, p)
        pos += size


def qt_layout(buf):
    """Timescales and display matrices ScummVM cares about: {'mvhd': (timescale, matrix), 'vide': (...)}."""
    out, traks, cur = {}, [], None
    for p, s, e in qt_atoms(buf):
        if p in ((b"moov", b"mvhd"), (b"moov", b"trak", b"tkhd"), (b"moov", b"trak", b"mdia", b"mdhd")) and buf[s]:
            raise ValueError(f"{p[-1].decode()} version {buf[s]} not supported")
        if p == (b"moov", b"mvhd"):
            out["mvhd"] = (s, struct.unpack(">I", buf[s + 12:s + 16])[0], bytes(buf[s + 36:s + 72]))
        elif p == (b"moov", b"trak"):
            cur = {}
            traks.append(cur)
        elif cur is not None and p[:2] == (b"moov", b"trak"):
            if p[-1] == b"tkhd":
                cur["tkhd"] = s
            elif p[-2:] == (b"mdia", b"mdhd"):
                cur["timescale"] = struct.unpack(">I", buf[s + 12:s + 16])[0]
            elif p[-2:] == (b"mdia", b"hdlr"):  # media handler (minf/hdlr is the data handler)
                cur["kind"] = bytes(buf[s + 8:s + 12])
    for t in traks:
        if t.get("kind") == b"vide" and "tkhd" in t:
            s = t["tkhd"]
            out["vide"] = (s, t.get("timescale"), bytes(buf[s + 40:s + 76]), bytes(buf[s + 76:s + 84]))
            break
    return out


def rebase_qt(data, delta):
    """Return a copy of a QuickTime file with every stco/co64 offset shifted by delta."""
    buf = bytearray(data)

    def walk(start, end):
        pos = start
        while pos + 8 <= end:
            size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
            hdr = 8
            if size == 1:
                size, = struct.unpack(">Q", buf[pos + 8:pos + 16]); hdr = 16
            elif size == 0:
                size = end - pos
            if size < hdr or pos + size > end:
                break
            if typ in QT_CONTAINERS:
                walk(pos + hdr, pos + size)
            elif typ == b"stco":
                n, = struct.unpack(">I", buf[pos + 12:pos + 16])
                for i in range(n):
                    p = pos + 16 + i * 4
                    v, = struct.unpack(">I", buf[p:p + 4])
                    struct.pack_into(">I", buf, p, v + delta)
            elif typ == b"co64":
                n, = struct.unpack(">I", buf[pos + 12:pos + 16])
                for i in range(n):
                    p = pos + 16 + i * 8
                    v, = struct.unpack(">Q", buf[p:p + 8])
                    struct.pack_into(">Q", buf, p, v + delta)
            pos += size

    walk(0, len(buf))
    return bytes(buf)


# ---------------------------------------------------------------------------
# tBMP decoding (mirrors ScummVM engines/mohawk/bitmap.cpp)
# ---------------------------------------------------------------------------

def _riven_unpack(data, pos, out_size):
    dst = bytearray()
    n = len(data)
    pos += 4  # unknown uint32
    while pos < n and len(dst) < out_size:
        cmd = data[pos]; pos += 1
        if cmd == 0x00:
            break
        elif cmd <= 0x3F:
            dst += data[pos:pos + cmd * 2]; pos += cmd * 2
        elif cmd <= 0x7F:
            dst += dst[-2:] * (cmd - 0x40)
        elif cmd <= 0xBF:
            dst += dst[-4:] * (cmd - 0x80)
        else:
            for _ in range(cmd - 0xC0):
                sc = data[pos]; pos += 1
                m = sc & 0x0F
                a = dst.append
                if 0x01 <= sc <= 0x0F:
                    a(dst[-m * 2]); a(dst[-m * 2])
                elif sc == 0x10:
                    a(dst[-2]); a(data[pos]); pos += 1
                elif sc <= 0x1F:
                    a(dst[-2]); a(dst[-m])
                elif sc <= 0x2F:
                    a(dst[-2]); a((dst[-2] + m) & 0xFF)
                elif sc <= 0x3F:
                    a(dst[-2]); a((dst[-2] - m) & 0xFF)
                elif sc == 0x40:
                    a(data[pos]); pos += 1; a(dst[-2])
                elif sc <= 0x4F:
                    a(dst[-m]); a(dst[-2])
                elif sc == 0x50:
                    a(data[pos]); a(data[pos + 1]); pos += 2
                elif 0x51 <= sc <= 0x57:
                    a(dst[-(sc & 7)]); a(data[pos]); pos += 1
                elif 0x59 <= sc <= 0x5F:
                    a(data[pos]); pos += 1; a(dst[-(sc & 7)])
                elif 0x60 <= sc <= 0x6F:
                    a(data[pos]); pos += 1; a((dst[-2] + m) & 0xFF)
                elif 0x70 <= sc <= 0x7F:
                    a(data[pos]); pos += 1; a((dst[-2] - m) & 0xFF)
                elif 0x80 <= sc <= 0x8F:
                    a((dst[-2] + m) & 0xFF); a(dst[-2])
                elif 0x90 <= sc <= 0x9F:
                    a((dst[-2] + m) & 0xFF); a(data[pos]); pos += 1
                elif sc == 0xA0:
                    p = data[pos]; pos += 1
                    a((dst[-2] + (p >> 4)) & 0xFF); a((dst[-2] + (p & 15)) & 0xFF)
                elif sc == 0xB0:
                    p = data[pos]; pos += 1
                    a((dst[-2] + (p >> 4)) & 0xFF); a((dst[-2] - (p & 15)) & 0xFF)
                elif 0xC0 <= sc <= 0xCF:
                    a((dst[-2] - m) & 0xFF); a(dst[-2])
                elif 0xD0 <= sc <= 0xDF:
                    a((dst[-2] - m) & 0xFF); a(data[pos]); pos += 1
                elif sc == 0xE0:
                    p = data[pos]; pos += 1
                    a((dst[-2] - (p >> 4)) & 0xFF); a((dst[-2] + (p & 15)) & 0xFF)
                elif sc in (0xF0, 0xFF):
                    p = data[pos]; pos += 1
                    a((dst[-2] - (p >> 4)) & 0xFF); a((dst[-2] - (p & 15)) & 0xFF)
                elif sc == 0xFC:
                    b1, b2 = data[pos], data[pos + 1]; pos += 2
                    m1 = ((b1 & 3) << 8) | b2
                    for _ in range(((b1 >> 3) + 1) * 2 + 1):
                        a(dst[-m1])
                    if b1 & 4:
                        a(dst[-m1])
                    else:
                        a(data[pos]); pos += 1
                elif (sc & 0x0C) and (sc & 0xF0) in (0xA0, 0xB0, 0xE0, 0xF0) and sc not in (0xFC, 0xFD, 0xFE):
                    # Repeat n pixels from -m1; odd n ends with a literal byte
                    table = {0xA4: 3, 0xA8: 4, 0xAC: 5, 0xB4: 6, 0xB8: 7, 0xBC: 8,
                             0xE4: 9, 0xE8: 10, 0xEC: 11, 0xF4: 12, 0xF8: 13}
                    cnt = table[sc & 0xFC]
                    m1 = ((sc & 3) << 8) | data[pos]; pos += 1
                    for _ in range(cnt):
                        a(dst[-m1])
                    if cnt & 1:
                        a(data[pos]); pos += 1
                else:
                    print(f"  warning: unknown Riven subcommand {sc:#04x}", file=sys.stderr)
    if len(dst) < out_size:
        dst += bytes(out_size - len(dst))
    return bytes(dst[:out_size])


def _rle8_draw(data, pos, w, h):
    out = bytearray()
    for _ in range(h):
        row_len, = struct.unpack(">H", data[pos:pos + 2]); pos += 2
        start = pos
        row = bytearray()
        while len(row) < w:
            code = data[pos]; pos += 1
            run = (code & 0x7F) + 1
            if code & 0x80:
                row += bytes([data[pos]]) * run; pos += 1
            else:
                row += data[pos:pos + run]; pos += run
        out += row[:w]
        pos = start + row_len
    return bytes(out)


def decode_tbmp(data):
    """Return a PIL Image (RGB) from raw tBMP bytes."""
    w, h, bpr, fmt = struct.unpack(">HHhH", data[0:8])
    w &= 0x3FFF; h &= 0x3FFF; bpr &= 0x3FFE
    bpp = {0: 1, 1: 4, 2: 8, 3: 16, 4: 24}[fmt & 7]
    pack = fmt & 0x0F00
    draw = fmt & 0x00F0
    pos = 8
    if bpp not in (8, 24):
        raise ValueError(f"unsupported bpp {bpp}")

    palette = None
    if (fmt & 0x0008) or (pack == 0x0400 and bpp == 8):
        pos += 4  # tableSize, rgbBits, colorCount
        pal = data[pos:pos + 768]; pos += 768
        palette = bytearray(768)
        for i in range(256):  # stored BGR
            palette[i * 3:i * 3 + 3] = bytes((pal[i * 3 + 2], pal[i * 3 + 1], pal[i * 3]))

    if pack == 0x0400:
        pixels = _riven_unpack(data, pos, bpr * h); pos = 0
    elif pack == 0x0000:
        pixels = data;
    else:
        raise ValueError(f"unsupported pack type {pack:#06x}")

    if draw == 0x0010:
        raw = _rle8_draw(pixels, pos, w, h)
        bpr_eff = w
        pos = 0
    elif draw == 0x0000:
        raw, bpr_eff = pixels, bpr
    else:
        raise ValueError(f"unsupported draw type {draw:#06x}")

    stride = w * (3 if bpp == 24 else 1)
    rows = b"".join(raw[pos + y * bpr_eff: pos + y * bpr_eff + stride] for y in range(h))

    if bpp == 24:
        img = Image.frombytes("RGB", (w, h), rows, "raw", "BGR")
    else:
        img = Image.frombytes("P", (w, h), rows)
        img.putpalette(bytes(palette))
        img = img.convert("RGB")
    return img


def encode_tbmp_24(img):
    """Encode a PIL image as an uncompressed 24-bit tBMP (accepted by ScummVM's decoder)."""
    img = img.convert("RGB")
    w, h = img.size
    if w > 0x3FFF or h > 0x3FFF or w * 3 > 0x3FFE:
        raise ValueError("image too large")
    bpr = (w * 3 + 1) & ~1
    header = struct.pack(">HHhH", w, h, bpr, 0x0004)  # 24bpp, raw pack, raw draw
    bgr = img.tobytes("raw", "BGR")
    pad = b"\0" * (bpr - w * 3)
    body = b"".join(bgr[y * w * 3:(y + 1) * w * 3] + pad for y in range(h)) if pad else bgr
    return header + body


# ---------------------------------------------------------------------------
# Movies (ffmpeg)
# ---------------------------------------------------------------------------

def _tool(name):
    p = shutil.which(name)
    if not p:
        links = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", name + ".exe")
        p = links if os.path.exists(links) else None
    if not p:
        sys.exit(f"{name} not found (install ffmpeg, e.g.  winget install Gyan.FFmpeg)")
    return p


def probe_movie(path):
    out = subprocess.run([_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True, check=True, **NOWIN).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return v, a, float(info["format"].get("duration", 0) or 0)


def cinepak_strip_counts(path, first_only=False):
    """Strip count of each Cinepak frame in a QuickTime file."""
    cmd = [_tool("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries", "packet=pos,size", "-of", "json"]
    if first_only:
        cmd += ["-read_intervals", "%+#1"]
    packets = json.loads(subprocess.run(cmd + [path], capture_output=True, text=True, check=True,
                                        **NOWIN).stdout)["packets"]
    counts = []
    with open(path, "rb") as f:
        for p in packets:
            f.seek(int(p["pos"]) + 8)
            counts.append(struct.unpack(">H", f.read(2))[0])
    return counts


def encode_movie(src, ref_mov):
    """Re-encode `src` to match the reference QuickTime bytes (size, fps, audio). Returns QuickTime bytes.

    ScummVM's Cinepak decoder sizes its strip table from the FIRST frame and never resizes it, so every
    frame must have the same strip count (ffmpeg varies it by default -> heap overflow / garbage strips).
    We lock it to the original movie's count, like the original encoder did.

    ScummVM's QuickTime decoder multiplies timescales together in 32 bits (video/qt_decoder.cpp), so ffmpeg's
    default timescales (22050 movie x 15360 video) overflow after 12.7s and the video freezes while the audio
    plays on. We use the original's timescales (600/600 in Riven).

    ScummVM shows a track at frame size / track matrix scale (some Riven movies use 0.25), so the original's
    movie and track matrices are copied over too.
    """
    with tempfile.TemporaryDirectory() as td:
        ref = os.path.join(td, "ref.mov")
        out = os.path.join(td, "out.mov")
        with open(ref, "wb") as f:
            f.write(ref_mov)
        v, a, dur = probe_movie(ref)
        if not v:
            raise ValueError("original movie has no video track")
        w, h, fps = v["width"], v["height"], v.get("r_frame_rate", "15/1")
        strips = (cinepak_strip_counts(ref, first_only=True) or [3])[0]
        ref_layout = qt_layout(ref_mov)
        movie_ts, video_ts = ref_layout["mvhd"][1], ref_layout["vide"][1]
        # Never come out shorter than the original: scripts wait for a movie to end. (Some originals end
        # on "no change" frames that ffmpeg's decoder drops, e.g. a 3s still hold; tpad clones the last
        # frame to cover that, and -t cuts back to the right length.)
        length = max(dur, probe_movie(src)[2])
        cmd = [_tool("ffmpeg"), "-v", "error", "-y", "-i", src,
               "-vf", f"scale={w}:{h}:flags=lanczos,tpad=stop_mode=clone:stop_duration={length:.3f},"
                      f"fps={fps},format=rgb24", "-t", f"{length:.3f}",
               "-c:v", "cinepak", "-min_strips", str(strips), "-max_strips", str(strips)]
        if a:
            cmd += ["-c:a", "adpcm_ima_qt", "-ar", str(a["sample_rate"]), "-ac", str(a["channels"])]
        else:
            cmd += ["-an"]
        cmd += ["-movie_timescale", str(movie_ts), "-video_track_timescale", str(video_ts), "-f", "mov", out]
        subprocess.run(cmd, check=True, **NOWIN)
        counts = set(cinepak_strip_counts(out))
        if counts != {strips}:
            raise ValueError(f"encoder produced Cinepak strip counts {sorted(counts)}, need a constant {strips}")
        _, _, new_dur = probe_movie(out)
        if dur and abs(new_dur - dur) > 0.5:
            print(f"  note: {os.path.basename(src)} is {new_dur:.1f}s, original is {dur:.1f}s")
        with open(out, "rb") as f:
            buf = bytearray(f.read())

    # copy the original's display matrices (and track size) so ScummVM scales the movie the same way
    lay = qt_layout(buf)
    s = lay["mvhd"][0]
    buf[s + 36:s + 72] = ref_layout["mvhd"][2]
    s = lay["vide"][0]
    buf[s + 40:s + 84] = ref_layout["vide"][2] + ref_layout["vide"][3]
    got = qt_layout(buf)
    for k in ("mvhd", "vide"):
        if got[k][1:] != ref_layout[k][1:]:
            raise ValueError(f"{k} timescale/matrix mismatch after encoding: {got[k][1]} vs {ref_layout[k][1]}")
    return bytes(buf)


# ---------------------------------------------------------------------------
# Patching: rebuild [original][directory][blobs]
# ---------------------------------------------------------------------------

def _align(n):
    return n + (n & 1)


def current_patches(path):
    """{(tag, rid): bytes} of resources already patched into `path` (movies with relative offsets)."""
    orig_path = path + ".orig"
    if not os.path.exists(orig_path):
        return {}
    orig = Archive(orig_path)
    cur = Archive(path)
    if cur.abs_offset == orig.abs_offset:
        if cur.file_size != orig.file_size:
            print("  note: archive was patched by an older version of this tool; starting fresh from the backup")
        return {}
    first_new = len(orig.files) + 2  # +1 for the end-of-original marker entry
    out = {}
    for tag, m in cur.types.items():
        for rid, idx in m.items():
            if idx >= first_new:
                e = cur.files[idx - 1]  # stored sizes are exact for patched entries, movies included
                with open(path, "rb") as f:
                    f.seek(e.offset)
                    data = f.read(e.size)
                out[(tag, rid)] = rebase_qt(data, -e.offset) if tag == TMOV else data
    return out


def write_patches(path, patches):
    """Rewrite `path` as the backup plus a tail holding `patches` ({(tag, rid): bytes})."""
    orig_path = path + ".orig"
    if not os.path.exists(orig_path):
        print(f"Backing up original to {os.path.basename(orig_path)} (one time)...")
        shutil.copy2(path, orig_path)
    orig = Archive(orig_path)
    for tag, rid in patches:
        if rid not in orig.types.get(tag, {}):
            raise ValueError(f"{tag.decode()} {rid} is not in {os.path.basename(path)}")

    jobs = sorted(patches.items())
    marker_idx = len(orig.files) + 1
    new_idx = {key: marker_idx + 1 + i for i, (key, _) in enumerate(jobs)}
    if marker_idx + len(jobs) > 0xFFFF:
        raise ValueError("too many resources for one archive")

    # Directory: [u16 string-list offset, u16 type count][types][res+name tables][strings][file table]
    strings = bytearray()
    string_off = {}

    def sref(s):
        if s not in string_off:
            string_off[s] = len(strings)
            strings.extend(s.encode("latin-1") + b"\0")
        return string_off[s]

    tables = []
    for tag, res_list, names in orig.type_order:
        old_to_new = {}
        res = []
        for rid, idx in res_list:
            if (tag, rid) in new_idx:
                old_to_new.setdefault(idx, []).append(new_idx[(tag, rid)])
                idx = new_idx[(tag, rid)]
            res.append((rid, idx))
        nm = [(sref(s), idx) for s, idx in names]
        nm += [(sref(s), n) for s, idx in names for n in old_to_new.get(idx, [])]
        tables.append((tag, res, nm))

    pos = 4 + 8 * len(tables)
    type_entries, body = bytearray(), bytearray()
    for tag, res, nm in tables:
        res_off = pos + len(body)
        body += struct.pack(">H", len(res)) + b"".join(struct.pack(">HH", r, i) for r, i in res)
        name_off = pos + len(body)
        body += struct.pack(">H", len(nm)) + b"".join(struct.pack(">HH", o, i) for o, i in nm)
        type_entries += struct.pack(">4sHH", tag, res_off, name_off)
    str_off = pos + len(body)
    ft_off = _align(str_off + len(strings))
    if ft_off > 0xFFFF:
        raise ValueError("directory too large")
    n_files = marker_idx + len(jobs)
    dir_size = ft_off + 4 + n_files * 10

    dir_pos = _align(orig.file_size)
    blob_pos = []
    p = _align(dir_pos + dir_size)
    for _, blob in jobs:
        blob_pos.append(p)
        p = _align(p + len(blob))

    ft = bytearray(struct.pack(">I", n_files))
    for e in orig.files:
        ft += struct.pack(">IHBBH", e.offset, e.size & 0xFFFF, (e.size >> 16) & 0xFF, e.flags, e.unknown)
    ft += struct.pack(">IHBBH", orig.file_size, 0, 0, 0, 0)  # marks the end of original data for tMOV sizing
    ref_entry = {}
    for (tag, rid), _ in jobs:
        ref_entry[(tag, rid)] = orig.entry(tag, rid)
    for ((tag, rid), blob), bp in zip(jobs, blob_pos):
        e = ref_entry[(tag, rid)]
        size = len(blob)
        if size >= 1 << 27:
            raise ValueError(f"{tag.decode()} {rid} is too large")
        flags = (e.flags & ~7) | ((size >> 24) & 7)
        ft += struct.pack(">IHBBH", bp, size & 0xFFFF, (size >> 16) & 0xFF, flags, e.unknown)

    directory = (struct.pack(">HH", str_off, len(tables)) + type_entries + body + strings)
    directory += b"\0" * (ft_off - len(directory)) + ft
    assert len(directory) == dir_size

    if blob_pos and blob_pos[-1] + len(jobs[-1][1]) > 0xFFFFFFFF:
        raise ValueError("archive would exceed 4GB")

    # Write: restore the original header+directory bytes, cut the old tail, append the new one
    with open(orig_path, "rb") as f:
        head = f.read(orig.dir_end)
    os.chmod(path, 0o666)
    with open(path, "r+b") as f:
        f.write(head)
        f.truncate(orig.file_size)
        if jobs:
            f.seek(20)
            f.write(struct.pack(">IH", dir_pos, ft_off))
            f.seek(orig.file_size)
            f.write(b"\0" * (dir_pos - orig.file_size))
            f.write(directory)
            for ((tag, rid), blob), bp in zip(jobs, blob_pos):
                f.write(b"\0" * (bp - f.tell()))
                f.write(rebase_qt(blob, bp) if tag == TMOV else blob)

    # verify
    a2 = Archive(path)
    for (tag, rid), blob in jobs:
        got = a2.read_movie(rid) if tag == TMOV else a2.read(tag, rid)
        if tag == TMOV:
            got = got[:len(blob)]
        assert got == blob, f"verify failed for {tag.decode()} {rid}"
    for tag, m in orig.types.items():
        for rid in m:
            if (tag, rid) not in patches:
                assert a2.span(tag, rid) == orig.span(tag, rid), f"{tag.decode()} {rid} moved"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def cmd_list(path, movies=False):
    a = Archive(path)
    if movies:
        ids = a.ids(TMOV)
        print(f"{os.path.basename(path)}: {len(ids)} tMOV movies")
        for rid in ids:
            print(f"  {rid:5d}  {a.span(TMOV, rid)[1]:10d} bytes  {a.names.get((TMOV, rid), '')}")
        return
    ids = a.ids()
    print(f"{os.path.basename(path)}: {len(ids)} tBMP images")
    for rid in ids:
        data = a.read(TBMP, rid)
        w, h, _, fmt = struct.unpack(">HHhH", data[:8])
        name = a.names.get((TBMP, rid), "")
        print(f"  {rid:5d}  {w & 0x3FFF:4d}x{h & 0x3FFF:<4d}  fmt={fmt:#06x}  {len(data):8d} bytes  {name}")


def cmd_extract(path, outdir, only=None):
    a = Archive(path)
    os.makedirs(outdir, exist_ok=True)
    ids = [i for i in a.ids() if not only or i in only]
    ok = 0
    for n, rid in enumerate(ids, 1):
        name = a.names.get((TBMP, rid), "")
        fn = f"{rid}" + (f"_{_safe(name)}" if name else "") + ".png"
        try:
            decode_tbmp(a.read(TBMP, rid)).save(os.path.join(outdir, fn))
            ok += 1
        except Exception as e:
            print(f"  {rid}: FAILED ({e})", file=sys.stderr)
        if n % 50 == 0:
            print(f"  {n}/{len(ids)}...")
    print(f"Extracted {ok}/{len(ids)} images to {outdir}")


def mov_to_mp4(src, dst):
    """Editing-friendly copy (H.264 + AAC) for video editors that can't import Cinepak.

    Padded to the movie's full length: ffmpeg drops trailing "no change" Cinepak frames (still holds)."""
    dur = probe_movie(src)[2]
    subprocess.run([_tool("ffmpeg"), "-v", "error", "-y", "-i", src, "-t", f"{dur:.3f}",
                    "-vf", f"pad=ceil(iw/2)*2:ceil(ih/2)*2,tpad=stop_mode=clone:stop_duration={dur:.3f}",
                    "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst], check=True, **NOWIN)


def cmd_extract_movies(path, outdir, only=None, mp4=False):
    a = Archive(path)
    os.makedirs(outdir, exist_ok=True)
    ids = [i for i in a.ids(TMOV) if not only or i in only]
    for n, rid in enumerate(ids, 1):
        name = a.names.get((TMOV, rid), "")
        name = re.sub(r"\.mov$", "", name, flags=re.I)
        base = os.path.join(outdir, f"{rid}" + (f"_{_safe(name)}" if name else ""))
        with open(base + ".mov", "wb") as f:
            f.write(a.read_movie(rid))
        if mp4:
            mov_to_mp4(base + ".mov", base + ".mp4")
            if n % 10 == 0:
                print(f"  {n}/{len(ids)}...")
    print(f"Extracted {len(ids)} movies to {outdir}" + (" (with .mp4 copies)" if mp4 else ""))


def _id_from_filename(fn):
    m = re.match(r"(\d+)", os.path.basename(fn))
    if not m:
        raise ValueError(f"{fn}: filename must start with the resource id (e.g. 123.png)")
    return int(m.group(1))


FINGERPRINTED = re.compile(r"^a_data(_[a-z]+)?\.mhk$", re.I)


# ---------------------------------------------------------------------------
# Same-size (in-place) patching, for archives ScummVM fingerprints (a_data*.mhk)
# ---------------------------------------------------------------------------
# ScummVM's detection checks a_data.mhk's exact size and the md5 of its first 5000 bytes. The normal scheme
# (append + new directory) changes both. Instead, a re-encoded image goes into its ORIGINAL slot (same offset,
# zero-padded to the same size, file table untouched), so both checks keep passing. It only works if the
# edited image compresses into that slot: riven_pack.pack() beats the original encoder by about 3%.
FINGERPRINT_BYTES = 5000


class FitError(ValueError):
    """An edited image doesn't compress into its original slot."""

    def __init__(self, rid, size, slot):
        self.rid, self.size, self.slot = rid, size, slot
        super().__init__(f"image {rid} needs {size:,} bytes but its slot holds {slot:,} "
                         f"({100 * (size - slot) / slot:.1f}% too big)")


def is_inplace(path):
    return bool(FINGERPRINTED.match(os.path.basename(path)))


def tbmp_indices(data):
    """(w, h, bytes per row, palette block, palette index bytes) of an 8-bit palette tBMP."""
    w, h, bpr, fmt = struct.unpack(">HHhH", data[:8])
    w, h, bpr = w & 0x3FFF, h & 0x3FFF, bpr & 0x3FFE
    pack_type = fmt & 0x0F00
    if fmt & 7 != 2 or fmt & 0x00F0 or not (fmt & 0x0008 or pack_type == 0x0400) or pack_type not in (0, 0x0400):
        raise ValueError(f"same-size patching needs an 8-bit palette image (this one is format {fmt:#06x})")
    pal_block = data[8:8 + 4 + 768]
    if pack_type == 0x0400:
        idx = _riven_unpack(data, 8 + 4 + 768, bpr * h)
    else:
        idx = data[8 + 4 + 768:8 + 4 + 768 + bpr * h]
    return w, h, bpr, pal_block, idx


def encode_tbmp_inplace(img, orig_data, slot):
    """Re-encode `img` with the original image's palette, Riven-packed, to fit in `slot` bytes.

    Pixels that didn't change keep their exact original palette index (so untouched areas compress as well
    as before); changed pixels get the nearest colour in the original palette. Raises FitError if too big."""
    from PIL import ImageChops
    from riven_pack import pack
    w, h, bpr, pal_block, idx = tbmp_indices(orig_data)
    rgb_pal = bytearray(768)
    for i in range(256):  # stored BGR
        rgb_pal[i * 3:i * 3 + 3] = bytes((pal_block[4 + i * 3 + 2], pal_block[4 + i * 3 + 1], pal_block[4 + i * 3]))
    new = img.convert("RGB")
    if new.size != (w, h):
        raise ValueError(f"size is {new.size[0]}x{new.size[1]}, must be {w}x{h}")
    rows = b"".join(idx[y * bpr:y * bpr + w] for y in range(h))
    orig_idx = Image.frombytes("L", (w, h), rows)
    orig_rgb = Image.frombytes("P", (w, h), rows)
    orig_rgb.putpalette(bytes(rgb_pal))
    orig_rgb = orig_rgb.convert("RGB")
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(bytes(rgb_pal))
    nearest = Image.frombytes("L", (w, h), new.quantize(palette=pal_img, dither=Image.Dither.NONE).tobytes())
    r, g, b = ImageChops.difference(orig_rgb, new).split()
    changed = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v else 0)
    merged = Image.composite(nearest, orig_idx, changed).tobytes()
    new_idx = b"".join(merged[y * w:(y + 1) * w] + idx[y * bpr + w:(y + 1) * bpr] for y in range(h))
    stream = pack(new_idx)
    if _riven_unpack(stream, 0, bpr * h) != new_idx:
        raise AssertionError("internal error: Riven pack round-trip mismatch")
    blob = struct.pack(">HHhH", w, h, bpr, 0x040A) + pal_block + stream
    if len(blob) > slot:
        raise FitError(None, len(blob), slot)
    return blob


def inplace_changed(path):
    """{(tag, id)} whose slot in `path` differs from the backup."""
    orig_path = path + ".orig"
    if not os.path.exists(orig_path):
        return set()
    orig = Archive(orig_path)
    with open(path, "rb") as f:
        cur = f.read()
    with open(orig_path, "rb") as f:
        org = f.read()
    out = set()
    for tag in (TBMP, TMOV):
        for rid, i in orig.types.get(tag, {}).items():
            e = orig.files[i - 1]
            if cur[e.offset:e.offset + e.size] != org[e.offset:e.offset + e.size]:
                out.add((tag, rid))
    return out


def write_inplace(path, changes):
    """changes: {(TBMP, id): blob, or None to put the original back}. Writes into the original slots and
    verifies the archive still passes ScummVM's detection (same size, same first 5000 bytes)."""
    orig_path = path + ".orig"
    if not os.path.exists(orig_path):
        print(f"Backing up original to {os.path.basename(orig_path)} (one time)...")
        shutil.copy2(path, orig_path)
    orig = Archive(orig_path)
    if os.path.getsize(path) != orig.file_size:
        raise ValueError(f"{os.path.basename(path)} has a different size than its backup; it was changed some "
                         "other way. Restore it first.")
    with open(orig_path, "rb") as f:
        head = f.read(FINGERPRINT_BYTES)
    plan = []
    for (tag, rid), blob in sorted(changes.items()):
        if tag != TBMP:
            raise ValueError(f"{os.path.basename(path)}: only images can be patched in same-size mode")
        e = orig.entry(tag, rid)
        if e.offset < FINGERPRINT_BYTES:
            raise ValueError(f"image {rid} lies in the fingerprinted start of the file and can't be changed")
        if blob is None:
            blob = orig.read(tag, rid)
        if len(blob) > e.size:
            raise FitError(rid, len(blob), e.size)
        plan.append((e.offset, blob + bytes(e.size - len(blob)), rid))
    os.chmod(path, 0o666)
    with open(path, "r+b") as f:
        for off, data, _ in plan:
            f.seek(off)
            f.write(data)
    # verify: detection fingerprint intact, and every slot holds exactly what we meant to write
    if os.path.getsize(path) != orig.file_size:
        raise AssertionError("file size changed")
    with open(path, "rb") as f:
        if f.read(FINGERPRINT_BYTES) != head:
            raise AssertionError("fingerprinted start of the file changed")
    cur = Archive(path)
    for off, data, rid in plan:
        got = cur.read(TBMP, rid)
        if got != data:
            raise AssertionError(f"verify failed for image {rid}")
        decode_tbmp(got)


def cmd_patch(path, files, force=False):
    if is_inplace(path):
        orig = Archive(find_original(path))
        changes = {}
        for fn in files:
            rid = _id_from_filename(fn)
            if os.path.splitext(fn)[1].lower() not in IMAGE_EXTS:
                sys.exit(f"{fn}: {os.path.basename(path)} is fingerprinted by ScummVM; only images can be "
                         "patched there (same-size mode)")
            if rid not in orig.types.get(TBMP, {}):
                sys.exit(f"{fn}: tBMP {rid} is not in {os.path.basename(path)}")
            slot = orig.entry(TBMP, rid).size
            print(f"  encoding {os.path.basename(fn)} (same-size mode, slot {slot:,} bytes)...")
            try:
                blob = encode_tbmp_inplace(Image.open(fn), orig.read(TBMP, rid), slot)
            except FitError as e:
                sys.exit(f"{fn}: doesn't fit: needs {e.size:,} bytes, slot holds {slot:,} "
                         f"({100 * (e.size - slot) / slot:.1f}% too big). Nothing was written.")
            print(f"    {len(blob):,} bytes, {100 * (slot - len(blob)) / slot:.1f}% to spare")
            changes[(TBMP, rid)] = blob
        write_inplace(path, changes)
        print(f"Done. {len(changes)} image(s) patched in place; size and fingerprint unchanged.")
        return
    orig = Archive(find_original(path))
    new = {}
    for fn in files:
        rid = _id_from_filename(fn)
        if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
            if rid not in orig.types.get(TBMP, {}):
                sys.exit(f"{fn}: tBMP {rid} is not in {os.path.basename(path)}")
            old = decode_tbmp(orig.read(TBMP, rid))
            img = Image.open(fn)
            if img.size != old.size:
                sys.exit(f"{fn}: size {img.size[0]}x{img.size[1]} doesn't match original "
                         f"{old.size[0]}x{old.size[1]}")
            new[(TBMP, rid)] = encode_tbmp_24(img)
        else:
            if rid not in orig.types.get(TMOV, {}):
                sys.exit(f"{fn}: tMOV {rid} is not in {os.path.basename(path)}")
            print(f"  encoding {os.path.basename(fn)}...")
            new[(TMOV, rid)] = encode_movie(fn, orig.read_movie(rid))

    patches = current_patches(path)
    patches.update(new)
    write_patches(path, patches)
    for tag, rid in sorted(new):
        print(f"  patched {tag.decode()} {rid}")
    print(f"Done. {len(new)} resource(s) patched, {len(patches)} total in {os.path.basename(path)}")


def cmd_restore(path):
    backup = path + ".orig"
    if not os.path.exists(backup):
        sys.exit("No backup found.")
    if os.path.exists(path):
        os.chmod(path, 0o666)
    shutil.copyfile(backup, path)
    print(f"Restored {os.path.basename(path)} from backup.")


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    force = "--force" in argv
    movies = "--movies" in argv
    mp4 = "--mp4" in argv
    argv = [x for x in argv if x not in ("--force", "--movies", "--mp4")]
    cmd, path = argv[1], argv[2]
    if cmd == "list":
        cmd_list(path, movies)
    elif cmd == "extract" and len(argv) >= 4:
        cmd_extract(path, argv[3], {int(x) for x in argv[4:]} or None)
    elif cmd == "extract-movies" and len(argv) >= 4:
        cmd_extract_movies(path, argv[3], {int(x) for x in argv[4:]} or None, mp4)
    elif cmd == "patch" and len(argv) >= 4:
        cmd_patch(path, argv[3:], force)
    elif cmd == "restore":
        cmd_restore(path)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
