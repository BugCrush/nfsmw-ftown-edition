"""The Delhi Metro Violet Line over F-Town: the elevated viaduct along Mathura Road (OSM railway=subway, the two
"Delhi Metro Violet Line" tracks; the depot's yard tracks are left out) and its stations Neelam Chowk Ajronda, Bata
Chowk and Old Faridabad on their OSM outlines (render metres, heights above the ground).

Calls (docs/ftown-notes.md "Landmarks and street furniture"):
- the deck: a box girder DECK_W wide centred on the middle of the two tracks, GIRDER deep, parapets PARAPET above it;
  its underside UNDERSIDE above the ground, raised to CLEARANCE above any flyover deck within reach (none in this area:
  the line keeps 16 m or more from the decks), changing by at most GRADE;
- piers every PIER_STEP (25-35 m in Delhi) where the spot is off every carriageway (ground and raised) by LANE_CLEAR;
  a pier that would land in a lane moves along the line up to PIER_SHIFT; where none fits, a portal frame (two legs
  either side of the road, a cross-head under the deck); piers and legs are barriers, the deck is drawn only (no car
  reaches it, so no collision faces above a road);
- a station: its OSM outline as a box from CONCOURSE (the concourse's underside) to PLATFORM_TOP, the deck through it at
  the platform level, an arched roof over its long axis, columns every COLUMN_STEP in two rows (off the lanes), stairs at
  the OSM entrances (Old Faridabad's Gate 1 and Gate 2); its fronts from the photos (the registry's faces), the rest in
  its finish (Neelam Chowk Ajronda beige, Bata Chowk orange and blue, Old Faridabad brick and white).
"""
import json
import math
import os
import sys
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import parts as P  # noqa: E402
from tools.citymap import station_letters, surfaces  # noqa: E402

LINE_NAME = "Delhi Metro Violet Line"
DECK_W = 10.0
GIRDER = 2.0
PARAPET = 1.1
UNDERSIDE = 10.5
CLEARANCE = 5.0
GRADE = 0.03
SAMPLE = 5.0
PIER_STEP = 30.0
LAMP_STEP = 30.0  # the evening's deck lights, both sides (furniture_models.metro_lamp)
PIER_SHIFT = 10.0
PIER_ALONG, PIER_ACROSS = 1.0, 1.2  # half sizes: a 2.0 x 2.4 m pier
CAP_ACROSS = 4.0
LEG = 0.6
SPAN_MAX = 40.0
LANE_CLEAR = 0.5
CONCOURSE = 6.0
PLATFORM = UNDERSIDE + GIRDER  # 12.5: the platform floor is the deck's top
PLATFORM_TOP = PLATFORM + 6.0
ROOF_RISE = 3.0
COLUMN_STEP = 15.0
COLUMN = 0.6
STAIR_W, STAIR_L = 3.0, 14.0
CONCRETE_TILE = (4.0, 4.0)
FINISH_TILE = (4.0, 3.2)
DECK_GREY = 64.0


def tracks(details, proj, outer):
    """The two mainline tracks (LineStrings, render) inside `outer`, the longest piece of each."""
    out = []
    for e in details["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("railway") == "subway" and t.get("name") == LINE_NAME and "service" not in t:
            g = LineString([proj.to_render(p["lat"], p["lon"]) for p in e["geometry"]]).intersection(outer)
            if g.geom_type == "MultiLineString":
                g = max(g.geoms, key=lambda x: x.length)
            if not g.is_empty:
                out.append(g)
    out.sort(key=lambda g: -g.length)
    if len(out) < 2:
        raise ValueError("expected the two Violet Line tracks, found %d" % len(out))
    return out[0], out[1]


def centre_line(a, b, step=2.0):
    pts = []
    s = 0.0
    while s <= a.length:
        p = a.interpolate(s)
        q = b.interpolate(b.project(p))
        pts.append(((p.x + q.x) / 2, (p.y + q.y) / 2))
        s += step
    return LineString(pts).simplify(0.05)


@dataclass
class Viaduct:
    centre: LineString
    s: list
    pts: list
    tangents: list
    under: list
    parts: P.PartSet
    pier_boxes: list = field(default_factory=list)
    pier_s: list = field(default_factory=list)
    portal_legs: int = 0
    skipped: list = field(default_factory=list)
    barriers: list = field(default_factory=list)

    def underside_at(self, s):
        k = min(len(self.s) - 1, max(0, int(s // SAMPLE)))
        return self.under[k]

    def underside_samples(self, step=2.0):
        for k, (c, t) in enumerate(zip(self.pts, self.tangents)):
            n = (-t[1], t[0])
            o = -DECK_W / 2
            while o <= DECK_W / 2 + 1e-9:
                yield (c[0] + n[0] * o, c[1] + n[1] * o), self.under[k]
                o += step

    def footprint(self, grow=0.0):
        return self.centre.buffer(DECK_W / 2 + grow, cap_style="flat")


def _tangent(line, s):
    a = line.interpolate(max(0.0, s - 1.0))
    b = line.interpolate(min(line.length, s + 1.0))
    dx, dy = b.x - a.x, b.y - a.y
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def _undersides(pts, tangents, L):
    need = []
    E = L.elevated
    for c, t in zip(pts, tangents):
        n = (-t[1], t[0])
        z = UNDERSIDE
        probe = LineString([(c[0] - n[0] * (DECK_W / 2 + 2), c[1] - n[1] * (DECK_W / 2 + 2)),
                            (c[0] + n[0] * (DECK_W / 2 + 2), c[1] + n[1] * (DECK_W / 2 + 2))])
        if probe.intersects(E):
            for k in range(0, 15):
                pp = probe.interpolate(k / 14.0, normalized=True)
                if E.contains(pp):
                    z = max(z, L.z_at(pp.x, pp.y) + CLEARANCE)
        need.append(z)
    out = list(need)
    for k in range(1, len(out)):  # an envelope over the needs: never steeper than GRADE
        out[k] = max(out[k], out[k - 1] - GRADE * SAMPLE)
    for k in range(len(out) - 2, -1, -1):
        out[k] = max(out[k], out[k + 1] - GRADE * SAMPLE)
    return out


def _rect(c, t, half_a, half_b):
    return P.box(c[0], c[1], t[0], t[1], half_a, half_b, 0, 0)


# m a pier's cap (or a portal's leg) keeps off a station's outline (Run J, item 2): 1.5 m put the moved piers just
# outside the ends, hiding up to 90% of their lower band from the road; at 10 m Bata Chowk's north end is clear (1%)
# right of u 0.44 and Neelam Chowk Ajronda's ends as they were (piers that far already)
STATION_CLEAR = 10.0


def viaduct(details, proj, L, outer, lanes=None, stations=()):
    """The deck, piers and portals (module doc). L: levels.Levels; lanes: the carriageways grown by LANE_CLEAR
    (default from L); stations: the stations' outlines (Run J, item 2: a pier stood in Bata Chowk's north end, 6 cm
    out of its drawn face and its cap 30 cm, in front of the lettering; inside a station its own columns carry the
    deck, so no pier or portal within STATION_CLEAR of one; a span beside a station is up to 2 x STATION_CLEAR +
    PIER_STEP longer)."""
    a, b = tracks(details, proj, outer)
    centre = centre_line(a, b)
    n = max(2, int(math.ceil(centre.length / SAMPLE)) + 1)
    s = [min(centre.length, k * SAMPLE) for k in range(n)]
    pts = [centre.interpolate(x).coords[0] for x in s]
    tangents = [_tangent(centre, x) for x in s]
    under = _undersides(pts, tangents, L)
    ps = P.PartSet("metro")
    v = Viaduct(centre, s, pts, tangents, under, ps)
    deck = ps.get("concrete")
    hw = DECK_W / 2
    for k in range(n - 1):
        c0, c1 = pts[k], pts[k + 1]
        t0, t1 = tangents[k], tangents[k + 1]
        n0, n1 = (-t0[1], t0[0]), (-t1[1], t1[0])
        zu0, zu1 = under[k], under[k + 1]
        L0 = (c0[0] - n0[0] * hw, c0[1] - n0[1] * hw)
        R0 = (c0[0] + n0[0] * hw, c0[1] + n0[1] * hw)
        L1 = (c1[0] - n1[0] * hw, c1[1] - n1[1] * hw)
        R1 = (c1[0] + n1[0] * hw, c1[1] + n1[1] * hw)
        u0, u1 = s[k] / CONCRETE_TILE[0], s[k + 1] / CONCRETE_TILE[0]
        mid = ((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2)
        hi = GIRDER + PARAPET
        for p0, p1 in ((L0, L1), (R0, R1)):
            side = ((p0[0] + p1[0]) / 2 - mid[0], (p0[1] + p1[1]) / 2 - mid[1], 0.0)
            # the outer side (girder and parapet), facing away from the line; the parapet's inner face, facing it
            q = [(p0[0], p0[1], zu0), (p1[0], p1[1], zu1), (p1[0], p1[1], zu1 + hi), (p0[0], p0[1], zu0 + hi)]
            quv = [(u0, hi / 4), (u1, hi / 4), (u1, 0.0), (u0, 0.0)]
            tris, uvs = P.quad(q, quv, side)
            deck.add(tris, uvs, [P.lit(t, DECK_GREY) for t in tris])
            q = [(p0[0], p0[1], zu0 + GIRDER), (p1[0], p1[1], zu1 + GIRDER), (p1[0], p1[1], zu1 + hi),
                 (p0[0], p0[1], zu0 + hi)]
            tris, uvs = P.quad(q, [(u0, PARAPET / 4), (u1, PARAPET / 4), (u1, 0.0), (u0, 0.0)],
                               (-side[0], -side[1], 0.0))
            ps.get("concrete", "build", P.DETAIL).add(tris, uvs, [P.lit(t, DECK_GREY * 0.9) for t in tris])
        for z0_, z1_, up, grey in ((zu0, zu1, (0, 0, -1), 50), (zu0 + GIRDER, zu1 + GIRDER, (0, 0, 1), 60)):
            q = [(L0[0], L0[1], z0_), (L1[0], L1[1], z1_), (R1[0], R1[1], z1_), (R0[0], R0[1], z0_)]
            tris, uvs = P.quad(q, [(p[0] / 4, -p[1] / 4) for p in q], up)
            deck.add(tris, uvs, P.colour((grey, grey, grey)))
    lanes = lanes if lanes is not None else shapely.union_all([L.ground_polygon, L.elevated]).buffer(LANE_CLEAR)
    shapely.prepare(lanes)
    keep = shapely.union_all([s.buffer(STATION_CLEAR) for s in stations]) if stations else None
    _piers(v, lanes, keep)
    return v


def deck_lamps(v, avoid=(), step=LAMP_STEP):
    """The deck's lights (the evening): [AnchoredPart] of the ground instance's furniture (near only), one a lamp, a
    lamp on each parapet every `step` m, leaning over the deck; none within 3 m of a polygon of `avoid` (the
    stations). tiles.CityGeometry keeps a lamp only where its tile already draws furniture with room under its next
    1,000 triangles (no tile gains a draw)."""
    from tools.citymap import furniture, furniture_models as FM, housedetail
    out = []
    model = FM.metro_lamp()
    hw = DECK_W / 2 - 0.1
    s = step / 2
    while s < v.centre.length:
        k = min(int(s // SAMPLE), len(v.s) - 2)
        f = (s - v.s[k]) / max(1e-9, v.s[k + 1] - v.s[k])
        zu = v.under[k] + (v.under[k + 1] - v.under[k]) * f
        c = v.centre.interpolate(s)
        t = _tangent(v.centre, s)
        n = (-t[1], t[0])
        for sg in (1, -1):
            x, y = c.x + n[0] * hw * sg, c.y + n[1] * hw * sg
            if any(a.distance(Point(x, y)) < 3.0 for a in avoid):
                continue
            hd = math.atan2(t[1], t[0]) + (math.pi if sg == 1 else 0.0)  # its +y towards the deck's middle
            part = housedetail.AnchoredPart("ground", "furniture", levels=("A",), tag="METROLAMPS", anchor=(x, y))
            furniture._add_model(part, model, x, y, zu + GIRDER + PARAPET, hd)
            out.append(part)
        s += step
    return out


def _free(lanes, ring):
    return not lanes.intersects(Polygon(ring))


def _pier(v, c, t, zu, piers):
    ring = _rect(c, t, PIER_ALONG, PIER_ACROSS)
    P.prism(piers, ring, 0.0, zu - 1.2, *CONCRETE_TILE, grey=DECK_GREY)
    cap = _rect(c, t, PIER_ALONG + 0.2, CAP_ACROSS)
    P.prism(v.parts.get("concrete", "build", P.DETAIL), cap, zu - 1.2, zu, *CONCRETE_TILE, grey=DECK_GREY,
            bottom=True)
    v.pier_boxes.append(ring)
    v.barriers += P.ring_barriers(ring, 0.0, zu - 1.2)


def _piers(v, lanes, keep=None):
    piers = v.parts.get("concrete")

    def off_station(ring):
        return keep is None or not keep.intersects(Polygon(ring))
    line = v.centre
    last = -1e9
    target = PIER_STEP / 2
    while target < line.length - 2.0:
        placed = None
        for d in [0.0] + [x * sg for x in range(1, int(PIER_SHIFT) + 1) for sg in (1, -1)]:
            sv = target + d
            if sv <= last + 10.0 or sv < 1.0 or sv > line.length - 1.0:
                continue
            c = line.interpolate(sv).coords[0]
            t = _tangent(line, sv)
            if _free(lanes, _rect(c, t, PIER_ALONG, PIER_ACROSS)) and off_station(
                    _rect(c, t, PIER_ALONG + 0.2, CAP_ACROSS)):
                placed = sv
                break
        if placed is None and not off_station(_rect(line.interpolate(target).coords[0], _tangent(line, target),
                                                     PIER_ALONG + 0.2, CAP_ACROSS)):
            v.skipped.append(round(target, 1))  # (in a station: its columns carry the deck)
            target += PIER_STEP
            continue
        if placed is not None:
            c = line.interpolate(placed).coords[0]
            _pier(v, c, t, v.underside_at(placed), piers)
            v.pier_s.append(placed)
            last = placed
            target = placed + PIER_STEP
            continue
        # a portal frame across the road at the target
        c = line.interpolate(target).coords[0]
        t = _tangent(line, target)
        nrm = (-t[1], t[0])
        legs = []
        for sg in (1, -1):
            off = DECK_W / 2 - 1.0
            found = None
            while off <= 30.0:
                q = (c[0] + nrm[0] * off * sg, c[1] + nrm[1] * off * sg)
                ring = _rect(q, t, LEG, LEG)
                if _free(lanes, ring) and off_station(ring):
                    found = (q, ring)
                    break
                off += 0.5
            legs.append(found)
        if all(legs):
            zu = v.underside_at(target)
            for q, ring in legs:
                P.prism(piers, ring, 0.0, zu - 1.5, *CONCRETE_TILE, grey=DECK_GREY)
                v.pier_boxes.append(ring)
                v.barriers += P.ring_barriers(ring, 0.0, zu - 1.5)
                v.portal_legs += 1
            (qa, _), (qb, _) = legs
            mid = ((qa[0] + qb[0]) / 2, (qa[1] + qb[1]) / 2)
            ax = (qb[0] - qa[0], qb[1] - qa[1])
            La = math.hypot(*ax) or 1.0
            beam = P.box(mid[0], mid[1], ax[0] / La, ax[1] / La, La / 2 + LEG, LEG + 0.3, 0, 0)
            P.prism(piers, beam, zu - 1.5, zu, *CONCRETE_TILE, grey=DECK_GREY, bottom=True)
            v.pier_s.append(target)
            last = target
        else:
            v.skipped.append(round(target, 1))
        target += PIER_STEP


@dataclass
class Station:
    key: str
    name: str
    footprint: Polygon
    underside: float
    parts: P.PartSet
    columns: list = field(default_factory=list)
    stairs: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    photo_faces: int = 0
    letter_tris: int = 0

    def part_tris(self):
        return [t for p in self.parts.all() for t in p.tris]


FINISH = {"station_beige": "stn_beige", "station_orange": "stn_orange", "station_brick": "stn_brick"}


def _axes(fp):
    r = fp.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    if math.hypot(*e0) < math.hypot(*e1):
        e0, e1 = e1, e0
    la, lb = math.hypot(*e0), math.hypot(*e1)
    ctr = r.centroid
    return (ctr.x, ctr.y), (e0[0] / la, e0[1] / la), la, lb


def stations(lms, v, L, details, proj, photo_names, lanes=None):
    """[Station] for the station landmarks (tools/citymap/landmarks.py, kind "station"). photo_names: the photo
    textures available (their FTL_ names); a face without one is drawn in the finish."""
    from tools.citymap import landmarks, phototex
    lanes = lanes if lanes is not None else shapely.union_all([L.ground_polygon, L.elevated]).buffer(LANE_CLEAR)
    shapely.prepare(lanes)
    entrances = [proj.to_render(e["lat"], e["lon"]) for e in details["elements"]
                 if e["type"] == "node" and e.get("tags", {}).get("railway") == "subway_entrance"]
    out = []
    for lm in lms:
        fp = lm.footprint
        ps = P.PartSet(lm.key)
        st = Station(lm.key, lm.name, fp, CONCOURSE, ps)
        finish = FINISH.get(lm.finish, "stn_beige")
        by_edge = {}
        for f in lm.faces:
            by_edge.setdefault(f.edge_index, []).append(f)
        ring = list(fp.exterior.coords)[:-1]
        for k, (p, q) in enumerate(landmarks.edges(fp)):
            fs = by_edge.get(k, [])
            f = fs[0] if fs else None
            kind = phototex.texture_name(f.name) if f is not None else None
            if kind is not None and kind not in photo_names:
                kind = None
            if f is not None and kind is not None:
                st.photo_faces += 1
            if f is not None and f.z and f.z[1] <= PLATFORM + 0.01:  # the crop is the concourse: platform level plain
                P.faced_wall(ps, p, q, CONCOURSE, PLATFORM, finish, FINISH_TILE, f, kind, photo_glow="station")
                P.faced_wall(ps, p, q, PLATFORM, PLATFORM_TOP, finish, FINISH_TILE)
            else:
                P.faced_wall(ps, p, q, CONCOURSE, PLATFORM_TOP, finish, FINISH_TILE, f, kind, photo_glow="station")
            if f is not None and kind is not None:
                # Run J, item 2: the station's names as raised block letters on the face (one part a station, near
                # levels only: tools/citymap/station_letters.py)
                za, zb = f.z if f.z else (CONCOURSE, PLATFORM_TOP)
                st.letter_tris += station_letters.letters(kind, f, p, q, za, zb,
                                                          ps.get(station_letters.KIND, levels=P.DETAIL))
        # the concourse's underside
        under = ps.get("concrete")
        tris, uvs = P.flat(surfaces.triangulate(fp, 32.0), CONCOURSE, *CONCRETE_TILE, up=False)
        under.add(tris, uvs, P.colour((52, 52, 52)))
        _roof(ps, fp)
        _columns(st, fp, lanes)
        _stairs(st, fp, entrances, lanes)
        out.append(st)
    return out


def _roof(ps, fp):
    """An arch over the footprint's rotated rectangle along its long axis: 6 segments across, ROOF_RISE high."""
    (cx, cy), a, la, lb = _axes(fp)
    b = (-a[1], a[0])
    roof = ps.get("roofmetal")
    segs = 6
    prof = []
    for k in range(segs + 1):
        x = -lb / 2 + lb * k / segs
        z = PLATFORM_TOP + ROOF_RISE * (1 - (2 * x / lb) ** 2) + 0.3
        prof.append((x, z))
    ends = (-la / 2 - 1.0, la / 2 + 1.0)
    for (x0, z0), (x1, z1) in zip(prof, prof[1:]):
        P0 = (cx + a[0] * ends[0] + b[0] * x0, cy + a[1] * ends[0] + b[1] * x0, z0)
        P1 = (cx + a[0] * ends[1] + b[0] * x0, cy + a[1] * ends[1] + b[1] * x0, z0)
        Q0 = (cx + a[0] * ends[0] + b[0] * x1, cy + a[1] * ends[0] + b[1] * x1, z1)
        Q1 = (cx + a[0] * ends[1] + b[0] * x1, cy + a[1] * ends[1] + b[1] * x1, z1)
        for tris in ([(P0, P1, Q1), (P0, Q1, Q0)], [(P0, Q1, P1), (P0, Q0, Q1)]):  # both sides: seen from below too
            uvs = [tuple((p[0] / 4, -p[1] / 4) for p in t) for t in tris]
            roof.add(tris, uvs, [P.lit(t, 66.0) for t in tris])
    # the ends: the arch's gables, both sides
    for e in ends:
        base = [(cx + a[0] * e + b[0] * x, cy + a[1] * e + b[1] * x, PLATFORM_TOP) for x, _z in prof]
        arch = [(cx + a[0] * e + b[0] * x, cy + a[1] * e + b[1] * x, z) for x, z in prof]
        for k in range(segs):
            for tris in ([(base[k], base[k + 1], arch[k + 1]), (base[k], arch[k + 1], arch[k])],
                         [(base[k], arch[k + 1], base[k + 1]), (base[k], arch[k], arch[k + 1])]):
                uvs = [tuple((p[0] / 4, -p[2] / 4) for p in t) for t in tris]
                roof.add(tris, uvs, [P.lit(t, 60.0) for t in tris])


def _columns(st, fp, lanes):
    (cx, cy), a, la, lb = _axes(fp)
    b = (-a[1], a[0])
    conc = st.parts.get("concrete", "build", P.DETAIL)
    inner = fp.buffer(-0.8)
    n = max(1, int(la // COLUMN_STEP))
    for side in (-1, 1):
        for k in range(n + 1):
            x = -la / 2 + 2.0 + (la - 4.0) * k / n
            c = (cx + a[0] * x + b[0] * side * (lb / 2 - 2.0), cy + a[1] * x + b[1] * side * (lb / 2 - 2.0))
            ring = P.box(c[0], c[1], a[0], a[1], COLUMN, COLUMN, 0, 0)
            if not inner.contains(Polygon(ring)) or not _free(lanes, ring):
                continue
            P.prism(conc, ring, 0.0, CONCOURSE, *CONCRETE_TILE, grey=DECK_GREY)
            st.columns.append(ring)
            st.barriers += P.ring_barriers(ring, 0.0, CONCOURSE)


def _stairs(st, fp, entrances, lanes):
    """A stair at each OSM entrance within 40 m of the station: from the entrance up to the concourse, pointing at the
    station; turned (90, 180, 270 degrees) or left out when it would stand in a lane."""
    conc = st.parts.get("concrete", "build", P.DETAIL)
    c = fp.centroid
    for ex, ey in entrances:
        if fp.distance(Point(ex, ey)) > 40.0:
            continue
        dx, dy = c.x - ex, c.y - ey
        L0 = math.hypot(dx, dy) or 1.0
        base = (dx / L0, dy / L0)
        for turn in (0, 90, -90, 180):
            r = math.radians(turn)
            d = (base[0] * math.cos(r) - base[1] * math.sin(r), base[0] * math.sin(r) + base[1] * math.cos(r))
            mid = (ex + d[0] * STAIR_L / 2, ey + d[1] * STAIR_L / 2)
            ring = P.box(mid[0], mid[1], d[0], d[1], STAIR_L / 2, STAIR_W / 2, 0, 0)
            if _free(lanes, ring):
                break
        else:
            continue
        # a sloped block: its foot at the entrance (0 m), its head CONCOURSE up
        lo0, hi0, hi1, lo1 = ring  # corners: (-a,-b), (+a,-b), (+a,+b), (-a,+b): -a is the entrance end
        zf, zh = 0.3, CONCOURSE
        top = [((lo0[0], lo0[1], zf), (hi0[0], hi0[1], zh), (hi1[0], hi1[1], zh)),
               ((lo0[0], lo0[1], zf), (hi1[0], hi1[1], zh), (lo1[0], lo1[1], zf))]
        conc.add(top, [tuple((p[0] / 1, -p[1] / 1) for p in t) for t in top], P.colour((70, 70, 68)))
        for p, q, zp, zq in ((lo0, hi0, zf, zh), (hi1, lo1, zh, zf), (hi0, hi1, zh, zh), (lo1, lo0, zf, zf)):
            A, B, C, D = (p[0], p[1], 0.0), (q[0], q[1], 0.0), (q[0], q[1], zq), (p[0], p[1], zp)
            tris = [(A, B, C), (A, C, D)]  # facing out of the counter-clockwise ring (Run H fixes, fault 1)
            conc.add(tris, [tuple((x[0] / 4, -x[2] / 4) for x in t) for t in tris], [P.lit(t, DECK_GREY) for t in tris])
        st.stairs.append(ring)
        st.barriers += P.ring_barriers(ring, 0.0, 1.5)


def main(argv):
    import time
    from tools.citymap import buildings, geo, levels, roadmodel
    area = argv[0] if argv else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), ".superpowers", "citymap", "faridabad")
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        osm = json.load(f)
    with open(os.path.join(area, "details", "details.json"), encoding="utf-8") as f:
        details = json.load(f)
    proj = geo.Projection()
    L = levels.build(roadmodel.build(osm, proj))
    outer = buildings.edge_box(proj, (28.385, 77.305, 28.420, 77.332))
    t = time.time()
    v = viaduct(details, proj, L, outer)
    print("centre %.0f m, %d piers, %d portal legs, skipped %s, %d triangles, %.1f s" % (
        v.centre.length, len(v.pier_boxes), v.portal_legs, v.skipped, sum(len(p.tris) for p in v.parts.all()),
        time.time() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
