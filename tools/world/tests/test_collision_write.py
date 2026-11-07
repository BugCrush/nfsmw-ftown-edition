"""Collision packs (0x3B801) written by tools/world/collision_write.py, and the height model tools/world/heightcheck.py:
python -m unittest tools.world.tests.test_collision_write -v

The round trip runs all 390 of Rockport's packs through collision_write.read_pack and write_pack, which rebuilds the
CARP header's size, the UGroup/UData headers and offsets, the article headers, strip offsets and vertex counts, and
every alignment and filler run. heightcheck.height_at is a Python model of the game's height query
(WCollisionMgr::FindFaceInCInst, WCollisionMgr.cpp:196); it is checked against a brute-force search over Part 1's
reader's triangles on Rockport's own packs before it is used on ours. All coordinates are physics (y up).
"""
import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import L2RA, STREAM, need  # noqa: E402
from chunks import Chunk, chunk_bytes, read_chunks  # noqa: E402
from world import bun, collision, collision_write, heightcheck, scenery  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "tools", "x360"))
from vlthash import vlt32  # noqa: E402

ASPHALT = 0x19DB2F1E
# the 10 sections with the most road triangles (docs/ftown-notes.md, Task 4)
SECTIONS = ["G60", "E43", "P70", "G42", "D41", "E42", "E45", "G50", "G46", "Q42"]
# the place (physics): render (2000, 11500, 100) = physics (-11500, 100, 2000)
CX, CY, CZ = -11500.0, 100.0, 2000.0


def brute_height(tris, x, z, y):
    """The face below (x, y, z) with the smallest gap among all triangles (Part 1's reader), as the game's rules:
    gap > 0, the face's lowest corner less than 0.5 m above the point."""
    best = None
    for p0, p1, p2, _surf, _n in tris:
        d = (p1[2] - p2[2]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[2] - p2[2])
        if d == 0:
            continue
        a = ((p1[2] - p2[2]) * (x - p2[0]) + (p2[0] - p1[0]) * (z - p2[2])) / d
        b = ((p2[2] - p0[2]) * (x - p2[0]) + (p0[0] - p2[0]) * (z - p2[2])) / d
        c = 1 - a - b
        if min(a, b, c) < -1e-9:
            continue
        h = a * p0[1] + b * p1[1] + c * p2[1]
        gap = y - h
        if gap > 0 and min(p0[1], p1[1], p2[1]) - 0.5 < y and (best is None or gap < best[0]):
            best = (gap, h)
    return None if best is None else best[1]


def write_read(pack, pos=8):
    """The pack's bytes read back by both readers: (collision_write.Pack, collision.CollisionPack)."""
    c = collision_write.write_pack(pack, pos)
    top = read_chunks(chunk_bytes(c))
    return collision_write.read_pack(top[0].data, pos), collision.read_pack(top[0].data, pos)


def slab(size=200.0, step=10.0, y=CY):
    return collision_write.grid_faces(CX - size / 2, CZ - size / 2, CX + size / 2, CZ + size / 2, y, step)


class RoundTrip(unittest.TestCase):
    def test_all_packs_roundtrip(self):
        need(self, L2RA, STREAM)
        n = bad = 0
        first = None
        for s in bun.sections(L2RA):
            for c, pos in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
                if c.id != collision.COLLISION_PACK:
                    continue
                n += 1
                if chunk_bytes(collision_write.write_pack(collision_write.read_pack(c.data, pos), pos)) != chunk_bytes(c):
                    bad += 1
                    first = first or "%s at +0x%X" % (s.name, pos)
        print("\n  %d collision packs, %d differ%s" % (n, bad, "" if not first else " (first: %s)" % first))
        self.assertEqual(n, 390)
        self.assertEqual(bad, 0)


class HeightModel(unittest.TestCase):
    def test_heightcheck_matches_rockport(self):
        need(self, L2RA, STREAM)
        secs = {s.name: s for s in bun.sections(L2RA)}
        rng = random.Random(20261103)
        total = agree = 0
        worst = []
        for name in SECTIONS:
            s = secs[name]
            for c, pos in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
                if c.id != collision.COLLISION_PACK:
                    continue
                model = collision_write.read_pack(c.data, pos)
                tris = collision.triangles(collision.read_pack(c.data, pos))
                for _ in range(200):
                    p0, p1, p2, _surf, _n = rng.choice(tris)
                    a, b = rng.random(), rng.random()
                    if a + b > 1:
                        a, b = 1 - a, 1 - b
                    x = p0[0] + a * (p1[0] - p0[0]) + b * (p2[0] - p0[0])
                    z = p0[2] + a * (p1[2] - p0[2]) + b * (p2[2] - p0[2])
                    yf = p0[1] + a * (p1[1] - p0[1]) + b * (p2[1] - p0[1])
                    want = brute_height(tris, x, z, yf + 1.0)
                    got = heightcheck.height_at(model, x, z, yf + 1.0)
                    total += 1
                    if (want is None and got is None) or (want is not None and got is not None and
                                                          abs(want - got) <= 0.01):
                        agree += 1
                    else:
                        worst.append((name, x, z, want, got))
        print("\n  %d points, %d agree; first differences %s" % (total, agree, worst[:3]))
        self.assertEqual(total, 2000)
        self.assertEqual(agree, total)


class MakePack(unittest.TestCase):
    def test_make_pack_heights(self):
        pack, ref = write_read(collision_write.make_pack(2601, slab(), []))
        self.assertEqual(ref.section, 2601)
        self.assertEqual(ref.name, "2601")
        for art in ref.articles.values():
            self.assertEqual(art.surfaces, [ASPHALT])
        bad = []
        for i in range(201):
            for j in range(201):
                x, z = CX - 100 + i, CZ - 100 + j
                h = heightcheck.height_at(pack, x, z, CY + 1.0)
                if h is None or abs(h - 100.0) > 0.01:
                    bad.append((x, z, h))
        self.assertEqual(bad[:5], [])
        for x, z in ((CX - 100.5, CZ), (CX + 100.5, CZ), (CX, CZ - 100.5), (CX, CZ + 100.5),
                     (CX - 100.5, CZ - 100.5), (CX + 100.5, CZ + 100.5)):
            self.assertIsNone(heightcheck.height_at(pack, x, z, CY + 1.0))

    def test_make_pack_tile_and_surfaces(self):
        """F-Town's city packs: 128 m articles and a surface per face (asphalt, grass, ...), read back by Part 1's
        reader with the right surface under every face."""
        faces = slab(256.0, 8.0)
        grass = vlt32("grass")
        surf = [ASPHALT if (sum(p[0] for p in t) / 3) < CX else grass for t in faces]
        pack, ref = write_read(collision_write.make_pack(1100, faces, [], tile=128.0, face_surfaces=surf))
        # 256 m centred on the place: the 128 m tiles it touches (by triangle centre), not the 64 m ones
        self.assertLessEqual(len(pack.instances), 9)
        tris = collision.triangles(ref)
        self.assertEqual(len(tris), len(faces))
        for p0, p1, p2, h, _n in tris:
            cx = (p0[0] + p1[0] + p2[0]) / 3
            self.assertEqual(h, ASPHALT if cx < CX else grass)
        self.assertAlmostEqual(heightcheck.height_at(pack, CX - 50, CZ, CY + 1), CY, places=2)
        self.assertAlmostEqual(heightcheck.height_at(pack, CX + 50, CZ, CY + 1), CY, places=2)

    def test_make_pack_face_flags(self):
        """A flags byte per face (the high byte of the triangle's surface word: 4 = the wheels' query looks on past
        this face for a closer one, WWorldPos::FindClosestFace 0x779170) is written and read back face by face."""
        faces = slab(64.0, 8.0)
        flags = [4 if k % 3 == 0 else 0 for k in range(len(faces))]
        pack, _ = write_read(collision_write.make_pack(1100, faces, [], tile=128.0, face_flags=flags))
        got = {}
        for inst in pack.instances:
            art = pack.articles[inst.article]
            t = inst.t
            for st in art.strips:
                pts = st.points()
                for k in range(len(pts) - 2):
                    key = tuple(sorted((round(p[0] - t[0], 3), round(p[2] - t[2], 3)) for p in pts[k:k + 3]))
                    got[key] = st.surfaces[k] >> 8
        for f, fl in zip(faces, flags):
            key = tuple(sorted((round(p[0], 3), round(p[2], 3)) for p in f))
            self.assertEqual(got[key], fl)
        with self.assertRaises(ValueError):
            collision_write.make_pack(1100, faces, [], face_flags=[0])

    def test_make_pack_joins_strips(self):
        """Triangles handed over in strip order (each sharing the last two vertices of the one before) are joined into
        strips, so a grid of rows costs a few strips, not one per triangle."""
        pack, _ = write_read(collision_write.make_pack(1100, slab(64.0, 4.0), [], tile=128.0))
        n = sum(len(a.strips) for a in pack.articles)
        self.assertLess(n, 2 * 16 * 16 / 8)

    def test_make_pack_strips_in_range(self):
        pack, _ = write_read(collision_write.make_pack(2601, slab(400.0, 25.0), []))
        for art in pack.articles:
            for st in art.strips:
                for v in st.verts:
                    self.assertTrue(all(-32768 <= q <= 32767 for q in v[:3]))

    def test_make_pack_ramp(self):
        # a ramp 20 m long (physics +x), 8 m wide, rising 0 -> 3 m, on the slab with the slab's faces under it removed
        x0, x1, z0, z1 = CX - 10.0, CX + 10.0, CZ - 4.0, CZ + 4.0
        floor = [t for t in slab(step=2.0) if not all(x0 <= p[0] <= x1 and z0 <= p[2] <= z1 for p in t)]
        ramp = collision_write.ramp_faces(x0, z0, x1, z1, CY, CY + 3.0, 2.0)
        pack, _ = write_read(collision_write.make_pack(2601, floor + ramp, []))
        for k in range(0, 21):
            x = x0 + k
            want = CY + 3.0 * k / 20.0
            h = heightcheck.height_at(pack, x, CZ, want + 1.0)
            self.assertIsNotNone(h, x)
            self.assertAlmostEqual(h, want, delta=0.01)
        # the foot: on the slab just before the ramp, and the ramp's own face at its first metre
        self.assertAlmostEqual(heightcheck.height_at(pack, x0 - 1.0, CZ, CY + 1.0), CY, delta=0.01)
        self.assertAlmostEqual(heightcheck.height_at(pack, x0 + 0.5, CZ, CY + 1.0), CY + 0.075, delta=0.01)
        # no floor under the ramp: under its high end there is nothing below a point at the slab's level
        self.assertIsNone(heightcheck.height_at(pack, x1 - 1.0, CZ, CY + 0.5))
        # past the ramp's end: the slab again (the 3 m drop)
        self.assertAlmostEqual(heightcheck.height_at(pack, x1 + 1.0, CZ, CY + 4.0), CY, delta=0.01)

    def test_make_pack_barriers(self):
        walls = [((CX - 100.0, CZ - 100.0), (CX + 100.0, CZ - 100.0), CY, CY + 3.0),
                 ((CX + 25.0, CZ), (CX + 25.0, CZ + 50.0), CY, CY + 3.0)]
        _, ref = write_read(collision_write.make_pack(2601, slab(), walls))
        got = collision.barriers(ref)
        self.assertEqual(len(got), 2)
        for (a, b), (ga, gb, gh, gs, _n) in zip([(w[0], w[1]) for w in walls], got):
            self.assertEqual((ga[0], ga[2]), a)
            self.assertEqual((gb[0], gb[2]), b)
            self.assertEqual((min(ga[1], gb[1]), max(ga[1], gb[1])), (CY, CY + 3.0))
            self.assertAlmostEqual(gh, 3.0, places=4)
            self.assertEqual(gs, ASPHALT)

    def test_make_pack_barrier_flags(self):
        """A barrier's flags byte: 0x02 by default (single-sided, Rockport's 41,607), 0x12 when given (both sides)."""
        walls = [((CX - 10.0, CZ), (CX + 10.0, CZ), CY, CY + 3.0),
                 ((CX, CZ + 5.0), (CX + 10.0, CZ + 5.0), CY, CY + 3.0, 0x12)]
        pack, _ = write_read(collision_write.make_pack(2601, slab(), walls))
        got = sorted((b.word >> 8) & 0xFF for a in pack.articles for b in a.barriers)
        self.assertEqual(got, [0x02, 0x12])

    def test_make_pack_instances_cover_geometry(self):
        pack, ref = write_read(collision_write.make_pack(2601, slab(), []))
        for inst in ref.instances:
            art = ref.articles[inst.article]
            for st in art.strips:
                for v in st.verts:
                    self.assertLessEqual(abs(v[0]), inst.width)
                    self.assertLessEqual(abs(v[2]), inst.length)
            self.assertAlmostEqual(inst.radius, math.hypot(inst.width, inst.length), places=3)


if __name__ == "__main__":
    unittest.main()
