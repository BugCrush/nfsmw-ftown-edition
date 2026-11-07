"""Task 3 (landmarks plan): the Delhi Metro Violet Line viaduct and its three stations.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_metro -v
"""
import json
import math
import os
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Point

from tools.citymap.tests import common
from tools.citymap.tests.test_landmarks import DETAILS, resolved


def built_metro():
    if "metro" not in common._cache:
        from tools.citymap import buildings, levels, metro
        common.need(DETAILS)
        with open(DETAILS, encoding="utf-8") as f:
            details = json.load(f)
        m = common.model()
        L = common._cache.get("levels") or levels.build(m)
        common._cache["levels"] = L
        outer = buildings.edge_box(common.proj(), (28.385, 77.305, 28.420, 77.332))
        lms = resolved()
        v = metro.viaduct(details, common.proj(), L, outer, stations=[lm.footprint for lm in lms if lm.kind == "station"])
        st = metro.stations([lm for lm in lms if lm.kind == "station"], v, L, details, common.proj(), set())
        common._cache["metro"] = (details, L, outer, v, st)
    return common._cache["metro"]


class Metro(unittest.TestCase):
    def test_piers_not_in_lanes(self):
        """No pier, portal leg, station column or stair stands in a carriageway (ground or raised, grown by 0.5 m):
        piers go on medians, verges and pavements; spans lengthen where there is none."""
        from tools.citymap import metro
        _d, L, _o, v, st = built_metro()
        lanes = shapely.union_all([L.ground_polygon, L.elevated]).buffer(metro.LANE_CLEAR)
        shapely.prepare(lanes)
        feet = [shapely.Polygon(p) for p in v.pier_boxes] + [shapely.Polygon(p) for s in st for p in s.columns] + \
            [shapely.Polygon(p) for s in st for p in s.stairs]
        bad = [f.centroid.coords[0] for f in feet if lanes.intersects(f)]
        spans = np.diff(sorted(v.pier_s))
        print("\n  %d piers (%d portal legs), %d station columns, %d stairs; longest span %.1f m, median %.1f m; "
              "in a lane: %d" % (len(v.pier_boxes), v.portal_legs, sum(len(s.columns) for s in st),
                                 sum(len(s.stairs) for s in st), spans.max(), float(np.median(spans)), len(bad)))
        self.assertEqual(bad, [])
        self.assertGreater(len(v.pier_boxes), 80)

    def test_clearance(self):
        """The deck's underside is at least 5 m above every road and deck below it (ground roads at 0, the flyovers
        by their profile), across its whole width every 2 m; the stations' undersides likewise."""
        from tools.citymap import levels
        _d, L, _o, v, st = built_metro()
        worst = 99.0
        n = 0
        for (x, y), zu in v.underside_samples():
            if L.ground_polygon.contains(Point(x, y)):
                worst = min(worst, zu - 0.0)
                n += 1
            if L.elevated.contains(Point(x, y)):
                worst = min(worst, zu - L.z_at(x, y))
                n += 1
        for s in st:
            pts = s.footprint.buffer(-0.5)
            x0, y0, x1, y1 = pts.bounds
            for x in np.arange(x0, x1, 2.0):
                for y in np.arange(y0, y1, 2.0):
                    if pts.contains(Point(x, y)):
                        if L.ground_polygon.contains(Point(x, y)):
                            worst = min(worst, s.underside)
                        if L.elevated.contains(Point(x, y)):
                            worst = min(worst, s.underside - L.z_at(x, y))
        print("\n  %d deck points over a road; least clearance %.2f m" % (n, worst))
        self.assertGreater(n, 50)
        self.assertGreaterEqual(worst, levels.CLEARANCE)

    def test_follows_osm(self):
        """The deck's centre line is the middle of OSM's two Violet Line tracks: every track point inside the area
        within half the tracks' spacing + 1 m of it, and every centre-line point within 1 m of the tracks' middle."""
        from tools.citymap import metro
        d, _L, outer, v, _st = built_metro()
        a, b = metro.tracks(d, common.proj(), outer)
        worst = 0.0
        for tr, other in ((a, b), (b, a)):
            s = 0.0
            while s < tr.length:
                p = tr.interpolate(s)
                sep = other.distance(p)
                worst = max(worst, v.centre.distance(p) - sep / 2)
                s += 5.0
        mid = 0.0
        s = 0.0
        while s < v.centre.length:
            c = v.centre.interpolate(s)
            pa = a.interpolate(a.project(c))
            pb = b.interpolate(b.project(c))
            mid = max(mid, math.dist(c.coords[0], ((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)))
            s += 5.0
        print("\n  centre line %.0f m; worst track point beyond half the spacing %.2f m; worst from the middle %.2f m"
              % (v.centre.length, worst, mid))
        self.assertGreater(v.centre.length, 3500)
        self.assertLess(worst, 1.0)
        self.assertLess(mid, 1.0)

    def test_stations_at_osm(self):
        """Each of the three stations stands on its OSM outline, the deck runs through it, and the OSM stop nodes of
        its name lie inside it."""
        d, _L, _o, v, st = built_metro()
        self.assertEqual(sorted(s.name for s in st), ["Bata Chowk", "Neelam Chowk Ajronda", "Old Faridabad"])
        stops = [(e["tags"]["name"], common.proj().to_render(e["lat"], e["lon"])) for e in d["elements"]
                 if e["type"] == "node" and e.get("tags", {}).get("railway") in ("stop", "station")]
        for s in st:
            self.assertTrue(v.centre.intersects(s.footprint), s.name)
            self.assertGreater(v.centre.intersection(s.footprint).length, 80.0, s.name)
            mine = [p for n, p in stops if n == s.name]
            self.assertTrue(mine, s.name)
            for p in mine:
                self.assertTrue(s.footprint.buffer(1.0).contains(Point(p)), s.name)
            self.assertGreater(len(s.part_tris()), 50, s.name)

    def test_route_still_drivable(self):
        """The stage 2 checks on the city file written with the metro: every road's centre line on a face, the first
        route on faces with no barrier across it, no barrier inside a road (tools/citymap/tests/test_city.py); and the
        metro's piers are in the written packs."""
        from tools.citymap.tests import test_city
        c = test_city.City("test_route_drivable")
        c.test_route_drivable()
        c.test_no_barrier_on_road()
        c.test_written_centrelines_drivable()
        _d, _L, _o, v, _st = built_metro()
        bars = test_city.all_barriers()
        tops = [round(b[3] - test_city._gz(b), 1) for b in bars]  # over the built ground (elevation, 2026-11-05)
        self.assertGreaterEqual(sum(1 for t in tops if t > 8.0), len(v.pier_boxes) * 4 - 4)


if __name__ == "__main__":
    unittest.main()
