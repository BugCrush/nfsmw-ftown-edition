"""Where can a road leave Rockport for F-Town? (docs/ftown-connection-research.md "Where the connector leaves").

Read-only on the game. For every road-network node of Rockport (not road 149, the final chase's road) within 1,500 m of
the edge of Rockport's drivable sections, and for headings within 40 degrees of the way out, walks a straight line from
the node outwards until it leaves every drivable section, and measures along it:
  inside    metres from the node to the edge of the drivable sections (the part of the connector Rockport streams)
  crossings collision faces of other roads within 6 m of the line, beyond 40 m from the node (a connector must not cross
            Rockport's roads: it would need a junction or a bridge there)
  walls     Rockport barriers the line crosses within 60 m of the node (walls to open at run time)
  relief    the lowest and highest collision face (any kind) within 6 m of the line, against the node's height
Then the best line per side of the map (north, east, south, west) and a picture of all candidates.

usage: .tools/cityenv/Scripts/python tools/citymap/connection_sites.py <game dir> <out dir>
    out: connection-sites.json, connection-sites.png
The collision of all of Rockport is read once into <out dir>/collision-cache.pkl (the research's cache format).
"""
import json
import math
import os
import pickle
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from world import bun, collision, roadnet, scenery  # noqa: E402

FINAL_CHASE_ROAD = 149
CELL = 8.0  # metres per raster cell
NEAR = 40.0  # crossings ignored this close to the node (its own road)
WALL_NEAR = 60.0
SIDE = 6.0


def load_collision(game, cache):
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    stream = os.path.join(game, "TRACKS", "STREAML2RA.BUN")
    tris, bars = [], []
    for s in bun.sections(l2ra):
        if s.letter in "XYZV":
            continue
        for p in collision.packs_in(bun.read_range(stream, s.offset, s.size), s.offset):
            for a, b, c, h, n in collision.triangles(p):
                ra, rb, rc = collision.to_render(a), collision.to_render(b), collision.to_render(c)
                tris.append(((ra[0] + rb[0] + rc[0]) / 3, (ra[1] + rb[1] + rc[1]) / 3, (ra[2] + rb[2] + rc[2]) / 3, h,
                             p.section))
            for a, b, hgt, h, n in collision.barriers(p):
                ra, rb = collision.to_render(a), collision.to_render(b)
                bars.append((ra[0], ra[1], rb[0], rb[1], min(ra[2], rb[2]), max(ra[2], rb[2]), p.section))
    with open(cache, "wb") as f:
        pickle.dump((tris, bars), f)
    return tris, bars


def load_network(game):
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    for c, pos in scenery.with_positions(bun.read_file(l2ra), 0):
        if c.id == 0x3B800:
            return roadnet.read_rngp(c.data, pos)[0]
    raise ValueError("no road network in L2RA.BUN")


def seg_intersect(p, q, a, b):
    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    d1, d2 = cross(a, b, p), cross(a, b, q)
    d3, d4 = cross(p, q, a), cross(p, q, b)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def main(game, outdir):
    import numpy as np
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    from PIL import Image, ImageDraw
    os.makedirs(outdir, exist_ok=True)
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    bounds = bun.boundaries(l2ra)
    drv = [Polygon(b.points).buffer(0) for n, b in bounds.items() if bun.is_drivable(n)]
    hull = unary_union(drv)
    tris, bars = load_collision(game, os.path.join(outdir, "collision-cache.pkl"))
    net = load_network(game)
    # nodes of road 149 (and the junction node it leaves from) are out
    nodes = [(n.pos[2], -n.pos[0], n.pos[1]) for n in net.nodes]
    excluded = set()
    for s in net.segments:
        if s.road == FINAL_CHASE_ROAD:
            excluded.update(s.nodes)
    road_of = {}
    for s in net.segments:
        if s.road >= 0:
            for n in s.nodes:
                road_of.setdefault(n, set()).add(s.road)
    # collision faces in 8 m cells: (z min, z max, count of non-terrain road faces)
    x0, y0 = -2400.0, -1800.0
    W, H = int(8400 / CELL), int(7800 / CELL)
    zmin = np.full((H, W), np.inf)
    zmax = np.full((H, W), -np.inf)
    road = np.zeros((H, W), dtype=np.int32)
    asphalt = 0x19DB2F1E
    for cx, cy, cz, h, sec in tris:
        i, j = int((cy - y0) / CELL), int((cx - x0) / CELL)
        if 0 <= i < H and 0 <= j < W:
            zmin[i, j] = min(zmin[i, j], cz)
            zmax[i, j] = max(zmax[i, j], cz)
            if h == asphalt:
                road[i, j] += 1

    def cells_near(px, py, r):
        out = []
        for i in range(int((py - r - y0) / CELL), int((py + r - y0) / CELL) + 1):
            for j in range(int((px - r - x0) / CELL), int((px + r - x0) / CELL) + 1):
                if 0 <= i < H and 0 <= j < W:
                    out.append((i, j))
        return out

    bar_cells = {}
    for k, b in enumerate(bars):
        for t in (0.0, 0.5, 1.0):
            px, py = b[0] + t * (b[2] - b[0]), b[1] + t * (b[3] - b[1])
            bar_cells.setdefault((int((py - y0) / 32), int((px - x0) / 32)), set()).add(k)
    edge = hull.boundary
    results = []
    for idx, (nx, ny, nz) in enumerate(nodes):
        if idx in excluded:
            continue
        p = Point(nx, ny)
        d_edge = edge.distance(p)
        if d_edge > 1500 or not hull.contains(p):
            continue
        q = edge.interpolate(edge.project(p))
        out_dir = math.atan2(q.y - ny, q.x - nx)
        best = None
        for dd in range(-40, 41, 10):
            a = out_dir + math.radians(dd)
            ux, uy = math.cos(a), math.sin(a)
            inside = None
            cross, lo, hi = 0, np.inf, -np.inf
            for step in range(1, int(2200 / CELL)):
                s = step * CELL
                px, py = nx + ux * s, ny + uy * s
                if inside is None and not hull.contains(Point(px, py)):
                    inside = s
                    break
                for (i, j) in cells_near(px, py, SIDE):
                    if s > NEAR and road[i, j]:
                        cross += 1
                    if np.isfinite(zmin[i, j]) and s > NEAR:
                        lo, hi = min(lo, zmin[i, j]), max(hi, zmax[i, j])
            if inside is None:
                continue
            walls = 0
            p0, p1 = (nx, ny), (nx + ux * WALL_NEAR, ny + uy * WALL_NEAR)
            seen = set()
            for t in range(0, int(WALL_NEAR) + 1, 16):
                key = (int((ny + uy * t - y0) / 32), int((nx + ux * t - x0) / 32))
                for k in bar_cells.get(key, ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    b = bars[k]
                    if seg_intersect(p0, p1, (b[0], b[1]), (b[2], b[3])) and b[5] > nz - 5:
                        walls += 1
            cand = dict(node=idx, render=[round(nx, 1), round(ny, 1), round(nz, 1)], heading=round(math.degrees(a), 1),
                        inside=round(inside, 0), crossings=cross, walls=walls,
                        relief=[None if not np.isfinite(lo) else round(lo - nz, 1),
                                None if not np.isfinite(hi) else round(hi - nz, 1)],
                        exit=[round(nx + ux * inside, 1), round(ny + uy * inside, 1)],
                        roads=sorted(road_of.get(idx, ())), segments=len(net.nodes[idx].segments))
            key = (cross > 0, inside)
            if best is None or key < best[0]:
                best = (key, cand)
        if best:
            results.append(best[1])

    def side(c):
        ex, ey = c["exit"]
        cx, cy = 1700.0, 1800.0  # the middle of Rockport's drivable extent
        a = math.degrees(math.atan2(ey - cy, ex - cx))
        return "east" if -45 <= a < 45 else "north" if 45 <= a < 135 else "south" if -135 <= a < -45 else "west"

    by_side = {}
    for c in results:
        c["side"] = side(c)
        by_side.setdefault(c["side"], []).append(c)
    summary = {}
    for sname, cs in sorted(by_side.items()):
        clean = sorted([c for c in cs if c["crossings"] == 0], key=lambda c: c["inside"])
        summary[sname] = clean[:8]
        print("%s: %d nodes with a line out, %d crossing no other road" % (sname, len(cs), len(clean)))
        for c in clean[:8]:
            print("  node %4d render (%7.1f, %7.1f, z %6.1f) heading %6.1f: %5.0f m inside, walls %d, relief %s, "
                  "exit (%.0f, %.0f), roads %s, %d segments" % (c["node"], *c["render"], c["heading"], c["inside"],
                                                               c["walls"], c["relief"], *c["exit"], c["roads"],
                                                               c["segments"]))
    with open(os.path.join(outdir, "connection-sites.json"), "w") as f:
        json.dump(dict(summary=summary, all=results), f, indent=1)
    # picture: 1 px = 5 m
    S = 0.2
    X0, Y0, X1, Y1 = -3000.0, -2200.0, 6200.0, 11800.0
    img = Image.new("RGB", (int((X1 - X0) * S), int((Y1 - Y0) * S)), (250, 250, 250))
    dr = ImageDraw.Draw(img)

    def P(x, y):
        return ((x - X0) * S, (Y1 - y) * S)

    for poly in drv:
        if poly.geom_type == "Polygon":
            dr.polygon([P(*xy) for xy in poly.exterior.coords], fill=(228, 234, 248), outline=(180, 190, 220))
    for cx, cy, cz, h, sec in tris[::3]:
        dr.point(P(cx, cy), fill=(60, 60, 60) if h == asphalt else (170, 170, 170))
    for s in net.segments:
        a, b = nodes[s.nodes[0]], nodes[s.nodes[1]]
        col = (220, 0, 160) if s.road == FINAL_CHASE_ROAD else (240, 140, 20)
        dr.line([P(a[0], a[1]), P(b[0], b[1])], fill=col, width=2 if s.road == FINAL_CHASE_ROAD else 1)
    colours = {"north": (0, 120, 200), "east": (0, 150, 60), "south": (150, 60, 200), "west": (200, 40, 40)}
    for sname, cs in summary.items():
        for rank, c in enumerate(cs[:3]):
            nx, ny, nz = c["render"]
            dr.line([P(nx, ny), P(*c["exit"])], fill=colours[sname], width=4 if rank == 0 else 2)
            dr.ellipse([P(nx, ny)[0] - 5, P(nx, ny)[1] - 5, P(nx, ny)[0] + 5, P(nx, ny)[1] + 5],
                       outline=colours[sname], width=2)
            dr.text((P(*c["exit"])[0] + 6, P(*c["exit"])[1] - 6),
                    "%s %d: node %d, %d m in Rockport" % (sname, rank + 1, c["node"], c["inside"]), fill=colours[sname])
    box = (629.6, 9504.1, 3370.4, 13495.9)
    dr.rectangle([P(box[0], box[3]), P(box[2], box[1])], outline=(0, 140, 70), width=3)
    dr.text((P(box[0], box[3])[0] + 6, P(box[0], box[3])[1] + 6), "F-Town today", fill=(0, 140, 70))
    gx = (-1664.0, 4928.0, -1088.0, 4800.0)
    dr.rectangle([P(gx[0], gx[3]), P(gx[1], gx[2])], outline=(200, 0, 0))
    dr.rectangle([P(gx[0], 13760.0), P(gx[1], gx[3])], outline=(250, 150, 150))
    dr.text((P(gx[0], 8000)[0] + 6, P(gx[0], 8000)[1]), "the widened grid (moving traffic): render y to 13,760",
            fill=(200, 80, 80))
    dr.text((10, img.size[1] - 20), "Candidate lines out of Rockport (not road 149, magenta). Blue fill: drivable "
            "sections; orange: road network; 1 km = 200 px", fill=(0, 0, 0))
    img.save(os.path.join(outdir, "connection-sites.png"))
    print("wrote", os.path.join(outdir, "connection-sites.png"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
