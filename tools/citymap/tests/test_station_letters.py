"""Run J, item 2 (docs/ftown-notes.md "Run J: the city side"): the stations' lettering laid out where neither the
viaduct (deck, piers, portals) nor a station's roof, columns or stairs hides it from the road, and their names as
raised block letters (tools/citymap/station_letters.py).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_station_letters -v
"""
import math
import unittest

import numpy as np

from tools.citymap.tests import common
from tools.citymap.tests.test_landmarks import resolved

HIDDEN_MOST = 0.04  # of (point, road viewpoint) pairs a lettering line may be hidden (far piers: 1-3%)


def built():
    """(viaduct, stations, landmarks, ground) built with every station face drawn."""
    if "stations_drawn" not in common._cache:
        import json
        import shapely
        from tools.citymap import buildings, levels, metro, station_letters
        from tools.citymap.tests.test_landmarks import DETAILS
        common.need(DETAILS)
        with open(DETAILS, encoding="utf-8") as f:
            details = json.load(f)
        m = common.model()
        L = common._cache.get("levels") or levels.build(m)
        common._cache["levels"] = L
        outer = buildings.edge_box(common.proj(), (28.385, 77.305, 28.420, 77.332))
        lms = [lm for lm in resolved() if lm.kind == "station"]
        v = metro.viaduct(details, common.proj(), L, outer, stations=[lm.footprint for lm in lms])
        st = metro.stations(lms, v, L, details, common.proj(), set(station_letters.TEXTS))
        common._cache["stations_drawn"] = (v, st, lms, L.ground_polygon)
    return common._cache["stations_drawn"]


def occluders(v, st):
    """The viaduct's triangles and the stations' own but their walls (the drawn faces, the finish) and letters."""
    out = [t for p in v.parts.all() for t in p.tris]
    for s in st:
        out += [t for p in s.parts.all() if not (p.kind.startswith("FTL_") or p.kind.startswith("stn_") or
                                                 p.kind == "paint") for t in p.tris]
    return out


def faces(lms):
    from tools.citymap import landmarks, phototex
    for lm in lms:
        for f in lm.faces:
            p, q = landmarks.edges(lm.footprint)[f.edge_index]
            yield lm, phototex.texture_name(f.name), f, p, q


def line_hidden(name, f, p, q, eyes, occ, lines):
    from tools.citymap import station_letters as SL
    out = []
    saved = SL.TEXTS[name]
    try:
        for ln in lines:
            SL.TEXTS[name] = [ln]
            pts = SL.lettering_points(name, f, p, q, f.z[0], f.z[1], 24)
            h, n = SL.hidden_share(pts, eyes, occ)
            out.append((ln, h / max(1, n)))
    finally:
        SL.TEXTS[name] = saved
    return out


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v, cls.st, cls.lms, cls.ground = built()
        cls.occ = occluders(cls.v, cls.st)

    def test_no_lettering_hidden_from_the_road(self):
        """Every line of lettering on the stations' faces (raised names and the painted plaques and boards) is hidden
        from at most HIDDEN_MOST of the (point, viewpoint) pairs: points on its ink, viewpoints on the ground roads
        12-110 m in front of the face, at most 70 degrees off its normal, 1.3 m up."""
        from tools.citymap import station_letters as SL
        worst = []
        for lm, name, f, p, q in faces(self.lms):
            if name not in SL.TEXTS or not SL.TEXTS[name]:
                continue
            eyes = SL.viewpoints(p, q, self.ground)
            self.assertGreater(len(eyes), 30, name)
            for ln, share in line_hidden(name, f, p, q, eyes, self.occ, SL.TEXTS[name]):
                worst.append((share, name, ln.text))
        worst.sort(reverse=True)
        print("\n  most hidden: %s" % ", ".join("%s %.1f%%" % (n[8:], 100 * s) for s, n, _t in worst[:4]), end="")
        self.assertLessEqual(worst[0][0], HIDDEN_MOST, worst[0])

    def test_run_i_layout_was_hidden(self):
        """The same measure on Run I's Neelam Chowk Ajronda layout (the names across the face's middle, screenshot 131:
        "the metro carrier way goes through the name of the metro station"): its Hindi lines hidden from 15% or more."""
        from tools.citymap import station_letters as SL
        from tools.citymap.station_letters import Line
        old = [Line("लखानी अरमान", (0.14, 0.27, 0.86, 0.36), SL.NEELAM_BLUE, SL.DEVA),
               Line("नीलम चौक अजरौंदा", (0.10, 0.38, 0.90, 0.47), SL.NEELAM_BLUE, SL.DEVA)]
        for lm, name, f, p, q in faces(self.lms):
            if not name.startswith("FTL_STN_NEELAM"):
                continue
            res = line_hidden(name, f, p, q, SL.viewpoints(p, q, self.ground), self.occ, old)
            print("\n  run I %s: %s" % (name[8:], ", ".join("%.0f%%" % (100 * s) for _l, s in res)), end="")
            for _ln, share in res:
                self.assertGreaterEqual(share, 0.15)

    def test_no_pier_at_a_station(self):
        """No pier's cap or portal leg within STATION_CLEAR of a station (Run I: one stood in Bata Chowk's north end,
        6 cm out of its face, its cap 30 cm, in front of the lettering)."""
        from shapely.geometry import Polygon
        from tools.citymap import metro
        for ring in self.v.pier_boxes:
            for lm in self.lms:
                self.assertGreater(lm.footprint.distance(Polygon(ring)), metro.STATION_CLEAR - 0.3)


class Letters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v, cls.st, cls.lms, cls.ground = built()

    def _parts(self, s):
        from tools.citymap import station_letters as SL
        return [p for p in s.parts.all() if p.kind == SL.KIND]

    def test_one_part_a_station_near_levels(self):
        """Each station's raised letters are one part (merged) on FTC_PAINT, in the near levels only."""
        from tools.citymap import parts as P
        for s in self.st:
            ps = self._parts(s)
            self.assertEqual(len(ps), 1, s.name)
            self.assertEqual(ps[0].levels, P.DETAIL)
            self.assertEqual(len(ps[0].tris), s.letter_tris)

    def test_few_triangles_a_glyph(self):
        """60 triangles a glyph or fewer on average (front and sides; Old Faridabad's names repeat every 24 m along its
        138 m side: six copies), and the stations' letters 40,000 triangles in all or fewer."""
        from tools.citymap import station_letters as SL
        total = sum(s.letter_tris for s in self.st)
        glyphs = 0
        for lm, name, f, p, q in faces(self.lms):
            copies = len(SL.placements(f, p, q, *f.z))
            glyphs += copies * sum(len(ln.text.replace(" ", "")) for ln in SL.TEXTS.get(name, ()) if ln.raised)
        print("\n  %d letter triangles, %d glyphs, %.0f a glyph; %s" % (
            total, glyphs, total / glyphs, {s.name: s.letter_tris for s in self.st}), end="")
        self.assertLessEqual(total / glyphs, 60)
        self.assertLessEqual(total, 40000)
        for s in self.st:
            self.assertGreater(s.letter_tris, 500, s.name)

    def test_raised_out_of_the_wall_and_lit(self):
        """Every letter vertex stands 0..DEPTH out of its face's wall (outside), the fronts DEPTH out facing out; the
        sides' shading differs from the fronts' (pre-lit by the sun, parts.lit); the evening classes set."""
        from tools.citymap import evening, station_letters as SL
        from tools.citymap import parts as P
        walls = []
        for lm, name, f, p, q in faces(self.lms):
            if any(ln.raised for ln in SL.TEXTS.get(name, ())):
                L = math.dist(p, q)
                walls.append((lm.key, p, ((q[0] - p[0]) / L, (q[1] - p[1]) / L), L, f.z))
        for s in self.st:
            part = self._parts(s)[0]
            mine = [w for w in walls if w[0] == s.key]
            fronts = sides = 0
            front_cols, side_cols = set(), set()
            for t, c in zip(part.tris, part.cols):
                best = None
                for _k, p, d, L, z in mine:
                    n = (d[1], -d[0])
                    out = [(v[0] - p[0]) * n[0] + (v[1] - p[1]) * n[1] for v in t]
                    along = [(v[0] - p[0]) * d[0] + (v[1] - p[1]) * d[1] for v in t]
                    if all(-1e-4 <= o <= SL.DEPTH + 1e-4 for o in out) and all(-1e-3 <= a <= L + 1e-3 for a in along) \
                            and all(z[0] - 1e-3 <= v[2] <= z[1] + 1e-3 for v in t):
                        best = (n, out)
                        break
                self.assertIsNotNone(best, "a letter triangle off its face (%s)" % s.name)
                n, out = best
                nn = P.normal(t)
                if all(abs(o - SL.DEPTH) < 1e-4 for o in out):
                    fronts += 1
                    self.assertGreater(nn[0] * n[0] + nn[1] * n[1], 0.999)
                    front_cols.add(c & 0xFFFFFF)
                else:
                    sides += 1
                    self.assertLess(abs(nn[0] * n[0] + nn[1] * n[1]), 1e-3)
                    side_cols.add(c & 0xFFFFFF)
                self.assertIn(c >> 24, {a for k, (a, _rgb) in evening.CLASSES.items() if k.startswith("letters_")})
            self.assertGreater(fronts, 100, s.name)
            self.assertGreater(sides, fronts, s.name)
            self.assertTrue(side_cols - front_cols, "the sides are lit as the fronts (%s)" % s.name)

    def test_every_line_whole_on_its_wall(self):
        """The review: in every copy of a repeated face each raised line's box ends before the wall does (Old
        Faridabad's 138.3 m side has six copies every 24 m, the last 18.3 m: its English name was cut)."""
        from tools.citymap import station_letters as SL
        n = 0
        for lm, name, f, p, q in faces(self.lms):
            L = math.dist(p, q)
            for s0, w in SL.placements(f, p, q, *f.z):
                for ln in SL.TEXTS.get(name, ()):
                    if not ln.raised:  # (a painted line runs on, cut by the wall's end as the texture is)
                        continue
                    self.assertLessEqual(s0 + ln.box[2] * w, L + 1e-6, "%s %s at %.1f m" % (name, ln.text, s0))
                    n += ln.raised
        print("\n  %d raised lines placed whole" % n, end="")
        self.assertGreater(n, 15)

    def test_sides_face_out_of_their_glyph(self):
        """The review: a side's normal points out of its glyph: 2 mm along it from the side's middle, at mid depth,
        is outside every glyph of that line (checked in the line's own plane)."""
        import shapely
        from tools.citymap import station_letters as SL
        from tools.citymap import parts as P
        bad = total = 0
        for lm, name, f, p, q in faces(self.lms):
            L = math.dist(p, q)
            d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
            n = (d[1], -d[0])
            part = SL.KIND
            ps = P.PartSet()
            SL.letters(name, f, p, q, f.z[0], f.z[1], ps.get(part))
            tris = ps.get(part).tris
            if not tris:
                continue
            # the fronts' union in (s, z) of the wall: a glyph's area
            fronts = [shapely.Polygon([((v[0] - p[0]) * d[0] + (v[1] - p[1]) * d[1], v[2]) for v in t]) for t in tris
                      if all(abs((v[0] - p[0]) * n[0] + (v[1] - p[1]) * n[1] - SL.DEPTH) < 1e-4 for v in t)]
            ink = shapely.union_all([g.buffer(1e-6) for g in fronts])
            for t in tris:
                out = [(v[0] - p[0]) * n[0] + (v[1] - p[1]) * n[1] for v in t]
                if all(abs(o - SL.DEPTH) < 1e-4 for o in out):
                    continue
                nn = P.normal(t)
                mid = [sum(v[i] for v in t) / 3 for i in range(3)]
                s = (mid[0] - p[0]) * d[0] + (mid[1] - p[1]) * d[1] + 0.002 * (nn[0] * d[0] + nn[1] * d[1])
                z = mid[2] + 0.002 * nn[2]
                total += 1
                bad += ink.contains(shapely.Point(s, z))
        print("\n  %d sides, %d facing into their glyph" % (total, bad), end="")
        self.assertGreater(total, 1000)
        self.assertEqual(bad, 0)

    def test_face_sizes_for_the_shadows(self):
        """station_letters.FACE_M (the painted shadows' shapes) is each drawn face's size on its built wall."""
        from tools.citymap import station_letters as SL
        seen = set()
        for lm, name, f, p, q in faces(self.lms):
            if name not in SL.FACE_M:
                continue
            seen.add(name)
            w = f.width_m if f.repeat else min(f.width_m or math.dist(p, q), math.dist(p, q))
            self.assertAlmostEqual(SL.FACE_M[name][0], w, delta=0.3, msg=name)
            self.assertAlmostEqual(SL.FACE_M[name][1], f.z[1] - f.z[0], delta=0.01, msg=name)
        self.assertEqual(seen, set(SL.FACE_M))

    def test_texture_leaves_the_raised_names_out(self):
        """The drawn faces carry no ink of a raised line (it is geometry now), only its shadow: in each raised line's
        box at most 1% of the texels near the letters' colour."""
        from tools.citymap import landmark_tex, station_letters as SL
        for name, lines in SL.TEXTS.items():
            raised = [ln for ln in lines if ln.raised]
            if not raised:
                continue
            w, h = (256, 256) if "NEELAM" in name else (256, 128) if name.endswith("BATA_N") else (512, 256)
            img = landmark_tex.PAINTERS[name](w, h, 1).astype(int)
            for ln in raised:
                u0, v0, u1, v1 = ln.box
                crop = img[int(v0 * h):int(v1 * h), int(u0 * w):int(u1 * w)]
                near = (np.abs(crop - np.array(ln.rgb)).max(-1) <= 20).mean()
                self.assertLessEqual(near, 0.01, "%s %s: %.1f%%" % (name, ln.text, 100 * near))


if __name__ == "__main__":
    unittest.main()
