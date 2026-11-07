"""Renders of what the reader sees: python -m unittest discover -s tools/carbuild/tests -p test_render.py"""
import os
import subprocess
import sys
import tempfile
import unittest

from common import CARBUILD, GTI_GEOMETRY, GTI_TEXTURES, REPO, need

CARBIN = os.path.join(CARBUILD, "carbin.py")
BLENDER = os.path.join(REPO, ".tools", "blender-4.3.2-windows-x64", "blender.exe")
VIEWS = ("front.png", "side.png", "rear.png", "three_quarter.png")


class RenderTests(unittest.TestCase):
    def test_render_gti(self):
        need(self, GTI_GEOMETRY, GTI_TEXTURES)
        if not os.path.exists(BLENDER):
            self.skipTest("portable Blender missing at " + BLENDER)
        from PIL import Image
        scratch = os.path.join(REPO, ".superpowers", "carbuild")  # git-ignored; relative paths are part of the test
        os.makedirs(scratch, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as d:
            d = os.path.relpath(d, os.getcwd())
            desc, out = os.path.join(d, "gti"), os.path.join(d, "renders")
            for src in (GTI_GEOMETRY, GTI_TEXTURES):
                subprocess.run([sys.executable, CARBIN, "dump", src, desc], check=True, capture_output=True)
            r = subprocess.run([sys.executable, CARBIN, "render", desc, out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            for name in VIEWS:
                path = os.path.join(out, name)
                self.assertTrue(os.path.exists(path), name)
                img = Image.open(path).convert("RGB")
                self.assertEqual(img.size, (1280, 720), name)
                lo, hi = zip(*img.getextrema())
                self.assertGreater(max(hi) - min(lo), 64, name + " is (nearly) a single colour")
                # the car fills a good part of the frame: not just background
                bg = img.getpixel((2, 2))
                differing = sum(1 for px in img.resize((128, 72)).getdata() if max(abs(a - b) for a, b in zip(px, bg)) > 24)
                self.assertGreater(differing, 128 * 72 // 10, name + ": the car covers under 10% of the frame")
            self.assertIn("parts:", r.stdout)


if __name__ == "__main__":
    unittest.main()
