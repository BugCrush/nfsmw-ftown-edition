"""F-Town's events (docs/superpowers/plans/2026-11-04-ftown-events.md Task 1): the Time Attack unchanged as the first
event, a quarter-mile Drag on the DND-KMP Expressway, a Speed Trap on Mathura Road, a Sector Sprint through the
sectors; every route drivable end to end on the built city; ftown/ftown-events.json is the tool's current output.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_events -v

Needs the road model, route 1 and the built city (ftown/ftown-city.bun); skips without them.
"""
import json
import math
import os
import unittest

from tools.citymap.tests import common

ROADS = os.path.join(common.AREA, "ftown-roads.json")
CITY = os.path.join(common.REPO, "ftown", "ftown-city.bun")
COMMITTED = os.path.join(common.REPO, "ftown", "ftown-events.json")
OUT = os.path.join(common.SCRATCH, "events")
from tools.citymap import geo  # noqa: E402

# (written in the frame before the connection's move: geo.moved puts them where the city is now)
MARKET = geo.moved(2124.0, 12553.0)  # Sector 16 Market (OSM way 352291207)
HUDA_PARK = geo.moved(2053.0, 12258.0)  # Dr. Aggarwal's, "beside Sector 16 HUDA Park" (tools/citymap/landmarks/registry.json)
QUARTER_MILE = 402.336


def _seg_heading(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


class EventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(ROADS, common.ROUTE, CITY)
        from tools.citymap import events, roadmodel
        cls.ev = events
        cls.model = roadmodel.RoadModel.load(ROADS)
        cls.events = events.build_all(cls.model)
        cls.by_id = {e["id"]: e for e in cls.events}
        os.makedirs(OUT, exist_ok=True)
        cls.path = os.path.join(OUT, "ftown-events.json")
        events.write(cls.events, cls.path)

    def _roads_of(self, e):
        """The road model's road of each route segment."""
        want = {}
        for r in self.model.roads:
            for a, b in zip(r.keys, r.keys[1:]):
                want[(a, b)] = r
                want[(b, a)] = r
        return [want.get((a, b)) for a, b in zip(e["keys"], e["keys"][1:])]

    def test_course_band_covers_the_drawn_road(self):
        """Run K, item 3 ("the yellow line during race is here, great, but its very thin, make it as thick as the full
        road"): each event's band (one [cx, cy, half] per route point) spans the road the minimap draws across the route
        (tools/citymap/minimap.render: the picture the game shows), both halves of a divided road: every BAND_STEP m
        along the route the band's edges (3 m in) lie on drawn road at 95% of the points or more (never painted over
        the ground), the band is at least the route road's drawn width everywhere, and at render (1846, 8982)
        (screenshot 135) it matches the run of road-coloured texels across the route within BAND_TOL m each side (both
        halves of Lal Bahadur Shastri Marg)."""
        import numpy as np
        from tools.citymap import minimap
        if "minimap_img" not in common._cache:
            common._cache["minimap_img"] = minimap.render(common.model())
        img = common._cache["minimap_img"].astype(int)
        BAND_TOL = 4.0  # m: 1.6 texels of 2.5 m
        BAND_STEP = 10.0
        SCREENSHOT_135 = (1846.0, 8982.0)
        road, fly = np.array(minimap.ROAD), np.array(minimap.FLYOVER)

        def is_road(x, y):
            px, py = minimap.to_pixel(x, y)
            c = img[int(py), int(px)]
            return min(np.abs(c - road).max(), np.abs(c - fly).max()) < 40

        def drawn_run(p, nrm):
            ends = []
            for sgn in (-1, 1):
                d = 0.0
                while d < 60.0 and is_road(p[0] + nrm[0] * sgn * (d + 0.5), p[1] + nrm[1] * sgn * (d + 0.5)):
                    d += 0.5
                ends.append(sgn * d)
            return ends

        checked = {}
        for e in self.events:
            pts, band = e["route"], e["band"]
            self.assertEqual(len(band), len(pts), e["id"])
            good = n = 0
            bad = []
            # every BAND_STEP m along each segment (between its ends: a route point is a junction, where the crossing
            # road lengthens the drawn run), the band interpolated as FTownLoader draws it (FTownCourse.h)
            for i in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[i], pts[i + 1]
                L = math.dist(pts[i], pts[i + 1])
                if L < 1e-3:
                    continue
                nrm = (-(by - ay) / L, (bx - ax) / L)
                for k in range(1, int(L // BAND_STEP) + 1):
                    t = k * BAND_STEP / L
                    if t >= 1.0:
                        break
                    p = (ax + (bx - ax) * t, ay + (by - ay) * t)
                    cx = band[i][0] + (band[i + 1][0] - band[i][0]) * t
                    cy = band[i][1] + (band[i + 1][1] - band[i][1]) * t
                    h = band[i][2] + (band[i + 1][2] - band[i][2]) * t
                    if not is_road(*p):
                        continue
                    c = (cx - p[0]) * nrm[0] + (cy - p[1]) * nrm[1]
                    n += 1
                    # the band's own edges (3 m in: a texel and the anti-aliased edge) on drawn road: the line never spills onto the ground
                    ok = all(is_road(p[0] + nrm[0] * o, p[1] + nrm[1] * o) for o in (c - h + 3.0, c + h - 3.0))
                    good += ok
                    if not ok:
                        bad.append((round(p[0]), round(p[1]), round(c - h, 1), round(c + h, 1)))
                    if e["id"] == "timeattack" and math.dist(p, SCREENSHOT_135) < 12.0:
                        lo, hi = drawn_run(p, nrm)
                        checked[(round(p[0]), round(p[1]))] = (
                            abs((c - h) - lo) <= BAND_TOL and abs((c + h) - hi) <= BAND_TOL, round(c - h, 1),
                            round(c + h, 1), lo, hi)
            print("\n  %s: band on the drawn road at %d of %d points (first misses %s)" % (e["id"], good, n, bad[:4]),
                  end="")
            self.assertGreaterEqual(good, 0.95 * n, e["id"])
            # at least the route road's own drawn width everywhere (the old line was 8 m wide)
            roads = self._roads_of(e)
            for i, (_x, _y, h) in enumerate(band):
                ws = [minimap.WIDE.get(r.kind, minimap.NARROW) for r in roads[max(0, i - 1):i + 1] if r is not None]
                self.assertGreaterEqual(h, max(ws or [minimap.NARROW]) / 2 - 0.01, (e["id"], i))
        # where screenshot 135 was taken: the band is the drawn road from kerb to kerb across both halves
        self.assertTrue(checked)
        for k, v in checked.items():
            self.assertTrue(v[0], "at %s: band %.1f..%.1f, drawn %.1f..%.1f" % (k, v[1], v[2], v[3], v[4]))
            self.assertGreater(v[2] - v[1], 30.0)  # both halves (each drawn 22 m) of Lal Bahadur Shastri Marg

    def test_four_events_in_order(self):
        self.assertEqual([e["id"] for e in self.events], ["timeattack", "drag", "speedtrap", "sprint"])
        self.assertEqual([e["name"] for e in self.events], ["Time Attack", "Drag (DND-KMP Expressway)",
                                                             "Speed Trap (Mathura Road)", "Sector Sprint"])
        for e in self.events:
            self.assertNotIn("$", e["name"])
            self.assertEqual(e["gates"][-1]["type"], "finish")
            self.assertTrue(all(g["type"] != "finish" for g in e["gates"][:-1]))
            self.assertLessEqual(len(e["gates"]), 17)
            s = [g["s"] for g in e["gates"]]
            self.assertEqual(s, sorted(s))
            self.assertEqual(len(e["keys"]), len(e["route"]))

    def test_timeattack_unchanged(self):
        from tools.citymap import route_gates
        e = self.by_id["timeattack"]
        self.assertEqual(e["start"], [3231.43, 10414.57, 101.0, 136.6])
        route = route_gates.route_render(common.ROUTE, common.proj())
        want = route_gates.gates(route)
        self.assertEqual(len(e["gates"]), 8)
        for g, w in zip(e["gates"], want):
            self.assertAlmostEqual(g["x"], round(w["x"], 2), places=6)
            self.assertAlmostEqual(g["y"], round(w["y"], 2), places=6)
            self.assertAlmostEqual(g["heading"], round(w["heading"], 1), places=6)
        self.assertEqual(e["barriers"], "ftown-barriers.bun")
        self.assertEqual(e["best"], "Route1")

    def test_drag_quarter_mile(self):
        e = self.by_id["drag"]
        self.assertEqual([g["type"] for g in e["gates"]], ["finish"])
        self.assertAlmostEqual(e["gates"][0]["s"] - e["start_s"], QUARTER_MILE, places=2)
        roads = self._roads_of(e)
        self.assertTrue(all(r is not None and r.kind == "motorway" and r.level == 0 for r in roads))
        self.assertGreaterEqual(e["length_m"] - e["gates"][0]["s"], 300.0)
        h0 = _seg_heading(e["route"][0], e["route"][1])
        for a, b in zip(e["route"], e["route"][1:]):
            self.assertLess(abs((_seg_heading(a, b) - h0 + 180) % 360 - 180), 3.0)

    def test_speedtrap_cameras(self):
        e = self.by_id["speedtrap"]
        cams = [g for g in e["gates"] if g["type"] == "camera"]
        self.assertGreaterEqual(len(cams), 4)
        self.assertEqual([g["type"] for g in e["gates"]], ["camera"] * len(cams) + ["finish"])
        roads = self._roads_of(e)
        self.assertTrue(all(r is not None and r.name and r.name.startswith("Mathura Road") for r in roads))
        raised = [c for c in cams if self.ev.on_raised(self.model, e, c["s"])]
        self.assertGreaterEqual(len(raised), 1, "no camera on a flyover")

    def test_sprint_is_new(self):
        from shapely.geometry import LineString, Point
        e = self.by_id["sprint"]
        t = self.by_id["timeattack"]
        ta = set(zip(t["keys"], t["keys"][1:])) | set(zip(t["keys"][1:], t["keys"]))
        self.assertFalse(set(zip(e["keys"], e["keys"][1:])) & ta, "the sprint runs along route 1")
        self.assertGreaterEqual(e["length_m"], 2000.0)
        line = LineString(e["route"])
        # the market's blocks (about 45 m across) stand between route 1 and the sprint's road: their centres within
        # 80 m, on two sides (east and north); the park (not in OSM) is passed at its south-east corner
        self.assertLess(line.distance(Point(MARKET)), 80.0)
        self.assertLess(line.distance(Point(*geo.moved(2132.0, 12471.0))), 80.0)
        self.assertLess(line.distance(Point(self.ev.HUDA_PARK_CORNER)), 45.0)
        self.assertLess(line.distance(Point(HUDA_PARK)), 100.0)
        cps = [g for g in e["gates"] if g["type"] == "checkpoint"]
        for k, g in enumerate(cps):
            self.assertAlmostEqual(g["s"] - e["start_s"], 400.0 * (k + 1), places=6)

    def test_routes_drivable(self):
        """Each route from its start to its end every 0.5 m: a face found as a car follows it (the game's query from
        1 m above the last height), no step over 0.3 m, the wheels' query on the same face (2 cm), no city barrier
        across the centre line at the car's height."""
        for e in self.events:
            d = self.ev.drivable(e, CITY)
            print("\n  %s: %d points, %d without a face, max step %.3f m, %d barriers across, heights %.2f..%.2f" % (
                e["id"], d["points"], d["no_face"], d["max_step"], d["barriers_across"], d["z_min"], d["z_max"]))
            self.assertEqual(d["no_face"], 0, e["id"])
            self.assertLess(d["max_step"], 0.3, e["id"])
            self.assertEqual(d["wheels_off"], 0, e["id"])
            self.assertEqual(d["barriers_across"], 0, e["id"])

    def test_starts_on_their_routes(self):
        for e in self.events:
            x, y, _z, h = e["start"]
            p = self.ev.point_at(e["route"], e["start_s"])
            # the Time Attack's start is the city's route-start spawn (build_city places it 0.66 m off the first node)
            near = 1.0 if e["id"] == "timeattack" else 0.02
            self.assertLess(math.dist((x, y), p[:2]), near, e["id"])
            self.assertLess(abs((h - p[2] + 180) % 360 - 180), 1.0 if e["id"] == "timeattack" else 0.1, e["id"])

    def test_menu_text_hashes_not_the_games(self):
        """FTownLoader answers the string lookup for its own text hashes before the game's table (FTownGame.h): none
        of them may be a hash the game's English table holds (it would show our text for one of the game's)."""
        import re
        import struct
        eng = os.path.join(common.REPO, "Need For Speed Most Wanted Black Edition", "LANGUAGES", "English.bin")
        common.need(eng)
        with open(os.path.join(common.REPO, "ftown", "src", "FTownGame.h"), encoding="utf-8") as f:
            src = f.read()
        block = src[src.index("static Text g_texts"):src.index("static char g_modeWhy")]
        hashes = {int(h, 16) for h in re.findall(r"0x([0-9A-F]{8})u", block)}
        self.assertEqual(len(hashes), 4 + 8)
        with open(eng, "rb") as f:
            data = f.read()
        for h in hashes:
            self.assertNotIn(struct.pack("<I", h), data, "0x%08X is in English.bin" % h)

    def test_ini_has_no_gates_any_more(self):
        """The Time Attack's start and gates live in the events file now, not in [TimeAttack]."""
        import re
        with open(os.path.join(common.REPO, "ftown", "FTownLoader.ini"), "rb") as f:
            text = f.read().decode("ascii")
        sec = text[text.index("\r\n[TimeAttack]\r\n"):]
        sec = sec[:sec.index("\r\n[", 5)]
        self.assertFalse(re.findall(r"\r\n(Start|Gate\d+|Finish) =", sec))
        self.assertIn("\r\n[Events]\r\nFile = ftown-events.json\r\n", text.replace(
            text[text.index("\r\n[Events]\r\n") + 12:text.index("File = ftown-events.json")], ""))

    def test_committed_json_is_this_build(self):
        with open(COMMITTED, encoding="ascii") as f, open(self.path, encoding="ascii") as g:
            self.assertEqual(f.read(), g.read(), "ftown/ftown-events.json is not the tool's current output: rerun it")
        with open(COMMITTED, encoding="ascii") as f:
            data = json.load(f)
        self.assertIn("OpenStreetMap", data["note"])


if __name__ == "__main__":
    unittest.main()
