"""Task 1: the projection and the road model (our own data, kept for later stages).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_roadmodel -v
"""
import collections
import json
import math
import os
import random
import unittest

from tools.citymap.tests import common


def haversine(a, b, R=6371008.8):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


class Projection(unittest.TestCase):
    def test_projection_accuracy(self):
        from tools.citymap import geo
        p = geo.Projection()
        rng = random.Random(1)
        worst = 0.0
        for _ in range(1000):
            a = (rng.uniform(28.385, 28.420), rng.uniform(77.305, 77.332))
            b = (rng.uniform(28.385, 28.420), rng.uniform(77.305, 77.332))
            h = haversine(a, b)
            if h < 50:
                continue
            xa, ya = p.to_render(*a)
            xb, yb = p.to_render(*b)
            worst = max(worst, abs(math.hypot(xb - xa, yb - ya) - h) / h)
        print("\n  projection: worst relative error %.5f%% over 1,000 pairs" % (worst * 100))
        self.assertLess(worst, 0.001)

    def test_centre_and_axes(self):
        from tools.citymap import geo
        p = geo.Projection()
        x, y = p.to_render(28.4025, 77.3185)
        self.assertAlmostEqual(x, 2000.0, places=6)
        self.assertAlmostEqual(y, 9068.0, places=6)  # (11500 before the connection's move, geo.SHIFT)
        xn, yn = p.to_render(28.4125, 77.3185)
        self.assertGreater(yn, y + 1000)  # north = render +y
        xe, ye = p.to_render(28.4025, 77.3285)
        self.assertGreater(xe, x + 900)  # east = render +x
        la, lo = p.to_latlon(*p.to_render(28.41461, 77.33109))
        self.assertAlmostEqual(la, 28.41461, places=9)
        self.assertAlmostEqual(lo, 77.33109, places=9)


class RoadModel(unittest.TestCase):
    def test_kinds_kept_and_dropped(self):
        from tools.citymap import roadmodel
        m = common.model()
        kinds = collections.Counter(r.kind for r in m.roads)
        osm_kinds = collections.Counter(e["tags"]["highway"] for e in common.osm()["elements"]
                                        if e["type"] == "way" and "highway" in e.get("tags", {}))
        print("\n  kept:", dict(kinds))
        print("  dropped:", {k: v for k, v in osm_kinds.items() if k not in roadmodel.KEPT})
        for k in ("footway", "path", "steps", "track", "cycleway", "pedestrian"):
            self.assertNotIn(k, kinds)
        for k, n in osm_kinds.items():
            if k in roadmodel.KEPT:
                self.assertEqual(kinds[k], n, k)  # every kept way of the data is in the model
        self.assertGreater(sum(kinds.values()), 1400)

    def test_widths(self):
        m = common.model()
        for r in m.roads:
            self.assertGreater(r.width_m, 3.0, r.id)
            if r.kind in ("residential", "unclassified") and r.lanes_tagged is None:
                self.assertEqual(r.width_m, 5.5)
            if r.kind in ("living_street", "service") and r.lanes_tagged is None:
                self.assertEqual(r.width_m, 4.0)
            if r.kind.endswith("_link") and r.lanes_tagged is None:
                self.assertEqual(r.width_m, 4.5)
            if r.kind == "tertiary" and r.lanes_tagged is None:
                self.assertEqual(r.width_m, 8.0)  # 2 lanes of 3.5 + a 0.5 m shoulder each side
            if r.kind in ("motorway", "trunk") and r.oneway and r.lanes_tagged is None:
                self.assertEqual(r.width_m, 11.5)
            if r.lanes_tagged is not None and r.kind in ("residential", "service", "living_street"):
                self.assertEqual(r.width_m, 3.5 * r.lanes_tagged)

    def test_junctions_shared(self):
        m = common.model()
        j = m.junctions()
        ways_at = collections.Counter()
        for r in m.roads:
            for k in set(r.keys):
                ways_at[k] += 1
        expect = {k for k, n in ways_at.items() if n >= 2}
        print("\n  junction nodes (shared by 2+ kept roads): %d of %d nodes" % (len(j), len(m.nodes)))
        self.assertEqual(set(j), expect)
        for k in j:
            n = m.nodes[k]
            self.assertGreaterEqual(len(set(n.road_ids)), 2)
            for rid in n.road_ids:
                r = m.road(rid)
                i = r.keys.index(k)
                self.assertAlmostEqual(r.points[i][0], n.x, places=6)
                self.assertAlmostEqual(r.points[i][1], n.y, places=6)
        self.assertGreater(len(j), 1000)

    def test_route_length(self):
        common.need(common.ROUTE)
        with open(common.ROUTE) as f:
            pts = json.load(f)["points"]
        p = common.proj()
        xy = [p.to_render(a, b) for a, b in pts]
        L = sum(math.dist(a, b) for a, b in zip(xy, xy[1:]))
        print("\n  first route: %.1f m projected" % L)
        self.assertLess(abs(L - 3920.0), 3920.0 * 0.005)

    def test_route_on_model(self):
        """Every point of the first route is a point of a kept road (the route is made of OSM nodes)."""
        common.need(common.ROUTE)
        from tools.citymap import roadmodel
        with open(common.ROUTE) as f:
            pts = json.load(f)["points"]
        m = common.model()
        for a, b in pts:
            self.assertIn(roadmodel.node_key(a, b), m.nodes)

    def test_bridges(self):
        m = common.model()
        osm_bridges = [e for e in common.osm()["elements"] if e["type"] == "way" and e.get("tags", {}).get("bridge")]
        self.assertEqual(len(osm_bridges), 19)
        br = [r for r in m.roads if r.bridge]
        by = collections.Counter(r.name for r in br if r.level == 1)
        print("\n  bridges kept: %d; raised: %s" % (len(br), dict(by)))
        for r in br:
            print("   ", r.id, r.kind, r.name, "layer", r.layer, "level", r.level, r.bridge_note)
        self.assertEqual(by["Neelam Flyover"], 2)
        self.assertEqual(by["Mathura Road Flyover"], 6)
        res = [r for r in br if r.kind == "residential"]
        self.assertEqual(len(res), 2)
        self.assertTrue(all(r.level == 1 for r in res))
        dnd = [r for r in br if r.kind == "motorway"]
        self.assertEqual(len(dnd), 2)
        for r in dnd:
            self.assertEqual(r.layer_tagged, None)
            self.assertIn(r.bridge_note, ("crosses a road: raised", "crosses no road: ground"))
            self.assertEqual(r.level, 1 if r.bridge_note.startswith("crosses a road") else 0)
        self.assertFalse(any(r.kind in ("footway", "steps") for r in br))

    def test_save_load_roundtrip(self):
        from tools.citymap import roadmodel
        m = common.model()
        os.makedirs(common.SCRATCH, exist_ok=True)
        path = os.path.join(common.SCRATCH, "roads-roundtrip.json")
        m.save(path)
        m2 = roadmodel.RoadModel.load(path)
        self.assertEqual(len(m2.roads), len(m.roads))
        self.assertEqual(set(m2.nodes), set(m.nodes))
        for a, b in zip(m.roads, m2.roads):
            self.assertEqual(a, b)
        for k in m.nodes:
            self.assertEqual(m.nodes[k], m2.nodes[k])


if __name__ == "__main__":
    unittest.main()
