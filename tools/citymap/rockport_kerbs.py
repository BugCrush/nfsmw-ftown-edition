"""How Rockport's collision takes its kerbs and sidewalks, measured from the game's files (read only; numbers only), the
reference for F-Town's climbable platforms (docs/ftown-notes.md "Run H fixes (2026-11-04)", fault 3).

    .tools/cityenv/Scripts/python tools/citymap/rockport_kerbs.py

Over every collision pack of STREAML2RA.BUN: the faces' edges keyed by their (x, z) ends to 2 cm, each face's height at
the edge. Where an edge of a flat face (normal y > 0.9) of one surface lies on an edge of a flat face of another
surface: the step between them (0 = joined). Where a flat face's edge meets a steep face (normal y 0.2 .. 0.9): a
chamfer: its rise and width. And the barriers (walls) along a sidewalk's edge: low ones (under 1.5 m) and all, within
0.3 m of a concrete-asphalt edge.
"""
import collections
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

from vlthash import vlt32  # noqa: E402
from world import bun, collision, scenery  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")
NAMES = ["asphalt", "concrete", "none", "grass", "asphalt_no_leaves", "grass_shoulder", "cobble", "wood", "gravel",
         "golf_rough", "metal", "golf_fairway", "dirt", "stone", "sand", "golf_green", "railroad", "glass"]
NAME_OF = {vlt32(n): n for n in NAMES}
NAME_OF[0] = "none"


def _name(h):
    return NAME_OF.get(h, "0x%08X" % (h or 0))


def measure():
    steps = collections.defaultdict(list)  # (surface a, surface b) -> [|dy|] at flat-flat edges
    chamfer = collections.defaultdict(list)  # (flat surface, steep surface) -> [(rise, width)]
    steep_area = collections.Counter()
    flat_area = collections.Counter()
    kerb_edges = []  # midpoints (x, z, y) of concrete-asphalt edges with a step over 5 cm
    bars = []
    for s in bun.sections(L2RA):
        for c, p in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
            if c.id != collision.COLLISION_PACK:
                continue
            try:
                pk = collision.read_pack(c.data, p)
            except (ValueError, struct.error):
                continue
            edges = collections.defaultdict(list)
            for a, b, cc, h, _n in collision.triangles(pk):
                A, B, C = np.array(a), np.array(b), np.array(cc)
                n = np.cross(B - A, C - A)
                L = np.linalg.norm(n)
                if L < 1e-6:
                    continue
                ny = abs(n[1]) / L
                area = L / 2
                nm = _name(h)
                if ny > 0.9:
                    kind = "flat"
                    flat_area[nm] += area
                elif ny > 0.2:
                    kind = "steep"
                    steep_area[nm] += area
                else:
                    kind = "wall"
                    steep_area[nm + " (vertical face)"] += area
                ys = [A[1], B[1], C[1]]
                xs = [(A[0], A[2]), (B[0], B[2]), (C[0], C[2])]
                for i, j in ((0, 1), (1, 2), (2, 0)):
                    ka = (round(xs[i][0] / 0.02), round(xs[i][1] / 0.02))
                    kb = (round(xs[j][0] / 0.02), round(xs[j][1] / 0.02))
                    if ka == kb:
                        continue
                    key = (ka, kb) if ka < kb else (kb, ka)
                    edges[key].append((nm, kind, (ys[i] + ys[j]) / 2, (A, B, C)))
            for key, fs in edges.items():
                flats = [f for f in fs if f[1] == "flat"]
                for i in range(len(flats)):
                    for j in range(i + 1, len(flats)):
                        a, b = flats[i], flats[j]
                        if a[0] == b[0]:
                            continue
                        pair = tuple(sorted((a[0], b[0])))
                        dy = abs(a[2] - b[2])
                        steps[pair].append(dy)
                        if pair == ("asphalt", "concrete") and dy > 0.05:
                            kx = (key[0][0] + key[1][0]) * 0.01
                            kz = (key[0][1] + key[1][1]) * 0.01
                            kerb_edges.append((kx, kz, min(a[2], b[2])))
                for f in flats:
                    for g in fs:
                        if g[1] == "steep":
                            A, B, C = g[3]
                            ys = [A[1], B[1], C[1]]
                            xz = np.array([[A[0], A[2]], [B[0], B[2]], [C[0], C[2]]])
                            width = float(np.ptp(xz[:, 0]) if np.ptp(xz[:, 0]) < np.ptp(xz[:, 1])
                                          else np.ptp(xz[:, 1]))
                            chamfer[(f[0], g[0])].append((max(ys) - min(ys), width))
            for pa, pb, hgt, h, _n in collision.barriers(pk):
                bars.append(((pa[0] + pb[0]) / 2, (pa[2] + pb[2]) / 2, min(pa[1], pb[1]), hgt))
    return steps, chamfer, steep_area, flat_area, kerb_edges, bars


def main(argv):
    steps, chamfer, steep_area, flat_area, kerb_edges, bars = measure()
    print("flat faces by surface (m2):", {k: round(v) for k, v in flat_area.most_common(10)})
    print("steep and vertical faces by surface (m2):", {k: round(v) for k, v in steep_area.most_common(12)})
    print("\nflat-flat edges between two surfaces: count, joined (< 2 cm), steps 2-10 cm, 10-25 cm, over 25 cm, "
          "median step of the stepped")
    for pair, v in sorted(steps.items(), key=lambda kv: -len(kv[1]))[:12]:
        v = np.array(v)
        st = v[v >= 0.02]
        print("  %-30s %7d  %6d %6d %6d %6d  %.3f" % ("%s / %s" % pair, len(v), int((v < 0.02).sum()),
                                                     int(((v >= 0.02) & (v < 0.10)).sum()),
                                                     int(((v >= 0.10) & (v < 0.25)).sum()), int((v >= 0.25).sum()),
                                                     float(np.median(st)) if len(st) else 0.0))
    print("\nflat face edge on a steep face (a chamfer): count, median rise, median width (m)")
    for pair, v in sorted(chamfer.items(), key=lambda kv: -len(kv[1]))[:10]:
        v = np.array(v)
        print("  %-30s %7d  %.3f %.3f" % ("%s -> %s" % pair, len(v), float(np.median(v[:, 0])),
                                          float(np.median(v[:, 1]))))
    if kerb_edges and bars:
        K = np.array(kerb_edges)
        Bm = np.array(bars)
        near, low = 0, 0
        cell = {}
        for i, (x, z, y, h) in enumerate(Bm):
            cell.setdefault((int(x // 4), int(z // 4)), []).append(i)
        for x, z, y in K:
            hit = []
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in cell.get((int(x // 4) + dx, int(z // 4) + dz), ()):
                        bx, bz, by, bh = Bm[i]
                        if (bx - x) ** 2 + (bz - z) ** 2 < 0.3 ** 2 + 4.0 and by < y + 1.0:
                            hit.append(bh)
            if hit:
                near += 1
                if min(hit) < 1.5:
                    low += 1
        print("\n%d asphalt-concrete edges with a step over 5 cm; a barrier's middle within 2 m: %d (under 1.5 m "
              "tall: %d)" % (len(K), near, low))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
