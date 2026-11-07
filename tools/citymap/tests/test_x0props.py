"""Street life Task 1: X0's catalogue (Rockport's library section of trees and street objects, read from the game's
files; only names, hashes, boxes and counts are kept: tools/citymap/x0props.json).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_x0props -v
"""
import json
import os
import re
import unittest

from tools.citymap.tests import common

GAME = os.path.join(common.REPO, "Need For Speed Most Wanted Black Edition")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")


def x0():
    if not os.path.exists(STREAM):
        raise unittest.SkipTest("the game's files are not here")
    if "x0" not in common._cache:
        from tools.citymap import x0props
        common._cache["x0"] = x0props.read_x0(GAME)
    return common._cache["x0"]


class Catalogue(unittest.TestCase):
    def test_every_catalogued_hash_is_in_x0(self):
        """Every model of the committed catalogue is a solid of X0 with that name, mesh and triangle count."""
        from tools.citymap import x0props
        cat = x0props.load()
        solids = x0()
        self.assertGreater(len(cat["models"]), 100)
        for m in cat["models"]:
            so = solids.get(int(m["hash"], 16))
            self.assertIsNotNone(so, m["name"])
            self.assertEqual(so.name, m["name"])
            self.assertEqual(len(so.meshes), m["meshes"], m["name"])
            self.assertEqual(x0props.num_polys(so), m["tris"], m["name"])

    def test_catalogue_is_whole_models_only(self):
        """No breakable prop's fragment or damaged state (_FRAG, _DMG, _PART, _PAPER, SMACK) is catalogued; every
        model is an X?_..._<n><level>_ name of a detail set (A/B = near, C, Z)."""
        from tools.citymap import x0props
        for m in x0props.load()["models"]:
            self.assertTrue(x0props.whole(m["name"]), m["name"])
            self.assertIsNone(re.search(r"FRAG|DMG|_PART|PAPER|SMACK", m["name"]), m["name"])
            self.assertIn(m["level"], "ABCZ")
        self.assertFalse(x0props.whole("XO_PARKBENCHA_FRAG01"))
        self.assertFalse(x0props.whole("TRASHCAN_PART01"))
        self.assertTrue(x0props.whole("XT_CT_POPLARS_1B_JG_00"))

    def test_picks_are_near_models_the_main_view_draws(self):
        """Every pick is a catalogued near model (level A or B) that Rockport's own scenery puts in slot 0 (the slot
        the main view draws close up: DrawAScenery, Scenery.cpp:740-756), with its kind, a scale and a draw
        distance; trees and parked things are solid, bushes and benches not (the plan)."""
        from tools.citymap import x0props
        cat = x0props.load()
        by_name = {m["name"]: m for m in cat["models"]}
        self.assertEqual(set(cat["picks"]), set(x0props.PICKS))
        for role, p in cat["picks"].items():
            m = by_name[p["name"]]
            self.assertIn(m["level"], "AB", role)
            self.assertGreater(m["use"].get("0", 0), 0, role)
            self.assertEqual(p["hash"], m["hash"])
            self.assertGreater(p["draw"], 0)
        kinds = {r: by_name[p["name"]]["kind"] for r, p in cat["picks"].items()}
        self.assertIn("tree", kinds.values())
        self.assertIn("bush", kinds.values())
        for role, p in cat["picks"].items():
            self.assertEqual(p["solid"], kinds[role] in ("tree", "shelter"), role)
            # Rockport's flags at slot 0, but the low byte 0x60 as the tiles' (exclude bits ^ 0x60 against the view's
            # flags, Scenery.cpp:695: 0x60 is drawn in every view the tiles are); never 0x80, 0x200 or 0x2000000
            fl = int(p["flags"], 16)
            self.assertEqual(fl & 0xFF, 0x60, role)
            self.assertFalse(fl & 0x2000280, role)

    def test_committed_catalogue_is_current(self):
        """The committed json is what the reader makes from the game's files today (deterministic)."""
        from tools.citymap import x0props
        x0()
        with open(x0props.CATALOGUE) as f:
            committed = json.load(f)
        self.assertEqual(x0props.catalogue(GAME), committed)

    def test_draw_distance_by_radius(self):
        """Each pick's info radius makes the game drop it at its draw distance (VIEW_H): a model of 40 triangles or
        more goes to slot 2 (empty: drawn nothing) when pixel size / max(Density, 6) < 8.7, pixel size = (radius + 6)
        H / (d - radius - 6); one of 39 or fewer never switches and is drawn until its pixel size reaches 17
        (DrawAScenery 0x729120)."""
        from tools.citymap import build_city, x0props
        cat = x0props.load()
        by_name = {m["name"]: m for m in cat["models"]}
        H = build_city.VIEW_H
        for role, p in cat["picks"].items():
            m = by_name[p["name"]]
            r = x0props.info_radius(role)
            self.assertGreaterEqual(r, 0.0)
            R = r + 6.0
            if m["tris"] > 39:
                d = R + R * H / (8.7 * max(6.0, m["density"]))
                self.assertAlmostEqual(d, p["draw"], delta=1.0, msg=role)
                # never far close up whatever H (720..1000): within 2R the pixel size is H itself
                self.assertGreater(720.0 / max(6.0, m["density"]), 8.7, role)
            else:
                self.assertEqual(r, 0.0, role)
                self.assertAlmostEqual(p["draw"], R + R * H / 17.0, delta=1.0, msg=role)
            self.assertEqual(x0props.slots(role), (int(p["hash"], 16), 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
