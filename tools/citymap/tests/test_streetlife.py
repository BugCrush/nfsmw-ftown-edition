"""Street life Task 3: trees, bushes, benches, bus shelters and bins (Rockport's X0 models, referenced by name hash) and
our own parked vehicles, placed by the city builder (tools/citymap/streetlife.py), checked on the written city file.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_streetlife -v

FTOWN_CITY=<file> points the file checks at any built city (as test_runh); the placement record (base heights of the
parked vehicles) comes from the build itself.
"""
import collections
import math
import os
import unittest

import numpy as np
import shapely

from tools.citymap.tests import common
from tools.citymap.tests.test_runh import barriers, chunks, height_at, written, _spawns

from world import scenery  # noqa: E402  (test_runh put tools/ on the path)

GAME = os.path.join(common.REPO, "Need For Speed Most Wanted Black Edition")


def lanes():
    """The carriageways (ground and raised) and the raised ones alone, from the road model."""
    if "sl_lanes" not in common._cache:
        from tools.citymap import levels
        L = common._cache.get("levels") or levels.build(common.model())
        common._cache["levels"] = L
        common._cache["sl_lanes"] = (shapely.union_all([L.ground_polygon, L.elevated]), L.elevated)
    return common._cache["sl_lanes"]


def file_solids_and_instances():
    if "sl_inst" not in common._cache:
        sols, out = set(), []
        for c, p in chunks():
            if c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        sols.add(scenery.read_solid(k, kp).name_hash)
            elif c.id == scenery.SCENERY_SECTION:
                sc = scenery.read_scenery(c, p)
                out += [(sc.infos[i.info_index], i, sc.number) for i in sc.instances]
        common._cache["sl_inst"] = (sols, out)
    return common._cache["sl_inst"]


def props():
    """[(role, x, y, z, scale, instance)] of every street-life instance in the file."""
    from tools.citymap import x0props
    by_hash = {int(p["hash"], 16): r for r, p in x0props.load()["picks"].items()}
    _sols, inst = file_solids_and_instances()
    out = []
    for info, i, _n in inst:
        r = by_hash.get(info.solid_hashes[0])
        if r is not None:
            m = i.matrix
            out.append((r, m[3][0], m[3][1], m[3][2], math.hypot(m[0][0], m[0][1]), i))
    return out


def build_record():
    from tools.citymap.tests import test_city
    if os.environ.get("FTOWN_CITY"):
        raise unittest.SkipTest("the placement record comes from a build")
    return test_city.built()[0]["streetlife"]


class Budget(unittest.TestCase):
    def test_view_budget_capped(self):
        """No view may draw more triangles than Rockport's largest loaded set (the own looks' rule, notes "The budget";
        the review: view_budget's max() let Bata Chowk's and Marengo Asia's landmarks-stage margin pass it)."""
        from tools.citymap import build_city
        for name in build_city.PLAIN_VIEWS:
            _m, t, _i = build_city.view_budget(name)
            self.assertLessEqual(t, build_city.ROCKPORT_TRIANGLES_MAX, name)


class StreetLife(unittest.TestCase):
    def test_props_by_hash_only(self):
        """Every instance names either one of our solids (the tiles) or a catalogued pick of X0 in slot 0 alone, with
        the pick's flags and our own info name; no solid of the file has an X0 hash and no X0 name is in the file
        (nothing of X0 is copied); the counts by kind (the plan: trees, bushes, benches, bus shelters)."""
        from tools.citymap import streetlife, x0props
        cat = x0props.load()
        picks = {int(p["hash"], 16): (r, p) for r, p in cat["picks"].items()}
        sols, inst = file_solids_and_instances()
        n = collections.Counter()
        from tools.citymap import breakables
        poles = {breakables.solid_hash(r) for r in breakables.ROLES}
        for info, i, _num in inst:
            h = info.solid_hashes[0]
            if info.name.startswith("FTB_"):  # a breakable pole (2026-11-05): test_breakables checks it
                self.assertIn(h, poles, info.name)
                continue
            if h in sols:
                self.assertTrue(info.name.startswith(("FTC_", "FTV_")), info.name)
                continue
            self.assertIn(h, picks, info.name)
            role, p = picks[h]
            self.assertEqual(info.solid_hashes, (h, 0, 0, 0))
            self.assertEqual(i.exclude_flags, int(p["flags"], 16))
            self.assertTrue(info.name.startswith("FTS_"), info.name)
            self.assertAlmostEqual(info.radius, x0props.info_radius(role), places=3)
            n[role] += 1
        x0 = {int(m["hash"], 16) for m in cat["models"]}
        if os.path.exists(os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")):
            x0 |= set(x0props.read_x0(GAME))
        self.assertFalse(sols & x0)
        from tools.citymap.tests.test_runh import city_bytes
        data = city_bytes()
        for m in cat["models"]:
            if m["kind"] in ("tree", "bush", "bench", "shelter", "bin"):
                self.assertNotIn(m["name"].encode("ascii"), data, m["name"])
        trees = sum(v for r, v in n.items() if r.startswith("tree"))
        print("\n  street life instances %s (trees %d, all %d)" % (dict(n), trees, sum(n.values())), end="")
        self.assertGreater(trees, 600)
        self.assertGreater(n["bush"], 100)
        self.assertGreater(n["bench"], 15)
        self.assertGreater(n["shelter"], 4)
        self.assertGreater(n["bin"], 10)
        self.assertLessEqual(sum(n.values()), streetlife.MAX_PROPS)

    def test_tile_budget(self):
        """No 128 m tile holds more than streetlife.MAX_PER_TILE street-life instances (the builder's per-tile
        budget)."""
        from tools.citymap import streetlife, tiles
        per = collections.Counter((math.floor(x / tiles.TILE), math.floor(y / tiles.TILE)) for _r, x, y, _z, _s, _i
                                  in props())
        print("\n  street life: %d tiles, at most %d instances a tile" % (len(per), max(per.values())), end="")
        self.assertLessEqual(max(per.values()), streetlife.MAX_PER_TILE)

    def test_nothing_in_or_near_a_lane(self):
        """No street-life instance's footprint and no parked vehicle's vertex within 1 m of a carriageway (ground or
        raised), and none within 3 m of a raised one (nothing on or under the decks and ramps)."""
        from tools.citymap import streetlife
        lanes_all, raised = lanes()
        pr = props()
        # each footprint from the written instance: its position, heading and scale (the trunk's ring for a tree)
        pts = [streetlife.footprint(r, x, y, math.atan2(i.matrix[0][1], i.matrix[0][0]), s)
               for r, x, y, _z, s, i in pr]
        d = shapely.distance(lanes_all, pts)
        bad = [(pr[k][0], round(pr[k][1], 1), round(pr[k][2], 1), round(d[k], 2)) for k in range(len(pr))
               if d[k] < streetlife.LANE_CLEAR - 0.01]
        dr = shapely.distance(raised, pts)
        high = int((dr < streetlife.RAISED_CLEAR - 0.01).sum())
        w = written()
        V = w["P"][w["tex"] == "FTC_VEHICLES"].reshape(-1, 3)
        V = np.unique(np.round(V[:, :2], 2), axis=0)
        vb =lanes_all.buffer(streetlife.LANE_CLEAR - 0.01, quad_segs=4)
        shapely.prepare(vb)
        vbad = int(shapely.intersects(vb, shapely.points(V)).sum())
        vr = raised.buffer(streetlife.RAISED_CLEAR - 0.01, quad_segs=4)
        vhigh = int(shapely.intersects(vr, shapely.points(V)).sum())
        print("\n  %d instances: %d within %.1f m of a lane (first %s), %d near a deck; %d vehicle vertices: %d near "
              "a lane, %d near a deck" % (len(pr), len(bad), streetlife.LANE_CLEAR, bad[:3], high, len(V), vbad,
                                         vhigh), end="")
        self.assertGreater(len(V), 1000)
        self.assertEqual(bad, [])
        self.assertEqual(high, 0)
        self.assertEqual(vbad, 0)
        self.assertEqual(vhigh, 0)

    def test_props_on_their_face(self):
        """Every street-life instance stands on the face under it (the game's height query from 1 m above, within
        2 cm), and every parked vehicle's wheels at its footprint's corners and middle."""
        pr = props()
        xs = np.array([x for _r, x, _y, _z, _s, _i in pr])
        ys = np.array([y for _r, _x, y, _z, _s, _i in pr])
        zs = np.array([z for _r, _x, _y, z, _s, _i in pr])
        h = height_at(xs, ys, zs + 1.0)
        off = np.abs(h - zs)
        bad = int((~(off <= 0.02)).sum())
        rec = build_record()
        vbad, n = 0, 0
        for kind, _v, x, y, z, hd in rec["vehicles"]:
            from tools.citymap import vehicles
            L, W, _H = vehicles.size(kind)
            c, s = math.cos(hd), math.sin(hd)
            for a, b in ((0, 0), (L / 2, W / 2), (L / 2, -W / 2), (-L / 2, W / 2), (-L / 2, -W / 2)):
                px, py = x + a * c - b * s, y + a * s + b * c
                hh = height_at(np.array([px]), np.array([py]), np.array([z + 1.0]))[0]
                n += 1
                vbad += not abs(hh - z) <= 0.02
        print("\n  %d instances: %d off their face (worst %.3f m); %d vehicle points: %d off" % (
            len(pr), bad, float(np.nanmax(off)) if len(off) else 0.0, n, vbad), end="")
        self.assertEqual(bad, 0)
        self.assertEqual(vbad, 0)

    def test_trunks_and_vehicles_solid(self):
        """Tree trunks, bus shelters and parked vehicles are small barriers (the plan); bushes are not."""
        from tools.citymap import streetlife, vehicles
        bars = barriers()
        cells = collections.defaultdict(list)
        for k, b in enumerate(bars):
            cells[(int(b[0][0] // 4), int(b[0][1] // 4))].append(k)

        def near(x, y, r, tall):
            got = 0
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for k in cells.get((int(x // 4) + di, int(y // 4) + dj), ()):
                        b = bars[k]
                        if math.dist(b[0], (x, y)) <= r and math.dist(b[1], (x, y)) <= r and b[3] - b[2] >= tall:
                            got += 1
            return got
        def ringed(poly, tall):
            """Barriers with both ends on the outline of poly (within 5 cm), tall enough."""
            from shapely.geometry import Point
            edge = poly.exterior.buffer(0.05)
            x0, y0, x1, y1 = poly.bounds
            got = 0
            for i in range(int(x0 // 4) - 1, int(x1 // 4) + 2):
                for j in range(int(y0 // 4) - 1, int(y1 // 4) + 2):
                    for k in cells.get((i, j), ()):
                        b = bars[k]
                        if b[3] - b[2] >= tall and edge.contains(Point(b[0])) and edge.contains(Point(b[1])):
                            got += 1
            return got
        bad = collections.Counter()
        for role, x, y, _z, s, i in props():
            hd = math.atan2(i.matrix[0][1], i.matrix[0][0])
            if role.startswith("tree"):
                bad[role] += ringed(streetlife.base(role, x, y, hd, s), 3.0) < 4
            elif role == "shelter":
                bad[role] += ringed(streetlife.base(role, x, y, hd, s), 2.5) < 4
            elif role == "bush":
                bad[role] += near(x, y, 0.3, 0.0) > 0
        rec = build_record()
        for kind, _v, x, y, _z, hd in rec["vehicles"]:
            # Run I fixes, item 1: only two-wheelers, and not solid (no barrier on their outline)
            L, W, H = vehicles.size(kind)
            bad[kind] += kind not in streetlife.DRAWN_VEHICLES or \
                ringed(streetlife.footprint_vehicle(x, y, hd, L, W), 0.5) > 0
        print("\n  without their barriers (bushes, two-wheelers: with one): %s; %d vehicles" % (
            dict(bad), len(rec["vehicles"])), end="")
        self.assertEqual(sum(bad.values()), 0)
        self.assertGreater(len(rec["vehicles"]), 100)

    def test_nothing_through_a_wall_or_railing(self):
        """No tree, bus shelter or parked vehicle stands across a two-sided barrier (a median's railing, a crash wall,
        a boundary wall: the first build put rows of junipers on Mathura Road's railing medians) and none stands on a
        median (only the shrubs do: the plan)."""
        from shapely.geometry import LineString
        from tools.citymap import streetlife, vehicles
        two = [LineString([b[0], b[1]]) for b in barriers() if b[4] & 0x10 and math.dist(b[0], b[1]) > 0.05]
        tree = shapely.STRtree(two)
        stands = [streetlife.base(r, x, y, math.atan2(i.matrix[0][1], i.matrix[0][0]), s)
                  for r, x, y, _z, s, i in props() if r.startswith("tree") or r == "shelter"]
        rec = build_record()
        for kind, _v, x, y, _z, hd in rec["vehicles"]:
            L, W, _H = vehicles.size(kind)
            stands.append(streetlife.footprint_vehicle(x, y, hd, L, W))
        hits = sum(1 for g in stands if len(tree.query(g, predicate="intersects")))
        on_median = rec.get("on_median", None)
        print("\n  %d stands: %d across a two-sided barrier; on a median: %s" % (len(stands), hits, on_median), end="")
        self.assertEqual(hits, 0)
        self.assertEqual(on_median, 0)

    def test_vehicles_drawn_close_up(self):
        """Every parked vehicle is drawn by the main view from 20 m before it, from each of four sides, looking at it
        (the review: the game's pixel size is 0 once the camera is radius + 6 past an instance's position, the tile's
        middle for a tile's vehicles), and lies wholly in its own tile (a tile's FTV instance holds it whole)."""
        from tools.citymap import tiles, vehicles, view_proxy
        from tools.citymap.tests.test_runh import city_bytes
        ftv = {e["name"]: e for e in view_proxy.entries_of(city_bytes()) if e["name"].startswith("FTV_")}
        rec = build_record()
        hidden, split = 0, 0
        for kind, _v, x, y, z, hd in rec["vehicles"]:
            i, j = math.floor(x / tiles.TILE), math.floor(y / tiles.TILE)
            e = ftv["FTV_%02d_%03d" % (i, j)]
            L, W, _H = vehicles.size(kind)
            c, s = math.cos(hd), math.sin(hd)
            for a, b in ((L / 2, W / 2), (L / 2, -W / 2), (-L / 2, W / 2), (-L / 2, -W / 2)):
                px, py = x + a * c - b * s, y + a * s + b * c
                split += (math.floor(px / tiles.TILE), math.floor(py / tiles.TILE)) != (i, j)
            for k in range(4):
                h = k * 90.0
                view = {"x": x - 20.0 * math.cos(math.radians(h)), "y": y - 20.0 * math.sin(math.radians(h)),
                        "z": z + 1.0, "heading": h}
                hidden += not view_proxy.breakdown([e], view)
        # never far close up whatever the game's H (720..1000): within 2R the pixel size is H itself
        worst = max(8.7 * max(6.0, e["models"][0]["density"]) for e in ftv.values())
        print("\n  %d vehicles: %d views from 20 m that miss them, %d corners outside their tile; near-branch bound "
              "%.0f" % (len(rec["vehicles"]), hidden, split, worst), end="")
        self.assertEqual(hidden, 0)
        self.assertEqual(split, 0)
        self.assertLess(worst, 720.0)

    def test_per_view_proxy(self):
        """The main view's proxy (tools/citymap/view_proxy.py, X0's models' counts from the catalogue) from every
        viewpoint within the Run H fixes' numbers + 15% (the plan) in instances and meshes, and triangles within that
        or, since the own looks, build_city.own_looks_triangles (1.5 x the street life's, at most Rockport's largest
        loaded set: docs/ftown-notes.md "Own looks and a lived-in city (2026-11-04)")."""
        from tools.citymap import build_city, view_proxy
        from tools.citymap.tests.test_runh import city_bytes
        rows = view_proxy.report(view_proxy.entries_of(city_bytes()), _spawns() + build_city.VIEWPOINTS)
        for r in rows:
            b = build_city.RUNH_FIXES_VIEWS[r["name"]]
            print("\n  %-18s %5d instances (%5d) %6d meshes (%5d) %8d triangles (%7d)" % (
                r["name"], r["instances"], b[0], r["meshes"], b[1], r["triangles"], b[2]), end="")
            for got, base in zip((r["instances"], r["meshes"]), b):
                self.assertLessEqual(got, build_city.STREET_MARGIN * base, r["name"])
            self.assertLessEqual(r["triangles"], max(build_city.STREET_MARGIN * b[2],
                                                     build_city.own_looks_triangles(r["name"])), r["name"])


if __name__ == "__main__":
    unittest.main()
