"""Own looks Task 3: the house atlases FTC_HOUSES and FTC_STREET (drawn by us).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_housetex -v
"""
import os
import unittest

import numpy as np


def drawn():
    """Both atlases drawn afresh (lettering's cache cleared first: two draws compared are two draws, the review)."""
    from tools.citymap import housetex, lettering
    lettering._cache.clear()
    return housetex.draw_houses(), housetex.draw_street()


LUM = np.array([0.299, 0.587, 0.114])


class HouseTex(unittest.TestCase):
    def test_layout(self):
        """The facade blocks, the boundary strip and the cell row tile the atlas top to bottom; a cell's uvs stay 4 px
        inside it; facade_v counts from the parapet's top down; the shop strips stay inside the street atlas."""
        from tools.citymap import textures as T
        self.assertEqual(T.HOUSE_SPAN_M, 16.0)
        self.assertAlmostEqual(T.FACADE_M, 0.9 + 4 * 3.2)
        # (a texel inside each block since the review fixes: test_facade_inset)
        self.assertAlmostEqual(T.facade_v(0, 0.0), 1 / 1024)
        self.assertAlmostEqual(T.facade_v(0, T.FACADE_M), 447 / 1024)
        self.assertAlmostEqual(T.facade_v(1, 0.0), 449 / 1024)
        self.assertAlmostEqual(T.facade_v(1, T.FACADE_M), 895 / 1024)
        self.assertEqual(T.BOUNDARY_V, (896 / 1024, 960 / 1024))
        for k, cell in enumerate(T.HOUSE_CELLS):
            for s, t in ((0, 0), (1, 1), (0.5, 0.5)):
                u, v = T.house_cell_uv(cell, s, t)
                x, y = u * 1024, v * 1024
                self.assertTrue(k * 64 + 4 <= x <= k * 64 + 60, (cell, x))
                self.assertTrue(964 <= y <= 1020, (cell, y))
        for strip in range(T.STREET_STRIPS):
            a, b = T.street_v(strip, 0.0), T.street_v(strip, 3.2)
            self.assertTrue(0.0 <= a < b <= 1.0)
            if strip:
                self.assertGreaterEqual(a * 1024, T.street_v(strip - 1, 3.2) * 1024 + 4)

    def test_facade_tone(self):
        """The facade region (both blocks): mean luminance 70-100 and chroma at most 18 (the colour is the vertex
        tint's; Rockport's plaster 85.9 / 7.2, ours 87.8 / 11.0 before); the street atlas 65-100 / 48."""
        houses, street = drawn()
        f = houses[:896].reshape(-1, 3).astype(float)
        lum, ch = float((f @ LUM).mean()), float((f.max(1) - f.min(1)).mean())
        print("\n  facades: luminance %.1f chroma %.1f" % (lum, ch))
        self.assertTrue(70.0 <= lum <= 100.0, lum)
        self.assertLessEqual(ch, 18.0)
        s = street.reshape(-1, 3).astype(float)
        lum, ch = float((s @ LUM).mean()), float((s.max(1) - s.min(1)).mean())
        print("  street: luminance %.1f chroma %.1f" % (lum, ch))
        self.assertTrue(65.0 <= lum <= 100.0, lum)
        self.assertLessEqual(ch, 48.0)

    def test_rows_distinct(self):
        """Each storey row of each facade block has windows (dark texels 8-45% of it) and differs from the others."""
        from tools.citymap import textures as T
        houses, _s = drawn()
        g = houses.astype(float) @ LUM
        for b in range(2):
            rows = []
            for k in range(4):
                y0 = int(round(T.facade_v(b, 0.9 + 3.2 * k) * 1024))
                y1 = int(round(T.facade_v(b, 0.9 + 3.2 * (k + 1)) * 1024))
                r = g[y0:y1]
                dark = float((r < 60).mean())
                self.assertTrue(0.08 <= dark <= 0.45, (b, k, dark))
                rows.append(r[:100].copy())
            for i in range(4):
                for j in range(i + 1, 4):
                    self.assertFalse(np.array_equal(rows[i], rows[j]), (b, i, j))

    def test_seamless(self):
        """u wraps along a wall: the facades, the boundary strip and the shop strips run on across the atlas's left
        and right edges (the first and last columns differ no more than neighbouring columns do inside)."""
        houses, street = drawn()
        for img, y1 in ((houses, 960), (street, 1024)):
            a = img[:y1].astype(float)
            edge = np.abs(a[:, 0] - a[:, -1]).mean()
            inner = np.abs(a[:, 1:] - a[:, :-1]).mean()
            self.assertLess(edge, 4 * inner + 2, (edge, inner))

    def test_deterministic_and_committed(self):
        """Two draws are identical, and tools/citymap/textures/ftc_houses.png and ftc_street.png are the draw."""
        from PIL import Image
        from tools.citymap import textures as T
        a1, s1 = drawn()
        a2, s2 = drawn()
        self.assertTrue(np.array_equal(a1, a2) and np.array_equal(s1, s2))
        for name, img in (("ftc_houses.png", a1), ("ftc_street.png", s1)):
            p = os.path.join(T.HERE, "textures", name)
            self.assertTrue(os.path.exists(p), p)
            with Image.open(p) as im:
                self.assertTrue(np.array_equal(np.asarray(im.convert("RGB")), img), name)

    def test_ground_rows_have_doors(self):
        """Rows are counted from the roof down, so the ground storey of a 2-, 3- and 4-storey house is row 1, 2 and 3:
        each of those rows has a door bay in both blocks and no balcony door with railings (rows 1 and 2; the second
        review: 4,630 houses showed an upper-storey row at street level and no front door)."""
        from tools.citymap import housetex
        for b in (0, 1):
            for r in (1, 2, 3):
                self.assertIn("door", housetex.BAYS[b][r], (b, r))
            for r in (1, 2):
                self.assertNotIn("balc", housetex.BAYS[b][r], (b, r))

    def test_facade_inset(self):
        """A facade block's uvs stay a texel inside it (the review: v on the block's edge blends the next region:
        the cell row through wrap addressing above block 0, block 1's parapet under block 0, the boundary strip under
        block 1)."""
        from tools.citymap import textures as T
        for b in (0, 1):
            self.assertAlmostEqual(T.facade_v(b, 0.0), (448 * b + 1) / 1024)
            self.assertAlmostEqual(T.facade_v(b, T.FACADE_M), (448 * (b + 1) - 1) / 1024)
        for cell in T.HOUSE_CELLS:
            for t in (0.0, 1.0):
                v = T.house_cell_uv(cell, 0.5, t)[1] * 1024
                self.assertTrue(964 <= v <= 1016, (cell, v))

    def test_no_dark_seams(self):
        """Through the box-filtered mip chain (mips 0-3: a texel up to a quarter metre of wall), each facade block's
        top and bottom edge, sampled bilinearly at the v the walls use (wrap addressing), is at most 15 luminance
        darker than the block's own texel there (the review's bleed.py: up to 43-56 at the parapet's top, every mip)."""
        from tools.citymap import textures as T
        houses, _s = drawn()
        m = houses.astype(float) @ LUM
        worst = 0.0
        for level in range(4):
            if level:
                m = m.reshape(m.shape[0] // 2, 2, m.shape[1] // 2, 2).mean((1, 3))
            n = m.shape[0]
            for b in (0, 1):
                for v, inward in ((T.facade_v(b, 0.0), 1e-6), (T.facade_v(b, T.FACADE_M), -1e-6)):
                    c = v * n - 0.5
                    i0 = int(np.floor(c))
                    f = c - i0
                    got = (1 - f) * m[i0 % n] + f * m[(i0 + 1) % n]
                    own = m[int(np.floor((v + inward) * n)) % n]
                    d = float((own - got).max())
                    worst = max(worst, d)
                    self.assertLessEqual(d, 15.0, (level, b, v * 1024, round(d, 1)))
        print("\n  darkest facade edge against its own texel, mips 0-3: %.1f" % worst)

    def test_in_city_textures(self):
        """textures.draw() carries both atlases under their names, 1024 px square."""
        from tools.citymap import textures as T
        self.assertEqual(T.NAMES["houses"], "FTC_HOUSES")
        self.assertEqual(T.NAMES["street"], "FTC_STREET")
        d = T.draw()
        self.assertEqual(d["houses"][0], 1024)
        self.assertEqual(d["street"][0], 1024)


if __name__ == "__main__":
    unittest.main()
