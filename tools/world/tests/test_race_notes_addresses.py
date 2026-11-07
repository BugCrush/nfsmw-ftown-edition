"""docs/ftown-race-notes.md (the minimap, the race machinery, the Quick Race menu, HUD text): every speed.exe address in
it is real, every research question has an answer with a source and a recommendation, and the facts the minimap build
relies on hold in the game's own files:

    python -m unittest discover -s tools/world/tests -p test_race_notes_addresses.py -v

Addresses as in test_notes_addresses.py (six hexadecimal digits, 0x400000..0x9FFFFF): code ones start a decodable
instruction, data ones lie in .rdata or .data. The questions are the '### R<n>' sections (R1 minimap, R2 race machinery,
R3 Quick Race menu, R4 HUD text); each ends with a line starting 'Recommendation:'.
"""
import os
import re
import struct
import unittest

from common import EXE, GAME, REPO, need
from world import pe

NOTES = os.path.join(REPO, "docs", "ftown-race-notes.md")
ADDR = re.compile(r"(?<![0-9A-Za-z_])0x([4-9][0-9A-Fa-f]{5})(?![0-9A-Za-z_])")
QUESTIONS = 28  # R13-R19: the Run I fixes, the game side; R20-R22: Run J, the game side; R23: moving traffic;
# R24: the breakable poles; R25: the connection to Rockport; R26-R28: the Run K fixes
SOURCE = re.compile(r"(\.cpp|\.hpp|\.h)(:\d+)?|\bunknown\b|test_\w+|mwdis", re.I)
GLOBALB = os.path.join(GAME, "GLOBAL", "GLOBALB.BUN")
MINI_MAP = os.path.join(GAME, "TRACKS", "L2RA", "MINI_MAP.BIN")


def question_sections(text):
    """{n: section text} for every '### R<n>' heading (to the next '##' heading)."""
    out = {}
    parts = re.split(r"(?m)^(#{2,3} .*)$", text)
    for i in range(1, len(parts), 2):
        m = re.match(r"### R(\d+)\b", parts[i])
        if m:
            out[int(m.group(1))] = parts[i] + parts[i + 1]
    return out


def track_infos(path):
    """[(name, track number, upper left x, upper left y, width)] from the TrackInfo chunk 0x34201 (0x120 a record,
    World/TrackInfo.hpp: +0x8A TrackNumber, +0xAC TrackMapCalibrationUpperLeft, +0xB4 TrackMapCalibrationMapWidthMetres)."""
    with open(path, "rb") as f:
        d = f.read()
    found = []

    def walk(start, end, depth):
        off = start
        while off + 8 <= end:
            cid, size = struct.unpack_from("<II", d, off)
            if off + 8 + size > end:
                return
            if cid == 0x34201:
                for k in range(size // 0x120):
                    e = d[off + 8 + k * 0x120: off + 8 + (k + 1) * 0x120]
                    found.append((e[:32].split(b"\0")[0].decode("latin-1"), struct.unpack_from("<h", e, 0x8A)[0])
                                 + struct.unpack_from("<3f", e, 0xAC))
            if cid & 0x80000000 and depth < 2:
                walk(off + 8, off + 8 + size, depth + 1)
            off += 8 + size

    walk(0, len(d), 0)
    return found


class RaceNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(NOTES):
            raise AssertionError("docs/ftown-race-notes.md does not exist yet")
        with open(NOTES, encoding="utf-8") as f:
            cls.text = f.read()

    def test_every_address_in_notes_is_a_function_or_data(self):
        need(self, EXE)
        img = pe.Image(EXE)
        addrs = sorted({int(m.group(1), 16) for m in ADDR.finditer(self.text)})
        self.assertGreater(len(addrs), 20, "the notes name too few addresses")
        code = [a for a in addrs if img.section_of(a) == ".text"]
        other = [a for a in addrs if img.section_of(a) != ".text"]
        for a in other:
            self.assertIn(img.section_of(a), (".rdata", ".data"), "0x%06X is in no code or data section" % a)
        decoded = pe.decode_first(EXE, code)
        bad = [("0x%06X" % a) for a in code if not decoded[a]]
        self.assertFalse(bad, "addresses that do not start an instruction: %s" % bad)
        print("\n  %d addresses: %d code, %d data" % (len(addrs), len(code), len(other)))

    def test_every_question_has_a_source_and_a_recommendation(self):
        qs = question_sections(self.text)
        for n in range(1, QUESTIONS + 1):
            self.assertIn(n, qs, "no '### R%d' section" % n)
            body = qs[n]
            self.assertTrue(ADDR.search(body), "R%d names no address" % n)
            self.assertTrue(SOURCE.search(body), "R%d names no source file, test or 'unknown'" % n)
            self.assertRegex(body, r"(?m)^Recommendation:", "R%d has no 'Recommendation:' line" % n)

    def test_rockport_calibration_is_the_one_in_the_notes(self):
        """The world-to-minimap numbers the notes quote for track 2000 are the game's (GLOBALB.BUN's TrackInfo)."""
        need(self, GLOBALB)
        rows = {r[1]: r for r in track_infos(GLOBALB)}
        self.assertIn(2000, rows)
        _, _, x, y, w = rows[2000]
        quoted = "upper left (%.1f, %.1f), width %.1f m" % (x, y, w)
        self.assertIn(quoted, self.text, "the notes do not quote %s" % quoted)

    def test_minimap_chops_are_as_the_notes_say(self):
        """MINI_MAP.BIN: 64 chunks 0x3A100, each JDLZ holding one texture pack with one 128 x 128 DXT3 texture named
        MINI_MAP_CHOP<n> (the name the minimap asks for: '%s_CHOP%d' with the map header)."""
        need(self, MINI_MAP)
        import jdlz
        from world.texpack import read_pack
        from chunks import read_chunks, bstringhash
        with open(MINI_MAP, "rb") as f:
            d = f.read()
        off, n = 0, 0
        while off + 8 <= len(d):
            cid, size = struct.unpack_from("<II", d, off)
            self.assertEqual(cid, 0x3A100)
            if n in (0, 63):
                raw = jdlz.decompress(d[off + 8: off + 8 + size])
                pack = read_pack(read_chunks(raw)[0])
                self.assertEqual(len(pack.textures), 1)
                t = pack.textures[0]
                name = "MINI_MAP_CHOP%d" % n
                self.assertEqual(t.name_hash, bstringhash(name))
                self.assertEqual(struct.unpack_from("<hh", t.info, 0x44), (128, 128))
                self.assertEqual(t.comp[0x14:0x18], b"DXT3")
            off += 8 + size
            n += 1
        self.assertEqual(n, 64)
        self.assertIn("64 chunks 0x3A100", self.text)


if __name__ == "__main__":
    unittest.main()
