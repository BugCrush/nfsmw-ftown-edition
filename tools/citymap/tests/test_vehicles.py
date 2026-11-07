"""Street life Task 2: our own parked vehicles (tools/citymap/vehicles.py): auto-rickshaw, e-rickshaw, hatchback, SUV,
scooter, motorbike; low-poly, solid colours from our own drawn atlas FTC_VEHICLES.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_vehicles -v
"""
import math
import unittest

import numpy as np


def _normal(t):
    a, b, c = (np.array(p, float) for p in t)
    n = np.cross(b - a, c - a)
    return n, np.linalg.norm(n) / 2


class Vehicles(unittest.TestCase):
    def test_triangle_limits(self):
        """Every model under 400 triangles (the plan), and not trivially few."""
        from tools.citymap import vehicles
        for name in vehicles.KINDS:
            for variant in range(vehicles.VARIANTS):
                n = len(vehicles.model(name, variant))
                self.assertLess(n, 400, name)
                self.assertGreater(n, 30, name)

    def test_real_proportions(self):
        """Length, width and height within 5% of the real vehicle's (vehicles.REAL: Bajaj RE auto-rickshaw, a common
        e-rickshaw, Maruti Swift, Hyundai Creta, Honda Activa, Hero Splendor); wheels on the ground (z 0); the
        model's middle at the origin (x forward, y left)."""
        from tools.citymap import vehicles
        for name, (L, W, H) in vehicles.REAL.items():
            pts = np.array([p for t, _c in vehicles.model(name, 0) for p in t])
            lo, hi = pts.min(0), pts.max(0)
            self.assertAlmostEqual(hi[0] - lo[0], L, delta=0.05 * L, msg=name)
            self.assertAlmostEqual(hi[1] - lo[1], W, delta=0.05 * W, msg=name)
            self.assertAlmostEqual(hi[2] - lo[2], H, delta=0.05 * H, msg=name)
            self.assertAlmostEqual(lo[2], 0.0, places=3, msg=name)
            self.assertAlmostEqual((hi[0] + lo[0]) / 2, 0.0, delta=0.05 * L, msg=name)
            self.assertAlmostEqual((hi[1] + lo[1]) / 2, 0.0, delta=0.02, msg=name)
            self.assertEqual(vehicles.size(name), (L, W, H))

    def test_faces_outward(self):
        """The game draws only the side a triangle faces (notes "Run H fixes"): the model's faces point away from
        the part they bound; checked as: area-weighted, at least 85% of the area faces away from the model's
        vertical axis or up, and nothing faces straight down."""
        from tools.citymap import vehicles
        for name in vehicles.KINDS:
            out = inward = 0.0
            for t, _c in vehicles.model(name, 0):
                n, area = _normal(t)
                if area < 1e-9:
                    continue
                n = n / (2 * area)
                c = np.mean(np.array(t, float), 0)
                self.assertGreater(n[2], -0.99, name)
                radial = np.array([c[0], c[1], 0.0])
                if n[2] > 0.7 or np.dot(n, radial) > 0:
                    out += area
                else:
                    inward += area
            self.assertGreater(out / (out + inward), 0.85, name)

    def test_cells_in_the_atlas(self):
        """Every triangle names a cell of FTC_VEHICLES; the atlas is drawn (one solid colour a cell) and its cell
        centres carry the palette's colours."""
        from tools.citymap import textures, vehicles
        side, px = textures.draw()["vehicles"]
        self.assertEqual(textures.NAMES["vehicles"], "FTC_VEHICLES")
        img = np.array(px, float).reshape(side, side, 3)
        for name in vehicles.KINDS:
            for variant in range(vehicles.VARIANTS):
                for _t, cell in vehicles.model(name, variant):
                    self.assertIn(cell, vehicles.PALETTE)
        for cell, rgb in vehicles.PALETTE.items():
            u, v = vehicles.uv(cell)
            got = img[int(v * side), int(u * side)]
            self.assertLess(np.abs(got - np.array(rgb)).max(), 4, cell)

    def test_variants_differ_in_colour(self):
        """Cars come in the photos' common colours (white, silver, grey, black, navy, red): variants differ."""
        from tools.citymap import vehicles
        cells = {frozenset(c for _t, c in vehicles.model("hatchback", v)) for v in range(vehicles.VARIANTS)}
        self.assertGreater(len(cells), 3)
        self.assertEqual(len({vehicles.body_colour("hatchback", v) for v in range(vehicles.VARIANTS)}),
                         vehicles.VARIANTS)

    def test_place_turns_and_moves(self):
        """place() puts the model's +x along the heading at (x, y, z)."""
        from tools.citymap import vehicles
        L = vehicles.REAL["hatchback"][0]
        tris = vehicles.place("hatchback", 0, 100.0, 50.0, 0.15, math.pi / 2)
        pts = np.array([p for t, _c in tris for p in t])
        self.assertAlmostEqual(pts[:, 1].max() - pts[:, 1].min(), L, delta=0.05 * L)
        self.assertAlmostEqual(pts[:, 2].min(), 0.15, places=3)
        self.assertAlmostEqual((pts[:, 0].max() + pts[:, 0].min()) / 2, 100.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
