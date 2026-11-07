"""Read-only report of a .blend file for the car build: objects, triangles, size, materials, textures.

    .tools\\blender-4.3.2-windows-x64\\blender.exe -b "<file.blend>" --python tools/carbuild/inspect_blend.py -- <out.txt>

Nothing is saved: Blender opens the file in the background, this script writes the report and Blender quits.
"""
import sys

import bpy

out_path = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None
lines = []


def say(s=""):
    lines.append(s)


def tris(obj):
    me = obj.data
    return sum(len(p.vertices) - 2 for p in me.polygons)


scene = bpy.context.scene
say("file: %s" % bpy.data.filepath)
say("scene units: %s, scale %.4f; frame %d" % (scene.unit_settings.system, scene.unit_settings.scale_length, scene.frame_current))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
say("objects: %d (%d meshes); materials %d; images %d" % (len(bpy.data.objects), len(meshes), len(bpy.data.materials),
                                                       len(bpy.data.images)))
total = 0
say("")
say("%-40s %8s %8s  %-28s %-24s %s" % ("object", "tris", "verts", "size x/y/z (m, world)", "location", "materials"))
for o in sorted(meshes, key=lambda o: -tris(o)):
    t = tris(o)
    total += t
    d = o.dimensions
    loc = o.matrix_world.translation
    mats = [s.material.name if s.material else "-" for s in o.material_slots]
    mods = [m.type for m in o.modifiers]
    say("%-40s %8d %8d  %6.2f %6.2f %6.2f        %6.2f %6.2f %6.2f  %s%s%s" % (
        o.name[:40], t, len(o.data.vertices), d.x, d.y, d.z, loc.x, loc.y, loc.z, ",".join(mats)[:80],
        "  parent=" + o.parent.name if o.parent else "", "  modifiers=" + ",".join(mods) if mods else ""))
say("")
say("total triangles (before modifiers): %d" % total)

# with modifiers applied (subdivision etc. raise the count)
dg = bpy.context.evaluated_depsgraph_get()
ev_total = 0
for o in meshes:
    eo = o.evaluated_get(dg)
    me = eo.to_mesh()
    ev_total += sum(len(p.vertices) - 2 for p in me.polygons)
    eo.to_mesh_clear()
say("total triangles (with modifiers): %d" % ev_total)

say("")
say("materials:")
for m in bpy.data.materials:
    if not m.use_nodes:
        say("  %-32s no nodes, colour %s" % (m.name, tuple(round(c, 2) for c in m.diffuse_color)))
        continue
    kinds = sorted({n.type for n in m.node_tree.nodes})
    imgs = [n.image.name + ("(%dx%d)" % tuple(n.image.size) if n.image else "") for n in m.node_tree.nodes
            if n.type == "TEX_IMAGE" and n.image]
    users = m.users
    say("  %-32s users %d  nodes %s%s" % (m.name, users, ",".join(kinds), ("  images " + ",".join(imgs)) if imgs else ""))
say("")
say("images:")
for im in bpy.data.images:
    say("  %-40s %dx%d packed=%s file=%s" % (im.name, im.size[0], im.size[1], bool(im.packed_file), im.filepath))

text = "\n".join(lines)
if out_path:
    open(out_path, "w", encoding="utf-8").write(text)
print(text)
