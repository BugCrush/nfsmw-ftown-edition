"""Task 3: flyovers and ramps.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_levels -v
"""
import math
import os
import sys
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box

from tools.citymap.tests import common

TOOLS = common.TOOLS
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)


def lv():
    from tools.citymap import levels
    if "levels" not in common._cache:
        common._cache["levels"] = levels.build(common.model())
    return common._cache["levels"]


class Levels(unittest.TestCase):
    def test_flyovers_present(self):
        L = lv()
        raised = [c for c in L.chains if c.raised]
        names = {}
        for c in raised:
            names.setdefault(c.name, []).append(c)
        print("\n  raised chains:")
        for c in L.chains:
            print("   %-22s raised %-5s length %6.0f m, feet at %s, top %.2f m, crossings %s" % (
                c.name, c.raised, c.length, c.foot_notes, c.top(),
                ["%.0f m: %.2f" % (s, c.z(s)) for s, _rid in c.crossings]))
        self.assertEqual(len(names.get("Mathura Road Flyover", [])), 4)  # two flyovers, each one-way pair
        self.assertEqual(len(names.get("Neelam Flyover", [])), 2)
        for c in raised:
            self.assertAlmostEqual(c.top(), 7.0, places=6)
        self.assertEqual(L.DECK_HEIGHT, 7.0)

    def test_grades(self):
        """At most 6% along every road with the terrain (elevation, 2026-11-05: the ground's own slope added to the
        profile, terrain.offset)."""
        from tools.citymap import terrain
        L = lv()
        h = L.heights
        worst = 0.0
        for r in common.model().roads:
            z = h[r.id]
            self.assertEqual(len(z), len(r.points))
            for (a, b), za, zb in zip(zip(r.points, r.points[1:]), z, z[1:]):
                d = math.dist(a, b)
                if d > 0.01:
                    worst = max(worst, abs(zb + terrain.offset(*b) - za - terrain.offset(*a)) / d)
        for c in L.chains:
            for s in np.arange(0, c.length, 0.5):
                s1 = min(c.length, s + 0.5)
                p0, p1 = c.line.interpolate(s), c.line.interpolate(s1)
                worst = max(worst, abs(c.z(s1) + terrain.offset(p1.x, p1.y) - c.z(s) - terrain.offset(p0.x, p0.y)) /
                            0.5)
        print("\n  steepest grade along any road: %.3f%%" % (worst * 100))
        self.assertLessEqual(worst, 0.06 + 1e-9)
        # the mesh: no triangle edge climbs more than 6% of the distance it covers along its road (its vertices'
        # projections on the nearest chain); on a curve the inner edge of a ramp is steeper than its centre line by
        # R / (R - w / 2), a property of every curved ramp (up to 8.8% on the Neelam ramps' tight curve at the chowk)
        tris = L.deck_surfaces()
        bad = steepest_edge = 0
        for t in tris:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                c = L._nearest((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)[0]
                ds = abs(c.line.project(Point(b[:2])) - c.line.project(Point(a[:2])))
                if abs(b[2] - a[2]) > 0.06 * ds + 0.02:
                    bad += 1
                if d > 1.0:
                    steepest_edge = max(steepest_edge, abs(b[2] - a[2]) / d)
        print("  deck mesh: %d triangles, %d edges climbing more than 6%% along the road; steepest edge %.1f%%"
              % (len(tris), bad, steepest_edge * 100))
        self.assertEqual(bad, 0)

    def test_no_steps(self):
        L = lv()
        h = L.heights
        m = common.model()
        # along each chain, where one road hands over to the next, both give the same height
        for c in L.chains:
            for (ra, ia, ja), (rb, ib, jb) in zip(c.parts, c.parts[1:]):
                za = h[ra][ja]
                zb = h[rb][ib]
                self.assertLess(abs(za - zb), 0.02, (c.name, ra, rb))
            if not c.raised:
                continue
            # at each foot the ramp is at ground
            self.assertLess(c.z(0.0), 0.02)
            self.assertLess(c.z(c.length), 0.02)
        # where the elevated surface meets the ground road surface, it is at ground
        ground = L.ground_polygon
        seam = shapely.boundary(L.elevated).intersection(ground.buffer(0.01))
        pts = []
        for g in getattr(seam, "geoms", [seam]):
            if g.is_empty:
                continue
            pts += list(g.coords) if hasattr(g, "coords") else []
        walls = shapely.union_all([LineString([w.a, w.b]) for w in L.walls()])
        shapely.prepare(walls)
        at_ground = walled = 0
        for x, y in pts:
            z = L.z_at(x, y)
            if z < 0.02:
                at_ground += 1
            else:
                # above the ground road: a wall stands on that edge (an embankment, or a parapet high over it)
                self.assertLess(walls.distance(Point(x, y)), 0.05, (x, y, z))
                walled += 1
        print("\n  %d seam points between ramps and ground roads: %d at ground (< 2 cm), %d with a wall"
              % (len(pts), at_ground, walled))
        self.assertGreater(at_ground, 0)
        # the deck mesh's vertices on the seam are at ground too
        tris = L.deck_surfaces()
        gb = shapely.boundary(ground)
        shapely.prepare(gb)
        on = [p for t in tris for p in t if gb.distance(Point(p[0], p[1])) < 0.005]
        self.assertGreater(len(on), 0)
        for p in on:
            if p[2] >= 0.02:
                self.assertLess(walls.distance(Point(p[0], p[1])), 0.05, p)

    def test_road_below_flyover(self):
        """At each place a raised deck crosses a ground road, the game's height rule (the nearest face below, notes Q4)
        finds the ground road from 1 m above it and the deck from 1 m above the deck, on collision written from both."""
        from world import collision_write, heightcheck
        from world.collision import to_physics
        from tools.citymap import surfaces
        L = lv()
        n = 0
        for c in L.chains:
            if not c.raised:
                continue
            for s, rid in c.crossings:
                x, y = c.line.interpolate(s).coords[0]
                win = box(x - 20, y - 20, x + 20, y + 20)
                g2 = surfaces.triangulate(L.ground_polygon.intersection(win))
                faces = [tuple(to_physics((p[0], p[1], 0.0)) for p in t) for t in g2]
                faces += [tuple(to_physics(p) for p in t) for t in L.deck_surfaces(win)]
                pack = collision_write.make_pack(2400, faces, [])
                X, Y, Z = to_physics((x, y, 0.0))
                low = heightcheck.height_at(pack, X, Z, 1.0)
                high = heightcheck.height_at(pack, X, Z, c.z(s) + 1.0)
                self.assertIsNotNone(low)
                self.assertAlmostEqual(low, 0.0, delta=0.02)
                self.assertAlmostEqual(high, c.z(s), delta=0.05)
                self.assertGreaterEqual(c.z(s), L.CLEARANCE)
                n += 1
        print("\n  %d crossings under raised decks: the ground road found from below, the deck from above" % n)
        self.assertGreaterEqual(n, 10)

    def test_low_overlaps(self):
        """Away from the feet, nothing of the ground road surface lies under the elevated surface where it is lower
        than the clearance (a car on the ground road would run into the underside of a ramp)."""
        L = lv()
        over = L.elevated.intersection(L.ground_polygon)
        bad = 0.0
        for t in __import__("tools.citymap.surfaces", fromlist=["x"]).triangulate(over, 2.0):
            cx, cy = sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3
            z = L.z_at(cx, cy)
            if 0.05 < z < L.CLEARANCE:
                bad += abs(__import__("tools.citymap.surfaces", fromlist=["x"]).tri_area(t))
        print("\n  ground road under the elevated surface: %.1f m2 in all, %.2f m2 of it below %.1f m"
              % (over.area, bad, L.CLEARANCE))
        self.assertLess(bad, 1.0)

    def test_pillars_clear(self):
        L = lv()
        pil = L.pillars()
        print("\n  %d pillars" % len(pil))
        self.assertGreater(len(pil), 40)
        g = L.ground_polygon
        shapely.prepare(g)
        for footprint, top in pil:
            self.assertFalse(g.intersects(footprint))
            self.assertGreater(top, L.CLEARANCE - 0.01)

    def test_walls(self):
        L = lv()
        walls = L.walls()
        kinds = {}
        for w in walls:
            kinds[w.kind] = kinds.get(w.kind, 0) + 1
            self.assertGreater(w.top, w.bottom)
            if w.kind == "parapet":
                self.assertAlmostEqual(w.top - w.z_road, 1.0, places=6)
                self.assertGreaterEqual(w.z_road, L.CLEARANCE - 1e-9)
            else:
                self.assertEqual(w.bottom, 0.0)
        print("\n  walls:", kinds)
        self.assertIn("parapet", kinds)
        self.assertIn("embankment", kinds)


if __name__ == "__main__":
    unittest.main()
