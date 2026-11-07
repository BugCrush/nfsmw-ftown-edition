"""The Time Attack's race barriers (Task 2 of docs/superpowers/plans/2026-11-04-ftown-game-mode.md): every side road
that meets the first route before the finish is closed by a line of Rockport's race-barrier panels and a wall within
its first 30 m, the route itself is never closed, and the file is one scenery section and one collision pack (1409)
that name X0's panel by hash only.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_race_barriers -v

Needs the road model (.superpowers/citymap/faridabad/ftown-roads.json), the route and the built city
(ftown/ftown-city.bun, for the edges over open ground); skips without them.
"""
import json
import math
import os
import struct
import unittest

from tools.citymap.tests import common

ROADS = os.path.join(common.AREA, "ftown-roads.json")
CITY = os.path.join(common.REPO, "ftown", "ftown-city.bun")
JSON = os.path.join(common.REPO, "ftown", "ftown-barriers.json")
OUT = os.path.join(common.SCRATCH, "barriers")
PANEL = 0x54A4FC3F  # XO_TRACKBARRIERPLAYER_1B_00
START = (3231.43, 12846.57)  # the route-start spawn (ftown/ftown-city.json)


class RaceBarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(ROADS, common.ROUTE, CITY)
        from tools.citymap import race_barriers
        cls.rb = race_barriers
        os.makedirs(OUT, exist_ok=True)
        cls.info = race_barriers.build(os.path.join(OUT, "ftown-barriers.bun"), os.path.join(OUT, "ftown-barriers.json"))
        cls.plan = race_barriers.LAST  # the legs, lines and route of that build
        with open(os.path.join(OUT, "ftown-barriers.bun"), "rb") as f:
            cls.data = f.read()

    def test_every_side_leg_blocked_within_30m(self):
        from shapely.geometry import LineString, Point
        legs, lines = self.plan["legs"], self.plan["lines"]
        self.assertGreater(len(legs), 40)
        worst = 0.0
        inside = {id(g) for g in self.plan["inside_legs"]}
        for leg in legs:
            path = LineString(leg.path)
            if id(leg) in inside:
                # Run J, item 5: a divided road's other half (or a gap in its median) leaving a route node lies inside
                # the whole road for its first 30 m: part of the road, closed by the ring where it leaves it
                self.assertTrue(self.plan["ring_area"].buffer(0.05).contains(path.interpolate(min(30.0, path.length))))
                continue
            best = None
            for ln in lines:
                if ln.kind != "junction" or ln.leg is not leg:
                    continue
                x = path.intersection(LineString([ln.a, ln.b]))
                if x.is_empty:
                    continue
                pts = [x] if x.geom_type == "Point" else list(getattr(x, "geoms", []))
                for p in pts:
                    d = path.project(Point(p.x, p.y))
                    best = d if best is None else min(best, d)
            self.assertIsNotNone(best, "side road %s at s=%.0f is not crossed by its barrier" % (leg.road_id, leg.s))
            self.assertLessEqual(best, 30.0 + 1e-6, "side road %s at s=%.0f closed at %.1f m" % (leg.road_id, leg.s,
                                                                                               best))
            worst = max(worst, best)
        print("\n  %d side roads closed, the farthest at %.1f m" % (len(legs), worst))
        # the review (Run J): five unnamed roads leaving Ambedkar Marg's other half were taken for that half (one
        # family, "~tertiary") and closed only by chance; they are side legs now
        self.assertTrue({172377539, 172383372, 1391506384, 1517410057, 1305937706} <= {g.road_id for g in legs})

    def test_route_never_closed(self):
        """No barrier line comes within 1 m of the route's carriageway, and the walls of the file read back cross
        neither the route's centre line nor its carriageway."""
        from shapely.geometry import LineString
        corridor = self.plan["corridor"]
        for ln in self.plan["lines"]:
            d = corridor.distance(LineString([ln.a, ln.b]))
            # Run I fixes: the ring on the kerb line, 1 m out, KERB_MIN where another road's lanes begin (no car fits)
            self.assertGreaterEqual(d, CLOSEST - 1e-6, "%s line at s=%.0f is %.2f m from the route" % (ln.kind, ln.s, d))
        centre = LineString(self.plan["route"])
        walls = self.rb.read_walls(self.data)
        self.assertEqual(len(walls), self.info["walls"])
        for a, b, lo, hi in walls:
            self.assertFalse(LineString([a, b]).intersects(centre), "a wall crosses the route at %s" % (a,))
            self.assertGreaterEqual(corridor.distance(LineString([a, b])), CLOSEST - 0.01)
            self.assertGreater(hi - lo, 20.0)

    def test_route_sealed(self):
        """Review: the barriers must close the route, not only cross each side road's centre line. Our walls alone (the
        file read back, the city's own walls ignored) are drawn on a 1 m grid; a flood from the route's centre line (4
        neighbours: a drawn wall is 8-connected, so it stops it) must stay within SEAL_REACH metres of the route's
        carriageway (a side road's pocket in front of its barrier is up to 30 m deep)."""
        import collections
        import numpy as np
        import shapely
        from shapely.geometry import LineString
        SEAL_REACH = 45.0
        walls = self.rb.read_walls(self.data)
        route = self.plan["route"]
        xs = [p[0] for p in route]
        ys = [p[1] for p in route]
        x0, y0 = min(xs) - 120.0, min(ys) - 120.0
        nx, ny = int(max(xs) + 120.0 - x0), int(max(ys) + 120.0 - y0)
        wall = np.zeros((ny, nx), bool)
        for a, b, _lo, _hi in walls:
            n = int(math.dist(a, b) / 0.2) + 2
            for k in range(n + 1):
                t = k / n
                wall[int(a[1] + (b[1] - a[1]) * t - y0), int(a[0] + (b[0] - a[0]) * t - x0)] = True
        seen = np.zeros_like(wall)
        q = collections.deque()
        centre = LineString(route)
        for k in range(0, int(centre.length), 2):
            p = centre.interpolate(k)
            c = (int(p.y - y0), int(p.x - x0))
            if not wall[c] and not seen[c]:
                seen[c] = True
                q.append(c)
        while q:
            r, c = q.popleft()
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < ny and 0 <= cc < nx and not seen[rr, cc] and not wall[rr, cc]:
                    seen[rr, cc] = True
                    q.append((rr, cc))
        rows, cols = np.nonzero(seen)
        inside = shapely.contains_xy(self.plan["corridor"].buffer(SEAL_REACH), cols + x0 + 0.5, rows + y0 + 0.5)
        out = int((~inside).sum())
        print("\n  the flood from the route: %d cells, %d farther than %.0f m from the carriageway" % (
            len(rows), out, SEAL_REACH))
        self.assertEqual(out, 0, "the route is not sealed: the flood leaves it (first at x %.0f, y %.0f)" % (
            (cols[~inside][0] + x0, rows[~inside][0] + y0) if out else (0, 0)))

    def test_file_reads_back(self):
        from world import collision, scenery
        from chunks import read_chunks
        sections, packs, kinds = [], [], set()
        panels = 0
        for c, p in scenery.with_positions(read_chunks(self.data), 0):
            kinds.add(c.id)
            if c.id == scenery.SCENERY_SECTION:
                sc = scenery.read_scenery(c, p)
                sections.append(sc.number)
                for inst in sc.instances:
                    self.assertEqual(sc.infos[inst.info_index].solid_hashes, (PANEL, 0, 0, 0))
                    panels += 1
            elif c.id == 0x3B801:
                packs.append(collision.read_pack(c.data, p).section)
        self.assertEqual(kinds - {0}, {scenery.SCENERY_SECTION, 0x3B801})  # no solids, no textures
        self.assertEqual((sections, packs), ([1409], [1409]))
        self.assertEqual(panels, self.info["panels"])

    def test_counts_in_json(self):
        """ftown/ftown-barriers.json (committed) describes the file this build makes."""
        with open(JSON) as f:
            committed = json.load(f)
        for k in ("bytes", "sha256", "panels", "walls", "legs", "junction_lines", "edge_lines", "section", "pack",
                  "legs_on_ring"):
            self.assertEqual(committed[k], self.info[k], k)

    def test_start_clear(self):
        """No wall where the car is put down at the route-start spawn: every line farther from it than a car's half
        diagonal (4.5 x 1.8 m: 2.42 m) with room to spare (the nearest is the expressway's barrier beside the ramp)."""
        from shapely.geometry import LineString, Point
        for ln in self.plan["lines"]:
            self.assertGreater(LineString([ln.a, ln.b]).distance(Point(START)), 2.6)

    def test_markers_point_the_way(self):
        """Run I's items 5 and 10 (markers_report)."""
        markers_report(self, self.data, self.plan, "route 1")

    def test_edge_panels_off_the_lanes(self):
        """No edge panel stands in a drawn carriageway (run I: half the panels stood in a lane, 3 m out from the
        route's own carriageway in another road's)."""
        n, inside = _edge_panels_in_lanes(self.rb, self.plan)
        print("\n  route 1: %d edge panels, %d in a lane" % (n, inside), end="")
        self.assertLessEqual(inside, 0.02 * n)

    def test_whole_road_on_divided_roads(self):
        """Run J, item 5 ("they only allow me to drive on my side of the traffic. i want the full road"): on route 1's
        divided stretches (Ambedkar Marg, LBS Marg) no wall of the file stands between the route and the other half."""
        n, bad = _divided_crossings(self.rb, self.data, self.plan["route"], route_keys(self.rb))
        print("\n  route 1: %d points beside a divided road's other half, %d walled off from it" % (n, bad), end="")
        self.assertGreater(n, 100)
        self.assertEqual(bad, 0)

    def test_full_width_between_the_barriers(self):
        """Run K, item 4 (screenshot 135, render (1846, 8982), the westward stretch to Mathura Road: chevrons halfway
        across the road): at every route point beside a divided road's other half, judged from the carriageways alone
        (full_width), no wall between the halves."""
        n, bad = full_width(self.rb, self.data, self.plan["route"], route_keys(self.rb))
        _report_full_width(self, "route 1", n, bad)
        self.assertGreater(n, 150)

    def test_panels_on_their_lines(self):
        """A panel every 8 m at most along each line, across its whole length."""
        for ln in [l for l in self.plan["lines"] if l.panel and math.dist(l.a, l.b) >= self.rb.SLIVER]:
            n = len(self.rb.panels([ln]))
            self.assertGreaterEqual(n * self.rb.PANEL_W, math.dist(ln.a, ln.b) - 1e-6)



CLOSEST = 0.3  # race_barriers.KERB_MIN - RING_TOL: a barrier's least distance from the route's carriageway
SPEEDCAM = 0xD18402DA  # XO_PHOTORADAR_1B_MD_00, Rockport's photo radar (tools/citymap/x0props.json)


def _instances(data):
    """[(solid hash, 4 x 4 matrix)] of every scenery instance of a barrier file."""
    import numpy as np
    from chunks import read_chunks
    from world import scenery
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id == scenery.SCENERY_SECTION:
            sc = scenery.read_scenery(c, p)
            out += [(sc.infos[i.info_index].solid_hashes[0], np.array(i.matrix, float)) for i in sc.instances]
    return out


def _travel(route, x, y):
    """(nearest route point, unit travel direction there) for a point."""
    from shapely.geometry import LineString, Point
    ln = route if hasattr(route, "project") else LineString(route)
    s = ln.project(Point(x, y))
    a, b = ln.interpolate(max(0.0, s - 2.0)), ln.interpolate(min(ln.length, s + 2.0))
    t = (b.x - a.x, b.y - a.y)
    L = math.hypot(*t) or 1.0
    q = ln.interpolate(s)
    return (q.x, q.y), (t[0] / L, t[1] / L)


def markers_report(case, data, plan, name, raised=None):
    """Run I's items 5 and 10, checked on a written barrier file (route 1's or an event's): every chevron panel's
    arrow (its model x axis) within 60 degrees of the travel direction where its line runs along the route, its drawn
    face (model -y: the panel is single-sided, docs/ftown-notes.md "Run I fixes") towards the route; panels along each
    line abut (scaled to the line, none overlapping); edge panels on the kerb line, at most 1.2 m outside the route's
    carriageway and never nearer than CLOSEST (KERB_MIN less RING_TOL: beside another road's lanes); an edge piece without panels has a wall of the city 2 m or longer behind it, or stands beside a raised
    part of the route (the gaps: run I's dashed rows and the tree trunks counted as walls)."""
    import numpy as np
    from shapely.geometry import LineString, Point
    rb = case.rb
    route = LineString(plan["route"])
    corr = plan["corridor"]
    bad_dir, bad_face, along = 0, 0, 0
    for h, m in _instances(data):
        if h != PANEL:
            continue
        x, y = m[3][0], m[3][1]
        q, t = _travel(route, x, y)
        arrow = m[0][:2] / (np.linalg.norm(m[0][:2]) or 1.0)
        front = -m[1][:2] / (np.linalg.norm(m[1][:2]) or 1.0)
        if np.dot(front, (q[0] - x, q[1] - y)) <= 0:
            bad_face += 1
        if abs(np.dot(arrow, t)) >= 0.5:
            along += 1
            if np.dot(arrow, t) < 0.5:
                bad_dir += 1
    walls = [LineString(w) for w in rb.city_walls() if math.dist(*w) >= rb.WALL_MIN]
    from shapely.strtree import STRtree
    tree = STRtree(walls)
    gaps, dists, overlap = 0, [], 0
    for ln in plan["lines"]:
        if ln.kind != "edge":
            continue
        L = math.dist(ln.a, ln.b)
        mx, my = (ln.a[0] + ln.b[0]) / 2, (ln.a[1] + ln.b[1]) / 2
        if ln.panel:
            if math.dist((mx, my), plan["route"][0]) > rb.START_KEEP:  # (the room left round the car's start)
                dists.append(corr.distance(Point(mx, my)))
            pans = rb.panels([ln], route)
            overlap += L >= rb.SLIVER and abs(sum(p[4] for p in pans) * rb.PANEL_W - L) > 0.01
            continue
        if raised is not None and raised(mx, my):
            continue
        if any(math.dist((mx, my), m[3][:2]) < rb.CAM_GAP + rb.PANEL_W for h, m in _instances(data) if h == SPEEDCAM):
            continue  # the row opens round a speed camera (item 8)
        nx, ny = -(ln.b[1] - ln.a[1]) / (L or 1.0), (ln.b[0] - ln.a[0]) / (L or 1.0)
        if plan["ring_area"].contains(Point(mx + nx * 0.5, my + ny * 0.5)):
            nx, ny = -nx, -ny  # outward: out of the ring's region
        ray = LineString([(mx, my), (mx + nx * rb.OPEN_BEHIND, my + ny * rb.OPEN_BEHIND)])
        if not any(walls[i].intersects(ray) for i in tree.query(ray)):
            gaps += 1
    dists = np.array(dists)
    print("\n  %s: %d panels along the route, %d pointing back, %d facing away; %d open edge pieces without panels; "
          "edge panels %.2f..%.2f m from the carriageway; %d lines not covered exactly" % (
              name, along, bad_dir, bad_face, gaps, dists.min(), dists.max(), overlap), end="")
    case.assertGreater(along, 20, name)
    case.assertEqual(bad_dir, 0, name)
    case.assertEqual(bad_face, 0, name)
    case.assertEqual(gaps, 0, name)
    case.assertEqual(overlap, 0, name)
    # the review (2026-11-05): no sliver panels (a squashed chevron, two draws for little), every panel a rotation
    # standing 0.234-6.043 m over the ground, and no card (its centre +- 4 m x scale along its arrow) nearer the
    # carriageway than 0.1 m
    from tools.citymap import terrain
    thin = bad_roll = near = 0
    for h, m in _instances(data):
        if h != PANEL:
            continue
        sx = float(np.linalg.norm(m[0][:3]))
        thin += sx < rb.SLIVER / rb.PANEL_W - 1e-6
        R = m[:3, :3]
        zs = [float(m[3][2] + z * R[2][2]) - terrain.ground_z(m[3][0], m[3][1]) for z in (0.234, 6.043)]
        bad_roll += np.linalg.det(R) <= 0 or abs(min(zs) - 0.234) > 0.02 or abs(max(zs) - 6.043) > 0.02
        ax = m[0][:2] / (np.linalg.norm(m[0][:2]) or 1.0) * 4.0 * sx
        card = LineString([(m[3][0] - ax[0], m[3][1] - ax[1]), (m[3][0] + ax[0], m[3][1] + ax[1])])
        near += corr.distance(card) < 0.1
    print("  %d sliver panels, %d not rolled right, %d cards nearer than 0.1 m" % (thin, bad_roll, near), end="")
    case.assertEqual(thin, 0, name)
    case.assertEqual(bad_roll, 0, name)
    case.assertEqual(near, 0, name)
    case.assertGreaterEqual(dists.min(), CLOSEST - 1e-6, name)
    case.assertLessEqual(dists.max(), 1.2 + 1e-6, name)


def _edge_panels_in_lanes(rb, plan):
    """(edge panels, those whose centre lies in a drawn ground carriageway (the levels' ground roads), farther than
    KERB_MIN from the route's own)."""
    import shapely
    from shapely.geometry import LineString, Point
    from tools.citymap import levels
    if "lanes" not in common._cache:
        L = levels.build(common.model())
        # (a panel stands on the ground: a deck over it is no lane; 10 cm in from a lane's edge: a panel on the
        # edge of a carved lane is beside it)
        common._cache["lanes"] = L.ground_polygon.buffer(-0.1)
        shapely.prepare(common._cache["lanes"])
    lanes = common._cache["lanes"]
    route = LineString(plan["route"])
    pans = rb.panels([ln for ln in plan["lines"] if ln.kind == "edge"], route)
    # (on the line between a divided road's halves a panel stands KERB_MIN into the other half's drawn polygon)
    near = plan["corridor"].buffer(rb.KERB_MIN + 0.05)
    return len(pans), sum(1 for p in pans if lanes.contains(Point(p[0], p[1])) and not near.contains(Point(p[0], p[1])))


def route_keys(rb):
    return rb.route_points()[0]


def _divided_crossings(rb, data, route, keys, step=10.0):
    """Run J, item 5, on a written barrier file: (points every `step` m of the route on one half of a divided road
    with the other half beside it (at most furniture.PAIR_GAP apart edge to edge, running the other way), those whose
    straight line to the other half's centre crosses a wall of the file). Run I's files wall every one off (the ring
    stood on the kerb between the halves)."""
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    from tools.citymap import furniture, roadmodel
    if "roads_model" not in common._cache:
        common._cache["roads_model"] = roadmodel.RoadModel.load(ROADS)
    model = common._cache["roads_model"]
    tw = rb.twins(model)
    seg = rb.route_segments(model, keys)
    walls = [LineString([a, b]) for a, b, _lo, _hi in rb.read_walls(data)]
    tree = STRtree(walls)
    n = bad = 0
    for (ka, kb), a, b in zip(zip(keys, keys[1:]), route, route[1:]):
        r = seg.get((ka, kb))
        if r is None or r.id not in tw:
            continue
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / (L or 1.0), (b[1] - a[1]) / (L or 1.0))
        s = step / 2
        while s < L:
            p = (a[0] + u[0] * s, a[1] + u[1] * s)
            s += step
            for t in tw[r.id]:
                tl = LineString(t.points)
                sp = tl.project(Point(p))
                pp = tl.interpolate(sp)
                ahead = tl.interpolate(min(tl.length, sp + 2.0))
                behind = tl.interpolate(max(0.0, sp - 2.0))
                d = (ahead.x - behind.x, ahead.y - behind.y)
                if Point(p).distance(pp) > r.width_m / 2 + t.width_m / 2 + furniture.PAIR_GAP or (
                        d[0] * u[0] + d[1] * u[1] > -0.8 * math.hypot(*d)) or sp < 1e-6 or sp > tl.length - 1e-6:
                    continue
                n += 1
                gap = LineString([p, (pp.x, pp.y)])
                bad += any(walls[i].intersects(gap) for i in tree.query(gap))
                break
    return n, bad


FULL_STEP = 5.0  # m between the route points full_width samples
FULL_REACH = 40.0  # m each side of the route the cross line looks for carriageways
FULL_PARALLEL = 0.9  # |cos| from which another road's carriageway runs along the route at a point
FULL_KERB = 0.3  # CLOSEST: a wall may stand this far into the span's ends (the ring between two roads' lanes)


def full_width(rb, data, route, keys, raised=None, step=FULL_STEP, ends=10.0):
    """Run K, item 4 ("the guidance line here is again covering half the road and not the full road"), on a written
    barrier file, from the road model's carriageways alone (not race_barriers.twins: run K's half road was a pair the
    twins missed, so a test through them could not see it). At every route point `step` m apart on the ground (more than
    `ends` from the route's ends): the line across the route there; on it the carriageways of the ground roads running
    along the route (|cos| >= FULL_PARALLEL), each its centre +- half its width; the span is the route's own carriageway
    and, joined while the gap is at most furniture.PAIR_GAP, every one-way carriageway beside it running the other way
    (a divided road's other half, the expressway's left out: crash walls stand between its halves). No wall of the file
    may cross the span (FULL_KERB in from its ends). Points where `raised` says the route is on a ramp or deck are left
    out (a ground road beside a ramp is no other half: the ramp's edge keeps its wall). Returns (points, [(s, x, y,
    span width, other halves) of each point walled]), s along the route."""
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    from tools.citymap import furniture, roadmodel
    if "roads_model" not in common._cache:
        common._cache["roads_model"] = roadmodel.RoadModel.load(ROADS)
    model = common._cache["roads_model"]
    if "full_width_tree" not in common._cache:
        ground = [r for r in model.roads if r.level == 0]
        common._cache["full_width_tree"] = (ground, [LineString(r.points) for r in ground])
    ground, glines = common._cache["full_width_tree"]
    gtree = STRtree(glines)
    seg = rb.route_segments(model, keys)
    walls = [LineString([a, b]) for a, b, _lo, _hi in rb.read_walls(data)]
    wtree = STRtree(walls)
    total = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    n, bad, s0 = 0, [], 0.0
    for (ka, kb), a, b in zip(zip(keys, keys[1:]), route, route[1:]):
        r = seg.get((ka, kb))
        L = math.dist(a, b)
        if r is None or r.level != 0 or L < 1e-6:
            s0 += L
            continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        nrm = (-u[1], u[0])
        s = (step - s0 % step) % step
        while s < L:
            sr = s0 + s
            p = (a[0] + u[0] * s, a[1] + u[1] * s)
            s += step
            if sr < ends or sr > total - ends or (raised is not None and raised(*p)):
                continue
            cross = LineString([(p[0] - nrm[0] * FULL_REACH, p[1] - nrm[1] * FULL_REACH),
                                (p[0] + nrm[0] * FULL_REACH, p[1] + nrm[1] * FULL_REACH)])
            spans = []  # (lo, hi, kind): kind "own", "opp" (one-way the other way), "other"
            for i in gtree.query(cross):
                t, tl = ground[i], glines[i]
                x = tl.intersection(cross)
                for q in ([x] if x.geom_type == "Point" else [g for g in getattr(x, "geoms", []) if g.geom_type == "Point"]):
                    st = tl.project(q)
                    h1, h0 = tl.interpolate(min(tl.length, st + 1.0)), tl.interpolate(max(0.0, st - 1.0))
                    d = (h1.x - h0.x, h1.y - h0.y)
                    dl = math.hypot(*d) or 1.0
                    c = (d[0] * u[0] + d[1] * u[1]) / dl
                    if abs(c) < FULL_PARALLEL:
                        continue
                    o = (q.x - p[0]) * nrm[0] + (q.y - p[1]) * nrm[1]
                    kind = "own" if t.id == r.id else (
                        "opp" if t.oneway and c < -0.8 and t.name not in furniture.SKIP_NAMES else "other")
                    spans.append((o - t.width_m / 2, o + t.width_m / 2, kind))
            own = [sp for sp in spans if sp[2] == "own" and sp[0] <= 0.0 <= sp[1]]
            if not own:
                continue
            lo, hi = min(sp[0] for sp in own), max(sp[1] for sp in own)
            # the other half: the nearest one-way carriageway the other way within PAIR_GAP, edge to edge (one only:
            # a service road beyond it, Mathura Road's, is another road)
            near = [(max(sl - hi, lo - sh), sl, sh) for sl, sh, kind in spans if kind == "opp"]
            near = [g for g in near if g[0] <= furniture.PAIR_GAP]
            if not near:
                continue  # (a road with no other half beside it here: the ring on its kerbs, the earlier tests)
            _gap, sl, sh = min(near)
            lo, hi, halves = min(lo, sl), max(hi, sh), 1
            n += 1
            span = LineString([(p[0] + nrm[0] * (lo + FULL_KERB), p[1] + nrm[1] * (lo + FULL_KERB)),
                               (p[0] + nrm[0] * (hi - FULL_KERB), p[1] + nrm[1] * (hi - FULL_KERB))])
            if any(walls[i].intersects(span) for i in wtree.query(span)):
                bad.append((round(sr, 1), round(p[0], 1), round(p[1], 1), round(hi - lo, 1), halves))
        s0 += L
    return n, bad


def _report_full_width(case, name, n, bad):
    print("\n  %s: %d route points beside a divided road's other half (from the carriageways), %d walled off%s" % (
        name, n, len(bad), (": first " + ", ".join("s %.0f (%.0f, %.0f) %.1f m" % b[:4] for b in bad[:6])) if bad else ""),
        end="")
    case.assertEqual(bad, [], name)


def _flood_escapes(walls, route, corridor, reach=45.0):
    """test_route_sealed's flood over `walls` alone from the route's centre line: the cells it reaches farther than
    `reach` from the carriageway (0 when sealed)."""
    import collections
    import numpy as np
    import shapely
    from shapely.geometry import LineString
    xs = [p[0] for p in route]
    ys = [p[1] for p in route]
    x0, y0 = min(xs) - 120.0, min(ys) - 120.0
    nx, ny = int(max(xs) + 120.0 - x0), int(max(ys) + 120.0 - y0)
    wall = np.zeros((ny, nx), bool)
    for a, b, _lo, _hi in walls:
        n = int(math.dist(a, b) / 0.2) + 2
        for k in range(n + 1):
            t = k / n
            wall[int(a[1] + (b[1] - a[1]) * t - y0), int(a[0] + (b[0] - a[0]) * t - x0)] = True
    seen = np.zeros_like(wall)
    q = collections.deque()
    centre = LineString(route)
    for k in range(0, int(centre.length), 2):
        p = centre.interpolate(k)
        c = (int(p.y - y0), int(p.x - x0))
        if not wall[c] and not seen[c]:
            seen[c] = True
            q.append(c)
    while q:
        r, c = q.popleft()
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < ny and 0 <= cc < nx and not seen[rr, cc] and not wall[rr, cc]:
                seen[rr, cc] = True
                q.append((rr, cc))
    rows, cols = np.nonzero(seen)
    inside = shapely.contains_xy(corridor.buffer(reach), cols + x0 + 0.5, rows + y0 + 0.5)
    return int((~inside).sum()), len(rows)


class EventBarrierTests(unittest.TestCase):
    """Each event's own barrier file (docs/superpowers/plans/2026-11-04-ftown-events.md Task 2): the same rules as
    route 1's, for the Drag, the Speed Trap and the Sector Sprint (side legs all along the route, the run-off sealed
    too), no panel beside a ramp or deck, the json committed beside each file."""

    @classmethod
    def setUpClass(cls):
        common.need(ROADS, common.ROUTE, CITY, os.path.join(common.REPO, "ftown", "ftown-events.json"))
        from tools.citymap import events, race_barriers
        cls.rb = race_barriers
        cls.events = [e for e in events.read() if e["id"] != "timeattack"]
        cls.out = os.path.join(common.SCRATCH, "barriers-events")
        os.makedirs(cls.out, exist_ok=True)
        cls.infos = [i for i in race_barriers.build_events(events.read(), cls.out) if i]
        cls.plans = dict(race_barriers.LAST_EVENTS)
        cls.data = {}
        for e in cls.events:
            with open(os.path.join(cls.out, e["barriers"]), "rb") as f:
                cls.data[e["id"]] = f.read()

    def test_three_files(self):
        self.assertEqual([e["barriers"] for e in self.events],
                         ["ftown-barriers-drag.bun", "ftown-barriers-speedtrap.bun", "ftown-barriers-sprint.bun"])
        for info in self.infos:
            self.assertEqual((info["section"], info["pack"]), (1409, 1409))
            self.assertLessEqual(info["collision_instances"], 255)

    def test_side_legs_blocked_and_route_open(self):
        from shapely.geometry import LineString, Point
        for e in self.events:
            plan = self.plans[e["id"]]
            inside = {id(g) for g in plan["inside_legs"]}
            for leg in plan["legs"]:
                path = LineString(leg.path)
                if id(leg) in inside:  # (Run J, item 5: a divided road's other half, inside the whole road)
                    self.assertTrue(plan["ring_area"].buffer(0.05).contains(
                        path.interpolate(min(self.rb.EVENT_LAST_D, path.length))), e["id"])
                    continue
                best = None
                for ln in plan["lines"]:
                    if True:  # any line of the file closes it (a ring piece is filed under the first leg it crosses)
                        x = path.intersection(LineString([ln.a, ln.b]))
                        for p in ([x] if x.geom_type == "Point" else list(getattr(x, "geoms", []))):
                            d = path.project(Point(p.x, p.y))
                            best = d if best is None else min(best, d)
                if best is None:
                    # a slip road beside a flyover's ramp (Mathura Road, 752874850) lies inside the ring all along
                    # it: a pocket of the sealed route (test_sealed), nothing to close
                    self.assertTrue(plan["corridor"].buffer(self.rb.RING_OFFSET).contains(path),
                                    "%s: side road %s not closed" % (e["id"], leg.road_id))
                    continue
                self.assertLessEqual(best, self.rb.EVENT_LAST_D + 1e-6, "%s: side road %s closed at %.1f m" % (e["id"], leg.road_id, best))
            for ln in plan["lines"]:
                self.assertGreaterEqual(plan["corridor"].distance(LineString([ln.a, ln.b])), CLOSEST - 1e-6, e["id"])
            centre = LineString(e["route"])
            for a, b, _lo, hi in self.rb.read_walls(self.data[e["id"]]):
                self.assertFalse(LineString([a, b]).intersects(centre), "%s: a wall across the route" % e["id"])
                # 30 m above the built ground (the elevation, 2026-11-05), above every deck (Mathura Road's are 7 m)
                from tools.citymap import terrain
                self.assertGreaterEqual(hi, max(terrain.ground_z(*a), terrain.ground_z(*b)) + 30.0 - 0.01)
            print("\n  %s: %d side roads closed, %d walls" % (e["id"], len(plan["legs"]), len(plan["lines"])))

    def test_sealed(self):
        for e in self.events:
            plan = self.plans[e["id"]]
            out, cells = _flood_escapes(self.rb.read_walls(self.data[e["id"]]), e["route"], plan["corridor"])
            print("\n  %s: the flood reaches %d cells, %d farther than 45 m" % (e["id"], cells, out))
            self.assertEqual(out, 0, e["id"])

    def test_start_clear(self):
        from shapely.geometry import LineString, Point
        for e in self.events:
            for ln in self.plans[e["id"]]["lines"]:
                self.assertGreater(LineString([ln.a, ln.b]).distance(Point(e["start"][:2])), 2.6, e["id"])

    def test_no_panel_beside_a_deck(self):
        """The Speed Trap's flyovers: every ring piece beside a raised part of the route is a wall only."""
        e = [v for v in self.events if v["id"] == "speedtrap"][0]
        raised = self.rb.event_raised(e)
        lines = self.plans["speedtrap"]["lines"]
        up = [ln for ln in lines if raised((ln.a[0] + ln.b[0]) / 2, (ln.a[1] + ln.b[1]) / 2)]
        self.assertGreater(len(up), 100)
        self.assertFalse([ln for ln in up if ln.panel])

    def test_markers_point_the_way(self):
        for e in self.events:
            markers_report(self, self.data[e["id"]], self.plans[e["id"]], e["id"], self.rb.event_raised(e))

    def test_whole_road_on_divided_roads(self):
        """Run J, item 5: the Speed Trap's Mathura Road stretches enclose both halves (the Drag's expressway has crash
        walls between its halves, the Sector Sprint no divided road: none there)."""
        for e in self.events:
            n, bad = _divided_crossings(self.rb, self.data[e["id"]], [tuple(p) for p in e["route"]], e["keys"])
            print("\n  %s: %d points beside a divided road's other half, %d walled off from it" % (e["id"], n, bad),
                  end="")
            if e["id"] == "speedtrap":
                self.assertGreater(n, 50)
            self.assertEqual(bad, 0, e["id"])

    def test_full_width_between_the_barriers(self):
        """Run K, item 4, for every event's route (full_width: from the carriageways alone)."""
        for e in self.events:
            n, bad = full_width(self.rb, self.data[e["id"]], [tuple(p) for p in e["route"]], e["keys"],
                                self.rb.event_raised(e))
            _report_full_width(self, e["id"], n, bad)
            if e["id"] == "speedtrap":
                self.assertGreater(n, 200)

    def test_edge_panels_off_the_lanes(self):
        for e in self.events:
            n, inside = _edge_panels_in_lanes(self.rb, self.plans[e["id"]])
            print("\n  %s: %d edge panels, %d in a lane" % (e["id"], n, inside), end="")
            self.assertLessEqual(inside, 0.02 * n, e["id"])

    def test_speedtrap_cameras(self):
        """Item 8 (the road side): Rockport's photo radar at each Speed Trap camera gate (one within 15 m of each
        gate, beside the route, facing the car that comes), in the Speed Trap's file only."""
        import numpy as np
        from shapely.geometry import LineString, Point
        for e in self.events:
            cams = [m for h, m in _instances(self.data[e["id"]]) if h == SPEEDCAM]
            gates = [g for g in e["gates"] if g["type"] == "camera"]
            if e["id"] != "speedtrap":
                self.assertEqual(cams, [], e["id"])
                continue
            self.assertEqual(len(cams), len(gates))
            route = LineString(e["route"])
            for g in gates:
                near = [m for m in cams if math.dist(m[3][:2], (g["x"], g["y"])) < 15.0]
                self.assertEqual(len(near), 1, g)
                m = near[0]
                dc = self.plans[e["id"]]["corridor"].distance(Point(m[3][0], m[3][1]))
                if self.rb.event_raised(e)(g["x"], g["y"]):
                    self.assertLess(dc, 0.1)  # on a deck: on its edge
                else:
                    self.assertGreater(dc, 0.3)  # on the ground: on the kerb
                # its lens (model -y) towards the cars that come: against the travel direction
                _q, t = _travel(route, m[3][0], m[3][1])
                self.assertLess(float(np.dot(-m[1][:2], t)), -0.9)
                print("\n  camera at s %.0f: %.1f m from the gate, %.1f m off the centre line, z %.2f" % (
                    g["s"], math.dist(m[3][:2], (g["x"], g["y"])), route.distance(Point(m[3][0], m[3][1])),
                    m[3][2]), end="")

    def test_counts_in_json(self):
        for e, info in zip(self.events, self.infos):
            with open(os.path.join(common.REPO, "ftown", e["barriers"][:-4] + ".json")) as f:
                committed = json.load(f)
            for k in ("bytes", "sha256", "panels", "walls", "legs", "junction_lines", "edge_lines", "legs_on_ring"):
                self.assertEqual(committed[k], info[k], "%s %s" % (e["id"], k))


if __name__ == "__main__":
    unittest.main()
