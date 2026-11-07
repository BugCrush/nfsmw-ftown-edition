"""F-Town's landmark buildings (the hospitals, Sector 16 Market's blocks, the malls, the gym building, Dr. Aggarwal's),
the Neelam Flyover's mural, the DND-KMP Expressway's side walls and the Sector 16A sign (render metres, heights above
the ground; docs/ftown-notes.md "Landmarks and street furniture").

- A building landmark stands on its footprint (tools/citymap/landmarks.py: the trimmed block, so no wall on a road):
  walls to its height in its finish (glass curtain walls for the hospitals and the gym building, cladding for the
  malls, blue panels for Dr. Aggarwal's, shop fronts under plaster for the market), the registry's photo crops on their
  faces, a flat roof with a 1 m parapet; its walls are barriers (as the block it replaces). Marengo Asia gets its arched
  canopy before the photo front (from photos 18 and 20; drawn only above 2.5 m, its feet off the roads).
- The mural (photo 36) on the outer faces of the Neelam Flyover's embankment walls 2.5 m or taller, 4 cm proud of the
  concrete, repeating every 24 m along each carriageway.
- The DND-KMP Expressway (look only, the design: no new raising): a 1.1 m crash wall 0.3 m outside each carriageway's
  edge, cut 0.3 m clear of every other road; two-sided barriers.
- The Sector 16A sign: a green board on two posts beside Mathura Road at its registry point (moved off the lanes),
  facing the traffic, its back plain.
"""
import dataclasses
import math
import os
import sys
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import buildings as bmod  # noqa: E402
from tools.citymap import parts as P  # noqa: E402
from tools.citymap import evening  # noqa: E402
from tools.citymap import surfaces, textures  # noqa: E402

FINISH = {"glass": "glass", "mall": "mallpanel", "blue_panel": "bluepanel", "market": "plaster", "plain": "plaster"}
PARAPET = 1.0
CANOPY_MIN = 2.5
MURAL_MIN = 2.5
MURAL_OUT = 0.04
CRASH_H = 1.1
CRASH_OUT = 0.3
TWO_SIDED = 0x12
DND = "DND-KMP Expressway"
SHOP_BAND = 3.2
PIECE = 5.0


@dataclass
class Result:
    parts: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    footprints: dict = field(default_factory=dict)  # key: footprint of the building landmarks
    mural_m: dict = field(default_factory=dict)  # chain index: metres of mural
    mural_parts: list = field(default_factory=list)
    crash_m: float = 0.0
    canopies: list = field(default_factory=list)
    sign_at: tuple = None
    photo_faces: int = 0


def _tile(kind):
    return textures.TILE_M.get(kind, (4.0, 3.2))


def building(lm, photo_names, res):
    from tools.citymap import landmarks, phototex
    fp = lm.footprint
    ps = P.PartSet(lm.key)
    h = lm.height_m
    fin = FINISH.get(lm.finish, "plaster")
    by_edge = {}
    for f in lm.faces:
        by_edge.setdefault(f.edge_index, []).append(f)
    for k, (p, q) in enumerate(landmarks.edges(fp)):
        fs = by_edge.get(k, [])
        wall_face = next((f for f in fs if not f.z or f.z[0] < h - 0.01), None)
        signs = [f for f in fs if f.z and f.z[0] >= h - 0.01]
        kind = phototex.texture_name(wall_face.name) if wall_face is not None else None
        if kind is not None and kind not in photo_names:
            kind = None
        if kind is not None:
            res.photo_faces += 1
        atlas_front = lm.finish == "market" and kind is None
        if atlas_front:
            # own looks: the market's other fronts as the ordinary market blocks (FTC_STREET's shops under the house
            # atlas's facade block 1, its storeys from the roof line); the roof is at h, the atlas's 0.9 m parapet
            # over it (the review: it stood below the roof, with a plain parapet above)
            from tools.citymap import tiles
            L = math.dist(p, q)
            u0 = (k * 5.3) % textures.HOUSE_SPAN_M
            tris, uvs = tiles._wall_uv(p, q, 0.0, SHOP_BAND, u0 / textures.HOUSE_SPAN_M,
                                       (u0 + L) / textures.HOUSE_SPAN_M, textures.street_v(k % textures.STREET_STRIPS,
                                                                                         0.0),
                                       textures.street_v(k % textures.STREET_STRIPS, 3.2))
            ps.get("street").add(tris, uvs, [evening.glow(P.lit(t, 64.0), "shop") for t in tris])
            tris, uvs = tiles.house_wall(p, q, SHOP_BAND, h, 1, u0)
            ps.get("houses").add(tris, uvs, [P.lit(t, 62.0, (1.08, 1.02, 0.94)) for t in tris])
        else:
            P.faced_wall(ps, p, q, 0.0, h, fin, _tile(fin), wall_face, kind)
        for f in signs:
            sk = phototex.texture_name(f.name)
            lift = h + PARAPET + 0.05 - f.z[0]
            if lift > 0:  # the sign stands on the parapet, not in its plane (two faces in one plane flicker)
                f = dataclasses.replace(f, z=(f.z[0] + lift, f.z[1] + lift))
            if sk in photo_names:
                res.photo_faces += 1
                P.faced_wall(ps, p, q, h, h, fin, _tile(fin), f, sk)
        # the parapet: the wall carried 1 m over the roof (the atlas fronts' own 0.9 m), its inside facing the roof
        top = h + (bmod.PARAPET if atlas_front else PARAPET)
        if not atlas_front:
            tris, uvs = P.tiled_wall(p, q, h, top, *_tile("roof"))
            ps.get("roof").add(tris, uvs, [P.lit(t, 58.0) for t in tris])
        tris, uvs = P.tiled_wall(q, p, h, top, *_tile("roof"))
        ps.get("roof", "build", P.DETAIL).add(tris, uvs, [P.lit(t, 50.0) for t in tris])
        res.barriers.append((p, q, 0.0, h))
    roof = [tuple((x[0], x[1], h) for x in t) for t in surfaces.triangulate(fp, 64.0)]
    ps.get("roof").add(roof, [tuple((x[0] / 8, -x[1] / 8) for x in t) for t in roof], P.colour((66, 66, 66)))
    if lm.extra.get("canopy"):
        _canopy(ps, lm, res)
    res.parts += ps.all()
    res.footprints[lm.key] = fp


def _canopy(ps, lm, res):
    """An arch before the face carrying the canopy spec {"edge", "width_m", "height_m", "depth_m"}: a 1.5 m band in a
    half ellipse, its feet in front of the wall (the registry says the edge)."""
    from tools.citymap import landmarks
    c = lm.extra["canopy"]
    p, q = landmarks.edges(lm.footprint)[c["edge"]]
    L = math.dist(p, q)
    t = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    n = landmarks.outward(p, q)
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    W, H, D = c["width_m"], c["height_m"], c["depth_m"]
    band = 1.5
    frame = ps.get("concrete", "build", P.DETAIL)
    segs = 12
    outer, inner = [], []
    for k in range(segs + 1):
        a = math.pi * k / segs
        outer.append((-W / 2 * math.cos(a), H * math.sin(a)))
        inner.append((-(W / 2 - band) * math.cos(a), (H - band) * math.sin(a)))

    def at(x, z, d):
        return (mid[0] + t[0] * x + n[0] * d, mid[1] + t[1] * x + n[1] * d, z)
    uv4 = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for d, want in ((D, n), (0.3, (-n[0], -n[1]))):  # the band's front and back
        for k in range(segs):
            qd = [at(*outer[k], d), at(*outer[k + 1], d), at(*inner[k + 1], d), at(*inner[k], d)]
            tris, uvs = P.quad(qd, uv4, (want[0], want[1], 0.0))
            frame.add(tris, uvs, [P.lit(tr, 72.0) for tr in tris])
    for k in range(segs):  # its outer and inner curved surfaces, wall to front
        x, z = (outer[k][0] + outer[k + 1][0]) / 2, (outer[k][1] + outer[k + 1][1]) / 2
        for ring, sg in ((outer, 1.0), (inner, -1.0)):
            qd = [at(*ring[k], 0.3), at(*ring[k + 1], 0.3), at(*ring[k + 1], D), at(*ring[k], D)]
            tris, uvs = P.quad(qd, uv4, (t[0] * x * sg, t[1] * x * sg, z * sg))
            frame.add(tris, uvs, [P.lit(tr, 70.0) for tr in tris])
    res.canopies.append(Polygon([(at(-W / 2, 0, 0.3)[0], at(-W / 2, 0, 0.3)[1]), (at(W / 2, 0, 0.3)[0],
                        at(W / 2, 0, 0.3)[1]), (at(W / 2, 0, D)[0], at(W / 2, 0, D)[1]),
                        (at(-W / 2, 0, D)[0], at(-W / 2, 0, D)[1])]))


def mural(chains, L, photo_kind, res, width_m=24.0):
    """The mural on the Neelam Flyover's tall embankment walls (module doc)."""
    if not chains:
        return
    names = {c.name for c in chains}
    E = L.elevated
    ps = P.PartSet("MURAL")
    part = ps.get(photo_kind, "build", P.DETAIL)
    for w in L.walls():
        if w.kind != "embankment":
            continue
        mid = ((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2)
        c, _pt = L._nearest(*mid)
        if c.name not in names:
            continue
        top_a, top_b = w.za + 1.0, w.zb + 1.0
        if max(top_a, top_b) < MURAL_MIN:
            continue
        dx, dy = w.b[0] - w.a[0], w.b[1] - w.a[1]
        Ln = math.hypot(dx, dy) or 1.0
        left = (-dy / Ln, dx / Ln)
        left_in = E.contains(Point(mid[0] + left[0] * 0.05, mid[1] + left[1] * 0.05))
        out = (-left[0], -left[1]) if left_in else left
        a = (w.a[0] + out[0] * MURAL_OUT, w.a[1] + out[1] * MURAL_OUT)
        b = (w.b[0] + out[0] * MURAL_OUT, w.b[1] + out[1] * MURAL_OUT)
        sa = c.line.project(Point(w.a))
        sb = c.line.project(Point(w.b))
        qd = [(a[0], a[1], 0.0), (b[0], b[1], 0.0), (b[0], b[1], top_b), (a[0], a[1], top_a)]
        # u grows to the right of a viewer facing the mural (Run H fixes: on walls left of the chain's direction it
        # ran the other way and read mirrored); u wraps, so its sign only turns the picture
        right = (-out[1], out[0])
        sg = 1.0 if ((b[0] - a[0]) * right[0] + (b[1] - a[1]) * right[1]) * (sb - sa) >= 0 else -1.0
        uv = [(sg * sa / width_m, 1.0), (sg * sb / width_m, 1.0), (sg * sb / width_m, 0.0), (sg * sa / width_m, 0.0)]
        tris, uvs = P.quad(qd, uv, (out[0], out[1], 0.0))
        part.add(tris, uvs, [P.lit(t, 70.0) for t in tris])
        k = chains.index(c) if c in chains else [x.name for x in chains].index(c.name)
        res.mural_m[k] = res.mural_m.get(k, 0.0) + Ln
    res.parts += ps.all()
    res.mural_parts += ps.all()


def crash_walls(model, polys_all, res):
    """The DND-KMP Expressway's side walls (module doc)."""
    ps = P.PartSet("DND")
    part = ps.get("crashwall")
    clear = polys_all.buffer(CRASH_OUT - 0.01)
    for r in model.roads:
        if r.name != DND or r.level != 0:
            continue
        line = LineString(r.points)
        for side in (1, -1):
            off = line.offset_curve(side * (r.width_m / 2 + CRASH_OUT))
            if off.is_empty:
                continue
            g = off.difference(clear)
            for seg in getattr(g, "geoms", [g]):
                if seg.is_empty or seg.geom_type != "LineString":
                    continue
                pts = list(seg.coords)
                cut = []
                for a, b in zip(pts, pts[1:]):  # pieces of at most PIECE metres (levels.WALL_PIECE's rule)
                    n = max(1, int(math.ceil(math.dist(a, b) / PIECE)))
                    cut += [((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n),
                             (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n))
                            for k in range(n)]
                for p, q in cut:
                    Ln = math.dist(p, q)
                    if Ln < 0.3:
                        continue
                    for out_right in (True, False):
                        tris, uvs = P.tiled_wall(p, q, 0.0, CRASH_H, 2.0, 1.1 * 1.0, out_right)
                        part.add(tris, uvs, [P.lit(t, 70.0) for t in tris])
                    res.barriers.append((p, q, 0.0, CRASH_H, TWO_SIDED))
                    res.crash_m += Ln
    res.parts += ps.all()


def sign(lm, photo_names, lanes, model, res):
    """The Sector 16A sign on two posts (module doc): at the registry point, moved to the nearest spot off the lanes,
    its face turned to the nearest trunk road's traffic."""
    from tools.citymap import phototex
    x, y = lm.point
    best = None
    for r in range(0, 30):
        for a in range(0, 360, 15):
            p = (x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a)))
            if not lanes.intersects(Point(p).buffer(1.5)):
                best = p
                break
        if best:
            break
    if best is None:
        return
    trunk = min((LineString(rd.points) for rd in model.roads if rd.kind == "trunk"),
                key=lambda ln: ln.distance(Point(best)))
    s = trunk.project(Point(best))
    a, b = trunk.interpolate(max(0, s - 2)), trunk.interpolate(min(trunk.length, s + 2))
    t = ((b.x - a.x), (b.y - a.y))
    Lt = math.hypot(*t) or 1.0
    t = (t[0] / Lt, t[1] / Lt)  # the board stands across the road's direction, its face to the oncoming traffic
    nrm = (-t[1], t[0])
    ps = P.PartSet(lm.key)
    face = lm.faces[0] if lm.faces else None
    kind = phototex.texture_name(face.name) if face else None
    w, z0, z1 = 2.4, 2.2, 3.4
    pa = (best[0] - nrm[0] * w / 2, best[1] - nrm[1] * w / 2)
    pb = (best[0] + nrm[0] * w / 2, best[1] + nrm[1] * w / 2)
    fur = ps.get("furniture", "build", P.DETAIL)
    if kind in photo_names:
        tris, uvs = P.quad([(pa[0], pa[1], z0), (pb[0], pb[1], z0), (pb[0], pb[1], z1), (pa[0], pa[1], z1)],
                           [(1, 1), (0, 1), (0, 0), (1, 0)], (-t[0], -t[1], 0.0))
        ps.get(kind, "build", P.DETAIL).add(tris, uvs, [P.lit(tr, 72.0) for tr in tris])
    else:
        _solid_quad(fur, pa, pb, z0, z1, (-t[0], -t[1]), "signgreen")
    _solid_quad(fur, pb, pa, z0, z1, (t[0], t[1]), "signgreen")
    for e in (pa, pb):
        ring = P.box(e[0] + t[0] * 0.05, e[1] + t[1] * 0.05, t[0], t[1], 0.05, 0.05, 0, 0)
        for p, q in zip(ring, ring[1:] + ring[:1]):
            tris, uvs = P.wall(p, q, 0.0, z1, 0.6, 0.6, 0.6, 0.6)
            _solid(fur, tris, "black" if e is pa else "white")
    res.parts += ps.all()
    res.sign_at = best


def _solid(part, tris, cell):
    u, v = textures.furniture_uv(cell)
    part.add(tris, [((u, v),) * 3 for _ in tris], [P.colour((72, 72, 72))] * len(tris))


def _solid_quad(part, pa, pb, z0, z1, facing, cell):
    tris, _uvs = P.quad([(pa[0], pa[1], z0), (pb[0], pb[1], z0), (pb[0], pb[1], z1), (pa[0], pa[1], z1)],
                        [(0, 0)] * 4, (facing[0], facing[1], 0.0))
    _solid(part, tris, cell)


def build(lms, photo_names, L, lanes, model, polys_all):
    """Result for every non-station landmark (module doc)."""
    from tools.citymap import phototex
    res = Result()
    for lm in lms:
        if lm.kind in ("hospital", "commercial", "market", "mall"):
            building(lm, photo_names, res)
        elif lm.kind == "mural":
            kind = phototex.texture_name(lm.faces[0].name) if lm.faces else None
            mural(lm.extra.get("chains", []), L, kind if kind in photo_names else "stn_orange", res,
                  lm.faces[0].width_m or 24.0)
        elif lm.kind == "sign":
            sign(lm, photo_names, lanes, model, res)
    crash_walls(model, polys_all, res)
    return res
