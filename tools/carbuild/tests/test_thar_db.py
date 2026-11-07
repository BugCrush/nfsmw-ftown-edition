"""The Thar's database script: python -m unittest discover -s tools/carbuild/tests -p test_thar_db.py

Reads the game's database through an Attribulator unpack of copies of its GLOBAL files (cached under
.superpowers/carbuild/cache; the game folder is only read). The expected numbers below are written out by hand from
the tuned Raptor in the game (raptor.nfsms v2, read back from the unpack on 2026-11-02) and the user's rules, so the
test does not reuse the generator's arithmetic.
"""
import os
import sys
import tempfile
import unittest

from common import GAME, REPO

sys.path.insert(0, os.path.join(REPO, "tools", "x360"))
WHEEL_REPORT = os.path.join(REPO, ".superpowers", "carbuild", "thar", "out", "wheel_report.json")
CACHE = os.path.join(REPO, ".superpowers", "carbuild", "cache")
SCRIPT = os.path.join(REPO, "tools", "cars", "packages", "thar", "thar.nfsms")

RAPTOR_TORQUE = [763.1, 1122.2, 1364.7, 1539.7, 1643.0, 1692.4, 1593.6, 1432.0, 1247.9]
RAPTOR_TORQUE_TOP = [1822.5, 2258.0, 3627.1, 4125.4, 4408.2, 4547.4, 4273.5, 3824.6, 3245.5]
K = 5000.0 / 7000.0
# (class, field, member or None): (raptor stock, raptor top)
SCALED = {
    ("chassis", "SPRING_STIFFNESS", "Front"): (720, 600), ("chassis", "SPRING_STIFFNESS", "Rear"): (710, 600),
    ("chassis", "SHOCK_STIFFNESS", "Front"): (31, 60), ("chassis", "SHOCK_STIFFNESS", "Rear"): (29, 60),
    ("chassis", "SHOCK_EXT_STIFFNESS", "Front"): (51, 80), ("chassis", "SHOCK_EXT_STIFFNESS", "Rear"): (49, 80),
    ("chassis", "SWAYBAR_STIFFNESS", "Front"): (285, 285), ("chassis", "SWAYBAR_STIFFNESS", "Rear"): (275, 275),
    ("brakes", "BRAKES", "Front"): (962, 1531.4), ("brakes", "BRAKES", "Rear"): (1437.8, 1791.4),
    ("brakes", "EBRAKE", None): (1690, 2574),
}


def parse(lines):
    """{(command, class, collection, field, member): value} for update_field lines (member '' when none)."""
    out = {}
    for l in lines:
        w = l.split()
        if w[0] == "update_field":
            if len(w) == 5:
                out[(w[1], w[2], w[3], "")] = w[4]
            elif len(w) == 6:
                out[(w[1], w[2], w[3], w[4])] = w[5]
    return out


class TharDbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import thar_db
        try:
            cls.unpack = thar_db.game_unpack(GAME, CACHE)
        except thar_db.DatabaseUnavailable as e:
            raise unittest.SkipTest(str(e))
        if not os.path.exists(WHEEL_REPORT):
            raise unittest.SkipTest("Part 2's wheel report missing: " + WHEEL_REPORT)
        cls.out = os.path.join(tempfile.mkdtemp(prefix="thar-db-"), "thar.nfsms")
        cls.lines = thar_db.write_script(cls.unpack, WHEEL_REPORT, cls.out)
        cls.v = parse(cls.lines)

    def val(self, cls_, coll, field, member=""):
        key = (cls_, coll, field, member)
        self.assertIn(key, self.v, "no line sets %s" % (key,))
        return float(self.v[key])

    def close(self, got, want, rel=1e-4):
        self.assertAlmostEqual(got, want, delta=abs(want) * rel + 1e-6)

    def test_values(self):
        self.assertEqual(self.val("pvehicle", "thar", "MASS"), 5000)
        for i, t in enumerate(RAPTOR_TORQUE):
            self.close(self.val("engine", "thar", "TORQUE[%d]" % i), 1.25 * t)
        for i, t in enumerate(RAPTOR_TORQUE_TOP):
            self.close(self.val("engine", "thar_top", "TORQUE[%d]" % i), 1.25 * t)
        ratio = 0.3638 / 0.436  # Thar 245/50 R19 radius / Raptor 315/70 R17 radius
        self.close(self.val("transmission", "thar", "FINAL_GEAR"), 5.3 * ratio, 2e-3)
        self.close(self.val("transmission", "thar_top", "FINAL_GEAR"), 4.5 * ratio, 2e-3)
        for (c, f, m), (stock, top) in SCALED.items():
            self.close(self.val(c, "thar", f, m or ""), stock * K)
            self.close(self.val(c, "thar_top", f, m or ""), top * K)
        for stage in ("thar", "thar_top"):
            for axle in ("Front", "Rear"):
                self.assertEqual(self.val("tires", stage, "GRIP_SCALE", axle), 1)
                self.assertEqual(self.val("tires", stage, "SECTION_WIDTH", axle), 245)
                self.assertEqual(self.val("tires", stage, "ASPECT_RATIO", axle), 50)
                self.assertEqual(self.val("tires", stage, "RIM_SIZE", axle), 19)
            self.close(self.val("chassis", stage, "DRAG_COEFFICIENT"), 0.22)
        # wheels as drawn (ecar), from the wheel report: FL, FR, RR, RL
        want = [(1.3237, 0.9366), (1.3237, -0.9366), (-1.0841, -0.9366), (-1.0841, 0.9366)]
        for i, (x, y) in enumerate(want):
            self.close(self.val("ecar", "thar", "TireOffsets[%d]" % i, "X"), x, 1e-3)
            self.close(self.val("ecar", "thar", "TireOffsets[%d]" % i, "Y"), y, 1e-3)
            self.assertEqual(self.val("ecar", "thar", "TireOffsets[%d]" % i, "Z"), 0)
            self.close(self.val("ecar", "thar", "TireOffsets[%d]" % i, "W"), 0.3746, 1e-3)
            self.close(self.val("ecar", "thar", "TireSkidWidth[%d]" % i), 0.2656, 1e-3)
        for part in ("Visual", "Collision", "Collision64"):
            self.assertEqual(self.v[("pvehicle", "thar", "MODEL", part)], "THAR")

    def test_ride_height_93(self):
        """Fix 1 of the first test-copy race: RIDE_HEIGHT 40 lay beyond the suspension's travel (the body floated in
        races); the tuned Raptor's 9.3 on both axles in both stages, the value the wheel report was built for."""
        for stage in ("thar", "thar_top"):
            for axle in ("Front", "Rear"):
                self.assertEqual(self.val("chassis", stage, "RIDE_HEIGHT", axle), 9.3)

    def test_wheels_sit_in_the_arches_in_the_car_select_and_in_races(self):
        """Issue 1 of the second test-copy race. speed.exe draws the wheel centre at z = FECompressions in the car
        select and at z = W - RIDE_HEIGHT*0.0254 + c - RideHeight*0.0254 in races (conventions.py; RIDE_HEIGHT and
        ecar RideHeight in inches, c the spring's rest compression). The model's wheels are at z 0.2816 (wheel report),
        so FECompressions = 0.2816 and ecar RideHeight lowers the drawn body onto the wheels while RIDE_HEIGHT stays
        9.3 (the physics the user drove). Rest compressions by hand, 5,000 kg, springs x 5/7 (lb/in), the Raptor's
        progression and weight bias: stock 53.8% front, 514.3 / 507.1, 7.9 / 7.7 -> 0.0869 / 0.0793 m; top 53%,
        428.6 / 428.6, 10 / 10 -> 0.0908 / 0.0836 m; mean 0.0852. RideHeight = (0.3746 - 9.3*0.0254 + 0.0852 -
        0.2816) / 0.0254 = -2.28 in (game racers use -3.5 .. +3)."""
        import conventions
        for i in range(2):
            self.close(self.val("ecar", "thar", "FECompressions[%d]" % i), 0.2816, 2e-3)
        rh = self.val("ecar", "thar", "RideHeight")
        self.assertAlmostEqual(rh, -2.28, delta=0.03)
        for c in (0.0869, 0.0793, 0.0908, 0.0836):
            z = conventions.race_wheel_centre_z(0.3746, 9.3, c, rh)
            self.assertAlmostEqual(z, 0.2816, delta=0.008, msg="compression %.4f: wheel centre %.4f" % (c, z))
        # the WheelWell clamp (racers' 22.5 in = 0.5715 m) would pull tyre tops at 0.656 m down by 8.5 cm (the code
        # reviewer's finding): the Thar's own is above its tyre top at full bump (front travel 7.5 in: centre rises
        # to 0.2816 + 0.1905 - 0.0869 = 0.3852, top 0.760 m = 29.9 in), so it never clamps
        ww = self.val("ecar", "thar", "WheelWell")
        self.assertGreaterEqual(ww * conventions.INCH, 0.2816 + 0.1905 - 0.0793 + 0.3746)
        self.assertEqual(conventions.wheel_well_drop([0.2816 + 0.3746] * 4, ww), 0.0)

    def test_turns_readily_without_drifting(self):
        """Issue 3 (slow to turn at 120-200 km/h). SuspensionRacer scales the tyres' yaw torque by YAW_SPEED before the
        rigid body turns it, against an inertia scaled by pvehicle TENSOR_SCALE Y; STEERING scales the wheel angle.
        The Thar carried the truck's 0.4 against Y 2.87 (ratio 0.139, as slow as the Elise's 0.12), and the top
        stage's STEERING 0.9. Now YAW_SPEED 0.46 against Y 2.0 (the GTI's, whose collision box the Thar uses):
        ratio 0.23, the 911 Turbo's and the Lancer's; STEERING 1.0 in both stages. YAW_CONTROL (rear grip added in
        proportion to the slide, the truck's anti-drift setting) is kept."""
        for stage in ("thar", "thar_top"):
            self.assertEqual(self.val("tires", stage, "STEERING"), 1)
        self.assertEqual(self.val("pvehicle", "thar", "TENSOR_SCALE", "Y"), 2)
        # YAW_SPEED and YAW_CONTROL moved again after the third race: test_turns_more_at_speed

    def test_turns_more_at_speed(self):
        """Third test-copy race (the user: "damn good. just slightly work on the handling a bit more"): turning at
        120-200 km/h, p90 course rate at full steer, went 23.0 -> 28.4 deg/s (target 34, the Challenger's). The
        Challenger runs YAW_CONTROL [0.06, 0.1, 0.1, 0.15]; the Thar still had the Raptor's [0.3, 0.6, 0.7, 0.95]
        (top [0.5, 0.8, 1.2, 1.5]), rear grip added against slides that grows with speed. A measured step towards the
        Golf/Gallardo range, keeping some anti-slide (the user disliked the truck's drifting): stock [0.2, 0.4, 0.45,
        0.5], top [0.3, 0.5, 0.7, 0.8]; YAW_SPEED 0.46 -> 0.5 (ratio to TENSOR_SCALE Y 2: 0.25)."""
        want = {"thar": (0.2, 0.4, 0.45, 0.5), "thar_top": (0.3, 0.5, 0.7, 0.8)}
        for stage, values in want.items():
            for i, x in enumerate(values):
                self.close(float(self.v[("tires", stage, "YAW_CONTROL[%d]" % i, "")]), x, 1e-6)
            self.assertEqual(self.val("tires", stage, "YAW_SPEED"), 0.5)

    def test_physics_geometry_is_the_thars(self):
        """Ruling (ledger): game cars' chassis WHEEL_BASE, FRONT_AXLE and TRACK_WIDTH match their own ecar wheels, so
        the Thar takes its own (wheelbase 2.408, front axle 1.324, track = 2|Y| - skid = 1.6077)."""
        for stage in ("thar", "thar_top"):
            self.close(self.val("chassis", stage, "WHEEL_BASE"), 2.4078, 1e-3)
            self.close(self.val("chassis", stage, "FRONT_AXLE"), 1.3237, 1e-3)
            for axle in ("Front", "Rear"):
                self.close(self.val("chassis", stage, "TRACK_WIDTH", axle), 1.6077, 1e-3)

    def test_links_and_frontend(self):
        for f in ("engine", "transmission", "tires", "chassis", "brakes"):
            self.assertEqual(self.v[("pvehicle", "thar", "%s[0]" % f, "Collection")], "thar")
            self.assertEqual(self.v[("pvehicle", "thar", "%s[1]" % f, "Collection")], "thar_top")
        self.assertEqual(self.v[("pvehicle", "thar", "induction[1]", "Collection")], "thar_base")
        self.assertEqual(self.v[("pvehicle", "thar", "induction[2]", "Collection")], "thar_top")
        self.assertEqual(self.v[("pvehicle", "thar", "frontend", "Collection")], "thar")
        copies = [l.split() for l in self.lines if l.startswith("copy_node")]
        self.assertIn(["copy_node", "frontend", "raptor", "mahindra", "thar"], copies)
        maker = [w for w in copies if w[1] == "frontend" and w[4] == "mahindra"]
        self.assertEqual(len(maker), 1)
        self.assertGreater(self.val("frontend", "thar", "Cost"), 60000 - 1)  # quicker than the Raptor: not cheaper

    def test_script_resolves_against_game(self):
        import nfsms
        classes = {l.split()[1] for l in self.lines if l.split()[0] in nfsms.DB_COMMANDS + ("copy_node", "add_node")}
        kept, dropped = nfsms.resolve(self.lines, nfsms.load_collections(self.unpack, classes),
                                      nfsms.load_hashed_fields(self.unpack, classes))
        self.assertEqual(dropped, {})
        self.assertEqual(len(kept), len(self.lines))
        # no field the Raptor's collections lack (Attribulator would stop: update_field needs an existing field)
        shapes = nfsms.load_field_shapes(self.unpack, classes)
        for l in self.lines:
            w = l.split()
            if w[0] == "update_field":
                self.assertIn(w[3].partition("[")[0], shapes[w[1]], l)

    def test_written_file_is_the_committed_one(self):
        """The committed tools/cars/packages/thar/thar.nfsms is what the generator writes today."""
        self.assertTrue(os.path.exists(SCRIPT), SCRIPT)
        self.assertEqual(open(self.out, "rb").read(), open(SCRIPT, "rb").read())


if __name__ == "__main__":
    unittest.main()
