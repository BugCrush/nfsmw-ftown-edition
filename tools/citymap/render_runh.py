"""Before/after renders for Run H's faults (docs/ftown-notes.md "Run H fixes (2026-11-04)"): two city files side by side
from the same eyes, back faces culled as the game culls them (render_tex --cull).

    .tools/cityenv/Scripts/python tools/citymap/render_runh.py <before.bun> <after.bun> <out.png> [--slot N]

Views: Pacific Mall's photo front from 40 m out, the first billboards from the road, a sector street, a median from
the road. The eyes are found in the after file (its photo and billboard faces). The sheet holds photo textures: write
it under .superpowers/ (git-ignored) only.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import render_tex  # noqa: E402


def _eye_before(face_P, face_N, back, up=1.5):
    c = face_P.mean(0)
    n = face_N / np.linalg.norm(face_N[:2])
    eye = (c[0] + n[0] * back, c[1] + n[1] * back, 100.0 + up)
    hd = float(np.degrees(np.arctan2(-n[1], -n[0])))
    pt = float(np.degrees(np.arctan2(c[2] - eye[2], back)))
    return eye, hd, pt


def views(after_path):
    os.environ["FTOWN_CITY"] = after_path
    from tools.citymap.tests import test_runh as T
    w = T.written()
    out = []
    k = np.nonzero(w["tex"] == "FTL_PACIFIC_FRONT")[0]
    if len(k):
        P = w["P"][k].reshape(-1, 3)
        e, hd, pt = _eye_before(P, w["N"][k[0]], 45.0)
        out.append(("Pacific Mall's front (photo 43) from 45 m", e, hd, pt))
    bb = np.nonzero(T._billboard_faces(w))[0]
    if len(bb):
        e, hd, pt = _eye_before(w["P"][bb[0]], w["N"][bb[0]], 18.0)
        out.append(("a billboard from the road, 18 m", e, hd, max(pt, 4.0)))
    out.append(("Mathura Road at Bata Chowk looking north", (1470.0, 9560.0, 101.5), 90.0, 3.0))
    # a planted median's edge from its road, 6 m out, looking along it (the edge found in the after file: a riser on
    # asphalt with grass 0.25 m behind it)
    from vlthash import vlt32
    _w, _i, cen, nxy, _hb, _z0, z1 = T.Platforms()._risers(every=1)
    tops = T.heights().wheel_surfaces(-(cen[:, 1] - nxy[:, 1] * 0.25), cen[:, 0] - nxy[:, 0] * 0.25, z1 + 1.0)
    for c, n, (h, s) in zip(cen, nxy, tops):
        if s == vlt32("grass"):
            eye = (c[0] + n[0] * 6.0, c[1] + n[1] * 6.0, 101.3)
            hd = float(np.degrees(np.arctan2(-n[1], -n[0]))) + 35.0
            out.append(("a planted median from its road (grass top 0.15 m up)", eye, hd, -4.0))
            break
    return out


def main(argv):
    slot = 0
    if "--slot" in argv:
        i = argv.index("--slot")
        slot = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 3:
        print(__doc__)
        return 1
    vs = views(os.path.abspath(argv[1]))
    W, H = 560, 350
    scenes = [render_tex.Scene(argv[0], slot), render_tex.Scene(argv[1], slot)]
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(vs) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, eye, hd, pt) in enumerate(vs):
        y = 6 + r * (H + 24)
        dr.text((10, y), "%s   |   before (run H) left, after right; back faces culled" % title, fill=(255, 255, 255))
        for c, sc in enumerate(scenes):
            sheet.paste(sc.view(eye, hd, pt, W, H, cull=True), (10 + c * (W + 10), y + 16))
    os.makedirs(os.path.dirname(os.path.abspath(argv[2])), exist_ok=True)
    sheet.save(argv[2])
    print(argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
