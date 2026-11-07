"""The maker and model logos for the car select: python -m unittest discover -s tools/carbuild/tests -p test_logo.py

The rule (speed.exe, docs/carbuild-format.md "Logos in the car select"): the maker logo is the front-end texture
CARSELECT_MANUFACTURER_<maker> (0x591330; the Unlimiter's manufacturer hook names the maker from the frontend entry's
parent node), the model logo SECONDARY_LOGO_<frontend CollectionName> (0x591240); both names are hashed upper-cased
(0x5AF1C0), and a missing texture falls back to GENERIC_LOGO_128 / GENERIC_LOGO_256.
"""
import os
import struct
import tempfile
import unittest

from common import GAME, REPO, need, read
from chunks import bstringhash, find, read_chunks

LOGO_SRC = os.path.join(REPO, ".superpowers", "downloads", "cars", "thar", "logo", "Mahindra_Automotive_new_logo.png")
CHIRON_LOGOS = os.path.join(REPO, ".superpowers", "downloads", "cars", "697", "files", "Texture Compiler by MWInside",
                            "FRONTEND", "Add", "1")
FRONTB = os.path.join(GAME, "FRONTEND", "FrontB.lzc")


def dds_info(path):
    d = read(path)
    assert d[:4] == b"DDS "
    h, w = struct.unpack_from("<II", d, 12)
    mips = struct.unpack_from("<I", d, 28)[0]
    return w, h, mips, d[84:88]


def upper_hash(s):
    """The game's 0x5AF1C0: bStringHash with a..z upper-cased."""
    return bstringhash(s.upper())


class LogoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LOGO_SRC):
            raise unittest.SkipTest("logo download missing: " + LOGO_SRC)
        import logo
        cls.out = tempfile.mkdtemp(prefix="thar-logo-")
        cls.files = logo.make_logo_textures(LOGO_SRC, cls.out)

    def test_logo_names_match_lookup(self):
        names = sorted(os.path.basename(f) for f in self.files)
        self.assertEqual(names, ["CARSELECT_MANUFACTURER_MAHINDRA.dds", "SECONDARY_LOGO_THAR.dds"])
        # the names hash as the game's lookup does for maker node "mahindra" and frontend collection "thar"
        self.assertEqual(bstringhash("CARSELECT_MANUFACTURER_MAHINDRA"), upper_hash("CARSELECT_MANUFACTURER_" + "mahindra"))
        self.assertEqual(bstringhash("SECONDARY_LOGO_THAR"), upper_hash("SECONDARY_LOGO_" + "thar"))
        for f in self.files:
            self.assertTrue(os.path.isfile(f))
            self.assertEqual(os.path.dirname(os.path.abspath(f)), os.path.abspath(self.out))

    def test_sizes_and_formats_as_the_chirons(self):
        need(self, CHIRON_LOGOS)
        pairs = {"CARSELECT_MANUFACTURER_MAHINDRA.dds": "CARSELECT_MANUFACTURER_BUGATTI.dds",
                 "SECONDARY_LOGO_THAR.dds": "SECONDARY_LOGO_CHIRON.dds"}
        for ours, theirs in pairs.items():
            self.assertEqual(dds_info(os.path.join(self.out, ours)), dds_info(os.path.join(CHIRON_LOGOS, theirs)), ours)

    def test_alpha_and_picture(self):
        from PIL import Image
        for f in self.files:
            im = Image.open(f).convert("RGBA")
            lo, hi = im.getchannel("A").getextrema()
            self.assertEqual((lo, hi), (0, 255), f)
            box = im.getchannel("A").getbbox()
            # the logo fills most of the height and stays inside the frame
            self.assertGreater(box[3] - box[1], 0.6 * im.size[1], f)
            self.assertGreater(box[0], 0, f)
            self.assertLess(box[2], im.size[0], f)

    def test_dxt3_encoding_matches_the_picture(self):
        """The DDS decodes (Pillow's own DXT3 reader) to the picture it was made from, within block-coding error.
        Colours are compared as they show (multiplied by their alpha): a fully transparent pixel's colour is unseen."""
        from PIL import Image
        for f in self.files:
            want = Image.open(f.replace(".dds", ".png")).convert("RGBA")
            got = Image.open(f).convert("RGBA")
            self.assertEqual(want.size, got.size)
            err = [0.0] * 4
            for p, q in zip(want.getdata(), got.getdata()):
                for k in range(3):
                    err[k] += abs(p[k] * p[3] - q[k] * q[3]) / 255.0
                err[3] += abs(p[3] - q[3])
            n = want.size[0] * want.size[1]
            err = [e / n for e in err]
            self.assertLess(max(err), 6.0, (f, err))

    def test_nearly_transparent_pixels_do_not_pick_the_colours(self):
        """A block of grey pixels with one almost invisible yellow one (the download's edges have such pixels) keeps
        its greys: the end colours come from the visible pixels."""
        import logo
        px = [(96, 92, 87, 255), (82, 76, 69, 255), (112, 104, 98, 251), (79, 72, 67, 255)] * 3 + \
             [(255, 255, 0, 1), (0, 0, 0, 0), (191, 191, 191, 8), (95, 92, 85, 152)]
        alpha, v0, v1, idx = struct.unpack("<QHHI", logo._block(px))
        e0, e1 = logo._unpack565(v0), logo._unpack565(v1)
        pal = [e0, e1, tuple((2 * a + b) // 3 for a, b in zip(e0, e1)), tuple((a + 2 * b) // 3 for a, b in zip(e0, e1))]
        for i, p in enumerate(px):
            if p[3] > 128:
                q = pal[(idx >> (2 * i)) & 3]
                self.assertLess(max(abs(p[k] - q[k]) for k in range(3)), 16, (p, q))

    def test_names_are_new_in_the_games_front_end(self):
        need(self, FRONTB)
        top = read_chunks(read(FRONTB))
        hashes = set()
        for c in find(top, 0x33310002):
            hashes |= {struct.unpack_from("<I", c.data, k)[0] for k in range(0, len(c.data), 8)}
        self.assertIn(bstringhash("CARSELECT_MANUFACTURER_BUGATTI"), hashes)  # the reader works
        for f in self.files:
            self.assertNotIn(bstringhash(os.path.basename(f)[:-4]), hashes, f)


if __name__ == "__main__":
    unittest.main()
