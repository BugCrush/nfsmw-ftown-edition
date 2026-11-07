"""Tests for tools/cars/make-test-copy.py. Run: python tools/cars/tests/test_make_test_copy.py"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mtc", os.path.join(HERE, "..", "make-test-copy.py"))
mtc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mtc)


class MakeTestCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "game")
        os.makedirs(os.path.join(self.src, "GLOBAL"))
        for rel, data in (("speed.exe", b"exe"), ("GLOBAL/a.bin", b"\x00" * 1000)):
            with open(os.path.join(self.src, rel), "wb") as f:
                f.write(data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_and_verifies_every_file(self):
        dest = os.path.join(self.tmp.name, "copy")
        n = mtc.make_copy(self.src, dest, game_running=lambda: False)
        self.assertEqual(n, 2)
        with open(os.path.join(dest, "GLOBAL", "a.bin"), "rb") as f:
            self.assertEqual(f.read(), b"\x00" * 1000)

    def test_refuses_existing_destination(self):
        dest = os.path.join(self.tmp.name, "copy")
        os.makedirs(dest)
        with self.assertRaises(mtc.Refused):
            mtc.make_copy(self.src, dest, game_running=lambda: False)

    def test_refuses_while_game_runs(self):
        with self.assertRaises(mtc.Refused):
            mtc.make_copy(self.src, os.path.join(self.tmp.name, "copy"), game_running=lambda: True)


if __name__ == "__main__":
    sys.exit(unittest.main())
