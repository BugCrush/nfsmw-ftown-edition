"""F-Town's road model: every road for cars of the OSM data as our own data (centre lines in render metres, widths,
lanes, one-way, bridge levels, junctions), kept for later stages (the design: "the road graph is kept as our own
data from stage 2", so opponents can be given a road network without rebuilding the city).

    .tools/cityenv/Scripts/python tools/citymap/roadmodel.py <area dir>      (writes <area dir>/ftown-roads.json)

Kept (the user's "every road for cars"): motorway, trunk, primary, secondary, tertiary and their _links, residential,
unclassified, living_street, service, road. Left out: footway, path, steps, track, cycleway, pedestrian, and anything
else.

Widths (calls marked in docs/ftown-notes.md "Stage 2: the streets"; a `lanes` tag wins over the default lane count):
lane 3.5 m; motorway and trunk one-way 3 lanes, two-way trunk 6; primary/secondary two-way 4, one-way 2; tertiary 2;
plus a 0.5 m shoulder each side on motorway/trunk/primary/secondary/tertiary. Without a lanes tag: _link 4.5 m,
residential and unclassified 5.5 m, living_street and service 4.0 m. With a lanes tag every kind is lanes x 3.5 m
(+ shoulders on the main kinds).

Junctions: the OSM download ("out tags geom") carries no node ids, so a point is keyed by its coordinates to 1e-7
degrees (OSM's own precision); ways that share an OSM node share its coordinates exactly.

Levels: a bridge with layer >= 1 is level 1 (raised); a bridge without a layer tag (the two DND-KMP motorway bridges)
is level 1 when it crosses another kept road and level 0 otherwise; everything else (tunnels with layer -1 included)
is level 0 (flat ground, the design's call).
"""
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import geo  # noqa: E402

KEPT = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "residential", "unclassified", "living_street", "service", "road"}
MAIN = {"motorway", "trunk", "primary", "secondary", "tertiary"}
LANE = 3.5
SHOULDER = 0.5


def node_key(lat, lon):
    return "%d,%d" % (round(lat * 1e7), round(lon * 1e7))


@dataclass
class Road:
    id: int
    kind: str
    name: Optional[str]
    points: List[Tuple[float, float]]
    keys: List[str]
    width_m: float
    lanes: int
    lanes_tagged: Optional[int]
    oneway: bool
    layer: int
    layer_tagged: Optional[int]
    bridge: bool
    level: int
    bridge_note: str = ""

    def length(self):
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


@dataclass
class Node:
    x: float
    y: float
    road_ids: List[int] = field(default_factory=list)


class RoadModel:
    def __init__(self, roads, nodes):
        self.roads = roads
        self.nodes = nodes
        self._by_id = {r.id: r for r in roads}

    def road(self, rid):
        return self._by_id[rid]

    def junctions(self):
        """{key: Node} of the points shared by two or more kept roads."""
        return {k: n for k, n in self.nodes.items() if len(set(n.road_ids)) >= 2}

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        data = {"roads": [asdict(r) for r in self.roads],
                "nodes": {k: asdict(n) for k, n in self.nodes.items()},
                "note": "F-Town road model, derived from OpenStreetMap data (c) OpenStreetMap contributors (ODbL)"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        roads = []
        for r in data["roads"]:
            r["points"] = [tuple(p) for p in r["points"]]
            roads.append(Road(**r))
        nodes = {k: Node(**n) for k, n in data["nodes"].items()}
        return cls(roads, nodes)


def _int(v):
    try:
        return int(str(v).split(";")[0].strip())
    except (TypeError, ValueError):
        return None


def _oneway(t):
    v = t.get("oneway")
    if v in ("yes", "1", "true", "-1"):
        return True
    if v == "no":
        return False
    return t.get("highway") in ("motorway", "motorway_link") or t.get("junction") == "roundabout"


def _lanes_default(kind, oneway):
    if kind in ("motorway", "trunk"):
        return 3 if oneway else 6
    if kind in ("primary", "secondary"):
        return 2 if oneway else 4
    if kind == "tertiary":
        return 2
    if kind.endswith("_link"):
        return 1
    return 2 if kind in ("residential", "unclassified", "road") else 1


def width_of(kind, lanes_tagged, oneway):
    """(width in metres, lane count) for a road kind, its lanes tag (or None) and one-way."""
    lanes = lanes_tagged if lanes_tagged else _lanes_default(kind, oneway)
    sh = 2 * SHOULDER if kind in MAIN else 0.0
    if lanes_tagged:
        return lanes * LANE + sh, lanes
    if kind.endswith("_link"):
        return 4.5, 1
    if kind in ("residential", "unclassified", "road"):
        return 5.5, lanes
    if kind in ("living_street", "service"):
        return 4.0, lanes
    return lanes * LANE + sh, lanes


def _crosses_other(road, others):
    from shapely.geometry import LineString
    a = LineString(road.points)
    mine = set(road.keys)
    for o in others:
        if o.id == road.id:
            continue
        b = LineString(o.points)
        if not a.intersects(b):
            continue
        inter = a.intersection(b)
        pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
        shared = {(round(p[0], 6), round(p[1], 6)) for k, p in zip(o.keys, o.points) if k in mine}
        for p in pts:
            if p.geom_type != "Point" or (round(p.x, 6), round(p.y, 6)) not in shared:
                return True
    return False


def build(osm, proj=None):
    proj = proj or geo.Projection()
    roads = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("highway") not in KEPT or "geometry" not in e:
            continue
        kind = t["highway"]
        geom = e["geometry"]
        if t.get("oneway") == "-1":
            geom = list(reversed(geom))
        pts = [proj.to_render(p["lat"], p["lon"]) for p in geom]
        keys = [node_key(p["lat"], p["lon"]) for p in geom]
        oneway = _oneway(t)
        lt = _int(t.get("lanes"))
        lt = lt if lt and lt > 0 else None
        w, lanes = width_of(kind, lt, oneway)
        layer_t = _int(t.get("layer"))
        bridge = t.get("bridge") not in (None, "no")
        layer = layer_t if layer_t is not None else 0
        roads.append(Road(e["id"], kind, t.get("name"), pts, keys, w, lanes, lt, oneway, layer, layer_t, bridge,
                          1 if bridge and layer >= 1 else 0))
    for r in roads:
        if r.bridge and r.layer_tagged is None:
            if _crosses_other(r, roads):
                r.level, r.layer, r.bridge_note = 1, 1, "crosses a road: raised"
            else:
                r.bridge_note = "crosses no road: ground"
        elif r.bridge:
            r.bridge_note = "layer %d" % r.layer
    nodes = {}
    for r in roads:
        for k, p in zip(r.keys, r.points):
            n = nodes.get(k)
            if n is None:
                n = nodes[k] = Node(p[0], p[1], [])
            if r.id not in n.road_ids:
                n.road_ids.append(r.id)
    return RoadModel(roads, nodes)


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 1
    area = argv[0]
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        m = build(json.load(f))
    out = os.path.join(area, "ftown-roads.json")
    m.save(out)
    print("%d roads, %d nodes, %d junctions, %.1f km -> %s" % (len(m.roads), len(m.nodes), len(m.junctions()),
                                                              sum(r.length() for r in m.roads) / 1000, out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
