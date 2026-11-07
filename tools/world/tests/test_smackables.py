"""The breakable poles' spawner packs (tools/world/smackables.py):
python -m unittest discover -s tools/world/tests -p test_smackables.py

The proof of the writer: Rockport's own packs (STREAML2RA.BUN, every 0x34027 of the first sections that have one)
read and written again at the same position are byte for byte the file's; the quaternion from a heading equals
Rockport's records against their instances' matrices.
"""
import math
import os
import struct
import sys
import unittest

from common import L2RA, STREAM, TOOLS, need
from world import bun, scenery, smackables

sys.path.insert(0, os.path.join(TOOLS, "x360"))
from vlthash import vlt32  # noqa: E402


class Rockport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA, STREAM)
        cls.packs = []
        for s in bun.sections(L2RA):
            if s.size == 0 or len(cls.packs) >= 40:
                continue
            for c, pos in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
                if c.id == smackables.SPAWNER:
                    # pos counts from the section's start, which is 2,048-aligned in the file
                    cls.packs.append((s, c, pos))

    def test_packs_round_trip(self):
        self.assertGreaterEqual(len(self.packs), 40)
        for s, c, pos in self.packs:
            section, first, recs = smackables.read_pack(c.data, pos)
            raw = [struct.pack("<4f4f8I", *r["q"], *r["pos"], r["w"], r["model"], r["collision"], r["attributes"],
                               r["override"], r["uid"], r["exclude"], r["pointer"], r["pad"]) for r in recs]
            again = smackables.pack_chunk(section, first, raw, pos)
            self.assertEqual(again.data, c.data, s.name)
            self.assertTrue(all(r["pointer"] == 0 and r["pad"] == 0 and r["w"] == 1.0 for r in recs), s.name)

    def test_quaternion_from_heading(self):
        # two of Rockport's records (survey: StreetLightC in section 129, StreetLightCb in 204) and their instances'
        # model x axes in render (rows v0 of the scenery matrix)
        for row0, q in (((-0.4954833984375, 0.86865234375), (0.0, -0.864755392074585, 0.0, 0.5022532343864441)),
                        ((-0.7940673828125, -0.6077880859375), (-0.0, 0.9471186399459839, 0.0, 0.32089388370513916))):
            h = math.atan2(row0[1], row0[0])
            got = smackables.quaternion(h)
            for a, b in zip(got, q):
                self.assertAlmostEqual(a, b, places=3)


class Writer(unittest.TestCase):
    def test_file_round_trip(self):
        rec = smackables.make_record(smackables.quaternion(0.5), (1.0, 2.0, 3.0), vlt32("XO_StreetLightC_1b_00"),
                                     vlt32("XO_StreetLightC_1b_00"), vlt32("trafficlight"), 22340, 20000)
        rec2 = smackables.make_record(smackables.quaternion(1.5), (4.0, 5.0, 6.0), 7, 7, 8, 22341, 20001)
        data = smackables.write_file([(1100, 20000, [rec]), (1101, 20001, [rec2])], [(1100, 5, 0x8060),
                                                                                       (1101, 9, 0x8060)])
        base, entries, packs = smackables.read_file(data)
        self.assertEqual(base, 22340)
        self.assertEqual(entries, [(1100, 5, 0x8060), (1101, 9, 0x8060)])
        self.assertEqual([(p[0], p[1], len(p[2])) for p in packs], [(1100, 20000, 1), (1101, 20001, 1)])
        self.assertEqual(packs[1][2][0]["override"], 22341)
        self.assertEqual(packs[0][2][0]["pos"], (1.0, 2.0, 3.0))
        # every pack's data 16-aligned in the file (the loader's (chunk + 0x17) & ~0xF)
        off = 0
        while off < len(data):
            cid, size = struct.unpack_from("<II", data, off)
            if cid == smackables.SPAWNER:
                start = (off + 0x17) & ~0xF
                self.assertEqual(struct.unpack_from("<II", data, start), (0x0B, 0x0B))
                self.assertEqual(data[off + 8:start], b"\x11" * (start - off - 8))
            off += 8 + size

    def test_loader_bits_refused(self):
        with self.assertRaises(ValueError):
            smackables.make_record((0, 0, 0, 1), (0, 0, 0), 1, 1, 1, 0, 0, exclude=0x40040000)
        with self.assertRaises(ValueError):
            smackables.pack_chunk(1100, 0, [], 8)


if __name__ == "__main__":
    unittest.main()
