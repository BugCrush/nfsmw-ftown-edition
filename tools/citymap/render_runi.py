"""Before/after renders of Run I's city fixes (docs/ftown-notes.md "Run I fixes: the city side (2026-11-05)"): run I's
files left, the fixed ones right, drawn from the files themselves (render_tex.Scene, the game's detail levels, back
faces culled, X0's models from the game's files: the street life and the race panels; nothing written anywhere but
the sheets under .superpowers/, git-ignored: they hold Rockport's textures). Lit as render_evening.py does (the world
shader's formula, no shadows, bloom or colour grade).

    .tools/cityenv/Scripts/python tools/citymap/render_runi.py <before dir> <after dir> <out dir>

Each dir holds ftown-city.bun, ftown-evening.bin, ftown-barriers*.bun. Sheets: billboards (day, evening), trees,
markers (a driver's view along the Time Attack and the Speed Trap, a camera gate), ground.
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
from shapely.geometry import LineString  # noqa: E402

from tools.citymap import evening, events, render_evening, render_tex, terrain, textures  # noqa: E402

GAME = render_evening.GAME
W, H = 520, 325
OUTLINE, FILL = 0xA711C606, 0x2C505700  # the panel's neon outline (additive) and striped fill (translucent)


def library():
    sols, tex = render_tex.x0_library(GAME)
    for h in (OUTLINE, FILL):  # drawn alpha-tested here: the outline where it glows, the fill's stripes
        if h in tex:
            t = tex[h].copy()
            lum = t[..., :3].astype(float).mean(-1)
            t[..., 3] = np.where(lum > (60 if h == OUTLINE else 150), 255, 0)
            tex[h] = t
    return sols, tex


def scene(d, lib, which="day", barriers=(), tmp=None):
    city = os.path.join(d, "ftown-city.bun")
    path = city
    if which == "evening":
        with open(city, "rb") as f:
            data = f.read()
        path = os.path.join(tmp or d, "_evening-render-%d.bun" % (abs(hash(os.path.abspath(d))) % 100000))
        with open(path, "wb") as f:
            f.write(evening.apply(data, evening.read_lights(os.path.join(d, "ftown-evening.bin"))))
    sc = render_tex.Scene(path, "lod", lib, extra=tuple(os.path.join(d, b) for b in barriers))
    sc.rgb = render_evening.light(sc, which)
    return sc


def billboard_eyes(sc, n=3, back=16.0):
    """Eyes `back` m in front of n billboards (their design faces: furniture atlas triangles spanning an area)."""
    names = {h: k for k, h in enumerate(sc.tex)}
    from chunks import bstringhash
    fur = names.get(bstringhash(textures.NAMES["furniture"]))
    uv = sc.UV
    a = np.abs((uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1]) - (uv[:, 2, 0] - uv[:, 0, 0]) *
               (uv[:, 1, 1] - uv[:, 0, 1]))
    sel = np.nonzero((sc.T == fur) & (a > 1e-6))[0]
    out, used = [], []
    for k in sel:
        c = sc.centre[k]
        if any(np.hypot(*(c[:2] - u)) < 300 for u in used):
            continue
        nrm = sc.normal[k][:2] / (np.linalg.norm(sc.normal[k][:2]) or 1.0)
        e = c[:2] + nrm * back
        hd = math.degrees(math.atan2(-nrm[1], -nrm[0]))
        out.append(("a billboard from %d m" % back, (e[0], e[1], terrain.ground_z(*e) + 1.6), hd, 7.0))
        used.append(c[:2])
        if len(out) >= n:
            break
    return out


def route_eyes(ev, ss, up=1.3):
    line = LineString(ev["route"])
    out = []
    for s in ss:
        a, b = line.interpolate(s), line.interpolate(s + 3.0)
        hd = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
        out.append(("%s at %d m" % (ev["name"], s), (a.x, a.y, terrain.ground_z(a.x, a.y) + up), hd, -1.0))
    return out


def sheet(rows, scenes, out, title, tag="run I left, fixed right"):
    sh = Image.new("RGB", (2 * W + 30, (H + 24) * len(rows) + 30), (30, 30, 30))
    dr = ImageDraw.Draw(sh)
    dr.text((10, 8), title, fill=(255, 255, 255))
    for r, (label, eye, hd, pt) in enumerate(rows):
        top = 30 + r * (H + 24)
        dr.text((10, top), label + "   |   " + tag, fill=(255, 255, 255))
        for c, (sc, which) in enumerate(scenes):
            render_tex.SKY = np.array(render_evening.LIGHT[which]["sky"], dtype=float)
            sh.paste(sc.view(np.array(eye, float), hd, pt, W, H, fov=75.0, far=700.0, cull=True),
                     (10 + c * (W + 10), top + 16))
    sh.save(out)
    print(out)


def main(argv):
    before, after, out_dir = argv
    os.makedirs(out_dir, exist_ok=True)
    lib = library()
    evs = {e["id"]: e for e in events.read()}
    for which in ("day", "evening"):
        scs = [(scene(d, lib, which, tmp=out_dir), which) for d in (before, after)]
        sheet(billboard_eyes(scs[1][0]), scs, os.path.join(out_dir, "billboards-%s.png" % which),
              "Billboards (item 2), %s" % which)
        if which == "day":
            sheet(route_eyes(evs["timeattack"], (150, 900, 2600)) +
                  [("Sector 16 Market", (2095.0, 12500.0, terrain.ground_z(2095.0, 12500.0) + 1.6), 45.0, -8.0),
                   ("Marengo Asia's front", (2070.0, 13000.0, terrain.ground_z(2070.0, 13000.0) + 1.6), -90.0, -8.0)],
                  scs, os.path.join(out_dir, "trees-ground.png"), "Trees (item 4), ground (item 11), dummy cars (1)")
    for ev, ss in ((evs["timeattack"], (300, 1250, 2500)), (evs["sprint"], (400, 1500)),
                   (evs["speedtrap"], [g["s"] - 60 for g in evs["speedtrap"]["gates"] if g["type"] == "camera"][1:3])):
        scs = [(scene(d, lib, "day", (ev["barriers"],)), "day") for d in (before, after)]
        sheet(route_eyes(ev, ss), scs, os.path.join(out_dir, "markers-%s.png" % ev["id"]),
              "Route markers (items 5, 10) and speed cameras (8): a driver's view")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
