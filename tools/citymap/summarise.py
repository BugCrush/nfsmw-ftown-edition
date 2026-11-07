"""Summary of an OSM download (road kinds and lengths, lane tags, bridges, names, buildings and heights).

    python tools/citymap/summarise.py <osm.json>
"""
import collections
import json
import math
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
els = d["elements"]


def length(g):
    total = 0.0
    for a, b in zip(g, g[1:]):
        dy = (b["lat"] - a["lat"]) * 111320
        dx = (b["lon"] - a["lon"]) * 111320 * math.cos(math.radians(a["lat"]))
        total += math.hypot(dx, dy)
    return total


roads, road_len = collections.Counter(), collections.Counter()
lanes = bridges = 0
named = set()
b = bh = bl = 0
btype = collections.Counter()
for e in els:
    t = e.get("tags", {})
    if "highway" in t and e["type"] == "way":
        h = t["highway"]
        roads[h] += 1
        road_len[h] += length(e.get("geometry", []))
        lanes += "lanes" in t
        bridges += t.get("bridge") == "yes"
        if "name" in t:
            named.add(t["name"])
    if "building" in t:
        b += 1
        btype[t["building"]] += 1
        bh += "height" in t
        bl += "building:levels" in t
print("road ways by type (count, km):")
for k, _ in roads.most_common(14):
    print("  %-14s %4d %6.1f" % (k, roads[k], road_len[k] / 1000))
print("ways with a lanes tag", lanes, "; bridges/flyovers", bridges)
print("named roads:", sorted(named)[:30])
print("buildings", b, "; with height", bh, "; with levels", bl, btype.most_common(6))
