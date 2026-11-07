"""The game's height query over many points at once (numpy), for checking a whole city's collision.

The same rules as tools/world/heightcheck.py (WCollisionMgr::GetWorldHeightAtPoint -> FindClosestFace ->
FindFaceInCInst -> FindFaceInTriStrip, notes Q4 and "Part 2: writers"), which agrees with Rockport at 2,000 of 2,000
points: an instance counts when the point's (x, z) distance from its position is under its radius and the point lies
in its local box; a strip counts when the point is inside its sphere (radius in 1/16 m); in a strip the **first**
triangle holding the point (InTriR / InTriL alternating from the strip's flags bit 0, InTri for bit 1; faces whose
surface word has flag 8 skipped; for InTri strips also the lowest corner less than 1 m above the point, as
heightcheck's _strip_face) is the strip's face; the face counts when its lowest corner is less than 0.5 m above the
point and the point is above its plane (normal y clamped to 0.9999); the smallest gap wins. Instances are taken as heightcheck does: rows (1, 0, 0) / (0, 0, 1) (make_pack's;
a turned instance raises). Checked against heightcheck by tools/citymap/tests/test_city.py.
"""
import math

import numpy as np


class HeightModel:
    def __init__(self, packs, cell=128.0):
        self.cell = cell
        self.items = []  # per instance: dict of arrays
        self.buckets = {}
        for pack in packs:
            for inst in pack.instances:
                if inst.flags & 3:
                    raise ValueError("instances with a turned up axis are not modelled")
                if inst.r0 != (1.0, 0.0, 0.0) or inst.r2 != (0.0, 0.0, 1.0):
                    raise ValueError("only unrotated instances are modelled")
                art = pack.articles[inst.article]
                self._add(inst, art)

    def _add(self, inst, art):
        tr = inst.t
        A, B, C, mode, first, sph = [], [], [], [], [], []
        scen, srad = [], []
        fflags, fsurf = [], []
        for si, st in enumerate(art.strips):
            pts = st.points()
            n = len(pts) - 2
            right = bool(st.flags & 1)
            for i in range(n):
                skip = (st.surfaces[i] >> 8) & 8
                f = pts[i:i + 3]
                m = 2 if st.flags & 2 else (0 if right else 1)
                if not st.flags & 2:
                    right = not right
                if skip:
                    continue
                A.append(f[0])
                B.append(f[1])
                C.append(f[2])
                mode.append(m)
                first.append(si)
                fflags.append(st.surfaces[i] >> 8)
                si_ = st.surfaces[i] & 0xFF
                fsurf.append(art.surfaces[si_] if si_ < len(art.surfaces) else 0)
            scen.append(st.centre)
            srad.append(st.radius / 16.0)
        rec = {
            "pos": (-tr[0], -tr[1], -tr[2]), "radius": inst.radius, "w": inst.width, "l": inst.length, "t": tr,
            "A": np.array(A, dtype=float).reshape(-1, 3), "B": np.array(B, dtype=float).reshape(-1, 3),
            "C": np.array(C, dtype=float).reshape(-1, 3), "mode": np.array(mode, dtype=int),
            "strip": np.array(first, dtype=int), "scen": np.array(scen, dtype=float).reshape(-1, 3),
            "srad": np.array(srad, dtype=float), "flags": np.array(fflags, dtype=int),
            "surf": np.array(fsurf, dtype=np.int64),
        }
        k = len(self.items)
        self.items.append(rec)
        x, z = rec["pos"][0], rec["pos"][2]
        r = rec["radius"]
        for i in range(int(math.floor((x - r) / self.cell)), int(math.floor((x + r) / self.cell)) + 1):
            for j in range(int(math.floor((z - r) / self.cell)), int(math.floor((z + r) / self.cell)) + 1):
                self.buckets.setdefault((i, j), []).append(k)

    @staticmethod
    def _dir(p1, p2, t):
        # PtDir4 in the xz plane: (p1.x - p2.x) (t.z - p2.z) - (t.x - p2.x) (p1.z - p2.z); p1, p2 (n, 3), t (m, 3)
        return (p1[None, :, 0] - p2[None, :, 0]) * (t[:, None, 2] - p2[None, :, 2]) - \
            (t[:, None, 0] - p2[None, :, 0]) * (p1[None, :, 2] - p2[None, :, 2])

    def heights(self, x, z, y):
        """Physics points (arrays x, z, y): the height of the face the game's query finds, NaN where none."""
        x, z, y = np.asarray(x, float), np.asarray(z, float), np.asarray(y, float)
        best_gap = np.full(len(x), np.inf)
        best_h = np.full(len(x), np.nan)
        keys = {}
        for n, (a, b) in enumerate(zip(np.floor(x / self.cell).astype(int), np.floor(z / self.cell).astype(int))):
            keys.setdefault((int(a), int(b)), []).append(n)
        todo = {}
        for key, idx in keys.items():
            for k in self.buckets.get(key, ()):
                todo.setdefault(k, []).extend(idx)
        for k, idx in todo.items():
            rec = self.items[k]
            idx = np.array(idx)
            px, pz = x[idx], z[idx]
            d2 = (rec["pos"][0] - px) ** 2 + (rec["pos"][2] - pz) ** 2
            keep = d2 < rec["radius"] ** 2
            tr = rec["t"]
            lx, lz = px + tr[0], pz + tr[2]
            keep &= (np.abs(lx) <= rec["w"]) & (np.abs(lz) <= rec["l"])
            if not keep.any() or len(rec["A"]) == 0:
                continue
            for part in np.array_split(idx[keep], max(1, int(math.ceil(keep.sum() / 400)))):
                self._query(rec, part, x, y, z, best_gap, best_h)
        return best_h

    def wheel_heights(self, x, z, y, reverse=False):
        """The wheels' ground query over many points (physics arrays x, z, y): WWorldPos::FindClosestFace on the
        collider's triangle list (WWorldPos.cpp:100, PC 0x779170, read in the code): the faces in list order (here:
        instances in pack order, strips in article order, triangles in strip order; `reverse` walks it backwards),
        each face holding the point in (x, z) (either winding) whose plane is less than 1 m above it (dist > -1) is
        taken when its dist is smaller than the one held; the search **stops at a taken face whose surface flags lack
        4**. So without flag 4 the first face in the list wins, wherever it is in height. Returns the taken face's
        height (NaN where none).

        Not modelled (review): the game's shortcut at 0x779187..0x7791CD: a WWorldPos that already holds a face
        still holding the point in (x, z) (0x762D00) keeps it without a search, whatever its height, so a wheel can
        carry a face from one frame to the next. Harmless for this city (no ground lies under the low ramps a wheel
        could carry onto a deck), but a change that puts faces under low ramps is not proven safe by this model.
        The candidates are also more than the game's list holds (no instance box, strip sphere or flag-8 test): the
        model is the stricter."""
        x, z, y = np.asarray(x, float), np.asarray(z, float), np.asarray(y, float)
        cand = self.candidates(x, z)
        out = np.full(len(x), np.nan)
        for n, cs in enumerate(cand):
            cs.sort(reverse=reverse)
            best, got = 1e38, None
            for c in cs:
                h, fl = c[2], c[3]
                dist = y[n] - h
                if -1.0 < dist < best:
                    best, got = dist, h
                    if not fl & 4:
                        break
            if got is not None:
                out[n] = got
        return out

    def wheel_surfaces(self, x, z, y, reverse=False):
        """As wheel_heights, but (height, surface name hash) of the taken face per point ((nan, 0) where none)."""
        x, z, y = np.asarray(x, float), np.asarray(z, float), np.asarray(y, float)
        out = []
        for n, cs in enumerate(self.candidates(x, z)):
            cs.sort(reverse=reverse)
            best, got = 1e38, (float("nan"), 0)
            for c in cs:
                dist = y[n] - c[2]
                if -1.0 < dist < best:
                    best, got = dist, (c[2], c[4])
                    if not c[3] & 4:
                        break
            out.append(got)
        return out

    def candidates(self, x, z):
        """Per point (physics arrays x, z): every face holding it in (x, z), either winding, as (instance number,
        face number, plane height, surface flags, surface name hash), in no particular order."""
        x, z = np.asarray(x, float), np.asarray(z, float)
        y = np.zeros(len(x))
        cand = [[] for _ in range(len(x))]
        keys = {}
        for n, (a, b) in enumerate(zip(np.floor(x / self.cell).astype(int), np.floor(z / self.cell).astype(int))):
            keys.setdefault((int(a), int(b)), []).append(n)
        todo = {}
        for key, idx in keys.items():
            for k in self.buckets.get(key, ()):
                todo.setdefault(k, []).extend(idx)
        for k, idx in todo.items():
            rec = self.items[k]
            if len(rec["A"]) == 0:
                continue
            tr = rec["t"]
            A, B, C = rec["A"], rec["B"], rec["C"]
            idx = np.array(idx)
            for part in np.array_split(idx, max(1, int(math.ceil(len(idx) / 400)))):
                T = np.stack([x[part] + tr[0], y[part] + tr[1], z[part] + tr[2]], axis=1)
                d0, d1, d2 = self._dir(A, B, T), self._dir(B, C, T), self._dir(C, A, T)
                hold = np.where(d0 <= 0, (d1 <= 0) & (d2 <= 0), (d1 >= 0) & (d2 >= 0))
                if not hold.any():
                    continue
                nrm = np.cross(B - A, A - C)
                L = np.linalg.norm(nrm, axis=1)
                nrm = np.where(L[:, None] > 0, nrm / np.where(L[:, None] > 0, L[:, None], 1), np.array([0, 1.0, 0]))
                nrm = np.where(nrm[:, 1:2] < 0, -nrm, nrm)
                nrm[:, 1] = np.minimum(nrm[:, 1], 0.9999)
                pi, fi = np.nonzero(hold)
                ny = nrm[fi, 1]
                plane = A[fi, 1] - (nrm[fi, 0] * (T[pi, 0] - A[fi, 0]) + nrm[fi, 2] * (T[pi, 2] - A[fi, 2])) / \
                    np.where(ny == 0, 1, ny)
                for p_, f_, h_ in zip(pi, fi, plane):
                    cand[part[p_]].append((k, int(f_), float(h_ - tr[1]), int(rec["flags"][f_]),
                                           int(rec["surf"][f_])))
        return cand

    def _query(self, rec, idx, x, y, z, best_gap, best_h):
        tr = rec["t"]
        T = np.stack([x[idx] + tr[0], y[idx] + tr[1], z[idx] + tr[2]], axis=1)
        A, B, C = rec["A"], rec["B"], rec["C"]
        d0 = self._dir(A, B, T)
        d1 = self._dir(B, C, T)
        d2_ = self._dir(C, A, T)
        mode = rec["mode"][None, :]
        r_ok = (d0 <= 0) & (d1 <= 0) & (d2_ <= 0)
        l_ok = (d0 >= 0) & (d1 >= 0) & (d2_ >= 0)
        either = np.where(d0 <= 0, (d1 <= 0) & (d2_ <= 0), (d1 >= 0) & (d2_ >= 0))
        hold = np.where(mode == 0, r_ok, np.where(mode == 1, l_ok, either))
        # the strip's sphere must hold the point
        sc = rec["scen"][rec["strip"]]
        sr = rec["srad"][rec["strip"]]
        inside = (sc[None, :, 0] - T[:, None, 0]) ** 2 + (sc[None, :, 2] - T[:, None, 2]) ** 2 < sr[None, :] ** 2
        hold &= inside
        # heightcheck's _strip_face: for either-winding strips (flags bit 1) the triangle also needs its lowest
        # corner less than 1 m above the point
        low = np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1])
        hold &= (mode != 2) | (low[None, :] < T[:, None, 1] + 1.0)
        # only the first holding triangle of each strip
        strip = rec["strip"]
        cs = np.cumsum(hold, axis=1)
        starts = np.r_[0, np.nonzero(np.diff(strip))[0] + 1]
        start_of = np.repeat(starts, np.diff(np.r_[starts, len(strip)]))
        base = np.where(start_of > 0, cs[:, np.maximum(start_of - 1, 0)], 0)
        firsts = hold & ((cs - base) == 1)
        # the face's plane: CalcCollisionFaceNormal
        vz = B - A
        vx = A - C
        nrm = np.cross(vz, vx)
        L = np.linalg.norm(nrm, axis=1)
        nrm = np.where(L[:, None] > 0, nrm / np.where(L[:, None] > 0, L[:, None], 1), np.array([0, 1.0, 0]))
        nrm = np.where(nrm[:, 1:2] < 0, -nrm, nrm)
        nrm[:, 1] = np.minimum(nrm[:, 1], 0.9999)
        ny = nrm[None, :, 1]
        plane = A[None, :, 1] - (nrm[None, :, 0] * (T[:, None, 0] - A[None, :, 0]) +
                                 nrm[None, :, 2] * (T[:, None, 2] - A[None, :, 2])) / np.where(ny == 0, 1, ny)
        gap = T[:, None, 1] - plane
        ok = firsts & (gap > 0) & (low[None, :] - 0.5 < T[:, None, 1])
        gap = np.where(ok, gap, np.inf)
        j = np.argmin(gap, axis=1)
        g = gap[np.arange(len(idx)), j]
        h = plane[np.arange(len(idx)), j] - tr[1]
        better = g < best_gap[idx]
        best_gap[idx[better]] = g[better]
        best_h[idx[better]] = h[better]
