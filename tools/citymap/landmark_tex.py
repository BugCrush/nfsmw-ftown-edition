"""F-Town's landmark faces drawn by us (the user, 2026-11-04: the photos "were for you to take reference from and
actually build the look of the building yourself"): one texture per face of the registry
(tools/citymap/landmarks/registry.json), at its size, under the same FTL_ name, so every face keeps its place and its
tests. Each painter is designed by looking at the face's photo (ftownphotos/, git-ignored): its layout, materials,
colours, window rhythm and signage, the names as on the real signs (lettering by tools/citymap/lettering.py, logos as
simple shapes in their colours). No photo is opened here: the pixels are ours (test_landmark_tex checks it).

    .tools/cityenv/Scripts/python tools/citymap/landmark_tex.py [out dir]   (writes ftl_*.png, default textures/)

A face's texture runs left to right as seen from outside, its top row at the top of the face (parts.wall's v);
faces that repeat along their wall (the stations' sides, the market row, the mural) are seamless left to right.
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from tools.citymap import lettering  # noqa: E402
from tools.citymap import station_letters  # noqa: E402

OUT = os.path.join(HERE, "textures")
DEVA = "Nirmala UI"


class Canvas:
    """An (h, w, 3) float picture with drawing helpers in fractions of the width (x) and height (y)."""

    def __init__(self, w, h, rgb, seed):
        self.w, self.h = w, h
        self.a = np.empty((h, w, 3), dtype=float)
        self.a[:] = rgb
        self.rng = np.random.default_rng(seed)

    def px(self, x0, y0, x1, y1):
        return (int(round(x0 * self.w)), int(round(y0 * self.h)), int(round(x1 * self.w)), int(round(y1 * self.h)))

    def rect(self, x0, y0, x1, y1, rgb, wrap=False):
        a, b, c, d = self.px(x0, y0, x1, y1)
        b, d = max(0, b), min(self.h, d)
        if wrap:
            for k in range(a, c):
                self.a[b:d, k % self.w] = rgb
            return
        self.a[b:d, max(0, a):min(self.w, c)] = rgb

    def frame(self, x0, y0, x1, y1, rgb, t=1):
        a, b, c, d = self.px(x0, y0, x1, y1)
        self.a[b:b + t, a:c] = rgb
        self.a[d - t:d, a:c] = rgb
        self.a[b:d, a:a + t] = rgb
        self.a[b:d, c - t:c] = rgb

    def vgrad(self, x0, y0, x1, y1, top, bottom):
        a, b, c, d = self.px(x0, y0, x1, y1)
        t = np.linspace(0.0, 1.0, max(1, d - b))[:, None, None]
        self.a[b:d, a:c] = np.asarray(top, float) * (1 - t) + np.asarray(bottom, float) * t

    def disc(self, cx, cy, r_px, rgb, ring=None):
        """A disc of r_px pixels at (cx, cy) fractions (round on the pixel grid whatever the aspect)."""
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        d = np.hypot(xx + 0.5 - cx * self.w, yy + 0.5 - cy * self.h)
        m = d <= r_px if ring is None else (d <= r_px) & (d >= r_px - ring)
        self.a[m] = rgb

    def text(self, s, x0, y0, x1, y1, rgb, font="Arial", weight=700, italic=False, align="center", stretch=False):
        lettering.draw(self.a, s, self.px(x0, y0, x1, y1), rgb, font, weight, italic, align, stretch)

    def grain(self, amp=4.0):
        self.a += self.rng.uniform(-amp, amp, size=self.a.shape[:2])[..., None]

    def shade(self, x0, y0, x1, y1, k):
        a, b, c, d = self.px(x0, y0, x1, y1)
        self.a[b:d, a:c] *= k

    def windows(self, x0, y0, x1, y1, cols, rows, glass, frame, gap=0.18, wrap=False):
        """A grid of windows in the box: each cell a pane with a frame round it."""
        for i in range(cols):
            for j in range(rows):
                cx0 = x0 + (x1 - x0) * i / cols
                cy0 = y0 + (y1 - y0) * j / rows
                cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
                self.rect(cx0 + cw * gap / 2, cy0 + ch * gap / 2, cx0 + cw * (1 - gap / 2), cy0 + ch * (1 - gap / 2),
                          frame, wrap)
                self.rect(cx0 + cw * gap, cy0 + ch * gap, cx0 + cw * (1 - gap), cy0 + ch * (1 - gap), glass, wrap)

    def out(self):
        return np.clip(np.round(self.a), 0, 255).astype(np.uint8)


def metro_logo(c, cx, cy, r):
    """The Delhi Metro roundel: a red disc, a white band across it, red again inside the band's middle line."""
    c.disc(cx, cy, r, (200, 30, 40))
    a, b, _x, _y = c.px(cx, cy, cx, cy)
    t = max(1, int(r * 0.22))
    yy, xx = np.mgrid[0:c.h, 0:c.w]
    inside = np.hypot(xx + 0.5 - a, yy + 0.5 - b) <= r * 0.8
    band = (np.abs(yy + 0.5 - b) <= t) & inside
    c.a[band] = (245, 245, 245)
    c.a[(np.abs(yy + 0.5 - b) <= max(1, t // 3)) & inside] = (200, 30, 40)


# --- the stations ---

def stn_neelam(w, h, seed, north=False):
    """Neelam Chowk Ajronda's ends (photos 35 and 33): brown-beige horizontal slats over the whole face, a white
    "Lakhani SHOES" plaque high up, the station's name in Hindi (dark blue, two lines), the metro roundel, and the
    English name in two lines below; a dark band at the concourse's foot."""
    c = Canvas(w, h, (128, 104, 80), seed)
    for k in range(0, h, 6):  # slats: light board, dark gap (6 px: no moire at a distance)
        y = k / h
        c.rect(0, y, 1, y + 2.0 / h, (92, 72, 54))
        c.rect(0, y + 2.0 / h, 1, y + 6.0 / h, (138 + (k * 7) % 11, 112 + (k * 5) % 9, 86))
    c.grain(5)
    c.rect(0.0, 0.0, 1.0, 0.03, (70, 70, 72))
    c.rect(0.0, 0.94, 1.0, 1.0, (64, 62, 60))
    # Run J, item 2 (tools/citymap/station_letters.py): the lettering under the deck, the names raised (geometry; here
    # their shadows), the plaque beside them
    pu0, pv0, pu1, pv1 = station_letters.NEELAM_PLAQUE[north]
    c.rect(pu0, pv0, pu1, pv1, (236, 236, 232))
    c.frame(pu0, pv0, pu1, pv1, (40, 50, 110), 2)
    metro_logo(c, (pu0 + pu1) / 2, 0.83 if north else 0.865, w * (0.02 if north else 0.03))
    if north:  # the north end (photo 33): the green direction board at the right of its foot
        c.rect(0.83, 0.86, 0.97, 0.92, (30, 110, 70))
        c.frame(0.83, 0.86, 0.97, 0.92, (230, 230, 226), 1)
    station_letters.paint(c, "FTL_STN_NEELAM_N" if north else "FTL_STN_NEELAM_S")
    return c.out()


def stn_bata_n(w, h, seed):
    """Bata Chowk's north end (photo 41): an orange frame and columns, a navy "KARIGARI" board on the left above a row
    of arched windows, and the sign band: IndianOil in Hindi and English with its roundel, the metro roundel, "बाटा
    चौक" and "BATA CHOWK" in white on blue."""
    c = Canvas(w, h, (214, 92, 40), seed)
    c.rect(0, 0, 1, 0.06, (40, 60, 120))
    # windows: arched tops over a dark grid
    c.rect(0.06, 0.20, 0.94, 0.58, (60, 66, 70))
    for k in range(10):
        x0 = 0.07 + 0.087 * k
        c.rect(x0, 0.24, x0 + 0.075, 0.56, (110, 126, 136))
        c.rect(x0 + 0.036, 0.24, x0 + 0.04, 0.56, (60, 66, 70))
        c.rect(x0, 0.39, x0 + 0.075, 0.41, (60, 66, 70))
    # Run J, item 2 (tools/citymap/station_letters.py): the board and the sign band's lettering right of u 0.44,
    # where neither the deck nor a pier hides them from the road; the names raised (geometry; here their shadows)
    b0, b1, b2, b3 = station_letters.BATA_BOARD
    c.rect(b0, b1, b2, b3, (34, 44, 92))
    # the sign band
    c.rect(0.0, 0.62, 1.0, 0.86, (34, 52, 120))
    c.rect(0.0, 0.62, 1.0, 0.635, (226, 226, 222))
    c.rect(0.0, 0.845, 1.0, 0.86, (226, 226, 222))
    c.disc(0.46, 0.74, h * 0.085, (236, 110, 30))
    c.disc(0.46, 0.74, h * 0.05, (40, 60, 140))
    metro_logo(c, 0.70, 0.74, h * 0.08)
    station_letters.paint(c, "FTL_STN_BATA_N")
    # the orange columns below
    c.rect(0, 0.86, 1, 1, (70, 70, 74))
    for x in (0.0, 0.32, 0.64, 0.96):
        c.rect(x, 0.86, x + 0.05, 1.0, (214, 92, 40))
    c.grain(3)
    return c.out()


def stn_bata_w(w, h, seed):
    """Bata Chowk's side (photo 38), seamless every 36 m: the blue roof edge, a white panel band with green leaf
    marks and "WISH YOU A SAFE AND POLLUTION FREE DRIVING EXPERIENCE", orange swoosh bands, blue glazing."""
    c = Canvas(w, h, (226, 228, 230), seed)
    c.rect(0, 0, 1, 0.12, (40, 96, 190))
    c.rect(0, 0.12, 1, 0.15, (20, 50, 120))
    c.rect(0, 0.18, 1, 0.45, (238, 238, 236))
    for x in (0.03, 0.53):
        for k, dy in enumerate((0.0, 0.05, 0.10)):
            c.disc(x + 0.03 + 0.015 * k, 0.26 + dy, h * 0.035, (60, 150, 70))
    station_letters.paint(c, "FTL_STN_BATA_W")
    c.rect(0, 0.46, 1, 0.52, (236, 120, 30))
    yy, xx = np.mgrid[0:h, 0:w]
    sw = (np.abs(yy / h - (0.58 + 0.06 * np.sin(2 * np.pi * xx / w * 2))) < 0.035)
    c.a[sw] = (244, 160, 40)
    c.rect(0, 0.66, 1, 0.90, (50, 100, 170))
    for k in range(24):
        c.rect(k / 24.0, 0.66, k / 24.0 + 0.004, 0.90, (200, 204, 210))
    c.rect(0, 0.90, 1, 1, (236, 120, 30))
    c.grain(3)
    return c.out()


def stn_oldfbd_w(w, h, seed):
    """Old Faridabad's west side (photo 53), seamless every 24 m: light grey panels with joints above, the white sign
    box "ओल्ड फरीदाबाद (roundel) Old Faridabad" in blue, then the pink-red plastered base with dark openings."""
    c = Canvas(w, h, (196, 196, 194), seed)
    c.rect(0, 0, 1, 0.05, (40, 96, 180))
    for k in range(16):
        c.rect(k / 16.0, 0.05, k / 16.0 + 0.003, 0.62, (150, 150, 150))
    for y in (0.20, 0.35, 0.50):
        c.rect(0, y, 1, y + 0.006, (160, 160, 158))
    # (Run J review: the sign within u 0.74, so the last copy on the 138.3 m side, 18.3 m of 24, carries it whole)
    b0, b1, b2, b3 = station_letters.OLDFBD_SIGN
    c.rect(b0, b1, b2, b3, (246, 246, 244))
    c.frame(b0, b1, b2, b3, (120, 120, 124), 2)
    metro_logo(c, (b0 + b2) / 2, 0.34, h * 0.07)
    station_letters.paint(c, "FTL_STN_OLDFBD_W")  # (Run J, item 2: the names raised, geometry; here their shadows)
    c.rect(0, 0.62, 1, 1, (176, 92, 82))
    c.rect(0, 0.62, 1, 0.64, (230, 230, 228))
    for x in (0.06, 0.40, 0.73):
        c.rect(x, 0.74, x + 0.18, 0.96, (60, 56, 56))
        for k in range(6):
            c.rect(x + 0.03 * k, 0.74, x + 0.03 * k + 0.004, 0.96, (120, 116, 112))
    c.grain(3)
    return c.out()


# --- the hospitals ---

def glass_grid(c, x0, y0, x1, y1, cols, rows, base=(70, 98, 116), mull=(170, 176, 180)):
    c.vgrad(x0, y0, x1, y1, tuple(v + 25 for v in base), base)
    for i in range(cols + 1):
        x = x0 + (x1 - x0) * i / cols
        c.rect(x - 0.002, y0, x + 0.002, y1, mull)
    for j in range(rows + 1):
        y = y0 + (y1 - y0) * j / rows
        c.rect(x0, y - 0.004, x1, y + 0.004, mull)


def marengo_front(w, h, seed):
    """Marengo Asia's front (photo 20): grey aluminium panelled blocks either side of a blue-grey glass curtain wall,
    the big arched glass canopy band across the lower storeys, and posters on the boundary at the foot."""
    c = Canvas(w, h, (178, 182, 186), seed)
    for i in range(24):
        c.rect(i / 24.0, 0, i / 24.0 + 0.002, 1, (150, 154, 158))
    for j in range(12):
        c.rect(0, j / 12.0, 1, j / 12.0 + 0.004, (156, 160, 164))
    glass_grid(c, 0.30, 0.06, 0.70, 0.62, 12, 6)
    glass_grid(c, 0.02, 0.10, 0.20, 0.50, 4, 4)
    glass_grid(c, 0.80, 0.10, 0.98, 0.50, 4, 4)
    yy, xx = np.mgrid[0:h, 0:w]
    u, v = xx / w, yy / h
    arch = np.abs((u - 0.5) / 0.42) ** 2 + ((v - 0.86) / 0.32) ** 2
    c.a[(arch < 1.0) & (arch > 0.82) & (v < 0.86)] = (210, 214, 218)
    for k in range(18):
        a = np.pi * k / 17
        x, y = 0.5 - 0.40 * np.cos(a), 0.86 - 0.30 * np.sin(a)
        c.rect(x - 0.003, y - 0.03, x + 0.003, y, (120, 124, 128))
    c.rect(0, 0.86, 1, 1, (120, 116, 108))
    for x, col in ((0.08, (220, 220, 214)), (0.22, (236, 236, 230)), (0.78, (230, 226, 220))):
        c.rect(x, 0.88, x + 0.10, 0.97, col)
        c.rect(x + 0.01, 0.90, x + 0.04, 0.95, (180, 40, 50))
    c.text("NEUROSURGERY", 0.225, 0.905, 0.315, 0.935, (40, 60, 130), "Arial", 700)
    c.grain(3)
    return c.out()


def marengo_sign(w, h, seed):
    """Marengo Asia's rooftop sign (photo 20): "Marengo Asia Hospitals" in blue with its round mark, on light grey."""
    c = Canvas(w, h, (206, 210, 214), seed)
    c.disc(0.06, 0.5, h * 0.36, (40, 70, 160))
    c.disc(0.06, 0.5, h * 0.22, (206, 210, 214))
    c.rect(0.055, 0.2, 0.065, 0.8, (40, 70, 160))
    c.text("Marengo Asia Hospitals", 0.12, 0.12, 0.98, 0.88, (40, 64, 150), "Arial", 700)
    c.grain(2)
    return c.out()


def fortis_logo(c, cx, cy, size_px):
    """Fortis' green figure (size_px tall, centred at (cx, cy) fractions): a head over a stem, two arms raised in a V
    from the stem's top."""
    g = (40, 140, 70)
    x, y = cx * c.w, cy * c.h
    s = size_px
    yy, xx = np.mgrid[0:c.h, 0:c.w] + 0.5
    c.a[np.hypot(xx - x, yy - (y - 0.36 * s)) <= 0.13 * s] = g
    c.a[(np.abs(xx - x) <= 0.06 * s) & (yy >= y - 0.18 * s) & (yy <= y + 0.5 * s)] = g
    for sg in (-1, 1):  # the arms: from (x, y - 0.1 s) out and up to (x +- 0.3 s, y - 0.32 s)
        t = np.clip((xx - x) * sg / (0.3 * s), 0, 1)
        on = ((xx - x) * sg >= 0) & ((xx - x) * sg <= 0.3 * s) & (np.abs(yy - (y - 0.1 * s - 0.22 * s * t)) <= 0.05 * s)
        c.a[on] = g


def fortis_front(w, h, seed):
    """Fortis Escorts' front block (photo 50): white-grey cladding, a long glass band with green tints, the green
    "Fortis Escorts" sign high on the right, "SRL" in blue below it, posters at the left."""
    c = Canvas(w, h, (214, 216, 214), seed)
    c.rect(0, 0.0, 1, 0.08, (190, 192, 190))
    glass_grid(c, 0.05, 0.38, 0.95, 0.70, 18, 2, base=(70, 120, 120), mull=(190, 196, 194))
    fortis_logo(c, 0.585, 0.19, h * 0.17)
    c.text("Fortis Escorts", 0.61, 0.10, 0.96, 0.28, (40, 140, 70), "Georgia", 700)
    c.text("SRL", 0.80, 0.29, 0.94, 0.37, (40, 70, 160), "Arial", 700)
    for k, col in enumerate(((230, 200, 160), (200, 220, 240), (240, 230, 200))):
        x = 0.06 + 0.13 * k
        c.rect(x, 0.12, x + 0.11, 0.33, col)
        c.disc(x + 0.055, 0.22, h * 0.05, (200, 120, 90))
    c.rect(0, 0.70, 1, 0.74, (40, 140, 70))
    c.rect(0, 0.74, 1, 1, (176, 178, 176))
    c.rect(0.10, 0.80, 0.30, 0.98, (90, 96, 100))
    c.grain(3)
    return c.out()


def fortis_sign(w, h, seed):
    """Fortis Escorts' rooftop sign (photo 24): the green figure and "Fortis Escorts" on pale grey."""
    c = Canvas(w, h, (214, 218, 218), seed)
    fortis_logo(c, 0.07, 0.52, h * 0.8)
    c.text("Fortis Escorts", 0.15, 0.10, 0.98, 0.90, (40, 140, 70), "Georgia", 700)
    c.grain(2)
    return c.out()


def aggarwal_front(w, h, seed):
    """Dr. Aggarwal's Eye Hospital (photo 12): deep blue cladding with vertical ribs over the upper storeys, the white
    Hindi name in two lines ("डॉ अग्रवाल्स" large, "आई हॉस्पिटल" below), a light band and the glazed ground floor."""
    c = Canvas(w, h, (36, 56, 160), seed)
    for k in range(40):
        x = k / 40.0
        c.rect(x, 0.04, x + 0.004, 0.70, (24, 40, 120))
    c.rect(0, 0, 1, 0.04, (220, 222, 226))
    c.text("डॉ अग्रवाल्स", 0.22, 0.12, 0.86, 0.38, (245, 245, 245), DEVA, 700)
    c.text("आई हॉस्पिटल", 0.46, 0.40, 0.84, 0.56, (245, 245, 245), DEVA, 700)
    c.rect(0, 0.70, 1, 0.74, (226, 228, 230))
    glass_grid(c, 0.0, 0.74, 1.0, 1.0, 14, 1, base=(64, 90, 106), mull=(200, 204, 208))
    c.grain(3)
    return c.out()


def gym_front(w, h, seed):
    """The Everyday Fitness and AU Small Finance Bank building (photo 15): a dark glass curtain wall over the upper
    storeys with "EVERYDAY FITNESS" in big white letters, a dark yellow round mark, the maroon AU band with the orange
    AU disc and its name, and the shop level with shutters and AC units."""
    c = Canvas(w, h, (150, 154, 160), seed)
    glass_grid(c, 0.0, 0.0, 1.0, 0.56, 16, 4, base=(46, 62, 76), mull=(120, 126, 132))
    c.rect(0.06, 0.20, 0.96, 0.36, (40, 44, 50))
    c.text("EVERYDAY FITNESS", 0.16, 0.21, 0.94, 0.35, (245, 245, 240), "Impact", 400, stretch=True)
    c.disc(0.10, 0.28, h * 0.07, (220, 180, 40))
    c.disc(0.10, 0.28, h * 0.045, (40, 44, 50))
    c.rect(0.0, 0.58, 1.0, 0.70, (150, 60, 80))
    c.disc(0.36, 0.64, h * 0.05, (236, 120, 40))
    c.text("AU", 0.34, 0.615, 0.38, 0.665, (255, 255, 255), "Arial", 700)
    c.text("AU SMALL FINANCE BANK", 0.40, 0.60, 0.80, 0.68, (245, 240, 240), "Arial", 700)
    c.rect(0, 0.70, 1, 1, (184, 160, 150))
    for k in range(7):
        x = 0.02 + 0.14 * k
        c.rect(x, 0.74, x + 0.11, 0.98, (130, 132, 134))
        for j in range(12):
            c.rect(x, 0.74 + 0.02 * j, x + 0.11, 0.745 + 0.02 * j, (110, 112, 114))
    for k in range(5):
        c.rect(0.05 + 0.18 * k, 0.715, 0.09 + 0.18 * k, 0.735, (230, 230, 228))
    c.grain(3)
    return c.out()


# --- the market ---

def board(c, x0, y0, x1, y1, bg, s, fg, font="Arial", weight=700, italic=False):
    c.rect(x0, y0, x1, y1, bg)
    c.frame(x0, y0, x1, y1, tuple(v * 0.7 for v in bg), 1)
    c.text(s, x0 + 0.01, y0 + (y1 - y0) * 0.15, x1 - 0.01, y1 - (y1 - y0) * 0.15, fg, font, weight, italic)


def mkt_bata_front(w, h, seed):
    """Dwarka Complex in Sector 16 Market (photo 02): a four-storey row of offices and shops covered in signboards, as
    on the photo: insurance and finance boards up top, "Muthoot Finance", "airtel", "BAJAJ Allianz", "OPPO", the red
    "Bata" boards with "Sale 70%", "SAMSUNG", "vivo" and "fabindia" over the shop fronts."""
    c = Canvas(w, h, (196, 176, 150), seed)
    c.rect(0, 0, 1, 0.05, (170, 150, 128))
    for j, y in enumerate((0.07, 0.30)):  # office storeys: windows between boards
        for k in range(8):
            x = 0.02 + 0.122 * k
            c.rect(x, y + 0.06, x + 0.09, y + 0.20, (70, 76, 84))
            c.rect(x + 0.044, y + 0.06, x + 0.047, y + 0.20, (170, 160, 150))
    board(c, 0.02, 0.06, 0.24, 0.12, (236, 236, 236), "CASH HOME LOANS", (200, 30, 30))
    board(c, 0.66, 0.06, 0.98, 0.14, (240, 236, 230), "INSURANCE ADVISOR", (180, 40, 40))
    board(c, 0.26, 0.10, 0.44, 0.16, (250, 230, 120), "COACHING", (40, 40, 40))
    board(c, 0.02, 0.29, 0.30, 0.36, (200, 30, 30), "Muthoot Finance", (255, 255, 255), "Georgia")
    board(c, 0.32, 0.29, 0.52, 0.36, (220, 30, 40), "airtel", (255, 255, 255))
    board(c, 0.54, 0.29, 0.98, 0.36, (40, 70, 150), "BAJAJ Allianz", (255, 255, 255))
    board(c, 0.02, 0.52, 0.22, 0.60, (40, 140, 80), "OPPO", (255, 255, 255))
    board(c, 0.24, 0.52, 0.62, 0.60, (210, 30, 40), "Bata", (255, 255, 255), "Georgia", 700, True)
    board(c, 0.64, 0.52, 0.98, 0.60, (210, 30, 40), "Bata", (255, 255, 255), "Georgia", 700, True)
    board(c, 0.02, 0.61, 0.22, 0.68, (36, 70, 170), "vivo", (255, 255, 255))
    board(c, 0.24, 0.61, 0.44, 0.68, (236, 230, 220), "Sale 70%", (200, 30, 40))
    board(c, 0.46, 0.61, 0.74, 0.68, (240, 240, 244), "SAMSUNG", (20, 40, 140))
    board(c, 0.76, 0.61, 0.98, 0.68, (36, 70, 150), "Smart Cafe", (255, 255, 255))
    board(c, 0.10, 0.70, 0.48, 0.76, (120, 60, 40), "fabindia", (245, 236, 220), "Georgia")
    board(c, 0.52, 0.70, 0.90, 0.76, (120, 60, 40), "fabindia", (245, 236, 220), "Georgia")
    c.rect(0, 0.77, 1, 1, (60, 58, 56))  # the shop level: goods and lit counters
    for k in range(10):
        x = 0.01 + 0.1 * k
        c.rect(x, 0.80, x + 0.08, 0.98, ((150, 120, 90), (90, 110, 140), (170, 150, 110))[k % 3])
        c.rect(x, 0.80, x + 0.08, 0.82, (230, 220, 190))
    c.grain(3)
    return c.out()


def mkt_lic_front(w, h, seed):
    """The LIC and Sardar block (photo 07), seamless every 14 m: office boards stacked on a plastered three-storey
    front ("RAGHUNATH Builders • Promoters", "S K S D & ASSOCIATES", "V.D. CONSULTANTS", "PMSS & CO."), the yellow
    "LIC" board and the red "SARDAR A PURE MEAT SHOP" board over the shutters."""
    c = Canvas(w, h, (206, 190, 160), seed)
    c.rect(0, 0, 1, 0.04, (176, 160, 136))
    c.rect(0.04, 0.06, 0.60, 0.26, (120, 130, 140))
    for k in range(5):
        c.rect(0.04 + 0.112 * k, 0.06, 0.044 + 0.112 * k, 0.26, (210, 210, 210))
    board(c, 0.64, 0.08, 0.98, 0.20, (230, 226, 216), "RAGHUNATH", (180, 40, 40))
    c.text("Builders • Promoters", 0.65, 0.20, 0.97, 0.25, (180, 40, 40), "Arial", 700)
    board(c, 0.02, 0.32, 0.36, 0.40, (40, 50, 110), "S K S D & ASSOCIATES", (255, 255, 255))
    board(c, 0.38, 0.32, 0.68, 0.40, (40, 50, 110), "V.D. CONSULTANTS", (255, 255, 255))
    board(c, 0.70, 0.32, 0.98, 0.40, (230, 230, 228), "PMSS & CO.", (30, 40, 120))
    board(c, 0.02, 0.42, 0.48, 0.50, (40, 100, 160), "AK PHOTO GALLERY", (255, 255, 255))
    board(c, 0.50, 0.42, 0.98, 0.50, (240, 240, 236), "HEALTHCARE", (30, 90, 160))
    board(c, 0.02, 0.56, 0.48, 0.68, (200, 30, 40), "SARDAR", (255, 255, 255), "Georgia", 700, True)
    c.text("A PURE MEAT SHOP", 0.04, 0.665, 0.46, 0.70, (200, 30, 40), "Arial", 700)
    board(c, 0.52, 0.56, 0.98, 0.68, (240, 200, 40), "LIC", (30, 50, 140))
    c.text("भारतीय जीवन बीमा निगम", 0.54, 0.665, 0.96, 0.70, (30, 50, 140), DEVA, 700)
    c.rect(0, 0.72, 1, 1, (90, 88, 86))
    for x in (0.02, 0.52):
        c.rect(x, 0.74, x + 0.46, 0.99, (140, 140, 138))
        for j in range(13):
            c.rect(x, 0.74 + 0.019 * j, x + 0.46, 0.745 + 0.019 * j, (116, 116, 114))
    c.grain(3)
    return c.out()


def mkt_ashoka_front(w, h, seed):
    """Ashoka Sweets and Restaurant (photo 10): a red frame round a white facade with "Ashoka" in red script and
    "SWEETS & RESTAURANT" below, a red-and-white awning and the sweet counters under it."""
    c = Canvas(w, h, (200, 40, 40), seed)
    c.rect(0.06, 0.06, 0.94, 0.60, (236, 234, 230))
    c.text("Ashoka", 0.16, 0.12, 0.84, 0.38, (200, 30, 40), "Segoe Script", 700)
    c.text("SWEETS & RESTAURANT", 0.10, 0.42, 0.90, 0.54, (200, 30, 40), "Arial", 700)
    c.rect(0, 0.62, 1, 0.70, (230, 230, 226))
    for k in range(12):
        if k % 2 == 0:
            c.rect(k / 12.0, 0.62, (k + 1) / 12.0, 0.70, (200, 40, 40))
    c.rect(0, 0.70, 1, 1, (80, 60, 50))
    c.rect(0.08, 0.76, 0.46, 0.96, (210, 200, 170))
    c.rect(0.54, 0.76, 0.92, 0.96, (210, 200, 170))
    for x in (0.10, 0.20, 0.30, 0.56, 0.66, 0.76):
        c.rect(x, 0.80, x + 0.07, 0.84, (230, 160, 60))
    c.grain(3)
    return c.out()


def pacific_front(w, h, seed):
    """Pacific Mall's east front (photo 43): a cream panel with "PACIFIC" in dark serif capitals over a grey glazed
    block with vertical fins, the "SHOPPERS STOP" board on the right and shop signs at the foot."""
    c = Canvas(w, h, (150, 152, 154), seed)
    c.rect(0.18, 0.00, 0.62, 0.42, (222, 212, 180))
    c.text("PACIFIC", 0.22, 0.08, 0.58, 0.34, (40, 40, 44), "Georgia", 400)
    for k in range(30):
        x = k / 30.0
        if not 0.18 <= x <= 0.62:
            c.rect(x, 0.10, x + 0.004, 0.70, (120, 122, 126))
    c.rect(0, 0.42, 1, 0.74, (100, 108, 116))
    for k in range(40):
        c.rect(k / 40.0, 0.42, k / 40.0 + 0.003, 0.74, (170, 172, 176))
    board(c, 0.66, 0.30, 0.86, 0.46, (40, 40, 44), "SHOPPERS STOP", (240, 240, 240), "Georgia")
    c.rect(0, 0.74, 1, 1, (200, 200, 196))
    board(c, 0.62, 0.78, 0.74, 0.88, (240, 240, 240), "AZORTE", (40, 40, 40))
    board(c, 0.76, 0.78, 0.90, 0.88, (240, 240, 240), "trends", (200, 40, 40))
    c.grain(2)
    return c.out()


def mural(w, h, seed):
    """The Neelam-Mathura flyover's mural "dedicated to the Armed Forces" (photo 36), seamless every 24 m: a sky and
    sea in blues, rolling waves, a grey warship, a jet and a helicopter in the sky, a soldier's figure; a white band
    and a dark kerb at the foot."""
    c = Canvas(w, h, (120, 170, 210), seed)
    c.vgrad(0, 0, 1, 0.55, (150, 196, 228), (90, 150, 200))
    c.vgrad(0, 0.55, 1, 0.92, (40, 110, 170), (20, 70, 130))
    yy, xx = np.mgrid[0:h, 0:w]
    for k, (amp, y0, col) in enumerate(((0.03, 0.62, (210, 230, 240)), (0.025, 0.74, (120, 180, 220)),
                                        (0.02, 0.84, (200, 226, 240)))):
        crest = y0 + amp * np.sin(2 * np.pi * (xx / w * (3 + k) + 0.2 * k))
        c.a[np.abs(yy / h - crest) < 0.012] = col
    # the warship (left half): hull, deck, superstructure, mast
    c.rect(0.08, 0.46, 0.36, 0.56, (90, 96, 104))
    c.rect(0.10, 0.40, 0.30, 0.46, (110, 116, 124))
    c.rect(0.16, 0.30, 0.24, 0.40, (120, 126, 132))
    c.rect(0.195, 0.16, 0.205, 0.30, (80, 84, 90))
    c.rect(0.08, 0.53, 0.36, 0.56, (60, 64, 70))
    # the jet (right half) and its trail
    c.rect(0.58, 0.12, 0.70, 0.15, (220, 222, 226))
    c.rect(0.63, 0.08, 0.66, 0.19, (200, 204, 210))
    c.rect(0.50, 0.125, 0.58, 0.135, (236, 240, 244))
    # the helicopter
    c.rect(0.78, 0.30, 0.86, 0.36, (60, 90, 70))
    c.rect(0.86, 0.32, 0.93, 0.335, (60, 90, 70))
    c.rect(0.74, 0.28, 0.90, 0.29, (40, 40, 40))
    # the soldier: helmet, face, uniform
    c.rect(0.44, 0.34, 0.50, 0.56, (90, 110, 70))
    c.disc(0.47, 0.30, h * 0.05, (200, 160, 120))
    c.rect(0.435, 0.22, 0.505, 0.27, (70, 90, 60))
    c.rect(0, 0.92, 1, 0.96, (236, 236, 236))
    c.rect(0, 0.96, 1, 1, (60, 60, 62))
    c.grain(3)
    return c.out()


def sign_16a(w, h, seed):
    """The Sector 16A direction sign (photo 32): a green board with a white border, a left chevron, "सेक्टर 16 ए"
    over "Sector 16 A" in white."""
    c = Canvas(w, h, (24, 110, 64), seed)
    c.frame(0.03, 0.06, 0.97, 0.94, (240, 240, 236), 2)
    yy, xx = np.mgrid[0:h, 0:w]
    u, v = xx / w, yy / h
    chev = (np.abs(v - 0.5) * (h / w) * 1.0 + 0.05 - (u - 0.08)) < 0.0
    chev &= ~((np.abs(v - 0.5) * (h / w) + 0.10 - (u - 0.08)) < 0.0) & (u < 0.25) & (np.abs(v - 0.5) < 0.32)
    c.a[chev] = (240, 240, 236)
    c.text("सेक्टर 16 ए", 0.26, 0.14, 0.94, 0.50, (245, 245, 240), DEVA, 700)
    c.text("Sector 16 A", 0.26, 0.54, 0.94, 0.86, (245, 245, 240), "Arial", 700)
    c.grain(2)
    return c.out()


PAINTERS = {
    "FTL_STN_NEELAM_S": lambda w, h, s: stn_neelam(w, h, s),
    "FTL_STN_NEELAM_N": lambda w, h, s: stn_neelam(w, h, s, north=True),
    "FTL_STN_BATA_N": stn_bata_n,
    "FTL_STN_BATA_W": stn_bata_w,
    "FTL_STN_OLDFBD_W": stn_oldfbd_w,
    "FTL_MARENGO_FRONT": marengo_front,
    "FTL_MARENGO_SIGN": marengo_sign,
    "FTL_FORTIS_FRONT": fortis_front,
    "FTL_FORTIS_SIGN": fortis_sign,
    "FTL_AGGARWAL_FRONT": aggarwal_front,
    "FTL_GYM_FRONT": gym_front,
    "FTL_MKT_BATA_FRONT": mkt_bata_front,
    "FTL_MKT_LIC_FRONT": mkt_lic_front,
    "FTL_MKT_ASHOKA_FRONT": mkt_ashoka_front,
    "FTL_PACIFIC_FRONT": pacific_front,
    "FTL_MURAL": mural,
    "FTL_SIGN_16A": sign_16a,
}


def colour_range(img):
    """Our drawn face brought into the colour range the city's textures keep (Rockport's walls; notes "City fixes"
    3): mean luminance into 72-92 by one scale, mean chroma at most 44 by mixing towards grey (phototex's rule,
    applied to our own pixels)."""
    from tools.citymap import phototex
    out, _before, _after = phototex.colour_match(img)
    return out


def draw_all(reg=None):
    """{texture name: (w, h, uint8 (h, w, 3))} for every face texture of the registry, at its size."""
    from tools.citymap import landmarks, phototex
    reg = reg or landmarks.read()
    out = {}
    for k, (name, f) in enumerate(sorted(phototex.faces(reg), key=lambda nf: nf[0])):
        w, h = f["tex"]
        seed = sum(ord(ch) for ch in name) * 7919
        img = colour_range(PAINTERS[name](w, h, seed))
        out[name] = (w, h, img)
    return out


def save(out_dir=OUT):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, (_w, _h, img) in draw_all().items():
        p = os.path.join(out_dir, name.lower() + ".png")
        Image.fromarray(img).save(p, optimize=False)
        paths.append(p)
    return paths


if __name__ == "__main__":
    print("\n".join(save(sys.argv[1] if len(sys.argv) > 1 else OUT)))
