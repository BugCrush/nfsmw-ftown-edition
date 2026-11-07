"""Run I's city faults (docs/ftown-notes.md "Run I fixes: the city side (2026-11-05)"), each checked on the written
city file (the one test_city builds, or FTOWN_CITY: run I's own is kept as
.superpowers/citymap/runI-fixes/before/ftown-city.bun, on which every test here fails).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_runi -v

Items (the user's numbers): 1 the dummy cars (immovable walls), 2 unreadable billboards, 4 the junipers, 11 the dead
street ground.
"""
import math
import os
import struct
import unittest

import numpy as np

from tools.citymap import terrain
from tools.citymap.tests import common
from tools.citymap.tests import test_runh as R

from world import collision_write, scenery  # noqa: E402  (test_runh puts tools/ on the path)


def instances():
    """[(info name, solid hashes, matrix (4 x 4))] of every scenery instance of the written file."""
    if "runi_inst" not in common._cache:
        out = []
        for c, p in R.chunks():
            if c.id == scenery.SCENERY_SECTION:
                sc = scenery.read_scenery(c, p)
                for inst in sc.instances:
                    info = sc.infos[inst.info_index]
                    out.append((info.name, tuple(info.solid_hashes), np.array(inst.matrix, dtype=float)))
        common._cache["runi_inst"] = out
    return common._cache["runi_inst"]


def barriers():
    """[(a, b, bottom, top)] render, of every collision barrier of the written file."""
    if "runi_bars" not in common._cache:
        out = []
        for pack in R.packs():
            for inst in pack.instances:
                t = inst.t
                art = pack.articles[struct.unpack_from("<H", inst.raw, 0x1A)[0]]
                for bar in art.barriers:
                    a = (bar.p0[0] - t[0], bar.p0[2] - t[2])
                    b = (bar.p1[0] - t[0], bar.p1[2] - t[2])
                    out.append(((a[1], -a[0]), (b[1], -b[0]), bar.p0[1] - t[1], bar.p1[1] - t[1]))
        common._cache["runi_bars"] = out
    return common._cache["runi_bars"]


def _components(mask):
    """The number of 4-connected components of a boolean mask."""
    import collections
    seen = np.zeros_like(mask)
    h, w = mask.shape
    n = 0
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        n += 1
        seen[y, x] = True
        q = collections.deque([(y, x)])
        while q:
            a, b = q.popleft()
            for c, d in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if 0 <= c < h and 0 <= d < w and mask[c, d] and not seen[c, d]:
                    seen[c, d] = True
                    q.append((c, d))
    return n


def lum(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def rel_lum(rgb):
    """WCAG relative luminance of sRGB 0..255."""
    c = np.asarray(rgb, dtype=float) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


class DummyCars(unittest.TestCase):
    """Item 1: "some dummy cars are not real cars and are immovable wall like obstructions" (screenshots 109, 110,
    118): the street life's parked cars, SUVs, autos and e-rickshaws were solid rings."""

    def test_no_solid_dummy_vehicles(self):
        """No parked vehicle of ours taller than a two-wheeler (scooter 1.16 m, motorbike 1.05 m; a hatchback is 1.53
        m), and no collision barrier stands on any of them."""
        import shapely
        w = R.written()
        sel = np.array([str(n).startswith("FTV_") for n in w["inst"]])
        P = w["P"][sel]
        if len(P):
            z = P[..., 2] - R.gz(P[..., 0], P[..., 1])
            top = float(z.max())
        else:
            top = 0.0
        foot = shapely.union_all([shapely.Polygon(t[:, :2]).buffer(0.05) for t in P
                                  if abs(shapely.Polygon(t[:, :2]).area) > 1e-6]) if len(P) else shapely.Polygon()
        shapely.prepare(foot)
        on = sum(1 for a, b, _lo, _hi in barriers()
                 if foot.contains(shapely.Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
        print("\n  %d vehicle triangles, highest %.2f m over the ground; %d barriers on them" % (len(P), top, on))
        self.assertLessEqual(top, 1.35)
        self.assertEqual(on, 0)


class Billboards(unittest.TestCase):
    """Item 2: "some boards are still not readable" (screenshots 106, 107, all in F-Town (Evening)): abstract text
    bars, and bright designs under the evening's raised vertex colour blown out to white."""

    def _designs(self):
        from tools.citymap import textures
        atlas = R.textures_by_name()["FTC_FURNITURE"]
        h, w = atlas.shape[:2]
        out = []
        for k in range(textures.BILLBOARDS):
            u0, v0, u1, v1 = textures.billboard_rect(k)
            out.append(atlas[int(round(v0 * h)):int(round(v1 * h)), int(round(u0 * w)):int(round(u1 * w))])
        return out

    def test_billboards_readable(self):
        """Every design (as written, DXT1 decoded) holds lettering: at least 20 separate strokes of one colour that
        stands 3:1 or more against its background (WCAG contrast), covering 6% or more of the design; the atlas has
        at least 35 pixels per metre of board (10 m across; run I's: 19-26)."""
        from tools.citymap import textures
        for k, d in enumerate(self._designs()):
            self.assertGreaterEqual(d.shape[1] / 10.0, 35.0, "design %d: %d px across 10 m" % (k, d.shape[1]))
            spec = textures.BILLBOARD_ADS[k]
            ink = np.linalg.norm(d.astype(float) - np.array(spec["ink"], float), axis=-1) < 40
            bg = np.linalg.norm(d.astype(float) - np.array(spec["bg"], float), axis=-1) < 40
            strokes = _components(ink)
            hi, lo = sorted((rel_lum(spec["ink"]), rel_lum(spec["bg"])), reverse=True)
            contrast = (hi + 0.05) / (lo + 0.05)
            print("\n  design %d %r: ink %.1f%%, background %.1f%%, %d strokes, contrast %.1f" % (
                k, spec["text"][0], 100 * ink.mean(), 100 * bg.mean(), strokes, contrast), end="")
            self.assertGreaterEqual(ink.mean(), 0.06)
            self.assertGreaterEqual(bg.mean(), 0.25)
            self.assertGreaterEqual(strokes, 20)
            self.assertGreaterEqual(contrast, 3.0)

    def test_board_evening_not_blown(self):
        """In the evening a board's face (texture x the evening vertex colour) is no brighter than the market shop
        fronts' (FTC_STREET x the shop colour), which stayed readable in run I (screenshot 118); by day each design's
        mean luminance is 85-115 (the shop fronts' 99.5)."""
        from tools.citymap import evening
        street = R.textures_by_name()["FTC_STREET"]
        shop = float(lum(street).mean()) * float(lum(evening.CLASSES["shop"][1])) / 255.0
        for k, d in enumerate(self._designs()):
            m = float(lum(d).mean())
            ev = m * float(lum(evening.CLASSES["board"][1])) / 255.0
            print("\n  design %d: mean luminance %.1f, evening %.1f (shop fronts %.1f)" % (k, m, ev, shop), end="")
            self.assertLessEqual(ev, shop)
            self.assertTrue(85.0 <= m <= 115.0, m)


JUNIPERS = {0x75A66D2F, 0x599A9467}  # XT_CT_JUNIPERA_1B_00, XT_CT_JUNIPERROWA_1B_00
FALL_TREES = {0x00D6DA46: 30.1, 0x468929B4: 25.4, 0x8327AAA3: 29.9}  # FALLTREE2D, FALLTREED, FALLTREES: box top (m)


class Trees(unittest.TestCase):
    """Item 4: "the tree in front looks very good, while the others look very weird" (screenshot 119): the junipers
    standing in for Ashoka trees; more real-looking different trees of the same species."""

    def test_no_junipers(self):
        n = sum(1 for _n, hs, _m in instances() if hs[0] in JUNIPERS)
        print("\n  %d juniper instances" % n)
        self.assertEqual(n, 0)

    def test_trees_vary(self):
        """At least three of X0's whole fall trees (the user's good one and its two siblings), each used 100 times or
        more; tree heights (box top x the matrix's z scale) spread 1.4 x or more between the 5th and 95th
        percentiles; leans 0.3-3 degrees on most, never past 3; every axis of each matrix of one length (within 1%:
        a uniform scale, no shear)."""
        trees = [(hs[0], m) for _n, hs, m in instances() if hs[0] in FALL_TREES]
        use = {h: sum(1 for t, _m in trees if t == h) for h in FALL_TREES}
        heights, leans, bad = [], [], 0
        for h, m in trees:
            rows = np.linalg.norm(m[:3, :3], axis=1)
            if rows.max() - rows.min() > 0.01 * rows.mean():
                bad += 1
            heights.append(FALL_TREES[h] * rows[2])
            z = m[2, :3] / rows[2]
            leans.append(math.degrees(math.acos(min(1.0, z[2]))))
        heights, leans = np.array(heights), np.array(leans)
        p5, p95 = np.percentile(heights, [5, 95])
        print("\n  %d fall trees %s; heights %.1f..%.1f m (5..95%%); leans median %.2f max %.2f deg; %d sheared" % (
            len(trees), {"%08X" % k: v for k, v in use.items()}, p5, p95, np.median(leans), leans.max(), bad))
        self.assertTrue(all(v >= 100 for v in use.values()), use)
        self.assertGreaterEqual(p95 / p5, 1.4)
        # (the rotation is stored as s16 / 8192: a lean reads back within about 0.007 degrees of the one placed; after
        # the connection's move one tree's 3.0 degrees read 3.0016)
        self.assertLessEqual(leans.max(), 3.0 + 0.01)
        self.assertGreater(np.median(leans), 0.3)
        self.assertEqual(bad, 0)


GROUND_KINDS = ("FTC_EARTH", "FTC_GRASS", "FTC_PAVER", "FTC_LOT")


def earth_vertices():
    """(positions (n, 2) render, colours (n, 3)) of every vertex of the written file's FTC_EARTH meshes (slot 0)."""
    if "runi_earth" not in common._cache:
        from chunks import bstringhash
        from tools.citymap import textures
        want = bstringhash(textures.NAMES["earth"])
        sols, P, C = {}, [], []
        scs = []
        for c, p in R.chunks():
            if c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        so = scenery.read_solid(k, kp)
                        sols[so.name_hash] = so
            elif c.id == scenery.SCENERY_SECTION:
                scs.append(scenery.read_scenery(c, p))
        for sc in scs:
            for inst in sc.instances:
                so = sols.get(sc.infos[inst.info_index].solid_hashes[0])
                if so is None:
                    continue
                m = np.array(inst.matrix, dtype=float)
                for mesh in so.meshes:
                    if so.textures[mesh.texture_slots[0]] != want:
                        continue
                    st = so.stride(mesh.buffer)
                    raw = np.frombuffer(so.vertex_buffers[mesh.buffer], dtype=np.uint8, count=mesh.vertex_count * st,
                                        offset=mesh.vertex_offset * st).reshape(mesh.vertex_count, st)
                    pos = raw[:, 0:12].copy().view("<f4").astype(float)
                    P.append((pos @ m[:3, :3] + m[3, :3])[:, :2])
                    C.append(raw[:, 24:27][:, ::-1].astype(int))  # stored B, G, R, A
        common._cache["runi_earth"] = (np.concatenate(P), np.concatenate(C))
    return common._cache["runi_earth"]


class Ground(unittest.TestCase):
    """Item 11: "the street ground looks very dead": one plain earth texture everywhere off the roads."""

    def test_dusty_verges(self):
        """The earth's vertices on a ground carriageway's or pavement's edge (within 0.3 m) carry the dusty verge
        colour (tiles.DUST_RGB, within 2 levels), 95% of them; those 4 m or more away the ground grey."""
        import shapely
        from tools.citymap import levels, surfaces, tiles
        P, C = earth_vertices()
        L = levels.build(common.model())
        edge = shapely.union_all([L.ground_polygon, surfaces.pavements(common.model(), {0: L.ground_polygon})])
        rnd = np.random.default_rng(1)
        k = rnd.choice(len(P), size=min(len(P), 40000), replace=False)
        d = shapely.distance(edge, shapely.points(P[k]))
        dust = (np.abs(C[k] - np.array(tiles.DUST_RGB)) <= 2).all(1)
        grey = (np.abs(C[k] - np.array([(tiles.GROUND_COLOUR >> s) & 255 for s in (16, 8, 0)])) <= 2).all(1)
        on, far = d < 0.3, d > tiles.DUST_W + 0.5
        print("\n  %d earth vertices sampled: %d on a road's edge, %.1f%% of them dusty; %d far, %.1f%% grey" % (
            len(k), on.sum(), 100 * dust[on].mean(), far.sum(), 100 * grey[far].mean()))
        self.assertGreater(on.sum(), 1000)
        self.assertGreaterEqual(dust[on].mean(), 0.95)
        self.assertGreaterEqual(grey[far].mean(), 0.95)

    def test_ground_varied(self):
        """Paved forecourts and worn lots are drawn (each over 2,000 m2); around Sector 16 Market (150 m) three or more
        ground kinds; the earth is drawn at 32 px a metre or finer; every ground texture's mean luminance 55-100
        (Rockport's ground: dirt 62, grass 70, sidewalk 94.6)."""
        from tools.citymap import build_city
        w = R.written()
        tex = R.textures_by_name()
        area = {k: float(w["area"][w["tex"] == k].sum()) for k in GROUND_KINDS}
        vp = [v for v in build_city.VIEWPOINTS if v["name"] == "Sector 16 Market"][0]
        c = w["P"].mean(1)
        near = np.hypot(c[:, 0] - vp["x"], c[:, 1] - vp["y"]) < 150.0
        kinds = sorted(set(str(t) for t in w["tex"][near]) & set(GROUND_KINDS))
        means = {k: float(lum(tex[k]).mean()) for k in GROUND_KINDS if k in tex}
        print("\n  areas %s; at Sector 16 Market %s; means %s" % (
            {k: round(v) for k, v in area.items()}, kinds, {k: round(v, 1) for k, v in means.items()}))
        for k in ("FTC_PAVER", "FTC_LOT"):
            self.assertGreater(area[k], 2000.0, k)
        self.assertGreaterEqual(len(kinds), 3)
        from tools.citymap import textures
        self.assertGreaterEqual(textures.SIDES["earth"] / textures.TILE_M["earth"][0], 32.0)
        for k, m in means.items():
            self.assertTrue(55.0 <= m <= 100.0, (k, m))


if __name__ == "__main__":
    unittest.main()
