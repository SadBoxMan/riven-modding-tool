"""
riven_pack.py - an optimal-parse encoder for Riven's own image compression (tBMP pack type 0x0400).

Used for "same-size" patching (a_data.mhk), where an edited image has to compress into the original's exact
slot. It finds the cheapest command sequence for the whole image (dynamic programming), which beats the
original 1997 encoder by about 3% on Riven's journal pages.

Command semantics mirror ScummVM engines/mohawk/bitmap.cpp (unpackRiven / handleRivenSubcommandStream).
Every command reproduces the target bytes exactly, and its meaning depends only on bytes already output,
so the cheapest encoding is a shortest path over byte positions. States model the 1-byte group headers:
S = inside a subcommand group, L = inside a literal run, T = after a top-level repeat.
"""
import struct

TABLE_EXACT = {4: 0xA8, 6: 0xB4, 8: 0xBC, 10: 0xE8, 12: 0xF4}          # NDUPLETS(n): n pixels copied
TABLE_LIT = {4: 0xA4, 6: 0xAC, 8: 0xB8, 10: 0xE4, 12: 0xEC, 14: 0xF8}  # n-1 pixels copied + 1 literal
INF = float("inf")
G = 1.0 / 63  # extra header byte per 63 group entries, amortised


def _best_sub(px, i):
    """Cheapest single-duplet subcommand for px[i:i+2] (i >= 2) -> (cost, bytes) or None."""
    b0, b1 = px[i], px[i + 1]
    p0, p1 = px[i - 2], px[i - 1]
    for m in range(1, 16):                                   # 0x01-0x0F: the duplet m duplets back
        if i - 2 * m >= 0 and px[i - 2 * m] == b0 and px[i + 1 - 2 * m] == b1:
            return 1, bytes([m])
    if b0 == p0:
        d = (b1 - p1) & 0xFF
        if d < 16:
            return 1, bytes([0x20 + d])                      # b1 = p1 + m
        d = (p1 - b1) & 0xFF
        if d < 16:
            return 1, bytes([0x30 + d])                      # b1 = p1 - m
        for m in range(1, 16):
            if px[i + 1 - m] == b1:
                return 1, bytes([0x10 + m])                  # b1 = pixel m back
    if b1 == p1:
        d = (b0 - p0) & 0xFF
        if d < 16:
            return 1, bytes([0x80 + d])                      # b0 = p0 + m
        d = (p0 - b0) & 0xFF
        if d < 16:
            return 1, bytes([0xC0 + d])                      # b0 = p0 - m
        for m in range(1, 16):
            if i - m >= 0 and px[i - m] == b0:
                return 1, bytes([0x40 + m])                  # b0 = pixel m back
    if b0 == p0:
        return 2, bytes([0x10, b1])
    if b1 == p1:
        return 2, bytes([0x40, b0])
    d0p, d0m = (b0 - p0) & 0xFF, (p0 - b0) & 0xFF
    d1p, d1m = (b1 - p1) & 0xFF, (p1 - b1) & 0xFF
    if d0p < 16 and d1p < 16:
        return 2, bytes([0xA0, (d0p << 4) | d1p])
    if d0p < 16 and d1m < 16:
        return 2, bytes([0xB0, (d0p << 4) | d1m])
    if d0m < 16 and d1p < 16:
        return 2, bytes([0xE0, (d0m << 4) | d1p])
    if d0m < 16 and d1m < 16:
        return 2, bytes([0xF0, (d0m << 4) | d1m])
    if d1p < 16:
        return 2, bytes([0x60 + d1p, b0])
    if d1m < 16:
        return 2, bytes([0x70 + d1m, b0])
    if d0p < 16:
        return 2, bytes([0x90 + d0p, b1])
    if d0m < 16:
        return 2, bytes([0xD0 + d0m, b1])
    for m in range(1, 8):
        if i - m >= 0 and px[i - m] == b0:
            return 2, bytes([0x50 + m, b1])                  # 0x51-0x57
        if px[i + 1 - m] == b1:
            return 2, bytes([0x58 + m, b0])                  # 0x59-0x5F
    return None


def _match_info(px, chain):
    """For each even i: (longest copy length >= 3, distance 1..1023), overlap allowed like the decoder."""
    n = len(px)
    heads = {}
    best = [None] * (n + 1)
    for i in range(n):
        if i % 2 == 0 and i + 4 <= n:
            bl, bd = 0, 0
            for j in reversed(heads.get(px[i:i + 3], ())[-chain:]):
                d = i - j
                if d > 1023:
                    break
                L = 0
                lim = min(66, n - i)
                while L < lim and px[i + L] == px[i + L - d]:
                    L += 1
                if L > bl:
                    bl, bd = L, d
                    if L == lim:
                        break
            if bl >= 3:
                best[i] = (bl, bd)
        if i + 3 <= n:
            lst = heads.setdefault(px[i:i + 3], [])
            lst.append(i)
            if len(lst) > 96:
                del lst[:48]
    return best


def pack(px, chain=48):
    """Riven-pack `px` (8bpp index bytes, even length). Returns the stream that follows the palette."""
    n = len(px)
    if n % 2:
        raise ValueError("pixel data length must be even")
    mi = _match_info(px, chain)
    subs = [None] * n
    for i in range(2, n, 2):
        subs[i] = _best_sub(px, i)
    cost = [[INF] * (n + 1) for _ in range(3)]
    back = [[None] * (n + 1) for _ in range(3)]
    cost[2][0] = 0.0

    def relax(st, j, c, info):
        if c < cost[st][j]:
            cost[st][j] = c
            back[st][j] = info

    for i in range(0, n, 2):
        for s in range(3):
            c0 = cost[s][i]
            if c0 == INF:
                continue
            open_s = 0 if s == 0 else 1
            open_l = 0 if s == 1 else 1
            relax(1, i + 2, c0 + open_l + 2 + G, (s, i, "lit", None))
            if i >= 2:
                sb = subs[i]
                if sb:
                    relax(0, i + 2, c0 + open_s + sb[0] + G, (s, i, "sub", sb[1]))
                relax(0, i + 2, c0 + open_s + 3 + G, (s, i, "sub", bytes([0x50, px[i], px[i + 1]])))
                k = 0
                while k < 63 and i + 2 * k + 2 <= n and px[i + 2 * k] == px[i - 2] and px[i + 2 * k + 1] == px[i - 1]:
                    k += 1
                    relax(2, i + 2 * k, c0 + 1, (s, i, "top", 0x40 + k))
            if i >= 4:
                k = 0
                while k < 63 and i + 4 * k + 4 <= n and px[i + 4 * k:i + 4 * k + 4] == px[i - 4:i]:
                    k += 1
                    relax(2, i + 4 * k, c0 + 1, (s, i, "top", 0x80 + k))
            m = mi[i]
            if m:
                Lmax, d = m
                for L in range(4, min(Lmax, 66) + 1, 2):        # fully copied
                    if L <= 12:
                        relax(0, i + L, c0 + open_s + 2 + G,
                              (s, i, "sub", bytes([TABLE_EXACT[L] | (d >> 8), d & 0xFF])))
                    else:
                        k = (L - 2) // 2
                        relax(0, i + L, c0 + open_s + 3 + G,
                              (s, i, "sub", bytes([0xFC, ((k - 1) << 3) | 0x04 | (d >> 8), d & 0xFF])))
                for L in range(4, min(Lmax + 1, 66) + 1, 2):    # L-1 copied + 1 literal
                    if L - 1 > Lmax:
                        continue
                    if L in TABLE_LIT:
                        relax(0, i + L, c0 + open_s + 3 + G,
                              (s, i, "sub", bytes([TABLE_LIT[L] | (d >> 8), d & 0xFF, px[i + L - 1]])))
                    elif L >= 16:
                        k = (L - 2) // 2
                        relax(0, i + L, c0 + open_s + 4 + G,
                              (s, i, "sub", bytes([0xFC, ((k - 1) << 3) | (d >> 8), d & 0xFF, px[i + L - 1]])))

    s = min(range(3), key=lambda q: cost[q][n])
    toks, i = [], n
    while i > 0:
        ps, pi, kind, val = back[s][i]
        toks.append((kind, val, pi))
        s, i = ps, pi
    toks.reverse()

    out = bytearray(struct.pack(">I", n))   # the 'unknown' u32: original files hold about bpr * height
    k = 0
    while k < len(toks):
        kind = toks[k][0]
        if kind == "top":
            out.append(toks[k][1])
            k += 1
            continue
        j = k
        while j < len(toks) and toks[j][0] == kind and j - k < 63:
            j += 1
        if kind == "sub":
            out.append(0xC0 + (j - k))
            for t in toks[k:j]:
                out += t[1]
        else:
            out.append(j - k)
            for t in toks[k:j]:
                out += px[t[2]:t[2] + 2]
        k = j
    out.append(0)
    return bytes(out)
