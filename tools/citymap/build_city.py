"""Builds F-Town's city file from the OSM downloads: the road model, surfaces, flyovers, buildings and ground, cut into
128 m tiles, written with Part 2's writers into one chunk file that FTownLoader loads at the place outside Rockport.

    .tools/cityenv/Scripts/python tools/citymap/build_city.py <area dir> <out.bun>

    e.g. .tools/cityenv/Scripts/python tools/citymap/build_city.py .superpowers/citymap/faridabad ftown/ftown-city.bun

<area dir> holds osm.json, areas.json and route_main.json (tools/citymap/fetch_osm.py, route_main.py). Writes <out.bun>
(derived from OpenStreetMap data, (c) OpenStreetMap contributors, ODbL: git-ignored) and ftown-city.json beside it
(numbers only: spawns, sections, packs, counts; committed).

The file, in order: one texture pack (our drawn textures), one solid list per district, one scenery section per
district, one collision pack per district. A district is 8 x 9 tiles (1,024 x 1,152 m, from the area's south-west tile); its number is both its scenery
section's and its collision pack's: K0..K9, N0..N9, W0..W9, then U0, U2..U9 (letters Rockport leaves unused; a
sub-number under 10 is drawn whenever the camera is outside Rockport's drivable sections, notes Q2; 2101 is the
slab's). At most 64 top-level chunks (UnloadChunks keeps 64, 0x658A4F).
"""
import hashlib
import json
import math
import os
import statistics
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

import shapely  # noqa: E402

from chunks import Chunk, bstringhash, chunk_bytes, write_chunks  # noqa: E402
from vlthash import vlt32  # noqa: E402
from world import collision_write, scenery_write, smackables, solids, texpack  # noqa: E402
from world.collision import to_physics  # noqa: E402

from tools.citymap import buildings, furniture, geo, landmark_build, landmarks, levels, metro, phototex  # noqa: E402
from tools.citymap import breakables, evening, roadmodel  # noqa: E402
from tools.citymap import streetlife, stripify, surfaces, terrain, textures, tiles, x0props  # noqa: E402

BBOX = (28.385, 77.305, 28.420, 77.332)
DISTRICT = (8, 9)  # tiles across (x) and up (y): 1,024 x 1,152 m, so the area (2.8 x 4.1 km) is 3 x 4 districts
NUMBERS = [1100 + n for n in range(10)] + [1400 + n for n in range(10)] + [2300 + n for n in range(10)] + \
    [2100] + [2102 + n for n in range(8)]
ROUTE_START = (28.41461, 77.33109)
ROUTE_END = (28.39993, 77.31195)
TEXTURE_PACK_NAME = "FTOWN_CITY"
TEXTURE_PACK_FILE = "FTown\\FTownCity.tpk"
GROUND_KINDS = ["asphalt", "pavement", "grass", "earth", "paint", "concrete", "paver", "lot"]
BUILD_KINDS = ["plaster", "roof", "concrete"]
# the view model for the draw budget (DrawAScenery, Scenery.cpp:678; InlinedViewGetPixelSize, Scenery.hpp:402)
VIEW_FOV = 106.0  # degrees across while racing (notes "Graphics part 2": the game widens it with speed)
VIEW_H = 1000.0  # the view's H: assumed (2240 px across at 106 degrees is a focal length of 844 px; rounded up)
# the landmarks plan's five landmark viewpoints for the draw budget (besides the two spawns): on a road, looking at it
# (written in the frame before the connection's move: geo.moved puts them where the city is now)
VIEWPOINTS = [dict(v, y=geo.moved(v["x"], v["y"])[1]) for v in (
    {"name": "Neelam Chowk", "x": 1372.0, "y": 10820.0, "z": 101.0, "heading": 90.0},
    {"name": "Bata Chowk", "x": 1470.0, "y": 9560.0, "z": 101.0, "heading": 90.0},
    {"name": "Old Fbd station", "x": 1279.0, "y": 12300.0, "z": 101.0, "heading": 72.0},
    {"name": "Sector 16 Market", "x": 2095.0, "y": 12500.0, "z": 101.0, "heading": 45.0},
    {"name": "Marengo Asia", "x": 2070.0, "y": 13000.0, "z": 101.0, "heading": -90.0})]
# the budget per view (docs/ftown-notes.md "Landmarks and street furniture"): each viewpoint against the streets alone
# (build --plain: the city Run G drove, 99.7 FPS on the route, with the city fixes) at the same spot. Meshes are the
# draw calls the CPU-bound frame pays for: at most MESH_MARGIN times the plain view's (99.7 FPS x 1 / 1.25 = 80 FPS
# even if the frame time grew with the draws alone); triangles (the GPU has headroom) TRI_MARGIN times; no new
# instances but the few tiles that had nothing to draw before (INSTANCE_EXTRA); a small view (Bata Chowk's 78 meshes)
# may add MESH_SLACK meshes however small its plain count. PLAIN_VIEWS: the plain city's numbers (2026-11-03; the
# spawns' equal Run G's, notes "Stage 2").
# (INSTANCE_EXTRA: the whole city has 12 more instances than the streets alone, 1,409 against 1,397, tiles with
# something to draw now; the Bata Chowk view north sees 13 more: the new tiles' and one tile turning from culled)
MESH_MARGIN, MESH_SLACK, TRI_MARGIN, TRI_SLACK, INSTANCE_EXTRA = 1.25, 50, 1.6, 10000, 16


# the street life (docs/ftown-notes.md "Street life (2026-11-04)"): each viewpoint's proxy (tools/citymap/view_proxy.py:
# instances, meshes, triangles) on the Run H fixes' city (d8013b0a..., 2026-11-04) and the plan's margin over it
RUNH_FIXES_VIEWS = {"route start": (345, 548, 86240), "route end": (369, 572, 76018),
                    "Neelam Chowk": (771, 1009, 191808), "Bata Chowk": (1203, 1466, 292308),
                    "Old Fbd station": (335, 519, 86716), "Sector 16 Market": (223, 394, 55160),
                    "Marengo Asia": (1061, 1308, 231749)}
STREET_MARGIN = 1.15
# own looks (docs/ftown-notes.md "Own looks and a lived-in city (2026-11-04)"): the street-life city's proxy
# (a0834e64..., 2026-11-04) per view; the stage keeps instances and meshes (the draws the CPU-bound frame pays for:
# 8.0 ms + 1.1 us a draw, notes "Run H fixes" 4) within the street-life limits above and lets triangles (the GPU has
# headroom; they cost a mesh only past 1,000 per texture per tile) grow to OWN_TRI_MARGIN x the street life's, never
# past Rockport's largest loaded set
STREET_LIFE_VIEWS = {"route start": (395, 607, 89032), "route end": (419, 637, 80538),
                     "Neelam Chowk": (817, 1073, 196232), "Bata Chowk": (1242, 1519, 295660),
                     "Old Fbd station": (361, 557, 89172), "Sector 16 Market": (233, 410, 63402),
                     "Marengo Asia": (1097, 1357, 243349)}
OWN_TRI_MARGIN = 1.5
ROCKPORT_TRIANGLES_MAX = 343529


def own_looks_triangles(name):
    """The triangles a viewpoint may draw since the own looks (STREET_LIFE_VIEWS' rule)."""
    return min(OWN_TRI_MARGIN * STREET_LIFE_VIEWS[name][2], ROCKPORT_TRIANGLES_MAX)


def _q(v):
    """A matrix entry as the scenery writer stores it (an s16 / 8192)."""
    return round(v * 8192.0) / 8192.0


def spawn_points(proj, route):
    """The spawns: 1 m above the road at the route's ends, heading along the route."""
    rp = [proj.to_render(a, b) for a, b in route]
    s0 = proj.to_render(*ROUTE_START)
    s1 = proj.to_render(*ROUTE_END)
    h0 = math.degrees(math.atan2(rp[1][1] - rp[0][1], rp[1][0] - rp[0][0]))
    h1 = math.degrees(math.atan2(rp[-1][1] - rp[-2][1], rp[-1][0] - rp[-2][0]))
    # 1 m above the built ground (terrain.ground_z: the elevation, 2026-11-05)
    x0, y0, x1, y1 = round(s0[0], 2), round(s0[1], 2), round(s1[0], 2), round(s1[1], 2)
    return [{"name": "route start", "x": x0, "y": y0, "z": round(terrain.ground_z(x0, y0) + 1.0, 2),
             "heading": round(h0, 1)},
            {"name": "route end", "x": x1, "y": y1, "z": round(terrain.ground_z(x1, y1) + 1.0, 2),
             "heading": round(h1, 1)}]


def viewpoints():
    """VIEWPOINTS with z 1 m over the built ground (terrain.ground_z)."""
    return [dict(v, z=round(terrain.ground_z(v["x"], v["y"]) + 1.0, 2)) for v in VIEWPOINTS]


def street_budgets():
    """{view name: (instances, meshes, triangles)} the street life may add at each viewpoint: the plan's 15% over the
    Run H fixes' numbers, less one of each for rounding."""
    return {n: tuple(int((STREET_MARGIN - 1.0) * v) - 1 for v in b) for n, b in RUNH_FIXES_VIEWS.items()}


def prop_axes(heading, lean=0.0, lean_dir=0.0):
    """The model's x, y, z axes in the world (unit rows, the scenery matrix's rows): turned by `heading` about the
    vertical, then tilted `lean` radians towards the horizontal direction `lean_dir` (Run I fixes, item 4: each tree
    leans a little; the trunk's foot stays at the origin). A rotation: no shear, no mirror."""
    c, s = math.cos(heading), math.sin(heading)
    axes = [(c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0)]
    if not lean:
        return axes
    k = (-math.sin(lean_dir), math.cos(lean_dir), 0.0)  # tilting about k takes +z towards lean_dir
    ca, sa = math.cos(lean), math.sin(lean)
    out = []
    for v in axes:
        kv = sum(a * b for a, b in zip(k, v))
        cr = (k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0])
        out.append(tuple(v[i] * ca + cr[i] * sa + k[i] * kv * (1 - ca) for i in range(3)))
    return out


def prop_entry(p):
    """A street-life prop as scenery_write.make_section's props entry: X0's model in slot 0 alone (named by hash),
    the info radius that sets its draw distance, the model's box from the catalogue, the turned and scaled matrix,
    the pick's flags (tools/citymap/x0props.py)."""
    rows = prop_axes(p.heading, getattr(p, "lean", 0.0), getattr(p, "lean_dir", 0.0))
    m = tuple(tuple(_q(v * p.scale) for v in r) + (0.0,) for r in rows) + \
        ((p.x, p.y, terrain.ground_z(p.x, p.y) + p.z, 1.0),)
    box = x0props.model(x0props.pick(p.role)["name"])["box"]
    return ("FTS_" + p.role.upper(), x0props.slots(p.role), x0props.info_radius(p.role), box, m,
            x0props.flags(p.role))


def view_budget(name):
    """(meshes, triangles, instances) a viewpoint may draw (the views' names carry no place name the game's files
    may not: "Old Fbd" is Old Faridabad station)."""
    pi, pm, pt = PLAIN_VIEWS[name]
    # triangles: the landmarks stage's margin, or the own looks' rule where it allows more (own_looks_triangles);
    # never past Rockport's largest loaded set (the own looks' rule; the review: the max() let the margin pass it)
    tri = min(max(TRI_MARGIN * pt, pt + TRI_SLACK, own_looks_triangles(name)), ROCKPORT_TRIANGLES_MAX)
    return max(MESH_MARGIN * pm, pm + MESH_SLACK), tri, pi + INSTANCE_EXTRA
PLAIN_VIEWS = {"route start": (344, 886, 84495), "route end": (367, 988, 74763), "Neelam Chowk": (763, 1924, 186551),
               "Bata Chowk": (1193, 2972, 285452), "Old Fbd station": (330, 874, 84083),
               "Sector 16 Market": (218, 568, 52226), "Marengo Asia": (1055, 2612, 232992)}
GRID = {"min_x": -4800.0, "min_z": -1664.0, "edge": 64.0, "cols": 92, "rows": 103, "margin": 64.0}


def _load(area):
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        osm = json.load(f)
    with open(os.path.join(area, "areas.json"), encoding="utf-8") as f:
        areas = json.load(f)
    with open(os.path.join(area, "route_main.json")) as f:
        route = json.load(f)["points"]
    return osm, areas, route


class Extras:
    """What the landmarks stage adds to the streets (docs/ftown-notes.md "Landmarks and street furniture"): parts and
    barriers for the tiles, blocks removed or drawn by a landmark, and the pieces for the tests."""

    def __init__(self):
        self.parts, self.barriers, self.skip_blocks = [], [], set()
        self.landmarks, self.viaduct, self.stations, self.photo_names = [], None, [], set()


def _details(area):
    p = os.path.join(area, "details", "details.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def face_textures(reg=None):
    """{name: (w, h, array)} of the landmark faces, drawn by us (tools/citymap/landmark_tex.py, docs/ftown-notes.md
    "Own looks and a lived-in city"): no photo is opened (the photo crops of tools/citymap/phototex.py are no longer
    used by the build)."""
    from tools.citymap import landmark_tex
    return landmark_tex.draw_all(reg)


def _trim_blocks(blocks, cut):
    """Blocks less `cut` (the viaduct's and stations' footprints): parts under buildings.MIN_PART dropped."""
    shapely.prepare(cut)
    out = []
    for b in blocks:
        if not cut.intersects(b.footprint):
            out.append(b)
            continue
        g = b.footprint.difference(cut)
        for p in buildings._parts(buildings._clean(g)):
            if p.area >= buildings.MIN_PART:
                out.append(buildings.Block(b.osm_id, p, b.height_m, b.kind, b.source_area))
    return out


def extras(area, proj, model, L, osm, bl, photo_names, pav=None):
    """Extras for the city (the landmarks plan's Tasks 3-6); bl.blocks is changed in place (blocks under the metro
    and its stations removed or trimmed)."""
    ex = Extras()
    details = _details(area)
    outer = buildings.edge_box(proj, BBOX)
    lms = landmarks.resolve(landmarks.load(), osm, details, proj, bl.blocks, L.raised_chains)
    ex.landmarks, ex.photo_names = lms, set(photo_names)
    lanes = shapely.union_all([L.ground_polygon, L.elevated]).buffer(metro.LANE_CLEAR)
    v = metro.viaduct(details, proj, L, outer, lanes, [lm.footprint for lm in lms if lm.kind == "station"])
    st = metro.stations([lm for lm in lms if lm.kind == "station"], v, L, details, proj, ex.photo_names, lanes)
    ex.viaduct, ex.stations = v, st
    ex.parts += v.parts.all()
    # the evening's deck lights (tools/citymap/evening.py), off the stations
    ex.parts += metro.deck_lamps(v, [s.footprint for s in st])
    ex.barriers += v.barriers
    for s in st:
        ex.parts += s.parts.all()
        ex.barriers += s.barriers
    station_ids = {lm.osm_id for lm in lms if lm.kind == "station"}
    cut = shapely.union_all([v.footprint(1.0)] + [s.footprint.buffer(0.5) for s in st])
    bl.blocks[:] = _trim_blocks([b for b in bl.blocks if b.osm_id not in station_ids], cut)
    # the landmark buildings, the mural, the DND-KMP walls, the sign (Task 4): the plain blocks they stand on go
    lb = landmark_build.build(lms, ex.photo_names, L, lanes, model, shapely.union_all([L.ground_polygon,
                                                                                       L.elevated]))
    ex.landmark_result = lb
    ex.parts += lb.parts
    ex.barriers += lb.barriers
    ex.ground_cut = list(lb.footprints.values())
    fps = shapely.union_all(ex.ground_cut)
    shapely.prepare(fps)
    bl.blocks[:] = [b for b in bl.blocks if not fps.intersects(b.footprint) or
                    fps.intersection(b.footprint).area < 1.0]
    # street furniture (Task 5)
    occupied = [b.footprint for b in bl.blocks] + ex.ground_cut + [s.footprint for s in st]
    fr = furniture.build(model, L, pav, details, proj, occupied, v.pier_boxes, outer)
    ex.furniture = fr
    ex.parts += fr.parts
    ex.barriers += fr.barriers
    # ordinary buildings styled after the photos (Task 6): tints, parapets and market shop fronts (tiles._buildings
    # reads each block's style); boundary walls with gates before houses on residential lanes
    _osm, areas, _route = _load(area)
    lanes_pav = shapely.union_all([L.ground_polygon, L.elevated] + ([pav] if pav is not None else []))
    buildings.styles(bl.blocks, model, lanes_pav, buildings.market_areas(proj, osm, areas))
    gates = [proj.to_render(e["lat"], e["lon"]) for e in details["elements"]
             if e["type"] == "node" and e.get("tags", {}).get("barrier") == "gate"]
    others = shapely.union_all(occupied + [f for _n, f in fr.feet] + [m.polygon for m in fr.medians])
    ex.boundary = buildings.boundary_walls(bl.blocks, model, lanes_pav, gates, others)
    ex.parts += _boundary_parts(ex.boundary)
    ex.barriers += [(p, q, 0.0, buildings.BOUNDARY_H, furniture.TWO_SIDED) for p, q in _pieces(ex.boundary)]
    # own looks: mumties, water tanks, balconies, hedges (tools/citymap/housedetail.py)
    from tools.citymap import housedetail
    ex.house_detail = housedetail.build(bl.blocks, lanes_pav, ex.boundary, raised=L.elevated)
    ex.parts += ex.house_detail.parts
    # own looks: electricity poles and wires along the residential lanes (tools/citymap/poles.py)
    from tools.citymap import poles
    # and off every race route by ROUTE_KEEP (the review: a slide at race speed ends on a solid pole)
    routes = [[proj.to_render(a, b) for a, b in _route]] + event_routes()
    keep = shapely.union_all([lanes_pav, others] + [shapely.LineString(s).buffer(0.2) for s in ex.boundary] +
                             [shapely.Polygon(r) for r in v.pier_boxes] +
                             [shapely.LineString(r).buffer(poles.ROUTE_KEEP) for r in routes if len(r) > 1])
    # what stands in the wires' height (the review): balconies, the tall street furniture, landmarks, stations, the
    # metro's piers and deck
    wire_keep = shapely.union_all([b.polygon.buffer(0.2) for b in ex.house_detail.balconies] +
                                  [g.buffer(0.3) for g in furniture_hulls(fr)] + ex.ground_cut +
                                  [s.footprint for s in st] + [shapely.Polygon(r).buffer(0.3) for r in v.pier_boxes] +
                                  [v.footprint(0.5)])
    ex.poles = poles.build(model, keep, outer.buffer(-furniture.EDGE_KEEP), [b.footprint for b in bl.blocks],
                           wire_keep)
    ex.parts += ex.poles.parts
    ex.barriers += ex.poles.barriers
    return ex


EVENTS_JSON = os.path.join(REPO, "ftown", "ftown-events.json")


def event_routes(path=None):
    """[[(x, y)]] the routes of the events in ftown/ftown-events.json (the events helper's file, read only; render
    metres); [] when there is none."""
    path = EVENTS_JSON if path is None else path
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [[tuple(p) for p in e["route"]] for e in json.load(f).get("events", []) if e.get("route")]


def furniture_hulls(fr):
    """Plan hulls of the street furniture standing 6 m or more tall (lamp posts, street lights, signals, billboards:
    their models as placed)."""
    from shapely.geometry import MultiPoint
    from tools.citymap import furniture_models as FM
    # the lamps, lights and signals are breakable poles since 2026-11-05: their models' plans (X0's boxes, our lantern)
    out = [breakables.footprint(b.role, b.x, b.y, b.heading) for b in getattr(fr, "breakables", [])]
    models = {"billboard": FM.billboard(0)[0]}
    for name, x, y, z, hd in fr.placed:
        if name not in models:
            continue
        pts = [v for t, _uv in FM.place(models[name], x, y, z, math.radians(hd)) for v in t]
        if max(v[2] for v in pts) >= 6.0:
            out.append(MultiPoint([(v[0], v[1]) for v in pts]).convex_hull)
    return out


def _pieces(segs, piece=5.0):
    out = []
    for a, b in segs:
        n = max(1, int(math.ceil(math.dist(a, b) / piece)))
        out += [((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n),
                 (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)) for k in range(n)]
    return out


def _boundary_parts(segs):
    """The boundary walls (both faces), with the buildings: since the own looks in FTC_HOUSES' boundary strip (piers,
    coping, a gate near each wall's middle, creepers), a house tint per wall."""
    import random
    from tools.citymap import parts as P
    ps = P.PartSet("BOUNDARY")
    part = ps.get("houses", "build", P.DETAIL)  # left out far and in the shadow views (Task 7)
    span = textures.HOUSE_SPAN_M
    vt, vb = textures.BOUNDARY_V
    vt, vb = vt + 1 / 1024, vb - 1 / 1024  # a pixel inside the strip: the cell row below never bleeds in
    for a, b in segs:
        L = math.dist(a, b)
        tint = buildings.HOUSE_TINTS[random.Random(int(a[0] * 10) * 7919 + int(a[1] * 10)).randrange(
            len(buildings.HOUSE_TINTS))]
        off = 7.7 - L / 2.0  # the strip's gate (6.6-8.8 m) at the wall's middle
        s = 0.0
        for p, q in _pieces([(a, b)], 20.0):
            Lp = math.dist(p, q)
            for out_right in (True, False):
                tris, uvs = P.wall(p, q, 0.0, buildings.BOUNDARY_H, (off + s) / span, (off + s + Lp) / span, vt, vb,
                                   out_right)
                part.add(tris, uvs, [P.lit(t, 62.0, tint) for t in tris])
            s += Lp
    return ps.all()


def geometry(area, photos=None, plain=False):
    """photos: {name: (w, h, array)} of the landmark face textures (face_textures(): drawn by us; None: drawn here;
    the name is kept from when they were cut from the photos); plain: the
    streets only, as before the landmarks stage (the baseline the draw budget and the comparison renders use; the
    kerbs keep their new paint)."""
    osm, areas, route = _load(area)
    proj = geo.Projection()
    model = roadmodel.build(osm, proj)
    L = levels.build(model)
    pav = surfaces.pavements(model, {0: L.ground_polygon}).difference(L.elevated)
    marks = surfaces.markings(model, {0: L.ground_polygon})
    roads = shapely.union_all([L.ground_polygon, pav, L.elevated])
    bl = buildings.blocks(osm, proj, roads, seed=1, areas=areas, model=model, bbox=BBOX)
    photos = face_textures() if photos is None else photos
    if plain:
        ex = Extras()
        ex.ground_cut = []
    else:
        ex = extras(area, proj, model, L, osm, bl, photos, pav)
    B =shapely.union_all([b.footprint for b in bl.blocks] + ex.ground_cut)
    low = L.elevated.intersection(L.low_zone)
    # the medians' tops (Run H fixes, fault 3): drawn and collided at their height, out of the pavement and ground
    # cut by the carriageways: a median may overlap a lane by a few square centimetres (simplified, then cut), and a
    # face over a lane would be a stacked face the wheels' first-face rule must not meet unflagged
    lanes_all = shapely.union_all([L.ground_polygon, L.elevated])
    plats = [(p.difference(lanes_all), z, k, s) for p, z, k, s in platforms(ex)]
    med = shapely.union_all([p for p, _z, _k, _s in plats]) if plats else shapely.Polygon()
    # pavement slivers the medians leave (under 0.6 m wide, within 1 m of a median) join the median beside them: a
    # sliver's triangles are too thin to hold a wheel and its kerb would stand with nothing behind it
    pav_c = pav.difference(med)
    core = pav_c.buffer(-0.3).buffer(0.3).intersection(pav_c)
    slivers = pav_c.difference(core).intersection(med.buffer(1.0))
    if not slivers.is_empty:
        plats = [(p.union(slivers.intersection(p.buffer(1.0))), z, k, s) for p, z, k, s in plats]
        med = shapely.union_all([p for p, _z, _k, _s in plats])
    ground = buildings.ground(proj, BBOX, areas, cut=shapely.union_all([L.ground_polygon, pav, low, B, med]))
    if not plain:
        ground = street_ground(ground, *_markets_hospitals(proj, osm, areas, ex), _osm_lots(proj, areas))
    outer = buildings.edge_box(proj, BBOX)
    edge = buildings.edge_barriers(proj, BBOX)
    sl = None
    if not plain:
        sl = street_life(proj, model, L, bl, ex, osm, areas, route, pav_c.difference(med), plats, ground, outer,
                         _details(area))
    city = tiles.CityGeometry(model, L, bl.blocks, ground, outer, edge, marks, pav_c.difference(med),
                              ex.parts + (sl.parts if sl else []), ex.barriers + (sl.barriers if sl else []),
                              ex.skip_blocks, plats, None if plain else shapely.union_all([L.ground_polygon, pav]))
    city.extras = ex
    city.streetlife = sl
    return proj, model, L, bl, city, route


def _markets_hospitals(proj, osm, areas, ex):
    """([market polygons], [hospital polygons]): OSM's commercial and retail areas and the market landmarks; the
    hospital landmarks (and, for the ground, OSM's hospital areas)."""
    hospitals, markets = [], list(buildings.market_areas(proj, osm, areas))
    fps = ex.landmark_result.footprints if getattr(ex, "landmark_result", None) else {}
    for lm in getattr(ex, "landmarks", []):
        fp = fps.get(lm.key) or lm.footprint
        if fp is None:
            continue
        if lm.kind == "hospital":
            hospitals.append(fp)
        elif lm.kind == "market":
            markets.append(fp)
    return markets, hospitals


def _osm_lots(proj, areas):
    """OSM's parking areas, industrial yards and hospital grounds (render polygons): worn concrete lots."""
    return [g for _id, g in streetlife._osm_polys(proj, areas, lambda t: t.get("amenity") in ("parking", "hospital") or
                                                  t.get("landuse") == "industrial")]


# Run I fixes, item 11 (docs/ftown-notes.md "Run I fixes: the city side"): the ground off the roads by place, in
# priority order: paved forecourts (FTC_PAVER) within FORECOURT of a market or hospital, worn lots (FTC_LOT) on OSM's
# parking, industrial and hospital areas and within MARKET_LOT of a market or LOT_HOSPITAL of a hospital, the earth
# elsewhere (redrawn; its vertex colours dusty along the roads: tiles.DUST_RGB); parks keep grass. (Shoulders as their
# own texture were tried first: 90,000 more triangles and a mesh in almost every tile, over every view's budget.)
FORECOURT = 10.0
MARKET_LOT = 25.0
LOT_HOSPITAL = 40.0


def street_ground(ground, markets, hospitals, lots):
    """[(polygon, kind)]: the earth of buildings.ground() split into paver, lot and earth (above)."""
    near = [g.buffer(FORECOURT) for g in list(markets) + list(hospitals)]
    paver = shapely.union_all(near) if near else shapely.Polygon()
    lz = list(lots) + [g.buffer(MARKET_LOT) for g in markets] + [g.buffer(LOT_HOSPITAL) for g in hospitals]
    lot = shapely.union_all(lz).difference(paver) if lz else shapely.Polygon()
    out = []
    for poly, kind in ground:
        if kind != "earth":
            out.append((poly, kind))
            continue
        rest = poly
        for zone, k in ((paver, "paver"), (lot, "lot")):
            part = rest.intersection(zone)
            rest = rest.difference(zone)
            out += [(p, k) for p in _polys_of(part)]
        out += [(p, "earth") for p in _polys_of(rest)]
    return out


def _polys_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g] if g.area > 1e-4 else []
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon" and p.area > 1e-4]


def street_life(proj, model, L, bl, ex, osm, areas, route, pav, plats, ground, outer, details):
    """The street life (tools/citymap/streetlife.py) on the finished streets: what it may stand on (the pavements, the
    medians' tops, the ground as the tiles draw it) and what it must keep off (buildings, landmarks, stations, piers,
    the furniture's feet, boundary walls)."""
    med = shapely.union_all([p for p, _z, _k, _s in plats]) if plats else shapely.Polygon()
    planted = shapely.union_all([p for p, _z, k, _s in plats if k == "grass"]) if plats else shapely.Polygon()
    ground_u = shapely.union_all([p for p, _k in ground])
    fr = ex.furniture
    feet = [f for _n, f in fr.feet]
    if getattr(ex, "poles", None) is not None:  # own looks: nothing stands on an electricity pole's foot
        feet += [shapely.Point(x, y).buffer(0.4, quad_segs=2) for x, y, _rid in ex.poles.poles]
    occupied = [b.footprint.buffer(0.5) for b in bl.blocks] + [g.buffer(0.5) for g in ex.ground_cut] + \
        [s.footprint.buffer(0.5) for s in ex.stations] + \
        [shapely.Polygon(r).buffer(0.8) for r in (ex.viaduct.pier_boxes if ex.viaduct else [])] + \
        [shapely.LineString([p, q]).buffer(0.5) for p, q in ex.boundary]
    markets, hospitals = _markets_hospitals(proj, osm, areas, ex)
    rp = [proj.to_render(a, b) for a, b in route]
    # the street life's own view model is on the flat city (its props at GROUND_Z): the spawns at their flat height
    views = [dict(s, z=tiles.GROUND_Z + 1.0) for s in spawn_points(proj, route)] + VIEWPOINTS
    return streetlife.build(model, L, pav, med, planted, ground_u, occupied, proj, areas, details, markets, hospitals,
                            rp, views, ex.viaduct.footprint(0.0) if ex.viaduct else None,
                            outer.buffer(-furniture.EDGE_KEEP), feet, street_budgets(),
                            (VIEW_H, VIEW_FOV), fixed=breakable_costs(fr))


def breakable_costs(fr):
    """The breakable poles as the street life's fixed instances (tools/citymap/breakables.py): where they stand, their
    info radius and their slot-0 model's numbers."""
    out = []
    for b in getattr(fr, "breakables", []):
        m = breakables.model_stats(b.role)
        out.append({"x": b.x, "y": b.y, "z": b.z, "radius": breakables.info_radius(b.role, VIEW_H), "tris": m["tris"],
                    "meshes": m["meshes"], "density": m["density"]})
    return out


def breakable_entry(b):
    """A breakable pole as scenery_write.make_section's props entry (with its hierarchy): its slot-0 model by hash,
    its info radius (draw distance), its model's box, the matrix (its model's x axis at b.heading; foot on the built
    ground), breakables.INSTANCE_FLAGS."""
    rows = prop_axes(b.heading)
    m = tuple(tuple(_q(v) for v in r) + (0.0,) for r in rows) + \
        ((b.x, b.y, terrain.ground_z(b.x, b.y) + b.z, 1.0),)
    name = "FTB_" + b.role.upper()
    return (name, (breakables.solid_hash(b.role), 0, 0, 0), breakables.info_radius(b.role, VIEW_H),
            tuple(breakables.model_stats(b.role)["box"]), m, breakables.INSTANCE_FLAGS, breakables.hierarchy(b.role))


def platforms(ex):
    """[(polygon, height, texture kind, surface)] of the climbable platforms besides the pavements: the medians'
    tops (planted: grass, the off-road feel; railing medians: paving, concrete as Rockport's sidewalks)."""
    fr = getattr(ex, "furniture", None)
    if fr is None:
        return []
    return [(m.polygon, furniture.MEDIAN_H, "grass" if m.kind == "planted" else "pavement",
             "grass" if m.kind == "planted" else "concrete") for m in fr.medians]


def tex_name(kind):
    return textures.NAMES.get(kind, kind)


def _texture_pack(photos):
    """(the pack, {texture name: far atlas uv}): our drawn textures, the photo textures and the far atlas."""
    import numpy as np
    drawn = textures.draw()
    texs = [texpack.new_texture(textures.NAMES[k], side, side, px, encode=phototex.encode_list)
            for k, (side, px) in drawn.items()]
    means = {textures.NAMES[k]: textures.far_mean(k, side, px) for k, (side, px) in drawn.items()}
    for name, (w, h, arr) in sorted(photos.items()):
        texs.append(texpack.new_texture(name, w, h, [tuple(p) for p in arr.reshape(-1, 3).tolist()],
                                        encode=phototex.encode_list))
        means[name] = arr.reshape(-1, 3).astype(float).mean(0)
    side, px, far_uv = textures.far_atlas(means)
    texs.append(texpack.new_texture(textures.FAR_NAME, side, side, px, encode=phototex.encode_list))
    return texpack.new_pack(TEXTURE_PACK_NAME, TEXTURE_PACK_FILE, texs), far_uv


def _kinds(T, inst, base):
    """The texture kinds a tile's instance draws: the streets' own first (their order as before), then the others
    sorted by name."""
    have = {k for (i, _lv, k) in T.groups.g if i == inst}
    return [k for k in base if k in have] + sorted(have - set(base))


def _solid(name, T, inst, levels_, kinds):
    cx, cy = T.centre
    oc = terrain.offset(cx, cy)
    groups = []
    for kind in kinds:
        for lv in levels_:
            e = T.groups.g.get((inst, lv, kind))
            if e:
                tris = [tuple((p[0] - cx, p[1] - cy, p[2] + terrain.offset(p[0], p[1]) - oc) for p in t)
                        for t in e[0]]
                groups.append((bstringhash(tex_name(kind)), tex_name(kind), tris, e[1], e[2]))
                break
    if not groups:
        return None
    return solids.make_solid_multi(name, groups)


def _far_solid(name, T, inst, far_uv):
    """The far model of a tile's instance (Run H fixes, fault 4): its C level (no markings, kerbs, furniture or
    detail) in one texture, the far atlas, each triangle on its own texture's cell: one mesh per 1,000 triangles."""
    cx, cy = T.centre
    oc = terrain.offset(cx, cy)
    tris, uvs, cols = [], [], []
    for (i, lv, kind), e in sorted(T.groups.g.items()):
        if i != inst or lv != "C":
            continue
        uv = far_uv[tex_name(kind)]
        tris += [tuple((p[0] - cx, p[1] - cy, p[2] + terrain.offset(p[0], p[1]) - oc) for p in t) for t in e[0]]
        uvs += [(uv, uv, uv)] * len(e[0])
        cols += e[2]
    if not tris:
        return None
    return solids.make_solid_multi(name, [(bstringhash(textures.FAR_NAME), textures.FAR_NAME, tris, uvs, cols)])


def far_density(radius, switch=None):
    """The Density a near model needs for the game to switch to the far model at `switch` m (tiles.FAR_SWITCH):
    DrawAScenery (0x729120) takes slot 2 when the distance is 25 m or more and pixel size / max(Density, 6) < 8.7,
    pixel size = R H / (d - R), R = the info radius + 6, H = VIEW_H (the PC code, read: constants 6.0 at 0x8B27E0,
    25.0 at 0x8B27E4, 8.7 at 0x8B27F0; Density is read nowhere else)."""
    switch = tiles.FAR_SWITCH if switch is None else switch
    R = radius + 6.0
    return R * VIEW_H / (8.7 * (switch - R))


def _set_density(so, density):
    h = bytearray(so.header)
    struct.pack_into("<f", h, 0x9C, density)
    so.header = bytes(h)


def _tile_solids(T, far_uv=None):
    """{level: WorldSolid} for the ground and buildings instances of a tile (with far_uv also their far models, gF
    and bF)."""
    tag = "%02d_%03d" % (T.i, T.j)
    out = {}
    gk, bk = _kinds(T, "ground", GROUND_KINDS), _kinds(T, "build", BUILD_KINDS)
    out["gA"] = _solid("FTC_G_%s_A" % tag, T, "ground", ("A",), gk)
    out["gC"] = _solid("FTC_G_%s_C" % tag, T, "ground", ("C",), gk)
    out["bA"] = _solid("FTC_B_%s_A" % tag, T, "build", ("A",), bk)
    # the street life's parked vehicles (tools/citymap/streetlife.py): their own instance, near only
    out["vA"] = _solid("FTV_%s" % tag, T, "veh", ("A",), ["vehicles"])
    # the far level (the landmarks plan's Task 7): without the detail parts (parts.DETAIL: canopies, signs, columns,
    # stairs, pier caps, parapets' inner faces, the mural, boundary walls); only where the tile has such detail
    def tris(lv):
        return sum(len(e[0]) for (i, l_, _k), e in T.groups.g.items() if i == "build" and l_ == lv)
    if out["bA"] is not None and tris("C") < tris("A"):
        out["bC"] = _solid("FTC_B_%s_C" % tag, T, "build", ("C",), bk)
    if far_uv is not None:
        out["gF"] = _far_solid("FTC_G_%s_F" % tag, T, "ground", far_uv) if out["gA"] is not None else None
        out["bF"] = _far_solid("FTC_B_%s_F" % tag, T, "build", far_uv) if out["bA"] is not None else None
    return {k: v for k, v in out.items() if v is not None}


def _canon(t):
    """A triangle by its vertices from the smallest, keeping the winding (stripify may rotate a strip's first)."""
    k = t.index(min(t))
    return t[k:] + t[:k]


def _phys_face(t):
    return tuple(to_physics((p[0], p[1], p[2] + terrain.ground_z(p[0], p[1]))) for p in t)


def _phys_barrier(a, b, lo, hi, *flags):
    A = to_physics((a[0], a[1], 0.0))
    Bp = to_physics((b[0], b[1], 0.0))
    # a barrier is a level box: its bottom on the lower end's ground, its top over the higher end's (the elevation)
    oa, ob = terrain.offset(*a), terrain.offset(*b)
    return ((A[0], A[2]), (Bp[0], Bp[2]), lo + tiles.GROUND_Z + min(oa, ob), hi + tiles.GROUND_Z + max(oa, ob)) + \
        tuple(flags)


MULTI_LEVEL = 0x04  # face surface flags: the wheels' query looks on past this face (collision_write._article)


def _plane_z(t, x, y):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return az if nz == 0 else az - (nx * (x - ax) + ny * (y - ay)) / nz


def face_flags(T, elevated_near=None):
    """One flags byte per face of tile T (T.faces order): MULTI_LEVEL (fault 1, docs/ftown-notes.md "City fixes") on
    every face of the elevated surface (a vertex more than 0.2 m up: decks and ramps, so slivers between them count
    too) and on every pair of faces whose (x, y) footprints overlap with their planes more than 2 cm apart there (the
    ground under the elevated surface, and the slivers where a pavement overlaps a road); 0 elsewhere. A tile's faces
    lie inside the tile, so their partners are in the same tile. elevated_near: the elevated surface grown by 5 cm;
    a face reaching into it is flagged too (the pack stores vertices to 1/128 m, so a pavement sliver that only
    touches a deck's edge in the builder can overlap it by a centimetre in the written file)."""
    n = len(T.faces)
    flags = [MULTI_LEVEL if max(p[2] for p in t) > 0.2 else 0 for t, _s in T.faces]
    if not n:
        return flags
    polys = shapely.polygons([[(p[0], p[1]) for p in t] for t, _s in T.faces])
    if elevated_near is not None:
        E = elevated_near.intersection(tiles.tile_box(T.i, T.j))
        if not E.is_empty:
            for k, ar in enumerate(shapely.area(shapely.intersection(polys, E))):
                if ar > 1e-6:
                    flags[k] = MULTI_LEVEL
    if n < 2:
        return flags
    i, j = shapely.STRtree(polys).query(polys, predicate="intersects")
    keep = i < j
    i, j = i[keep], j[keep]
    if not len(i):
        return flags
    inter = shapely.intersection(polys[i], polys[j])
    area = shapely.area(inter)
    for a, b, ar, g in zip(i, j, area, inter):
        if ar <= 1e-8:
            continue
        c = g.representative_point()
        ta, tb = T.faces[a][0], T.faces[b][0]
        if abs(_plane_z(ta, c.x, c.y) - _plane_z(tb, c.x, c.y)) > 0.02:
            flags[a] = flags[b] = MULTI_LEVEL
    # a sliver (under 5 cm across) touching a face whose plane is more than 2 cm off: the pack's 1/128 m vertices can
    # make the two overlap (Run H fixes: a median's sliver against the road beside it)
    thin = [k for k, (t, _s) in enumerate(T.faces) if _thin(t)]
    if thin:
        ti, tj = shapely.STRtree(polys).query(polys[thin], predicate="dwithin", distance=0.03)
        for a_, b in zip(ti, tj):
            a = thin[a_]
            if a == b:
                continue
            c = polys[a].centroid
            if abs(_plane_z(T.faces[a][0], c.x, c.y) - _plane_z(T.faces[b][0], c.x, c.y)) > 0.02:
                flags[a] = flags[b] = MULTI_LEVEL
    return flags


def _thin(t, across=0.05):
    """A triangle less than `across` metres high over its longest side (its plan)."""
    (ax, ay, _), (bx, by, _), (cx, cy, _) = t
    area2 = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))
    longest = max(math.dist((ax, ay), (bx, by)), math.dist((bx, by), (cx, cy)), math.dist((cx, cy), (ax, ay)))
    return longest > 0 and area2 / longest < across


def _density(so):
    return struct.unpack_from("<f", so.header, 0x9C)[0]


def views(entries, spawns):
    """The draw load of the main view from each spawn (see VIEW_FOV, VIEW_H), from the instances' positions and radii,
    their models' meshes, triangles and density."""
    out = []
    for sp in spawns:
        ex, ey, ez = sp["x"], sp["y"], sp["z"] + 0.5
        h = math.radians(sp["heading"])
        fx, fy = math.cos(h), math.sin(h)
        inst = meshes = tris = high = low = props = 0
        for e in entries:
            dx, dy, dz = e["pos"][0] - ex, e["pos"][1] - ey, e["pos"][2] - ez
            R = e["radius"] + 6.0
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            ahead = dx * fx + dy * fy
            if ahead < -R:
                continue
            if d > R:
                ang = math.degrees(math.acos(max(-1.0, min(1.0, ahead / max(1e-6, math.hypot(dx, dy))))))
                if ang - math.degrees(math.asin(min(1.0, R / d))) > VIEW_FOV / 2:
                    continue
            px = VIEW_H if d - R <= R else R * VIEW_H / (d - R)
            if int(px) <= 0x11:
                continue
            m0 = e["models"][0]
            use = m0
            if m0["tris"] > 39 and (px / max(6.0, m0["density"])) < 8.7:
                use = e["models"][2]
            if use is None:
                continue
            inst += 1
            props += bool(e.get("prop"))
            meshes += use["meshes"]
            tris += use["tris"]
            if use is m0:
                high += 1
            else:
                low += 1
        out.append({"name": sp["name"], "instances": inst, "meshes": meshes, "triangles": tris, "high": high,
                    "low": low, "props": props})
    return out


def grid_tags(pack_instances):
    """FTownLoader's registration modelled: every cell whose 64 m square the instance's (x, z) circle grown by 64 m
    touches, indices clamped as WGrid::GetRowCol (notes "Part 2: the slab and FTownLoader")."""
    cells = {}
    g = GRID
    for (x, z), r in pack_instances:
        rr = r + g["margin"]
        c0 = int((x - rr - g["min_x"]) // g["edge"])
        c1 = int((x + rr - g["min_x"]) // g["edge"])
        r0 = int((z - rr - g["min_z"]) // g["edge"])
        r1 = int((z + rr - g["min_z"]) // g["edge"])
        seen = set()
        for c in range(c0, c1 + 1):
            for rw in range(r0, r1 + 1):
                key = (min(g["rows"] - 1, max(0, rw)), min(g["cols"] - 1, max(0, c)))
                if key in seen:
                    continue
                seen.add(key)
                cells[key] = cells.get(key, 0) + 1
    vals = sorted(cells.values())
    return {"instances": len(pack_instances), "entries": sum(vals), "cells": len(vals), "max": max(vals),
            "median": int(statistics.median(vals))}


def assemble(parts):
    """[(kind, model)] -> top-level chunks: the texture pack at 0, scenery sections at multiples of 16 (an 8- or
    16-byte padding chunk before one when needed), the rest where they fall (their writers align their own data)."""
    out, pos = [], 0
    for kind, part in parts:
        if kind == "scenery" and pos % 16:
            gap = (-pos) % 16
            if gap < 8:
                gap += 16
            out.append(Chunk(0, bytes(gap - 8)))
            pos += gap
        if kind == "tex":
            if pos:
                raise ValueError("the texture pack goes first")
            c = texpack.write_pack(part, pos + 8)
        elif kind == "solids":
            c = solids.write_list(part, pos + 8)
        elif kind == "scenery":
            c = scenery_write.write_section(part, pos + 8)
        else:
            c = collision_write.write_pack(part, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return out


def build(area, out_path, plain=False):
    photos = face_textures()
    proj, model, L, bl, city, route = geometry(area, photos, plain)
    tex, far_uv = _texture_pack(photos)
    districts = {}
    i0 = min(i for i, _j in city.tiles)
    j0 = min(j for _i, j in city.tiles)
    for (i, j), T in sorted(city.tiles.items()):
        districts.setdefault(((j - j0) // DISTRICT[1], (i - i0) // DISTRICT[0]), []).append(T)
    if len(districts) > len(NUMBERS):
        raise ValueError("%d districts, %d numbers" % (len(districts), len(NUMBERS)))
    # the street life's X0 instances by district (tools/citymap/streetlife.py; X0's models by name hash only)
    sl = getattr(city, "streetlife", None)
    sl_by_district, sl_dropped = {}, 0
    for p in (sl.props if sl else []):
        i, j = math.floor(p.x / tiles.TILE), math.floor(p.y / tiles.TILE)
        key = ((j - j0) // DISTRICT[1], (i - i0) // DISTRICT[0])
        if key in districts:
            sl_by_district.setdefault(key, []).append(p)
        else:
            sl_dropped += 1
    # the breakable poles by district (tools/citymap/breakables.py), each its own instance after the street life's
    fr = getattr(getattr(city, "extras", None), "furniture", None)
    bk_by_district, bk_dropped = {}, 0
    for b in (getattr(fr, "breakables", []) if fr is not None else []):
        i, j = math.floor(b.x / tiles.TILE), math.floor(b.y / tiles.TILE)
        key = ((j - j0) // DISTRICT[1], (i - i0) // DISTRICT[0])
        if key in districts:
            bk_by_district.setdefault(key, []).append(b)
        else:
            bk_dropped += 1
    lantern_done = False
    smk_packs, smk_entries, smk_kinds = [], [], {}
    lists, sceneries, packs, tile_info, entries, pack_inst = [], [], [], [], [], []
    near = L.elevated.buffer(0.05)
    numbers = []
    totals = {"triangles_A": 0, "triangles_C": 0, "meshes_A": 0, "meshes_C": 0, "solids": 0, "faces": 0,
              "barriers": 0, "collision_instances": 0}
    ident = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
    for n, key in enumerate(sorted(districts)):
        number = NUMBERS[n]
        numbers.append(number)
        sol, models, faces, fsurf, fflags, bars = [], [], [], [], [], []
        for T in districts[key]:
            ts = _tile_solids(T, far_uv)
            cx, cy = T.centre
            mat = ident + ((cx, cy, terrain.ground_z(cx, cy), 1.0),)
            tag = "%02d_%03d" % (T.i, T.j)
            rec = {"tile": tag, "meshes_A": 0, "triangles_A": 0}
            for k in ("g", "b"):
                a = ts.get(k + "A")
                if a is None:
                    continue
                # the far model (Run H fixes, fault 4) in slot 2 (the main view beyond FAR_SWITCH) and slot 3 (the
                # shadow and reflection views, for instances without the terrain bit 0x80: DrawAScenery,
                # Scenery.cpp:721); the C level is the far model's source and no longer written itself
                c = ts.get(k + "F") or a
                sol += [a] if c is a else [a, c]
                models.append(("FTC_%s_%s" % (k.upper(), tag), (a.name_hash, a.name_hash, c.name_hash, c.name_hash),
                               mat, tiles.GROUND_FLAGS if k == "g" else tiles.BUILDING_FLAGS))
                rec["meshes_A"] += len(a.meshes)
                rec["triangles_A"] += struct.unpack_from("<h", a.header, 0x14)[0]
                totals["meshes_A"] += len(a.meshes)
                totals["meshes_C"] += len(c.meshes)
                totals["triangles_A"] += struct.unpack_from("<h", a.header, 0x14)[0]
                totals["triangles_C"] += struct.unpack_from("<h", c.header, 0x14)[0]
            v = ts.get("vA")
            if v is not None:
                # drawn VEHICLE_DRAW from the tile's middle (the info radius below), nothing far or in the shadow and
                # reflection views (slots 1-3 empty, as the X0 instances)
                sol.append(v)
                models.append(("FTV_%s" % tag, (v.name_hash, 0, 0, 0), mat, tiles.GROUND_FLAGS))
            tile_info.append(rec)
            ordered = stripify.order([t for t, _s in T.faces])
            surf_of = {_canon(t): s for t, s in T.faces}
            flag_of = {_canon(t): f for (t, _s), f in zip(T.faces, face_flags(T, near))}
            faces += [_phys_face(t) for t in ordered]
            fsurf += [vlt32(surf_of[_canon(t)]) for t in ordered]
            fflags += [flag_of[_canon(t)] for t in ordered]
            bars += [_phys_barrier(*b) for b in T.barriers]
        bks = bk_by_district.get(key, [])
        if not lantern_done and any(b.role == "lantern" for b in bks):
            sol.append(breakables.lantern_solid())  # one solid of ours, named by every lantern instance
            lantern_done = True
        by_hash = {s.name_hash: s for s in sol}
        props = [prop_entry(p) for p in sl_by_district.get(key, [])]
        first_bk = len(models) + len(props)
        bk_entries = [breakable_entry(b) for b in bks]
        props += bk_entries
        sc = scenery_write.make_section(number, models, by_hash, props=props)
        if bks:
            recs = []
            for k, (b, e) in enumerate(zip(bks, bk_entries)):
                inst_no = first_bk + k
                inst = sc.instances[inst_no]
                if inst.matrix[3][:3] != tuple(float(v) for v in e[4][3][:3]):
                    raise ValueError("breakable pole %d of section %d is not its instance" % (k, number))
                uid = breakables.FIRST_UID + len(smk_entries)
                rec = breakables.record(b, inst.matrix[3][:3], smackables.ROCKPORT_OVERRIDES + len(smk_entries), uid)
                smk_entries.append((number, inst_no, breakables.OVERRIDE_FLAGS))
                smk_kinds[b.role] = smk_kinds.get(b.role, 0) + 1
                recs.append(rec)
            smk_packs.append((number, breakables.FIRST_UID + len(smk_entries) - len(recs), recs))
        for model_, info in zip(models, sc.infos):
            # forged only for compact instances: within 2R the game's pixel size is H itself, and a large R needs a
            # Density that would send the model far even there for a smaller H (the review: H < 8.7 Density)
            if model_[1][2] != model_[1][0] and info.radius + 6.0 < tiles.FAR_SWITCH / 3.0:
                _set_density(by_hash[model_[1][0]], far_density(info.radius))
            if model_[0].startswith("FTV_"):
                # the info radius stays the farthest vertex (the game's "behind" test needs it: the review); the
                # solid's Density sets the stop at VEHICLE_DRAW from the tile's middle
                _set_density(by_hash[model_[1][0]], streetlife.vehicle_density(info.radius, VIEW_H))
        for model_, info, inst in zip(models, sc.infos, sc.instances):
            ms = []
            for h in model_[1]:
                so = by_hash.get(h)
                ms.append(None if so is None else {"meshes": len(so.meshes), "density": _density(so),
                                                   "tris": struct.unpack_from("<h", so.header, 0x14)[0]})
            entries.append({"pos": inst.matrix[3][:3], "radius": info.radius, "models": ms,
                            "prop": model_[0].startswith("FTV_")})
        lib = x0props.library()
        lan = breakables.lantern_stats() if lantern_done else None
        for inst in sc.instances[len(models):]:
            info = sc.infos[inst.info_index]
            m0 = lan if info.solid_hashes[0] == breakables.solid_hash("lantern") else lib[info.solid_hashes[0]]
            entries.append({"pos": inst.matrix[3][:3], "radius": info.radius, "prop": True,
                            "models": [m0, None, None, None]})
        pack = collision_write.make_pack(number, faces, bars, tile=tiles.TILE, face_surfaces=fsurf, face_flags=fflags)
        for ci in pack.instances:
            pack_inst.append(((-ci.t[0], -ci.t[2]), ci.radius))
        totals["solids"] += len(sol)
        totals["faces"] += len(faces)
        totals["barriers"] += len(bars)
        totals["multi_level_faces"] = totals.get("multi_level_faces", 0) + sum(1 for f in fflags if f)
        totals["collision_instances"] += len(pack.instances)
        lists.append(solids.new_list(sol, "FTown_City_%d.bin" % number, ""))
        sceneries.append(sc)
        packs.append(pack)
    parts = [("tex", tex)] + [("solids", x) for x in lists] + [("scenery", x) for x in sceneries] + \
        [("collision", x) for x in packs]
    top = assemble(parts)
    if len(top) > 64:
        raise ValueError("%d top-level chunks: UnloadChunks keeps 64" % len(top))
    data = write_chunks(top)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    # the evening's lights list beside the city (tools/citymap/evening.py; FTownLoader [Evening] Lights)
    lights_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "ftown-evening.bin")
    lights = evening.write_lights(data, lights_path)
    # the breakable poles' spawner records beside the city (tools/world/smackables.py; FTownLoader [Breakables] File)
    smk_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "ftown-smackables.bun")
    smk = smackables.write_file(smk_packs, smk_entries) if smk_entries else None
    if smk is not None:
        if len(smk_entries) > smackables.MAX_RECORDS:
            raise ValueError("%d breakable poles: the game keeps %d smackables" % (len(smk_entries),
                                                                                 smackables.MAX_RECORDS))
        with open(smk_path, "wb") as f:
            f.write(smk)
    elif os.path.exists(smk_path):
        os.remove(smk_path)
    spawns = spawn_points(proj, route)
    x0, y0, x1, y1 = city.outer.bounds
    info = {
        "name": "F-Town", "file": os.path.basename(out_path), "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "top_level_chunks": len(top), "sections": numbers,
        "packs": numbers, "tile_m": tiles.TILE, "district_tiles": DISTRICT, "tiles_count": len(city.tiles),
        "instances": len(entries), "edge_box": [x0, y0, x1, y1], "spawns": spawns,
        "roads": len(model.roads), "junctions": len(model.junctions()),
        "raised_chains": [{"name": c.name, "length_m": round(c.length, 1)} for c in L.raised_chains],
        "buildings": {"blocks": len(bl.blocks), "trimmed": bl.trimmed, "dropped": bl.dropped_on_road +
                      bl.dropped_outside + bl.dropped_slivers},
        "grid": grid_tags(pack_inst), "views": views(entries, spawns + viewpoints()), "totals": totals,
        "terrain": {k: terrain.model()[k] for k in ("model", "dz_dx", "dz_dy", "anchor")},
        "licence": "Map data (c) OpenStreetMap contributors (ODbL)",
        "evening": {"file": os.path.basename(lights_path), "bytes": os.path.getsize(lights_path),
                    "vertices": lights, "panes": getattr(city, "panes_added", 0),
                    "panes_skipped": getattr(city, "panes_skipped", 0), "deck_lamps": getattr(city, "lamps_added", 0),
                    "deck_lamps_skipped": getattr(city, "lamps_skipped", 0)},
    }
    if smk is not None:
        info["breakables"] = {"file": os.path.basename(smk_path), "bytes": len(smk),
                              "sha256": hashlib.sha256(smk).hexdigest(), "records": len(smk_entries),
                              "packs": len(smk_packs), "kinds": dict(sorted(smk_kinds.items())), "dropped": bk_dropped,
                              "override_base": smackables.ROCKPORT_OVERRIDES}
    if sl is not None:
        info["streetlife"] = {"counts": sl.counts, "instances": len(sl.props) - sl_dropped, "dropped": sl_dropped,
                              "vehicles": len(sl.vehicles), "thinned": sl.thinned, "on_median": sl.on_median}
        # Run I fixes, item 1: where the parked cars stood, for tools/citymap/traffic_spots.py (x, y, heading deg)
        info["parking_bays"] = [[round(x, 2), round(y, 2), round(math.degrees(h), 1)] for x, y, h in sl.bays]
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "ftown-city.json"), "w", newline="\n") as f:
        json.dump(info, f, indent=1)
    info["tiles"] = tile_info
    if sl is not None:
        info["streetlife"]["vehicles"] = [(k, v, x, y, terrain.ground_z(x, y) + z, hd)
                                          for k, v, x, y, z, hd in sl.vehicles]
    return info


def main(argv):
    plain = "--plain" in argv
    argv = [a for a in argv if a != "--plain"]
    if len(argv) != 2:
        print(__doc__)
        return 1
    info = build(argv[0], argv[1], plain)
    print(json.dumps({k: v for k, v in info.items() if k != "tiles"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
