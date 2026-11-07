"""JDLZ: python -m unittest discover -s tools/carbuild/tests -p test_jdlz.py"""
import os
import struct
import unittest

from common import TRUCK_GEOMETRY, need, read
import jdlz


class JdlzTests(unittest.TestCase):
    def test_decompress_truck_body(self):  # the Longnose Cab's body block starts at 0x2E00
        need(self, TRUCK_GEOMETRY)
        blob = read(TRUCK_GEOMETRY)[0x2E00:]
        out = jdlz.decompress(blob)
        self.assertEqual(len(out), 101728)
        self.assertEqual(struct.unpack_from("<I", out, 0)[0], 0x80134010)

    def test_literal_compress_roundtrip(self):
        for data in (b"", b"x", bytes(range(256)) * 37, os.urandom(10001)):
            self.assertEqual(jdlz.decompress(jdlz.compress_literal(data)), data)

    def test_literal_header(self):
        blob = jdlz.compress_literal(b"abcdefghij")
        self.assertEqual(blob[:8], b"JDLZ\x02\x10\x00\x00")
        self.assertEqual(struct.unpack_from("<II", blob, 8), (10, len(blob)))

    def test_rejects_non_jdlz(self):
        with self.assertRaises(ValueError):
            jdlz.decompress(b"XXXX" + bytes(12))


if __name__ == "__main__":
    unittest.main()
