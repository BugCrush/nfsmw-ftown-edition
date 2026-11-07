"""The Thar's install package: python -m unittest discover -s tools/carbuild/tests -p test_thar_package.py

tools/cars/packages/thar/ (our Binarius launcher and scripts, the parts-list and car-type makers, the Unlimiter file)
and its cars.yaml entry. Builds the package's generated files into a temporary folder; reads the templates and the
game's cars read-only.
"""
import os
import re
import struct
import sys
import tempfile
import unittest

from common import CARS, REPO, need, read
from chunks import bstringhash

PKG = os.path.join(REPO, "tools", "cars", "packages", "thar")
DL = os.path.join(REPO, ".superpowers", "downloads", "cars")
PARTS_TEMPLATE = os.path.join(DL, "3803", "files", "Longnose Cab Semi Truck (Addon)", "Binary Files", "_CarParts",
                              "DBModelParts.bin")
CARTYPE_TEMPLATE = os.path.join(DL, "5882", "files", "Binary Files", "_CarParts", "CarTypeInfos.bin")
THAR_GEOMETRY = os.path.join(REPO, ".superpowers", "carbuild", "thar", "out", "GEOMETRY.BIN")
LANGUAGES = ("Danish", "Dutch", "English", "Finnish", "French", "German", "Italian", "Largest", "Polish", "Spanish",
             "Swedish")


def load(name):
    sys.path.insert(0, PKG)
    try:
        return __import__(name)
    finally:
        sys.path.remove(PKG)


def is_crlf(path):
    d = read(path)
    return d.count(b"\n") > 0 and d.count(b"\r\n") == d.count(b"\n")


class PartsTest(unittest.TestCase):
    def test_parts_template(self):
        need(self, PARTS_TEMPLATE)
        make_parts = load("make_parts")
        src = read(PARTS_TEMPLATE)
        out = make_parts.make(src)
        names = set(re.findall(rb"[A-Z][A-Z0-9_]{2,}", out[36:]))
        self.assertFalse([n for n in names if b"LONGNOSECAB" in n or b"GTI" in n])
        self.assertIn(b"THAR_BODY_KIT00", out)
        self.assertIn(b"THAR_CV\0", out)
        for k in range(1, 6):
            self.assertIn(b"THAR_0%d_CV\0" % k, out)
        # length: each LONGNOSECAB (11) -> THAR (4) shortens by 7; each GTI (3) -> THAR (4) in a _CV label lengthens by 1
        n_truck = src[36:].count(b"LONGNOSECAB")
        n_cv = len(re.findall(rb"GTI(_0\d)?_CV", src[36:]))
        self.assertEqual(n_cv, 6)
        self.assertEqual(len(out), len(src) - 7 * n_truck + n_cv)
        # Binary's header: the four size fields follow the new length
        for at, less in {4: 8, 16: 20, 28: 36, 32: 20}.items():
            self.assertEqual(struct.unpack_from("<I", out, at)[0], len(out) - less)
        self.assertEqual(out[:4], b"gMpB")
        self.assertEqual(out[8:16], src[8:16])
        self.assertEqual(out[20:28], src[20:28])


class CarTypeTest(unittest.TestCase):
    def test_cartype(self):
        need(self, CARTYPE_TEMPLATE)
        make_cartype = load("make_cartype")
        src = read(CARTYPE_TEMPLATE)
        out = make_cartype.make(src)
        body = out[36:]
        self.assertTrue(body.startswith(b"THAR\0MAHINDRA\0"), body[:20])
        self.assertEqual(len(out), len(src) - len(b"TOMAHAWK") + len(b"THAR") - len(b"DODGE") + len(b"MAHINDRA"))
        for at, less in {4: 8, 16: 20, 28: 36, 32: 20}.items():
            self.assertEqual(struct.unpack_from("<I", out, at)[0], len(out) - less)
        # Skinnable: the byte before the 4-byte DefaultBasePaint at the end (the truck's reads 0 there, the
        # Tomahawk's and the Chiron's 1)
        self.assertEqual(out[-5], 1)
        # usage type: the int just before CarMemTypeHash = bStringHash("Racing")
        at = out.index(struct.pack("<I", bstringhash("Racing")))
        self.assertEqual(struct.unpack_from("<i", out, at - 4)[0], 0)
        # everything after the names is the Tomahawk's but the default paint (the last four bytes)
        self.assertEqual(body[len(b"THAR\0MAHINDRA\0"):-4], src[36 + len(b"TOMAHAWK\0DODGE\0"):-4])

    def test_default_paint_is_chrome(self):
        """The user (2026-11-02): "make the default colour chrome". DefaultBasePaint (the record's last four bytes,
        which the Unlimiter's RideInfo_SetStockParts puts on BASE_PAINT) is CHROME01_PAINT: the game's PAINT part
        with brand PEARL (the paint shop's Pearl group), light material CUSTOMPAINT_11 and colour 220/220/220, the
        plain silver of the ten chromes (the Tomahawk's was GLOSS_L1_COLOR21)."""
        need(self, CARTYPE_TEMPLATE)
        out = load("make_cartype").make(read(CARTYPE_TEMPLATE))
        self.assertEqual(struct.unpack_from("<I", out, len(out) - 4)[0], bstringhash("CHROME01_PAINT"))
        self.assertEqual(bstringhash("CHROME01_PAINT"), 0x8F2E74B9)


class CollisionTest(unittest.TestCase):
    def test_collision_donor_size(self):
        need(self, THAR_GEOMETRY)
        import donor
        target = donor.body_box(THAR_GEOMETRY, "THAR")
        boxes = {}
        for car in donor.STOCK_RACERS:
            p = os.path.join(CARS, car, "GEOMETRY.BIN")
            if os.path.exists(p):
                boxes[car] = donor.body_box(p, car)
        if len(boxes) < 30:
            self.skipTest("game cars missing")
        best, err = donor.best(target, boxes)
        self.assertLessEqual(err, 0.15, (best, err, boxes[best], target))
        line = [l for l in read(os.path.join(PKG, "install.end")).decode().splitlines() if l.startswith("copy_collection")]
        self.assertEqual(line, ["copy_collection GLOBAL\\GLOBALB.LZC Collisions %s THAR" % best])


class ScriptsTest(unittest.TestCase):
    def test_install_end(self):
        path = os.path.join(PKG, "install.end")
        self.assertTrue(is_crlf(path))
        text = read(path).decode()
        lines = [l for l in text.splitlines() if l and not l.startswith("//")]
        self.assertEqual(lines[0], "[VERSN2]")
        self.assertIn("unlock_memory all", lines)
        self.assertIn('create_folder absolute "CARS\\THAR"', lines)
        out = "..\\..\\..\\..\\.superpowers\\carbuild\\thar\\out\\"
        pkg = "..\\..\\..\\..\\.superpowers\\carbuild\\thar\\package\\"
        self.assertIn('move_file override relative absolute "%sGEOMETRY.BIN" "CARS\\THAR\\GEOMETRY.BIN"' % out, lines)
        self.assertIn('move_file override relative absolute "%sTEXTURES.BIN" "CARS\\THAR\\TEXTURES.BIN"' % out, lines)
        self.assertIn('import override GLOBAL\\GLOBALB.LZC DBModelParts "%sDBModelParts.bin"' % pkg, lines)
        self.assertIn('import override GLOBAL\\GLOBALB.LZC CarTypeInfos "%sCarTypeInfos.bin"' % pkg, lines)
        self.assertIn('bind_textures synchronize FrontEnd\\FrontB.lzc TPKBlocks FRONTENDTEXTURES "%slogo"' % pkg, lines)
        self.assertEqual(lines[-1], "append strings.end")

    def test_strings_end(self):
        path = os.path.join(PKG, "strings.end")
        self.assertTrue(is_crlf(path))
        text = read(path).decode()
        for lang in LANGUAGES:
            self.assertIn('add_or_update_string Languages\\%s.bin STRBlocks GLOBAL AUTO CARNAME_MAHINDRA_THAR '
                          '"Mahindra Thar"' % lang, text)
        self.assertIn('add_or_update_string Languages\\Labels.bin STRBlocks GLOBAL AUTO CARNAME_MAHINDRA_THAR '
                      '"CARNAME_MAHINDRA_THAR"', text)

    def test_launcher(self):
        path = os.path.join(PKG, "launcher.end")
        self.assertTrue(is_crlf(path))
        text = read(path).decode()
        self.assertIn('"Usage": "User"', text)
        self.assertIn('"Endscript": "install.end"', text)
        self.assertIn('"GLOBAL\\GLOBALB.LZC"', text)
        self.assertIn('"FRONTEND\\FRONTB.LZC"', text)
        self.assertIn('"LANGUAGES\\Labels.bin"', text)

    def test_unlimiter_file(self):
        """Paint and window tint only, one body kit, nothing random the model lacks (cars-notes: the truck)."""
        import configparser
        path = os.path.join(PKG, "THAR.ini")
        self.assertTrue(is_crlf(path))
        cp = configparser.ConfigParser(inline_comment_prefixes=("//",), interpolation=None, strict=False)
        cp.optionxform = str
        raw = read(path).decode("utf-8")
        # section headers carry // comments too
        cp.read_string(re.sub(r"^(\[[A-Za-z]+\]).*$", r"\1", raw, flags=re.M))
        allowed = {"Paint", "WindowTint"}
        for key, value in cp["Parts"].items():
            self.assertEqual(value.strip(), "0", key)
        for key, value in cp["Visual"].items():
            self.assertEqual(value.strip(), "1" if key in allowed else "0", key)
        self.assertEqual(cp["RandomParts"]["CustomRandomParts"].strip(), "1")
        for key, value in cp["RandomParts"].items():
            if key in ("ForceCustomizationLevel", "CustomRandomParts"):
                continue
            self.assertEqual(value.strip(), "1" if key in allowed else "0", key)
        self.assertEqual(cp["Main"]["ForceLODA"].strip(), "0")

    def test_ini_shows_interior_and_driver(self):
        """Thar fix 2: the Unlimiter's `[Parts] Interior` and `[Visual] Driver` only decide whether the customisation
        menu offers the INTERIOR / DRIVER slots and whether they are randomised (Unlimiter CustomizeSub.h, RideInfo.h);
        drawing goes by the parts list. The GTI, which draws its interior and driver, has no file of its own and uses
        _General.ini: the Thar's file sets these keys as that one does."""
        general = None
        game = os.path.join(os.path.dirname(CARS), "scripts", "UnlimiterData", "_General.ini")
        if not os.path.exists(game):
            self.skipTest("the game's _General.ini is missing")
        if os.path.exists(os.path.join(os.path.dirname(game), "GTI.ini")):
            self.fail("the GTI has its own Unlimiter file now: compare with that")

        def keys(path):
            out, section = {}, None
            for line in read(path).decode("utf-8", "replace").splitlines():
                m = re.match(r"\s*\[([A-Za-z]+)\]", line)
                if m:
                    section = m.group(1)
                    continue
                m = re.match(r"\s*([A-Za-z0-9]+)\s*=\s*([-0-9.]*)", line)
                if m and section and (section, m.group(1)) not in out:
                    out[(section, m.group(1))] = m.group(2)
            return out
        general, mine = keys(game), keys(os.path.join(PKG, "THAR.ini"))
        for key in (("Parts", "Interior"), ("Visual", "Driver")):
            self.assertIn(key, general)
            self.assertEqual(mine[key], general[key], key)
        self.assertEqual(mine[("RandomParts", "Interior")], "0")

    def test_cars_yaml_entry(self):
        import yaml
        cfg = yaml.safe_load(open(os.path.join(REPO, "tools", "cars", "cars.yaml"), encoding="utf-8"))
        e = cfg["thar"]
        self.assertEqual(e["source"], "tools/cars/packages/thar")
        self.assertEqual(e["binarius"], {"launcher": "launcher.end", "base": ".", "script": "install.end"})
        self.assertEqual(e["vlt"], {"script": "thar.nfsms"})
        self.assertEqual(e["frontend"], "thar")
        self.assertEqual(e["overrides"], {"UnlockedAt": 16, "IsCustomizable": "True"})
        self.assertEqual(e["copies"], [["THAR.ini", "scripts/UnlimiterData/THAR.ini"]])


class BuildTest(unittest.TestCase):
    def test_build_writes_the_package_files(self):
        need(self, PARTS_TEMPLATE, CARTYPE_TEMPLATE)
        build = load("build")
        out = tempfile.mkdtemp(prefix="thar-pkg-")
        files = build.build(out)
        self.assertEqual(sorted(os.path.relpath(f, out).replace(os.sep, "/") for f in files),
                         ["CarTypeInfos.bin", "DBModelParts.bin", "logo/CARSELECT_MANUFACTURER_MAHINDRA.dds",
                          "logo/SECONDARY_LOGO_THAR.dds"])
        # the logo folder holds the DDS files only: bind_textures takes every file in it
        self.assertEqual(sorted(os.listdir(os.path.join(out, "logo"))),
                         ["CARSELECT_MANUFACTURER_MAHINDRA.dds", "SECONDARY_LOGO_THAR.dds"])


if __name__ == "__main__":
    unittest.main()
