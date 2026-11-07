"""Elevation (2026-11-04): the study of the real ground (tools/citymap/elevation.py) and the city's height function
(tools/citymap/terrain.py).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_terrain -v
"""
import json
import math
import os
import unittest

import numpy as np

from tools.citymap.tests import common

DEM = os.path.join(common.REPO, ".superpowers", "elevation")


class Study(unittest.TestCase):
    def test_plane_fit_recovers_a_known_slope(self):
        """A 0.05% slope uphill at 30 degrees under 3 m of noise on the study's grid is found within 0.005%."""
        from tools.citymap import elevation
        rng = np.random.default_rng(3)
        X, Y = np.meshgrid(np.arange(0, 2800, 30.0), np.arange(0, 4000, 30.0))
        g = 0.0005
        a, b = g * math.cos(math.radians(30)), g * math.sin(math.radians(30))
        Z = 200 + a * X + b * Y + rng.normal(0, 3.0, X.shape)
        fa, fb, _c = elevation.fit_plane(X.ravel(), Y.ravel(), Z.ravel())
        self.assertLess(math.hypot(fa - a, fb - b), 0.00005)

    def test_smooth_keeps_a_plane_and_ignores_masked(self):
        """The normalised smoothing returns a constant field unchanged and gives masked cells no weight."""
        from tools.citymap import elevation
        g = np.full((60, 50), 5.0)
        m = np.ones(g.shape, bool)
        m[10:20, 10:20] = False
        g[~m] = 1000.0
        s = elevation.smooth(g, m, 4.0)
        self.assertTrue(np.allclose(s[~np.isnan(s)], 5.0))

    def test_terrain_json_is_the_study(self):
        """terrain.json is what the study of the downloaded data gives (skipped where the data is not downloaded)."""
        from tools.citymap import elevation
        if not os.path.exists(os.path.join(DEM, "copernicus", elevation.COP_TILE + ".tif")):
            self.skipTest("no elevation data downloaded (elevation.py fetch)")
        common.need(common.OSM)
        out, model = elevation.study(DEM, common.AREA)
        with open(elevation.TERRAIN_JSON) as f:
            have = json.load(f)
        self.assertEqual(have["model"], model["model"])
        self.assertAlmostEqual(have["dz_dx"], model["dz_dx"], places=7)
        self.assertAlmostEqual(have["dz_dy"], model["dz_dy"], places=7)
        print("\n  %s" % json.dumps({k: out["sources"][k]["grade_pct"] for k in out["sources"]}))


class Terrain(unittest.TestCase):
    def test_offset_is_the_model(self):
        """offset is terrain.json's plane, 0 at the first spawn (so a spawn at 101.00 there still finds its face);
        offsets agrees with offset; ground_z = tiles.GROUND_Z + offset."""
        from tools.citymap import terrain, tiles
        m = terrain.model()
        ax, ay = m["anchor"]
        self.assertEqual(terrain.offset(ax, ay), 0.0)
        self.assertEqual(terrain.offset(3231.43, 10414.57), 0.0)  # the first spawn (moved with geo.SHIFT)
        for x, y in ((1359.34, 8782.23), (0.0, 6568.0), (3500.0, 11468.0)):
            self.assertAlmostEqual(terrain.offset(x, y), m["dz_dx"] * (x - ax) + m["dz_dy"] * (y - ay), places=9)
            self.assertAlmostEqual(terrain.ground_z(x, y), tiles.GROUND_Z + terrain.offset(x, y), places=9)
        xs, ys = np.array([0.0, 1000.0, 2500.0]), np.array([9500.0, 11000.0, 13000.0])
        self.assertTrue(np.allclose(terrain.offsets(xs, ys), [terrain.offset(x, y) for x, y in zip(xs, ys)]))

    def test_grades_within_six_percent(self):
        """The ramps' rise (levels.GRADE) plus the terrain's steepest grade stays within 6%."""
        from tools.citymap import levels, terrain
        self.assertGreater(terrain.max_grade(), 0.0)
        self.assertLessEqual(levels.GRADE + terrain.max_grade(), 0.06 + 1e-12)

    def test_barrier_on_a_slope_spans_the_ground(self):
        """A barrier is a level box: on a steep plane (5%, so any error shows) a 100 m piece, as build_city and
        race_barriers write it, has its bottom at or below the ground and its top at or above its height over the
        ground at both ends (the final review: the plan's test was missing). The flat-city formula fails it."""
        from tools.citymap import build_city, race_barriers, terrain
        saved = terrain._model
        terrain._model = {"model": "plane", "dz_dx": 0.03, "dz_dy": 0.04, "anchor": [0.0, 0.0]}
        try:
            a, b = (1000.0, 2000.0), (1060.0, 2080.0)  # 100 m uphill, 5 m rise
            ga, gb = terrain.ground_z(*a), terrain.ground_z(*b)
            self.assertAlmostEqual(gb - ga, 5.0, places=6)
            got = [build_city._phys_barrier(a, b, 0.0, 1.0)[2:4], race_barriers._phys_wall(a, b)[2:4]]
            above = [1.0, race_barriers.WALL[1] - terrain.GROUND_Z]
            for (lo, hi), up in zip(got, above):
                self.assertLessEqual(lo, min(ga, gb) + 1e-9)
                self.assertGreaterEqual(hi, max(ga, gb) + up - 1e-9)
            # the flat city's barrier (bottom and top at GROUND_Z) would leave the uphill end 5 m under the ground
            flat_hi = terrain.GROUND_Z + 1.0
            self.assertLess(flat_hi, max(ga, gb) + 1.0)
        finally:
            terrain._model = saved

    def test_relief_over_the_city(self):
        """The offsets over the city's edge box span what the study found (about 3 m), none past 4 m."""
        from tools.citymap import terrain
        from tools.citymap import build_city, buildings, geo
        x0, y0, x1, y1 = buildings.edge_box(geo.Projection(), build_city.BBOX).bounds
        corners = [terrain.offset(x, y) for x in (x0, x1) for y in (y0, y1)]
        print("\n  offsets at the edge box's corners: %s" % ["%.2f" % c for c in corners])
        self.assertGreater(max(corners) - min(corners), 1.0)
        self.assertLess(max(abs(c) for c in corners), 4.0)


if __name__ == "__main__":
    unittest.main()
