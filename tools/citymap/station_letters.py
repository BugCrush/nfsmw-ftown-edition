"""The metro stations' names as raised block letters (Run J, item 2; docs/ftown-notes.md "Run J: the city side").

The user (screenshot 131): "the metro carrier way goes through the name of the metro station on the wall. make the full
name visible. also, emboss the name of the station like they are block letters pasted on the wall."

- **The layout** (TEXTS): every line of lettering on a station's drawn face, in fractions of the face's texture (u left
  to right as seen from outside, v from the top), its font, colour and whether it is raised. One source for both: the
  painters (tools/citymap/landmark_tex.py) draw the lines that are not raised and, under each raised one, only its
  shadow (one texel down and right); this module builds the raised ones as geometry. Neelam Chowk Ajronda's names now sit in the band under the
  viaduct's deck (the deck crosses its ends 10.5-13.6 m up), the plaque beside the deck.
- **The letters** (letter_polygons, letters): the text's ink from our lettering module (tools/citymap/lettering.py,
  GDI) at LETTER_PX pixels of ink height, its outline traced and simplified (SIMPLIFY pixels), fitted into its box as
  lettering.draw fits it, extruded DEPTH metres out of the wall: a front face (constrained Delaunay of each glyph's
  polygon with its holes) and side walls round every ring. Pre-lit like the city's walls (parts.lit: the sides darker
  or lighter than the front by the sun), on the near-white FTC_PAINT, in the line's colour; one part per station
  (merged), the near levels only (the far level and the shadow and reflection views leave them out); the evening
  lights them in their own colour (evening.CLASSES "letters_*").
- **Hidden lettering** (hidden_share): the share of (lettering point, road viewpoint) pairs whose sight line meets a
  triangle of the viaduct (deck, piers, portals) or of a station (roof, columns, stairs); the test that Run I's layout
  fails (test_station_letters).
"""
import math
import os
import sys
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

DEVA = "Nirmala UI"
DEPTH = 0.08  # m the letters stand out of the wall (block letters on a station's front: 5-10 cm)
SHADOW = 0.45  # how much the painted shadow under a raised letter darkens the wall (one texel down and right)
LETTER_PX = 30  # pixels of ink height the outline is traced at (a modest resolution: few triangles a glyph)
SIMPLIFY = 1.0  # pixels: the traced outline simplified by this (the pixel steps go: 44 triangles a glyph; 0.55: 126)
LETTER_GREY = 68.0  # as the drawn faces' vertex grey (parts.faced_wall: lit(t, 68))
PAINT_WHITE = 232.0  # FTC_PAINT's mean texel (textures: (232, 232, 224))
KIND = "paint"


@dataclass(frozen=True)
class Line:
    text: str
    box: tuple  # (u0, v0, u1, v1) fractions of the face's texture
    rgb: tuple
    font: str = "Arial"
    weight: int = 700
    italic: bool = False
    raised: bool = False
    stretch: bool = False
    glow: str = ""  # the evening class of a raised line (evening.CLASSES)


NEELAM_BLUE = (36, 44, 104)
BATA_WHITE = (240, 240, 236)
OLDFBD_BLUE = (36, 60, 150)


# where each face's lettering goes (Run J, item 2), from a map of what hides each part of the face from the road
# (hidden_share over a grid of the face; docs/ftown-notes.md "Run J"): the viaduct's deck crosses Neelam Chowk
# Ajronda's ends 10.5-13.6 m up (u 0.45-0.80 of the south end, 0.18-0.53 of the north) and hides 7-100% of the face
# above it from the road; under it the south end is clear over u 0.04-0.76, the north end over u 0.32-0.97 (2-3%: the
# piers beyond); Bata Chowk's north end is clear (1%) under 9.3 m right of u 0.44 (the deck and a pier hide the rest)
NEELAM_PLAQUE = {False: (0.03, 0.66, 0.17, 0.80), True: (0.83, 0.66, 0.97, 0.80)}
NEELAM_NAMES = {False: (0.20, 0.76), True: (0.33, 0.80)}


def _neelam(north):
    """Neelam Chowk Ajronda's ends (photos 35, 33). Run I drew the Hindi names across the face's middle, where the
    deck crosses it (v 0.27-0.47 of the 12.5 m face, 12.6-15.1 m up), and the plaque above it: the four lines of the
    name now stand one under the other in the band under the deck (v 0.655-0.925, 6.9-10.2 m up) where nothing hides
    them, the Lakhani plaque beside them."""
    pu0, pv0, pu1, pv1 = NEELAM_PLAQUE[north]
    u0, u1 = NEELAM_NAMES[north]
    raised = dict(raised=True, glow="letters_neelam")
    out = [
        Line("Lakhani", (pu0 + 0.01, pv0 + 0.02, pu1 - 0.01, pv0 + 0.075), (40, 50, 120), "Georgia", 700, True),
        Line("SHOES", (pu0 + 0.02, pv0 + 0.085, pu1 - 0.02, pv1 - 0.02), (40, 50, 120)),
        Line("लखानी अरमान", (u0, 0.655, u1, 0.72), NEELAM_BLUE, DEVA, **raised),
        Line("नीलम चौक अजरौंदा", (u0, 0.725, u1, 0.79), NEELAM_BLUE, DEVA, **raised),
        Line("LAKHANI ARMAAN", (u0, 0.80, u1, 0.855), NEELAM_BLUE, **raised),
        Line("NEELAM CHOWK AJRONDA", (u0, 0.865, u1, 0.92), NEELAM_BLUE, **raised),
    ]
    if north:  # the green direction board at the foot (photo 33)
        out.append(Line("Greater Faridabad", (0.84, 0.87, 0.96, 0.91), (240, 240, 236)))
    return out


BATA_BOARD = (0.72, 0.31, 0.98, 0.46)  # the KARIGARI board (Run I: top left, 11.3-12.0 m up, 10-85% hidden)
# Old Faridabad's sign box, repeated every 24 m along its 138.3 m side: within u 0.74 so the last copy (18.3 m, u 0.76)
# carries its names whole (the review: "Old Farida..." and shadows without letters at the wall's end)
OLDFBD_SIGN = (0.11, 0.24, 0.74, 0.44)


TEXTS = {
    "FTL_STN_NEELAM_S": _neelam(False),
    "FTL_STN_NEELAM_N": _neelam(True),
    "FTL_STN_BATA_N": [
        Line("KARIGARI", (BATA_BOARD[0] + 0.02, BATA_BOARD[1] + 0.015, BATA_BOARD[2] - 0.02, BATA_BOARD[1] + 0.095),
             (240, 236, 226), "Georgia", 700),
        Line("BY CHEF HARPAL SINGH SOKHI", (BATA_BOARD[0] + 0.02, BATA_BOARD[1] + 0.10, BATA_BOARD[2] - 0.02,
                                            BATA_BOARD[3] - 0.015), (220, 216, 206), "Arial", 400),
        Line("इंडियनऑयल", (0.50, 0.645, 0.66, 0.74), (240, 240, 236), DEVA),
        Line("IndianOil", (0.50, 0.75, 0.66, 0.84), (240, 240, 236)),
        Line("बाटा चौक", (0.75, 0.645, 0.97, 0.74), BATA_WHITE, DEVA, raised=True, glow="letters_bata"),
        Line("BATA CHOWK", (0.74, 0.75, 0.98, 0.84), BATA_WHITE, raised=True, glow="letters_bata"),
    ],
    "FTL_STN_BATA_W": [
        Line("WISH YOU A SAFE AND POLLUTION FREE DRIVING EXPERIENCE", (0.11, 0.24, 0.49, 0.38), (36, 70, 150),
             stretch=True),
        Line("WISH YOU A SAFE AND POLLUTION FREE DRIVING EXPERIENCE", (0.61, 0.24, 0.99, 0.38), (36, 70, 150),
             stretch=True),
    ],
    "FTL_STN_OLDFBD_W": [
        Line("ओल्ड फरीदाबाद", (0.13, 0.26, 0.37, 0.42), OLDFBD_BLUE, DEVA, raised=True, glow="letters_oldfbd"),
        Line("Old Faridabad", (0.46, 0.27, 0.72, 0.41), OLDFBD_BLUE, "Arial", 700, True, raised=True,
             glow="letters_oldfbd"),
    ],
}


# ---------------------------------------------------------------- the texture side

# the faces' size on their walls (metres across a copy, metres tall: the registry's z), for the shadows' shapes: a face
# texture's texels are not square (Neelam Chowk Ajronda's 256 x 256 over 28.5 x 12.5 m), and the raised letters keep
# their font's proportions (test_station_letters checks these against the built walls)
FACE_M = {"FTL_STN_NEELAM_S": (28.5, 12.5), "FTL_STN_NEELAM_N": (28.6, 12.5), "FTL_STN_BATA_N": (28.5, 6.5),
          "FTL_STN_OLDFBD_W": (24.0, 6.5), "FTL_STN_BATA_W": (36.0, 6.5)}


def paint(canvas, name):
    """Draws the face's lines on a landmark_tex.Canvas: the flat ones as they are, under a raised one only its shadow
    (the wall darkened by SHADOW where the block letter's shadow falls: the letter's own outline, as letters() places
    it on a face of FACE_M metres, one texel down and right)."""
    from PIL import Image, ImageDraw
    from tools.citymap import lettering
    for ln in TEXTS.get(name, ()):
        x0, y0, x1, y1 = canvas.px(*ln.box)
        if not ln.raised:
            lettering.draw(canvas.a, ln.text, (x0, y0, x1, y1), ln.rgb, ln.font, ln.weight, ln.italic,
                           stretch=ln.stretch)
            continue
        wm, hm = FACE_M[name]
        u0, v0, u1, v1 = ln.box
        polys, iw, ih = letter_polygons(ln)
        kx, ky, ox, oy = fit(ln, (u1 - u0) * wm, (v1 - v0) * hm, iw, ih)
        ss = 4
        im = Image.new("L", (canvas.w * ss, canvas.h * ss), 0)
        dr = ImageDraw.Draw(im)

        def px(x, y):
            return (((u0 * wm + ox + x * kx) / wm * canvas.w + 1.0) * ss,
                    ((v1 * hm - oy - y * ky) / hm * canvas.h + 1.0) * ss)
        for poly in polys:
            dr.polygon([px(*c) for c in poly.exterior.coords], fill=255)
            for ring in poly.interiors:
                dr.polygon([px(*c) for c in ring.coords], fill=0)
        shade = np.asarray(im.reduce(ss), dtype=float)[..., None] / 255.0
        canvas.a *= 1.0 - SHADOW * shade


# ---------------------------------------------------------------- the letters' outlines

_poly_cache = {}


def letter_polygons(ln):
    """(polygons in ink pixels (x right, y up, origin the ink's bottom left), ink width, ink height): the line's ink
    at LETTER_PX pixels of height traced into polygons (pixel runs joined, simplified by SIMPLIFY)."""
    key = (ln.text, ln.font, ln.weight, ln.italic)
    if key in _poly_cache:
        return _poly_cache[key]
    from tools.citymap import lettering
    m = lettering.mask(ln.text, ln.font, LETTER_PX, ln.weight, ln.italic)
    # the mask's ink height depends on the font's em: scale the em so the ink is LETTER_PX tall
    px = max(8, int(round(LETTER_PX * LETTER_PX / max(1, m.shape[0]))))
    m = lettering.mask(ln.text, ln.font, px, ln.weight, ln.italic)
    ink = m >= 0.5
    h, w = ink.shape
    rects = []
    for r in range(h):
        row = ink[r]
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        y0, y1 = h - r - 1, h - r
        rects += [box(a, y0, b, y1) for a, b in zip(starts, ends)]
    g = shapely.union_all(rects).simplify(SIMPLIFY, preserve_topology=True)
    polys = [orient(p, 1.0) for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 1.0]
    out = (polys, float(w), float(h))
    _poly_cache[key] = out
    return out


def fit(ln, bw, bh, ink_w, ink_h):
    """(scale metres a pixel, x offset, y offset) placing ink of ink_w x ink_h pixels into a box bw x bh metres as
    lettering.draw places it: at the box's height, shrunk to its width (or stretched to it), centred."""
    k = bh / ink_h
    kx = k
    if ln.stretch:
        kx = bw / ink_w
    elif ink_w * k > bw:
        k = kx = bw / ink_w
    return kx, k, (bw - ink_w * kx) / 2.0, (bh - ink_h * k) / 2.0


# ---------------------------------------------------------------- the geometry

def placements(face, p, q, za, zb):
    """[(s, w)]: where the face's texture lies along its wall p -> q (as parts.faced_wall puts it): s metres from p
    where a copy starts and its width w (every width_m along the whole wall when the face repeats)."""
    L = math.dist(p, q)
    w = min(face.width_m or L, L)
    if face.repeat:
        out, s = [], 0.0
        while s < L - 1e-6:
            out.append((s, face.width_m))
            s += face.width_m
        return out
    s0 = min(max(0.0, face.at * L - w / 2), L - w)
    return [(s0, w)]


def _lit(t, rgb):
    from tools.citymap import parts as P
    return P.lit(t, LETTER_GREY, tuple(c / PAINT_WHITE for c in rgb))


def letters(name, face, p, q, za, zb, part):
    """Adds the raised lines of face texture `name` on the wall p -> q (outside on the right), the face from za to zb,
    to `part` (a parts.Part on FTC_PAINT). Returns the triangles added."""
    from tools.citymap import evening
    from tools.citymap import parts as P
    L = math.dist(p, q)
    if L < 0.01:
        return 0
    d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    n = (d[1], -d[0])  # outward: the right of p -> q
    H = zb - za
    added = 0
    for s_start, w in placements(face, p, q, za, zb):
        for ln in TEXTS.get(name, ()):
            if not ln.raised:
                continue
            u0, v0, u1, v1 = ln.box
            bw, bh = (u1 - u0) * w, (v1 - v0) * H
            polys, iw, ih = letter_polygons(ln)
            kx, ky, ox, oy = fit(ln, bw, bh, iw, ih)
            s_box, z_box = s_start + u0 * w, zb - v1 * H  # the box's bottom left on the wall
            if s_box + bw > L + 1e-6:  # (a copy cut by the wall's end: the line whole or not at all; the layouts
                continue          # keep every line inside the last copy, test_station_letters)

            def P3(x, y, depth):
                s = s_box + ox + x * kx
                z = z_box + oy + y * ky
                return (p[0] + d[0] * s + n[0] * depth, p[1] + d[1] * s + n[1] * depth, z)
            for poly in polys:
                tris, cols = [], []
                for t in shapely.constrained_delaunay_triangles(poly).geoms:
                    c = list(t.exterior.coords)[:3]
                    tri = tuple(P3(x, y, DEPTH) for x, y in c)
                    nn = P.normal(tri)
                    if nn[0] * n[0] + nn[1] * n[1] < 0:
                        tri = (tri[0], tri[2], tri[1])
                    tris.append(tri)
                for ring in [poly.exterior] + list(poly.interiors):
                    cs = list(ring.coords)
                    for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                        el = math.hypot(bx - ax, by - ay)
                        if el < 1e-6:
                            continue
                        # out of the glyph: the right of a -> b (exterior counter-clockwise, holes clockwise)
                        ex, ey = (by - ay) / el, -(bx - ax) / el
                        want = (d[0] * ex, d[1] * ex, ey)
                        quad = [P3(ax, ay, 0.0), P3(bx, by, 0.0), P3(bx, by, DEPTH), P3(ax, ay, DEPTH)]
                        t2, _u = P.quad(quad, [(0.5, 0.5)] * 4, want)
                        tris += t2
                uvs = [((0.5, 0.5), (0.5, 0.5), (0.5, 0.5))] * len(tris)
                cols = [evening.glow(_lit(t, ln.rgb), ln.glow) if ln.glow else _lit(t, ln.rgb) for t in tris]
                part.add(tris, uvs, cols)
                added += len(tris)
    return added


# ---------------------------------------------------------------- hidden lettering

def lettering_points(name, face, p, q, za, zb, per_line=40, raised_only=False):
    """3D points (render x, y, z) on the face's lettering: per_line points spread over each line's ink (every line,
    raised or not; raised ones at their front), in every copy of a repeated face."""
    L = math.dist(p, q)
    d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    n = (d[1], -d[0])
    H = zb - za
    out = []
    rng = np.random.default_rng(len(name))
    for s_start, w in placements(face, p, q, za, zb):
        for ln in TEXTS.get(name, ()):
            if raised_only and not ln.raised:
                continue
            u0, v0, u1, v1 = ln.box
            bw, bh = (u1 - u0) * w, (v1 - v0) * H
            polys, iw, ih = letter_polygons(ln)
            kx, ky, ox, oy = fit(ln, bw, bh, iw, ih)
            g = shapely.union_all(polys)
            pts = []
            while len(pts) < per_line:
                x, y = rng.uniform(0, iw), rng.uniform(0, ih)
                if g.contains(shapely.Point(x, y)):
                    pts.append((x, y))
            for x, y in pts:
                s = s_start + u0 * w + ox + x * kx
                if s > L:
                    continue
                z = zb - v1 * H + oy + y * ky
                dep = DEPTH if ln.raised else 0.0
                out.append((p[0] + d[0] * s + n[0] * (dep + 0.01), p[1] + d[1] * s + n[1] * (dep + 0.01), z))
    return np.array(out, dtype=float).reshape(-1, 3)


def viewpoints(p, q, ground, eye=1.3, near=12.0, far=110.0, step=5.0, most_off=70.0):
    """Points on the ground carriageways (eye metres up) in front of the wall p -> q, near..far from its middle and at
    most most_off degrees off its outward normal: where a driver sees the face from."""
    L = math.dist(p, q)
    d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    n = (d[1], -d[0])
    c = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    out = []
    for x in np.arange(c[0] - far, c[0] + far, step):
        for y in np.arange(c[1] - far, c[1] + far, step):
            vx, vy = x - c[0], y - c[1]
            r = math.hypot(vx, vy)
            if not near <= r <= far:
                continue
            if (vx * n[0] + vy * n[1]) / r < math.cos(math.radians(most_off)):
                continue
            if ground.contains(shapely.Point(x, y)):
                out.append((x, y, eye))
    return np.array(out, dtype=float).reshape(-1, 3)


def hidden_share(points, eyes, tris, chunk=4096):
    """(hidden pairs, pairs): sight lines eye -> point that cross any triangle (Moller-Trumbore, the segment's open
    interior: t in (1e-4, 1 - 1e-3))."""
    if not len(points) or not len(eyes) or not len(tris):
        return 0, len(points) * len(eyes)
    T = np.asarray(tris, dtype=float)
    v0, e1, e2 = T[:, 0], T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    O = np.repeat(eyes, len(points), axis=0)
    D = np.tile(points, (len(eyes), 1)) - O
    hidden = np.zeros(len(O), bool)
    lo = np.minimum(O, O + D)
    hi = np.maximum(O, O + D)
    tlo, thi = T.min(1), T.max(1)
    for a in range(0, len(O), chunk):
        o, dd = O[a:a + chunk], D[a:a + chunk]
        # the triangles whose boxes meet the chunk's segments' box
        bl, bh = lo[a:a + chunk].min(0), hi[a:a + chunk].max(0)
        keep = np.all((thi >= bl) & (tlo <= bh), axis=1)
        if not keep.any():
            continue
        V0, E1, E2 = v0[keep], e1[keep], e2[keep]
        pv = np.cross(dd[:, None, :], E2[None])
        det = np.einsum("tk,stk->st", E1, pv)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = o[:, None, :] - V0[None]
        u = np.einsum("stk,stk->st", tv, pv) * inv
        qv = np.cross(tv, E1[None])
        v = np.einsum("sk,stk->st", dd, qv) * inv
        t = np.einsum("tk,stk->st", E2, qv) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-4) & (t < 1 - 1e-3)
        hidden[a:a + chunk] = hit.any(1)
    return int(hidden.sum()), len(O)
