"""Test road networks for the stand-in (ftown/tests/run.py's net-* variants), made by tools/citymap/roadnet_build.py
from a small model on the slab's test ground: a two-way street north along render x 2000 from y 10950 to 13050 (the
test Time Attack's course) and a one-way street east from its point at y 12000; the stand-in's own Rockport network
(3 profiles, 4 nodes, 3 segments, 1 road) and its grid (Rockport's: min -4800, -1664, 64 m, 103 x 92).

    .tools/cityenv/Scripts/python ftown/tests/make_test_net.py <out dir> <traffic spots json>

writes net.bin (the stand-in's counts) and net-mismatch.bin (built after Rockport's real counts: refused).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from tools.citymap import roadmodel, roadnet_build as rb  # noqa: E402


def road(rid, kind, pts, oneway=False):
    w, lanes = roadmodel.width_of(kind, None, oneway)
    keys = ["%d,%d" % (round(x), round(y)) for x, y in pts]
    return roadmodel.Road(rid, kind, None, list(pts), keys, w, lanes, None, oneway, 0, None, False, 0)


def real_city(out):
    """net-realcity.bin: the real network (the road model, the city's heights, the events, the spots) numbered after
    the stand-in's Rockport, so the stand-in installs it over the real city (ftown/tests/run.py net-real-city)."""
    model = roadmodel.RoadModel.load(rb.ROADS)
    with open(rb.CITY_JSON) as f:
        bx = json.load(f)["edge_box"]
    box = (bx[0] + rb.BOX_INSET, bx[1] + rb.BOX_INSET, bx[2] - rb.BOX_INSET, bx[3] - rb.BOX_INSET)
    with open(rb.EVENTS) as f:
        events = [{"id": e["id"], "keys": e["keys"]} for e in json.load(f)["events"] if e.get("keys")]
    with open(rb.SPOTS) as f:
        spots = json.load(f)["spots"]
    built = rb.build(model, rb.city_heights(), box, rb.Rockport(3, 4, 3, 1, (-4800.0, -1664.0), 64.0, 103, 92),
                     events, spots)
    rb.write_file(built, os.path.join(out, "net-realcity.bin"))
    print("net-realcity.bin: %d nodes, %d segments, %d cells" % (len(built.net.nodes), len(built.net.segments),
                                                                 len(built.cells)))


def main(out, spots_path):
    if spots_path == "--real":
        return real_city(out)
    north = [(2000.0, 10950.0 + 50.0 * k) for k in range(43)]  # 10950 .. 13050, a point at 12000
    roads = [road(1, "residential", north), road(2, "tertiary", [(2000.0, 12000.0), (2150.0, 12000.0),
                                                                  (2300.0, 12000.0)], oneway=True)]
    nodes = {}
    for r in roads:
        for k, p in zip(r.keys, r.points):
            n = nodes.setdefault(k, roadmodel.Node(p[0], p[1], []))
            if r.id not in n.road_ids:
                n.road_ids.append(r.id)
    model = roadmodel.RoadModel(roads, nodes)
    with open(spots_path) as f:
        spots = json.load(f)["spots"]
    events = [{"id": "timeattack", "keys": roads[0].keys[1:-1]}]
    rb.GRID_MARGIN = 3000.0  # the slab's one big collision instance must fall inside our columns
    flat = lambda xs, ys, lv: [100.0] * len(xs)  # noqa: E731
    for name, rock in (("net.bin", rb.Rockport(3, 4, 3, 1, (-4800.0, -1664.0), 64.0, 103, 92)),
                       ("net-mismatch.bin", rb.Rockport(710, 4385, 6538, 1308, (-4800.0, -1664.0), 64.0, 103, 92))):
        built = rb.build(model, flat, (1000.0, 10000.0, 3000.0, 14000.0), rock, events, spots)
        rb.write_file(built, os.path.join(out, name))
        print("%s: %d nodes, %d segments, %d cells, pad %d, parking %d of %d" % (
            name, len(built.net.nodes), len(built.net.segments), len(built.cells), built.pad_cols,
            sum(built.parking), len(built.parking)))
    # the connection (FTownConnect.h, run.py link-* and net-join*): two one-way carriageways leaving the box's south
    # edge at x 1990 (north) and 2010 (south), and a link from the stand-in's Rockport (nodes 1 and 2 at render
    # (1030, 2000) and (1060, 2000), their segments 0, 1 and 1, 2) north to their middle on the edge; net-link-bad.bin
    # names node 1's segments as 0, 2 (another Rockport: the join is refused)
    roads += [road(3, "trunk", [(1990.0, 9900.0), (1990.0, 10100.0), (1990.0, 10200.0)], oneway=True),
              road(4, "trunk", [(2010.0, 10200.0), (2010.0, 10100.0), (2010.0, 9900.0)], oneway=True),
              road(5, "residential", [(1990.0, 10200.0), (2010.0, 10200.0)])]
    for r in roads[2:]:
        for k, p in zip(r.keys, r.points):
            n = nodes.setdefault(k, roadmodel.Node(p[0], p[1], []))
            if r.id not in n.road_ids:
                n.road_ids.append(r.id)
    model = roadmodel.RoadModel(roads, nodes)
    pts = [(1045.0 + (2000.0 - 1045.0) * k / 80.0, 2000.0 + 8000.0 * k / 80.0, 113.0 - 13.0 * k / 80.0)
           for k in range(81)]
    rock = rb.Rockport(3, 4, 3, 1, (-4800.0, -1664.0), 64.0, 103, 92)
    for name, segs1 in (("net-link.bin", [0, 1]), ("net-link-bad.bin", [0, 2])):
        mouths = [rb.RockMouth(1, (1030.0, 2000.0, 113.0), (-1.0, 0.0), False, segs1),
                  rb.RockMouth(2, (1060.0, 2000.0, 113.0), (1.0, 0.0), False, [1, 2])]
        link = rb.Link(points=pts, width_m=16.0, lanes=4, kind="motorway", junction=(1045.0, 2000.0), mouths=mouths,
                       carriageways=[3, 4])
        built = rb.build(model, flat, (1000.0, 10000.0, 3000.0, 14000.0), rock, events, spots, link=link)
        rb.write_file(built, os.path.join(out, name))
        print("%s: %d nodes, %d segments, joins %s, %d cells in Rockport's columns, %d link segments" % (
            name, len(built.net.nodes), len(built.net.segments), [(j.rock_node, j.added) for j in built.joins],
            len(built.rock_cells), len(built.link_segments)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
