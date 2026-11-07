"""The Speed Trap's photo radars (Run I fixes, item 8) from the approaching car: 40 m and 15 m before each camera of
ftown-barriers-speedtrap.bun, looking along the route; drawn as render_runi.py does (X0's models from the game's
files). The sheet stays under .superpowers/ (git-ignored).

    .tools/cityenv/Scripts/python tools/citymap/render_cameras.py <dir with the city and barrier files> <out.png>
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

from chunks import read_chunks  # noqa: E402
from world import scenery  # noqa: E402

from tools.citymap import events, render_evening, render_runi, render_tex, terrain  # noqa: E402

SPEEDCAM = 0xD18402DA  # XO_PHOTORADAR_1B_MD_00


def cameras(path):
    with open(path, "rb") as f:
        data = f.read()
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id == scenery.SCENERY_SECTION:
            sc = scenery.read_scenery(c, p)
            out += [inst.matrix[3][:3] for inst in sc.instances if sc.infos[inst.info_index].solid_hashes[0] == SPEEDCAM]
    return out


def main(argv):
    d, out = argv
    ev = [e for e in events.read() if e["id"] == "speedtrap"][0]
    lib = render_runi.library()
    sc = render_runi.scene(d, lib, "day", (ev["barriers"],), tmp=os.path.dirname(os.path.abspath(out)))
    route = LineString(ev["route"])
    W, H = render_runi.W, render_runi.H
    cams = cameras(os.path.join(d, ev["barriers"]))
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(cams) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    render_tex.SKY = np.array(render_evening.LIGHT["day"]["sky"], dtype=float)
    for r, (x, y, z) in enumerate(cams):
        s = route.project(Point(x, y))
        top = 6 + r * (H + 24)
        dr.text((10, top), "camera at s %.0f m (z %.1f): 40 m and 15 m before it" % (s, z), fill=(255, 255, 255))
        for c, back in enumerate((40.0, 15.0)):
            a = route.interpolate(s - back)
            hd = math.degrees(math.atan2(y - a.y, x - a.x))
            zz = (z if z > terrain.ground_z(x, y) + 0.5 else terrain.ground_z(a.x, a.y)) + 1.3
            sheet.paste(sc.view(np.array((a.x, a.y, zz)), hd, 4.0, W, H, fov=75.0, far=500.0, cull=True),
                        (10 + c * (W + 10), top + 16))
    sheet.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
