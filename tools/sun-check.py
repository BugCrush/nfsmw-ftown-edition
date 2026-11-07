"""The game's own view transform in a dissected frame, and where it puts the sun (graphics part 2, light shafts).

GfxProbe's dissection (gfx-captures/<label>/run-*/dissect-N/calls.txt) records every draw's vertex constants. For
the game's world-space draws (scenery, sky: no object matrix of their own) c0-c3 are the main view's world-to-clip
matrix as the game builds it (view 1's eViewPlatInfo + 0x80, camera matrix times projection): clip = (c0.p, c1.p,
c2.p, c3.p) for p = (x, y, z, 1). The most common c0-c3 on the main picture (T0, T9) is that matrix (hundreds of
draws share it; objects such as cars carry their own). From it:

- the view's forward direction (c3), its field of view across and up/down (atan of |c3| / |c0| and |c3| / |c1|);
- where the sun is: the light direction (to the sun, VisualBridge's SUN line `sun=(...)`) as a direction (w = 0):
  screen x = 0.5 + 0.5 c0.d / c3.d, y = 0.5 - 0.5 c1.d / c3.d, in front only when c3.d > 0;
- the player's car: the most common matrix with an object of its own a few metres ahead (|c3.w| < 20), whose origin
  lands at its (c0.w / c3.w, c1.w / c3.w).

Usage: python tools/sun-check.py <calls.txt> [dx dy dz]      (default direction: the 2026-10-23 race's sun)
       python tools/sun-check.py --json <calls.txt>           (the two matrices, full precision, for tests)

The first version of this tool (2026-10-23) picked any draw that put the logged camera's forward at the centre; those
were a few objects turned half round, and the logged camera was the rear-view mirror's (docs/visual-notes.md).
"""
import collections
import json
import math
import sys


def matrices(path, targets=("T0", "T9")):
    """Counter of (c0..c3 as 16 floats, row by row) over the draws on the main picture."""
    consts, target, seen = {}, "?", collections.Counter()
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith("target index=0"):
            target = dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv).get("target", "?")
        elif line.startswith("constants kind=vs"):
            parts = dict(kv.split("=", 1) for kv in line.split()[1:])
            reg, count = int(parts["reg"]), int(parts["count"])
            vals = [float(v) for v in parts["values"].split(",") if v]
            for i in range(count):
                if len(vals) >= i * 4 + 4:
                    consts[reg + i] = vals[i * 4:i * 4 + 4]
        elif line.startswith("draw") and all(r in consts for r in range(4)) and target in targets:
            seen[tuple(v for r in range(4) for v in consts[r])] += 1
    return seen


def main_view(seen):
    return seen.most_common(1)[0]


def car(seen):
    for m, n in seen.most_common():
        if 0.5 < abs(m[15]) < 20 and abs(math.sqrt(sum(v * v for v in m[12:15])) - 1) < 0.05:
            return m, n
    return None, 0


def project(rows, d, w=0.0):
    """Screen place of (d, w) through c0..c3 (16 floats, row by row); None when not in front."""
    p = list(d) + [w]
    c = [sum(rows[r * 4 + i] * p[i] for i in range(4)) for r in range(4)]
    if c[3] <= 1e-9:
        return None
    return 0.5 + 0.5 * c[0] / c[3], 0.5 - 0.5 * c[1] / c[3]


def fov(rows):
    n = lambda r: math.sqrt(sum(v * v for v in rows[r * 4:r * 4 + 3]))
    return math.degrees(2 * math.atan(n(3) / n(0))), math.degrees(2 * math.atan(n(3) / n(1)))


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    seen = matrices(args[0])
    view, n = main_view(seen)
    car_m, car_n = car(seen)
    if as_json:
        print(json.dumps({"view": list(view), "view_draws": n, "car": list(car_m) if car_m else None, "car_draws": car_n}))
        return
    d = [float(v) for v in args[1:4]] if len(args) >= 4 else [0.752, -0.504, 0.426]
    fx, fy = fov(view)
    length = math.sqrt(sum(v * v for v in view[12:15]))
    facing = sum(view[12 + i] * d[i] for i in range(3)) / length / math.sqrt(sum(v * v for v in d))
    print("main view: %d draws, forward (%.3f, %.3f, %.3f), field of view %.1f x %.1f deg" % (
        n, view[12] / length, view[13] / length, view[14] / length, fx, fy))
    at = project(view, d)
    print("sun: facing %.3f, %s" % (facing, "behind the camera" if at is None else "at (%.3f, %.3f)" % at))
    if car_m:
        print("player's car: %d draws, origin at (%.3f, %.3f)" % (car_n, 0.5 + 0.5 * car_m[3] / car_m[15], 0.5 - 0.5 * car_m[7] / car_m[15]))


if __name__ == "__main__":
    main()
