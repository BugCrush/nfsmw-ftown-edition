"""Task 4: buildings, ground and the edge.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_buildings -v
"""
import json
import os
import random
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box

from tools.citymap.tests import common

AREAS = os.path.join(common.AREA, "areas.json")
BBOX = (28.385, 77.305, 28.420, 77.332)


def roads_union():
    if "roads_union" not in common._cache:
        from tools.citymap import levels, surfaces
        L = levels.build(common.model())
        pav = surfaces.pavements(common.model(), {0: L.ground_polygon})
        common._cache["levels"] = L
        common._cache["pav"] = pav
        common._cache["roads_union"] = shapely.union_all([L.ground_polygon, pav, L.elevated])
    return common._cache["roads_union"]


def areas():
    common.need(AREAS)
    if "areas" not in common._cache:
        with open(AREAS, encoding="utf-8") as f:
            common._cache["areas"] = json.load(f)
    return common._cache["areas"]


def blocks():
    from tools.citymap import buildings
    if "blocks" not in common._cache:
        common._cache["blocks"] = buildings.blocks(common.osm(), common.proj(), roads_union(), seed=1,
                                                   areas=areas(), model=common.model())
    return common._cache["blocks"]


class Buildings(unittest.TestCase):
    def test_no_building_on_road(self):
        R = roads_union()
        shapely.prepare(R)
        worst = 0.0
        for b in blocks().blocks:
            if R.intersects(b.footprint):
                worst = max(worst, R.intersection(b.footprint).area)
        print("\n  largest overlap of a block with a road, pavement or ramp: %.6f m2" % worst)
        self.assertLess(worst, 1e-4)

    def test_heights_rules(self):
        from tools.citymap import buildings
        bl = blocks()
        kinds = {}
        for b in bl.blocks:
            kinds[b.kind] = kinds.get(b.kind, 0) + 1
            st = b.height_m / buildings.STOREY
            self.assertAlmostEqual(st, round(st), places=6)
            if b.kind == "tagged":
                self.assertIn(round(st), (8, 9))
            elif b.kind == "commercial":
                self.assertTrue(4 <= round(st) <= 8)
                self.assertGreater(b.source_area, 400.0)
            else:
                self.assertEqual(b.kind, "house")
                self.assertTrue(2 <= round(st) <= 4)
        print("\n  kinds:", kinds)
        self.assertEqual(kinds.get("tagged"), 2)
        self.assertGreater(kinds.get("commercial", 0), 50)
        # deterministic: the same seed gives the same heights, another seed others
        again = buildings.blocks(common.osm(), common.proj(), roads_union(), seed=1, areas=areas(),
                                 model=common.model())
        self.assertEqual([b.height_m for b in again.blocks], [b.height_m for b in bl.blocks])

    def test_counts(self):
        bl = blocks()
        print("\n  buildings in the data %d (ways %d, relations %d); blocks %d; trimmed by a road %d; dropped: "
              "on a road %d, outside the edge %d, slivers %d" % (
                  bl.source_count, bl.source_ways, bl.source_relations, len(bl.blocks), bl.trimmed,
                  bl.dropped_on_road, bl.dropped_outside, bl.dropped_slivers))
        self.assertEqual(bl.source_ways, 7095)
        self.assertEqual(bl.source_relations, 14)
        lost = bl.dropped_on_road + bl.dropped_outside + bl.dropped_slivers
        self.assertEqual(len({b.osm_id for b in bl.blocks}), bl.source_count - lost)
        self.assertGreater(len(bl.blocks), 6500)
        for b in bl.blocks:
            self.assertGreaterEqual(b.footprint.area, 10.0)
            self.assertTrue(b.footprint.is_valid)
            self.assertEqual(b.footprint.geom_type, "Polygon")

    def test_ground_covers(self):
        from tools.citymap import buildings
        p = common.proj()
        R = roads_union()
        B = shapely.union_all([b.footprint for b in blocks().blocks])
        cut = shapely.union_all([R, B])
        g = buildings.ground(p, BBOX, areas(), cut=cut)
        outer = buildings.edge_box(p, BBOX)
        kinds = {}
        for poly, kind in g:
            kinds[kind] = kinds.get(kind, 0.0) + poly.area
        print("\n  ground: %s m2; box with margin %.0f m2" % ({k: round(v) for k, v in kinds.items()}, outer.area))
        self.assertIn("grass", kinds)
        G = shapely.union_all([poly for poly, _k in g])
        self.assertLess(G.intersection(cut).area, 1.0)  # never under a road or a building (nothing drawn twice)
        everything = shapely.union_all([G, cut]).intersection(outer)
        self.assertLess(abs(everything.area - outer.area), 1.0)
        rng = random.Random(3)
        x0, y0, x1, y1 = outer.bounds
        xs = np.array([rng.uniform(x0, x1) for _ in range(20000)])
        ys = np.array([rng.uniform(y0, y1) for _ in range(20000)])
        shapely.prepare(everything)
        self.assertTrue(shapely.contains_xy(everything.buffer(0.01), xs, ys).all())

    def test_edge_closed(self):
        from tools.citymap import buildings
        p = common.proj()
        walls = buildings.edge_barriers(p, BBOX)
        for (a, b), (c, d) in zip(walls, walls[1:] + walls[:1]):
            self.assertEqual(b, c)  # each wall starts where the last one ended, round to the first
        ring = LineString([w[0] for w in walls] + [walls[0][0]])
        self.assertTrue(ring.is_ring)
        outer = buildings.edge_box(p, BBOX)
        self.assertAlmostEqual(shapely.Polygon(ring.coords).area, outer.area, delta=1.0)
        # every road that leaves the area meets the wall
        crossing = 0
        for r in common.model().roads:
            ln = LineString(r.points)
            if ln.crosses(outer.exterior):
                crossing += 1
                self.assertTrue(ln.intersects(ring))
        print("\n  %d edge walls, %d m round; %d roads leave the area through it" % (
            len(walls), ring.length, crossing))
        self.assertGreater(crossing, 10)
        self.assertEqual(buildings.EDGE_HEIGHT, 3.0)


if __name__ == "__main__":
    unittest.main()
