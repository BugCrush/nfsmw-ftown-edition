"""Our own parked vehicles for F-Town's street life (no game data; docs/ftown-notes.md "Street life (2026-11-04)"):
auto-rickshaw, e-rickshaw, hatchback, SUV, scooter and motorbike, the vehicles of the user's street photos.

Local metres: x forward, y to the left, z up, the wheels on z = 0, the middle of the length at x = 0. Every triangle
carries a cell of our own drawn atlas **FTC_VEHICLES** (textures.draw()["vehicles"]: one solid colour a cell, the
palette below), wound to face outward (the game draws only the side a triangle faces: notes "Run H fixes"). Shapes are
side profiles extruded across the width (prisms), so a car is a few dozen triangles; wheels are hexagonal prisms.

**Sizes** (REAL, metres; length, width, height): the Bajaj RE auto-rickshaw (2.635 x 1.30 x 1.71), a common
e-rickshaw (2.75 x 1.0 x 1.75), the Maruti Swift (3.845 x 1.735 x 1.53), the Hyundai Creta (4.30 x 1.79 x 1.635), the
Honda Activa (1.76 x 0.71 x 1.16), the Hero Splendor (2.00 x 0.72 x 1.05): the makers' published dimensions, rounded.

**Colours** (PALETTE): chosen by eye from the user's photos with sampled medians as a guide (photo 18: the CNG
auto's green body (53, 96, 60) and its yellow canopy, the scooter's grey (58, 58, 55); photo 12: the e-rickshaw's blue
(32, 70, 119); photos 11 and 22: the parked cars' white, silver, grey, black and dark blue; red is seen in photos 01,
13), brought to the brightness of Rockport's painted props (no colour brighter than about 200).
"""
import math
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import parts as P  # noqa: E402

REAL = {"auto": (2.635, 1.30, 1.71), "erickshaw": (2.75, 1.00, 1.75), "hatchback": (3.845, 1.735, 1.53),
        "suv": (4.30, 1.79, 1.635), "scooter": (1.76, 0.71, 1.16), "motorbike": (2.00, 0.72, 1.05)}
KINDS = list(REAL)
VARIANTS = 6
PALETTE = {
    "white": (178, 180, 176), "silver": (140, 143, 143), "grey": (92, 94, 95), "black": (34, 36, 39),
    "navy": (38, 50, 82), "red": (150, 36, 32), "auto_green": (55, 105, 60), "auto_yellow": (205, 172, 60),
    "erick_blue": (35, 75, 125), "erick_green": (50, 110, 70), "scooter_grey": (60, 60, 58), "scooter_blue": (40, 62, 120),
    "glass": (30, 38, 46), "tyre": (20, 20, 20), "seat": (28, 26, 24), "light": (215, 212, 196),
    "taillight": (150, 30, 25), "metal": (110, 112, 114), "darkmetal": (45, 46, 48),
}
CELLS = list(PALETTE)
ATLAS_SIDE = 128
CELL_PX = 16
BODY = {"hatchback": ["white", "silver", "grey", "black", "navy", "red"],
        "suv": ["white", "black", "silver", "navy", "grey", "white"],
        "auto": ["auto_green", "auto_green", "black", "auto_green", "auto_green", "black"],
        "erickshaw": ["erick_blue", "erick_green", "erick_blue", "white", "erick_blue", "erick_green"],
        "scooter": ["scooter_grey", "black", "white", "scooter_blue", "red", "silver"],
        "motorbike": ["black", "red", "black", "navy", "black", "grey"]}


def uv(cell):
    """The uv of a cell's centre in FTC_VEHICLES (cells of CELL_PX pixels, row by row)."""
    k = CELLS.index(cell)
    per = ATLAS_SIDE // CELL_PX
    return (((k % per) * CELL_PX + CELL_PX / 2) / ATLAS_SIDE, ((k // per) * CELL_PX + CELL_PX / 2) / ATLAS_SIDE)


def atlas():
    """(side, pixels [(r, g, b)] row by row) of FTC_VEHICLES."""
    per = ATLAS_SIDE // CELL_PX
    px = []
    for y in range(ATLAS_SIDE):
        for x in range(ATLAS_SIDE):
            k = (y // CELL_PX) * per + x // CELL_PX
            px.append(PALETTE[CELLS[k]] if k < len(CELLS) else (128, 128, 128))
    return ATLAS_SIDE, px


def size(kind):
    return REAL[kind]


def body_colour(kind, variant):
    return BODY[kind][variant % VARIANTS]


def _prism(out, profile, y0, y1, cell_of):
    """A convex side profile [(x, z)] extruded from y0 to y1: its two side faces (cell_of("side")) and the faces round
    its edge (cell_of((nx, nz))), each wound to face out; edges facing straight down are left out."""
    n = len(profile)
    cx = sum(p[0] for p in profile) / n
    cz = sum(p[1] for p in profile) / n
    for i in range(n):
        a, b = profile[i], profile[(i + 1) % n]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        if L < 1e-6:
            continue
        nx, nz = dz / L, -dx / L
        mx, mz = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cz
        if nx * mx + nz * mz < 0:
            nx, nz = -nx, -nz
        if nz < -0.99:
            continue
        q = [(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1])]
        tris, _uv = P.quad(q, [(0, 0)] * 4, (nx, 0.0, nz))
        out += [(t, cell_of((nx, nz))) for t in tris]
    for y, want in ((y0, (0.0, -1.0, 0.0)), (y1, (0.0, 1.0, 0.0))):
        for i in range(1, n - 1):
            t = ((profile[0][0], y, profile[0][1]), (profile[i][0], y, profile[i][1]),
                 (profile[i + 1][0], y, profile[i + 1][1]))
            nrm = P.normal(t)
            if nrm[1] * want[1] < 0:
                t = (t[0], t[2], t[1])
            out.append((t, cell_of("side")))


def _box(out, x0, x1, y0, y1, z0, z1, cell):
    _prism(out, [(x0, z0), (x1, z0), (x1, z1), (x0, z1)], y0, y1, lambda _k: cell)


def _wheel(out, x, y_mid, r, w, both_caps=False):
    """A hexagonal wheel touching z = 0: its tread's faces and its outer side (the side away from the vehicle's
    middle; both for a wheel on the middle line); the tread's top faces only where a single-track wheel shows them."""
    prof = [(x + r * math.cos(math.radians(270 + 60 * k)), r + r * math.sin(math.radians(270 + 60 * k)))
            for k in range(6)]
    y0, y1 = y_mid - w / 2, y_mid + w / 2
    for i in range(6):
        a, b = prof[i], prof[(i + 1) % 6]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        nx, nz = dz / L, -dx / L
        if nx * ((a[0] + b[0]) / 2 - x) + nz * ((a[1] + b[1]) / 2 - r) < 0:
            nx, nz = -nx, -nz
        if nz > 0.3 and not both_caps:
            continue  # inside the wheel arch
        tris, _uv = P.quad([(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1])],
                           [(0, 0)] * 4, (nx, 0.0, nz))
        out += [(t, "tyre") for t in tris]
    caps = [(y0, -1.0), (y1, 1.0)] if both_caps else [(y1, 1.0) if y_mid > 0 else (y0, -1.0)]
    for y, sgn in caps:
        for i in range(1, 5):
            t = ((prof[0][0], y, prof[0][1]), (prof[i][0], y, prof[i][1]), (prof[i + 1][0], y, prof[i + 1][1]))
            if P.normal(t)[1] * sgn < 0:
                t = (t[0], t[2], t[1])
            out.append((t, "tyre"))


def _plate(out, x, y0, y1, z0, z1, cell, facing):
    """A vertical quad at x across y0..y1, z0..z1, facing +x (facing 1) or -x (-1): lights."""
    tris, _uv = P.quad([(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)], [(0, 0)] * 4, (facing, 0.0, 0.0))
    out += [(t, cell) for t in tris]


def _cabin_cells(side_cell, roof_cell):
    def f(k):
        if k == "side":
            return side_cell
        nx, nz = k
        return roof_cell if nz > 0.9 else "glass"
    return f


def _car(L, W, H, body, clear, wheel_r, nose, tail, belt):
    """A car: a lower body (bonnet, boot) and a glass cabin with a body-coloured roof; four wheels; lights."""
    out = []
    hl = L / 2
    lower = [(-hl, clear), (hl, clear), (hl, belt - 0.12), (hl - nose, belt), (-hl + tail, belt + 0.02),
             (-hl, belt - 0.05)]
    _prism(out, lower, -W / 2, W / 2, lambda _k: body)
    cw = W / 2 - 0.07
    cabin = [(-hl + tail * 0.4, belt), (hl - nose, belt), (hl - nose - 0.75, H), (-hl + tail * 0.4 + 0.25, H)]
    _prism(out, cabin, -cw, cw, _cabin_cells("glass", body))
    for sx in (1, -1):
        for sy in (1, -1):
            _wheel(out, sx * (hl - 0.68), sy * (W / 2 - 0.13), wheel_r, 0.2)
    for sy in (1, -1):
        _plate(out, hl, sy * (W / 2 - 0.12) - 0.16, sy * (W / 2 - 0.12) + 0.16, belt - 0.3, belt - 0.18, "light", 1)
        _plate(out, -hl, sy * (W / 2 - 0.1) - 0.14, sy * (W / 2 - 0.1) + 0.14, belt - 0.15, belt - 0.03,
               "taillight", -1)
    return out


def hatchback(body):
    L, W, H = REAL["hatchback"]
    return _car(L, W, H, body, 0.30, 0.29, 0.85, 0.25, 0.90)


def suv(body):
    L, W, H = REAL["suv"]
    return _car(L, W, H, body, 0.38, 0.33, 0.95, 0.15, 1.02)


def auto(body):
    """The three-wheeler: a body-coloured tub and front cowl, a black frame, a yellow canopy, a windscreen."""
    L, W, H = REAL["auto"]
    hl = L / 2
    out = []
    _wheel(out, hl - 0.25, 0.0, 0.2, 0.12, True)
    for sy in (1, -1):
        _wheel(out, -hl + 0.45, sy * (W / 2 - 0.08), 0.2, 0.14)
    _prism(out, [(-hl, 0.28), (0.25, 0.28), (0.25, 0.85), (-hl, 0.85)], -W / 2 + 0.16, W / 2 - 0.16,
           lambda _k: body)
    _prism(out, [(0.25, 0.3), (hl - 0.1, 0.3), (hl, 0.95), (0.25, 1.0)], -0.45, 0.45, lambda _k: body)
    _box(out, -hl + 0.15, -0.3, -W / 2 + 0.2, W / 2 - 0.2, 0.85, 1.05, "seat")
    _box(out, hl - 0.32, hl - 0.28, -0.55, 0.55, 1.0, 1.52, "glass")
    for x in (-hl + 0.05, hl - 0.36):
        for sy in (1, -1):
            _box(out, x, x + 0.05, sy * (W / 2 - 0.14) - 0.025, sy * (W / 2 - 0.14) + 0.025, 0.85, 1.55, "black")
    canopy = [(-hl, 1.52), (hl - 0.22, 1.52), (hl - 0.38, H), (-hl + 0.06, H)]
    _prism(out, canopy, -W / 2, W / 2, lambda _k: "auto_yellow")
    _plate(out, hl, -0.1, 0.1, 0.75, 0.85, "light", 1)
    return out


def erickshaw(body):
    """The e-rickshaw: an open frame on a low floor, two bench seats, a front cowl, a flat roof."""
    L, W, H = REAL["erickshaw"]
    hl = L / 2
    out = []
    _wheel(out, hl - 0.25, 0.0, 0.2, 0.1, True)
    for sy in (1, -1):
        _wheel(out, -hl + 0.5, sy * (W / 2 - 0.06), 0.2, 0.12)
    _box(out, -hl, hl - 0.5, -W / 2 + 0.13, W / 2 - 0.13, 0.3, 0.55, body)
    _prism(out, [(hl - 0.5, 0.3), (hl - 0.05, 0.3), (hl, 1.05), (hl - 0.5, 1.1)], -0.32, 0.32, lambda _k: body)
    for x0 in (-hl + 0.1, -0.35):
        _box(out, x0, x0 + 0.5, -W / 2 + 0.15, W / 2 - 0.15, 0.55, 0.85, "seat")
    _box(out, hl - 0.45, hl - 0.42, -0.4, 0.4, 1.1, 1.55, "glass")
    for x in (-hl + 0.05, hl - 0.48):
        for sy in (1, -1):
            _box(out, x, x + 0.04, sy * (W / 2 - 0.08) - 0.02, sy * (W / 2 - 0.08) + 0.02, 0.55, H - 0.08, "metal")
    _box(out, -hl + 0.02, hl - 0.3, -W / 2, W / 2, H - 0.08, H, body)
    _plate(out, hl, -0.08, 0.08, 0.8, 0.9, "light", 1)
    return out


def scooter(body):
    L, W, H = REAL["scooter"]
    out = []
    for x in (-0.63, 0.63):
        _wheel(out, x, 0.0, 0.25, 0.1, True)
    _prism(out, [(-0.88, 0.32), (-0.05, 0.3), (-0.05, 0.62), (-0.7, 0.8), (-0.88, 0.7)], -0.18, 0.18,
           lambda _k: body)
    _box(out, -0.05, 0.42, -0.15, 0.15, 0.25, 0.36, "darkmetal")
    _prism(out, [(0.42, 0.25), (0.62, 0.3), (0.58, 1.0), (0.42, 0.95)], -0.2, 0.2, lambda _k: body)
    _box(out, -0.72, -0.08, -0.15, 0.15, 0.8, 0.88, "seat")
    _box(out, 0.48, 0.58, -W / 2, W / 2, 1.06, H, "black")
    _plate(out, 0.62, -0.06, 0.06, 0.85, 0.95, "light", 1)
    return out


def motorbike(body):
    L, W, H = REAL["motorbike"]
    out = []
    for x in (-0.7, 0.7):
        _wheel(out, x, 0.0, 0.3, 0.1, True)
    _box(out, -0.3, 0.3, -0.14, 0.14, 0.28, 0.6, "darkmetal")
    _prism(out, [(-0.05, 0.62), (0.45, 0.66), (0.4, 0.88), (0.0, 0.9)], -0.15, 0.15, lambda _k: body)
    _box(out, -0.65, -0.05, -0.13, 0.13, 0.72, 0.82, "seat")
    _box(out, -0.95, -0.6, -0.1, 0.1, 0.6, 0.72, body)
    _box(out, 0.52, 0.58, -0.04, 0.04, 0.3, 0.95, "metal")
    _box(out, 0.5, 0.6, -W / 2, W / 2, 0.95, H, "black")
    _plate(out, 0.66, -0.07, 0.07, 0.82, 0.94, "light", 1)
    return out


BUILDERS = {"auto": auto, "erickshaw": erickshaw, "hatchback": hatchback, "suv": suv, "scooter": scooter,
            "motorbike": motorbike}
_models = {}


def model(kind, variant):
    """[(triangle, cell)] of a vehicle in local metres (module doc)."""
    key = (kind, variant % VARIANTS)
    if key not in _models:
        _models[key] = BUILDERS[kind](body_colour(kind, variant))
    return _models[key]


def place(kind, variant, x, y, z, heading_rad):
    """The vehicle's triangles moved to (x, y, z), its +x along heading (radians from render +x)."""
    c, s = math.cos(heading_rad), math.sin(heading_rad)
    return [(tuple((x + p[0] * c - p[1] * s, y + p[0] * s + p[1] * c, z + p[2]) for p in t), cell)
            for t, cell in model(kind, variant)]
