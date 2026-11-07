"""Rockport's section C9 moved to the F-Town place (tools/world/relocate.py), the loader's known-good test data:
python -m unittest tools.world.tests.test_relocate -v

The output is game data and is written only under .superpowers/world/ (git-ignored).
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import GAME, L2RA, OUT, STREAM, need  # noqa: E402
from chunks import read_chunks, write_chunks  # noqa: E402
from world import bun, collision, collision_write, heightcheck, relocate, scenery, slab, texpack  # noqa: E402


class Relocated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA, STREAM)
        cls.r = relocate.relocate(GAME, "C9")
        cls.data = write_chunks(cls.r.chunks)
        cls.top = read_chunks(cls.data)
        pos = scenery.with_positions(cls.top, 0)
        cls.pack = [collision_write.read_pack(c.data, p) for c, p in pos if c.id == collision.COLLISION_PACK][0]
        cls.ref = [collision.read_pack(c.data, p) for c, p in pos if c.id == collision.COLLISION_PACK][0]
        cls.sec = scenery.read_section(cls.top)

    def test_numbers_are_the_slabs(self):
        self.assertEqual([s.number for s in self.sec.sceneries], [slab.SECTION_NUMBER])
        self.assertEqual(self.ref.section, slab.PACK_NUMBER)
        self.assertEqual(self.ref.name, str(slab.PACK_NUMBER))

    def test_shift_lands_on_the_place(self):
        s = self.r.shift
        cx, cy = self.r.centre
        # the shift is stored as float32 (as every coordinate it moves): 1 mm
        self.assertAlmostEqual(cx + s[0], slab.CENTRE[0], delta=0.001)
        self.assertAlmostEqual(cy + s[1], slab.CENTRE[1], delta=0.001)
        self.assertAlmostEqual(self.r.road_height + s[2], slab.TOP, delta=0.001)

    def test_relocated_heights(self):
        rng = random.Random(9)
        tris = collision.triangles(self.r.original_ref)
        s = self.r.shift
        ps = collision.to_physics(s)
        checked = 0
        for _ in range(500):
            p0, p1, p2, _surf, _n = rng.choice(tris)
            a, b = rng.random(), rng.random()
            if a + b > 1:
                a, b = 1 - a, 1 - b
            x = p0[0] + a * (p1[0] - p0[0]) + b * (p2[0] - p0[0])
            z = p0[2] + a * (p1[2] - p0[2]) + b * (p2[2] - p0[2])
            y = p0[1] + a * (p1[1] - p0[1]) + b * (p2[1] - p0[1]) + 1.0
            want = heightcheck.height_at(self.r.original_pack, x, z, y)
            got = heightcheck.height_at(self.pack, x + ps[0], z + ps[2], y + ps[1])
            if want is None:
                self.assertIsNone(got)
            else:
                self.assertIsNotNone(got)
                self.assertAlmostEqual(got, want + ps[1], delta=0.01)
                checked += 1
        self.assertGreater(checked, 400)

    def test_relocated_draw_matches(self):
        """Every placed vertex (instance matrix x solid vertex) = the original's + the shift."""
        orig = self.r.original_placed
        new = relocate.placed_vertices(self.sec)
        self.assertEqual(len(orig), len(new))
        self.assertGreater(len(new), 10000)
        s = self.r.shift
        worst = max(max(abs(n[a] - (o[a] + s[a])) for a in range(3)) for o, n in zip(orig, new))
        self.assertLess(worst, 0.01)

    def test_relocated_self_contained(self):
        have = set(self.sec.solids)
        for sc in self.sec.sceneries:
            for inst in sc.instances:
                for h in sc.infos[inst.info_index].solid_hashes:
                    if h not in scenery.NO_MODEL and h not in self.r.solids_not_found:
                        self.assertIn(h, have)
        # the references that stay unresolved name solids Rockport's region file does not have either
        self.assertLessEqual(len(self.r.solids_not_found), 3)
        self.assertFalse(self.r.solids_not_found & self.r.rockport_solid_hashes)
        tp = texpack.read_pack([c for c in self.top if c.id == texpack.PACK][0], 8)
        tex = {t.name_hash for t in tp.textures}
        missing = {t for so in self.sec.solids.values() for t in so.textures} - tex
        self.assertEqual(sorted(missing)[:5], sorted(self.r.textures_not_found)[:5])
        self.assertLessEqual(len(missing), len(self.r.textures_not_found))

    def test_names_do_not_collide_with_rockport(self):
        """Every solid and texture of the file is renamed (FTR_...), so loading it next to Rockport's own copies
        registers no name twice."""
        self.assertFalse(set(self.sec.solids) & self.r.rockport_solid_hashes)
        tp = texpack.read_pack([c for c in self.top if c.id == texpack.PACK][0], 8)
        self.assertFalse({t.name_hash for t in tp.textures} & self.r.rockport_texture_hashes)

    def test_all_instances_preculler_zero(self):
        for inst in self.sec.instances:
            self.assertEqual(inst.preculler, 0)
        self.assertEqual(self.sec.sceneries[0].other[scenery.PRECULLER][:0x80], bytes(0x80))

    def test_spawn_on_its_road(self):
        x, y, z, _h = relocate.spawn(self.r)
        p = collision.to_physics((x, y, z))
        h = heightcheck.height_at(self.pack, p[0], p[2], p[1] + 0.025)
        self.assertIsNotNone(h)
        self.assertAlmostEqual(z - h, 1.0, delta=0.05)

    def test_written_only_under_superpowers(self):
        out = os.path.join(OUT, "ftown-reloc-test.bun")
        relocate.write(self.r, out)
        self.assertTrue(os.path.abspath(out).startswith(os.path.abspath(OUT)))
        with open(out, "rb") as f:
            self.assertEqual(f.read(), self.data)
        os.remove(out)


if __name__ == "__main__":
    unittest.main()
