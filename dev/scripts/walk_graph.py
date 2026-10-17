"""Read-only: distance (in card jumps) of every location from the new-game start, over the whole game graph."""
import collections
import statistics
import struct
import sys

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
sys.path.insert(0, GAME)
import riven_gui as G
import riven_img as R

STACKS = {1: "o", 2: "p", 3: "r", 4: "t", 5: "b", 6: "g", 7: "j", 8: "a"}
SPECIAL = [(8, 0x1f04, 1, 0x44ad), (5, 0x1c0e7, 1, 0x2e76), (6, 0x111b1, 1, 0x2e76), (7, 0x28a18, 3, 0xf94),
           (7, 0x26228, 1, 0x2e76), (1, 0x5f0d, 2, 0x3bf0), (1, 0x470a, 7, 0x1508e), (1, 0x5c52, 6, 0x10bea),
           (1, 0x5d68, 5, 0x1adfd), (1, 0x5e49, 4, 0xe87), (2, 0x4108, 1, 0x2e76), (3, 0x32d8, 7, 0x1c474),
           (4, 0x21b69, 1, 0x2e76)]


def scan(d, p, links, stacks):
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        p = scan_script(d, p + 2, links, stacks)
    return p


def scan_script(d, p, links, stacks):
    n, = struct.unpack_from(">H", d, p)
    p += 2
    for _ in range(n):
        t, = struct.unpack_from(">H", d, p)
        p += 2
        if t == 8:
            _, _, branches = struct.unpack_from(">3H", d, p)
            p += 6
            for _ in range(branches):
                p = scan_script(d, p + 2, links, stacks)
        elif t == 27:
            _, stack, gid = struct.unpack_from(">HHI", d, p)
            stacks.add((stack, gid))
            p += 8
        else:
            argc, = struct.unpack_from(">H", d, p)
            args = struct.unpack_from(f">{argc}H", d, p + 2)
            p += 2 + 2 * argc
            if t == 2 and args:
                links.add(args[0])
    return p


def card_links(arc, cid):
    links, stacks = set(), set()
    try:
        scan(arc.read(b"CARD", cid), 4, links, stacks)
        if cid in arc.types.get(b"HSPT", {}):
            h = arc.read(b"HSPT", cid)
            n, = struct.unpack_from(">H", h, 0)
            q = 2
            for _ in range(n):
                q = scan(h, q + 22, links, stacks)
    except struct.error:
        pass
    return links, stacks


def build():
    nodes, gid_to_card, edges, info = {}, {}, collections.defaultdict(set), {}
    pending = []
    for title, files, _ in G.AREAS:
        letter = "extras" if files == ["extras.mhk"] else files[0][0]
        sid = next((k for k, v in STACKS.items() if v == letter), None)
        if sid is None or letter == "a":
            continue
        arcs = [R.Archive(R.find_original(GAME + "\\" + f)) for f in files]
        rmap = None
        for a in arcs:
            if b"RMAP" in a.types:
                raw = a.read(b"RMAP", a.ids(b"RMAP")[0])
                rmap = struct.unpack(f">{len(raw) // 4}I", raw)
        for a in arcs:
            for cid in a.types.get(b"CARD", {}):
                node = (letter, cid)
                nodes[node] = title
                if rmap and cid < len(rmap):
                    gid_to_card[(sid, rmap[cid])] = node
                links, stacks = card_links(a, cid)
                for l in links:
                    edges[node].add((letter, l))
                for s in stacks:
                    pending.append((node, s))
    for node, (sid, gid) in pending:
        tgt = gid_to_card.get((sid, gid))
        if tgt:
            edges[node].add(tgt)
    for s1, g1, s2, g2 in SPECIAL:
        a, b = gid_to_card.get((s1, g1)), gid_to_card.get((s2, g2))
        if a and b:
            edges[a].add(b)
    return nodes, gid_to_card, edges


def bfs(edges, start):
    dist = {start: 0}
    q = collections.deque([start])
    while q:
        n = q.popleft()
        for m in edges.get(n, ()):
            if m not in dist:
                dist[m] = dist[n] + 1
                q.append(m)
    return dist


if __name__ == "__main__":
    nodes, gid_to_card, edges = build()
    start = gid_to_card[(4, 0x6e9a)]
    dist = bfs(edges, start)
    print("cards", len(nodes), "edges", sum(len(v) for v in edges.values()), "start", start,
          "reached", sum(1 for n in nodes if n in dist))
    by_island = collections.Counter(nodes[n] for n in dist if n in nodes)
    print("reached per island:", dict(by_island))
    first_island = {}
    for n, d in sorted(dist.items(), key=lambda kv: kv[1]):
        if n in nodes and nodes[n] not in first_island:
            first_island[nodes[n]] = d
    print("first depth per island:", first_island)
    for title, files, _ in G.AREAS:
        letter = files[0][0]
        if letter in ("e", "a"):
            continue
        arcs, res, cards = G.load_area(GAME, files, title)
        per = collections.defaultdict(list)
        for c in cards.values():
            d = dist.get((letter, c.cid))
            if d is not None:
                per[c.loc].append(d)
        print(f"\n== {title}")
        for loc, ds in sorted(per.items(), key=lambda kv: statistics.median(kv[1])):
            print(f"   median {statistics.median(ds):5.1f}  min {min(ds):3d}  cards {len(ds):3d}/{sum(1 for c in cards.values() if c.loc == loc):3d}  {loc}")
