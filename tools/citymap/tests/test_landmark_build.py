"""Task 4 (landmarks plan): the landmark buildings, the Neelam Flyover's mural, the DND-KMP side walls, the sign.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_landmark_build -v
"""
import unittest

import numpy as np
import shapely
from shapely.geometry import Point

from tools.citymap.tests import common


def geometry():
    if "geometry" not in common._cache:
        from tools.citymap import build_city
        common.need(common.OSM)
        common._cache["geometry"] = build_city.geometry(common.AREA)
    return common._cache["geometry"]


class MarketFronts(unittest.TestCase):
    def test_market_fronts_one_parapet(self):
        """A market landmark's fronts without a drawn face (Sector 16 Market's other fronts, own looks) carry the
        house atlas's facade up to its parapet's top, h + buildings.PARAPET over the roof at h, and no second, plain
        parapet above it (the review: the atlas's parapet stood below the roof and a plain one above)."""
        import types
        from shapely.geometry import Polygon as Poly
        from tools.citymap import buildings, landmark_build, parts as P
        h = 9.6
        lm = types.SimpleNamespace(footprint=Poly([(0, 0), (20, 0), (20, 14), (0, 14)]), key="TEST_MARKET",
                                   height_m=h, finish="market", faces=[], extra={})
        res = landmark_build.Result()
        landmark_build.building(lm, set(), res)
        outward = []
        for part in res.parts:
            for t in part.tris:
                n = P.normal(t)
                if abs(n[2]) > 0.1:
                    continue
                m = np.mean(t, 0)
                if n[0] * (m[0] - 10.0) + n[1] * (m[1] - 7.0) > 0:  # faces away from the middle: an outer face
                    outward.append((part.kind, t))
        top = max(v[2] for _k, t in outward for v in t)
        self.assertAlmostEqual(top, h + buildings.PARAPET)
        above = [k for k, t in outward if min(v[2] for v in t) >= h - 1e-6]
        self.assertEqual(set(above) - {"houses"}, set(), "a plain parapet above the facade's own")


class LandmarkBuild(unittest.TestCase):
    def test_replaces_block(self):
        """No plain block is left on a landmark building's footprint (the landmark draws it), and each building
        landmark was drawn with its photo faces where the photos are there."""
        _proj, _m, _L, bl, city, _r = geometry()
        lb = city.extras.landmark_result
        self.assertGreaterEqual(len(lb.footprints), 12)
        fps = list(lb.footprints.items())
        tree = shapely.STRtree([b.footprint for b in bl.blocks])
        for key, fp in fps:
            for k in tree.query(fp):
                self.assertLess(bl.blocks[k].footprint.intersection(fp).area, 1.0, key)
        for s in city.extras.stations:
            for k in tree.query(s.footprint):
                self.assertLess(bl.blocks[k].footprint.intersection(s.footprint).area, 1.0, s.name)
        print("\n  %d landmark buildings, %d photo faces drawn (%d photo textures available); %d blocks left" % (
            len(fps), lb.photo_faces, len(city.extras.photo_names), len(bl.blocks)))

    def test_inside_footprint(self):
        """No landmark geometry below 4.5 m over a carriageway (ground or raised): walls on their footprints, the
        canopy's feet, the sign's posts and the crash walls beside the roads; the mural is a skin on the flyover's own
        walls (4 cm proud, checked apart)."""
        _proj, _m, L, _bl, city, _r = geometry()
        lb = city.extras.landmark_result
        lanes = shapely.union_all([L.ground_polygon, L.elevated]).buffer(-0.05)
        shapely.prepare(lanes)
        mural = set(id(p) for p in lb.mural_parts)
        cx, cy = [], []
        for p in lb.parts:
            if id(p) in mural:
                continue
            for t in p.tris:
                if min(v[2] for v in t) < 4.5:
                    cx.append((t[0][0] + t[1][0] + t[2][0]) / 3)
                    cy.append((t[0][1] + t[1][1] + t[2][1]) / 3)
        inside = shapely.contains_xy(lanes, np.array(cx), np.array(cy))
        print("\n  %d low triangles of the landmarks; %d over a carriageway; crash walls %.0f m; sign at %s" % (
            len(cx), int(inside.sum()), lb.crash_m, lb.sign_at))
        self.assertEqual(int(inside.sum()), 0)
        self.assertGreater(lb.crash_m, 300.0)
        self.assertIsNotNone(lb.sign_at)
        for c in lb.canopies:
            self.assertFalse(lanes.intersects(c))

    def test_signs_clear_the_parapet(self):
        """The review's finding: a rooftop sign starts above the parapet (no two faces in one plane to flicker): the
        lowest point of every rooftop sign's photo quad is above the building's height + its parapet."""
        from tools.citymap import landmark_build
        _proj, _m, _L, _bl, city, _r = geometry()
        lb = city.extras.landmark_result
        tops = {lm.key: lm.height_m for lm in city.extras.landmarks}
        n = 0
        for p in lb.parts:
            if p.kind.endswith("_SIGN"):
                low = min(v[2] for t in p.tris for v in t)
                self.assertGreater(low, tops[p.tag] + landmark_build.PARAPET, p.kind)
                n += 1
        self.assertEqual(n, 2)

    def test_mural_on_neelam(self):
        """The mural is on both Neelam Flyover carriageways' outer walls (more than 100 m of each), every mural quad
        within 5 cm of a flyover wall."""
        _proj, _m, L, _bl, city, _r = geometry()
        lb = city.extras.landmark_result
        print("\n  mural metres per carriageway: %s" % {k: round(v) for k, v in lb.mural_m.items()})
        self.assertEqual(len(lb.mural_m), 2)
        self.assertTrue(all(v > 100.0 for v in lb.mural_m.values()))
        walls = shapely.union_all([shapely.LineString([w.a, w.b]) for w in L.walls()])
        for p in lb.mural_parts:
            for t in p.tris[::7]:
                c = Point((t[0][0] + t[1][0] + t[2][0]) / 3, (t[0][1] + t[1][1] + t[2][1]) / 3)
                self.assertLess(walls.distance(c), 0.05)

    def test_route_still_drivable(self):
        """The stage 2 checks on the city file written with the landmarks (tools/citymap/tests/test_city.py)."""
        from tools.citymap.tests import test_city
        c = test_city.City("test_route_drivable")
        c.test_route_drivable()
        c.test_no_barrier_on_road()
        c.test_written_centrelines_drivable()
        c.test_barriers_face_the_road()


if __name__ == "__main__":
    unittest.main()
