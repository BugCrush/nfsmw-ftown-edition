"""Tests for tools/cars/extract_car.py (Nikki-based export of one car's entries). Run:
python tools/cars/tests/test_extract_car.py

Known answer, a round trip: the Challenger's entries exported from the test copy's GlobalB.lzc and imported with
Binarius into the GlobalB.lzc from before the Challenger's install (its install record) give the same part list for
the car as the test copy, and exporting again gives the same bytes. (The mod's own CarPart file is not byte-equal:
it was made by an older Binary that also keeps part labels as text; ours holds them as hashes, which is all the
game reads.)
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extract_car, install, parts = _load("extract_car"), _load("install"), _load("parts")

TEST_COPY = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - cars test")
BEFORE = os.path.join(ROOT, "telemetry", "cars-records", "test-copy", "challenger71-20261031", "before", "GLOBAL",
                      "GlobalB.lzc")
LAUNCHER = ('[VERSN1]\n\n{\n  "Usage": "User",\n  "Game": "MostWanted",\n  "Directory": "",\n'
            '  "Endscript": "import.end",\n  "Files": [\n    "GLOBAL\\GLOBALB.LZC"\n  ],\n  "Links": [\n  ]\n}\n')


def model_parts(globalb, model_hash):
    return [(p.name_hash, p.name) for p in parts.read_parts(globalb) if p.model_hash == model_hash]


class ExtractCar(unittest.TestCase):
    def test_extract_roundtrip(self):
        tmp = tempfile.mkdtemp()
        first = extract_car.extract_car(os.path.join(TEST_COPY, "GLOBAL", "GlobalB.lzc"), "CHALLENGER71",
                                        os.path.join(tmp, "first"), managers=("DBModelParts", "Collisions"))
        game = os.path.join(tmp, "game")
        os.makedirs(os.path.join(game, "GLOBAL"))
        shutil.copy(BEFORE, os.path.join(game, "GLOBAL", "GlobalB.lzc"))
        mod = os.path.join(tmp, "mod")
        os.makedirs(mod)
        for m, p in first.items():
            shutil.copy(p, os.path.join(mod, m + ".bin"))
        with open(os.path.join(mod, "launcher.end"), "w") as f:
            f.write(LAUNCHER)
        with open(os.path.join(mod, "import.end"), "w") as f:
            f.write("[VERSN2]\nimport override GLOBAL\\GLOBALB.LZC DBModelParts DBModelParts.bin\n"
                    "import override GLOBAL\\GLOBALB.LZC Collisions Collisions.bin\n")
        install._run_binarius({"source": mod, "binarius": {"launcher": "launcher.end", "base": ".",
                                                            "script": "import.end"}}, game)
        before = parts.read_parts(BEFORE)
        ours = parts.read_parts(os.path.join(game, "GLOBAL", "GlobalB.lzc"))
        model = ours[-1].model_hash  # the imported car is appended after every model the file had
        self.assertNotIn(model, {p.model_hash for p in before})
        self.assertEqual(ours[:len(before)], before)
        self.assertEqual(model_parts(os.path.join(game, "GLOBAL", "GlobalB.lzc"), model),
                         model_parts(os.path.join(TEST_COPY, "GLOBAL", "GlobalB.lzc"), model))
        self.assertGreater(len(model_parts(os.path.join(TEST_COPY, "GLOBAL", "GlobalB.lzc"), model)), 100)
        again = extract_car.extract_car(os.path.join(game, "GLOBAL", "GlobalB.lzc"), "CHALLENGER71",
                                        os.path.join(tmp, "again"), managers=("DBModelParts", "Collisions"))
        # The re-imported car is named by its hash (no name dictionary here): CHALLENGER71 -> 0x3C21C0BC (parts) and
        # 0x3A3A461D (collision, keyed by the database hash). The name sits at byte 36 after a size field; every
        # byte after it must be the same.
        for m, new_name in (("DBModelParts", b"0x3C21C0BC"), ("Collisions", b"0x3A3A461D")):
            a, b = open(first[m], "rb").read(), open(again[m], "rb").read()
            self.assertEqual(a[36:36 + 12], b"CHALLENGER71", m)
            self.assertEqual(b[36:36 + len(new_name)], new_name, m)
            self.assertEqual(a[36 + 12:], b[36 + len(new_name):], m)

    def test_missing_collection_is_an_error(self):
        with self.assertRaises(extract_car.Failed):
            extract_car.extract_car(os.path.join(TEST_COPY, "GLOBAL", "GlobalB.lzc"), "NOSUCHCAR",
                                    tempfile.mkdtemp(), managers=("DBModelParts",))


if __name__ == "__main__":
    sys.exit(unittest.main())
