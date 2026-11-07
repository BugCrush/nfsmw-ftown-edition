"""Blender preparation of the Thar (the source .blend -> an intermediate folder of game parts):
python -m unittest discover -s tools/carbuild/tests -p test_prep.py

Runs `carbin.py prep` once per test class into .superpowers/carbuild/thar/test/prep (git-ignored) and checks the
result. Skips without portable Blender or the source model. The source .blend is only read.
"""
import json
import os
import re
import struct
import subprocess
import sys
import unittest

from common import CARBUILD, GTI_GEOMETRY, REPO, read

CARBIN = os.path.join(CARBUILD, "carbin.py")
BLENDER = os.path.join(REPO, ".tools", "blender-4.3.2-windows-x64", "blender.exe")
CONFIG = os.path.join(CARBUILD, "cars", "thar.json")
SOURCE = os.path.join(REPO, ".superpowers", "downloads", "cars", "thar", "blendswap", "Mahindra Thar 3D Model.blend")
PREP = os.path.join(REPO, ".superpowers", "carbuild", "thar", "test", "prep")


def load_part(folder, entry):
    """(positions, normals, uvs, materials) of one part level: triangle corners, unindexed."""
    t = entry["triangles"]
    with open(os.path.join(folder, entry["file"]), "rb") as f:
        data = f.read()
    n = t * 3
    pos = struct.unpack_from("<%df" % (n * 3), data, 0)
    nor = struct.unpack_from("<%df" % (n * 3), data, n * 12)
    uv = struct.unpack_from("<%df" % (n * 2), data, n * 24)
    mat = struct.unpack_from("<%dH" % t, data, n * 32)
    pts = [pos[k:k + 3] for k in range(0, len(pos), 3)]
    nrm = [nor[k:k + 3] for k in range(0, len(nor), 3)]
    uvs = [uv[k:k + 2] for k in range(0, len(uv), 2)]
    return pts, nrm, uvs, list(mat)


def box(pts):
    return [min(p[a] for p in pts) for a in range(3)] + [max(p[a] for p in pts) for a in range(3)]


class PrepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BLENDER):
            raise unittest.SkipTest("portable Blender missing at " + BLENDER)
        if not os.path.exists(SOURCE):
            raise unittest.SkipTest("source model missing at " + SOURCE)
        r = subprocess.run([sys.executable, CARBIN, "prep", CONFIG, "--out", PREP], capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError("prep failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        with open(os.path.join(PREP, "parts.json"), encoding="utf-8") as f:
            cls.info = json.load(f)
        with open(os.path.join(PREP, "wheel.json"), encoding="utf-8") as f:
            cls.wheel = json.load(f)
        cls.cache = {}

    def level(self, part, lod="A"):
        key = (part, lod)
        if key not in self.cache:
            self.cache[key] = load_part(PREP, self.info["parts"][part]["levels"][lod])
        return self.cache[key]

    def all_points(self, lod="A", tyre=False):
        out = []
        for name, p in self.info["parts"].items():
            if lod in p["levels"] and (tyre or name != "KIT00_FRONT_TIRE"):
                out += self.level(name, lod)[0]
        return out

    def test_dimensions(self):
        b = box(self.all_points())
        length, width, height = b[3] - b[0], b[4] - b[1], b[5] - b[2]
        self.assertAlmostEqual(length, 3.99, delta=0.01)
        self.assertAlmostEqual(self.info["source_length"] * self.info["scale"], 3.99, delta=0.001)
        # like with like: the parts without the four wheels (the tyre part sits at the origin) against the source's
        # objects without them (source axes: length along y, width x, height z)
        src = self.info["source_box_without_wheels"]
        s = length / (src[4] - src[1])
        self.assertAlmostEqual(width / (src[3] - src[0]), s, delta=0.005 * s)
        self.assertAlmostEqual(height / (src[5] - src[2]), s, delta=0.005 * s)

    def test_axes(self):
        parts = self.info["parts"]
        for side in ("LEFT", "RIGHT"):
            hl = box(self.level("KIT00_%s_HEADLIGHT" % side)[0])
            self.assertGreater((hl[0] + hl[3]) / 2, 1.5)
            bl = box(self.level("KIT00_%s_BRAKELIGHT" % side)[0])
            self.assertLess((bl[0] + bl[3]) / 2, -1.5)
        for name in parts:
            if "_LEFT_" in name or name.startswith("LEFT_"):
                b = box(self.level(name)[0])
                self.assertGreater((b[1] + b[4]) / 2, 0, name)

    def test_left_right_symmetry(self):
        for name in self.info["parts"]:
            if "_LEFT_" not in name:
                continue
            twin = name.replace("_LEFT_", "_RIGHT_")
            self.assertIn(twin, self.info["parts"])
            a, b = box(self.level(name)[0]), box(self.level(twin)[0])
            mirrored = [b[0], -b[4], b[2], b[3], -b[1], b[5]]
            for u, v in zip(a, mirrored):
                self.assertAlmostEqual(u, v, delta=0.005, msg="%s vs %s: %s / %s" % (name, twin, a, mirrored))
        pts, nrm, _, _ = self.level("KIT00_BODY")
        c = [sum(p[a] for p in pts) / len(pts) for a in range(3)]
        mean = sum(sum(n[a] * (p[a] - c[a]) for a in range(3)) for p, n in zip(pts, nrm)) / len(pts)
        self.assertGreater(mean, 0, "the body's normals face inward on average")

    def test_part_budgets(self):
        total = 0
        for name, p in self.info["parts"].items():
            e = p["levels"]["A"]
            pts, nrm, uvs, mats = self.level(name)
            with self.subTest(part=name):
                self.assertGreater(e["triangles"], 0)
                self.assertEqual(len(mats), e["triangles"])
                self.assertLess(len(set(zip(pts, nrm, uvs))), 65536)
                self.assertTrue(all(m < len(p["materials"]) for m in mats))
            total += e["triangles"]
        self.assertLessEqual(self.info["parts"]["KIT00_BODY"]["levels"]["A"]["triangles"], 20000)
        self.assertTrue(25000 <= total <= 45000, "level A total %d" % total)

    def test_part_names_follow_gti(self):
        names = {"BASE", "KIT00_BODY", "KIT00_FRONT_TIRE", "KIT00_FRONT_WINDOW", "KIT00_REAR_WINDOW",
                 "KIT00_LEFT_HEADLIGHT", "KIT00_RIGHT_HEADLIGHT", "KIT00_LEFT_BRAKELIGHT", "KIT00_RIGHT_BRAKELIGHT",
                 "KIT00_LEFT_SIDE_MIRROR", "KIT00_RIGHT_SIDE_MIRROR"}
        self.assertTrue(names <= set(self.info["parts"]), names - set(self.info["parts"]))
        if os.path.exists(GTI_GEOMETRY):
            from geometry import read_geometry
            gti = {re.sub(r"^GTI_|_[A-E]$", "", s.name) for s in read_geometry(read(GTI_GEOMETRY)).solids}
            self.assertEqual(set(self.info["parts"]) - gti, set())

    def test_tyre_follows_rule(self):
        import conventions
        b = box(self.level("KIT00_FRONT_TIRE")[0])
        self.assertLess(abs((b[0] + b[3]) / 2), 0.005)
        self.assertLess(abs((b[2] + b[5]) / 2), 0.005)
        if conventions.TYRE_SIDE > 0:
            self.assertAlmostEqual(b[1], 0.0, delta=0.001)
            self.assertGreater(b[4], 0.15)
        radius = max(b[3] - b[0], b[5] - b[2]) / 2
        self.assertAlmostEqual(radius, self.wheel["radius"], delta=0.01)
        self.assertAlmostEqual(b[4] - b[1], self.wheel["width"], delta=0.01)
        c = self.wheel["centres"]
        self.assertGreater(c["FL"][0], 0)
        self.assertLess(c["RL"][0], 0)
        self.assertGreater(c["FL"][1], 0)
        self.assertLess(c["FR"][1], 0)

    def test_lods(self):
        """Detail levels as the GTI has them per part (E only on the body; brake light glass A..C), each with fewer
        triangles than the one before, and none shrinking the part (every box within 2 cm of level A's)."""
        table = {}
        if os.path.exists(GTI_GEOMETRY):
            from geometry import read_geometry
            for s in read_geometry(read(GTI_GEOMETRY)).solids:
                m = re.match(r"GTI_(.*)_([A-E])$", s.name)
                if m:
                    table.setdefault(m.group(1), set()).add(m.group(2))
        else:
            self.skipTest("the GTI's level table needs the game's GTI")
        for name, p in self.info["parts"].items():
            with self.subTest(part=name):
                self.assertEqual(set(p["levels"]), table[name])
                lods = sorted(p["levels"])
                counts = [p["levels"][l]["triangles"] for l in lods]
                self.assertEqual(counts, sorted(counts, reverse=True))
                self.assertEqual(len(set(counts)), len(counts), "%s: %s" % (name, counts))
                a = p["levels"]["A"]["box"]
                for l in lods[1:]:
                    for u, v in zip(a, p["levels"][l]["box"]):
                        self.assertAlmostEqual(u, v, delta=0.02, msg="%s level %s box" % (name, l))
                    self.assertEqual(len(load_part(PREP, p["levels"][l])[3]), p["levels"][l]["triangles"])

    def test_no_dropped_object_survives(self):
        used = {o for p in self.info["parts"].values() for o in p["objects"]}
        for name in used:
            self.assertFalse(name == "Plane.005" or name.startswith("Cutter") or name == "WIper's", name)
        # Cube.001 is a boolean cutter in the render-hidden collection "extra" (final review finding 2): objects in
        # collections hidden from renders are not part of the car
        self.assertNotIn("Cube.001", used)
        self.assertIn("Cube.001", self.info["dropped"])
        self.assertIn("Plane.005", self.info["dropped"])
        self.assertIn("WIper's", self.info["dropped"])


if __name__ == "__main__":
    unittest.main()
