"""F-Town's traffic spots (Task 2 of docs/superpowers/plans/2026-11-04-ftown-traffic-cars.md): kerb and lane spots on
ground-level roads away from junctions, clear of the built city's barriers, on flat ground at the city's ground level,
apart from each other and the spawns, the Time Attack route's flagged; the file FTownLoader reads, one spot a line.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_traffic_spots -v

Needs the road model, the route and the built city (ftown/ftown-city.bun); skips without them.
"""
import json
import math
import os
import random
import re
import unittest

from tools.citymap.tests import common

ROADS = os.path.join(common.AREA, "ftown-roads.json")
CITY = os.path.join(common.REPO, "ftown", "ftown-city.bun")
OUT = os.path.join(common.SCRATCH, "traffic")
# FTownLoader's rule for a spot line: '[' then six numbers (FTownTraffic.h ReadSpots)
C_LINE = re.compile(r"^\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(\d+)\s*,\s*(\d)\s*\]")


class TrafficSpotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(ROADS, common.ROUTE, CITY)
        from tools.citymap import race_barriers, roadmodel, traffic_spots
        cls.ts = traffic_spots
        os.makedirs(OUT, exist_ok=True)
        cls.path = os.path.join(OUT, "ftown-traffic.json")
        cls.spots, cls.counts = traffic_spots.build(cls.path)
        cls.model = roadmodel.RoadModel.load(ROADS)
        from tools.citymap import events
        cls.events = events.read()
        # Run J, item 5: the whole road (both halves of a divided road and the median) is the event's carriageway
        # (Run K, item 4: with the barriers' own `raised`, as traffic_spots.build)
        cls.corrs = [race_barriers.whole_road(cls.model, e["keys"], [tuple(p) for p in e["route"]], None, None,
                                              None if e["id"] == "timeattack" else race_barriers.event_raised(e))
                     for e in cls.events]
        cls.city = traffic_spots.City(CITY)

    def test_count_range(self):
        n = len(self.spots)
        self.assertTrue(150 <= n <= 4000, n)
        self.assertGreaterEqual(sum(1 for s in self.spots if not s.route), 30)
        self.assertTrue(any(s.kind == 0 for s in self.spots) and any(s.kind == 1 for s in self.spots))

    def test_spots_on_level0_roads_away_from_junctions(self):
        from shapely.geometry import LineString, Point
        roads = [r for r in self.model.roads if r.kind in self.ts.KINDS and r.level == 0 and not r.bridge]
        lines = [(LineString(r.points), r.width_m) for r in roads]
        junctions = [(n.x, n.y) for n in self.model.junctions().values()]
        # Run I fixes, item 1: the city's parking bays (where the street life's parked cars stood) are spots too, off
        # the carriageway at the markets and hospitals
        bays = [(x, y) for x, y, _h, _k, _r in self.ts.bays(os.path.join(os.path.dirname(CITY), "ftown-city.json"))]
        on_bay = 0
        for s in self.spots:
            p = Point(s.x, s.y)
            if any(math.dist((s.x, s.y), b) < 0.01 for b in bays):
                on_bay += 1
                continue
            self.assertTrue(any(ln.distance(p) <= w / 2 for ln, w in lines if ln.distance(p) < 20),
                            "spot %s not on a kept road's carriageway" % (s,))
            self.assertTrue(all(math.dist((s.x, s.y), j) >= self.ts.JUNCTION_CLEAR for j in junctions),
                            "spot %s near a junction" % (s,))
        print("\n  %d spots, %d of them in parking bays (of %d bays)" % (len(self.spots), on_bay, len(bays)), end="")
        self.assertGreater(on_bay, 100)

    def test_spot_footprints_clear_of_city_walls(self):
        from shapely.geometry import Polygon
        for s in self.spots:
            self.assertFalse(self.city.blocked(Polygon(self.ts.footprint(s.x, s.y, s.heading))), s)

    def test_spots_on_flat_ground(self):
        rng = random.Random(4)
        for s in rng.sample(self.spots, 50):
            hs = [self.city.height(x, y) for x, y in [(s.x, s.y)] + self.ts.footprint(s.x, s.y, s.heading, 0.0)]
            self.assertTrue(all(h is not None for h in hs), s)
            self.assertLessEqual(max(hs) - min(hs), 0.25 + 1e-6, s)
            # on the built ground (the elevation, 2026-11-05: terrain.ground_z)
            from tools.citymap import terrain
            self.assertAlmostEqual(hs[0], terrain.ground_z(s.x, s.y), delta=0.6)
            self.assertAlmostEqual(hs[0], s.z, delta=0.01)

    def test_spacing_and_spawns(self):
        pts = [(s.x, s.y) for s in self.spots]
        for i, a in enumerate(pts):
            for b in pts[i + 1:]:
                self.assertGreaterEqual(math.dist(a, b), 10.0 - 1e-6)
        starts = [tuple(e["start"][:2]) for e in self.events]
        for sp in self.ts.spawns() + starts:
            self.assertTrue(all(math.dist(sp, p) >= 40.0 for p in pts), sp)

    def test_route_flag(self):
        """Since the events: `route` holds bit k when the footprint comes within 5 m of event k's carriageway
        (ftown/ftown-events.json's order: 1 the Time Attack, 2 the Drag, 4 the Speed Trap, 8 the Sector Sprint)."""
        from shapely.geometry import Polygon
        nears = [c.buffer(5.0) for c in self.corrs]
        per = [0] * len(nears)
        for s in self.spots:
            poly = Polygon(self.ts.footprint(s.x, s.y, s.heading))
            want = sum(1 << k for k, near in enumerate(nears) if poly.intersects(near))
            self.assertEqual(s.route, want, s)
            for k in range(len(nears)):
                per[k] += bool(want >> k & 1)
        print("\n  spots by each event's route: %s" % per)
        self.assertTrue(all(n > 0 for n in per[:1] + per[2:]), per)

    def test_other_halves_flagged(self):
        """Run K, item 4: the rings now enclose divided roads whose halves OSM names differently, so the parked spots
        on those other halves are inside a race: Lal Bahadur Shastri Marg's far kerb beside route 1's westward stretch
        (screenshot 135) carries the Time Attack's bit, Mathura Road's beside the Speed Trap's ground stretch between the
        flyovers the Speed Trap's (before: route 0, a parked car inside the ring)."""
        want = {(1816.25, 8989.8): 1, (1856.2, 8991.71): 1, (1383.93, 8504.17): 4, (1381.08, 8544.07): 4}
        got = {}
        for s in self.spots:
            for (x, y), bit in want.items():
                if math.dist((s.x, s.y), (x, y)) < 0.05:
                    got[(x, y)] = s.route & bit
        self.assertEqual(got, want)

    def test_file_round_trip_and_line_format(self):
        with open(self.path, encoding="ascii") as f:
            text = f.read()
        data = json.loads(text)
        self.assertEqual(len(data["spots"]), len(self.spots))
        rows = [m.groups() for m in (C_LINE.match(line) for line in text.split("\n")) if m]
        self.assertEqual(len(rows), len(self.spots))
        back = self.ts.read(self.path)
        self.assertEqual([(s.x, s.y, s.route, s.kind) for s in back], [(s.x, s.y, s.route, s.kind) for s in self.spots])
        self.assertIn("OpenStreetMap", data["note"])

    def test_committed_file_is_this_build(self):
        committed = os.path.join(common.REPO, "ftown", "ftown-traffic.json")
        with open(committed, encoding="ascii") as f, open(self.path, encoding="ascii") as g:
            self.assertEqual(f.read(), g.read(), "ftown/ftown-traffic.json is not the tool's current output: rerun it")


if __name__ == "__main__":
    unittest.main()
