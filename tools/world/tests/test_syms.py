"""Symbol lookup for speed.exe v1.3: python -m unittest discover -s tools/world/tests -p test_syms.py -v"""
import random
import unittest

from common import EXE, SYMBOLS, need
from world import pe, syms


class SymsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, SYMBOLS)
        cls.s = syms.load()

    def test_find_loader(self):
        hits = self.s.by_name("FindLoader@bChunkLoader")
        self.assertIn(0x45D650, [a for a, _ in hits])

    def test_load_collision_pack(self):
        hits = self.s.by_name(r"LoadCollisionPack@WCollisionAssets")
        self.assertTrue(hits)
        for a, name in hits:
            self.assertTrue(0x401000 <= a < 0x890000, (hex(a), name))

    def test_at_inside_function(self):
        a, name = self.s.at(0x45D651)
        self.assertEqual(a, 0x45D650)
        self.assertIn("FindLoader", name)

    def test_at_outside_any_function(self):
        self.assertIsNone(self.s.at(0x300000))

    def test_symbols_match_exe(self):  # 20 named functions at a fixed seed: each starts with a real instruction
        need(self, EXE)
        named = [(a, n) for a, n in self.s.functions() if not n.startswith(("sub_", "nullsub_", "j_", "unknown"))]
        picks = random.Random(1351).sample(named, 20)
        img = pe.Image(EXE)
        results = pe.decode_first(EXE, [a for a, _ in picks])
        for (a, n) in picks:
            first = img.read(a, 4)
            self.assertNotIn(first[0], (0xCC, 0x00), "%08X %s starts with padding" % (a, n))
            self.assertTrue(results[a], "%08X %s does not decode" % (a, n))


if __name__ == "__main__":
    unittest.main()
