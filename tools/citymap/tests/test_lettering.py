"""Own looks Task 1: lettering drawn by Windows GDI (Latin and Devanagari, shaped by the system).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_lettering -v
"""
import unittest

import numpy as np


class Lettering(unittest.TestCase):
    def test_devanagari_shaped(self):
        """The i-matra (ि) is drawn before the consonant it follows in the text (shaping, not code-point order): in
        "कि" the leftmost ink column belongs to the matra, whose hook rises above the head line; unshaped text would
        put the matra's glyph after "क". And a whole word hangs from one head line (shirorekha)."""
        from tools.citymap import lettering
        ka = lettering.mask("क", "Nirmala UI", 96)
        ki = lettering.mask("कि", "Nirmala UI", 96)
        # the matra's hook stands above "क"'s head line: kI is taller than ka by the hook
        self.assertGreater(ki.shape[0], ka.shape[0] + 4)
        # its top row of ink is at the left (the matra's hook curves over the consonant from the left)
        top = np.nonzero(ki[2] > 0.5)[0]
        self.assertGreater(len(top), 0)
        self.assertLess(top.mean(), ki.shape[1] * 0.75)
        w = lettering.mask("अग्रवाल्स", "Nirmala UI", 96)
        rows = (w > 0.5).mean(1)
        self.assertGreater(rows.max(), 0.8)

    def test_deterministic(self):
        from tools.citymap import lettering
        lettering._cache.clear()
        a = lettering.mask("Marengo Asia Hospitals", "Arial", 48)
        lettering._cache.clear()  # the second draw is drawn again, not read from the cache (the review)
        b = lettering.mask("Marengo Asia Hospitals", "Arial", 48)
        self.assertEqual(a.shape, b.shape)
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(a.dtype, np.float32)
        self.assertTrue(0.0 <= a.min() and a.max() <= 1.0)

    def test_missing_font_fails(self):
        """A font that is not installed stops the build (GDI would draw the text in a substitute: Devanagari in a
        Latin font is boxes); every font the drawn textures name is installed."""
        from tools.citymap import housetex, landmark_tex, lettering
        with self.assertRaises(ValueError):
            lettering.mask("x", "No Such Font F-Town")
        used, raw = set(), lettering._raw

        def spy(text, font, *a):
            used.add(font)
            return raw(text, font, *a)
        lettering._raw = spy
        lettering._cache.clear()
        try:
            landmark_tex.draw_all()
            housetex.draw_street()
        finally:
            lettering._raw = raw
        print("\n  fonts drawn: %s" % sorted(used))
        self.assertTrue({"Nirmala UI", "Arial"} <= used)
        for name in sorted(used):
            self.assertTrue(lettering.installed(name), name)

    def test_draw_fits_box(self):
        from tools.citymap import lettering
        img = np.zeros((100, 300, 3), dtype=float)
        lettering.draw(img, "सेक्टर 16 ए", (40, 20, 260, 70), (255, 255, 255), font="Nirmala UI")
        ink = img[..., 0] > 1.0
        ys, xs = np.nonzero(ink)
        self.assertGreater(len(xs), 200)
        self.assertGreaterEqual(xs.min(), 40)
        self.assertLess(xs.max(), 260)
        self.assertGreaterEqual(ys.min(), 20)
        self.assertLess(ys.max(), 70)


if __name__ == "__main__":
    unittest.main()
