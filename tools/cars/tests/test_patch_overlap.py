"""Tests for tools/cars/patch-overlap.py. Run: python tools/cars/tests/test_patch_overlap.py"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("po", os.path.join(HERE, "..", "patch-overlap.py"))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

BEFORE = "RANGE start=0x500000 len=5\nOWNER start=0x500000 owner=X360Stuff.asi+0x10\n" \
         "RANGE start=0x600000 len=6\nOWNER start=0x600000 owner=-\n"


class Overlap(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_range_taken_from_another_module_is_reported(self):
        after = self.write("RANGE start=0x500002 len=5\nOWNER start=0x500002 owner=NFSMWUnlimiter.asi+0x20\n")
        taken, fresh = po.overlaps(po.ranges(self.write(BEFORE)), po.ranges(after), "NFSMWUnlimiter.asi")
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0][1][0][2], "X360Stuff.asi")

    def test_new_range_is_not_taken(self):
        after = self.write("RANGE start=0x700000 len=5\nOWNER start=0x700000 owner=NFSMWUnlimiter.asi+0x20\n"
                           "RANGE start=0x600000 len=6\nOWNER start=0x600000 owner=NFSMWUnlimiter.asi+0x30\n")
        taken, fresh = po.overlaps(po.ranges(self.write(BEFORE)), po.ranges(after), "NFSMWUnlimiter.asi")
        # 0x600000 was changed before by something PatchMap could not name ("-"): reported too, so a person looks.
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0][1][0][2], "-")
        self.assertEqual(fresh, 1)


    def test_a_range_whose_extent_changed_is_reported_whoever_owns_it(self):
        # PatchMap names an owner from the first jump in a range: a later module overwriting the new one's patch keeps
        # the later owner in both logs, but the range's extent changes
        before = self.write("RANGE start=0x500000 len=5\nOWNER start=0x500000 owner=X360Stuff.asi+0x10\n")
        after = self.write("RANGE start=0x4FFFFE len=9\nOWNER start=0x4FFFFE owner=X360Stuff.asi+0x10\n")
        changed = po.changed_extents(po.ranges(before), po.ranges(after))
        self.assertEqual(changed, [((0x4FFFFE, 9, "X360Stuff.asi"), [(0x500000, 5, "X360Stuff.asi")])])

    def test_unchanged_ranges_are_not_reported(self):
        before = self.write(BEFORE)
        self.assertEqual(po.changed_extents(po.ranges(before), po.ranges(before)), [])


if __name__ == "__main__":
    sys.exit(unittest.main())
