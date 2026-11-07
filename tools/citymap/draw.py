"""Draws an OSM download (roads by kind, buildings, bridges in blue) to a PNG; the bounding box and scale are the
F-Town first area's (edit S, W, N, E for another).

    python tools/citymap/draw.py <osm.json> <map.png>
"""
import json
import math
import sys

from PIL import Image, ImageDraw

d = json.load(open(sys.argv[1], encoding="utf-8"))
S, W, N, E = 28.385, 77.305, 28.420, 77.332
scale = 0.35  # pixels per metre
lat0 = (S + N) / 2
w = int((E - W) * 111320 * math.cos(math.radians(lat0)) * scale)
h = int((N - S) * 111320 * scale)
img = Image.new("RGB", (w, h), (245, 243, 238))
g = ImageDraw.Draw(img)


def xy(p):
    return ((p["lon"] - W) * 111320 * math.cos(math.radians(lat0)) * scale, (N - p["lat"]) * 111320 * scale)


style = {"motorway": ((200, 60, 60), 7), "trunk": ((230, 120, 40), 6), "trunk_link": ((230, 120, 40), 3),
         "secondary": ((230, 190, 60), 5), "tertiary": ((180, 180, 180), 4), "residential": ((205, 205, 205), 2),
         "living_street": ((205, 205, 205), 2), "service": ((225, 225, 225), 1)}
for e in d["elements"]:
    t = e.get("tags", {})
    if "building" in t and "geometry" in e:
        pts = [xy(p) for p in e["geometry"]]
        if len(pts) > 2:
            g.polygon(pts, fill=(150, 130, 120))
order = ["service", "living_street", "residential", "tertiary", "secondary", "trunk_link", "trunk", "motorway"]
for kind in order:
    col, width = style[kind]
    for e in d["elements"]:
        t = e.get("tags", {})
        if t.get("highway") == kind and "geometry" in e:
            g.line([xy(p) for p in e["geometry"]], fill=col, width=width)
for e in d["elements"]:
    t = e.get("tags", {})
    if t.get("bridge") == "yes" and "geometry" in e and t.get("highway"):
        g.line([xy(p) for p in e["geometry"]], fill=(60, 60, 200), width=4)
img.save(sys.argv[2])
print(img.size)
