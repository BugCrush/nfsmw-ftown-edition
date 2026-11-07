"""Description folders and the command line: python -m unittest discover -s tools/carbuild/tests -p test_describe.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from common import (CARBUILD, CHALLENGER_GEOMETRY, GTI_GEOMETRY, GTI_TEXTURES, SEMI_GEOMETRY, TRUCK_TEXTURES, car,
                    need, read)
from describe import dump, dump_textures, load, load_textures
from geometry import read_geometry, write_geometry
from textures import read_textures, write_textures

CARBIN = os.path.join(CARBUILD, "carbin.py")


class DescribeTests(unittest.TestCase):
    def test_dump_load_identical(self):  # GTI and SEMI, and the Raptor's odd names / zero padding
        for path in (GTI_GEOMETRY, SEMI_GEOMETRY, car("RAPTOR")):
            need(self, path)
            data = read(path)
            pack = read_geometry(data)
            with tempfile.TemporaryDirectory() as d:
                dump(pack, d)
                self.assertEqual(write_geometry(load(d)), write_geometry(pack), path)

    def test_obj_has_every_mesh(self):  # one 'o' per solid, vertex count = sum of mesh vertex counts
        need(self, GTI_GEOMETRY)
        pack = read_geometry(read(GTI_GEOMETRY))
        with tempfile.TemporaryDirectory() as d:
            dump(pack, d)
            files = sorted(os.listdir(os.path.join(d, "obj")))
            self.assertEqual(len(files), len([s for s in pack.solids if s.vertices]))
            body = [s for s in pack.solids if s.name == "GTI_KIT00_BODY_A"][0]
            name = [f for f in files if f.endswith("_GTI_KIT00_BODY_A.obj")][0]
            lines = open(os.path.join(d, "obj", name)).read().splitlines()
            self.assertEqual(sum(1 for l in lines if l.startswith("o ")), 1)
            self.assertEqual(sum(1 for l in lines if l.startswith("v ")), sum(m.vertex_count for m in body.meshes()))
            self.assertEqual(sum(1 for l in lines if l.startswith("f ")),
                             sum(m.triangle_count for m in body.meshes()))
            self.assertEqual(sum(1 for l in lines if l.startswith("g ")), len(body.meshes()))

    def test_decoded_fields_are_used(self):  # car.json's named fields win over the hex they were decoded from
        need(self, GTI_GEOMETRY)
        pack = read_geometry(read(GTI_GEOMETRY))
        with tempfile.TemporaryDirectory() as d:
            dump(pack, d)
            path = os.path.join(d, "car.json")
            doc = json.load(open(path))
            s = [s for s in doc["solids"] if s["name"] == "GTI_BASE_A"][0]
            s["bbox"][0] = -9.5
            s["meshes"][0]["shader_index"] = 1
            json.dump(doc, open(path, "w"))
            again = [s for s in load(d).solids if s.name == "GTI_BASE_A"][0]
            self.assertEqual(again.bbox[0], -9.5)
            self.assertEqual(again.meshes()[0].shader_index, 1)

    def test_cli_roundtrip(self):  # carbin.py dump then build gives identical bytes (subprocess, temp folder)
        need(self, GTI_GEOMETRY)
        with tempfile.TemporaryDirectory() as d:
            desc, out = os.path.join(d, "gti"), os.path.join(d, "GEOMETRY.BIN")
            subprocess.run([sys.executable, CARBIN, "dump", GTI_GEOMETRY, desc], check=True, capture_output=True)
            subprocess.run([sys.executable, CARBIN, "build", desc, out], check=True, capture_output=True)
            self.assertEqual(read(out), read(GTI_GEOMETRY))

    def test_cli_compressed_addon_builds_game_layout(self):
        need(self, CHALLENGER_GEOMETRY)
        with tempfile.TemporaryDirectory() as d:
            desc, out = os.path.join(d, "ch"), os.path.join(d, "GEOMETRY.BIN")
            subprocess.run([sys.executable, CARBIN, "dump", CHALLENGER_GEOMETRY, desc], check=True, capture_output=True)
            subprocess.run([sys.executable, CARBIN, "build", desc, out], check=True, capture_output=True)
            self.assertEqual(read(out), write_geometry(read_geometry(read(CHALLENGER_GEOMETRY))))

    def test_textures_dump_load_identical(self):  # GTI (has a HUFF texture) and the truck (compressed add-on)
        for path in (GTI_TEXTURES, TRUCK_TEXTURES):
            need(self, path)
            data = read(path)
            with tempfile.TemporaryDirectory() as d:
                dump_textures(read_textures(data), d)
                self.assertEqual(write_textures(load_textures(d)), data, path)
                dds = [f for f in os.listdir(os.path.join(d, "textures")) if f.endswith(".dds")]
                self.assertTrue(dds)
                self.assertTrue(all(read(os.path.join(d, "textures", f))[:4] == b"DDS " for f in dds))

    def test_cli_textures_roundtrip(self):
        need(self, GTI_TEXTURES)
        with tempfile.TemporaryDirectory() as d:
            desc, out = os.path.join(d, "gti"), os.path.join(d, "TEXTURES.BIN")
            subprocess.run([sys.executable, CARBIN, "dump", GTI_TEXTURES, desc], check=True, capture_output=True)
            subprocess.run([sys.executable, CARBIN, "build", desc, out], check=True, capture_output=True)
            self.assertEqual(read(out), read(GTI_TEXTURES))

    def test_cli_car_folder_both_files(self):  # one folder holds a car's model and textures; the output name picks
        need(self, GTI_GEOMETRY, GTI_TEXTURES)
        with tempfile.TemporaryDirectory() as d:
            desc = os.path.join(d, "gti")
            for src in (GTI_GEOMETRY, GTI_TEXTURES):
                subprocess.run([sys.executable, CARBIN, "dump", src, desc], check=True, capture_output=True)
            for name, src in (("GEOMETRY.BIN", GTI_GEOMETRY), ("TEXTURES.BIN", GTI_TEXTURES)):
                out = os.path.join(d, name)
                subprocess.run([sys.executable, CARBIN, "build", desc, out], check=True, capture_output=True)
                self.assertEqual(read(out), read(src), name)


if __name__ == "__main__":
    unittest.main()
