"""Task 2: ground-level road surfaces, junctions, pavements and lane markings.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_surfaces -v
"""
import math
import unittest

import numpy as np
import shapely
from shapely.geometry import Point, Polygon, box

from tools.citymap.tests import common


def samples(points, step=1.0):
    """Points every `step` metres along a polyline, both ends included."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        L = math.dist(a, b)
        n = max(1, int(math.ceil(L / step)))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


class Surfaces(unittest.TestCase):
    def test_centrelines_covered(self):
        m = common.model()
        ground = common.polys()[0]
        shapely.prepare(ground)
        pts, total = [], 0
        for r in m.roads:
            if r.level == 0:
                s = samples(r.points)
                pts += s
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        inside = shapely.contains_xy(ground, xs, ys)
        misses = int((~inside).sum())
        print("\n  %d centre-line points of %d ground roads sampled every 1 m: %d outside the surface"
              % (len(pts), sum(1 for r in m.roads if r.level == 0), misses))
        self.assertEqual(misses, 0)

    def test_junction_covered(self):
        m = common.model()
        ground = common.polys()[0]
        shapely.prepare(ground)
        n_checked, bad = 0, []
        for k, node in m.junctions().items():
            roads = [m.road(i) for i in set(node.road_ids)]
            if any(r.level != 0 for r in roads):
                continue
            w = min(r.width_m for r in roads)
            disc = Point(node.x, node.y).buffer(0.4 * w, quad_segs=16)
            n_checked += 1
            if not ground.contains(disc):
                bad.append(k)
        print("\n  %d ground junctions: a disc of 0.4 x the narrowest width inside the surface at all but %d"
              % (n_checked, len(bad)))
        self.assertEqual(bad, [])
        self.assertGreater(n_checked, 1000)

    def test_levels(self):
        p = common.polys()
        self.assertEqual(sorted(p), [0, 1])
        self.assertGreater(p[0].area, 1.0e6)  # about 265 km of roads 4-12 m wide
        self.assertGreater(p[1].area, 2.0e4)  # the flyover decks

    def test_triangulation_exact(self):
        from tools.citymap import surfaces
        ground = common.polys()[0]
        # a 600 x 600 m window holding junctions, a roundabout-free sector grid and curves; then the whole city
        for poly in (ground.intersection(box(1700, 11300, 2300, 11900)), ground):
            tris = surfaces.triangulate(poly, max_edge=8.0)
            areas = [abs(surfaces.tri_area(t)) for t in tris]
            total = sum(areas)
            print("\n  %d triangles, area %.1f m2 of %.1f m2 (%.5f%%); smallest %.4f m2"
                  % (len(tris), total, poly.area, 100 * abs(total - poly.area) / poly.area, min(areas)))
            self.assertLess(abs(total - poly.area), poly.area * 1e-4)
            self.assertGreaterEqual(min(areas), 1e-4)  # no sliver below 1 cm2
            for t in tris:
                self.assertGreater(surfaces.tri_area(t), 0)  # counter-clockwise seen from above
            cx = np.array([sum(p[0] for p in t) / 3 for t in tris])
            cy = np.array([sum(p[1] for p in t) / 3 for t in tris])
            shapely.prepare(poly)
            self.assertTrue(shapely.contains_xy(poly.buffer(1e-6), cx, cy).all())
            # every triangle lies inside: vertices are snapped to 0.1 mm, so a triangle may stick out by that much
            sample = tris[:: max(1, len(tris) // 3000)]
            worst = max(Polygon(t).difference(poly).area for t in sample)
            far = max(poly.distance(Point(p)) for t in sample for p in t)
            self.assertLess(worst, 2e-3)
            self.assertLess(far, 1e-3)
            for t in sample:
                for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    self.assertLessEqual(math.dist(a, b), 8.0 * math.sqrt(2) + 1e-6)

    def test_triangulation_conforming(self):
        """Inside the polygon no triangle edge ends on another triangle's edge (no T-junctions): every interior edge is
        shared by exactly two triangles, so the collision written from them has no cracks."""
        from tools.citymap import surfaces
        ground = common.polys()[0]
        poly = ground.intersection(box(1900, 11400, 2100, 11600))
        tris = surfaces.triangulate(poly, max_edge=8.0)
        edges = {}
        for t in tris:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(a, b), max(a, b))
                edges[k] = edges.get(k, 0) + 1
        boundary = shapely.boundary(poly)
        shapely.prepare(boundary)
        odd = [k for k, n in edges.items() if n == 1
               and not boundary.distance(Point((k[0][0] + k[1][0]) / 2, (k[0][1] + k[1][1]) / 2)) < 1e-3]
        print("\n  %d edges, %d used once away from the boundary" % (len(edges), len(odd)))
        self.assertEqual(odd, [])
        self.assertEqual([k for k, n in edges.items() if n > 2], [])

    def test_pavements(self):
        from tools.citymap import surfaces
        m = common.model()
        p = common.polys()
        pav = surfaces.pavements(m, p)
        print("\n  pavements: %.0f m2" % pav.area)
        self.assertLess(pav.intersection(p[0]).area, 1.0)  # outside the carriageways
        self.assertGreater(pav.area, 1.0e5)
        # 2.5 m wide: a point 1.25 m beyond a tertiary road's edge, away from junctions, is pavement
        r = next(r for r in m.roads if r.kind == "tertiary" and r.level == 0 and r.length() > 300)
        (ax, ay), (bx, by) = r.points[0], r.points[1]
        L = math.dist((ax, ay), (bx, by))
        mx, my = (ax + bx) / 2, (ay + by) / 2
        nx, ny = -(by - ay) / L, (bx - ax) / L
        d = r.width_m / 2 + 1.25
        hits = sum(pav.contains(Point(mx + s * nx * d, my + s * ny * d)) for s in (1, -1))
        self.assertGreaterEqual(hits, 1)
        self.assertEqual(surfaces.PAVEMENT_RISE, 0.15)

    def test_markings_on_road(self):
        from tools.citymap import surfaces
        m = common.model()
        p = common.polys()
        marks = surfaces.markings(m, p)
        kinds = {}
        for kind, poly, _rid in marks:
            kinds[kind] = kinds.get(kind, 0) + 1
        print("\n  markings:", kinds)
        self.assertIn("centre", kinds)
        self.assertIn("lane", kinds)
        allm = shapely.union_all([poly for _k, poly, _r in marks])
        self.assertLess(allm.difference(p[0].union(p[1])).area, 0.05)
        self.assertGreater(surfaces.MARKING_RISE, 0)
        self.assertLess(surfaces.MARKING_RISE, 0.05)


if __name__ == "__main__":
    unittest.main()
