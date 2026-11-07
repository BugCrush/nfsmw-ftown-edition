"""F-Town's events (docs/superpowers/plans/2026-11-04-ftown-events.md; notes docs/ftown-race-notes.md "Events"): the
routes, starts and gates of every event FTownLoader offers after Free Roam, made from the road model and checked
drivable on the built city, written to the committed ftown/ftown-events.json.

    .tools/cityenv/Scripts/python tools/citymap/events.py        (writes ftown/ftown-events.json, prints a summary)

The events, in the menu's order (render metres: x east, y north; headings in degrees counter-clockwise from +x):
- **Time Attack** (route 1, unchanged): DND-KMP exit to Mathura Road (route_main.json), the city's route-start spawn,
  a checkpoint every 500 m and the finish 30 m before the end (route_gates.py).
- **Drag (DND-KMP Expressway)**: the expressway's northbound carriageway inside the area, all at ground level (its two
  OSM bridges cross no road: roadmodel keeps them on the ground) and straight (within 1 degree), 1,078 m of it: a
  standing start DRAG_START_IN in from its south end, the finish a quarter mile (402.336 m) on, the rest run-off.
- **Speed Trap (Mathura Road)**: Mathura Road's northbound carriageway from the area's south edge over both flyovers
  (Neelam Chowk's and the northern one): cameras at the top of the first flyover, twice on the long ground stretch and
  at the top of the second flyover, the finish SPEEDTRAP_RUNOFF before the end.
- **Sector Sprint**: Sector 15's internal roads north, across Lal Bahadur Shastri Marg, Sector 16's roads past the HUDA
  park (Dr. Aggarwal's) and behind Sector 16 Market; never along route 1; a checkpoint every 400 m, the finish 30 m
  before the end.

Each event's route is its list of road-model nodes (`keys`, OSM coordinates) and their points: race_barriers.py seals
it (its own barrier file) and traffic_spots.py keeps its spots clear while it runs.
"""
import heapq
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild"), os.path.join(TOOLS, "x360")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.citymap import geo, race_barriers, roadmodel, route_gates  # noqa: E402

AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
ROADS = os.path.join(AREA, "ftown-roads.json")
CITY_JSON = os.path.join(REPO, "ftown", "ftown-city.json")
CITY = os.path.join(REPO, "ftown", "ftown-city.bun")
OUT = os.path.join(REPO, "ftown", "ftown-events.json")
NOTE = "F-Town events, routes derived from OpenStreetMap data (c) OpenStreetMap contributors (ODbL)"

QUARTER_MILE = 402.336
DRAG_START_IN = 60.0  # the drag's start this far from the carriageway's first node inside the area
SPEEDTRAP_START_IN = 40.0
SPEEDTRAP_RUNOFF = 350.0
SPRINT_START_IN = 15.0
SPRINT_SPACING = 400.0
EDGE_MARGIN = 15.0  # a route's nodes stay this far inside the city's closed edge box
START_Z = 1.0  # a start 1 m above the built ground (as the spawns; terrain.ground_z: the elevation)
SPRINT_KINDS = {"residential", "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link"}
# the sprint's waypoints (snapped to the nearest node of a road it may use): Sector 15's long east-west road west, its
# road north to Lal Bahadur Shastri Marg, across into Sector 16 and north to the HUDA park's south-east corner (the
# park is not in OSM: the open block west of road 172383263, Dr. Aggarwal's "beside Sector 16 HUDA Park"), east, north
# along the market's east side, west along its north side to the finish short of route 1's road
# (all in the frame before the connection's move: geo.moved puts them where the city is now)
SPRINT_WAYPOINTS = [geo.moved(*p) for p in [(2740.0, 10700.0), (2360.0, 10722.0), (2312.0, 11440.0), (2180.0, 11650.0),
                                            (2136.0, 12218.0), (2226.0, 12223.0), (2195.0, 12645.0), (2068.0, 12628.0)]]
HUDA_PARK_CORNER = geo.moved(2095.0, 12215.0)  # the park block's south-east corner (a road-model node)
# the menu's icons: the game's own mode-select icons (UIQRModeSelect::Setup 0x7AA900: Tollbooth, Drag, Speedtrap, Sprint)
ICONS = {"timeattack": "0x1A091045", "drag": "0xAAAB31E9", "speedtrap": "0x66C9A7B6", "sprint": "0x2521E5EB"}


# ---------------------------------------------------------------- geometry along a route

def along(pts):
    return route_gates.along(pts)


def point_at(pts, s_at):
    """(x, y, heading degrees) at s_at metres along pts."""
    return route_gates.point_at(pts, s_at)


def _gate(kind, pts, s):
    x, y, h = point_at(pts, s)
    return {"type": kind, "s": round(s, 2), "x": round(x, 2), "y": round(y, 2), "heading": round(h, 1)}


def _start(pts, s):
    x, y, h = point_at(pts, s)
    from tools.citymap import terrain
    x, y = round(x, 2), round(y, 2)
    return [x, y, round(terrain.ground_z(x, y) + START_Z, 2), round(h, 1)]


# ---------------------------------------------------------------- the road graph

def _graph(model, use):
    """{key: [(key2, metres, road)]} over the roads `use(road)` accepts; one-way roads one way only."""
    g = {}
    for r in model.roads:
        if not use(r):
            continue
        for (ka, kb), (a, b) in zip(zip(r.keys, r.keys[1:]), zip(r.points, r.points[1:])):
            d = math.dist(a, b)
            g.setdefault(ka, []).append((kb, d, r))
            if not r.oneway:
                g.setdefault(kb, []).append((ka, d, r))
            else:
                g.setdefault(kb, [])
    return g


def _snap(model, g, p):
    best = None
    for k in g:
        n = model.nodes[k]
        d = math.dist((n.x, n.y), p)
        if best is None or d < best[0]:
            best = (d, k)
    return best[1]


def _shortest(g, src, dst, banned=frozenset()):
    pq, done, best, prev = [(0.0, src)], set(), {src: 0.0}, {src: None}
    while pq:
        c, k = heapq.heappop(pq)
        if k in done:
            continue
        done.add(k)
        if k == dst:
            out = [k]
            while prev[out[-1]] is not None:
                out.append(prev[out[-1]])
            return out[::-1]
        for k2, d, _r in g.get(k, ()):
            if k2 not in done and (k, k2) not in banned and c + d < best.get(k2, 1e18):
                best[k2] = c + d
                prev[k2] = k
                heapq.heappush(pq, (c + d, k2))
    raise ValueError("no path from %s to %s" % (src, dst))


def path_through(model, use, waypoints, banned=frozenset()):
    """The node keys of the shortest drivable path through every waypoint in turn."""
    g = _graph(model, use)
    snapped = [_snap(model, g, p) for p in waypoints]
    keys = [snapped[0]]
    for a, b in zip(snapped, snapped[1:]):
        keys += _shortest(g, a, b, banned)[1:]
    return keys


def _points(model, keys):
    return [(model.nodes[k].x, model.nodes[k].y) for k in keys]


def _inside(model, keys, box):
    out = []
    for k in keys:
        n = model.nodes[k]
        if box[0] + EDGE_MARGIN < n.x < box[2] - EDGE_MARGIN and box[1] + EDGE_MARGIN < n.y < box[3] - EDGE_MARGIN:
            out.append(k)
        elif out:
            break
    return out


def segment_roads(model, keys):
    """The road of each segment of the route (by its two node keys, either way)."""
    seg = race_barriers.route_segments(model, keys)
    return [seg.get((a, b)) for a, b in zip(keys, keys[1:])]


def road_interval(model, ev, road_ids):
    """(s0, s1): where along the event's route the segments of these roads lie."""
    s = along(ev["route"])
    got = [(s[i], s[i + 1]) for i, r in enumerate(segment_roads(model, ev["keys"])) if r is not None and r.id in road_ids]
    return min(a for a, _ in got), max(b for _, b in got)


def on_raised(model, ev, s_at):
    """Is the route at s_at on a raised road (a flyover deck, level 1)?"""
    s = along(ev["route"])
    for i, r in enumerate(segment_roads(model, ev["keys"])):
        if s[i] <= s_at <= s[i + 1]:
            return r is not None and r.level == 1
    return False


# ---------------------------------------------------------------- the events

def _event(eid, name, title, kind, best, barriers, keys, pts, start_s, start, gates):
    return {"id": eid, "name": name, "title": title, "kind": kind, "icon": ICONS[kind], "best": best,
            "barriers": barriers, "start_s": round(start_s, 2), "start": start, "gates": gates,
            "length_m": round(along(pts)[-1], 2), "finish_s": gates[-1]["s"],
            "route": [[round(x, 2), round(y, 2)] for x, y in pts], "keys": list(keys)}


def time_attack():
    keys, pts = race_barriers.route_points()
    with open(CITY_JSON) as f:
        s0 = json.load(f)["spawns"][0]
    gates = []
    g = route_gates.gates(pts)
    for k, gate in enumerate(g):
        gates.append({"type": "finish" if k == len(g) - 1 else "checkpoint", "s": round(gate["s"], 2),
                      "x": round(gate["x"], 2), "y": round(gate["y"], 2), "heading": round(gate["heading"], 1)})
    start = [s0["x"], s0["y"], s0["z"], s0["heading"]]
    return _event("timeattack", "Time Attack", "TIME ATTACK", "timeattack", "Route1", "ftown-barriers.bun", keys, pts,
                  0.0, start, gates)


def _box():
    with open(CITY_JSON) as f:
        return json.load(f)["edge_box"]


def drag(model):
    use = lambda r: r.kind == "motorway"  # noqa: E731
    keys = path_through(model, use, [geo.moved(3333.0, 12442.0), geo.moved(3072.0, 13487.0)])
    keys = _inside(model, keys, _box())
    pts = _points(model, keys)
    start_s = DRAG_START_IN
    gates = [_gate("finish", pts, start_s + QUARTER_MILE)]
    return _event("drag", "Drag (DND-KMP Expressway)", "DRAG", "drag", "Drag", "ftown-barriers-drag.bun", keys, pts,
                  start_s, _start(pts, start_s), gates)


def speed_trap(model):
    use = lambda r: bool(r.name) and r.name.startswith("Mathura Road")  # noqa: E731
    keys = path_through(model, use, [geo.moved(1493.0, 9275.0), geo.moved(1169.0, 13639.0)])
    keys = _inside(model, [k for k in keys if model.nodes[k].y > _box()[1] + EDGE_MARGIN], _box())
    pts = _points(model, keys)
    ev = {"route": pts, "keys": keys}
    roads = segment_roads(model, keys)
    decks = []  # the raised runs, in route order: (s0, s1)
    s = along(pts)
    for i, r in enumerate(roads):
        if r is not None and r.level == 1:
            if decks and abs(decks[-1][1] - s[i]) < 1e-6:
                decks[-1] = (decks[-1][0], s[i + 1])
            else:
                decks.append((s[i], s[i + 1]))
    runs = []  # the ground runs, merged
    for i, r in enumerate(roads):
        if r is not None and r.level == 0:
            if runs and abs(runs[-1][1] - s[i]) < 1e-6:
                runs[-1] = (runs[-1][0], s[i + 1])
            else:
                runs.append((s[i], s[i + 1]))
    ground = max(runs, key=lambda ab: ab[1] - ab[0])
    cams = [(decks[0][0] + decks[0][1]) / 2, ground[0] + 0.3 * (ground[1] - ground[0]),
            ground[0] + 0.75 * (ground[1] - ground[0]), decks[1][0] + 0.35 * (decks[1][1] - decks[1][0])]
    finish = s[-1] - SPEEDTRAP_RUNOFF
    gates = [_gate("camera", pts, c) for c in cams] + [_gate("finish", pts, finish)]
    del ev
    return _event("speedtrap", "Speed Trap (Mathura Road)", "SPEED TRAP", "speedtrap", "SpeedTrap",
                  "ftown-barriers-speedtrap.bun", keys, pts, SPEEDTRAP_START_IN, _start(pts, SPEEDTRAP_START_IN), gates)


def sprint(model, ta):
    banned = set(zip(ta["keys"], ta["keys"][1:])) | set(zip(ta["keys"][1:], ta["keys"]))
    use = lambda r: r.kind in SPRINT_KINDS and r.level == 0 and not r.bridge  # noqa: E731
    keys = path_through(model, use, SPRINT_WAYPOINTS, frozenset(banned))
    pts = _points(model, keys)
    length = along(pts)[-1]
    gates = []
    k = 1
    while SPRINT_START_IN + k * SPRINT_SPACING < length - route_gates.FINISH_BEFORE_END - 100.0:
        gates.append(_gate("checkpoint", pts, SPRINT_START_IN + k * SPRINT_SPACING))
        k += 1
    gates.append(_gate("finish", pts, length - route_gates.FINISH_BEFORE_END))
    return _event("sprint", "Sector Sprint", "SECTOR SPRINT", "sprint", "SectorSprint", "ftown-barriers-sprint.bun",
                  keys, pts, SPRINT_START_IN, _start(pts, SPRINT_START_IN), gates)


def build_all(model=None):
    model = model or roadmodel.RoadModel.load(ROADS)
    ta = time_attack()
    evs = [ta, drag(model), speed_trap(model), sprint(model, ta)]
    for e in evs:  # Run K, item 3: the course line as wide as the road the minimap draws
        e["band"] = course_band(model, e, None if e["id"] == "timeattack" else race_barriers.event_raised(e))
    return evs


BAND_REACH = 40.0  # m each side of a route point the other half is looked for


def course_band(model, ev, raised=None):
    """Run K, item 3 ("the yellow line ... is very thin, make it as thick as the full road"): [[cx, cy, half]] one per
    route point, the road the minimap draws across the route there (tools/citymap/minimap.py: each road WIDE[kind] wide,
    NARROW otherwise, on its centre line): the route road's (the wider of the two segments at the point) and, where the
    route is on one half of a divided road (the halves race_barriers.whole_road matches with the barriers' own `raised`:
    the ring encloses both), the other half's at its offset (the nearest of them running the other way along the route
    within furniture.PAIR_GAP edge to edge, real widths); centre and half width of the whole. On a ramp or deck
    (raised) only the twins of the name family (as whole_road). FTownLoader paints the course line over this band."""
    from shapely.geometry import LineString, Point
    from tools.citymap import furniture, minimap
    keys, pts = ev["keys"], [tuple(p) for p in ev["route"]]
    seg = race_barriers.route_segments(model, keys)
    matched = set()
    race_barriers.whole_road(model, keys, pts, None, matched, raised)
    own_ids = {r.id for r in seg.values()}
    others = [model.road(i) for i in sorted(matched - own_ids)]
    olines = [LineString(r.points) for r in others]
    tw = race_barriers.twins(model)

    def drawn(r):
        return float(minimap.WIDE.get(r.kind, minimap.NARROW))

    out = []
    n = len(pts)
    for i, p in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(n - 1, i + 1)]
        L = math.dist(a, b) or 1.0
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        nrm = (-u[1], u[0])
        roads = [r for r in (seg.get((keys[j], keys[j + 1])) for j in (i - 1, i) if 0 <= j < n - 1) if r is not None]
        w = max([drawn(r) for r in roads] or [float(minimap.NARROW)])
        lo, hi = -w / 2, w / 2
        up = raised is not None and raised(*p)
        cross = LineString([(p[0] - nrm[0] * BAND_REACH, p[1] - nrm[1] * BAND_REACH),
                            (p[0] + nrm[0] * BAND_REACH, p[1] + nrm[1] * BAND_REACH)])
        best = None
        for t, tl in zip(others, olines):
            if up and not any(t.id in {x.id for x in tw.get(r.id, [])} for r in roads):
                continue
            x = tl.intersection(cross)
            for q in ([x] if x.geom_type == "Point" else [g for g in getattr(x, "geoms", []) if g.geom_type == "Point"]):
                st = tl.project(q)
                h1, h0 = tl.interpolate(min(tl.length, st + 1.0)), tl.interpolate(max(0.0, st - 1.0))
                d = (h1.x - h0.x, h1.y - h0.y)
                c = (d[0] * u[0] + d[1] * u[1]) / (math.hypot(*d) or 1.0)
                if c > -0.8:
                    continue
                o = (q.x - p[0]) * nrm[0] + (q.y - p[1]) * nrm[1]
                own_w = max([r.width_m for r in roads] or [8.0])
                if abs(o) - own_w / 2 - t.width_m / 2 > furniture.PAIR_GAP:
                    continue
                if best is None or abs(o) < abs(best[0]):
                    best = (o, drawn(t))
        if best is not None:
            lo, hi = min(lo, best[0] - best[1] / 2), max(hi, best[0] + best[1] / 2)
        m = (lo + hi) / 2
        out.append([round(p[0] + nrm[0] * m, 2), round(p[1] + nrm[1] * m, 2), round((hi - lo) / 2, 2)])
    return out


# ---------------------------------------------------------------- the file

def write(evs, path=OUT):
    """JSON, one gate, route point or key a line (FTownLoader reads it with its own small JSON reader)."""
    lines = ["{", ' "note": %s,' % json.dumps(NOTE),
             ' "format": "render metres (x east, y north, z up); headings in degrees counter-clockwise from +x; s: metres '
             'along the route",', ' "events": [']
    for n, e in enumerate(evs):
        lines.append("  {")
        for k in ("id", "name", "title", "kind", "icon", "best", "barriers"):
            lines.append('   "%s": %s,' % (k, json.dumps(e[k])))
        lines.append('   "start": [%.2f, %.2f, %.2f, %.1f],' % tuple(e["start"]))
        lines.append('   "start_s": %.2f, "length_m": %.2f, "finish_s": %.2f,' % (e["start_s"], e["length_m"],
                                                                                 e["finish_s"]))
        lines.append('   "gates": [')
        for i, g in enumerate(e["gates"]):
            lines.append('    {"type": "%s", "s": %.2f, "x": %.2f, "y": %.2f, "heading": %.1f}%s' % (
                g["type"], g["s"], g["x"], g["y"], g["heading"], "," if i + 1 < len(e["gates"]) else ""))
        lines.append("   ],")
        lines.append('   "route": [')
        for i, (x, y) in enumerate(e["route"]):
            lines.append("    [%.2f, %.2f]%s" % (x, y, "," if i + 1 < len(e["route"]) else ""))
        lines.append("   ],")
        if e.get("band"):  # Run K, item 3: [centre x, y, half width] of the drawn road at each route point
            lines.append('   "band": [')
            for i, (x, y, h) in enumerate(e["band"]):
                lines.append("    [%.2f, %.2f, %.2f]%s" % (x, y, h, "," if i + 1 < len(e["band"]) else ""))
            lines.append("   ],")
        lines.append('   "keys": [')
        for i, k in enumerate(e["keys"]):
            lines.append('    "%s"%s' % (k, "," if i + 1 < len(e["keys"]) else ""))
        lines.append("   ]")
        lines.append("  }%s" % ("," if n + 1 < len(evs) else ""))
    lines += [" ]", "}", ""]
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines))


def read(path=OUT):
    with open(path, encoding="ascii") as f:
        return json.load(f)["events"]


# ---------------------------------------------------------------- drivable end to end

def _city_packs(path):
    from chunks import read_chunks
    from world import collision_write, scenery
    with open(path, "rb") as f:
        data = f.read()
    packs = [collision_write.read_pack(c.data, p) for c, p in scenery.with_positions(read_chunks(data), 0)
             if c.id == collision_write.COLLISION_PACK]
    return data, packs


_CACHE = {}


def _city(city_path=CITY):
    from tools.citymap import fastheight
    if city_path not in _CACHE:
        data, packs = _city_packs(city_path)
        _CACHE[city_path] = (fastheight.HeightModel(packs), race_barriers.read_walls(data))
    return _CACHE[city_path]


def _follow(ev, city_path, step, s0):
    """(S, X, Y, Z, misses): the route every `step` m from s0 to its end and the height a car following it finds at
    each point (of the faces holding the point, the one nearest the last height and less than 1 m above it; NaN
    where none)."""
    import numpy as np
    fh, _walls = _city(city_path)
    pts = [tuple(p) for p in ev["route"]]
    s = along(pts)
    n = int((s[-1] - s0) / step)
    S = s0 + step * np.arange(n + 1)
    X, Y = np.empty(n + 1), np.empty(n + 1)
    k = 0
    for i, si in enumerate(S):
        while k + 2 < len(s) and s[k + 1] < si:
            k += 1
        t = (si - s[k]) / (s[k + 1] - s[k])
        X[i] = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * t
        Y[i] = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * t
    z, last, misses = [], ev["start"][2] - 1.0, 0
    for cs in fh.candidates(-Y, X):
        best = None
        for c in cs:
            h = c[2]
            if h < last + 1.0 and (best is None or abs(h - last) < abs(best - last)):
                best = h
        if best is None:
            misses += 1
            z.append(float("nan"))
            continue
        z.append(best)
        last = best
    return S, X, Y, np.array(z), misses


def follow(ev, city_path=CITY, step=1.0):
    """(S, Z): the route's height every `step` m from its first point, as a car following it finds it."""
    S, _X, _Y, Z, _m = _follow(ev, city_path, step, 0.0)
    return S, Z


def drivable(ev, city_path=CITY, step=0.5):
    """The route from its start to its end every `step` m as a car follows it: at each point the face (of every face
    holding the point) nearest below 1 m above the last height, then confirmed by the game's height query from 1 m
    above it (fastheight.heights) and by the wheels' query from 0.5 m above (fastheight.wheel_heights, within 2 cm);
    the largest step between neighbours; the city's barriers crossing the centre line between the car's height + 0.2 m
    and + 1.5 m."""
    import numpy as np
    from shapely.geometry import LineString
    S, X, Y, Z, no_face = _follow(ev, city_path, step, ev["start_s"])
    fh, walls = _city(city_path)
    game = fh.heights(-Y, X, Z + 1.0)
    wheels = fh.wheel_heights(-Y, X, Z + 0.5)
    ok = ~np.isnan(Z)
    no_face += int((ok & (np.isnan(game) | (np.abs(game - Z) > 0.02))).sum())
    wheels_off = int((ok & (np.isnan(wheels) | (np.abs(wheels - Z) > 0.02))).sum())
    steps = np.abs(np.diff(Z))
    max_step = float(np.nanmax(steps)) if len(steps) else 0.0
    line = LineString([(x, y) for x, y in zip(X, Y)])
    across = 0
    for a, b, lo, hi in walls:
        seg = LineString([a, b])
        if not line.intersects(seg):
            continue
        x = line.intersection(seg)
        p = x if x.geom_type == "Point" else list(getattr(x, "geoms", [x]))[0]
        i = int(round(line.project(p) / step))
        zc = Z[min(max(i, 0), len(Z) - 1)]
        if min(lo, hi) < zc + 1.5 and max(lo, hi) > zc + 0.2:
            across += 1
    return {"points": len(X), "no_face": no_face, "wheels_off": wheels_off, "max_step": max_step,
            "barriers_across": across, "z_min": float(np.nanmin(Z)), "z_max": float(np.nanmax(Z))}


def main():
    model = roadmodel.RoadModel.load(ROADS)
    evs = build_all(model)
    write(evs)
    for e in evs:
        d = drivable(e)
        print("%-10s %7.1f m, start s %.0f, %d gates (%s), finish s %.1f; drivable: %s" % (
            e["id"], e["length_m"], e["start_s"], len(e["gates"]), ",".join(g["type"][0] for g in e["gates"]),
            e["finish_s"], d))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
