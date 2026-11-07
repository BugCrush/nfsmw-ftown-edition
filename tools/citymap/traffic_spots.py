"""Where F-Town's traffic cars stand (docs/ftown-race-notes.md R11; plan docs/superpowers/plans/2026-11-04-ftown-traffic-cars.md
Task 2): spots at the kerbs and in the lanes of F-Town's ground-level roads, checked against the built city, written
for FTownLoader ([Traffic] File).

    .tools/cityenv/Scripts/python tools/citymap/traffic_spots.py      (writes ftown/ftown-traffic.json)

Rules (render metres, x east, y north, z up; heading in degrees counter-clockwise from +x):
- Roads of kind trunk, primary, secondary, tertiary, residential, unclassified, at level 0 and not bridges.
- A station every STEP metres along each road, none within JUNCTION_CLEAR of a junction (a point two roads share) or
  of the road's ends.
- Kerb spots on roads at least KERB_MIN_W wide: KERB_IN metres in from the road's edge; on a two-way road the left kerb
  faces along the road and the right kerb faces back (F-Town keeps left), alternating station by station; on a one-way
  road both face the road's way.
- Lane spots (a car stopped in traffic) on roads with at least 2 lanes a direction: LANE_OFF from the centre line, left
  of it, facing the road's way (one-way: the same offset), every LANE_EVERY-th station.
- A car's footprint (CAR_L x CAR_W, + MARGIN all round) crosses no collision barrier of the built city
  (ftown/ftown-city.bun: buildings, the street life's solids, medians); the ground under its centre and four corners is
  found by the game's height rule (tools/world/heightcheck.py), all within FLAT of each other and within GROUND_TOL of
  GROUND_Z (no deck, no ramp).
- The city's parking bays (ftown-city.json "parking_bays": where the street life's parked cars stood before Run I's
  fixes) are kerb candidates too, checked first, by the same rules.
- SPACING apart; SPAWN_CLEAR from the spawns ([Spawn] Spawn1.. in ftown/FTownLoader.ini) and every event's start
  (ftown/ftown-events.json).
- `route`: bit k set when the footprint comes within ROUTE_NEAR of event k's carriageway (ftown/ftown-events.json's
  order: 1 the Time Attack, 2 the Drag, 4 the Speed Trap, 8 the Sector Sprint; race_barriers.whole_road since Run J
  (both halves of a divided road), the ring of walls stands 1 m outside it): FTownLoader leaves the spots of the
  running event's route empty.

The file is JSON with one spot a line, `[x, y, z, heading, route, kind]` (kind 0 kerb, 1 lane): FTownLoader reads every
line that starts with `[` and holds six numbers.
"""
import json
import math
import os
import random
import re
import struct
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from chunks import read_chunks  # noqa: E402
from world import collision_write, heightcheck, scenery  # noqa: E402

from tools.citymap import race_barriers, roadmodel  # noqa: E402

AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
ROADS = os.path.join(AREA, "ftown-roads.json")
CITY = os.path.join(REPO, "ftown", "ftown-city.bun")
INI = os.path.join(REPO, "ftown", "FTownLoader.ini")
OUT = os.path.join(REPO, "ftown", "ftown-traffic.json")

KINDS = ("trunk", "primary", "secondary", "tertiary", "residential", "unclassified")
STEP = 40.0
JUNCTION_CLEAR = 25.0
KERB_MIN_W = 5.5
KERB_IN = 1.4  # the car's centre this far in from the road's edge
LANE_OFF = 1.75
LANE_EVERY = 3
CAR_L, CAR_W, MARGIN = 4.8, 2.0, 0.25
GROUND_Z = 100.0  # the flat city's ground; the built ground is terrain.ground_z (elevation, 2026-11-05)
GROUND_TOL = 0.6
FLAT = 0.25
SPACING = 10.0
SPAWN_CLEAR = 40.0
ROUTE_NEAR = 5.0
CELL = 64.0
NOTE = "F-Town traffic spots, derived from OpenStreetMap data (c) OpenStreetMap contributors (ODbL)"


@dataclass
class Spot:
    x: float
    y: float
    z: float
    heading: float
    route: int
    kind: int



def _ground_z(x, y):
    """The built ground's z (terrain.ground_z: the elevation, 2026-11-05)."""
    from tools.citymap import terrain
    return terrain.ground_z(x, y)

def footprint(x, y, heading, margin=MARGIN):
    h = math.radians(heading)
    c, s = math.cos(h), math.sin(h)
    hl, hw = CAR_L / 2 + margin, CAR_W / 2 + margin
    return [(x + c * a - s * b, y + s * a + c * b) for a, b in ((hl, hw), (-hl, hw), (-hl, -hw), (hl, -hw))]


class City:
    """The built city's collision: its barriers (render segments) and a height query by the game's rule."""

    def __init__(self, path=CITY):
        with open(path, "rb") as f:
            data = f.read()
        self.walls = []
        self.cells = {}
        for c, p in scenery.with_positions(read_chunks(data), 0):
            if c.id != collision_write.COLLISION_PACK:
                continue
            pack = collision_write.read_pack(c.data, p)
            for inst in pack.instances:
                t, r0, r2 = inst.t, inst.r0, inst.r2
                art = pack.articles[struct.unpack_from("<H", inst.raw, 0x1A)[0]]
                for bar in art.barriers:
                    a = (bar.p0[0] - t[0], bar.p0[2] - t[2])  # physics x, z
                    b = (bar.p1[0] - t[0], bar.p1[2] - t[2])
                    self.walls.append(LineString([(a[1], -a[0]), (b[1], -b[0])]))
                if inst.flags & 3:
                    continue
                px = -(t[0] * r0[0] + t[1] * r0[1] + t[2] * r0[2])
                pz = -(t[0] * r2[0] + t[1] * r2[1] + t[2] * r2[2])
                rad = inst.radius
                for i in range(int((px - rad) // CELL), int((px + rad) // CELL) + 1):
                    for k in range(int((pz - rad) // CELL), int((pz + rad) // CELL) + 1):
                        self.cells.setdefault((i, k), []).append((pack, inst, px, pz, rad))
        self.wall_tree = STRtree(self.walls)

    def height(self, rx, ry, probe=None):
        """The ground under render (rx, ry) as the game's height query finds it from `probe` (default 1 m over the
        built ground, terrain.ground_z), or None."""
        if probe is None:
            from tools.citymap import terrain
            probe = terrain.ground_z(rx, ry) + 1.0
        x, z = -ry, rx
        best = None
        for pack, inst, px, pz, rad in self.cells.get((int(x // CELL), int(z // CELL)), ()):
            if (px - x) ** 2 + (pz - z) ** 2 >= rad * rad:
                continue
            hit = heightcheck.face_in_instance(pack, inst, x, probe, z)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = (hit[0], inst, hit[1], hit[2])
        if best is None:
            return None
        _gap, inst, f, n = best
        t = tuple(x * inst.r0[a] + probe * (0.0, 1.0, 0.0)[a] + z * inst.r2[a] + inst.t[a] for a in range(3))
        return heightcheck._plane_y(n, f[0], t) - inst.t[1]

    def blocked(self, poly):
        for i in self.wall_tree.query(poly):
            if self.walls[int(i)].intersects(poly):
                return True
        return False


def spawns(ini=INI):
    """[(x, y)] of the ini's spawns and the Time Attack's start."""
    out = []
    with open(ini, encoding="ascii") as f:
        for line in f:
            m = re.match(r"\s*(Spawn\d+|Start)\s*=\s*([-\d.]+)\s*,\s*([-\d.]+)", line)
            if m:
                out.append((float(m.group(2)), float(m.group(3))))
    return out


def _stations(road):
    """(x, y, dx, dy) every STEP metres along a road, the first STEP/2 in."""
    pts = road.points
    seg = [(a, b, math.dist(a, b)) for a, b in zip(pts, pts[1:])]
    total = sum(s[2] for s in seg)
    out = []
    d = STEP / 2
    while d < total:
        acc = 0.0
        for a, b, L in seg:
            if acc + L >= d and L > 0:
                f = (d - acc) / L
                out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, (b[0] - a[0]) / L, (b[1] - a[1]) / L,
                            d, total - d))
                break
            acc += L
        d += STEP
    return out


def candidates(model):
    """Every kerb and lane spot the road rules give, before the city checks: (x, y, heading, kind, road)."""
    junctions = [Point(n.x, n.y) for n in model.junctions().values()]
    jtree = STRtree(junctions)
    out = []
    for road in model.roads:
        if road.kind not in KINDS or road.level != 0 or road.bridge:
            continue
        per_dir = road.lanes if road.oneway else road.lanes // 2
        for k, (x, y, dx, dy, d0, d1) in enumerate(_stations(road)):
            if d0 < JUNCTION_CLEAR or d1 < JUNCTION_CLEAR:
                continue
            p = Point(x, y)
            if any(junctions[int(i)].distance(p) < JUNCTION_CLEAR for i in jtree.query(p.buffer(JUNCTION_CLEAR))):
                continue
            lx, ly = -dy, dx  # left of the road's way
            head = math.degrees(math.atan2(dy, dx))
            if per_dir >= 2 and k % LANE_EVERY == 1:
                out.append((x + lx * LANE_OFF, y + ly * LANE_OFF, head, 1, road))
                continue  # the station's kerb spot would stand beside it
            if road.width_m >= KERB_MIN_W:
                off = road.width_m / 2 - KERB_IN
                if road.oneway or k % 2 == 0:
                    out.append((x + lx * off, y + ly * off, head, 0, road))
                else:
                    out.append((x - lx * off, y - ly * off, head + 180.0 if not road.oneway else head, 0, road))
    # the spot itself (off the centre line) keeps the junction distance too
    return [c for c in out if not any(junctions[int(i)].distance(Point(c[0], c[1])) < JUNCTION_CLEAR
                                      for i in jtree.query(Point(c[0], c[1]).buffer(JUNCTION_CLEAR)))]


def bays(path=None):
    """The city's parking bays (ftown-city.json "parking_bays", Run I fixes item 1: where the street life's parked
    cars stood, off the carriageway at the markets and hospitals) as kerb candidates (x, y, heading, 0, None)."""
    path = path or os.path.join(os.path.dirname(CITY), "ftown-city.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [(x, y, h, 0, None) for x, y, h in json.load(f).get("parking_bays", [])]


def _norm(h):
    return (h + 180.0) % 360.0 - 180.0


def spots(model, city, corridors, spawn_points, extra=()):
    """`corridors`: each event's carriageway, in the events' order (bit k of `route`); `extra`: more candidates (the
    parking bays), checked first."""
    out, taken = [], {}
    nears = [c.buffer(ROUTE_NEAR) for c in corridors]
    for x, y, head, kind, _road in list(extra) + candidates(model):
        # every check on the values written to the file
        x, y, head = round(x, 2), round(y, 2), round(_norm(head), 1)
        if any(math.dist((x, y), s) < SPAWN_CLEAR for s in spawn_points):
            continue
        key = (int(x // SPACING), int(y // SPACING))
        if any(math.dist((x, y), q) < SPACING for i in (-1, 0, 1) for j in (-1, 0, 1)
               for q in taken.get((key[0] + i, key[1] + j), ())):
            continue
        poly = Polygon(footprint(x, y, head))
        if city.blocked(poly):
            continue
        hs = [city.height(px, py) for px, py in [(x, y)] + footprint(x, y, head, 0.0)]
        if any(h is None for h in hs) or max(hs) - min(hs) > FLAT or abs(hs[0] - _ground_z(x, y)) > GROUND_TOL:
            continue
        route = sum(1 << k for k, near in enumerate(nears) if poly.intersects(near))
        out.append(Spot(x, y, round(hs[0], 2), head, route, kind))
        taken.setdefault(key, []).append((x, y))
    return out


def write(spot_list, path=OUT):
    counts = {"spots": len(spot_list), "route": sum(1 for s in spot_list if s.route),
              "kerb": sum(s.kind == 0 for s in spot_list), "lane": sum(s.kind == 1 for s in spot_list)}
    lines = ["{", ' "note": %s,' % json.dumps(NOTE), ' "format": "[x, y, z, heading, route (bit k: by the route of event k), kind]",',
             ' "counts": %s,' % json.dumps(counts), ' "spots": [']
    for i, s in enumerate(spot_list):
        lines.append("  [%.2f, %.2f, %.2f, %.1f, %d, %d]%s" % (s.x, s.y, s.z, s.heading, s.route, s.kind,
                                                            "," if i + 1 < len(spot_list) else ""))
    lines += [" ]", "}", ""]
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines))
    return counts


def read(path=OUT):
    with open(path, encoding="ascii") as f:
        return [Spot(*v[:4], int(v[4]), int(v[5])) for v in json.load(f)["spots"]]


def build(out=OUT, city_path=CITY):
    from tools.citymap import events
    model = roadmodel.RoadModel.load(ROADS)
    evs = events.read()
    # Run J, item 5: the whole road (both halves of a divided road, the median) is inside the event's ring now; Run K,
    # item 4: whatever the halves' names, with the barriers' own `raised` (race_barriers.build: none for the Time
    # Attack; build_events: event_raised), so the spots emptied are those inside each event's ring
    corrs = [race_barriers.whole_road(model, e["keys"], [tuple(p) for p in e["route"]], None, None,
                                      None if e["id"] == "timeattack" else race_barriers.event_raised(e)) for e in evs]
    city = City(city_path)
    found = spots(model, city, corrs, spawns() + [tuple(e["start"][:2]) for e in evs],
                  bays(os.path.join(os.path.dirname(os.path.abspath(city_path)), "ftown-city.json")))
    return found, write(found, out)


def main():
    _found, counts = build()
    print("wrote %s: %s" % (OUT, counts))


if __name__ == "__main__":
    main()
