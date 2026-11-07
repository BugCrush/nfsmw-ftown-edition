"""What Rockport draws along a candidate connector (docs/ftown-connection-research.md "Where the connector leaves").

Read-only on the game. For a straight line from a road-network node outwards (render x, y, heading, length), finds the
drivable sections the line passes, the union of their visible lists (what the streamer loads and the game draws there,
notes Q2/Q3), reads those sections' drawn scenery (every detail level 0 solid, library solids from X/V) and reports
per 50 m along the line: the highest and lowest drawn triangle within `half` metres of the line (the ground or a hill
the connector would have to pass over or through), and which section draws it. Also a top-down picture of the drawn
triangles around the line, coloured by height.

usage: .tools/cityenv/Scripts/python tools/citymap/connection_profile.py <game> <out dir> <name> <x> <y> <heading deg>
       <length m> [half width m]
    out: profile-<name>.json, profile-<name>.png
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from world import bun, scenery, world  # noqa: E402

STEP = 50.0


def main(game, outdir, name, x, y, heading, length, half=40.0):
    from PIL import Image, ImageDraw
    l2ra, stream = world.paths(game)
    bounds = bun.boundaries(l2ra)
    vis = bun.drivable_sections(l2ra)
    secs = {s.number: s for s in bun.sections(l2ra)}
    present = set(secs)
    ux, uy = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    zones, along = [], []
    for k in range(int(length / 10) + 1):
        px, py = x + ux * 10 * k, y + uy * 10 * k
        z = 0
        for n, b in bounds.items():
            if bun.is_drivable(n) and bun.point_in_poly((px, py), b.points):
                z = n
                break
        along.append(z)
        if z and z not in zones:
            zones.append(z)
    wanted = set()
    for z in zones:
        wanted.update(vis.get(z, []))
    lib = world.library_solids(game)
    prof = {}
    tris_near = []
    all_tris = []
    for n in sorted(wanted):
        num = bun.combined_number(n, present) if n not in present else n
        s = secs.get(num)
        if s is None:
            continue
        data = scenery.read_section(bun.read_range(stream, s.offset, s.size))
        for p0, p1, p2, kind, sname in scenery.placed_triangles(data, lib, drivable_only=False):
            cx, cy, cz = [(p0[i] + p1[i] + p2[i]) / 3 for i in range(3)]
            dx, dy = cx - x, cy - y
            t = dx * ux + dy * uy
            d = abs(-dx * uy + dy * ux)
            all_tris.append((p0, p1, p2, n, kind))
            if -100 <= t <= length + 100 and d <= half * 3:
                tris_near.append((p0, p1, p2, n, kind))
            if 0 <= t <= length and d <= half:
                b = int(t // STEP)
                for p in (p0, p1, p2):
                    lo, hi, who = prof.get(b, (1e9, -1e9, set()))
                    who.add(bun.section_name(n))
                    prof[b] = (min(lo, p[2]), max(hi, p[2]), who)
    # the drawn surface right above/below each 10 m point of the line (triangles containing it in x, y)
    surf = [(-1e9, "") for _ in range(int(length / 10) + 1)]
    for p0, p1, p2, n, kind in all_tris:
        xs, ys = (p0[0], p1[0], p2[0]), (p0[1], p1[1], p2[1])
        ts = [((px - x) * ux + (py - y) * uy) for px, py in zip(xs, ys)]
        ds = [(-(px - x) * uy + (py - y) * ux) for px, py in zip(xs, ys)]
        if max(ts) < 0 or min(ts) > length or min(ds) > 0 or max(ds) < 0:
            continue
        for k in range(max(0, int(min(ts) // 10)), min(len(surf) - 1, int(max(ts) // 10) + 1) + 1):
            qx, qy = x + ux * 10 * k, y + uy * 10 * k
            det = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
            if abs(det) < 1e-9:
                continue
            a = ((p1[1] - p2[1]) * (qx - p2[0]) + (p2[0] - p1[0]) * (qy - p2[1])) / det
            b = ((p2[1] - p0[1]) * (qx - p2[0]) + (p0[0] - p2[0]) * (qy - p2[1])) / det
            c = 1 - a - b
            if a < -1e-6 or b < -1e-6 or c < -1e-6:
                continue
            zq = a * p0[2] + b * p1[2] + c * p2[2]
            if zq > surf[k][0]:
                surf[k] = (zq, bun.section_name(n))
    rows = []
    for b in range(int(length // STEP) + 1):
        lo, hi, who = prof.get(b, (None, None, set()))
        rows.append(dict(at=b * STEP, low=None if lo is None else round(lo, 1), high=None if hi is None else round(hi, 1),
                         sections=sorted(who), zone=bun.section_name(along[min(len(along) - 1, int(b * STEP / 10))])
                         if along[min(len(along) - 1, int(b * STEP / 10))] else "none",
                         surface=[None if surf[k][0] < -1e8 else [round(surf[k][0], 1), surf[k][1]]
                                  for k in range(int(b * STEP / 10), min(len(surf), int((b + 1) * STEP / 10)))]))
    out = dict(name=name, start=[x, y], heading=heading, length=length, half=half,
               zones=[bun.section_name(z) for z in zones], visible=sorted(bun.section_name(n) for n in wanted),
               profile=rows)
    with open(os.path.join(outdir, "profile-%s.json" % name), "w") as f:
        json.dump(out, f, indent=1)
    print("%s: zones along the line %s; %d visible sections" % (name, out["zones"], len(wanted)))
    for r in rows:
        top = [q for q in r["surface"] if q]
        hi = max(top) if top else None
        print("  %5.0f m  zone %-4s  drawn z %s .. %s  %s; highest surface over the line %s" % (
            r["at"], r["zone"], r["low"], r["high"], ",".join(r["sections"][:8]), hi))
    # picture
    S = 1.0
    pts = [p for t in tris_near for p in t[:3]]
    if not pts:
        return out
    X0 = min(p[0] for p in pts)
    X1 = max(p[0] for p in pts)
    Y0 = min(p[1] for p in pts)
    Y1 = max(p[1] for p in pts)
    S = min(1400 / max(1.0, X1 - X0), 1400 / max(1.0, Y1 - Y0))
    img = Image.new("RGB", (int((X1 - X0) * S) + 20, int((Y1 - Y0) * S) + 40), (255, 255, 255))
    d = ImageDraw.Draw(img)
    zs = sorted(p[2] for p in pts)
    zlo, zhi = zs[len(zs) // 50], zs[-len(zs) // 50 - 1]

    def P(p):
        return (10 + (p[0] - X0) * S, 10 + (Y1 - p[1]) * S)

    for p0, p1, p2, n, kind in sorted(tris_near, key=lambda t: max(t[0][2], t[1][2], t[2][2])):
        zc = (p0[2] + p1[2] + p2[2]) / 3
        v = max(0.0, min(1.0, (zc - zlo) / max(1.0, zhi - zlo)))
        col = (int(40 + 200 * v), int(120 + 60 * (1 - v)), int(220 * (1 - v)))
        if kind == "road":
            col = (60, 60, 60)
        d.polygon([P(p0), P(p1), P(p2)], fill=col)
    d.line([P((x, y)), P((x + ux * length, y + uy * length))], fill=(255, 0, 0), width=3)
    d.text((10, img.size[1] - 25), "%s: drawn scenery near the line (blue low %.0f m .. red high %.0f m; dark = road); "
           "red line: the candidate" % (name, zlo, zhi), fill=(0, 0, 0))
    img.save(os.path.join(outdir, "profile-%s.png" % name))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], float(a[3]), float(a[4]), float(a[5]), float(a[6]), float(a[7]) if len(a) > 7 else 40.0)
