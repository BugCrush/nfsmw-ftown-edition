"""The road network's records (tools/world/roadnet.py): python -m unittest discover -s tools/world/tests -p test_roadnet.py

The proof of the writer: Rockport's own network (L2RA.BUN chunk 0x3B800, UGroup 'CARP' > 'RNgp') decoded and written
again is byte for byte the file's, item by item and as the whole region the five items fill.
"""
import os
import unittest

from common import L2RA, need
from world import bun, roadnet, scenery


def _rockport():
    cs = bun.read_file(L2RA)
    for c, pos in scenery.with_positions(cs, 0):
        if c.id == 0x3B800:
            return c.data, pos
    raise AssertionError("no chunk 0x3B800")


class RoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA)
        cls.data, cls.pos = _rockport()
        cls.net, cls.region, cls.offset = roadnet.read_rngp(cls.data, cls.pos)

    def test_counts(self):
        h = self.net.header
        self.assertEqual((h.profiles, h.nodes, h.segments, h.intersections, h.roads, h.junctions),
                         (710, 4385, 6538, 0, 1308, 0))
        self.assertEqual((len(self.net.profiles), len(self.net.nodes), len(self.net.segments), len(self.net.roads)),
                         (710, 4385, 6538, 1308))

    def test_items_byte_for_byte(self):
        items = roadnet.rngp_items(self.data, self.pos)
        again = roadnet.encode(roadnet.decode(items))
        for k in ("RNhd", "RNnd", "RNpf", "RNrd", "RNsg"):
            self.assertEqual(again[k], items[k], k)

    def test_region_byte_for_byte(self):
        self.assertEqual(roadnet.rngp_region(self.net), self.region)
        self.assertEqual(len(self.region), 0x8697C - 0x33910)

    def test_decoded_values(self):
        p = self.net.profiles[5]
        self.assertEqual((p.zones, p.middle), (9, 4))
        t, w, o = roadnet.lane(p.words[1])
        self.assertEqual(t, 1)
        self.assertAlmostEqual(w, 3.992, places=3)
        self.assertAlmostEqual(o, 17.995, places=3)
        s = self.net.segments[36]
        self.assertEqual((s.nodes, s.road, s.index, s.flags), ((29, 30), 23, 36, 16))
        self.assertEqual(s.start_handle, (-126, 0, -5))
        n = self.net.nodes[0]
        self.assertEqual(n.index, 0)
        self.assertEqual(len(n.segments), self.net.nodes[0].count)


class Encoding(unittest.TestCase):
    def test_lane_word(self):
        w = roadnet.lane_word(1, 3.992, 17.995)
        self.assertEqual(roadnet.lane(w)[0], 1)
        self.assertAlmostEqual(roadnet.lane(w)[1], 3.992, places=2)
        self.assertAlmostEqual(roadnet.lane(w)[2], 17.995, places=2)
        neg = roadnet.lane_word(3, 0.5, -5.25)
        self.assertAlmostEqual(roadnet.lane(neg)[2], -5.25, places=2)

    def test_make_profile(self):
        p = roadnet.Profile.make([(1, 2.75, 1.375), (1, 2.75, 1.375)], 1)
        self.assertEqual((p.zones, p.middle, p.pad), (2, 1, b"\xaa\xaa"))
        self.assertEqual(p.words[2:], [0xAAAAAAAA] * 13)
        self.assertEqual(len(roadnet.encode_profile(p)), 64)

    def test_new_records_round_trip(self):
        net = roadnet.Network(
            roadnet.Header(1, 2, 1, 0, 1, 0, b"\0\0"),
            [roadnet.Profile.make([(1, 3.5, 1.75)], 0)],
            [roadnet.Node((1.0, 2.0, 3.0), 0, 0, [0]), roadnet.Node((4.0, 2.0, 3.0), 1, 0, [0])],
            [roadnet.Segment.make(0, 1, 3.0, 0, 0, roadnet.CURVED, (1, 0, 0), (1, 0, 0), 1.0, 1.0)],
            [roadnet.Road(256, 49, 255, 35, 0)])
        again = roadnet.decode(roadnet.encode(net))
        self.assertEqual(roadnet.encode(again), roadnet.encode(net))
        s = again.segments[0]
        self.assertAlmostEqual(s.length_m, 3.0, delta=1000.0 / 65535)  # one step of the length
        self.assertEqual(s.start_handle, (127, 0, 0))
        self.assertEqual(s.end_handle, (-127, 0, 0))  # stored backwards (GetEndForwardVec uses -1/127)
        self.assertEqual(again.nodes[1].unused, [0xAAAA] * 6)  # Rockport's filler (every unused slot, 17,619)
        self.assertEqual(again.nodes[1].pad, 0xAA)


if __name__ == "__main__":
    unittest.main()
