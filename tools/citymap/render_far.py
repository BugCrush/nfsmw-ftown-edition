"""The long views with the game's detail levels (render_tex.Scene(path, "lod"): slot 0 or 2 per instance by the game's
rule), two city files side by side, back faces culled, 4 km deep (docs/ftown-notes.md "Run H fixes (2026-11-04)",
fault 4: the far level).

    .tools/cityenv/Scripts/python tools/citymap/render_far.py <before.bun> <after.bun> <out.png>

Under .superpowers/ only (the renders hold photo textures).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import build_city, render_tex  # noqa: E402


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    views = [(v["name"] + " (the budget's viewpoint)", (v["x"], v["y"], v["z"] + 0.5), v["heading"], 2.0)
             for v in build_city.VIEWPOINTS if v["name"] in ("Bata Chowk", "Neelam Chowk", "Marengo Asia")]
    W, H = 640, 360
    scenes = [render_tex.Scene(argv[0], "lod"), render_tex.Scene(argv[1], "lod")]
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(views) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, eye, hd, pt) in enumerate(views):
        y = 6 + r * (H + 24)
        dr.text((10, y), "%s   |   run H left, after right; game detail levels, 4 km, 106 deg" % title,
                fill=(255, 255, 255))
        for c, sc in enumerate(scenes):
            sheet.paste(sc.view(eye, hd, pt, W, H, fov=106.0, far=4000.0, cull=True), (10 + c * (W + 10), y + 16))
    os.makedirs(os.path.dirname(os.path.abspath(argv[2])), exist_ok=True)
    sheet.save(argv[2])
    print(argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
