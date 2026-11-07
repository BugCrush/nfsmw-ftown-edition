"""Breakable poles (docs/ftown-notes.md "Breakable poles (2026-11-05)"; tools/citymap/breakables.py).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_breakables -v

The user's choice ("Mix"): Rockport's own smackable street lights and signal masts (X0, by hash) on the main roads and
at every signal, our lantern lamps on the sector roads, breakable; electricity poles solid. Checked on the written
city and its ftown-smackables.bun.
"""
import math
import os
import struct
import sys
import unittest

from tools.citymap import breakables
from tools.citymap.tests import common

TOOLS = common.TOOLS
for p in (TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from vlthash import vlt32  # noqa: E402
from world import scenery, smackables  # noqa: E402
from world.collision import to_render  # noqa: E402


class Classify(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(breakables.median_role("trunk", "trunk", True), "light_cb")
        for k in ("tertiary", "secondary_link", "primary", "motorway"):
            self.assertEqual(breakables.median_role(k, "residential", False), "light_c", k)
        for k in ("residential", "service", "unclassified", "living_street"):
            self.assertEqual(breakables.median_role(k, k, False), "lantern", k)
        self.assertEqual(breakables.signal_role(12.0), "signal_a")
        self.assertEqual(breakables.signal_role(7.0), "signal_b")

    def test_arm_over_the_road(self):
        """X0's poles reach along their model's -y: the heading puts it towards the given direction."""
        for a in (0.0, 1.0, 2.5, -2.0):
            h = breakables.arm_heading(math.cos(a), math.sin(a))
            arm = (math.sin(h), -math.cos(h))  # -(row 1) of a model turned by h
            self.assertAlmostEqual(arm[0], math.cos(a))
            self.assertAlmostEqual(arm[1], math.sin(a))

    def test_rockport_names(self):
        """The records' model and volume hashes are Rockport's own (its records, survey 2026-11-05) and the lantern
        borrows XO_LightPoleA's volume; the slot-0 solids and hierarchies are X0's B models."""
        self.assertEqual(breakables.volume("light_c"), 0xB21A3F48)
        self.assertEqual(breakables.volume("light_cb"), 0x7EFE134E)
        self.assertEqual(breakables.volume("signal_a"), 0xB1A4176B)
        self.assertEqual(breakables.volume("signal_b"), 0xDE0209BD)
        self.assertEqual(breakables.volume("lantern"), 0xD11BF68F)
        self.assertEqual(breakables.hierarchy("light_cb"), 0x13288C4A)
        self.assertEqual(breakables.hierarchy("signal_a"), 0x07D9FC0E)
        self.assertEqual(breakables.hierarchy("lantern"), 0)


def _built():
    from tools.citymap.tests import test_city
    info, data, out = test_city.built()
    path = os.path.join(os.path.dirname(out), "ftown-smackables.bun")
    with open(path, "rb") as f:
        smk = f.read()
    return info, data, smk


def _sections(data):
    from chunks import read_chunks
    return {sc.number: sc for sc in (scenery.read_scenery(c, p) for c, p in
                                     scenery.with_positions(read_chunks(data), 0) if c.id == scenery.SCENERY_SECTION)}


class Written(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(common.OSM)
        cls.info, cls.data, cls.smk = _built()
        cls.base, cls.entries, cls.packs = smackables.read_file(cls.smk)
        cls.secs = _sections(cls.data)

    def test_counts(self):
        recs = [r for _s, _f, rs in self.packs for r in rs]
        kinds = self.info["breakables"]["kinds"]
        print("\n  breakable poles %s; %d records in %d packs, %d bytes" % (kinds, len(recs), len(self.packs),
                                                                           len(self.smk)))
        self.assertEqual(self.base, 22340)
        self.assertEqual(len(recs), len(self.entries))
        self.assertLessEqual(len(recs), smackables.MAX_RECORDS)
        self.assertTrue(all(len(rs) <= smackables.MAX_RECORDS for _s, _f, rs in self.packs))
        self.assertEqual(self.info["breakables"]["dropped"], 0)
        for k in ("lantern", "light_c", "light_cb"):
            self.assertGreater(kinds.get(k, 0), 5, k)
        self.assertGreaterEqual(kinds.get("signal_a", 0) + kinds.get("signal_b", 0), 16)  # OSM's 16 signal nodes
        self.assertEqual([r["override"] for r in recs], list(range(22340, 22340 + len(recs))))
        self.assertEqual([r["uid"] for r in recs], list(range(breakables.FIRST_UID, breakables.FIRST_UID + len(recs))))

    def test_each_record_its_instance(self):
        """Every record's override entry names its pole's own instance in its pack's section: same position (physics,
        1 cm), the instance's low 16 exclude bits equal to the entry's flags, its info naming the role's model in
        slot 0 alone and the hierarchy, the quaternion turning the model's x axis as the instance's matrix."""
        k = 0
        roles = {breakables.solid_hash(r): r for r in breakables.ROLES}
        for section, _first, recs in self.packs:
            for r in recs:
                s, i, flags = self.entries[k]
                k += 1
                self.assertEqual(s, section)
                inst = self.secs[s].instances[i]
                info = self.secs[s].infos[inst.info_index]
                role = roles[info.solid_hashes[0]]
                self.assertEqual(info.solid_hashes[1:], (0, 0, 0))
                self.assertEqual(info.hierarchy, breakables.hierarchy(role))
                self.assertEqual(inst.exclude_flags, breakables.INSTANCE_FLAGS)
                self.assertEqual(inst.exclude_flags & 0xFFFF, flags)
                rp = to_render(r["pos"])
                for a in range(3):
                    self.assertAlmostEqual(rp[a], inst.matrix[3][a], delta=0.01)
                self.assertEqual((r["model"], r["collision"]), (breakables.volume(role), breakables.volume(role)))
                self.assertEqual(r["attributes"], vlt32("trafficlight"))
                self.assertEqual(r["exclude"] & smackables.LOADER_BITS, 0)
                q = r["q"]
                h = -2.0 * math.atan2(q[1], q[3])
                row0 = inst.matrix[0]
                self.assertAlmostEqual(math.cos(h), row0[0], delta=0.002)
                self.assertAlmostEqual(math.sin(h), row0[1], delta=0.002)

    def test_no_barrier_at_a_breakable_pole(self):
        """No barrier taller than 2 m within 0.6 m of a breakable pole's foot (they had a ring of 9 m barriers; Mathura
        Road's 1.1 m railing runs through its lights' feet down the median, as before); the electricity poles keep
        theirs."""
        from tools.citymap import terrain
        from tools.citymap.tests import test_city
        import shapely
        bars = test_city.all_barriers()
        lines = shapely.STRtree([shapely.LineString([a, b]) for a, b, _lo, _hi in bars])
        tall = low = 0
        for _s, _f, recs in self.packs:
            for r in recs:
                p = to_render(r["pos"])
                for k in lines.query(shapely.Point(p[0], p[1]).buffer(0.6), predicate="intersects"):
                    if bars[k][3] - terrain.ground_z(p[0], p[1]) > 2.0:
                        tall += 1
                    else:
                        low += 1
        print("\n  barriers within 0.6 m of a breakable pole: %d over 2 m, %d lower (the railing)" % (tall, low))
        self.assertEqual(tall, 0)
        from tools.citymap.tests.test_landmark_build import geometry
        poles = geometry()[4].extras.poles
        hit = sum(1 for x, y, _rid in poles.poles
                  if len(lines.query(shapely.Point(x, y).buffer(0.4), predicate="intersects")))
        print("\n  electricity poles with their barriers: %d of %d" % (hit, len(poles.poles)))
        self.assertEqual(hit, len(poles.poles))

    def test_nothing_of_rockport_copied(self):
        """Our files name X0's models and volumes by hash only: no X0 name in the city or the spawner file, the
        lantern's solid is ours."""
        from tools.citymap import x0props
        self.assertNotIn(b"XO_", self.smk)
        self.assertNotIn(b"XO_STREETLIGHT", self.data)
        self.assertNotIn(b"XO_TRAFFICLIGHT", self.data)
        lib = x0props.library()
        self.assertNotIn(breakables.solid_hash("lantern"), lib)


if __name__ == "__main__":
    unittest.main()
