"""F-Town's house atlases, drawn by us after the photos of Sector 15/16's houses and markets (photos 01, 03, 05, 06, 08,
11, 13: docs/ftown-notes.md "Own looks and a lived-in city"): plastered walls with window frames, iron grilles and
sunshades (chajjas), balcony doors behind railings, AC units, a stair window of breeze blocks, floor bands; boundary
walls with piers, a gate and creepers; roof, water tank and stair-head room (mumty) cells; market shop fronts with
shutters and colourful boards.

- draw_houses() -> (1024, 1024, 3) uint8: FTC_HOUSES, laid out as tools/citymap/textures.py says (two facade blocks of
  parapet + four storeys counted from the roof line, 16 m across, wrapping in u; the 1.5 m boundary strip; sixteen
  64 px cells). The plaster is a light neutral: a building's colour is its vertex tint.
- draw_street() -> (1024, 1024, 3) uint8: FTC_STREET, six 3.2 m shop strips of four 4 m shops each, wrapping in u;
  generic shop names (no brands) in Latin and Devanagari.
"""
import os
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import lettering  # noqa: E402

PLASTER = np.array([112.0, 109.0, 103.0])
DARK_GLASS = np.array([34.0, 40.0, 46.0])
GRILLE = np.array([28.0, 28.0, 30.0])
FRAME = np.array([132.0, 130.0, 126.0])
BAND = np.array([92.0, 90.0, 86.0])
SHADOW = np.array([64.0, 63.0, 60.0])
DOOR = np.array([62.0, 46.0, 34.0])
AC = np.array([150.0, 150.0, 146.0])


class Strip:
    """A region of an image addressed in metres: x along the wall (wrapping every span metres), y down from the
    region's top; px_x, px_y pixels per metre."""

    def __init__(self, img, y0, height_m, span_m, px_y):
        self.img, self.y0, self.height_m, self.span = img, y0, height_m, span_m
        self.px_x = img.shape[1] / span_m
        self.px_y = px_y

    def rect(self, x0, y0, x1, y1, rgb):
        a = int(round(x0 * self.px_x))
        b = int(round(x1 * self.px_x))
        r0 = self.y0 + int(round(y0 * self.px_y))
        r1 = self.y0 + int(round(y1 * self.px_y))
        r0, r1 = max(self.y0, r0), min(self.y0 + int(round(self.height_m * self.px_y)), r1)
        if r1 <= r0 or b <= a:
            return
        cols = np.arange(a, b) % self.img.shape[1]
        self.img[r0:r1, cols] = rgb

    def mul(self, x0, y0, x1, y1, k):
        a, b = int(round(x0 * self.px_x)), int(round(x1 * self.px_x))
        r0 = self.y0 + int(round(y0 * self.px_y))
        r1 = self.y0 + int(round(y1 * self.px_y))
        if r1 <= r0 or b <= a:
            return
        cols = np.arange(a, b) % self.img.shape[1]
        self.img[r0:r1, cols] *= k

    def text(self, s, x0, y0, x1, y1, rgb, font="Arial", weight=700, italic=False):
        box = (int(round(x0 * self.px_x)), self.y0 + int(round(y0 * self.px_y)), int(round(x1 * self.px_x)),
               self.y0 + int(round(y1 * self.px_y)))
        lettering.draw(self.img, s, box, rgb, font, weight, italic)


# --- the facade pieces (metres: x from the bay's left, y down from the storey's top; a storey is 3.2 m) ---

def window(st, x, y0, w=1.5, h=1.4, grille=True, chajja=True):
    """A window: a light frame, dark glass, an iron grille of bars, a sunshade slab over it with its shadow."""
    if getattr(st, "windows", None) is not None:  # window_rects' recorder
        st.windows.append((x, y0, w, h))
    st.rect(x - 0.08, y0 - 0.08, x + w + 0.08, y0 + h + 0.10, FRAME)
    st.rect(x, y0, x + w, y0 + h, DARK_GLASS + 6)
    st.rect(x + w / 2 - 0.03, y0, x + w / 2 + 0.03, y0 + h, FRAME * 0.8)
    if grille:
        n = max(3, int(w / 0.12))
        for k in range(1, n):
            xx = x + w * k / n
            st.rect(xx - 0.015, y0, xx + 0.015, y0 + h, GRILLE)
        for yy in (y0 + h * 0.33, y0 + h * 0.66):
            st.rect(x, yy - 0.02, x + w, yy + 0.02, GRILLE)
    if chajja:
        st.rect(x - 0.35, y0 - 0.32, x + w + 0.35, y0 - 0.20, PLASTER * 1.12)
        st.rect(x - 0.30, y0 - 0.20, x + w + 0.30, y0 - 0.10, SHADOW)
    st.mul(x, y0 + h + 0.10, x + w, y0 + h + 0.9, 0.93)  # rain streaks under the sill


def balcony(st, x, w=2.6):
    """A balcony door (wood and glass) behind a railing on a slab edge across w metres."""
    st.rect(x + 0.6, 0.65, x + 1.65, 2.95, FRAME)
    st.rect(x + 0.68, 0.72, x + 1.57, 2.95, DOOR)
    st.rect(x + 0.74, 0.80, x + 1.51, 1.6, DARK_GLASS)
    st.rect(x - 0.1, 0.45, x + w + 0.1, 0.62, SHADOW)  # the slab above (the next balcony's underside)
    st.rect(x, 1.95, x + w, 2.05, GRILLE)  # the railing's top rail
    for k in range(int(w / 0.14)):
        xx = x + 0.07 + 0.14 * k
        st.rect(xx - 0.015, 2.05, xx + 0.015, 2.95, GRILLE)
    st.rect(x - 0.1, 2.95, x + w + 0.1, 3.12, PLASTER * 1.1)  # the slab's edge


def ac_unit(st, x, y):
    st.rect(x, y, x + 0.85, y + 0.55, AC)
    st.rect(x + 0.05, y + 0.05, x + 0.45, y + 0.50, AC * 0.55)
    for k in range(5):
        st.rect(x + 0.05, y + 0.08 + 0.09 * k, x + 0.45, y + 0.11 + 0.09 * k, AC * 0.8)
    st.rect(x + 0.4, y + 0.55, x + 0.42, y + 1.3, GRILLE)  # the drain pipe


def jali(st, x, w=0.7):
    """A stair window of breeze blocks."""
    st.rect(x - 0.06, 0.4, x + w + 0.06, 2.9, FRAME)
    for i in range(int(w / 0.2)):
        for j in range(int(2.4 / 0.2)):
            st.rect(x + 0.04 + 0.2 * i, 0.46 + 0.2 * j, x + 0.16 + 0.2 * i, 0.58 + 0.2 * j, DARK_GLASS + 10)


def door(st, x):
    st.rect(x - 0.08, 0.75, x + 1.08, 3.0, FRAME)
    st.rect(x, 0.83, x + 1.0, 3.0, DOOR)
    st.rect(x + 0.1, 0.95, x + 0.9, 1.9, DOOR * 0.8)


BAYS = {  # per facade block, per storey row (top storey first): the bays across 16 m
    # rows count from the roof down, so row 1, 2 or 3 is the ground storey of a 2-, 3- or 4-storey house: each has a
    # door and rows 1 and 2 no balcony door with railings (the second review of the own looks)
    0: [["win", "ac", "jali", "win"],
        ["door", "win", "win", "ac"],
        ["win", "pair", "door", "jali"],
        ["door", "win", "ac", "pair"]],
    1: [["balc", "balc", "ac", "balc"],
        ["win", "door", "jali", "win"],
        ["door", "ac", "win", "win"],
        ["pair", "door", "win", "balc"]],
}


def _storey(st, row_bays, block):
    for k, kind in enumerate(row_bays):
        x = 4.0 * k
        if kind == "win":
            window(st, x + 1.25, 1.0, 1.5 if block == 0 else 2.0)
        elif kind == "pair":
            window(st, x + 0.6, 1.1, 0.9, 1.2)
            window(st, x + 2.4, 1.1, 0.9, 1.2)
        elif kind == "ac":
            window(st, x + 0.6, 1.0, 1.4, 1.4)
            ac_unit(st, x + 2.5, 1.3)
        elif kind == "balc":
            balcony(st, x + 0.7, 2.6 if block == 0 else 3.2)
        elif kind == "jali":
            jali(st, x + 1.6)
        elif kind == "door":
            door(st, x + 0.5)
            window(st, x + 2.2, 1.1, 1.2, 1.3)
    st.rect(0, 3.0, st.span, 3.2, BAND)  # the floor band (reads as a plinth on the lowest storey)


class _Recorder:
    """A Strip that draws nothing and keeps the windows' rectangles (window_rects)."""
    span = 16.0

    def __init__(self):
        self.windows = []

    def rect(self, *a):
        pass

    def mul(self, *a):
        pass

    def text(self, *a, **k):
        pass


def window_rects(block, row):
    """[(x, y0, w, h)] of the glazed windows of facade block `block`'s storey row `row` (0 = the top storey): metres
    across the 16 m span and down from the storey's top, as _storey draws them (the evening's lit panes,
    tools/citymap/evening.py)."""
    rec = _Recorder()
    _storey(rec, BAYS[block][row], block)
    return rec.windows


def _facade(img, block):
    y0 = block * 448
    pxy = 448.0 / 13.7
    img[y0:y0 + 448] = PLASTER
    par = Strip(img, y0, 0.9, 16.0, pxy)
    par.rect(0, 0.0, 16, 0.10, PLASTER * 1.15)  # the coping
    par.rect(0, 0.10, 16, 0.16, SHADOW)
    for k in range(4):  # a jali panel in the parapet now and then
        if (k + block) % 2 == 0:
            for i in range(6):
                par.rect(1.2 + 4 * k + 0.25 * i, 0.32, 1.35 + 4 * k + 0.25 * i, 0.62, SHADOW)
    for r in range(4):
        st = Strip(img, y0 + int(round((0.9 + 3.2 * r) * pxy)), 3.2, 16.0, pxy)
        _storey(st, BAYS[block][r], block)


def _cells(img, rng):
    from tools.citymap import textures as T
    y0 = 960
    for k, cell in enumerate(T.HOUSE_CELLS):
        x0 = k * 64
        c = img[y0:y0 + 64, x0:x0 + 64]
        if cell == "roof":
            c[:] = (96, 94, 90)
            c += rng.uniform(-6, 6, size=(64, 64, 1))
        elif cell == "terrace":
            c[:] = (104, 86, 78)
            c[::8] = (84, 70, 64)
            c[:, ::8] = (84, 70, 64)
        elif cell == "tank":
            c[:] = (26, 26, 28)
            c[::6] = (44, 44, 46)  # the ribs
        elif cell == "tanktop":
            c[:] = (34, 34, 36)
        elif cell == "mumty":
            c[:] = PLASTER
            c[14:64, 18:46] = DOOR
            c[4:8] = PLASTER * 1.12
        elif cell == "mumtyroof":
            c[:] = (90, 88, 84)
        elif cell == "balcony":
            c[:] = PLASTER
            c[0:5] = PLASTER * 1.12
            c[5:9] = SHADOW
            c[12:44, ::6] = GRILLE
            c[54:64] = BAND
        elif cell == "slab":
            c[:] = (70, 69, 66)
        elif cell == "hedge":
            c[:] = (46, 70, 36)
            c += rng.uniform(-10, 10, size=(64, 64, 1))
            c[rng.uniform(size=(64, 64)) < 0.04] = (150, 50, 110)  # bougainvillea
        elif cell == "pole":
            c[:] = (108, 106, 100)
        elif cell == "wire":
            c[:] = (18, 18, 18)
        elif cell == "gate":
            c[:] = (40, 52, 60)
            c[:, ::5] = (24, 30, 34)
        elif cell == "ac":
            c[:] = AC
        elif cell == "litwin":  # a lit window for the evening (evening.wall_panes): warm glass, curtains, a grille
            c[:] = (250, 214, 146)
            c[24:40] = (255, 232, 176)  # the lamp's glow in the middle
            c[:, 0:11] = (214, 132, 78)
            c[:, 53:64] = (214, 132, 78)
            c[:, 31:33] = (96, 84, 66)  # the frame's middle bar
            c[:, 10::9] = (120, 100, 74)  # the grille's bars
            c[21:23] = (120, 100, 74)
            c[42:44] = (120, 100, 74)
        else:
            c[:] = PLASTER


def _boundary(img, rng):
    """The 1.5 m boundary wall, 16 m across (y 896-959): coping, piers every 3.2 m, a gate at 6.4-8.8 m, a creeper
    patch at 11-13 m, a plinth line."""
    st = Strip(img, 896, 1.5, 16.0, 64 / 1.5)
    st.rect(0, 0, 16, 1.5, PLASTER * 0.98)
    st.rect(0, 0, 16, 0.10, PLASTER * 1.15)
    st.rect(0, 0.10, 16, 0.15, SHADOW)
    for k in range(5):
        st.rect(3.2 * k - 0.2, 0, 3.2 * k + 0.2, 1.5, PLASTER * 1.07)
        st.rect(3.2 * k + 0.2, 0.1, 3.2 * k + 0.24, 1.5, SHADOW)
    st.rect(6.6, 0.12, 8.8, 1.5, (40, 52, 60))
    for k in range(22):
        st.rect(6.65 + 0.1 * k, 0.2, 6.68 + 0.1 * k, 1.5, (24, 30, 34))
    st.rect(6.6, 0.55, 8.8, 0.6, (24, 30, 34))
    st.rect(0, 1.38, 16, 1.5, BAND)
    a = img[896 + 2:896 + 40, int(11 * 64):int(13.2 * 64)]
    m = rng.uniform(size=a.shape[:2]) < 0.55
    a[m] = (46, 72, 38)
    a[m & (rng.uniform(size=a.shape[:2]) < 0.15)] = (150, 50, 110)


def draw_houses():
    rng = np.random.default_rng(20261104)
    img = np.zeros((1024, 1024, 3), dtype=float)
    _facade(img, 0)
    _facade(img, 1)
    _boundary(img, rng)
    _cells(img, rng)
    img[:960] += rng.uniform(-4, 4, size=(960, 1024, 1))
    # the cell row's edge rows, outside every cell's uvs (textures.house_cell_uv): the coping's colour at the bottom
    # (wrap addressing samples it above block 0's parapet), the boundary wall's plinth band at the top (the review)
    img[1020:1024] = PLASTER * 1.15
    img[960:964] = BAND
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


SHOPS = [  # (board colour, text colour, name, Devanagari?) per shop, six strips of four
    [((176, 40, 36), (250, 240, 220), "SHARMA GENERAL STORE", False),
     ((230, 150, 30), (120, 20, 20), "गुप्ता स्वीट्स", True),
     ((36, 80, 160), (250, 250, 250), "MOBILE POINT", False),
     ((40, 130, 70), (250, 250, 250), "JAIN MEDICOS", False)],
    [((40, 60, 130), (250, 230, 120), "AGARWAL TRADERS", False),
     ((200, 60, 40), (250, 250, 240), "बंसल किराना स्टोर", True),
     ((230, 200, 60), (40, 40, 40), "NEW STYLE TAILORS", False),
     ((120, 40, 110), (250, 250, 250), "KRISHNA HARDWARE", False)],
    [((30, 110, 130), (250, 250, 250), "SINGH ELECTRICALS", False),
     ((170, 30, 50), (250, 220, 120), "शिव शक्ति ज्वैलर्स", True),
     ((236, 236, 230), (30, 90, 40), "CHAUHAN DAIRY", False),
     ((210, 110, 30), (250, 250, 250), "OM PHOTOSTAT", False)],
    [((40, 120, 60), (250, 250, 240), "GUPTA PAINTS", False),
     ((36, 60, 140), (250, 250, 250), "यादव ऑटो पार्ट्स", True),
     ((190, 40, 40), (250, 250, 250), "BHARAT BAKERY", False),
     ((236, 230, 210), (160, 30, 30), "VERMA OPTICALS", False)],
    [((210, 160, 30), (60, 30, 10), "LAKSHMI CLOTH HOUSE", False),
     ((40, 100, 160), (250, 250, 250), "CITY DENTAL CLINIC", False),
     ((150, 40, 40), (250, 230, 200), "मित्तल बर्तन भंडार", True),
     ((30, 120, 110), (250, 250, 250), "STAR CYBER CAFE", False)],
    [((236, 236, 236), (190, 30, 40), "KHANNA SHOES", False),
     ((200, 80, 30), (250, 250, 250), "राजू टी स्टॉल", True),
     ((60, 60, 140), (250, 250, 250), "ARORA BOOK DEPOT", False),
     ((40, 140, 90), (250, 250, 250), "FRESH FRUITS", False)],
]


def _shop(st, x, board, ink, name, deva, k, rng):
    st.rect(x, 0, x + 4, 3.2, PLASTER * 0.8)
    st.rect(x + 0.1, 0.05, x + 3.9, 0.95, board)  # the signboard
    st.rect(x + 0.1, 0.05, x + 3.9, 0.10, np.array(board) * 0.7)
    st.rect(x + 0.1, 0.90, x + 3.9, 0.95, np.array(board) * 0.7)
    st.text(name, x + 0.25, 0.20, x + 3.75, 0.82, ink, "Nirmala UI" if deva else "Arial", 700)
    st.rect(x, 0.95, x + 4, 1.12, SHADOW)
    if k % 2 == 0:  # a rolling shutter, half up, goods inside
        st.rect(x + 0.25, 1.12, x + 3.75, 3.2, (60, 56, 52))
        for j in range(5):
            st.rect(x + 0.5 + 0.6 * j, 2.0, x + 0.95 + 0.6 * j, 2.9, rng.choice([(150, 60, 50), (60, 90, 140),
                                                                             (190, 160, 80), (90, 120, 70)]))
        st.rect(x + 0.25, 1.12, x + 3.75, 1.7, (140, 140, 136))
        for j in range(8):
            st.rect(x + 0.25, 1.15 + 0.07 * j, x + 3.75, 1.17 + 0.07 * j, (112, 112, 110))
    else:  # a glass front with a counter
        st.rect(x + 0.25, 1.12, x + 3.75, 3.2, (54, 66, 74))
        st.rect(x + 0.25, 2.4, x + 3.75, 3.2, (150, 140, 120))
        st.rect(x + 1.9, 1.12, x + 2.0, 3.2, FRAME)


def draw_street():
    from tools.citymap import textures as T
    rng = np.random.default_rng(20261105)
    img = np.empty((1024, 1024, 3), dtype=float)
    img[:] = PLASTER * 0.72
    for s, shops in enumerate(SHOPS):
        y0 = int(round(T.street_v(s, 0.0) * 1024))
        st = Strip(img, y0, 3.2, 16.0, (T.street_v(s, 3.2) - T.street_v(s, 0.0)) * 1024 / 3.2)
        for k, (board, ink, name, deva) in enumerate(shops):
            _shop(st, 4.0 * k, np.array(board, float), ink, name, deva, k + s, rng)
        for k in range(4):  # the pillars between shops, across the wrap at 0 / 16 m too
            st.rect(4.0 * k - 0.08, 0, 4.0 * k + 0.08, 3.2, PLASTER * 0.95)
    img += rng.uniform(-3, 3, size=(1024, 1024, 1))
    return np.clip(np.round(img), 0, 255).astype(np.uint8)
