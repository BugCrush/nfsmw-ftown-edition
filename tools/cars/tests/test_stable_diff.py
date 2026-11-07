"""Tests for tools/cars/stable-diff.py. Run: python tools/cars/tests/test_stable_diff.py"""
import importlib.util
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sd", os.path.join(HERE, "..", "stable-diff.py"))
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)


def blank():
    img = bytearray(0x8CC8)
    for i in range(200):
        struct.pack_into("<I", img, i * 0x14, 0xFFFFFFFF)
    for i in range(75):
        img[0xFA0 + i * 0x198 + 0x194] = 0xFF
    return img


def put(img, slot, vkey, bits, custom=0xFF):
    struct.pack_into("<IIIIBB", img, slot * 0x14, slot, vkey + 1, vkey, bits, custom, 0xFF)
    if custom != 0xFF:
        img[0xFA0 + custom * 0x198 + 0x194] = custom


class StableDiff(unittest.TestCase):
    def test_identical_images_have_no_differences(self):
        a = blank()
        put(a, 0, 0xA, 1)
        self.assertEqual(sd.differences(bytes(a), bytes(a)), [])

    def test_reports_car_only_in_one_and_changed_bits(self):
        a, b = blank(), blank()
        put(a, 0, 0xA, 1)
        put(b, 0, 0xA, 9)
        put(b, 1, 0xB, 1)
        diffs = sd.differences(bytes(a), bytes(b))
        self.assertIn("car 0x0000000A: filter bits 0x00000001 -> 0x00000009", diffs)
        self.assertIn("car 0x0000000B: only in second (slot 1)", diffs)

    def test_reports_customisation_bytes_of_the_same_car(self):
        a, b = blank(), blank()
        put(a, 0, 0xA, 8, custom=0)
        put(b, 0, 0xA, 8, custom=0)
        b[0xFA0 + 0x10] = 7
        diffs = sd.differences(bytes(a), bytes(b))
        self.assertEqual(diffs, ["car 0x0000000A: customisation differs at +0x10 (1 bytes)"])

    def test_reports_slot_order(self):
        a, b = blank(), blank()
        put(a, 0, 0xA, 1)
        put(a, 1, 0xB, 1)
        put(b, 0, 0xB, 1)
        put(b, 1, 0xA, 1)
        self.assertIn("order of cars differs (first at slot 0)", sd.differences(bytes(a), bytes(b)))


if __name__ == "__main__":
    sys.exit(unittest.main())
