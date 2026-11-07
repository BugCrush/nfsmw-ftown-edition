"""Own looks Task 5: electricity poles and overhead wires along the residential lanes.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_poles -v
"""
import math
import unittest

import shapely
from shapely.geometry import Point

from tools.citymap.tests import common
from tools.citymap.tests.test_landmark_build import geometry


class Poles(unittest.TestCase):
    def test_counts(self):
        """Poles line the residential lanes (one side, every 32-40 m) and most are strung to the next by wires."""
        _p, _m, _L, _bl, city, _r = geometry()
        pr = city.extras.poles
        print("\n  %d poles, %d wire spans, %d triangles" % (len(pr.poles), pr.spans,
                                                              sum(len(p.tris) for p in pr.parts)))
        self.assertGreater(len(pr.poles), 1000)
        self.assertGreater(pr.spans, 0.6 * len(pr.poles))

    def test_poles_off_lanes(self):
        """Every pole's foot is 0.5 m or more off every carriageway (ground and raised) and pavement, off the medians,
        off every building and boundary wall, and inside the city's edge."""
        _p, _m, L, bl, city, _r = geometry()
        pr = city.extras.poles
        lanes = shapely.union_all([L.ground_polygon, L.elevated, city.pav]).buffer(0.5)
        meds = shapely.union_all([m.polygon for m in city.extras.furniture.medians])
        blocks = shapely.union_all([b.footprint for b in bl.blocks])
        walls = shapely.union_all([shapely.LineString(s) for s in city.extras.boundary]).buffer(0.2)
        for g in (lanes, meds, blocks, walls):
            shapely.prepare(g)
        inner = city.outer.buffer(-3.0)
        bad = [(x, y) for x, y, _rid in pr.poles
               if lanes.intersects(Point(x, y).buffer(0.15)) or meds.intersects(Point(x, y).buffer(0.15))
               or blocks.intersects(Point(x, y).buffer(0.15)) or walls.intersects(Point(x, y).buffer(0.15))
               or not inner.contains(Point(x, y))]
        self.assertEqual(bad, [])

    def test_poles_solid(self):
        """Each pole stands in a ring of four outward barriers from the ground to 8 m or more round its foot."""
        _p, _m, _L, _bl, city, _r = geometry()
        pr = city.extras.poles
        self.assertEqual(len(pr.barriers), 4 * len(pr.poles))
        for k, (x, y, _rid) in enumerate(pr.poles):
            ring = pr.barriers[4 * k:4 * k + 4]
            for p, q, lo, hi in ring:
                self.assertLess(math.dist(p, (x, y)), 0.3)
                self.assertEqual(lo, 0.0)
                self.assertGreaterEqual(hi, 8.0)
                # outward: the pole's axis on the left of p -> q (a counter-clockwise ring)
                self.assertGreater((q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]), 0)

    def test_poles_off_event_routes(self):
        """No pole within poles.ROUTE_KEEP (8 m) of the centre line of the first route or of any event's route in
        ftown/ftown-events.json (the review: 68 solid poles 3.75 m from the Sector Sprint's line, where a slide at
        race speed ends)."""
        import json
        import os
        from tools.citymap import poles
        proj, _m, _L, _bl, city, route = geometry()
        lines = [shapely.LineString([proj.to_render(a, b) for a, b in route])]
        p = os.path.join(common.REPO, "ftown", "ftown-events.json")
        with open(p, encoding="utf-8") as f:
            evs = json.load(f)["events"]
        lines += [shapely.LineString(e["route"]) for e in evs]
        self.assertGreaterEqual(len(lines), 5)
        self.assertGreaterEqual(poles.ROUTE_KEEP, 8.0)
        near = [(x, y) for x, y, _rid in city.extras.poles.poles
                if min(ln.distance(Point(x, y)) for ln in lines) < poles.ROUTE_KEEP]
        print("\n  %d routes; %d poles within %.0f m" % (len(lines), len(near), poles.ROUTE_KEEP))
        self.assertEqual(near, [])

    def test_wires_clear(self):
        """No wire passes through anything standing in its height: balconies, the tall street furniture (lamp posts,
        street lights, signals, billboards: each model's plan and heights), landmark buildings, stations, the
        metro's piers and the ground under its deck (the review: 16 balconies, 1 lamp post, 2 piers, 6 under the
        viaduct)."""
        from shapely.geometry import MultiPoint, Polygon
        from tools.citymap import furniture_models as FM
        _p, _m, _L, _bl, city, _r = geometry()
        ex = city.extras
        obs = []  # (plan polygon, z low, z high, kind)
        for b in ex.house_detail.balconies:
            obs.append((b.polygon, b.underside, 1000.0, "balcony"))
        # the lamps, lights and signals are breakable poles since 2026-11-05: their models' plans (X0's boxes, our
        # lantern) and heights
        from tools.citymap import breakables
        for b in ex.furniture.breakables:
            obs.append((breakables.footprint(b.role, b.x, b.y, b.heading).buffer(0.05), b.z,
                        b.z + breakables.height(b.role), b.role))
        models = {"billboard": FM.billboard(0)[0]}
        for name, x, y, z, hd in ex.furniture.placed:
            if name not in models:
                continue
            pts = [v for t, _uv in FM.place(models[name], x, y, z, math.radians(hd)) for v in t]
            obs.append((MultiPoint([(v[0], v[1]) for v in pts]).convex_hull.buffer(0.05), min(v[2] for v in pts),
                        max(v[2] for v in pts), name))
        for fp in ex.landmark_result.footprints.values():
            obs.append((fp, 0.0, 1000.0, "landmark"))
        for s in ex.stations:
            obs.append((s.footprint, 0.0, 1000.0, "station"))
        for r in ex.viaduct.pier_boxes:
            obs.append((Polygon(r), 0.0, 1000.0, "pier"))
        obs.append((ex.viaduct.footprint(0.0), 0.0, 1000.0, "viaduct"))
        tree = shapely.STRtree([o[0] for o in obs])
        hits = {}
        for span in ex.poles.wire_tris:
            hit = set()
            for t in span:
                g = Polygon([(v[0], v[1]) for v in t]).buffer(0.01)
                zl, zh = min(v[2] for v in t), max(v[2] for v in t)
                for k in tree.query(g, predicate="intersects"):
                    if obs[k][1] <= zh and zl <= obs[k][2]:
                        hit.add(obs[k][3])
            for kind in hit:
                hits[kind] = hits.get(kind, 0) + 1
        print("\n  %d wires, %d obstacles: hits %s" % (len(ex.poles.wire_tris), len(obs), hits))
        self.assertGreater(len(ex.poles.wire_tris), 1000)
        self.assertEqual(hits, {})

    def test_wires_high(self):
        """Every wire is above 5.5 m (over any vehicle), and no wire crosses a building."""
        _p, _m, _L, bl, city, _r = geometry()
        pr = city.extras.poles
        low = sum(1 for w in pr.wire_tris for t in w for v in t if v[2] < 5.5)
        self.assertEqual(low, 0)
        blocks = shapely.union_all([b.footprint for b in bl.blocks])
        shapely.prepare(blocks)
        crossing = sum(1 for a, b in pr.wire_lines if blocks.intersects(shapely.LineString([a, b])))
        self.assertEqual(crossing, 0)


if __name__ == "__main__":
    unittest.main()
