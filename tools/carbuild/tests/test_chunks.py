"""Chunk tree: python -m unittest discover -s tools/carbuild/tests -p test_chunks.py"""
import unittest

from common import GTI_GEOMETRY, car_files, need, need_cars, read
from chunks import Chunk, find, read_chunks, write_chunks


class ChunkTests(unittest.TestCase):
    def test_roundtrip_all_cars_chunk_level(self):
        need_cars(self)
        files = car_files()
        for path in files:
            data = read(path)
            self.assertEqual(write_chunks(read_chunks(data)), data, path)
        print("\n  chunk round trip: %d files identical" % len(files))

    def test_gti_top_level(self):
        need(self, GTI_GEOMETRY)
        top = read_chunks(read(GTI_GEOMETRY))
        self.assertEqual([(c.id, len(write_chunks([c])) - 8) for c in top],
                         [(0x80134000, 5450664), (0, 85432), (0, 8)])

    def test_gti_container_starts_with_empty_padding(self):
        need(self, GTI_GEOMETRY)
        top = read_chunks(read(GTI_GEOMETRY))
        first = top[0].children[:2]
        self.assertEqual((first[0].id, first[0].data), (0, b""))
        self.assertEqual(first[1].id, 0x80134001)

    def test_find_depth_first(self):
        tree = [Chunk(0x80000001, None, [Chunk(5, b"a", None), Chunk(0x80000002, None, [Chunk(5, b"b", None)])]),
                Chunk(5, b"c", None)]
        self.assertEqual([c.data for c in find(tree, 5)], [b"a", b"b", b"c"])

    def test_short_container_size_kept(self):  # like the Raptor: the container's size misses its last child's tail
        good = bytes.fromhex("01000080 08000000 07000000 04000000") + b"wxyz"
        data = good[:4] + (6).to_bytes(4, "little") + good[8:]
        tree = read_chunks(data)
        self.assertEqual((tree[0].size, len(tree[0].children)), (6, 1))
        self.assertEqual(write_chunks(tree), data)

    def test_leaf_and_container_bytes(self):
        tree = [Chunk(0x80000001, None, [Chunk(7, b"xyz", None)])]
        self.assertEqual(write_chunks(tree),
                         bytes.fromhex("01000080 0b000000 07000000 03000000") + b"xyz")


if __name__ == "__main__":
    unittest.main()
