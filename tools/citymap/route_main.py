"""Main roads only (tertiary and above). Shortest drivable connection between the DND-KMP Expressway (motorway) and Mathura Road (trunk) in the OSM data,
and the road names along it. Writes route.json and route.png (the map with the route drawn)."""
import heapq
import json
import math
import sys

from PIL import Image, ImageDraw

d = json.load(open("osm.json", encoding="utf-8"))  # run inside the area folder (osm.json, map.png)
DRIVE = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
         "tertiary", "tertiary_link"}


def dist(a, b):
    dy = (b[0] - a[0]) * 111320
    dx = (b[1] - a[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


graph, names, kind_of = {}, {}, {}
for e in d["elements"]:
    t = e.get("tags", {})
    if e["type"] != "way" or t.get("highway") not in DRIVE or "geometry" not in e:
        continue
    pts = [(round(p["lat"], 7), round(p["lon"], 7)) for p in e["geometry"]]
    oneway = t.get("oneway") == "yes" or t.get("highway") in ("motorway", "motorway_link")
    for a, b in zip(pts, pts[1:]):
        w = dist(a, b)
        graph.setdefault(a, []).append((b, w, e["id"]))
        if not oneway:
            graph.setdefault(b, []).append((a, w, e["id"]))
        for p in (a, b):
            kind_of.setdefault(p, set()).add(t["highway"])
    names[e["id"]] = (t.get("name") or t.get("ref") or t["highway"], t["highway"])

starts = [p for p, k in kind_of.items() if k & {"motorway"}]
goals = {p for p, k in kind_of.items() if "trunk" in k and names and True}
best = None
for direction in ("to_mathura", "to_dnd"):
    src = starts if direction == "to_mathura" else list(goals)
    dst = goals if direction == "to_mathura" else set(starts)
    pq = [(0.0, p, None) for p in src]
    seen, prev = {}, {}
    while pq:
        c, p, via = heapq.heappop(pq)
        if p in seen:
            continue
        seen[p] = c
        prev[p] = via
        if p in dst and c > 0:
            path, q = [], p
            while prev.get(q):
                path.append(prev[q])
                q = prev[q][0]
            path.reverse()
            if best is None or c < best[0]:
                best = (c, direction, p, path)
            break
        for n, w, wid in graph.get(p, []):
            if n not in seen:
                heapq.heappush(pq, (c + w, n, (p, wid)))

c, direction, end, path = best
seq = []
for _, wid in path:
    nm = names[wid]
    if not seq or seq[-1][0] != nm[0]:
        seq.append([nm[0], nm[1]])
print("shortest connection %.2f km (%s)" % (c / 1000, direction))
for nm, k in seq:
    print("  ", nm, "(%s)" % k)
pts = [p for p, _ in path] + [end]
json.dump({"length_m": c, "direction": direction, "roads": seq, "points": pts}, open("route_main.json", "w"))

S, W, N, E = 28.385, 77.305, 28.420, 77.332
scale, lat0 = 0.35, (S + N) / 2
img = Image.open("map.png").convert("RGB")
g = ImageDraw.Draw(img)
xy = [((p[1] - W) * 111320 * math.cos(math.radians(lat0)) * scale, (N - p[0]) * 111320 * scale) for p in pts]
g.line(xy, fill=(0, 170, 0), width=8)
img.save("route_main.png")
