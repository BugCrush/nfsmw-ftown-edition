"""Building parts and packs that did not come from a game file (the final review's findings 1-4):
python -m unittest discover -s tools/carbuild/tests -p test_build_fresh.py"""
import struct
import unittest

from common import GTI_GEOMETRY, GTI_TEXTURES, need, read
from chunks import bstringhash
from geometry import Mesh, check, extents_bbox, finalize, read_geometry, write_geometry
from textures import read_textures, write_textures


def gti_solid(name="GTI_KIT00_FRONT_TIRE_A"):
    return [s for s in read_geometry(read(GTI_GEOMETRY)).solids if s.name == name][0]


class FreshBuildTests(unittest.TestCase):
    def test_mesh_to_raw_rejects_wrong_slot_count(self):  # finding 1: a slice assignment resized the entry
        m = Mesh(texture_index=0, shader_index=0, vertex_offset=0, vertex_count=3, index_offset=0, index_count=3,
                 stride=36, flags=0x4180, raw=bytes(104), texture_slots=(0, 0, 0, 0), triangle_count=1)
        with self.assertRaises(ValueError):
            m.to_raw()
        m.texture_slots = ()
        with self.assertRaises(ValueError):
            m.to_raw()
        m.raw = bytes(100)
        m.texture_slots = (0,) * 5
        with self.assertRaises(ValueError):
            m.to_raw()

    def test_mesh_to_raw_writes_texture_index_as_slot_0(self):
        m = Mesh(texture_index=2, shader_index=1, vertex_offset=0, vertex_count=3, index_offset=0, index_count=3,
                 stride=36, flags=0x4180, raw=bytes(104), texture_slots=(0,) * 5, triangle_count=1)
        raw = m.to_raw()
        self.assertEqual(len(raw), 104)
        self.assertEqual(raw[0x18], 2)

    def test_texture_size_change_updates_directory(self):  # finding 2
        need(self, GTI_TEXTURES)
        pack = read_textures(read(GTI_TEXTURES))
        t = [t for t in pack.textures if t.data is not None and t.mipmaps == 1 and t.fmt == "DXT1"][0]
        t.data = bytes(len(t.data) // 4)  # a quarter of the size (half the width and height)
        again = read_textures(write_textures(pack))  # raised "directory says ..." before the fix
        self.assertEqual([x.data for x in again.textures if x.name_hash == t.name_hash], [t.data])

    def test_pack_hash_follows_file_name(self):  # finding 3
        need(self, GTI_TEXTURES)
        pack = read_textures(read(GTI_TEXTURES))
        self.assertEqual(struct.unpack_from("<I", pack.raw_parts["info"], 0x60)[0], bstringhash(pack.filename))
        pack.filename = "CARTEMPLATETEXTURES_THAR.tpk"
        out = write_textures(pack)
        info = read_textures(out).raw_parts["info"]
        self.assertEqual(struct.unpack_from("<I", info, 0x60)[0], bstringhash("CARTEMPLATETEXTURES_THAR.tpk"))
        self.assertIn(struct.pack("<3I", 0, 0, 1) + struct.pack("<I", bstringhash("CARTEMPLATETEXTURES_THAR.tpk")),
                      out)

    def test_finalize_fills_bookkeeping(self):  # finding 4: a hand-edited solid comes out consistent
        need(self, GTI_GEOMETRY)
        s = gti_solid("GTI_BASE_A")
        good_header, good_indices, good_bbox = s.mesh_header, s.indices, s.bbox
        s.mesh_header = bytes(48)
        s.header = s.header[:0x20] + bytes(32) + s.header[0x40:]
        if len(s.indices) % 4:  # the GTI base has an odd index count: pad dropped
            s.indices = s.indices[:-2]
        self.assertTrue(check(s))
        finalize(s)
        self.assertEqual(check(s), [])
        mh = struct.unpack_from("<12I", s.mesh_header)
        ref = struct.unpack_from("<12I", good_header)
        self.assertEqual((mh[3], mh[4], mh[11]), (ref[3], ref[4], ref[11]))
        self.assertEqual(s.indices, good_indices)
        for a, b in zip(s.bbox, good_bbox):
            self.assertAlmostEqual(a, b, places=5)

    def test_extents_bbox_is_game_convention(self):
        need(self, GTI_GEOMETRY)
        s = gti_solid()
        for a, b in zip(extents_bbox(s), s.bbox):
            self.assertAlmostEqual(a, b, places=4)

    def test_check_clean_on_game_solids(self):  # the game's own solids agree (but for the 74 known flag ORs)
        need(self, GTI_GEOMETRY)
        problems = [p for s in read_geometry(read(GTI_GEOMETRY)).solids for p in check(s)]
        self.assertEqual(problems, [])

    def test_finalized_solid_round_trips(self):
        need(self, GTI_GEOMETRY)
        pack = read_geometry(read(GTI_GEOMETRY))
        before = write_geometry(pack)
        for s in pack.solids:
            finalize(s)
        self.assertEqual(write_geometry(pack), before)  # the GTI's bookkeeping already agrees


if __name__ == "__main__":
    unittest.main()
