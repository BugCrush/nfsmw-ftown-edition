"""F-Town's road network for the game's AI (traffic now; racers and cops later), from our road model, and the data
file FTownLoader appends to Rockport's network (plan docs/superpowers/plans/2026-11-05-ftown-moving-traffic.md Task 2,
research docs/ftown-traffic-ai-research.md).

    .tools/cityenv/Scripts/python tools/citymap/roadnet_build.py

writes ftown/ftown-roadnet.bin (git-ignored: drawn from OSM), ftown/ftown-roadnet.json (its numbers) and a picture
.superpowers/citymap/faridabad/roadnet-preview.png. Rebuild it whenever the road model, the city (ftown-city.bun: the
node heights), the events or the traffic spots change.

Built Rockport's way (E1): every road of the model inside the built city's edge box (less 15 m) is cut at the points
it shares with other roads (junctions); each arm of a junction ends in a "mouth" node min(8 m, a third of the arm)
back from the junction point, and every pair of a junction's mouths is joined by a decision segment (Decision |
Intersection, road -1); between mouths a road is cut into pieces of at most 30 m (a node also at every bend of more
than 20 degrees), each a cubic curve from the centre line's direction at its two nodes. One profile per lane layout:
right-hand traffic (the research: forward lanes are those at or right of the middle zone and the AI's edges assume
lanes left to right), lanes (width less shoulders) / lane count wide, a 0.5 m cop lane (type 3) at each edge of the
main kinds, the whole as wide as the built carriageway (the city buffers the centre line by width / 2). One-way roads:
OneWay on every piece, node 0 to node 1 along the road. Service roads and living streets: NoTraffic. Heights: the
built city's faces at each node (level 1: the highest, else the lowest; none: the terrain plane at 100 m). Numbers
start after Rockport's (710 profiles, 4,385 nodes, 6,538 segments, 1,308 roads): FTownLoader appends ours unchanged.

The data file (little-endian, version 1):
    0x00 'FTRN', u32 1
    0x08 u32 Rockport's profiles, nodes, segments, roads (the counts FTownLoader expects in the game)
    0x18 u32 our profiles, nodes, segments, roads
    0x28 f32 the grid's min x, min z, edge (expected), u32 rows, cols (expected), u32 columns we add on its low-x side
    0x40 u32 cells, cell tags, events, parking entries
    0x50 u32 the traffic spots the parking list is for, u32 0 x 3
    0x60 profiles (64 B), nodes (32 B), segments (22 B; padded to 4), roads (8 B), u8 km/h per segment (padded to 4),
         cells {u32 cell in the widened grid, u32 first tag, u32 count}, u32 tags (segment numbers),
         events {char id[16], u32 first mark, u32 count}, u32 marks (segment | 0x10000 forward | 0x20000 exit),
         u8 parking per traffic spot (1: a kerb spot kept with moving traffic; padded to 4)
"""
import collections
import hashlib
import json
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if os.path.join(REPO, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "tools"))

from tools.citymap import roadmodel  # noqa: E402
from world import roadnet  # noqa: E402

AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
ROADS = os.path.join(AREA, "ftown-roads.json")
CITY = os.path.join(REPO, "ftown", "ftown-city.bun")
CITY_JSON = os.path.join(REPO, "ftown", "ftown-city.json")
EVENTS = os.path.join(REPO, "ftown", "ftown-events.json")
SPOTS = os.path.join(REPO, "ftown", "ftown-traffic.json")
L2RA = os.path.join(REPO, "Need For Speed Most Wanted Black Edition", "TRACKS", "L2RA.BUN")
OUT_BIN = os.path.join(REPO, "ftown", "ftown-roadnet.bin")
OUT_JSON = os.path.join(REPO, "ftown", "ftown-roadnet.json")
PREVIEW = os.path.join(AREA, "roadnet-preview.png")

PIECE = 30.0       # metres at most between nodes along a road
MOUTH = 8.0        # a mouth node this far back from the junction point (a third of a shorter arm)
BEND = 20.0        # degrees: a node at every sharper bend of the centre line
BOX_INSET = 15.0   # metres inside the city's edge box (its walls stand on the box)
GRID_MARGIN = 256.0
NO_TRAFFIC_KINDS = {"service", "living_street"}
# the posted speed of each kind (km/h): FTownLoader gives traffic on our segments this, times 0.85..1.15 a car
KMH = {"motorway": 80, "motorway_link": 40, "trunk": 70, "trunk_link": 40, "primary": 60, "primary_link": 40,
       "secondary": 55, "secondary_link": 40, "tertiary": 45, "tertiary_link": 40, "residential": 35,
       "unclassified": 35, "road": 35, "living_street": 20, "service": 20}
COP_LANE = 0.5     # the main kinds' shoulders (roadmodel.SHOULDER), as cop lanes (type 3) as Rockport's shoulders are


@dataclass
class Rockport:
    profiles: int
    nodes: int
    segments: int
    roads: int
    grid_min: tuple  # physics (x, z)
    edge: float
    rows: int
    cols: int


@dataclass
class RockMouth:
    """One of the Rockport junction's mouth nodes the connector joins (docs/ftown-connection-research.md C5): its
    number, render position, the direction its road leaves the junction (render x, y), whether its decision segments
    read the profile inverted at its end, and its segment list as the game's file has it."""
    index: int
    pos: tuple
    out_dir: tuple
    inverted: bool
    segments: List[int]


@dataclass
class Link:
    """The connector (tools/citymap/connector.network_road): its centre line [(x, y, z)] from Rockport's junction to
    the middle of Mathura Road's carriageways on the clipping box, and Rockport's side."""
    points: list
    width_m: float
    lanes: int
    kind: str
    junction: tuple
    mouths: List[RockMouth]
    carriageways: List[int]


@dataclass
class Join:
    rock_node: int
    before: List[int]
    added: int


@dataclass
class Built:
    net: roadnet.Network
    kmh: List[int]
    cells: Dict[int, List[int]]
    events: Dict[str, Dict[int, str]]
    parking: List[int]
    pad_cols: int
    rock: Rockport
    road_kind: List[str]
    road_model: list
    road_profile: List[int]
    segment_kinds: List[set]
    max_curve_error: float
    km: float = 0.0
    stats: dict = field(default_factory=dict)
    joins: List[Join] = field(default_factory=list)
    rock_cells: Dict[int, List[int]] = field(default_factory=dict)
    link_segments: List[int] = field(default_factory=list)


class _LinkRoad:
    """The connector as a road of the model (roadmodel.Road's fields that build reads)."""

    def __init__(self, link):
        self.id, self.kind, self.name = -1, link.kind, "Rockport Link"
        self.width_m, self.lanes, self.oneway, self.level = link.width_m, link.lanes, False, 0
        self.points = [(p[0], p[1]) for p in link.points]
        self.keys = ["LINK_R"] + [None] * (len(link.points) - 2) + ["LINK_F"]


# ---------------------------------------------------------------- geometry

def _phys(x, y, z):
    return (-y, z, x)


def _unit(v):
    L = math.hypot(*v)
    return (v[0] / L, v[1] / L) if L > 1e-9 else (1.0, 0.0)


def _clip(points, keys, box):
    """Runs [(x, y, key)] of a polyline inside box (x0, y0, x1, y1); a cut point has key None."""
    x0, y0, x1, y1 = box

    def inside(p):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1

    def cross(p, q):
        """parameters in (0, 1) where p->q crosses the box's edges, sorted."""
        ts = []
        for a, b, lo, hi in ((p[0], q[0], x0, x1), (p[1], q[1], y0, y1)):
            if b != a:
                for v in (lo, hi):
                    t = (v - a) / (b - a)
                    if 0 < t < 1:
                        m = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
                        if x0 - 1e-6 <= m[0] <= x1 + 1e-6 and y0 - 1e-6 <= m[1] <= y1 + 1e-6:
                            ts.append(t)
        return sorted(ts)

    runs, cur = [], []
    for i, (p, k) in enumerate(zip(points, keys)):
        if i:
            q = points[i - 1]
            for t in cross(q, p):
                m = (q[0] + (p[0] - q[0]) * t, q[1] + (p[1] - q[1]) * t, None)
                if cur:
                    cur.append(m)
                    runs.append(cur)
                    cur = []
                else:
                    cur = [m]
        if inside(p):
            cur.append((p[0], p[1], k))
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


class Edge:
    """A piece of a road between two junction points or ends: its centre line, keys and arc lengths."""

    def __init__(self, road, pts, keys, start_j, end_j):
        self.road, self.pts, self.keys, self.start_j, self.end_j = road, pts, keys, start_j, end_j
        self.s = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.s.append(self.s[-1] + math.dist(a, b))
        self.length = self.s[-1]
        self.nodes = []  # (s, local node number)

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        for i in range(len(self.pts) - 1):
            if s <= self.s[i + 1] or i == len(self.pts) - 2:
                L = self.s[i + 1] - self.s[i]
                t = 0.0 if L <= 0 else (s - self.s[i]) / L
                a, b = self.pts[i], self.pts[i + 1]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def tangent(self, s):
        """The centre line's direction at s; at a vertex the mean of the two pieces' directions."""
        eps = 1e-6
        for i in range(1, len(self.pts) - 1):
            if abs(s - self.s[i]) < 1e-3:
                d0 = _unit((self.pts[i][0] - self.pts[i - 1][0], self.pts[i][1] - self.pts[i - 1][1]))
                d1 = _unit((self.pts[i + 1][0] - self.pts[i][0], self.pts[i + 1][1] - self.pts[i][1]))
                return _unit((d0[0] + d1[0], d0[1] + d1[1]))
        for i in range(len(self.pts) - 1):
            if s <= self.s[i + 1] + eps or i == len(self.pts) - 2:
                a, b = self.pts[i], self.pts[i + 1]
                return _unit((b[0] - a[0], b[1] - a[1]))

    def bends(self, lo, hi):
        out = []
        for i in range(1, len(self.pts) - 1):
            if lo + 1.0 < self.s[i] < hi - 1.0:
                d0 = _unit((self.pts[i][0] - self.pts[i - 1][0], self.pts[i][1] - self.pts[i - 1][1]))
                d1 = _unit((self.pts[i + 1][0] - self.pts[i][0], self.pts[i + 1][1] - self.pts[i][1]))
                ang = math.degrees(math.acos(max(-1.0, min(1.0, d0[0] * d1[0] + d0[1] * d1[1]))))
                if ang > BEND:
                    out.append(self.s[i])
        return out


def _bezier(p0, c0, c1, p1, t):
    u = 1 - t
    return tuple(u * u * u * p0[k] + 3 * u * u * t * c0[k] + 3 * u * t * t * c1[k] + t * t * t * p1[k]
                 for k in range(len(p0)))


# ---------------------------------------------------------------- profiles

def lanes_of(r):
    """(forward lanes, backward lanes) of a road (right-hand traffic)."""
    n = max(1, r.lanes)
    if r.oneway:
        return n, 0
    if n == 1:
        return 1, 1
    return n - n // 2, n // 2


def profile_of(r):
    """roadnet.Profile for a road: [cop] backward lanes (outer to inner) forward lanes (inner to outer) [cop]."""
    sh = COP_LANE if r.kind in roadmodel.MAIN else 0.0
    tw = r.width_m - 2 * sh
    nf, nb = lanes_of(r)
    lw = tw / (nf + nb)
    divider = -tw / 2 + nb * lw  # render: left of the road negative
    zones = []  # (type, width, position from the centre line, positive to the right)
    if sh:
        zones.append((roadnet.LANE_COP, sh, -tw / 2 - sh / 2))
    for j in reversed(range(nb)):
        zones.append((roadnet.LANE_TRAFFIC, lw, divider - (j + 0.5) * lw))
    middle = len(zones)
    for i in range(nf):
        zones.append((roadnet.LANE_TRAFFIC, lw, divider + (i + 0.5) * lw))
    if sh:
        zones.append((roadnet.LANE_COP, sh, tw / 2 + sh / 2))
    if r.oneway:
        middle = 0
    # stored offset: the distance on the lane's own side (GetRelativeLaneOffset negates lanes left of the middle)
    lanes = [(t, w, pos if i >= middle else -pos) for i, (t, w, pos) in enumerate(zones)]
    return roadnet.Profile.make(lanes, middle)


# ---------------------------------------------------------------- the network

def build(model, heights, box, rock, events=(), spots=(), link=None):
    """Built from a RoadModel; heights(xs, ys, levels) -> z list (render metres); box (x0, y0, x1, y1) render. With
    `link` (a Link) the connector to Rockport is one more road: joined at its far end (LINK_F, on the box) to the two
    carriageways it names where the box clips them, at its Rockport end (LINK_R) a mouth node and one decision segment to
    each of Rockport's mouths (the joins); its nodes take the link's own heights."""
    from shapely.geometry import LineString, Point
    runs = []
    for r in model.roads:
        for run in _clip(r.points, r.keys, box):
            if sum(math.dist(a[:2], b[:2]) for a, b in zip(run, run[1:])) > 1.0:
                runs.append((r, run))
    link_road = None
    if link is not None:
        lf = tuple(link.points[-1][:2])
        joined = 0
        for i, (r, run) in enumerate(runs):
            if r.id in link.carriageways:
                d0, d1 = math.dist(run[0][:2], lf), math.dist(run[-1][:2], lf)
                if min(d0, d1) > 30.0:
                    continue
                runs[i] = (r, [(lf[0], lf[1], "LINK_F")] + run if d0 < d1 else run + [(lf[0], lf[1], "LINK_F")])
                joined += 1
        if joined != len(link.carriageways):
            raise ValueError("the link meets %d of its %d carriageways at the box" % (joined, len(link.carriageways)))
        link_road = _LinkRoad(link)
        runs.append((link_road, [(x, y, k) for (x, y), k in zip(link_road.points, link_road.keys)]))
    occ = collections.Counter(k for _r, run in runs for (_x, _y, k) in run if k)
    junction = {k for k, n in occ.items() if n >= 2}
    if link_road is not None:
        junction.add("LINK_R")
    edges = []
    for r, run in runs:
        start = 0
        for i in range(1, len(run)):
            if i == len(run) - 1 or run[i][2] in junction:
                piece = run[start:i + 1]
                pts = [(p[0], p[1]) for p in piece]
                keys = [p[2] for p in piece]
                sj = keys[0] if keys[0] in junction else None
                ej = keys[-1] if keys[-1] in junction else None
                e = Edge(r, pts, keys, sj, ej)
                if e.length > 0.05:
                    edges.append(e)
                start = i
    arms = collections.defaultdict(list)  # junction key -> [(edge number, end 0 start / 1 end)]
    for n, e in enumerate(edges):
        if e.start_j:
            arms[e.start_j].append((n, 0))
        if e.end_j:
            arms[e.end_j].append((n, 1))
    too_many = {k: len(v) for k, v in arms.items() if len(v) > 7}
    if too_many:
        raise ValueError("junctions with more than 7 arms (the node's 7 segment slots): %s" % too_many)

    # profiles and roads (one road record per edge)
    prof_index, profiles = {}, []
    road_kind, road_model, road_profile, roads = [], [], [], []
    for e in edges:
        p = profile_of(e.road)
        key = (p.middle, tuple(p.words))
        if key not in prof_index:
            prof_index[key] = len(profiles)
            profiles.append(p)
        e.profile = rock.profiles + prof_index[key]
        e.number = rock.roads + len(roads)
        tw = sum(w for _t, w, _o in p.lanes())
        roads.append(roadnet.Road(256, min(65535, int(round(e.length * 65535.0 / 4000.0))), 255,
                                  min(255, int(tw * 8.5)), 0))
        road_kind.append(e.road.kind)
        road_model.append(e.road)
        road_profile.append(e.profile)

    # nodes along each edge
    node_xy, node_prof, node_level, node_tan, node_link_s = [], [], [], [], []
    mouth = {}  # (edge, end) -> local node
    for n, e in enumerate(edges):
        d0 = min(MOUTH, e.length / 3) if e.start_j else 0.0
        d1 = min(MOUTH, e.length / 3) if e.end_j else 0.0
        lo, hi = d0, e.length - d1
        # a bend gets a node a little before and after it (the centre line's own directions there), so the short
        # curve between them rounds the corner as a fillet would
        breaks = [lo]
        bends = e.bends(lo, hi)
        for i, sb in enumerate(bends):
            prev = bends[i - 1] if i else lo
            nxt = bends[i + 1] if i + 1 < len(bends) else hi
            r = min(4.0, (sb - prev) / 3, (nxt - sb) / 3)
            breaks += [sb - r, sb + r]
        breaks.append(hi)
        ss = [lo]
        line = LineString(e.pts)
        for a, b in zip(breaks, breaks[1:]):
            k = max(1, int(math.ceil((b - a) / PIECE - 1e-9)))
            for i in range(1, k + 1):
                ss += _fit(e, line, a + (b - a) * (i - 1) / k, a + (b - a) * i / k)
        for s in ss:
            e.nodes.append((s, len(node_xy)))
            node_xy.append(e.at(s))
            node_prof.append(e.profile)
            node_level.append(e.road.level)
            node_tan.append(e.tangent(s))
            node_link_s.append(s if e.road is link_road else None)
        mouth[(n, 0)] = e.nodes[0][1]
        mouth[(n, 1)] = e.nodes[-1][1]
    zs = list(heights([p[0] for p in node_xy], [p[1] for p in node_xy], node_level))
    if link_road is not None:
        ls = [0.0]
        for a, b in zip(link.points, link.points[1:]):
            ls.append(ls[-1] + math.dist(a[:2], b[:2]))
        for i, s in enumerate(node_link_s):
            if s is None:
                continue
            k = next((j for j in range(1, len(ls)) if ls[j] >= s), len(ls) - 1)
            t = 0.0 if ls[k] <= ls[k - 1] else (s - ls[k - 1]) / (ls[k] - ls[k - 1])
            zs[i] = link.points[k - 1][2] + (link.points[k][2] - link.points[k - 1][2]) * min(1.0, max(0.0, t))
    node_segs = [[] for _ in node_xy]
    segments, kmh, seg_kinds, seg_edge = [], [], [], []
    max_err = 0.0

    def add_segment(a, b, flags, road, t0, t1, h0, h1, speed, kinds, where=None):
        pa = _phys(node_xy[a][0], node_xy[a][1], zs[a])
        pb = _phys(node_xy[b][0], node_xy[b][1], zs[b])
        dz = zs[b] - zs[a]
        chord = math.dist(node_xy[a], node_xy[b]) or 0.01
        g = dz / chord
        sd = _phys(t0[0], t0[1], g)
        ed = _phys(t1[0], t1[1], g)
        c0 = tuple(pa[k] + sd[k] / math.sqrt(1 + g * g) * h0 for k in range(3))
        c1 = tuple(pb[k] - ed[k] / math.sqrt(1 + g * g) * h1 for k in range(3))
        pts = [_bezier(pa, c0, c1, pb, i / 16.0) for i in range(17)]
        length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        ch = _unit((node_xy[b][0] - node_xy[a][0], node_xy[b][1] - node_xy[a][1]))
        straight = min(t0[0] * ch[0] + t0[1] * ch[1], t1[0] * ch[0] + t1[1] * ch[1]) > math.cos(math.radians(2.0))
        if not straight:
            flags |= roadnet.CURVED
        idx = rock.segments + len(segments)
        s = roadnet.Segment.make(rock.nodes + a, rock.nodes + b, length, road, idx, flags, sd, ed, h0, h1)
        segments.append(s)
        kmh.append(speed)
        seg_kinds.append(kinds)
        seg_edge.append(where)
        node_segs[a].append(idx)
        node_segs[b].append(idx)
        return pts

    for n, e in enumerate(edges):
        r = e.road
        flags = (roadnet.ONE_WAY if r.oneway else 0) | (roadnet.NO_TRAFFIC if r.kind in NO_TRAFFIC_KINDS else 0)
        line = LineString(e.pts)
        for (s0, a), (s1, b) in zip(e.nodes, e.nodes[1:]):
            chord = math.dist(node_xy[a], node_xy[b])
            pts = add_segment(a, b, flags, e.number, node_tan[a], node_tan[b], chord / 3, chord / 3, KMH[r.kind],
                              {r.kind}, (n, s0, s1))
            for p in pts:
                max_err = max(max_err, line.distance(Point(p[2], -p[0])))
    for key, alist in arms.items():
        jx = edges[alist[0][0]].pts[0 if alist[0][1] == 0 else -1]
        for i in range(len(alist)):
            for j in range(i + 1, len(alist)):
                (ea, enda), (eb, endb) = alist[i], alist[j]
                a, b = mouth[(ea, enda)], mouth[(eb, endb)]
                ta = node_tan[a] if enda == 1 else (-node_tan[a][0], -node_tan[a][1])
                tb = node_tan[b] if endb == 0 else (-node_tan[b][0], -node_tan[b][1])
                flags = roadnet.DECISION | roadnet.INTERSECTION
                if enda == 0:
                    flags |= roadnet.START_INVERTED
                if endb == 1:
                    flags |= roadnet.END_INVERTED
                ka, kb = edges[ea].road.kind, edges[eb].road.kind
                if ka in NO_TRAFFIC_KINDS or kb in NO_TRAFFIC_KINDS:
                    flags |= roadnet.NO_TRAFFIC
                ha = max(0.5, 0.55 * math.dist(node_xy[a], jx))
                hb = max(0.5, 0.55 * math.dist(node_xy[b], jx))
                add_segment(a, b, flags, -1, ta, tb, ha, hb, min(KMH[ka], KMH[kb]), {ka, kb}, ("J", key, a, b))
    joins, rock_pos = [], {}
    link_edge = next((n for n, e in enumerate(edges) if e.road is link_road), None) if link_road is not None else None
    if link_edge is not None:
        a = mouth[(link_edge, 0)]
        jx = link.junction
        for m in link.mouths:
            pa = _phys(node_xy[a][0], node_xy[a][1], zs[a])
            pb = _phys(*m.pos)
            rock_pos[m.index] = pb
            t0 = (-node_tan[a][0], -node_tan[a][1])  # from our mouth into the junction
            g = (m.pos[2] - zs[a]) / (math.dist(node_xy[a], m.pos[:2]) or 0.01)
            sd, ed = _phys(t0[0], t0[1], g), _phys(m.out_dir[0], m.out_dir[1], g)
            ha = max(0.5, 0.55 * math.dist(node_xy[a], jx))
            hb = max(0.5, 0.55 * math.dist(m.pos[:2], jx))
            c0 = tuple(pa[k] + sd[k] / math.sqrt(1 + g * g) * ha for k in range(3))
            c1 = tuple(pb[k] - ed[k] / math.sqrt(1 + g * g) * hb for k in range(3))
            pts = [_bezier(pa, c0, c1, pb, i / 16.0) for i in range(17)]
            length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
            flags = roadnet.DECISION | roadnet.INTERSECTION | roadnet.START_INVERTED | roadnet.CURVED
            if m.inverted:
                flags |= roadnet.END_INVERTED
            idx = rock.segments + len(segments)
            segments.append(roadnet.Segment.make(rock.nodes + a, m.index, length, -1, idx, flags, sd, ed, ha, hb))
            kmh.append(50)
            seg_kinds.append({link.kind})
            seg_edge.append(("JOIN", m.index))
            node_segs[a].append(idx)
            joins.append(Join(m.index, list(m.segments), idx))
    pruned = _prune_dead_ends(segments, node_segs, rock)
    over = [len(s) for s in node_segs if len(s) > 7]
    if over:
        raise ValueError("%d nodes with more than 7 segments" % len(over))
    nodes = [roadnet.Node(_phys(node_xy[i][0], node_xy[i][1], zs[i]), rock.nodes + i, node_prof[i], node_segs[i])
             for i in range(len(node_xy))]
    net = roadnet.Network(roadnet.Header(len(profiles), len(nodes), len(segments), 0, len(roads), 0),
                          profiles, nodes, segments, roads)

    # the grid: our columns on the low-x side of Rockport's
    min_x = min(n.pos[0] for n in nodes) - GRID_MARGIN
    pad = max(1, int(math.ceil((rock.grid_min[0] - min_x) / rock.edge)))
    cols = rock.cols + pad
    gx = rock.grid_min[0] - pad * rock.edge
    zmax = rock.grid_min[1] + rock.rows * rock.edge
    cells = collections.defaultdict(set)
    rock_cells = collections.defaultdict(set)
    for s in segments:
        a = nodes[s.nodes[0] - rock.nodes]
        if s.nodes[1] >= rock.nodes:
            b = nodes[s.nodes[1] - rock.nodes]
            pa, pb = a.pos, b.pos
            half = max(_half_width(profiles[a.profile - rock.profiles]),
                       _half_width(profiles[b.profile - rock.profiles]))
        else:
            pa, pb = a.pos, rock_pos[s.nodes[1]]
            half = _half_width(profiles[a.profile - rock.profiles])
        c0 = tuple(pa[k] + v for k, v in enumerate(s.start_control()))
        c1 = tuple(pb[k] + v for k, v in enumerate(s.end_control()))
        rad = half + 2.0
        k = max(4, int(math.ceil(s.length_m / 2.0)))
        for i in range(k + 1):
            p = _bezier(pa, c0, c1, pb, i / k)
            if not rock.grid_min[1] <= p[2] < zmax:
                raise ValueError("a segment outside the grid's rows (physics z %.1f)" % p[2])
            for col in range(int((p[0] - rad - gx) // rock.edge), int((p[0] + rad - gx) // rock.edge) + 1):
                for row in range(int((p[2] - rad - rock.grid_min[1]) // rock.edge),
                                 int((p[2] + rad - rock.grid_min[1]) // rock.edge) + 1):
                    if 0 <= row < rock.rows and 0 <= col < pad:
                        cells[row * cols + col].add(s.index)
                    elif 0 <= row < rock.rows and pad <= col < cols and link_road is not None:
                        rock_cells[row * rock.cols + col - pad].add(s.index)
    cells = {c: sorted(v) for c, v in sorted(cells.items())}
    rock_cells = {c: sorted(v) for c, v in sorted(rock_cells.items())}
    link_segments = []
    if link_edge is not None:
        link_mouths = {mouth[(link_edge, 0)], mouth[(link_edge, 1)]}
        for s, where in zip(segments, seg_edge):
            on_link = where is not None and (where[0] == link_edge or where[0] == "JOIN")
            turn = s.flags & roadnet.DECISION and any(k - rock.nodes in link_mouths for k in s.nodes if k >= rock.nodes)
            if on_link or turn:
                link_segments.append(s.index)

    # the events' routes
    marks_by_event = {}
    for ev in events:
        marks_by_event[ev["id"]] = _route_marks(ev["keys"], edges, arms, mouth, segments, seg_edge, rock)
    parking = _parking(spots, edges)
    km = sum(e.length for e in edges) / 1000.0
    return Built(net, kmh, cells, marks_by_event, parking, pad, rock, road_kind, road_model, road_profile, seg_kinds,
                 max_err, km, {"junctions": len(arms), "edges": len(edges), "dead_end_closed": pruned}, joins,
                 rock_cells, sorted(link_segments))


def _prune_dead_ends(segments, node_segs, rock):
    """NoTraffic on every branch that leads only to dead ends (the review: Rockport has no end node on a segment that
    allows traffic; a traffic car there stops for good, GetNextTraffic / PrivateIncNavPosition's fDeadEnd). A node is
    closed when at most one of its segments allows traffic, or when it has turns but its road piece is closed; all its
    segments are then closed, until nothing changes. Returns the segments closed."""
    seg = {s.index: s for s in segments}
    closed = 0
    todo = list(range(len(node_segs)))
    while todo:
        nxt = set()
        for n in todo:
            allowed = [k for k in node_segs[n] if not seg[k].flags & roadnet.NO_TRAFFIC]
            if not allowed:
                continue
            roads_open = [k for k in allowed if not seg[k].flags & roadnet.DECISION]
            has_turns = any(seg[k].flags & roadnet.DECISION for k in node_segs[n])
            if len(allowed) == 1 or (has_turns and not roads_open):
                for k in allowed:
                    seg[k].flags |= roadnet.NO_TRAFFIC
                    closed += 1
                    for e in seg[k].nodes:
                        if e >= rock.nodes:
                            nxt.add(e - rock.nodes)
        todo = sorted(nxt)
    return closed


FIT = 0.5  # metres: a piece whose curve strays further from the centre line is halved (down to 2 m)


def _fit(e, line, a, b):
    """The node places after a up to b: b, or more where the curve between a and b strays over FIT metres."""
    from shapely.geometry import Point
    pa, pb = e.at(a), e.at(b)
    ta, tb = e.tangent(a), e.tangent(b)
    L = math.dist(pa, pb) / 3
    c0 = (pa[0] + ta[0] * L, pa[1] + ta[1] * L)
    c1 = (pb[0] - tb[0] * L, pb[1] - tb[1] * L)
    err = max(line.distance(Point(_bezier(pa, c0, c1, pb, t / 8.0))) for t in range(1, 8))
    if err <= FIT or b - a < 2.0:
        return [b]
    m = (a + b) / 2
    return _fit(e, line, a, m) + _fit(e, line, m, b)


def _half_width(p):
    return max(abs((o if i >= p.middle else -o)) + w / 2 for i, (t, w, o) in enumerate(p.lanes()))


def _route_marks(keys, edges, arms, mouth, segments, seg_edge, rock):
    """{segment number: "forward" | "backward" | "exit"} for a route given as model keys in driving order."""
    pairs = {(a, b) for a, b in zip(keys, keys[1:])}
    marks = {}
    for i, s in enumerate(segments):
        w = seg_edge[i]
        if w is None or w[0] in ("J", "JOIN"):
            continue
        n, s0, s1 = w
        e = edges[n]
        for k in range(len(e.keys) - 1):
            ka, kb = e.keys[k], e.keys[k + 1]
            lo, hi = e.s[k], e.s[k + 1]
            if min(hi, s1) - max(lo, s0) <= 0.1:
                continue
            if (ka, kb) in pairs:
                marks[s.index] = "forward"
            elif (kb, ka) in pairs:
                marks[s.index] = "backward"
    dec = {}
    for i, s in enumerate(segments):
        w = seg_edge[i]
        if w is not None and w[0] == "J":
            dec[(w[2], w[3])] = s.index
    for p, j, nx in zip(keys, keys[1:], keys[2:]):
        if j not in arms:
            continue
        a = b = None
        for en, end in arms[j]:
            e = edges[en]
            near = e.keys[1] if end == 0 else e.keys[-2]
            if near == p and a is None:
                a = mouth[(en, end)]
            elif near == nx and b is None:
                b = mouth[(en, end)]
        if a is None or b is None:
            continue
        for (x, y), sn in dec.items():
            if (x, y) == (a, b):
                marks[sn] = "forward"
            elif (x, y) == (b, a):
                marks[sn] = "backward"
            elif (x in (a, b) or y in (a, b)) and sn not in marks:
                marks[sn] = "exit"
    return marks


def _parking(spots, edges):
    """Per traffic spot 1 when a parked car may stand there with moving traffic: a kerb spot (kind 0) beside a side of
    the road with at least two traffic lanes, so one lane stays free (right-hand traffic: the left kerb, facing along
    the road, has the backward lanes)."""
    if not spots:
        return []
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    lines = [LineString(e.pts) for e in edges]
    tree = STRtree(lines)
    out = []
    for sp in spots:
        x, y, _z, _h, _route, kind = sp[:6]
        if kind != 0:
            out.append(0)
            continue
        p = Point(x, y)
        best, bd = None, None
        for i in tree.query(p.buffer(12.0)):
            d = lines[i].distance(p)
            if bd is None or d < bd:
                best, bd = int(i), d
        if best is None:
            out.append(0)
            continue
        e = edges[best]
        s = lines[best].project(p)
        t = e.tangent(s)
        q = e.at(s)
        left = t[0] * (y - q[1]) - t[1] * (x - q[0]) > 0
        nf, nb = lanes_of(e.road)
        out.append(1 if bd <= e.road.width_m / 2 + 1.0 and (nf if e.road.oneway else nb if left else nf) >= 2 else 0)
    return out


# ---------------------------------------------------------------- the file

def _pad4(b):
    return b + b"\0" * ((-len(b)) % 4)


def write_file(built, path):
    net, rock = built.net, built.rock
    e = roadnet.encode(net)
    events = sorted(built.events.items())
    marks, ev_recs = [], []
    for eid, m in events:
        first = len(marks)
        for s, kind in sorted(m.items()):
            marks.append(s | (0x10000 if kind == "forward" else 0) | (0x20000 if kind == "exit" else 0))
        ev_recs.append(struct.pack("<16sII", eid.encode("ascii")[:15], first, len(marks) - first))
    cells, tags = [], []
    for c, v in built.cells.items():
        cells.append(struct.pack("<3I", c, len(tags), len(v)))
        tags += v
    rcells, rtags = [], []
    for c, v in built.rock_cells.items():
        rcells.append(struct.pack("<3I", c, len(rtags), len(v)))
        rtags += v
    joins = b"".join(struct.pack("<2H7HH", j.rock_node, len(j.before), *(list(j.before) + [0xFFFF] * (7 - len(j.before))),
                                 j.added) for j in built.joins)
    head = struct.pack("<4sI4I4I3f3I4I4I", b"FTRN", 2, rock.profiles, rock.nodes, rock.segments, rock.roads,
                       len(net.profiles), len(net.nodes), len(net.segments), len(net.roads), rock.grid_min[0],
                       rock.grid_min[1], rock.edge, rock.rows, rock.cols, built.pad_cols, len(cells), len(tags),
                       len(ev_recs), len(built.parking), len(built.parking), len(built.joins), len(rcells),
                       len(built.link_segments))
    assert len(head) == 0x60
    body = (e["RNpf"] + e["RNnd"] + _pad4(e["RNsg"]) + e["RNrd"] + _pad4(bytes(built.kmh)) + b"".join(cells) +
            struct.pack("<%dI" % len(tags), *tags) + b"".join(ev_recs) + struct.pack("<%dI" % len(marks), *marks) +
            _pad4(bytes(built.parking)) + joins + b"".join(rcells) + struct.pack("<%dI" % len(rtags), *rtags) +
            struct.pack("<%dI" % len(built.link_segments), *built.link_segments))
    data = head + body
    with open(path, "wb") as f:
        f.write(data)
    return data


def read_file(data):
    h = struct.unpack_from("<4sI4I4I3f3I4I4I", data, 0)
    f = {"magic": h[0], "version": h[1], "rock_profiles": h[2], "rock_nodes": h[3], "rock_segments": h[4],
         "rock_roads": h[5], "grid": h[10:16], "spots": h[20]}
    npf, nnd, nsg, nrd = h[6:10]
    ncell, ntag, nev, npark = h[16:20]
    o = 0x60
    items = {"RNpf": data[o:o + 64 * npf]}
    o += 64 * npf
    items["RNnd"] = data[o:o + 32 * nnd]
    o += 32 * nnd
    items["RNsg"] = data[o:o + 22 * nsg]
    o += 22 * nsg + ((-22 * nsg) % 4)
    items["RNrd"] = data[o:o + 8 * nrd]
    o += 8 * nrd
    items["RNhd"] = struct.pack("<6H2s", npf, nnd, nsg, 0, nrd, 0, b"\xaa\xaa")
    f["net"] = roadnet.decode(items)
    f["kmh"] = list(data[o:o + nsg])
    o += nsg + ((-nsg) % 4)
    recs = [struct.unpack_from("<3I", data, o + 12 * i) for i in range(ncell)]
    o += 12 * ncell
    tags = struct.unpack_from("<%dI" % ntag, data, o)
    o += 4 * ntag
    f["cells"] = {c: list(tags[a:a + n]) for c, a, n in recs}
    evs = [struct.unpack_from("<16sII", data, o + 24 * i) for i in range(nev)]
    o += 24 * nev
    nmarks = sum(n for _i, _a, n in evs)
    marks = struct.unpack_from("<%dI" % nmarks, data, o)
    o += 4 * nmarks
    f["events"] = {}
    for eid, a, n in evs:
        m = {}
        for v in marks[a:a + n]:
            m[v & 0xFFFF] = "forward" if v & 0x10000 else "exit" if v & 0x20000 else "backward"
        f["events"][eid.rstrip(b"\0").decode("ascii")] = m
    f["parking"] = list(data[o:o + npark])
    o += npark + ((-npark) % 4)
    njoin, nrcell, nlink = h[21:24] if h[1] >= 2 else (0, 0, 0)
    f["joins"] = []
    for i in range(njoin):
        v = struct.unpack_from("<2H7HH", data, o + 20 * i)
        f["joins"].append(Join(v[0], list(v[2:2 + v[1]]), v[9]))
    o += 20 * njoin
    recs = [struct.unpack_from("<3I", data, o + 12 * i) for i in range(nrcell)]
    o += 12 * nrcell
    ntags = sum(n for _c, _a, n in recs)
    tags = struct.unpack_from("<%dI" % ntags, data, o)
    o += 4 * ntags
    f["rock_cells"] = {c: list(tags[a:a + n]) for c, a, n in recs}
    f["link"] = list(struct.unpack_from("<%dI" % nlink, data, o))
    o += 4 * nlink
    if o != len(data):
        raise ValueError("FTRN: %d bytes, %d read" % (len(data), o))
    return f


# ---------------------------------------------------------------- the real data

def mouth_inverted(s, m):
    """Whether a decision segment arriving at mouth node m (travelling out of the junction onto m's road) reads its
    profile inverted there, from one of m's own decision segments `s`: its end flag when it ends at m (the same way
    of travel), the negation of its start flag when it starts at m (the review, 2026-11-06)."""
    if s.nodes[1] == m:
        return bool(s.flags & roadnet.END_INVERTED)
    return not s.flags & roadnet.START_INVERTED


def rockport_mouths(indices, path=L2RA):
    """RockMouth records of Rockport's junction mouths `indices` from the game's network (read only)."""
    from world import bun, scenery
    for c, pos in scenery.with_positions(bun.read_file(path), 0):
        if c.id == 0x3B800:
            net = roadnet.read_rngp(c.data, pos)[0]
            break
    else:
        raise ValueError("no road network in %s" % path)
    out = []
    for m in indices:
        n = net.nodes[m]
        here = (n.pos[2], -n.pos[0], n.pos[1])
        road = [k for k in n.segments if not net.segments[k].flags & roadnet.DECISION]
        dec = [k for k in n.segments if net.segments[k].flags & roadnet.DECISION]
        if len(road) != 1 or not dec:
            raise ValueError("Rockport node %d is not a junction mouth (%d road segments, %d turns)" % (
                m, len(road), len(dec)))
        other = net.nodes[[k for k in net.segments[road[0]].nodes if k != m][0]]
        d = _unit((other.pos[2] - here[0], -other.pos[0] - here[1]))
        inverted = mouth_inverted(net.segments[dec[0]], m)
        out.append(RockMouth(m, here, d, inverted, list(n.segments)))
    return out


def link_from_connector():
    """The Link of tools/citymap/connector.py (the built city's edge box and heights, Rockport's mouths)."""
    from tools.citymap import connector
    info = connector.city_info()
    p = connector.path(info)
    road = connector.network_road(p, info, BOX_INSET)
    return Link(points=road["points"], width_m=road["width_m"], lanes=road["lanes"], kind=road["kind"],
                junction=connector.JUNCTION, mouths=rockport_mouths(connector.ROCK_MOUTHS),
                carriageways=road["carriageways"])


def rockport_from_game(path=L2RA):
    from world import bun, collision, scenery
    for c, pos in scenery.with_positions(bun.read_file(path), 0):
        if c.id == 0x3B800:
            net, _region, _off = roadnet.read_rngp(c.data, pos)
            g = collision.read_world_grid(c.data, pos)
            h = net.header
            return Rockport(h.profiles, h.nodes, h.segments, h.roads, (g.min[0], g.min[2]), g.edge, g.rows, g.cols)
    raise ValueError("no road network in %s" % path)


def city_heights(city=CITY, city_json=CITY_JSON):
    """heights(xs, ys, levels) over the built city's collision (level 1: the highest face, else the lowest)."""
    from tools.citymap import events as ev_mod, fastheight
    _data, packs = ev_mod._city_packs(city)
    fh = fastheight.HeightModel(packs)
    with open(city_json) as f:
        terr = json.load(f)["terrain"]

    def heights(xs, ys, levels):
        out = []
        for x, y, lv, cs in zip(xs, ys, levels, fh.candidates([-y for y in ys], list(xs))):
            hs = [c[2] for c in cs]
            if not hs:
                ax, ay = terr["anchor"]
                out.append(100.0 + terr["dz_dx"] * (x - ax) + terr["dz_dy"] * (y - ay))
            else:
                out.append(max(hs) if lv == 1 else min(hs))
        return out
    return heights


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def preview(built, path=PREVIEW, scale=0.25):
    from PIL import Image, ImageDraw
    net = built.net
    xs = [n.pos[2] for n in net.nodes]
    ys = [-n.pos[0] for n in net.nodes]
    x0, y0, x1, y1 = min(xs) - 40, min(ys) - 40, max(xs) + 40, max(ys) + 40
    W, H = int((x1 - x0) * scale), int((y1 - y0) * scale)
    img = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(img)
    colour = {80: (255, 80, 60), 70: (255, 140, 40), 60: (255, 200, 40), 55: (230, 230, 60), 45: (150, 220, 90),
              40: (90, 200, 200), 35: (120, 150, 255), 20: (110, 110, 110)}

    def px(p):
        return ((p[2] - x0) * scale, (y1 + p[0]) * scale)
    for i, s in enumerate(net.segments):
        a = net.nodes[s.nodes[0] - built.rock.nodes].pos
        b = net.nodes[s.nodes[1] - built.rock.nodes].pos
        c0 = tuple(a[k] + v for k, v in enumerate(s.start_control()))
        c1 = tuple(b[k] + v for k, v in enumerate(s.end_control()))
        pts = [px(_bezier(a, c0, c1, b, t / 8.0)) for t in range(9)]
        dec = s.flags & roadnet.DECISION
        col = (200, 200, 200) if dec else colour.get(built.kmh[i], (255, 255, 255))
        d.line(pts, fill=col, width=1 if dec else 2)
    for n in net.nodes:
        x, y = px(n.pos)
        d.point((x, y), fill=(255, 255, 255))
    d.text((10, 10), "F-Town road network: %d nodes, %d segments, %.0f km; colour = posted km/h (red 80 .. blue 35, "
                     "grey 20 / junction turns)" % (len(net.nodes), len(net.segments), built.km), fill=(255, 255, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def main():
    model = roadmodel.RoadModel.load(ROADS)
    with open(CITY_JSON) as f:
        bx = json.load(f)["edge_box"]
    box = (bx[0] + BOX_INSET, bx[1] + BOX_INSET, bx[2] - BOX_INSET, bx[3] - BOX_INSET)
    rock = rockport_from_game()
    with open(EVENTS) as f:
        events = [{"id": e["id"], "keys": e["keys"]} for e in json.load(f)["events"] if e.get("keys")]
    with open(SPOTS) as f:
        spots = json.load(f)["spots"]
    link = link_from_connector() if "--no-link" not in sys.argv else None
    built = build(model, city_heights(), box, rock, events, spots, link=link)
    data = write_file(built, OUT_BIN)
    preview(built)
    net = built.net
    dec = sum(1 for s in net.segments if s.flags & roadnet.DECISION)
    per_kind = collections.Counter()
    for k, e_len in zip(built.road_kind, (r.nlength * 4000.0 / 65535.0 for r in net.roads)):
        per_kind[k] += e_len / 1000.0
    info = {
        "note": "F-Town's road network for the game's AI (tools/citymap/roadnet_build.py), derived from OpenStreetMap "
                "data (c) OpenStreetMap contributors (ODbL); the file itself is git-ignored",
        "file": os.path.basename(OUT_BIN), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "counts": {"profiles": len(net.profiles), "nodes": len(net.nodes), "segments": len(net.segments),
                   "decision_segments": dec, "road_segments": len(net.segments) - dec, "roads": len(net.roads),
                   "junctions": built.stats["junctions"], "cells": len(built.cells),
                   "cell_tags": sum(len(v) for v in built.cells.values()),
                   "max_tags_in_a_cell": max(len(v) for v in built.cells.values()),
                   "one_way_segments": sum(1 for s in net.segments if s.flags & roadnet.ONE_WAY),
                   "no_traffic_segments": sum(1 for s in net.segments if s.flags & roadnet.NO_TRAFFIC),
                   "curved_segments": sum(1 for s in net.segments if s.flags & roadnet.CURVED),
                   "dead_end_closed": built.stats["dead_end_closed"]},
        "km": round(built.km, 1), "km_by_kind": {k: round(v, 1) for k, v in sorted(per_kind.items())},
        "kmh_by_kind": KMH, "max_curve_error_m": round(built.max_curve_error, 3),
        "rockport": {"profiles": rock.profiles, "nodes": rock.nodes, "segments": rock.segments, "roads": rock.roads,
                     "grid_min": list(rock.grid_min), "edge": rock.edge, "rows": rock.rows, "cols": rock.cols},
        "grid_pad_cols": built.pad_cols, "grid_min_x_widened": rock.grid_min[0] - built.pad_cols * rock.edge,
        "events": {k: {"route": sum(1 for v in m.values() if v != "exit"),
                       "exits": sum(1 for v in m.values() if v == "exit")} for k, m in sorted(built.events.items())},
        "parking": {"spots": len(built.parking), "kept": sum(built.parking)},
        "nodes_z": [round(min(n.pos[1] for n in net.nodes), 2), round(max(n.pos[1] for n in net.nodes), 2)],
        "built_from": {"roads": _sha(ROADS), "city": _sha(CITY), "events": _sha(EVENTS), "traffic": _sha(SPOTS)},
        "box": [round(v, 2) for v in box],
        "link": {"joins": [{"rock_node": j.rock_node, "before": j.before, "added": j.added} for j in built.joins],
                 "rock_cells": len(built.rock_cells), "rock_cell_tags": sum(len(v) for v in built.rock_cells.values()),
                 "segments": len(built.link_segments)},
    }
    with open(OUT_JSON, "w", encoding="ascii") as f:
        json.dump(info, f, indent=1)
        f.write("\n")
    print(json.dumps({k: info[k] for k in ("bytes", "counts", "km", "grid_pad_cols", "events", "parking",
                                            "max_curve_error_m", "nodes_z")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
