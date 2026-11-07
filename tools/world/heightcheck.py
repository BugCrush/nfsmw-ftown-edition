"""A Python model of the game's height query, for checking collision packs before they reach the game.

WCollisionMgr::GetWorldHeightAtPoint (0x7897C0, World/Common/WCollisionMgr.cpp:342) -> WWorldPos::FindClosestFace
(WWorldPos.cpp:18) -> for every instance the grid hands it whose (x, z) distance from the point is under the
instance's radius (GetInstanceListGuts, WCollisionMgr.cpp:544, radius 0, cylinder test) -> FindFaceInCInst
(WCollisionMgr.cpp:196): the point into the instance's local space; outside |x| <= width, |z| <= length: nothing;
for every strip whose sphere (radius in 1/16 m, the (x, z) distance) holds the point, FindFaceInTriStrip
(WCollisionMgr.cpp:47) returns the strip's first triangle that holds the point in (x, z) (flags & 2: either winding;
else InTriR / InTriL alternating from flags & 1) and whose surface flags lack 8; the face counts when its lowest
corner is less than 0.5 m above the point and the point is above its plane (gap > 0); the smallest gap over all wins.
The height is the face's plane at the point, with the normal's y clamped to 0.9999 as the game does.

Not modelled: the grid (every instance of the pack is a candidate), instances with a turned up axis (flags & 3; none
in Rockport), the surface exclusion masks (the height query uses 0), and float32 rounding. The game's
GetWorldHeightAtPoint raises the point by 0.025 m first (WWorldPos(0.025f)): callers that model it add that to y.
All coordinates physics (y up).
"""
import math


def _pt_dir(p1, p2, t):
    return (p1[0] - p2[0]) * (t[2] - p2[2]) - (t[0] - p2[0]) * (p1[2] - p2[2])


def _in_tri(t, f):
    if _pt_dir(f[0], f[1], t) <= 0:
        return _pt_dir(f[1], f[2], t) <= 0 and _pt_dir(f[2], f[0], t) <= 0
    return _pt_dir(f[1], f[2], t) >= 0 and _pt_dir(f[2], f[0], t) >= 0


def _in_tri_r(t, f):
    return _pt_dir(f[0], f[1], t) <= 0 and _pt_dir(f[1], f[2], t) <= 0 and _pt_dir(f[2], f[0], t) <= 0


def _in_tri_l(t, f):
    return 0 <= _pt_dir(f[0], f[1], t) and 0 <= _pt_dir(f[1], f[2], t) and 0 <= _pt_dir(f[2], f[0], t)


def _normal(f):
    """CalcCollisionFaceNormal (WCollisionMgr.cpp:110): (p1 - p0) x (p0 - p2), unit, y made positive, y <= 0.9999."""
    vz = [f[1][a] - f[0][a] for a in range(3)]
    vx = [f[0][a] - f[2][a] for a in range(3)]
    n = (vz[1] * vx[2] - vz[2] * vx[1], vz[2] * vx[0] - vz[0] * vx[2], vz[0] * vx[1] - vz[1] * vx[0])
    L = math.sqrt(sum(x * x for x in n))
    n = (0.0, 1.0, 0.0) if L == 0 else tuple(x / L for x in n)
    if n[1] < 0:
        n = (-n[0], -n[1], -n[2])
    if n[1] >= 0.9999:
        n = (n[0], 0.9999, n[2])
    return n


def _plane_y(n, p, t):
    if n[1] == 0:
        return p[1]
    return p[1] - (n[0] * (t[0] - p[0]) + n[2] * (t[2] - p[2])) / n[1]


def _strip_face(st, t):
    pts = st.points()
    n = len(pts) - 2
    if st.flags & 2:
        for i in range(n):
            if not (st.surfaces[i] >> 8) & 8:
                f = pts[i:i + 3]
                if _in_tri(t, f) and min(p[1] for p in f) < t[1] + 1.0:
                    return f
        return None
    right = bool(st.flags & 1)
    for i in range(n):
        f = pts[i:i + 3]
        if not (st.surfaces[i] >> 8) & 8:
            if (right and _in_tri_r(t, f)) or (not right and _in_tri_l(t, f)):
                return f
        right = not right
    return None


def face_in_instance(pack, inst, x, y, z):
    """(gap, local face) of FindFaceInCInst for one instance, or None."""
    r0, r2, tr = inst.r0, inst.r2, inst.t
    r1 = (0.0, 1.0, 0.0)
    t = tuple(x * r0[a] + y * r1[a] + z * r2[a] + tr[a] for a in range(3))
    if abs(t[0]) > inst.width or abs(t[2]) > inst.length:
        return None
    art = pack.articles[inst.article]
    best = None
    for st in art.strips:
        dx, dz = st.centre[0] - t[0], st.centre[2] - t[2]
        rad = st.radius / 16.0
        if dx * dx + dz * dz >= rad * rad:
            continue
        f = _strip_face(st, t)
        if f is None:
            continue
        n = _normal(f)
        gap = t[1] - _plane_y(n, f[0], t)
        if min(p[1] for p in f) - 0.5 < t[1] and 0 < gap and (best is None or gap < best[0]):
            best = (gap, f, n)
    return best


def height_at(pack, x, z, y):
    """The height of the face the game's query finds below physics point (x, y, z), or None (no face)."""
    best = None
    for inst in pack.instances:
        if inst.flags & 3:
            raise ValueError("instances with a turned up axis are not modelled")
        r0, r2, tr = inst.r0, inst.r2, inst.t
        # CalcPosition (WCollision.cpp:34): -(t . r0), -(t . r1), -(t . r2) with r1 = (0, 1, 0)
        pos = (-(tr[0] * r0[0] + tr[1] * r0[1] + tr[2] * r0[2]), -tr[1],
               -(tr[0] * r2[0] + tr[1] * r2[1] + tr[2] * r2[2]))
        if (pos[0] - x) ** 2 + (pos[2] - z) ** 2 >= inst.radius ** 2:
            continue
        hit = face_in_instance(pack, inst, x, y, z)
        if hit is not None and (best is None or hit[0] < best[0]):
            best = (hit[0], inst, hit[1], hit[2])
    if best is None:
        return None
    _gap, inst, f, n = best
    t = tuple(x * inst.r0[a] + y * (0.0, 1.0, 0.0)[a] + z * inst.r2[a] + inst.t[a] for a in range(3))
    local_h = _plane_y(n, f[0], t)
    # back to world: the local y differs from the world y by the translation's y (r1 = (0, 1, 0))
    return local_h - inst.t[1]
