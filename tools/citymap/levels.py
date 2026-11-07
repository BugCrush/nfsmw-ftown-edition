"""F-Town's flyovers: raised decks, their ramps, parapets, embankment walls and pillars (render metres, z above the
flat ground; Task 5 adds the ground's height).

The rules (calls marked in docs/ftown-notes.md "Stage 2: the streets"):
- A **chain** is a run of bridge ways joined end to end (one carriageway of a flyover), extended at both ends along
  the road's own ways (the approach) until the first point where another road joins (or the data ends, or
  RAMP_REACH metres): that point is the chain's **foot**, at ground.
- The height along a chain: flat at ground from the foot until the chain's cross-section (a disc of half its width +
  0.5 m) is clear of every other ground road (the junction at the foot; searched over FOOT_SEARCH = 60 m); where a
  ground road runs alongside so closely that this never happens (Mathura Road's service carriageways beside the
  flyover ramps), until the centre line is CENTRE_CLEAR (1 m) clear of it. Then up at GRADE (6%) to DECK_HEIGHT (7 m),
  flat, and down the same way to the other foot. The rise may run onto the bridge way itself (OSM tags the bridge
  structure, not its embankment), so short approaches still meet 6%.
- A chain is **raised** only when every ground road it crosses lies under a part at least CLEARANCE (5 m) high;
  otherwise it stays at ground and its crossings are flat crossings (the two 15 m residential bridges, whose feet are
  junctions at both ends).
- The elevated surface: the raised chains' roads buffered by half their width, less the ground road surface wherever
  the chain is lower than CLEARANCE (at the feet both are at ground and the ground road wins, so nothing is drawn
  twice; alongside, the ramp is narrowed by the ground road and a wall stands on the seam); higher up the ground road
  surface stays whole under the deck (roads under a flyover stay drivable). Every vertex takes the height of its
  nearest chain at its projection.
- Walls (drawn and as barriers), on the elevated surface's outline: a 1 m parapet (from the road up) on bridge ways
  where the road is at least CLEARANCE up; elsewhere an embankment wall from the ground to 1 m above the road where the
  road is over WALL_FROM (0.25 m) up, or over SEAM (2 cm) up where it borders a ground road (a car on the ground can't
  drive under a ramp, and no step is left without a wall). Pillars 1.2 x 1.2 m every 25 m under the bridge ways where
  the deck is at least CLEARANCE up, left out where one would stand within 0.5 m of a ground road.
"""
import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import surfaces  # noqa: E402

from tools.citymap import terrain as _terrain  # noqa: E402

DECK_HEIGHT = 7.0
# the ramps' rise over the ground: 6% less the ground's own steepest grade (rounded down to 0.01%), so no road
# climbs more than 6% with the terrain (elevation, 2026-11-05; tools/citymap/terrain.py)
GRADE = math.floor((0.06 - _terrain.max_grade()) * 10000.0) / 10000.0
CLEARANCE = 5.0
RAMP_REACH = DECK_HEIGHT / GRADE + 40.0
PARAPET = 1.0
PILLAR = 1.2
PILLAR_STEP = 25.0
WALL_PIECE = 5.0
FOOT_SEARCH = 60.0
CENTRE_CLEAR = 1.0
WALL_FROM = 0.25
SEAM = 0.02
DECK_EDGE = 4.0  # m: the elevated surface's grid (8 m cut the tight Neelam curve's corner by 2.2 cm)


@dataclass
class Chain:
    parts: List[Tuple[int, int, int]]  # (road id, first point index, last point index) in chain order
    name: str
    widths: List[float]  # per part
    bridge: List[bool]  # per part
    line: LineString = None
    part_s: List[Tuple[float, float]] = field(default_factory=list)  # (s start, s end) per part
    rise_a: float = 0.0  # where the rise starts from foot A (s)
    rise_b: float = 0.0  # ... from foot B (length - s)
    raised: bool = False
    crossings: List[Tuple[float, int]] = field(default_factory=list)  # (s, ground road id)
    foot_notes: List[str] = field(default_factory=list)

    @property
    def length(self):
        return self.line.length

    def z(self, s):
        if not self.raised:
            return 0.0
        L = self.length
        return max(0.0, min(DECK_HEIGHT, GRADE * (s - self.rise_a), GRADE * ((L - s) - self.rise_b)))

    def top(self):
        if not self.raised:
            return 0.0
        return max(self.z(s) for s in np.linspace(0, self.length, 400))

    def part_at(self, s):
        for k, (a, b) in enumerate(self.part_s):
            if s <= b + 1e-9:
                return k
        return len(self.part_s) - 1


@dataclass
class Wall:
    kind: str  # "parapet" or "embankment"
    a: Tuple[float, float]
    b: Tuple[float, float]
    za: float  # road height at a
    zb: float
    bottom: float
    top: float

    @property
    def z_road(self):
        return max(self.za, self.zb)


def _pieces_from(model, road, i, step):
    """Indices of road's points walking from index i by step (+1/-1) to its end."""
    j = i
    out = [i]
    while 0 <= j + step < len(road.points):
        j += step
        out.append(j)
    return out


class Levels:
    DECK_HEIGHT = DECK_HEIGHT
    GRADE = GRADE
    CLEARANCE = CLEARANCE

    def __init__(self, model):
        self.model = model
        self.chains = []
        self._build_chains()
        self._build_ground()
        for c in self.chains:
            self._profile(c)
        self._build_elevated()
        self.heights = self._heights()

    # -------------------------------------------------- chains
    def _deck_ids(self):
        return {r.id for r in self.model.roads if r.bridge and r.level >= 1}

    def _build_chains(self):
        m = self.model
        decks = self._deck_ids()
        used = set()

        def deck_neighbours(rid, key):
            return [i for i in m.nodes[key].road_ids if i != rid and i in decks]

        for r in m.roads:
            if r.id not in decks or r.id in used:
                continue
            # walk back to the start of this run of decks
            cur, at_start = r, True
            seen = {r.id}
            while True:
                key = cur.keys[0] if at_start else cur.keys[-1]
                nb = [i for i in deck_neighbours(cur.id, key) if i not in seen]
                if len(nb) != 1:
                    break
                nxt = m.road(nb[0])
                seen.add(nxt.id)
                at_start = nxt.keys[-1] == key  # we arrive at its end: keep walking from its start
                cur = nxt
            # now walk forward from that end
            parts = []
            start_key = cur.keys[0] if at_start else cur.keys[-1]
            key = start_key
            while cur is not None:
                used.add(cur.id)
                if cur.keys[0] == key:
                    parts.append((cur.id, 0, len(cur.points) - 1))
                    key = cur.keys[-1]
                else:
                    parts.append((cur.id, len(cur.points) - 1, 0))
                    key = cur.keys[0]
                nb = [i for i in deck_neighbours(cur.id, key) if i not in used]
                cur = m.road(nb[0]) if len(nb) == 1 else None
            parts = self._extend(parts, at_end=False) + parts[0:0]
            parts = self._extend(parts, at_end=True)
            name = m.road(next(p[0] for p in parts if m.road(p[0]).id in decks)).name or "bridge %d" % parts[0][0]
            c = Chain(parts, name, [m.road(p[0]).width_m for p in parts],
                      [m.road(p[0]).id in decks for p in parts])
            pts = []
            for rid, i, j in parts:
                rp = m.road(rid).points
                seq = rp[i:j + 1] if i <= j else list(reversed(rp[j:i + 1]))
                if pts and seq and pts[-1] == seq[0]:
                    seq = seq[1:]
                pts += seq
            c.line = LineString(pts)
            s = 0.0
            for rid, i, j in parts:
                rp = m.road(rid).points
                seq = rp[i:j + 1] if i <= j else list(reversed(rp[j:i + 1]))
                L = sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))
                c.part_s.append((s, s + L))
                s += L
            self.chains.append(c)

    def _extend(self, parts, at_end):
        """Add the approach ways at one end of a chain of decks (see the module's doc)."""
        m = self.model
        notes = []
        if at_end:
            rid, i, j = parts[-1]
            key = m.road(rid).keys[j]
        else:
            rid, i, j = parts[0]
            key = m.road(rid).keys[i]
        prev = rid
        added = []
        reach = 0.0
        while True:
            others = [k for k in m.nodes[key].road_ids if k != prev]
            if len(others) != 1:
                break
            r = m.road(others[0])
            if r.bridge and r.level >= 1:
                break
            idx = r.keys.index(key)
            if idx == 0:
                step = 1
            elif idx == len(r.keys) - 1:
                step = -1
            else:
                break  # the approach meets the middle of another road: the foot is here
            seq = _pieces_from(m, r, idx, step)
            stop = None
            for a, b in zip(seq, seq[1:]):
                reach += math.dist(r.points[a], r.points[b])
                if len(m.nodes[r.keys[b]].road_ids) > 1 and b != seq[-1]:
                    stop = b
                    break
                if reach >= RAMP_REACH:
                    stop = b
                    break
            last = seq[-1] if stop is None else stop
            added.append((r.id, idx, last))
            if stop is not None:
                break
            prev, key = r.id, r.keys[last]
            if reach >= RAMP_REACH:
                break
        if at_end:
            return parts + added
        return [(rid, j, i) for rid, i, j in reversed(added)] + parts

    # -------------------------------------------------- ground and profiles
    def _chain_segments(self):
        """{road id: set of segment indices k (points k..k+1) that belong to a chain}."""
        out = {}
        for c in self.chains:
            for rid, i, j in c.parts:
                a, b = min(i, j), max(i, j)
                out.setdefault(rid, set()).update(range(a, b))
        return out

    def _ground_lines(self, exclude_raised_only=False, raised=None):
        """Buffers of every road's runs that are not in a (raised) chain."""
        segs = self._chain_segments_raised(raised) if raised is not None else self._chain_segments()
        bufs = []
        for r in self.model.roads:
            own = segs.get(r.id, set())
            run = []
            for k in range(len(r.points) - 1):
                if k in own:
                    if len(run) > 1:
                        bufs.append(LineString(run).buffer(r.width_m / 2, quad_segs=surfaces.QUAD_SEGS))
                    run = []
                    continue
                if not run:
                    run = [r.points[k]]
                run.append(r.points[k + 1])
            if len(run) > 1:
                bufs.append(LineString(run).buffer(r.width_m / 2, quad_segs=surfaces.QUAD_SEGS))
        return bufs

    def _chain_segments_raised(self, raised):
        out = {}
        for c in self.chains:
            if c not in raised:
                continue
            for rid, i, j in c.parts:
                a, b = min(i, j), max(i, j)
                out.setdefault(rid, set()).update(range(a, b))
        return out

    def _build_ground(self):
        # first the ground without any chain (for the feet and the crossings), then decide which chains rise
        self._g0 = surfaces._as_multi(shapely.union_all(self._ground_lines()))
        shapely.prepare(self._g0)

    def _profile(self, c):
        g = self._g0
        L = c.length

        def clear(s):
            w = c.widths[c.part_at(s)]
            p = c.line.interpolate(s)
            return not g.intersects(p.buffer(w / 2 + 0.5, quad_segs=4))

        def centre_clear(s):
            return g.distance(c.line.interpolate(s)) >= CENTRE_CLEAR

        def first_clear(from_b):
            s = 0.0
            while s < min(L / 2, FOOT_SEARCH):
                if clear(L - s if from_b else s):
                    return s, "junction at the foot clear after %.0f m" % s
                s += 1.0
            s = 0.0
            while s < L / 2:
                if centre_clear(L - s if from_b else s):
                    return s, "a ground road alongside: the centre line %.0f m clear of it after %.0f m" % (
                        CENTRE_CLEAR, s)
                s += 1.0
            return L / 2, "never clear"

        c.rise_a, na = first_clear(False)
        c.rise_b, nb = first_clear(True)
        # crossings: ground roads the chain's centre line crosses (not at a shared point)
        m = self.model
        mine = {rid for rid, _i, _j in c.parts}
        keys = set()
        for rid, i, j in c.parts:
            r = m.road(rid)
            keys.update(r.keys[min(i, j):max(i, j) + 1])
        for r in m.roads:
            if r.id in mine:
                continue
            gl = LineString(r.points)
            if not c.line.intersects(gl):
                continue
            inter = c.line.intersection(gl)
            pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
            shared = {(round(p[0], 6), round(p[1], 6)) for k, p in zip(r.keys, r.points) if k in keys}
            for q in pts:
                if q.geom_type == "Point" and (round(q.x, 6), round(q.y, 6)) not in shared:
                    c.crossings.append((c.line.project(q), r.id))
        c.crossings.sort()
        c.raised = True
        ok = bool(c.crossings) and all(c.z(s) >= CLEARANCE for s, _r in c.crossings)
        c.raised = ok
        c.foot_notes = ["foot A: " + na, "foot B: " + nb]
        if not ok:
            c.foot_notes.append("not raised: a crossing would be under %.1f m" % CLEARANCE)

    def _build_elevated(self):
        raised = [c for c in self.chains if c.raised]
        self.raised_chains = raised
        self.ground_polygon = surfaces._as_multi(shapely.union_all(self._ground_lines(raised=raised)))
        shapely.prepare(self.ground_polygon)
        bufs, low = [], []
        for c in raised:
            for (rid, i, j), w in zip(c.parts, c.widths):
                r = self.model.road(rid)
                seq = r.points[min(i, j):max(i, j) + 1]
                bufs.append(LineString(seq).buffer(w / 2, quad_segs=surfaces.QUAD_SEGS))
            wmax = max(c.widths)
            # the parts lower than the clearance, from each foot (plus the half width a buffer reaches beyond them)
            up = CLEARANCE / GRADE
            for a, b in ((0.0, c.rise_a + up + wmax / 2 + 1), (c.length - c.rise_b - up - wmax / 2 - 1, c.length)):
                sub = shapely.ops.substring(c.line, max(0.0, a), min(c.length, b))
                low.append(sub.buffer(wmax / 2 + 1, quad_segs=4))
        E = shapely.union_all(bufs) if bufs else Polygon()
        F = shapely.union_all(low) if low else Polygon()
        # where a ramp is lower than the clearance the ground road wins: the ramp is narrowed by it (a wall stands on
        # the seam where the ramp is above the ground); higher up the ground road passes under
        self.low_zone = F
        self.elevated = surfaces._as_multi(E.difference(self.ground_polygon.intersection(F)))
        shapely.prepare(self.elevated)
        self._lines = [c.line for c in raised]

    def _nearest(self, x, y):
        p = Point(x, y)
        best, bd = None, None
        for c in self.raised_chains:
            d = c.line.distance(p)
            if bd is None or d < bd:
                best, bd = c, d
        return best, p

    def z_at(self, x, y):
        """The elevated surface's height at (x, y): its nearest raised chain's height at the point's projection."""
        c, p = self._nearest(x, y)
        if c is None:
            return 0.0
        return c.z(c.line.project(p))

    def _heights(self):
        out = {r.id: [0.0] * len(r.points) for r in self.model.roads}
        for c in self.raised_chains:
            for rid, i, j in c.parts:
                r = self.model.road(rid)
                for k in range(min(i, j), max(i, j) + 1):
                    out[rid][k] = c.z(c.line.project(Point(r.points[k])))
        return out

    # -------------------------------------------------- geometry
    def knee_lines(self):
        """Lines across each raised chain where its profile bends (the rise's start and top at both ends): the
        elevated surface is cut along them so that a triangle never spans a bend (linear between its vertices, it
        would cut the corner by up to 6% of half a cell)."""
        out = []
        for c in self.raised_chains:
            L = c.length
            w = max(c.widths) + 4.0
            up = DECK_HEIGHT / GRADE
            for s in (c.rise_a, c.rise_a + up, L - c.rise_b - up, L - c.rise_b):
                if not 0.0 <= s <= L:
                    continue
                p = c.line.interpolate(s)
                q = c.line.interpolate(min(L, s + 0.5))
                r = c.line.interpolate(max(0.0, s - 0.5))
                dx, dy = q.x - r.x, q.y - r.y
                n = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / n * w, dx / n * w
                out.append(LineString([(p.x - nx, p.y - ny), (p.x + nx, p.y + ny)]))
        return out

    def _pieces(self, poly):
        from shapely.ops import split
        pieces = [poly]
        for ln in self._knees:
            nxt = []
            for g in pieces:
                if g.intersects(ln):
                    nxt += [q for q in split(g, ln).geoms if q.geom_type == "Polygon"]
                else:
                    nxt.append(g)
            pieces = nxt
        return pieces

    def deck_surfaces(self, window=None):
        """[((x, y, z), (x, y, z), (x, y, z))] of the elevated surface (counter-clockwise from above), cut along the
        profile's bends (knee_lines)."""
        poly = self.elevated if window is None else self.elevated.intersection(window)
        if not hasattr(self, "_knees"):
            self._knees = self.knee_lines()
        out = []
        cache = {}
        tris2 = []
        for part in self._pieces(poly):
            for g in (part.geoms if hasattr(part, "geoms") else [part]):
                tris2 += surfaces.triangulate(g, DECK_EDGE)
        for t in tris2:
            tri = []
            for x, y in t:
                z = cache.get((x, y))
                if z is None:
                    z = cache[(x, y)] = self.z_at(x, y)
                tri.append((x, y, z))
            out.append(tuple(tri))
        return out

    def _bridge_at(self, x, y):
        c, p = self._nearest(x, y)
        return c.bridge[c.part_at(c.line.project(p))]

    def walls(self):
        """[Wall] along the elevated surface's outline, cut in pieces of at most WALL_PIECE metres."""
        out = []
        for poly in self.elevated.geoms:
            for ring in [poly.exterior] + list(poly.interiors):
                pts = list(ring.coords)
                for a, b in zip(pts, pts[1:]):
                    L = math.dist(a, b)
                    n = max(1, int(math.ceil(L / WALL_PIECE)))
                    for k in range(n):
                        p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                        q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
                        zp, zq = self.z_at(*p), self.z_at(*q)
                        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                        zr = max(zp, zq)
                        seam = self.ground_polygon.distance(Point(mid)) < 0.01
                        if seam and zr < SEAM:
                            continue  # the ramp meets the ground road at ground: no wall
                        if not seam and zr <= WALL_FROM:
                            continue  # a low edge over open ground: drivable off and on
                        if zr >= CLEARANCE and self._bridge_at(*mid):
                            out.append(Wall("parapet", p, q, zp, zq, min(zp, zq), zr + PARAPET))
                        else:
                            out.append(Wall("embankment", p, q, zp, zq, 0.0, zr + PARAPET))
        return out

    def pillars(self):
        """[(footprint polygon, top height)] under the bridge ways."""
        out = []
        g = self.ground_polygon
        for c in self.raised_chains:
            for k, (a, b) in enumerate(c.part_s):
                if not c.bridge[k]:
                    continue
                s = a + PILLAR_STEP / 2
                while s < b:
                    z = c.z(s)
                    if z >= CLEARANCE:
                        p = c.line.interpolate(s)
                        q = c.line.interpolate(min(c.length, s + 1.0))
                        h = math.atan2(q.y - p.y, q.x - p.x)
                        ca, sa = math.cos(h) * PILLAR / 2, math.sin(h) * PILLAR / 2
                        fp = Polygon([(p.x + ca - sa, p.y + sa + ca), (p.x - ca - sa, p.y - sa + ca),
                                      (p.x - ca + sa, p.y - sa - ca), (p.x + ca + sa, p.y + sa - ca)])
                        if not g.intersects(fp.buffer(0.5)):
                            out.append((fp, z))
                    s += PILLAR_STEP
        return out


def build(model):
    import shapely.ops  # noqa: F401
    return Levels(model)


def heights(model):
    return build(model).heights


def deck_surfaces(model):
    return build(model).deck_surfaces()
