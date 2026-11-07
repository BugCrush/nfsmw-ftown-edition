"""F-Town's evening lights (docs/ftown-notes.md "Evening (2026-11-05)"): glow classes in the vertex colours' alpha, the
lights list written beside the city, window panes behind the walls, furniture and signal classes, and the built city."""
import math
import os
import struct
import unittest

from tools.citymap.tests import common


def _city_file(groups):
    """A one-list chunk file (as the city's) of one solid made from groups; returns its bytes."""
    from tools.carbuild.chunks import write_chunks
    from tools.world import solids
    so = solids.make_solid_multi("TEST_SOLID", groups)
    lst = solids.new_list([so], "Test.bin", "")
    return write_chunks([solids.write_list(lst, 8)])


TRI = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0))  # normal (0, -1, 0)
TRI2 = ((5.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 0.0, 1.0))
UV = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))


class Classes(unittest.TestCase):
    def test_glow_keeps_rgb_and_sets_the_class_alpha(self):
        from tools.citymap import evening
        for cls, (alpha, _rgb) in evening.CLASSES.items():
            c = evening.glow(0xFF123456, cls)
            self.assertEqual(c & 0xFFFFFF, 0x123456)
            self.assertEqual(c >> 24, alpha, cls)

    def test_classes_distinct_and_below_opaque(self):
        from tools.citymap import evening
        alphas = [a for a, _rgb in evening.CLASSES.values()]
        self.assertEqual(len(set(alphas)), len(alphas))
        self.assertTrue(all(0xF0 <= a < 0xFF for a in alphas))
        self.assertEqual(set(evening.CLASSES), {"lamp", "sig_red", "sig_amber", "sig_green", "board", "shop",
                                                "station", "pane", "letters_neelam", "letters_bata",
                                                "letters_oldfbd"})


class Table(unittest.TestCase):
    def test_table_lists_marked_vertices_only(self):
        from tools.citymap import evening
        lamp = evening.glow(0xFF404040, "lamp")
        pane = evening.glow(0xFF303030, "pane")
        data = _city_file([(1, "a", [TRI], [UV], [0xFF505050]), (2, "b", [TRI2], [UV], [lamp]),
                           (3, "c", [TRI], [UV], [pane])])
        table = evening.lights_table(data)
        self.assertEqual(len(table), 6)
        by_day = {}
        for off, dx, dy, dz, day, eve in table:
            self.assertEqual(struct.unpack_from("<I", data, off + 24)[0], day)
            by_day.setdefault(day, []).append((off, dx, dy, dz, eve))
        self.assertEqual(set(by_day), {lamp, pane})
        for off, dx, dy, dz, eve in by_day[lamp]:
            self.assertEqual((dx, dy, dz), (0.0, 0.0, 0.0))
            r, g, b = evening.CLASSES["lamp"][1]
            self.assertEqual(eve, 0xFF000000 | r << 16 | g << 8 | b)
        for off, dx, dy, dz, eve in by_day[pane]:
            n = struct.unpack_from("<3f", data, off + 12)
            for d, c in zip((dx, dy, dz), n):
                self.assertAlmostEqual(d, c * evening.PANE_SHIFT, places=5)

    def test_apply_moves_and_recolours_and_refuses_a_stale_list(self):
        from tools.citymap import evening
        pane = evening.glow(0xFF303030, "pane")
        data = _city_file([(3, "c", [TRI], [UV], [pane])])
        table = evening.lights_table(data)
        out = evening.apply(data, table)
        for off, dx, dy, dz, day, eve in table:
            self.assertEqual(struct.unpack_from("<I", out, off + 24)[0], eve)
            p0 = struct.unpack_from("<3f", data, off)
            p1 = struct.unpack_from("<3f", out, off)
            self.assertAlmostEqual(p1[1] - p0[1], dy, places=5)
        bad = [(table[0][0],) + table[0][1:4] + (0xFF000000, table[0][5])]
        with self.assertRaises(ValueError):
            evening.apply(data, bad)

    def test_written_file(self):
        from tools.citymap import evening
        lamp = evening.glow(0xFF404040, "lamp")
        data = _city_file([(2, "b", [TRI2], [UV], [lamp])])
        os.makedirs(common.SCRATCH, exist_ok=True)
        path = os.path.join(common.SCRATCH, "evening-test.bin")
        counts = evening.write_lights(data, path)
        self.assertEqual(counts, {"lamp": 3})
        with open(path, "rb") as f:
            raw = f.read()
        magic, ver, size, n, zero = struct.unpack_from("<4sIIII", raw, 0)
        self.assertEqual((magic, ver, size, n, zero), (b"FTEV", 1, len(data), 3, 0))
        self.assertEqual(len(raw), 20 + 24 * 3)
        self.assertEqual(evening.read_lights(path), evening.lights_table(data))


class Panes(unittest.TestCase):
    def test_window_rects(self):
        from tools.citymap import housetex
        for block in (0, 1):
            for row in range(4):
                for x, y0, w, h in housetex.window_rects(block, row):
                    self.assertTrue(0.0 <= x and x + w <= 16.0 + 1e-6)
                    self.assertTrue(0.0 <= y0 and y0 + h <= 3.2)
        self.assertGreater(len(housetex.window_rects(0, 0)), 1)

    def test_panes_behind_the_wall_facing_out(self):
        from tools.citymap import evening, parts as P
        p, q = (0.0, 0.0), (40.0, 0.0)  # outward on the right: -y
        tris, uvs = evening.wall_panes(p, q, 0.0, 9.6, 0, 3.0, key=7, percent=100)
        self.assertGreater(len(tris), 10)
        self.assertEqual(len(tris), len(uvs))
        for t in tris:
            n = P.normal(t)
            self.assertAlmostEqual(n[1], -1.0, places=6)
            for x, y, z in t:
                self.assertAlmostEqual(y, evening.PANE_IN, places=6)  # inside: +y, 5 cm behind the wall
                self.assertTrue(0.0 <= x <= 40.0 and 0.0 <= z <= 9.6 + 0.9)

    def test_pane_depth_margin(self):
        """The review: a 24-bit depth step with the game's 0.5 m near plane is z^2 / (0.5 x 2^24) (5.8 cm at the 700 m
        far switch): hidden by day and in front in the evening by at least 1.5 steps there."""
        from tools.citymap import evening, tiles
        step = tiles.FAR_SWITCH ** 2 / (0.5 * 2 ** 24)
        self.assertGreaterEqual(evening.PANE_IN, 2.5 * step)
        self.assertGreaterEqual(evening.PANE_SHIFT - evening.PANE_IN, 1.5 * step)

    def test_panes_share_and_fraction(self):
        from tools.citymap import evening
        all_ = evening.wall_panes((0.0, 0.0), (160.0, 0.0), 0.0, 12.8, 1, 0.0, key=3, percent=100)[0]
        some = evening.wall_panes((0.0, 0.0), (160.0, 0.0), 0.0, 12.8, 1, 0.0, key=3, percent=25)[0]
        self.assertTrue(0.1 < len(some) / len(all_) < 0.4, len(some) / len(all_))


class Furniture(unittest.TestCase):
    def test_lanterns_and_one_signal_lamp(self):
        from tools.citymap import evening, furniture, furniture_models as FM, parts as P
        part = P.Part("ground", "furniture", levels=("A",))
        furniture._add_model(part, FM.lamp_sector(), 0.0, 0.0, 0.0, 0.0)
        lamps = [c for c in part.cols if c >> 24 == evening.CLASSES["lamp"][0]]
        self.assertEqual(len(lamps), 10)  # the lantern box: 4 sides and its top
        self.assertTrue(all(c >> 24 in (0xFF, evening.CLASSES["lamp"][0]) for c in part.cols))
        for k, cls in enumerate(("sig_red", "sig_green", "sig_amber")):
            part = P.Part("ground", "furniture", levels=("A",))
            furniture._add_model(part, FM.signal(), 0.0, 0.0, 0.0, 0.0, signal=k)
            marked = [c >> 24 for c in part.cols if c >> 24 != 0xFF]
            self.assertEqual(marked, [evening.CLASSES[cls][0]] * 4, cls)  # both faces' lit lamp


class BuiltCity(unittest.TestCase):
    def test_city_and_lights_file(self):
        """Every vertex of the written city is opaque or a glow class; every class is there; ftown-evening.bin is
        the city's own list."""
        from tools.citymap import evening
        city = os.path.join(common.REPO, "ftown", "ftown-city.bun")
        lights = os.path.join(common.REPO, "ftown", "ftown-evening.bin")
        common.need(city, lights)
        with open(city, "rb") as f:
            data = f.read()
        alphas = evening.vertex_alphas(data)
        known = {a for a, _rgb in evening.CLASSES.values()} | {0xFF}
        self.assertEqual(set(alphas) - known, set())
        # The breakable poles (2026-11-05) replaced our signal poles at every junction with Rockport's XO_TrafficLightB
        # (by hash, unlit by our evening), so the signal lamp classes no longer occur in the built city.
        gone = {"sig_red", "sig_green", "sig_amber"}
        for cls, (a, _rgb) in evening.CLASSES.items():
            if cls in gone:
                self.assertEqual(alphas.get(a, 0), 0, cls)
            else:
                self.assertGreater(alphas.get(a, 0), 0, cls)
        self.assertEqual(evening.read_lights(lights), evening.lights_table(data))


if __name__ == "__main__":
    unittest.main()
