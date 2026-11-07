"""Before/after renders of Run J's city side (docs/ftown-notes.md "Run J: the city side (2026-11-05)"): run I's files
left, Run J's right, drawn from the files themselves as render_runi.py draws them (render_tex.Scene, X0's models from
the game's files; the sheets go under .superpowers/, git-ignored: they hold Rockport's textures).

    .tools/cityenv/Scripts/python tools/citymap/render_runj.py <before dir> <after dir> <out dir>

Sheets: stations (each drawn face from the road in front of it, the names raised), divided roads (a driver's view on
the Time Attack's Ambedkar Marg and the Speed Trap's Mathura Road, the barriers round the whole road).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.citymap import events, render_runi, terrain  # noqa: E402


def station_eyes():
    """A viewpoint on the road in front of each station face (its middle, 30-45 m out, 1.3 m up, looking at it)."""
    import shapely
    from tools.citymap import build_city as B, buildings, geo, landmarks, levels, roadmodel, station_letters as SL
    from tools.citymap import surfaces
    from tools.citymap import phototex
    area = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
    osm, areas, _route = B._load(area)
    proj = geo.Projection()
    model = roadmodel.build(osm, proj)
    L = levels.build(model)
    pav = surfaces.pavements(model, {0: L.ground_polygon}).difference(L.elevated)
    roads = shapely.union_all([L.ground_polygon, pav, L.elevated])
    bl = buildings.blocks(osm, proj, roads, seed=1, areas=areas, model=model, bbox=B.BBOX)
    lms = landmarks.resolve(landmarks.load(), osm, B._details(area), proj, bl.blocks, L.raised_chains)
    out = []
    for lm in lms:
        if lm.kind != "station":
            continue
        seen = set()
        for f in lm.faces:
            name = phototex.texture_name(f.name)
            if name in seen or name not in SL.TEXTS:
                continue
            seen.add(name)
            p, q = landmarks.edges(lm.footprint)[f.edge_index]
            Lf = math.dist(p, q)
            n = ((q[1] - p[1]) / Lf, -(q[0] - p[0]) / Lf)
            c = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            best = None
            for back in range(18, 61, 3):
                e = (c[0] + n[0] * back, c[1] + n[1] * back)
                if L.ground_polygon.contains(shapely.Point(e)):
                    best = e
                    break
            e = best or (c[0] + n[0] * 35, c[1] + n[1] * 35)
            dist = math.dist(e, c)
            hd = math.degrees(math.atan2(c[1] - e[1], c[0] - e[0]))
            pitch = math.degrees(math.atan2(8.5 - 1.3, dist))
            out.append(("%s from %.0f m" % (name[8:], dist), (e[0], e[1], terrain.ground_z(*e) + 1.3), hd, pitch))
    return out


def main(argv):
    before, after, out_dir = argv
    os.makedirs(out_dir, exist_ok=True)
    lib = render_runi.library()
    evs = {e["id"]: e for e in events.read()}
    scs = [(render_runi.scene(d, lib, "day"), "day") for d in (before, after)]
    render_runi.sheet(station_eyes(), scs, os.path.join(out_dir, "stations.png"),
                      "Stations (item 2): the lettering clear of the deck, the names raised")
    for ev, ss in ((evs["timeattack"], (430, 850, 1750)), (evs["speedtrap"], (120, 1600, 2600))):
        scs = [(render_runi.scene(d, lib, "day", (ev["barriers"],)), "day") for d in (before, after)]
        render_runi.sheet(render_runi.route_eyes(ev, ss), scs, os.path.join(out_dir, "whole-road-%s.png" % ev["id"]),
                          "The barriers round the whole road (item 5): a driver's view")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
