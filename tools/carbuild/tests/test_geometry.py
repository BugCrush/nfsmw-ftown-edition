"""Geometry packs (structure level): python -m unittest discover -s tools/carbuild/tests -p test_geometry.py"""
import struct
import unittest

from common import (CHALLENGER_GEOMETRY, GTI_GEOMETRY, TRUCK_GEOMETRY, car, geometry_files, is_compressed, need,
                    need_cars, read)
from chunks import bstringhash
from geometry import read_geometry, write_geometry


def made_by_game(data):
    """The game's own packs store their file length in the info chunk (+0x68); add-on tools write 0 there."""
    i = data.find(struct.pack("<I", 0x134002))
    return struct.unpack_from("<I", data, i + 8 + 0x68)[0] == len(data)


def content(pack):
    """Everything a solid holds, padding excluded."""
    return [(s.name, s.name_hash, s.header, s.textures, s.shaders, s.mesh_header, s.mesh_entries, s.vertices,
             s.indices, s.mesh_names, [(c.id, c.data) for c in s.other]) for s in pack.solids]


class GeometryTests(unittest.TestCase):
    def test_roundtrip_geometry_identical(self):  # every pack the game's own tools made
        need_cars(self)
        done = 0
        for path in geometry_files():
            data = read(path)
            if is_compressed(data) or not made_by_game(data):
                continue
            self.assertEqual(write_geometry(read_geometry(data)), data, path)
            done += 1
        self.assertGreaterEqual(done, 90)
        print("\n  geometry round trip: %d game packs identical" % done)

    def test_uncompressed_addons_content_roundtrip(self):  # the Raptor and the Chiron: other tools, other layouts
        for name in ("RAPTOR", "CHIRON"):
            path = car(name)
            need(self, path)
            pack = read_geometry(read(path))
            self.assertEqual(content(read_geometry(write_geometry(pack))), content(pack), name)

    def test_gti_solid_names(self):
        need(self, GTI_GEOMETRY)
        names = [s.name for s in read_geometry(read(GTI_GEOMETRY)).solids]
        self.assertIn("GTI_KIT00_BODY_A", names)
        self.assertIn("GTI_BASE_A", names)
        self.assertEqual(len(names), 295)

    def test_name_hashes(self):
        need(self, GTI_GEOMETRY)
        for s in read_geometry(read(GTI_GEOMETRY)).solids:
            self.assertEqual(s.name_hash, bstringhash(s.name))

    def test_gti_bbox(self):  # GTI_KIT00_FRONT_TIRE_A: y extent -0.015..+0.247 (truck investigation)
        need(self, GTI_GEOMETRY)
        tyre = [s for s in read_geometry(read(GTI_GEOMETRY)).solids if s.name == "GTI_KIT00_FRONT_TIRE_A"][0]
        self.assertAlmostEqual(tyre.bbox[1], -0.015, places=3)
        self.assertAlmostEqual(tyre.bbox[4], 0.247, places=3)

    def test_compressed_reads_same_solids(self):  # the Longnose Cab: 26 solids incl. LONGNOSECAB_KIT00_BODY_A..E
        need(self, TRUCK_GEOMETRY)
        pack = read_geometry(read(TRUCK_GEOMETRY))
        self.assertEqual(len(pack.solids), 26)
        body = [s for s in pack.solids if s.name == "LONGNOSECAB_KIT00_BODY_A"][0]
        self.assertEqual(len(body.mesh_entries), 17)
        self.assertEqual(body.textures, [0x70F85C30])

    def test_compressed_rewritten_uncompressed_reads_back(self):
        need(self, CHALLENGER_GEOMETRY)
        pack = read_geometry(read(CHALLENGER_GEOMETRY))
        out = write_geometry(pack)
        self.assertFalse(is_compressed(out))
        again = read_geometry(out)
        self.assertEqual([(s.name, s.vertices, s.indices) for s in again.solids],
                         [(s.name, s.vertices, s.indices) for s in pack.solids])
        self.assertEqual(content(again), content(pack))
        self.assertTrue(made_by_game(out))  # written in the game's own layout

    def test_compressed_write_reads_back(self):  # literal JDLZ blocks, like the add-on tools' packs
        need(self, TRUCK_GEOMETRY)
        pack = read_geometry(read(TRUCK_GEOMETRY))
        out = write_geometry(pack, compressed=True)
        self.assertTrue(is_compressed(out))
        self.assertEqual(content(read_geometry(out)), content(pack))


if __name__ == "__main__":
    unittest.main()
