"""F-Town's road network for the AI (tools/citymap/roadnet_build.py, plan
docs/superpowers/plans/2026-11-05-ftown-moving-traffic.md Task 2).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_roadnet_build -v

The synthetic tests need nothing; the real-data tests need the road model, the events and the data file the builder
wrote (ftown/ftown-roadnet.bin) and skip without them.
"""
import json
import math
import os
import struct
import sys
import unittest

from tools.citymap.tests import common

sys.path.insert(0, os.path.join(common.TOOLS))  # "world" for roadnet
from tools.citymap import roadmodel, roadnet_build as rb  # noqa: E402
from world import roadnet  # noqa: E402

ROCK = rb.Rockport(profiles=710, nodes=4385, segments=6538, roads=1308, grid_min=(-4800.0, -1664.0), edge=64.0,
                   rows=103, cols=92)
BIN = os.path.join(common.REPO, "ftown", "ftown-roadnet.bin")
JSON = os.path.join(common.REPO, "ftown", "ftown-roadnet.json")


def model(roads):
    nodes = {}
    for r in roads:
        for k, p in zip(r.keys, r.points):
            n = nodes.setdefault(k, roadmodel.Node(p[0], p[1], []))
            if r.id not in n.road_ids:
                n.road_ids.append(r.id)
    return roadmodel.RoadModel(roads, nodes)


def road(rid, kind, pts, oneway=False, level=0):
    w, lanes = roadmodel.width_of(kind, None, oneway)
    keys = ["%d,%d" % (round(x * 10), round(y * 10)) for x, y in pts]
    return roadmodel.Road(rid, kind, None, list(pts), keys, w, lanes, None, oneway, 0, None, False, level)


def dead_ends(test, net, base_nodes=4385, base_segs=6538):
    segs = {s.index: s for s in net.segments}
    for n in net.nodes:
        allowed = [k for k in n.segments if not segs[k].flags & roadnet.NO_TRAFFIC]
        test.assertNotEqual(len(allowed), 1, "node %d: one segment that allows traffic (a dead end)" % n.index)
        roads = [k for k in n.segments if not segs[k].flags & roadnet.DECISION]
        if any(segs[k].flags & roadnet.DECISION for k in allowed):
            test.assertTrue(any(k in allowed for k in roads), "node %d: turns allowed into a closed road" % n.index)


def flat(xs, ys, levels):
    return [100.0 + 7.0 * lv for lv in levels]


# a T: a two-way residential street west-east through (1500, 11000), a one-way tertiary going north from the junction,
# a trunk (one-way) far away with a bend, a service road off the street's west end
T_ROADS = [road(1, "residential", [(1400, 11000), (1450, 11000), (1500, 11000), (1560, 11000), (1620, 11000)]),
           road(2, "tertiary", [(1500, 11000), (1500, 11060), (1500, 11130)], oneway=True),
           road(3, "trunk", [(2000, 11000), (2100, 11000), (2160, 11060), (2160, 11200)], oneway=True),
           road(4, "service", [(1400, 11000), (1400, 10950)])]
BOX = (1000.0, 10000.0, 3000.0, 12000.0)


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = rb.build(model(T_ROADS), flat, BOX, ROCK)
        cls.net = cls.b.net

    def seg(self, i):
        return self.net.segments[i - ROCK.segments]

    def test_numbered_after_rockport(self):
        n = self.net
        self.assertEqual([s.index for s in n.segments], list(range(ROCK.segments, ROCK.segments + len(n.segments))))
        self.assertEqual([x.index for x in n.nodes], list(range(ROCK.nodes, ROCK.nodes + len(n.nodes))))
        for x in n.nodes:
            self.assertGreaterEqual(x.profile, ROCK.profiles)
        for s in n.segments:
            self.assertTrue(s.road == -1 or s.road >= ROCK.roads)

    def test_t_junction(self):
        dec = [s for s in self.net.segments if s.flags & roadnet.DECISION]
        self.assertTrue(all(s.flags & roadnet.INTERSECTION and s.road == -1 for s in dec))
        # the T: 3 mouths, 3 decision segments; the street's west end meets the service road: 2 mouths, 1
        self.assertEqual(len(dec), 3 + 1)
        for s in dec:
            for k in s.nodes:
                self.assertLessEqual(len(self.net.nodes[k - ROCK.nodes].segments), 7)

    def test_nodes_and_segments_agree(self):
        for s in self.net.segments:
            for k in s.nodes:
                self.assertIn(s.index, self.net.nodes[k - ROCK.nodes].segments)
        for n in self.net.nodes:
            for k in n.segments:
                self.assertIn(n.index, self.seg(k).nodes)

    def test_no_dead_end_for_traffic(self):
        # Rockport has no end node on a segment that allows traffic (the review): a car there stops for good. Every
        # branch that leads only to dead ends is NoTraffic up to its junction, the turns into it too
        dead_ends(self, self.net)

    def test_pieces_at_most_30_m(self):
        for s in self.net.segments:
            if not s.flags & roadnet.DECISION:
                self.assertLessEqual(s.length_m, 30.5)

    def test_one_way(self):
        ow = [s for s in self.net.segments if s.flags & roadnet.ONE_WAY]
        self.assertTrue(ow)
        for s in ow:  # node 0 -> node 1 runs along the road: render x and y never fall on the tertiary or the trunk
            a, b = (self.net.nodes[k - ROCK.nodes].pos for k in s.nodes)
            ra, rbb = (a[2], -a[0]), (b[2], -b[0])  # render (x, y) = (physics z, -physics x)
            self.assertGreaterEqual(rbb[0] - ra[0], -1e-3)
            self.assertGreaterEqual(rbb[1] - ra[1], -1e-3)
            self.assertGreater(math.dist(ra, rbb), 0.1)
        self.assertFalse(any(s.flags & roadnet.ONE_WAY for s in self.net.segments
                             if s.road >= 0 and self.b.road_kind[s.road - ROCK.roads] == "residential"))

    def test_no_traffic_on_service(self):
        for s in self.net.segments:
            kinds = self.b.segment_kinds[s.index - ROCK.segments]
            if "service" in kinds or "living_street" in kinds:  # (dead-end branches are closed too)
                self.assertTrue(s.flags & roadnet.NO_TRAFFIC)

    def test_profiles_match_the_carriageway(self):
        for r_i, kind in enumerate(self.b.road_kind):
            r = self.b.road_model[r_i]
            p = self.net.profiles[self.b.road_profile[r_i] - ROCK.profiles]
            lanes = p.lanes()
            edges = []
            for i, (t, w, o) in enumerate(lanes):
                pos = o if i >= p.middle else -o
                edges += [pos - w / 2, pos + w / 2]
            self.assertAlmostEqual(min(edges), -r.width_m / 2, delta=0.02, msg=kind)
            self.assertAlmostEqual(max(edges), r.width_m / 2, delta=0.02, msg=kind)
            traffic = sum(1 for t, _w, _o in lanes if t == roadnet.LANE_TRAFFIC)
            self.assertEqual(traffic, max(r.lanes, 1 if r.oneway else 2))
            if r.oneway:
                self.assertEqual(p.middle, 0)

    def test_curves_follow_the_centre_line(self):
        # a bend's corner is rounded over 4 m each side (the 45-degree bend: 0.76 m inside the corner)
        self.assertLess(self.b.max_curve_error, 1.0)

    def test_heights(self):
        for n in self.net.nodes:
            self.assertAlmostEqual(n.pos[1], 100.0, places=3)

    def test_speeds(self):
        kmh = {k: v for k, v in rb.KMH.items()}
        for s in self.net.segments:
            if s.road >= 0:
                self.assertEqual(self.b.kmh[s.index - ROCK.segments], kmh[self.b.road_kind[s.road - ROCK.roads]])
        self.assertEqual(rb.KMH["trunk"], 70)
        self.assertEqual(rb.KMH["residential"], 35)

    def test_cells(self):
        cols = ROCK.cols + self.b.pad_cols
        min_x = ROCK.grid_min[0] - self.b.pad_cols * ROCK.edge
        self.assertLessEqual(min_x, min(n.pos[0] for n in self.net.nodes) - rb.GRID_MARGIN)
        found = {}
        for cell, segs in self.b.cells.items():
            row, col = divmod(cell, cols)
            self.assertLess(col, self.b.pad_cols)  # never one of Rockport's columns
            for s in segs:
                found.setdefault(s, set()).add(cell)
        for s in self.net.segments:
            a = self.net.nodes[s.nodes[0] - ROCK.nodes].pos
            col = int((a[0] - min_x) // ROCK.edge)
            row = int((a[2] - ROCK.grid_min[1]) // ROCK.edge)
            self.assertIn(row * cols + col, found[s.index])

    def test_file(self):
        path = os.path.join(common.SCRATCH, "roadnet-test.bin")
        os.makedirs(common.SCRATCH, exist_ok=True)
        rb.write_file(self.b, path)
        data = open(path, "rb").read()
        f = rb.read_file(data)
        self.assertEqual(f["magic"], b"FTRN")
        self.assertEqual((f["rock_profiles"], f["rock_nodes"], f["rock_segments"], f["rock_roads"]), (710, 4385,
                                                                                                     6538, 1308))
        self.assertEqual(roadnet.encode(f["net"]), roadnet.encode(self.net))
        self.assertEqual(f["cells"], {c: sorted(v) for c, v in self.b.cells.items()})
        self.assertEqual(f["kmh"], self.b.kmh)


class Route(unittest.TestCase):
    def test_marks(self):
        m = model(T_ROADS)
        ev = {"id": "t", "keys": T_ROADS[0].keys[:3] + T_ROADS[1].keys[1:]}  # west along the street, north
        b = rb.build(m, flat, BOX, ROCK, events=[ev])
        marks = b.events["t"]
        fwd = [s for s, f in marks.items() if f == "forward"]
        back = [s for s, f in marks.items() if f == "backward"]
        exits = [s for s, f in marks.items() if f == "exit"]
        self.assertTrue(fwd)
        self.assertEqual(len(exits), 2)  # at the T: the two decision segments to the street's east arm
        net = b.net
        turn = [s for s in fwd + back if net.segments[s - ROCK.segments].flags & roadnet.DECISION]
        self.assertEqual(len(turn), 1)
        for s in exits:
            self.assertTrue(net.segments[s - ROCK.segments].flags & roadnet.DECISION)


def link_case():
    """Two one-way carriageways leaving the box's south edge at x 1500 (north) and 1520 (south), and a connector from a
    Rockport T at (1510, 4600) (inside Rockport's grid: render y < 4,800) north to their middle on the edge."""
    roads = [road(10, "trunk", [(1500, 9900), (1500, 10100), (1500, 10300)], oneway=True),
             road(11, "trunk", [(1520, 10300), (1520, 10100), (1520, 9900)], oneway=True),
             road(12, "residential", [(1500, 10300), (1520, 10300)])]
    pts = [(1510.0, 4600.0 + k * 100.0, 200.0 - k * 2.0) for k in range(55)] + [(1510.0, 10000.0, 100.0)]
    mouths = [rb.RockMouth(259, (1500.0, 4590.0, 200.0), (-1.0, 0.0), True, [11, 12, 13]),
              rb.RockMouth(260, (1520.0, 4590.0, 200.0), (1.0, 0.0), False, [14, 12, 15]),
              rb.RockMouth(261, (1510.0, 4580.0, 200.0), (0.0, -1.0), True, [16, 13, 15])]
    link = rb.Link(points=pts, width_m=16.0, lanes=4, kind="motorway", junction=(1510.0, 4590.0), mouths=mouths,
                   carriageways=[10, 11])
    return model(roads), link


class MouthInversion(unittest.TestCase):
    """The review (2026-11-06): our join segment arrives at a Rockport mouth travelling out of the junction, as a
    decision segment that ends there does; one that starts there travels the other way, so its flag is negated."""

    def seg(self, a, b, flags):
        return roadnet.Segment((a, b), 1000, -1, 0, roadnet.DECISION | roadnet.INTERSECTION | flags, 0, 0, (0, 0, 0),
                               (0, 0, 0))

    def test_ending_at_the_mouth(self):
        self.assertTrue(rb.mouth_inverted(self.seg(5, 7, roadnet.END_INVERTED), 7))
        self.assertFalse(rb.mouth_inverted(self.seg(5, 7, roadnet.START_INVERTED), 7))

    def test_starting_at_the_mouth(self):
        self.assertFalse(rb.mouth_inverted(self.seg(7, 5, roadnet.START_INVERTED), 7))
        self.assertTrue(rb.mouth_inverted(self.seg(7, 5, 0), 7))

    def test_rockport_mouths(self):
        common.need(rb.L2RA)
        got = {m.index: m.inverted for m in rb.rockport_mouths((259, 260, 261))}
        self.assertEqual(got, {259: True, 260: True, 261: False})  # 261's road 2241 leaves it uninverted


class Link(unittest.TestCase):
    """The connection to Rockport (plan docs/superpowers/plans/2026-11-06-ftown-rockport-connection.md Task 3)."""

    @classmethod
    def setUpClass(cls):
        m, cls.link = link_case()
        cls.b = rb.build(m, flat, BOX, ROCK, link=cls.link)
        cls.net = cls.b.net
        cls.segs = {s.index: s for s in cls.net.segments}

    def test_joins(self):
        self.assertEqual([j.rock_node for j in self.b.joins], [259, 260, 261])
        for j, mouth in zip(self.b.joins, self.link.mouths):
            s = self.segs[j.added]
            self.assertEqual(j.before, mouth.segments)
            self.assertEqual(s.flags & (roadnet.DECISION | roadnet.INTERSECTION), roadnet.DECISION | roadnet.INTERSECTION)
            self.assertEqual(s.road, -1)
            self.assertTrue(s.flags & roadnet.START_INVERTED)
            self.assertEqual(bool(s.flags & roadnet.END_INVERTED), mouth.inverted)
            self.assertEqual(s.nodes[1], mouth.index)
            ours = self.net.nodes[s.nodes[0] - ROCK.nodes]
            self.assertIn(j.added, ours.segments)

    def test_our_mouth(self):
        mouth = self.net.nodes[self.segs[self.b.joins[0].added].nodes[0] - ROCK.nodes]
        kinds = sorted(bool(self.segs[k].flags & roadnet.DECISION) for k in mouth.segments)
        self.assertEqual(kinds, [False, True, True, True])
        self.assertAlmostEqual(mouth.pos[1], 200.0, delta=0.5)  # the connector's own height, not the city's

    def test_edge_junction(self):
        link = set(self.b.link_segments)
        dec_f = [s for s in self.net.segments if s.flags & roadnet.DECISION and s.index not in
                 {j.added for j in self.b.joins} and 9900 < min(-self.net.nodes[k - ROCK.nodes].pos[0] for k in s.nodes) < 10100]
        self.assertEqual(len(dec_f), 3)  # connector, north and south carriageways
        self.assertEqual(sum(1 for s in dec_f if s.index in link), 2)  # the U-turn between the carriageways stays

    def test_link_segments(self):
        link = set(self.b.link_segments)
        for j in self.b.joins:
            self.assertIn(j.added, link)
        road = [s for s in self.net.segments if s.road >= 0 and self.b.road_kind[s.road - ROCK.roads] == "motorway"]
        self.assertTrue(road)
        self.assertTrue(all(s.index in link for s in road))

    def test_no_dead_end(self):
        dead_ends(self, self.net)

    def test_rock_cells(self):
        self.assertTrue(self.b.rock_cells)
        for cell, tags in self.b.rock_cells.items():
            self.assertLess(cell, ROCK.rows * ROCK.cols)
            row, col = divmod(cell, ROCK.cols)
            self.assertLessEqual(-4800.0 + col * 64.0, -4590.0 + 64.0)  # the junction's end of the grid
            for t in tags:
                self.assertIn(t, self.segs)
        joined = {j.added for j in self.b.joins}
        self.assertTrue(joined & {t for v in self.b.rock_cells.values() for t in v})

    def test_file_v2(self):
        path = os.path.join(common.SCRATCH, "roadnet-link.bin")
        os.makedirs(common.SCRATCH, exist_ok=True)
        rb.write_file(self.b, path)
        f = rb.read_file(open(path, "rb").read())
        self.assertEqual(f["version"], 2)
        self.assertEqual([(j.rock_node, j.before, j.added) for j in f["joins"]],
                         [(j.rock_node, j.before, j.added) for j in self.b.joins])
        self.assertEqual(f["rock_cells"], {c: sorted(v) for c, v in self.b.rock_cells.items()})
        self.assertEqual(f["link"], sorted(self.b.link_segments))
        self.assertEqual(roadnet.encode(f["net"]), roadnet.encode(self.net))

    def test_without_link_still_version_1_layout(self):
        b = rb.build(model(T_ROADS), flat, BOX, ROCK)
        self.assertEqual((b.joins, b.rock_cells, b.link_segments), ([], {}, []))


class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(BIN, JSON)
        cls.data = open(BIN, "rb").read()
        cls.f = rb.read_file(cls.data)
        with open(JSON) as fh:
            cls.info = json.load(fh)

    def test_counts_match_the_json(self):
        net = self.f["net"]
        c = self.info["counts"]
        self.assertEqual((len(net.profiles), len(net.nodes), len(net.segments), len(net.roads)),
                         (c["profiles"], c["nodes"], c["segments"], c["roads"]))
        self.assertEqual(self.info["bytes"], len(self.data))

    def test_limits(self):
        net = self.f["net"]
        self.assertLess(6538 + len(net.segments), 32768)
        self.assertLess(4385 + len(net.nodes), 32768)
        self.assertLessEqual(max(len(n.segments) for n in net.nodes), 7)
        self.assertLess(max(len(v) for v in self.f["cells"].values()), 255)

    def test_no_dead_end_for_traffic(self):
        dead_ends(self, self.f["net"])

    def test_every_event_marked(self):
        ids = {e["id"] for e in json.load(open(os.path.join(common.REPO, "ftown", "ftown-events.json")))["events"]}
        self.assertEqual(set(self.f["events"]), ids)
        for eid, marks in self.f["events"].items():
            self.assertGreater(sum(1 for v in marks.values() if v != "exit"), 20, eid)


if __name__ == "__main__":
    unittest.main()
