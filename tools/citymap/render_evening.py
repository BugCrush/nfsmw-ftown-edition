"""Day and evening renders of F-Town (docs/ftown-notes.md "Evening (2026-11-05)"): the same eyes in the city as written
(the day) and in the city with ftown-evening.bin applied (what FTownLoader loads for F-Town (Evening)), each lit with
the game's world shader formula (vs 7a500353 / ps b4c51ce5): (vertex colour x ambient x 4 + N.L x diffuse) x
texture, with the pack's database values: by day `sunny` (ambient 0.19, 0.24, 0.32; diffuse 0.60, 0.48, 0.22) and the
sun at time 0.6 (the dissected frame's light direction), in the evening `dusk_sunny` (ambient 0.15, 0.19, 0.36; diffuse
0.73, 0.48, 0.05) and the sun at time 0.95. No shadows, no bloom, no colour grade: an approximation for the eye, not
the game's picture. The renders stay under .superpowers/ (git-ignored).

    .tools/cityenv/Scripts/python tools/citymap/render_evening.py <city.bun> <ftown-evening.bin> <out dir>
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import evening, render_tex, terrain  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
LIGHT = {
    "day": {"amb": (0.19, 0.24, 0.32), "dif": (0.60, 0.48, 0.22), "sun": (-0.35, -0.47, 0.80),
            "sky": (150, 185, 220)},
    "evening": {"amb": (0.15, 0.19, 0.36), "dif": (0.73, 0.48, 0.05), "sun": (-0.969, -0.206, 0.135),
                "sky": (196, 150, 118)},
}
EYES = [("Sector 16 Market's inner road", 2095.0, 12500.0, 45.0, 0.0),
        ("Neelam Chowk (Mathura Road, the metro)", 1372.0, 10820.0, 90.0, 4.0),
        ("Bata Chowk, north up Mathura Road", 1470.0, 9560.0, 90.0, 4.0),
        ("Old Faridabad station", 1279.0, 12300.0, 72.0, 6.0),
        ("Marengo Asia, south over the city", 2070.0, 13000.0, -90.0, 0.0)]


def light(scene, which):
    """Per-triangle multipliers of the texture (render_tex's rgb) for the game's formula under LIGHT[which]."""
    L = LIGHT[which]
    c = scene.C
    vc = np.stack([(c >> 16) & 255, (c >> 8) & 255, c & 255], -1).astype(float) / 255.0
    n = scene.normal / np.maximum(np.linalg.norm(scene.normal, axis=1, keepdims=True), 1e-9)
    s = np.array(L["sun"], dtype=float)
    s /= np.linalg.norm(s)
    ndl = np.clip(n @ s, 0.0, 1.0)[:, None]
    return vc * np.array(L["amb"]) * 4.0 + ndl * np.array(L["dif"])


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    city, lights_path, out_dir = argv
    os.makedirs(out_dir, exist_ok=True)
    with open(city, "rb") as f:
        data = f.read()
    lit = os.path.join(out_dir, "ftown-city-evening.bun")
    with open(lit, "wb") as f:
        f.write(evening.apply(data, evening.read_lights(lights_path)))
    lib = render_tex.x0_library(GAME) if os.path.isdir(GAME) else None
    scenes = []
    for path, which in ((city, "day"), (lit, "evening")):
        sc = render_tex.Scene(path, "lod", lib)
        sc.rgb = light(sc, which)
        scenes.append((sc, which))
    W, H = 560, 350
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(EYES) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, x, y, hd, pt) in enumerate(EYES):
        top = 6 + r * (H + 24)
        dr.text((10, top), "%s   |   day left (sunny, time 0.6), evening right (dusk_sunny, time 0.95, lights)" % title,
                fill=(255, 255, 255))
        eye = (x, y, terrain.ground_z(x, y) + 1.5)
        for c, (sc, which) in enumerate(scenes):
            render_tex.SKY = np.array(LIGHT[which]["sky"], dtype=float)
            sheet.paste(sc.view(eye, hd, pt, W, H, fov=75.0, far=900.0, cull=True), (10 + c * (W + 10), top + 16))
    out = os.path.join(out_dir, "evening-streets.png")
    sheet.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
