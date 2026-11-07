"""Task 5 (landmarks plan): street furniture.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_furniture -v
"""
import json
import math
import os
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Point

from tools.citymap.tests import common
from tools.citymap.tests.test_landmark_build import geometry
from tools.citymap.tests.test_landmarks import DETAILS


class Furniture(unittest.TestCase):
    def test_medians_only_between_pairs(self):
        """Every median lies between the two carriageways of its pair: one-way, opposite ways, one name (or one kind
        unnamed), each within the pair gap of the median; no median beside a two-way road only."""
        from tools.citymap import furniture
        _p, m, _L, _bl, city, _r = geometry()
        fr = city.extras.furniture
        self.assertGreater(len(fr.medians), 20)
        for md in fr.medians:
            ra, rb = m.road(md.pair[0]), m.road(md.pair[1])
            self.assertTrue(ra.oneway and rb.oneway)
            self.assertEqual(ra.name, rb.name)
            c = md.polygon.representative_point()
            for r in (ra, rb):
                self.assertLessEqual(LineString(r.points).distance(c), r.width_m / 2 + furniture.PAIR_GAP + 0.01)
        area = sum(md.polygon.area for md in fr.medians)
        kinds = {k: sum(1 for md in fr.medians if md.kind == k) for k in ("railing", "planted")}
        print("\n  %d medians (%s), %.0f m2" % (len(fr.medians), kinds, area))
        self.assertGreater(kinds["railing"], 0)
        self.assertGreater(kinds["planted"], 0)

    def test_carriageways_keep_width(self):
        """No median, kerb or furniture triangle below 2 m lies over a carriageway (ground or raised, 5 cm inside its
        edge): every carriageway keeps its full width."""
        _p, _m, L, _bl, city, _r = geometry()
        fr = city.extras.furniture
        lanes = shapely.union_all([L.ground_polygon, L.elevated]).buffer(-0.05)
        shapely.prepare(lanes)
        for md in fr.medians:
            self.assertLess(md.polygon.intersection(lanes).area, 0.01)
        cx, cy, kinds = [], [], []
        for p in fr.parts:
            for t in p.tris:
                if min(v[2] for v in t) < 2.0:
                    cx.append(sum(v[0] for v in t) / 3)
                    cy.append(sum(v[1] for v in t) / 3)
                    kinds.append(p.kind)
        inside = shapely.contains_xy(lanes, np.array(cx), np.array(cy))
        print("\n  %d low furniture triangles, %d over a carriageway %s" % (
            len(cx), int(inside.sum()), [(kinds[i], round(cx[i], 2), round(cy[i], 2)) for i in np.nonzero(inside)[0]]))
        self.assertEqual(int(inside.sum()), 0)

    def test_nothing_in_lanes(self):
        """No pole, post or railing stands inside a carriageway (ground or raised, grown by 0.3 m)."""
        _p, _m, L, _bl, city, _r = geometry()
        fr = city.extras.furniture
        lanes = shapely.union_all([L.ground_polygon, L.elevated]).buffer(0.3)
        shapely.prepare(lanes)
        bad = [(n, f.centroid.coords[0]) for n, f in fr.feet if lanes.intersects(f)]
        for md in fr.medians:
            if md.kind == "railing":
                for line in md.lines:
                    self.assertFalse(line.intersects(L.ground_polygon.buffer(-0.05)))
        counts = {n: fr.count(n) for n in ("lamp_sector", "light_trunk", "signal", "billboard")}
        print("\n  placed %s; railing %.0f m; median barriers and posts; in a lane: %d" % (counts, fr.railing_m,
                                                                                         len(bad)))
        self.assertEqual(bad, [])
        self.assertGreater(counts["lamp_sector"], 30)
        self.assertGreater(counts["billboard"], 10)

    def test_signals_at_osm(self):
        """Each of OSM's 16 traffic-signal nodes has a signal pole within 25 m."""
        from tools.citymap import furniture
        _p, _m, _L, _bl, city, _r = geometry()
        fr = city.extras.furniture
        with open(DETAILS, encoding="utf-8") as f:
            d = json.load(f)
        nodes = [common.proj().to_render(e["lat"], e["lon"]) for e in d["elements"]
                 if e["type"] == "node" and e.get("tags", {}).get("highway") == "traffic_signals"]
        self.assertEqual(len(nodes), 16)
        poles = [p for _n, p in fr.signals]
        far = [n for n in nodes if min(math.dist(n, p) for p in poles) > furniture.SIGNAL_REACH]
        print("\n  %d signal nodes, %d poles, nodes without a pole within 25 m: %d" % (len(nodes), len(poles),
                                                                                    len(far)))
        self.assertEqual(far, [])

    def test_draw_pieces_per_view(self):
        """The seven viewpoints (the two spawns, Neelam Chowk, Bata Chowk, Old Faridabad station, Sector 16 Market,
        Marengo Asia): drawn pieces (meshes, every instance's), triangles and instances within the budget against the
        streets alone at the same spot (build_city.PLAIN_VIEWS, MESH_MARGIN, TRI_MARGIN; docs/ftown-notes.md), every
        view under Rockport's median loaded meshes and a quarter of the 5,000 draw records."""
        from tools.citymap import build_city
        from tools.citymap.tests import test_city
        info = test_city.built()[0]
        vs = info["views"]
        self.assertEqual(len(vs), 7)
        for v in vs:
            pi, pm, pt = build_city.PLAIN_VIEWS[v["name"]]
            print("\n  %-22s %4d instances %5d meshes (plain %4d, x%.2f) %7d triangles (plain %6d, x%.2f)" % (
                v["name"], v["instances"], v["meshes"], pm, v["meshes"] / pm, v["triangles"], pt,
                v["triangles"] / pt), end="")
            bm, bt, bi = build_city.view_budget(v["name"])
            self.assertLessEqual(v["meshes"], bm, v["name"])
            self.assertLessEqual(v["triangles"], bt, v["name"])
            # the tiles' instances: the street life's (2026-11-04) are held to the Run H fixes' + 15% by
            # test_streetlife.test_per_view_proxy
            self.assertLessEqual(v["instances"] - v.get("props", 0), bi, v["name"])
            self.assertLessEqual(v["meshes"], test_city.ROCKPORT["meshes_median"], v["name"])
            self.assertLess(v["instances"] - v.get("props", 0), test_city.DRAW_RECORDS / 4, v["name"])
        self.assertLess(info["instances"], test_city.DRAW_RECORDS)

    def test_route_still_drivable(self):
        """The stage 2 checks on the city file written with the furniture (tools/citymap/tests/test_city.py)."""
        from tools.citymap.tests import test_city
        c = test_city.City("test_route_drivable")
        c.test_route_drivable()
        c.test_no_barrier_on_road()
        c.test_written_centrelines_drivable()
        c.test_barriers_face_the_road()


if __name__ == "__main__":
    unittest.main()
