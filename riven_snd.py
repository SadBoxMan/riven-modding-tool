"""
riven_snd.py - tWAV sound format handling for Riven Mod Tool.

tWAV (Mohawk WAVE) format used by the 25th Anniversary / Steam release:
  [MHWK(4) + fileSize(4) + WAVE(4)]          12-byte outer header
  [ADPC(4) + chunkSize(4) + seek-table...]    optional IMA seek table
  [Data(4) + chunkSize(4) + 20-byte header    DATA chunk:
     sampleRate(2) + sampleCount(4)             format header
     bitsPerSample(1) + channels(1)
     encoding(2) + loopCount(2)
     loopStart(4) + loopEnd(4)]
  [raw audio bytes]                             IMA nibbles OR MP2 stream

Encodings:
  0 = Raw PCM (rare, 8-bit unsigned, some Myst sounds)
  1 = Intel DVI / IMA ADPCM  (kCodecADPCM in ScummVM)
  2 = MPEG-2 Layer II / MP2  (kCodecMPEG2 in ScummVM)

DVI ADPCM layout (ScummVM DVI_ADPCMStream):
  Continuous nibble stream, NO block headers.
  Each byte → two samples:
    stereo:  high nibble = L channel, low nibble = R channel (interleaved per-frame)
    mono:    high nibble = sample[2n], low nibble = sample[2n+1]
  Initial predictor/step per channel come from the ADPC seek table (frame 0).

Requires ffmpeg on PATH (or at C:/ffmpeg/bin/ffmpeg.exe) for MP2 encode/decode
and for decoding user audio files to raw PCM.
"""
import os
import struct
import subprocess
import sys
import tempfile

# ── IMA ADPCM tables ──────────────────────────────────────────────────────────

_STEP = [
    7,     8,     9,    10,    11,    12,    13,    14,
   16,    17,    19,    21,    23,    25,    28,    31,
   34,    37,    41,    45,    50,    55,    60,    66,
   73,    80,    88,    97,   107,   118,   130,   143,
  157,   173,   190,   209,   230,   253,   279,   307,
  337,   371,   408,   449,   494,   544,   598,   658,
  724,   796,   876,   963,  1060,  1166,  1282,  1411,
 1552,  1707,  1878,  2066,  2272,  2499,  2749,  3024,
 3327,  3660,  4026,  4428,  4871,  5358,  5894,  6484,
 7132,  7845,  8630,  9493, 10442, 11487, 12635, 13899,
15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
32767,
]

_ADJ = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]

# ── Encoding constants ────────────────────────────────────────────────────────

ENC_RAW   = 0
ENC_ADPCM = 1
ENC_MP2   = 2

ENC_NAMES = {ENC_RAW: "PCM", ENC_ADPCM: "ADPCM", ENC_MP2: "MP2"}


# ── Low-level IMA nibble decode / encode ─────────────────────────────────────

def _dec_nibble(nib, pred, idx):
    step = _STEP[idx]
    E = (2 * (nib & 7) + 1) * step >> 3
    pred = max(-32768, min(32767, pred + (-E if nib & 8 else E)))
    idx  = max(0, min(88, idx + _ADJ[nib]))
    return pred, idx


def _enc_nibble(sample, pred, idx):
    diff = sample - pred
    sign = 8 if diff < 0 else 0
    if sign:
        diff = -diff
    step = _STEP[idx]
    nib  = min(7, (diff * 4) // step)
    E    = (2 * nib + 1) * step >> 3
    pred = max(-32768, min(32767, pred + (-E if sign else E)))
    idx  = max(0, min(88, idx + _ADJ[nib | sign]))
    return nib | sign, pred, idx


# ── Public decode / encode ───────────────────────────────────────────────────

def decode_dvi_adpcm(data, channels, init_preds=None, init_steps=None):
    """
    Decode Riven DVI ADPCM nibble stream → raw 16-bit LE PCM bytes.

    data       : bytes of compressed audio (no block headers)
    channels   : 1 (mono) or 2 (stereo)
    init_preds : initial predictor per channel (default 0)
    init_steps : initial step index per channel (default 0)
    """
    if init_preds is None:
        init_preds = [0] * channels
    if init_steps is None:
        init_steps = [0] * channels

    preds = list(init_preds[:channels])
    steps = list(init_steps[:channels])
    out   = []

    if channels == 2:
        for byte in data:
            hi = (byte >> 4) & 0xF
            lo =  byte       & 0xF
            preds[0], steps[0] = _dec_nibble(hi, preds[0], steps[0])
            preds[1], steps[1] = _dec_nibble(lo, preds[1], steps[1])
            out.append(preds[0])
            out.append(preds[1])
    else:
        for byte in data:
            hi = (byte >> 4) & 0xF
            lo =  byte       & 0xF
            preds[0], steps[0] = _dec_nibble(hi, preds[0], steps[0])
            out.append(preds[0])
            preds[0], steps[0] = _dec_nibble(lo, preds[0], steps[0])
            out.append(preds[0])

    return struct.pack(f"<{len(out)}h", *out)


def encode_dvi_adpcm(pcm_bytes, channels):
    """
    Encode raw 16-bit LE PCM → Riven DVI ADPCM nibble stream.

    Returns (compressed_bytes, init_preds, init_steps).
    init_preds / init_steps are always [0] * channels (fresh start).
    """
    n = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{n}h", pcm_bytes[:n * 2])

    preds = [0] * channels
    steps = [0] * channels
    out   = bytearray()

    if channels == 2:
        # interleaved: L R L R …
        for i in range(0, n - 1, 2):
            hi, preds[0], steps[0] = _enc_nibble(samples[i],     preds[0], steps[0])
            lo, preds[1], steps[1] = _enc_nibble(samples[i + 1], preds[1], steps[1])
            out.append((hi << 4) | lo)
    else:
        for i in range(0, n - 1, 2):
            s1 = samples[i]
            s2 = samples[i + 1] if i + 1 < n else 0
            hi, preds[0], steps[0] = _enc_nibble(s1, preds[0], steps[0])
            lo, preds[0], steps[0] = _enc_nibble(s2, preds[0], steps[0])
            out.append((hi << 4) | lo)

    return bytes(out), [0] * channels, [0] * channels


# ── tWAV format ──────────────────────────────────────────────────────────────

def parse_twav(data):
    """
    Parse a tWAV resource.

    Returns a dict:
      encoding, sample_rate, sample_count, bits_per_sample, channels,
      loop_count, loop_start, loop_end,
      audio_start (byte offset into data), audio_size,
      adpc_preds  (list[int] of initial predictors, one per channel),
      adpc_steps  (list[int] of initial step indices, one per channel)
    """
    info = dict(
        encoding=None, sample_rate=0, sample_count=0,
        bits_per_sample=16, channels=2,
        loop_count=0, loop_start=0, loop_end=0,
        audio_start=0, audio_size=0,
        adpc_preds=[], adpc_steps=[],
    )
    if data[:4] != b"MHWK":
        return info

    pos = 12  # skip MHWK(4) + fileSize(4) + WAVE(4)
    while pos + 8 <= len(data):
        tag       = data[pos:pos + 4]
        chunk_sz  = struct.unpack_from(">I", data, pos + 4)[0]
        body_off  = pos + 8

        if tag == b"ADPC":
            # Seek table: itemCount(2) + channels(2) + itemCount × [sampleFrame(4) + ch × (pred(2)+step(2))]
            if body_off + 4 <= len(data):
                item_count = struct.unpack_from(">H", data, body_off)[0]
                adpc_ch    = struct.unpack_from(">H", data, body_off + 2)[0]
                off = body_off + 4
                preds, steps = [], []
                for _ in range(item_count):
                    off += 4  # sampleFrame
                    for _ in range(adpc_ch):
                        if off + 4 <= len(data):
                            preds.append(struct.unpack_from(">h", data, off)[0])
                            steps.append(struct.unpack_from(">H", data, off + 2)[0])
                        off += 4
                info["adpc_preds"] = preds
                info["adpc_steps"] = steps

        elif tag == b"Data":
            # 20-byte format header, then raw audio
            if body_off + 20 <= len(data):
                hdr = data[body_off:body_off + 20]
                info["sample_rate"]      = struct.unpack_from(">H", hdr, 0)[0]
                info["sample_count"]     = struct.unpack_from(">I", hdr, 2)[0]
                info["bits_per_sample"]  = hdr[6]
                info["channels"]         = hdr[7]
                info["encoding"]         = struct.unpack_from(">H", hdr, 8)[0]
                info["loop_count"]       = struct.unpack_from(">H", hdr, 10)[0]
                info["loop_start"]       = struct.unpack_from(">I", hdr, 12)[0]
                info["loop_end"]         = struct.unpack_from(">I", hdr, 16)[0]
                info["audio_start"]      = body_off + 20
                info["audio_size"]       = chunk_sz - 20

        pos += 8 + chunk_sz

    return info


def build_twav(audio_bytes, rate, channels, encoding, sample_count,
               loop_count=0, loop_start=0, loop_end=0,
               init_preds=None, init_steps=None):
    """
    Build a complete tWAV resource (MHWK WAVE).

    audio_bytes  : raw IMA ADPCM nibbles (encoding=1) or MP2 stream (encoding=2)
    sample_count : PCM frame count
    init_preds/steps : initial IMA state per channel (encoding=1 only)
    """
    chunks = b""

    if encoding == ENC_ADPCM:
        preds = (init_preds or [0] * channels)[:channels]
        steps = (init_steps or [0] * channels)[:channels]
        # ADPC seek table: 1 item at frame 0
        body  = struct.pack(">HH", 1, channels)        # itemCount=1, channels
        body += struct.pack(">I", 0)                   # sampleFrame=0
        for ch in range(channels):
            body += struct.pack(">hH", preds[ch], steps[ch])
        chunks += b"ADPC" + struct.pack(">I", len(body)) + body

    # DATA chunk: 20-byte format header + audio
    hdr = struct.pack(">H",  rate)
    hdr += struct.pack(">I",  sample_count)
    hdr += struct.pack(">BB", 16, channels)            # bitsPerSample=16, channels
    hdr += struct.pack(">H",  encoding)
    hdr += struct.pack(">H",  loop_count)
    hdr += struct.pack(">I",  loop_start)
    hdr += struct.pack(">I",  loop_end)                # 20 bytes total
    payload = hdr + audio_bytes
    chunks += b"Data" + struct.pack(">I", len(payload)) + payload

    inner  = b"WAVE" + chunks
    return b"MHWK" + struct.pack(">I", len(inner)) + inner


# ── Export tWAV → WAV ────────────────────────────────────────────────────────

def export_to_wav(twav_data, ffmpeg=None):
    """
    Decode a tWAV resource and return raw WAV bytes.

    ADPCM: decoded in Python (no ffmpeg needed).
    MP2:   decoded via ffmpeg.
    """
    info = parse_twav(twav_data)
    if info["encoding"] is None:
        raise ValueError("Not a valid tWAV resource")

    rate     = info["sample_rate"]
    channels = info["channels"]
    audio    = twav_data[info["audio_start"]:info["audio_start"] + info["audio_size"]]

    if info["encoding"] == ENC_ADPCM:
        preds = info["adpc_preds"][:channels] if info["adpc_preds"] else [0] * channels
        steps = info["adpc_steps"][:channels] if info["adpc_steps"] else [0] * channels
        pcm = decode_dvi_adpcm(audio, channels, preds, steps)
        return _wrap_wav(pcm, rate, channels)

    if info["encoding"] == ENC_MP2:
        if not ffmpeg:
            ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found — cannot decode MP2 audio")
        with tempfile.NamedTemporaryFile(suffix=".mp2", delete=False) as f:
            f.write(audio); tmp_in = f.name
        tmp_out = tmp_in + ".wav"
        try:
            r = subprocess.run([ffmpeg, "-y", "-i", tmp_in, tmp_out],
                               capture_output=True, timeout=60)
            if os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 44:
                with open(tmp_out, "rb") as f:
                    return f.read()
            raise RuntimeError(f"ffmpeg decode failed:\n{r.stderr.decode(errors='replace')[-300:]}")
        finally:
            for t in (tmp_in, tmp_out):
                try: os.unlink(t)
                except OSError: pass

    raise ValueError(f"Unknown tWAV encoding {info['encoding']}")


# ── Import user audio → tWAV ─────────────────────────────────────────────────

def import_audio(src_path, target_enc, rate, channels, ffmpeg=None):
    """
    Encode a user audio file to match the target tWAV format.

    Returns (audio_bytes, sample_count, init_preds, init_steps).
    init_preds / init_steps are None for MP2.
    """
    if not ffmpeg:
        ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — cannot encode audio")

    # Decode source to raw 16-bit LE PCM
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        tmp_pcm = f.name
    try:
        r = subprocess.run([
            ffmpeg, "-y", "-i", src_path,
            "-f", "s16le", "-ar", str(rate), "-ac", str(channels),
            tmp_pcm,
        ], capture_output=True, timeout=120)
        if not os.path.exists(tmp_pcm) or os.path.getsize(tmp_pcm) == 0:
            raise RuntimeError(
                f"ffmpeg could not read {os.path.basename(src_path)}:\n"
                + r.stderr.decode(errors="replace")[-300:]
            )
        with open(tmp_pcm, "rb") as f:
            pcm_bytes = f.read()
    finally:
        try: os.unlink(tmp_pcm)
        except OSError: pass

    sample_count = len(pcm_bytes) // 2 // channels  # PCM frame count

    if target_enc == ENC_ADPCM:
        audio_bytes, preds, steps = encode_dvi_adpcm(pcm_bytes, channels)
        return audio_bytes, sample_count, preds, steps

    if target_enc == ENC_MP2:
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as fw:
            fw.write(pcm_bytes); tmp_in = fw.name
        with tempfile.NamedTemporaryFile(suffix=".mp2", delete=False) as fw:
            tmp_out = fw.name
        try:
            r = subprocess.run([
                ffmpeg, "-y",
                "-f", "s16le", "-ar", str(rate), "-ac", str(channels),
                "-i", tmp_in,
                "-codec:a", "mp2", "-b:a", "192k",
                tmp_out,
            ], capture_output=True, timeout=120)
            if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
                raise RuntimeError(
                    f"ffmpeg MP2 encode failed:\n"
                    + r.stderr.decode(errors="replace")[-300:]
                )
            with open(tmp_out, "rb") as f:
                audio_bytes = f.read()
        finally:
            for t in (tmp_in, tmp_out):
                try: os.unlink(t)
                except OSError: pass
        return audio_bytes, sample_count, None, None

    raise ValueError(f"Unknown target encoding {target_enc}")


# ── Utility ──────────────────────────────────────────────────────────────────

def dur_str(sample_count, rate):
    """'m:ss' duration string."""
    if not rate:
        return "?"
    secs = int(sample_count / rate)
    return f"{secs // 60}:{secs % 60:02d}"


def info_str(info):
    """Human-readable one-liner for a parsed tWAV info dict."""
    enc   = ENC_NAMES.get(info.get("encoding", -1), "?")
    rate  = info.get("sample_rate", 0)
    ch    = info.get("channels", 0)
    sc    = info.get("sample_count", 0)
    ch_s  = "Stereo" if ch == 2 else "Mono" if ch == 1 else f"{ch}ch"
    dur   = dur_str(sc, rate)
    lc    = info.get("loop_count", 0)
    loop  = "  (loops)" if lc == 0xFFFF else f"  ({lc}×)" if lc else ""
    return f"{enc}  {rate} Hz  {ch_s}  {dur}{loop}"


def _wrap_wav(pcm_bytes, rate, channels):
    """Wrap raw 16-bit LE PCM in a RIFF WAV container."""
    data_size = len(pcm_bytes)
    fmt = struct.pack("<4sIHHIIHH",
        b"fmt ", 16, 1,
        channels, rate, rate * channels * 2,
        channels * 2, 16)
    data_chunk = b"data" + struct.pack("<I", data_size) + pcm_bytes
    body = fmt + data_chunk
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def _find_ffmpeg():
    # When frozen by PyInstaller, prefer the bundled binary
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "ffmpeg.exe")
    if os.path.exists(bundled):
        return bundled
    for fp in ("ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"):
        try:
            subprocess.run([fp, "-version"], capture_output=True, timeout=3)
            return fp
        except Exception:
            pass
    return None
