"""The Time Attack's gates on F-Town's first route (DND-KMP exit to Mathura Road, .superpowers/citymap/faridabad/
route_main.json): a checkpoint every 500 m along the route and the finish 30 m before its end, each a line across the
route (FTownLoader counts a gate when the car's path between two frames crosses it, in the route's direction).

    .tools/cityenv/Scripts/python tools/citymap/route_gates.py     print the [TimeAttack] lines for ftown/FTownLoader.ini

Positions in render metres (x east, y north), heading in degrees counter-clockwise from +x, as [Spawn]. The start is
the city's "route start" spawn (ftown/ftown-city.json).
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

SPACING = 500.0
FINISH_BEFORE_END = 30.0


def route_render(route_json, proj):
    with open(route_json) as f:
        return [proj.to_render(lat, lon) for lat, lon in json.load(f)["points"]]


def along(route):
    s = [0.0]
    for a, b in zip(route, route[1:]):
        s.append(s[-1] + math.dist(a, b))
    return s


def point_at(route, s_at):
    s = along(route)
    for k in range(len(route) - 1):
        if s[k + 1] >= s_at:
            (ax, ay), (bx, by) = route[k], route[k + 1]
            t = (s_at - s[k]) / (s[k + 1] - s[k])
            return ax + (bx - ax) * t, ay + (by - ay) * t, math.degrees(math.atan2(by - ay, bx - ax))
    raise ValueError("%.1f m is past the route's end" % s_at)


def gates(route):
    """[{s, x, y, heading}]: the checkpoints every SPACING metres, then the finish."""
    length = along(route)[-1]
    out = []
    k = 1
    while k * SPACING < length - FINISH_BEFORE_END:
        x, y, h = point_at(route, k * SPACING)
        out.append({"s": k * SPACING, "x": x, "y": y, "heading": h})
        k += 1
    x, y, h = point_at(route, length - FINISH_BEFORE_END)
    out.append({"s": length - FINISH_BEFORE_END, "x": x, "y": y, "heading": h})
    return out


def ini_lines(route, repo=REPO):
    """[(key, value)] for [TimeAttack]: Start (the route-start spawn), Gate1..GateN, Finish."""
    with open(os.path.join(repo, "ftown", "ftown-city.json")) as f:
        s0 = json.load(f)["spawns"][0]
    out = [("Start", "%.2f, %.2f, %.2f, %.1f" % (s0["x"], s0["y"], s0["z"], s0["heading"]))]
    g = gates(route)
    for k, gate in enumerate(g[:-1]):
        out.append(("Gate%d" % (k + 1), "%.2f, %.2f, %.1f" % (gate["x"], gate["y"], gate["heading"])))
    out.append(("Finish", "%.2f, %.2f, %.1f" % (g[-1]["x"], g[-1]["y"], g[-1]["heading"])))
    return out


def main():
    from tools.citymap import geo
    route = route_render(os.path.join(REPO, ".superpowers", "citymap", "faridabad", "route_main.json"), geo.Projection())
    print("; route %.1f m" % along(route)[-1])
    for k, v in ini_lines(route):
        print("%s = %s" % (k, v))


if __name__ == "__main__":
    main()
