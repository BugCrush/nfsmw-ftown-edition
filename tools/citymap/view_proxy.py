"""The per-view draw proxy read from a written city file (build_city.views' model of the main view: what the game's
DrawAScenery would draw from each viewpoint), with a breakdown: meshes by texture, by distance band and by model
level (docs/ftown-notes.md "Run H fixes (2026-11-04)", fault 4).

    .tools/cityenv/Scripts/python tools/citymap/view_proxy.py <city.bun> [<city.json>] [--detail NAME]

The spawns come from the json beside the file (or the one given); the five landmark viewpoints from build_city.
"""
import collections
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import read_chunks  # noqa: E402
from world import scenery  # noqa: E402

from tools.citymap import build_city  # noqa: E402


def entries_of(data):
    """[{"pos", "radius", "name", "models": [{"meshes", "density", "tris", "kinds": [mesh name...]} or None] x 4}]."""
    solids, scs = {}, []
    for c, p in scenery.with_positions(read_chunks(data), 0):
        if c.id == scenery.SOLID_LIST:
            for k, kp in scenery.with_positions(c.children, p):
                if k.id == scenery.SOLID:
                    so = scenery.read_solid(k, kp)
                    solids[so.name_hash] = so
        elif c.id == scenery.SCENERY_SECTION:
            scs.append(scenery.read_scenery(c, p))
    out = []
    from tools.citymap import x0props
    lib = x0props.library()  # the street life's instances name X0's models (by hash): their counts from the catalogue
    for sc in scs:
        for inst in sc.instances:
            info = sc.infos[inst.info_index]
            ms = []
            for h in info.solid_hashes:
                so = solids.get(h)
                if so is None:
                    ms.append(lib.get(h))
                    continue
                ms.append({"meshes": len(so.meshes), "density": struct.unpack_from("<f", so.header, 0x9C)[0],
                           "tris": struct.unpack_from("<h", so.header, 0x14)[0], "kinds": list(so.mesh_names),
                           "name": so.name})
            out.append({"pos": inst.matrix[3][:3], "radius": info.radius, "name": info.name, "models": ms})
    return out


def breakdown(entries, view):
    """As build_city.views for one viewpoint, with the drawn instances listed: [(entry, model, distance)]."""
    ex, ey, ez = view["x"], view["y"], view["z"] + 0.5
    h = math.radians(view["heading"])
    fx, fy = math.cos(h), math.sin(h)
    drawn = []
    for e in entries:
        dx, dy, dz = e["pos"][0] - ex, e["pos"][1] - ey, e["pos"][2] - ez
        R = e["radius"] + 6.0
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        ahead = dx * fx + dy * fy
        if ahead < -R:
            continue
        if d > R:
            ang = math.degrees(math.acos(max(-1.0, min(1.0, ahead / max(1e-6, math.hypot(dx, dy))))))
            if ang - math.degrees(math.asin(min(1.0, R / d))) > build_city.VIEW_FOV / 2:
                continue
        px = build_city.VIEW_H if d - R <= R else R * build_city.VIEW_H / (d - R)
        if int(px) <= 0x11:
            continue
        m0 = e["models"][0]
        use = m0
        if m0["tris"] > 39 and (px / max(6.0, m0["density"])) < 8.7:
            use = e["models"][2]
        if use is None:
            continue
        drawn.append((e, use, d, use is m0))
    return drawn


def report(entries, views, detail=None):
    rows = []
    for v in views:
        dr = breakdown(entries, v)
        meshes = sum(u["meshes"] for _e, u, _d, _n in dr)
        tris = sum(u["tris"] for _e, u, _d, _n in dr)
        rows.append({"name": v["name"], "instances": len(dr), "meshes": meshes, "triangles": tris})
        if detail and v["name"] == detail:
            by_kind = collections.Counter()
            by_band = collections.Counter()
            by_level = collections.Counter()
            for e, u, d, near in dr:
                for k in u["kinds"]:
                    by_kind[k] += 1
                band = "%4d-%4d m" % (int(d // 250) * 250, int(d // 250) * 250 + 250)
                by_band[band] += u["meshes"]
                by_level[("near " if near else "far ") + e["name"][:5]] += u["meshes"]
            print("%s: meshes by texture %s" % (v["name"], dict(by_kind.most_common())))
            print("  by distance %s" % dict(sorted(by_band.items())))
            print("  by level and instance kind %s" % dict(by_level))
    return rows


def main(argv):
    detail = None
    if "--detail" in argv:
        i = argv.index("--detail")
        detail = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__)
        return 1
    with open(argv[0], "rb") as f:
        data = f.read()
    js = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(argv[0])), "ftown-city.json")
    with open(js) as f:
        spawns = json.load(f)["spawns"]
    entries = entries_of(data)
    for r in report(entries, spawns + build_city.VIEWPOINTS, detail):
        print("%-18s %5d instances %6d meshes %8d triangles" % (r["name"], r["instances"], r["meshes"],
                                                              r["triangles"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
