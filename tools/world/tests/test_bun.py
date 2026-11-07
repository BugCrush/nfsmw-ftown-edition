"""World files (L2RA.BUN, STREAML2RA.BUN): python -m unittest discover -s tools/world/tests -p test_bun.py -v"""
import os
import unittest

from common import L2RA, STREAM, need
from chunks import write_chunks
from world import bun


class BunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA, STREAM)
        cls.sections = bun.sections(L2RA)
        cls.top = list(bun.iter_top(STREAM))

    def test_l2ra_roundtrip(self):
        with open(L2RA, "rb") as f:
            data = f.read()
        self.assertEqual(write_chunks(bun.read_file(L2RA)), data)

    def test_stream_top_level_covers_file(self):
        end = 0
        for off, cid, size in self.top:
            self.assertEqual(off, end, "gap or overlap at 0x%X" % off)
            end = off + 8 + size
        self.assertEqual(end, os.path.getsize(STREAM))

    def test_section_count_and_fields(self):
        self.assertEqual(len(self.sections), 720)
        names = set()
        for s in self.sections:
            self.assertEqual(bun.section_name(s.number), s.name)
            self.assertNotIn(s.name, names)
            names.add(s.name)
            self.assertEqual(s.file_type, 1)  # every section lives in the region file (STREAML2RA.BUN)
            self.assertEqual(s.compressed_size, s.size)  # none is compressed in this copy

    def test_sections_point_into_stream(self):
        starts = {off: i for i, (off, _, _) in enumerate(self.top)}
        ends = {off + 8 + size: i for i, (off, _, size) in enumerate(self.top)}
        matched = 0
        for s in self.sections:
            self.assertIn(s.offset, starts, "%s starts inside a chunk" % s.name)
            self.assertIn(s.offset + s.size, ends, "%s ends inside a chunk" % s.name)
            matched += 1
        self.assertEqual(matched, 720)

    def test_sections_and_gaps_cover_stream(self):  # sum of section sizes + gaps = file size, no overlap
        spans = sorted((s.offset, s.size) for s in self.sections)
        pos = gaps = 0
        for off, size in spans:
            self.assertGreaterEqual(off, pos)
            gaps += off - pos
            pos = off + size
        self.assertEqual(sum(sz for _, sz in spans) + gaps + (os.path.getsize(STREAM) - pos), os.path.getsize(STREAM))
        self.assertEqual(pos, os.path.getsize(STREAM))

    def test_section_ranges_roundtrip(self):
        with open(STREAM, "rb") as f:
            for s in self.sections:
                f.seek(s.offset)
                raw = f.read(s.size)
                self.assertEqual(write_chunks(bun.read_range(STREAM, s.offset, s.size)), raw, s.name)

    def test_boundaries_contain_centres(self):
        bounds = bun.boundaries(L2RA)
        by_number = {s.number: s for s in self.sections}
        inside = outside = 0
        bad = []
        missing = []
        for number, b in bounds.items():
            s = by_number.get(bun.combined_number(number, by_number))
            if s is None or s.radius == 0:
                missing.append(number)
                continue
            if bun.point_in_poly(s.centre, b.points):
                inside += 1
            else:
                outside += 1
                bad.append(s.name)
        print("\n  boundaries %d; streaming centres inside their boundary %d, outside %d: %s; no streaming section %d:"
              " %s" % (len(bounds), inside, outside, " ".join(bad[:20]), len(missing),
                       " ".join(bun.section_name(n) for n in missing[:30])))
        self.assertGreater(inside, 0)
        self.assertGreaterEqual(inside / (inside + outside), 0.9)

    def test_drivable_sections(self):
        """0x34153: one record per drivable boundary; every visible section it lists is streamed (directly or as its
        LOD section) or is a scenery-only section."""
        ds = bun.drivable_sections(L2RA)
        bounds = bun.boundaries(L2RA)
        present = {s.number for s in self.sections}
        self.assertEqual(set(ds), {n for n in bounds if bun.is_drivable(n)})
        missing = [(n, v) for n, vs in ds.items() for v in vs if bun.combined_number(v, present) not in present]
        regular = [m for m in missing if "A" <= bun.section_name(m[1])[0] < "U"]
        print("\n  drivable sections %d, visible lists %d..%d long (%d entries); entries with no streaming section %d,"
              " of which regular (A..T) %d (the rest are X/Y/V library numbers this region file does not have)" %
              (len(ds), min(len(v) for v in ds.values()), max(len(v) for v in ds.values()),
               sum(len(v) for v in ds.values()), len(missing), len(regular)))
        self.assertEqual(regular, [])

    def test_boundary_bbox_matches_points(self):
        for number, b in bun.boundaries(L2RA).items():
            xs = [p[0] for p in b.points]
            ys = [p[1] for p in b.points]
            self.assertAlmostEqual(min(xs), b.bbox_min[0], places=2)
            self.assertAlmostEqual(min(ys), b.bbox_min[1], places=2)
            self.assertAlmostEqual(max(xs), b.bbox_max[0], places=2)
            self.assertAlmostEqual(max(ys), b.bbox_max[1], places=2)


if __name__ == "__main__":
    unittest.main()
