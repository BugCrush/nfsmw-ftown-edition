"""Run H's faults (docs/ftown-notes.md "Run H fixes (2026-11-04)"), each checked on the written city file.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_runh -v

The file is the one test_city builds (.superpowers/citymap/test-out/ftown-city.bun), or the one named by the
environment variable FTOWN_CITY (e.g. run H's build, to see the tests fail on it):

    set FTOWN_CITY=.superpowers\\citymap\\runh-fixes\\runH-before.bun

Conventions checked (the game draws the side a triangle's right-hand normal (B - A) x (C - A) faces, as our ground,
counter-clockwise from above, is drawn from above; Rockport's faces agree with their own vertex normals on 99.99% of
their upward area, tools/citymap/rockport_winding.py).
"""
import math
import os
import struct
import sys
import unittest

import numpy as np

from tools.citymap import terrain
from tools.citymap.tests import common

TOOLS = common.TOOLS
for p in (TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import read_chunks  # noqa: E402
from world import collision_write, scenery, texpack  # noqa: E402

VERTICAL = 0.25  # |normal z| under this: a wall


def gz(x, y):
    """The built ground's z under render (x, y) (terrain.ground_z over arrays; elevation, 2026-11-05)."""
    return terrain.GROUND_Z + terrain.offsets(x, y)


def _bgz(b):
    """The built ground's z under a barrier's middle (b: (a, b, ...), render)."""
    return terrain.ground_z((b[0][0] + b[1][0]) / 2.0, (b[0][1] + b[1][1]) / 2.0)


def city_bytes():
    if "runh_data" not in common._cache:
        path = os.environ.get("FTOWN_CITY")
        if path:
            with open(path, "rb") as f:
                common._cache["runh_data"] = f.read()
        else:
            from tools.citymap.tests import test_city
            common._cache["runh_data"] = test_city.built()[1]
    return common._cache["runh_data"]


def chunks():
    if "runh_chunks" not in common._cache:
        common._cache["runh_chunks"] = list(scenery.with_positions(read_chunks(city_bytes()), 0))
    return common._cache["runh_chunks"]


def textures_by_name():
    """{name: (h, w, 3) uint8} of the written texture pack, decoded."""
    if "runh_tex" not in common._cache:
        from tools.citymap import render_tex
        out = {}
        for c, p in chunks():
            if c.id == texpack.PACK:
                for t in texpack.read_pack(c, p).textures:
                    w, h = struct.unpack_from("<hh", t.info, 0x44)
                    name = t.info[0x0C:0x24].split(b"\0")[0].decode("latin-1")
                    out[name] = render_tex.dxt1_decode(t.data, w, h)
        common._cache["runh_tex"] = out
    return common._cache["runh_tex"]


def written(slot=0):
    """Every triangle of the models in `slot` of every instance of the written file: P (n, 3, 3) render metres, UV
    (n, 3, 2), N (n, 3) unit right-hand normals, tex (n,) texture names, inst (n,) instance names, alpha (n,) the
    first vertex's colour alpha (the evening's glow class, tools/citymap/evening.py)."""
    key = "runh_written_%d" % slot
    if key not in common._cache:
        sols, scs, names = {}, [], {}
        for c, p in chunks():
            if c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        so = scenery.read_solid(k, kp)
                        sols[so.name_hash] = so
            elif c.id == scenery.SCENERY_SECTION:
                scs.append(scenery.read_scenery(c, p))
            elif c.id == texpack.PACK:
                for t in texpack.read_pack(c, p).textures:
                    names[t.name_hash] = t.info[0x0C:0x24].split(b"\0")[0].decode("latin-1")
        P, UV, TX, IN, AL = [], [], [], [], []
        for sc in scs:
            for inst in sc.instances:
                info = sc.infos[inst.info_index]
                so = sols.get(info.solid_hashes[slot])
                if so is None:
                    continue
                m = np.array(inst.matrix, dtype=float)
                for k, mesh in enumerate(so.meshes):
                    st = so.stride(mesh.buffer)
                    raw = np.frombuffer(so.vertex_buffers[mesh.buffer], dtype=np.uint8, count=mesh.vertex_count * st,
                                        offset=mesh.vertex_offset * st).reshape(mesh.vertex_count, st)
                    pos = raw[:, 0:12].copy().view("<f4").astype(float)
                    uv = raw[:, 28:36].copy().view("<f4").astype(float)
                    tri = np.array(so.triangles(k), dtype=np.int64)
                    if not len(tri):
                        continue
                    P.append((pos @ m[:3, :3] + m[3, :3])[tri])
                    UV.append(uv[tri])
                    AL.append(raw[:, 27][tri[:, 0]])
                    nm = names.get(so.textures[mesh.texture_slots[0]], "?")
                    TX.append(np.full(len(tri), nm, dtype=object))
                    IN.append(np.full(len(tri), info.name, dtype=object))
        P = np.concatenate(P)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        L = np.linalg.norm(n, axis=1)
        N = n / np.where(L > 0, L, 1.0)[:, None]
        common._cache[key] = {"P": P, "UV": np.concatenate(UV), "N": N, "area": L / 2, "tex": np.concatenate(TX),
                              "inst": np.concatenate(IN), "alpha": np.concatenate(AL)}
    return common._cache[key]


def packs():
    if "runh_packs" not in common._cache:
        common._cache["runh_packs"] = [collision_write.read_pack(c.data, p) for c, p in chunks()
                                       if c.id == collision_write.COLLISION_PACK]
    return common._cache["runh_packs"]


def heights():
    if "runh_fh" not in common._cache:
        from tools.citymap import fastheight
        common._cache["runh_fh"] = fastheight.HeightModel(packs())
    return common._cache["runh_fh"]


def barriers():
    """[((ax, ay), (bx, by), bottom, top, flags)] in render coordinates (a -> b: the front is its right)."""
    if "runh_bars" not in common._cache:
        out = []
        for pk in packs():
            for inst in pk.instances:
                t = inst.t
                for b in pk.articles[inst.article].barriers:
                    a = (b.p0[0] - t[0], b.p0[1] - t[1], b.p0[2] - t[2])
                    q = (b.p1[0] - t[0], b.p1[1] - t[1], b.p1[2] - t[2])
                    out.append(((a[2], -a[0]), (q[2], -q[0]), min(a[1], q[1]), max(a[1], q[1]), (b.word >> 8) & 0xFF))
        common._cache["runh_bars"] = out
    return common._cache["runh_bars"]


def height_at(x, y, from_z):
    """The wheels' face height under render points (x, y) from render height from_z (NaN where none)."""
    return heights().wheel_heights(-np.asarray(y, float), np.asarray(x, float), np.asarray(from_z, float))


class Grid:
    """Vertical triangles by 8 m cells of their (x, y) boxes, for horizontal rays."""

    def __init__(self, P, idx, cell=8.0):
        self.cell, self.cells = cell, {}
        lo = P[idx, :, :2].min(1)
        hi = P[idx, :, :2].max(1)
        for k, a, b in zip(idx, np.floor(lo / cell).astype(int), np.floor(hi / cell).astype(int)):
            for i in range(a[0], b[0] + 1):
                for j in range(a[1], b[1] + 1):
                    self.cells.setdefault((i, j), []).append(k)

    def along(self, o, d, length):
        out = set()
        n = int(math.ceil(length / (self.cell / 2))) + 1
        for s in range(n):
            x, y = o[0] + d[0] * s * self.cell / 2, o[1] + d[1] * s * self.cell / 2
            i, j = int(math.floor(x / self.cell)), int(math.floor(y / self.cell))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    out.update(self.cells.get((i + di, j + dj), ()))
        return np.fromiter(out, dtype=np.int64) if out else np.zeros(0, dtype=np.int64)


def ray_hits(P, cand, o, d):
    """(t, index) of the candidate triangles a ray o + t d crosses (Moller-Trumbore), sorted by t, t > 0."""
    if not len(cand):
        return []
    A, B, C = P[cand, 0], P[cand, 1], P[cand, 2]
    e1, e2 = B - A, C - A
    pv = np.cross(d[None, :], e2)
    det = (e1 * pv).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = o[None, :] - A
    u = (tv * pv).sum(1) * inv
    qv = np.cross(tv, e1)
    v = (qv * d[None, :]).sum(1) * inv
    t = (qv * e2).sum(1) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 0)
    order = np.argsort(t[hit])
    return list(zip(t[hit][order], cand[hit][order]))


def walls_mask(w):
    return (np.abs(w["N"][:, 2]) < VERTICAL) & (w["area"] > 1e-4)


def first_hit(w, grid, n, d, length, skip_backing=False, skip=None):
    """(t, k) of the first face a horizontal ray from wall n's centroid in direction d meets within `length` m, or
    None. Passed over: n itself; a two-sided sheet (two hits at one t with opposite normals: a parapet, a boundary
    wall, a ribbon); with skip_backing, faces with n's own normal within 10 cm (a photo or board face's backing, a
    pole inside its lantern). The ray runs along the ground's slope (terrain.json's plane: the city is the flat city
    sheared, so the ray meets what a horizontal one met there; a horizontal ray on the slope grazed a parapet's top
    63 m from Marengo Asia's front by 0.8 mm)."""
    P, N = w["P"], w["N"]
    m = terrain.model()
    d = np.array([d[0], d[1], m["dz_dx"] * d[0] + m["dz_dy"] * d[1]])
    o = P[n].mean(0) - d * 0.001
    hits = [(t, k) for t, k in ray_hits(P, grid.along(o, d, length), o, d) if k != n and t <= length and
            (skip is None or not skip[k])]
    i = 0
    while i < len(hits):
        t, k = hits[i]
        same = [kk for tt, kk in hits[i:] if tt - t < 0.002]
        if len(same) > 1 and any(float(N[a] @ N[b]) < -0.99 for a in same for b in same):
            i += len(same)
            continue
        if skip_backing and t < 0.1 and float(N[k] @ N[n]) > 0.99:
            i += 1
            continue
        return t, k
    return None


def low_wall(w):
    """Mask of the risers: kerbs' and medians' sides (at most 0.4 m tall, tops under 0.45 m)."""
    c = w["P"].mean(1)
    return walls_mask(w) & (np.ptp(w["P"][:, :, 2], axis=1) <= 0.4) & \
        (w["P"][:, :, 2].max(1) - gz(c[:, 0], c[:, 1]) < 0.45)


def wall_grid(w):
    if "runh_grid" not in common._cache:
        common._cache["runh_grid"] = Grid(w["P"], np.nonzero(walls_mask(w))[0])
    return common._cache["runh_grid"]


def unit_xy(v):
    d = np.array([v[0], v[1], 0.0])
    return d / np.linalg.norm(d)


class Fronts(unittest.TestCase):
    """Faults 1 and 2 (run H): building fronts not drawn from outside, Pacific Mall's name mirrored from behind,
    billboards black."""

    def test_walls_face_their_barriers_front(self):
        """Every drawn wall lying on a one-sided barrier (a building's, a landmark's, a station's, a pillar's or pier's
        wall, the edge: barriers stop a body on their front only, and test_city's test_barriers_face_the_road proves
        those fronts face the drivable side) faces the same way as the barrier: its right-hand normal on the barrier's
        front side. Left out: risers (test_risers_face_down_the_step) and walls with a twin facing the other way in
        their plane (two-sided: a parapet's inner face, two buildings sharing a wall). Run H's build: the walls faced
        the other way."""
        w = written()
        wall = np.nonzero(walls_mask(w) & ~low_wall(w))[0]
        cen = w["P"][wall].mean(1)
        bars = [b for b in barriers() if not b[4] & 0x10 and math.dist(b[0], b[1]) > 0.1]
        cells = {}
        for k, b in enumerate(bars):
            for i in range(int(min(b[0][0], b[1][0]) // 8), int(max(b[0][0], b[1][0]) // 8) + 1):
                for j in range(int(min(b[0][1], b[1][1]) // 8), int(max(b[0][1], b[1][1]) // 8) + 1):
                    cells.setdefault((i, j), []).append(k)
        good = bad = twins = 0
        bad_tex = {}
        grid = wall_grid(w)
        for n, c in zip(wall, cen):
            for k in cells.get((int(c[0] // 8), int(c[1] // 8)), ()):
                (ax, ay), (bx, by), lo, hi, _f = bars[k]
                dx, dy = bx - ax, by - ay
                L = math.hypot(dx, dy)
                s = ((c[0] - ax) * dx + (c[1] - ay) * dy) / (L * L)
                off = ((c[0] - ax) * dy - (c[1] - ay) * dx) / L  # + on the right
                if not (0.0 < s < 1.0 and abs(off) < 0.03 and lo - 0.05 <= c[2] <= hi + 0.05):
                    continue
                if abs(w["N"][n, 0] * dx + w["N"][n, 1] * dy) / L > 0.2:
                    continue  # not along the barrier (an end face)
                if (w["N"][n, 0] * dy - w["N"][n, 1] * dx) / L > 0:
                    good += 1
                else:
                    d = -unit_xy(w["N"][n])
                    o = w["P"][n].mean(0) - d * 0.001
                    if any(t < 0.03 and float(w["N"][kk] @ w["N"][n]) < -0.99
                           for t, kk in ray_hits(w["P"], grid.along(o, d, 1.0), o, d) if kk != n):
                        twins += 1
                    else:
                        bad += 1
                        bad_tex[w["tex"][n]] = bad_tex.get(w["tex"][n], 0) + 1
                break
        print("\n  %d walls on one-sided barriers: %d face its front, %d its back (%d more with a twin facing it) %s"
              % (good + bad + twins, good, bad, twins, dict(sorted(bad_tex.items()))))
        self.assertGreater(good + bad, 50000)
        # a handful where two blocks share an edge and one's wall is cut differently (unseen between them)
        self.assertLessEqual(bad, 10)

    def test_risers_face_down_the_step(self):
        """Every riser (a kerb's or a median's side) standing on a step, the faces 0.25 m either side at its foot and at
        its top (within 5 cm), faces the lower side (the road), from where it is seen."""
        w = written()
        idx = np.nonzero(low_wall(w))[0]
        cen = w["P"][idx].mean(1)
        nxy = w["N"][idx, :2] / np.linalg.norm(w["N"][idx, :2], axis=1)[:, None]
        z0 = w["P"][idx, :, 2].min(1)
        z1 = w["P"][idx, :, 2].max(1)
        hf = height_at(cen[:, 0] + 0.25 * nxy[:, 0], cen[:, 1] + 0.25 * nxy[:, 1], z1 + 1.0)
        hb = height_at(cen[:, 0] - 0.25 * nxy[:, 0], cen[:, 1] - 0.25 * nxy[:, 1], z1 + 1.0)
        lo, hi = np.fmin(hf, hb), np.fmax(hf, hb)
        step = ~np.isnan(hf) & ~np.isnan(hb) & (np.abs(lo - z0) < 0.05) & (np.abs(hi - z1) < 0.05) & (hi - lo >= 0.08)
        wrong = step & (hf > hb)
        print("\n  %d risers, %d on a step: %d face the upper side" % (len(idx), int(step.sum()), int(wrong.sum())))
        self.assertGreater(int(step.sum()), 5000)
        # a few on pavement slivers the kerb's simplified ring leaves (centimetres off the pavement's edge)
        self.assertLessEqual(int(wrong.sum()), 10)

    def test_fronts_open_behind(self):
        """Behind every wall is the inside of what it bounds: a horizontal ray through it against its normal meets
        within 300 m first a face it leaves (its normal along the ray: the far side of a building, a pillar, a board),
        or nothing where the ray leaves the city's edge (the edge walls). Passed over: two-sided sheets, the wall's
        backing (its own normal within 5 cm behind). Risers are test_risers_face_down_the_step's. 20,000 sampled
        walls and every billboard face; at most 0.2% open behind (overlapping pieces: a girder through a station, a
        ribbon through a lantern). Run H's build: open behind almost everywhere."""
        w = written()
        N = w["N"]
        wall = np.nonzero(walls_mask(w) & ~low_wall(w))[0]
        # (Run I fixes: the parked vehicles, left out below, are left out before the sample is drawn, so the sample
        # does not change with how many vehicles there are: run I's 36,428 vehicle walls fell to 15,032)
        wall = wall[w["tex"][wall] != "FTC_VEHICLES"]
        # Run J, item 2: the stations' raised letters are blocks on their walls (tools/citymap/station_letters.py):
        # behind a letter's front, 8 cm in, is the station's own wall, its closed back (left out before the sample is
        # drawn, as the vehicles)
        from tools.citymap import evening as _ev
        wall = wall[~np.isin(w["alpha"][wall], [a for k, (a, _c) in _ev.CLASSES.items() if k.startswith("letters_")])]
        grid = wall_grid(w)
        rng = np.random.default_rng(7)
        special = wall[_billboard_faces(w)[wall]]
        pick = np.unique(np.concatenate([rng.choice(wall, min(20000, len(wall)), replace=False), special]))
        P = w["P"]
        lo = P[:, :, :2].reshape(-1, 2).min(0)
        hi = P[:, :, :2].reshape(-1, 2).max(0)
        # the street life's parked vehicles are left out (street life, 2026-11-04): small closed models of overlapping
        # pieces (a wheel inside its arch, the cabin on the body); their faces' outward winding is test_vehicles'
        pick = pick[w["tex"][pick] != "FTC_VEHICLES"]
        # the own looks' balconies are left out too (2026-11-04): a balcony's parapet is a thin wall standing before
        # its house's own front, outer faces only (its inside, the balcony's floor space, is seen from above only);
        # the house atlas's balcony cell names them. Seen from above means from a flyover deck, which is a road: the
        # second review found 5 balconies within 40 m of a raised road whose parapet's open back a driver on the deck
        # sees (accepted, notes "Review fixes (own looks)")
        from tools.citymap import textures
        k_balc = textures.HOUSE_CELLS.index("balcony")
        uvc = w["UV"][pick]
        in_balc = (uvc[:, :, 1].min(1) * 1024 >= 960) & (np.floor(uvc[:, :, 0].mean(1) * 1024 / 64) == k_balc)
        pick = pick[~((w["tex"][pick] == "FTC_HOUSES") & in_balc)]
        # the evening's window panes (tools/citymap/evening.py) stand 15 cm behind their walls by day, hidden: glass
        # inside the wall, neither a wall to test nor a face a wall's ray may stop at
        from tools.citymap import evening
        pane = w["alpha"] == evening.CLASSES["pane"][0]
        pick = pick[~pane[pick]]
        bad, kinds = 0, {}
        for n in pick:
            d = -unit_xy(N[n])
            h = first_hit(w, grid, n, d, 300.0, skip_backing=True, skip=pane)
            if h is None:
                end = P[n].mean(0)[:2] + d[:2] * 300.0
                ok = not (lo[0] + 1 < end[0] < hi[0] - 1 and lo[1] + 1 < end[1] < hi[1] - 1)
            else:
                ok = float(N[h[1]] @ d) > 0
            if not ok:
                bad += 1
                kinds[w["tex"][n]] = kinds.get(w["tex"][n], 0) + 1
        print("\n  %d walls checked (%d billboard faces): %d open behind %s" % (
            len(pick), len(special), bad, dict(sorted(kinds.items(), key=lambda kv: -kv[1])[:12])))
        self.assertGreater(len(special), 100)
        self.assertLessEqual(bad, len(pick) // 500)

    def test_photo_faces_open_in_front(self):
        """Every photo face (FTL_* textures: fronts, rooftop signs, the stations' ends, the mural, the sign) looks out:
        a horizontal ray from it along its normal meets within 300 m nothing, or first another face from that face's
        front (it is outside). Run H's build: the ray ran into the building's inside and met its far wall from
        behind."""
        w = written()
        N = w["N"]
        grid = wall_grid(w)
        sel = np.nonzero(np.array([t.startswith("FTL_") for t in w["tex"]], dtype=bool) & walls_mask(w))[0]
        bad = {}
        for n in sel:
            d = unit_xy(N[n])
            h = first_hit(w, grid, n, d, 300.0)
            if h is not None and h[0] > 0.01 and float(N[h[1]] @ d) > 0:  # 1 cm: pieces crossing at a bend
                bad[w["tex"][n]] = bad.get(w["tex"][n], 0) + 1
        print("\n  %d photo-face triangles: %d look into something %s" % (len(sel), sum(bad.values()), bad))
        self.assertGreater(len(sel), 100)
        # the mural where two Neelam Flyover embankments meet (render (1168, 10405)): a wall between two elevated
        # pieces, its outside ambiguous (levels' walls); a few triangles allowed there, none elsewhere
        self.assertEqual({k: v for k, v in bad.items() if k != "FTL_MURAL"}, {})
        self.assertLessEqual(bad.get("FTL_MURAL", 0), 4)

    def test_photo_faces_unmirrored(self):
        """Every photo face (FTL_* textures) reads unmirrored from its front: u grows to the right of a viewer facing
        it and v downwards (a texture's top row first)."""
        w = written()
        sel = np.nonzero(np.array([t.startswith("FTL_") for t in w["tex"]], dtype=bool) & walls_mask(w))[0]
        bad = 0
        for n in sel:
            nn = w["N"][n]
            right = np.cross(-nn, (0.0, 0.0, 1.0))
            right /= np.linalg.norm(right)
            X = np.stack([w["P"][n] @ right, w["P"][n][:, 2], np.ones(3)], 1)
            try:
                a = np.linalg.solve(X, w["UV"][n])
            except np.linalg.LinAlgError:
                continue
            if a[0, 0] < -1e-4 or not a[1, 1] < 0:  # du 0: a sliver at a bend of the mural, not mirrored
                bad += 1
        print("\n  %d photo-face triangles: %d mirrored or upside down from their front" % (len(sel), bad))
        self.assertGreater(len(sel), 100)
        self.assertEqual(bad, 0)

    def test_billboards_face_the_road(self):
        """Every billboard's design face: its front towards the road it stands behind (the point 12 m in front lies on
        asphalt or a pavement at the ground), and the design's texels it shows not black (run H: plain black)."""
        from vlthash import vlt32
        w = written()
        sel = np.nonzero(_billboard_faces(w))[0]
        cen = w["P"][sel].mean(1)
        nxy = w["N"][sel, :2]
        nxy = nxy / np.linalg.norm(nxy, axis=1)[:, None]
        fx, fy = cen[:, 0] + 12 * nxy[:, 0], cen[:, 1] + 12 * nxy[:, 1]
        got = heights().wheel_surfaces(-fy, fx, gz(fx, fy) + 1.0)
        road = {vlt32("asphalt"), vlt32("concrete")}
        facing = sum(1 for (h, s), g in zip(got, gz(fx, fy)) if s in road and abs(h - g) < 0.3)
        tex = textures_by_name()["FTC_FURNITURE"]
        th, tw, _ = tex.shape
        uv = w["UV"][sel].mean(1)
        px = tex[(np.floor(uv[:, 1] % 1.0 * th).astype(int)) % th, (np.floor(uv[:, 0] % 1.0 * tw).astype(int)) % tw]
        lum = float((px @ np.array([0.299, 0.587, 0.114])).mean())
        print("\n  %d billboard face triangles: %d face a road 12 m in front; design texels' luminance %.1f" % (
            len(sel), facing, lum))
        self.assertGreater(len(sel), 200)
        self.assertGreaterEqual(facing, 0.9 * len(sel))
        self.assertGreater(lum, 40.0)


def _billboard_faces(w):
    """Mask of the billboards' design triangles: furniture atlas triangles with uvs spanning an area (the solid
    colour cells have all three uvs on one texel)."""
    uv = w["UV"]
    a = np.abs((uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1]) -
               (uv[:, 2, 0] - uv[:, 0, 0]) * (uv[:, 1, 1] - uv[:, 0, 1]))
    return (w["tex"] == "FTC_FURNITURE") & (a > 1e-6)


RAIL_H = 1.1  # furniture.RAIL_BARRIER: the railing medians' railing (the one barrier a platform keeps)


def _vehicle_barrier(b):
    """Whether barrier b is a parked vehicle's (its middle on a vehicle's outline, within 5 cm: the build's street-life
    record; none when the file under test is not a build of this run)."""
    if "runh_vehicle_edges" not in common._cache:
        edges = None
        if not os.environ.get("FTOWN_CITY"):
            import shapely
            from tools.citymap import streetlife, vehicles
            from tools.citymap.tests import test_city
            rec = test_city.built()[0].get("streetlife", {}).get("vehicles", [])
            if rec:
                edges = shapely.union_all([streetlife.footprint_vehicle(x, y, hd, *vehicles.size(k)[:2])
                                           .exterior.buffer(0.05) for k, _v, x, y, _z, hd in rec])
                shapely.prepare(edges)
        common._cache["runh_vehicle_edges"] = edges
    edges = common._cache["runh_vehicle_edges"]
    if edges is None:
        return False
    from shapely.geometry import Point
    return edges.contains(Point((b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2))


def _crosses(p, q, a, b):
    def orient(u, v, w_):
        return (v[0] - u[0]) * (w_[1] - u[1]) - (v[1] - u[1]) * (w_[0] - u[0])
    return (orient(p, q, a) * orient(p, q, b) < 0) and (orient(a, b, p) * orient(a, b, q) < 0)


class Platforms(unittest.TestCase):
    """Fault 3 (run H): medians, pavements and kerbs stopped the car like walls (9 of 44 hard stops within 2.5 m of a
    median's 1.0 m barrier). Rockport's kerbs are steps in the faces, no barrier (tools/citymap/rockport_kerbs.py)."""

    def _risers(self, every=4):
        """Every `every`-th riser triangle standing on a step (as test_risers_face_down_the_step), with its centroid,
        unit normal (to the road) and edge direction."""
        w = written()
        idx = np.nonzero(low_wall(w))[0]
        cen = w["P"][idx].mean(1)
        nxy = w["N"][idx, :2] / np.linalg.norm(w["N"][idx, :2], axis=1)[:, None]
        z0 = w["P"][idx, :, 2].min(1)
        z1 = w["P"][idx, :, 2].max(1)
        hf = height_at(cen[:, 0] + 0.25 * nxy[:, 0], cen[:, 1] + 0.25 * nxy[:, 1], z1 + 1.0)
        hb = height_at(cen[:, 0] - 0.25 * nxy[:, 0], cen[:, 1] - 0.25 * nxy[:, 1], z1 + 1.0)
        from vlthash import vlt32
        fs = heights().wheel_surfaces(-(cen[:, 1] + 0.25 * nxy[:, 1]), cen[:, 0] + 0.25 * nxy[:, 0], z1 + 1.0)
        road = np.array([s_ == vlt32("asphalt") for _h, s_ in fs], dtype=bool)
        on = ~np.isnan(hf) & (np.abs(hf - z0) < 0.05) & (np.abs(hf - gz(cen[:, 0] + 0.25 * nxy[:, 0], cen[:, 1] + 0.25 * nxy[:, 1])) < 0.02) & (z1 - z0 >= 0.08) & road
        k = np.nonzero(on)[0][::every]
        return w, idx[k], cen[k], nxy[k], hb[k], z0[k], z1[k]

    def test_platforms_have_tops(self):
        """Every platform edge (a riser standing on asphalt) has the platform's top behind it: a face at the riser's
        top (within 5 cm) 0.25 m behind it. Run H's build: the medians' tops were drawn only (ground under them)."""
        w, idx, cen, nxy, hb, z0, z1 = self._risers(every=1)
        top = ~np.isnan(hb) & (np.abs(hb - z1) < 0.05)
        kinds = {}
        for n, ok in zip(idx, top):
            if not ok:
                kinds[w["inst"][n][:5]] = kinds.get(w["inst"][n][:5], 0) + 1
        print("\n  %d platform edges: %d without the platform's top behind them" % (len(idx), int((~top).sum())))
        self.assertGreater(len(idx), 3000)
        self.assertLessEqual(int((~top).sum()), len(idx) // 200)

    def test_platforms_climbable(self):
        """A car-wide probe (three lines 0.9 m apart) across every 4th platform edge, from 3 m out on the road to 2.4 m
        onto the platform (a pavement is 2.5 m wide; boundary walls stand 0.6 m beyond it): no barrier at a car's height (bottom under 1.2 m, top over 5 cm) crosses it but a railing
        medians' railing (two-sided, RAIL_H tall, 0.3 m or more in from the edge); walls over 1.6 m (buildings,
        flyover walls, the edge) are walls by design; the wheels' query every 0.1 m along
        the middle line, 3 m out to 1 m in, finds a face everywhere and no step over 0.2 m; the top's surface (0.25 m in) grass or concrete."""
        from vlthash import vlt32
        w, idx, cen, nxy, hb, z0, z1 = self._risers()
        # barriers at a car's height of a platform's kind (up to 1.6 m: run H's median outline 1.0 m, boundary walls
        # 1.5 m, crash walls 1.1 m); taller ones are walls by design (buildings, flyover walls, the edge)
        bars = [b for b in barriers() if b[2] < _bgz(b) + 1.2 and b[3] > _bgz(b) + 0.05 and b[3] - b[2] <= 1.6]
        # a flyover's wall where a ramp leaves the ground (two-sided pieces whose tops climb from piece to piece): a
        # wall by design, met beside a pavement at a ramp's foot
        ends = {}
        for b_ in barriers():
            for e in (b_[0], b_[1]):
                ends.setdefault((round(e[0], 1), round(e[1], 1)), []).append(b_[3])
        bars = [b_ for b_ in bars if not any(abs(t - b_[3]) > 0.1 for e in (b_[0], b_[1])
                                             for t in ends.get((round(e[0], 1), round(e[1], 1)), ()))]
        # the street life's parked vehicles are solid by design, off the carriageways (the street-life plan: "never
        # block a platform's crossing except by deliberate solid trunks and vehicles"; test_streetlife): left out
        bars = [b_ for b_ in bars if not _vehicle_barrier(b_)]
        cells = {}
        for k, b in enumerate(bars):
            for i in range(int(min(b[0][0], b[1][0]) // 8), int(max(b[0][0], b[1][0]) // 8) + 1):
                for j in range(int(min(b[0][1], b[1][1]) // 8), int(max(b[0][1], b[1][1]) // 8) + 1):
                    cells.setdefault((i, j), []).append(k)
        blocked, kinds, first = 0, {}, []
        lines = []
        for c, n in zip(cen, nxy):
            t = (-n[1], n[0])
            hit = False
            for off in (-0.9, 0.0, 0.9):
                a = (c[0] + n[0] * 3.0 + t[0] * off, c[1] + n[1] * 3.0 + t[1] * off)
                b_ = (c[0] - n[0] * 2.4 + t[0] * off, c[1] - n[1] * 2.4 + t[1] * off)
                near = set()
                for i in range(int(min(a[0], b_[0]) // 8), int(max(a[0], b_[0]) // 8) + 1):
                    for j in range(int(min(a[1], b_[1]) // 8), int(max(a[1], b_[1]) // 8) + 1):
                        near.update(cells.get((i, j), ()))
                for k in near:
                    (bx0, by0), (bx1, by1), lo, hi, fl = bars[k]
                    if not _crosses(a, b_, (bx0, by0), (bx1, by1)):
                        continue
                    # where along the probe (metres in from the edge)
                    d0 = ((bx0 - c[0]) * -n[0] + (by0 - c[1]) * -n[1])
                    d1 = ((bx1 - c[0]) * -n[0] + (by1 - c[1]) * -n[1])
                    rail = fl & 0x10 and abs((hi - lo) - RAIL_H) < 0.02 and min(d0, d1) >= 0.3
                    if not rail:
                        hit = True
                        key = "%.2f m %s" % (hi - lo, "two-sided" if fl & 0x10 else "one-sided")
                        kinds[key] = kinds.get(key, 0) + 1
                        if len(first) < 3:
                            first.append((round(float(c[0])), round(float(c[1]))))
                        break
                if hit:
                    break
            blocked += hit
            s = np.arange(-2.95, 0.96, 0.1)  # off the riser's own line (a hairline between two triangulations)
            lines.append((c[0] - n[0] * s, c[1] - n[1] * s))
        X = np.concatenate([x for x, _y in lines])
        Y = np.concatenate([y for _x, y in lines])
        H = height_at(X, Y, np.full(len(X), 101.5)).reshape(len(lines), -1)
        gaps = int(np.isnan(H).any(1).sum())
        steps = np.nanmax(np.abs(np.diff(H, axis=1)), axis=1)
        tall = int((steps > 0.2).sum())
        tops = heights().wheel_surfaces(-(cen[:, 1] - nxy[:, 1] * 0.25), cen[:, 0] - nxy[:, 0] * 0.25, z1 + 1.0)
        soft = {vlt32("grass"), vlt32("concrete")}
        hard = sum(1 for h, s_ in tops if s_ not in soft)
        print("\n  %d platform crossings: %d blocked by a barrier %s (first at %s); %d with a gap, %d with a step "
              "over 0.2 m (worst %.2f); %d tops not grass or concrete" % (len(cen), blocked, kinds, first, gaps, tall,
                                                                          float(np.nanmax(steps)), hard))
        self.assertGreater(len(cen), 1000)
        # never run H's median outline (1.0 m); at most one in a thousand: a flyover parapet standing alone at a ramp's
        # tip in the probe's line (render (1459, 9978), two-sided 1.08 m), a wall by design
        self.assertNotIn("1.00 m two-sided", kinds)
        self.assertLessEqual(blocked, len(cen) // 1000)
        self.assertLessEqual(gaps + tall, len(cen) // 200)
        self.assertLessEqual(hard, len(cen) // 200)

    def test_poles_solid(self):
        """Every lamp post and street light on a median that is drawn in the tiles is a barrier (review, 2026-11-04:
        with the medians' outline barrier gone a car could drive onto a median and through its poles): each pole (a
        furniture column 8 m tall or more, its foot on a platform) has a barrier 8 m tall or more within 0.3 m of its
        axis. Since the breakable poles (2026-11-05) no median pole is in the tiles any more: each is an instance of
        its own with a smackable spawner (the game's trigger, not a barrier: test_breakables), so none is found here
        and every median lamp of the furniture is a breakable record."""
        w = written()
        P = w["P"]
        sel = (w["tex"] == "FTC_FURNITURE") & walls_mask(w) & (np.ptp(P[:, :, 2], axis=1) >= 8.0) & \
            (np.abs(P[:, :, 2].min(1) - gz(P[:, :, 0].mean(1), P[:, :, 1].mean(1)) - 0.15) < 0.02)
        feet = {}
        for c in P[sel].mean(1):
            feet.setdefault((round(c[0] / 0.5), round(c[1] / 0.5)), c[:2])
        tall = [b for b in barriers() if b[3] - b[2] >= 8.0]
        cells = {}
        for k, b in enumerate(tall):
            cells.setdefault((int(b[0][0] // 4), int(b[0][1] // 4)), []).append(k)
        # the breakable poles (2026-11-05): our lanterns are drawn by instances of their own (FTC_FURNITURE too), with
        # no barrier by design (the game's smackable trigger: test_breakables); they are left out here
        from tools.citymap.tests.test_landmark_build import geometry
        fr = geometry()[4].extras.furniture
        lanterns = [(b.x, b.y) for b in fr.breakables if b.role == "lantern"]
        feet = {k: c for k, c in feet.items() if all(math.dist(c, q) > 0.5 for q in lanterns)}
        bad = 0
        for c in feet.values():
            near = False
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for k in cells.get((int(c[0] // 4) + di, int(c[1] // 4) + dj), ()):
                        if math.dist(tall[k][0], c) < 0.3:
                            near = True
            bad += not near
        print("\n  %d poles on the medians drawn in the tiles: %d without a barrier" % (len(feet), bad))
        self.assertEqual(bad, 0)
        lamps = [p for p in fr.placed if p[0] in ("lamp_sector", "light_main", "light_trunk")]
        self.assertGreater(len(lamps), 150)
        # every median lamp is a breakable pole now
        self.assertEqual(len([b for b in fr.breakables if not b.role.startswith("signal")]), len(lamps))

    def test_railings_solid(self):
        """The railing medians keep their railing as a barrier (a car does not cross it): two-sided barriers RAIL_H
        tall standing on the platform (bottom at its top), 1,000 m or more of them (run H's railing: 1,389 m)."""
        L = sum(math.dist(b[0], b[1]) for b in barriers()
                if b[4] & 0x10 and abs((b[3] - b[2]) - RAIL_H) < 0.02 and abs(b[2] - _bgz(b) - 0.15) < 0.03)
        print("\n  railing barriers: %.0f m" % L)
        self.assertGreater(L, 1000.0)


# run H's per-view proxy (tools/citymap/view_proxy.py on run H's file, 00a5c3cc...): meshes
RUNH_VIEW_MESHES = {"route start": 978, "route end": 1169, "Neelam Chowk": 2117, "Bata Chowk": 3274,
                    "Old Fbd station": 974, "Sector 16 Market": 643, "Marengo Asia": 2919}


def _spawns():
    import json
    path = os.environ.get("FTOWN_CITY")
    if path:
        js = os.path.join(os.path.dirname(os.path.abspath(path)), "ftown-city.json")
    else:
        from tools.citymap.tests import test_city
        js = os.path.join(os.path.dirname(test_city.built()[2]), "ftown-city.json")
    with open(js) as f:
        return json.load(f)["spawns"]


class FarLevel(unittest.TestCase):
    """Fault 4 (run H): Bata Chowk looking north at 17-20 ms a frame (1% low 47.9 FPS without the screenshot frames):
    draw calls (frame time 8.0 ms + about 1.1 us a draw, GfxProbe's windows); 93% of the view's 3,274 meshes were
    tiles beyond 750 m drawn with their full set of textures."""

    def test_far_level_cuts_draws(self):
        """The main view's proxy from every viewpoint (tools/citymap/view_proxy.py on the written file): Bata Chowk at
        most 1,500 meshes, every view at most 0.65 x run H's (the small near views gain least: Sector 16 Market)."""
        from tools.citymap import build_city, view_proxy
        # the tiles' instances (the far level's subject); the street life's X0 instances since 2026-11-04 are held to
        # the Run H fixes' numbers + 15% by test_streetlife.test_per_view_proxy
        tiles_only = [e for e in view_proxy.entries_of(city_bytes()) if e["name"].startswith("FTC_")]
        rows = view_proxy.report(tiles_only, _spawns() + build_city.VIEWPOINTS)
        for r in rows:
            print("\n  %-18s %5d instances %6d meshes (run H %5d) %8d triangles" % (
                r["name"], r["instances"], r["meshes"], RUNH_VIEW_MESHES[r["name"]], r["triangles"]), end="")
        got = {r["name"]: r["meshes"] for r in rows}
        self.assertLessEqual(got["Bata Chowk"], 1500)
        for name, m in got.items():
            self.assertLessEqual(m, 0.65 * RUNH_VIEW_MESHES[name], name)

    def test_far_switch_distance(self):
        """Every instance whose near model has 40 triangles or more switches to its far model at tiles.FAR_SWITCH
        (+-5%) in the game's rule (DrawAScenery 0x729120: slot 2 when pixel size / max(Density, 6) < 8.7, pixel size
        (radius + 6) H / (distance - radius - 6), H = build_city.VIEW_H), and every far model is one texture,
        FTC_FAR."""
        from tools.citymap import build_city, tiles, view_proxy
        n, bad, multi = 0, [], 0
        for e in view_proxy.entries_of(city_bytes()):
            m0, m2 = e["models"][0], e["models"][2]
            if not e["name"].startswith("FTC_"):
                continue  # the street life's X0 instances stop at their own distances (test_x0props)
            if m0["tris"] <= 39:
                continue  # never switches (NumPolys > 39 is the rule's first test); a few boundary-wall pieces
            if m2 is not None and set(m2["kinds"]) != {"FTC_FAR"}:
                multi += 1
            n += 1
            R = e["radius"] + 6.0
            d = R + R * build_city.VIEW_H / (8.7 * max(6.0, m0["density"]))
            if abs(d - tiles.FAR_SWITCH) > 0.05 * tiles.FAR_SWITCH:
                bad.append((e["name"], round(d)))
        print("\n  %d instances switch by distance: %d not at %.0f m (first %s); %d far models not FTC_FAR alone" % (
            n, len(bad), tiles.FAR_SWITCH, bad[:3], multi))
        self.assertGreater(n, 1000)
        self.assertEqual(bad, [])
        self.assertEqual(multi, 0)

    def test_far_never_near(self):
        """No forged near model can switch to the far one close up whatever the game's H (review, 2026-11-04): within
        2R the game's pixel size is H itself, so a model goes far there when H < 8.7 max(Density, 6). Every instance's
        near model keeps that bound under 400 (H is about 720-1000 at the user's 1920 px; build_city.VIEW_H assumes
        1000), so tiles stay small (no 530 m kerb quad stretching one, as run H's FTC_G_21_099)."""
        from tools.citymap import view_proxy
        worst = []
        for e in view_proxy.entries_of(city_bytes()):
            m0, m2 = e["models"][0], e["models"][2]
            if m0["tris"] <= 39 or m2 is None or m2["name"] == m0["name"]:
                continue
            worst.append((8.7 * max(6.0, m0["density"]), e["name"], round(e["radius"])))
        worst.sort(reverse=True)
        print("\n  near-branch bound 8.7 max(Density, 6), worst: %s" % [(round(b), n, r) for b, n, r in worst[:3]])
        self.assertLess(worst[0][0], 400.0)

    def test_far_colours_match(self):
        """The far atlas (FTC_FAR): one flat cell per texture the far models replace, each cell within 6 levels of its
        texture's mean (decoded from the written pack); every far triangle's uvs on one cell's centre."""
        tex = textures_by_name()
        far = tex["FTC_FAR"].astype(float)
        from tools.citymap import textures
        cells = textures.FAR_CELL
        side = far.shape[0] // cells
        cell_rgb = [far[(k // cells) * side:(k // cells + 1) * side, (k % cells) * side:(k % cells + 1) * side]
                    .reshape(-1, 3).mean(0) for k in range(cells * cells)]
        missing = []
        for name, img in tex.items():
            if name in ("FTC_FAR", "FTC_FURNITURE", "FTC_PAINT"):
                continue
            mean = img.reshape(-1, 3).astype(float).mean(0)
            if min(np.abs(c - mean).max() for c in cell_rgb) > 6.0:
                missing.append(name)
        w2 = written(2)
        sel = w2["tex"] == "FTC_FAR"
        uv = w2["UV"][sel]
        k = np.floor(uv * cells).astype(int)
        centre = (k + 0.5) / cells
        off = float(np.abs(uv - centre).max()) if len(uv) else 0.0
        same = bool((k == k[:, :1]).all()) if len(uv) else True
        print("\n  far atlas %dx%d cells; textures without a matching cell: %s; far triangles %d, worst uv off a cell "
              "centre %.5f" % (cells, cells, missing, int(sel.sum()), off))
        self.assertEqual(missing, [])
        self.assertGreater(int(sel.sum()), 100000)
        self.assertLess(off, 0.5 / (cells * side))
        self.assertTrue(same)


if __name__ == "__main__":
    unittest.main()
