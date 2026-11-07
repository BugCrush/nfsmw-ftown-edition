"""F-Town's buildings, ground and edge (render metres, x east, y north).

- blocks(osm, proj, road_polys, seed, areas, model): every OSM building (ways from osm.json, multipolygon relations from
  areas.json) as a block on its real footprint, trimmed by the roads, pavements and ramps (road_polys) plus TRIM_GAP
  (so no wall stands on a road); a part under MIN_PART (10 m2) is dropped. Heights (the design's estimates, calls in
  docs/ftown-notes.md "Stage 2: the streets"): building:levels x STOREY (3.2 m) when tagged; otherwise a commercial
  building (more than 400 m2 of footprint and within 30 m of a tertiary-or-larger road) 4-8 storeys, a house 2-4;
  the number of storeys drawn per OSM id from `seed` (the same city every build). Walls are barriers.
- ground(proj, bbox, areas, cut): the area's box plus EDGE_MARGIN (50 m) as flat ground: grass where OSM has a park,
  garden, pitch, grass or wood, earth elsewhere (water too: the ground is flat), less `cut` (roads and buildings: nothing
  is drawn twice).
- edge_barriers(proj, bbox): walls EDGE_HEIGHT (3 m) tall round that box in pieces of EDGE_PIECE metres, counter-
  clockwise, each starting where the last ended (the design: the edge of the area is closed).
"""
import math
import os
import random
import sys
from dataclasses import dataclass

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import roadmodel  # noqa: E402

STOREY = 3.2
MIN_PART = 10.0
TRIM_GAP = 0.25
COMMERCIAL_AREA = 400.0
COMMERCIAL_REACH = 30.0
EDGE_MARGIN = 50.0
EDGE_HEIGHT = 3.0
EDGE_PIECE = 50.0
GRASS = {"leisure": {"park", "garden", "pitch", "playground", "golf_course", "recreation_ground"},
         "landuse": {"grass", "recreation_ground", "meadow", "village_green", "forest", "orchard", "farmland"},
         "natural": {"grassland", "scrub", "wood", "heath", "wetland"}}


@dataclass
class Block:
    osm_id: int
    footprint: Polygon
    height_m: float
    kind: str  # "tagged", "commercial", "house"
    source_area: float
    style: object = None  # Style (styles(), the landmarks stage), or None: the plain look


# --- the landmarks stage: ordinary buildings styled after the photos (docs/ftown-notes.md "Landmarks and street
# furniture") ---
# plain wall areas of the photos (the design's numbers; rectangles in their pixels: x0, y0, x1, y1): house and market
# walls in plaster (photo 01 the tower by Ambedkar Marg, 03 the market's tall block, 05 a house by the market, 06 and 08
# market rows, 11 a market block); their mean colours give the palette's hues and relative lightness
PALETTE_SOURCES = [(1, (613, 354, 750, 600)), (3, (109, 545, 273, 982)), (5, (695, 273, 804, 491)),
                   (6, (205, 723, 341, 818)), (8, (218, 529, 409, 638)), (11, (518, 474, 655, 665))]
# a tint multiplies a wall's vertex grey: its lightness relative to the palette's mean, held in LIGHT_RANGE, and its hue
# at most TINT_CHROMA off grey per channel (the city fixes: Rockport's walls are grey, ours were too yellow; the plaster
# tints' vertex colours stay within 6 of grey, test_city)
LIGHT_RANGE = (0.88, 1.06)
TINT_CHROMA = 0.04
# measured by palette_from_photos() (test_styles checks it still is), rounded to 3 places
PALETTE = [(0.895, 0.879, 0.845), (1.092, 1.052, 1.018), (0.914, 0.91, 0.871), (1.067, 1.065, 1.018),
           (0.968, 0.923, 0.924), (0.88, 0.896, 0.889)]
PARAPET = 0.9  # m: the walls carried over the roof (the roof stays at the building's height)
SHOP_BAND = 3.2  # m: a market block's ground storey of shop fronts
BOUNDARY_H = 1.5
GATE_GAP = 3.0
SETBACK = (1.4, 8.0)  # m between a house's front and the road (with its pavement) for a boundary wall
MARKET_WORDS = ("market", "bazaar")


# own looks (docs/ftown-notes.md "Own looks and a lived-in city (2026-11-04)"): the houses' colours, chosen by eye from
# the photos of Sector 15/16's houses and markets (05, 06, 08, 11, 13: cream, salmon, pale yellow, light grey,
# off-white, pale green, sky blue, dusty pink, ochre, peach), muted so a wall's vertex colour stays within 14 of grey
# (test_houses.test_tints_muted); the atlas's plaster is a light neutral, the tint gives the colour
# (the review fixes, 2026-11-05: each channel divided by its mean over the tints, so the mean tint is grey within 1%;
# it was R 1.056 G 1.018 B 0.973, 8% warm; the sky blue kept as it was, the 14-of-grey rule)
HOUSE_TINTS = [(1.06, 1.04, 0.96), (1.08, 0.98, 0.96), (1.06, 1.07, 0.94), (0.96, 1.00, 1.04), (1.03, 1.07, 1.09),
               (0.94, 1.07, 1.00), (0.95, 1.01, 1.12), (1.07, 0.97, 1.04), (1.04, 1.00, 0.92), (1.08, 1.01, 0.97),
               (0.94, 0.98, 1.08)]
MUMTY_SHARE, TANK_SHARE, BALCONY_SHARE = 0.6, 0.85, 0.5
MUMTY_MIN_ROOF = 40.0  # m2 of roof for a stair-head room
BALCONY_MIN_EDGE = 5.0


@dataclass
class Style:
    tint: tuple
    market: bool
    shop_edges: frozenset  # indices of the footprint's counter-clockwise exterior edges facing a road
    facade: int = 0  # FTC_HOUSES facade block (0 houses, 1 flats and commercial)
    u0: float = 0.0  # metres the facade starts into the atlas (neighbours differ)
    mumty: bool = False
    tank: bool = False
    balcony_edges: frozenset = frozenset()  # road-facing exterior edges with balconies on every upper storey


def tint_from_rgb(rgb, ref_lum):
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    rel = min(max(lum / ref_lum, LIGHT_RANGE[0]), LIGHT_RANGE[1])
    dev = [c / lum - 1.0 for c in rgb]
    m = max(abs(d) for d in dev) or 1.0
    k = min(1.0, TINT_CHROMA / m)
    return tuple(round(float(rel * (1.0 + d * k)), 3) for d in dev)


def palette_from_photos(photos_dir=None):
    """The palette from PALETTE_SOURCES' mean colours, or None without the photos."""
    from tools.citymap import landmarks
    photos_dir = photos_dir or landmarks.PHOTOS
    files = landmarks.photo_files(photos_dir)
    if not files:
        return None
    import numpy as np
    from PIL import Image
    means = []
    for n, (x0, y0, x1, y1) in PALETTE_SOURCES:
        with Image.open(os.path.join(photos_dir, files[n])) as im:
            a = np.asarray(im.convert("RGB"), dtype=float)[y0:y1, x0:x1]
        means.append(tuple(a.reshape(-1, 3).mean(0)))
    ref = sum(0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2] for m in means) / len(means)
    return [tint_from_rgb(m, ref) for m in means]


def _faces_road(p, q, lanes, reach):
    import math
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy) or 1.0
    n = (dy / L, -dx / L)
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    return lanes.intersects(LineString([(mid[0] + n[0] * 0.3, mid[1] + n[1] * 0.3),
                                        (mid[0] + n[0] * reach, mid[1] + n[1] * reach)]))


def styles(blocks, model, lanes, market_polys=(), seed=1):
    """Gives every block its Style: a palette tint drawn per OSM id (the same city every build); market blocks (inside
    an OSM commercial or retail area, or within 25 m of a road named a market or bazaar) get shop fronts on the edges
    facing a road within 12 m. lanes: the carriageways and pavements."""
    from shapely.geometry.polygon import orient
    shapely.prepare(lanes)
    mk = unary_union(list(market_polys)) if market_polys else Polygon()
    named = [LineString(r.points) for r in model.roads
             if r.name and any(w in r.name.lower() for w in MARKET_WORDS)]
    near_named = unary_union([ln.buffer(25.0) for ln in named]) if named else Polygon()
    shapely.prepare(mk)
    shapely.prepare(near_named)
    for b in blocks:
        rng = random.Random(seed * 7919 + b.osm_id)
        tint = HOUSE_TINTS[rng.randrange(len(HOUSE_TINTS))]
        market = mk.intersects(b.footprint.representative_point()) or near_named.intersects(b.footprint)
        edges, balc = set(), set()
        pts = list(orient(b.footprint, 1.0).exterior.coords)
        house = b.kind == "house"
        want_balc = house and rng.random() < BALCONY_SHARE
        for k, (p, q) in enumerate(zip(pts, pts[1:])):
            L = math_dist(p, q)
            if market and L >= 3.0 and _faces_road(p, q, lanes, 12.0):
                edges.add(k)
            elif want_balc and L >= BALCONY_MIN_EDGE and _faces_road(p, q, lanes, 12.0):
                balc.add(k)
        facade = 1 if not house or rng.random() < 0.3 else 0
        u0 = rng.uniform(0.0, 16.0)
        mumty = house and b.footprint.area >= MUMTY_MIN_ROOF and rng.random() < MUMTY_SHARE
        tank = rng.random() < TANK_SHARE
        b.style = Style(tint, market, frozenset(edges), facade, round(u0, 3), mumty, tank, frozenset(balc))
    return blocks


def math_dist(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def market_areas(proj, osm, areas):
    """OSM landuse commercial and retail areas (render polygons)."""
    out = []
    for src in (osm, areas):
        for e in (src or {}).get("elements", []):
            t = e.get("tags", {})
            if t.get("landuse") in ("commercial", "retail") and e["type"] == "way" and len(e.get("geometry", [])) >= 4:
                out.append(_clean(Polygon(_ring(proj, e["geometry"]))))
    return [g for g in out if not g.is_empty]


def boundary_walls(blocks, model, lanes, gates, others):
    """[(p, q)] 1.5 m walls before houses on residential lanes (the design: houses' boundary walls and gates): for each
    house edge (4 m or longer) facing a residential or living street road within SETBACK, a wall parallel to it 0.6 m
    short of the road and pavement, cut 0.3 m clear of them and of every building (others), a GATE_GAP gap where an OSM
    gate node lies within 6 m of it."""
    import math
    from shapely.geometry.polygon import orient
    lanes_c = lanes.buffer(0.3)
    shapely.prepare(lanes_c)
    res_lines = [LineString(r.points) for r in model.roads if r.kind in ("residential", "living_street")]
    res_tree = shapely.STRtree(res_lines) if res_lines else None
    gate_pts = [Point(g) for g in gates]
    gtree = shapely.STRtree(gate_pts) if gate_pts else None
    oth = others.buffer(0.3)
    shapely.prepare(oth)
    out = []
    for b in blocks:
        if b.kind != "house":
            continue
        pts = list(orient(b.footprint, 1.0).exterior.coords)
        for p, q in zip(pts, pts[1:]):
            L = math.dist(p, q)
            if L < 4.0:
                continue
            n = ((q[1] - p[1]) / L, -(q[0] - p[0]) / L)
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            probe = LineString([(mid[0] + n[0] * 0.2, mid[1] + n[1] * 0.2),
                                (mid[0] + n[0] * SETBACK[1], mid[1] + n[1] * SETBACK[1])])
            if res_tree is None or not len(res_tree.query(probe, predicate="intersects")):
                continue
            hit = probe.intersection(lanes)
            if hit.is_empty:
                continue
            gap = Point(mid).distance(hit) if hit.geom_type != "Point" else Point(mid).distance(hit)
            if gap < SETBACK[0]:
                continue
            off = gap - 0.6
            a = (p[0] + n[0] * off, p[1] + n[1] * off)
            c = (q[0] + n[0] * off, q[1] + n[1] * off)
            seg = LineString([a, c]).difference(lanes_c).difference(oth)
            if gtree is not None:
                for k in gtree.query(LineString([a, c]).buffer(6.0)):
                    g = gate_pts[int(k)]
                    s = LineString([a, c]).project(g)
                    gp = LineString([a, c]).interpolate(s)
                    seg = seg.difference(gp.buffer(GATE_GAP / 2))
            for part in getattr(seg, "geoms", [seg]):
                if part.is_empty or part.geom_type != "LineString" or part.length < 1.0:
                    continue
                cs = list(part.coords)
                out.append((cs[0], cs[-1]))
    return out

@dataclass
class Blocks:
    blocks: list
    source_ways: int
    source_relations: int
    trimmed: int
    dropped_on_road: int
    dropped_outside: int
    dropped_slivers: int

    @property
    def source_count(self):
        return self.source_ways + self.source_relations


def _ring(proj, geom):
    return [proj.to_render(p["lat"], p["lon"]) for p in geom]


def _relation_polygon(proj, rel):
    outers = [LineString(_ring(proj, m["geometry"])) for m in rel.get("members", [])
              if m["type"] == "way" and m.get("role") == "outer" and len(m.get("geometry", [])) > 1]
    inners = [LineString(_ring(proj, m["geometry"])) for m in rel.get("members", [])
              if m["type"] == "way" and m.get("role") == "inner" and len(m.get("geometry", [])) > 1]
    outer = unary_union(list(polygonize(unary_union(outers)))) if outers else Polygon()
    if inners:
        outer = outer.difference(unary_union(list(polygonize(unary_union(inners)))))
    return outer


def _clean(g):
    if g.is_empty:
        return g
    if not g.is_valid:
        g = shapely.make_valid(g)
    return g


def _parts(g):
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]


def edge_box(proj, bbox, margin=EDGE_MARGIN):
    s, w, n, e = bbox
    x0, y0 = proj.to_render(s, w)
    x1, y1 = proj.to_render(n, e)
    return box(x0 - margin, y0 - margin, x1 + margin, y1 + margin)


def _storeys(seed, osm_id, lo, hi):
    return random.Random(seed * 1000003 + osm_id).randint(lo, hi)


def blocks(osm, proj, road_polys, seed=1, areas=None, model=None, bbox=(28.385, 77.305, 28.420, 77.332)):
    """Blocks (see the module's doc)."""
    src = []
    nways = nrel = 0
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and "building" in t and len(e.get("geometry", [])) >= 4:
            nways += 1
            src.append((e["id"], t, Polygon(_ring(proj, e["geometry"]))))
    for e in (areas or {}).get("elements", []):
        t = e.get("tags", {})
        if e["type"] == "relation" and "building" in t:
            nrel += 1
            src.append((e["id"], t, _relation_polygon(proj, e)))
    outer = edge_box(proj, bbox)
    cut = road_polys.buffer(TRIM_GAP, quad_segs=4)
    shapely.prepare(cut)
    main = []
    if model is not None:
        main = [LineString(r.points).buffer(r.width_m / 2, quad_segs=4) for r in model.roads if r.kind in roadmodel.MAIN]
    tree = shapely.STRtree(main) if main else None
    out = []
    trimmed = on_road = outside = slivers = 0
    for osm_id, t, fp in src:
        fp = _clean(fp)
        if fp.is_empty or fp.area <= 0:
            slivers += 1
            continue
        area = fp.area
        inside = fp.intersection(outer)
        if inside.is_empty or inside.area < MIN_PART:
            outside += 1
            continue
        g = inside
        was_cut = cut.intersects(g)
        if was_cut:
            g = _clean(g.difference(cut))
        parts = [p for p in _parts(g) if p.area >= MIN_PART]
        if not parts:
            if was_cut:
                on_road += 1
            else:
                slivers += 1
            continue
        if was_cut:
            trimmed += 1
        lv = roadmodel._int(t.get("building:levels"))
        if lv and lv > 0:
            kind, st = "tagged", lv
        else:
            near = False
            if area > COMMERCIAL_AREA and tree is not None:
                for k in tree.query(fp.buffer(COMMERCIAL_REACH, quad_segs=2)):
                    if main[k].distance(fp) <= COMMERCIAL_REACH:
                        near = True
                        break
            kind = "commercial" if near else "house"
            st = _storeys(seed, osm_id, 4, 8) if near else _storeys(seed, osm_id, 2, 4)
        for p in parts:
            out.append(Block(osm_id, p, st * STOREY, kind, area))
    return Blocks(out, nways, nrel, trimmed, on_road, outside, slivers)


def _area_polys(proj, areas):
    out = []
    for e in (areas or {}).get("elements", []):
        t = e.get("tags", {})
        grass = any(t.get(k) in v for k, v in GRASS.items())
        if not grass:
            continue
        if e["type"] == "way" and len(e.get("geometry", [])) >= 4 and e["geometry"][0] == e["geometry"][-1]:
            out.append(_clean(Polygon(_ring(proj, e["geometry"]))))
        elif e["type"] == "relation":
            out.append(_clean(_relation_polygon(proj, e)))
    return [g for g in out if not g.is_empty]


def ground(proj, bbox, areas, cut=None, margin=EDGE_MARGIN):
    """[(Polygon, kind)] with kind "grass" or "earth" (see the module's doc)."""
    outer = edge_box(proj, bbox, margin)
    grass = unary_union(_area_polys(proj, areas)).intersection(outer) if areas else Polygon()
    earth = outer.difference(grass)
    if cut is not None:
        grass = grass.difference(cut)
        earth = earth.difference(cut)
    return [(p, "grass") for p in _parts(grass) if p.area > 0] + [(p, "earth") for p in _parts(earth) if p.area > 0]


def edge_barriers(proj, bbox, margin=EDGE_MARGIN, piece=EDGE_PIECE):
    """[((x0, y0), (x1, y1))] round the edge box, counter-clockwise (the inside on the left of each)."""
    x0, y0, x1, y1 = edge_box(proj, bbox, margin).bounds
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    out = []
    for a, b in zip(corners, corners[1:] + corners[:1]):
        L = math.dist(a, b)
        n = max(1, int(math.ceil(L / piece)))
        pts = [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)] + [b]
        out += list(zip(pts, pts[1:]))
    return out
