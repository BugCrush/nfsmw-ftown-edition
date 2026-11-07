"""F-Town's landmarks: the registry (tools/citymap/landmarks/registry.json, committed: coordinates, OSM ids, photo
numbers and file names, crop corners; no pixels) read and resolved onto the city's own footprints.

    .tools/cityenv/Scripts/python tools/citymap/landmarks.py [registry]      (prints each landmark's resolved edges)

A landmark is found by one of:
- "osm_way": an OSM way id: a building of osm.json (its block, as tools/citymap/buildings.py trimmed it, the largest
  part) or, when "source" is "details", a way of details/details.json (the metro stations: their own outline, not
  trimmed, since a station stands over the road);
- "near": [lat, lon]: the block nearest to that point (Dr. Aggarwal's: the user's "beside Sector 16 HUDA Park");
- "point": [lat, lon]: a placed thing with no outline (the "Sector 15A" sign);
- "chains": a name: the raised carriageways of that flyover (the Neelam Flyover's mural).

A face is one edge of the footprint's exterior (counter-clockwise, edge k from point k to k + 1, its outside on the
right) that carries a photo crop: "edge" (index), "facing_road" (the OSM road id the photo was taken from: the
face's outward normal must point within 60 degrees of it), "photo" (the design's number = position in the sorted file
names of ftownphotos/), "corners" (the quad in the photo's pixels: top left, top right, bottom right, bottom left),
"tex" ([w, h], powers of two), optional "z" ([bottom, top] metres above the ground; default the landmark's walls),
"width_m" (metres of the edge the crop covers, centred unless "at" (0..1) says where; default the whole edge) and
"repeat" (the crop tiles along the edge every width_m). Photo overlays (the phone's and Google's buttons, labels and
pins) are recorded once per layout ("layouts") and per photo ("photos": "layout", "patch" rectangles filled from
their surroundings before the crop, "block" rectangles a crop may not touch).
"""
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import shapely
import shapely.ops
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REGISTRY = os.path.join(HERE, "landmarks", "registry.json")
PHOTOS = os.path.join(REPO, "ftownphotos")
STOREY_RANGE = (3.2, 4.0)  # metres a storey, the design's range for heights from storeys counted in the photos
FACING_DEG = 60.0


@dataclass
class Face:
    edge_index: int
    facing_road_id: int
    photo: int
    corners_px: List[Tuple[float, float]]
    tex_size: Tuple[int, int]
    z: Optional[Tuple[float, float]] = None
    width_m: Optional[float] = None
    at: float = 0.5
    repeat: bool = False
    name: str = ""


@dataclass
class Landmark:
    key: str
    kind: str
    name: str
    ref: dict
    footprint: Optional[Polygon]
    height_m: float
    storeys: int
    faces: List[Face]
    photos: List[int]
    finish: str = "plain"
    osm_name: Optional[str] = None
    extra: dict = field(default_factory=dict)
    point: Optional[Tuple[float, float]] = None
    osm_id: Optional[int] = None


def _face(d, key, k):
    return Face(d["edge"], d["facing_road"], d["photo"], [tuple(c) for c in d["corners"]], tuple(d["tex"]),
                tuple(d["z"]) if d.get("z") else None, d.get("width_m"), d.get("at", 0.5), d.get("repeat", False),
                d.get("name") or "%s_%d" % (key, k))


def read(path=REGISTRY):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load(path=REGISTRY):
    """[Landmark] with footprint None (resolve() finds it)."""
    reg = read(path)
    out = []
    for d in reg["landmarks"]:
        ref = {k: d[k] for k in ("osm_way", "near", "point", "chains", "source") if k in d}
        faces = [_face(f, d["key"], k) for k, f in enumerate(d.get("faces", []))]
        out.append(Landmark(d["key"], d["kind"], d["name"], ref, None, d.get("height_m", 0.0), d.get("storeys", 0),
                            faces, d.get("photos", []), d.get("finish", "plain"), d.get("osm_name"),
                            {k: v for k, v in d.items() if k not in ("key", "kind", "name", "faces", "photos")}))
    return out


def photo_files(photos_dir=PHOTOS):
    """{number: file name}: the design's photo numbers are the order of the sorted file names."""
    if not os.path.isdir(photos_dir):
        return {}
    names = sorted(n for n in os.listdir(photos_dir) if n.lower().endswith((".jpg", ".jpeg", ".png")))
    return {k + 1: n for k, n in enumerate(names)}


def _ring(proj, geom):
    return [proj.to_render(p["lat"], p["lon"]) for p in geom]


def _ways(*sources):
    out = {}
    for src in sources:
        for e in (src or {}).get("elements", []):
            if e["type"] == "way" and e.get("geometry"):
                out[e["id"]] = e
    return out


def clean_footprint(poly):
    """The landmark's footprint as its edges are numbered: the largest polygon part, counter-clockwise, simplified by
    0.3 m (OSM outlines carry points a few centimetres apart; their edges would be too short to carry a photo)."""
    if poly.geom_type != "Polygon":
        poly = max([p for p in getattr(poly, "geoms", []) if p.geom_type == "Polygon"], key=lambda p: p.area)
    poly = Polygon(poly.exterior)
    return orient(poly.simplify(0.3, preserve_topology=True), 1.0)


def edges(fp):
    pts = list(fp.exterior.coords)
    return list(zip(pts, pts[1:]))


def outward(p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy) or 1.0
    return dy / L, -dx / L  # the right of p -> q: outside a counter-clockwise ring


def resolve(reg, osm, details, proj, blocks=None, chains=None):
    """Each Landmark of `reg` (load()) with its footprint (render metres) and osm_id. blocks: buildings.blocks(...)
    .blocks (their trimmed footprints); chains: levels.Levels.raised_chains (for "chains" entries)."""
    ways = _ways(osm)
    dways = _ways(details)
    by_id = {}
    for b in blocks or []:
        by_id.setdefault(b.osm_id, []).append(b)
    tree = shapely.STRtree([b.footprint for b in blocks]) if blocks else None
    out = []
    for lm in reg:
        ref = lm.ref
        if "osm_way" in ref:
            wid = ref["osm_way"]
            lm.osm_id = wid
            if ref.get("source") == "details":
                e = dways[wid]
                lm.footprint = clean_footprint(shapely.make_valid(Polygon(_ring(proj, e["geometry"]))))
                lm.extra["osm_tags"] = e.get("tags", {})
            else:
                parts = by_id.get(wid)
                if parts:
                    lm.footprint = clean_footprint(max(parts, key=lambda b: b.footprint.area).footprint)
                else:
                    e = ways[wid]
                    lm.footprint = clean_footprint(shapely.make_valid(Polygon(_ring(proj, e["geometry"]))))
                lm.extra["osm_tags"] = ways.get(wid, dways.get(wid, {})).get("tags", {})
        elif "near" in ref:
            x, y = proj.to_render(*ref["near"])
            k = tree.nearest(Point(x, y))
            b = blocks[int(k)]
            lm.osm_id = b.osm_id
            lm.footprint = clean_footprint(b.footprint)
            lm.extra["osm_tags"] = ways.get(b.osm_id, {}).get("tags", {})
        elif "point" in ref:
            lm.point = proj.to_render(*ref["point"])
        elif "chains" in ref:
            lm.extra["chains"] = [c for c in (chains or []) if c.name == ref["chains"]]
        out.append(lm)
    return out


def road_lines(model):
    return {r.id: LineString(r.points) for r in model.roads}


def facing_point(fp, face, lines):
    """The nearest point of the face's facing road at least 2 m in front of the face's line (a road behind the face
    never counts), or None."""
    p, q = edges(fp)[face.edge_index]
    n = outward(p, q)
    mid = Point((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    t = (-n[1], n[0])
    front = Polygon([(mid.x + n[0] * 2 + t[0] * s, mid.y + n[1] * 2 + t[1] * s) for s in (-1000, 1000)] +
                    [(mid.x + n[0] * 1000 + t[0] * s, mid.y + n[1] * 1000 + t[1] * s) for s in (1000, -1000)])
    line = lines[face.facing_road_id].intersection(front)
    if line.is_empty:
        return None
    c = shapely.ops.nearest_points(line, mid)[0]
    return (c.x, c.y)


def facing_angle(fp, face, lines):
    """(Degrees between the face's outward normal and the direction from the edge's middle to facing_point, the
    distance there)."""
    p, q = edges(fp)[face.edge_index]
    n = outward(p, q)
    mid = Point((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    c = facing_point(fp, face, lines)
    if c is None:
        return 180.0, float("inf")
    c = Point(c)
    dx, dy = c.x - mid.x, c.y - mid.y
    L = math.hypot(dx, dy) or 1.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (dx * n[0] + dy * n[1]) / L)))), L


def overlays(reg_json, photo):
    """(block rectangles, patch rectangles) of a photo: its layout's plus its own, [x0, y0, x1, y1] pixels."""
    p = reg_json.get("photos", {}).get(str(photo), {})
    block = list(reg_json.get("layouts", {}).get(p.get("layout", "plain"), [])) + list(p.get("block", []))
    return block, list(p.get("patch", []))


def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from tools.citymap import buildings, geo, levels, roadmodel, surfaces
    area = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        osm = json.load(f)
    with open(os.path.join(area, "areas.json"), encoding="utf-8") as f:
        areas = json.load(f)
    with open(os.path.join(area, "details", "details.json"), encoding="utf-8") as f:
        details = json.load(f)
    proj = geo.Projection()
    model = roadmodel.build(osm, proj)
    L = levels.build(model)
    pav = surfaces.pavements(model, {0: L.ground_polygon}).difference(L.elevated)
    roads = shapely.union_all([L.ground_polygon, pav, L.elevated])
    bl = buildings.blocks(osm, proj, roads, seed=1, areas=areas, model=model)
    lms = resolve(load(argv[0] if argv else REGISTRY), osm, details, proj, bl.blocks, L.raised_chains)
    lines = road_lines(model)
    named = [(r.id, r.name, r.kind, LineString(r.points)) for r in model.roads ]
    for lm in lms:
        print("==", lm.key, lm.osm_id, lm.extra.get("osm_tags", {}).get("name"))
        if lm.footprint is None:
            continue
        print("   area %.0f centroid (%.0f, %.0f)" % (lm.footprint.area, lm.footprint.centroid.x, lm.footprint.centroid.y))
        for k, (p, q) in enumerate(edges(lm.footprint)):
            L_ = math.dist(p, q)
            if L_ < 6:
                continue
            n = outward(p, q)
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            probe = LineString([mid, (mid[0] + n[0] * 80, mid[1] + n[1] * 80)])
            hits = sorted((ln.distance(Point(mid)), rid, nm, kd) for rid, nm, kd, ln in named if ln.intersects(probe))
            print("   edge %d len %.1f normal (%.2f, %.2f) roads ahead %s" % (k, L_, n[0], n[1],
                  [(round(d, 1), rid, nm, kd) for d, rid, nm, kd in hits[:2]]))
        for f in lm.faces:
            print("   face %s: %.1f deg, %.1f m" % (f.name, *facing_angle(lm.footprint, f, lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
