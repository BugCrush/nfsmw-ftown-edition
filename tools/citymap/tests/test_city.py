"""Task 5: tiles, detail levels, textures and the map file.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_city -v

The city is built once per run into .superpowers/citymap/test-out/ftown-city.bun (git-ignored) and every claim is
checked on the written file, read back with Part 1's readers and the height model of the game's query.
"""
import json
import math
import os
import random
import struct
import sys
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Point

from tools.citymap import terrain
from tools.citymap.tests import common

TOOLS = common.TOOLS
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import bstringhash, read_chunks  # noqa: E402
from world import collision, collision_write, heightcheck, scenery, solids, texpack  # noqa: E402
from world.collision import to_physics  # noqa: E402

GAME = os.path.join(common.REPO, "Need For Speed Most Wanted Black Edition")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")
# Rockport's loaded visible sets (tools/citymap/rockport_budget.py over the game's files, 2026-11-03; notes "Stage 2")
ROCKPORT = {"instances_median": 2176, "instances_max": 3449, "meshes_median": 4406, "meshes_max": 6630,
            "triangles_median": 188793, "triangles_max": 343529}
DRAW_RECORDS = 5000  # SceneryDrawInfoTable on PC: 0x994368 .. 0x9A2DC8 (DoCulling 0x731B80), 12 bytes each


def built():
    if "city" not in common._cache:
        from tools.citymap import build_city
        common.need(common.OSM)
        out = os.path.join(common.SCRATCH, "ftown-city.bun")
        info = build_city.build(common.AREA, out)
        with open(out, "rb") as f:
            data = f.read()
        common._cache["city"] = (info, data, out)
    return common._cache["city"]


def chunks_with_pos():
    if "chunks" not in common._cache:
        _info, data, _out = built()
        top = read_chunks(data)
        common._cache["chunks"] = list(scenery.with_positions(top, 0))
    return common._cache["chunks"]


def packs():
    if "packs" not in common._cache:
        out = []
        for c, p in chunks_with_pos():
            if c.id == collision_write.COLLISION_PACK:
                out.append((collision_write.read_pack(c.data, p), collision.read_pack(c.data, p)))
        common._cache["packs"] = out
    return common._cache["packs"]


def heights():
    from tools.citymap import fastheight
    if "fh" not in common._cache:
        common._cache["fh"] = fastheight.HeightModel([w for w, _r in packs()])
    return common._cache["fh"]


def all_barriers():
    """[(a (x, y), b (x, y), bottom z, top z)] in render coordinates, from the written packs."""
    if "bars" not in common._cache:
        out = []
        for _w, ref in packs():
            for pa, pb, _h, _s, _n in collision.barriers(ref):
                ra, rb = collision.to_render(pa), collision.to_render(pb)
                out.append(((ra[0], ra[1]), (rb[0], rb[1]), min(ra[2], rb[2]), max(ra[2], rb[2])))
        common._cache["bars"] = out
    return common._cache["bars"]


def _gz(b):
    """The built ground's z (terrain.ground_z) under a barrier's middle (b: (a, b, ...), render)."""
    return terrain.ground_z((b[0][0] + b[1][0]) / 2.0, (b[0][1] + b[1][1]) / 2.0)


def samples(points, step):
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        L = math.dist(a, b)
        n = max(1, int(math.ceil(L / step)))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return out


class Helpers(unittest.TestCase):
    def test_stripify_keeps_triangles_and_joins(self):
        from tools.citymap import stripify, surfaces
        poly = shapely.box(0, 0, 64, 64).difference(Point(30, 30).buffer(9))
        tris = surfaces.triangulate(poly, 8.0)
        order = stripify.order(tris)
        def canon(t):
            k = t.index(min(t))
            return t[k:] + t[:k]

        self.assertEqual(sorted(map(canon, order)), sorted(map(canon, tris)))
        faces = [tuple(to_physics((p[0] - 11500.0, p[1] + 2000.0, 100.0)) for p in t) for t in order]
        pack = collision_write.make_pack(1100, faces, [], tile=128.0)
        n = sum(len(a.strips) for a in pack.articles)
        print("\n  %d triangles in %d strips" % (len(tris), n))
        self.assertLess(n, len(tris) / 3)

    def test_fastheight_matches_heightcheck(self):
        """The vectorised height model agrees with tools/world/heightcheck.py (2,000 / 2,000 on Rockport) at 2,000
        random points over the city's packs, on and off faces, at ground and on the flyovers."""
        fh = heights()
        rng = random.Random(5)
        ws = [w for w, _r in packs()]
        pts = []
        for _ in range(2000):
            w = rng.choice(ws)
            inst = rng.choice(w.instances)
            pos = (-inst.t[0], -inst.t[1], -inst.t[2])
            x = pos[0] + rng.uniform(-inst.width, inst.width)
            z = pos[2] + rng.uniform(-inst.length, inst.length)
            y = 100.0 + rng.choice([1.0, 1.0, 8.0, 3.0])
            pts.append((x, y, z))
        got = fh.heights(np.array([p[0] for p in pts]), np.array([p[2] for p in pts]), np.array([p[1] for p in pts]))
        agree = 0
        for (x, y, z), g in zip(pts, got):
            best = None
            for w in ws:
                h = heightcheck.height_at(w, x, z, y)
                if h is not None:
                    best = h if best is None or (y - h) < (y - best) else best
            if (best is None and np.isnan(g)) or (best is not None and not np.isnan(g) and abs(best - g) < 1e-3):
                agree += 1
        print("\n  fast height model agrees with heightcheck at %d of %d points" % (agree, len(pts)))
        self.assertEqual(agree, len(pts))


class City(unittest.TestCase):
    def test_file_reads_back(self):
        info, data, _out = built()
        from tools.citymap import x0props
        # the street life's instances name Rockport's X0 models by hash (held by X0, not this file: test_streetlife)
        x0_picks = {int(p["hash"], 16) for p in x0props.load()["picks"].values()}
        # and the breakable poles' X0 street lights and signal masts (tools/citymap/breakables.py, 2026-11-05)
        from tools.citymap import breakables
        x0_picks |= {breakables.solid_hash(r) for r in breakables.ROLES if r != "lantern"}
        kinds = {}
        sections, pack_numbers, solid_hashes, texture_hashes, named = [], [], set(), set(), set()
        for c, p in chunks_with_pos():
            kinds[c.id] = kinds.get(c.id, 0) + 1
            if c.id == texpack.PACK:
                for t in texpack.read_pack(c, p).textures:
                    texture_hashes.add(t.name_hash)
            elif c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        so = scenery.read_solid(k, kp)
                        solid_hashes.add(so.name_hash)
                        named.update(so.textures)
                        for m in so.meshes:
                            self.assertLessEqual(m.triangle_count, solids.MAX_TRIS_PER_MESH)
            elif c.id == scenery.SCENERY_SECTION:
                sc = scenery.read_scenery(c, p)
                sections.append(sc.number)
                for inst in sc.instances:
                    for h in sc.infos[inst.info_index].solid_hashes:
                        if h not in scenery.NO_MODEL and h not in x0_picks:
                            self.assertIn(h, solid_hashes)  # solids come before the sceneries that name them
            elif c.id == collision_write.COLLISION_PACK:
                pack_numbers.append(collision.read_pack(c.data, p).section)
            else:
                self.assertEqual(c.id, 0)
        self.assertTrue(named <= texture_hashes)
        n_top = sum(kinds.values())
        print("\n  %d bytes, %d top-level chunks %s; sections %s; packs %s" % (
            len(data), n_top, {hex(k): v for k, v in kinds.items()}, sections, pack_numbers))
        self.assertLessEqual(n_top, 64)  # UnloadChunks keeps 64 (0x658A4F)
        self.assertEqual(sorted(sections), sorted(pack_numbers))
        for n in sections:
            self.assertIn(n // 100, (11, 14, 21, 23))  # letters K, N, U, W
            self.assertLess(n % 100, 10)
            self.assertNotEqual(n, 2101)  # the slab's
        self.assertEqual(info["sections"], sorted(sections))
        # free in every Rockport table, as the slab's 2101 (tools/world/tests/test_slab.py)
        if os.path.exists(L2RA) and os.path.exists(STREAM):
            from world import bun
            used = {s.number for s in bun.sections(L2RA)} | set(bun.boundaries(L2RA)) | \
                set(bun.drivable_sections(L2RA))
            rp, rsolids, rtex = set(), set(), set()
            for s in bun.sections(L2RA):
                for c, p in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
                    if c.id == collision.COLLISION_PACK:
                        rp.add(collision.read_pack(c.data, p).section)
                    elif c.id == scenery.SCENERY_SECTION:
                        used.add(scenery.read_scenery(c, p).number)
                    elif c.id == scenery.SOLID_LIST:
                        for k, kp in scenery.with_positions(c.children, p):
                            if k.id == scenery.SOLID:
                                rsolids.add(scenery.read_solid(k, kp).name_hash)
                    elif c.id == texpack.PACK:
                        rtex.update(t.name_hash for t in texpack.read_pack(c, p).textures)
            for n in sections:
                self.assertNotIn(n, used | rp)
            self.assertFalse(solid_hashes & rsolids)
            self.assertFalse(texture_hashes & rtex)
        self.assertNotIn(b"aridabad", data.lower())

    def test_written_centrelines_drivable(self):
        """Task 2's coverage test on the written packs: every road's centre line every 1 m has a face at the road's
        height (ground 100 m, ramps and decks by Task 3's profile) within 2 cm, by the game's rule from 1 m above."""
        from tools.citymap import levels
        info, _d, _o = built()
        m = common.model()
        L = common._cache.get("levels") or levels.build(m)
        common._cache["levels"] = L
        outer = info["edge_box"]
        # which raised chain each road segment belongs to: its height is the chain's profile at the point (the
        # profile bends between OSM points), every other segment is at ground
        seg_chain = {}
        for c in L.raised_chains:
            for rid, i, j in c.parts:
                for k in range(min(i, j), max(i, j)):
                    seg_chain[(rid, k)] = c
        xs, ys, zs = [], [], []
        for r in m.roads:
            for k, (a, b) in enumerate(zip(r.points, r.points[1:])):
                c = seg_chain.get((r.id, k))
                n = max(1, int(math.ceil(math.dist(a, b))))
                for q in range(n + 1):
                    x, y = a[0] + (b[0] - a[0]) * q / n, a[1] + (b[1] - a[1]) * q / n
                    if not (outer[0] + 1 < x < outer[2] - 1 and outer[1] + 1 < y < outer[3] - 1):
                        continue
                    xs.append(x)
                    ys.append(y)
                    zs.append(terrain.ground_z(x, y) + (c.z(c.line.project(Point(x, y))) if c is not None else 0.0))
        X, Y, Z = np.array(xs), np.array(ys), np.array(zs)
        got = heights().heights(-Y, X, Z + 1.0)  # physics x = -render y, z = render x
        bad = np.isnan(got) | (np.abs(got - Z) > 0.02)
        print("\n  %d centre-line points of %d roads every 1 m: %d without a face at the road's height"
              % (len(X), len(m.roads), int(bad.sum())))
        if bad.any():
            k = np.nonzero(bad)[0][:5]
            print("  first misses:", [(round(X[i], 2), round(Y[i], 2), round(Z[i], 2), got[i]) for i in k])
        self.assertEqual(int(bad.sum()), 0)

    def _levels(self):
        from tools.citymap import levels
        L = common._cache.get("levels") or levels.build(common.model())
        common._cache["levels"] = L
        return L

    def _elevated_points(self, step=0.5):
        """Render points every `step` m over the elevated surface (decks and ramps) 0.3 m inside its edge."""
        info, _d, _o = built()
        area = self._levels().elevated.buffer(-0.3).intersection(shapely.box(*info["edge_box"]))
        x0, y0, x1, y1 = area.bounds
        X, Y = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
        X, Y = X.ravel(), Y.ravel()
        keep = shapely.contains_xy(area, X, Y)
        return X[keep], Y[keep]

    def test_overlapping_faces_flagged(self):
        """Fault 1 (run G, the fall through the Mathura Road flyover): the wheels' query takes the first face in the
        collider's list unless its surface flags have 4 (WWorldPos::FindClosestFace 0x779170). Rockport sets 4 on
        faces that lie over or under others (3,000 of its unflagged faces sampled: none has another face 2 m above or
        below). Here: wherever two faces of the written file hold one point more than 5 cm apart in height, both carry
        flag 4. Checked at every elevated point (every 0.5 m) and at the centroid of every face."""
        X, Y = self._elevated_points()
        fh = heights()
        bad = 0
        pairs = 0
        for cs in fh.candidates(-Y, X):
            hs = [c[2] for c in cs]
            if len(hs) > 1 and max(hs) - min(hs) > 0.05:
                pairs += 1
                if any(not c[3] & 4 for c in cs):
                    bad += 1
        # every face's centroid (a ground face under a deck that the grid above missed); slivers under 1 dm2 left out:
        # their centroid lies on a neighbour's edge, which holds it too (the query counts edges) without overlapping
        cx, cz = [], []
        for rec in fh.items:
            if len(rec["A"]):
                A, B, C = rec["A"], rec["B"], rec["C"]
                area = 0.5 * np.abs((B[:, 0] - A[:, 0]) * (C[:, 2] - A[:, 2]) - (C[:, 0] - A[:, 0]) * (B[:, 2] - A[:, 2]))
                c = ((A + B + C) / 3.0 - np.asarray(rec["t"])[None, :])[area >= 0.01]
                cx.append(c[:, 0])
                cz.append(c[:, 2])
        cx, cz = np.concatenate(cx), np.concatenate(cz)
        bad_c = 0
        for cs in fh.candidates(cx, cz):
            hs = [c[2] for c in cs]
            if len(hs) > 1 and max(hs) - min(hs) > 0.05 and any(not c[3] & 4 for c in cs):
                bad_c += 1
        print("\n  %d elevated points over another face, %d with an unflagged face; %d face centroids with an "
              "unflagged face over or under another" % (pairs, bad, bad_c))
        self.assertGreater(pairs, 1000)
        self.assertEqual((bad, bad_c), (0, 0))

    def test_wheels_find_the_deck(self):
        """Fault 1: at every elevated point (every 0.5 m, decks and ramps, both carriageways, foot to foot) the wheels'
        query from 0.5 m above the highest face finds that face (within 2 cm), whichever order the collider's list
        holds the faces in (as written and reversed): never the ground below, never nothing."""
        X, Y = self._elevated_points()
        fh = heights()
        top = np.array([max(c[2] for c in cs) if cs else np.nan for cs in fh.candidates(-Y, X)])
        self.assertEqual(int(np.isnan(top).sum()), 0)
        for rev in (False, True):
            got = fh.wheel_heights(-Y, X, top + 0.5, reverse=rev)
            miss = np.isnan(got) | (np.abs(got - top) > 0.02)
            print("\n  %d elevated points, list %s: %d where the wheels find another face (first: %s)" % (
                len(X), "reversed" if rev else "as written", int(miss.sum()),
                [(round(X[i], 2), round(Y[i], 2), round(top[i], 2), got[i]) for i in np.nonzero(miss)[0][:3]]))
            self.assertEqual(int(miss.sum()), 0)
        # along every raised carriageway, foot to foot, every 0.25 m on the centre line and 1 m inside each edge: no
        # gap and no step over 2 cm beyond the climb of the steepest grade (10.5% on a tight curve's inner edge)
        L = self._levels()
        info = built()[0]
        box = shapely.box(*info["edge_box"]).buffer(-1.0)
        worst, n_pts, gaps = 0.0, 0, 0
        inside = L.elevated.buffer(-0.3).intersection(box)
        shapely.prepare(inside)
        for c in L.raised_chains:
            for side in (-1.0, 0.0, 1.0):
                pts = []
                s = 0.0
                while s <= c.length:
                    p = c.line.interpolate(s)
                    q = c.line.interpolate(min(c.length, s + 0.1))
                    r = c.line.interpolate(max(0.0, s - 0.1))
                    dx, dy = q.x - r.x, q.y - r.y
                    n = math.hypot(dx, dy) or 1.0
                    off = side * (min(c.widths) / 2 - 1.0)
                    pts.append((p.x - dy / n * off, p.y + dx / n * off))
                    s += 0.25
                PX = np.array([p[0] for p in pts])
                PY = np.array([p[1] for p in pts])
                ok = shapely.contains_xy(inside, PX, PY)
                if ok.sum() < 2:
                    continue
                # the profile's points on the elevated surface only (where a ground road narrows a low ramp, the
                # offset line leaves it): a step is measured between neighbours 0.25 m apart only
                PX, PY = PX[ok], PY[ok]
                pts = list(zip(PX, PY))
                want = terrain.GROUND_Z + terrain.offsets(PX, PY) + \
                    np.array([c.z(c.line.project(Point(p))) for p in pts])
                got = fh.wheel_heights(-PY, PX, want + 0.5)
                gaps += int(np.isnan(got).sum())
                gap = np.hypot(np.diff(PX), np.diff(PY))
                d = (np.abs(np.diff(got)) - 0.105 * gap)[gap < 0.3]
                if len(d):
                    worst = max(worst, float(np.nanmax(d)))
                n_pts += len(pts)
        print("  along %d raised carriageways: %d points, %d gaps, worst step beyond the grade %.3f m" % (
            len(L.raised_chains), n_pts, gaps, worst))
        self.assertEqual(gaps, 0)
        self.assertLess(worst, 0.02)

    def test_barriers_face_the_road(self):
        """Fault 4 (run G, three automatic resets against the edge walls): a barrier whose flags lack 0x10 stops a body
        only on the side its normal points to (WCollisionMgr::Collide, WCollisionMgr.cpp:774; the normal is the right
        of p0 -> p1 in render coordinates; Rockport has road in front of 6,709 single-sided barriers and behind 51).
        Every single-sided barrier of the written file: never ground at its foot behind it with none in front (the
        drivable side behind is a wall cars pass through). The flyover walls (a car can meet them from the deck and
        from the ground) are two-sided (0x12, as 351 of Rockport's)."""
        info, _d, _o = built()
        fh = heights()
        mids, fronts, backs, lows, two = [], [], [], [], 0
        for w, _ref in packs():
            for inst in w.instances:
                t = inst.t
                for b in w.articles[inst.article].barriers:
                    p0 = (b.p0[0] - t[0], b.p0[1] - t[1], b.p0[2] - t[2])
                    p1 = (b.p1[0] - t[0], b.p1[1] - t[1], b.p1[2] - t[2])
                    L = math.hypot(p1[0] - p0[0], p1[2] - p0[2])
                    if (b.word >> 8) & 0x10:
                        two += 1
                        continue
                    if L < 0.1:
                        continue
                    nx, nz = (p1[2] - p0[2]) / L, -(p1[0] - p0[0]) / L
                    mx, mz = (p0[0] + p1[0]) / 2, (p0[2] + p1[2]) / 2
                    fronts.append((mx + 0.5 * nx, mz + 0.5 * nz))
                    backs.append((mx - 0.5 * nx, mz - 0.5 * nz))
                    lows.append(min(p0[1], p1[1]))
        lows = np.array(lows)

        def ground(pts):
            P = np.array(pts)
            h = fh.heights(P[:, 0], P[:, 1], lows + 1.0)
            return ~np.isnan(h) & (np.abs(h - lows) < 0.3)
        f, bk = ground(fronts), ground(backs)
        wrong = bk & ~f
        walls = [w_ for w_ in self._levels().walls()
                 if shapely.box(*info["edge_box"]).contains(Point((w_.a[0] + w_.b[0]) / 2, (w_.a[1] + w_.b[1]) / 2))]
        print("\n  %d single-sided barriers: %d with the ground behind and none in front (first at physics %s); %d "
              "two-sided, %d flyover walls" % (len(lows), int(wrong.sum()),
                                              [fronts[i] for i in np.nonzero(wrong)[0][:3]], two, len(walls)))
        self.assertEqual(int(wrong.sum()), 0)
        # every flyover wall two-sided; since the landmarks stage also the DND-KMP crash walls, railings and medians
        # (two-sided: met from either carriageway, docs/ftown-notes.md "Landmarks and street furniture")
        self.assertGreaterEqual(two, len(walls))

    def test_no_terrain_bit(self):
        """Fault 2 (run G, black ground in the shadows of our buildings, the walls' dark sides grey): by elimination the
        difference is the ground's exclude bit 0x80, Rockport's terrain bit (render flag 0x2000, drawn in a pass of its
        own, Scenery.cpp:1114). Rockport draws kind-0 ground on non-terrain instances too (0x8000, 0x8040, 0x8200,
        0x8060: 30.7 km2). No instance of ours has 0x80 or 0x200; ground instances have a slot-3 model (the shadow
        and reflection views draw slot 3 for instances without 0x80, DrawAScenery Scenery.cpp:721)."""
        n = 0
        for c, p in chunks_with_pos():
            if c.id != scenery.SCENERY_SECTION:
                continue
            sc = scenery.read_scenery(c, p)
            for inst in sc.instances:
                n += 1
                self.assertFalse(inst.exclude_flags & 0x280, hex(inst.exclude_flags))
                info = sc.infos[inst.info_index]
                if info.name.startswith("FTC_G_"):
                    self.assertNotIn(info.solid_hashes[3], scenery.NO_MODEL)
        self.assertGreater(n, 1000)

    def test_colours_in_rockport_range(self):
        """Fault 3 (run G, too yellow and bright): our textures and vertex colours within Rockport's measured ranges
        (tools/citymap/rockport_colours.py, medians of the decoded mip 0 by name: dirt luminance 62.1 chroma 8.9, grass
        69.8 / 25.4, sidewalk 94.6 / 7.2, concrete 81.3 / 7.8, plaster 85.9 / 7.2; kind-0 vertex colours: non-terrain
        ground (71, 71, 72), walls (59, 59, 58), grey). The written pack's textures decoded as the game reads them."""
        from tools.citymap import textures, tiles
        want = {"earth": (50, 80, 20), "grass": (55, 85, 35), "pavement": (80, 105, 12), "plaster": (70, 100, 18),
                "roof": (70, 100, 20), "concrete": (60, 100, 15)}
        got = {}
        for c, p in chunks_with_pos():
            if c.id != texpack.PACK:
                continue
            for t in texpack.read_pack(c, p).textures:
                for kind, name in textures.NAMES.items():
                    if t.name_hash == bstringhash(name) and kind in want:
                        w, h = struct.unpack_from("<hh", t.info, 0x44)
                        px = np.array(texpack.dxt1_decode(t.data, w, h), dtype=float)
                        lum = float((px @ np.array([0.299, 0.587, 0.114])).mean())
                        chroma = float((px.max(1) - px.min(1)).mean())
                        got[kind] = (round(lum, 1), round(chroma, 1))
        print("\n  luminance, chroma: %s" % got)
        self.assertEqual(sorted(got), sorted(want))
        for kind, (lo, hi, cmax) in want.items():
            self.assertTrue(lo <= got[kind][0] <= hi, (kind, got[kind]))
            self.assertLessEqual(got[kind][1], cmax, kind)
        g = tiles.GROUND_COLOUR
        self.assertEqual(((g >> 16) & 255, (g >> 8) & 255, g & 255), (71, 71, 72))
        for tint in tiles.PLASTER_TINTS:
            col = tiles.colour(tuple(62.0 * 1.05 * k for k in tint))
            ch = [(col >> 16) & 255, (col >> 8) & 255, col & 255]
            self.assertLessEqual(max(ch) - min(ch), 6, tint)

    def test_route_drivable(self):
        """The first route every 0.5 m: a face everywhere, and no barrier across the path at the car's height."""
        common.need(common.ROUTE)
        with open(common.ROUTE) as f:
            route = [common.proj().to_render(a, b) for a, b in json.load(f)["points"]]
        pts = samples(route, 0.5)
        X = np.array([p[0] for p in pts])
        Y = np.array([p[1] for p in pts])
        got = heights().heights(-Y, X, terrain.GROUND_Z + terrain.offsets(X, Y) + 1.0)
        self.assertEqual(int(np.isnan(got).sum()), 0)
        line = LineString(route)
        crossing = [b for b in all_barriers() if b[2] < _gz(b) + 1.5 and b[3] > _gz(b) + 0.2 and
                    line.intersects(LineString(b[:2]))]
        print("\n  route: %d points every 0.5 m, all on a face (%.2f..%.2f m); %d barriers across it" % (
            len(X), float(np.nanmin(got)), float(np.nanmax(got)), len(crossing)))
        self.assertEqual(crossing, [])

    def test_no_barrier_on_road(self):
        """No barrier stands inside a road, a deck or a ramp at the car's height there (walls on a ramp's seam lie on
        its edge; the edge walls cross the roads that leave the area: that is where they end)."""
        from tools.citymap import levels
        info, _d, _o = built()
        L = common._cache.get("levels") or levels.build(common.model())
        common._cache["levels"] = L
        ground = L.ground_polygon.buffer(-0.05)
        shapely.prepare(ground)
        deck = L.elevated.buffer(-0.05)
        shapely.prepare(deck)
        edge = shapely.box(*info["edge_box"]).exterior.buffer(0.05)
        bad = []
        for a, b, lo, hi in all_barriers():
            seg = LineString([a, b])
            if edge.contains(seg):
                continue
            g = _gz((a, b))
            if lo < g + 1.5 and hi > g and ground.intersects(seg):
                bad.append(("ground road", a, b, lo, hi))
            elif deck.intersects(seg):
                mid = seg.interpolate(0.5, normalized=True)
                z = terrain.ground_z(mid.x, mid.y) + L.z_at(mid.x, mid.y)
                if lo < z + 1.5 and hi > z:
                    bad.append(("deck", a, b, lo, hi))
        print("\n  %d barriers; %d inside a road at the car's height" % (len(all_barriers()), len(bad)))
        self.assertEqual(bad[:5], [])

    def test_draw_budget(self):
        info, _d, _o = built()
        tiles = info["tiles"]
        worst_meshes = max(t["meshes_A"] for t in tiles)
        worst_tris = max(t["triangles_A"] for t in tiles)
        print("\n  %d tiles of %d m, %d instances; per tile at most %d meshes, %d triangles (high detail)" % (
            len(tiles), info["tile_m"], info["instances"], worst_meshes, worst_tris))
        self.assertLess(worst_meshes, 40)
        self.assertLess(worst_tris, 0x7FFF)
        # everything loaded at once is fewer instances than Rockport's largest loaded set
        self.assertLessEqual(info["instances"], ROCKPORT["instances_max"])
        for v in info["views"]:
            print("  view from %s: %d instances, %d meshes, %d triangles (high %d tiles, low %d tiles)" % (
                v["name"], v["instances"], v["meshes"], v["triangles"], v["high"], v["low"]))
            # the tiles' instances (the street life's X0 instances take records in the main view only, and are held
            # to the Run H fixes' numbers + 15% by test_streetlife.test_per_view_proxy)
            self.assertLess(v["instances"] - v.get("props", 0), DRAW_RECORDS / 4)
            self.assertLessEqual(v["meshes"], ROCKPORT["meshes_median"])
            self.assertLessEqual(v["triangles"], ROCKPORT["triangles_max"])

    def test_budget_views(self):
        """The landmarks plan's Task 7: the seven viewpoints (the two spawns and five landmarks) against the budget
        (build_city.view_budget: the streets alone at the same spot, docs/ftown-notes.md "Landmarks and street
        furniture"), and the far level: buildings solids with a C model drawn far and in the shadow views."""
        from tools.citymap import build_city
        info, _d, _o = built()
        self.assertEqual([v["name"] for v in info["views"]],
                         ["route start", "route end"] + [p["name"] for p in build_city.VIEWPOINTS])
        for v in info["views"]:
            bm, bt, bi = build_city.view_budget(v["name"])
            print("\n  %-22s %4d instances %5d meshes (budget %4d) %7d triangles (budget %6d)" % (
                v["name"], v["instances"], v["meshes"], bm, v["triangles"], bt), end="")
            self.assertLessEqual(v["meshes"], bm)
            self.assertLessEqual(v["triangles"], bt)
            self.assertLessEqual(v["instances"] - v.get("props", 0), bi)  # street life: test_streetlife
        far = sum(1 for c, p in chunks_with_pos() if c.id == scenery.SOLID_LIST
                  for k, kp in scenery.with_positions(c.children, p)
                  # the far level is the far-atlas model since the Run H fixes ("_F", test_runh.FarLevel)
                  if k.id == scenery.SOLID and scenery.read_solid(k, kp).name.endswith("_F") and
                  scenery.read_solid(k, kp).name.startswith("FTC_B_"))
        print("\n  %d buildings solids with a far level; triangles high %d, far %d" % (
            far, info["totals"]["triangles_A"], info["totals"]["triangles_C"]))
        self.assertGreater(far, 50)

    def test_spawns_on_road(self):
        info, _d, _o = built()
        from tools.citymap import levels
        L = common._cache.get("levels") or levels.build(common.model())
        sp = info["spawns"]
        self.assertEqual([s["name"] for s in sp], ["route start", "route end"])
        for s in sp:
            h = heights().heights(np.array([-s["y"]]), np.array([s["x"]]), np.array([s["z"]]))[0]
            self.assertFalse(np.isnan(h))
            self.assertAlmostEqual(s["z"] - h, 1.0, delta=0.05)
            self.assertTrue(L.ground_polygon.contains(Point(s["x"], s["y"])) or L.elevated.contains(
                Point(s["x"], s["y"])))
        p = common.proj()
        a = p.to_render(28.41461, 77.33109)
        b = p.to_render(28.39993, 77.31195)
        self.assertLess(math.dist(a, (sp[0]["x"], sp[0]["y"])), 1.0)
        self.assertLess(math.dist(b, (sp[1]["x"], sp[1]["y"])), 1.0)

    def test_grid_tags(self):
        """FTownLoader's grid registration modelled (cells a collision instance's circle + 64 m touches, clamped as
        WGrid::GetRowCol): tags per cell reported for Task 6 and Task 8 (Rockport: 21,112 tags in 2,779 cells)."""
        info, _d, _o = built()
        g = info["grid"]
        print("\n  grid: %d instances, %d entries in %d cells; per cell max %d, median %d" % (
            g["instances"], g["entries"], g["cells"], g["max"], g["median"]))
        self.assertLess(g["max"], 400)

    def test_json_committed_numbers(self):
        info, data, out = built()
        with open(os.path.join(os.path.dirname(out), "ftown-city.json")) as f:
            j = json.load(f)
        self.assertEqual(j["bytes"], len(data))
        self.assertEqual(j["sections"], info["sections"])
        self.assertNotIn("aridabad", json.dumps(j).lower())


if __name__ == "__main__":
    unittest.main()
