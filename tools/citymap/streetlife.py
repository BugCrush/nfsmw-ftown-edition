"""F-Town's static street life (docs/ftown-notes.md "Street life (2026-11-04)"; plan
docs/superpowers/plans/2026-11-04-ftown-street-life.md): trees along the main roads and in the parks, shrubs on the
planted medians, benches, bus shelters and bins (Rockport's own X0 models, referenced by name hash: tools/citymap/
x0props.py), and parked vehicles (our own models, tools/citymap/vehicles.py) at the markets, the hospitals' fronts and
along the wide residential lanes. Nothing moves.

Rules (the plan's constraints):
- **Off the carriageways**: every footprint (a tree's trunk, a bush, bench, shelter or bin, a parked vehicle) at least
  LANE_CLEAR from every carriageway, ground or raised, and RAISED_CLEAR from the raised ones (nothing on or under the
  flyovers' decks and ramps), wholly on one surface (pavement, a median's top, or the ground: no footprint straddles a
  kerb), clear of buildings, landmarks, the metro's piers and stations, the furniture's feet, boundary walls and each
  other; trees keep TREE_VIADUCT from the metro's deck (their crowns would cross it).
- **Solid**: tree trunks (a TRUNK square ring, TRUNK_H tall) and bus shelters are small barriers facing out; bushes,
  benches, bins and the parked two-wheelers are not (Run I fixes, item 1: no parked cars are drawn; their places are
  parking bays for the real traffic cars).
- **Budget**: at most MAX_PER_TILE X0 instances a 128 m tile and MAX_PROPS in the city (so the city's instances stay
  under Rockport's largest loaded set, 3,449: tools/citymap/tests/test_city.py); placed by priority: shelters, benches
  and bins; the medians' shrubs; the parks; the roadside trees (near the route first). Since 2026-11-05 the
  breakable poles (tools/citymap/breakables.py: instances of their own) count in MAX_PROPS, their tiles and every
  view's budget as fixed instances (`fixed`), never thinned. Parked vehicles are one
  instance a tile (a solid of ours, one mesh of FTC_VEHICLES, at most VEHICLE_TRIS triangles; at most
  MAX_VEHICLE_TILES such tiles; each vehicle wholly inside its tile) whose solid's Density makes the game stop
  drawing it VEHICLE_DRAW from the tile's middle (its info radius stays its farthest vertex: the game's "behind" test
  reads it) (slots 1-3 empty, as the X0 instances: no far model, no shadow or reflection draws).
- **Deterministic**: every random choice from a generator seeded by the road, park or node id.
"""
import math
import os
import random
import sys
from dataclasses import dataclass, field

import shapely
import shapely.ops
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import parts as P  # noqa: E402
from tools.citymap import surfaces, vehicles, x0props  # noqa: E402
from tools.citymap.tiles import GROUND_Z  # noqa: E402

LANE_CLEAR = 1.0
RAISED_CLEAR = 3.0
TREE_VIADUCT = 6.0
TRUNK = 0.3  # half side of a trunk's square barrier ring
TRUNK_H = 4.0
SHELTER_H = 2.8
MAX_PROPS = 1950
# tiles with parked vehicles: each is one more instance (the vehicles' own, drawn VEHICLE_DRAW from its tile's middle);
# 1,409 tile instances + MAX_PROPS + MAX_VEHICLE_TILES = 3,439 < 3,449 (Rockport's largest loaded set)
MAX_VEHICLE_TILES = 80
VEHICLE_DRAW = 300.0
MAX_PER_TILE = 24
VEHICLE_TRIS = 1000  # (2,500 before Run I's fixes: with the cars gone the two-wheelers alone filled it, 553 of them)
TILE = 128.0
KERB = surfaces.PAVEMENT_RISE
MEDIAN_H = 0.15
TREE_ROADS = ("trunk", "secondary", "tertiary")
SKIP_NAMES = {"DND-KMP Expressway"}
TREE_STEP = (12.0, 20.0)  # m between roadside trees (the plan), jittered
# the gap a prop keeps from everything placed before it (a broad crown's from the trunk; the junipers' from their
# canopy, which is their footprint)
# Run I fixes, item 4: the three fall trees of one family in equal parts (x0props.PICKS), no junipers
TREES = ("tree_broad", "tree_fall_d", "tree_fall_s")
GAP = {"tree_broad": 6.0, "tree_fall_d": 6.0, "tree_fall_s": 6.0, "bush": 1.0}
ROAD_TREES = tuple((t, 1.0 / 3) for t in TREES)
PARK_TREES = ROAD_TREES
CANOPY = ()  # (the junipers' foliage reached the ground; a broad tree keeps its trunk off the lanes)
TREE_LEAN = 3.0  # degrees at most, each tree its own (seeded by its place)
ROUTE_NEAR = 150.0  # m: roadside trees this close to the route or a viewpoint are kept first
BUSH_STEP = 30.0
SHELTER_STEP = 700.0
PARK_STEP = 15.0
FURN_GREY = 72.0
PARK_PER_M2 = 1.0 / 900.0
PARK_CAP = 12
# at most this many of a kind (the rest of the budget goes to the trees)
ROLE_CAP = {"bin": 60, "bench": 60, "bush": 360, "shelter": 40}
VEHICLE_WEIGHTS = (("hatchback", 0.32), ("suv", 0.14), ("scooter", 0.20), ("motorbike", 0.14), ("auto", 0.12),
                   ("erickshaw", 0.08))
# Run I fixes, item 1 (docs/ftown-notes.md "Run I fixes: the city side"): the user found the low-poly cars, SUVs,
# autos and e-rickshaws "immovable wall like obstructions". Only the two-wheelers are still drawn, and they are not
# solid (a car brushes through a scooter at the kerb); where a car would have stood, a parking bay is recorded
# (Result.bays) for FTownLoader's real traffic cars (tools/citymap/traffic_spots.py).
DRAWN_VEHICLES = ("scooter", "motorbike")
BAY_KINDS = ("hatchback", "suv")
PARK_ROADS = ("tertiary", "secondary", "residential", "service", "unclassified", "living_street")


@dataclass
class Prop:
    role: str
    x: float
    y: float
    z: float  # above the ground (0, or 0.15 on a pavement or a median)
    heading: float  # radians
    scale: float
    lean: float = 0.0  # radians from the vertical (trees: Run I fixes, item 4)
    lean_dir: float = 0.0  # radians: the horizontal direction it leans to
    bars: list = field(default_factory=list)  # its barriers (a trunk's ring, a shelter's outline)


@dataclass
class Result:
    props: list = field(default_factory=list)
    vehicles: list = field(default_factory=list)  # (kind, variant, x, y, z, heading radians)
    bays: list = field(default_factory=list)  # (x, y, heading radians): where a parked car would stand (item 1)
    parts: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    thinned: dict = field(default_factory=dict)  # view name: props taken out to keep its budget
    on_median: int = 0  # trees, shelters, bins, benches and vehicles standing on a median (only shrubs may)


def _box_xy(role, scale):
    b = x0props.model(x0props.pick(role)["name"])["box"]
    return [(x * scale, y * scale) for x in (b[0], b[3]) for y in (b[1], b[4])]


def _turned(x, y, heading, scale, pts):
    c, s = math.cos(heading), math.sin(heading)
    return Polygon([(x + (px * c - py * s) * scale, y + (px * s + py * c) * scale) for px, py in pts])


def _box_foot(role, x, y, heading, scale):
    b = x0props.model(x0props.pick(role)["name"])["box"]
    return _turned(x, y, heading, scale, [(b[0], b[1]), (b[3], b[1]), (b[3], b[4]), (b[0], b[4])])


def base(role, x, y, heading, scale):
    """What a prop stands on (wholly on one surface) and what is solid: a tree's trunk ring; the others' boxes."""
    if role.startswith("tree"):
        return Polygon(P.box(x, y, 1.0, 0.0, TRUNK, TRUNK, 0, 0))
    return _box_foot(role, x, y, heading, scale)


def footprint(role, x, y, heading, scale):
    """A prop's footprint as the builder keeps it off the lanes and clear of everything (a broad tree's trunk, its
    crown high above the road; the others' boxes)."""
    if role in CANOPY:
        return _box_foot(role, x, y, heading, scale)
    return base(role, x, y, heading, scale)


def footprint_vehicle(x, y, heading, L, W):
    return _rect(x, y, heading, L, W)


def _rect(x, y, heading, L, W):
    return Polygon(P.box(x, y, math.cos(heading), math.sin(heading), L / 2, W / 2, 0, 0))


class Grid:
    """Placed footprints by 16 m cells, for the gaps between things."""

    def __init__(self):
        self.cells = {}

    def _keys(self, g, grow):
        x0, y0, x1, y1 = g.bounds
        for i in range(int(math.floor((x0 - grow) / 16)), int(math.floor((x1 + grow) / 16)) + 1):
            for j in range(int(math.floor((y0 - grow) / 16)), int(math.floor((y1 + grow) / 16)) + 1):
                yield i, j

    def clear(self, g, gap):
        for k in self._keys(g, gap):
            for h in self.cells.get(k, ()):
                if h.distance(g) < gap:
                    return False
        return True

    def add(self, g):
        for k in self._keys(g, 0.0):
            self.cells.setdefault(k, []).append(g)


class Place:
    def __init__(self, lanes, raised, pav, med, ground, blocked, viaduct, inside):
        self.near_lane = lanes.buffer(LANE_CLEAR, quad_segs=4)
        self.near_raised = raised.buffer(RAISED_CLEAR, quad_segs=4)
        self.pav, self.med, self.ground = pav, med, ground
        self.blocked = blocked
        self.viaduct = viaduct.buffer(TREE_VIADUCT) if viaduct is not None else Polygon()
        self.inside = inside
        for g in (self.near_lane, self.near_raised, pav, med, ground, blocked, self.viaduct, inside):
            shapely.prepare(g)
        self.grid = Grid()
        self.per_tile = {}
        # the breakable poles (tools/citymap/breakables.py, 2026-11-05): instances of their own placed before the
        # street life; they count in the city's total, their tiles and every view's budget, and are never thinned
        self.fixed = []
        self.roles = {}
        self.res = Result()
        self.vtris = {}
        self.vrad = {}  # tile: its vehicles' farthest vertex from the tile's middle (the FTV info's radius)
        self.vlist = []
        ps = P.PartSet("STREETLIFE")
        self.vpart = ps.get("vehicles", "veh", ("A",))
        self.ps = ps

    def surface(self, foot):
        """The foot's height above the ground (0, KERB, MEDIAN_H) if it lies wholly on one surface, else None."""
        if self.pav.contains(foot):
            return KERB
        if self.med.contains(foot):
            return MEDIAN_H
        if self.ground.contains(foot):
            return 0.0
        return None

    def free(self, foot, gap, tree=False):
        if not self.inside.contains(foot):
            return False
        if self.near_lane.intersects(foot) or self.near_raised.intersects(foot) or self.blocked.intersects(foot):
            return False
        if tree and self.viaduct.intersects(foot):
            return False
        return self.grid.clear(foot, gap)

    def full(self):
        return len(self.res.props) + len(self.fixed) >= MAX_PROPS

    def add_fixed(self, f):
        """A breakable pole: {"x", "y", "z", "radius", "tris", "meshes", "density"} (z above the ground)."""
        self.fixed.append(f)
        k = (math.floor(f["x"] / TILE), math.floor(f["y"] / TILE))
        self.per_tile[k] = self.per_tile.get(k, 0) + 1

    def tile_full(self, x, y):
        return self.per_tile.get((math.floor(x / TILE), math.floor(y / TILE)), 0) >= MAX_PER_TILE

    def prop(self, role, x, y, heading, scale):
        """Places an X0 prop if it fits (module doc); True when placed."""
        if self.full() or self.tile_full(x, y) or \
                self.roles.get(role, 0) >= ROLE_CAP.get(role, MAX_PROPS):
            return False
        foot = footprint(role, x, y, heading, scale)
        stand = base(role, x, y, heading, scale)
        tree = role.startswith("tree")
        if not self.free(foot, GAP.get(role, 0.3), tree):
            return False
        if role != "bush" and (self.med.intersects(foot) or self.med.intersects(stand)):
            return False  # only the shrubs stand on the medians (Mathura Road's carry a railing down the middle)
        z = self.surface(stand)
        if z is None:
            return False
        prop = Prop(role, x, y, z, heading, scale)
        if tree:
            lr = random.Random("lean:%.2f:%.2f" % (x, y))
            prop.lean = math.radians(lr.uniform(0.0, TREE_LEAN))
            prop.lean_dir = lr.uniform(0.0, 2 * math.pi)
        self.res.props.append(prop)
        self.roles[role] = self.roles.get(role, 0) + 1
        k = (math.floor(x / TILE), math.floor(y / TILE))
        self.per_tile[k] = self.per_tile.get(k, 0) + 1
        self.grid.add(foot)
        ring = list(orient(stand, 1.0).exterior.coords)[:-1]
        if tree:
            prop.bars = P.ring_barriers(ring, z, z + TRUNK_H)
        elif role == "shelter":
            prop.bars = P.ring_barriers(ring, z, z + SHELTER_H)
        return True

    def vehicle(self, kind, variant, x, y, heading):
        L, W, H = vehicles.size(kind)
        foot = _rect(x, y, heading, L, W)
        if not self.free(foot, 0.35) or self.med.intersects(foot):
            return False
        z = self.surface(foot)
        if z is None:
            return False
        if kind not in DRAWN_VEHICLES:
            # its place stays empty (item 1): nothing drawn or solid, kept free of the street life (so the two-wheelers
            # stay as many as before, not filling every gap); a car's is a parking bay for a real traffic car
            if kind in BAY_KINDS:
                self.res.bays.append((x, y, heading))
            self.grid.add(foot)
            return True
        k = (math.floor(x / TILE), math.floor(y / TILE))
        if any((math.floor(px / TILE), math.floor(py / TILE)) != k for px, py in foot.exterior.coords):
            return False  # wholly in its tile: the tile's FTV instance holds it whole (the review)
        n = len(vehicles.model(kind, variant))
        if self.vtris.get(k, 0) + n > VEHICLE_TRIS or (k not in self.vtris and len(self.vtris) >= MAX_VEHICLE_TILES):
            return False
        self.vtris[k] = self.vtris.get(k, 0) + n
        placed = vehicles.place(kind, variant, x, y, z, heading)
        tris = [t for t, _c in placed]
        cx, cy = (k[0] + 0.5) * TILE, (k[1] + 0.5) * TILE
        far = max(math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + p[2] ** 2) for t in tris for p in t)
        self.vrad[k] = max(self.vrad.get(k, 0.0), far)
        # kept apart until thin() has run (a view over its budget may take vehicles out too); finish() bakes them
        self.vlist.append({"rec": (kind, variant, x, y, z, heading), "tile": k, "n": n, "far": far,
                           "tris": tris, "uvs": [(vehicles.uv(c),) * 3 for _t, c in placed],
                           "cols": [P.lit(t, FURN_GREY) for t in tris],
                           "bars": []})  # two-wheelers are not solid (item 1)
        self.grid.add(foot)
        return True

    def drop_vehicle(self, v):
        self.vlist.remove(v)
        k = v["tile"]
        left = [w for w in self.vlist if w["tile"] == k]
        if left:
            self.vtris[k] = sum(w["n"] for w in left)
            self.vrad[k] = max(w["far"] for w in left)
        else:
            del self.vtris[k]
            del self.vrad[k]

    def finish(self):
        for v in self.vlist:
            self.vpart.add(v["tris"], v["uvs"], v["cols"])
            self.res.vehicles.append(v["rec"])
            self.res.barriers += v["bars"]


def _dir(line, s):
    a = line.interpolate(max(0.0, s - 1.0))
    b = line.interpolate(min(line.length, s + 1.0))
    d = math.hypot(b.x - a.x, b.y - a.y) or 1.0
    return (b.x - a.x) / d, (b.y - a.y) / d


def _choose(rng, weighted):
    r = rng.random()
    acc = 0.0
    for name, w in weighted:
        acc += w
        if r < acc:
            return name
    return weighted[-1][0]


def _scale(rng, role):
    lo, hi = x0props.pick(role)["scale"]
    return round(rng.uniform(lo, hi), 3)


def _osm_polys(proj, src, test):
    from tools.citymap import buildings
    out = []
    for e in (src or {}).get("elements", []):
        t = e.get("tags", {})
        if not test(t) or e["type"] != "way" or len(e.get("geometry", [])) < 4:
            continue
        if e["geometry"][0] != e["geometry"][-1]:
            continue
        g = buildings._clean(Polygon(buildings._ring(proj, e["geometry"])))
        if not g.is_empty:
            out.append((e["id"], g))
    return sorted(out, key=lambda ig: ig[0])


def build(model, L, pav, med, planted, ground, occupied, proj, areas, details, market_polys=(), hospitals=(),
          route=None, viewpoints=(), viaduct=None, inside=None, lamp_feet=(), budgets=None, view_model=None,
          fixed=()):
    """Result (module doc). fixed: the breakable poles (Place.add_fixed's dicts), counted in the city's total, their
    tiles and every view's budget, never thinned. pav: the pavements (less the medians); med: the medians' tops; planted: the planted
    medians' tops (the shrubs' places); ground: the ground's
    polygons (grass and earth, as the tiles draw them); occupied: what nothing may stand on (buildings, landmarks,
    stations, piers, boundary walls...); market_polys and hospitals: polygons whose fronts get parked vehicles; route:
    the first route's points; viewpoints: (x, y) whose surroundings get their trees first; viaduct: the metro deck's
    footprint; inside: the city's edge box less its margin; lamp_feet: polygons of the medians' poles; viewpoints:
    the draw budget's views ({"name", "x", "y", "z", "heading"}); budgets: {view name: (instances, meshes,
    triangles)} the street life may add there; view_model: (H, field of view)."""
    lanes = shapely.union_all([L.ground_polygon, L.elevated])
    blocked = shapely.union_all(list(occupied) + [f.buffer(0.5) for f in lamp_feet])
    pl = Place(lanes, L.elevated, pav, med, ground, blocked, viaduct, inside if inside is not None else
               shapely.box(-1e7, -1e7, 1e7, 1e7))
    for f in fixed:
        pl.add_fixed(f)
    roads = sorted([r for r in model.roads if r.level == 0], key=lambda r: str(r.id))
    _shelters_benches_bins(pl, roads, proj, details, market_polys)
    first, rest = _roadside_candidates(roads, route, viewpoints)
    _place_trees(pl, first)
    _median_bushes(pl, planted)
    _parks(pl, proj, areas)
    _place_trees(pl, rest)
    _vehicles(pl, roads, market_polys, hospitals)
    res = pl.res
    if budgets and view_model:
        res.thinned = thin(pl, viewpoints, budgets, view_model)
    pl.finish()
    for p in res.props:
        res.barriers += p.bars
    res.on_median = sum(1 for p in res.props if p.role != "bush" and
                        med.intersects(base(p.role, p.x, p.y, p.heading, p.scale))) + \
        sum(1 for k, _v, x, y, _z, hd in res.vehicles if med.intersects(_rect(x, y, hd, *vehicles.size(k)[:2])))
    res.parts = pl.ps.all()
    c = {}
    for p in res.props:
        c[p.role] = c.get(p.role, 0) + 1
    for v in res.vehicles:
        c["vehicle_" + v[0]] = c.get("vehicle_" + v[0], 0) + 1
    res.counts = dict(sorted(c.items()))
    return res


def _beside(pl, role, r, line, s, side, rng, offs, along=True):
    """Tries to place a prop beside road r at s on one side (offsets from the road's edge); heading along the road
    (or facing it)."""
    c = line.interpolate(s)
    t = _dir(line, s)
    n = (-t[1], t[0])
    hd = math.atan2(t[1], t[0]) if along else math.atan2(-n[1] * side, -n[0] * side)
    for off in offs:
        d = r.width_m / 2 + off
        if pl.prop(role, c.x + n[0] * side * d, c.y + n[1] * side * d, hd, _scale(rng, role)):
            return True
    return False


def _shelters_benches_bins(pl, roads, proj, details, market_polys):
    els = details.get("elements", []) if details else []
    stops = []
    for e in els:
        t = e.get("tags", {})
        if e["type"] == "node" and t.get("public_transport") in ("stop_position", "platform") or \
                t.get("highway") == "bus_stop":
            stops.append((e["id"], proj.to_render(e["lat"], e["lon"])))
        elif e["type"] == "way" and t.get("amenity") == "shelter" and e.get("geometry"):
            pts = [proj.to_render(p["lat"], p["lon"]) for p in e["geometry"]]
            stops.append((e["id"], (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))))
    main = [r for r in roads if r.kind in ("trunk", "secondary", "tertiary") and r.name not in SKIP_NAMES]
    lines = [(r, LineString(r.points)) for r in main]
    offs = [LANE_CLEAR + 1.5 + k * 0.5 for k in range(10)]
    for sid, (x, y) in sorted(stops):
        rng = random.Random("stop:%s" % sid)
        r, line = min(lines, key=lambda rl: rl[1].distance(Point(x, y)))
        if line.distance(Point(x, y)) > 40.0:
            continue
        s = line.project(Point(x, y))
        side = 1 if ((x - line.interpolate(s).x) * -_dir(line, s)[1] + (y - line.interpolate(s).y) *
                     _dir(line, s)[0]) >= 0 else -1
        if _beside(pl, "shelter", r, line, s, side, rng, offs):
            _beside(pl, "bin", r, line, s + 4.5, side, rng, offs[:4])
    # shelters along the trunk and secondary roads, one side then the other
    k = 0
    for r, line in lines:
        if r.kind not in ("trunk", "secondary"):
            continue
        rng = random.Random("shelters:%s" % r.id)
        s = SHELTER_STEP / 2
        while s < line.length:
            side = 1 if k % 2 == 0 else -1
            for ds in (0.0, 15.0, -15.0, 30.0, -30.0):
                if 0 < s + ds < line.length and _beside(pl, "shelter", r, line, s + ds, side, rng, offs):
                    _beside(pl, "bin", r, line, s + ds + 4.5, side, rng, offs[:4])
                    break
            k += 1
            s += SHELTER_STEP
    # OSM's benches: at the node or the nearest free spot within 6 m, facing the nearest road
    for e in sorted(els, key=lambda e: e["id"]):
        if e["type"] != "node" or e.get("tags", {}).get("amenity") != "bench":
            continue
        x, y = proj.to_render(e["lat"], e["lon"])
        rng = random.Random("bench:%s" % e["id"])
        r, line = min([(r, LineString(r.points)) for r in roads], key=lambda rl: rl[1].distance(Point(x, y)))
        q = line.interpolate(line.project(Point(x, y)))
        hd = math.atan2(q.y - y, q.x - x)
        for k in range(12):
            a = k * math.pi / 6
            d = 0.0 if k == 0 else 3.0 + (k % 3)
            if pl.prop("bench", x + d * math.cos(a), y + d * math.sin(a), hd, 1.0):
                break
    # bins along the market roads every 40 m
    if market_polys:
        mk = shapely.union_all(list(market_polys)).buffer(20.0)
        shapely.prepare(mk)
        for r in roads:
            line = LineString(r.points)
            if not mk.intersects(line) or r.kind in ("trunk",):
                continue
            rng = random.Random("bins:%s" % r.id)
            s = 10.0
            side = 1
            while s < line.length:
                if mk.contains(line.interpolate(s)):
                    _beside(pl, "bin", r, line, s, side, rng, offs[:6], along=False)
                    side = -side
                s += 80.0


def _median_bushes(pl, med):
    """Shrubs on the planted medians every BUSH_STEP along their middle (only where the median is wide enough to keep
    them LANE_CLEAR off both carriageways)."""
    if med is None or med.is_empty:
        return
    parts = [g for g in getattr(med, "geoms", [med]) if g.area > 20.0]
    for k, g in enumerate(sorted(parts, key=lambda g: (round(g.centroid.x, 1), round(g.centroid.y, 1)))):
        rng = random.Random("median:%d" % k)
        core = g.buffer(-0.2)
        if core.is_empty:
            continue
        # the median's long axis: its minimum rotated rectangle's longer side
        rect = list(g.minimum_rotated_rectangle.exterior.coords)
        e0, e1 = math.dist(rect[0], rect[1]), math.dist(rect[1], rect[2])
        a, b = (rect[0], rect[1]) if e0 >= e1 else (rect[1], rect[2])
        if max(e0, e1) < BUSH_STEP:
            continue
        axis = LineString([a, b])
        s = rng.uniform(4.0, BUSH_STEP)
        while s < axis.length:
            c = axis.interpolate(s)
            # the point of the median nearest the axis point (medians bend)
            p = shapely.ops.nearest_points(core, c)[0]
            hd = rng.uniform(0, 2 * math.pi)
            pl.prop("bush", p.x, p.y, hd, _scale(rng, "bush"))
            s += BUSH_STEP


def _parks(pl, proj, areas):
    """Trees on a jittered PARK_STEP grid inside every OSM park (at most one a PARK_PER_M2), a few shrubs along its edge
    and a bench (with a bin) by its edge."""
    parks = _osm_polys(proj, areas, lambda t: t.get("leisure") in ("park", "garden"))
    for pid, g in parks:
        rng = random.Random("park:%s" % pid)
        inner = g.buffer(-2.5)
        if inner.is_empty:
            continue
        x0, y0, x1, y1 = inner.bounds
        cap = min(PARK_CAP, max(2, int(g.area * PARK_PER_M2)))
        pts = []
        y = y0 + rng.uniform(0, PARK_STEP)
        while y < y1:
            x = x0 + rng.uniform(0, PARK_STEP)
            while x < x1:
                pts.append((x + rng.uniform(-3, 3), y + rng.uniform(-3, 3)))
                x += PARK_STEP
            y += PARK_STEP
        rng.shuffle(pts)
        n = 0
        for x, y in pts:
            if n >= cap:
                break
            if inner.contains(Point(x, y)):
                role = _choose(rng, PARK_TREES)
                n += pl.prop(role, x, y, rng.uniform(0, 2 * math.pi), _scale(rng, role))
        edge = g.buffer(-1.8).exterior if g.buffer(-1.8).geom_type == "Polygon" else None
        if edge is None:
            continue
        s, nb = rng.uniform(0, 12.0), 0
        while s < edge.length and nb < 4:
            c = edge.interpolate(s)
            nb += pl.prop("bush", c.x, c.y, rng.uniform(0, 2 * math.pi), _scale(rng, "bush"))
            s += 14.0
        if g.area > 2000.0:
            ring = g.buffer(-3.5)
            if ring.geom_type == "Polygon" and not ring.is_empty:
                ln = ring.exterior
                for f in (0.13,):
                    c = ln.interpolate(f * ln.length)
                    q = g.centroid
                    hd = math.atan2(q.y - c.y, q.x - c.x)
                    if pl.prop("bench", c.x, c.y, hd, 1.0):
                        pl.prop("bin", c.x + 2.0 * math.cos(hd + math.pi / 2), c.y + 2.0 * math.sin(hd + math.pi / 2),
                                hd, 1.0)


def _roadside_candidates(roads, route, viewpoints):
    """Tree places every TREE_STEP along the main roads, both sides: (those near the route or a viewpoint, the rest in
    a seeded random order)."""
    near = []
    if route:
        near.append(LineString(route).buffer(ROUTE_NEAR))
    near += [Point(v["x"], v["y"]).buffer(ROUTE_NEAR * 2) for v in viewpoints]
    near_g = shapely.union_all(near) if near else Polygon()
    shapely.prepare(near_g)
    first, rest = [], []
    for r in roads:
        if r.kind not in TREE_ROADS or r.name in SKIP_NAMES:
            continue
        line = LineString(r.points)
        rng = random.Random("trees:%s" % r.id)
        s = rng.uniform(3.0, TREE_STEP[1])
        while s < line.length - 2.0:
            for side in (1, -1):
                role = _choose(rng, ROAD_TREES)
                cand = (r, line, s, side, role, rng.random(), _scale(rng, role), rng.uniform(0, 2 * math.pi))
                (first if near_g.contains(line.interpolate(s)) else rest).append(cand)
            s += rng.uniform(*TREE_STEP)
    rest.sort(key=lambda c: c[5])
    return first, rest


def _place_trees(pl, cands):
    """Each candidate on the verge (the pavement beyond the kerb's LANE_CLEAR, or the ground behind it), the first
    offset that fits."""
    offs = [LANE_CLEAR + TRUNK + 0.25 + k * 0.6 for k in range(10)]
    for r, line, s, side, role, _key, scale, hd in cands:
        if pl.full():
            break
        c = line.interpolate(s)
        t = _dir(line, s)
        n = (-t[1], t[0])
        for off in offs:
            d = r.width_m / 2 + off
            if pl.prop(role, c.x + n[0] * side * d, c.y + n[1] * side * d, hd, scale):
                break


def _vehicles(pl, roads, market_polys, hospitals):
    """Parked vehicles in bays beside the carriageway (LANE_CLEAR off it): nose-in rows at the markets and the
    hospitals' fronts (autos and e-rickshaws alongside), a few parallel along the wide residential lanes."""
    zones = [g.buffer(25.0) for g in market_polys] + [g.buffer(40.0) for g in hospitals]
    zone = shapely.union_all(zones) if zones else Polygon()
    shapely.prepare(zone)
    for r in roads:
        if r.kind not in PARK_ROADS:
            continue
        line = LineString(r.points)
        wide = r.kind in ("residential", "living_street") and r.width_m >= 6.0
        if not (zone.intersects(line) or wide):
            continue
        rng = random.Random("parked:%s" % r.id)
        for side in (1, -1):
            s = rng.uniform(1.0, 4.0)
            while s < line.length - 1.0:
                c = line.interpolate(s)
                dense = zone.contains(c)
                kind = _choose(rng, VEHICLE_WEIGHTS)
                variant = rng.randrange(vehicles.VARIANTS)
                L, W, _H = vehicles.size(kind)
                skip = rng.random()
                if not dense and (not wide or skip < 0.95):
                    s += 6.0
                    continue
                if dense and skip < 0.45:
                    s += W + 0.6
                    continue
                t = _dir(line, s)
                n = (-t[1], t[0])
                nose_in = dense and kind not in ("auto", "erickshaw")
                depth = L if nose_in else W
                hd = math.atan2(n[1] * side, n[0] * side) if nose_in else math.atan2(t[1], t[0])
                if nose_in and rng.random() < 0.5:
                    hd += math.pi
                placed = False
                for extra in (0.05, 0.6, 1.3, 2.6, 3.4):
                    d = r.width_m / 2 + LANE_CLEAR + depth / 2 + extra
                    if pl.vehicle(kind, variant, c.x + n[0] * side * d, c.y + n[1] * side * d, hd):
                        placed = True
                        break
                s += ((W + 0.5) if nose_in else (L + 1.2)) if placed else 2.0


def drawn(view, pos, radius, tris, density, H, fov):
    """Whether the main view from `view` draws an instance whose info names its model in slot 0 alone (slot 2 empty),
    by build_city.views' model of DrawAScenery (the bounding circle in the field of view, pixel size over 17, no
    switch to the empty slot 2)."""
    ex, ey, ez = view["x"], view["y"], view["z"] + 0.5
    h = math.radians(view["heading"])
    fx, fy = math.cos(h), math.sin(h)
    dx, dy, dz = pos[0] - ex, pos[1] - ey, pos[2] - ez
    R = radius + 6.0
    d = math.sqrt(dx * dx + dy * dy + dz * dz)
    ahead = dx * fx + dy * fy
    if ahead < -R:
        return False
    if d > R:
        ang = math.degrees(math.acos(max(-1.0, min(1.0, ahead / max(1e-6, math.hypot(dx, dy))))))
        if ang - math.degrees(math.asin(min(1.0, R / d))) > fov / 2:
            return False
    px = H if d - R <= R else R * H / (d - R)
    if int(px) <= 0x11:
        return False
    return not (tris > 39 and px / max(6.0, density) < 8.7)


def vehicle_density(radius, H=x0props.VIEW_H):
    """The Density a tile's vehicles' solid needs for the game to stop drawing it VEHICLE_DRAW from the tile's middle,
    its info radius being its farthest vertex (the review: a smaller radius makes the game's pixel size 0 once the
    camera is radius + 6 past the tile's middle, so vehicles beside the car vanished). DrawAScenery: slot 2 (empty)
    when (radius + 6) H / (d - radius - 6) / max(Density, 6) < 8.7. Under 6 the game takes 6 (an earlier switch)."""
    R = radius + 6.0
    return R * H / (8.7 * (VEHICLE_DRAW - R))


def costs(pl, view, view_model):
    """(instances, meshes, triangles) the street life adds to a view, and the drawn props [(distance, prop, cost)]."""
    H, fov = view_model[:2]
    lib = x0props.library()
    inst = meshes = tris = 0
    for (i, j), n in pl.vtris.items():
        pos = ((i + 0.5) * TILE, (j + 0.5) * TILE, GROUND_Z)
        r = pl.vrad[(i, j)]
        if drawn(view, pos, r, n, vehicle_density(r, H), H, fov):
            inst, meshes, tris = inst + 1, meshes + 1, tris + n
    for f in pl.fixed:  # the breakable poles: counted, never thinned (not in the list returned)
        if drawn(view, (f["x"], f["y"], GROUND_Z + f["z"]), f["radius"], f["tris"], f["density"], H, fov):
            inst, meshes, tris = inst + 1, meshes + f["meshes"], tris + f["tris"]
    out = []
    for p in pl.res.props:
        m = lib[int(x0props.pick(p.role)["hash"], 16)]
        pos = (p.x, p.y, GROUND_Z + p.z)
        if drawn(view, pos, x0props.info_radius(p.role), m["tris"], m["density"], H, fov):
            out.append((math.dist(pos[:2], (view["x"], view["y"])), p, (1, m["meshes"], m["tris"])))
            inst, meshes, tris = inst + 1, meshes + m["meshes"], tris + m["tris"]
    return (inst, meshes, tris), out


def thin(pl, viewpoints, budgets, view_model):
    """Takes props and parked vehicles out of every view over its budget, the farthest first (the plan: thin the props
    where the +15% cannot hold rather than exceed it); {view: things taken out}."""
    out = {}
    for v in viewpoints:
        b = budgets.get(v["name"])
        if b is None:
            continue
        (ni, nm, nt), seen = costs(pl, v, view_model)
        # the drawn tiles' vehicles too (the review: the vehicles alone could pass Sector 16 Market's budget); a
        # tile's instance and mesh go with its last vehicle
        H, fov = view_model[:2]
        left = {}
        for k, n in pl.vtris.items():
            pos = ((k[0] + 0.5) * TILE, (k[1] + 0.5) * TILE, GROUND_Z)
            r = pl.vrad[k]
            if drawn(v, pos, r, n, vehicle_density(r, H), H, fov):
                for w in pl.vlist:
                    if w["tile"] == k:
                        seen.append((math.dist(w["rec"][2:4], (v["x"], v["y"])), w, (0, 0, w["n"])))
                        left[k] = left.get(k, 0) + 1
        gone, vgone = set(), []
        for _d, p, c in sorted(seen, key=lambda e: -e[0]):
            if ni <= b[0] and nm <= b[1] and nt <= b[2]:
                break
            ni, nm, nt = ni - c[0], nm - c[1], nt - c[2]
            if isinstance(p, dict):
                vgone.append(p)
                left[p["tile"]] -= 1
                if not left[p["tile"]]:
                    ni, nm = ni - 1, nm - 1
            else:
                gone.add(id(p))
        if gone or vgone:
            pl.res.props = [p for p in pl.res.props if id(p) not in gone]
            for w in vgone:
                pl.drop_vehicle(w)
            out[v["name"]] = len(gone) + len(vgone)
    return out
