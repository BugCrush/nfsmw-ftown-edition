"""Electricity poles and overhead wires along F-Town's residential lanes (own looks, docs/ftown-notes.md "Own looks
and a lived-in city (2026-11-04)"; photos 05, 06, 11, 13: concrete poles with cross-arms and sagging wires over
every sector lane).

    place(model, keep_off, inside) -> [(x, y, road id)]
    build(model, keep_off, inside, blocks) -> Result(poles, parts, barriers, spans, wire_tris, wire_lines)

- A pole every STEP (+- JITTER) metres along each residential or living-street ground road, on its left side (the
  way's direction) or else its right, OFFSET (or OFFSET_MIN) metres beyond the carriageway's edge; left out where its
  foot (FOOT radius) comes within
  CLEAR of keep_off (carriageways, raised roads, pavements, medians, buildings, boundary walls, furniture feet) or
  lies outside `inside` (the city's edge less 3 m).
- A pole: a tapered concrete shaft H tall (0.26 -> 0.16 m square), a cross-arm at ARM_Z across the road; three wires
  from its arm to the next pole's on the same road when SPAN_MAX or closer and the straight line between them crosses
  no building: each a horizontal ribbon of WIRE_W, sagging SAG at its middle, drawn from below.
- In the furniture atlas's solid cells (FTC_FURNITURE, as the lamp posts), in the ground instance's near level only
  (as the street furniture: the far level and the shadow and reflection views leave it out; the ground instance spans
  its whole tile, so no instance's radius or count grows): one part per pole anchored in its foot's tile
  (tiles.CityGeometry._extras), the wires cut at the tiles' edges. Each foot a ring of four outward barriers, H tall
  (a car stops at a pole; none stands in a lane).
"""
import math
import os
import sys
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import parts as P  # noqa: E402
from tools.citymap import textures  # noqa: E402
from tools.citymap.housedetail import AnchoredPart  # noqa: E402

KINDS = ("residential", "living_street")
STEP = 36.0
JITTER = 4.0
OFFSET = 1.0
OFFSET_MIN = 0.75  # CLEAR + FOOT + a little: the closest a pole stands to a carriageway
FOOT = 0.19  # the radius round the foot (a 0.26 m square: 0.184)
CLEAR = 0.5
H = 8.5
ARM_Z = 7.6
ARM_HALF = 0.7
WIRE_W = 0.04
SAG = 0.45
SPAN_MAX = 46.0
WIRE_PIECES = 3
POLE_CELL, WIRE_CELL = "lightgrey", "black"
TILE = 128.0  # tiles.TILE
ROUTE_KEEP = 8.0  # no pole this close to a race route's centre line (a slide at race speed: the own looks' review)


@dataclass
class Result:
    poles: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    spans: int = 0
    wire_tris: list = field(default_factory=list)
    wire_lines: list = field(default_factory=list)


def place(model, keep_off, inside):
    """[(x, y, road id, (ux, uy) the road's direction there)] (module doc)."""
    shapely.prepare(keep_off)
    out = []
    for r in model.roads:
        if r.kind not in KINDS or r.level != 0 or len(r.points) < 2:
            continue
        line = LineString(r.points)
        L = line.length
        s = STEP / 2 + (r.id % 7) * 1.3
        k = 0
        while s < L - 2.0:
            jit = ((r.id * 31 + k * 17) % 9 - 4) / 4.0 * JITTER
            sp = min(max(0.5, s + jit), L - 0.5)
            a, b = line.interpolate(max(0.0, sp - 0.5)), line.interpolate(min(L, sp + 0.5))
            dx, dy = b.x - a.x, b.y - a.y
            n = math.hypot(dx, dy) or 1.0
            u = (dx / n, dy / n)
            c = line.interpolate(sp)
            # the left side first, then the right; as close to the carriageway as CLEAR allows when the houses
            # stand close (sector lanes: the poles stand at the house fronts)
            for side, off in ((1, OFFSET), (1, OFFSET_MIN), (-1, OFFSET), (-1, OFFSET_MIN)):
                n_ = (-u[1] * side, u[0] * side)
                d = r.width_m / 2 + off
                x, y = c.x + n_[0] * d, c.y + n_[1] * d
                foot = Point(x, y).buffer(FOOT + CLEAR + 0.05, quad_segs=8)  # (a polygon inside the true circle)
                if inside.contains(Point(x, y)) and not keep_off.intersects(foot):
                    out.append((x, y, r.id, u))
                    break
            s += STEP
            k += 1
    return out


def _cell(cell):
    """The furniture atlas's solid colour cell: every uv on its centre (FTC_FURNITURE, textures.furniture_uv)."""
    return textures.furniture_uv(cell)


def _pole(part, x, y, u, res):
    v = (-u[1], u[0])  # across the road
    uv = _cell(POLE_CELL)
    lo = P.box(x, y, u[0], u[1], 0.13, 0.13, 0, 0)
    hi = P.box(x, y, u[0], u[1], 0.08, 0.08, 0, 0)
    for k in range(4):
        p0, q0, p1, q1 = lo[k], lo[(k + 1) % 4], hi[k], hi[(k + 1) % 4]
        L = math.dist(p0, q0)
        out = ((q0[1] - p0[1]) / L, -(q0[0] - p0[0]) / L, 0.0)
        quad = [(p0[0], p0[1], 0.0), (q0[0], q0[1], 0.0), (q1[0], q1[1], H), (p1[0], p1[1], H)]
        tris, uvs = P.quad(quad, [uv] * 4, out)
        part.add(tris, uvs, [P.lit(t, 66.0) for t in tris])
    arm = P.box(x, y, v[0], v[1], ARM_HALF, 0.05, 0, 0)
    # the cross-arm: its two long faces (along and against the road) only, 0.1 m tall
    for p, q in ((arm[0], arm[1]), (arm[2], arm[3])):
        L = math.dist(p, q)
        out = ((q[1] - p[1]) / L, -(q[0] - p[0]) / L, 0.0)
        tris, uvs = P.quad([(p[0], p[1], ARM_Z - 0.1), (q[0], q[1], ARM_Z - 0.1), (q[0], q[1], ARM_Z),
                            (p[0], p[1], ARM_Z)], [uv] * 4, out)
        part.add(tris, uvs, [P.lit(t, 58.0) for t in tris])
    res.barriers += P.ring_barriers(lo, 0.0, H)



def _split(p, q):
    """The 3D segment p -> q cut where it crosses a tile's edge (tiles.TILE lines in x and y): [(a, b)]."""
    ts = {0.0, 1.0}
    for i in (0, 1):
        lo, hi = sorted((p[i], q[i]))
        k = math.floor(lo / TILE) + 1
        while k * TILE < hi:
            ts.add((k * TILE - p[i]) / (q[i] - p[i]))
            k += 1
    ts = sorted(ts)
    pts = [tuple(p[j] + (q[j] - p[j]) * t for j in range(3)) for t in ts]
    return list(zip(pts, pts[1:]))


def _wire(part, a, b, za, zb, res):
    """A sagging horizontal ribbon from a to b (render x, y) at heights za, zb, WIRE_PIECES straight pieces of a
    parabola, cut at the tiles' edges (each piece then lies in one tile: no tile's radius grows), drawn from below."""
    L = math.dist(a, b)
    d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    s = (-d[1] * WIRE_W / 2, d[0] * WIRE_W / 2)
    pts = []
    for k in range(WIRE_PIECES + 1):
        t = k / WIRE_PIECES
        pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, za + (zb - za) * t - 4 * SAG * t * (1 - t)))
    uv = [_cell(WIRE_CELL)] * 4
    tris_all = []
    for p0, q0 in zip(pts, pts[1:]):
        for p, q in _split(p0, q0):
            if math.dist(p[:2], q[:2]) < 1e-3:
                continue
            quad = [(p[0] - s[0], p[1] - s[1], p[2]), (q[0] - s[0], q[1] - s[1], q[2]),
                    (q[0] + s[0], q[1] + s[1], q[2]), (p[0] + s[0], p[1] + s[1], p[2])]
            # seen from below (a car is always under them; a flyover deck is level with them at most)
            tris, uvs = P.quad(quad, uv, (0.0, 0.0, -1.0))
            part.add(tris, uvs, P.colour((40, 40, 40)))
            tris_all += tris
    res.wire_tris.append(tris_all)


def build(model, keep_off, inside, blocks=(), wire_keep=None):
    """Result (module doc). blocks: footprints a wire may not cross; wire_keep: what else stands in the wires' height
    (balconies, tall street furniture, landmarks, stations, the metro's piers and deck: the own looks' review)."""
    res = Result()
    found = place(model, keep_off, inside)
    stops = list(blocks) + ([wire_keep] if wire_keep is not None else [])
    bl = shapely.union_all(stops) if stops else shapely.Polygon()
    shapely.prepare(bl)
    wires = P.Part("ground", "furniture", levels=("A",), tag="WIRES")
    for k, (x, y, rid, u) in enumerate(found):
        part = AnchoredPart("ground", "furniture", levels=("A",), tag="POLES", anchor=(x, y))
        _pole(part, x, y, u, res)
        res.poles.append((x, y, rid))
        nxt = found[k + 1] if k + 1 < len(found) else None
        if nxt is not None and nxt[2] == rid and math.dist((x, y), nxt[:2]) <= SPAN_MAX:
            # the three wires run 0.55 m either side of the poles' line: the span's whole width must be clear
            if not bl.intersects(LineString([(x, y), nxt[:2]]).buffer(0.6, cap_style="flat")):
                v = (-u[1], u[0])
                vn = (-nxt[3][1], nxt[3][0])
                for off in (-0.55, 0.0, 0.55):
                    a = (x + v[0] * off, y + v[1] * off)
                    b = (nxt[0] + vn[0] * off, nxt[1] + vn[1] * off)
                    _wire(wires, a, b, ARM_Z, ARM_Z, res)
                res.spans += 1
                res.wire_lines.append(((x, y), nxt[:2]))
        res.parts.append(part)
    if wires.tris:
        res.parts.append(wires)
    return res
