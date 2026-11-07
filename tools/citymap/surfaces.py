"""F-Town's road surfaces at ground and deck level: polygons, triangles, pavements and lane markings (render metres,
x east, y north; heights are Task 3's and Task 5's).

- road_polygons(model): every road buffered by half its width (round caps and joins), unioned per level (0 ground,
  1 decks). Junctions join by construction: the roads meeting at a shared point overlap there and the union has no
  seam, no gap and no two faces over one spot (nothing to flicker).
- triangulate(polygon, max_edge): the polygon cut by a fixed 8 m grid (aligned to multiples of 8 m from the render
  origin, so tiles of 64 or 128 m cut along grid lines) and each piece triangulated (constrained Delaunay); vertices
  snapped to 0.1 mm so pieces that share an edge share its vertices exactly; triangles under 1 cm2 dropped. Every
  triangle is inside the polygon and counter-clockwise seen from above.
- pavements(model, polys): 2.5 m on each side of every tertiary-or-larger ground road (not the motorway: no walkers),
  outside every carriageway, PAVEMENT_RISE above the road.
- markings(model, polys): white lines 0.15 m wide, MARKING_RISE above the road: a dashed centre line on two-way
  tertiary-or-larger roads, dashed lane lines between the lanes of each carriageway with 2+ lanes a direction; kept off
  junctions (a disc of the widest meeting road's width round each shared point).
"""
import math
import os
import sys

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import roadmodel  # noqa: E402

PAVEMENT_WIDTH = 2.5
PAVEMENT_RISE = 0.15
PAVEMENT_KINDS = {"trunk", "primary", "secondary", "tertiary"}
MARKING_RISE = 0.02
MARKING_WIDTH = 0.15
DASH, GAP = 3.0, 4.5
MARKED_KINDS = {"motorway", "trunk", "primary", "secondary", "tertiary"}
SNAP = 1e-4
MIN_AREA = 1e-4  # 1 cm2
GRID_BASE = (0.0, 0.0)
QUAD_SEGS = 8


def _as_multi(g):
    if g.is_empty:
        return MultiPolygon()
    if g.geom_type == "Polygon":
        return MultiPolygon([g])
    if g.geom_type == "MultiPolygon":
        return g
    return MultiPolygon([p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"])


def road_buffer(r, extra=0.0):
    return LineString(r.points).buffer(r.width_m / 2 + extra, quad_segs=QUAD_SEGS)


def road_polygons(model, skip=()):
    """{level: MultiPolygon} of the roads of each level (0, 1); roads whose id is in `skip` are left out."""
    by = {0: [], 1: []}
    for r in model.roads:
        if r.id in skip:
            continue
        by[1 if r.level >= 1 else 0].append(road_buffer(r))
    return {k: _as_multi(shapely.union_all(v)) for k, v in by.items()}


def tri_area(t):
    (ax, ay), (bx, by), (cx, cy) = [p[:2] for p in t]
    return ((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / 2.0


def _cells(geom, max_edge):
    """The polygon cut into the pieces of a fixed grid of `max_edge` cells, by recursive halving (each step cuts the
    pieces of the step before, so a huge polygon is never intersected with many boxes)."""
    if geom.is_empty:
        return []
    x0, y0, x1, y1 = geom.bounds
    bx, by = GRID_BASE
    gx0 = bx + math.floor((x0 - bx) / max_edge) * max_edge
    gy0 = by + math.floor((y0 - by) / max_edge) * max_edge
    n = max(1, math.ceil(max(x1 - gx0, y1 - gy0) / max_edge))
    size = max_edge * (1 << max(0, math.ceil(math.log2(n))))
    items = [(geom, gx0, gy0, size)]
    while items and items[0][3] > max_edge + 1e-9:
        geoms, boxes, meta = [], [], []
        for g, x, y, s in items:
            h = s / 2
            for dx in (0, h):
                for dy in (0, h):
                    geoms.append(g)
                    boxes.append(box(x + dx, y + dy, x + dx + h, y + dy + h))
                    meta.append((x + dx, y + dy, h))
        parts = shapely.intersection(np.array(geoms, dtype=object), np.array(boxes, dtype=object))
        items = [(p, *mm) for p, mm in zip(parts, meta) if not p.is_empty and p.area > 0]
    return [g for g, _x, _y, _s in items]


def _polys(g):
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]


def triangulate(polygon, max_edge=8.0):
    """[((x, y), (x, y), (x, y))] counter-clockwise, covering the polygon (see the module's doc)."""
    pieces = []
    for c in _cells(polygon, max_edge):
        pieces += _polys(c)
    if not pieces:
        return []
    arr = shapely.set_precision(np.array(pieces, dtype=object), SNAP)
    cdt = shapely.constrained_delaunay_triangles(arr)
    out = []
    for coll in cdt:
        for t in getattr(coll, "geoms", []):
            c = list(t.exterior.coords)[:3]
            tri = tuple((round(x / SNAP) * SNAP, round(y / SNAP) * SNAP) for x, y in c)
            a = tri_area(tri)
            if abs(a) < MIN_AREA:
                continue
            out.append(tri if a > 0 else (tri[0], tri[2], tri[1]))
    return out


def pavements(model, polys, skip=()):
    """MultiPolygon of the pavements (see the module's doc)."""
    bufs = [road_buffer(r, PAVEMENT_WIDTH) for r in model.roads
            if r.kind in PAVEMENT_KINDS and r.level == 0 and r.id not in skip]
    if not bufs:
        return MultiPolygon()
    return _as_multi(shapely.union_all(bufs).difference(polys[0]))


def _dashes(line, dash=DASH, gap=GAP):
    out = []
    L = line.length
    s = gap / 2
    while s < L:
        e = min(L, s + dash)
        if e - s > 0.5:
            out.append(shapely.ops.substring(line, s, e))
        s += dash + gap
    return out


def markings(model, polys):
    """[(kind, polygon, road id)]: kind "centre" or "lane" (see the module's doc)."""
    import shapely.ops  # noqa: F401
    keep_off = []
    for k, n in model.junctions().items():
        w = max(model.road(i).width_m for i in set(n.road_ids))
        keep_off.append(Point(n.x, n.y).buffer(w, quad_segs=4))
    off = shapely.union_all(keep_off) if keep_off else Polygon()
    shapely.prepare(off)
    out = []
    for r in model.roads:
        if r.kind not in MARKED_KINDS or len(r.points) < 2:
            continue
        line = LineString(r.points)
        lines = []
        if not r.oneway:
            lines.append(("centre", line))
            per = r.lanes // 2
            for i in range(1, per):
                for side in (1, -1):
                    lines.append(("lane", line.offset_curve(side * i * roadmodel.LANE)))
        else:
            n = r.lanes
            for i in range(1, n):
                lines.append(("lane", line.offset_curve(-n * roadmodel.LANE / 2 + i * roadmodel.LANE)))
        own = road_buffer(r, -0.3)
        for kind, ln in lines:
            if ln.is_empty or ln.geom_type != "LineString":
                continue
            for d in _dashes(ln):
                p = d.buffer(MARKING_WIDTH / 2, cap_style="flat").intersection(own).difference(off)
                for q in _polys(p):
                    if q.area > 0.05:
                        out.append((kind, q, r.id))
    return out
