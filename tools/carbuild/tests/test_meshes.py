"""Mesh entries and vertex layout: python -m unittest discover -s tools/carbuild/tests -p test_meshes.py"""
import math
import os
import unittest

from common import GTI_GEOMETRY, TRUCK_GEOMETRY, geometry_files, need, need_cars, read
from chunks import bstringhash
from geometry import read_geometry

_cache = {}


def all_packs():
    """(car, pack) for every GEOMETRY.BIN in the game (the game's cars and the add-ons, compressed or not)."""
    if "all" not in _cache:
        _cache["all"] = [(os.path.basename(os.path.dirname(p)), read_geometry(read(p))) for p in geometry_files()]
    return _cache["all"]


def solid(path, name):
    return [s for s in read_geometry(read(path)).solids if s.name == name][0]


# the one mesh whose indices reach outside its own vertex range (an add-on tool's quirk; still inside the solid's
# vertex buffer)
FOREIGN_INDEX_MESHES = {("CHALLENGER71", "CHALLENGER71_STYLE13_HOOD_A", 3)}


class MeshTests(unittest.TestCase):
    def test_vertex_counts_match_chunks_every_car(self):
        need_cars(self)
        foreign = set()
        meshes = 0
        for car, pack in all_packs():
            for s in pack.solids:
                ms = s.meshes()
                if s.vertices is None:
                    self.assertEqual(sum(m.vertex_count for m in ms), 0, s.name)
                    continue
                self.assertEqual(sum(m.vertex_count * m.stride for m in ms), len(s.vertices), s.name)
                total = len(s.vertices) // 36
                for k, m in enumerate(ms):
                    meshes += 1
                    tris = s.triangles(m)
                    self.assertEqual(len(tris) * 3, m.index_count, s.name)
                    if not all(0 <= i < m.vertex_count for t in tris for i in t):
                        foreign.add((car, s.name, k))
                        self.assertTrue(all(0 <= i + m.vertex_offset < total for t in tris for i in t), s.name)
        self.assertEqual(foreign, FOREIGN_INDEX_MESHES)
        print("\n  meshes checked: %d" % meshes)

    def test_positions_inside_header_bbox(self):  # every solid: vertices inside its bbox (1 mm tolerance)
        need_cars(self)
        for car, pack in all_packs():
            for s in pack.solids:
                b = s.bbox
                for m in s.meshes():
                    for p in s.positions(m):
                        for a in range(3):
                            self.assertTrue(b[a] - 0.001 <= p[a] <= b[a + 3] + 0.001, (car, s.name, p, b))

    def test_normals_unit_length(self):  # a wrong layout would not give unit vectors at +12
        need_cars(self)
        bad = total = 0
        for car, pack in all_packs():
            for s in pack.solids:
                for m in s.meshes():
                    for n in s.normals(m):
                        total += 1
                        bad += abs(math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) - 1) > 0.02
        self.assertLess(bad, total * 0.001, (bad, total))

    def test_known_extents(self):
        # The truck work's -0.017..+0.444 was the header's bounding box; the vertices span 1 cm less on each side
        # (ruling in the ledger, Task 3): the game's tools store every solid's box as the vertex extents +- 0.01 m.
        need(self, TRUCK_GEOMETRY)
        tyre = solid(TRUCK_GEOMETRY, "LONGNOSECAB_KIT00_FRONT_TIRE_A")
        ys = [p[1] for m in tyre.meshes() for p in tyre.positions(m)]
        self.assertAlmostEqual(min(ys), -0.0066, places=4)
        self.assertAlmostEqual(max(ys), 0.4340, places=4)
        self.assertAlmostEqual(tyre.bbox[1], -0.017, places=3)
        self.assertAlmostEqual(tyre.bbox[4], 0.444, places=3)

    def test_bbox_is_extents_plus_one_cm(self):  # every GTI solid, every axis
        need(self, GTI_GEOMETRY)
        for s in read_geometry(read(GTI_GEOMETRY)).solids:
            ps = [p for m in s.meshes() for p in s.positions(m)]
            for a in range(3):
                self.assertAlmostEqual(min(p[a] for p in ps) - 0.01, s.bbox[a], places=4)
                self.assertAlmostEqual(max(p[a] for p in ps) + 0.01, s.bbox[a + 3], places=4)

    def test_uvs_in_reasonable_range(self):
        # Ruling (ledger, Task 3): the game's own data has 389 of 41,149 meshes with tiling UVs beyond 8 (grilles,
        # window masks, up to 83,745 on the Punto's window mask), so "every mesh within -8..8" cannot hold. Instead:
        # every UV finite, and at least 99% of meshes within -8..8 (a wrong layout reads positions or colours there).
        need_cars(self)
        inside = total = 0
        for car, pack in all_packs():
            for s in pack.solids:
                for m in s.meshes():
                    uv = s.uvs(m)
                    self.assertTrue(all(math.isfinite(c) for t in uv for c in t), s.name)
                    total += 1
                    inside += all(-8 <= c <= 8 for t in uv for c in t)
        self.assertGreaterEqual(inside, total * 0.99, (inside, total))

    def test_gti_mesh_fields(self):  # GTI_BASE_A, read by hand from the bytes (docs/carbuild-format.md)
        need(self, GTI_GEOMETRY)
        ms = solid(GTI_GEOMETRY, "GTI_BASE_A").meshes()
        self.assertEqual(len(ms), 7)
        self.assertEqual((ms[0].vertex_offset, ms[0].vertex_count, ms[0].index_offset, ms[0].index_count),
                         (0, 128, 0, 300))
        self.assertEqual((ms[1].vertex_offset, ms[1].vertex_count, ms[1].index_offset, ms[1].index_count),
                         (128, 120, 300, 312))
        self.assertEqual((ms[0].flags, ms[0].stride, ms[0].shader_index, ms[0].texture_index), (0x14180, 36, 2, 3))

    def test_shader_index_names(self):  # the mesh's shader index picks the right shader for windows and tyres
        need(self, GTI_GEOMETRY)
        seen = set()
        for s in read_geometry(read(GTI_GEOMETRY)).solids:
            for m, name in zip(s.meshes(), s.mesh_names):
                shader = s.shaders[m.shader_index]
                if name == "WINDOW_FRONT":
                    self.assertEqual(shader, bstringhash("WINDSHIELD"), s.name)
                    seen.add("window")
                if name.startswith("TIRE"):
                    seen.add("tire")
        self.assertIn("window", seen)


if __name__ == "__main__":
    unittest.main()
