"""The F-Town test slab: our own ground at the empty place outside Rockport, written as one chunk file.

    python tools/world/slab.py build ftown/ftown-slab.bun
    python tools/world/slab.py render .superpowers/world        (slab-top.png, slab-spawn.png)
    python tools/world/slab.py textures tools/world/textures    (the drawn textures as PNG)

The slab (render coordinates: x, y horizontal, z up; centred on (2000, 11500), top at z = 100, notes Task 6):
- a 200 x 200 m asphalt square, cut in 10 m cells (uv repeating every 10 m);
- a dashed centre line: the 10 m column x 1995..2005 uses a texture with a white line down its middle (5 m dashes);
- a ramp 20 m long, 8 m wide (x 1996..2004, y 11480..11500) rising 0 -> 3 m towards +y, with a 3 m drop at its end:
  its collision replaces the slab's under it (no floor under the ramp, notes Q4);
- a wall 50 m long, 0.3 m thick, 3 m tall in the north-east quarter (x 2025..2075 at y 11550), red and white;
- the closed edge: walls 3 m tall round the square (design: "the edge of the area is closed");
- the spawn 30 m from the south edge on the centre line, 1 m above the surface, facing the ramp (+y).

The file holds, in this order: the texture pack (the solids name its textures; Rockport's sections carry their packs
first), the solid list, the scenery section (its instances name the solids), the collision pack; each at a multiple
of 128 (padding chunks between; LoadChunks skips id 0). Nothing here reads a game file: every byte comes from our
geometry, our drawn textures and the format constants recorded in docs/ftown-notes.md ("Part 2: writers").
"""
import math
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, chunk_bytes, write_chunks  # noqa: E402
from world import collision_write, scenery_write, solids, texpack  # noqa: E402
from world.collision import to_physics  # noqa: E402

# U1: letter U is unused by Rockport (A..T, V, X, Y, Z are), sub-number 1 < 10, so WhatSectionsShouldWeDraw draws it
# whenever the camera is outside Rockport's drivable sections (notes Q2); free in UserInfoTable (2,800 slots). The
# collision pack takes the same number (< 2,700 slots, free: Rockport's packs carry drivable numbers 101..2039).
SECTION_NUMBER = 2101
PACK_NUMBER = 2101
CENTRE = (2000.0, 11500.0)
TOP = 100.0
SIZE = 200.0
CELL = 10.0
LINE_COLUMN = (1995.0, 2005.0)
RAMP = (1996.0, 11480.0, 2004.0, 11500.0)  # x0, y0, x1, y1
RAMP_HEIGHT = 3.0
RAMP_STEP = 2.0
WALL = (2025.0, 2075.0, 11550.0)  # x0, x1, y
WALL_THICK = 0.3
WALL_HEIGHT = 3.0
TEX = 128  # pixels per texture side (concrete, wall)
# the asphalt and the line: 256 px per 10 m tile = 3.9 cm per pixel, as Rockport's lane textures (128 x 1024 over
# 4 x 40 m: 3.1-3.9 cm), with the full mip chain (6 levels, as Rockport's 256 x 256 road textures); docs/ftown-notes.md
# "Small fixes (2026-11-03)"
GROUND_TEX = 256
TARMAC_LUM = 58  # Rockport's road textures: luminance 52-57, means about (52-56, 54-58, 55-59)
TARMAC_TINT = (-2, 0, 3)
SIDES = {"asphalt": GROUND_TEX, "line": GROUND_TEX, "concrete": TEX, "wall": TEX}
NAMES = {"asphalt": "FTOWN_ASPHALT", "line": "FTOWN_ASPHALT_LINE", "concrete": "FTOWN_CONCRETE",
         "wall": "FTOWN_WALL_STRIPES"}
TEXTURE_PACK_NAME = "FTOWN"
TEXTURE_PACK_FILE = "FTown\\FTownTextures.tpk"


def spawn():
    """(render x, y, z, heading): 30 m from the south edge on the centre line, 1 m up, heading 90 degrees =
    facing +y (degrees counter-clockwise from render +x)."""
    return (CENTRE[0], CENTRE[1] - SIZE / 2 + 30.0, TOP + 1.0, 90.0)


def in_ramp(x, y):
    x0, y0, x1, y1 = RAMP
    return x0 <= x <= x1 and y0 <= y <= y1


# ---------------------------------------------------------------- textures (drawn here)

def _tarmac_ladder():
    """[(colour, luminance)] for each 6-bit green level: the 565 colour nearest to (L - 2, L, L + 3), the tint of
    Rockport's road textures' means. Every asphalt pixel is one of these, so a DXT1 block's endpoints (its darkest and
    brightest pixel) are exact and its two in-between colours lie between them: the block stays grey instead of
    taking the tints that rounding each channel of a near-grey on its own gives (screenshot 87's coloured speckle)."""
    out = []
    for g6 in range(64):
        g = (g6 << 2) | (g6 >> 4)
        r5 = max(0, min(31, round((g + TARMAC_TINT[0]) * 31 / 255)))
        b5 = max(0, min(31, round((g + TARMAC_TINT[2]) * 31 / 255)))
        c = ((r5 << 3) | (r5 >> 2), g, (b5 << 3) | (b5 >> 2))
        out.append((c, 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]))
    return out


def _value_noise(n, period, rng):
    """Tileable value noise on an n x n texture: random values in -1..1 on a grid every `period` pixels, wrapped,
    blended with a smoothstep."""
    g = n // period
    grid = [[rng.uniform(-1, 1) for _ in range(g)] for _ in range(g)]
    out = []
    for y in range(n):
        gy, fy = divmod(y / period, 1)
        gy = int(gy)
        sy = fy * fy * (3 - 2 * fy)
        for x in range(n):
            gx, fx = divmod(x / period, 1)
            gx = int(gx)
            sx = fx * fx * (3 - 2 * fx)
            a = grid[gy % g][gx % g] * (1 - sx) + grid[gy % g][(gx + 1) % g] * sx
            b = grid[(gy + 1) % g][gx % g] * (1 - sx) + grid[(gy + 1) % g][(gx + 1) % g] * sx
            out.append(a * (1 - sy) + b * sy)
    return out


def _tarmac(n, rng):
    """Tarmac grey, row by row, tileable: patches 2.5 m and 1.25 m across (value noise), a per-pixel grain (gaussian,
    sd 4.5 levels) and a few light stone chips and dark pits, every pixel snapped to the tinted grey ladder."""
    ladder = _tarmac_ladder()
    lums = [l for _c, l in ladder]
    big, small = _value_noise(n, n // 4, rng), _value_noise(n, n // 8, rng)
    out = []
    for i in range(n * n):
        v = TARMAC_LUM + 6.0 * big[i] + 4.0 * small[i] + rng.gauss(0, 4.5)
        r = rng.random()
        if r < 0.015:
            v += rng.uniform(14, 26)  # a light stone chip
        elif r < 0.023:
            v -= rng.uniform(8, 12)  # a pit
        k = min(range(len(lums)), key=lambda j: abs(lums[j] - v))
        out.append(ladder[k][0])
    return out


def draw_textures():
    """{kind: list of (r, g, b) rows} drawn deterministically: tarmac (GROUND_TEX px per 10 m tile), the same with a
    dashed white line down the middle, light concrete with a seam, red and white stripes (TEX px)."""
    rng = random.Random(20261103)
    n = TEX
    m = GROUND_TEX
    a = _tarmac(m, rng)
    line = list(a)
    half_w = m // 64  # 8 px of 256 per 10 m: 0.31 m
    for y in range(m // 2):  # the dash: the first half of the tile (5 m of 10)
        for x in range(m // 2 - half_w, m // 2 + half_w):
            line[y * m + x] = (232, 232, 224)
    conc = []
    for y in range(n):
        for x in range(n):
            v = 170 + rng.randint(-8, 8) - (30 if y in (0, 1, n - 1) else 0)
            conc.append((v, v, v - 6))
    stripes = []
    for y in range(n):
        for x in range(n):
            stripes.append((200, 30, 30) if ((x + y) // 16) % 2 else (235, 235, 235))
    return {"asphalt": a, "line": line, "concrete": conc, "wall": stripes}


def save_textures(out_dir):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for kind, px in draw_textures().items():
        img = Image.new("RGB", (SIDES[kind], SIDES[kind]))
        img.putdata(px)
        p = os.path.join(out_dir, NAMES[kind].lower() + ".png")
        img.save(p)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- geometry (render coordinates)

def _cuts(a, b, step, extra):
    xs = {a + k * step for k in range(int(round((b - a) / step)) + 1)}
    return sorted(xs | {e for e in extra if a < e < b})


def _ccw(t):
    a, b, c = t
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return t if cross > 0 else (a, c, b)


def _band(xs, y0, y1, z0, z1):
    """Triangles of a band of cells between the lines y0 and y1 at cut positions xs, in strip order (zigzag: the
    lower line's point, the upper line's point, ...); each (p0, p1, p2) render."""
    out = []
    for i in range(len(xs) - 1):
        a, b = (xs[i], y0, z0), (xs[i], y1, z1)
        c, d = (xs[i + 1], y0, z0), (xs[i + 1], y1, z1)
        out += [(a, b, c), (b, c, d)]
    return out


def slab_cells():
    """[(kind, triangles in strip order)] of the square without the ramp's footprint, by row."""
    cx, cy = CENTRE
    x_lo, x_hi, y_lo, y_hi = cx - SIZE / 2, cx + SIZE / 2, cy - SIZE / 2, cy + SIZE / 2
    xs = _cuts(x_lo, x_hi, CELL, [LINE_COLUMN[0], LINE_COLUMN[1], RAMP[0], RAMP[2]])
    ys = _cuts(y_lo, y_hi, CELL, [RAMP[1], RAMP[3]])
    out = []
    for j in range(len(ys) - 1):
        ya, yb = ys[j], ys[j + 1]
        run, kind = [], None
        for i in range(len(xs) - 1):
            xa, xb = xs[i], xs[i + 1]
            k = "line" if LINE_COLUMN[0] <= xa and xb <= LINE_COLUMN[1] else "asphalt"
            hole = in_ramp((xa + xb) / 2, (ya + yb) / 2)
            if hole or (run and k != kind):
                if len(run) > 1:
                    out.append((kind, _band(run, ya, yb, TOP, TOP)))
                run = []
            if hole:
                continue
            if not run:
                run = [xa]
            run.append(xb)
            kind = k
        if len(run) > 1:
            out.append((kind, _band(run, ya, yb, TOP, TOP)))
    return out


def ramp_top():
    """The ramp's top in strip order: rows of RAMP_STEP along +y, each the ramp's width."""
    x0, y0, x1, y1 = RAMP
    n = int(round((y1 - y0) / RAMP_STEP))
    out = []
    for k in range(n):
        ya, yb = y0 + k * RAMP_STEP, y0 + (k + 1) * RAMP_STEP
        za, zb = TOP + RAMP_HEIGHT * k / n, TOP + RAMP_HEIGHT * (k + 1) / n
        out += [((x0, ya, za), (x1, ya, za), (x0, yb, zb)), ((x1, ya, za), (x0, yb, zb), (x1, yb, zb))]
    return out


def _quad(a, b, c, d):
    """Two triangles of the quad a b c d (counter-clockwise seen from the side it faces) and their uvs."""
    return [(a, b, c), (a, c, d)]


def _wall_quads(p, q, z0, z1, length_per_u):
    """Vertical quads from p to q (render x, y), z0..z1, cut every 10 m, facing the left of p -> q."""
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    n = max(1, int(math.ceil(L / 10.0 - 1e-9)))
    tris, uvs = [], []
    for k in range(n):
        s0, s1 = k / n, (k + 1) / n
        a = (p[0] + (q[0] - p[0]) * s0, p[1] + (q[1] - p[1]) * s0)
        b = (p[0] + (q[0] - p[0]) * s1, p[1] + (q[1] - p[1]) * s1)
        u0, u1 = L * s0 / length_per_u, L * s1 / length_per_u
        A, B, C, D = (a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)
        tris += _quad(A, B, C, D)
        uvs += [((u0, 1), (u1, 1), (u1, 0)), ((u0, 1), (u1, 0), (u0, 0))]
    return tris, uvs


def drawn():
    """{kind: (triangles, uvs)} of everything drawn, counter-clockwise seen from the side it faces."""
    cx, cy = CENTRE
    out = {k: ([], []) for k in NAMES}

    def add(kind, tris, uvs):
        out[kind][0].extend(tris)
        out[kind][1].extend(uvs)

    def ground_uv(kind, p):
        if kind == "line":
            return ((p[0] - LINE_COLUMN[0]) / CELL, (p[1] - (cy - SIZE / 2)) / CELL)
        return ((p[0] - (cx - SIZE / 2)) / CELL, (p[1] - (cy - SIZE / 2)) / CELL)

    for kind, tris in slab_cells():
        tris = [_ccw(t) for t in tris]
        add(kind, tris, [tuple(ground_uv(kind, p) for p in t) for t in tris])
    rt = [_ccw(t) for t in ramp_top()]
    add("line", rt, [tuple(ground_uv("line", p) for p in t) for t in rt])
    # the ramp's sides (facing -x and +x) and its back (the 3 m drop, facing +y)
    x0, y0, x1, y1 = RAMP
    n = int(round((y1 - y0) / RAMP_STEP))
    for k in range(n):
        ya, yb = y0 + k * RAMP_STEP, y0 + (k + 1) * RAMP_STEP
        za, zb = TOP + RAMP_HEIGHT * k / n, TOP + RAMP_HEIGHT * (k + 1) / n
        for x, flip in ((x0, False), (x1, True)):
            A, B, C, D = (x, ya, TOP), (x, yb, TOP), (x, yb, zb), (x, ya, za)
            quad = [(A, B, C), (A, C, D)] if flip else [(A, C, B), (A, D, C)]
            if za == TOP:
                quad = [quad[0]]
            add("concrete", quad, [((0, 1), (1, 1), (1, 0))] * len(quad))
    t, u = _wall_quads((x0, y1), (x1, y1), TOP, TOP + RAMP_HEIGHT, 8.0)
    t = [(a, c, b) for a, b, c in t]  # the back faces +y: reverse the winding of the left-facing quads
    add("concrete", t, u)
    # the edge walls, facing inwards (counter-clockwise round the square: the left of each edge is inside)
    x_lo, x_hi, y_lo, y_hi = cx - SIZE / 2, cx + SIZE / 2, cy - SIZE / 2, cy + SIZE / 2
    for p, q in (((x_lo, y_lo), (x_hi, y_lo)), ((x_hi, y_lo), (x_hi, y_hi)), ((x_hi, y_hi), (x_lo, y_hi)),
                 ((x_lo, y_hi), (x_lo, y_lo))):
        t, u = _wall_quads(p, q, TOP, TOP + WALL_HEIGHT, 10.0)
        add("concrete", t, u)
    # the inner wall: a box, its faces outwards
    wx0, wx1, wy = WALL
    s, nn = wy - WALL_THICK / 2, wy + WALL_THICK / 2
    for p, q in (((wx1, s), (wx0, s)), ((wx0, nn), (wx1, nn)), ((wx0, s), (wx0, nn)), ((wx1, nn), (wx1, s))):
        t, u = _wall_quads(p, q, TOP, TOP + WALL_HEIGHT, 3.0)
        t = [(a, c, b) for a, b, c in t]
        add("wall", t, u)
    zt = TOP + WALL_HEIGHT
    add("wall", [((wx0, s, zt), (wx1, s, zt), (wx1, nn, zt)), ((wx0, s, zt), (wx1, nn, zt), (wx0, nn, zt))],
        [((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))])
    return out


def collision_faces():
    """Physics triangles (strip order) of the slab without the ramp's footprint, and the ramp's top."""
    tris = []
    for _kind, band in slab_cells():
        tris += band
    tris += ramp_top()
    return [tuple(to_physics(p) for p in t) for t in tris]


def barriers():
    """Physics barriers ((x, z), (x, z), bottom, top): the edge, the inner wall's four faces, the ramp's drop."""
    cx, cy = CENTRE
    x_lo, x_hi, y_lo, y_hi = cx - SIZE / 2, cx + SIZE / 2, cy - SIZE / 2, cy + SIZE / 2
    segs = [((x_lo, y_lo), (x_hi, y_lo)), ((x_hi, y_lo), (x_hi, y_hi)), ((x_hi, y_hi), (x_lo, y_hi)),
            ((x_lo, y_hi), (x_lo, y_lo))]
    wx0, wx1, wy = WALL
    s, n = wy - WALL_THICK / 2, wy + WALL_THICK / 2
    segs += [((wx0, s), (wx1, s)), ((wx1, s), (wx1, n)), ((wx1, n), (wx0, n)), ((wx0, n), (wx0, s))]
    x0, y0, x1, y1 = RAMP
    segs_ramp = [((x0, y1), (x1, y1))]
    out = []
    for p, q in segs + segs_ramp:
        P, Q = to_physics((p[0], p[1], 0.0)), to_physics((q[0], q[1], 0.0))
        out.append(((P[0], P[2]), (Q[0], Q[2]), TOP, TOP + WALL_HEIGHT))
    return out


# ---------------------------------------------------------------- the file

def _texture_hashes():
    from chunks import bstringhash
    return {k: bstringhash(v) for k, v in NAMES.items()}


def make_parts():
    """(texture pack, solid list, scenery section, collision pack) models."""
    px = draw_textures()
    texs = [texpack.new_texture(NAMES[k], SIDES[k], SIDES[k], px[k]) for k in NAMES]
    tpack = texpack.new_pack(TEXTURE_PACK_NAME, TEXTURE_PACK_FILE, texs)
    hashes = _texture_hashes()
    sols = []
    for kind, (tris, uvs) in drawn().items():
        if tris:
            sols.append(solids.make_solid("FTOWN_SLAB_%s" % kind.upper(), tris, uvs, hashes[kind],
                                          mesh_name=NAMES[kind]))
    slist = solids.new_list(sols, "FTown_Slab.bin", "U1")
    by_hash = {s.name_hash: s for s in sols}
    ident = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    models = [(s.name[:23], (s.name_hash,) * 3 + (0,), ident) for s in sols]
    sc = scenery_write.make_section(SECTION_NUMBER, models, by_hash)
    pack = collision_write.make_pack(PACK_NUMBER, collision_faces(), barriers())
    return tpack, slist, sc, pack


def assemble(tpack, slist, sc, pack):
    """The top-level chunk list: each part at a multiple of 128, zero padding chunks between."""
    out = []
    pos = 0
    for kind, part in (("tex", tpack), ("solids", slist), ("scenery", sc), ("collision", pack)):
        gap = (-pos) % 128
        if gap:
            if gap < 8:
                gap += 128
            pad = Chunk(0, bytes(gap - 8))
            out.append(pad)
            pos += gap
        if kind == "tex":
            c = texpack.write_pack(part, pos + 8)
        elif kind == "solids":
            c = solids.write_list(part, pos + 8)
        elif kind == "scenery":
            c = scenery_write.write_section(part, pos + 8)
        else:
            c = collision_write.write_pack(part, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return out


def build_chunks():
    return assemble(*make_parts())


def build(out_path):
    data = write_chunks(build_chunks())
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


# ---------------------------------------------------------------- pictures

def _shade(tri):
    a, b, c = tri
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    L = math.sqrt(sum(x * x for x in n)) or 1
    light = (0.4, -0.5, 0.77)
    return 0.55 + 0.45 * abs(sum(n[i] * light[i] for i in range(3)) / L)


def _avg(px):
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))


def render(out_dir):
    """slab-top.png (top-down, collision barriers in blue) and slab-spawn.png (a pinhole view 1.2 m above the spawn,
    looking along +y), both drawn from the triangles in the file's solids."""
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    px = draw_textures()
    colours = {k: _avg(v) for k, v in px.items()}
    colours["line"] = colours["asphalt"]
    parts = drawn()
    cx, cy = CENTRE
    S = 4  # pixels per metre
    W = int(SIZE * S) + 80
    img = Image.new("RGB", (W, W + 30), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def top(p):
        return ((p[0] - (cx - SIZE / 2)) * S + 40, ((cy + SIZE / 2) - p[1]) * S + 40)

    tex_img = {k: v for k, v in px.items()}
    allt = []
    for kind, (tris, uvs) in parts.items():
        for t, u in zip(tris, uvs):
            allt.append((max(p[2] for p in t), kind, t, u))
    for _z, kind, t, u in sorted(allt, key=lambda e: e[0]):
        # colour: the texture at the triangle's uv centre (the line shows), shaded by its normal
        uc = sum(q[0] for q in u) / 3 % 1.0
        vc = sum(q[1] for q in u) / 3 % 1.0
        base = tex_img[kind][int(vc * TEX) % TEX * TEX + int(uc * TEX) % TEX] if kind != "asphalt" else colours[kind]
        if kind == "line":
            base = colours["asphalt"]
        f = _shade(t)
        d.polygon([top(p) for p in t], fill=tuple(int(c * f) for c in base))
    # the centre line's dashes drawn from the texture rule (5 m of every 10 m, 0.31 m wide)
    for k in range(int(SIZE / CELL)):
        y0 = cy - SIZE / 2 + k * CELL
        if in_ramp(cx, y0 + 2.5):
            continue
        d.rectangle([top((cx - 0.16, y0 + 5.0)), top((cx + 0.16, y0))], fill=(232, 232, 224))
    for a, b, lo, hi in barriers():
        from world.collision import to_render
        A, B = to_render((a[0], 0, a[1])), to_render((b[0], 0, b[1]))
        d.line([top(A), top(B)], fill=(40, 90, 230), width=2)
    sx, sy, sz, hd = spawn()
    d.ellipse([top((sx - 1.5, sy + 1.5)), top((sx + 1.5, sy - 1.5))], outline=(0, 160, 0), width=3)
    d.text((10, W + 8), "F-Town test slab, top-down (render x right, y up), 200 x 200 m at (2000, 11500), z 100. Blue:"
           " collision barriers. Green: spawn. Ramp 20 m (x 1996..2004, y 11480..11500), wall x 2025..2075 y 11550.",
           fill=(0, 0, 0))
    p1 = os.path.join(out_dir, "slab-top.png")
    img.save(p1)
    # the view from the spawn
    Wv, Hv = 1280, 720
    img = Image.new("RGB", (Wv, Hv), (150, 185, 220))
    d = ImageDraw.Draw(img)
    eye = (sx, sy, sz + 0.2)
    f = Wv / 2 / math.tan(math.radians(35))

    def view(p):
        dx, dy, dz = p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]
        if dy < 0.49:
            return None
        return (Wv / 2 + f * dx / dy, Hv / 2 - f * dz / dy)

    def clip(t):
        """The triangle cut at 0.5 m in front of the eye (along +y), as a polygon."""
        out = []
        n = len(t)
        for i in range(n):
            a, b = t[i], t[(i + 1) % n]
            da, db = a[1] - eye[1] - 0.5, b[1] - eye[1] - 0.5
            if da >= 0:
                out.append(a)
            if (da >= 0) != (db >= 0):
                s = da / (da - db)
                out.append(tuple(a[k] + (b[k] - a[k]) * s for k in range(3)))
        return out

    faces = []
    for kind, (tris, uvs) in parts.items():
        for t, u in zip(tris, uvs):
            poly = clip(t)
            if len(poly) < 3:
                continue
            pts = [view((p[0], max(p[1], eye[1] + 0.5), p[2])) for p in poly]
            dist = sum(math.dist(p, eye) for p in t) / 3
            uc = sum(q[0] for q in u) / 3 % 1.0
            vc = sum(q[1] for q in u) / 3 % 1.0
            base = colours[kind] if kind in ("asphalt", "line") else \
                tex_img[kind][int(vc * TEX) % TEX * TEX + int(uc * TEX) % TEX]
            faces.append((dist, pts, base, _shade(t)))
    for dist, pts, base, sh in sorted(faces, key=lambda e: -e[0]):
        fog = min(1.0, dist / 400.0)
        col = tuple(int(c * sh * (1 - fog) + s * fog) for c, s in zip(base, (150, 185, 220)))
        d.polygon(pts, fill=col)
    d.text((10, Hv - 20), "From the spawn, 1.2 m above the slab, looking +y (towards the ramp). Pinhole 70 degrees.",
           fill=(0, 0, 0))
    p2 = os.path.join(out_dir, "slab-spawn.png")
    img.save(p2)
    return p1, p2


def _pack_mips():
    """{kind: [(w, h, pixels) per mip]} decoded from the texture pack as built (what the game is handed)."""
    from chunks import bstringhash
    by_hash = {bstringhash(n): k for k, n in NAMES.items()}
    from world import scenery
    tpack, tpos = [(c, p) for c, p in scenery.with_positions(build_chunks(), 0) if c.id == texpack.PACK][0]
    out = {}
    for t in texpack.read_pack(tpack, tpos).textures:
        w, h = struct.unpack_from("<hh", t.info, 0x44)
        mips, o = [], 0
        for size in texpack.mip_sizes(w, h):
            mips.append((w, h, texpack.dxt1_decode(t.data[o:o + size], w, h)))
            o += size
            w, h = w // 2, h // 2
        out[by_hash[t.name_hash]] = mips
    return out


def render_closeup(out_path, width=800, height=450):
    """A close-up of the ground as the GPU would sample it: a pinhole 1.2 m above the slab next to the centre line,
    looking along +y and 12 degrees down; each pixel's ray meets the top (z 100), the mip level is chosen from the
    pixel's footprint on the ground (log2 of texels per pixel) and sampled bilinearly from the built pack's DXT1
    mips. No lighting (the game multiplies by the baked vertex colour and its own light): it shows the texture."""
    from PIL import Image
    mips = _pack_mips()
    cx, cy = CENTRE
    eye = (2001.5, cy - SIZE / 2 + 25.0, TOP + 1.2)
    pitch = math.radians(12)
    f = width / 2 / math.tan(math.radians(30))
    fwd = (0.0, math.cos(pitch), -math.sin(pitch))
    up = (0.0, math.sin(pitch), math.cos(pitch))
    img = Image.new("RGB", (width, height))
    put = img.load()

    def sample(m, u, v):
        w, h, px = m
        x, y = u * w - 0.5, v * h - 0.5
        x0, y0 = math.floor(x), math.floor(y)
        fx, fy = x - x0, y - y0
        acc = [0.0, 0.0, 0.0]
        for dx, dy, wt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy),
                           (1, 1, fx * fy)):
            p = px[((y0 + dy) % h) * w + (x0 + dx) % w]
            for i in range(3):
                acc[i] += p[i] * wt
        return acc

    for j in range(height):
        for i in range(width):
            sx, sy = (i + 0.5 - width / 2) / f, (height / 2 - j - 0.5) / f
            d = (sx, fwd[1] + sy * up[1], fwd[2] + sy * up[2])
            if d[2] >= -1e-4:
                put[i, j] = (150, 185, 220)
                continue
            t = (TOP - eye[2]) / d[2]
            x, y = eye[0] + t * d[0], eye[1] + t * d[1]
            kind = "line" if LINE_COLUMN[0] <= x < LINE_COLUMN[1] else "asphalt"
            u = ((x - (LINE_COLUMN[0] if kind == "line" else cx - SIZE / 2)) / CELL) % 1.0
            v = ((y - (cy - SIZE / 2)) / CELL) % 1.0
            dist = t * math.sqrt(sum(c * c for c in d))
            # footprint: metres of ground per screen pixel, stretched by the grazing angle
            foot = dist / f / max(0.05, -d[2] / math.sqrt(sum(c * c for c in d)))
            chain = mips[kind]
            lod = max(0.0, min(len(chain) - 1.0, math.log2(max(1e-6, foot * chain[0][0] / CELL))))
            col = sample(chain[int(round(lod))], u, v)  # D3D: v = 0 is the first (top) row
            fog = min(1.0, dist / 400.0)
            put[i, j] = tuple(int(c * (1 - fog) + s * fog) for c, s in zip(col, (150, 185, 220)))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return out_path


def main(argv):
    if len(argv) >= 2 and argv[0] == "closeup":
        print(render_closeup(argv[1]))
    elif len(argv) >= 2 and argv[0] == "build":
        n = build(argv[1])
        print("wrote %s (%d bytes)" % (argv[1], n))
    elif len(argv) >= 2 and argv[0] == "render":
        print("\n".join(render(argv[1])))
    elif len(argv) >= 2 and argv[0] == "textures":
        print("\n".join(save_textures(argv[1])))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
