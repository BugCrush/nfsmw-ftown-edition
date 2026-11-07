"""World solid lists (0x80134000) written by tools/world/solids.py:
python -m unittest tools.world.tests.test_solids -v

The round trip runs every one of Rockport's 3,305 solid lists through solids.read_list and solids.write_list; the
writer rebuilds every offset, count, index chunk and alignment run from the model, so a byte-identical result says
the model holds everything the files need. New solids (make_solid) are read back with tools/world/scenery.py, the
reader checked over all of Rockport in Part 1.
"""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import L2RA, STREAM, need  # noqa: E402
from chunks import chunk_bytes, read_chunks  # noqa: E402
from world import bun, scenery, solids  # noqa: E402


def read_back(lst, pos=0):
    """The list as the game's files hold it, parsed again by scenery.py: {name hash: scenery.Solid}."""
    data = chunk_bytes(solids.write_list(lst, pos))
    top = read_chunks(data)
    out = {}
    for c, cpos in scenery.with_positions(top, pos - 8):
        for k, kpos in scenery.with_positions(c.children, cpos):
            if k.id == scenery.SOLID:
                so = scenery.read_solid(k, kpos)
                out[so.name_hash] = so
    return out


def quad():
    p = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.0), (10.0, 10.0, 100.0), (0.0, 10.0, 100.0)]
    uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    return [(p[0], p[1], p[2]), (p[0], p[2], p[3])], [(uv[0], uv[1], uv[2]), (uv[0], uv[2], uv[3])]


def grid(n):
    """n x n cells of 2 triangles each, 1 m cells, at z = 100."""
    tris, uvs = [], []
    for i in range(n):
        for j in range(n):
            a, b, c, d = (i, j, 100.0), (i + 1, j, 100.0), (i + 1, j + 1, 100.0), (i, j + 1, 100.0)
            tris += [(a, b, c), (a, c, d)]
            uvs += [((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))]
    return tris, uvs


def uv_of(so, k):
    m = so.meshes[k]
    st = so.stride(m.buffer)
    buf = so.vertex_buffers[m.buffer]
    return [struct.unpack_from("<2f", buf, (m.vertex_offset + i) * st + 28) for i in range(m.vertex_count)]


class RoundTrip(unittest.TestCase):
    def test_all_lists_roundtrip(self):
        need(self, L2RA, STREAM)
        n = bad = 0
        first = None
        for s in bun.sections(L2RA):
            chunks = bun.read_range(STREAM, s.offset, s.size)
            for c, pos in scenery.with_positions(chunks, 0):
                if c.id != scenery.SOLID_LIST:
                    continue
                n += 1
                lst = solids.read_list(c, pos)
                if chunk_bytes(solids.write_list(lst, pos)) != chunk_bytes(c):
                    bad += 1
                    first = first or "%s at +0x%X" % (s.name, pos)
        print("\n  %d solid lists, %d differ%s" % (n, bad, "" if not first else " (first: %s)" % first))
        self.assertEqual(n, 3305)
        self.assertEqual(bad, 0)

    def test_list_is_regenerated_not_copied(self):
        """A solid removed from the model disappears from the index, the count and the bytes."""
        need(self, L2RA, STREAM)
        s = {x.name: x for x in bun.sections(L2RA)}["C9"]
        chunks = bun.read_range(STREAM, s.offset, s.size)
        c, pos = [(c, p) for c, p in scenery.with_positions(chunks, 0) if c.id == scenery.SOLID_LIST][0]
        lst = solids.read_list(c, pos)
        gone = lst.solids.pop(0)
        out = read_back(lst, pos)
        self.assertNotIn(gone.name_hash, out)
        self.assertEqual(len(out), len(lst.solids))
        head = [k for k in solids.write_list(lst, pos).children if k.id == scenery.LIST_HEADER][0]
        info, index = head.children[0].data, head.children[1].data
        self.assertEqual(struct.unpack_from("<I", info, 0x0C)[0], len(lst.solids))
        self.assertEqual(len(index), 8 * len(lst.solids))


class MakeSolid(unittest.TestCase):
    def test_make_solid_reads_back(self):
        tris, uvs = quad()
        a = solids.make_solid("FTOWN_TEST_QUAD", tris, uvs, 0x12345678)
        tris2, uvs2 = grid(25 * 2)[0][:2500], grid(50)[1][:2500]
        b = solids.make_solid("FTOWN_TEST_GRID", tris2, uvs2, 0x9ABCDEF0)
        out = read_back(solids.new_list([a, b], "ftown_test.bin"), 8)
        for name, (t, u, tex, meshes) in {"FTOWN_TEST_QUAD": (tris, uvs, 0x12345678, 1),
                                          "FTOWN_TEST_GRID": (tris2, uvs2, 0x9ABCDEF0, 3)}.items():
            so = out[solids.bstringhash(name)]
            self.assertEqual(so.name, name)
            self.assertEqual(so.textures, [tex])
            self.assertEqual(len(so.meshes), meshes)
            got_t, got_u = [], []
            for k in range(len(so.meshes)):
                ps, us = so.positions(k), uv_of(so, k)
                for i, j, l in so.triangles(k):
                    got_t.append((ps[i], ps[j], ps[l]))
                    got_u.append((us[i], us[j], us[l]))
            self.assertEqual(len(got_t), len(t))
            for g, w in zip(got_t, t):
                for gp, wp in zip(g, w):
                    self.assertEqual(gp, tuple(float(x) for x in wp))
            for g, w in zip(got_u, u):
                for gp, wp in zip(g, w):
                    self.assertEqual(gp, tuple(float(x) for x in wp))
            # the header as Rockport's: box = vertex extents + 0.01 m, volume = box volume, density = polys / volume
            bb = so.bbox
            xs = [p[a] for tri in t for p in tri for a in (0,)]
            self.assertAlmostEqual(bb[0], min(xs) - 0.01, places=4)
            self.assertAlmostEqual(bb[3], max(xs) + 0.01, places=4)
            vol = (bb[3] - bb[0]) * (bb[4] - bb[1]) * (bb[5] - bb[2])
            self.assertAlmostEqual(struct.unpack_from("<f", so.header, 0x98)[0], vol, delta=1e-3 * vol)
            self.assertEqual(struct.unpack_from("<h", so.header, 0x14)[0], len(t))

    def test_make_solid_vertex_colour(self):
        tris, uvs = quad()
        for colour in (0x7F515151, solids.ROAD_COLOUR):
            so = read_back(solids.new_list([solids.make_solid("FTOWN_C", tris, uvs, 1, colour=colour)], "c.bin"))
            so = list(so.values())[0]
            buf = so.vertex_buffers[0]
            cols = {struct.unpack_from("<I", buf, i * 36 + 24)[0] for i in range(len(buf) // 36)}
            self.assertEqual(cols, {colour})

    def test_make_solid_normals_up(self):
        tris, uvs = quad()
        so = list(read_back(solids.new_list([solids.make_solid("FTOWN_N", tris, uvs, 1)], "n.bin")).values())[0]
        buf = so.vertex_buffers[0]
        for i in range(len(buf) // 36):
            self.assertEqual(struct.unpack_from("<3f", buf, i * 36 + 12), (0.0, 0.0, 1.0))


class MakeSolidMulti(unittest.TestCase):
    """make_solid_multi: several textures in one solid (F-Town's tiles), vertices shared within a mesh."""

    def groups(self):
        tris, _uvs = grid(30)  # 1,800 triangles: two meshes of at most 1,000
        uvs = [tuple((p[0] / 10.0, p[1] / 10.0) for p in t) for t in tris]  # planar: neighbours share uvs
        cols = [0xFF525964] * len(tris)
        wall = [((0.0, 0.0, 100.0), (4.0, 0.0, 100.0), (4.0, 0.0, 103.2)),
                ((0.0, 0.0, 100.0), (4.0, 0.0, 103.2), (0.0, 0.0, 103.2))]
        wuv = [((0, 1), (1, 1), (1, 0)), ((0, 1), (1, 0), (0, 0))]
        return [(0x11111111, "FTC_ASPHALT", tris, uvs, cols), (0x22222222, "FTC_PLASTER", wall, wuv,
                                                               [0xFF8090A0, 0xFF8090A0])]

    def test_reads_back(self):
        g = self.groups()
        so = solids.make_solid_multi("FTC_TEST_TILE", g)
        out = read_back(solids.new_list([so], "ftc_test.bin"), 8)[solids.bstringhash("FTC_TEST_TILE")]
        self.assertEqual(out.textures, [0x11111111, 0x22222222])
        self.assertEqual([m.texture_slots for m in out.meshes], [(0,) * 5, (0,) * 5, (1,) * 5])
        got = {0: [], 1: []}
        for k, m in enumerate(out.meshes):
            ps = out.positions(k)
            for i, j, l in out.triangles(k):
                got[m.texture_slots[0]].append((ps[i], ps[j], ps[l]))
        for slot, (_h, _n, tris, _u, _c) in enumerate(g):
            self.assertEqual(len(got[slot]), len(tris))
            for a, b in zip(got[slot], tris):
                self.assertEqual(a, tuple(tuple(struct.unpack('<f', struct.pack('<f', v))[0] for v in p) for p in b))
        # shared vertices: a 30 x 30 grid's two meshes hold far fewer than 3 per triangle
        n = sum(m.vertex_count for m in out.meshes[:2])
        self.assertLess(n, 1800 * 1.5)
        buf = out.vertex_buffers[out.meshes[2].buffer]
        m = out.meshes[2]
        cols = {struct.unpack_from("<I", buf, (m.vertex_offset + i) * 36 + 24)[0] for i in range(m.vertex_count)}
        self.assertEqual(cols, {0xFF8090A0})

    def test_header_counts(self):
        so = solids.make_solid_multi("FTC_TEST_TILE", self.groups())
        out = read_back(solids.new_list([so], "ftc_test.bin"), 8)[solids.bstringhash("FTC_TEST_TILE")]
        self.assertEqual(struct.unpack_from("<h", so.header, 0x14)[0], 1802)
        self.assertEqual(sum(m.triangle_count for m in out.meshes), 1802)

    def test_vertex_limit(self):
        tris, uvs = grid(160)  # 51,200 triangles, unshared corners: over 65,535 vertices in one buffer
        tris = [tuple((p[0] + 1e-3 * k, p[1], p[2]) for p in t) for k, t in enumerate(tris)]
        with self.assertRaises(ValueError):
            solids.make_solid_multi("FTC_BIG", [(1, "FTC_ASPHALT", tris, uvs, [0xFFFFFFFF] * len(tris))])


if __name__ == "__main__":
    unittest.main()
