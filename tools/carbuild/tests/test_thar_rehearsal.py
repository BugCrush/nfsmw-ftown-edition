"""The Thar's install rehearsed in a scratch mini game folder (slow: one install per run, about a minute or two):

    python -m unittest discover -s tools/carbuild/tests -p test_thar_rehearsal.py

Makes .superpowers/carbuild/thar/rehearsal from copies of the game's files (tools/carbuild/rehearsal.py), builds the
package (tools/cars/packages/thar/build.py), runs tools/cars/install.py's install of `thar` into it with a record under
.superpowers/carbuild/thar/rehearsal-records/, and reads every result back. The last test (named to sort last) undoes
the install and compares every file with its state before. Never touches the game or the test copy; skips without the
game, Binarius or Attribulator.
"""
import hashlib
import os
import re
import struct
import subprocess
import sys
import time
import unittest

from common import GAME, REPO, need, read
from chunks import bstringhash, find, read_chunks

sys.path.insert(0, os.path.join(REPO, "tools", "cars"))
sys.path.insert(0, os.path.join(REPO, "tools", "x360"))
OUT = os.path.join(REPO, ".superpowers", "carbuild", "thar", "out")
PKG = os.path.join(REPO, "tools", "cars", "packages", "thar")
CACHE = os.path.join(REPO, ".superpowers", "carbuild", "cache")
LANGUAGES = ("Danish", "Dutch", "English", "Finnish", "French", "German", "Italian", "Largest", "Polish", "Spanish",
             "Swedish")
CAR_TYPES, RECORD, SKINNABLE, USAGE, MAKER_AT = 0x00034600, 0xD0, 0xC7, 0x94, 0x40


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tree(root):
    out = {}
    for dp, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = sha(p)
    return out


def car_type_record(data, name):
    """The game's 0xD0-byte CarTypeInfo record for name in GlobalB.lzc's car type chunk."""
    p = 0
    while p + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, p)
        if cid == CAR_TYPES:
            start = p + 8
            while data[start] == 0x11:
                start += 1
            recs = [data[start + i * RECORD:start + (i + 1) * RECORD] for i in range((p + 8 + size - start) // RECORD)]
            found = [r for r in recs if r[:16].split(b"\0")[0] == name]
            return found, recs
        p += 8 + size
    raise ValueError("no car type chunk")


class TharRehearsalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import install
        import rehearsal
        need_files = [os.path.join(GAME, "GLOBAL", "GlobalB.lzc"), os.path.join(OUT, "GEOMETRY.BIN"),
                      os.path.join(install.BINARIUS_DIR, "Binarius.exe")]
        for p in need_files:
            if not os.path.exists(p):
                raise unittest.SkipTest("missing: " + p)
        sys.path.insert(0, PKG)
        import build
        build.build()
        cls.mini = rehearsal.make(GAME, rehearsal.MINI)
        cls.record = os.path.join(rehearsal.RECORDS, "thar-" + time.strftime("%Y%m%d-%H%M%S"))
        cls.before = tree(cls.mini)
        cls.result = install.install("thar", install.load_config()["thar"], cls.mini, cls.record)
        cls.after = tree(cls.mini)

    def path(self, rel):
        return os.path.join(self.mini, *rel.split("/"))

    def test_rehearsal_car_type_and_parts(self):
        globalb = read(self.path("GLOBAL/GlobalB.lzc"))
        found, recs = car_type_record(globalb, b"THAR")
        self.assertEqual(len(found), 1)
        r = found[0]
        self.assertEqual(r[MAKER_AT:MAKER_AT + 16].split(b"\0")[0], b"MAHINDRA")
        self.assertEqual(r[SKINNABLE], 1)
        self.assertEqual(struct.unpack_from("<i", r, USAGE)[0], 0)
        self.assertEqual(struct.unpack_from("<I", r, 0x50)[0], bstringhash("THAR"))  # CarTypeNameHash
        gti = car_type_record(globalb, b"GTI")[0][0]
        self.assertEqual(gti[SKINNABLE], 1)  # the layout check: a stock racer reads 1 there too
        # the parts list: a THAR model with its parts, the body kits' labels THAR_CV.. (strings in the parts chunk)
        import parts
        p = parts.read_parts_bytes(globalb)
        thar = [x for x in p if x.model_hash == bstringhash("THAR")]
        self.assertGreater(len(thar), 100)
        self.assertTrue(all(x.name_hash != 0 for x in thar))
        self.assertIn(bstringhash("THAR_BODY_KIT00"), {x.name_hash for x in thar})
        self.assertFalse([x for x in p if "LONGNOSECAB" in x.name and x.model_hash == bstringhash("THAR")])
        # the interior and driver parts (Thar fix 2): THAR_INTERIOR / THAR_DRIVER, no attributes, the same group and
        # name-building entry (struct offset) as the GTI's, whose parts draw GTI_KIT00_INTERIOR_<LOD> /
        # GTI_KIT00_DRIVER_<LOD>: so the Thar's draw THAR_KIT00_INTERIOR_<LOD> / THAR_KIT00_DRIVER_<LOD>
        subs = parts._subs(globalb)
        a_at, a_size = subs[parts.SUB_ARRAY]
        recs = [struct.unpack_from("<IBHBHHH", globalb, a_at + 8 + i * parts.RECORD) for i in range(a_size // parts.RECORD)]
        by_hash = {r[0]: r for r in recs}
        for what in ("INTERIOR", "DRIVER"):
            mine, gti = by_hash.get(bstringhash("THAR_" + what)), by_hash[bstringhash("GTI_" + what)]
            self.assertIsNotNone(mine, what)
            self.assertEqual(p[recs.index(mine)].model_hash, bstringhash("THAR"), what)
            # group, upgrade group, attribute offset (none), struct offset
            self.assertEqual((mine[1], mine[2], mine[5], mine[6]), (gti[1], gti[2], gti[5], gti[6]), what)
        # labels: exported back with Nikki (the form Binarius imports), THAR_CV and no GTI_CV
        import extract_car
        exp = os.path.join(self.record, "exported")
        files = extract_car.extract_car(self.path("GLOBAL/GlobalB.lzc"), "THAR", exp)
        dbp = read(files["DBModelParts"])
        # Nikki writes a string it doesn't know as its hash ("0x%08X" of bStringHash): the labels come back that way
        for label in ["THAR_CV"] + ["THAR_0%d_CV" % k for k in range(1, 6)]:
            self.assertIn(b"0x%08X\0" % bstringhash(label), dbp, label)
        for label in ["GTI_CV"] + ["GTI_0%d_CV" % k for k in range(1, 6)] + ["LONGNOSECAB_CV"]:
            self.assertNotIn(b"0x%08X\0" % bstringhash(label), dbp, label)
            self.assertNotIn(label.encode() + b"\0", dbp, label)
        self.assertNotIn(b"LONGNOSECAB", dbp)
        # the collision: one named THAR, a copy of the GTI's
        col = read(files["Collisions"])
        self.assertIn(b"THAR\0", col[:64])
        gti_col = read(extract_car.extract_car(self.path("GLOBAL/GlobalB.lzc"), "GTI", os.path.join(exp, "gti"),
                                               ["Collisions"])["Collisions"])
        self.assertEqual(col[36 + len(b"THAR\0"):], gti_col[36 + len(b"GTI\0"):])

    def test_rehearsal_part_indices_same(self):
        before = os.path.join(self.record, "before", "GLOBAL", "GlobalB.lzc")
        self.assertTrue(os.path.exists(before))
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "cars", "parts.py"), "diff", before,
                            self.path("GLOBAL/GlobalB.lzc"), self.path("SAVE/NFS Most Wanted/player/player")],
                           capture_output=True, text=True)
        self.assertTrue(p.stdout.startswith("SAME"), p.stdout + p.stderr)
        self.assertEqual(p.returncode, 0)

    def test_rehearsal_database(self):
        import thar_db
        import yaml
        y = thar_db.game_unpack(self.mini, CACHE)

        def coll(cls, name):
            colls, vlt32 = thar_db._collections(y, cls)
            it = colls.get(name) or colls.get(vlt32(name))
            self.assertIsNotNone(it, "%s %s missing" % (cls, name))
            return it

        pv = coll("pvehicle", "thar")
        self.assertEqual(str(pv["ParentName"]), "racers")
        d = pv["Data"]
        self.assertEqual(d["MASS"], 5000)
        self.assertEqual(d["MODEL"], "THAR")
        self.assertEqual(d["frontend"], {"ClassKey": "frontend", "CollectionKey": "thar"})
        for f in ("engine", "transmission", "tires", "chassis", "brakes"):
            refs = d[f]["Data"]
            self.assertEqual(refs[0], {"ClassKey": f, "CollectionKey": "thar"})
            self.assertEqual(refs[1]["ClassKey"], f)
            self.assertIn(refs[1]["CollectionKey"], ("thar_top", thar_db._collections(y, f)[1]("thar_top")))
        fe = coll("frontend", "thar")
        self.assertEqual(str(fe["ParentName"]), "mahindra")
        self.assertEqual(fe["Data"]["UnlockedAt"], 16)
        self.assertIs(fe["Data"]["IsCustomizable"], True)
        self.assertEqual(fe["Data"]["CollectionName"], "thar")
        self.assertEqual(fe["Data"]["Cost"], 70000)
        self.assertEqual(str(coll("frontend", "mahindra")["ParentName"]), "japan")
        self.assertEqual(coll("frontend", "mahindra")["Data"]["CollectionName"], "mahindra")
        for stage in ("thar", "thar_top"):
            t = coll("tires", stage)["Data"]
            for axle in ("Front", "Rear"):
                self.assertEqual((t["SECTION_WIDTH"][axle], t["ASPECT_RATIO"][axle], t["RIM_SIZE"][axle]), (245, 50, 19))
                self.assertAlmostEqual(coll("chassis", stage)["Data"]["RIDE_HEIGHT"][axle], 9.3, places=5)  # float32
        self.assertAlmostEqual(coll("engine", "thar_top")["Data"]["TORQUE"]["Data"][5], 1.25 * 4547.4, delta=0.01)
        e = coll("ecar", "thar")["Data"]
        offs = e["TireOffsets"]["Data"]
        self.assertAlmostEqual(offs[0]["X"], 1.3237, delta=1e-3)
        self.assertAlmostEqual(offs[0]["Y"], 0.9366, delta=1e-3)
        self.assertAlmostEqual(offs[1]["Y"], -0.9366, delta=1e-3)
        self.assertAlmostEqual(offs[2]["X"], -1.0841, delta=1e-3)
        self.assertAlmostEqual(offs[3]["W"], 0.3746, delta=1e-3)
        self.assertEqual([round(v, 4) for v in e["TireSkidWidth"]["Data"]], [0.2656] * 4)
        # second test-copy race fixes: wheel height (FECompressions, RideHeight, WheelWell), turning, tensor
        self.assertEqual([round(v, 4) for v in e["FECompressions"]["Data"]], [0.2816] * 2)
        self.assertAlmostEqual(e["RideHeight"], -2.29, places=4)
        self.assertEqual(e["WheelWell"], 30.5)
        self.assertEqual(d["TENSOR_SCALE"]["Y"], 2)
        # third race: YAW_SPEED 0.5 and YAW_CONTROL lowered (thar_db.YAW_SPEED / YAW_CONTROL)
        yaw_control = {"thar": (0.2, 0.4, 0.45, 0.5), "thar_top": (0.3, 0.5, 0.7, 0.8)}
        for stage in ("thar", "thar_top"):
            self.assertAlmostEqual(coll("tires", stage)["Data"]["YAW_SPEED"], 0.5, places=5)
            self.assertEqual(coll("tires", stage)["Data"]["STEERING"], 1)
            self.assertEqual([round(v, 4) for v in coll("tires", stage)["Data"]["YAW_CONTROL"]["Data"]],
                             list(yaw_control[stage]))
        # no link with an empty class anywhere in the Thar's entries (the Challenger's hidden-car lesson)
        def links(v):
            if isinstance(v, dict):
                if "ClassKey" in v and "CollectionKey" in v:
                    yield v
                for x in v.values():
                    yield from links(x)
            elif isinstance(v, list):
                for x in v:
                    yield from links(x)
        for cls, name in (("pvehicle", "thar"), ("ecar", "thar"), ("frontend", "thar"), ("frontend", "mahindra")):
            bad = [l for l in links(coll(cls, name)["Data"]) if l["CollectionKey"] not in ("", None) and not l["ClassKey"]]
            self.assertEqual(bad, [], (cls, name))

    def test_rehearsal_strings(self):
        key = struct.pack("<I", bstringhash("CARNAME_MAHINDRA_THAR"))
        for lang in LANGUAGES:
            data = read(self.path("LANGUAGES/%s.bin" % lang))
            self.assertIn(key, data, lang)
            self.assertIn(b"Mahindra Thar", data, lang)
        self.assertIn(b"CARNAME_MAHINDRA_THAR", read(self.path("LANGUAGES/Labels.bin")))

    def test_rehearsal_logo(self):
        top = read_chunks(read(self.path("FRONTEND/FrontB.lzc")))
        hashes = set()
        for c in find(top, 0x33310002):
            hashes |= {struct.unpack_from("<I", c.data, k)[0] for k in range(0, len(c.data), 8)}
        self.assertIn(bstringhash("CARSELECT_MANUFACTURER_MAHINDRA"), hashes)
        self.assertIn(bstringhash("SECONDARY_LOGO_THAR"), hashes)
        self.assertIn(bstringhash("CARSELECT_MANUFACTURER_BUGATTI"), hashes)  # the existing ones stay

    def test_rehearsal_files(self):
        self.assertEqual(sha(self.path("CARS/THAR/GEOMETRY.BIN")), sha(os.path.join(OUT, "GEOMETRY.BIN")))
        self.assertEqual(sha(self.path("CARS/THAR/TEXTURES.BIN")), sha(os.path.join(OUT, "TEXTURES.BIN")))
        self.assertEqual(sha(self.path("scripts/UnlimiterData/THAR.ini")), sha(os.path.join(PKG, "THAR.ini")))
        # what changed is what the plan expects, and nothing outside the backed-up folders
        changed = set(self.result["changed"])
        self.assertTrue({"GLOBAL/GlobalB.lzc", "GLOBAL/attributes.bin", "FRONTEND/FrontB.lzc"} <= changed, changed)
        import json
        rec = json.load(open(os.path.join(self.record, "record.json")))
        self.assertEqual(rec["not_undoable"], [])
        self.assertEqual(sorted(rec["created"]), ["CARS/THAR/GEOMETRY.BIN", "CARS/THAR/TEXTURES.BIN",
                                                  "scripts/UnlimiterData/THAR.ini"])

    def test_rehearsal_zz_undo(self):
        """(Runs last.) install.py undo restores every file byte for byte and removes the new ones."""
        import install
        install.undo(self.mini, self.record)
        self.assertEqual(tree(self.mini), self.before)
        self.assertFalse(os.path.exists(self.path("CARS/THAR")))


if __name__ == "__main__":
    unittest.main()
