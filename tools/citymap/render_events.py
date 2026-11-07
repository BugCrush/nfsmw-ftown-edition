"""A top view of F-Town's events (ftown/ftown-events.json) over the road model: each route in its colour, its start
(a triangle), checkpoints (bars), speed cameras (squares) and finish (a chequered bar), and the barriers of each
event's file when built (thin lines).

    .tools/cityenv/Scripts/python tools/citymap/render_events.py [out.png]
        (default .superpowers/citymap/faridabad/events-preview.png)
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import events, race_barriers, roadmodel  # noqa: E402

OUT = os.path.join(events.AREA, "events-preview.png")
COLOURS = {"timeattack": (255, 150, 30), "drag": (60, 200, 255), "speedtrap": (255, 60, 200), "sprint": (90, 230, 90)}
SCALE = 0.4  # pixels a metre


def render(out=OUT):
    model = roadmodel.RoadModel.load(events.ROADS)
    evs = events.read()
    box = events._box()
    x0, y0, x1, y1 = box[0] - 40, box[1] - 40, box[2] + 40, box[3] + 40
    img = Image.new("RGB", (int((x1 - x0) * SCALE), int((y1 - y0) * SCALE) + 60), (18, 18, 22))
    g = ImageDraw.Draw(img)

    def P(p):
        return ((p[0] - x0) * SCALE, (y1 - p[1]) * SCALE)

    g.rectangle([P((box[0], box[3])), P((box[2], box[1]))], outline=(90, 90, 90))
    for r in model.roads:
        c = (95, 95, 100) if r.level == 0 else (150, 150, 170)
        g.line([P(p) for p in r.points], fill=c, width=max(1, int(r.width_m * SCALE)))
    for e in evs:
        col = COLOURS.get(e["id"], (255, 255, 255))
        bun = os.path.join(REPO, "ftown", e["barriers"])
        if os.path.exists(bun):
            with open(bun, "rb") as f:
                for a, b, _lo, _hi in race_barriers.read_walls(f.read()):
                    g.line([P(a), P(b)], fill=tuple(v // 2 for v in col), width=1)
        g.line([P(p) for p in e["route"]], fill=col, width=4)
        for gate in e["gates"]:
            h = math.radians(gate["heading"])
            nx, ny = -math.sin(h) * 20, math.cos(h) * 20
            a, b = P((gate["x"] + nx, gate["y"] + ny)), P((gate["x"] - nx, gate["y"] - ny))
            if gate["type"] == "camera":
                q = P((gate["x"], gate["y"]))
                g.rectangle([q[0] - 6, q[1] - 6, q[0] + 6, q[1] + 6], outline=(255, 255, 255), width=2)
            else:
                g.line([a, b], fill=(255, 255, 255) if gate["type"] == "finish" else col, width=5 if gate["type"] == "finish" else 3)
        x, y, _z, hd = e["start"]
        h = math.radians(hd)
        tri = [(x + math.cos(h) * 30, y + math.sin(h) * 30), (x - math.sin(h) * 14, y + math.cos(h) * 14),
               (x + math.sin(h) * 14, y - math.cos(h) * 14)]
        g.polygon([P(p) for p in tri], fill=col)
    y = img.size[1] - 50
    for k, e in enumerate(evs):
        col = COLOURS.get(e["id"], (255, 255, 255))
        g.rectangle([10, y + k * 12, 30, y + k * 12 + 8], fill=col)
        n = sum(1 for q in e["gates"] if q["type"] != "finish")
        g.text((36, y + k * 12 - 2), "%s: %.0f m, %d %s + finish" % (
            e["name"], e["finish_s"] - e["start_s"], n, "cameras" if e["kind"] == "speedtrap" else "checkpoints"),
               fill=(230, 230, 230))
    img.save(out)
    return out


if __name__ == "__main__":
    print(render(*sys.argv[1:]))
