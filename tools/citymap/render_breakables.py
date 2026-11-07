"""A map of F-Town's breakable poles by kind (docs/ftown-notes.md "Breakable poles (2026-11-05)").

    .tools/cityenv/Scripts/python tools/citymap/render_breakables.py [<ftown-smackables.bun> [<out.png>]]

Reads the spawner file (each record's position, and its volume: the kind) and the roads of the OSM model; writes
.superpowers/citymap/breakables/poles-map.png (git-ignored): roads grey, poles as dots coloured by kind, each record's
arm direction (X0's poles reach along their model's -y) as a short line, a legend with the counts.
"""
import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild"), os.path.join(REPO, "tools", "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import breakables, geo, roadmodel  # noqa: E402
from world import smackables  # noqa: E402
from world.collision import to_render  # noqa: E402

COLOURS = {"light_c": (31, 119, 180), "light_cb": (214, 39, 40), "signal_a": (148, 103, 189),
           "signal_b": (255, 127, 14), "lantern": (44, 160, 44)}
NAMES = {"light_c": "XO_StreetLightC (main roads' medians)", "light_cb": "XO_StreetLightCb (Mathura Road)",
         "signal_a": "XO_TrafficLightA", "signal_b": "XO_TrafficLightB (signals)", "lantern": "our lantern lamp"}
SCALE = 0.5  # px a metre


def main(argv):
    smk = argv[0] if argv else os.path.join(REPO, "ftown", "ftown-smackables.bun")
    out = argv[1] if len(argv) > 1 else os.path.join(REPO, ".superpowers", "citymap", "breakables", "poles-map.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(smk, "rb") as f:
        _base, _entries, packs = smackables.read_file(f.read())
    by_volume = {breakables.volume(r): r for r in breakables.ROLES}
    pts = collections.defaultdict(list)
    for _s, _f, recs in packs:
        for r in recs:
            p = to_render(r["pos"])
            h = -2.0 * math.atan2(r["q"][1], r["q"][3])
            pts[by_volume[r["collision"]]].append((p[0], p[1], h))
    with open(os.path.join(REPO, ".superpowers", "citymap", "faridabad", "osm.json"), encoding="utf-8") as f:
        osm = json.load(f)
    model = roadmodel.build(osm, geo.Projection())
    xs = [x for r in model.roads for x, _y in r.points]
    ys = [y for r in model.roads for _x, y in r.points]
    x0, y1 = min(xs) - 20, max(ys) + 20
    W, H = int((max(xs) - x0 + 20) * SCALE), int((y1 - min(ys) + 20) * SCALE)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def px(x, y):
        return ((x - x0) * SCALE, (y1 - y) * SCALE)

    for r in model.roads:
        d.line([px(*q) for q in r.points], fill=(200, 200, 200), width=max(1, int(r.width_m * SCALE)))
    for role, ps in pts.items():
        for x, y, h in ps:
            cx, cy = px(x, y)
            if role != "lantern":
                ax, ay = px(x + 6.0 * math.sin(h), y - 6.0 * math.cos(h))
                d.line([(cx, cy), (ax, ay)], fill=COLOURS[role], width=1)
            d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=COLOURS[role])
    y = 10
    for role in sorted(pts):
        d.rectangle([10, y, 22, y + 12], fill=COLOURS[role])
        d.text((28, y), "%s: %d" % (NAMES[role], len(pts[role])), fill=(0, 0, 0))
        y += 18
    img.save(out)
    print(out, {k: len(v) for k, v in pts.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
