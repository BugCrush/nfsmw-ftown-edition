"""The Time Attack's gates on the first route (Task 3 of docs/superpowers/plans/2026-11-04-ftown-minimap-timeattack.md):
a gate about every 500 m along the route, the finish near its end on Mathura Road, written into FTownLoader.ini
[TimeAttack] so the plugin needs no OSM data.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_route_gates -v
"""
import math
import os
import re
import unittest

from tools.citymap.tests import common

INI = os.path.join(common.REPO, "ftown", "FTownLoader.ini")
EVENTS = os.path.join(common.REPO, "ftown", "ftown-events.json")


def ini_section(name):
    with open(INI, "rb") as f:
        text = f.read().decode("ascii")
    m = re.search(r"\r\n\[%s\]\r\n(.*?)(\r\n\[|\Z)" % name, text, re.S)
    out = {}
    for line in m.group(1).split("\r\n"):
        k = re.match(r"(\w+) = (.*)$", line)
        if k:
            out[k.group(1)] = k.group(2)
    return out


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common.need(common.ROUTE)
        from tools.citymap import route_gates
        cls.rg = route_gates
        cls.route = route_gates.route_render(common.ROUTE, common.proj())
        cls.gates = route_gates.gates(cls.route)

    def test_every_500_m_and_the_finish_near_the_end(self):
        length = self.rg.along(self.route)[-1]
        s = [g["s"] for g in self.gates]
        self.assertEqual(len(s), int((length - self.rg.FINISH_BEFORE_END) // self.rg.SPACING) + 1)
        for k in range(len(s) - 1):
            self.assertAlmostEqual(s[k], (k + 1) * self.rg.SPACING, places=6)
        self.assertAlmostEqual(s[-1], length - self.rg.FINISH_BEFORE_END, places=6)
        self.assertGreater(s[-1] - s[-2], 100, "the finish too close to the last checkpoint")

    def test_gates_lie_on_the_route_facing_along_it(self):
        for g in self.gates:
            # the nearest route segment: distance and direction
            best = None
            for (ax, ay), (bx, by) in zip(self.route, self.route[1:]):
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, ((g["x"] - ax) * dx + (g["y"] - ay) * dy) / (dx * dx + dy * dy)))
                d = math.hypot(ax + dx * t - g["x"], ay + dy * t - g["y"])
                if best is None or d < best[0]:
                    best = (d, math.degrees(math.atan2(dy, dx)))
            self.assertLess(best[0], 0.01)
            diff = (g["heading"] - best[1] + 180) % 360 - 180
            self.assertLess(abs(diff), 0.1)

    def test_events_json_carries_the_gates_and_the_start(self):
        """Since the events (plan 2026-11-04-ftown-events): the Time Attack is the first event of ftown/ftown-events.json
        (FTownLoader reads its start and gates there, not from the ini)."""
        import json
        with open(EVENTS) as f:
            ta = json.load(f)["events"][0]
        self.assertEqual(ta["id"], "timeattack")
        want = dict(self.rg.ini_lines(self.route, common.REPO))
        self.assertEqual("%.2f, %.2f, %.2f, %.1f" % tuple(ta["start"]), want["Start"])
        gates = ta["gates"]
        self.assertEqual(len(gates), len(self.gates))
        for k, g in enumerate(gates[:-1]):
            self.assertEqual("%.2f, %.2f, %.1f" % (g["x"], g["y"], g["heading"]), want["Gate%d" % (k + 1)])
        self.assertEqual("%.2f, %.2f, %.1f" % (gates[-1]["x"], gates[-1]["y"], gates[-1]["heading"]), want["Finish"])


if __name__ == "__main__":
    unittest.main()
