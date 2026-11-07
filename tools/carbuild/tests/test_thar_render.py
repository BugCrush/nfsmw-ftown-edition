"""Renders of the built Thar beside its source model, from the same cameras:
python -m unittest discover -s tools/carbuild/tests -p test_thar_render.py

Uses test_assemble.py's output (.superpowers/carbuild/thar/test/out; made here if missing) and writes
.superpowers/carbuild/thar/test/renders. Skips without Blender, the source model or the GTI.
"""
import os
import subprocess
import sys
import unittest

from common import GTI_GEOMETRY, REPO
from test_assemble import OUT
from test_prep import BLENDER, CARBIN, CONFIG, PREP, SOURCE

RENDERS = os.path.join(REPO, ".superpowers", "carbuild", "thar", "test", "renders")
VIEWS = ("front", "side", "rear", "three_quarter")


def mask(path):
    """The car's pixels (anything not near the white background) of a mask render, as a set of (x, y)."""
    from PIL import Image
    img = Image.open(path).convert("L")
    w, h = img.size
    px = img.load()
    return {(x, y) for y in range(0, h, 2) for x in range(0, w, 2) if px[x, y] < 128}


class TharRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in (BLENDER, SOURCE, GTI_GEOMETRY):
            if not os.path.exists(p):
                raise unittest.SkipTest("missing: " + p)
        if not os.path.exists(os.path.join(PREP, "parts.json")):
            subprocess.run([sys.executable, CARBIN, "prep", CONFIG, "--out", PREP], check=True, capture_output=True)
        if not os.path.exists(os.path.join(OUT, "desc", "car.json")):
            subprocess.run([sys.executable, CARBIN, "assemble", CONFIG, "--prep", PREP, "--out", OUT], check=True,
                           capture_output=True)
        r = subprocess.run([sys.executable, CARBIN, "render", os.path.join(OUT, "desc"), RENDERS,
                            "--compare", CONFIG, "--prep", PREP, "--wheels-at", os.path.join(OUT, "wheel_report.json")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError("render failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        cls.log = r.stdout

    def test_outputs(self):
        for v in VIEWS:
            for kind in ("built_", "source_", "mask_built_", "mask_source_"):
                self.assertTrue(os.path.exists(os.path.join(RENDERS, kind + v + ".png")), kind + v)
        self.assertTrue(os.path.exists(os.path.join(RENDERS, "compare_sheet.png")))

    def test_select_view(self):
        """--select renders one low front-right three-quarter view (as the car select shows the car) with the tyres at
        --wheel-z, where the game's rules put the wheel centres (conventions.fe_wheel_centre_z / race_...)."""
        out = os.path.join(RENDERS, "select")
        r = subprocess.run([sys.executable, CARBIN, "render", os.path.join(OUT, "desc"), out, "--wheels-at",
                            os.path.join(OUT, "wheel_report.json"), "--wheel-z", "0.2", "--select"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertTrue(os.path.exists(os.path.join(out, "select.png")))
        self.assertIn("wheel centre z 0.2", r.stdout)

    def test_silhouettes_match(self):
        for v in VIEWS:
            a = mask(os.path.join(RENDERS, "mask_source_%s.png" % v))
            b = mask(os.path.join(RENDERS, "mask_built_%s.png" % v))
            with self.subTest(view=v):
                self.assertGreater(len(a), 1000, "source mask nearly empty")
                iou = len(a & b) / len(a | b)
                self.assertGreaterEqual(iou, 0.92, "%s: intersection over union %.3f" % (v, iou))


CABIN_VIEWS = ("cabin_left", "cabin_front", "cabin_three_quarter")


def differing(a, b):
    """The share of pixels (every second one) that differ noticeably between two renders of the same size."""
    from PIL import Image
    x, y = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    w, h = x.size
    pa, pb = x.load(), y.load()
    n = d = 0
    for j in range(0, h, 2):
        for i in range(0, w, 2):
            n += 1
            if sum(abs(u - v) for u, v in zip(pa[i, j], pb[i, j])) > 30:
                d += 1
    return d / n


class TharCabinRenderTests(unittest.TestCase):
    """The borrowed interior and driver (Thar fix 2), rendered with and without them: the outside views (glass
    opaque in these renders) must not change (nothing pokes through the body or glass), the cabin views (windows
    left out, close on the glasshouse) must."""

    @classmethod
    def setUpClass(cls):
        for p in (BLENDER, GTI_GEOMETRY):
            if not os.path.exists(p):
                raise unittest.SkipTest("missing: " + p)
        if not os.path.exists(os.path.join(OUT, "desc", "car.json")):
            raise unittest.SkipTest("no assembled Thar in " + OUT)
        cls.full, cls.empty = os.path.join(RENDERS, "cabin"), os.path.join(RENDERS, "cabin-empty")
        # --masks on one of them: the cabin views come after the mask renders and must not inherit their shading
        for out, extra in ((cls.full, ["--masks"]), (cls.empty, ["--hide-interior"])):
            r = subprocess.run([sys.executable, CARBIN, "render", os.path.join(OUT, "desc"), out, "--cabin",
                                "--wheels-at", os.path.join(OUT, "wheel_report.json")] + extra,
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise AssertionError("render failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])

    def test_cabin_views_show_the_interior(self):
        for v in CABIN_VIEWS:
            with self.subTest(view=v):
                self.assertGreater(differing(os.path.join(self.full, v + ".png"),
                                             os.path.join(self.empty, v + ".png")), 0.02)

    def test_cabin_views_in_colour(self):
        from PIL import Image
        for v in CABIN_VIEWS:
            img = Image.open(os.path.join(self.full, v + ".png")).convert("RGB")
            px = list(img.getdata())[::7]
            coloured = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 20)  # a mask is greys only
            self.assertGreater(coloured / len(px), 0.01, v)

    def test_nothing_pokes_through(self):
        for v in VIEWS:
            with self.subTest(view=v):
                self.assertLess(differing(os.path.join(self.full, v + ".png"),
                                          os.path.join(self.empty, v + ".png")), 0.001)


if __name__ == "__main__":
    unittest.main()
