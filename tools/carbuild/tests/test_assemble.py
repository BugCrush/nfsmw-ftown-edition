"""Assembling the Thar's game files from the preparation folder:
python -m unittest discover -s tools/carbuild/tests -p test_assemble.py

Uses the preparation folder test_prep.py makes (.superpowers/carbuild/thar/test/prep; made here if missing) and the
game's GTI as the donor, read only. Writes .superpowers/carbuild/thar/test/out. Skips without Blender, the source
model or the GTI.
"""
import json
import os
import struct
import subprocess
import sys
import unittest

from common import CARBUILD, GTI_GEOMETRY, GTI_TEXTURES, REPO, SHARED_TEXTURES, need, read
from test_prep import BLENDER, CARBIN, CONFIG, PREP, SOURCE

OUT = os.path.join(REPO, ".superpowers", "carbuild", "thar", "test", "out")
TEST = os.path.join(REPO, ".superpowers", "carbuild", "thar", "test")
PREP_SOURCES = [CONFIG] + [os.path.join(CARBUILD, n) for n in ("blender_prep.py", "conventions.py")]


def fresh_prep(config, folder):
    """Makes the preparation folder when it is missing or older than the config or the preparation code."""
    parts = os.path.join(folder, "parts.json")
    if os.path.exists(parts) and os.path.getmtime(parts) > max(os.path.getmtime(p) for p in PREP_SOURCES + [config]):
        return
    if not (os.path.exists(BLENDER) and os.path.exists(SOURCE)):
        raise unittest.SkipTest("no fresh preparation folder and no Blender/source to make one")
    r = subprocess.run([sys.executable, CARBIN, "prep", config, "--out", folder], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("prep failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])


def assemble_into(config, prep, out):
    r = subprocess.run([sys.executable, CARBIN, "assemble", config, "--prep", prep, "--out", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("assemble failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])


class AssembleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in (GTI_GEOMETRY, GTI_TEXTURES):
            if not os.path.exists(p):
                raise unittest.SkipTest("game file missing: " + p)
        fresh_prep(CONFIG, PREP)
        assemble_into(CONFIG, PREP, OUT)
        from geometry import read_geometry
        from textures import read_textures
        cls.geo = read_geometry(read(os.path.join(OUT, "GEOMETRY.BIN")))
        cls.tex = read_textures(read(os.path.join(OUT, "TEXTURES.BIN")))
        cls.gti = read_geometry(read(GTI_GEOMETRY))
        with open(os.path.join(OUT, "wheel_report.json"), encoding="utf-8") as f:
            cls.report = json.load(f)
        with open(os.path.join(PREP, "parts.json"), encoding="utf-8") as f:
            cls.prep = json.load(f)
        with open(os.path.join(PREP, "wheel.json"), encoding="utf-8") as f:
            cls.wheel = json.load(f)

    def test_reads_back(self):
        from chunks import bstringhash
        from geometry import check
        names = {s.name for s in self.geo.solids}
        want = {"THAR_%s_%s" % (p, l) for p, d in self.prep["parts"].items() for l in d["levels"]}
        borrowed = {s.name for s in self.interior_solids()}  # the interior and driver (their own test below)
        self.assertEqual(names - borrowed, want)
        for s in self.geo.solids:
            if s.name in borrowed:
                continue
            with self.subTest(solid=s.name):
                self.assertEqual(s.name_hash, bstringhash(s.name))
                self.assertEqual(check(s), [])
                tris = sum(m.triangle_count for m in s.meshes())
                self.assertEqual(struct.unpack_from("<I", s.header, 0x14)[0], tris)
                self.assertEqual((s.header[0x19], s.header[0x1A]), (len(s.textures), len(s.shaders)))
                part, lod = s.name[5:-2], s.name[-1]
                cover = 2 if part == self.wheel["tyre_part"] else 0  # the tyre's inner cover (test_tyre_inner_cover)
                self.assertEqual(tris, self.prep["parts"][part]["levels"][lod]["triangles"] + cover)

    def test_header_counts_rule_on_game_solids(self):
        """The rule the assembler writes: solid header +0x14 = triangles, +0x19 / +0x1A = texture / shader counts."""
        ok = [struct.unpack_from("<I", s.header, 0x14)[0] == sum(m.triangle_count for m in s.meshes()) and
              s.header[0x19] == len(s.textures or []) and s.header[0x1A] == len(s.shaders or [])
              for s in self.gti.solids]
        self.assertGreater(sum(ok) / len(ok), 0.98)

    def test_header_density_fields(self):
        """Solid header +0x98 x +0x9C = the solid's triangles on every game solid (GTI: 4.4058 x 326.84 = 1440 on
        BASE_A); the Chiron and Raptor add-ons write (1.0, triangles). Ours must describe our own geometry, not the
        donor's (final review finding 1)."""
        def product_ok(s):
            a, b = struct.unpack_from("<2f", s.header, 0x98)
            t = sum(m.triangle_count for m in s.meshes())
            return abs(a * b - t) <= max(1.0, 0.001 * t)
        game = [product_ok(s) for s in self.gti.solids]
        self.assertGreater(sum(game) / len(game), 0.98)
        borrowed = {s.name for s in self.interior_solids()}
        for s in self.geo.solids:
            self.assertTrue(product_ok(s), s.name)
            if s.name not in borrowed:  # the borrowed interior keeps the game's own figures (same triangles)
                self.assertEqual(struct.unpack_from("<f", s.header, 0x98)[0], 1.0, s.name)

    def test_meshes_within_game_limits(self):
        """No game mesh has more than 1,000 triangles (39,330 meshes in the game's own cars); ours neither."""
        for s in self.geo.solids:
            for m in s.meshes():
                self.assertLessEqual(m.triangle_count, 1000, s.name)
                self.assertGreater(m.triangle_count, 0, s.name)

    def test_every_mesh_has_a_known_shader(self):
        from chunks import bstringhash
        donor = {h for s in self.gti.solids for h in (s.shaders or [])}
        names = {bstringhash(n): n for n in ("CARSKIN", "WINDSHIELD", "RUBBER", "DULLPLASTIC", "CHROME", "MAGSILVER",
                                             "BRAKEDISC", "HEADLIGHTGLASS", "HEADLIGHTREFLECTOR", "BRAKELIGHT",
                                             "BRAKELIGHTGLASS")}
        seen = set()
        for s in self.geo.solids:
            for m in s.meshes():
                h = s.shaders[m.shader_index]
                self.assertIn(h, donor, "%s: shader 0x%08X" % (s.name, h))
                seen.add(names.get(h, hex(h)))
        self.assertIn("CARSKIN", seen)
        self.assertIn("WINDSHIELD", seen)
        self.assertIn("RUBBER", seen)
        body = [s for s in self.geo.solids if s.name == "THAR_KIT00_BODY_A"][0]
        skin = [m for m in body.meshes() if body.shaders[m.shader_index] == bstringhash("CARSKIN")]
        self.assertTrue(skin)
        for m in skin:  # the paint's meshes use the car's skin in every slot, as the GTI's body does
            self.assertEqual({body.textures[k] for k in m.texture_slots}, {bstringhash("THAR_SKIN1")})

    def test_tyre_inner_cover(self):
        """Issue 2 of the second test-copy race (the far-side wheels showed the back of the alloy and the disc). Every
        game racer's tyre solid closes its inner face with a 2-triangle square (shader PLAINNOTHING, the global
        texture 0xE38806E3, flags 0x4080) at the tyre's inner face, centred on the axle, half as wide as about 0.84 of
        the tyre's radius at A and the full radius at the far levels (GTI, Elise). The game turns the left tyres half a
        turn (CarRenderInfo::Render, LeftTireRotateZMatrix 0x9B3600), so a tyre's y-min face is outward on both sides
        and its y-max face (where the cover sits) inward."""
        from chunks import bstringhash
        tyres = [s for s in self.geo.solids if s.name.startswith("THAR_KIT00_FRONT_TIRE_")]
        self.assertTrue(tyres)
        for s in tyres:
            with self.subTest(solid=s.name):
                cover = [m for m in s.meshes() if s.shaders[m.shader_index] == bstringhash("PLAINNOTHING")]
                self.assertEqual(len(cover), 1)
                m = cover[0]
                self.assertEqual(m.triangle_count, 2)
                self.assertEqual(m.flags, 0x4080)
                self.assertEqual({s.textures[k] for k in m.texture_slots}, {0xE38806E3})
                ps = s.positions(m)
                others = [p for n in s.meshes() if n is not m for p in s.positions(n)]
                ymax = max(p[1] for p in others)
                radius = max(max(abs(p[0]), abs(p[2])) for p in others)
                for p in ps:
                    # 2 mm into the tyre from its flat inner sidewall, not in its plane (two surfaces at one depth
                    # flicker; the reviewer's finding), and not beyond it (the game scales the tyre by its box width),
                    # yet behind the whole alloy
                    self.assertAlmostEqual(p[1], ymax - 0.002, delta=0.0005)
                rim = [q for n in s.meshes() if s.shaders[n.shader_index] in (bstringhash("MAGSILVER"),
                                                                              bstringhash("BRAKEDISC"))
                       for q in s.positions(n)]
                self.assertLess(max(q[1] for q in rim), ps[0][1])
                half = max(abs(p[0]) for p in ps)
                self.assertAlmostEqual(half, max(abs(p[2]) for p in ps), delta=0.002)
                # covers the whole alloy (its disc fits in the square) yet its corners stay inside the tyre, so it
                # hides nothing outside the tyre whether or not the global texture masks the corners (the renders,
                # which lack that texture, showed the game-ratio square's corners beside the tyres)
                self.assertGreaterEqual(half, self.report["rim_radius_visible"])
                self.assertLessEqual(half * 2 ** 0.5, radius + 0.001, "half %.3f radius %.3f" % (half, radius))

    def test_indices_valid(self):
        for s in self.geo.solids:
            for m in s.meshes():
                self.assertEqual(m.index_count, 3 * m.triangle_count)
                for t in s.triangles(m):
                    self.assertTrue(all(0 <= i < m.vertex_count for i in t), s.name)
            n = len(s.vertices) // 36
            self.assertEqual(n, sum(m.vertex_count for m in s.meshes()))

    def test_textures(self):
        from chunks import bstringhash
        from textures import read_textures
        have = {t.name_hash for t in self.tex.textures}
        self.assertIn(bstringhash("THAR_SKIN1"), have)
        self.assertIn(bstringhash("THAR_MISC"), have)
        for t in self.tex.textures:
            if t.name != "THAR_INTERIOR":  # the borrowed interior texture keeps its format (its own test)
                self.assertEqual(t.fmt, "A8R8G8B8")
            self.assertEqual(t.codec, "RAWW")
            self.assertEqual(t.name, t.name[:23])
            self.assertTrue(bstringhash(t.name) == t.name_hash or len(t.name) == 23, t.name)
        skin = [t for t in self.tex.textures if t.name == "THAR_SKIN1"][0]
        self.assertEqual(set(skin.data[k:k + 4] for k in range(0, len(skin.data), 4)), {b"\xff\xff\xff\xff"})
        self.assertEqual(self.tex.filename, "Global\\Pipeline\\CarTemplateTextures_THAR.tpk")
        allowed = set(have) | {h for s in self.gti.solids for h in (s.textures or [])}
        if os.path.exists(SHARED_TEXTURES):
            allowed |= {t.name_hash for t in read_textures(read(SHARED_TEXTURES)).textures}
        for s in self.geo.solids:
            for m in s.meshes():
                self.assertIn(s.textures[m.texture_index], allowed, s.name)
                for k in m.texture_slots:
                    h = s.textures[k]
                    self.assertTrue(h in allowed, "%s: slot texture 0x%08X" % (s.name, h))

    def test_brake_light_contrast(self):
        """Issue 4 (tail lights not lighting up). The game swaps BRAKELIGHT_* / BRAKELIGHT_GLASS_* for
        <CAR>_KIT00_BRAKELIGHT(_GLASS)_ON while braking (CarRenderInfo::UpdateLightStateTextures), as built. The GTI's
        glass is more transparent when on (mean alpha 110 -> 70) so its lit lamp behind shows through; the Thar's
        glass got more opaque (200 -> 230) over a lamp only 2.1 x brighter. Now the glass thins when on and the lamp
        behind is bright: the lamp seen through the glass (alpha-blended) is at least 2.5 x as bright when on."""
        from chunks import bstringhash

        def rgba(name):
            t = [t for t in self.tex.textures if t.name_hash == bstringhash(name)][0]
            b, g, r, a = t.data[0:4]
            return r, g, b, a

        def seen(state):
            gr, gg, gb, ga = rgba("THAR_KIT00_BRAKELIGHT_GLASS_" + state)
            lr, lg, lb, _ = rgba("THAR_KIT00_BRAKELIGHT_" + state)
            k = ga / 255.0
            r, g, b = (k * x + (1 - k) * y for x, y in ((gr, lr), (gg, lg), (gb, lb)))
            return 0.3 * r + 0.59 * g + 0.11 * b

        self.assertLess(rgba("THAR_KIT00_BRAKELIGHT_GLASS_ON")[3], rgba("THAR_KIT00_BRAKELIGHT_GLASS_OFF")[3])
        self.assertGreaterEqual(seen("ON") / seen("OFF"), 2.5, "%.1f / %.1f" % (seen("ON"), seen("OFF")))

    def test_light_markers(self):
        """Light flare and exhaust positions (0x13401A markers, 80 bytes: name hash, 3 zeros, a 4x4 matrix) sit on the
        Thar's own lamps, not the GTI's."""
        from chunks import bstringhash
        base = [s for s in self.geo.solids if s.name == "THAR_BASE_A"][0]
        data = [c.data for c in base.other if c.id == 0x13401A][0]
        marks = {struct.unpack_from("<I", data, k)[0]: struct.unpack_from("<3f", data, k + 16 + 48)
                 for k in range(0, len(data), 80)}
        boxes = {s.name: s.bbox for s in self.geo.solids}
        for name, part in (("LEFT_HEADLIGHT", "KIT00_LEFT_HEADLIGHT_GLASS"), ("RIGHT_HEADLIGHT", "KIT00_RIGHT_HEADLIGHT_GLASS"),
                           ("LEFT_BRAKELIGHT", "KIT00_LEFT_BRAKELIGHT_GLASS"),
                           ("RIGHT_BRAKELIGHT", "KIT00_RIGHT_BRAKELIGHT_GLASS")):
            p = marks[bstringhash(name)]
            b = boxes["THAR_%s_A" % part]
            for k in range(3):
                self.assertTrue(b[k] - 0.02 <= p[k] <= b[k + 3] + 0.02, "%s at %s, lamp box %s" % (name, p, b))

    # ---------------------------------------------------------------- the borrowed interior and driver (fix 2)

    def interior_solids(self):
        import interior
        return [s for s in self.geo.solids if interior.is_interior_part(s.name, "THAR")]

    def test_interior_and_driver_levels(self):
        """Every level the donor has, under the Thar's names (the parts list's INTERIOR and DRIVER parts name
        THAR_KIT00_INTERIOR_<LOD> / THAR_KIT00_DRIVER_<LOD> the way the GTI's name GTI_KIT00_...)."""
        from chunks import bstringhash
        from geometry import check
        with open(os.path.join(OUT, "interior_report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        donor = rep["donor"]
        from geometry import read_geometry
        from common import car
        dpack = read_geometry(read(car(donor)))
        want = {"THAR" + s.name[len(donor):] for s in dpack.solids
                if s.name.startswith((donor + "_KIT00_INTERIOR_", donor + "_KIT00_DRIVER_"))}
        got = {s.name for s in self.interior_solids()}
        self.assertEqual(got, want)
        self.assertIn("THAR_KIT00_INTERIOR_A", got)
        self.assertIn("THAR_KIT00_DRIVER_A", got)
        for s in self.interior_solids():
            self.assertEqual(s.name_hash, bstringhash(s.name))
            self.assertEqual(check(s), [], s.name)

    def test_transplant_references_resolve(self):
        """Each borrowed mesh's texture slots and shader index point into its lists, and every texture it names is in
        the Thar's pack (the donor's <DONOR>_INTERIOR, renamed THAR_INTERIOR: the game loads a car's own textures by
        those names), the shared car pack or the game's GLOBAL packs; shaders are the donor's own."""
        import interior
        from chunks import bstringhash
        from common import CARS
        have = {t.name_hash for t in self.tex.textures}
        elsewhere = interior.global_texture_hashes(os.path.join(os.path.dirname(CARS), "GLOBAL"))
        elsewhere |= interior.shared_texture_hashes(CARS)
        with open(os.path.join(OUT, "interior_report.json"), encoding="utf-8") as f:
            donor = json.load(f)["donor"]
        from geometry import read_geometry
        from common import car
        dshaders = {h for s in read_geometry(read(car(donor))).solids for h in (s.shaders or [])}
        self.assertIn(bstringhash("THAR_INTERIOR"), have)
        used_own = set()
        for s in self.interior_solids():
            for m in s.meshes():
                self.assertLess(m.shader_index, len(s.shaders), s.name)
                self.assertIn(s.shaders[m.shader_index], dshaders, s.name)
                for k in m.texture_slots:
                    self.assertLess(k, len(s.textures), s.name)
            for h in s.textures:
                self.assertTrue(h in have or h in elsewhere, "%s: texture 0x%08X" % (s.name, h))
                self.assertNotIn(h, (bstringhash(donor + "_INTERIOR"), bstringhash(donor + "_MISC")), s.name)
                if h in have:
                    used_own.add(h)
        self.assertIn(bstringhash("THAR_INTERIOR"), used_own)
        # the copied texture is the donor's, pixel for pixel
        from textures import read_textures
        dtex = {t.name_hash: t for t in read_textures(read(car(donor, "TEXTURES.BIN"))).textures}
        mine = [t for t in self.tex.textures if t.name_hash == bstringhash("THAR_INTERIOR")][0]
        theirs = dtex[bstringhash(donor + "_INTERIOR")]
        self.assertEqual(mine.data, theirs.data)
        self.assertEqual((mine.width, mine.height, mine.fmt, mine.mipmaps),
                         (theirs.width, theirs.height, theirs.fmt, theirs.mipmaps))
        self.assertEqual(mine.name, "THAR_INTERIOR")

    def test_interior_inside_glasshouse(self):
        """Nothing borrowed reaches outside the Thar's glasshouse: behind its rear window, beyond its side windows,
        under its floor panel, above its roof or forward of its windscreen base (so nothing pokes through the body or
        glass seen from outside)."""
        import interior
        gh = interior.glasshouse(self.geo, "THAR")
        ps = [p for s in self.interior_solids() for m in s.meshes() for p in s.positions(m)]
        self.assertTrue(ps)
        for k in range(3):
            self.assertGreaterEqual(min(p[k] for p in ps), gh[k] - 0.001, "axis %d" % k)
            self.assertLessEqual(max(p[k] for p in ps), gh[k + 3] + 0.001, "axis %d" % k)

    def escaping(self, dy=0.0):
        """{direction: share of the borrowed parts' (level A) vertices, moved dy across, whose ray in that direction
        meets no triangle of the Thar's own level-A shell (body, base, glass, lamps, mirrors)}."""
        import numpy as np
        import interior
        shell, pts = [], set()
        for s in self.geo.solids:
            if not s.name.endswith("_A") or "_TIRE" in s.name:
                continue
            for m in s.meshes():
                ps = s.positions(m)
                if interior.is_interior_part(s.name, "THAR"):
                    pts.update((p[0], p[1] + dy, p[2]) for p in ps)
                else:
                    shell += [(ps[a], ps[b], ps[c]) for a, b, c in s.triangles(m)]
        t = np.array(shell, dtype=np.float64)
        v0, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        out = {}
        for name, d in (("+x", (1, 0, 0)), ("-x", (-1, 0, 0)), ("+y", (0, 1, 0)), ("-y", (0, -1, 0)),
                        ("+z", (0, 0, 1)), ("-z", (0, 0, -1))):
            d = np.array(d, dtype=np.float64)
            h = np.cross(d, e2)
            a = (e1 * h).sum(1)
            ok = np.abs(a) > 1e-12
            f = np.where(ok, 1.0 / np.where(ok, a, 1), 0)
            esc = 0
            for p in pts:
                s_ = np.array(p) - v0
                u = f * (s_ * h).sum(1)
                q = np.cross(s_, e1)
                v = f * (q @ d)
                tt = f * (e2 * q).sum(1)
                if not (ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (tt > 1e-4)).any():
                    esc += 1
            out[name] = esc / len(pts)
        return out

    def test_interior_enclosed_by_the_shell(self):
        """Final review finding 1: the glasshouse box test is the fit's own box. Here every borrowed vertex must lie
        inside the Thar's own shell: a ray from it in each of six directions meets a shell triangle (at most 1% escape
        through seams of the decimated body). The same interior moved 0.3 m sideways must fail this."""
        for name, share in self.escaping().items():
            self.assertLessEqual(share, 0.01, "%s: %.1f%% of the interior's vertices escape" % (name, 100 * share))
        moved = self.escaping(dy=0.3)
        self.assertGreater(moved["+y"], 0.05, moved)

    def test_wheel_report(self):
        import conventions
        r = self.report
        tyre = [s for s in self.geo.solids if s.name == "THAR_KIT00_FRONT_TIRE_A"][0]
        ps = [p for m in tyre.meshes() for p in tyre.positions(m)]
        radius = max(max(p[0] for p in ps) - min(p[0] for p in ps), max(p[2] for p in ps) - min(p[2] for p in ps)) / 2
        width = max(p[1] for p in ps) - min(p[1] for p in ps)
        self.assertAlmostEqual(r["model_radius"], radius, delta=0.01)
        # the game draws the tyre scaled by W / (box length / 2) and TireSkidWidth / box width (box = extents +
        # 0.01 m a side): these values draw the model at its own size
        self.assertAlmostEqual(r["W"], radius + conventions.BOX_MARGIN, delta=0.001)
        self.assertAlmostEqual(r["TireSkidWidth"], width + 2 * conventions.BOX_MARGIN, delta=0.001)
        to = r["TireOffsets"]  # game order: front left, front right, rear right, rear left
        self.assertEqual(len(to), 4)
        self.assertGreater(to[0]["X"], 0)
        self.assertLess(to[2]["X"], 0)
        self.assertGreater(to[0]["Y"], 0)
        self.assertLess(to[1]["Y"], 0)
        self.assertAlmostEqual(to[0]["Y"], -to[1]["Y"], delta=0.005)
        self.assertAlmostEqual(to[3]["Y"], -to[2]["Y"], delta=0.005)
        for t in to:
            self.assertAlmostEqual(t["W"], r["W"], delta=1e-6)
        # no tyre sticks out of the body (Task 1 rule (b)). The source's tyres sit flush with its wheel arches
        # (body side - outer face within 2 mm), and |Y| is the measured face + 1 cm (the game draws the right tyre at
        # |Y| and the left one 2 cm further in), so the right tyres may reach 1 cm past the body's side.
        for i, gap in enumerate(r["body_side_minus_Y"]):
            self.assertGreaterEqual(gap, -0.015, "wheel %d" % i)
        tyre_size = r["physics_tyre"]
        self.assertAlmostEqual(tyre_size["radius"], radius, delta=0.02)
        self.assertAlmostEqual(r["final_gear_ratio_vs_raptor"], tyre_size["radius"] / 0.436, delta=1e-6)


def _markers(solid):
    data = b"".join(c.data for c in solid.other if c.id == 0x13401A)
    return {struct.unpack_from("<I", data, k)[0]: struct.unpack_from("<3f", data, k + 64)
            for k in range(0, len(data), 80)}


class OriginOffsetTests(unittest.TestCase):
    """The Thar's origin (fix 1 of the first test-copy race, plan 2026-11-02-thar-fixes): with the config's
    `ride_height_cm` the model sits against its origin so that the wheel rule (wheel centre z = W - RIDE_HEIGHT/100)
    holds at that ride height; every part, marker and the wheel report move together. Compared with a build of the
    same config without `ride_height_cm` (the old origin: the body's lowest point at z = 0)."""

    @classmethod
    def setUpClass(cls):
        for p in (GTI_GEOMETRY, GTI_TEXTURES):
            if not os.path.exists(p):
                raise unittest.SkipTest("game file missing: " + p)
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        cls.ride = cfg.get("ride_height_cm")
        cfg.pop("ride_height_cm", None)
        os.makedirs(TEST, exist_ok=True)
        old_cfg = os.path.join(TEST, "thar-no-ride-height.json")
        text = json.dumps(cfg, indent=1)
        if not os.path.exists(old_cfg) or open(old_cfg, encoding="utf-8").read() != text:
            with open(old_cfg, "w", encoding="utf-8") as f:
                f.write(text)
        old_prep, old_out = os.path.join(TEST, "prep-old-origin"), os.path.join(TEST, "out-old-origin")
        fresh_prep(old_cfg, old_prep)
        fresh_prep(CONFIG, PREP)
        assemble_into(old_cfg, old_prep, old_out)
        assemble_into(CONFIG, PREP, OUT)
        from geometry import read_geometry
        cls.old = {s.name: s for s in read_geometry(read(os.path.join(old_out, "GEOMETRY.BIN"))).solids}
        cls.new = {s.name: s for s in read_geometry(read(os.path.join(OUT, "GEOMETRY.BIN"))).solids}
        with open(os.path.join(old_out, "wheel_report.json"), encoding="utf-8") as f:
            cls.old_report = json.load(f)
        with open(os.path.join(OUT, "wheel_report.json"), encoding="utf-8") as f:
            cls.report = json.load(f)
        with open(os.path.join(PREP, "parts.json"), encoding="utf-8") as f:
            cls.prep = json.load(f)

    def test_ride_height_is_the_raptors(self):
        self.assertEqual(self.ride, 9.3)
        self.assertEqual(self.report["ride_height_cm"], 9.3)

    def test_offset_moves_everything(self):
        dz = self.prep["origin_z_offset"]
        # derived from the wheels, not typed in: the old wheel centre sat 0.4006 m - W below the rule at 9.3
        self.assertAlmostEqual(dz, self.old_report["ride_height_cm_for_wheel_rule"] / 100 - 0.093, delta=0.002)
        self.assertGreater(dz, 0.25)
        self.assertEqual(set(self.old), set(self.new))
        for name, s in self.new.items():
            o = self.old[name]
            want = 0.0 if "_FRONT_TIRE_" in name else dz  # the tyre model sits on its own axle, not the body's frame
            with self.subTest(solid=name):
                for k in range(6):
                    self.assertAlmostEqual(s.bbox[k], o.bbox[k] + (want if k in (2, 5) else 0.0), delta=1e-4)
                om, nm = _markers(o), _markers(s)
                self.assertEqual(set(om), set(nm))
                for h in om:
                    for k in range(3):
                        self.assertAlmostEqual(nm[h][k], om[h][k] + (want if k == 2 else 0.0), delta=1e-4,
                                               msg="marker 0x%08X" % h)
        self.assertAlmostEqual(self.report["wheel_centre_z"], self.old_report["wheel_centre_z"] + dz, delta=1e-4)
        for a, b in zip(self.report["TireOffsets"], self.old_report["TireOffsets"]):
            self.assertEqual(a, b)  # TireOffsets X, Y, Z, W stay: only the body moves against the origin
        # the rule at the Raptor's ride height puts the wheel centres where the model's wheels are
        self.assertAlmostEqual(self.report["wheel_centre_z"], self.report["W"] - 0.093, delta=0.005)
        self.assertAlmostEqual(self.report["ride_height_cm_for_wheel_rule"], 9.3, delta=0.5)


if __name__ == "__main__":
    unittest.main()
