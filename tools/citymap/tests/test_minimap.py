"""F-Town's minimap (Task 2 of docs/superpowers/plans/2026-11-04-ftown-minimap-timeattack.md): the picture, the 64-chop
texture pack the game's HUD minimap draws, and the calibration FTownLoader gives it.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_minimap -v

How the game's minimap works and why these numbers: docs/ftown-race-notes.md R1. The OSM data is git-ignored; the tests
that need the road model skip without it.
"""
import math
import os
import random
import struct
import sys
import unittest

import numpy as np

from tools.citymap.tests import common

for p in (common.TOOLS, os.path.join(common.TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

INI = os.path.join(common.REPO, "ftown", "FTownLoader.ini")
CITY_JSON = os.path.join(common.REPO, "ftown", "ftown-city.json")


def _cache_image():
    from tools.citymap import minimap
    if "minimap" not in common._cache:
        common._cache["minimap"] = minimap.render(common.model())
    return common._cache["minimap"]


def _on_colours(c, on, tol=6.0):
    """c is one of the colours `on` or a blend of two of them (Run I fixes: the map is anti-aliased, so where the
    route crosses a road or a flyover meets one their colours mix along the edge), within tol per channel."""
    c = np.array(c, float)
    for i, a in enumerate(on):
        for b in on[i:]:
            a_, b_ = np.array(a, float), np.array(b, float)
            d = b_ - a_
            t = 0.0 if not d.any() else float(np.clip(np.dot(c - a_, d) / np.dot(d, d), 0, 1))
            if np.abs(c - (a_ + d * t)).max() <= tol:
                return True
    return False


class CalibrationTests(unittest.TestCase):
    def test_city_edge_box_inside_the_safe_range(self):
        """The game's minimap has no upper bound on the chop number (notes R1): every drivable point must map into
        [1/16, 15/16) on both axes, so the 2 x 2 chops around the car stay in rows and columns 0..7."""
        import json
        from tools.citymap import minimap
        with open(CITY_JSON) as f:
            x0, y0, x1, y1 = json.load(f)["edge_box"]
        for x in (x0, x1):
            for y in (y0, y1):
                mx, my = minimap.to_map(x, y)
                for v in (mx, my):
                    self.assertGreaterEqual(v, 1 / 16)
                    self.assertLess(v, 15 / 16)

    def test_to_map_is_the_games_convert_pos(self):
        """Minimap::ConvertPos 0x567510: x = (x - UL.x) / W, y = (UL.y - y) / W + 1."""
        from tools.citymap import minimap
        ulx, uly, w = minimap.UPPER_LEFT[0], minimap.UPPER_LEFT[1], minimap.WIDTH
        self.assertEqual(minimap.to_map(ulx, uly), (0.0, 1.0))
        self.assertEqual(minimap.to_map(ulx + w, uly + w), (1.0, 0.0))

    def test_ini_carries_the_same_calibration(self):
        """FTownLoader.ini [Minimap] holds the numbers the picture was drawn with."""
        from tools.citymap import minimap
        with open(INI, "rb") as f:
            text = f.read().decode("ascii")
        self.assertIn("\r\nUpperLeftX = %g\r\n" % minimap.UPPER_LEFT[0], text)
        self.assertIn("\r\nUpperLeftY = %g\r\n" % minimap.UPPER_LEFT[1], text)
        self.assertIn("\r\nWidthMetres = %g\r\n" % minimap.WIDTH, text)
        self.assertIn("\r\nHeader = %s\r\n" % minimap.HEADER, text)


class PictureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(common.OSM, common.ROUTE)
        cls.img = _cache_image()
        cls.model = common.model()

    def _pixel(self, x, y):
        from tools.citymap import minimap
        px, py = minimap.to_pixel(x, y)
        return tuple(int(v) for v in self.img[int(py), int(px)])

    def test_size(self):
        from tools.citymap import minimap
        self.assertEqual(self.img.shape, (minimap.SIZE, minimap.SIZE, 3))

    def test_roads_are_road_coloured(self):
        """1,000 points on road centre lines inside the city's edge box (sampled along the roads by length) are road,
        flyover or route colour."""
        import json
        from tools.citymap import minimap
        with open(CITY_JSON) as f:
            x0, y0, x1, y1 = json.load(f)["edge_box"]
        rnd = random.Random(4)
        segs = [(a, b) for r in self.model.roads for a, b in zip(r.points, r.points[1:])]
        cum = np.cumsum([np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]).tolist()
        on = (minimap.ROAD, minimap.FLYOVER)
        n, bad = 0, []
        while n < 1000:
            (ax, ay), (bx, by) = segs[rnd.choices(range(len(segs)), cum_weights=cum)[0]]
            t = rnd.random()
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if not (x0 < x < x1 and y0 < y < y1):
                continue
            n += 1
            c = self._pixel(x, y)
            if not _on_colours(c, on):
                bad.append((round(x), round(y), c))
        self.assertLessEqual(len(bad), 5, "points on roads not road-coloured: %s" % bad[:10])

    def test_off_road_is_not_road_coloured(self):
        """1,000 points at least 30 m from every road centre line inside the city are not road, flyover or route
        colour."""
        import shapely
        from shapely.geometry import LineString, Point
        from tools.citymap import minimap
        lines = shapely.union_all([LineString(r.points) for r in self.model.roads])
        rnd = random.Random(5)
        import json
        with open(CITY_JSON) as f:
            x0, y0, x1, y1 = json.load(f)["edge_box"]
        on = (minimap.ROAD, minimap.FLYOVER, minimap.ROUTE)
        n, bad = 0, []
        while n < 1000:
            x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
            if lines.distance(Point(x, y)) < 30:
                continue
            n += 1
            c = self._pixel(x, y)
            if c in on:
                bad.append((round(x), round(y), c))
        self.assertFalse(bad, "off-road points drawn as road: %s" % bad[:10])

    def test_no_fixed_route_line(self):
        """Run J, item 7: the fixed orange first-route line is gone ("we dont need it": the plugin draws a GPS-style
        course line during races): no pixel of the picture is near the route's orange (run I's: 1.1% of them)."""
        d = np.abs(self.img.astype(int) - np.array((236, 170, 40))).max(-1)
        n = int((d <= 30).sum())
        print("\n  %d route-orange pixels" % n, end="")
        self.assertEqual(n, 0)


    def test_outside_the_city_is_dark(self):
        from tools.citymap import minimap
        self.assertEqual(tuple(int(v) for v in self.img[2, 2]), minimap.OUTSIDE)


class SmoothTests(unittest.TestCase):
    """Run I's item 3: "the minimap map roads look very rough ... very rough irregular looking roads" (screenshots
    105-107): drawn without anti-aliasing at 5 m a pixel, magnified about 2.6 x on the HUD (a chop of 128 texels
    spans 128 of the HUD's 640 x 480 units: SetupMinimap's SectionSize)."""

    @classmethod
    def setUpClass(cls):
        common.need(common.OSM, common.ROUTE)
        cls.img = _cache_image()
        cls.model = common.model()

    def _lum(self):
        return self.img.astype(float) @ np.array([0.299, 0.587, 0.114])

    def test_resolution(self):
        """2.5 m a pixel or finer (chops of 256 texels: the HUD samples a chop by uv, SetupMinimap)."""
        from tools.citymap import minimap
        self.assertLessEqual(minimap.WIDTH / self.img.shape[0], 2.5)
        self.assertEqual(minimap.CHOP * 8, self.img.shape[0])

    def test_edges_antialiased(self):
        """Edge pixels blend the colours either side: 2% or more of the city's pixels are none of the palette's."""
        from tools.citymap import minimap
        pal = np.array([minimap.OUTSIDE, minimap.GROUND, minimap.EDGE, minimap.ROAD, minimap.FLYOVER, minimap.ROUTE])
        d = np.abs(self.img[:, :, None, :].astype(int) - pal[None, None]).sum(-1).min(-1)
        share = float((d > 6).mean())
        print("\n  %.1f%% blended pixels" % (100 * share), end="")
        self.assertGreater(share, 0.02)

    def test_straight_edges_straight(self):
        """Along the 12 longest diagonal straight road pieces (main roads, 15-75 degrees off the axes, 50 m or more),
        the road's edge (luminance crossing halfway between road and edge colour) found every half pixel moves off its
        line by at most 0.5 m on the ground (median of the pieces' standard deviations; run I's map: 1.2 m, stair-steps of
        whole 5 m pixels)."""
        from tools.citymap import minimap
        lum = self._lum()
        H, W = lum.shape
        half = (sum(minimap.ROAD) / 3 + sum(minimap.EDGE) / 3) / 2

        def sample(x, y):
            x0, y0 = int(np.floor(x)), int(np.floor(y))
            fx, fy = x - x0, y - y0
            a = lum[y0:y0 + 2, x0:x0 + 2]
            return (a[0, 0] * (1 - fx) + a[0, 1] * fx) * (1 - fy) + (a[1, 0] * (1 - fx) + a[1, 1] * fx) * fy
        segs = []
        for r in self.model.roads:
            if r.kind not in minimap.WIDE or r.level >= 1:
                continue
            for a, b in zip(r.points, r.points[1:]):
                L = np.hypot(b[0] - a[0], b[1] - a[1])
                ang = np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])) % 90
                if L >= 50 and 15 <= ang <= 75:
                    segs.append((L, a, b, minimap.WIDE[r.kind]))
        segs.sort(key=lambda s: -s[0])
        stds = []
        for L, a, b, wide in segs[:12]:
            pa, pb = np.array(minimap.to_pixel(*a)), np.array(minimap.to_pixel(*b))
            d = (pb - pa) / np.linalg.norm(pb - pa)
            n = np.array([-d[1], d[0]])
            wpx = wide * self.img.shape[0] / minimap.WIDTH / 2
            offs = []
            for t in np.arange(0.25, 0.75, 0.5 / np.linalg.norm(pb - pa)):
                c = pa + (pb - pa) * t
                prof = [sample(*(c + n * s)) for s in np.arange(0, wpx + 4, 0.1)]
                k = next((i for i, v in enumerate(prof) if v < half), None)
                if k is not None:
                    offs.append(k * 0.1)
            if len(offs) > 8:
                offs = np.array(offs)
                med = np.median(offs)
                offs = offs[np.abs(offs - med) < 2.0]  # another road joining
                stds.append(float(offs.std()) * minimap.WIDTH / self.img.shape[0])
        print("\n  %d pieces, edge wobble median %.2f m (max %.2f)" % (len(stds), np.median(stds), max(stds)), end="")
        self.assertGreaterEqual(len(stds), 6)
        self.assertLessEqual(float(np.median(stds)), 0.5)


class PackTests(unittest.TestCase):
    """The texture pack: as the game's own chops are (notes R1; test_race_notes_addresses checks the game's), but 64
    textures FTOWN_MAP_CHOP<n> in one pack, the chunk the city's loader hands to LoadChunks."""

    @classmethod
    def setUpClass(cls):
        from tools.citymap import minimap
        rnd = np.random.default_rng(7)
        cls.img = rnd.integers(0, 256, size=(1024, 1024, 3), dtype=np.uint8)
        cls.img[:512, :512] = (140, 138, 140)
        cls.blob = minimap.pack_bytes(cls.img)

    def test_one_texture_pack_chunk(self):
        from chunks import read_chunks
        top = read_chunks(self.blob)
        self.assertEqual([c.id for c in top], [0xB3300000])
        self.assertEqual(len(self.blob) % 4, 0)

    def test_64_chops_named_and_sized_as_the_games(self):
        from chunks import read_chunks, bstringhash
        from world.texpack import read_pack
        pack = read_pack(read_chunks(self.blob)[0], 8)
        self.assertEqual(len(pack.textures), 64)
        hashes = {t.name_hash for t in pack.textures}
        self.assertEqual(hashes, {bstringhash("FTOWN_MAP_CHOP%d" % n) for n in range(64)})
        for t in pack.textures:
            self.assertEqual(struct.unpack_from("<hhBBB", t.info, 0x44), (128, 128, 7, 7, 0x24))
            self.assertEqual(t.info[0x4E], 1, "one mip level, as the game's chops")
            self.assertEqual(t.comp[0x14:0x18], b"DXT3")
            self.assertEqual(len(t.data), 128 * 128)

    def test_chop_n_is_row_n_div_8_column_n_mod_8(self):
        """Chop 0 is the top-left 128 x 128 of the picture (grey here), chop 63 the bottom-right; DXT3 decoded back
        within the encoder's error."""
        from chunks import read_chunks, bstringhash
        from world.texpack import read_pack
        from tools.citymap import minimap
        pack = read_pack(read_chunks(self.blob)[0], 8)
        by = {t.name_hash: t for t in pack.textures}
        c0 = minimap.dxt3_decode(by[bstringhash("FTOWN_MAP_CHOP0")].data, 128, 128)
        self.assertTrue((np.abs(c0[..., :3].astype(int) - (140, 138, 140)) <= 4).all())
        self.assertTrue((c0[..., 3] == 255).all(), "opaque, as the game's chops")
        c63 = minimap.dxt3_decode(by[bstringhash("FTOWN_MAP_CHOP63")].data, 128, 128)
        err = np.abs(c63[..., :3].astype(int) - self.img[896:, 896:].astype(int)).mean()
        self.assertLess(err, 60)  # random noise: only that the right tile went there (a wrong tile gives about 85)

    def test_chops_an_eighth_of_the_picture(self):
        """A 2,048 picture gives 256-texel chops (Run I fixes: the HUD samples by uv); a 1,024 one stays the size the
        plugin's stand-in test loads (1,059,584 bytes, ftown/tests/run.py)."""
        from chunks import read_chunks
        from world.texpack import read_pack
        from tools.citymap import minimap
        self.assertEqual(len(self.blob), 1059584)
        big = np.zeros((2048, 2048, 3), np.uint8)
        pack = read_pack(read_chunks(minimap.pack_bytes(big))[0], 8)
        for t in pack.textures:
            self.assertEqual(struct.unpack_from("<hhBBB", t.info, 0x44), (256, 256, 8, 8, 0x24))
            self.assertEqual(len(t.data), 256 * 256)

    def test_dxt3_best_endpoints(self):
        """On a picture of blended edges (road grey, edge black and route orange mixed in each block), every block's
        error is at most what the darkest-and-brightest endpoints alone give, and smaller on some."""
        from tools.citymap import minimap
        rnd = np.random.default_rng(3)
        cols = np.array([minimap.ROAD, minimap.EDGE, minimap.ROUTE, minimap.GROUND], float)
        w = rnd.dirichlet((0.3, 0.3, 0.3, 0.3), size=(64, 64))
        img = np.round(w @ cols).astype(np.uint8)
        dec = minimap.dxt3_decode(minimap.dxt3_encode(img), 64, 64)[..., :3].astype(int)
        blk = img.reshape(16, 4, 16, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
        n = np.arange(len(blk))
        lum = blk[..., 0] * 3 + blk[..., 1] * 6 + blk[..., 2]
        old = minimap._fit(blk, blk[n, lum.argmax(1)], blk[n, lum.argmin(1)])[3]
        new = ((dec - img.astype(int)) ** 2).reshape(16, 4, 16, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 48).sum(1)
        print("\n  block error: old endpoints %.0f, best of three %.0f" % (old.mean(), new.mean()), end="")
        self.assertTrue((new <= old).all())
        self.assertLess(new.mean(), old.mean())

    def test_pack_data_is_128_aligned_in_the_file(self):
        """The loaders need the texture data at a multiple of 128 from the buffer's start (FTownLoader's buffer is
        64 KB aligned)."""
        from chunks import read_chunks
        from world.texpack import read_pack
        pack_chunk = read_chunks(self.blob)[0]
        pack = read_pack(pack_chunk, 8)  # raises when the 0x11 run does not end at a multiple of 128
        self.assertEqual(len(pack.textures), 64)


if __name__ == "__main__":
    unittest.main()
