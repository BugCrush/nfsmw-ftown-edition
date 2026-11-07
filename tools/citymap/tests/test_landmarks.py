"""Task 1 (landmarks plan): the landmark registry resolved onto the city.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_landmarks -v
"""
import json
import os
import unittest

import shapely
from shapely.geometry import Point, Polygon, box

from tools.citymap.tests import common

DETAILS = os.path.join(common.AREA, "details", "details.json")
AREAS = os.path.join(common.AREA, "areas.json")


def resolved():
    if "landmarks" not in common._cache:
        from tools.citymap import buildings, landmarks, levels, surfaces
        common.need(DETAILS, AREAS)
        with open(DETAILS, encoding="utf-8") as f:
            details = json.load(f)
        with open(AREAS, encoding="utf-8") as f:
            areas = json.load(f)
        m = common.model()
        L = common._cache.get("levels") or levels.build(m)
        common._cache["levels"] = L
        pav = surfaces.pavements(m, {0: L.ground_polygon}).difference(L.elevated)
        roads = shapely.union_all([L.ground_polygon, pav, L.elevated])
        bl = buildings.blocks(common.osm(), common.proj(), roads, seed=1, areas=areas, model=m)
        common._cache["blocks"] = bl
        common._cache["landmarks"] = landmarks.resolve(landmarks.load(), common.osm(), details, common.proj(),
                                                       bl.blocks, L.raised_chains)
    return common._cache["landmarks"]


class Registry(unittest.TestCase):
    def test_every_landmark_resolves(self):
        """Each entry gets exactly one footprint (or point, or chains) inside the area; names match OSM's where OSM
        has them; keys are unique; heights are storeys x 3.2-4.0 m (the design's estimate from the photos)."""
        from tools.citymap import buildings, landmarks
        lms = resolved()
        outer = buildings.edge_box(common.proj(), (28.385, 77.305, 28.420, 77.332))
        keys = [lm.key for lm in lms]
        self.assertEqual(len(keys), len(set(keys)))
        names = {"Neelam Chowk Ajronda", "Bata Chowk", "Old Faridabad", "Marengo Asia Hospitals", "Fortis Escorts",
                 "Dr. Aggarwal's Eye Hospital", "Pacific Mall", "Station 1", "SRS multiplex", "Neelam Flyover mural",
                 "Sector 16A direction sign"}
        self.assertTrue(names <= {lm.name for lm in lms}, names - {lm.name for lm in lms})
        fps = []
        for lm in lms:
            if lm.kind == "sign":
                self.assertIsNotNone(lm.point)
                self.assertTrue(outer.contains(Point(lm.point)), lm.key)
                continue
            if lm.kind == "mural":
                self.assertEqual(len(lm.extra["chains"]), 2, lm.key)  # both Neelam Flyover carriageways
                continue
            self.assertIsNotNone(lm.footprint, lm.key)
            self.assertEqual(lm.footprint.geom_type, "Polygon", lm.key)
            self.assertTrue(outer.contains(lm.footprint), lm.key)
            self.assertGreater(lm.footprint.area, 300.0, lm.key)
            if lm.osm_name:
                self.assertEqual(lm.extra["osm_tags"].get("name"), lm.osm_name, lm.key)
            if lm.storeys:
                lo, hi = landmarks.STOREY_RANGE
                self.assertTrue(lo * lm.storeys - 1e-6 <= lm.height_m <= hi * lm.storeys + 1e-6, lm.key)
            fps.append((lm.key, lm.footprint))
        # no two landmarks on one outline
        for i, (ka, a) in enumerate(fps):
            for kb, b in fps[i + 1:]:
                self.assertLess(a.intersection(b).area, 1.0, (ka, kb))
        print("\n  %d landmarks resolved: %s" % (len(lms), ", ".join("%s %s" % (lm.key, lm.osm_id or "") for lm in lms)))

    def test_faces_face_roads(self):
        """Each textured face's outward normal points within 60 degrees of the direction to its facing road (the
        nearest part of that road at least 2 m in front of the face): a photo never lands on a wall turned away from
        the street it was taken from."""
        from tools.citymap import landmarks
        lines = landmarks.road_lines(common.model())
        n = 0
        for lm in resolved():
            for f in lm.faces:
                if f.edge_index < 0:
                    continue
                self.assertLess(f.edge_index, len(landmarks.edges(lm.footprint)), f.name)
                ang, dist = landmarks.facing_angle(lm.footprint, f, lines)
                self.assertLessEqual(ang, landmarks.FACING_DEG, (lm.key, f.name, ang))
                self.assertLess(dist, 120.0, (lm.key, f.name))
                n += 1
        print("\n  %d faces checked against their roads" % n)
        self.assertGreater(n, 15)

    def test_nothing_between_face_and_road(self):
        """The review's finding: no other building stands between a photo face and the facing road it was taken from
        (the line from the edge's middle to the nearest part of that road in front of it crosses no other block)."""
        from tools.citymap import landmarks
        lms = resolved()
        lines = landmarks.road_lines(common.model())
        blocks = common._cache["blocks"].blocks
        tree = shapely.STRtree([b.footprint for b in blocks])
        bad = []
        for lm in lms:
            for f in lm.faces:
                if f.edge_index < 0:
                    continue
                p, q = landmarks.edges(lm.footprint)[f.edge_index]
                c = landmarks.facing_point(lm.footprint, f, lines)
                n = landmarks.outward(p, q)
                mid = ((p[0] + q[0]) / 2 + n[0] * 0.3, (p[1] + q[1]) / 2 + n[1] * 0.3)
                ray = shapely.LineString([mid, c])
                for k in tree.query(ray):
                    fp = blocks[int(k)].footprint
                    if fp.intersection(lm.footprint).area > 1.0:
                        continue  # the landmark's own block
                    if fp.intersects(ray):
                        bad.append((lm.key, f.name, blocks[int(k)].osm_id))
        self.assertEqual(bad, [])

    def test_photo_files_exist(self):
        """Every photo number of the registry maps, by the order of the sorted file names in ftownphotos/, to the file
        the registry records (and the file exists)."""
        from tools.citymap import landmarks
        files = landmarks.photo_files()
        if not files:
            raise unittest.SkipTest("ftownphotos/ is missing (the user's photos, git-ignored)")
        self.assertEqual(len(files), 55)
        reg = landmarks.read()
        used = set()
        for d in reg["landmarks"]:
            used.update(d.get("photos", []))
            used.update(f["photo"] for f in d.get("faces", []))
        for n in used:
            self.assertIn(n, files)
        for n, p in reg["photos"].items():
            self.assertEqual(files[int(n)], p["file"], n)
            self.assertTrue(os.path.exists(os.path.join(landmarks.PHOTOS, p["file"])))
        for d in reg["landmarks"]:
            for f in d.get("faces", []):
                self.assertIn(str(f["photo"]), reg["photos"], f.get("name"))

    def test_corners_inside_picture(self):
        """Every crop's corners lie inside its photo, and the crop's quad touches none of the photo's overlay areas
        (the screenshot layout's top bar and bottom panel, labels, pins); "patch" rectangles are filled before the crop
        and may lie inside it."""
        from PIL import Image
        from tools.citymap import landmarks
        files = landmarks.photo_files()
        if not files:
            raise unittest.SkipTest("ftownphotos/ is missing")
        reg = landmarks.read()
        n = 0
        for d in reg["landmarks"]:
            for f in d.get("faces", []):
                with Image.open(os.path.join(landmarks.PHOTOS, files[f["photo"]])) as im:
                    w, h = im.size
                for x, y in f["corners"]:
                    self.assertTrue(0 <= x < w and 0 <= y < h, (f.get("name"), x, y, w, h))
                quad = Polygon(f["corners"])
                self.assertTrue(quad.is_valid and quad.area > 100, f.get("name"))
                block, _patch = landmarks.overlays(reg, f["photo"])
                for r in block:
                    self.assertFalse(quad.intersects(box(*r).buffer(-0.5)), (f.get("name"), r))
                tw, th = f["tex"]
                self.assertFalse(tw & (tw - 1) or th & (th - 1) or min(tw, th) < 8, f.get("name"))
                n += 1
        self.assertGreater(n, 15)


if __name__ == "__main__":
    unittest.main()
