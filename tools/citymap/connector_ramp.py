"""The ramp over Rockport's closure at the connector's T (the user, 2026-11-06: "option B - build a ramp over the
barrier. but make it at such an angle that it gives me a good jump if im on speed"; plan
docs/superpowers/plans/2026-11-06-ftown-connector-ramp.md; notes docs/ftown-race-notes.md "The connector ramp").

Coordinates: s metres along the connector's centre line from the T's centre (render 883, 4548; negative s straight back
along the start heading, road 179's line), d metres to its left (render, z up). Read only on the game.

What stands at the opening (closure(), measured from the game's files):
  - pack 703 instance 6, barriers 4-8: Rockport's wall on the carriageway's north edge, z 201.7 .. 265.7, flags 0x02
    (single-sided, facing the road): the wall FTownLoader opens (surface flags | 0xC0) while the connection is on;
  - three smackables XS_MedianPole_1b (G43's 0x34027 records 28, 29, 31; attributes mediummetalpost: mass 250 kg,
    DETACH_FORCE 1), s 9.49..9.54, d +2.60, -0.58, -3.75, their collision volume B8FCC952's box from the road (202.59)
    to 204.85;
  - no collision face above the road and no collision object (OBB) there: the drawn concrete wall has no collision of
    its own.

The ramp ("table", symmetric): from the road (202.7) up at LIP_DEG to the flat top TOP_Z (the poles' 204.85 + 0.5) at
S1, flat to S2 (past the wall line at every d of the opening), down at LIP_DEG to the deck. 16 m wide (the opening and
the deck); over Rockport's carriageway it has side wings sloping at WING_DEG so the carriageway's traffic rolls over
it (the carriageway is one-way, two lanes, s -2.5 .. 9: the up-ramp covers all of it at the T).

The jump: a point launched at the lip at the lip angle, gravity g (the conservative case 9.81 m/s2: the game adds 3.0
m/s2 while no wheel touches and downforce 0.8 x 2 x AERO_COEFFICIENT x 1000 x v / mass, Chassis::DoJumpStabilizer and
DoAerodynamics, rigidbodyspecs GRAVITY -9.8128 for cars); the car's roof ROOF + HALF_LEN sin(lip) + MARGIN above it must
stay under the lowest drawn surface (the overpass deck "TRN_CT_PROPS_HIGHLANDS"; trees "XT_" are drawn only) over
|d| <= 8 all the way; it lands on the deck (northwards) or Rockport's road 179 (southwards).
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for _p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

JUNCTION = (883.0, 4548.0)
HEADING = 70.0
BASE_Z = 202.7
ROCK_WALL = ((872.70, 4562.32), (901.36, 4551.10))
POLE_S_MIN, POLE_S_MAX = 9.24, 9.78  # the three poles' boxes (centres s 9.49..9.54, half extent 0.26)
POLE_TOP = 204.85
TOP_Z = POLE_TOP + 0.5
LIP_DEG = 11.0  # the Rockport side: the jump towards F-Town
BACK_DEG = 7.0  # the F-Town side: the jump into Rockport (it must come down on road 179 before the road leaves the line)
S1, S2 = 9.0, 11.0
SOUTH_LAND_MIN = -205.0  # road 179's collision lies on the straight line back to s -212
HALF = 8.0  # the opening and the deck: 16 m
WING_DEG = 6.0
WING_END = 8.4  # the wings stop short of the carriageway's north wall (s 8.8 at d -32, 9.0 .. 10.1 nearer the middle)
CHEVRON = 1.0  # metres of yellow and black chevrons before each lip
REGION_Z = (202.0, 204.5)  # Rockport's faces flagged 4 under the ramp: the T's road, not the road 12 m below it
ROCK_FACES_END = 9.8  # Rockport's faces end before the wall line (s 9.6 at most)
ROOF, HALF_LEN, MARGIN = 1.5, 2.5, 0.5
CAR_HALF_W = 1.2
SPEEDS = tuple(range(80, 351, 10))
G_CLIMB = 9.81
CACHE = os.path.join(REPO, ".superpowers", "research", "connection", "ramp-study.json")
STUDY_S = (-350, 450)


def _u():
    return (math.cos(math.radians(HEADING)), math.sin(math.radians(HEADING)))


def straight(s, d=0.0):
    """Render (x, y) at (s, d) on the straight line from the T at the start heading."""
    u = _u()
    return (JUNCTION[0] + u[0] * s - u[1] * d, JUNCTION[1] + u[1] * s + u[0] * d)


def to_sd(x, y):
    u = _u()
    dx, dy = x - JUNCTION[0], y - JUNCTION[1]
    return dx * u[0] + dy * u[1], -dx * u[1] + dy * u[0]


def wall_s(d):
    """s where the line at offset d meets Rockport's wall line."""
    (ax, ay), (bx, by) = ROCK_WALL
    p0 = straight(0.0, d)
    u = _u()
    wx, wy = bx - ax, by - ay
    # cross(w, p0 + u s - a) = 0
    c0 = wx * (p0[1] - ay) - wy * (p0[0] - ax)
    c1 = wx * u[1] - wy * u[0]
    return -c0 / c1


class Ramp:
    def __init__(self, top_z=TOP_Z, lip_deg=LIP_DEG, s1=S1, s2=S2, base_z=BASE_Z, wing_deg=WING_DEG,
                 back_deg=BACK_DEG):
        self.top_z, self.lip_deg, self.back_deg, self.s1, self.s2, self.base_z = top_z, lip_deg, back_deg, s1, s2,             base_z
        self.height = top_z - base_z
        self.s0 = s1 - self.height / math.tan(math.radians(lip_deg))
        self.s3 = s2 + self.height / math.tan(math.radians(back_deg))
        self.wing = math.tan(math.radians(wing_deg))

    def z(self, s):
        """The table's surface on the centre line (|d| <= HALF)."""
        if s <= self.s0 or s >= self.s3:
            return self.base_z
        if s < self.s1:
            return self.base_z + self.height * (s - self.s0) / (self.s1 - self.s0)
        if s <= self.s2:
            return self.top_z
        return self.base_z + self.height * (self.s3 - s) / (self.s3 - self.s2)

    def surface(self, s, d):
        """With the wings: beyond |d| = HALF the surface falls at WING_DEG (on a flat road at base_z)."""
        h = self.z(s)
        if abs(d) <= HALF:
            return h
        return max(self.base_z, h - (abs(d) - HALF) * self.wing)

    def wing_reach(self, s):
        """|d| where the wing meets the flat road."""
        return HALF + (self.z(s) - self.base_z) / self.wing


# ---------------------------------------------------------------- Rockport's faces under the ramp (pack 703)

def rock_faces(game):
    """[(render vertices)] of every face of pack 703's instances the plugin scans (not turned or dynamic: flags & 3 =
    0), in the article order the game keeps them."""
    from world import bun, collision
    l2ra, stream = _game_paths(game)
    secs = {s.name: s for s in bun.sections(l2ra)}
    g43 = secs["G43"]
    out = []
    for p in collision.packs_in(bun.read_range(stream, g43.offset, g43.size), g43.offset):
        if p.section != 703:
            continue
        for inst in p.instances:
            art = p.articles.get(inst.article)
            if art is None or inst.flags & 3:
                continue
            for st in art.strips:
                w = [collision.to_render(inst.to_world(v)) for v in st.verts]
                for k in range(len(w) - 2):
                    out.append(tuple(w[k:k + 3]))
    return out


def road_height(game):
    """render (x, y) -> the T's road height there (the highest of pack 703's faces within REGION_Z), or BASE_Z."""
    g = _Grid([f for f in rock_faces(game) if REGION_Z[0] <= sum(v[2] for v in f) / 3 <= REGION_Z[1]], cell=4.0)

    def at(x, y):
        hs = [z for z in g.heights((x, y)) if REGION_Z[0] <= z <= REGION_Z[1]]
        return max(hs) if hs else BASE_Z
    return at


def footprint(ramp, s, d):
    return ramp.s0 <= s <= ROCK_FACES_END and abs(d) <= ramp.wing_reach(min(s, WING_END)) + 0.5


def rock_faces_under(game, ramp):
    """[(vertices, under)]: under = a vertex or the centre of the face within the ramp's footprint over Rockport."""
    out = []
    for f in rock_faces(game):
        c = tuple(sum(v[a] for v in f) / 3 for a in range(3))
        if not REGION_Z[0] <= c[2] <= REGION_Z[1]:
            continue
        under = any(footprint(ramp, *to_sd(q[0], q[1])) for q in list(f) + [c])
        out.append((f, under))
    return out


def _seg_dist(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L <= 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L))
    return math.hypot(a[0] + t * dx - q[0], a[1] + t * dy - q[1])


def in_region(f, verts):
    """The plugin's rule (FTownConnect.h ScanFaces): the face's centre within the region's z range, and a vertex or the
    centre within `half` of the region's axis. f = (pack, expect, x0, y0, x1, y1, half, z low, z high)."""
    c = tuple(sum(v[a] for v in verts) / 3 for a in range(3))
    if not f[7] <= c[2] <= f[8]:
        return False
    return any(_seg_dist(q, (f[2], f[3]), (f[4], f[5])) < f[6] for q in list(verts) + [c])


def region(game, ramp):
    """The face region for ftown-connect.bin: an axis across the carriageway (along d) through the middle of the
    footprint's s range, wide enough to hold the whole footprint, and the count of pack 703's faces in it."""
    s_lo, s_hi = ramp.s0 - 1.0, ROCK_FACES_END + 1.0
    sm = (s_lo + s_hi) / 2
    half = (s_hi - s_lo) / 2 + 1.0
    reach = ramp.wing_reach(WING_END) + 2.0
    a, b = straight(sm, -reach), straight(sm, reach)
    faces = rock_faces(game)
    for _ in range(20):  # no vertex within 1 cm of the edge (float32 in the plugin)
        f = (703, 0, a[0], a[1], b[0], b[1], half, REGION_Z[0], REGION_Z[1])
        edge = any(abs(_seg_dist(q, a, b) - half) < 0.01 for v in faces for q in list(v) +
                   [tuple(sum(x[k] for x in v) / 3 for k in range(3))])
        if not edge:
            break
        half += 0.05
    n = sum(1 for v in faces if in_region(f, v))
    return (703, n, a[0], a[1], b[0], b[1], half, REGION_Z[0], REGION_Z[1])


def region_count(game, f):
    return sum(1 for v in rock_faces(game) if in_region(f, v))


# ---------------------------------------------------------------- ballistics

def height_at(x, v, lip_deg, g):
    th = math.radians(lip_deg)
    c = math.cos(th)
    return x * math.tan(th) - g * x * x / (2.0 * v * v * c * c)


def peak(v, lip_deg, g):
    vz = v * math.sin(math.radians(lip_deg))
    return vz * vz / (2.0 * g)


def airborne_g(mass, aero, v):
    """The game's downward acceleration on a car in the air at speed v (m/s): gravity, the jump stabilizer's 3 m/s2 and
    the downforce at 80 % (ignoring the late landing boost, up to 10 m/s2 more within 6 m of the ground)."""
    return 9.8128 + 3.0 + 0.8 * 2.0 * aero * 1000.0 * v / mass


# ---------------------------------------------------------------- what the game has there (read only)

def _game_paths(game):
    return os.path.join(game, "TRACKS", "L2RA.BUN"), os.path.join(game, "TRACKS", "STREAML2RA.BUN")


def closure(game):
    """What collides at the opening: {barriers, smackables, faces_above_road, objects} (module doc)."""
    from vlthash import vlt32
    from world import bun, collision, scenery
    l2ra, stream = _game_paths(game)
    secs = {s.name: s for s in bun.sections(l2ra)}
    g43 = secs["G43"]
    chunks = bun.read_range(stream, g43.offset, g43.size)
    out = {"barriers": [], "smackables": [], "faces_above_road": 0, "objects": 0}
    for p in collision.packs_in(chunks, g43.offset):
        for n, inst in enumerate(p.instances):
            art = p.articles.get(inst.article)
            if art is None:
                continue
            for k, b in enumerate(art.barriers):
                a, c = collision.to_render(inst.to_world(b.p0)), collision.to_render(inst.to_world(b.p1))
                if all(bun.dist_to_segment(q[:2], *ROCK_WALL) < 0.6 for q in (a, c)):
                    out["barriers"].append({"pack": p.section, "instance": n, "index": k, "flags": b.surface_flags,
                                            "z": (min(a[2], c[2]), max(a[2], c[2]))})
    # every pack: faces above the road and objects at the opening
    for s in bun.sections(l2ra):
        for p in collision.packs_in(bun.read_range(stream, s.offset, s.size), s.offset):
            for a, b, c, _h, _n in collision.triangles(p):
                r = [collision.to_render(v) for v in (a, b, c)]
                cs, cd = to_sd(sum(v[0] for v in r) / 3, sum(v[1] for v in r) / 3)
                if 7.0 <= cs <= 12.0 and abs(cd) <= HALF and BASE_Z + 0.5 < sum(v[2] for v in r) / 3 < BASE_Z + 10:
                    out["faces_above_road"] += 1
            for o in p.objects:
                pos = collision.to_render(struct.unpack_from("<3f", o, 0))
                if math.dist(pos[:2], straight(10.0)) < 30.0:
                    out["objects"] += 1
    # smackables: G43's spawner records at the opening, their volume from L2RA's bounds
    names = {vlt32(a): a for a in ("mediummetalpost", "largemetalpost", "smallmetalpost", "trafficlight",
                                    "streetlight", "lightpost", "default")}
    top_chunks = bun.read_file(l2ra)
    for c, pos in scenery.with_positions(chunks, 0):
        if c.id != 0x34027:
            continue
        raw = c.data
        at = g43.offset + pos - 8
        start = ((at + 0x17) & ~0xF) - (at + 8)
        count = struct.unpack_from("<h", raw, start + 12)[0]
        for i in range(count):
            r = raw[start + 16 + 0x40 * i: start + 16 + 0x40 * (i + 1)]
            p = collision.to_render(struct.unpack_from("<3f", r, 0x10))
            model, coll, attr = struct.unpack_from("<3I", r, 0x20)
            s, d = to_sd(p[0], p[1])
            if not (7.0 <= s <= 12.0 and abs(d) <= HALF + 1):
                continue
            out["smackables"].append({"record": i, "render": p, "s": s, "d": d, "volume": "%08X" % coll,
                                      "attributes": names.get(attr, "%08X" % attr),
                                      "top": p[2] + volume_top(top_chunks, coll)})
    return out


def volume_top(top_chunks, name_hash):
    """The highest point of a collision volume (L2RA 0x8003B900 / 0x3B901, Physics/Bounds.h: header 16 bytes, Bounds
    0x30 each; vectors in 1/1000 m; model y up) above its origin, taking each box at its position or its pivot."""
    for c in top_chunks:
        if c.id != 0x8003B900:
            continue
        for k in c.children:
            d = k.data
            i = d.find(struct.pack("<I", name_hash))
            if i < 0 or (i % 4):
                continue
            n = struct.unpack_from("<i", d, i + 4)[0]
            top = 0.0
            for b in range(n):
                o = i + 16 + 0x30 * b
                pos = struct.unpack_from("<3h", d, o + 8)
                half = struct.unpack_from("<3h", d, o + 16)
                pivot = struct.unpack_from("<3h", d, o + 24)
                top = max(top, (max(pos[1], pivot[1]) + half[1]) / 1000.0)
            return top
    raise ValueError("no collision volume %08X" % name_hash)


def _point(p, s, d=0.0):
    if s < 0:
        return straight(s, d)
    c, t = p.at(s), p.tangent(s)
    return (c[0] - t[1] * d, c[1] + t[0] * d)


def _cover(tri, q):
    p0, p1, p2 = tri
    det = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
    if abs(det) < 1e-9:
        return None
    a = ((p1[1] - p2[1]) * (q[0] - p2[0]) + (p2[0] - p1[0]) * (q[1] - p2[1])) / det
    b = ((p2[1] - p0[1]) * (q[0] - p2[0]) + (p0[0] - p2[0]) * (q[1] - p2[1])) / det
    if min(a, b, 1 - a - b) < -1e-6:
        return None
    return a * p0[2] + b * p1[2] + (1 - a - b) * p2[2]


class _Grid:
    def __init__(self, tris, cell=8.0):
        self.cell, self.cells = cell, {}
        for t in tris:
            xs, ys = [v[0] for v in t], [v[1] for v in t]
            for i in range(int(math.floor(min(xs) / cell)), int(math.floor(max(xs) / cell)) + 1):
                for j in range(int(math.floor(min(ys) / cell)), int(math.floor(max(ys) / cell)) + 1):
                    self.cells.setdefault((i, j), []).append(t)

    def heights(self, q):
        out = []
        for t in self.cells.get((int(math.floor(q[0] / self.cell)), int(math.floor(q[1] / self.cell))), ()):
            z = _cover(t, q)
            if z is not None:
                out.append(z)
        return out


def study(game, p, cache=CACHE):
    """{"ceiling": [[s, lowest drawn surface 2.5 m or more over the road, over |d| <= 8, or None]], "ground": [[s,
    Rockport's collision face heights at d 0]] for s in STUDY_S every 1 m}, cached (delete the file to read again)."""
    if cache and os.path.exists(cache):
        with open(cache) as f:
            got = json.load(f)
        if got.get("version") == 2:
            return got
    from world import bun, collision, scenery, world
    l2ra, stream = _game_paths(game)
    bounds = bun.boundaries(l2ra)
    vis = bun.drivable_sections(l2ra)
    secs = {s.number: s for s in bun.sections(l2ra)}
    present = set(secs)
    rng = range(STUDY_S[0], STUDY_S[1] + 1)
    zones = set()
    for s in rng[::10]:
        q = _point(p, float(s))
        for n, b in bounds.items():
            if bun.is_drivable(n) and bun.point_in_poly(q, b.points):
                zones.add(n)
    wanted = set()
    for z in zones:
        wanted.update(vis.get(z, []))
    corridor = [_point(p, float(s), float(d)) for s in rng for d in (-HALF, 0.0, HALF)]
    xs, ys = [q[0] for q in corridor], [q[1] for q in corridor]
    box = (min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20)
    lib = world.library_solids(game)
    drawn = []
    for n in sorted(wanted):
        num = n if n in present else bun.combined_number(n, present)
        sec = secs.get(num)
        if sec is None:
            continue
        data = scenery.read_section(bun.read_range(stream, sec.offset, sec.size))
        for p0, p1, p2, _kind, sname in scenery.placed_triangles(data, lib, drivable_only=False):
            if sname.upper().startswith("XT_"):
                continue
            if max(p0[0], p1[0], p2[0]) < box[0] or min(p0[0], p1[0], p2[0]) > box[2] or \
                    max(p0[1], p1[1], p2[1]) < box[1] or min(p0[1], p1[1], p2[1]) > box[3]:
                continue
            drawn.append((tuple(p0), tuple(p1), tuple(p2)))
    faces = []
    for sec in bun.sections(l2ra):
        for pk in collision.packs_in(bun.read_range(stream, sec.offset, sec.size), sec.offset):
            for a, b, c, _h, _n in collision.triangles(pk):
                r = [collision.to_render(v) for v in (a, b, c)]
                if max(v[0] for v in r) < box[0] or min(v[0] for v in r) > box[2] or \
                        max(v[1] for v in r) < box[1] or min(v[1] for v in r) > box[3]:
                    continue
                faces.append(tuple(r))
    gd, gf = _Grid(drawn), _Grid(faces)
    ground = []
    for s in rng:
        ground.append([s, sorted(round(z, 3) for z in gf.heights(_point(p, float(s))))])
    ceiling = []
    for (s, hs) in ground:
        if s >= 0:
            ref = p.z(float(s))
        elif hs:
            ref = max(hs)
        else:
            ceiling.append([s, None])  # no road of Rockport's on the line: a flight must be down before
            continue
        low = None
        for d in (-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0):
            for z in gd.heights(_point(p, float(s), d)):
                if z > ref + 2.5 and (low is None or z < low):
                    low = z
        ceiling.append([s, None if low is None else round(low, 3)])
    got = {"version": 2, "ceiling": ceiling, "ground": ground, "zones": sorted(bun.section_name(z) for z in zones)}
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as f:
            json.dump(got, f)
    return got


# ---------------------------------------------------------------- the arc table

def _lateral(p, xy, s_guess):
    best = None
    for k in range(-40, 41):
        s = max(0.0, s_guess + k * 1.0)
        c = p.at(s)
        dd = math.dist(c, xy)
        if best is None or dd < best[0]:
            best = (dd, s)
    s = best[1]
    c, t = p.at(s), p.tangent(s)
    return s, -(xy[0] - c[0]) * t[1] + (xy[1] - c[1]) * t[0]


def flight(p, st, direction, v_kmh, g, lip_deg=None, ramp=None):
    """One jump off the lip facing `direction` (+1 north, at the ramp's lip_deg; -1 south, at its back_deg): {speed,
    v_lip, peak, clearance (least ceiling - roof over the flight; None: nothing above), land_s, land_d (northwards: off
    the deck's centre line), distance}. lip_deg overrides that side's angle."""
    if ramp is None:
        ramp = Ramp(**({} if lip_deg is None else ({"lip_deg": lip_deg} if direction > 0 else {"back_deg": lip_deg})))
    lip_deg = ramp.lip_deg if direction > 0 else ramp.back_deg
    ceil = {s: z for s, z in st["ceiling"]}
    ground = {s: hs for s, hs in st["ground"]}
    v = v_kmh / 3.6
    v_l = math.sqrt(max(1.0, v * v - 2.0 * G_CLIMB * ramp.height))
    s_l = ramp.s1 if direction > 0 else ramp.s2
    xy0 = _point(p, s_l)
    t = p.tangent(s_l)
    t = (t[0] * direction, t[1] * direction)
    pitch = HALF_LEN * math.sin(math.radians(lip_deg))
    clear = None
    land = None
    prev = ramp.top_z
    x = 0.0
    while x < 1500.0:
        x += 0.25
        z = ramp.top_z + height_at(x, v_l, lip_deg, g)
        s = s_l + direction * x
        si = int(round(s))
        c = ceil.get(si)
        if c is not None:
            room = c - (z + ROOF + pitch + MARGIN)
            clear = room if clear is None else min(clear, room)
        if direction > 0:
            if z <= max(p.z(s), ramp.z(s)):
                land = s
                break
        else:
            if s < STUDY_S[0]:
                break
            cands = list(ground.get(si, [])) + ([ramp.z(s)] if ramp.s0 <= s <= ramp.s3 else [])
            if any(z <= h <= z + 3.0 for h in cands):
                land = s
                break
        prev = z
    row = {"speed": v_kmh, "v_lip": round(v_l * 3.6, 1), "peak": round(peak(v_l, lip_deg, g), 2),
           "clearance": None if clear is None else round(clear, 2), "land_s": None if land is None else round(land, 1),
           "land_d": None, "distance": None if land is None else round(abs(land - s_l), 1)}
    if land is not None and direction > 0:
        xy = (xy0[0] + t[0] * (land - s_l), xy0[1] + t[1] * (land - s_l))
        _s, d = _lateral(p, xy, land)
        row["land_d"] = round(d, 2)
    return row


def arc_table(p, st, direction, g, speeds=SPEEDS, lip_deg=None):
    return [flight(p, st, direction, v, g, lip_deg) for v in speeds]


def _safe(row, direction):
    if row["clearance"] is not None and row["clearance"] <= 0.0:
        return False
    if direction < 0:
        return row["land_s"] is not None and row["land_s"] >= SOUTH_LAND_MIN
    return row["land_s"] is not None and abs(row["land_d"]) < HALF - CAR_HALF_W


def max_safe_angle(p, st, g, direction=1, speeds=SPEEDS, step=0.1):
    """The steepest lip on that side whose every jump in `speeds` clears the overpass and comes down where it should
    (north: on the deck between the parapets; south: on road 179 before it leaves the line)."""
    best = 0.0
    a = 2.0
    while a <= 30.0:
        ok = all(_safe(r, direction) for r in arc_table(p, st, direction, g, speeds, a))
        if not ok:
            break
        best = a
        a = round(a + step, 3)
    return best


def main():
    from tools.citymap import connector as cn
    p = cn.path()
    st = study(cn.GAME, p)
    print("max safe lip angle north (g 9.81): %.1f deg; chosen %.1f" % (max_safe_angle(p, st, 9.81, 1), LIP_DEG))
    print("max safe lip angle south (g 9.81): %.1f deg; chosen %.1f" % (max_safe_angle(p, st, 9.81, -1), BACK_DEG))
    for direction in (1, -1):
        print("north (to F-Town)" if direction > 0 else "south (into Rockport)")
        for r in arc_table(p, st, direction, 9.81):
            print("  ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
