"""World texture packs (0xB3300000 as the streaming sections carry them) written by tools/world/texpack.py:
python -m unittest tools.world.tests.test_texpack -v

Rockport's sections carry texture packs in another layout than the cars' TEXTURES.BIN (tools/carbuild/textures.py):
TextureInfo records (0x33310004) and format records (0x33310005) with the pixel data stored uncompressed in one data
chunk. The round trip runs all 477 of them through texpack.read_pack and write_pack; new packs are read back.
"""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import L2RA, STREAM, need  # noqa: E402
from chunks import bstringhash, chunk_bytes, read_chunks  # noqa: E402
from world import bun, scenery, texpack  # noqa: E402


def checker(w, h, a=(200, 30, 30), b=(240, 240, 240), cell=4):
    return [a if ((x // cell) + (y // cell)) % 2 else b for y in range(h) for x in range(w)]


class RoundTrip(unittest.TestCase):
    def test_all_world_packs_roundtrip(self):
        need(self, L2RA, STREAM)
        n = bad = 0
        first = None
        for s in bun.sections(L2RA):
            for c, pos in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
                if c.id != texpack.PACK:
                    continue
                n += 1
                if chunk_bytes(texpack.write_pack(texpack.read_pack(c, pos), pos)) != chunk_bytes(c):
                    bad += 1
                    first = first or "%s at +0x%X" % (s.name, pos)
        print("\n  %d texture packs, %d differ%s" % (n, bad, "" if not first else " (first: %s)" % first))
        self.assertEqual(n, 477)
        self.assertEqual(bad, 0)


class Dxt1(unittest.TestCase):
    def test_dxt1_two_colour_block_exact(self):
        px = checker(8, 8)
        data = texpack.dxt1_encode(px, 8, 8)
        self.assertEqual(len(data), 4 * 8)
        back = texpack.dxt1_decode(data, 8, 8)
        for (r, g, b), (r2, g2, b2) in zip(px, back):
            self.assertLessEqual(max(abs(r - r2), abs(g - g2), abs(b - b2)), 8)

    def test_mip_chain_sizes(self):
        self.assertEqual(texpack.mip_sizes(256, 256), [32768, 8192, 2048, 512, 128, 32])
        self.assertEqual(texpack.mip_sizes(128, 128), [8192, 2048, 512, 128, 32])


class NewPack(unittest.TestCase):
    def test_new_pack_reads_back(self):
        t1 = texpack.new_texture("FTOWN_TEST_A", 64, 64, checker(64, 64))
        t2 = texpack.new_texture("FTOWN_TEST_B_WITH_A_LONG_NAME", 128, 128, checker(128, 128, cell=8))
        pack = texpack.new_pack("FTOWN", "FTown\\FTownTextures.tpk", [t2, t1])
        c = texpack.write_pack(pack, 8)
        back = texpack.read_pack(read_chunks(chunk_bytes(c))[0], 8)
        self.assertEqual([t.name_hash for t in back.textures], sorted([t1.name_hash, t2.name_hash]))
        self.assertEqual(back.filename_hash, bstringhash("FTown\\FTownTextures.tpk"))
        for t in back.textures:
            info = t.info
            w, h = struct.unpack_from("<hh", info, 0x44)
            self.assertEqual(info[0x4A], texpack.COMP_DXT1)
            self.assertEqual(info[0x4E], len(texpack.mip_sizes(w, h)))
            self.assertEqual(struct.unpack_from("<i", info, 0x38)[0], len(t.data))
            self.assertEqual(struct.unpack_from("<i", info, 0x30)[0] % 128, 0)
            self.assertEqual(t.comp[0x14:0x18], b"DXT1")
        long = [t for t in back.textures if t.name_hash == bstringhash("FTOWN_TEST_B_WITH_A_LONG_NAME")][0]
        self.assertEqual(long.info[0x0C:0x24].split(b"\0")[0], b"FTOWN_TEST_B_WITH_A_LON")


if __name__ == "__main__":
    unittest.main()
