"""Scenery sections (0x80034100) written by tools/world/scenery_write.py:
python -m unittest tools.world.tests.test_scenery_write -v

The round trip runs all 947 of Rockport's scenery sections through scenery.read_scenery (Part 1's reader) and
scenery_write.write_section, which rebuilds the header's number, every record, the tree's counts and the alignment
runs. New sections (make_section) are read back with the same reader.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import L2RA, STREAM, need  # noqa: E402
from chunks import chunk_bytes, read_chunks  # noqa: E402
from world import bun, scenery, scenery_write, solids  # noqa: E402

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def square(x0, y0, size, z=100.0):
    a, b, c, d = (x0, y0, z), (x0 + size, y0, z), (x0 + size, y0 + size, z), (x0, y0 + size, z)
    return [(a, b, c), (a, c, d)], [((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))]


def read_back(sc, pos=8):
    c = scenery_write.write_section(sc, pos)
    top = read_chunks(chunk_bytes(c))
    return scenery.read_scenery(top[0], pos)


class RoundTrip(unittest.TestCase):
    def test_all_sections_roundtrip(self):
        need(self, L2RA, STREAM)
        n = bad = 0
        first = None
        for s in bun.sections(L2RA):
            chunks = bun.read_range(STREAM, s.offset, s.size)
            for c, pos in scenery.with_positions(chunks, 0):
                if c.id != scenery.SCENERY_SECTION:
                    continue
                n += 1
                if chunk_bytes(scenery_write.write_section(scenery.read_scenery(c, pos), pos)) != chunk_bytes(c):
                    bad += 1
                    first = first or "%s at +0x%X" % (s.name, pos)
        print("\n  %d scenery sections, %d differ%s" % (n, bad, "" if not first else " (first: %s)" % first))
        self.assertEqual(n, 947)
        self.assertEqual(bad, 0)


class MakeSection(unittest.TestCase):
    def setUp(self):
        self.solids = {}
        for k, x in enumerate((0.0, 50.0, 100.0)):
            t, u = square(1000.0 + x, 2000.0, 40.0)
            so = solids.make_solid("FTOWN_T%d" % k, t, u, 0x1234)
            self.solids[so.name_hash] = so
        moved = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (5.0, 6.0, 7.0, 1.0))
        hs = list(self.solids)
        self.models = [("FTOWN_A", (hs[0],) * 3 + (0,), IDENTITY), ("FTOWN_B", (hs[1],) * 3 + (0,), IDENTITY),
                       ("FTOWN_C", (hs[2],) * 3 + (0,), moved)]

    def test_make_section_reads_back(self):
        sc = read_back(scenery_write.make_section(2601, self.models, self.solids))
        self.assertEqual(sc.number, 2601)
        self.assertEqual([i.name for i in sc.infos], ["FTOWN_A", "FTOWN_B", "FTOWN_C"])
        self.assertEqual([i.solid_hashes for i in sc.infos], [m[1] for m in self.models])
        self.assertEqual([sc.infos[i.info_index].name for i in sc.instances], ["FTOWN_A", "FTOWN_B", "FTOWN_C"])
        for inst, m in zip(sc.instances, self.models):
            self.assertEqual(inst.matrix, m[2])
            self.assertEqual(inst.preculler, 0)
            self.assertEqual(inst.lighting, -1)
            self.assertEqual(inst.exclude_flags, scenery_write.ROAD_EXCLUDE_FLAGS)
        # the preculler table holds one record with no hidden bits (every instance points at it)
        self.assertEqual(sc.other[scenery.PRECULLER], bytes(0x80))
        # the instance's box is its solid's vertex extents placed by the matrix
        c = sc.instances[2]
        self.assertAlmostEqual(c.bbox[0], 1105.0, places=3)
        self.assertAlmostEqual(c.bbox[5], 107.0, places=3)

    def test_make_section_flags_per_model(self):
        """A model may name its instance's exclude flags (F-Town's placed tiles: no 0x200, which draws without the
        matrix, Scenery.cpp:768); the others keep the road terrain's."""
        models = [self.models[0], self.models[2] + (0x8060,)]
        sc = read_back(scenery_write.make_section(1100, models, self.solids))
        self.assertEqual([i.exclude_flags for i in sc.instances], [scenery_write.ROAD_EXCLUDE_FLAGS, 0x8060])

    def test_make_section_tree_covers(self):
        many = [("FTOWN_%d" % k, m[1], m[2]) for k in range(37) for m in self.models[:1]]
        for models in (self.models, many):
            sc = read_back(scenery_write.make_section(2601, models, self.solids))
            nodes = scenery_write.parse_tree(sc.tree)
            seen, stack = [], [0]
            while stack:
                box, kids = nodes[stack.pop()]
                self.assertLessEqual(len(kids), 5)
                for k in kids:
                    if k >= 0:
                        seen.append(k)
                    else:
                        stack.append(-k)
            self.assertEqual(sorted(seen), list(range(len(sc.instances))))
            root = nodes[0][0]
            for inst in sc.instances:
                for a in range(3):
                    self.assertLessEqual(root[a], inst.bbox[a])
                    self.assertGreaterEqual(root[3 + a], inst.bbox[3 + a])

    def test_make_section_props_share_infos(self):
        """Props (F-Town's street life): instances of a model held elsewhere (named by hash only; no solid here) share
        one info per (name, slots, radius); the info's radius is the one given; each box is the given model box placed
        by the instance's matrix (scaled and turned); flags per prop; they come after the models' instances."""
        s, c = 0.5, 0.0
        turn = ((c * s, s, 0.0, 0.0), (-s, c * s, 0.0, 0.0), (0.0, 0.0, s, 0.0), (10.0, 20.0, 100.0, 1.0))
        box = (-2.0, -1.0, 0.0, 2.0, 1.0, 8.0)
        props = [("FTS_TREE", (0x12345678, 0, 0, 0), 11.5, box, turn, 0x208060),
                 ("FTS_TREE", (0x12345678, 0, 0, 0), 11.5, box, IDENTITY[:3] + ((0.0, 0.0, 100.0, 1.0),), 0x208060),
                 ("FTS_BENCH", (0x9ABCDEF0, 0, 0, 0), 30.0, box, turn, 0x40188060)]
        sc = read_back(scenery_write.make_section(1100, self.models[:1], self.solids, props=props))
        self.assertEqual([i.name for i in sc.infos], ["FTOWN_A", "FTS_TREE", "FTS_BENCH"])
        self.assertEqual(sc.infos[1].solid_hashes, (0x12345678, 0, 0, 0))
        self.assertAlmostEqual(sc.infos[1].radius, 11.5, places=4)
        self.assertEqual([i.info_index for i in sc.instances], [0, 1, 1, 2])
        self.assertEqual([i.exclude_flags for i in sc.instances[1:]], [0x208060, 0x208060, 0x40188060])
        t = sc.instances[1]
        self.assertEqual(t.matrix, turn)
        # x' = p.x v0 + p.y v1: the box's x (-2..2) turns onto y (-1..1 after the 0.5 scale), y onto x
        for got, want in zip(t.bbox, (9.5, 19.0, 100.0, 10.5, 21.0, 104.0)):
            self.assertAlmostEqual(got, want, places=4)
        self.assertEqual(sc.infos[1].checksum, 0x12345678)

    def test_make_section_radius_reaches_from_the_instance(self):
        sc = read_back(scenery_write.make_section(2601, self.models[:1], self.solids))
        far = max((x * x + y * y + z * z) ** 0.5 for x in (1000.0, 1040.0) for y in (2000.0, 2040.0) for z in (100.0,))
        self.assertAlmostEqual(sc.infos[0].radius, far, places=1)


if __name__ == "__main__":
    unittest.main()
