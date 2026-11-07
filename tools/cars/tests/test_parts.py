"""Tests for tools/cars/parts.py. Run: python tools/cars/tests/test_parts.py

Uses the user's game files (not in the repo): the test copy's GLOBAL\\GlobalB.lzc and the profile backup.
"""
import importlib.util
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
spec = importlib.util.spec_from_file_location("parts", os.path.join(HERE, "..", "parts.py"))
parts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parts)

# the game's GlobalB.lzc as it was before any car (frozen in the Unlimiter's install record)
GLOBALB = os.path.join(ROOT, "telemetry", "cars-records", "game", "unlimiter-20261031", "before", "GLOBAL", "GlobalB.lzc")
PROFILE = os.path.join(ROOT, "telemetry", "profile-backups", "player-20261031", "player")


class Parts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = open(GLOBALB, "rb").read()
        cls.list = parts.read_parts_bytes(cls.data)

    def test_reads_every_part_in_model_order(self):
        self.assertEqual(len(self.list), 11925)
        self.assertEqual([p.index for p in self.list], list(range(11925)))
        models = [p.model for p in self.list]
        self.assertEqual(models, sorted(models))

    def test_user_indices_belong_to_their_car(self):
        # The known answer: each customisation record in the save installs mostly parts of one car model (its car);
        # a list read wrongly, or indices that are not positions in it, would scatter them.
        used = parts.save_indices(PROFILE)
        self.assertGreater(len(used), 1000)
        by_record = {}
        for key, custom, slot, index in used:
            by_record.setdefault(custom, []).append(self.list[index].model)
        for custom, models in by_record.items():
            top = max(set(models), key=models.count)
            self.assertGreaterEqual(models.count(top) / len(models), 0.7, "customisation %d" % custom)

    def test_diff_same_on_identical_files(self):
        self.assertEqual(parts.diff(self.list, self.list, parts.save_indices(PROFILE)), [])

    def test_diff_reports_shift(self):
        # One part inserted at position 5: every used index from 5 on now names another part.
        shifted = parts.read_parts_bytes(parts.insert_part_for_test(self.data, 5))
        changed = parts.diff(self.list, shifted, parts.save_indices(PROFILE))
        used = {i for _, _, _, i in parts.save_indices(PROFILE)}
        self.assertEqual({c[0] for c in changed}, {i for i in used if i >= 5})


if __name__ == "__main__":
    sys.exit(unittest.main())
