"""Our parked vehicles drawn beside the user's photos (street life Task 2; the output is git-ignored: it holds the
photos).

    .tools/cityenv/Scripts/python tools/citymap/render_vehicles.py [out.png]

A three-quarter view of every vehicle in two of its colours (painter's order, flat shading by a fixed sun, back faces
left out as the game does), then photos 18, 12, 22 and 11 (auto and scooter, e-rickshaw, parked cars) scaled down.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.citymap import vehicles  # noqa: E402

OUT = os.path.join(REPO, ".superpowers", "citymap", "faridabad", "streetlife", "vehicles.png")
PHOTOS = os.path.join(REPO, "ftownphotos")
SUN = np.array([0.45, -0.55, 0.70]) / np.linalg.norm([0.45, -0.55, 0.70])


def draw_model(tris, size=260, yaw=35.0, pitch=18.0, scale=55.0):
    img = Image.new("RGB", (size, size), (200, 205, 210))
    d = ImageDraw.Draw(img)
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    view = np.array([cy * cp, sy * cp, sp])  # towards the camera
    items = []
    for t, cell in tris:
        p = np.array(t, float)
        n = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n /= ln
        if np.dot(n, view) <= 0:
            continue  # back face: the game leaves it out
        # camera axes: right r, up u
        r = np.array([-sy, cy, 0.0])
        u = np.cross(view, r)
        pts = [(size / 2 + scale * np.dot(q, r), size * 0.65 - scale * np.dot(q, u)) for q in p]
        depth = float(np.mean(p @ view))
        shade = 0.55 + 0.45 * max(0.0, float(np.dot(n, SUN)))
        col = tuple(int(min(255, c * shade * 1.25)) for c in vehicles.PALETTE[cell])
        items.append((depth, pts, col))
    for _dpt, pts, col in sorted(items, key=lambda it: it[0]):
        d.polygon(pts, fill=col)
    return img


def main(argv):
    out = argv[0] if argv else OUT
    tiles = []
    for kind in vehicles.KINDS:
        for v in (0, 1):
            L = vehicles.REAL[kind][0]
            tiles.append(draw_model(vehicles.model(kind, v), scale=220.0 / max(2.2, L)))
    w = 260 * 6
    sheet = Image.new("RGB", (w, 260 * 2 + 420), (40, 40, 40))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k // 2) * 260, (k % 2) * 260))
    if os.path.isdir(PHOTOS):
        names = sorted(os.listdir(PHOTOS))
        x = 0
        for n in (18, 12, 22, 11):
            ph = Image.open(os.path.join(PHOTOS, names[n - 1])).convert("RGB")
            ph = ph.resize((int(ph.size[0] * 420 / ph.size[1]), 420))
            sheet.paste(ph, (x, 520))
            x += ph.size[0] + 10
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sheet.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
