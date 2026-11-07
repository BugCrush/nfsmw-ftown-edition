"""The ramp over Rockport's closure at the T (tools/citymap/connector_ramp.py, connector.py; plan
docs/superpowers/plans/2026-11-06-ftown-connector-ramp.md; notes docs/ftown-race-notes.md "The connector ramp").

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_connector_ramp -v

The measurements read the game's track files (read only) and skip without them; the arc study caches what it reads in
.superpowers/research/connection/ramp-study.json (delete it to read the game again).
"""
import math
import os
import sys
import unittest

from tools.citymap.tests import common

sys.path.insert(0, common.TOOLS)
sys.path.insert(0, os.path.join(common.TOOLS, "carbuild"))
from tools.citymap import connector as cn, connector_ramp as cr  # noqa: E402

GAME_STREAM = os.path.join(cn.GAME, "TRACKS", "STREAML2RA.BUN")


class Profile(unittest.TestCase):
    def test_table_both_ways(self):
        """Up from either side to the same flat top (each side its own angle: the F-Town side flatter, the arc study)."""
        r = cr.Ramp()
        for k in range(0, 101):
            a = r.s0 + (r.s1 - r.s0) * k / 100.0
            b = r.s3 - (r.s3 - r.s2) * k / 100.0
            self.assertAlmostEqual(r.z(a), r.z(b), places=6)
        back = (r.z(r.s2 + 0.5) - r.z(r.s2 + 1.5)) / 1.0
        self.assertAlmostEqual(math.degrees(math.atan(back)), cr.BACK_DEG, places=4)
        self.assertAlmostEqual(r.z(r.s0), r.base_z)
        self.assertAlmostEqual(r.z((r.s1 + r.s2) / 2), r.top_z)
        self.assertEqual(r.z(r.s0 - 5.0), r.base_z)
        self.assertEqual(r.z(r.s3 + 5.0), r.base_z)

    def test_lip_angle(self):
        r = cr.Ramp()
        grade = (r.z(r.s1 - 0.5) - r.z(r.s1 - 1.5)) / 1.0
        self.assertAlmostEqual(math.degrees(math.atan(grade)), cr.LIP_DEG, places=4)
        self.assertEqual(r.lip_deg, cr.LIP_DEG)

    def test_top_covers_the_opening(self):
        """The flat top spans the poles (s 9.24..9.78) and the wall line at every d of the opening, 0.2 m to spare."""
        r = cr.Ramp()
        for d in (-8.0, -4.0, 0.0, 4.0, 8.0):
            sw = cr.wall_s(d)
            self.assertLess(r.s1, cr.POLE_S_MIN - 0.2)
            self.assertGreater(r.s2, sw + 0.5, d)

    def test_wing_height(self):
        r = cr.Ramp()
        s = (r.s0 + r.s1) / 2
        self.assertAlmostEqual(r.surface(s, 0.0), r.z(s))
        self.assertAlmostEqual(r.surface(s, 8.0), r.z(s))
        drop = r.z(s) - r.surface(s, 10.0)
        self.assertAlmostEqual(drop, 2.0 * math.tan(math.radians(cr.WING_DEG)), places=6)
        self.assertEqual(r.surface(s, 200.0), r.base_z)


class Arcs(unittest.TestCase):
    """Pure ballistics against a made-up ceiling (known answers)."""

    def test_flat_ceiling_answer(self):
        # launched at 10 degrees, 100 m/s, g = 9.81: height at 50 m = 50 tan10 - g 50^2 / (2 v^2 cos^2)
        x = 50.0
        v = 100.0
        th = math.radians(10.0)
        want = x * math.tan(th) - 9.81 * x * x / (2 * v * v * math.cos(th) ** 2)
        self.assertAlmostEqual(cr.height_at(x, v, 10.0, 9.81), want, places=9)

    def test_peak(self):
        v, th = 50.0, 12.0
        vz = v * math.sin(math.radians(th))
        self.assertAlmostEqual(cr.peak(v, th, 9.81), vz * vz / (2 * 9.81), places=9)


class Closure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(cn.L2RA, GAME_STREAM)
        cls.c = cr.closure(cn.GAME)

    def test_wall_is_the_opened_one(self):
        bars = self.c["barriers"]
        self.assertEqual(len(bars), cn.ROCK_WALL_BARRIERS)
        self.assertTrue(all(b["pack"] == 703 and b["instance"] == 6 for b in bars))
        self.assertAlmostEqual(min(b["z"][0] for b in bars), 201.7, delta=0.1)

    def test_poles_measured(self):
        poles = self.c["smackables"]
        self.assertEqual(len(poles), 3)
        for p in poles:
            self.assertEqual(p["attributes"], "mediummetalpost")
            self.assertAlmostEqual(p["top"], 204.85, delta=0.05)
            self.assertTrue(cr.POLE_S_MIN <= p["s"] <= cr.POLE_S_MAX, p)
        self.assertGreaterEqual(cr.TOP_Z, max(p["top"] for p in poles) + 0.4)

    def test_nothing_else_collides(self):
        self.assertEqual(self.c["faces_above_road"], 0)
        self.assertEqual(self.c["objects"], 0)


class Study(unittest.TestCase):
    """The arcs against the overpass's real underside (the game's drawn surfaces) and the landing."""

    @classmethod
    def setUpClass(cls):
        common.need(cn.L2RA, GAME_STREAM, cn.CITY, cn.CITY_JSON, cn.ROADS)
        cls.p = cn.path()
        cls.study = cr.study(cn.GAME, cls.p)

    def test_overpass_found(self):
        ceil = dict(self.study["ceiling"])
        self.assertLess(min(ceil[s] for s in range(0, 40) if s in ceil), 216.0)
        self.assertGreater(min(ceil[s] for s in range(0, 40) if s in ceil), 212.0)

    def test_roof_never_reaches_the_overpass(self):
        for direction in (1, -1):
            for row in cr.arc_table(self.p, self.study, direction, g=9.81):
                self.assertGreater(row["clearance"], 0.0, (direction, row))

    def test_lands_on_the_deck_between_the_parapets(self):
        for row in cr.arc_table(self.p, self.study, 1, g=9.81):
            self.assertIsNotNone(row["land_s"], row)
            self.assertLess(abs(row["land_d"]), cn.WIDTH / 2 - cr.CAR_HALF_W, row)

    def test_lands_on_rockport_going_south(self):
        for row in cr.arc_table(self.p, self.study, -1, g=9.81):
            self.assertIsNotNone(row["land_s"], row)

    def test_angles_are_near_the_limit(self):
        """Each lip leaves less than 2 degrees unused (a real jump, not a timid one) and at least 0.5 (a margin)."""
        for direction, chosen in ((1, cr.LIP_DEG), (-1, cr.BACK_DEG)):
            best = cr.max_safe_angle(self.p, self.study, g=9.81, direction=direction)
            self.assertLessEqual(chosen, best - 0.5, direction)
            self.assertGreater(chosen, best - 2.0, direction)

    def test_south_lands_on_road_179(self):
        for row in cr.arc_table(self.p, self.study, -1, g=9.81):
            self.assertGreaterEqual(row["land_s"], cr.SOUTH_LAND_MIN, row)


def our_faces(data):
    """[(render vertices, flags byte)] of every face of the connector's collision pack."""
    from chunks import read_chunks
    from world import collision_write, scenery
    from world.collision import to_render
    out = []
    for c, pos in scenery.with_positions(read_chunks(data), 0):
        if c.id != 0x3B801:
            continue
        pk = collision_write.read_pack(c.data, pos)
        for inst in pk.instances:
            art = pk.articles[inst.article]
            t = inst.t
            for st in art.strips:
                pts = [to_render((q[0] - t[0], q[1] - t[1], q[2] - t[2])) for q in st.points()]
                for i in range(len(pts) - 2):
                    out.append((pts[i:i + 3], st.surfaces[i] >> 8))
    return out


class Drawn(unittest.TestCase):
    """The ramp's own geometry over Rockport's road (a flat road at 202.7: no game files needed)."""

    @classmethod
    def setUpClass(cls):
        common.need(cn.CITY, cn.CITY_JSON, cn.ROADS)
        cls.p = cn.path()
        cls.parts = cn.ramp_drawn(cls.p, lambda x, y: cr.BASE_Z)

    def test_vertical_faces_face_outward(self):
        n = 0
        for kind, (tris, _uvs) in self.parts.items():
            for a, b, c in tris:
                u = [b[k] - a[k] for k in range(3)]
                v = [c[k] - a[k] for k in range(3)]
                nrm = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                L = math.sqrt(sum(x * x for x in nrm)) or 1.0
                if abs(nrm[2]) / L > 0.2:
                    self.assertGreater(nrm[2], 0.0, (kind, a, b, c))  # surfaces face up
                    continue
                n += 1
                cx, cy = (a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3
                s, d = cr.to_sd(cx, cy)
                ns, nd = cr.to_sd(cr.JUNCTION[0] + nrm[0], cr.JUNCTION[1] + nrm[1])
                if abs(nd) > abs(ns):
                    self.assertGreater(abs(d), cr.HALF - 0.01, (kind, s, d))
                    self.assertGreater(nd * d, 0.0, (kind, s, d))  # a side: outward
                else:
                    self.assertGreater(ns, 0.0, (kind, s, d))  # the wings' end and the body: north
        self.assertGreater(n, 0)

    def test_parapets_face_their_sides(self):
        """The deck's parapets (the game draws the side a triangle's right-hand normal faces, test_runh): each inner
        face looks at the road, each outer face (the embankment's skirt) away from it."""
        parts = cn.drawn_piece(self.p, 100.0, 120.0, lambda s: False)
        n = 0
        for a, b, c in parts["concrete"][0]:
            u = [b[k] - a[k] for k in range(3)]
            v = [c[k] - a[k] for k in range(3)]
            nrm = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2])
            nz = u[0] * v[1] - u[1] * v[0]
            if abs(nz) > math.hypot(*nrm):
                continue  # the parapet's top
            cx, cy = (a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3
            s = 110.0
            ctr, t = self.p.at(s), self.p.tangent(s)
            d = -(cx - ctr[0]) * t[1] + (cy - ctr[1]) * t[0]
            nd = -nrm[0] * t[1] + nrm[1] * t[0]
            inner = abs(abs(d) - cn.WIDTH / 2) < 0.05
            self.assertEqual(nd * d < 0, inner, (d, nd))
            n += 1
        self.assertGreater(n, 8)

    def test_chevrons_at_the_lip(self):
        tris, _uvs = self.parts["chevron"]
        ss = [cr.to_sd(sum(v[0] for v in t) / 3, sum(v[1] for v in t) / 3)[0] for t in tris]
        r = cr.Ramp()
        self.assertTrue(ss and all(r.s1 - cr.CHEVRON - 0.01 <= s <= r.s1 + 0.01 for s in ss), ss[:5])


class Built(unittest.TestCase):
    """The built ftown-connector.bun / ftown-connect.bin (tools/citymap/connector.py)."""

    @classmethod
    def setUpClass(cls):
        common.need(cn.OUT_BUN, cn.OUT_BIN, cn.CITY, cn.CITY_JSON, cn.ROADS)
        cls.p = cn.path()
        cls.ramp = cr.Ramp()
        cls.faces = our_faces(open(cn.OUT_BUN, "rb").read())
        cls.connect = cn.read_connect(open(cn.OUT_BIN, "rb").read())

    def _sd(self, f):
        return cr.to_sd(sum(v[0] for v in f) / 3, sum(v[1] for v in f) / 3)

    def test_surface_follows_the_profile(self):
        n = 0
        for f, _fl in self.faces:
            s, d = self._sd(f)
            if self.ramp.s0 + 0.2 < s < self.ramp.s3 - 0.2 and abs(d) < cr.HALF - 0.2:
                z = sum(v[2] for v in f) / 3
                want = max(self.p.z(s), self.ramp.z(s)) if s >= 0 else self.ramp.z(s)
                self.assertAlmostEqual(z, want, delta=0.03, msg=(s, d))
                n += 1
        self.assertGreater(n, 20)

    def test_stacked_faces_flagged(self):
        """Every face of ours over Rockport's road (s up to 9.8, wings included) and every ramp face carries flag 4."""
        n = 0
        for f, fl in self.faces:
            s, d = self._sd(f)
            if self.ramp.s0 - 0.5 <= s <= self.ramp.s3 + 0.5 and abs(d) <= cr.HALF + 40:
                self.assertTrue(fl & 4, (s, d, fl))
                n += 1
        self.assertGreater(n, 100)

    def test_wings_drivable(self):
        """Across the carriageway (along d) the surface has no step over 5 cm in 0.25 m and no slope steeper than the
        wing angle (+ 1 degree), from d -40 to 40 at every s of the up-ramp."""
        from tools.citymap.connector_ramp import _Grid
        g = _Grid([f for f, _fl in self.faces], cell=4.0)
        top = math.tan(math.radians(cr.WING_DEG + 1.0))
        s = self.ramp.s0 + 0.5
        while s < cr.WING_END - 0.3:
            prev = None
            d = -40.0
            while d <= 40.0:
                hs = g.heights(cr.straight(s, d))
                z = max(hs) if hs else None
                if z is not None and prev is not None and abs(d) > cr.HALF + 0.3:
                    self.assertLess(abs(z - prev), max(0.05, 0.25 * top + 0.01), (s, d, z, prev))
                prev = z
                d += 0.25
            s += 1.0

    def test_wings_reach_their_end(self):
        """The collision wings run from the ramp's foot to WING_END (as the drawn ones), short of the north wall."""
        ss = [cr.to_sd(v[0], v[1])[0] for f, _fl in self.faces for v in f
              if abs(cr.to_sd(v[0], v[1])[1]) > cr.HALF + 0.5 and cr.to_sd(v[0], v[1])[0] < cr.ROCK_FACES_END]
        self.assertAlmostEqual(max(ss), cr.WING_END, delta=0.05)
        self.assertAlmostEqual(min(ss), self.ramp.s0, delta=1.0)

    def test_wings_inside_rockports_walls(self):
        """No face of ours over Rockport (the wings, the body south of the opened wall) crosses a wall of Rockport's
        that stays shut (pack 703's static barriers at the road's height, the five opened ones and the race walls left
        out)."""
        common.need(cn.L2RA, GAME_STREAM)
        from world import bun, collision
        l2ra, stream = cr._game_paths(cn.GAME)
        g43 = {s.name: s for s in bun.sections(l2ra)}["G43"]
        walls = []
        for pk in collision.packs_in(bun.read_range(stream, g43.offset, g43.size), g43.offset):
            for inst in pk.instances:
                art = pk.articles.get(inst.article)
                if inst.group or art is None:
                    continue
                for b in art.barriers:
                    a, c = collision.to_render(inst.to_world(b.p0)), collision.to_render(inst.to_world(b.p1))
                    if min(a[2], c[2]) > cr.BASE_Z + 0.5 or max(a[2], c[2]) < cr.BASE_Z + 0.5:
                        continue
                    if all(bun.dist_to_segment(q[:2], *cn.ROCK_WALL) < 0.6 for q in (a, c)):
                        continue  # opened
                    walls.append((a[:2], c[:2]))
        self.assertGreater(len(walls), 10)

        def cross(p, q, a, b):
            def o(u, v, w):
                return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
            return (o(a, b, p) > 0) != (o(a, b, q) > 0) and (o(p, q, a) > 0) != (o(p, q, b) > 0)

        bad = []
        for f, _fl in self.faces:
            s, d = self._sd(f)
            if not self.ramp.s0 - 0.5 <= s <= cr.ROCK_FACES_END or max(v[2] for v in f) < cr.BASE_Z + 0.1:
                continue
            for i in range(3):
                for a, b in walls:
                    if cross(f[i][:2], f[(i + 1) % 3][:2], a, b):
                        bad.append((round(s, 2), round(d, 2)))
        self.assertEqual(bad, [])

    def test_connect_file_has_the_face_region(self):
        c = self.connect
        self.assertEqual(c["version"], 2)
        self.assertEqual(len(c["faces"]), 1)
        f = c["faces"][0]
        self.assertEqual(f[0], 703)
        self.assertGreater(f[1], 20)

    def test_region_count_is_the_games(self):
        common.need(cn.L2RA, GAME_STREAM)
        f = self.connect["faces"][0]
        self.assertEqual(cr.region_count(cn.GAME, f), f[1])

    def test_region_covers_the_footprint(self):
        """Every Rockport face under the ramp (any vertex or its centre within the ramp's footprint) is in the region."""
        common.need(cn.L2RA, GAME_STREAM)
        f = self.connect["faces"][0]
        for verts, inside in cr.rock_faces_under(cn.GAME, self.ramp):
            if inside:
                self.assertTrue(cr.in_region(f, verts), verts)


class ConnectFormat(unittest.TestCase):
    def test_v2_round_trip(self):
        walls = [(703, 5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]
        faces = [(703, 99, 10.0, 20.0, 30.0, 40.0, 7.5, 200.0, 205.0)]
        b = cn.pack_connect((1.0, 2.0, 3.0), (0, 0, 1, 1), (703, 226, 723), (726, 723), [703], [2601],
                            [(0, 0), (1, 0), (1, 1)], walls, 1234, faces=faces)
        c = cn.read_connect(b)
        self.assertEqual(c["version"], 2)
        self.assertEqual([tuple(round(x, 3) for x in w) for w in c["faces"]], [faces[0]])
        self.assertEqual(c["bun_size"], 1234)


if __name__ == "__main__":
    unittest.main()
