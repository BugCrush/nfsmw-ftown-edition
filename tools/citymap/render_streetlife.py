"""Before/after renders of the street life (docs/ftown-notes.md "Street life (2026-11-04)"): two city files from the
same eyes, the game's detail levels per instance (render_tex "lod"), back faces culled, X0's trees and objects drawn
from the game's own files (read only, render_tex.x0_library: nothing of them is written but the picture, which stays
under .superpowers/, git-ignored).

    .tools/cityenv/Scripts/python tools/citymap/render_streetlife.py <before.bun | -> <after.bun> <out.png>

("-": the after file drawn without its street life's instances, FTS_ and FTV_, as the before.)

Eyes: the two spawns and the five landmark viewpoints (build_city.VIEWPOINTS, 1.5 m up), then the busiest parked row
and the densest park found in the after file.
"""
import collections
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import build_city, render_tex  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")


def eyes(after_path):
    with open(os.path.join(os.path.dirname(os.path.abspath(after_path)), "ftown-city.json")) as f:
        spawns = json.load(f)["spawns"]
    out = [(v["name"], (v["x"], v["y"], 101.5), v["heading"], 0.0) for v in spawns + build_city.VIEWPOINTS]
    os.environ["FTOWN_CITY"] = after_path
    from tools.citymap.tests import test_runh as T
    from tools.citymap.tests import test_streetlife as S
    w = T.written()
    V = w["P"][w["tex"] == "FTC_VEHICLES"].mean(1)
    if len(V):
        cells = collections.Counter((int(x // 20), int(y // 20)) for x, y, _z in V)
        (i, j), _n = cells.most_common(1)[0]
        c = V[(np.floor(V[:, 0] / 20) == i) & (np.floor(V[:, 1] / 20) == j)].mean(0)
        out.append(("the busiest parked row, from 22 m", (c[0] - 16.0, c[1] - 15.0, 101.8), 43.0, -3.0))
    trees = [(x, y) for r, x, y, _z, _s, _i in S.props() if r.startswith("tree")]
    if trees:
        cells = collections.Counter((int(x // 60), int(y // 60)) for x, y in trees)
        (i, j), _n = cells.most_common(1)[0]
        pts = np.array([p for p in trees if int(p[0] // 60) == i and int(p[1] // 60) == j])
        c = pts.mean(0)
        out.append(("the densest trees, from 45 m", (c[0] - 32.0, c[1] - 32.0, 102.0), 45.0, 2.0))
    return out


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    vs = eyes(os.path.abspath(argv[1]))
    lib = render_tex.x0_library(GAME) if os.path.isdir(GAME) else None
    W, H = 560, 350
    # "-": the after file without its street life instances (the tiles are the Run H fixes' own)
    before = render_tex.Scene(argv[1], "lod", lib, skip=("FTS_", "FTV_")) if argv[0] == "-" else \
        render_tex.Scene(argv[0], "lod", lib)
    scenes = [before, render_tex.Scene(argv[1], "lod", lib)]
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(vs) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, eye, hd, pt) in enumerate(vs):
        y = 6 + r * (H + 24)
        dr.text((10, y), "%s   |   before (Run H fixes) left, street life right; the game's detail levels" % title,
                fill=(255, 255, 255))
        for c, sc in enumerate(scenes):
            sheet.paste(sc.view(eye, hd, pt, W, H, fov=75.0, far=700.0, cull=True), (10 + c * (W + 10), y + 16))
    os.makedirs(os.path.dirname(os.path.abspath(argv[2])), exist_ok=True)
    sheet.save(argv[2])
    print(argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
