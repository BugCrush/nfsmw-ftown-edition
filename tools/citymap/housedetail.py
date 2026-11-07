"""The lived-in detail of F-Town's ordinary buildings (own looks, docs/ftown-notes.md "Own looks and a lived-in city
(2026-11-04)"), after the photos of Sector 15/16 (05, 06, 08, 11, 13): stair-head rooms (mumty) and black water tanks
on the roofs, balconies on the road fronts of houses, hedges with bougainvillea on boundary walls. All of it in the
house atlas FTC_HOUSES (cells: tools/citymap/textures.py), in the buildings instance's near level only (parts.DETAIL:
the far level and the shadow and reflection views leave it out); none of it is solid (all above a car, or on a wall).

    build(blocks, lanes, boundary) -> Result(parts, mumties, tanks, balconies, hedges)

blocks: buildings.Block with their Style (buildings.styles: mumty, tank, balcony_edges); lanes: the carriageways and
pavements (a balcony keeps BALCONY_CLEAR off them); boundary: [(p, q)] boundary walls (buildings.boundary_walls).
"""
import math
import os
import random
import sys
from dataclasses import dataclass, field

import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import buildings as bmod  # noqa: E402
from tools.citymap import parts as P  # noqa: E402
from tools.citymap import textures  # noqa: E402

MUMTY_H = 2.6
TANK_H = 1.1
BALCONY_DEPTH = 0.9
BALCONY_W = 3.6
BALCONY_PARAPET = 1.0
BALCONY_SLAB = 0.15
BALCONY_CLEAR = 0.3
OVERHANG_Z = 4.5  # a balcony's underside may hang over a ground lane from here up (the city's 4.5 m rule for detail)
HEDGE_SHARE = 0.3
HEDGE_H = 0.45
HEDGE_HALF = 0.3


@dataclass
class Balcony:
    osm_id: int
    polygon: Polygon
    floors: int
    underside: float = 0.0  # the lowest balcony's underside above the ground


@dataclass
class Result:
    parts: list = field(default_factory=list)
    mumties: int = 0
    tanks: int = 0
    balconies: list = field(default_factory=list)
    hedges: int = 0


def _uvq(cell):
    """uvs of a quad [bottom left, bottom right, top right, top left] spanning a cell."""
    return [textures.house_cell_uv(cell, s, t) for s, t in ((0, 1), (1, 1), (1, 0), (0, 0))]


def _add(part, q, cell, want, grey, tint):
    tris, uvs = P.quad(q, _uvq(cell), want)
    part.add(tris, uvs, [P.lit(t, grey, tint) for t in tris])


def _box_faces(part, ring, z0, z1, cell_side, grey, tint, door_cell=None, door_dir=None, top_cell=None, sides=None):
    """Walls round a counter-clockwise ring from z0 to z1 (outward; only the edges in `sides` when given), a top when
    top_cell; the wall facing door_dir most nearly takes door_cell."""
    best = None
    if door_dir is not None:
        best = max(range(len(ring)), key=lambda k: (ring[(k + 1) % len(ring)][1] - ring[k][1]) * door_dir[0] -
                   (ring[(k + 1) % len(ring)][0] - ring[k][0]) * door_dir[1])
    for k, p in enumerate(ring):
        if sides is not None and k not in sides:
            continue
        q = ring[(k + 1) % len(ring)]
        L = math.dist(p, q) or 1.0
        out = ((q[1] - p[1]) / L, -(q[0] - p[0]) / L, 0.0)
        quad = [(p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)]
        _add(part, quad, door_cell if k == best else cell_side, out, grey, tint)
    if top_cell:  # a fan from the ring's first point (convex rings), facing up
        x0, y0 = min(p[0] for p in ring), min(p[1] for p in ring)
        span = max(max(p[0] for p in ring) - x0, max(p[1] for p in ring) - y0, 1e-6)
        for k in range(1, len(ring) - 1):
            p, q = ring[k], ring[k + 1]
            t = ((ring[0][0], ring[0][1], z1), (p[0], p[1], z1), (q[0], q[1], z1))
            uv = tuple(textures.house_cell_uv(top_cell, (v[0] - x0) / span, (v[1] - y0) / span) for v in t)
            part.add([t], [uv], [P.colour((grey * 0.95,) * 3)])


def _spots(fp, half, margin=0.4):
    """Centres of a half x half square in each corner of the footprint's rotated rectangle, inside the footprint
    (0.3 m in), its first axis (unit) and the footprint's centre."""
    r = fp.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    la, lb = math.hypot(*e0), math.hypot(*e1)
    if la < 1e-6 or lb < 1e-6:
        return [], (1.0, 0.0)
    a = (e0[0] / la, e0[1] / la)
    b = (-a[1], a[0])
    ctr = r.centroid
    inner = fp.buffer(-0.3)
    out = []
    for sa, sb in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        da, db = la / 2 - half - margin, lb / 2 - half - margin
        if da < 0 or db < 0:
            continue
        x, y = ctr.x + a[0] * da * sa + b[0] * db * sb, ctr.y + a[1] * da * sa + b[1] * db * sb
        sq = Polygon(P.box(x, y, a[0], a[1], half, half, 0, 0))
        if inner.contains(sq):
            out.append((x, y))
    return out, a


def roof(part, b, rng, res):
    """A mumty in a roof corner (its door towards the roof's middle) and a black hexagonal tank on it or in another
    corner."""
    st = b.style
    h = b.height_m
    fp = b.footprint
    side = rng.uniform(2.4, 3.0)
    spots, a = _spots(fp, side / 2)
    tank_at = None
    if st.mumty and spots:
        x, y = spots[0]
        ring = P.box(x, y, a[0], a[1], side / 2, side / 2, 0, 0)
        c = fp.centroid
        d = (c.x - x, c.y - y)
        # no roof drawn: never seen from a road (the flyover decks are 7 m up, a mumty's top 9 m or more)
        _box_faces(part, ring, h, h + MUMTY_H, "plain", 62.0, st.tint, "mumty", d)
        res.mumties += 1
        tank_at = (x, y, h + MUMTY_H)
    if st.tank:
        if tank_at is None:
            small, _a = _spots(fp, 0.8)
            if not small:
                return
            x, y = small[-1]
            tank_at = (x, y, h)
        r = rng.uniform(0.5, 0.65)
        x, y, z = tank_at
        ring = [(x + r * math.cos(math.pi * k / 3), y + r * math.sin(math.pi * k / 3)) for k in range(6)]
        _box_faces(part, ring, z, z + TANK_H, "tank", 40.0, (1, 1, 1))  # its lid is above every eye: not drawn
        res.tanks += 1


def balconies(part, b, rng, lanes_clear, tree, footprints, res):
    """A balcony on every upper storey of each road-facing edge in the style's balcony_edges: a slab and a 1 m
    parapet, BALCONY_DEPTH out, BALCONY_W wide (or the edge less 1 m), where its footprint is off every other
    building and off the raised roads (lanes_clear[1]); over a ground carriageway or pavement (lanes_clear[0]) only
    from OVERHANG_Z up (as the sector lanes' upper balconies hang over the lane: nothing a car meets)."""
    lanes_clear, raised_clear = lanes_clear
    st = b.style
    n = int(round(b.height_m / bmod.STOREY))
    if n < 2 or not st.balcony_edges:
        return
    pts = list(orient(b.footprint, 1.0).exterior.coords)
    for k, (p, q) in enumerate(zip(pts, pts[1:])):
        if k not in st.balcony_edges:
            continue
        L = math.dist(p, q)
        w = min(BALCONY_W, L - 1.0)
        if w < 2.0:
            continue
        d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
        nn = (d[1], -d[0])
        s0 = rng.uniform(0.5, L - 0.5 - w)
        a = (p[0] + d[0] * s0, p[1] + d[1] * s0)
        bb = (a[0] + d[0] * w, a[1] + d[1] * w)
        A = (a[0] + nn[0] * BALCONY_DEPTH, a[1] + nn[1] * BALCONY_DEPTH)
        B = (bb[0] + nn[0] * BALCONY_DEPTH, bb[1] + nn[1] * BALCONY_DEPTH)
        poly = Polygon([a, bb, B, A])
        if raised_clear is not None and raised_clear.intersects(poly):
            continue
        if any(footprints[j].intersection(poly).area > 0.01 for j in tree.query(poly)):
            continue
        over = lanes_clear.intersects(poly)
        floors = 0
        for s in range(1, n):
            z = bmod.STOREY * s
            zb, zt = z - BALCONY_SLAB, z + BALCONY_PARAPET
            if over and zb < OVERHANG_Z:
                continue
            floors += 1
            _add(part, [(A[0], A[1], zb), (B[0], B[1], zb), (B[0], B[1], zt), (A[0], A[1], zt)], "balcony",
                 (nn[0], nn[1], 0.0), 62.0, st.tint)
            _add(part, [(a[0], a[1], zb), (A[0], A[1], zb), (A[0], A[1], zt), (a[0], a[1], zt)], "balcony",
                 (-d[0], -d[1], 0.0), 62.0, st.tint)
            _add(part, [(B[0], B[1], zb), (bb[0], bb[1], zb), (bb[0], bb[1], zt), (B[0], B[1], zt)], "balcony",
                 (d[0], d[1], 0.0), 62.0, st.tint)
            _add(part, [(a[0], a[1], zb), (bb[0], bb[1], zb), (B[0], B[1], zb), (A[0], A[1], zb)], "slab",
                 (0.0, 0.0, -1.0), 52.0, (1, 1, 1))  # its underside (the floor is seen from above only: left out)
        if floors:
            low = bmod.STOREY * (n - floors) - BALCONY_SLAB
            res.balconies.append(Balcony(b.osm_id, poly, floors, low))


def hedges(segs, res):
    """[part] a hedge with bougainvillea on HEDGE_SHARE of the boundary wall pieces (drawn per piece of up to 20 m,
    build_city._boundary_parts' pieces), each anchored in the tile of its wall piece's first triangle."""
    from tools.citymap import build_city
    out = []
    for p, q in build_city._pieces(segs, 20.0):
        L = math.dist(p, q)
        if L < 3.0:
            continue
        if random.Random(int(p[0] * 10) * 100003 + int(p[1] * 10)).random() >= HEDGE_SHARE:
            continue
        d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
        a = (p[0] + d[0] * 0.3, p[1] + d[1] * 0.3)
        b = (q[0] - d[0] * 0.3, q[1] - d[1] * 0.3)
        ring = P.box((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d[0], d[1], (L - 0.6) / 2, HEDGE_HALF, 0, 0)
        part = _part(((p[0] + 2 * q[0]) / 3, (p[1] + 2 * q[1]) / 3))
        # drawn whole: its top (1.95 m up) is below the chase camera, a tall cab's eye and a car on a kerb (the own
        # looks' review), so its ends and top are seen
        _box_faces(part, ring, bmod.BOUNDARY_H, bmod.BOUNDARY_H + HEDGE_H, "hedge", 64.0, (1, 1, 1),
                   top_cell="hedge")
        out.append(part)
        res.hedges += 1
    return out


@dataclass
class AnchoredPart(P.Part):
    """A Part drawn whole in the tile of `anchor` (tiles.CityGeometry._extras), not triangle by triangle: a house's
    detail stays in its block's tile, so no tile gains a buildings instance for a balcony over its edge."""
    anchor: tuple = None


def _part(anchor):
    return AnchoredPart("build", "houses", levels=P.DETAIL, tag="HOUSES", anchor=anchor)


def build(blocks, lanes, boundary=(), seed=1, raised=None):
    """Result (module doc); one part per block (anchored at its representative point, the tile its walls are in).
    raised: the raised roads (flyover decks and ramps): no balcony over them at any height."""
    res = Result()
    lanes_clear = lanes.buffer(BALCONY_CLEAR)
    shapely.prepare(lanes_clear)
    raised_clear = raised.buffer(BALCONY_CLEAR) if raised is not None else None
    if raised_clear is not None:
        shapely.prepare(raised_clear)
    lanes_clear = (lanes_clear, raised_clear)
    footprints = [b.footprint for b in blocks]
    tree = shapely.STRtree(footprints)
    out = []
    for b in blocks:
        st = b.style
        if st is None:
            continue
        rp = b.footprint.representative_point()
        part = _part((rp.x, rp.y))
        rng = random.Random(seed * 104729 + b.osm_id)
        if b.kind == "house":
            roof(part, b, rng, res)
            balconies(part, b, rng, lanes_clear, tree, footprints, res)
        elif st.tank:
            roof(part, b, rng, res)
        if part.tris:
            out.append(part)
    out += hedges(boundary, res)
    res.parts = out
    return res
