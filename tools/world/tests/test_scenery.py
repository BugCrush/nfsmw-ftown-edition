"""Scenery and world solids in every streaming section:
python -m unittest discover -s tools/world/tests -p test_scenery.py -v

One pass over all 720 sections (setUpClass) gathers what the tests check, so nothing large stays in memory.
"""
import collections
import math
import struct
import unittest

from common import L2RA, STREAM, need
from chunks import chunk_bytes, write_chunks
from world import bun, scenery


def inside_box(p, box, tol):
    return all(box[a] - tol <= p[a] <= box[3 + a] + tol for a in range(3))


class SceneryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA, STREAM)
        cls.sections = bun.sections(L2RA)
        cls.bounds = bun.boundaries(L2RA)
        st = collections.Counter()
        cls.strides = collections.Counter()
        cls.kind_stride = collections.defaultdict(collections.Counter)
        cls.problems = collections.defaultdict(list)
        cls.where = {}  # solid hash -> set of section names holding it
        cls.instance_refs = []  # (section name, scenery number, [hashes])
        cls.positions = []  # (scenery number, (x, y, z))
        cls.bbox_checks = collections.Counter()
        cls.zero_position = collections.Counter()
        cls.box_growth = collections.Counter()
        cls.list_roundtrip = collections.Counter()
        cls.list_headers = collections.Counter()
        cls.shaders = collections.Counter()
        cls.flags = collections.Counter()
        cls.colours = collections.Counter()
        cls.texture_hashes = collections.Counter()
        cls.sections_by_tris = []
        for s in cls.sections:
            chunks = bun.read_range(STREAM, s.offset, s.size)
            d = scenery.read_section(chunks)
            st["sections"] += 1
            st["sceneries"] += len(d.sceneries)
            st["solids"] += len(d.solids)
            tris = 0
            for sl in d.solid_lists:
                cls.list_roundtrip[write_chunks([sl]) == chunk_bytes(sl)] += 1
                head = [c for c in sl.children if c.id == scenery.LIST_HEADER][0]
                cls.list_headers[tuple(c.id for c in head.children)] += 1
            for h, so in d.solids.items():
                cls.where.setdefault(h, set()).add(s.name)
                cls.shaders[so.shaders is not None] += 1
                for b in range(len(so.vertex_buffers)):
                    stv = so.stride(b)
                    cls.strides[stv] += 1
                    n = sum(m.vertex_count for m in so.meshes if m.buffer == b)
                    if n * stv != len(so.vertex_buffers[b]):
                        cls.problems["buffer size"].append(so.name)
                for k, m in enumerate(so.meshes):
                    cls.kind_stride[m.kind][so.stride(m.buffer)] += 1
                    cls.flags[m.flags] += 1
                    st["meshes"] += 1
                    st["triangles"] += m.triangle_count
                    tris += m.triangle_count
                    if m.index_count != 3 * m.triangle_count:
                        cls.problems["index count"].append(so.name)
                    idx = struct.unpack_from("<%dH" % m.index_count, so.indices, m.index_offset * 2)
                    if idx and not (m.vertex_offset <= min(idx) and max(idx) < m.vertex_offset + m.vertex_count):
                        cls.problems["index range"].append(so.name)
                    ps = so.positions(k)
                    st["vertices"] += len(ps)
                    for p in ps:
                        if not inside_box(p, so.bbox, 0.02):
                            cls.problems["vertex outside box"].append(so.name)
                            break
                    st0 = so.stride(m.buffer)
                    buf = so.vertex_buffers[m.buffer]
                    for i in range(0, m.vertex_count, max(1, m.vertex_count // 4)):
                        base = (m.vertex_offset + i) * st0
                        nx, ny, nz = struct.unpack_from("<3f", buf, base + 12)
                        cls.colours[(st0, abs(math.sqrt(nx * nx + ny * ny + nz * nz) - 1) < 0.05)] += 1
                for t in so.textures:
                    cls.texture_hashes[t] += 1
            cls.sections_by_tris.append((tris, s.name))
            for sc in d.sceneries:
                st["infos"] += len(sc.infos)
                st["instances"] += len(sc.instances)
                for inst in sc.instances:
                    if not 0 <= inst.info_index < len(sc.infos):
                        cls.problems["info index"].append((s.name, inst.info_index))
                        continue
                    info = sc.infos[inst.info_index]
                    cls.instance_refs.append((s.name, sc.number,
                                              [h for h in info.solid_hashes if h not in scenery.NO_MODEL]))
                    cls.positions.append((sc.number, inst.centre))
                    cls.zero_position[inst.position == (0.0, 0.0, 0.0)] += 1
                    hi = info.solid_hashes[0] if info.solid_hashes[0] not in scenery.NO_MODEL else None
                    so = d.solids.get(hi)
                    if so is not None:
                        corners = [scenery.transform(inst.matrix, (x, y, z)) for x in (so.bbox[0], so.bbox[3])
                                   for y in (so.bbox[1], so.bbox[4]) for z in (so.bbox[2], so.bbox[5])]
                        lo = [min(c[a] for c in corners) for a in range(3)]
                        up = [max(c[a] for c in corners) for a in range(3)]
                        exact = all(abs(lo[a] - inst.bbox[a]) < 0.5 and abs(up[a] - inst.bbox[3 + a]) < 0.5
                                    for a in range(3))
                        within = all(inst.bbox[a] - 0.5 <= lo[a] and up[a] <= inst.bbox[3 + a] + 0.5 for a in range(3))
                        cls.bbox_checks[(exact, within)] += 1
                        if not exact and within:
                            grow = tuple(round(inst.bbox[3 + a] - up[a]) for a in range(3)) +                                 tuple(round(lo[a] - inst.bbox[a]) for a in range(3))
                            cls.box_growth[(info.name[:4], grow)] += 1
        cls.stats = st

    def test_solid_lists_parse(self):
        st = self.stats
        print("\n  %s" % dict(st))
        print("  strides per vertex buffer %s; stride by mesh kind %s" %
              (dict(self.strides), {k: dict(v) for k, v in self.kind_stride.items()}))
        print("  list header children %s; solids with a shader list %s" % (dict(self.list_headers), dict(self.shaders)))
        self.assertEqual(st["sections"], 720)
        self.assertGreater(st["solids"], 0)
        self.assertFalse(self.problems["buffer size"][:5])
        self.assertFalse(self.problems["index count"][:5])
        self.assertFalse(self.problems["index range"][:5])
        self.assertEqual(set(self.strides), {36, 44, 60})
        for kind, c in self.kind_stride.items():
            self.assertEqual(len(c), 1, "kind %d has strides %s" % (kind, dict(c)))

    def test_vertices_inside_solid_box(self):
        self.assertFalse(self.problems["vertex outside box"][:5])

    def test_normals_at_12(self):  # a unit normal at +12 in both 36- and 60-byte vertices
        print("\n  (stride, unit normal at +12): %s" % dict(self.colours))
        for stv in (36, 60):
            good, bad = self.colours[(stv, True)], self.colours[(stv, False)]
            self.assertGreater(good / (good + bad), 0.95, stv)

    def test_instance_info_indices_valid(self):
        self.assertFalse(self.problems["info index"][:5])

    def test_instance_solids_exist(self):
        own = elsewhere = missing = 0
        from_letters = collections.Counter()
        for name, number, hashes in self.instance_refs:
            for h in hashes:
                places = self.where.get(h)
                if places is None:
                    missing += 1
                elif name in places:
                    own += 1
                else:
                    elsewhere += 1
                    from_letters["".join(sorted({p[0] for p in places}))] += 1
        total = own + elsewhere + missing
        print("\n  instance solid references %d: in the own section %d, only elsewhere %d (by letter %s), nowhere %d" %
              (total, own, elsewhere, dict(from_letters.most_common(8)), missing))
        library = sum(v for k, v in from_letters.items() if "X" in k or "V" in k)
        self.assertGreater((own + library) / total, 0.95)
        self.assertLess(missing / total, 0.01)

    def test_instances_inside_boundary(self):
        inside = outside = noboundary = 0
        for number, p in self.positions:
            drivable = number if number in self.bounds else number - bun.LOD_OFFSET
            b = self.bounds.get(drivable)
            if b is None:
                noboundary += 1
                continue
            if bun.distance_outside(p[:2], b.points) <= 50:
                inside += 1
            else:
                outside += 1
        print("\n  instance box centres within 50 m of their section's boundary %d, beyond %d, no boundary %d; "
              "instances placed at (0, 0, 0) with geometry in world coordinates %d of %d" %
              (inside, outside, noboundary, self.zero_position[True], sum(self.zero_position.values())))
        self.assertGreaterEqual(inside / (inside + outside), 0.95)

    def test_instance_bbox_is_transformed_solid_box(self):  # the matrix convention (row vectors) and axes
        c = self.bbox_checks
        total = sum(c.values())
        within = c[(True, True)] + c[(False, True)]
        print("\n  solid box through the matrix vs the instance box (0.5 m): equal %d, inside %d, neither %d of %d;"
              " growth (name prefix, +x +y +z -x -y -z m) %s" % (c[(True, True)], c[(False, True)], c[(False, False)],
                                                                 total, self.box_growth.most_common(6)))
        self.assertGreater(within / total, 0.95)

    def test_section_solids_roundtrip(self):
        """Solid lists write back identical at chunk level. The car writer (geometry.write_geometry) does not apply:
        world lists have no 0x134004 directory and solids have several vertex buffers (asserted here)."""
        self.assertEqual(self.list_roundtrip[False], 0)
        self.assertNotIn(scenery.LIST_DIRECTORY, {i for k in self.list_headers for i in k})
        self.assertGreater(self.strides[60], 0)


if __name__ == "__main__":
    unittest.main()
