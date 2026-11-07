"""Task 2's pictures: the built road surfaces over the OSM drawing, and three junctions close up.

    .tools/cityenv/Scripts/python tools/citymap/render_surfaces.py <area dir>

Writes <area dir>/surfaces.png (the whole area over map.png) and surfaces-<name>.png close-ups: Neelam Chowk (the
roundabout under the Neelam Flyover), the first route's turn south between Sectors 15 and 16, and the route's end on
Mathura Road.
"""
import json
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import geo, render, roadmodel, surfaces  # noqa: E402

ROAD = (90, 90, 96, 200)
DECK = (60, 60, 200, 170)
PAV = (200, 170, 120, 200)
MARK = (255, 255, 255, 255)


def _sharpest_turn(pts):
    """The point where a polyline turns most (the route's turn south between Sectors 15 and 16)."""
    import math
    best, at = -1.0, pts[0]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        t = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
        if t > best and math.dist(a, b) > 5 and math.dist(b, c) > 5:
            best, at = t, b
    return at


def main(argv):
    area = argv[0]
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        m = roadmodel.build(json.load(f))
    p = surfaces.road_polygons(m)
    pav = surfaces.pavements(m, p)
    marks = surfaces.markings(m, p)
    import shapely
    mk = shapely.union_all([q for _k, q, _r in marks])
    lines = [(r.points, (220, 30, 30), 1) for r in m.roads]
    out = [render.top(os.path.join(area, "map.png"), os.path.join(area, "surfaces.png"),
                      [(pav, PAV), (p[0], ROAD), (p[1], DECK)], lines)]
    proj = geo.Projection()
    with open(os.path.join(area, "route_main.json")) as f:
        route = [proj.to_render(a, b) for a, b in json.load(f)["points"]]
    spots = {
        "neelam-chowk": next(r for r in m.roads if r.name == "Neelam Chowk").points[0],
        "route-turn": _sharpest_turn(route[: len(route) // 2]),
        "route-end": route[-1],
    }
    for name, c in spots.items():
        out.append(render.closeup(os.path.join(area, "surfaces-%s.png" % name), c, 90.0,
                                  [(pav, PAV), (p[0], ROAD), (p[1], DECK), (mk, MARK)],
                                  [(r.points, (220, 30, 30), 1) for r in m.roads], ppm=4.0,
                                  title="%s: road (grey), deck (blue), pavement (tan), markings (white), OSM centre "
                                        "lines (red); 180 m across" % name))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
