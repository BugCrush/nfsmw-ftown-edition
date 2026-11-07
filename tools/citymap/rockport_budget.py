"""Rockport's drawing load, measured from the game's files (read only), as the yardstick for F-Town's draw budget.

    .tools/cityenv/Scripts/python tools/citymap/rockport_budget.py "<game dir>" [out.json]

For every drivable section, the scenery the streamer loads with it (its visible list, 0x34153, and the LOD partners
the streamer combines, notes Task 2): the number of scenery instances (each one takes one of the 3,500 draw records
the game shares between all views a frame, Scenery.cpp:997), the meshes of their high-detail models (model[0]; a mesh
is a draw call at most) and the triangles. Prints the median and the largest, and the exclude flags of placed
(model-space) instances versus those at the origin. Numbers only: no game bytes are written.
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from world import bun, scenery  # noqa: E402


def measure(game):
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    stream = os.path.join(game, "TRACKS", "STREAML2RA.BUN")
    secs = bun.sections(l2ra)
    drivable = bun.drivable_sections(l2ra)
    present = {s.number for s in secs}
    solids = {}
    per_number = collections.defaultdict(lambda: [0, [], []])  # scenery number -> [instances, model0 hashes]
    flags = collections.Counter()
    for s in secs:
        d = scenery.read_section(bun.read_range(stream, s.offset, s.size))
        for h, so in d.solids.items():
            solids[h] = (len(so.meshes), sum(m.triangle_count for m in so.meshes))
        for sc in d.sceneries:
            rec = per_number[sc.number]
            for inst in sc.instances:
                rec[0] += 1
                info = sc.infos[inst.info_index]
                rec[1].append(info.solid_hashes[0])
                origin = inst.position == (0.0, 0.0, 0.0)
                flags[("origin" if origin else "placed", inst.exclude_flags & 0x200 != 0)] += 1
    rows = []
    for number, visible in drivable.items():
        nums = set()
        for v in visible:
            nums.add(v)
            nums.add(bun.combined_number(v, present))
        inst = meshes = tris = 0
        for n in nums:
            rec = per_number.get(n)
            if not rec:
                continue
            inst += rec[0]
            for h in rec[1]:
                m, t = solids.get(h, (0, 0))
                meshes += m
                tris += t
        rows.append((number, len(visible), inst, meshes, tris))
    return rows, flags


def summary(rows):
    out = {}
    for k, name in ((2, "instances"), (3, "meshes"), (4, "triangles")):
        vals = [r[k] for r in rows]
        top = max(rows, key=lambda r: r[k])
        out[name] = {"median": statistics.median(vals), "max": top[k], "max_section": top[0]}
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    rows, flags = measure(argv[0])
    s = summary(rows)
    s["exclude_0x200"] = {"%s, 0x200 %s" % k: v for k, v in flags.items()}
    print(json.dumps(s, indent=1))
    if len(argv) > 1:
        with open(argv[1], "w") as f:
            json.dump(s, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
