"""F-Town's minimap: a SIZE x SIZE picture (2,048 since Run I's fixes; 1,024 before) of the streets drawn from the road model, cut into the 64 chops the game's
HUD minimap draws, written as one texture pack (ftown/ftown-minimap.bun, loaded by FTownLoader beside the city).

    .tools/cityenv/Scripts/python tools/citymap/minimap.py            build ftown/ftown-minimap.bun, its json and a preview

How the game's minimap works (docs/ftown-race-notes.md R1): the world map is 8 x 8 textures of 128 x 128 named
"<header>_CHOP<n>" (n = row * 8 + column, row 0 at the top); the car's render position goes to map units by
Minimap::ConvertPos (0x567510): x = (x - UL.x) / W, y = (UL.y - y) / W + 1, with UL and W the current track's TrackInfo
calibration. FTownLoader writes F-Town's calibration (below, and in FTownLoader.ini [Minimap]) and the header FTOWN_MAP
while the car is on F-Town. The calibration keeps the city's closed edge box inside map [1/16, 15/16) on both axes: the
game has no upper bound on the chop number, so the 2 x 2 chops around the car must stay in rows and columns 0..7.

The picture follows Rockport's map in colours (grey roads on dark ground; read from TRACKS/L2RA/MINI_MAP.BIN in Task 1):
roads wider than they are (a minimap is read at a glance), flyovers lighter, the first route (DND-KMP exit to Mathura
Road) highlighted. Textures are DXT3 with one mip level and opaque alpha, as the game's chops are (since Run I's
fixes 256 x 256 each: the HUD samples a chop by its uvs).

Derived from OpenStreetMap data (c) OpenStreetMap contributors (ODbL): the built file is git-ignored.
"""
import hashlib
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from chunks import chunk_bytes  # noqa: E402
from tools.citymap import geo  # noqa: E402
from world import texpack  # noqa: E402

# the calibration (render metres): the map's south-west corner and its width; centred on the city's centre (geo.ORIGIN:
# (2000, 11500) before the connection's move, (2000, 9068) since)
WIDTH = 5120.0
UPPER_LEFT = (geo.ORIGIN[0] - WIDTH / 2, geo.ORIGIN[1] - WIDTH / 2)  # TrackMapCalibrationUpperLeft: x of the west edge, y of the south
HEADER = "FTOWN_MAP"
# Run I fixes, item 3 (docs/ftown-notes.md "Run I fixes: the city side"): "very rough irregular looking roads". The
# HUD draws a chop over 128 of its 640 x 480 units (SetupMinimap's SectionSize; uvs 0..1 of the chop's texture), so a
# 128-texel chop was magnified about 2.6 x at 1260 lines. Now 2,048 px (2.5 m a pixel; chops of 256), drawn at SS x
# that and box-filtered down (anti-aliased), round joins and caps at every point, DXT3 endpoints on each block's
# principal colour axis.
SIZE = 2048
CHOP = SIZE // 8
SS = 4

# colours (Rockport's minimap: road (140, 138, 140), ground (51, 52, 51), (41, 41, 41) further out, dark road edges)
OUTSIDE = (30, 31, 30)
GROUND = (51, 52, 51)
EDGE = (12, 12, 12)
ROAD = (140, 138, 140)
FLYOVER = (190, 188, 190)
ROUTE = (236, 170, 40)  # (the fixed first-route line's colour until Run J; not drawn since: item 7)
# Where FTownLoader may show the game's safe-house icon (render metres): set in FTownLoader.ini
# [Minimap] (SafeHouseIcon, SafeHouse); none in the public source.
SAFE_HOUSE = (0.0, 0.0)
SAFE_FILL = (90, 210, 90)  # a green house, as Rockport's safehouse icon
SAFE_EDGE = (10, 30, 10)
SAFE_TEXELS = 26  # the mark's width in texels of the 2,048 picture (65 m)
SAFE_OUTLINE = 1.5

# drawn widths in metres (5 m a pixel): the big roads stand out, lanes and service roads stay thin
WIDE = {"motorway": 32, "trunk": 32, "primary": 28, "secondary": 26, "tertiary": 22, "motorway_link": 18,
        "trunk_link": 18, "primary_link": 18, "secondary_link": 18, "tertiary_link": 16}
NARROW = 16
EDGE_M = 5

OUT_BUN = os.path.join(REPO, "ftown", "ftown-minimap.bun")
OUT_JSON = os.path.join(REPO, "ftown", "ftown-minimap.json")
AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
PREVIEW = os.path.join(AREA, "minimap-preview.png")


def to_map(x, y):
    """Render metres to map units, as Minimap::ConvertPos."""
    return ((x - UPPER_LEFT[0]) / WIDTH, (UPPER_LEFT[1] - y) / WIDTH + 1.0)


def to_pixel(x, y):
    mx, my = to_map(x, y)
    return mx * SIZE, my * SIZE



def safe_house(d, cx, cy, s):
    """Run J, item 6: the safe-house mark, our own drawing after Rockport's safehouse marker (a house on the map): a
    house (walls, a pitched roof, a door) in SAFE_FILL with a SAFE_EDGE outline, centred on (cx, cy) of the big picture,
    `s` its pixels a texel."""
    half = SAFE_TEXELS / 2.0 * s
    o = SAFE_OUTLINE * s
    wall_top = cy - half * 0.15
    body = [(cx - half * 0.72, wall_top), (cx + half * 0.72, wall_top), (cx + half * 0.72, cy + half),
            (cx - half * 0.72, cy + half)]
    roof = [(cx - half, wall_top + half * 0.08), (cx, cy - half), (cx + half, wall_top + half * 0.08)]

    def grown(poly, by):
        mx = sum(p[0] for p in poly) / len(poly)
        my = sum(p[1] for p in poly) / len(poly)
        out = []
        for x, y in poly:
            L = math.hypot(x - mx, y - my) or 1.0
            out.append((x + (x - mx) / L * by * 1.6, y + (y - my) / L * by * 1.6))
        return out
    d.polygon(grown(body, o), fill=SAFE_EDGE)
    d.polygon(grown(roof, o), fill=SAFE_EDGE)
    d.polygon(body, fill=SAFE_FILL)
    d.polygon(roof, fill=SAFE_FILL)
    dw, dh = half * 0.22, half * 0.5  # the door
    d.rectangle([cx - dw, cy + half - dh, cx + dw, cy + half], fill=SAFE_EDGE)


def render(model, edge_box=None):
    """The (SIZE, SIZE, 3) uint8 picture: dark outside the city's edge box, ground inside, every road (edge, then
    fill), flyovers over the roads (Run J: no fixed route line, item 7; Run K: no painted safe house, item 1: the
    plugin shows the game's icon at SAFE_HOUSE)."""
    if edge_box is None:
        with open(os.path.join(REPO, "ftown", "ftown-city.json")) as f:
            edge_box = json.load(f)["edge_box"]
    big = SIZE * SS
    im = Image.new("RGB", (big, big), OUTSIDE)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = edge_box
    (px0, py1), (px1, py0) = to_pixel(x0, y0), to_pixel(x1, y1)
    d.rectangle([px0 * SS, py0 * SS, px1 * SS, py1 * SS], fill=GROUND)

    def line(points, metres, colour):
        pts = [(x * SS, y * SS) for x, y in (to_pixel(x, y) for x, y in points)]
        w = max(1, int(round(metres * big / WIDTH)))
        d.line(pts, fill=colour, width=w)
        r = w / 2.0
        for x, y in pts:  # round joins and caps
            d.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    ground = [r for r in model.roads if r.level < 1]
    raised = [r for r in model.roads if r.level >= 1]
    for layer in (ground, raised):
        for r in layer:
            line(r.points, WIDE.get(r.kind, NARROW) + 2 * EDGE_M, EDGE)
        for r in layer:
            line(r.points, WIDE.get(r.kind, NARROW), FLYOVER if layer is raised else ROAD)
    # (Run K, item 1: no painted safe-house mark any more: it scrolled off the round map; FTownLoader shows the game's own
    # safe-house icon at SAFE_HOUSE, kept on the map's rim when out of view: [Minimap] SafeHouse)
    # the city ends at its closed edge (no road beyond it in the game): outside the box stays dark
    out = np.asarray(im.reduce(SS), dtype=np.uint8).copy()
    keep = np.zeros(out.shape[:2], bool)
    keep[int(round(py0)):int(round(py1)) + 1, int(round(px0)):int(round(px1)) + 1] = True
    out[~keep] = OUTSIDE
    return out


# ---------------------------------------------------------------- DXT3 (opaque: explicit alpha all 15)

def _565(c):
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _from565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)


def _fit(blk, hi, lo):
    """(c0, c1, indices, squared error) of a block for endpoint colours hi and lo (c0 >= c1: four colours)."""
    c0, c1 = _565(hi), _565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    a, b = _from565(c0), _from565(c1)
    pal = np.stack([a, b, (2 * a + b) // 3, (a + 2 * b) // 3], 1)
    d = ((blk[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(2)
    return c0, c1, idx, d.min(2).sum(1)


def dxt3_encode(img):
    """DXT3 of an (h, w, 3) uint8 image, alpha opaque. The colour block always decodes as four colours in DXT3, so
    the endpoints are ordered c0 >= c1 and indices chosen against the four-colour palette. Endpoints per block: the
    best of three candidates (Run I fixes, item 3: the anti-aliased map blends up to three colours in a block): the
    darkest and brightest pixel by 3r + 6g + b (as tools/world/texpack.py's DXT1), the ends of the block's principal
    colour axis, and its two most different pixels."""
    h, w, _ = img.shape
    blk = img.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
    n = np.arange(len(blk))
    lum = blk[..., 0] * 3 + blk[..., 1] * 6 + blk[..., 2]
    cands = [(blk[n, lum.argmax(1)], blk[n, lum.argmin(1)])]
    f = blk.astype(float)
    mean = f.mean(1)
    dev = f - mean[:, None, :]
    cov = np.einsum("bki,bkj->bij", dev, dev)
    v = np.ones((len(blk), 3)) / np.sqrt(3.0)
    for _ in range(8):  # the principal axis by power iteration
        v = np.einsum("bij,bj->bi", cov, v)
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    t = np.einsum("bki,bi->bk", dev, v)
    cands.append((np.clip(np.round(mean + v * t.max(1, keepdims=True)), 0, 255).astype(np.int32),
                  np.clip(np.round(mean + v * t.min(1, keepdims=True)), 0, 255).astype(np.int32)))
    pair = ((blk[:, :, None, :] - blk[:, None, :, :]) ** 2).sum(-1).reshape(len(blk), -1).argmax(1)
    cands.append((blk[n, pair // 16], blk[n, pair % 16]))
    best = None
    for hi, lo in cands:
        fit = _fit(blk, hi, lo)
        if best is None:
            best = list(fit)
            continue
        better = fit[3] < best[3]
        for k in range(3):
            best[k] = np.where(better[:, None] if best[k].ndim == 2 else better, fit[k], best[k])
        best[3] = np.minimum(best[3], fit[3])
    c0, c1, idx, _err = best
    bits = (idx.astype(np.uint64) << (2 * np.arange(16, dtype=np.uint64))[None, :]).sum(1).astype(np.uint32)
    out = np.zeros((len(blk), 4), dtype=np.uint32)
    out[:, 0] = 0xFFFFFFFF
    out[:, 1] = 0xFFFFFFFF
    out[:, 2] = (c0.astype(np.uint32) & 0xFFFF) | ((c1.astype(np.uint32) & 0xFFFF) << 16)
    out[:, 3] = bits
    return out.astype("<u4").tobytes()


def dxt3_decode(data, w, h):
    """(h, w, 4) uint8 of DXT3 bytes (four-colour palette, explicit 4-bit alpha)."""
    q = np.frombuffer(data, dtype="<u4").reshape(-1, 4)
    alpha = (q[:, 0].astype(np.uint64) | (q[:, 1].astype(np.uint64) << 32))
    c0, c1 = (q[:, 2] & 0xFFFF).astype(np.int32), (q[:, 2] >> 16).astype(np.int32)
    a, b = _from565(c0), _from565(c1)
    pal = np.stack([a, b, (2 * a + b) // 3, (a + 2 * b) // 3], 1)
    k = np.arange(16)
    idx = (q[:, 3][:, None] >> (2 * k[None, :]).astype(np.uint32)) & 3
    rgb = pal[np.arange(len(q))[:, None], idx]
    al = ((alpha[:, None] >> (4 * k[None, :]).astype(np.uint64)) & 15).astype(np.int32) * 17
    px = np.concatenate([rgb, al[..., None]], -1).astype(np.uint8)
    return px.reshape(h // 4, w // 4, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(h, w, 4)


# ---------------------------------------------------------------- the pack

COMP_DXT3 = 0x24
CLASS_HASH = 0x001A93CF  # TextureInfo +0x28, the same in the game's chops and world textures
FLAGS_4F = bytes.fromhex("000000000000000201")  # +0x4F..+0x57 as the game's chops
SCROLL_58 = bytes.fromhex("00010000000000000000000100010000")  # +0x58..+0x67 as the game's chops
FORMAT_DXT3 = struct.pack("<5I4s2I", 0, 0, 1, 5, 2, b"DXT3", 0, 0)  # the chops' format record


def chop_texture(name, tile):
    data = dxt3_encode(tile)
    side = tile.shape[0]
    shift = side.bit_length() - 1
    info = bytearray(texpack.TI)
    raw = name.encode("ascii")[:23]
    info[0x0C:0x0C + len(raw)] = raw
    struct.pack_into("<III", info, 0x24, texpack.bstringhash(name), CLASS_HASH, 0)
    struct.pack_into("<iiiii", info, 0x30, 0, 0, len(data), 0, len(data))
    struct.pack_into("<hhBBBBhB", info, 0x44, side, side, shift, shift, COMP_DXT3, 0, 0, 1)
    info[0x4F:0x58] = FLAGS_4F
    info[0x58:0x68] = SCROLL_58
    return texpack.WorldTexture(bytes(info), FORMAT_DXT3, data)


def pack_bytes(img):
    """The file: one texture pack chunk 0xB3300000 at offset 0 (its data at 8) holding FTOWN_MAP_CHOP0..63, each an
    eighth of the picture's side (a 1,024 picture: 128 texels, as the game's own chops)."""
    tex = []
    ch = img.shape[0] // 8
    for n in range(64):
        r, c = divmod(n, 8)
        tex.append(chop_texture("%s_CHOP%d" % (HEADER, n), img[r * ch:(r + 1) * ch, c * ch:(c + 1) * ch]))
    pack = texpack.new_pack(HEADER, "ftown-minimap.tpk", tex)
    return chunk_bytes(texpack.write_pack(pack, 8))


def main():
    from tools.citymap import geo, roadmodel
    osm_path = os.path.join(AREA, "osm.json")
    with open(osm_path, encoding="utf-8") as f:
        osm = json.load(f)
    proj = geo.Projection()
    model = roadmodel.build(osm, proj)
    img = render(model)
    blob = pack_bytes(img)
    with open(OUT_BUN, "wb") as f:
        f.write(blob)
    os.makedirs(AREA, exist_ok=True)
    Image.fromarray(img).save(PREVIEW)
    info = {"name": "F-Town minimap", "file": os.path.basename(OUT_BUN), "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "header": HEADER, "upper_left": list(UPPER_LEFT),
            "width_m": WIDTH, "chops": 64, "chop_px": CHOP, "metres_per_pixel": WIDTH / SIZE,
            "note": "derived from OpenStreetMap data (c) OpenStreetMap contributors (ODbL); built by "
                    "tools/citymap/minimap.py"}
    with open(OUT_JSON, "w", newline="\n") as f:
        json.dump(info, f, indent=1)
        f.write("\n")
    print("%s: %d bytes, sha256 %s; preview %s" % (OUT_BUN, len(blob), info["sha256"], PREVIEW))


if __name__ == "__main__":
    main()
