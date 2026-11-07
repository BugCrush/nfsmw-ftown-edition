"""How many race-barrier panels each event shows at once: the panels of its barrier file within PANEL_SEEN metres (the
panels' draw distance at H 1,000, docs/ftown-race-notes.md "Game mode: built") of each point of its route, every 10 m.

    .tools/cityenv/Scripts/python tools/citymap/events_panels.py      (prints max and median per event)
"""
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import read_chunks  # noqa: E402
from world import scenery  # noqa: E402

from tools.citymap import events  # noqa: E402

PANEL_SEEN = 359.0


def panel_positions(data):
    out = []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id == scenery.SCENERY_SECTION:
            for inst in scenery.read_scenery(c, p).instances:
                m = inst.matrix
                out.append((m[3][0], m[3][1]))
    return out


def seen(ev, path):
    import numpy as np
    with open(path, "rb") as f:
        P = np.array(panel_positions(f.read()))
    s = events.along(ev["route"])
    counts = []
    for k in range(0, int(s[-1]), 10):
        x, y, _h = events.point_at(ev["route"], k)
        counts.append(int((np.hypot(P[:, 0] - x, P[:, 1] - y) < PANEL_SEEN).sum()) if len(P) else 0)
    return max(counts), statistics.median(counts), len(P)


def main():
    for ev in events.read():
        path = os.path.join(REPO, "ftown", ev["barriers"])
        if os.path.exists(path):
            mx, med, n = seen(ev, path)
            print("%-10s %3d panels; within %.0f m of the route: max %d, median %.0f" % (ev["id"], n, PANEL_SEEN, mx, med))


if __name__ == "__main__":
    main()
