"""F-Town's city textures, drawn here (deterministic; no game pixels), and the metres one tile of each covers.

    .tools/cityenv/Scripts/python tools/citymap/textures.py tools/citymap/textures     (writes the PNGs)

The asphalt is the small fixes' tarmac (tools/world/slab.py: Rockport's road textures' grey, grain and patches, every
pixel on the tinted grey ladder so DXT1 keeps it grey). The plaster is a light wall with one window a tile, one tile =
TILE_M["plaster"] (4 m along the wall x one 3.2 m storey), so walls show their storeys; buildings get their colour from
the vertex colour (four plaster tints), so all walls are one texture and one draw a tile.
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (TOOLS, os.path.join(TOOLS, "carbuild"), os.path.dirname(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from world import slab  # noqa: E402

NAMES = {"asphalt": "FTC_ASPHALT", "paint": "FTC_PAINT", "pavement": "FTC_PAVEMENT", "concrete": "FTC_CONCRETE",
         "plaster": "FTC_PLASTER", "roof": "FTC_ROOF", "grass": "FTC_GRASS", "earth": "FTC_EARTH",
         # the landmarks stage (docs/ftown-notes.md "Landmarks and street furniture"): our own drawn finishes
         "stn_beige": "FTC_STN_BEIGE", "stn_orange": "FTC_STN_ORANGE", "stn_brick": "FTC_STN_BRICK",
         "roofmetal": "FTC_ROOFMETAL", "glass": "FTC_GLASS", "mallpanel": "FTC_MALLPANEL",
         "bluepanel": "FTC_BLUEPANEL", "shopfront": "FTC_SHOPFRONT", "furniture": "FTC_FURNITURE",
         "kerb": "FTC_KERB", "crashwall": "FTC_CRASHWALL",
         # street life (docs/ftown-notes.md "Street life (2026-11-04)"): the parked vehicles' colour cells
         "vehicles": "FTC_VEHICLES",
         # own looks (docs/ftown-notes.md "Own looks and a lived-in city (2026-11-04)"): the house atlases
         "houses": "FTC_HOUSES", "street": "FTC_STREET",
         # Run I fixes, item 11 (tools/citymap/groundtex.py): the street ground
         "paver": "FTC_PAVER", "lot": "FTC_LOT"}
SIDES = {"asphalt": 256, "paint": 64, "pavement": 128, "concrete": 128, "plaster": 128, "roof": 128, "grass": 128,
         "earth": 512, "stn_beige": 128, "stn_orange": 128, "stn_brick": 128, "roofmetal": 64, "glass": 128,
         "mallpanel": 128, "bluepanel": 128, "shopfront": 256, "furniture": 512, "kerb": 64, "crashwall": 64,
         "vehicles": 128, "houses": 1024, "street": 1024, "paver": 256, "lot": 256}
# metres one texture tile covers (u along x or along a wall, v along y or down a wall)
TILE_M = {"asphalt": (10.0, 10.0), "paint": (2.0, 2.0), "pavement": (2.0, 2.0), "concrete": (4.0, 4.0),
          "plaster": (4.0, 3.2), "roof": (8.0, 8.0), "grass": (8.0, 8.0), "earth": (16.0, 16.0),
          "stn_beige": (4.0, 3.2), "stn_orange": (4.0, 3.2), "stn_brick": (4.0, 3.2), "roofmetal": (2.0, 2.0),
          "glass": (4.0, 3.6), "mallpanel": (4.0, 4.0), "bluepanel": (4.0, 4.0), "shopfront": (8.0, 3.2),
          "furniture": (1.0, 1.0), "kerb": (1.0, 1.0), "crashwall": (2.0, 1.0), "vehicles": (1.0, 1.0),
          "houses": (16.0, 13.7), "street": (16.0, 3.2), "paver": (4.0, 4.0),
          "lot": (8.0, 8.0)}

# the house atlases (own looks; tools/citymap/housetex.py draws them). FTC_HOUSES, 1024 px square: u 0..1 is
# HOUSE_SPAN_M along a wall (it wraps); y 0-447 facade block 0 (sector houses), 448-895 block 1 (flats and commercial),
# each FACADE_M tall: a 0.9 m parapet over four 3.2 m storeys, counted from the parapet's top down (a 2-4 storey house
# is one quad per wall); y 896-959 the 1.5 m boundary wall; y 960-1023 sixteen 64 px cells (HOUSE_CELLS; uvs 4 px
# inside). FTC_STREET, 1024 px square: STREET_STRIPS shop strips of one 3.2 m storey, 16 m across, wrapping in u.
HOUSE_SPAN_M = 16.0
FACADE_M = 0.9 + 4 * 3.2
FACADE_PX = 448
BOUNDARY_V = (896 / 1024, 960 / 1024)
HOUSE_CELLS = ["roof", "terrace", "tank", "tanktop", "mumty", "mumtyroof", "balcony", "slab", "hedge", "pole", "wire",
               "gate", "ac", "plain", "plain2", "litwin"]
STREET_STRIPS = 6
STREET_PITCH = 170  # pixels from one shop strip's top to the next (a 4 px gap or more between strips)
STREET_PX = 164  # pixels of one 3.2 m strip


def facade_v(block, z_from_top):
    """v in FTC_HOUSES of a point z_from_top metres below the parapet's top in facade block 0 or 1: the block's
    FACADE_PX rows less one at each end (a texel inside: the review fixes, no neighbour blends in at its edges)."""
    return (block * FACADE_PX + 1 + z_from_top * (FACADE_PX - 2) / FACADE_M) / 1024.0


def house_cell_uv(cell, s, t):
    """(u, v) in FTC_HOUSES of (s, t) in 0..1 across a cell, 4 px inside its edges (no neighbour bleeds in; the
    row's top and bottom 4 px are painted the boundary plinth's and the coping's colours, so v stays 964..1016)."""
    k = HOUSE_CELLS.index(cell)
    s, t = min(max(s, 0.0), 1.0), min(max(t, 0.0), 1.0)  # (a roof's vertices are snapped 0.1 mm past its bounds)
    return ((k * 64 + 4 + 56 * s) / 1024.0, (960 + 4 + 52 * t) / 1024.0)


def street_v(strip, z_from_top):
    """v in FTC_STREET of a point z_from_top metres (0..3.2) below the top of shop strip `strip`."""
    return (strip * STREET_PITCH + 4 + z_from_top * STREET_PX / 3.2) / 1024.0


def far_mean(kind, side, px):
    """The colour a texture's far-atlas cell takes: its mean, or for FTC_HOUSES its facade blocks' mean (the walls a
    far building shows; the cells and boundary strip are near detail)."""
    import numpy as np
    a = np.asarray(px, dtype=float).reshape(side, side, 3)
    if kind == "houses":
        a = a[:2 * FACADE_PX]
    return a.reshape(-1, 3).mean(0)
# the furniture atlas (256 x 256, one texture so a tile's furniture is one mesh): 4 x 4 cells of 16 px in its top left
# corner, one solid colour each (a uv at a cell's centre draws its colour); the billboards' designs in the rest
FURNITURE_CELLS = ["metal", "yellow", "white", "black", "red", "amber", "green", "signgreen", "lightgrey", "concrete",
                   "planting", "blue", "lantern", "darkmetal", "orange", "brown"]
FURNITURE_RGB = {"metal": (70, 72, 74), "yellow": (190, 160, 30), "white": (190, 190, 186), "black": (22, 22, 22),
                 "red": (210, 40, 30), "amber": (220, 150, 30), "green": (40, 190, 70), "signgreen": (25, 105, 60),
                 "lightgrey": (140, 140, 138), "concrete": (96, 95, 90), "planting": (58, 84, 40), "blue": (35, 60, 140),
                 "lantern": (225, 222, 200), "darkmetal": (40, 42, 44), "orange": (200, 100, 40), "brown": (90, 70, 50)}
BILLBOARDS = 4  # designs: rows 1-3 of four (FURN_SIDE x FURN_SIDE / 4) and the top row's right three quarters


def furniture_uv(cell):
    k = FURNITURE_CELLS.index(cell)
    return (((k % 4) * 16 + 8) / 256.0, ((k // 4) * 16 + 8) / 256.0)


def billboard_rect(design):
    """(u0, v0, u1, v1) of a billboard design in the furniture atlas (v down from the top row)."""
    if design < 3:
        return (0.0, (design + 1) * 0.25, 1.0, (design + 2) * 0.25)
    return (0.25, 0.0, 1.0, 0.25)


def _noise(rng, n, base, amp):
    return [tuple(max(0, min(255, int(c + rng.uniform(-amp, amp)))) for c in base) for _ in range(n * n)]


def _blotchy(rng, n, base, amp, period):
    big = slab._value_noise(n, period, rng)
    out = []
    for i in range(n * n):
        v = big[i] * amp + rng.gauss(0, amp / 3)
        out.append(tuple(max(0, min(255, int(c + v))) for c in base))
    return out


def draw():
    """{kind: (side, [(r, g, b)] row by row)}."""
    rng = random.Random(20261103)
    out = {"asphalt": (256, slab.draw_textures()["asphalt"])}
    out["paint"] = (64, _noise(rng, 64, (232, 232, 224), 6))
    n = 128
    pav = []
    for y in range(n):
        for x in range(n):
            joint = x % 32 in (0, 1) or y % 32 in (0, 1)  # 0.5 m slabs on a 2 m tile
            base = (66, 65, 62) if joint else (96, 95, 92)
            pav.append(tuple(max(0, min(255, c + rng.randint(-5, 5))) for c in base))
    out["pavement"] = (n, pav)
    pl = []
    for y in range(n):
        for x in range(n):
            u, v = x / n, y / n
            if 0.32 <= u <= 0.68 and 0.22 <= v <= 0.66:  # the window (4 m x 3.2 m tile: 1.4 x 1.4 m)
                inner = 0.34 <= u <= 0.66 and 0.24 <= v <= 0.64
                base = (34, 40, 46) if inner else (70, 66, 60)
                if inner and abs(u - 0.5) < 0.01:
                    base = (70, 66, 60)
            elif v >= 0.94:  # the floor band at the bottom of each storey
                base = (84, 82, 77)
            else:
                base = (100, 97, 91)
            pl.append(tuple(max(0, min(255, c + rng.randint(-4, 4))) for c in base))
    out["plaster"] = (n, pl)
    # city fixes (fault 3): bases in Rockport's measured ranges (tools/citymap/rockport_colours.py: grass 70, dirt 62,
    # sidewalk 94.6, plaster 85.9, concrete 81.3 luminance; chroma 25, 9, 7, 7, 8)
    out["roof"] = (n, _blotchy(rng, n, (84, 82, 78), 8, 32))
    out["grass"] = (n, _blotchy(rng, n, (68, 76, 46), 9, 16))
    _old_earth = _blotchy(rng, n, (70, 63, 55), 8, 16)  # (drawn still: the generator's sequence stays as it was)
    from tools.citymap import groundtex  # Run I fixes, item 11: the earth redrawn, and the new street ground
    out.update(groundtex.draw())
    out["concrete"] = (n, _blotchy(rng, n, (84, 83, 79), 6, 32))  # the city's own (the slab keeps its lighter one)
    out.update(_landmark_finishes(random.Random(20261104)))
    from tools.citymap import vehicles  # the street life's parked vehicles (solid colour cells, no noise)
    out["vehicles"] = vehicles.atlas()
    from tools.citymap import housetex  # own looks: the house atlases
    for kind, img in (("houses", housetex.draw_houses()), ("street", housetex.draw_street())):
        out[kind] = (img.shape[0], [tuple(p) for p in img.reshape(-1, 3).tolist()])
    return out


def _img(n, f, rng, amp=4):
    """n x n pixels from f(u, v) -> (r, g, b), a little noise added."""
    px = []
    for y in range(n):
        for x in range(n):
            c = f((x + 0.5) / n, (y + 0.5) / n)
            px.append(tuple(max(0, min(255, int(ch + rng.randint(-amp, amp)))) for ch in c))
    return px


def _landmark_finishes(rng):
    """Our own finishes for the landmarks, the metro and the street furniture (docs/ftown-notes.md "Landmarks and
    street furniture"): colours after the photos, luminance near Rockport's walls."""
    out = {}

    def beige(u, v):  # Neelam Chowk Ajronda: brown-beige slats (photos 33, 35)
        return (112, 94, 76) if int(v * 40) % 2 else (96, 80, 64)
    out["stn_beige"] = (128, _img(128, beige, rng))

    def orange(u, v):  # Bata Chowk: a blue band, white panels with windows, an orange band (photos 37-41)
        if v < 0.18:
            return (40, 86, 150)
        if v > 0.82:
            return (196, 98, 40)
        if 0.35 < v < 0.65 and (u * 4) % 1.0 < 0.8:
            return (46, 66, 84)
        return (150, 150, 146)
    out["stn_orange"] = (128, _img(128, orange, rng))

    def brick(u, v):  # Old Faridabad: white panels over a red-brick base (photos 51, 53)
        if v > 0.55:
            row = int((v - 0.55) * 128 / 4)
            off = 0.5 if row % 2 else 0.0
            if int((v - 0.55) * 128) % 4 == 0 or int((u * 16 + off) * 4) % 4 == 0:
                return (120, 112, 104)
            return (140, 64, 48)
        return (128, 128, 126) if (u * 4) % 1.0 > 0.03 else (96, 96, 96)
    out["stn_brick"] = (128, _img(128, brick, rng))
    out["roofmetal"] = (64, _img(64, lambda u, v: (40, 104, 122) if (u * 8) % 1.0 < 0.7 else (30, 80, 96), rng))

    def glass(u, v):  # curtain walls (Marengo Asia, Fortis, malls): blue-grey panes, light mullions, a floor band
        if v > 0.88 or (u * 4) % 1.0 < 0.06:
            return (118, 122, 124)
        return (52, 72, 88) if v < 0.5 else (60, 80, 96)
    out["glass"] = (128, _img(128, glass, rng, 3))
    out["mallpanel"] = (128, _img(128, lambda u, v: (96, 96, 94) if (u * 2) % 1.0 < 0.02 or (v * 2) % 1.0 < 0.02
                                   else (132, 132, 128), rng, 3))
    out["bluepanel"] = (128, _img(128, lambda u, v: (30, 40, 90) if (u * 2) % 1.0 < 0.02 or (v * 2) % 1.0 < 0.02
                                   else (44, 62, 150), rng, 3))
    # shop fronts (8 m x one 3.2 m storey): a signboard band over shutters and glass, signs in four colours
    signs = [(170, 40, 34), (36, 70, 150), (30, 120, 60), (200, 160, 30), (150, 40, 110), (210, 110, 30)]
    pick = [signs[rng.randrange(len(signs))] for _ in range(4)]

    def shop(u, v):
        k = int(u * 4)
        uu = (u * 4) % 1.0
        if v < 0.30:
            c = pick[k]
            if 0.35 < v / 0.30 < 0.65 and 0.15 < uu < 0.85 and int(uu * 30) % 3:
                return (230, 228, 220)  # the sign's lettering, abstract
            return c
        if uu < 0.04 or uu > 0.96:
            return (110, 108, 104)
        if k % 2:
            return (110, 112, 112) if int(v * 64) % 2 else (88, 90, 90)  # a rolling shutter
        return (50, 62, 70) if v < 0.92 else (90, 86, 80)  # a glass front
    out["shopfront"] = (256, _img(256, shop, rng, 3))
    out["kerb"] = (64, _img(64, lambda u, v: (24, 24, 24) if u < 0.5 else (196, 196, 190), rng, 2))
    out["crashwall"] = (64, _img(64, lambda u, v: (150, 150, 146) if v < 0.75 else (80, 80, 78), rng, 3))
    out["furniture"] = (FURN_SIDE, furniture_atlas(rng))
    return out


# Run I fixes, item 2 (docs/ftown-notes.md "Run I fixes: the city side"): the user found the boards "still not
# readable": the designs were abstract bars, and in the evening their bright texels under the raised vertex colour
# blew out to white (screenshots 106, 107). Now four fictional adverts with large lettering (GDI: Latin and
# Devanagari), at 51 px a metre (the atlas 512 px), each mean luminance about the market shop fronts' (FTC_STREET,
# 99.5), light ink on a dark ground (contrast 3:1 or more); the evening colour of their class is held under the shop
# fronts' (evening.CLASSES "board"). No real brand: invented names and slogans.
FURN_SIDE = 512
BILLBOARD_ADS = [
    {"bg": (18, 86, 50), "ink": (250, 240, 205), "accent": (200, 40, 36),
     "text": ("F-TOWN COLA", "ठंडा पियो, मस्त जियो", "CHILL KARO! 250 ML")},
    {"bg": (128, 24, 26), "ink": (255, 226, 110), "accent": (250, 160, 40),
     "text": ("SHARMA SWEETS", "शुद्ध देसी घी की मिठाइयाँ", "SINCE 1972 • SECTOR 16")},
    {"bg": (20, 38, 94), "ink": (240, 240, 232), "accent": (230, 170, 30),
     "text": ("DRIVE SAFE", "सड़क सुरक्षा, जीवन रक्षा", "WEAR A HELMET • BUCKLE UP")},
    {"bg": (10, 62, 72), "ink": (255, 214, 70), "accent": (240, 240, 230),
     "text": ("GREENLINE HOMES", "2 और 3 BHK फ्लैट", "NOW BOOKING • NEAR METRO")},
]


def billboard_design(k, w=512, h=128):
    """(h, w, 3) uint8: advert k of BILLBOARD_ADS on a 10 x 2.5 m board: a dark frame, the ground, an accent disc on
    the left, the headline (Impact) over the Hindi line (Nirmala UI) and a small line (Arial)."""
    from tools.citymap import lettering
    import numpy as np
    ad = BILLBOARD_ADS[k]
    img = np.empty((h, w, 3), dtype=float)
    img[:] = ad["bg"]
    f = 4  # frame
    img[:f], img[-f:], img[:, :f], img[:, -f:] = (40, 40, 40), (40, 40, 40), (40, 40, 40), (40, 40, 40)
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy, r = h * 0.55, h / 2, h * 0.36
    disc = (xx - cx) ** 2 + (yy - cy) ** 2 < r * r
    img[disc] = ad["accent"]
    ring = np.abs(np.hypot(xx - cx, yy - cy) - r * 0.72) < r * 0.08
    img[ring & disc] = ad["bg"]
    x0 = int(cx + r + h * 0.15)
    head, hindi, small = ad["text"]
    lettering.draw(img, head, (x0, h * 0.08, w - 10, h * 0.50), ad["ink"], "Impact", 400)
    lettering.draw(img, hindi, (x0, h * 0.52, w - 10, h * 0.76), ad["ink"], "Nirmala UI", 700)
    lettering.draw(img, small, (x0, h * 0.78, w - 10, h * 0.93), ad["ink"], "Arial", 700)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def furniture_atlas(rng):
    """The furniture atlas's pixels, FURN_SIDE square, row by row: 4 x 4 solid colour cells in its top left quarter
    of a row (furniture_uv), the billboard designs (billboard_rect): three 512 x 128 rows and the top row's right
    part (384 x 128: design 3 drawn at 512 and squeezed, so the board's 10 m shows it unsqueezed)."""
    import numpy as np
    from PIL import Image
    n = FURN_SIDE
    a = np.zeros((n, n, 3), dtype=np.uint8)
    q = n // 4
    cell = q // 4
    for k, name in enumerate(FURNITURE_CELLS):
        a[(k // 4) * cell:(k // 4 + 1) * cell, (k % 4) * cell:(k % 4 + 1) * cell] = FURNITURE_RGB[name]
    for k in range(BILLBOARDS):
        d = billboard_design(k, n, q)
        if k < 3:
            a[(k + 1) * q:(k + 2) * q, :] = d
        else:
            a[0:q, q:] = np.asarray(Image.fromarray(d).resize((n - q, q), Image.Resampling.LANCZOS))
    return [tuple(p) for p in a.reshape(-1, 3).tolist()]


# the far atlas (Run H fixes, fault 4: docs/ftown-notes.md "Run H fixes (2026-11-04)"): FAR_CELL x FAR_CELL flat cells
# of FAR_SIDE pixels, one per texture, its colour the texture's mean; the far models draw every triangle with its
# texture's cell (all three uvs on the cell's centre: no texture gradient, so the GPU reads mip 0, the cell's colour)
FAR_NAME = "FTC_FAR"
FAR_CELL = 8
FAR_SIDE = 8


def far_atlas(means):
    """(side, pixels [(r, g, b)] row by row, {texture name: (u, v)}) of the far atlas for {texture name: (r, g, b)},
    cells in sorted name order."""
    names = sorted(means)
    if len(names) > FAR_CELL * FAR_CELL:
        raise ValueError("%d textures, %d far cells" % (len(names), FAR_CELL * FAR_CELL))
    side = FAR_CELL * FAR_SIDE
    px = [(128, 128, 128)] * (side * side)
    uv = {}
    for k, nm in enumerate(names):
        cx, cy = k % FAR_CELL, k // FAR_CELL
        c = tuple(int(round(v)) for v in means[nm])
        for y in range(cy * FAR_SIDE, (cy + 1) * FAR_SIDE):
            for x in range(cx * FAR_SIDE, (cx + 1) * FAR_SIDE):
                px[y * side + x] = c
        uv[nm] = ((cx + 0.5) / FAR_CELL, (cy + 0.5) / FAR_CELL)
    return side, px, uv


def mean(px):
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))


def save(out_dir):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for kind, (side, px) in draw().items():
        img = Image.new("RGB", (side, side))
        img.putdata(px)
        p = os.path.join(out_dir, NAMES[kind].lower() + ".png")
        img.save(p)
        paths.append(p)
    return paths


if __name__ == "__main__":
    print("\n".join(save(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "textures"))))
