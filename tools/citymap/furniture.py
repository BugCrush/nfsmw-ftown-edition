"""F-Town's street furniture (render metres; docs/ftown-notes.md "Landmarks and street furniture"): dividers (medians)
between paired one-way carriageways, lamp posts and street lights on them, Mathura Road's yellow railing, traffic
signals at OSM's signal nodes, billboards behind the pavements of Mathura Road and the tertiary roads.

- A **pair** is two one-way ground carriageways of one name (or both unnamed and of one kind, links counted with their
  road), running opposite ways side by side (at most PAIR_GAP apart, edge to edge) for MIN_PAIR metres or more; the
  DND-KMP Expressway is left out (its crash walls stand between its carriageways, tools/citymap/landmark_build.py).
- A **median** is the ground between a pair's carriageways: their union closed by CLOSE metres, less every carriageway
  (ground and raised, so a two-way road's lanes are never split and a crossing road cuts the median), kept where at
  least MIN_WIDTH wide; raised MEDIAN_H with black-and-white kerb faces, its top grass (planted, the sector roads:
  photos 01, 22) or concrete under a yellow railing (Mathura Road, a trunk: photos 37, 40). Since the Run H fixes
  (docs/ftown-notes.md "Run H fixes (2026-11-04)", fault 3): a car climbs it as Rockport's kerbs (steps in the faces,
  no barrier: tools/citymap/rockport_kerbs.py), its top drawn and collided by the tiles (build_city.platforms: grass
  or concrete, an off-road feel on the planted ones); only the railing is a barrier (two-sided, RAIL_BARRIER tall,
  standing on the top). Run H's outline barrier (1.0 m) stopped the car like a wall.
- Lamp posts (photo 01) every LAMP_STEP on planted medians, street lights every LIGHT_STEP on Mathura Road's medians;
  a signal pole beside the road at each OSM signal node (the left side first, India drives on the left); billboards
  every BILLBOARD_STEP, BILLBOARD_BACK behind the pavement, alternate sides, where they touch no road, pavement,
  building, landmark or pier. Billboard posts are barriers. Since 2026-11-05 the lamps, street lights and signals are
  breakable poles (tools/citymap/breakables.py, Result.breakables): Rockport's own smackable street lights and signal
  masts (X0, by hash) on the main roads and at every signal, our lantern lamps on the sector roads; each its own
  instance (not baked, no barrier: the game's smackable trigger breaks it).
- Everything is baked into the tiles' ground solids (one mesh per texture a tile, not one instance per lamp: the
  ledger's Ruling R1), in the ground's near level only (dropped by the far level and the shadow and reflection views),
  medians in both levels.
"""
import math
import os
import sys
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import breakables  # noqa: E402
from tools.citymap import furniture_models as FM  # noqa: E402
from tools.citymap import evening  # noqa: E402
from tools.citymap import parts as P  # noqa: E402
from tools.citymap import surfaces, textures  # noqa: E402

PAIR_GAP = 8.0
MIN_PAIR = 40.0
CLOSE = 6.0
MIN_WIDTH = 0.4
MIN_AREA = 4.0
MEDIAN_H = 0.15  # as the pavements' rise (surfaces.PAVEMENT_RISE); Rockport's kerb steps: median 0.10, 2,713 of 10-25 cm
RAIL_BARRIER = 1.1  # the railing's height (furniture_models.railing_piece)
TWO_SIDED = 0x12
PIECE = 5.0
LAMP_STEP = 35.0
LIGHT_STEP = 40.0
RAIL_STEP = 2.5
BILLBOARD_STEP = 150.0
BILLBOARD_BACK = 3.0
BILLBOARD_APART = 60.0
SIGNAL_REACH = 25.0
SKIP_NAMES = {"DND-KMP Expressway"}
FURN_GREY = 72.0
EDGE_KEEP = 3.0


@dataclass
class Median:
    polygon: Polygon
    kind: str  # "railing" or "planted"
    pair: tuple
    lines: list = field(default_factory=list)  # centre lines (LineStrings) inside the median


@dataclass
class Result:
    parts: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    medians: list = field(default_factory=list)
    placed: list = field(default_factory=list)  # (model name, x, y, z, heading degrees)
    feet: list = field(default_factory=list)  # (model name, footprint Polygon) of every pole and post
    railing_m: float = 0.0
    signals: list = field(default_factory=list)  # (node (x, y), pole (x, y))
    breakables: list = field(default_factory=list)  # breakables.Breakable: the lamps, lights and signals

    def count(self, name):
        return sum(1 for p in self.placed if p[0] == name)


def _family(kind):
    return kind.replace("_link", "")


def _dir(line, s):
    a = line.interpolate(max(0.0, s - 1.0))
    b = line.interpolate(min(line.length, s + 1.0))
    dx, dy = b.x - a.x, b.y - a.y
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def pairs(model):
    """[(road a, road b)] (module doc)."""
    one = [r for r in model.roads if r.oneway and r.level == 0 and r.name not in SKIP_NAMES]
    lines = [LineString(r.points) for r in one]
    tree = shapely.STRtree(lines)
    out = []
    for i, ra in enumerate(one):
        la = lines[i]
        for j in tree.query(la.buffer(PAIR_GAP + 12.0)):
            if j <= i:
                continue
            rb, lb = one[j], lines[j]
            if ra.name != rb.name or (ra.name is None and _family(ra.kind) != _family(rb.kind)):
                continue
            ok = 0
            s = 0.0
            while s < la.length:
                p = la.interpolate(s)
                d = lb.distance(p)
                if d - ra.width_m / 2 - rb.width_m / 2 <= PAIR_GAP:
                    t = lb.project(p)
                    a, b = _dir(la, s), _dir(lb, t)
                    if a[0] * b[0] + a[1] * b[1] < -0.8:
                        ok += 1
                s += 5.0
            if ok * 5.0 >= MIN_PAIR:
                out.append((ra, rb))
    return out


def medians(model, L, inside=None):
    """[Median] (module doc), within `inside` when given."""
    lanes = shapely.union_all([L.ground_polygon, L.elevated])
    shapely.prepare(lanes)
    out = []
    for ra, rb in pairs(model):
        pa = surfaces.road_buffer(ra)
        pb = surfaces.road_buffer(rb)
        both = shapely.union_all([pa, pb])
        closed = both.buffer(CLOSE, quad_segs=4).buffer(-CLOSE, quad_segs=4)
        g = closed.difference(lanes)
        g = g.intersection(pa.buffer(PAIR_GAP)).intersection(pb.buffer(PAIR_GAP))
        if inside is not None:
            g = g.intersection(inside)
        kind = "railing" if _family(ra.kind) == "trunk" else "planted"
        for poly0 in surfaces._polys(g):
            # simplified, then cut by the lanes again (simplifying may cut a lane's corner by a few centimetres)
            for poly in surfaces._polys(Polygon(poly0.exterior).simplify(0.05).difference(lanes.buffer(0.02))):
                poly = Polygon(poly.exterior)
                if poly.area < MIN_AREA or poly.buffer(-MIN_WIDTH / 2).is_empty:
                    continue
                out.append(Median(orient(poly, 1.0), kind, (ra.id, rb.id)))
    # one median per spot (a road may pair with two pieces of its partner): the larger kept
    out.sort(key=lambda m: -m.polygon.area)
    kept = []
    for m in out:
        if all(m.polygon.intersection(k.polygon).area < 0.5 for k in kept):
            kept.append(m)
    for m in kept:
        m.lines = _centre_lines(m, model)
    return kept


def _centre_lines(m, model):
    """Lines inside the median half way between its pair's edges, every 2.5 m."""
    ra, rb = model.road(m.pair[0]), model.road(m.pair[1])
    la, lb = LineString(ra.points), LineString(rb.points)
    inner = m.polygon.buffer(-0.12)
    pts, runs = [], []
    s = 0.0
    while s <= la.length:
        p = la.interpolate(s)
        q = lb.interpolate(lb.project(p))
        d = p.distance(q)
        if d > 0.01:
            u = ((q.x - p.x) / d, (q.y - p.y) / d)
            k = ra.width_m / 2 + (d - ra.width_m / 2 - rb.width_m / 2) / 2
            c = (p.x + u[0] * k, p.y + u[1] * k)
            if inner.contains(Point(c)):
                if pts and math.dist(pts[-1], c) > RAIL_STEP * 1.6:
                    runs.append(pts)
                    pts = []
                pts.append(c)
            elif pts:
                runs.append(pts)
                pts = []
        s += RAIL_STEP
    if pts:
        runs.append(pts)
    return [LineString(r) for r in runs if len(r) >= 2]


def _cells(tris_cells):
    tris = [t for t, _c in tris_cells]
    uvs = [tuple([textures.furniture_uv(c)] * 3) for _t, c in tris_cells]
    return tris, uvs


SIGNAL_LIT = ("red", "green", "amber")  # the evening's lit lamp of signal k: SIGNAL_LIT[k % 3]


def _add_model(fur, model_tris, x, y, z, hd, signal=None):
    """The model placed into fur; for the evening (tools/citymap/evening.py) its lanterns carry the lamp class and,
    for signal number `signal`, both faces' lamp SIGNAL_LIT[signal % 3] its signal class."""
    placed = FM.place(model_tris, x, y, z, hd)
    tris, uvs = _cells(placed)
    lit_cell = SIGNAL_LIT[signal % 3] if signal is not None else None
    cols = []
    for t, (_t, cell) in zip(tris, placed):
        c = P.lit(t, FURN_GREY)
        if cell == "lantern":
            c = evening.glow(c, "lamp")
        elif cell == lit_cell:
            c = evening.glow(c, "sig_" + cell)
        cols.append(c)
    fur.add(tris, uvs, cols)


def _foot(x, y, hd, half_a, half_b):
    return Polygon(P.box(x, y, math.cos(hd), math.sin(hd), half_a, half_b, 0, 0))


def build(model, L, pav, details, proj, occupied, piers=(), outer=None):
    """Result (module doc). occupied: blocks, landmarks and stations (a billboard keeps off them); piers: rings of the
    metro's piers and legs (a light keeps 2 m off them); outer: the city's edge box (nothing is placed within
    EDGE_KEEP of it or outside: the city's tiles stop there)."""
    res = Result()
    inside = outer.buffer(-EDGE_KEEP) if outer is not None else None
    ps = P.PartSet("FURNITURE")
    fur = ps.get("furniture", "ground", ("A",))
    board = fur  # the billboards' faces are in the furniture atlas: one mesh a tile for all of it
    lanes = shapely.union_all([L.ground_polygon, L.elevated])
    lanes_clear = lanes.buffer(0.3)
    shapely.prepare(lanes_clear)
    pier_g = shapely.union_all([Polygon(r).buffer(2.0) for r in piers]) if piers else Polygon()
    shapely.prepare(pier_g)
    # medians
    res.medians = medians(model, L, inside)
    if inside is not None:  # signals and billboards: only feet inside (lamps stand on the medians, already inside)
        occupied = list(occupied) + [outer.difference(inside)]
    for m in res.medians:
        # the kerb faces round the median: tiles._kerbs, round the pavements and platforms together (Run H fixes)
        for line in m.lines:
            if m.kind == "railing":
                pts = list(line.coords)
                for a, b in zip(pts, pts[1:]):
                    hd = math.atan2(b[1] - a[1], b[0] - a[0])
                    piece = FM.railing_piece(math.dist(a, b))
                    _add_model(fur, piece, a[0], a[1], MEDIAN_H, hd)
                    res.railing_m += math.dist(a, b)
                    res.barriers.append((a, b, MEDIAN_H, MEDIAN_H + RAIL_BARRIER, TWO_SIDED))
                step, half = LIGHT_STEP, 0.13
            else:
                step, half = LAMP_STEP, 0.09
            # breakable poles (2026-11-05, tools/citymap/breakables.py): by the pair's road kind, Rockport's own street
            # light (X0, by hash; its arm over one carriageway, alternating) or our lantern lamp; each its own
            # instance with no barrier (the game's trigger breaks it)
            ka, kb = model.road(m.pair[0]).kind, model.road(m.pair[1]).kind
            role = breakables.median_role(ka, kb, m.kind == "railing")
            name = {"lantern": "lamp_sector", "light_c": "light_main", "light_cb": "light_trunk"}[role]
            s = step / 2
            k = 0
            while s < line.length:
                c = line.interpolate(s)
                t = _dir(line, s)
                hd = math.atan2(t[1], t[0])
                foot = _foot(c.x, c.y, hd, half, half)
                if not lanes_clear.intersects(foot) and not pier_g.intersects(foot):
                    mh = hd if role == "lantern" or k % 2 == 0 else hd + math.pi
                    res.breakables.append(breakables.Breakable(role, c.x, c.y, MEDIAN_H, mh, _family(ka)))
                    res.placed.append((name, c.x, c.y, MEDIAN_H, math.degrees(hd)))
                    res.feet.append((name, foot))
                    k += 1
                s += step
    # signals
    nodes = [proj.to_render(e["lat"], e["lon"]) for e in details["elements"]
             if e["type"] == "node" and e.get("tags", {}).get("highway") == "traffic_signals"]
    occ = shapely.union_all(list(occupied)) if occupied else Polygon()
    shapely.prepare(occ)
    roads = [(r, LineString(r.points)) for r in model.roads if r.kind != "service" and r.level == 0]
    for nx, ny in nodes:
        r, line = min(roads, key=lambda rl: rl[1].distance(Point(nx, ny)))
        s = line.project(Point(nx, ny))
        t = _dir(line, s)
        n = (-t[1], t[0])
        hd = math.atan2(t[1], t[0])
        spot = None
        for side in (1, -1):
            off = r.width_m / 2 + 0.8
            while off <= r.width_m / 2 + 12.0:
                x, y = nx + n[0] * side * off, ny + n[1] * side * off
                foot = _foot(x, y, hd, 0.2, 0.2)
                if not lanes_clear.intersects(foot) and not occ.intersects(foot):
                    spot = (x, y, foot)
                    break
                off += 0.5
            if spot:
                break
        if spot is None:
            continue
        x, y, foot = spot
        # breakable (2026-11-05): Rockport's signal mast (X0, by hash), its arm towards the signal's node over the road
        res.breakables.append(breakables.Breakable(breakables.signal_role(r.width_m), x, y, 0.0,
                                                   breakables.arm_heading(nx - x, ny - y), _family(r.kind)))
        res.placed.append(("signal", x, y, 0.0, math.degrees(hd)))
        res.feet.append(("signal", foot))
        res.signals.append(((nx, ny), (x, y)))
    # billboards
    pav_g = pav if pav is not None else Polygon()
    shapely.prepare(pav_g)
    boards = []
    k = 0
    for r in model.roads:
        if r.level != 0 or not (r.kind == "trunk" or r.kind == "tertiary") or r.name in SKIP_NAMES:
            continue
        line = LineString(r.points)
        s = BILLBOARD_STEP / 2
        while s < line.length:
            c = line.interpolate(s)
            t = _dir(line, s)
            n = (-t[1], t[0])
            side = 1 if k % 2 == 0 else -1
            base = math.atan2(t[1], t[0]) + (math.pi if side == 1 else 0.0)
            for extra in (0.0, 1.0, 2.0, 4.0):
                off = r.width_m / 2 + 2.5 + BILLBOARD_BACK + extra
                x, y = c.x + n[0] * side * off, c.y + n[1] * side * off
                foot = _foot(x, y, base, 5.2, 0.35)
                if lanes_clear.intersects(foot) or pav_g.intersects(foot) or occ.intersects(foot) or \
                        pier_g.intersects(foot) or any(math.dist((x, y), b) < BILLBOARD_APART for b in boards):
                    continue
                furn, face = FM.billboard(k % textures.BILLBOARDS)
                _add_model(fur, furn, x, y, 0.0, base)
                placed = FM.place(face, x, y, 0.0, base)
                tris = [t_ for t_, _uv in placed]
                board.add(tris, [uv for _t, uv in placed], [evening.glow(P.lit(t_, FURN_GREY), "board") for t_ in tris])
                for px in (-3.5, 3.5):
                    cx, cy = x + math.cos(base) * px, y + math.sin(base) * px
                    pf = _foot(cx, cy, base, 0.15, 0.15)
                    res.barriers += P.ring_barriers(list(pf.exterior.coords)[:-1], 0.0, 4.0)
                    res.feet.append(("billboard", pf))
                res.placed.append(("billboard", x, y, 0.0, math.degrees(base)))
                boards.append((x, y))
                break
            k += 1
            s += BILLBOARD_STEP
    res.parts += ps.all()
    return res
