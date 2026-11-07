"""Own looks Task 2: the landmark faces drawn by us; no photo pixels in the city file.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_landmark_tex -v
"""
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

from tools.citymap.tests import common

for p in (common.TOOLS, os.path.join(common.TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)


def drawn():
    if "drawn_faces" not in common._cache:
        from tools.citymap import landmark_tex
        common._cache["drawn_faces"] = landmark_tex.draw_all()
    return common._cache["drawn_faces"]


class LandmarkTex(unittest.TestCase):
    def test_every_face_drawn(self):
        """One drawn texture per face texture of the registry, at the registry's size."""
        from tools.citymap import landmarks, phototex
        reg = landmarks.read()
        want = {n: tuple(f["tex"]) for n, f in phototex.faces(reg)}
        got = drawn()
        self.assertEqual(sorted(got), sorted(want))
        for n, (w, h, a) in got.items():
            self.assertEqual((w, h), want[n], n)
            self.assertEqual(a.shape, (h, w, 3), n)
            self.assertEqual(a.dtype, np.uint8)

    def test_build_reads_no_photo(self):
        """The build's face textures open no photo and nothing of phototex's output: every path the build's
        face_textures() opens or lists (open, PIL's Image.open, os.listdir, os.scandir) is recorded, none lies under
        the photos folder or phototex's (the review: the earlier version compared a function with itself)."""
        import builtins
        import io
        from PIL import Image
        from tools.citymap import build_city, landmarks, lettering, phototex
        seen = []
        saved = (builtins.open, io.open, Image.open, os.listdir, os.scandir)

        def spy(f):
            def g(p=".", *a, **k):
                seen.append(os.path.abspath(p) if isinstance(p, (str, bytes, os.PathLike)) else str(p))
                return f(p, *a, **k)
            return g
        builtins.open, io.open, Image.open, os.listdir, os.scandir = (spy(f) for f in saved)
        lettering._cache.clear()
        try:
            got = build_city.face_textures()
        finally:
            builtins.open, io.open, Image.open, os.listdir, os.scandir = saved
        self.assertEqual(sorted(got), sorted(drawn()))
        bad = [p for p in seen if os.path.abspath(landmarks.PHOTOS) in str(p) or
               os.path.abspath(phototex.OUT) in str(p)]
        print("\n  %d paths opened or listed while drawing the faces; under the photos: %d" % (len(seen), len(bad)))
        self.assertEqual(bad, [])
        # the spy sees a photo opened (it would fail a build that did)
        saved_open = Image.open
        Image.open = spy(saved_open)
        try:
            files = landmarks.photo_files()
            if files:
                Image.open(os.path.join(landmarks.PHOTOS, files[min(files)])).close()
        finally:
            Image.open = saved_open
        if files:
            self.assertTrue(any(os.path.abspath(landmarks.PHOTOS) in str(p) for p in seen[-1:]))

    def test_not_the_photo_crops(self):
        """Where the old photo crops still exist on this machine (git-ignored), no drawn face equals one, and none is
        a copy of its crop: the correlation of the two (grey, mean removed) is under 0.9."""
        from tools.citymap import phototex
        man_p = os.path.join(phototex.OUT, "manifest.json")
        if not os.path.exists(man_p):
            self.skipTest("no photo crops on this machine")
        with open(man_p) as f:
            man = json.load(f)["textures"]
        from PIL import Image
        crops = {r["sha256"] for r in man.values()}
        worst = 0.0
        for n, (_w, _h, a) in drawn().items():
            self.assertNotIn(hashlib.sha256(a.tobytes()).hexdigest(), crops, n)
            if n not in man:
                continue
            with Image.open(os.path.join(phototex.OUT, man[n]["png"])) as im:
                b = np.asarray(im.convert("RGB"), dtype=float)
            ga = a.astype(float) @ np.array([0.299, 0.587, 0.114])
            gb = b @ np.array([0.299, 0.587, 0.114])
            ga, gb = ga - ga.mean(), gb - gb.mean()
            r = float((ga * gb).sum() / np.sqrt((ga * ga).sum() * (gb * gb).sum()))
            worst = max(worst, r)
            self.assertLess(r, 0.9, n)
        print("\n  highest correlation of a drawn face with its old photo crop: %.2f" % worst)

    def test_colour_range(self):
        """Mean luminance 65-100 and mean chroma at most 48 (the range the photo textures were held to: Rockport's
        walls 73, plaster 85.9, sidewalk 94.6)."""
        for n, (_w, _h, a) in drawn().items():
            px = a.reshape(-1, 3).astype(float)
            lum = float((px @ np.array([0.299, 0.587, 0.114])).mean())
            chroma = float((px.max(1) - px.min(1)).mean())
            self.assertTrue(65.0 <= lum <= 100.0, (n, lum))
            self.assertLessEqual(chroma, 48.0, n)

    def test_committed_pngs_current(self):
        """tools/citymap/textures/ftl_*.png are the drawn faces (regenerate with landmark_tex.py)."""
        from PIL import Image
        from tools.citymap import landmark_tex
        for n, (_w, _h, a) in drawn().items():
            p = os.path.join(landmark_tex.OUT, n.lower() + ".png")
            self.assertTrue(os.path.exists(p), p)
            with Image.open(p) as im:
                self.assertTrue(np.array_equal(np.asarray(im.convert("RGB")), a), n)

    def test_pack_has_no_photo_texture(self):
        """The written city's texture pack: every FTL_ texture is the drawn face encoded (its DXT1 bytes, mip 0), and
        no texture's data equals an old photo texture's DXT (phototex manifest, when present)."""
        from chunks import bstringhash
        from world import texpack
        from tools.citymap import phototex
        from tools.citymap.tests import test_city
        ref = {bstringhash(n): (n, a) for n, (_w, _h, a) in drawn().items()}
        old = set()
        man_p = os.path.join(phototex.OUT, "manifest.json")
        if os.path.exists(man_p):
            with open(man_p) as f:
                old = {r["dxt_sha256"] for r in json.load(f)["textures"].values()}
        seen = 0
        for c, p in test_city.chunks_with_pos():
            if c.id != texpack.PACK:
                continue
            for t in texpack.read_pack(c, p).textures:
                self.assertNotIn(hashlib.sha256(t.data).hexdigest(), old)
                if t.name_hash in ref:
                    n, a = ref[t.name_hash]
                    w, h = struct.unpack_from("<hh", t.info, 0x44)
                    self.assertEqual(t.data[:w * h // 2], phototex.dxt1_encode(a), n)
                    seen += 1
        self.assertEqual(seen, len(ref))


if __name__ == "__main__":
    unittest.main()
