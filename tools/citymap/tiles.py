"""F-Town's city cut into square tiles: what each tile draws (per detail level and material) and what it collides
with (render metres for drawing, physics for collision).

Calls (docs/ftown-notes.md "Stage 2: the streets"):
- TILE (128 m) squares aligned to multiples of 128 m from the render origin (the 8 m and 32 m triangulation grids cut
  along them). Each tile is two scenery instances at the tile's centre, ground level (z GROUND_Z): a **ground** one
  (roads, decks' tops, pavements, kerbs, markings, grass and earth) with exclude flags 0x8060 (since the city fixes:
  Rockport's non-terrain kind-0 ground; the terrain bit 0x80 of run G's 0xE0 left it near black in shadows; 0x200
  would draw without the instance's matrix, Scenery.cpp:768), and a **buildings** one (walls,
  roofs, the flyovers' concrete: parapets, embankments, undersides, pillars, the edge walls) with 0x8060 (Rockport's
  placed scenery's most common plain value). One instance is one of the 5,000 draw records a frame (PC, 0x731B80).
- Detail levels, in the game's four model slots (DrawAScenery, Scenery.cpp:678: the main view draws slot 0 near and
  slot 2 far, shadow and reflection views slot 2 or 3, slot 1 is never drawn): ground A (everything) / B = C / C (no
  markings, no kerbs) / C (the shadow and reflection views' slot); buildings one model in all four (OSM footprints
  are mostly rectangles already, 15 triangles a building on average: a simplified level saved 2% of their triangles
  and cost 9 MB of file).
- Flat surfaces (roads, pavements, ground) triangulated on a 32 m grid, the elevated ones on 8 m (heights vary).
- Collision per tile: road and deck faces asphalt, pavements concrete, grass grass, earth dirt; barriers: building
  walls (ground to roof), the flyovers' parapets and embankment walls (Task 3), pillars, the edge (EDGE_BARRIER tall:
  a car on a deck can't cross it either).
"""
import math
import os
import sys

import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import buildings as bmod  # noqa: E402
from tools.citymap import levels as lmod  # noqa: E402
from tools.citymap import surfaces, textures  # noqa: E402
from tools.citymap import evening  # noqa: E402

DETAIL_LEVELS = ("A", "B")  # parts.DETAIL: the near level only (the far level and the shadow views leave it out)

TILE = 128.0
# the distance (render metres) at which a tile's instances switch to their far model (slot 2: one texture, the far
# atlas; build_city sets the near models' Density for it, the game's rule in DrawAScenery 0x729120): Run H fixes,
# fault 4 (93% of Bata Chowk's view north was tiles beyond 750 m drawn with every texture)
FAR_SWITCH = 700.0
GROUND_Z = 100.0
FLAT_EDGE = 32.0
RAMP_EDGE = 8.0
KERB = surfaces.PAVEMENT_RISE
KERB_PIECE = 16.0
DECK_THICK = 0.8
EDGE_BARRIER = 40.0
# a barrier's surface flags (collision_write._article): 0x02 stops a body only in front (the right of p -> q), 0x12
# on both sides (WCollisionMgr::Collide, WCollisionMgr.cpp:774; run G's resets at the edge, docs/ftown-notes.md
# "City fixes")
TWO_SIDED = 0x12
# the ground's collision surfaces by texture kind (Run I fixes, item 11: paved forecourts and lots are concrete)
GROUND_SURFACE = {"grass": "grass", "paver": "concrete", "lot": "concrete"}
# city fixes (fault 2): Rockport's non-terrain flags, as its RO_ road and ARC ground kind-0 instances (0x8060); 0x80
# (the terrain bit, drawn in its own pass) left the ground near black in our buildings' shadows in run G
GROUND_FLAGS = 0x8060
BUILDING_FLAGS = 0x8060
# city fixes (fault 3): Rockport's kind-0 non-terrain ground, area weighted (tools/citymap/rockport_colours.py); the
# old 0xFF525964 was its SHD_ shadow decals' colour
GROUND_COLOUR = 0xFF474748
# Run I fixes, item 11: the earth's vertex colour on a road's or pavement's edge (a dusty verge, lighter and warmer
# than the ground grey), fading to the grey over DUST_W
DUST_RGB = (98, 90, 76)
DUST_W = 4.0
SUN = (0.45, -0.55, 0.70)  # a fixed light for the walls' baked shading (from the south-east, high)
PLASTER_TINTS = [(1.00, 0.98, 0.96), (1.02, 1.00, 0.96), (1.01, 0.98, 0.97), (0.98, 0.98, 0.98)]  # Rockport's walls are grey


def colour(rgb):
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return 0xFF000000 | (r << 16) | (g << 8) | b


def tile_of(x, y):
    return int(math.floor(x / TILE)), int(math.floor(y / TILE))


def tile_box(i, j):
    return box(i * TILE, j * TILE, (i + 1) * TILE, (j + 1) * TILE)


def _polys(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]


def _shade(n):
    return 0.80 + 0.25 * max(0.0, n[0] * SUN[0] + n[1] * SUN[1] + n[2] * SUN[2])


def vquad(p, q, z0, z1, face_left, kind):
    """A vertical quad from p to q (render x, y), z0..z1, facing the left of p -> q (face_left) or its right; uvs: u
    along the wall, v down from z1, in the texture's metres. Facing: its right-hand normal (B - A) x (C - A) points
    there, the side the game draws (Run H fixes, fault 1: run H's walls were wound the other way and drawn from
    inside only)."""
    L = math.dist(p, q)
    tu, tv = textures.TILE_M[kind]
    A, B, C, D = (p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)
    ua, ub = 0.0, L / tu
    va, vb = (z1 - z0) / tv, 0.0
    if not face_left:
        return [(A, B, C), (A, C, D)], [((ua, va), (ub, va), (ub, vb)), ((ua, va), (ub, vb), (ua, vb))]
    return [(A, C, B), (A, D, C)], [((ua, va), (ub, vb), (ub, va)), ((ua, va), (ua, vb), (ub, vb))]


def _wall_uv(p, q, z0, z1, u0, u1, vt, vb):
    """vquad(..., face_left=False)'s wall (outward on a counter-clockwise ring) with its own uvs: u0 at p to u1 at q,
    vt at the top (z1) to vb at the bottom (z0)."""
    A, B, C, D = (p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)
    return [(A, B, C), (A, C, D)], [((u0, vb), (u1, vb), (u1, vt)), ((u0, vb), (u1, vt), (u0, vt))]


def house_wall(p, q, z0, h, block, u_off):
    """(triangles, uvs) of a building's wall p -> q (outward on the right) from z0 to its parapet's top h + PARAPET in
    FTC_HOUSES facade block `block` (own looks): the block's rows counted from the parapet's top down, so a wall of up
    to FACADE_M is one quad; a taller one takes the block's FACADE_M on top and one quad per 3.2 m storey below, the
    lowest on the block's bottom row, the others on its third. u runs (u_off + metres along the wall) / HOUSE_SPAN_M,
    to the right of a viewer facing the wall."""
    top = h + bmod.PARAPET
    L = math.dist(p, q)
    u0, u1 = u_off / textures.HOUSE_SPAN_M, (u_off + L) / textures.HOUSE_SPAN_M
    F = textures.FACADE_M
    if top - z0 <= F + 1e-6:
        return _wall_uv(p, q, z0, top, u0, u1, textures.facade_v(block, 0.0), textures.facade_v(block, top - z0))
    tris, uvs = _wall_uv(p, q, top - F, top, u0, u1, textures.facade_v(block, 0.0), textures.facade_v(block, F))
    z = top - F
    while z > z0 + 1e-6:
        zb = max(z0, z - bmod.STOREY)
        row = 3 if zb <= z0 + 1e-6 else 2
        r0 = bmod.PARAPET + bmod.STOREY * row
        t2, u2 = _wall_uv(p, q, zb, z, u0, u1, textures.facade_v(block, r0 + bmod.STOREY - (z - zb)),
                          textures.facade_v(block, r0 + bmod.STOREY))
        tris += t2
        uvs += u2
        z = zb
    return tris, uvs


def roof_uv(t, bounds, cell="roof"):
    """uvs of a roof triangle mapped whole into an FTC_HOUSES cell (own looks: the roof cell is flat concrete; its
    bounds' longer side spans the cell)."""
    x0, y0, x1, y1 = bounds
    span = max(x1 - x0, y1 - y0, 1e-6)
    return tuple(textures.house_cell_uv(cell, (p[0] - x0) / span, (p[1] - y0) / span) for p in t)


def _normal_of(t):
    a, b, c = t
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    L = math.sqrt(sum(x * x for x in n)) or 1.0
    return tuple(x / L for x in n)


def planar_uv(t, kind):
    tu, tv = textures.TILE_M[kind]
    return tuple((p[0] / tu, -p[1] / tv) for p in t)


class Groups:
    """{(instance, level, kind): [triangles, uvs, colours]} for one tile, in render coordinates."""

    def __init__(self):
        self.g = {}

    def add(self, inst, levels, kind, tris, uvs, cols):
        for lv in levels:
            e = self.g.setdefault((inst, lv, kind), ([], [], []))
            e[0].extend(tris)
            e[1].extend(uvs)
            e[2].extend(cols)


class Tile:
    def __init__(self, i, j):
        self.i, self.j = i, j
        self.groups = Groups()
        self.faces = []  # (render triangle with z above ground, surface name)
        self.barriers = []  # ((x, y), (x, y), bottom, top) render, heights above ground

    @property
    def centre(self):
        return ((self.i + 0.5) * TILE, (self.j + 0.5) * TILE)


class CityGeometry:
    """Everything of the city, cut into tiles. Inputs are the earlier tasks' objects."""

    def __init__(self, model, lv, blocks, ground, outer, edge, markings, pav, parts=(), barriers=(),
                 skip_blocks=frozenset(), platforms=(), dust=None):
        """parts: tools/citymap/parts.Part (the landmarks stage: landmarks, the metro, street furniture), each
        triangle into the tile of its centroid; barriers: (p, q, bottom, top[, flags]) render, into the tile of their
        middle; skip_blocks: OSM ids of blocks a landmark draws instead (they still cut the ground); platforms:
        (polygon, height, texture kind, surface) drawn and collided as the pavements (the medians' tops, Run H fixes:
        the caller cuts them out of the pavement and the ground); dust: the ground carriageways and pavements, whose
        edges the earth's vertex colours turn dusty (Run I fixes, item 11: DUST_W, DUST_RGB)."""
        self.model, self.L, self.blocks, self.outer = model, lv, blocks, outer
        self.parts, self.extra_barriers, self.skip_blocks = list(parts), list(barriers), set(skip_blocks)
        self.platforms = list(platforms)
        self.dust = dust
        self.tiles = {}
        self.pending_panes = {}
        self.pending_lamps = []
        self.G = lv.ground_polygon.intersection(outer)
        self.E = lv.elevated.intersection(outer)
        self.pav = pav.intersection(outer)
        self.ground = [(p.intersection(outer), k) for p, k in ground]
        self.markings = markings
        self.edge = edge
        self.chain_roads = {rid for c in lv.raised_chains for rid, _i, _j in c.parts}
        self._cut()

    def tile(self, i, j):
        t = self.tiles.get((i, j))
        if t is None:
            t = self.tiles[(i, j)] = Tile(i, j)
        return t

    def _tiles_over(self, geom):
        x0, y0, x1, y1 = geom.bounds
        for i in range(int(math.floor(x0 / TILE)), int(math.floor(x1 / TILE)) + 1):
            for j in range(int(math.floor(y0 / TILE)), int(math.floor(y1 / TILE)) + 1):
                yield i, j

    def _flat(self, geom, z, kind, surface, levels=("A", "C")):
        for i, j in self._tiles_over(geom):
            part = geom.intersection(tile_box(i, j))
            if part.is_empty or part.area <= 0:
                continue
            tris = surfaces.triangulate(part, FLAT_EDGE)
            if not tris:
                continue
            t3 = [tuple((p[0], p[1], z) for p in tr) for tr in tris]
            T = self.tile(i, j)
            cols = [GROUND_COLOUR] * len(t3)
            if kind == "earth" and self.dust is not None:
                cols = self._dusty(i, j, t3)
            T.groups.add("ground", levels, kind, t3, [planar_uv(tr, kind) for tr in t3], cols)
            T.faces += [(tr, surface) for tr in t3]

    def _dusty(self, i, j, t3):
        """Per-vertex colours of earth triangles: DUST_RGB on a road's or pavement's edge, the ground grey from DUST_W
        out, linear between (the triangles' own vertices: no triangle is added; the dust fades over the triangle beside
        the road, so its width varies as a real verge's does)."""
        import numpy as np
        import shapely
        D = self.dust.intersection(tile_box(i, j).buffer(DUST_W + 1.0))
        pts = np.array([p[:2] for t in t3 for p in t], dtype=float)
        if D.is_empty:
            d = np.full(len(pts), DUST_W)
        else:
            d = shapely.distance(D, shapely.points(pts))
        f = np.clip(d / DUST_W, 0.0, 1.0)
        g = np.array([(GROUND_COLOUR >> s_) & 255 for s_ in (16, 8, 0)], dtype=float)
        dc = np.array(DUST_RGB, dtype=float)
        rgb = dc[None, :] * (1 - f[:, None]) + g[None, :] * f[:, None]
        c = [colour(v) for v in rgb]
        return [tuple(c[3 * k:3 * k + 3]) for k in range(len(t3))]

    def _cut(self):
        L = self.L
        # roads at ground, pavements, grass and earth
        self._flat(self.G, 0.0, "asphalt", "asphalt")
        self._flat(self.pav, KERB, "pavement", "concrete")
        for poly, z, kind, surface in self.platforms:
            self._flat(poly.intersection(self.outer), z, kind, surface)
        for poly, kind in self.ground:
            self._flat(poly, 0.0, kind, GROUND_SURFACE.get(kind, "dirt"))
        # the elevated surface: the decks' and ramps' tops
        for i, j in self._tiles_over(self.E):
            b = tile_box(i, j)
            tris = L.deck_surfaces(b.intersection(self.outer))
            if not tris:
                continue
            T = self.tile(i, j)
            T.groups.add("ground", ("A", "C"), "asphalt", tris, [planar_uv(t, "asphalt") for t in tris],
                         [GROUND_COLOUR] * len(tris))
            T.faces += [(t, "asphalt") for t in tris]
            # the underside, where the deck stands over open ground (inside an embankment nothing is seen)
            under = [tuple((p[0], p[1], p[2] - DECK_THICK) for p in (t[0], t[2], t[1])) for t in tris
                     if min(p[2] for p in t) >= lmod.CLEARANCE - 0.01]
            if under:
                T.groups.add("build", ("A", "C"), "concrete", under, [planar_uv(t, "concrete") for t in under],
                             [colour((60, 60, 60))] * len(under))
        self._markings()
        self._kerbs()
        self._buildings()
        self._flyover_walls()
        self._edge()
        self._extras()
        self._panes()

    def _panes(self):
        """The evening's window panes (tools/citymap/evening.py), building by building into their tile's houses mesh
        only while that mesh's triangles stay under its next 1,000 (a mesh holds 1,000: no tile gains a draw)."""
        self.panes_added = self.panes_skipped = 0
        for key, items in sorted(self.pending_panes.items()):
            T = self.tiles[key]
            e = T.groups.g.get(("build", "A", "houses"))
            n = len(e[0]) if e else 0
            room = (-n) % 1000
            # a buildings instance of 39 triangles or fewer never switches to its far model and is not given a far
            # Density (build_city): panes there would make it switch at the wrong distance (test_runh FarLevel)
            if sum(len(g[0]) for (i, lv, _k), g in T.groups.g.items() if i == "build" and lv == "A") <= 39:
                room = 0
            for tris, uvs, tint in items:
                if len(tris) > room:
                    self.panes_skipped += len(tris) // 2
                    continue
                cols = [evening.glow(colour(tuple(40.0 * k_ for k_ in tint)), "pane")] * len(tris)
                T.groups.add("build", DETAIL_LEVELS, "houses", tris, uvs, cols)
                room -= len(tris)
                self.panes_added += len(tris) // 2
        # the metro's deck lights (metro.deck_lamps): only into a tile's existing furniture mesh with room
        self.lamps_added = self.lamps_skipped = 0
        x0, y0, x1, y1 = self.outer.bounds
        for part in self.pending_lamps:
            ax, ay = part.anchor
            T = self.tiles.get(tile_of(ax, ay))
            e = T.groups.g.get(("ground", "A", "furniture")) if T is not None else None
            if not (x0 <= ax <= x1 and y0 <= ay <= y1) or not e or len(part.tris) > (-len(e[0])) % 1000:
                self.lamps_skipped += 1
                continue
            T.groups.add(part.inst, part.levels, part.kind, part.tris, part.uvs, part.cols)
            self.lamps_added += 1

    def _extras(self):
        x0, y0, x1, y1 = self.outer.bounds
        self.extras_outside = 0
        for part in self.parts:
            if part.tag == "METROLAMPS":  # the evening's deck lights: added last, where they cost no draw (_panes)
                self.pending_lamps.append(part)
                continue
            by_tile = {}
            anchor = getattr(part, "anchor", None)  # own looks: a house's detail goes whole to its block's tile
            for t, uv, c in zip(part.tris, part.uvs, part.cols):
                cx = (t[0][0] + t[1][0] + t[2][0]) / 3.0
                cy = (t[0][1] + t[1][1] + t[2][1]) / 3.0
                if anchor is not None:
                    cx, cy = anchor
                if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                    self.extras_outside += 1  # nothing is drawn past the edge (the city's tiles stop there)
                    continue
                e = by_tile.setdefault(tile_of(cx, cy), ([], [], []))
                e[0].append(t)
                e[1].append(uv)
                e[2].append(c)
            for (i, j), (tris, uvs, cols) in by_tile.items():
                self.tile(i, j).groups.add(part.inst, part.levels, part.kind, tris, uvs, cols)
        for b in self.extra_barriers:
            mid = ((b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2)
            if not (x0 <= mid[0] <= x1 and y0 <= mid[1] <= y1):
                self.extras_outside += 1
                continue
            self.tile(*tile_of(*mid)).barriers.append(tuple(b))

    def _markings(self):
        L = self.L
        for kind, poly, rid in self.markings:
            poly = poly.intersection(self.outer)
            for part in _polys(poly):
                c = part.representative_point()
                T = self.tile(*tile_of(c.x, c.y))
                raised = rid in self.chain_roads
                tris = []
                for tr in surfaces.triangulate(part, RAMP_EDGE):
                    zs = []
                    for x, y in tr:
                        z = L.z_at(x, y) if raised and L.elevated.contains(Point(x, y)) else 0.0
                        zs.append(z + surfaces.MARKING_RISE)
                    tris.append(tuple((p[0], p[1], z) for p, z in zip(tr, zs)))
                T.groups.add("ground", ("A",), "paint", tris, [planar_uv(t, "paint") for t in tris],
                             [GROUND_COLOUR] * len(tris))

    def _kerbs(self):
        # round the pavements and the platforms (the medians' tops, at the same height) as one: a kerb only where the
        # raised surface meets the lower ground (Run H fixes)
        raised = self.pav
        if self.platforms:
            raised = shapely.union_all([self.pav] + [p.intersection(self.outer) for p, _z, _k, _s in self.platforms])
        for poly0 in _polys(raised):
            poly = orient(poly0.simplify(0.1), 1.0)
            shapely.prepare(poly0)
            for ring in [poly.exterior] + list(poly.interiors):
                pts = list(ring.coords)
                for p, q in zip(pts, pts[1:]):
                    L = math.dist(p, q)
                    if L < 0.05:
                        continue
                    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                    # facing away from the pavement, found from the pavement itself (Run H fixes: the simplified ring
                    # of a sliver the medians leave can run the other way; a kerb with pavement on both sides or
                    # neither, or less than 0.3 m of it behind (a sliver the triangulation drops: no top), is left
                    # out); black-and-white kerb paint (the landmarks stage: every pavement is beside
                    # a main road, docs/ftown-notes.md "Landmarks and street furniture")
                    rx, ry = (q[1] - p[1]) / L * 0.05, -(q[0] - p[0]) / L * 0.05
                    right_in = poly0.contains(Point(mid[0] + rx, mid[1] + ry))
                    left_in = poly0.contains(Point(mid[0] - rx, mid[1] - ry))
                    if right_in == left_in or not poly0.contains(
                            Point(mid[0] + rx * (6 if right_in else -6), mid[1] + ry * (6 if right_in else -6))):
                        continue
                    # in pieces of at most KERB_PIECE, each in the tile of its middle (the review, Run H fixes: one
                    # 530 m kerb quad stretched its tile's radius to 318 m, and the far switch's density with it)
                    n = max(1, int(math.ceil(L / KERB_PIECE)))
                    for k in range(n):
                        a = (p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n)
                        b = (p[0] + (q[0] - p[0]) * (k + 1) / n, p[1] + (q[1] - p[1]) * (k + 1) / n)
                        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                        sg = 6 if right_in else -6
                        if not poly0.contains(Point(m[0] + rx * sg, m[1] + ry * sg)):
                            continue  # a sliver's taper: no pavement 0.3 m behind this piece
                        Tk = self.tile(*tile_of(*m))
                        tris, uvs = vquad(a, b, 0.0, KERB, right_in, "kerb")
                        off = k * L / n / textures.TILE_M["kerb"][0]  # the stripes run on across the pieces
                        uvs = [tuple((u + off, v) for u, v in t) for t in uvs]
                        Tk.groups.add("ground", ("A",), "kerb", tris, uvs, [GROUND_COLOUR] * 2)

    def _buildings(self):
        for n, b in enumerate(self.blocks):
            if b.osm_id in self.skip_blocks:
                continue
            c = b.footprint.representative_point()
            T = self.tile(*tile_of(c.x, c.y))
            st = b.style
            tint = st.tint if st is not None else PLASTER_TINTS[b.osm_id % len(PLASTER_TINTS)]
            for level, fp in (("A", b.footprint),):
                fp = orient(fp, 1.0)
                walls, wuv, wcol = [], [], []
                shops, suv, scol = [], [], []
                h = b.height_m
                u_run = st.u0 if st is not None else 0.0
                for ri, ring in enumerate([fp.exterior] + list(fp.interiors)):
                    pts = list(ring.coords)
                    for k, (p, q) in enumerate(zip(pts, pts[1:])):
                        L = math.dist(p, q)
                        if L < 0.05:
                            continue
                        if st is None:
                            tris, uvs = vquad(p, q, 0.0, h, False, "plaster")  # outward: the right
                        else:
                            # own looks: the wall in FTC_HOUSES' facade block, from the ground (or over the shops)
                            # to the parapet's top, its storeys counted from the roof line; a market block's road
                            # fronts get a storey of shop fronts from FTC_STREET; u runs on round the corners
                            z0 = 0.0
                            if st.market and ri == 0 and k in st.shop_edges:
                                z0 = bmod.SHOP_BAND
                                strip = (b.osm_id + k) % textures.STREET_STRIPS
                                tr2, uv2 = _wall_uv(p, q, 0.0, z0, u_run / textures.HOUSE_SPAN_M,
                                                    (u_run + L) / textures.HOUSE_SPAN_M,
                                                    textures.street_v(strip, 0.0), textures.street_v(strip, 3.2))
                                shops += tr2
                                suv += uv2
                                sc = evening.glow(colour(tuple(64.0 * _shade(_normal_of(tr2[0])) for _k in range(3))),
                                                  "shop")
                                scol += [sc, sc]
                            tris, uvs = house_wall(p, q, z0, h, st.facade, u_run)
                            if ri == 0:  # the evening's lit window panes (evening.wall_panes), added last (_panes)
                                pt, pu = evening.wall_panes(p, q, z0, h, st.facade, u_run, (b.osm_id, k))
                                if pt:
                                    self.pending_panes.setdefault((T.i, T.j), []).append((pt, pu, tint))
                            u_run += L
                        sh = _shade(_normal_of(tris[0]))
                        col = colour(tuple(62.0 * sh * k_ for k_ in tint))
                        walls += tris
                        wuv += uvs
                        wcol += [col] * len(tris)
                        if level == "A":
                            T.barriers.append((p, q, 0.0, h))
                roof = [tuple((p[0], p[1], b.height_m) for p in tr) for tr in surfaces.triangulate(fp, 64.0)]
                lv = ("A", "B", "C", "D")
                if st is None:
                    T.groups.add("build", lv, "plaster", walls, wuv, wcol)
                    T.groups.add("build", lv, "roof", roof, [planar_uv(t, "roof") for t in roof],
                                 [colour((70, 70, 70))] * len(roof))
                    continue
                T.groups.add("build", lv, "houses", walls, wuv, wcol)
                if shops:
                    T.groups.add("build", lv, "street", shops, suv, scol)
                T.groups.add("build", lv, "houses", roof, [roof_uv(t, fp.bounds) for t in roof],
                             [colour((70, 70, 70))] * len(roof))

    def _flyover_walls(self):
        L = self.L
        E = L.elevated
        for w in L.walls():
            mid = ((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2)
            if not self.outer.contains(Point(mid)):
                continue
            dx, dy = w.b[0] - w.a[0], w.b[1] - w.a[1]
            Ln = math.hypot(dx, dy) or 1.0
            left_in = E.contains(Point(mid[0] - dy / Ln * 0.05, mid[1] + dx / Ln * 0.05))
            T = self.tile(*tile_of(*mid))
            out_left = not left_in
            cols = [colour((66, 66, 64))] * 2
            if w.kind == "parapet":
                for face_left in (True, False):
                    tris, uvs = self._sloped(w.a, w.b, w.za, w.zb, lmod.PARAPET, face_left)
                    T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, cols)
                # the fascia below the deck's edge, facing out
                tris, uvs = self._sloped(w.a, w.b, w.za - DECK_THICK, w.zb - DECK_THICK, DECK_THICK, out_left)
                T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, cols)
            else:
                # the embankment: its outside from the ground up to 1 m over the road, its inside above the road
                tris, uvs = self._sloped(w.a, w.b, 0.0, 0.0, None, out_left, tops=(w.za + lmod.PARAPET,
                                                                                    w.zb + lmod.PARAPET))
                T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, cols)
                tris, uvs = self._sloped(w.a, w.b, w.za, w.zb, lmod.PARAPET, not out_left)
                T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, cols)
            T.barriers.append((w.a, w.b, w.bottom, w.top, TWO_SIDED))  # met from the deck and from the ground
        for fp, top in L.pillars():
            c = fp.centroid
            if not self.outer.contains(c):
                continue
            T = self.tile(*tile_of(c.x, c.y))
            pts = list(orient(fp, 1.0).exterior.coords)
            for p, q in zip(pts, pts[1:]):
                tris, uvs = vquad(p, q, 0.0, top - DECK_THICK, False, "concrete")
                T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, [colour((58, 58, 56))] * 2)
                T.barriers.append((p, q, 0.0, top - DECK_THICK))  # up to the deck's underside

    @staticmethod
    def _sloped(a, b, za, zb, h, face_left, tops=None):
        """A wall from a to b whose bottom runs za -> zb and top za + h -> zb + h (or `tops`)."""
        ta, tb = tops if tops is not None else (za + h, zb + h)
        A, B, C, D = (a[0], a[1], za), (b[0], b[1], zb), (b[0], b[1], tb), (a[0], a[1], ta)
        L = math.dist(a, b)
        tu, tv = textures.TILE_M["concrete"]
        uv = {A: (0.0, (ta - za) / tv), B: (L / tu, (tb - zb) / tv), C: (L / tu, 0.0), D: (0.0, 0.0)}
        tris = [(A, C, B), (A, D, C)] if face_left else [(A, B, C), (A, C, D)]
        return tris, [tuple(uv[p] for p in t) for t in tris]

    def _edge(self):
        L = self.L
        for p, q in self.edge:
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            T = self.tile(*tile_of(mid[0] - 0.01 * (q[1] - p[1]), mid[1] + 0.01 * (q[0] - p[0])))
            # drawn 3 m tall, or 3 m over a deck that reaches the edge
            zhi = 0.0
            for s in (0.0, 0.25, 0.5, 0.75, 1.0):
                pt = (p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s)
                if L.elevated.distance(Point(pt)) < 2.0:
                    zhi = max(zhi, L.z_at(*pt))
            tris, uvs = vquad(p, q, 0.0, bmod.EDGE_HEIGHT + zhi, True, "concrete")  # the inside is on the left
            T.groups.add("build", ("A", "B", "C", "D"), "concrete", tris, uvs, [colour((70, 70, 68))] * 2)
            T.barriers.append((q, p, 0.0, EDGE_BARRIER))  # q -> p: its front (the right) faces the inside
