"""The road from Rockport to F-Town (docs/ftown-connection-research.md "The connection: decisions", C1-C7; plan
docs/superpowers/plans/2026-11-06-ftown-rockport-connection.md Task 2).

    .tools/cityenv/Scripts/python tools/citymap/connector.py            (after build_city.py: it reads the city)

writes ftown/ftown-connector.bun (our chunks: a texture pack, a solid list, scenery section Z1 = 2601, collision pack
2601), ftown/ftown-connect.bin (what FTownLoader needs at run time, below) and ftown/ftown-connector.json (numbers,
committed). The .bun and .bin are git-ignored (the .bin holds numbers read from the game's track file).

The road: from the centre of Rockport's T at render (883, 4548), z 202.7 (road 179 meets the north highway's upper
carriageway; Rockport's mouths 259, 260, 261), heading 70 degrees, a cubic (Hermite) curve to F-Town's south edge at
Mathura Road (the middle of its two carriageways and service roads at the edge box), heading 90 degrees. 16 m wide (two
lanes each way and shoulders); over its last 240 m it widens to the 52 m of Mathura Road at the edge. Level for 20 m
past Rockport's road edge, rising 0.25 % to 680 m (over the valley's rim), a cubic descent to F-Town's height, level
for the last 30 m. Drawn: the deck (asphalt, a dashed
centre line), concrete parapets 1 m tall whose outer faces run 40 m down (the embankment's walls), and beyond Rockport's
drivable sections a grass ground 150 m wide on each side. Collision: the deck (asphalt) from Rockport's road edge to the
city's; walls 64 m tall on both edges (two-sided, flags 0x12); walls closing what is left of the two walls the
connection opens (Rockport's north wall at the T, F-Town's edge pieces at Mathura Road).

ftown-connect.bin, version 2 (little-endian):
    'FTCN', u32 1
    f32 junction x, y, z (render); f32 on, off, near radii (m)
    f32 F-Town's edge box x0, y0, x1, y1
    u16 source zone (G3, 703: its list is copied), our zone (B26, 226), adjoin zone (G23, 723: shares our first two
        points), substitutes count, substitutes[2] (G26 726, G23 723)
    u16 source list count, extra count, our point count, wall count; u32 the connector file's size
    s16 the source zone's visible list as the game's file has it; s16 extra sections (F-Town's and Z1); pad to 4
    f32 our zone's points [x, y]
    walls {u16 pack (0: any of the city's packs), u16 barriers expected, f32 x0, y0, x1, y1 (render), f32 z low, high}
    u32 face region count; regions {u16 pack, u16 faces expected, f32 x0, y0, x1, y1 (the axis, render), f32 half
        (the reach from it), f32 z low, high}: Rockport's faces under the ramp, given flag 4 while the connection is on
        (a vertex or the centre within half of the axis, the centre within the heights; connector_ramp.in_region)

The ramp over Rockport's closure at the T (connector_ramp.py): the road's height follows the table's profile (Path.z),
the part over Rockport's road and the side wings are extra geometry (FTOWN_LINK_RAMP, collision flag 4).
"""
import hashlib
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, bstringhash, chunk_bytes, write_chunks  # noqa: E402
from world import collision_write, scenery_write, slab, solids, texpack  # noqa: E402
from world.collision import to_physics  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
ROADS = os.path.join(AREA, "ftown-roads.json")
CITY = os.path.join(REPO, "ftown", "ftown-city.bun")
CITY_JSON = os.path.join(REPO, "ftown", "ftown-city.json")
OUT_BUN = os.path.join(REPO, "ftown", "ftown-connector.bun")
OUT_BIN = os.path.join(REPO, "ftown", "ftown-connect.bin")
OUT_JSON = os.path.join(REPO, "ftown", "ftown-connector.json")

# Rockport's side (C1): the T, its height, the line's start, the wall the connection opens (pack 703, instance 6,
# barriers 4-8: the carriageway's north wall), Rockport's road edge on the line
JUNCTION = (883.0, 4548.0)
JUNCTION_Z = 202.7
START_HEADING = 70.0
END_HEADING = 90.0
ROCK_EDGE_S = 9.0  # Rockport's asphalt ends 9 m up the line (its wall stands at 10 m)
ROCK_WALL = ((872.70, 4562.32), (901.36, 4551.10))
ROCK_WALL_Z = (201.7, 265.7)
ROCK_WALL_PACK = 703
ROCK_WALL_BARRIERS = 5
ROCK_MOUTHS = (259, 260, 261)
# the zones (C3)
SOURCE_ZONE, OUR_ZONE, ADJOIN_ZONE, SUBSTITUTES = 703, 226, 723, (726, 723)
OUR_ZONE_GAP = 22.0  # our zone ends this far south of F-Town's edge box
ON_RADIUS, OFF_RADIUS, NEAR_RADIUS = 1500.0, 2500.0, 300.0
SECTION = 2601  # Z1: drawn from every Rockport zone and (sub-number 1 < 10) outside them
# the road
WIDTH = 16.0
LANES = 4
KIND = "motorway"  # roadnet_build: 80 km/h posted, cop lanes at the edges
WIDEN = 240.0
LEVEL_START = 20.0  # past Rockport's road edge
LEVEL_END = 30.0
HOLD_GRADE = -0.0025  # the first stretch's gentle rise (a fall when positive), to HOLD_END
HOLD_END = 680.0  # past Rockport's drawn ground in the valley: its far rim reaches 202.7 m at 660 m, then it ends
CENTRE_BAND = 10.0  # the line texture's 10 m tile, its dash down the middle
PARAPET_H, PARAPET_T = 1.0, 0.4
SKIRT = 40.0
WALL_TOP = 64.0
GROUND_W = 150.0
GROUND_DROP = 8.0  # the ground under the deck's level beyond Rockport, tapering to 0.3 m at F-Town's edge
STEP = 5.0
PIECE = 100.0  # metres of road per scenery instance (culled one by one)
HULL_Y = 5657.7  # G23's top edge (Rockport's drivable sections end there on the line)
TEXTURE_PACK_NAME = "FTOWN_LINK"
TEXTURE_PACK_FILE = "FTown\\FTownLink.tpk"
NAMES = {"asphalt": "FTOWN_LINK_ASPHALT", "line": "FTOWN_LINK_LINE", "concrete": "FTOWN_LINK_CONCRETE",
         "grass": "FTOWN_LINK_GRASS", "chevron": "FTOWN_LINK_CHEVRON"}
SIDES = {"asphalt": slab.GROUND_TEX, "line": slab.GROUND_TEX, "concrete": slab.TEX, "grass": slab.TEX,
         "chevron": slab.TEX}
EDGE_WALL_H = 3.0  # buildings.EDGE_HEIGHT


def _unit(a):
    return (math.cos(math.radians(a)), math.sin(math.radians(a)))


def city_info(path=CITY_JSON):
    with open(path) as f:
        return json.load(f)


def mathura_ends(model=None, box=None):
    """The roads crossing F-Town's south edge within 40 m of Mathura Road: [(road, x at the edge, width)] for the trunk
    carriageways and the secondary service roads beside them, and the apron (x left, x right) they span."""
    from tools.citymap import roadmodel
    model = model or roadmodel.RoadModel.load(ROADS)
    box = box or city_info()["edge_box"]
    y0 = box[1]
    found = []
    for r in model.roads:
        for a, b in zip(r.points, r.points[1:]):
            if (a[1] - y0) * (b[1] - y0) < 0:
                x = a[0] + (y0 - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
                found.append((r, x))
    trunks = [(r, x) for r, x in found if r.kind == "trunk" and r.name and r.name.startswith("Mathura Road")]
    if len(trunks) != 2:
        raise ValueError("Mathura Road's two carriageways not found at the edge (%d)" % len(trunks))
    mid = sum(x for _r, x in trunks) / 2
    near = [(r, x, r.width_m) for r, x in found if abs(x - mid) < 40.0 and r.kind in ("trunk", "secondary")]
    left = min(x - w / 2 for _r, x, w in near)
    right = max(x + w / 2 for _r, x, w in near)
    return near, (left, right), trunks


class Path:
    """The connector's centre line: a Hermite cubic from the junction to the apron's middle on F-Town's edge."""

    def __init__(self, end, end_z, apron_w, start=JUNCTION, start_z=JUNCTION_Z, headings=(START_HEADING, END_HEADING),
                 ramp=None):
        """(start, start_z, headings: the stand-in's test road, ftown/tests/make_test_link.py; ramp: the table over
        Rockport's closure at the T, connector_ramp.Ramp, its height added to the road's)"""
        self.p0, self.p1, self.start_z, self.ramp = tuple(start), end, start_z, ramp
        chord = math.dist(self.p0, self.p1)
        t0, t1 = _unit(headings[0]), _unit(headings[1])
        self.m0 = (t0[0] * chord, t0[1] * chord)
        self.m1 = (t1[0] * chord, t1[1] * chord)
        self.end_z, self.apron_w = end_z, apron_w
        n = 4000
        self._pts = [self._curve(i / n) for i in range(n + 1)]
        self._s = [0.0]
        for a, b in zip(self._pts, self._pts[1:]):
            self._s.append(self._s[-1] + math.dist(a, b))
        self.length = self._s[-1]

    def _curve(self, t):
        h00, h10, h01, h11 = 2 * t ** 3 - 3 * t * t + 1, t ** 3 - 2 * t * t + t, -2 * t ** 3 + 3 * t * t, t ** 3 - t * t
        return tuple(h00 * self.p0[k] + h10 * self.m0[k] + h01 * self.p1[k] + h11 * self.m1[k] for k in range(2))

    def _index(self, s):
        import bisect
        s = min(max(s, 0.0), self.length)
        i = max(1, min(len(self._s) - 1, bisect.bisect_left(self._s, s)))
        return i, s

    def at(self, s):
        i, s = self._index(s)
        a, b = self._pts[i - 1], self._pts[i]
        L = self._s[i] - self._s[i - 1]
        t = 0.0 if L <= 0 else (s - self._s[i - 1]) / L
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def tangent(self, s):
        i, _s = self._index(s)
        a, b = self._pts[i - 1], self._pts[i]
        L = math.dist(a, b) or 1.0
        return ((b[0] - a[0]) / L, (b[1] - a[1]) / L)

    def z(self, s):
        """The road's height (base_z) plus the ramp's over its table (s0 .. s3)."""
        h = self.base_z(s)
        if self.ramp is not None:
            h += self.ramp.z(s) - self.ramp.base_z
        return h

    def breaks(self, s0, s1):
        """The ramp's kinks (and the chevron bands' ends) strictly between s0 and s1: cuts of the deck's pieces."""
        if self.ramp is None:
            return []
        from tools.citymap import connector_ramp as cr
        r = self.ramp
        return [b for b in (r.s0, r.s1 - cr.CHEVRON, r.s1, r.s2, r.s2 + cr.CHEVRON, r.s3) if s0 < b < s1]

    def base_z(self, s):
        """Level to 20 m past Rockport's road edge, then up 0.25 % to HOLD_END (over the valley's far rim, whose drawn
        ground rises to 202.7 m at 660 m: test_drawn_surfaces_clear), then a cubic easing down to F-Town's height,
        level for the last 30 m."""
        a, b, c = ROCK_EDGE_S + LEVEL_START, HOLD_END, self.length - LEVEL_END
        if s <= a:
            return self.start_z
        if s <= b:
            return self.start_z - HOLD_GRADE * (s - a)
        if s >= c:
            return self.end_z
        z0, m0, L = self.start_z - HOLD_GRADE * (b - a), -HOLD_GRADE * (c - b), c - b
        t = (s - b) / L
        h00, h10, h01 = 2 * t ** 3 - 3 * t * t + 1, t ** 3 - 2 * t * t + t, -2 * t ** 3 + 3 * t * t
        return h00 * z0 + h10 * m0 + h01 * self.end_z

    def width(self, s):
        w0 = self.length - WIDEN
        if s <= w0:
            return WIDTH
        return WIDTH + (self.apron_w - WIDTH) * min(1.0, (s - w0) / WIDEN)

    def max_grade(self):
        """The steepest metre of the road (the ramp's table left out)."""
        return max(abs(self.base_z(s + 1.0) - self.base_z(s)) for s in range(0, int(self.length) - 1))


def end_height(end, city=CITY, city_json=CITY_JSON):
    from tools.citymap import roadnet_build
    return roadnet_build.city_heights(city, city_json)([end[0]], [end[1] + 1.0], [0])[0]


def path(info=None, ramp=True):
    from tools.citymap import connector_ramp as cr
    info = info or city_info()
    _near, (left, right), _t = mathura_ends(box=info["edge_box"])
    end = ((left + right) / 2, info["edge_box"][1])
    return Path(end, end_height(end), right - left, ramp=cr.Ramp() if ramp else None)


def _left(t):
    return (-t[1], t[0])


def cross_section(p, s):
    c, t = p.at(s), p.tangent(s)
    n = _left(t)
    return c, n, p.width(s) / 2, p.z(s)


# ---------------------------------------------------------------- the drawn geometry

def _quad(a, b, c, d):
    return [(a, b, c), (a, c, d)]


def _band_tris(p, s0, s1, lo, hi, z_of=None, up=True):
    """The deck's band between lateral offsets lo..hi (lo < hi, left positive... see below) from s0 to s1: triangles
    counter-clockwise seen from above (or below when up is False) and uvs (u along the band in tiles of 10 m across, v
    along s in 10 m)."""
    ca, na, _ha, za = cross_section(p, s0)
    cb, nb, _hb, zb = cross_section(p, s1)
    if z_of is not None:
        za, zb = z_of(s0), z_of(s1)
    lo_a, hi_a = lo(s0), hi(s0)
    lo_b, hi_b = lo(s1), hi(s1)
    A = (ca[0] + na[0] * lo_a, ca[1] + na[1] * lo_a, za)
    B = (cb[0] + nb[0] * lo_b, cb[1] + nb[1] * lo_b, zb)
    C = (cb[0] + nb[0] * hi_b, cb[1] + nb[1] * hi_b, zb)
    D = (ca[0] + na[0] * hi_a, ca[1] + na[1] * hi_a, za)
    # n is the left normal: lo (more negative = right) to hi (left); A B C D runs counter-clockwise from above
    uv = [((lo_a - lo_a) / 10.0, s0 / 10.0), ((lo_b - lo_a) / 10.0, s1 / 10.0), ((hi_b - lo_a) / 10.0, s1 / 10.0),
          ((hi_a - lo_a) / 10.0, s0 / 10.0)]
    tris = _quad(A, B, C, D) if up else _quad(A, D, C, B)
    uvs = [(uv[0], uv[1], uv[2]), (uv[0], uv[2], uv[3])] if up else [(uv[0], uv[3], uv[2]), (uv[0], uv[2], uv[1])]
    return tris, uvs


def _vertical(a, b, z0a, z1a, z0b, z1b, length_per_u=4.0):
    """A vertical quad from a to b (render x, y) facing the right of a -> b (its right-hand normal: the side the game
    draws, test_runh's convention)."""
    L = math.dist(a, b)
    A, B, C, D = (a[0], a[1], z0a), (b[0], b[1], z0b), (b[0], b[1], z1b), (a[0], a[1], z1a)
    u = L / length_per_u
    return _quad(A, B, C, D), [((0, 1), (u, 1), (u, 0)), ((0, 1), (u, 0), (0, 0))]


def drawn_piece(p, s0, s1, ground):
    """{kind: (triangles, uvs)} of the road between s0 and s1 (render coordinates)."""
    out = {k: ([], []) for k in NAMES}

    def add(kind, tu):
        out[kind][0].extend(tu[0])
        out[kind][1].extend(tu[1])

    half = p.width
    cut = sorted({s0, s1} | {s0 + k * STEP for k in range(1, int((s1 - s0) / STEP) + 1) if s0 + k * STEP < s1} |
                 set(p.breaks(s0, s1)))
    chev = None
    if p.ramp is not None:
        from tools.citymap import connector_ramp as cr
        chev = (p.ramp.s2, p.ramp.s2 + cr.CHEVRON)  # before the F-Town side's lip, seen from F-Town
    for a, b in zip(cut, cut[1:]):
        if chev and chev[0] - 1e-6 <= a and b <= chev[1] + 1e-6:
            add("chevron", _band_tris(p, a, b, lambda s: -half(s) / 2, lambda s: half(s) / 2))
        else:
            add("asphalt", _band_tris(p, a, b, lambda s: -half(s) / 2, lambda s: -CENTRE_BAND / 2))
            add("line", _band_tris(p, a, b, lambda s: -CENTRE_BAND / 2, lambda s: CENTRE_BAND / 2))
            add("asphalt", _band_tris(p, a, b, lambda s: CENTRE_BAND / 2, lambda s: half(s) / 2))
        for side in (1, -1):
            ca, na, ha, za = cross_section(p, a)
            cb, nb, hb, zb = cross_section(p, b)
            ia = (ca[0] + na[0] * ha * side, ca[1] + na[1] * ha * side)
            ib = (cb[0] + nb[0] * hb * side, cb[1] + nb[1] * hb * side)
            oa = (ca[0] + na[0] * (ha + PARAPET_T) * side, ca[1] + na[1] * (ha + PARAPET_T) * side)
            ob = (cb[0] + nb[0] * (hb + PARAPET_T) * side, cb[1] + nb[1] * (hb + PARAPET_T) * side)
            if side == 1:  # left edge: the inner face looks at the road (-d, the right of a -> b), the outer away
                add("concrete", _vertical(ia, ib, za, za + PARAPET_H, zb, zb + PARAPET_H))
                add("concrete", _vertical(ob, oa, zb - SKIRT, zb + PARAPET_H, za - SKIRT, za + PARAPET_H))
            else:
                add("concrete", _vertical(ib, ia, zb, zb + PARAPET_H, za, za + PARAPET_H))
                add("concrete", _vertical(oa, ob, za - SKIRT, za + PARAPET_H, zb - SKIRT, zb + PARAPET_H))
            top = [(ia[0], ia[1], za + PARAPET_H), (ib[0], ib[1], zb + PARAPET_H), (ob[0], ob[1], zb + PARAPET_H),
                   (oa[0], oa[1], za + PARAPET_H)]
            tris = _quad(*top) if side == 1 else _quad(top[0], top[3], top[2], top[1])
            add("concrete", (tris, [((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))]))
        if ground(a) and ground(b):
            gz = lambda s: p.z(s) - GROUND_DROP * min(1.0, max(0.0375, (p.length - s) / 200.0))  # noqa: E731
            add("grass", _band_tris(p, a, b, lambda s: -half(s) / 2 - PARAPET_T - GROUND_W,
                                    lambda s: -half(s) / 2 - PARAPET_T, gz))
            add("grass", _band_tris(p, a, b, lambda s: half(s) / 2 + PARAPET_T,
                                    lambda s: half(s) / 2 + PARAPET_T + GROUND_W, gz))
    return out


def _ramp_parts(p, road, body_end, drawn):
    """The ramp's part over Rockport's road (s0 .. body_end, |d| <= HALF), its wings over the carriageway (s0 ..
    WING_END, falling at WING_DEG to the road; `road`(x, y) the road's height there) and, when drawn, the wings' north
    ends and the body's sides beyond them (vertical, facing out). {kind: (triangles, uvs)} in render coordinates."""
    from tools.citymap import connector_ramp as cr
    r = p.ramp
    out = {"concrete": ([], []), "chevron": ([], [])}

    def P(s, d, z):
        q = cr._point(p, s, d)
        return (q[0], q[1], z)

    def quad(kind, s_a, s_b, lo, hi, z):
        A, B = P(s_a, lo, z(s_a, lo)), P(s_b, lo, z(s_b, lo))
        C, D = P(s_b, hi, z(s_b, hi)), P(s_a, hi, z(s_a, hi))
        uv = [(lo / 4.0, s_a / 4.0), (lo / 4.0, s_b / 4.0), (hi / 4.0, s_b / 4.0), (hi / 4.0, s_a / 4.0)]
        out[kind][0].extend(_quad(A, B, C, D))
        out[kind][1].extend([(uv[0], uv[1], uv[2]), (uv[0], uv[2], uv[3])])

    def rz(s, d):
        q = cr._point(p, s, d)
        return road(q[0], q[1])

    def wz(s, d):
        return max(r.surface(s, d), rz(s, d) + 0.03)

    def body_z(s, d):
        return p.z(s)

    cuts = sorted({r.s0, body_end} | {b for b in (r.s1 - cr.CHEVRON, r.s1, cr.WING_END) if r.s0 < b < body_end} |
                  {r.s0 + k for k in range(1, int(body_end - r.s0) + 1) if r.s0 + k < body_end})
    for a, b in zip(cuts, cuts[1:]):
        kind = "chevron" if a >= r.s1 - cr.CHEVRON - 1e-6 and b <= r.s1 + 1e-6 else "concrete"
        quad(kind, a, b, -cr.HALF, cr.HALF, body_z)
    wcuts = sorted({r.s0, cr.WING_END} | {b for b in (r.s1 - cr.CHEVRON, r.s1) if r.s0 < b < cr.WING_END} |
                   {r.s0 + k for k in range(1, int(cr.WING_END - r.s0) + 1) if r.s0 + k < cr.WING_END})
    reach = int(math.ceil(r.wing_reach(cr.WING_END))) + 2
    ds = [cr.HALF + k for k in range(0, reach - int(cr.HALF) + 1)]
    for a, b in zip(wcuts, wcuts[1:]):
        for di, dj in zip(ds, ds[1:]):
            for side in (1, -1):
                lo, hi = (di, dj) if side > 0 else (-dj, -di)
                if all(r.surface(s, d) <= rz(s, d) + 0.03 for s in (a, b) for d in (lo, hi)):
                    continue
                quad("concrete", a, b, lo, hi, wz)
    if drawn:
        e = cr.WING_END
        for di, dj in zip(ds, ds[1:]):
            for side in (1, -1):
                da, db = (di, dj) if side > 0 else (-dj, -di)  # walk towards +d: the face looks north (+s)
                za, zb = wz(e, da), wz(e, db)
                ra, rb = rz(e, da), rz(e, db)
                if za - ra < 0.05 and zb - rb < 0.05:
                    continue
                tu = _vertical(cr._point(p, e, da), cr._point(p, e, db), ra, za, rb, zb)
                out["concrete"][0].extend(tu[0])
                out["concrete"][1].extend(tu[1])
        scuts = sorted(set([c for c in cuts if c >= e] + [e]))
        for a, b in zip(scuts, scuts[1:]):
            for side in (1, -1):
                sa, sb = (b, a) if side > 0 else (a, b)  # left side walks -s (looks +d), right walks +s (looks -d)
                d = cr.HALF * side
                tu = _vertical(cr._point(p, sa, d), cr._point(p, sb, d), rz(sa, d), p.z(sa), rz(sb, d), p.z(sb))
                out["concrete"][0].extend(tu[0])
                out["concrete"][1].extend(tu[1])
    return out


def ramp_drawn(p, road):
    return _ramp_parts(p, road, ROCK_EDGE_S, True)


def ramp_faces(p, road):
    """The ramp's collision faces over Rockport (physics), all stacked (flag 4)."""
    parts = _ramp_parts(p, road, ROCK_EDGE_S - 1.0, False)
    return [tuple(to_physics(v) for v in t) for kind in parts for t in parts[kind][0]]


def beyond_rockport(p):
    """s -> True where the line is north of Rockport's drivable sections (G23's top edge)."""
    return lambda s: p.at(s)[1] > HULL_Y + 5.0


# ---------------------------------------------------------------- collision

def collision_faces(p, s0=ROCK_EDGE_S - 1.0):
    faces = []
    cut = [s0] + [s0 + k * STEP for k in range(1, int((p.length - s0) / STEP) + 1)] + [p.length]
    cut = sorted(set(min(c, p.length) for c in cut) | set(p.breaks(s0, p.length)))
    for a, b in zip(cut, cut[1:]):
        tris, _uv = _band_tris(p, a, b, lambda s: -p.width(s) / 2, lambda s: p.width(s) / 2)
        faces += [tuple(to_physics(v) for v in t) for t in tris]
    return faces


def _phys2(xy):
    P = to_physics((xy[0], xy[1], 0.0))
    return (P[0], P[2])


def _line_cross(a, b, c, d):
    """Where line a-b meets line c-d (render x, y)."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = a, b, c, d
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def edge_gap(info, apron):
    """F-Town's edge wall pieces (buildings.edge_barriers' south side) the apron crosses: (x0, x1) of the gap."""
    from shapely.geometry import box as sbox  # noqa: F401
    x0, y0, x1, _y1 = info["edge_box"]
    n = max(1, int(math.ceil((x1 - x0) / 50.0)))
    piece = (x1 - x0) / n
    k0 = int((apron[0] - x0) // piece)
    k1 = int((apron[1] - x0) // piece)
    return x0 + k0 * piece, x0 + (k1 + 1) * piece, k1 - k0 + 1


def barriers(p, info, apron, rock_wall=ROCK_WALL, rock_wall_z=ROCK_WALL_Z):
    """Physics barriers ((x, z), (x, z), bottom, top, flags)."""
    out = []
    s_lo = ROCK_EDGE_S + 1.0
    cut = [s_lo] + [s_lo + k * 10.0 for k in range(1, int((p.length - s_lo) / 10.0) + 1)] + [p.length]
    cut = sorted(set(min(c, p.length) for c in cut))
    for a, b in zip(cut, cut[1:]):
        for side in (1, -1):
            ca, na, ha, za = cross_section(p, a)
            cb, nb, hb, zb = cross_section(p, b)
            pa = (ca[0] + na[0] * ha * side, ca[1] + na[1] * ha * side)
            pb = (cb[0] + nb[0] * hb * side, cb[1] + nb[1] * hb * side)
            out.append((_phys2(pa), _phys2(pb), min(za, zb) - 2.0, max(za, zb) + WALL_TOP, 0x12))
    # Rockport's opened wall: its remainders either side of the deck, closed along the same line
    c, n, h, _z = cross_section(p, ROCK_EDGE_S + 1.0)
    t = p.tangent(ROCK_EDGE_S + 1.0)
    for side, end in ((1, rock_wall[0]), (-1, rock_wall[1])):
        e0 = (c[0] + n[0] * h * side, c[1] + n[1] * h * side)
        e1 = (e0[0] + t[0], e0[1] + t[1])
        meet = _line_cross(rock_wall[0], rock_wall[1], e0, e1)
        out.append((_phys2(end), _phys2(meet), rock_wall_z[0], rock_wall_z[1], 0x12))
    # F-Town's opened edge pieces: closed from the gap's ends to the apron's edges, on the edge line
    gx0, gx1, _k = edge_gap(info, apron)
    y0 = info["edge_box"][1]
    z = p.end_z
    for a, b in (((gx0, y0), (apron[0], y0)), ((apron[1], y0), (gx1, y0))):
        if abs(a[0] - b[0]) > 0.05:
            out.append((_phys2(a), _phys2(b), z - 1.0, z + EDGE_WALL_H, 0x12))
    return out


# ---------------------------------------------------------------- the file

def draw_textures():
    px = slab.draw_textures()
    import random
    rng = random.Random(20261106)
    n = slab.TEX
    grass = []
    for y in range(n):
        for x in range(n):
            v = rng.randint(-10, 10)
            grass.append((70 + v, 92 + v + rng.randint(-4, 4), 48 + v))
    chevron = []
    for y in range(n):
        for x in range(n):
            chevron.append((232, 186, 24) if ((x + y) // 16) % 2 else (24, 24, 24))
    return {"asphalt": px["asphalt"], "line": px["line"], "concrete": px["concrete"], "grass": grass,
            "chevron": chevron}


def texture_hashes():
    return {k: bstringhash(v) for k, v in NAMES.items()}


def face_flags(p, faces):
    """Flag 4 (stacked: the wheels look on for the closest face) on every deck face over the ramp's table."""
    if p.ramp is None:
        return None
    from tools.citymap import connector_ramp as cr
    from world.collision import to_render
    out = []
    for f in faces:
        r = [to_render(v) for v in f]
        s, _d = cr.to_sd(sum(v[0] for v in r) / 3, sum(v[1] for v in r) / 3)
        out.append(4 if s < p.ramp.s3 + 0.5 else 0)
    return out


def make_parts(p, info, apron, rock_wall=ROCK_WALL, rock_wall_z=ROCK_WALL_Z, road=None):
    px = draw_textures()
    texs = [texpack.new_texture(NAMES[k], SIDES[k], SIDES[k], px[k]) for k in NAMES]
    tpack = texpack.new_pack(TEXTURE_PACK_NAME, TEXTURE_PACK_FILE, texs)
    hashes = texture_hashes()
    ground = beyond_rockport(p)
    sols, models = [], []
    ident = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    s, k = ROCK_EDGE_S, 0
    while s < p.length - 0.01:
        e = min(p.length, s + PIECE)
        parts = drawn_piece(p, s, e, ground)
        groups = [(hashes[kind], NAMES[kind], tris, uvs, [solids.ROAD_COLOUR] * len(tris))
                  for kind, (tris, uvs) in parts.items() if tris]
        so = solids.make_solid_multi("FTOWN_LINK_%02d" % k, groups)
        sols.append(so)
        models.append((so.name[:23], (so.name_hash,) * 3 + (0,), ident))
        s, k = e, k + 1
    faces = collision_faces(p)
    flags = face_flags(p, faces)
    if p.ramp is not None:
        road = road or (lambda x, y: p.ramp.base_z)
        parts = ramp_drawn(p, road)
        groups = [(hashes[kind], NAMES[kind], tris, uvs, [solids.ROAD_COLOUR] * len(tris))
                  for kind, (tris, uvs) in parts.items() if tris]
        so = solids.make_solid_multi("FTOWN_LINK_RAMP", groups)
        sols.append(so)
        models.append((so.name[:23], (so.name_hash,) * 3 + (0,), ident))
        rf = ramp_faces(p, road)
        faces += rf
        flags += [4] * len(rf)
    slist = solids.new_list(sols, "FTown_Link.bin", "Z1")
    sc = scenery_write.make_section(SECTION, models, {so.name_hash: so for so in sols})
    pack = collision_write.make_pack(SECTION, faces, barriers(p, info, apron, rock_wall, rock_wall_z),
                                     face_flags=flags)
    return tpack, slist, sc, pack


def assemble(tpack, slist, sc, pack):
    out, pos = [], 0
    for kind, part in (("tex", tpack), ("solids", slist), ("scenery", sc), ("collision", pack)):
        gap = (-pos) % 128
        if gap:
            if gap < 8:
                gap += 128
            out.append(Chunk(0, bytes(gap - 8)))
            pos += gap
        c = {"tex": texpack.write_pack, "solids": solids.write_list, "scenery": scenery_write.write_section,
             "collision": collision_write.write_pack}[kind](part, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return out


def rockport_zones(l2ra=L2RA):
    from world import bun
    return bun.boundaries(l2ra), bun.drivable_sections(l2ra)


def our_zone_points(bounds, info):
    """B26's points: G23's top edge (its two points as the game's file has them), then north to OUR_ZONE_GAP short
    of F-Town's edge box."""
    g23 = bounds[ADJOIN_ZONE].points
    a = min(g23, key=lambda q: math.dist(q, (947.4, 5657.7)))
    b = min(g23, key=lambda q: math.dist(q, (1775.6, 5661.4)))
    top = info["edge_box"][1] - OUR_ZONE_GAP
    return [a, b, (b[0], top), (a[0], top)]


def connect_bytes(info, bounds, visible, bun_size, apron, end_z, faces=()):
    gx0, gx1, npieces = edge_gap(info, apron)
    y0 = info["edge_box"][1]
    walls = [(ROCK_WALL_PACK, ROCK_WALL_BARRIERS, ROCK_WALL[0][0], ROCK_WALL[0][1], ROCK_WALL[1][0], ROCK_WALL[1][1],
              ROCK_WALL_Z[0] - 0.5, ROCK_WALL_Z[1] + 0.5),
             (0, npieces, gx0, y0, gx1, y0, end_z - 3.0, end_z + 45.0)]  # the city's edge walls stand 40 m
    return pack_connect(JUNCTION + (JUNCTION_Z,), info["edge_box"], (SOURCE_ZONE, OUR_ZONE, ADJOIN_ZONE),
                        SUBSTITUTES, visible[SOURCE_ZONE], list(info["sections"]) + [SECTION],
                        our_zone_points(bounds, info), walls, bun_size, faces=faces)


def pack_connect(junction, box, zones, substitutes, source, extra, pts, walls, bun_size,
                 radii=(ON_RADIUS, OFF_RADIUS, NEAR_RADIUS), faces=()):
    """The FTCN bytes (the module's doc) from their parts."""
    out = struct.pack("<4sI3f3f4f", b"FTCN", 2, *junction, *radii, *box)
    out += struct.pack("<6H", *zones, len(substitutes), *substitutes)
    out += struct.pack("<4HI", len(source), len(extra), len(pts), len(walls), bun_size)
    out += struct.pack("<%dh" % len(source), *source) + struct.pack("<%dh" % len(extra), *extra)
    out += b"\0" * ((-len(out)) % 4)
    for q in pts:
        out += struct.pack("<2f", *q)
    for w in walls:
        out += struct.pack("<2H6f", *w)
    out += struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<2H7f", *f)
    return out


def read_connect(data):
    h = struct.unpack_from("<4sI3f3f4f", data, 0)
    o = struct.calcsize("<4sI3f3f4f")
    zones = struct.unpack_from("<6H", data, o)
    o += 12
    ns, ne, npt, nw, size = struct.unpack_from("<4HI", data, o)
    o += 12
    source = list(struct.unpack_from("<%dh" % ns, data, o))
    o += 2 * ns
    extra = list(struct.unpack_from("<%dh" % ne, data, o))
    o += 2 * ne
    o += (-o) % 4
    pts = [struct.unpack_from("<2f", data, o + 8 * i) for i in range(npt)]
    o += 8 * npt
    walls = [struct.unpack_from("<2H6f", data, o + 28 * i) for i in range(nw)]
    o += 28 * nw
    faces = []
    if h[1] >= 2:
        nf = struct.unpack_from("<I", data, o)[0]
        o += 4
        faces = [struct.unpack_from("<2H7f", data, o + 32 * i) for i in range(nf)]
        o += 32 * nf
    if o != len(data):
        raise ValueError("FTCN: %d bytes, %d read" % (len(data), o))
    return {"magic": h[0], "version": h[1], "junction": h[2:5], "radii": h[5:8], "box": h[8:12],
            "source_zone": zones[0], "our_zone": zones[1], "adjoin_zone": zones[2], "substitutes": zones[4:4 + zones[3]],
            "source": source, "extra": extra, "points": pts, "walls": walls, "bun_size": size, "faces": faces}


def network_road(p, info=None, inset=15.0):
    """The connector as a road for roadnet_build: centre line points (x, y, z) every 10 m from the junction to the
    apron's middle on the edge, then on to the middle of Mathura Road's two carriageways `inset` m inside the box
    (where roadnet_build clips them: the junction LINK_F, at the city's height there)."""
    info = info or city_info()
    box = list(info["edge_box"])
    _near, _apron, trunks = mathura_ends(box=box)
    _n2, _a2, inner = mathura_ends(box=[box[0], box[1] + inset, box[2], box[3]])
    n = max(2, int(p.length // 10.0))
    pts = [(*p.at(p.length * i / n), p.z(p.length * i / n)) for i in range(n + 1)]
    jf = (sum(x for _r, x in inner) / 2, box[1] + inset)
    pts.append((jf[0], jf[1], end_height(jf)))
    return {"points": pts, "width_m": WIDTH, "lanes": LANES, "kind": KIND, "start": "LINK_R", "end": "LINK_F",
            "carriageways": [r.id for r, _x in trunks]}


def build(out_bun=OUT_BUN, out_bin=OUT_BIN, out_json=OUT_JSON, l2ra=L2RA):
    info = city_info()
    _near, apron, _t = mathura_ends(box=info["edge_box"])
    p = path(info)
    from tools.citymap import connector_ramp as cr
    road = cr.road_height(GAME)
    data = write_chunks(assemble(*make_parts(p, info, apron, road=road)))
    with open(out_bun, "wb") as f:
        f.write(data)
    bounds, visible = rockport_zones(l2ra)
    region = cr.region(GAME, p.ramp)
    cb = connect_bytes(info, bounds, visible, len(data), apron, p.end_z, faces=[region])
    with open(out_bin, "wb") as f:
        f.write(cb)
    gx0, gx1, npieces = edge_gap(info, apron)
    summary = {
        "note": "F-Town's connection to Rockport (tools/citymap/connector.py); ftown-connector.bun and ftown-connect.bin "
                "are git-ignored",
        "connector": {"file": os.path.basename(out_bun), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                      "section": SECTION, "pack": SECTION},
        "connect": {"file": os.path.basename(out_bin), "bytes": len(cb), "sha256": hashlib.sha256(cb).hexdigest()},
        "length_m": round(p.length, 1), "start": list(JUNCTION) + [JUNCTION_Z],
        "end": [round(p.p1[0], 2), round(p.p1[1], 2), round(p.end_z, 2)], "max_grade_pct": round(100 * p.max_grade(), 2),
        "apron": [round(apron[0], 2), round(apron[1], 2)], "edge_gap": [round(gx0, 2), round(gx1, 2), npieces],
        "zones": {"source": SOURCE_ZONE, "ours": OUR_ZONE, "adjoin": ADJOIN_ZONE, "substitutes": list(SUBSTITUTES)},
        "radii": [ON_RADIUS, OFF_RADIUS, NEAR_RADIUS],
        "ramp": {"top_z": round(p.ramp.top_z, 2), "lip_deg": p.ramp.lip_deg, "back_deg": p.ramp.back_deg,
                 "s": [round(p.ramp.s0, 2), p.ramp.s1, p.ramp.s2, round(p.ramp.s3, 2)], "wing_deg": cr.WING_DEG,
                 "wing_end": cr.WING_END,
                 "faces_region": [round(x, 3) if isinstance(x, float) else x for x in region]},
    }
    with open(out_json, "w", encoding="ascii") as f:
        json.dump(summary, f, indent=1)
        f.write("\n")
    return summary


def main():
    print(json.dumps(build(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
