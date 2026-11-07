"""The road from Rockport to F-Town (tools/citymap/connector.py, plan
docs/superpowers/plans/2026-11-06-ftown-rockport-connection.md Task 2; decisions docs/ftown-connection-research.md C1-C7).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_connector -v

Needs the built city (ftown/ftown-city.bun, .json) and the road model; the Rockport checks also read the game's track
files (read only). Each skips without its files.
"""
import math
import os
import pickle
import struct
import sys
import unittest

from tools.citymap.tests import common

sys.path.insert(0, common.TOOLS)
sys.path.insert(0, os.path.join(common.TOOLS, "carbuild"))
from tools.citymap import connector as cn, geo  # noqa: E402

GAME_L2RA = cn.L2RA
GAME_STREAM = os.path.join(cn.GAME, "TRACKS", "STREAML2RA.BUN")


class Shift(unittest.TestCase):
    def test_geo_shift(self):
        self.assertEqual(geo.ORIGIN, (2000.0, 9068.0))
        self.assertEqual(geo.SHIFT[1] % 128.0, 0.0)
        self.assertEqual(geo.moved(2000.0, 11500.0), geo.ORIGIN)


class Path(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(cn.CITY, cn.CITY_JSON, cn.ROADS)
        cls.info = cn.city_info()
        cls.p = cn.path(cls.info)

    def test_ends(self):
        p = self.p
        self.assertEqual(p.at(0.0), cn.JUNCTION)
        t0, t1 = p.tangent(0.0), p.tangent(p.length)
        self.assertAlmostEqual(math.degrees(math.atan2(t0[1], t0[0])), cn.START_HEADING, delta=0.5)
        self.assertAlmostEqual(math.degrees(math.atan2(t1[1], t1[0])), cn.END_HEADING, delta=0.5)
        self.assertAlmostEqual(p.at(p.length)[1], self.info["edge_box"][1], delta=0.01)
        self.assertTrue(2500.0 <= p.length <= 2800.0, p.length)

    def test_heights(self):
        """The road's own heights (the ramp over Rockport's closure, test_connector_ramp, left out; outside its table the
        road is exactly the base)."""
        p = self.p
        self.assertEqual(p.base_z(0.0), cn.JUNCTION_Z)
        self.assertAlmostEqual(p.z(p.length), cn.end_height(p.at(p.length)), delta=0.05)
        grades = [abs(p.base_z(s + 5.0) - p.base_z(s)) / 5.0 for s in range(0, int(p.length) - 5, 5)]
        self.assertLessEqual(max(grades), 0.085)
        for s in range(int(p.ramp.s3) + 1, int(p.length), 25):
            self.assertEqual(p.z(float(s)), p.base_z(float(s)))

    def test_width(self):
        p = self.p
        self.assertEqual(p.width(100.0), cn.WIDTH)
        _near, (left, right), _t = cn.mathura_ends(box=self.info["edge_box"])
        self.assertAlmostEqual(p.width(p.length), right - left, delta=0.01)

    def test_network_road(self):
        road = cn.network_road(self.p, self.info)
        self.assertEqual(len(road["carriageways"]), 2)
        self.assertAlmostEqual(road["points"][-1][1], self.info["edge_box"][1] + 15.0, delta=0.01)
        self.assertEqual(road["points"][0][:2], cn.JUNCTION)


class Files(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(cn.OUT_BUN, cn.OUT_BIN, cn.CITY_JSON)
        cls.data = open(cn.OUT_BUN, "rb").read()
        cls.connect = cn.read_connect(open(cn.OUT_BIN, "rb").read())

    def test_chunks(self):
        from chunks import read_chunks
        from world import collision_write, scenery
        cs = read_chunks(self.data)
        ids = [c.id for c in cs if c.id]
        self.assertEqual(ids, [0xB3300000, 0x80134000, 0x80034100, 0x3B801])
        packs = [collision_write.read_pack(c.data, p) for c, p in scenery.with_positions(cs, 0) if c.id == 0x3B801]
        self.assertEqual(packs[0].section, cn.SECTION)
        heights = []
        for art in packs[0].articles:
            for b in art.barriers:
                heights.append(abs(b.p1[1] - b.p0[1]))
                self.assertEqual(b.flags >> 8 if hasattr(b, "flags") else 0x12, 0x12)
        self.assertGreater(len(heights), 500)
        self.assertGreaterEqual(min(heights), 4.0)  # every wall at least F-Town's edge walls' 3 m + 1

    def test_connect_file(self):
        c = self.connect
        self.assertEqual((c["magic"], c["version"]), (b"FTCN", 2))
        self.assertEqual((c["source_zone"], c["our_zone"], c["adjoin_zone"]), (703, 226, 723))
        self.assertEqual(list(c["substitutes"]), [726, 723])
        self.assertEqual(c["bun_size"], len(self.data))
        info = cn.city_info()
        self.assertEqual(c["extra"], list(info["sections"]) + [cn.SECTION])
        self.assertLessEqual(len(c["source"]) + 2 + len(c["extra"]), 72)
        self.assertEqual([(w[0], w[1]) for w in c["walls"]], [(703, 5), (0, 2)])

    def test_city_wall_barriers(self):
        """F-Town's edge pieces the connection opens: exactly the data's count of the city's barriers lie on the wall's
        line within its heights (as FTownConnect.h's ScanPack counts them)."""
        from chunks import read_chunks
        from world import bun, collision
        common.need(cn.CITY)
        w = [w for w in self.connect["walls"] if w[0] == 0][0]
        n = 0
        for p in collision.packs_in(read_chunks(open(cn.CITY, "rb").read())):
            for a, b, _h, _s, _i in collision.barriers(p):
                ends = [collision.to_render(q) for q in (a, b)]
                if all(bun.dist_to_segment(e[:2], (w[2], w[3]), (w[4], w[5])) < 0.6 for e in ends) and \
                        min(e[2] for e in ends) >= w[6] and max(e[2] for e in ends) <= w[7]:
                    n += 1
        self.assertEqual(n, w[1])


class Rockport(unittest.TestCase):
    """Against the game's own track file (read only)."""

    @classmethod
    def setUpClass(cls):
        common.need(GAME_L2RA, cn.CITY, cn.CITY_JSON)
        from world import bun
        cls.bun = bun
        cls.bounds = bun.boundaries(GAME_L2RA)
        cls.visible = bun.drivable_sections(GAME_L2RA)
        cls.info = cn.city_info()
        cls.p = cn.path(cls.info)

    def test_our_zone(self):
        from shapely.geometry import Polygon
        pts = cn.our_zone_points(self.bounds, self.info)
        g23 = self.bounds[cn.ADJOIN_ZONE].points
        self.assertIn(pts[0], g23)
        self.assertIn(pts[1], g23)
        ours = Polygon(pts)
        for n, b in self.bounds.items():
            if self.bun.is_drivable(n):
                self.assertLess(ours.intersection(Polygon(b.points).buffer(0)).area, 1.0, self.bun.section_name(n))
        self.assertNotIn(cn.OUR_ZONE, self.bounds)
        self.assertNotIn(cn.OUR_ZONE + 40, self.bounds)
        self.assertEqual(self.visible[cn.SUBSTITUTES[0]], [726, 766])
        self.assertEqual(self.visible[cn.SUBSTITUTES[1]], [723, 763])

    def test_path_zones(self):
        """The road runs through G3, G26, G23, then ours, then F-Town's box, and no other drivable section."""
        ours = cn.our_zone_points(self.bounds, self.info)
        allowed = {cn.SOURCE_ZONE, cn.SUBSTITUTES[0], cn.SUBSTITUTES[1]}
        seen = []
        for s in range(0, int(self.p.length), 10):
            q = self.p.at(float(s))
            z = [n for n, b in self.bounds.items() if self.bun.is_drivable(n) and self.bun.point_in_poly(q, b.points)]
            if not z and self.bun.point_in_poly(q, ours):
                z = [cn.OUR_ZONE]
            if not z:
                self.assertGreaterEqual(q[1], self.info["edge_box"][1] - cn.OUR_ZONE_GAP - 0.5, q)
                z = [0]
            self.assertTrue(set(z) <= allowed | {cn.OUR_ZONE, 0}, (s, z))
            if not seen or seen[-1] != z[0]:
                seen.append(z[0])
        self.assertEqual(seen, [703, 726, 723, 226, 0])

    def test_drawn_surfaces_clear(self):
        """Every surface Rockport draws from the zones on the way (G3's list) over the road's centre line lies 1 m or
        more under the road, or 6 m or more over it (the overpass at the junction)."""
        cache = os.path.join(common.REPO, ".superpowers", "research", "connection", "north-tris.pkl")
        common.need(cache)
        tris = pickle.load(open(cache, "rb"))
        wanted = set(self.visible[cn.SOURCE_ZONE])
        bad = []
        for s in range(int(cn.ROCK_EDGE_S) + 2, int(self.p.length), 10):
            qx, qy = self.p.at(float(s))
            zr = self.p.z(float(s))
            if qy > cn.HULL_Y:
                break
            for p0, p1, p2, n in tris:
                if n not in wanted:
                    continue
                if min(p0[0], p1[0], p2[0]) > qx or max(p0[0], p1[0], p2[0]) < qx or \
                        min(p0[1], p1[1], p2[1]) > qy or max(p0[1], p1[1], p2[1]) < qy:
                    continue
                det = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
                if abs(det) < 1e-9:
                    continue
                a = ((p1[1] - p2[1]) * (qx - p2[0]) + (p2[0] - p1[0]) * (qy - p2[1])) / det
                b = ((p2[1] - p0[1]) * (qx - p2[0]) + (p0[0] - p2[0]) * (qy - p2[1])) / det
                if min(a, b, 1 - a - b) < -1e-6:
                    continue
                z = a * p0[2] + b * p1[2] + (1 - a - b) * p2[2]
                if zr - 1.0 < z < zr + 6.0:
                    bad.append((s, round(z, 1), round(zr, 1), self.bun.section_name(n)))
        self.assertEqual(bad, [])

    def test_wall_barriers(self):
        """Rockport's wall the connection opens: exactly five barriers of pack 703 lie on its segment."""
        common.need(GAME_STREAM)
        from world import collision
        secs = {s.name: s for s in self.bun.sections(GAME_L2RA)}
        s = secs["G43"]
        a, b = cn.ROCK_WALL
        n = 0
        for p in collision.packs_in(self.bun.read_range(GAME_STREAM, s.offset, s.size), s.offset):
            if p.section != cn.ROCK_WALL_PACK:
                continue
            for pa, pb, _h, _s, _i in collision.barriers(p):
                ra, rb = collision.to_render(pa), collision.to_render(pb)
                if all(self.bun.dist_to_segment(q[:2], a, b) < 0.6 for q in (ra, rb)):
                    n += 1
        self.assertEqual(n, cn.ROCK_WALL_BARRIERS)


if __name__ == "__main__":
    unittest.main()
