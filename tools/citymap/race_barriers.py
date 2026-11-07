"""The Time Attack's race barriers on F-Town's first route (docs/ftown-race-notes.md R7; plan
docs/superpowers/plans/2026-11-04-ftown-game-mode.md Task 2): Rockport's own race-barrier panels and walls across every
side road that meets the route before the finish, and along the route's sides where the built city has no wall.

    .tools/cityenv/Scripts/python tools/citymap/race_barriers.py      (writes ftown/ftown-barriers.bun and .json, and
        every other event's ftown/ftown-barriers-<event>.bun and .json: build_events, plan 2026-11-04-ftown-events)

Since the events: each event of ftown/ftown-events.json has its own file built by the same rules (build_route), with
side legs all along its route (the ring closes the run-off past the finish), side-road barriers up to EVENT_LAST_D
along a leg, and walls only (no panels) beside the parts of the route on a ramp or a deck. All files use number 1409:
FTownLoader loads only the running event's. Rebuild every file after the city changes (the open-ground panels follow
its walls).

The file is one scenery section and one collision pack, both numbered 1409 (build_city.NUMBERS' last of the 1400
block; the city uses 1100..1109, 1400, 1401): the panels are X0's XO_TRACKBARRIERPLAYER_1B_00 (an 8 m wide, 6 m tall
neon arrow panel, 4 triangles; 5,771 of them in Rockport's scenery), named by hash in slot 0 only as the street life's
props are (nothing of X0 is in the file); the walls are collision barriers 31 m tall that block from both sides (flags
0x12, collision_write._article). FTownLoader loads the file while a Time Attack runs.

Rules (render metres, x east, y north):
- A **side leg** is every leg of a road at a route node (s along the route up to the finish, 30 m before the end) that
  is not one of the route's own segments; its path runs from the node away along the road (straight on past the road's
  end).
- Its **junction line** crosses the leg perpendicular to it, LINE_EXTRA metres longer than the road is wide on each
  side, at the first distance of 8, 10, .., 30 m along the leg where the line keeps CLEAR (1 m) from the route's
  carriageway (the route's centre line buffered by its road's half width); if none (the other half of a divided road
  running beside the route's own), the part of the line outside the carriageway + CLEAR that still crosses the leg, at
  the first such distance (the gap left beside the route is CLEAR, 1 m: no car fits).
- **The whole road** (Run J, item 5: "i want the full road"): where the route runs on one half of a divided road, the
  carriageway the ring bounds is both halves and the median between them (whole_road); the other half's legs at a
  route node lie inside it (inside_legs: nothing to close there).
- **The seal** (the review, 2026-11-04: lines across the side roads alone left gaps beside their ends): a ring of walls
  RING_OFFSET (1 m since Run I's fixes: the kerb line; 3 m before) outside the carriageway all round the route, closed behind the start and past the end. Where the
  ring crosses a side leg within 30 m it is that leg's barrier (panels); the legs it does not cross so (a divided
  road's other half beside the route) keep the junction line above. Elsewhere the ring shows panels over open ground
  (no wall of the built city, ftown/ftown-city.bun, WALL_MIN long or more within OPEN_BEHIND behind it; since Run I's
  fixes on every piece: continuous rows) and is a wall only in front of the city's own walls. Panels point the way of
  travel and face the route (panels(), facing()); the Speed Trap's file carries a photo radar at each camera gate. The route is closed past the finish: after it, Restart Race (pause menu) or quit.
- A panel every PANEL_W metres along each line (the whole length covered); one wall per line.
"""
import hashlib
import json
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from chunks import read_chunks, write_chunks  # noqa: E402
from world import collision_write, scenery, scenery_write  # noqa: E402
from world.collision import to_physics  # noqa: E402

from tools.citymap import geo, roadmodel, terrain  # noqa: E402

AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
ROADS = os.path.join(AREA, "ftown-roads.json")
ROUTE = os.path.join(AREA, "route_main.json")
CITY = os.path.join(REPO, "ftown", "ftown-city.bun")
OUT_BUN = os.path.join(REPO, "ftown", "ftown-barriers.bun")
OUT_JSON = os.path.join(REPO, "ftown", "ftown-barriers.json")

NUMBER = 1409
PANEL_HASH = 0x54A4FC3F  # XO_TRACKBARRIERPLAYER_1B_00 (tools/citymap/x0props.json)
PANEL_NAME = "FTB_TRACKBARRIER"
PANEL_BOX = (-4.014, -0.01, 0.234, 4.006, 0.059, 6.043)
PANEL_FLAGS = 0x8060  # as the street life's small props (no 0x80, 0x200 or 0x2000000: docs/ftown-notes.md)
PANEL_W = 8.0
PANEL_STAGGER = 0.12  # (before Run I's fixes: alternate panels aside; now panels are stretched to abut, no overlap)
# Run I fixes, items 5 and 10 (docs/ftown-notes.md "Run I fixes: the city side"). The panel is single-sided: two
# layers (the neon outline, the striped fill) facing model -y, the arrow along model +x (decoded from X0, by hash).
# Every panel's arrow points the way the car goes; one on the left of the route shows its face (the right of its
# arrow) to the road as it is; one on the right is rolled 180 degrees about its arrow (a rotation, no mirror: model
# z down, lifted by ROLL_LIFT so it stands 0.234-6.043 m as before), so its face looks left, at the road
ROLL_LIFT = 0.234 + 6.043  # (the model's box: z 0.234..6.043)
ALONG = 0.5  # |cos| between a line and the travel direction from which the line "runs along" the route
# Item 8 (the road side): Rockport's photo radar (X0 XO_PHOTORADAR_1B_MD_00, by hash) at each Speed Trap camera gate,
# on the route's left kerb (F-Town keeps left) CAM_OUT outside the carriageway, its lens (model -y) towards the cars
# that come, a small two-sided ring round its post on the ground (CAM_POST)
CAM_OUT = 0.5
CAM_POST = 0.25
CAM_GAP = 8.0  # m round a camera without panels (a wall only)
GROUND_Z = 100.0  # tiles.GROUND_Z: the flat city's ground; the built ground is terrain.ground_z (elevation)
WALL = (GROUND_Z - 1.0, GROUND_Z + 30.0)
WALL_FLAGS = 0x12  # blocks bodies on both sides
FINISH_BEFORE_END = 30.0  # route_gates.FINISH_BEFORE_END
FIRST, LAST_D, STEP_D = 8.0, 30.0, 2.0
# the events (build_events): a slip road leaving a flyover's ramp at a shallow angle (Mathura Road) stays within the
# ring's offset for more than 30 m: its barrier may stand up to this far along it
EVENT_LAST_D = 80.0
MIN_LINE = 0.05
LINE_EXTRA = 3.0
CLEAR = 1.0
# the ring of walls round the route: this far outside its carriageway (Run I fixes, item 10: 3 m stood half the
# panels in other roads' lanes, 219 of the Time Attack's 412; 1 m is the kerb line)
RING_OFFSET = 1.0
OPEN_BEHIND = 8.0  # a ring piece shows panels unless a wall of the city stands within this behind it
KERB_MIN = 0.4  # ... but never nearer it than this where another road's lanes begin (ring_area_of)
START_KEEP = 6.0  # m round the route's first point (the car is put down there) where the ring is not carved
START_ROOM = 3.6  # ... and at least this far from it all round (a 4.5 x 1.8 m car's half diagonal 2.42 m, and room)
RING_TOL = 0.1  # a ring piece's most distance from the ring it stands for (ring_pieces)
WALL_MIN = 2.0  # ... a wall 2 m long or more (Run I fixes, item 5: tree trunks and poles left gaps in the rows)
# panels on every n-th open edge piece (the wall is continuous): run I's 2 left the gaps the user saw (item 5); 1
EDGE_PANEL_EVERY = 1

LAST = {}  # the last build's legs, lines, route, corridor and ring area (for the tests)
RING_AREA = [None]
LAST_EVENTS = {}  # build_events: {event id: that build's LAST}


@dataclass
class Leg:
    s: float
    node: Tuple[float, float]
    path: List[Tuple[float, float]]
    width: float
    road_id: int
    kind: str


@dataclass
class Line:
    a: Tuple[float, float]
    b: Tuple[float, float]
    kind: str  # "junction" or "edge"
    s: float
    leg: Optional[Leg] = field(default=None, repr=False)
    panel: bool = True  # drawn with panels (else a wall only: a city wall stands right behind it)
    chain: int = -1  # the ring it is a piece of (ring_lines), and its place along it: panels run over such pieces
    seq: int = 0


def route_points(proj=None):
    proj = proj or geo.Projection()
    with open(ROUTE) as f:
        pts = json.load(f)["points"]
    return [roadmodel.node_key(lat, lon) for lat, lon in pts], [proj.to_render(lat, lon) for lat, lon in pts]


def along(pts):
    s = [0.0]
    for a, b in zip(pts, pts[1:]):
        s.append(s[-1] + math.dist(a, b))
    return s


def route_segments(model, keys):
    """{(key a, key b): road} for the route's segments (both directions)."""
    seg = {}
    want = set(zip(keys, keys[1:])) | set(zip(keys[1:], keys))
    for r in model.roads:
        for a, b in zip(r.keys, r.keys[1:]):
            if (a, b) in want:
                seg[(a, b)] = r
                seg[(b, a)] = r
    return seg


def corridor(model, keys, pts):
    """The route's carriageway: each segment buffered by half its road's width (flat ends, joined)."""
    seg = route_segments(model, keys)
    parts = []
    for (ka, kb), a, b in zip(zip(keys, keys[1:]), pts, pts[1:]):
        r = seg.get((ka, kb))
        w = r.width_m if r else 8.0
        parts.append(LineString([a, b]).buffer(w / 2.0, cap_style=2, join_style=2))
        parts.append(Point(a).buffer(w / 2.0))
    parts.append(Point(pts[-1]).buffer(4.0))
    return unary_union(parts)


TWIN_STEP = 4.0  # m: the pieces of the route matched against a divided road's other half (whole_road)


def twins(model):
    """{road id: [roads]}: the other halves of every divided road (furniture.pairs: two one-way ground carriageways of
    one name running opposite ways at most PAIR_GAP apart; the DND-KMP Expressway left out, its crash walls stand between
    its halves)."""
    from tools.citymap import furniture
    paired = set()
    for a, b in furniture.pairs(model):
        paired |= {a.id, b.id}
    # the other half's pieces: every one-way ground road of the family (a name, or unnamed of one kind) of a paired
    # road (the pair test needs MIN_PAIR metres side by side: a short piece of the other half between two side roads
    # left a notch in the whole road)
    def family(r):
        return r.name if r.name else "~" + furniture._family(r.kind)
    fam = {}
    for r in model.roads:
        if r.oneway and r.level == 0 and r.name not in furniture.SKIP_NAMES:
            fam.setdefault(family(r), []).append(r)
    out = {}
    for members in fam.values():
        if any(r.id in paired for r in members):
            for r in members:
                out[r.id] = [t for t in members if t.id != r.id]
    return out


def beside(model):
    """Run K, item 4: (roads, their lines, an STRtree of them) of every one-way ground carriageway that may be a
    divided road's other half whatever its name (the DND-KMP Expressway's left out, as in twins)."""
    from tools.citymap import furniture
    one = [r for r in model.roads if r.oneway and r.level == 0 and r.name not in furniture.SKIP_NAMES]
    lines = [LineString(r.points) for r in one]
    return one, lines, STRtree(lines)


def whole_road(model, keys, pts, corr=None, matched=None, raised=None):
    """Run J, item 5 ("they only allow me to drive on my side of the traffic. i want the full road"): the route's
    carriageway (corridor) and, where it runs on one half of a divided road, the other half beside it and the median
    between them. Every TWIN_STEP metres of the route on a road with a twin: the convex hull of that piece of the
    carriageway and the twin's piece beside it (both at their widths), wherever the two are at most PAIR_GAP apart edge
    to edge and run opposite ways (furniture.pairs' own test). The ring of walls then stands round the whole road.
    matched: a set given is filled with the ids of the other halves' roads that took part (the review: a family
    reaches across the city, "~tertiary" is 62 roads; the other half is only what was matched beside the route).
    Run K, item 4 (screenshot 135: chevrons halfway across Lal Bahadur Shastri Marg): the twins come from a name
    family, and OSM names the halves of one road differently (route 1's westward stretch is an unnamed tertiary beside
    "Lal Bahadur Shastri Marg"; the Speed Trap's ground stretches "Mathura Road Flyover" beside "Mathura Road"), so where
    the route is on the ground (raised(x, y) false or not given) every one-way ground carriageway of the route road's
    own kind beside it (beside()) is a candidate too; the same geometric test decides. On a ramp or deck only the family's (a ground road beside a
    rising ramp is no other half: the ramp's edge keeps its wall)."""
    from shapely.ops import substring
    from tools.citymap import furniture
    corr = corridor(model, keys, pts) if corr is None else corr
    tw = twins(model)
    one, one_lines, one_tree = beside(model)
    seg = route_segments(model, keys)
    lines = {}
    parts = []
    for (ka, kb), a, b in zip(zip(keys, keys[1:]), pts, pts[1:]):
        r = seg.get((ka, kb))
        if r is None or not r.oneway or r.level != 0 or r.name in furniture.SKIP_NAMES:
            continue
        L = math.dist(a, b)
        n = max(1, int(math.ceil(L / TWIN_STEP)))
        ux, uy = (b[0] - a[0]) / (L or 1.0), (b[1] - a[1]) / (L or 1.0)
        for k in range(n):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
            cands = list(tw.get(r.id, []))
            if raised is None or not raised((p[0] + q[0]) / 2, (p[1] + q[1]) / 2):
                # (of the route's own kind: a slip road (tertiary_link) leaving at a shallow angle, or Mathura Road (a
                # trunk) met at route 1's end, runs the other way beside it for a few metres and is no other half)
                near = LineString([p, q]).buffer(r.width_m / 2 + 12.0 + furniture.PAIR_GAP)
                have = {t.id for t in cands} | {r.id}
                cands += [one[i] for i in sorted(one_tree.query(near)) if one[i].id not in have and one[i].kind == r.kind]
            for t in cands:
                tl = lines.get(t.id) or lines.setdefault(t.id, LineString(t.points))
                sp, sq = tl.project(Point(p)), tl.project(Point(q))
                pp, qq = tl.interpolate(sp), tl.interpolate(sq)
                reach = r.width_m / 2 + t.width_m / 2 + furniture.PAIR_GAP
                if Point(p).distance(pp) > reach or Point(q).distance(qq) > reach or abs(sq - sp) < 1e-3:
                    continue
                if sq > sp or (qq.x - pp.x) * ux + (qq.y - pp.y) * uy < 0.8 * (sp - sq):
                    continue  # (the twin's own way runs against the route's here, and beside it: not across)
                mine = LineString([p, q]).buffer(r.width_m / 2, cap_style=2, join_style=2)
                other = substring(tl, min(sp, sq), max(sp, sq)).buffer(t.width_m / 2, cap_style=2, join_style=2)
                parts.append(unary_union([mine, other]).convex_hull.buffer(0.05, join_style=2))
                if matched is not None:
                    matched.add(t.id)
    if not parts:
        return corr
    return unary_union([corr] + parts)


def closer_lines(model, others, road):
    """The centre lines of the other halves (`others`: whole_road's matched roads less the route's own) that reach
    into the whole road: a ring piece across one closes that half where the whole road ends (ring_lines' closers)."""
    out = []
    for rid in sorted(others):
        ln = LineString(model.road(rid).points)
        if ln.intersects(road):
            out.append(ln)
    return out


def twin_legs(model, keys, pts, road, others, until=None):
    """The side legs of the other halves (Run J, item 5): every leg of a road but the other halves themselves
    (`others`: whole_road's matched roads less the route's own) at a node of one inside the whole road `road`, s its distance along the route (its nearest point), up
    to `until` (default the Time Attack's finish). Closed as the route's own side legs are (the ring crosses them, or a
    junction line)."""
    s_all = along(pts)
    finish = s_all[-1] - FINISH_BEFORE_END if until is None else until
    seg = route_segments(model, keys)
    if not others:
        return []
    route = LineString(pts)
    area = road.buffer(0.05)
    on_route = set(keys)
    legs, seen = [], set()
    for tid in sorted(others):
        t = model.road(tid)
        for k, (x, y) in zip(t.keys, t.points):
            if k in on_route or k in seen or not area.contains(Point(x, y)):
                continue
            seen.add(k)
            s = route.project(Point(x, y))
            if s > finish:
                continue
            node = model.nodes.get(k)
            if not node:
                continue
            for rid in sorted(set(node.road_ids)):
                if rid in others:
                    continue
                r = model.road(rid)
                for j, kk in enumerate(r.keys):
                    if kk != k:
                        continue
                    for step in (-1, 1):
                        nb = j + step
                        if not 0 <= nb < len(r.keys) or (k, r.keys[nb]) in seg:
                            continue
                        path = _leg_path(r, j, step)
                        if path:
                            legs.append(Leg(s, (x, y), path, r.width_m, r.id, r.kind))
    return legs


def inside_legs(legs, road, last_d=LAST_D):
    """The side legs whose first last_d metres lie inside the whole road (whole_road; grown by RING_OFFSET): a divided
    road's other half leaving a route node, a gap in the median. They are part of the road now, nothing to close; the
    ring closes them where they leave it."""
    from shapely.ops import substring
    area = road.buffer(RING_OFFSET + 0.01)
    out = []
    for leg in legs:
        ln = LineString(leg.path)
        if area.contains(substring(ln, 0.0, min(last_d, ln.length))):
            out.append(leg)
    return out


def _leg_path(road, j, step):
    """The road's points from index j going `step` (+1 or -1), extended straight to at least 60 m."""
    out = [road.points[j]]
    k = j + step
    while 0 <= k < len(road.points):
        out.append(road.points[k])
        k += step
    if len(out) < 2:
        return None
    total = sum(math.dist(a, b) for a, b in zip(out, out[1:]))
    if total < 60.0:
        (ax, ay), (bx, by) = out[-2], out[-1]
        L = math.dist(out[-2], out[-1]) or 1.0
        ext = 60.0 - total + 1.0
        out.append((bx + (bx - ax) / L * ext, by + (by - ay) / L * ext))
    return out


def side_legs(model, keys, pts, until=None):
    """Every leg of a road at a route node up to `until` metres along the route (default: the Time Attack's finish,
    FINISH_BEFORE_END before the end) that is not one of the route's own segments."""
    s = along(pts)
    finish = s[-1] - FINISH_BEFORE_END if until is None else until
    seg = route_segments(model, keys)
    legs = []
    for i, k in enumerate(keys):
        if s[i] > finish:
            continue
        node = model.nodes.get(k)
        if not node:
            continue
        for rid in sorted(set(node.road_ids)):
            r = model.road(rid)
            for j, kk in enumerate(r.keys):
                if kk != k:
                    continue
                for step in (-1, 1):
                    nb = j + step
                    if not 0 <= nb < len(r.keys) or (k, r.keys[nb]) in seg:
                        continue
                    path = _leg_path(r, j, step)
                    if path:
                        legs.append(Leg(s[i], pts[i], path, r.width_m, r.id, r.kind))
    return legs


def _across(path, d, half):
    """The line across `path` at distance d along it, `half` metres each side."""
    ln = LineString(path)
    p = ln.interpolate(d)
    q = ln.interpolate(min(d + 1.0, ln.length))
    o = ln.interpolate(max(d - 1.0, 0.0))
    dx, dy = q.x - o.x, q.y - o.y
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    return (p.x + nx * half, p.y + ny * half), (p.x - nx * half, p.y - ny * half)


def junction_lines(legs, corr, last_d=LAST_D):
    out = []
    for leg in legs:
        half = leg.width / 2.0 + LINE_EXTRA
        chosen = None
        d = FIRST
        while d <= last_d + 1e-9:
            a, b = _across(leg.path, d, half)
            if corr.distance(LineString([a, b])) >= CLEAR:
                chosen = (a, b)
                break
            d += STEP_D
        if chosen is None:
            # a carriageway beside the route's own (a divided road, the route on its other half): the line's part
            # outside the route's carriageway + CLEAR that still crosses the leg, at the first distance with one
            keep = corr.buffer(CLEAR + 0.01)
            centre = LineString(leg.path)
            d = FIRST
            while d <= last_d + 1e-9 and chosen is None:
                a, b = _across(leg.path, d, half)
                rest = LineString([a, b]).difference(keep)
                for piece in ([rest] if rest.geom_type == "LineString" else list(getattr(rest, "geoms", []))):
                    if not piece.is_empty and piece.intersects(centre):
                        chosen = (piece.coords[0], piece.coords[-1])
                        break
                d += STEP_D
        if chosen is None:
            raise ValueError("side road %d at s=%.0f cannot be closed clear of the route" % (leg.road_id, leg.s))
        out.append(Line(chosen[0], chosen[1], "junction", leg.s, leg))
    return out


def city_walls(path=CITY):
    """Every collision barrier of the built city as a render segment ((x0, y0), (x1, y1))."""
    with open(path, "rb") as f:
        data = f.read()
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id != collision_write.COLLISION_PACK:
            continue
        pack = collision_write.read_pack(c.data, p)
        for inst in pack.instances:
            t = inst.t
            art = pack.articles[struct.unpack_from("<H", inst.raw, 0x1A)[0]]
            for bar in art.barriers:
                a = (bar.p0[0] - t[0], bar.p0[2] - t[2])  # physics x, z
                b = (bar.p1[0] - t[0], bar.p1[2] - t[2])
                out.append(((a[1], -a[0]), (b[1], -b[0])))  # render = (z, -x)
    return out


def ring_area_of(corr, lanes=None, keep=None):
    """The region the ring bounds: the route's carriageway grown by RING_OFFSET, less the drawn carriageways of other
    roads farther than KERB_MIN from it (Run I fixes, item 10: on a divided road without a median the other half's
    lanes begin at the route's own kerb; the ring keeps to the line between them), the parts holding the route. keep:
    where nothing is carved (round the start, where the car is put down: START_KEEP)."""
    area = corr.buffer(RING_OFFSET)
    if lanes is not None:
        carve = lanes.difference(corr.buffer(KERB_MIN))
        if keep is not None:
            carve = carve.difference(keep)
        area = area.difference(carve)
    if keep is not None:
        area = area.union(keep.centroid.buffer(START_ROOM))
        parts = [g for g in getattr(area, "geoms", [area]) if g.intersects(corr)]
        area = unary_union(parts)
    return area


def ring_pieces(ring, most=PANEL_W, tol=None):
    """[(a, b)] along a closed ring, each at most `most` long and never more than `tol` (RING_TOL) off the ring it
    stands for: where a chord would leave the ring farther (a corner: a chord across a sharp inner corner would cut
    into the carriageway), the piece ends at the ring's vertex farthest from it."""
    import bisect
    tol = RING_TOL if tol is None else tol
    pts = list(ring.coords)
    s = [0.0]
    for a, b in zip(pts, pts[1:]):
        s.append(s[-1] + math.dist(a, b))
    total = s[-1]
    out, s0 = [], 0.0
    while s0 < total - 1e-6:
        end = min(s0 + most, total)
        while True:
            a, b = ring.interpolate(s0), ring.interpolate(end)
            lo, hi = bisect.bisect_right(s, s0 + 1e-6), bisect.bisect_left(s, end - 1e-6)
            if hi <= lo:
                break
            chord = LineString([a, b])
            d = [chord.distance(Point(pts[i])) for i in range(lo, hi)]
            k = max(range(len(d)), key=d.__getitem__)
            if d[k] <= tol:
                break
            end = s[lo + k]
        out.append(((a.x, a.y), (b.x, b.y)))
        s0 = end
    return out


def ring_lines(corr, legs, walls, raised=None, last_d=LAST_D, lanes=None, keep=None, closers=()):
    """The review's seal: a ring of walls RING_OFFSET outside the route's carriageway all round (it closes behind the
    start and past the end), cut into pieces of at most PANEL_W. A piece that crosses a side leg within LAST_D of its
    junction is that leg's barrier ("junction", panels); the others are "edge" pieces, with panels where no wall of the
    built city stands within OPEN_BEHIND behind them (open ground), a wall only where one does. `raised(x, y)`: true
    where the route beside the piece runs on a ramp or a deck (above the ground): a wall only there (a panel stands on
    the ground, it would stand under the deck; the deck's own railings hold the car). closers: centre lines (the other
    halves of divided roads, Run J item 5) a piece across which closes that carriageway where the whole road ends: a
    "junction" piece of no leg."""
    ring_area = ring_area_of(corr, lanes, keep)
    closer_tree = STRtree(list(closers)) if closers else None
    RING_AREA[:] = [ring_area]
    rings = []
    for poly in getattr(ring_area, "geoms", [ring_area]):
        rings.append(LineString(poly.exterior.coords))
        rings += [LineString(r.coords) for r in poly.interiors]
    wall_geoms = [LineString(w) for w in walls if math.dist(*w) >= WALL_MIN]
    wall_tree = STRtree(wall_geoms)
    leg_paths = [(leg, LineString(leg.path)) for leg in legs]
    out = []
    for ri, ring in enumerate(rings):
        for k, (a, b) in enumerate(ring_pieces(ring)):
            piece = LineString([a, b])
            crossed = None
            for leg, path in leg_paths:
                x = path.intersection(piece)
                if x.is_empty:
                    continue
                p = x if x.geom_type == "Point" else list(getattr(x, "geoms", [x]))[0]
                if path.project(Point(p.x, p.y)) <= last_d + 1e-6:
                    crossed = leg
                    break
            up = raised is not None and raised((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if crossed is not None:
                out.append(Line(a, b, "junction", crossed.s, crossed, not up, ri, k))
                continue
            if closer_tree is not None and any(closers[i].intersects(piece) for i in closer_tree.query(piece)):
                out.append(Line(a, b, "junction", 0.0, None, not up, ri, k))
                continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            L = math.dist(a, b) or 1.0
            nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            if ring_area.contains(Point(mx + nx * 0.5, my + ny * 0.5)):
                nx, ny = -nx, -ny  # outward: away from the route
            ray = LineString([(mx, my), (mx + nx * OPEN_BEHIND, my + ny * OPEN_BEHIND)])
            behind = any(wall_geoms[i].intersects(ray) for i in wall_tree.query(ray))
            out.append(Line(a, b, "edge", 0.0, None, not behind and not up and k % EDGE_PANEL_EVERY == 0, ri, k))
    return out


PANEL_TOL = 0.3  # a run of panels may cut a ring's corner by this much (they are seen, not met: the walls follow it)
SLIVER = 2.4  # m: a span shorter than this joins its neighbour (the review: 90 of route 1's panels were under 2 m)
MERGE_TOL = 0.6  # ... if the joined span stays this near the run
CARD_CLEAR = 0.1  # ... and this far off the carriageway


def runs(lines):
    """[[(x, y), ...]] the polylines panels are laid along: consecutive panelled pieces of one ring joined (Run I
    fixes: a ring cut at its corners left slivers of panels, 15% of them under half a panel wide), every other
    panelled line on its own."""
    out, cur, last = [], None, None
    ring = sorted([l for l in lines if l.panel and l.chain >= 0], key=lambda l: (l.chain, l.seq))
    for ln in ring:
        if cur is not None and last.chain == ln.chain and last.seq + 1 == ln.seq and math.dist(last.b, ln.a) < 1e-6:
            cur.append(ln.b)
        else:
            cur = [ln.a, ln.b]
            out.append(cur)
        last = ln
    out += [[l.a, l.b] for l in lines if l.panel and l.chain < 0]
    return out


def _joined(run, spans, corr=None):
    """spans with every one shorter than SLIVER joined to its shorter neighbour when the joined chord stays within
    MERGE_TOL of the run and CARD_CLEAR off the carriageway `corr` (the review: a corner's short spans each took a
    squashed panel, two draws for little); a sliver that cannot join is left out (its wall stays: a gap of less than
    SLIVER at a corner)."""
    out = [list(s) for s in spans]
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i, (a, b) in enumerate(out):
            if math.dist(a, b) >= SLIVER:
                continue
            cands = []
            if i > 0:
                cands.append((math.dist(*out[i - 1]), i - 1))
            if i + 1 < len(out):
                cands.append((math.dist(*out[i + 1]), i))
            for _L, j in sorted(cands):
                p, q = out[j][0], out[j + 1][1]
                chord = LineString([p, q])
                s0, s1 = run.project(Point(p)), run.project(Point(q))
                inner = [Point(c) for c in run.coords if s0 + 1e-6 < run.project(Point(c)) < s1 - 1e-6]
                if math.dist(p, q) <= PANEL_W * 1.25 and all(chord.distance(c) <= MERGE_TOL for c in inner) and (
                        corr is None or corr.distance(chord) >= CARD_CLEAR):
                    out[j:j + 2] = [[p, q]]
                    changed = True
                    break
            if changed:
                break
    return [tuple(s) for s in out if math.dist(*s) >= SLIVER]


def panels(lines, route=None, corr=None):
    """[(x, y, heading radians, rolled, x scale)]: along each run (runs()) spans of at most PANEL_W, within PANEL_TOL
    of it, each with ceil(length / PANEL_W) panels stretched to length / n (scale x; Rockport stretches its panels too),
    so they abut. With the route (a LineString) each panel's arrow points the way of travel and its face looks at the
    route (rolled on the route's right; module constants); without it the heading follows the line, nothing rolled."""
    out = []
    for run in runs(lines):
        spans = [(run[0], run[1])] if len(run) == 2 else _joined(LineString(run), ring_pieces(LineString(run), PANEL_W,
                                                                                             PANEL_TOL), corr)
        for a, b in spans:
            L = math.dist(a, b)
            if L < SLIVER:  # (a line on its own shorter than a sliver: its wall only)
                continue
            n = max(1, math.ceil(L / PANEL_W - 1e-9))
            h = math.atan2(b[1] - a[1], b[0] - a[0])
            for k in range(n):
                t = (k + 0.5) / n
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                hh, rolled = h, False
                if route is not None:
                    hh, rolled = facing(route, x, y, h)
                    if corr is not None:
                        x, y = _card_clear(corr, route, x, y, hh, L / n / PANEL_W)
                out.append((x, y, hh, rolled, L / n / PANEL_W))
    return out


CARD_CLEAR = 0.12  # m: a panel's card (centre +- PANEL_W / 2 x scale along its arrow) stays this far off the carriageway


def _card_clear(corr, route, x, y, h, sx):
    """(x, y) moved straight away from the route until the panel's card is CARD_CLEAR off the carriageway (the corridor);
    unchanged when it already is (a run cutting a corner by up to PANEL_TOL can bring a card's end near it: moving F-Town
    in 2026-11-06 left one Speed Trap card 0.054 m off)."""
    hx, hy = math.cos(h) * PANEL_W / 2 * sx, math.sin(h) * PANEL_W / 2 * sx
    d = corr.distance(LineString([(x - hx, y - hy), (x + hx, y + hy)]))
    if d >= CARD_CLEAR:
        return x, y
    q = route.interpolate(route.project(Point(x, y)))
    ox, oy = x - q.x, y - q.y
    L = math.hypot(ox, oy) or 1.0
    step = CARD_CLEAR - d + 0.01
    return x + ox / L * step, y + oy / L * step


def facing(route, x, y, h):
    """(heading, rolled) of a panel at (x, y) on a line of heading h: along the route (|cos| >= ALONG) the arrow with
    the travel direction, rolled when the panel stands right of the route; across it (an end of the ring) not
    rolled, its face (the right of its arrow) towards the route."""
    s = route.project(Point(x, y))
    a, b = route.interpolate(max(0.0, s - 2.0)), route.interpolate(min(route.length, s + 2.0))
    tx, ty = b.x - a.x, b.y - a.y
    L = math.hypot(tx, ty) or 1.0
    tx, ty = tx / L, ty / L
    q = route.interpolate(s)
    ux, uy = math.cos(h), math.sin(h)
    if abs(ux * tx + uy * ty) >= ALONG:
        if ux * tx + uy * ty < 0:
            h += math.pi
        left = tx * (y - q.y) - ty * (x - q.x) > 0
        return h, not left
    # across: the face is the right of the arrow, (sin h, -cos h)
    if math.sin(h) * (q.x - x) - math.cos(h) * (q.y - y) < 0:
        h += math.pi
    return h, False


def _q(v):
    """A matrix entry as the scenery writer stores it (an s16 / 8192, build_city._q)."""
    return round(v * 8192.0) / 8192.0


def _phys_wall(a, b):
    A, B = to_physics((a[0], a[1], 0.0)), to_physics((b[0], b[1], 0.0))
    # on the built ground (elevation, 2026-11-05): a level box from the lower end's ground to the higher end's top
    oa, ob = terrain.offset(*a), terrain.offset(*b)
    return ((A[0], A[2]), (B[0], B[2]), WALL[0] + min(oa, ob), WALL[1] + max(oa, ob), WALL_FLAGS)


def panel_matrix(x, y, h, rolled, sx):
    """The scenery matrix of a panel (rows: model x, y, z in the world, then its position on the built ground)."""
    c, s = math.cos(h), math.sin(h)
    z = terrain.ground_z(x, y)
    if rolled:  # 180 degrees about the arrow: y and z reversed, lifted so it stands where it stood
        return ((_q(c * sx), _q(s * sx), 0.0, 0.0), (_q(s), _q(-c), 0.0, 0.0), (0.0, 0.0, -1.0, 0.0),
                (x, y, z + ROLL_LIFT, 1.0))
    return ((_q(c * sx), _q(s * sx), 0.0, 0.0), (_q(-s), _q(c), 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (x, y, z, 1.0))


def make_file(lines, route=None, cameras=(), corr=None):
    """The file's bytes, its panel count and its collision instances. cameras: [(x, y, z, heading, on_ground)] of
    the Speed Trap's photo radars (camera_spots)."""
    from tools.citymap import x0props
    from tools.citymap.build_city import assemble
    props = []
    for x, y, h, rolled, sx in panels(lines, route, corr):
        props.append((PANEL_NAME, (PANEL_HASH, 0, 0, 0), 0.0, PANEL_BOX, panel_matrix(x, y, h, rolled, sx),
                      PANEL_FLAGS))
    n_panels = len(props)
    walls = [_phys_wall(ln.a, ln.b) for ln in lines]
    for x, y, z, h, ground in cameras:
        c, s = _q(math.cos(h)), _q(math.sin(h))
        m = ((c, s, 0.0, 0.0), (-s, c, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (x, y, z, 1.0))
        props.append(("FTB_SPEEDCAM", x0props.slots("speedcam"), x0props.info_radius("speedcam"),
                      tuple(x0props.model(x0props.pick("speedcam")["name"])["box"]), m, x0props.flags("speedcam")))
        if ground:
            r = CAM_POST
            ring = [(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)]
            for a, b in zip(ring, ring[1:] + ring[:1]):
                A, B = to_physics((a[0], a[1], 0.0)), to_physics((b[0], b[1], 0.0))
                walls.append(((A[0], A[2]), (B[0], B[2]), WALL[0] + terrain.offset(x, y), WALL[1] + terrain.offset(x, y),
                              WALL_FLAGS))  # (as tall as the ring's walls: the post is thin)
    sc = scenery_write.make_section(NUMBER, [], {}, props=props)
    pack = collision_write.make_pack(NUMBER, [], walls)
    return write_chunks(assemble([("scenery", sc), ("collision", pack)])), n_panels, len(pack.instances)


def camera_spots(ev, corr, raised):
    """[(x, y, z, heading, on_ground)] of a Speed Trap's cameras: at each camera gate on the route's left, CAM_OUT
    outside the carriageway (on a raised part: on the deck's edge, at the route's height), the
    model's x axis to the right of travel so its lens (model -y) faces the cars that come."""
    from tools.citymap import events
    route = LineString(ev["route"])
    S, Z = events.follow(ev)
    out = []
    for g in ev["gates"]:
        if g["type"] != "camera":
            continue
        s = route.project(Point(g["x"], g["y"]))
        a, b = route.interpolate(max(0.0, s - 2.0)), route.interpolate(min(route.length, s + 2.0))
        tx, ty = b.x - a.x, b.y - a.y
        L = math.hypot(tx, ty) or 1.0
        tx, ty = tx / L, ty / L
        q = route.interpolate(s)
        lx, ly = -ty, tx
        d = 0.0
        while d < 40.0 and corr.contains(Point(q.x + lx * d, q.y + ly * d)):
            d += 0.05
        up = raised(q.x, q.y)
        if not up:  # (on a deck: on its edge, where its parapet stands)
            d += CAM_OUT
        x, y = q.x + lx * d, q.y + ly * d
        if up:
            k = min(max(int(round((s - S[0]) / (S[1] - S[0]))), 0), len(Z) - 1)
            z = float(Z[k])  # events.follow: the face's height under the route there
        else:
            z = terrain.ground_z(x, y)
        out.append((x, y, z, math.atan2(-tx, ty), not up))
    return out


PANEL_DRAW = 6.0 + 6.0 * 1000.0 / 17.0  # m: a 4-triangle model, info radius 0, drawn until 17 px at H 1,000 (359 m)


def view_panels(data, route, step=25.0, fov=106.0):
    """(max, median) of the panels the main view draws from points every `step` m along the route looking the way of
    travel (within PANEL_DRAW, in the field of view `fov`, build_city.VIEW_FOV); each is two draws (two meshes)."""
    import numpy as np
    from chunks import read_chunks
    pos = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id == scenery.SCENERY_SECTION:
            sc = scenery.read_scenery(c, p)
            pos += [inst.matrix[3][:2] for inst in sc.instances if sc.infos[inst.info_index].solid_hashes[0] == PANEL_HASH]
    P = np.array(pos, dtype=float).reshape(-1, 2)
    line = LineString(route)
    counts = []
    for s in np.arange(0.0, line.length, step):
        a, b = line.interpolate(s), line.interpolate(min(line.length, s + 2.0))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= np.linalg.norm(t) or 1.0
        d = P - (a.x, a.y)
        r = np.hypot(d[:, 0], d[:, 1])
        ang = np.degrees(np.arccos(np.clip((d @ t) / np.maximum(r, 1e-6), -1, 1)))
        counts.append(int(((r < PANEL_DRAW) & ((ang < fov / 2) | (r < 6.0))).sum()))
    return max(counts), float(np.median(counts))


def read_walls(data):
    """[((x0, y0), (x1, y1), bottom, top)] render, of every barrier in a file's collision packs."""
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id != collision_write.COLLISION_PACK:
            continue
        pack = collision_write.read_pack(c.data, p)
        for inst in pack.instances:
            t = inst.t
            art = pack.articles[struct.unpack_from("<H", inst.raw, 0x1A)[0]]
            for bar in art.barriers:
                a = (bar.p0[0] - t[0], bar.p0[2] - t[2])
                b = (bar.p1[0] - t[0], bar.p1[2] - t[2])
                out.append(((a[1], -a[0]), (b[1], -b[0]), bar.p0[1] - t[1], bar.p1[1] - t[1]))
    return out


def _crossing(line):
    """How far along its leg a junction line crosses it."""
    path = LineString(line.leg.path)
    x = path.intersection(LineString([line.a, line.b]))
    p = x if x.geom_type == "Point" else list(getattr(x, "geoms", [x]))[0]
    return path.project(Point(p.x, p.y))


def build_route(keys, pts, legs_until, out_bun, out_json, name, raised=None, model=None, last_d=LAST_D, ev=None):
    """One route's barrier file and its numbers (json): side legs up to `legs_until` metres along the route, the ring
    round the whole route, panels where `raised` says the route is on the ground."""
    model = model or roadmodel.RoadModel.load(ROADS)
    own = corridor(model, keys, pts)
    matched = set()
    # Run J, item 5: both halves of a divided road and the median (Run K, item 4: whatever the halves' names)
    corr = whole_road(model, keys, pts, own, matched, raised)
    others = matched - {r.id for r in route_segments(model, keys).values()}
    legs = side_legs(model, keys, pts, legs_until) + twin_legs(model, keys, pts, corr, others, legs_until)
    within = inside_legs(legs, corr, last_d)
    from tools.citymap import levels
    ring = ring_lines(corr, legs, city_walls(), raised, last_d, levels.build(model).ground_polygon,
                      Point(pts[0]).buffer(START_KEEP), closer_lines(model, others, corr))
    on_ring = {id(l.leg) for l in ring if l.leg is not None}
    skip = on_ring | {id(g) for g in within}
    jl = [l for l in ring if l.kind == "junction"] + junction_lines([g for g in legs if id(g) not in skip], corr, last_d)
    el = [l for l in ring if l.kind == "edge"]
    # a ring of a few centimetres (a hole of the buffered carriageway where two segments meet) gives pieces too short
    # for a wall (collision_write divides by the length)
    jl = [l for l in jl if math.dist(l.a, l.b) >= MIN_LINE]
    el = [l for l in el if math.dist(l.a, l.b) >= MIN_LINE]
    lines = jl + el
    cams = camera_spots(ev, corr, raised) if ev is not None and ev.get("kind") == "speedtrap" else []
    for ln in lines:  # the row of panels opens round a camera: it stands out on the kerb (Rockport's stand alone)
        if any(LineString([ln.a, ln.b]).distance(Point(c[0], c[1])) < CAM_GAP for c in cams):
            ln.panel = False
    data, n_panels, n_inst = make_file(lines, LineString(pts), cams, corr)
    with open(out_bun, "wb") as f:
        f.write(data)
    info = {"name": name, "file": os.path.basename(out_bun), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "section": NUMBER, "pack": NUMBER, "panel": "XO_TRACKBARRIERPLAYER_1B_00",
            "legs": len(legs), "junction_lines": len(jl), "edge_lines": len(el), "panels": n_panels, "walls": len(lines),
            "collision_instances": n_inst, "route_m": round(along(pts)[-1], 1),
            "ring_m": round(sum(math.dist(l.a, l.b) for l in ring), 1),
            "edge_panels_m": round(sum(math.dist(l.a, l.b) for l in el if l.panel), 1),
            "legs_on_ring": len(on_ring), "legs_inside": len(within), "cameras": len(cams),
            "whole_road_added_m2": round(corr.area - own.area, 1),
            "farthest_junction_line_m": round(max((_crossing(l) for l in jl if l.leg is not None), default=0.0), 1),
            "closing_other_halves": sum(1 for l in jl if l.leg is None),
            "licence": "Map data (c) OpenStreetMap contributors (ODbL)"}
    with open(out_json, "w", newline="\n") as f:
        json.dump(info, f, indent=1)
    LAST.clear()
    LAST.update({"legs": legs, "lines": lines, "route": pts, "corridor": corr, "ring_area": RING_AREA[0], "own": own,
                 "inside_legs": within})
    return info


def build(out_bun=OUT_BUN, out_json=OUT_JSON):
    """The Time Attack's file (route 1: side legs up to its finish)."""
    keys, pts = route_points()
    return build_route(keys, pts, None, out_bun, out_json, "F-Town race barriers (route 1)")


def event_raised(ev, threshold=0.5):
    """raised(x, y) for an event: the route's height (as a car follows it on the built city, events.follow) at the
    route point nearest (x, y) is more than `threshold` above the built ground there (terrain.ground_z)."""
    from tools.citymap import events
    S, Z = events.follow(ev)
    line = LineString(ev["route"])

    def raised(x, y):
        s = line.project(Point(x, y))
        i = int(round((s - S[0]) / (S[1] - S[0]))) if len(S) > 1 else 0
        k = min(max(i, 0), len(Z) - 1)
        p = line.interpolate(S[k] - S[0])
        return bool(Z[k] > terrain.ground_z(p.x, p.y) + threshold)

    return raised


def build_events(evs=None, out_dir=None):
    """Every event's barrier file but the Time Attack's (build() makes that one): side legs all along the route (the
    ring closes the run-off past the finish too), panels only beside ground. [info] in the events' order (the Time
    Attack's None)."""
    from tools.citymap import events
    evs = evs or events.read()
    out_dir = out_dir or os.path.dirname(OUT_BUN)
    model = roadmodel.RoadModel.load(ROADS)
    out, last = [], {}
    for ev in evs:
        if ev["id"] == "timeattack":
            out.append(None)
            continue
        bun = os.path.join(out_dir, ev["barriers"])
        info = build_route(ev["keys"], [tuple(p) for p in ev["route"]], ev["length_m"] + 1.0, bun,
                           bun[:-4] + ".json", "F-Town race barriers (%s)" % ev["name"], event_raised(ev), model,
                           EVENT_LAST_D, ev)
        last[ev["id"]] = dict(LAST)
        out.append(info)
    LAST_EVENTS.clear()
    LAST_EVENTS.update(last)
    return out


def main():
    info = build()
    print(json.dumps(info, indent=1))
    for info in build_events():
        if info:
            print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
