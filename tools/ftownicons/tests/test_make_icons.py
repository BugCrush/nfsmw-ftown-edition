"""tools/ftownicons/make_icons.py: run with .tools/cityenv/Scripts/python -m unittest discover -s tools/ftownicons/tests"""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(TOOL))
for p in (TOOL, os.path.join(REPO, "tools", "carbuild"), os.path.join(REPO, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image  # noqa: E402

import make_icons  # noqa: E402
from chunks import bstringhash, read_chunks  # noqa: E402
from world import texpack  # noqa: E402

GLOBALB = os.path.join(REPO, "Need For Speed Most Wanted Black Edition", "GLOBAL", "GLOBALB.BUN")


def fake_icons(d):
    """Stand-ins for the user's logos (their real files are git-ignored): the same kinds of picture."""
    a = Image.new("RGB", (1254, 1254), (255, 255, 255))
    a.paste((0, 0, 0), (200, 200, 600, 1000))
    a.save(os.path.join(d, "ftown-morning.png"))
    b = Image.new("RGB", (1254, 1254), (0, 0, 0))
    b.paste((255, 255, 255), (200, 200, 600, 1000))
    b.save(os.path.join(d, "ftown-evening.png"))
    c = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    c.paste((0, 0, 0, 255), (80, 80, 120, 120))
    c.save(os.path.join(d, "freeroam.png"))


def decode_dxt3(data, w, h):
    px = [None] * (w * h)
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha = struct.unpack_from("<Q", data, o)[0]
            c0, c1, idx = struct.unpack_from("<HHI", data, o + 8)
            o += 16
            e0, e1 = texpack._from565(c0), texpack._from565(c1)
            pal = [e0, e1, tuple((2 * x + y) // 3 for x, y in zip(e0, e1)),
                   tuple((x + 2 * y) // 3 for x, y in zip(e0, e1))]
            for k in range(16):
                px[(by + k // 4) * w + bx + k % 4] = pal[(idx >> 2 * k) & 3] + (((alpha >> 4 * k) & 15) * 17,)
    return px


class IconsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="ftown-icons-")
        fake_icons(cls.dir)
        cls.blob = make_icons.build(cls.dir)
        top = read_chunks(cls.blob)
        cls.top = top
        cls.pack = texpack.read_pack(top[0], 8)

    def test_one_texture_pack_with_the_three_names(self):
        self.assertEqual([c.id for c in self.top if c.id], [0xB3300000])
        self.assertEqual(sorted(t.name_hash for t in self.pack.textures),
                         sorted(bstringhash(n) for n in ("FTOWN_ICON_MORNING", "FTOWN_ICON_EVENING", "FTOWN_ICON_FREEROAM")))

    def test_dxt3_128_one_level(self):
        for t in self.pack.textures:
            w, h = struct.unpack_from("<hh", t.info, 0x44)
            self.assertEqual((w, h, t.info[0x4A], t.info[0x4E], len(t.data)), (128, 128, 0x24, 1, 128 * 128))
            self.assertEqual(t.comp[0x14:0x18], b"DXT3")

    def test_pictures(self):
        by = {t.name_hash: decode_dxt3(t.data, 128, 128) for t in self.pack.textures}
        morning = by[bstringhash("FTOWN_ICON_MORNING")]
        evening = by[bstringhash("FTOWN_ICON_EVENING")]
        free = by[bstringhash("FTOWN_ICON_FREEROAM")]
        self.assertEqual(morning[0][:3], (255, 255, 255))  # white paper
        self.assertEqual(morning[64 * 128 + 30][:3], (0, 0, 0))  # the black bar
        self.assertEqual(evening[0][:3], (0, 0, 0))
        self.assertTrue(all(p[3] == 255 for p in morning + evening))  # opaque
        self.assertEqual(free[0][3], 0)  # transparent around the glyph
        centre = free[64 * 128 + 64]
        self.assertEqual(centre[3], 255)
        self.assertGreater(min(centre[:3]), 240)  # drawn white

    @unittest.skipUnless(os.path.exists(GLOBALB), "the game's GLOBALB.BUN")
    def test_record_as_the_games_mode_icon(self):
        found = []

        def walk(cs):
            for c in cs:
                if c.id == texpack.PACK:
                    try:
                        for t in texpack.read_pack(c, 0).textures:
                            if t.name_hash == 0xAAAB31E9:  # MODE_ICON_DRAG
                                found.append(t)
                    except ValueError:
                        pass
                elif c.children:
                    walk(c.children)
        walk(read_chunks(open(GLOBALB, "rb").read()))
        self.assertTrue(found)
        g = found[0]
        for t in self.pack.textures:
            self.assertEqual(t.info[0x4F:0x68], g.info[0x4F:0x68])
            self.assertEqual(t.comp, g.comp)
            self.assertEqual(t.info[0x4A], g.info[0x4A])


if __name__ == "__main__":
    unittest.main()
