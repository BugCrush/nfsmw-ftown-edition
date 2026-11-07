"""The F-Town test slab (tools/world/slab.py) and its data file:
python -m unittest tools.world.tests.test_slab -v

The slab: a 200 x 200 m asphalt square centred on render (2000, 11500) with its top at z = 100, a dashed centre
line, a 20 m ramp rising 3 m with a 3 m drop, a 50 m wall 3 m tall and 3 m walls round the edge. The file is built in
memory and read back with Part 1's readers; heights are checked with heightcheck (the model of the game's query).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import L2RA, STREAM, need  # noqa: E402
from chunks import read_chunks, write_chunks  # noqa: E402
from world import bun, collision, collision_write, heightcheck, scenery, slab, solids  # noqa: E402

PH = collision.to_physics


class SlabFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = write_chunks(slab.build_chunks())
        cls.top = read_chunks(cls.data)
        cls.positions = scenery.with_positions(cls.top, 0)
        cls.pack = [collision_write.read_pack(c.data, p) for c, p in cls.positions if c.id == collision.COLLISION_PACK][0]

    def test_slab_file_reads_back(self):
        ids = [c.id for c in self.top if c.id != 0]
        self.assertEqual(sorted(ids), sorted([0xB3300000, scenery.SOLID_LIST, scenery.SCENERY_SECTION,
                                              collision.COLLISION_PACK]))
        self.assertEqual(ids, [0xB3300000, scenery.SOLID_LIST, scenery.SCENERY_SECTION, collision.COLLISION_PACK])
        d = scenery.read_section(self.top)
        self.assertEqual([s.number for s in d.sceneries], [slab.SECTION_NUMBER])
        ref = collision.read_pack([c.data for c, p in self.positions if c.id == collision.COLLISION_PACK][0],
                                  [p for c, p in self.positions if c.id == collision.COLLISION_PACK][0])
        self.assertEqual(ref.section, slab.PACK_NUMBER)
        # every instance's solids are in the file, every solid's texture in its pack
        for inst in d.instances:
            for h in d.sceneries[0].infos[inst.info_index].solid_hashes:
                if h not in scenery.NO_MODEL:
                    self.assertIn(h, d.solids)
        from world import texpack
        tp = texpack.read_pack([c for c in self.top if c.id == texpack.PACK][0], 8)
        have = {t.name_hash for t in tp.textures}
        for so in d.solids.values():
            for t in so.textures:
                self.assertIn(t, have)
        # each top-level chunk starts at a multiple of 128 (the loader's 16- and 128-byte alignments then hold)
        for c, p in self.positions:
            if c.id:
                self.assertEqual((p - 8) % 128, 0, hex(c.id))

    def test_numbers_free_in_rockport(self):
        need(self, L2RA, STREAM)
        used = {s.number for s in bun.sections(L2RA)} | set(bun.boundaries(L2RA)) | set(bun.drivable_sections(L2RA))
        packs = set()
        for s in bun.sections(L2RA):
            ch = bun.read_range(STREAM, s.offset, s.size)
            for c, p in scenery.with_positions(ch, 0):
                if c.id == collision.COLLISION_PACK:
                    packs.add(collision.read_pack(c.data, p).section)
                elif c.id == scenery.SCENERY_SECTION:
                    used.add(scenery.read_scenery(c, p).number)
        self.assertNotIn(slab.SECTION_NUMBER, used)
        self.assertNotIn(slab.PACK_NUMBER, packs | used)
        self.assertLess(slab.SECTION_NUMBER % 100, 10)
        self.assertLess(slab.PACK_NUMBER, 2700)
        self.assertLess(slab.SECTION_NUMBER, 2800)

    def test_slab_heights(self):
        cx, cy = slab.CENTRE
        bad = []
        for i in range(0, 201, 2):
            for j in range(0, 201, 2):
                x, y = cx - 100 + i, cy - 100 + j
                if slab.in_ramp(x, y):
                    continue
                p = PH((x, y, slab.TOP + 1.0))
                h = heightcheck.height_at(self.pack, p[0], p[2], p[1])
                if h is None or abs(h - slab.TOP) > 0.01:
                    bad.append((x, y, h))
        self.assertEqual(bad[:5], [])
        # the ramp: along its centre line, the slope
        x0, y0, x1, y1 = slab.RAMP
        for k in range(21):
            y = y0 + (y1 - y0) * k / 20.0
            want = slab.TOP + slab.RAMP_HEIGHT * k / 20.0
            p = PH(((x0 + x1) / 2, y, want + 1.0))
            self.assertAlmostEqual(heightcheck.height_at(self.pack, p[0], p[2], p[1]), want, delta=0.01)
        # outside the edge: nothing
        for x, y in ((cx - 100.5, cy), (cx + 100.5, cy), (cx, cy - 100.5), (cx, cy + 100.5)):
            p = PH((x, y, slab.TOP + 1.0))
            self.assertIsNone(heightcheck.height_at(self.pack, p[0], p[2], p[1]))

    def test_slab_barriers(self):
        bars = [(a, b, lo, hi) for a, b, lo, hi in slab.barriers()]  # physics ((x, z), (x, z), bottom, top)

        def crosses(p, q):
            for a, b, lo, hi in bars:
                if lo > slab.TOP + 0.01 or hi < slab.TOP + slab.WALL_HEIGHT - 0.01:
                    continue
                d = (b[0] - a[0]) * (q[1] - p[1]) - (b[1] - a[1]) * (q[0] - p[0])
                if d == 0:
                    continue
                t = ((p[0] - a[0]) * (q[1] - p[1]) - (p[1] - a[1]) * (q[0] - p[0])) / d
                u = ((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / d
                if 0 <= t <= 1 and 0 <= u <= 1:
                    return True
            return False

        cx, cy = slab.CENTRE
        open_spots = []
        for k in range(200):
            s = -100 + k + 0.5
            for inside, outside in (((cx + s, cy - 99), (cx + s, cy - 101)), ((cx + s, cy + 99), (cx + s, cy + 101)),
                                    ((cx - 99, cy + s), (cx - 101, cy + s)), ((cx + 99, cy + s), (cx + 101, cy + s))):
                p, q = PH(inside + (0,)), PH(outside + (0,))
                if not crosses((p[0], p[2]), (q[0], q[2])):
                    open_spots.append(inside)
        self.assertEqual(open_spots[:5], [])
        wx0, wx1, wy = slab.WALL
        p, q = PH(((wx0 + wx1) / 2, wy - 1, 0)), PH(((wx0 + wx1) / 2, wy + 1, 0))
        self.assertTrue(crosses((p[0], p[2]), (q[0], q[2])))
        # and the barriers in the file are these
        ref = collision.barriers(collision.read_pack(*[(c.data, p) for c, p in self.positions
                                                       if c.id == collision.COLLISION_PACK][0]))
        self.assertEqual(len(ref), len(bars))

    def test_spawn_on_slab(self):
        x, y, z, heading = slab.spawn()
        self.assertAlmostEqual(z, slab.TOP + 1.0)
        p = PH((x, y, z))
        self.assertAlmostEqual(heightcheck.height_at(self.pack, p[0], p[2], p[1] + 0.025), slab.TOP, delta=0.01)
        x0, y0, x1, y1 = slab.RAMP
        self.assertTrue(x0 < x < x1 and y < y0, "the spawn faces the ramp along +y")
        self.assertAlmostEqual(slab.CENTRE[1] - 100 + 30, y)

    def test_slab_solids_cover_collision(self):
        drawn = []
        for so in scenery.read_section(self.top).solids.values():
            drawn += [t[:3] for t in so.world_triangles(((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))]
        buckets = {}
        for t in drawn:
            xs, ys = [p[0] for p in t], [p[1] for p in t]
            for bx in range(int(min(xs)) // 10, int(max(xs)) // 10 + 1):
                for by in range(int(min(ys)) // 10, int(max(ys)) // 10 + 1):
                    buckets.setdefault((bx, by), []).append(t)

        def drawn_height(x, y):
            out = []
            for t in buckets.get((int(x) // 10, int(y) // 10), []):
                (ax, ay, az), (bx, by, bz), (qx, qy, qz) = t
                d = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
                if d == 0:
                    continue
                l1 = ((by - qy) * (x - qx) + (qx - bx) * (y - qy)) / d
                l2 = ((qy - ay) * (x - qx) + (ax - qx) * (y - qy)) / d
                l3 = 1 - l1 - l2
                if min(l1, l2, l3) >= -1e-6:
                    out.append(l1 * az + l2 * bz + l3 * qz)
            return out

        uncovered = []
        ref = collision.read_pack(*[(c.data, p) for c, p in self.positions if c.id == collision.COLLISION_PACK][0])
        tris = collision.triangles(ref)
        self.assertGreater(len(tris), 500)
        for p0, p1, p2, _s, _n in tris:
            c = collision.to_render(tuple((p0[a] + p1[a] + p2[a]) / 3 for a in range(3)))
            # -0.005: collision vertices are s16 / 128 m from their strip's centre (quantised to 4 mm)
            if not any(-0.005 <= h - c[2] <= 0.05 for h in drawn_height(c[0], c[1])):
                uncovered.append(c)
        self.assertEqual(uncovered[:5], [])

    def test_build_reads_no_game_file(self):
        """The slab's file is made from our own geometry and drawn textures only (it is committed)."""
        import builtins
        opened = []
        real = builtins.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)

        builtins.open = spy
        try:
            slab.build_chunks()
        finally:
            builtins.open = real
        self.assertFalse([p for p in opened if "Need For Speed" in p])


def _texture(top, name):
    from chunks import bstringhash
    from world import texpack
    for c, p in scenery.with_positions(top, 0):
        if c.id == texpack.PACK:
            for t in texpack.read_pack(c, p).textures:
                if t.name_hash == bstringhash(name):
                    return t
    return None


def _stats(px, w, h):
    """Mean luminance, mean and 99th-percentile chroma (max - min channel), mean neighbour |dL|, spread of 8 px
    block means: the same measures as were taken of Rockport's road textures (docs/ftown-notes.md, small fixes)."""
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    chroma = sorted(max(p) - min(p) for p in px)
    fine = sum(abs(lum[y * w + x] - lum[y * w + x + 1]) for y in range(h) for x in range(w - 1)) / (h * (w - 1))
    blocks = [sum(lum[(by + y) * w + bx + x] for y in range(8) for x in range(8)) / 64
              for by in range(0, h, 8) for bx in range(0, w, 8)]
    bm = sum(blocks) / len(blocks)
    return (sum(lum) / len(lum), sum(chroma) / len(chroma), chroma[int(0.99 * len(chroma))], fine,
            (sum((v - bm) ** 2 for v in blocks) / len(blocks)) ** 0.5)


class SlabTextures(unittest.TestCase):
    """Small fixes (2026-11-03, screenshot 87: the asphalt read as coloured speckle up close). Targets from the
    measurements of Rockport's road textures: 256 x 256 with the full mip chain (6 levels, as Rockport's 607 road
    textures of that size), 3.9 cm per pixel over our 10 m tile (Rockport's lane textures: 3.1-3.9 cm), grey with a
    low chroma (Rockport 4.7-7.6), fine grain (neighbour |dL| 5.6-8.5) and patches (8 px block spread 3.2-11)."""

    @classmethod
    def setUpClass(cls):
        cls.top = read_chunks(write_chunks(slab.build_chunks()))

    def test_asphalt_reads_as_tarmac(self):
        from world import texpack
        import struct
        for name in ("FTOWN_ASPHALT", "FTOWN_ASPHALT_LINE"):
            t = _texture(self.top, name)
            self.assertIsNotNone(t, name)
            w, h = struct.unpack_from("<hh", t.info, 0x44)
            self.assertEqual((w, h, t.info[0x4E]), (256, 256, 6), name)
            self.assertEqual(len(t.data), sum(texpack.mip_sizes(256, 256)), name)
        t = _texture(self.top, "FTOWN_ASPHALT")
        lum, chroma, chroma99, fine, patches = _stats(texpack.dxt1_decode(t.data, 256, 256), 256, 256)
        print("\n  asphalt (DXT1 mip 0): luminance %.1f, chroma %.1f (99%% %d), fine |dL| %.1f, 8 px block spread %.1f"
              % (lum, chroma, chroma99, fine, patches))
        self.assertTrue(50 <= lum <= 70, lum)
        self.assertLessEqual(chroma, 6)
        self.assertLessEqual(chroma99, 12)
        self.assertTrue(3 <= fine <= 9, fine)
        self.assertTrue(2 <= patches <= 6, patches)

    def test_line_dash_width(self):
        """The dashed line stays 0.31 m wide (8 px of 256 over 10 m) and 5 m long, bright against the asphalt."""
        from world import texpack
        t = _texture(self.top, "FTOWN_ASPHALT_LINE")
        px = texpack.dxt1_decode(t.data, 256, 256)
        bright = lambda p: sum(p) / 3 > 180
        row = [bright(px[64 * 256 + x]) for x in range(256)]
        self.assertEqual(sum(row), 8)
        self.assertTrue(all(row[124:132]))
        col = [bright(px[y * 256 + 128]) for y in range(256)]
        self.assertEqual(sum(col[:128]), 128)
        self.assertEqual(sum(col[128:]), 0)


if __name__ == "__main__":
    unittest.main()
