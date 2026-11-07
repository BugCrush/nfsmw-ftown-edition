"""Rockport's triangle winding against its own vertex normals, measured from the game's files (read only; numbers only),
the reference for F-Town's walls (docs/ftown-notes.md "Run H fixes (2026-11-04)", fault 1).

    .tools/cityenv/Scripts/python tools/citymap/rockport_winding.py [sections]

For every kind-0 (36-byte vertex) mesh of the placed scenery of the first `sections` sections of STREAML2RA.BUN (all
by default): each triangle's right-hand normal (B - A) x (C - A) against the mean of its three stored vertex normals
(bytes 12-24, the normals the world shader lights with), area weighted, for walls (|normal z| < 0.25), upward faces
(z > 0.9) and the rest; and the same for instances whose matrix mirrors (determinant < 0), which flips a winding.
Rockport's walls are lit on their outside, so where the two agree, the game draws a face whose right-hand winding
normal points to the viewer (and culls the other side).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

from world import bun, scenery  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")


def measure(max_sections=None):
    acc = {}

    def add(key, agree, area):
        s = acc.setdefault(key, [0.0, 0.0, 0])
        s[0] += float(area[agree].sum())
        s[1] += float(area.sum())
        s[2] += int(len(area))
    rng = np.random.default_rng(1)
    for n, s in enumerate(bun.sections(L2RA)):
        if max_sections is not None and n >= max_sections:
            break
        solids, scs = {}, []
        for c, p in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
            if c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        try:
                            so = scenery.read_solid(k, kp)
                        except (ValueError, struct.error):
                            continue
                        solids[so.name_hash] = so
            elif c.id == scenery.SCENERY_SECTION:
                scs.append(scenery.read_scenery(c, p))
        walls_up = []
        for sc in scs:
            for inst in sc.instances:
                so = solids.get(sc.infos[inst.info_index].solid_hashes[0])
                if so is None:
                    continue
                R = np.array([r[:3] for r in inst.matrix[:3]], dtype=np.float64)
                T = np.array(inst.matrix[3][:3], dtype=np.float64)
                mirrored = np.linalg.det(R) < 0
                for k, m in enumerate(so.meshes):
                    if m.kind != 0 or so.stride(m.buffer) != 36:
                        continue
                    tri = np.array(so.triangles(k), dtype=np.int64)
                    if not len(tri):
                        continue
                    buf = so.vertex_buffers[m.buffer]
                    vs = np.frombuffer(buf[m.vertex_offset * 36:(m.vertex_offset + m.vertex_count) * 36],
                                       dtype=np.uint8).reshape(-1, 36)
                    pos = vs[:, 0:12].copy().view(np.float32).reshape(-1, 3).astype(np.float64)
                    nrm = vs[:, 12:24].copy().view(np.float32).reshape(-1, 3).astype(np.float64)
                    A, B, C = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
                    w = np.cross(B - A, C - A)
                    area = 0.5 * np.linalg.norm(w, axis=1)
                    ok = area > 1e-6
                    stored = nrm[tri[:, 0]] + nrm[tri[:, 1]] + nrm[tri[:, 2]]
                    agree = (w * stored).sum(1) > 0
                    # world-space vertical part of the winding normal (the matrix rows place the solid)
                    wz = (w @ R)[:, 2] / np.maximum(1e-12, 2 * area)
                    kind = np.where(np.abs(wz) < 0.25, "walls", np.where(wz > 0.9, "up", "other"))
                    if not mirrored:
                        walls_up.append((A @ R + T, B @ R + T, C @ R + T, w @ R, (np.abs(wz) < 0.25) & ok,
                                         (wz > 0.9) & ok))
                    tag = " (mirrored instances)" if mirrored else ""
                    for kd in ("walls", "up", "other"):
                        sel = ok & (kind == kd)
                        if sel.any():
                            add(kd + tag, agree[sel], area[sel])
        _outward(walls_up, acc, rng)
    return acc


def _outward(walls_up, acc, rng, per_section=200):
    """For sampled walls of a section: is there an upward face (ground) under the point 1 m in front of the wall (the
    side its winding normal points to) at or below the wall's bottom, and under the point 1 m behind it? A building's
    wall has ground in front and none behind (its inside); counted where exactly one side has ground."""
    if not walls_up:
        return
    A = np.concatenate([x[0] for x in walls_up])
    B = np.concatenate([x[1] for x in walls_up])
    C = np.concatenate([x[2] for x in walls_up])
    W = np.concatenate([x[3] for x in walls_up])
    iw = np.flatnonzero(np.concatenate([x[4] for x in walls_up]))
    iu = np.flatnonzero(np.concatenate([x[5] for x in walls_up]))
    if not len(iw) or not len(iu):
        return
    ua, ub, uc = A[iu], B[iu], C[iu]
    lo = np.minimum(np.minimum(ua, ub), uc)
    hi = np.maximum(np.maximum(ua, ub), uc)
    pick = rng.choice(iw, min(per_section, len(iw)), replace=False)
    for i in pick:
        cen = (A[i] + B[i] + C[i]) / 3.0
        bottom = min(A[i][2], B[i][2], C[i][2])
        n = W[i][:2] / (np.linalg.norm(W[i][:2]) or 1.0)
        has = []
        for sgn in (1.0, -1.0):
            x, y = cen[0] + sgn * n[0], cen[1] + sgn * n[1]
            m = (lo[:, 0] <= x) & (x <= hi[:, 0]) & (lo[:, 1] <= y) & (y <= hi[:, 1]) & (lo[:, 2] <= bottom + 0.5)
            hit = False
            for j in np.flatnonzero(m):
                a, b, c = ua[j], ub[j], uc[j]
                d1 = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
                d2 = (c[0] - b[0]) * (y - b[1]) - (c[1] - b[1]) * (x - b[0])
                d3 = (a[0] - c[0]) * (y - c[1]) - (a[1] - c[1]) * (x - c[0])
                if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
                    hit = True
                    break
            has.append(hit)
        if has[0] != has[1]:
            s = acc.setdefault("walls with ground on one side only", [0.0, 0.0, 0])
            s[0] += 1.0 if has[0] else 0.0
            s[1] += 1.0
            s[2] += 1


def main(argv):
    acc = measure(int(argv[0]) if argv else None)
    for key, (a, t, n) in sorted(acc.items()):
        if key.startswith("walls with ground"):
            print("%s: %d sampled, the ground in front of the winding normal on %.2f%%" % (key, n, 100.0 * a / t))
            continue
        print("%-28s %9d triangles %12.0f m2: winding normal agrees with the stored normal on %.2f%% of the area"
              % (key, n, t, 100.0 * a / t if t else 0.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
