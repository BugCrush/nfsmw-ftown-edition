"""Our own simple street furniture models for F-Town (no game data): in local metres, x along the road (forward), y to
its left, z up from the model's foot; each triangle with a cell of the furniture atlas (textures.FURNITURE_CELLS: a
solid colour) or, for a billboard's face, a uv in the billboard atlas. Wound by the city's conventions (parts.quad).

- lamp_sector: the sector roads' lamp post with its triangular lantern frame (photo 01): a 9 m pole, an inverted
  triangle hung across the road at its top, the lamp in its middle;
- light_trunk: Mathura Road's street light: a 10 m pole with two arms over both carriageways;
- signal: a 3.4 m pole with a three-lamp head (red, amber, green) facing both ways along the road;
- billboard: a 10 x 2.5 m board 4 m up on two posts, its face (one of textures.BILLBOARDS designs) to +y;
- railing: Mathura Road's yellow median railing (photos 37, 40): two rails and posts every 2.5 m, 1.1 m high.
"""
import math
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import parts as P  # noqa: E402
from tools.citymap import textures  # noqa: E402


def _box(out, x0, x1, y0, y1, z0, z1, cell, top=True):
    """An axis-aligned box's sides (and top) into out [(tri, cell)]."""
    faces = [([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
             ([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], (-1, 0, 0)),
             ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
             ([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], (0, 1, 0))]
    if top:
        faces.append(([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)))
    for q, want in faces:
        tris, _uv = P.quad(q, [(0, 0)] * 4, want)
        out += [(t, cell) for t in tris]


def _ribbon(out, a, b, w, normal_axis, cell):
    """A flat bar from a to b (3D), w wide, in the plane whose normal is normal_axis; drawn on both sides."""
    d = [b[i] - a[i] for i in range(3)]
    L = math.sqrt(sum(x * x for x in d)) or 1.0
    d = [x / L for x in d]
    n = normal_axis
    s = (d[1] * n[2] - d[2] * n[1], d[2] * n[0] - d[0] * n[2], d[0] * n[1] - d[1] * n[0])
    h = w / 2
    q = [tuple(a[i] - s[i] * h for i in range(3)), tuple(b[i] - s[i] * h for i in range(3)),
         tuple(b[i] + s[i] * h for i in range(3)), tuple(a[i] + s[i] * h for i in range(3))]
    for want in (n, tuple(-x for x in n)):
        tris, _uv = P.quad(q, [(0, 0)] * 4, want)
        out += [(t, cell) for t in tris]


def lamp_sector():
    out = []
    _box(out, -0.09, 0.09, -0.09, 0.09, 0.0, 9.0, "metal")
    top, bot, half = 9.3, 7.7, 0.9
    a, b, c = (0.0, -half, top), (0.0, half, top), (0.0, 0.0, bot)
    for p, q in ((a, b), (b, c), (c, a)):
        _ribbon(out, p, q, 0.09, (1, 0, 0), "white")
    _box(out, -0.15, 0.15, -0.15, 0.15, 8.45, 8.85, "lantern")
    return out


def light_trunk():
    out = []
    _box(out, -0.13, 0.13, -0.13, 0.13, 0.0, 10.0, "metal")
    for sg in (1, -1):
        y0, y1 = sorted((0.0, sg * 2.2))
        _box(out, -0.06, 0.06, y0, y1, 9.8, 9.92, "metal")
        y0, y1 = sorted((sg * 1.6, sg * 2.4))
        _box(out, -0.18, 0.18, y0, y1, 9.65, 9.85, "lantern")
    return out


def signal():
    out = []
    _box(out, -0.08, 0.08, -0.08, 0.08, 0.0, 2.4, "darkmetal")
    _box(out, -0.18, 0.18, -0.18, 0.18, 2.4, 3.4, "black")
    for x, want in ((0.181, (1, 0, 0)), (-0.181, (-1, 0, 0))):
        for k, cell in enumerate(("red", "amber", "green")):
            z0 = 3.3 - (k + 1) * 0.3 + 0.04
            q = [(x, -0.11, z0), (x, 0.11, z0), (x, 0.11, z0 + 0.22), (x, -0.11, z0 + 0.22)]
            tris, _uv = P.quad(q, [(0, 0)] * 4, want)
            out += [(t, cell) for t in tris]
    return out


def billboard(design):
    """(furniture triangles [(tri, cell)], face triangles [(tri, uvs)]): the board along x (10 m), its face to +y
    (towards the road when placed with y to the road), design k of the atlas."""
    out, face = [], []
    for x in (-3.5, 3.5):
        _box(out, x - 0.15, x + 0.15, -0.15, 0.15, 0.0, 4.0, "metal")
    _box(out, -5.0, 5.0, -0.2, 0.0, 4.0, 6.5, "darkmetal")
    u0, v0, u1, v1 = textures.billboard_rect(design)
    e = 0.5 / textures.SIDES["furniture"]  # half a texel inside the design's rectangle
    u0, v0, u1, v1 = u0 + e, v0 + e, u1 - e, v1 - e
    q = [(-5.0, 0.01, 4.0), (5.0, 0.01, 4.0), (5.0, 0.01, 6.5), (-5.0, 0.01, 6.5)]
    tris, uvs = P.quad(q, [(u1, v1), (u0, v1), (u0, v0), (u1, v0)], (0, 1, 0))
    face += list(zip(tris, uvs))
    return out, face


def metro_lamp():
    """The viaduct's deck light (the evening, docs/ftown-notes.md "Evening (2026-11-05)"): a 2.4 m post on the
    parapet's top, a lantern at its head leaning over the deck (+y)."""
    out = []
    _box(out, -0.06, 0.06, -0.06, 0.06, 0.0, 2.4, "darkmetal")
    _box(out, -0.05, 0.05, 0.0, 0.7, 2.3, 2.4, "darkmetal")
    _box(out, -0.14, 0.14, 0.45, 0.85, 2.15, 2.3, "lantern")
    return out


def railing_piece(length):
    """A railing piece along x from 0 to length: two rails and a post at its start."""
    out = []
    for z0, z1 in ((0.98, 1.08), (0.55, 0.62)):
        q = [(0.0, 0.0, z0), (length, 0.0, z0), (length, 0.0, z1), (0.0, 0.0, z1)]
        for want in ((0, 1, 0), (0, -1, 0)):
            tris, _uv = P.quad(q, [(0, 0)] * 4, want)
            out += [(t, "yellow") for t in tris]
    _box(out, -0.03, 0.03, -0.03, 0.03, 0.0, 1.1, "yellow", top=False)
    return out


def place(model, x, y, z, heading_rad):
    """The model's triangles moved to (x, y, z), its +x turned to heading (radians from render +x)."""
    c, s = math.cos(heading_rad), math.sin(heading_rad)
    out = []
    for item in model:
        t = item[0]
        out.append((tuple((x + p[0] * c - p[1] * s, y + p[0] * s + p[1] * c, z + p[2]) for p in t),) + tuple(item[1:]))
    return out


def count(model):
    return len(model)
