"""Every speed.exe address in docs/ftown-notes.md is real, and every code-path question has an answer with a source:
python -m unittest discover -s tools/world/tests -p test_notes_addresses.py -v

An address here is a hexadecimal number of exactly six digits from 0x400000 to 0x9FFFFF (the exe's image); chunk ids
and other numbers either have another length or start lower. Code addresses must start a decodable instruction (capstone,
through tools/world/pe.py); data addresses must lie in .rdata or .data (virtual size: .bss counts).
"""
import os
import re
import unittest

from common import EXE, REPO, need
from world import pe

NOTES = os.path.join(REPO, "docs", "ftown-notes.md")
ADDR = re.compile(r"(?<![0-9A-Za-z_])0x([4-9][0-9A-Fa-f]{5})(?![0-9A-Za-z_])")
QUESTIONS = 7
SOURCE = re.compile(r"(\.cpp|\.hpp|\.h)(:\d+)?|\bunknown\b|test_\w+|mwdis", re.I)


def question_sections(text):
    """{n: section text} for every '### Q<n>' heading (to the next '##' heading)."""
    out = {}
    parts = re.split(r"(?m)^(#{2,3} .*)$", text)
    for i in range(1, len(parts), 2):
        m = re.match(r"### Q(\d+)\b", parts[i])
        if m:
            out[int(m.group(1))] = parts[i] + parts[i + 1]
    return out


class NotesAddressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, NOTES)
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

    def test_every_answer_has_a_source(self):
        qs = question_sections(self.text)
        for n in range(1, QUESTIONS + 1):
            self.assertIn(n, qs, "no '### Q%d' section" % n)
            body = qs[n]
            self.assertTrue(ADDR.search(body), "Q%d names no address" % n)
            self.assertTrue(SOURCE.search(body), "Q%d names no source file, test or 'unknown'" % n)


if __name__ == "__main__":
    unittest.main()
