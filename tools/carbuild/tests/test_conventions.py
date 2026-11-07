"""The game's conventions for a car's origin and wheels, checked on the game's own cars:
python -m unittest discover -s tools/carbuild/tests -p test_conventions.py

Needs the game's car files and its database (unpacked once by Attribulator into a cache under .superpowers/, keyed by
attributes.bin's digest); skips when either is missing.
"""
import os
import statistics
import unittest

from common import CARS, GAME, REPO, car, need, read

# Racers with their own tyre solid, drawn like the Thar will be. 350Z and BMWM3 have no GEOMETRY.BIN of their own.
RACERS = ("GTI", "BMWM3GTR", "CORVETTE", "MUSTANGGT", "RX8", "GALLARDO", "CAMARO", "VIPER", "SUPRA", "CLK500",
          "ELISE", "CTS", "FORDGT", "SLR", "911TURBO", "PUNTO", "A3")


class ConventionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import conventions
        cls.conv = conventions
        if not os.path.isdir(CARS):
            raise unittest.SkipTest("no game cars at " + CARS)
        try:
            cls.db = conventions.load_database(GAME, os.path.join(REPO, ".superpowers", "carbuild", "cache"))
        except conventions.DatabaseUnavailable as e:
            raise unittest.SkipTest(str(e))
        cls.rules = {}

    def rule(self, name):
        if name not in self.rules:
            need(self, car(name))
            from geometry import read_geometry
            self.rules[name] = self.conv.wheel_rule(name, read_geometry(read(car(name))), self.db)
        return self.rules[name]

    def test_convention_holds(self):
        c = self.conv
        for name in RACERS:
            r = self.rule(name)
            with self.subTest(car=name):
                # (a) the tyre model starts at its outer-face plane (y ~ 0) and extends to the side TYRE_SIDE says
                ymin, ymax = r["tyre_y"]
                self.assertLess(abs(ymin), 0.04, "tyre model y starts at %.3f" % ymin)
                self.assertGreater(ymax * c.TYRE_SIDE, 0.15)
                for i, (x, y, z, w) in enumerate(r["offsets"]):
                    # (b) |TireOffsets Y| is the tyre's outer face: the body's side at the wheel lies 0..6 cm
                    # outside it (the A3's flares reach 5.4 cm, the most of these cars)
                    out = r["body_side"][i] - abs(y)
                    self.assertTrue(-0.01 <= out <= 0.06, "wheel %d: body side - |Y| = %.3f" % (i, out))
                    # (c) the front radius W matches the tyre model's radius. The rear wheels use the same front
                    # tyre model (no racer has a REAR_TIRE solid), scaled by W / model radius, so a rear W may differ
                    # (the Viper's rear is 6.5% larger, the Corvette's 3%)
                    if i > 1:
                        continue
                    self.assertLess(abs(w - r["tyre_radius"]) / r["tyre_radius"], 0.05,
                                    "wheel %d: W %.3f, model radius %.3f" % (i, w, r["tyre_radius"]))
                # (d) ORIGIN_Z: the body's lowest point is the origin's height
                self.assertEqual(c.ORIGIN_Z, "body_min")
                self.assertLess(abs(r["body_min_z"]), 0.10, "body lowest z %.3f" % r["body_min_z"])
                # (e) front axle ahead of the origin, rear axle behind
                xs = [o[0] for o in r["offsets"]]
                self.assertGreater(min(xs[0:2]), 0)
                self.assertLess(max(xs[2:4]), 0)
                # ORIGIN_X: the origin is the middle of the body's length (within 20 cm; BMWM3GTR 16 cm)
                self.assertEqual(c.ORIGIN_X, "body_centre")
                self.assertLess(abs(r["body_mid_x"]), 0.20, "body middle x %.3f" % r["body_mid_x"])

    def test_wheel_height_follows_ride_height(self):
        """Part 2's fender fit (not the game's rule, see test_race_and_front_end_agree_on_game_cars): the wheel centre at
        z = W - RIDE_HEIGHT/100 + TireOffsets Z puts the tyre
        tops sit just under the fenders on every racer (median gap a few cm). With the centre at z = W (origin on the
        ground) the median gap would be RIDE_HEIGHT smaller (tyres in the fenders); at z = 0 about 0.25 m larger."""
        gaps = []
        for name in RACERS:
            r = self.rule(name)
            for i, g in enumerate(r["fender_gap"]):
                if g is None:
                    continue
                with self.subTest(car=name, wheel=i):
                    self.assertTrue(-0.10 <= g <= 0.25, "fender gap %.3f" % g)
                gaps.append(g)
        self.assertGreater(len(gaps), 40)
        self.assertTrue(0.0 < statistics.median(gaps) < 0.08, "median fender gap %.3f" % statistics.median(gaps))

    def test_rest_compression_balances_the_spring(self):
        """SuspensionRacer: spring force = k c (1 + progression c), k in lb/in (LBIN2NM); at rest it carries the
        wheel's share of the weight."""
        c = self.conv
        k, p, load = 360.0, 6.3, 3465.0
        x = c.rest_compression(k, p, load)
        self.assertAlmostEqual(k * c.LBIN_TO_NM * x * (1 + p * x), load, delta=0.5)
        self.assertAlmostEqual(c.rest_compression(100.0, 0.0, 1751.268), 0.1, places=6)
        # never past the travel (inches): the spring bottoms out there
        self.assertAlmostEqual(c.rest_compression(1.0, 0.0, 1e6, travel_in=7.0), 7.0 * c.INCH, places=9)

    def test_wheel_well_clamp(self):
        """CarRenderConn::UpdateRenderMatrix (0x74736D..0x747425): if the highest tyre top (centre z + W) is above ecar
        WheelWell (inches; racers inherit 22.5 from `racers`), the body rises by the excess and every tyre drops by it."""
        c = self.conv
        self.assertEqual(c.wheel_well_drop([0.5, 0.656, 0.6], 22.5), 0.656 - 22.5 * c.INCH)
        self.assertEqual(c.wheel_well_drop([0.5, 0.55], 22.5), 0.0)
        self.assertEqual(c.wheel_well_drop([0.9], 0), 0.0)  # 0 switches it off
        self.assertEqual(c.attr(self.db, "ecar", "gti", "WheelWell"), 22.5)  # inherited from racers
        corvette = c.wheel_centres("corvette", self.db)
        self.assertTrue(any(w["clamped"] for w in corvette))

    def test_race_and_front_end_agree_on_game_cars(self):
        """The two placements read from speed.exe agree on the game's own cars, which is how EA set FECompressions:
        race (CarRenderConn tyre matrix z = TireOffsets Z + compression + W - physics radius, with the sim's
        compression = suspension compression - RIDE_HEIGHT + physics radius, RIDE_HEIGHT in inches, and the body
        raised by ecar RideHeight inches): z = Z + W - RIDE_HEIGHT*0.0254 + c - RideHeight*0.0254, c the spring's rest
        compression; car select (0x737AD0): z = Z + FECompressions. Over the racers the two differ by a median of
        under 2.5 cm (the old fender-fit rule W - RIDE_HEIGHT/100 differs by about 6 cm)."""
        diffs, old = [], []
        for name in RACERS + ("RX7", "TT", "SL500", "CAYMANS", "DB9", "MURCIELAGO", "GTO", "IS300"):
            for w in self.conv.wheel_centres(name.lower(), self.db):
                diffs.append(abs(w["race"] - w["fe"]))
                old.append(abs(w["old"] - w["fe"]))
        self.assertGreater(len(diffs), 90)
        self.assertLess(statistics.median(diffs), 0.025, "median |race - fe| %.3f" % statistics.median(diffs))
        self.assertGreater(statistics.median(old), 2 * statistics.median(diffs))

    def test_semi_is_drawn_from_a_centred_tyre(self):
        """The SEMI (traffic) keeps its tyre model centred on the hub plane, unlike every racer: the racers' rule is
        the one the Thar follows."""
        r = self.rule("SEMI")
        ymin, ymax = r["tyre_y"]
        self.assertLess(ymin, -0.2)
        self.assertGreater(ymax, 0.2)

    def test_game_places_left_tyre_inward_by_its_width(self):
        """speed.exe 0x74F221..0x74F235 with the box widths from 0x755C4A: right wheel y = Y + k*y_m, left wheel
        y = Y - skid + k*y_m, k = skid / box width (box = extents + 0.01 m a side). A racer's tyre lands on
        |y| in [|Y| - skid, |Y|] on both sides, to within a few cm."""
        r = self.rule("GTI")
        for i, (x, y, z, w) in enumerate(r["offsets"]):
            lo, hi = self.conv.tyre_span(y, r["skid"][i], r["tyre_y"])
            self.assertAlmostEqual(hi, abs(y), delta=0.03)
            self.assertAlmostEqual(lo, abs(y) - r["skid"][i], delta=0.03)

    def test_truck_breaks_the_rule(self):
        """Why the Longnose Cab's wheels looked wrong: its TireOffsets put the tyres' outer faces outside its body at
        the wheels (body side - |Y| < 0), the right-hand tyres land further out than the left by the placement above,
        and its body reaches 0.18 m below the origin (the chassis is under the road at ride height 7 cm)."""
        r = self.rule("LONGNOSECAB")
        for i, (x, y, z, w) in enumerate(r["offsets"]):
            self.assertLess(r["body_side"][i] - abs(y), -0.02, "wheel %d" % i)
        right = self.conv.tyre_span(r["offsets"][1][1], r["skid"][1], r["tyre_y"])
        left = self.conv.tyre_span(r["offsets"][0][1], r["skid"][0], r["tyre_y"])
        self.assertGreater(right[1] - left[1], 0.02)
        self.assertLess(r["body_min_z"], -0.10)


if __name__ == "__main__":
    unittest.main()
