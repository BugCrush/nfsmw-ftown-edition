"""Task 2 (landmarks plan): textures cut from the user's photos.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_phototex -v

The photos (ftownphotos/) and everything made from them stay out of git: the outputs go under
.superpowers/citymap/faridabad/phototex/ (git-ignored); the tests skip when the photos are missing.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import unittest

import numpy as np

from tools.citymap.tests import common

for p in (common.TOOLS, os.path.join(common.TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

OUT = os.path.join(common.AREA, "phototex")
OUT2 = os.path.join(common.SCRATCH, "phototex-again")


def need_photos():
    from tools.citymap import landmarks
    if not landmarks.photo_files():
        raise unittest.SkipTest("ftownphotos/ is missing (the user's photos, git-ignored)")


def built():
    if "phototex" not in common._cache:
        from tools.citymap import landmarks, phototex
        need_photos()
        common._cache["phototex"] = phototex.build_all(landmarks.read(), landmarks.PHOTOS, OUT)
    return common._cache["phototex"]


class Encoder(unittest.TestCase):
    def test_fast_dxt1_matches_reference(self):
        """The numpy DXT1 encoder gives the same bytes as tools/world/texpack.py's (the reference) on random and flat
        blocks."""
        from world import texpack
        from tools.citymap import phototex
        rng = random.Random(3)
        w, h = 32, 16
        px = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(w * h)]
        px[:4] = [(10, 20, 30)] * 4
        for k in range(4):  # one flat block
            for x in range(4):
                px[k * w + 8 + x] = (200, 100, 50)
        self.assertEqual(phototex.dxt1_encode(np.array(px, dtype=np.uint8).reshape(h, w, 3)),
                         texpack.dxt1_encode(px, w, h))


class PhotoTextures(unittest.TestCase):
    def test_rectified_size(self):
        """Every face's texture is its registry size (powers of two), one per texture name."""
        from PIL import Image
        man = built()
        from tools.citymap import landmarks
        sizes = {}
        for d in landmarks.read()["landmarks"]:
            for k, f in enumerate(d.get("faces", [])):
                name = phototex.texture_name(f.get("name") or "%s_%d" % (d["key"], k))
                sizes.setdefault(name, tuple(f["tex"]))
        self.assertEqual(sorted(sizes), sorted(man["textures"]))
        for name, rec in man["textures"].items():
            with Image.open(os.path.join(OUT, rec["png"])) as im:
                self.assertEqual(im.size, sizes[name], name)
            self.assertLessEqual(len(name), 23)
            self.assertNotIn("aridabad", name.lower())
        print("\n  %d photo textures in %s" % (len(man["textures"]), OUT))

    def test_deterministic(self):
        """Two builds give the same bytes (sha256 of every texture's pixels and DXT data)."""
        from tools.citymap import landmarks, phototex
        man = built()
        shutil.rmtree(OUT2, ignore_errors=True)
        again = phototex.build_all(landmarks.read(), landmarks.PHOTOS, OUT2)
        self.assertEqual({k: (v["sha256"], v["dxt_sha256"]) for k, v in man["textures"].items()},
                         {k: (v["sha256"], v["dxt_sha256"]) for k, v in again["textures"].items()})

    def test_outputs_ignored(self):
        """git check-ignore covers every photo-derived output (each texture, the manifest, the sheet, the test copy):
        none of it can be committed."""
        man = built()
        paths = [os.path.join(OUT, r["png"]) for r in man["textures"].values()]
        paths += [os.path.join(OUT, "manifest.json"), os.path.join(OUT, "sheet.png"), os.path.join(OUT2, "x.png")]
        for p in paths:
            r = subprocess.run(["git", "check-ignore", "-q", os.path.relpath(p, common.REPO)], cwd=common.REPO)
            self.assertEqual(r.returncode, 0, p)
        r = subprocess.run(["git", "check-ignore", "-q", "ftownphotos/x.jpeg"], cwd=common.REPO)
        self.assertEqual(r.returncode, 0)

    def test_colour_range(self):
        """Each texture, decoded from its DXT1 data as the game reads it: mean luminance and chroma inside the range
        recorded in docs/ftown-notes.md ("Landmarks and street furniture"): luminance 65-100 (Rockport's walls overall
        73, plaster 85.9, sidewalk 94.6; ours 82-92 since the city fixes), mean chroma at most 48 (signage keeps its
        colour; Rockport's billboards and shop signs are its most colourful textures)."""
        from world import texpack
        from tools.citymap import phototex
        man = built()
        got = {}
        for name, rec in man["textures"].items():
            with open(os.path.join(OUT, rec["dxt"]), "rb") as f:
                data = f.read()
            w, h = rec["size"]
            px = np.array(texpack.dxt1_decode(data[:w * h // 2], w, h), dtype=float)
            lum = float((px @ np.array([0.299, 0.587, 0.114])).mean())
            chroma = float((px.max(1) - px.min(1)).mean())
            got[name] = (round(lum, 1), round(chroma, 1))
            self.assertTrue(phototex.LUM[0] <= lum <= phototex.LUM[1], (name, lum))
            self.assertLessEqual(chroma, phototex.CHROMA_MAX, name)
        print("\n  luminance, chroma: %s" % got)


from tools.citymap import phototex  # noqa: E402


if __name__ == "__main__":
    unittest.main()
