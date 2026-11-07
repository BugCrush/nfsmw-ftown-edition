"""Tests for tools/cars/install.py. Run: python tools/cars/tests/test_install.py

test_overrides_applied runs the real Attribulator on copies of the test copy's database files (about a minute).
"""
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "tools", "x360"))
spec = importlib.util.spec_from_file_location("install", os.path.join(HERE, "..", "install.py"))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
import part1  # noqa: E402

TEST_COPY = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - cars test")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        self.src = os.path.join(self.tmp, "mod")
        for d in ("GLOBAL", "FRONTEND", "LANGUAGES", "scripts"):
            os.makedirs(os.path.join(self.game, d))
        with open(os.path.join(self.game, "speed.exe"), "wb") as f:
            f.write(b"exe")
        with open(os.path.join(self.game, "scripts", "a.ini"), "w") as f:
            f.write("[A]\nx = 1\n")
        os.makedirs(os.path.join(self.src, "CARS", "TESTCAR"))
        with open(os.path.join(self.src, "CARS", "TESTCAR", "GEOMETRY.BIN"), "wb") as f:
            f.write(b"geo")
        with open(os.path.join(self.src, "a.ini"), "w") as f:
            f.write("[A]\nx = 2\n")
        self.car = {"source": self.src, "copies": [["CARS/TESTCAR/GEOMETRY.BIN", "CARS/TESTCAR/GEOMETRY.BIN"],
                                                   ["a.ini", "scripts/a.ini"]]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refuses_while_game_runs(self):
        with self.assertRaises(install.Refused):
            install.install("testcar", self.car, self.game, os.path.join(self.tmp, "rec"), game_running=lambda: True)

    def test_refuses_chiron_first_mod_paths(self):
        car = dict(self.car, copies=[["First mod/GLOBAL/GlobalB.lzc", "GLOBAL/GlobalB.lzc"]])
        with self.assertRaises(install.Refused):
            install.install("testcar", car, self.game, os.path.join(self.tmp, "rec"), game_running=lambda: False)

    def test_refuses_used_record_folder(self):
        rec = os.path.join(self.tmp, "rec")
        os.makedirs(rec)
        with self.assertRaises(install.Refused):
            install.install("testcar", self.car, self.game, rec, game_running=lambda: False)

    def test_undo_restores_hashes(self):
        before = sha(os.path.join(self.game, "scripts", "a.ini"))
        rec = os.path.join(self.tmp, "rec")
        r = install.install("testcar", self.car, self.game, rec, game_running=lambda: False)
        self.assertEqual(sorted(r["changed"]), ["scripts/a.ini"])
        self.assertEqual(sorted(r["created"]), ["CARS/TESTCAR/GEOMETRY.BIN"])
        self.assertNotEqual(sha(os.path.join(self.game, "scripts", "a.ini")), before)
        install.undo(self.game, rec, game_running=lambda: False)
        self.assertEqual(sha(os.path.join(self.game, "scripts", "a.ini")), before)
        self.assertFalse(os.path.exists(os.path.join(self.game, "CARS", "TESTCAR")))

    def test_undo_refuses_a_file_changed_since(self):
        rec = os.path.join(self.tmp, "rec")
        install.install("testcar", self.car, self.game, rec, game_running=lambda: False)
        with open(os.path.join(self.game, "scripts", "a.ini"), "a") as f:
            f.write("y = 3\n")
        with self.assertRaises(install.Refused):
            install.undo(self.game, rec, game_running=lambda: False)

    def test_skip_classes_leaves_those_lines_out(self):
        lines = ["game MW", "update_field light_flares_cg traffic_light ZBias 0.4",
                 "update_field frontend angle_x cam_fov 1", "add_node light_flares_cg a b"]
        self.assertEqual(install._skip_classes(lines, ["light_flares_cg"]),
                         ["game MW", "update_field frontend angle_x cam_fov 1"])

    def test_launcher_without_version_line_gets_one(self):
        text = '{\r\n  "Usage": "User",\r\n  "Directory": " ",\r\n}'
        out = install._modder_launcher(text, "D:/game")
        self.assertTrue(out.startswith("[VERSN1]"))
        self.assertIn('"Usage": "Modder"', out)
        self.assertIn('"Directory": "D:/game"', out)
        self.assertEqual(install._modder_launcher("[VERSN1]\n\n" + text, "D:/game").count("[VERSN1]"), 1)

    def test_relative_record_path_is_made_absolute(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            r = install.install("testcar", self.car, self.game, "rec", game_running=lambda: False)
            m = install.json.load(open(os.path.join(self.tmp, "rec", "record.json")))
            self.assertTrue(os.path.isabs(m["record"]))
            install.undo(self.game, "rec", game_running=lambda: False)
        finally:
            os.chdir(cwd)

    def test_launcher_loses_database_links(self):
        text = ('[VERSN1]\n\n{\n  "Usage": "User",\n  "Game": "MostWanted",\n  "Directory": " ",\n'
                '  "Endscript": "x.end",\n  "Files": [\n    "GLOBAL\\GLOBALB.LZC",\n  ],\n  "Links": [\n'
                '    {\n      "LoadType": "Attributes",\n      "PathType": "Absolute",\n      "File": "GLOBAL\\attributes.bin"\n    },\n'
                '    {\n      "LoadType": "FeAttrib",\n      "PathType": "Absolute",\n      "File": "GLOBAL\\fe_attrib.bin"\n    },\n'
                '    {\n      "LoadType": "Labels",\n      "PathType": "Absolute",\n      "File": "LANGUAGES\\Labels.bin"\n    }\n'
                '  ]\n}')
        out = install._modder_launcher(text, "D:/game")
        self.assertNotIn("attributes.bin", out)
        self.assertNotIn("fe_attrib.bin", out)
        self.assertIn('"File": "LANGUAGES\\Labels.bin"', out)
        self.assertIn('"GLOBAL\\GLOBALB.LZC"', out)

    def test_launcher_keeps_only_files_the_script_names(self):
        text = ('[VERSN1]\n\n{\n  "Usage": "User",\n  "Directory": " ",\n  "Files": [\n'
                '    "GLOBAL\\GLOBALA.BUN",\n    "GLOBAL\\GLOBALB.LZC",\n    "LANGUAGES\\ENGLISH.BIN",\n'
                '    "FRONTEND\\FRONTA.BUN",\n  ],\n  "Links": [\n  ]\n}')
        script = ["[VERSN2]", "import override GLOBAL\\GlobalB.lzc DBModelParts x.bin",
                  "add_string LANGUAGES\\ENGLISH.BIN STRBlocks GLOBAL 0x1 A \"a\""]
        out = install._modder_launcher(text, "D:/game", script)
        self.assertIn('"GLOBAL\\GLOBALB.LZC"', out)
        self.assertIn('"LANGUAGES\\ENGLISH.BIN"', out)
        self.assertNotIn("GLOBALA.BUN", out)
        self.assertNotIn("FRONTA.BUN", out)

    def test_a_file_in_the_cars_root_is_recorded_and_undone(self):
        # The Unlimiter's script rewrites CARS\TEXTURES.BIN (the shared car textures); car folders are new files
        os.makedirs(os.path.join(self.game, "CARS"), exist_ok=True)
        with open(os.path.join(self.game, "CARS", "TEXTURES.BIN"), "wb") as f:
            f.write(b"shared textures")
        before = sha(os.path.join(self.game, "CARS", "TEXTURES.BIN"))
        with open(os.path.join(self.src, "TEXTURES.BIN"), "wb") as f:
            f.write(b"shared textures + dummy skins")
        car = dict(self.car, copies=self.car["copies"] + [["TEXTURES.BIN", "CARS/TEXTURES.BIN"]])
        rec = os.path.join(self.tmp, "rec")
        r = install.install("testcar", car, self.game, rec, game_running=lambda: False)
        self.assertIn("CARS/TEXTURES.BIN", r["changed"])
        install.undo(self.game, rec, game_running=lambda: False)
        self.assertEqual(sha(os.path.join(self.game, "CARS", "TEXTURES.BIN")), before)

    def test_a_change_outside_the_backed_up_folders_fails_loudly(self):
        # Review item 6: a file the installer does not back up (here one in the game root, changed by a step that does
        # not name it beforehand, as a Binarius script would) changed: the install says which, and the record lists it
        # as not undoable
        with open(os.path.join(self.game, "root.ini"), "w") as f:
            f.write("[A]\na = 1\n")
        car = {"source": self.src, "ini": {"root.ini": {"A": {"a": "2"}}}}
        rec = os.path.join(self.tmp, "rec")
        with self.assertRaises(install.Failed) as e:
            install.install("testcar", car, self.game, rec, game_running=lambda: False)
        self.assertIn("root.ini", str(e.exception))
        m = install.json.load(open(os.path.join(rec, "record.json")))
        self.assertEqual(m["not_undoable"], ["root.ini"])

    def test_a_copy_over_an_existing_file_anywhere_is_recorded_and_undone(self):
        # Switching a car's vinyls overwrites CARS\<car>\VINYLS.BIN, a folder the installer does not watch: a copy's
        # existing destination is backed up first
        os.makedirs(os.path.join(self.game, "CARS", "TESTCAR"))
        with open(os.path.join(self.game, "CARS", "TESTCAR", "VINYLS.BIN"), "wb") as f:
            f.write(b"512x")
        before = sha(os.path.join(self.game, "CARS", "TESTCAR", "VINYLS.BIN"))
        with open(os.path.join(self.src, "VINYLS1024.BIN"), "wb") as f:
            f.write(b"1024x vinyls")
        car = {"source": self.src, "copies": [["VINYLS1024.BIN", "CARS/TESTCAR/VINYLS.BIN"]]}
        rec = os.path.join(self.tmp, "rec")
        r = install.install("testcar", car, self.game, rec, game_running=lambda: False)
        self.assertEqual(r["changed"], ["CARS/TESTCAR/VINYLS.BIN"])
        install.undo(self.game, rec, game_running=lambda: False)
        self.assertEqual(sha(os.path.join(self.game, "CARS", "TESTCAR", "VINYLS.BIN")), before)

    def test_overrides_applied(self):
        g = os.path.join(TEST_COPY, "GLOBAL")
        for name in os.listdir(g):
            if name.lower() in ("attributes.bin", "fe_attrib.bin", "gameplay.bin"):
                shutil.copy(os.path.join(g, name), os.path.join(self.game, "GLOBAL", name))
        with open(os.path.join(self.src, "car.nfsms"), "w") as f:
            f.write("game MW\nadd_node frontend dodge carstabletest\nupdate_field frontend carstabletest UnlockedAt 3\n")
        car = {"source": self.src, "vlt": {"script": "car.nfsms", "options": {}},
               "frontend": "carstabletest", "overrides": {"UnlockedAt": 16, "IsCustomizable": "true"}}
        r = install.install("testcar", car, self.game, os.path.join(self.tmp, "rec"), game_running=lambda: False)
        # only the frontend vault was edited: attributes.bin and gameplay.bin stay byte for byte
        self.assertEqual([c.lower() for c in r["changed"]], ["global/fe_attrib.bin"])
        out = part1.unpack(os.path.join(self.game, "GLOBAL"), os.path.join(self.tmp, "yml"))
        text = open(os.path.join(out, "main", "fe_attrib", "frontend", "frontend.yml"), encoding="utf-8").read()
        block = text[text.index("Name: carstabletest"):]
        block = block[:block.find("\n- ", 1) if "\n- " in block else len(block)]
        self.assertIn("UnlockedAt: 16", block)
        self.assertIn("IsCustomizable: true", block)


if __name__ == "__main__":
    sys.exit(unittest.main())
