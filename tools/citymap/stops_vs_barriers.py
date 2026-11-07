"""Where the car stopped hard in a run, against the barriers of the city file it drove (docs/ftown-notes.md "Run H fixes
(2026-11-04)", fault 3).

    .tools/cityenv/Scripts/python tools/citymap/stops_vs_barriers.py <WorldProbe.log> <city.bun> [t0 t1]

A hard stop: WorldProbe's once-a-second POS shows the speed falling by more than 35 km/h to under 25 km/h between two
lines (a crash or a hard brake). For each: the barriers whose segment passes within 4 m of the car's position at the
second line, by height (bottom..top above the ground, 100 m) and sidedness (0x10 in the flags: two-sided).
"""
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import read_chunks  # noqa: E402
from world import collision_write, scenery  # noqa: E402


def barriers(data):
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id != collision_write.COLLISION_PACK:
            continue
        pk = collision_write.read_pack(c.data, p)
        for inst in pk.instances:
            t = inst.t
            for b in pk.articles[inst.article].barriers:
                a = (b.p0[0] - t[0], b.p0[1] - t[1], b.p0[2] - t[2])
                q = (b.p1[0] - t[0], b.p1[1] - t[1], b.p1[2] - t[2])
                # physics (x, y up, z) -> render (z, -x, y)
                out.append(((a[2], -a[0]), (q[2], -q[0]), min(a[1], q[1]), max(a[1], q[1]), (b.word >> 8) & 0xFF))
    return out


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    s = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - s * dx, p[1] - a[1] - s * dy)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    t0, t1 = (float(argv[2]), float(argv[3])) if len(argv) > 3 else (0.0, 1e9)
    pos = []
    for raw in open(argv[0], encoding="utf-8", errors="replace"):
        m = re.match(r"^\[\s*([0-9.]+)\] POS .*render \(([-0-9.]+), ([-0-9.]+), ([-0-9.]+)\).*speed ([0-9.]+)", raw)
        if m:
            pos.append(tuple(float(x) for x in m.groups()))
    with open(argv[1], "rb") as f:
        bars = barriers(f.read())
    kinds = {}
    n = 0
    for (ta, xa, ya, za, va), (tb, xb, yb, zb, vb) in zip(pos, pos[1:]):
        if not (t0 <= tb <= t1) or not (va - vb > 35.0 and vb < 25.0):
            continue
        n += 1
        near = sorted((seg_dist((xb, yb), b[0], b[1]), b) for b in bars if seg_dist((xb, yb), b[0], b[1]) < 4.0)
        desc = ["%.1f m: %.2f..%.2f %s" % (d, b[2] - 100.0, b[3] - 100.0, "two-sided" if b[4] & 0x10 else "one-sided")
                for d, b in near[:3]]
        k = "none within 4 m" if not near else "%.2f m tall %s" % (near[0][1][3] - near[0][1][2],
                                                                  "two-sided" if near[0][1][4] & 0x10 else "one-sided")
        kinds[k] = kinds.get(k, 0) + 1
        print("%8.1f s %5.0f -> %4.0f km/h at render (%.1f, %.1f, %.2f): %s" % (tb, va, vb, xb, yb, zb,
                                                                              "; ".join(desc) or "-"))
    print("\n%d hard stops; nearest barrier: %s" % (n, kinds))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
