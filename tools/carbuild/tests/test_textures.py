"""Texture packs: python -m unittest discover -s tools/carbuild/tests -p test_textures.py"""
import os
import struct
import unittest

from common import GTI_TEXTURES, TRUCK_TEXTURES, car, need, need_cars, read, texture_files
from chunks import bstringhash
from textures import mip_chain_size, read_textures, to_dds, write_textures

TOOL_LAYOUT = ("RAPTOR", "CHIRON")  # packs made by other tools in other layouts (docs/carbuild-format.md)

_cache = {}


def packs():
    """(car, data, pack) for every non-empty TEXTURES.BIN (per car and the shared one)."""
    if "all" not in _cache:
        out = []
        for p in texture_files():
            data = read(p)
            if data:
                out.append((os.path.basename(os.path.dirname(p)) if os.path.basename(p) == "TEXTURES.BIN" and
                            os.path.basename(os.path.dirname(p)) != "CARS" else "CARS", data, read_textures(data)))
        _cache["all"] = out
    return _cache["all"]


def content(pack):
    return [(t.name, t.name_hash, t.width, t.height, t.fmt, t.mipmaps, t.data, t.header) for t in pack.textures]


class TextureTests(unittest.TestCase):
    def test_roundtrip_textures_identical(self):  # every pack in the game's layout, and CARS/TEXTURES.BIN
        need_cars(self)
        done = 0
        for name, data, pack in packs():
            if name in TOOL_LAYOUT:
                continue
            self.assertEqual(write_textures(pack), data, name)
            done += 1
        self.assertGreaterEqual(done, 88)
        print("\n  texture round trip: %d packs identical" % done)

    def test_tool_layout_packs_content_roundtrip(self):  # the Raptor (128-byte alignment, RAWW) and the Chiron
        for name in TOOL_LAYOUT:
            path = car(name, "TEXTURES.BIN")
            need(self, path)
            pack = read_textures(read(path))
            again = read_textures(write_textures(pack))
            self.assertEqual(content(again), content(pack), name)

    def test_truck_skin_name(self):  # the Longnose Cab's pack (compressed): one texture, LONGNOSECAB_SKIN2
        need(self, TRUCK_TEXTURES)
        pack = read_textures(read(TRUCK_TEXTURES))
        self.assertEqual([t.name for t in pack.textures], ["LONGNOSECAB_SKIN2"])
        self.assertEqual(pack.textures[0].name_hash, 0x70F85C30)

    def test_compressed_pack_reads(self):  # dimensions powers of two, data length matches format and mipmaps
        need_cars(self)
        decoded = huff = 0
        for name, data, pack in packs():
            for t in pack.textures:
                if t.data is None:
                    self.assertEqual(t.codec, "HUFF", (name, t.name_hash))
                    huff += 1
                    continue
                decoded += 1
                if (name, t.name) != ("RAPTOR", "RAPTOR_SKIN2"):  # 896 x 1024: the one texture that is not 2^n
                    self.assertEqual(t.width & (t.width - 1), 0, (name, t.name))
                    self.assertEqual(t.height & (t.height - 1), 0, (name, t.name))
                self.assertIn(t.fmt, ("DXT1", "DXT3", "DXT5", "A8R8G8B8"), (name, t.name))
                if name in TOOL_LAYOUT and t.mipmaps == 1 and len(t.data) != mip_chain_size(t.width, t.height, t.fmt, 1):
                    # the Raptor's and Chiron's tools store the whole mip chain while the header says one level
                    full = 1 + max(t.width, t.height).bit_length() - 1
                    self.assertEqual(len(t.data), mip_chain_size(t.width, t.height, t.fmt, full), t.name)
                else:
                    self.assertEqual(len(t.data), mip_chain_size(t.width, t.height, t.fmt, t.mipmaps), (name, t.name))
        self.assertGreater(decoded, 1100)
        print("\n  textures decoded: %d, HUFF kept as stored: %d" % (decoded, huff))

    def test_names_match_directory(self):  # the header's hash is the directory's; names hash to it unless cut short
        need(self, GTI_TEXTURES)
        for t in read_textures(read(GTI_TEXTURES)).textures:
            if t.data is None:
                continue
            self.assertEqual(struct.unpack_from("<I", t.header, 0x24)[0], t.name_hash)
            if len(t.name) < 23:  # the name field holds 23 characters and a zero
                self.assertEqual(bstringhash(t.name), t.name_hash, t.name)

    def test_dds_header(self):  # to_dds starts with b"DDS " and has the texture's width/height
        need(self, GTI_TEXTURES)
        for t in read_textures(read(GTI_TEXTURES)).textures:
            if t.data is None:
                continue
            dds = to_dds(t)
            self.assertEqual(dds[:4], b"DDS ")
            self.assertEqual(struct.unpack_from("<I", dds, 4)[0], 124)
            self.assertEqual(struct.unpack_from("<II", dds, 12), (t.height, t.width))
            self.assertEqual(struct.unpack_from("<I", dds, 28)[0], t.mipmaps)
            self.assertEqual(len(dds), 128 + len(t.data))
            if t.fmt.startswith("DXT"):
                self.assertEqual(dds[84:88], t.fmt.encode())

    def test_uncompressed_write_reads_back(self):  # every decodable texture re-stored as RAWW (the Raptor's form)
        need(self, GTI_TEXTURES)
        pack = read_textures(read(GTI_TEXTURES))
        out = read_textures(write_textures(pack, compressed=False))
        self.assertEqual(content(out), content(pack))
        self.assertEqual({t.codec for t in out.textures if t.data is not None}, {"RAWW"})
        self.assertEqual([t.codec for t in out.textures if t.data is None],
                         [t.codec for t in pack.textures if t.data is None])

    def test_literal_jdlz_write_reads_back(self):
        need(self, TRUCK_TEXTURES)
        pack = read_textures(read(TRUCK_TEXTURES))
        out = read_textures(write_textures(pack, compressed=True))
        self.assertEqual(content(out), content(pack))

    def test_changed_texture_is_reencoded(self):  # a stale stored block must not be written for changed data
        need(self, GTI_TEXTURES)
        pack = read_textures(read(GTI_TEXTURES))
        t = pack.textures[0]
        t.data = bytes(len(t.data))
        out = read_textures(write_textures(pack))
        self.assertEqual(out.textures[0].data, t.data)


if __name__ == "__main__":
    unittest.main()
