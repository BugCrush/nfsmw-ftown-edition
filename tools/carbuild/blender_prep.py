"""Blender (headless) preparation of a source car model into the game's parts: the car builder's step 2.

    blender.exe -b <source.blend> --python-exit-code 1 --python tools/carbuild/blender_prep.py -- <config.json> <out dir>

Run through `python tools/carbuild/carbin.py prep <config.json> [--out <dir>]`. The .blend is only read: nothing is
saved. Steps (config keys in brackets):

1. Every modifier is shown as it renders; subdivision is capped [subsurf_max, subsurf_max_objects]; dense objects get
   a Decimate modifier at the end of their stack [pre_decimate]. Objects that are hidden in renders, empty, or match
   [drop] (wildcards) are left out and listed in parts.json "dropped".
2. The evaluated meshes (all modifiers applied, mirrors and arrays included) are read in world space, triangulated,
   with each triangle's material name (an empty slot takes [material_for_unassigned][object] or "-").
3. Game axes and size: the source's front is -Y and left +X; the game's front +X, left +Y, up +Z, so a point (x, y, z)
   becomes s * (-y, x, z), s = [length] / the source's length along y (every kept object, spare wheel included). The
   origin follows tools/carbuild/conventions.py: x at the middle of the body's length, z at the body's lowest point.
4. Triangles go to game parts by the first matching rule [rules] (object names, optional materials, "split": "side"
   puts each triangle in the {SIDE} = LEFT (y > 0) or RIGHT part by its centre).
5. The wheel [wheel]: the four wheels' centres and outer faces are measured from the tyre object; the front-right
   wheel's triangles (tyre, rim, disc) become the tyre part, centred on its axle in x and z, its outer face at y = 0 and
   extending to +y (conventions.TYRE_SIDE), as the game's racers store theirs. With [ride_height_cm] everything else
   then moves up or down so the wheel centres sit at conventions.wheel_centre_z(W, ride_height_cm) (parts.json
   "origin_z_offset"; the Thar: its body's lowest point ends up 0.31 m above the origin).
6. Each part is one Blender mesh, decimated (collapse) to its triangle budget [budget_A] (and the detail levels'
   ratios of it [lod_ratios]), shaded smooth with sharp edges above 35 degrees, and written out.

Output: parts.json (format carbuild-prep 1; per part: materials, source objects, and per level the file, triangle
count and box), one <PART>_<LOD>.bin per part and level (triangle corners, unindexed: float32 positions x 3, float32
normals x 3, float32 uvs x 2, then a uint16 material index per triangle), and wheel.json.
"""
import fnmatch
import json
import math
import os
import struct
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import conventions  # noqa: E402

SHARP_ANGLE = math.radians(35)
LODS = "ABCDE"


def matches(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def render_hidden_collection(o):
    """True when every collection holding the object is hidden from renders (itself or a parent collection), or
    excluded from the view layer: helper objects such as boolean cutters live there (Cube.001 in "extra")."""
    parents = {}
    for c in bpy.data.collections:
        for child in c.children:
            parents.setdefault(child.name, []).append(c)
    excluded = set()

    def walk(lc):
        if lc.exclude:
            excluded.add(lc.collection.name)
        for ch in lc.children:
            walk(ch)
    walk(bpy.context.view_layer.layer_collection)

    def hidden(c, seen=()):
        if c.hide_render or c.name in excluded:
            return True
        ps = parents.get(c.name, [])
        return bool(ps) and all(hidden(p, seen + (c.name,)) for p in ps if p.name not in seen)

    cols = list(o.users_collection)
    if not cols or any(c == bpy.context.scene.collection for c in cols):
        return False  # the scene's own collection is always rendered
    return all(hidden(c) for c in cols)


def prepare(cfg):
    dropped, kept = [], []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if matches(o.name, cfg.get("drop", [])) or o.hide_render or render_hidden_collection(o):
            dropped.append(o.name)
            continue
        cap = cfg.get("subsurf_max_objects", {}).get(o.name, cfg.get("subsurf_max", 0))
        for m in o.modifiers:
            m.show_viewport = m.show_render
            if m.type == "SUBSURF":
                m.levels = min(m.render_levels, cap)
        ratio = cfg.get("pre_decimate", {}).get(o.name)
        if ratio:
            d = o.modifiers.new("carbuild_pre", "DECIMATE")
            d.decimate_type = "COLLAPSE"
            d.ratio = ratio
        kept.append(o)
    return kept, dropped


def read_objects(objs, cfg):
    """{object name: (world vertices, triangles as vertex index triples, material name per triangle)}."""
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    unassigned = cfg.get("material_for_unassigned", {})
    out, empty = {}, []
    for o in objs:
        eo = o.evaluated_get(dg)
        me = eo.to_mesh()
        me.calc_loop_triangles()
        if not me.loop_triangles:
            empty.append(o.name)
            eo.to_mesh_clear()
            continue
        mw = eo.matrix_world
        flip = mw.determinant() < 0
        verts = [tuple(mw @ v.co) for v in me.vertices]
        slots = [s.material.name if s.material else None for s in eo.material_slots]
        tris, mats = [], []
        for lt in me.loop_triangles:
            a, b, c = lt.vertices
            if a == b or b == c or a == c:
                continue
            tris.append((a, c, b) if flip else (a, b, c))
            name = slots[lt.material_index] if lt.material_index < len(slots) else None
            mats.append(name or unassigned.get(o.name, "-"))
        out[o.name] = (verts, tris, mats)
        eo.to_mesh_clear()
    return out, empty


def part_of(obj, mat, rules):
    for r in rules:
        if matches(obj, r["objects"]) and ("materials" not in r or mat in r["materials"]):
            return r["part"], r.get("split")
    return None, None


def to_game(meshes, s):
    for name, (verts, tris, mats) in meshes.items():
        meshes[name] = ([(-y * s, x * s, z * s) for x, y, z in verts], tris, mats)


def shift(meshes, dx, dz):
    for name, (verts, tris, mats) in meshes.items():
        meshes[name] = ([(x + dx, y, z + dz) for x, y, z in verts], tris, mats)


def centroid(verts, t):
    return [(verts[t[0]][a] + verts[t[1]][a] + verts[t[2]][a]) / 3 for a in range(3)]


def build_mesh(name, pieces, materials):
    """A Blender object from [(verts, [(tri, material name)])] pieces, sharing each piece's vertices."""
    vs, faces, fmat = [], [], []
    for verts, tris in pieces:
        remap = {}
        for t, mat in tris:
            f = []
            for i in t:
                if i not in remap:
                    remap[i] = len(vs)
                    vs.append(verts[i])
                f.append(remap[i])
            faces.append(f)
            fmat.append(materials.index(mat))
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs, [], faces)
    for m in materials:
        mat = bpy.data.materials.get("carbuild:" + m) or bpy.data.materials.new("carbuild:" + m)
        me.materials.append(mat)
    me.polygons.foreach_set("material_index", fmat)
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def keep_extremes(ob):
    """A vertex group that lets the decimation touch every vertex but the part's outermost ones (the lowest and highest
    vertex along each axis: weight 0, which Blender's Decimate leaves in place), so no level comes out smaller than
    level A."""
    g = ob.vertex_groups.get("carbuild_extremes")
    if g is not None:
        return g
    g = ob.vertex_groups.new(name="carbuild_extremes")
    vs = ob.data.vertices
    ext = set()
    for k in range(3):
        ext.add(min(vs, key=lambda v: v.co[k]).index)
        ext.add(max(vs, key=lambda v: v.co[k]).index)
    g.add([v.index for v in vs if v.index not in ext], 1.0, "REPLACE")
    g.add(sorted(ext), 0.0, "REPLACE")
    return g


BOX_TOLERANCE = 0.015  # a level whose box moved more than this from level A's is not used


def decimated(ob, ratio, symmetric):
    """The part's object decimated (collapse, outermost vertices kept) to `ratio` of its triangles and shaded smooth
    with sharp edges above SHARP_ANGLE: a list of triangles (3 positions, 3 normals, material index)."""
    for m in list(ob.modifiers):
        ob.modifiers.remove(m)
    if ratio < 1:
        d = ob.modifiers.new("carbuild_lod", "DECIMATE")
        d.decimate_type = "COLLAPSE"
        d.ratio = ratio
        if symmetric:
            d.use_symmetry = True
            d.symmetry_axis = "Y"
        d.vertex_group = keep_extremes(ob).name
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    me.shade_smooth()
    me.set_sharp_from_angle(angle=SHARP_ANGLE)
    me.calc_loop_triangles()
    tris = [(tuple(tuple(me.vertices[i].co) for i in lt.vertices), tuple(tuple(n) for n in lt.split_normals),
             lt.material_index) for lt in me.loop_triangles]
    bpy.data.meshes.remove(me)
    return tris


def tri_box(tris):
    ps = [p for t in tris for p in t[0]]
    return [min(p[k] for p in ps) for k in range(3)] + [max(p[k] for p in ps) for k in range(3)]


def area(t):
    (a, b, c) = t[0]
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    w = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return math.sqrt(sum(x * x for x in w)) / 2


def drop_smallest(tris, target):
    """For parts too small to decimate (a 42-triangle window pane, a 10-triangle lamp housing): the previous level
    without its smallest triangles (a thin pane's rim first), keeping for each face of the part's box the largest triangle
    touching it, so the box stays the same."""
    box = tri_box(tris)
    keep = set()
    for k in range(6):  # for each face of the box, the largest triangle touching it
        touching = [i for i, t in enumerate(tris) if any(abs(p[k % 3] - box[k]) < 1e-6 for p in t[0])]
        keep.add(max(touching, key=lambda i: area(tris[i])))
    order = sorted((i for i in range(len(tris)) if i not in keep), key=lambda i: area(tris[i]))
    drop = set(order[:max(0, len(tris) - target)])
    return [t for i, t in enumerate(tris) if i not in drop]


def level_ok(tris, prev, box_a):
    return 0 < len(tris) < len(prev) and all(abs(u - v) <= BOX_TOLERANCE for u, v in zip(tri_box(tris), box_a))


def write_level(tris, path):
    pos = [c for t in tris for p in t[0] for c in p]
    nor = [c for t in tris for n in t[1] for c in n]
    mat = [t[2] for t in tris]
    with open(path, "wb") as f:
        f.write(struct.pack("<%df" % len(pos), *pos))
        f.write(struct.pack("<%df" % len(nor), *nor))
        f.write(bytes(len(mat) * 3 * 8))  # uvs: zero here; the assembler places them on the palette
        f.write(struct.pack("<%dH" % len(mat), *mat))
    return len(mat), tri_box(tris)


def main():
    a = sys.argv[sys.argv.index("--") + 1:]
    cfg_path, out = a[0], a[1]
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(out, exist_ok=True)
    objs, dropped = prepare(cfg)
    meshes, empty = read_objects(objs, cfg)
    dropped += empty

    allv = [v for verts, _, _ in meshes.values() for v in verts]
    src_box = [min(v[k] for v in allv) for k in range(3)] + [max(v[k] for v in allv) for k in range(3)]
    s = cfg["length"] / (src_box[4] - src_box[1])
    rest = [v for n, (verts, _, _) in meshes.items() if n not in cfg["wheel"]["objects"] for v in verts]
    src_box_parts = [min(v[k] for v in rest) for k in range(3)] + [max(v[k] for v in rest) for k in range(3)]
    to_game(meshes, s)

    wheel_cfg = cfg["wheel"]
    wheel_objs = [n for n in wheel_cfg["objects"] if n in meshes]
    rules = cfg["rules"]
    assign = {}  # part -> {object: [(tri, material)]}
    for name, (verts, tris, mats) in meshes.items():
        if name in wheel_objs:
            continue
        for t, mat in zip(tris, mats):
            part, split = part_of(name, mat, rules)
            if part is None:
                raise SystemExit("no rule for object %r material %r" % (name, mat))
            if split == "side":
                part = part.replace("{SIDE}", "LEFT" if centroid(verts, t)[1] > 0 else "RIGHT")
            assign.setdefault(part, {}).setdefault(name, []).append((t, mat))

    # origin (conventions.ORIGIN_X / ORIGIN_Z) from the body's own extents
    body = [meshes[n][0][i] for n, tl in assign["KIT00_BODY"].items() for t, _ in tl for i in t]
    assert conventions.ORIGIN_X == "body_centre" and conventions.ORIGIN_Z == "body_min"
    dx = -(min(p[0] for p in body) + max(p[0] for p in body)) / 2
    dz = -min(p[2] for p in body)
    shift(meshes, dx, dz)

    # the wheel: four centres from the tyre object, the front-right wheel as the tyre part
    tv, tt, _ = meshes[wheel_cfg["tyre_object"]]
    centres, outer = {}, {}
    for key, front, left in (("FL", True, True), ("FR", True, False), ("RL", False, True), ("RR", False, False)):
        idx = {i for t in tt for i in t if (centroid(tv, t)[0] > 0) == front and (centroid(tv, t)[1] > 0) == left}
        ps = [tv[i] for i in idx]
        lo = [min(p[k] for p in ps) for k in range(3)]
        hi = [max(p[k] for p in ps) for k in range(3)]
        centres[key] = [(lo[k] + hi[k]) / 2 for k in range(3)]
        ys = [verts[i][1] for n in wheel_objs for verts, tris, _ in [meshes[n]] for t in tris
              if (centroid(verts, t)[0] > 0) == front and (centroid(verts, t)[1] > 0) == left for i in t]
        outer[key] = max(ys) if left else -min(ys)  # the whole wheel's (tyre, rim, disc) outer face
    fr = centres["FR"]
    pieces, used = [], {}
    for n in wheel_objs:
        verts, tris, mats = meshes[n]
        sel = [(t, m) for t, m in zip(tris, mats) if centroid(verts, t)[0] > 0 and centroid(verts, t)[1] < 0]
        if sel:
            pieces.append((n, verts, sel))
    ymin = min(pieces_v[i][1] for _, pieces_v, sel in pieces for t, _ in sel for i in t)
    assert conventions.TYRE_SIDE == 1
    tyre_part = wheel_cfg["part"]
    for n, verts, sel in pieces:
        moved = [(x - fr[0], y - ymin, z - fr[2]) for x, y, z in verts]
        assign.setdefault(tyre_part, {})[n] = sel
        meshes[n] = (moved, meshes[n][1], meshes[n][2])
    tyre_pts = [meshes[wheel_cfg["tyre_object"]][0][i] for t, _ in assign[tyre_part][wheel_cfg["tyre_object"]] for i in t]
    all_pts = [meshes[n][0][i] for n, sel in assign[tyre_part].items() for t, _ in sel for i in t]
    radius = max(max(p[0] for p in tyre_pts) - min(p[0] for p in tyre_pts),
                 max(p[2] for p in tyre_pts) - min(p[2] for p in tyre_pts)) / 2
    width = max(p[1] for p in all_pts) - min(p[1] for p in all_pts)

    # [ride_height_cm]: the wheel rule (conventions.wheel_centre_z, W = radius + the box margin) at that ride height
    # decides where the wheel centres sit against the origin, so everything but the tyre part (which sits on its own
    # axle) moves by the difference. A model with no chassis underneath (the Thar's lowest point is its bumpers) would
    # otherwise need a ride height beyond the suspension's travel (the first test-copy race, 2026-11-02).
    oz = 0.0
    if cfg.get("ride_height_cm") is not None:
        zc = sum(c[2] for c in centres.values()) / 4
        oz = conventions.wheel_centre_z(radius + conventions.BOX_MARGIN, cfg["ride_height_cm"]) - zc
        for c in centres.values():
            c[2] += oz
        dz += oz

    def lifted(tris, part):
        if not oz or part == tyre_part:
            return tris
        return [(tuple((p[0], p[1], p[2] + oz) for p in t[0]),) + tuple(t[1:]) for t in tris]

    budgets = cfg.get("budget_A", {})
    ratios = cfg.get("lod_ratios", {})
    levels_of = cfg.get("levels", {})
    parts = {}
    for part in sorted(assign):
        mats = sorted({m for tl in assign[part].values() for _, m in tl})
        ob = build_mesh(part, [(meshes[n][0], tl) for n, tl in assign[part].items()], mats)
        total = sum(len(tl) for tl in assign[part].values())
        budget = budgets.get(part, budgets.get("*", total))
        base = min(1.0, budget / total)
        symmetric = "_LEFT" not in part and "_RIGHT" not in part and part != tyre_part
        levels, prev, box_a = {}, None, None
        for lod in levels_of.get(part, levels_of.get("*", "A")):
            r = base * (1.0 if lod == "A" else ratios[lod])
            tris, how = decimated(ob, r, symmetric), "collapse"
            if prev is None:
                box_a = tri_box(tris)
            elif not level_ok(tris, prev, box_a):
                # too small to decimate further without shrinking: thin the previous level instead
                tris, how = drop_smallest(prev, min(len(prev) - 1, max(1, round(levels["A"]["triangles"] * r)))),                     "drop_smallest"
                if not level_ok(tris, prev, box_a):
                    raise SystemExit("%s level %s: cannot make %d triangles smaller" % (part, lod, len(prev)))
            fname = "%s_%s.bin" % (part, lod)
            t, b = write_level(lifted(tris, part), os.path.join(out, fname))
            levels[lod] = {"file": fname, "triangles": t, "box": b, "ratio": r, "method": how}
            prev = tris
        parts[part] = {"materials": mats, "objects": sorted(assign[part]), "source_triangles": total,
                       "levels": levels}
        print("part %-32s %6d -> %s" % (part, total, " ".join("%s %d" % (k, v["triangles"]) for k, v in levels.items())))

    info = {
        "format": "carbuild-prep", "version": 1, "car": cfg["car"], "credit": cfg.get("credit"),
        "scale": s, "source_box": src_box, "source_length": src_box[4] - src_box[1],
        "source_box_without_wheels": src_box_parts,
        "transform": "game = scale * (-y, x, z) + (dx, 0, dz)", "origin_shift": [dx, 0, dz],
        "ride_height_cm": cfg.get("ride_height_cm"), "origin_z_offset": oz,
        "layout": "per triangle corner float32 position x3, then float32 normal x3, then float32 uv x2 (all corners of "
                  "each block in order), then uint16 material index per triangle",
        "parts": parts, "dropped": sorted(dropped),
    }
    with open(os.path.join(out, "parts.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    wheel = {"radius": radius, "width": width, "side": conventions.TYRE_SIDE, "centres": centres, "outer_y": outer,
             "tyre_part": tyre_part, "note": "game coordinates; outer_y = |y| of each wheel's outer face"}
    with open(os.path.join(out, "wheel.json"), "w", encoding="utf-8") as f:
        json.dump(wheel, f, indent=1)
    print("wrote", out)


main()
