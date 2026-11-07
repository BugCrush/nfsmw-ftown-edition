"""Choosing the game car whose interior and driver the Thar borrows (plan 2026-11-02-thar-fixes, Task 2):
python -m unittest discover -s tools/carbuild/tests -p test_interior.py

Reads the game's cars read-only and the Thar's built GEOMETRY.BIN (.superpowers/carbuild/thar/out, made by
`carbin.py assemble`); skips without them.
"""
import os
import unittest

from common import CARS, REPO, read

THAR_GEOMETRY = os.path.join(REPO, ".superpowers", "carbuild", "thar", "out", "GEOMETRY.BIN")
TOL = 0.001


class DonorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(CARS) or not os.path.exists(THAR_GEOMETRY):
            raise unittest.SkipTest("the game's cars or the Thar's build are missing")
        import interior
        from geometry import read_geometry
        cls.interior = interior
        cls.thar = read_geometry(read(THAR_GEOMETRY))
        cls.candidates = interior.CANDIDATES
        cls.usable, cls.excluded = interior.candidates(CARS, cls.candidates)
        cls.choice = interior.choose_donor(cls.thar, CARS, cls.candidates)

    def test_every_candidate_has_interior_and_driver(self):
        self.assertIn("COPSUV", self.candidates)  # the plan's tall-cabin candidates are looked at ...
        self.assertIn("COPSUVL", self.candidates)
        self.assertIn("COPSUV", self.excluded)  # ... but the police cars have a driver only, painted on their skin
        self.assertIn("INTERIOR", self.excluded["COPSUV"])
        self.assertGreater(len(self.usable), 20)
        for car, pack in self.usable.items():
            names = {s.name for s in pack.solids}
            self.assertIn(car + "_KIT00_INTERIOR_A", names)
            self.assertIn(car + "_KIT00_DRIVER_A", names)

    def test_donor_fit(self):
        c = self.choice
        self.assertIn(c["car"], self.usable)
        for s in c["transform"]["scale"]:
            self.assertTrue(0.85 - 1e-9 <= s <= 1.15, c["transform"])
        self.assertEqual(len(set(c["transform"]["scale"])), 1, "uniform scale (the plan's preference)")
        self.assertLessEqual(c["transform"]["clamp_depth"], 0.05)  # at most 5 cm pressed onto the rear glass plane
        # and it fills the cabin's length: a two-seater that leaves the back empty (the Elise: 0.65 m) is not a fit
        self.assertLessEqual(c["transform"]["rear_gap"], 0.05)
        # no other usable donor needs less scaling
        for car, t in c["others"].items():
            self.assertGreaterEqual(t["score"], c["transform"]["score"] - 1e-9, car)
        gh = self.interior.glasshouse(self.thar, "THAR")
        parts = self.interior.transplant(self.usable[c["car"]], c["car"], "THAR", c["transform"])
        self.assertTrue(parts)
        for s in parts:
            ps = [p for m in s.meshes() for p in s.positions(m)]
            for k in range(3):
                self.assertGreaterEqual(min(p[k] for p in ps), gh[k] - TOL, "%s axis %d" % (s.name, k))
                self.assertLessEqual(max(p[k] for p in ps), gh[k + 3] + TOL, "%s axis %d" % (s.name, k))

    def test_config_names_the_chosen_donor(self):
        """Final review finding 2: the donor fixed in thar.json is the one the measurement picks today."""
        import json
        with open(os.path.join(REPO, "tools", "carbuild", "cars", "thar.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["interior"]["donor"], self.choice["car"])

    def test_borrow_refuses_an_ineligible_donor(self):
        """The assembler applies choose_donor's checks to the configured donor: the SL500 (its interior uses its own
        _MISC) is refused; the SL65 is accepted."""
        import assemble
        from textures import TexturePack
        self.assertIsNone(self.interior.ineligible(CARS, "SL65"))
        self.assertIn("_MISC", self.interior.ineligible(CARS, "SL500"))
        with self.assertRaises(ValueError):
            assemble.borrow_interior({"car": "THAR", "interior": {"donor": "SL500"}}, list(self.thar.solids),
                                     TexturePack(name="x", filename="x", textures=[]), CARS)

    def test_donor_own_textures_take_car_names(self):
        """The game loads a car's own textures by name from a fixed list (<CAR>_SKIN1, _MISC, _INTERIOR, _INTERIOR_N,
        _BADGING, _DRIVER, ... : Unlimiter CarRenderInfo.h GetUsedCarTextureInfo; every game car's pack holds only such
        names), so the donor's own textures must become <CAR>_INTERIOR(_N): a donor whose interior also uses its _MISC
        (the SL500) would clash with the Thar's own palette THAR_MISC."""
        from chunks import bstringhash
        c = self.choice
        own = self.interior.donor_textures(CARS, c["car"])
        allowed = {bstringhash(c["car"] + "_INTERIOR"), bstringhash(c["car"] + "_INTERIOR_N")}
        for s in self.usable[c["car"]].solids:
            if self.interior.is_interior_part(s.name, c["car"]):
                for h in s.textures:
                    if h in own:
                        self.assertIn(h, allowed, "%s: own texture %s" % (s.name, own[h].name))
        self.assertIn("SL500", self.choice["excluded"])

    def test_donor_textures_decodable(self):
        """Every texture the chosen parts name is either decodable in the donor's own pack (to copy into the Thar's)
        or one of the game's global textures, found in the game's GLOBAL files (none needs substituting)."""
        c = self.choice
        own = self.interior.donor_textures(CARS, c["car"])
        globals_ = self.interior.global_texture_hashes(os.path.join(os.path.dirname(CARS), "GLOBAL"))
        globals_ |= self.interior.shared_texture_hashes(CARS)
        parts = [s for s in self.usable[c["car"]].solids if self.interior.is_interior_part(s.name, c["car"])]
        self.assertTrue(parts)
        seen_own = 0
        for s in parts:
            for h in s.textures:
                if h in own:
                    self.assertIsNotNone(own[h].data, "%s: texture 0x%08X is HUFF" % (s.name, h))
                    seen_own += 1
                else:
                    self.assertIn(h, globals_, "%s: texture 0x%08X is nowhere" % (s.name, h))
        self.assertGreater(seen_own, 0)
        self.assertEqual(c["substituted"], [])


if __name__ == "__main__":
    unittest.main()
