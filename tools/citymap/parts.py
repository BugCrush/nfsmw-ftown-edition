"""Drawn pieces added to F-Town's tiles beyond the streets (landmarks, the metro, street furniture): triangles in render
metres with their texture kind, uvs and pre-lit colours, and the barriers that go with them.

A Part goes into the tile of its first triangle's centroid (tiles.CityGeometry.add_parts); `inst` names the tile's
scenery instance ("build": every view, shadows too; "ground" with levels ("A",): the main view near only, the shadow and
reflection views draw the ground's C level, docs/ftown-notes.md "Stage 2"). A kind is a key of textures.NAMES or a
texture's own name (FTL_* photo textures, tools/citymap/phototex.py).
"""
import math
import os
import sys
from dataclasses import dataclass, field

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

SUN = (0.45, -0.55, 0.70)  # tiles.SUN: the walls' baked shading
WALL_GREY = 62.0  # tiles' plaster grey (Rockport's walls' vertex greys 47-78, median 56)
ALL = ("A", "B", "C", "D")
# detail the far level leaves out (the landmarks plan's Task 7): the buildings instance's slots 2 and 3 (far in the main
# view; the shadow and reflection views) draw its C model, made without these
DETAIL = ("A", "B")


@dataclass
class Part:
    inst: str
    kind: str
    tris: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    cols: list = field(default_factory=list)
    levels: tuple = ALL
    tag: str = ""

    def add(self, tris, uvs, col):
        self.tris += tris
        self.uvs += uvs
        self.cols += [col] * len(tris) if isinstance(col, int) else col


def colour(rgb):
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return 0xFF000000 | (r << 16) | (g << 8) | b


def normal(t):
    a, b, c = t
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    L = math.sqrt(sum(x * x for x in n)) or 1.0
    return tuple(x / L for x in n)


def shade(n):
    return 0.80 + 0.25 * max(0.0, n[0] * SUN[0] + n[1] * SUN[1] + n[2] * SUN[2])


def lit(t, grey=WALL_GREY, tint=(1.0, 1.0, 1.0)):
    s = shade(normal(t))
    return colour(tuple(grey * s * k for k in tint))


def wall(p, q, z0, z1, u0, u1, v0=0.0, v1=1.0, out_right=True):
    """A vertical quad p -> q (render x, y), z0..z1, facing the right of p -> q (out_right) or its left; u runs u0 at p
    to u1 at q, v from v0 at the top to v1 at the bottom (a texture's top row first). Facing: its right-hand normal
    points there (the side the game draws; Run H fixes, fault 1)."""
    A, B, C, D = (p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)
    ua, ub, vt, vb = u0, u1, v0, v1
    if not out_right:
        return [(A, C, B), (A, D, C)], [((ua, vb), (ub, vt), (ub, vb)), ((ua, vb), (ua, vt), (ub, vt))]
    return [(A, B, C), (A, C, D)], [((ua, vb), (ub, vb), (ub, vt)), ((ua, vb), (ub, vt), (ua, vt))]


def tiled_wall(p, q, z0, z1, tile_u, tile_v, out_right=True, u_start=0.0):
    L = math.dist(p, q)
    return wall(p, q, z0, z1, u_start / tile_u, (u_start + L) / tile_u, 0.0, (z1 - z0) / tile_v, out_right)


def flat(poly_tris, z, tile_u, tile_v, up=True):
    """Horizontal triangles (2D, counter-clockwise) at height z, facing up (or down: winding reversed)."""
    tris, uvs = [], []
    for t in poly_tris:
        t3 = tuple((p[0], p[1], z) for p in t)
        if not up:
            t3 = (t3[0], t3[2], t3[1])
        tris.append(t3)
        uvs.append(tuple((p[0] / tile_u, -p[1] / tile_v) for p in t3))
    return tris, uvs


def box(cx, cy, ax, ay, half_a, half_b, z0, z1):
    """The four corners (counter-clockwise) of a rectangle centred (cx, cy), its first axis (ax, ay) unit."""
    bx, by = -ay, ax
    return [(cx + ax * half_a * sa + bx * half_b * sb, cy + ay * half_a * sa + by * half_b * sb)
            for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def prism(part, ring, z0, z1, tile_u, tile_v, grey=WALL_GREY, top=False, bottom=False, tint=(1, 1, 1)):
    """Walls round a counter-clockwise ring (outside on the right) from z0 to z1, optional top and bottom faces."""
    for p, q in zip(ring, ring[1:] + ring[:1]):
        if math.dist(p, q) < 0.01:
            continue
        tris, uvs = tiled_wall(p, q, z0, z1, tile_u, tile_v)
        part.add(tris, uvs, [lit(t, grey, tint) for t in tris])
    if top or bottom:
        fan = [(ring[0], ring[k], ring[k + 1]) for k in range(1, len(ring) - 1)]
        if top:
            tris, uvs = flat(fan, z1, tile_u, tile_v, True)
            part.add(tris, uvs, colour((grey * 1.0,) * 3))
        if bottom:
            tris, uvs = flat(fan, z0, tile_u, tile_v, False)
            part.add(tris, uvs, colour((grey * 0.8,) * 3))


def quad(q, quv, want):
    """Two triangles of the quad q (four 3D points in order round it) with uvs quv, wound to face `want` by the city's
    own conventions (tools/citymap/tiles.py): counter-clockwise seen from the side it faces, its right-hand normal
    towards `want` (the side the game draws, as surfaces.triangulate's ground; Run H fixes, fault 1: vertical faces
    were wound away from `want` before)."""
    tris, uvs = [], []
    for i, j, k in ((0, 1, 2), (0, 2, 3)):
        t, u = (q[i], q[j], q[k]), (quv[i], quv[j], quv[k])
        n = normal(t)
        d = n[0] * want[0] + n[1] * want[1] + n[2] * want[2]
        if d < 0:
            t, u = (t[0], t[2], t[1]), (u[0], u[2], u[1])
        tris.append(t)
        uvs.append(u)
    return tris, uvs


class PartSet:
    """Parts by (instance, kind, levels), filled in order."""

    def __init__(self, tag=""):
        self.parts = {}
        self.tag = tag

    def get(self, kind, inst="build", levels=ALL):
        k = (inst, kind, levels)
        if k not in self.parts:
            self.parts[k] = Part(inst, kind, levels=levels, tag=self.tag)
        return self.parts[k]

    def all(self):
        return [p for p in self.parts.values() if p.tris]


def faced_wall(ps, p, q, z0, z1, finish, finish_tile, face=None, photo_kind=None, grey=WALL_GREY, tint=(1, 1, 1),
               photo_glow=None):
    """A wall p -> q (outside on the right) from z0 to z1 in the finish texture (tiled every finish_tile metres), with
    the face's photo crop (photo_kind, a Face of tools/citymap/landmarks.py) over its span and heights: centred at
    face.at over face.width_m metres (the whole edge when width_m is None; repeated every width_m when face.repeat),
    face.z (default z0..z1). A crop above z1 (a rooftop sign) stands on the roof line, its back in the finish.
    photo_glow: the evening's glow class of the face (tools/citymap/evening.py), or None."""
    L = math.dist(p, q)
    if L < 0.01:
        return
    tu, tv = finish_tile
    fin = ps.get(finish)

    def at(s):
        return (p[0] + (q[0] - p[0]) * s / L, p[1] + (q[1] - p[1]) * s / L)

    def finish_rect(s0, s1, za, zb):
        if s1 - s0 < 0.01 or zb - za < 0.01:
            return
        tris, uvs = wall(at(s0), at(s1), za, zb, s0 / tu, s1 / tu, (z1 - zb) / tv, (z1 - za) / tv)
        fin.add(tris, uvs, [lit(t, grey, tint) for t in tris])

    if face is None or photo_kind is None:
        finish_rect(0.0, L, z0, z1)
        return
    za, zb = face.z if face.z else (z0, z1)
    w = min(face.width_m or L, L)
    if face.repeat:
        s0, s1 = 0.0, L
        u1 = L / (face.width_m or L)
    else:
        s0 = min(max(0.0, face.at * L - w / 2), L - w)
        s1 = s0 + w
        u1 = 1.0
    ph = ps.get(photo_kind)
    tris, uvs = wall(at(s0), at(s1), za, zb, 0.0, u1, 0.0, 1.0)
    cols = [lit(t, 68.0) for t in tris]
    if photo_glow is not None:
        from tools.citymap import evening
        cols = [evening.glow(c, photo_glow) for c in cols]
    ph.add(tris, uvs, cols)
    if za >= z1 - 0.01:  # a sign on the roof: the wall below whole, the sign's back in the finish
        finish_rect(0.0, L, z0, z1)
        # the back 3 cm behind the photo (not in its plane: two faces in one plane flicker where nothing culls them)
        ix, iy = -(q[1] - p[1]) / L * 0.03, (q[0] - p[0]) / L * 0.03
        a, b = at(s0), at(s1)
        tris, uvs = wall((a[0] + ix, a[1] + iy), (b[0] + ix, b[1] + iy), za, zb, 0.0, w / tu, 0.0, (zb - za) / tv,
                         out_right=False)
        fin.add(tris, uvs, [lit(t, grey * 0.8) for t in tris])
        return
    zb = min(zb, z1)
    finish_rect(0.0, s0, z0, z1)
    finish_rect(s1, L, z0, z1)
    finish_rect(s0, s1, z0, za)
    finish_rect(s0, s1, zb, z1)


def ring_barriers(ring, z0, z1, flags=None):
    """Barriers round a counter-clockwise ring, each facing out (the right of p -> q, notes "City fixes" 4)."""
    out = []
    for p, q in zip(ring, ring[1:] + ring[:1]):
        if math.dist(p, q) >= 0.05:
            out.append((p, q, z0, z1) + ((flags,) if flags is not None else ()))
    return out
