"""Blender (headless) view of a car description: imports the parts the reader produced and renders fixed views.

    blender.exe -b --factory-startup --python tools/carbuild/blender_view.py -- <description folder> <out dir>
        [--textures <folder with textures.json>]... [--all-parts] [--wheels] [--wheels-at <wheel_report.json>]
        [--box x0 y0 z0 x1 y1 z1] [--prefix <name prefix>] [--masks]
    blender.exe -b <source.blend> --python tools/carbuild/blender_view.py -- <description folder> <out dir>
        --source <car config.json> --prep <preparation folder> [--box ...] [--prefix ...] [--masks]

Writes front.png, side.png, rear.png and three_quarter.png (1280x720) into <out dir>. Run through
`python tools/carbuild/carbin.py render <folder> <out dir>`.

Parts shown by default: detail level A only (names ending in _A), body kit 00 only, no damage variants, no shop
parts (STYLExx), no decal placeholders; tyres and brakes are left out because the game places them from the car's
`ecar` data (the model's tyre sits at the origin). Game axes: +X forward, +Y left, +Z up (headlights at +X, LEFT_
parts at +Y), which Blender shows as is.

--cabin also renders cabin_left.png, cabin_front.png and cabin_three_quarter.png: close on the windows' box with the
windows left out, to see the interior and driver; --hide-interior leaves the KIT00_INTERIOR and KIT00_DRIVER parts
out (to compare).

--wheels-at places the tyre part at the wheel report's four positions as the game draws it; --box fixes the framing
(so two runs share their cameras); --masks also renders mask_<prefix><view>.png, the car black on white. --source
renders the source model Blender was started with instead, in the game's axes and size (the preparation's scale and
origin), without the objects the preparation dropped, in flat colours by the config's material roles.

Materials: the mesh's slot-0 texture from the description's texture packs when found (DDS, loaded by Blender),
otherwise a flat colour by shader (paint red for CARSKIN, dark glass for WINDSHIELD, and so on). Rendered with the
Workbench engine (no GPU path tracing needed), studio light, texture colours.
"""
import json
import math
import os
import re
import sys

import bpy
from mathutils import Matrix, Vector


def bstringhash(name):
    h = 0xFFFFFFFF
    for c in name.encode("ascii"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


SHADER_COLOURS = {  # flat colours by shader when no texture is found (RGBA)
    "CARSKIN": (0.55, 0.05, 0.05, 1), "WINDSHIELD": (0.08, 0.1, 0.12, 1), "RUBBER": (0.03, 0.03, 0.03, 1),
    "INTERIOR": (0.15, 0.15, 0.15, 1), "BRAKELIGHT": (0.6, 0.02, 0.02, 1), "BRAKELIGHTGLASS": (0.7, 0.1, 0.1, 1),
    "HEADLIGHTGLASS": (0.75, 0.78, 0.8, 1), "HEADLIGHTREFLECTOR": (0.8, 0.8, 0.8, 1), "DULLPLASTIC": (0.06, 0.06, 0.06, 1),
    "CHROME": (0.75, 0.75, 0.78, 1), "DECAL": (0.5, 0.5, 0.5, 1), "LICENSEPLATE": (0.85, 0.85, 0.8, 1),
    "GRILL": (0.05, 0.05, 0.05, 1), "BRAKEDISC": (0.4, 0.4, 0.4, 1), "CARBONFIBRE": (0.08, 0.08, 0.09, 1),
}
SHADER_BY_HASH = {bstringhash(n): n for n in SHADER_COLOURS}
DEFAULT_COLOUR = (0.45, 0.45, 0.45, 1)


def args():
    a = sys.argv[sys.argv.index("--") + 1:]
    opts = {"desc": a[0], "out": a[1], "textures": [], "all": False, "wheels": False, "wheels_at": None,
            "box": None, "prefix": "", "masks": False, "source": None, "prep": None, "cabin": False,
            "hide_interior": False, "wheel_z": None, "select": False}
    k = 2
    while k < len(a):
        if a[k] == "--textures":
            opts["textures"].append(a[k + 1])
            k += 2
        elif a[k] == "--all-parts":
            opts["all"] = True
            k += 1
        elif a[k] == "--wheels":
            opts["wheels"] = True
            k += 1
        elif a[k] in ("--wheels-at", "--prefix", "--source", "--prep"):
            opts[a[k][2:].replace("-", "_")] = a[k + 1]
            k += 2
        elif a[k] == "--masks":
            opts["masks"] = True
            k += 1
        elif a[k] == "--wheel-z":
            opts["wheel_z"] = float(a[k + 1])
            k += 2
        elif a[k] in ("--cabin", "--hide-interior", "--select"):
            opts[a[k][2:].replace("-", "_")] = True
            k += 1
        elif a[k] == "--box":
            opts["box"] = [float(x) for x in a[k + 1:k + 7]]
            k += 7
        else:
            raise SystemExit("unknown option " + a[k])
    if os.path.exists(os.path.join(opts["desc"], "textures.json")):
        opts["textures"].insert(0, opts["desc"])
    return opts


def shown(name, opts):
    if opts["all"]:
        return True
    if not name.endswith("_A"):
        return False
    if re.search(r"_KIT(\d\d)_", name) and "_KIT00_" not in name:
        return False
    if any(k in name for k in ("DAMAGE", "_STYLE", "_DECAL_")):
        return False
    if opts["hide_interior"] and any(k in name for k in ("_KIT00_INTERIOR_", "_KIT00_DRIVER_")):
        return False
    if opts["wheels_at"] and "_TIRE" in name:
        return False  # placed at the wheel report's positions instead
    if not opts["wheels"] and any(k in name for k in ("_TIRE", "_BRAKE_A", "_FRONT_BRAKE", "_REAR_BRAKE", "_RIM")):
        return False
    return True


def texture_files(folders):
    """name hash -> DDS path, from the texture descriptions' textures.json."""
    out = {}
    for folder in folders:
        with open(os.path.join(folder, "textures.json")) as f:
            doc = json.load(f)
        for t in doc["textures"]:
            if t.get("data"):
                dds = os.path.abspath(os.path.join(folder, t["data"][:-4] + ".dds"))  # Blender: no relative paths
                if os.path.exists(dds):
                    out.setdefault(int(t["name_hash"], 16), dds)
    return out


def read_obj(path):
    verts, uvs, groups, faces = [], [], [], []
    current = None
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                verts.append(tuple(float(x) for x in line.split()[1:4]))
            elif line.startswith("vt "):
                uvs.append(tuple(float(x) for x in line.split()[1:3]))
            elif line.startswith("usemtl "):
                current = line.split()[1]
                groups.append(current)
            elif line.startswith("f "):
                idx = [int(p.split("/")[0]) - 1 for p in line.split()[1:4]]
                faces.append((idx, len(groups) - 1))
    return verts, uvs, groups, faces


_materials = {}


def material(key, tex_files):
    if key in _materials:
        return _materials[key]
    m = re.match(r"tex_([0-9A-F]{8})_shader_([0-9A-F]{8})", key)
    tex, shader = (int(m.group(1), 16), int(m.group(2), 16)) if m else (0, 0)
    shader_name = SHADER_BY_HASH.get(shader)
    mat = bpy.data.materials.new(key)
    mat.diffuse_color = SHADER_COLOURS.get(shader_name, DEFAULT_COLOUR)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    if tex in tex_files and shader_name != "CARSKIN":
        img = bpy.data.images.load(tex_files[tex], check_existing=True)
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = img
        mat.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
        mat.node_tree.nodes.active = node
    _materials[key] = mat
    return mat


def import_part(name, path, tex_files):
    verts, uvs, groups, faces = read_obj(path)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [f for f, _ in faces])
    me.update()
    if uvs:
        layer = me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                layer.data[li].uv = uvs[vi] if vi < len(uvs) else (0, 0)
    for g in groups:
        me.materials.append(material(g, tex_files))
    for poly, (_, gi) in zip(me.polygons, faces):
        poly.material_index = max(gi, 0)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def look_at(cam, target):
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def place_wheels(doc, opts, tex_files):
    """The tyre part at the wheel report's four positions, as the game draws it (speed.exe 0x74F054..0x74F235): scaled
    to W / box half length and TireSkidWidth / box width, the right wheels (Y < 0) at y = Y + y_m, the left ones turned
    half a turn about z so the model's outer face (y = 0) looks outward, covering [Y - width, Y]."""
    with open(opts["wheels_at"]) as f:
        rep = json.load(f)
    s = [s for s in doc["solids"] if s["name"].endswith("_KIT00_FRONT_TIRE_A")][0]
    stem = os.path.basename(s["vertices"])[:-4]
    tyre = import_part(s["name"], os.path.join(opts["desc"], "obj", stem + ".obj"), tex_files)
    lo, hi = s["bbox"][0:3], s["bbox"][3:6]  # the stored box: extents + 0.01 m, what the game measures
    zc = rep["wheel_centre_z"] if opts["wheel_z"] is None else opts["wheel_z"]
    print("wheel centre z %g" % zc)
    out = []
    for i, t in enumerate(rep["TireOffsets"]):
        o = tyre if i == 0 else bpy.data.objects.new("%s_%d" % (s["name"], i), tyre.data)
        if i:
            bpy.context.scene.collection.objects.link(o)
        o.scale = (t["W"] / ((hi[0] - lo[0]) / 2), rep["TireSkidWidth"] / (hi[1] - lo[1]),
                   t["W"] / ((hi[2] - lo[2]) / 2))
        o.location = (t["X"], t["Y"], zc + t["Z"])
        o.rotation_euler = (0, 0, math.pi if t["Y"] > 0 else 0)
        out.append(o)
    return out


def setup_desc(opts):
    with open(os.path.join(opts["desc"], "car.json")) as f:
        doc = json.load(f)
    tex_files = texture_files(opts["textures"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = []
    for k, s in enumerate(doc["solids"]):
        if not s.get("vertices") or not shown(s["name"], opts):
            continue
        stem = os.path.basename(s["vertices"])[:-4]
        path = os.path.join(opts["desc"], "obj", stem + ".obj")
        if os.path.exists(path):
            objs.append(import_part(s["name"], path, tex_files))
    if opts["wheels_at"]:
        objs += place_wheels(doc, opts, tex_files)
    print("parts: %d shown (%s)" % (len(objs), ", ".join(o.name for o in objs)))
    print("textures available: %d" % len(tex_files))
    return objs


ROLE_COLOURS = {"paint": (0.55, 0.05, 0.05, 1), "window": (0.08, 0.1, 0.12, 1),
                "headlight_glass": (0.75, 0.78, 0.8, 1), "headlight": (0.8, 0.8, 0.8, 1),
                "brakelight_glass": (0.7, 0.1, 0.1, 1), "brakelight": (0.6, 0.02, 0.02, 1)}


def setup_source(opts):
    """The source .blend Blender was started with, in the game's axes and size (the preparation's scale and origin),
    without the objects the preparation left out, with flat colours by the car config's material roles."""
    with open(opts["source"]) as f:
        cfg = json.load(f)
    with open(os.path.join(opts["prep"], "parts.json")) as f:
        info = json.load(f)
    scene = bpy.context.scene
    dropped = set(info["dropped"])
    root = bpy.data.objects.new("carbuild_root", None)
    scene.collection.objects.link(root)
    dx, _, dz = info["origin_shift"]
    root.matrix_world = (Matrix.Translation((dx, 0, dz)) @ Matrix.Scale(info["scale"], 4) @
                         Matrix.Rotation(math.pi / 2, 4, "Z"))
    for o in list(scene.objects):
        if o is root:
            continue
        if o.name in dropped:
            o.hide_render = True
        if o.parent is None:
            o.parent = root
    for m in bpy.data.materials:
        spec = cfg["materials"].get(m.name)
        if spec is None:
            continue
        if spec.get("colour"):
            r, g, b = cfg["palette"][spec["colour"]][:3]
            m.diffuse_color = (r / 255.0, g / 255.0, b / 255.0, 1)
        else:
            m.diffuse_color = ROLE_COLOURS.get(spec["role"], DEFAULT_COLOUR)
    scene.use_nodes = False
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    bpy.context.view_layer.update()
    objs = [o for o in scene.objects if o.type == "MESH" and not o.hide_render and o.visible_get()]
    print("source objects: %d shown" % len(objs))
    return objs


def world_box(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = [o.evaluated_get(dg).matrix_world @ Vector(c) for o in objs for c in o.evaluated_get(dg).bound_box]
    lo = Vector([min(p[a] for p in pts) for a in range(3)])
    hi = Vector([max(p[a] for p in pts) for a in range(3)])
    return lo, hi


def main():
    opts = args()
    objs = setup_source(opts) if opts["source"] else setup_desc(opts)
    if not objs:
        raise SystemExit("no parts to show")
    scene = bpy.context.scene
    if opts["box"]:
        lo, hi = Vector(opts["box"][0:3]), Vector(opts["box"][3:6])
    else:
        lo, hi = world_box(objs)
    centre = (lo + hi) / 2
    print("extent: min %s max %s" % (tuple(round(x, 4) for x in lo), tuple(round(x, 4) for x in hi)))

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("bg")
    scene.world = world
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam_data.sensor_fit = "AUTO"
    cam_data.sensor_width = 36
    cam_data.clip_end = 1000
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    views = {  # directions from the car's centre to the camera
        "front": Vector((1, 0, 0.22)),            # +X is the front
        "side": Vector((0, -1, 0.12)),            # from the car's right (-Y)
        "rear": Vector((-1, 0, 0.22)),
        "three_quarter": Vector((0.75, 0.6, 0.35)),  # front left
    }
    if opts["select"]:  # the car select's camera: low, from the front right
        views = {"select": Vector((0.75, -0.6, 0.06))}
    corners = [Vector((x, y, z)) - centre for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    tan_h = 36 / 2 / cam_data.lens  # 36 mm sensor across, 16:9 frame
    tan_v = tan_h * 9 / 16
    os.makedirs(opts["out"], exist_ok=True)
    modes = [("", False)] + ([("mask_", True)] if opts["masks"] else [])
    sh = scene.display.shading
    for mode, is_mask in modes:
        if is_mask:  # the car black on white: its silhouette
            sh.light, sh.color_type, sh.single_color = "FLAT", "SINGLE", (0, 0, 0)
            sh.show_cavity = False
            world.color = (1, 1, 1)
        else:
            sh.light = "STUDIO"
            sh.color_type = "MATERIAL" if opts["source"] else "TEXTURE"
            sh.show_cavity = True
            world.color = (0.82, 0.84, 0.88)
        sh.show_shadows = False
        for name, direction in views.items():
            direction = direction.normalized()
            cam.location = centre + direction
            look_at(cam, centre)
            bpy.context.view_layer.update()
            rot = cam.matrix_world.to_3x3()
            right, up = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
            # the nearest distance at which every corner of the box is inside the frame, plus a 6% margin
            dist = max(max(c.dot(direction) + abs(c.dot(right)) / tan_h, c.dot(direction) + abs(c.dot(up)) / tan_v)
                       for c in corners) * 1.06
            cam.location = centre + direction * dist
            scene.render.filepath = os.path.join(os.path.abspath(opts["out"]), mode + opts["prefix"] + name + ".png")
            bpy.ops.render.render(write_still=True)
            print("wrote", scene.render.filepath)
    if opts["cabin"]:
        cabin_views(objs, opts, scene, cam, tan_h, tan_v)


def cabin_views(objs, opts, scene, cam, tan_h, tan_v):
    """Close views of the cabin with the windows left out (these renders draw glass opaque): framed on the windows'
    box, from the driver's side (+Y, left-hand drive), the front and the front left, a little from above."""
    glass = [o for o in objs if "_WINDOW" in o.name]
    if not glass:
        raise SystemExit("--cabin: no window parts")
    lo, hi = world_box(glass)
    for o in glass:
        o.hide_render = True
    sh = scene.display.shading  # the normal look, whatever the mask renders before left set
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "MATERIAL" if opts["source"] else "TEXTURE", True
    scene.world.color = (0.82, 0.84, 0.88)
    centre = (lo + hi) / 2
    corners = [Vector((x, y, z)) - centre for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    views = {"cabin_left": Vector((0, 1, 0.25)), "cabin_front": Vector((1, 0, 0.3)),
             "cabin_three_quarter": Vector((0.6, 0.75, 0.35))}
    for name, direction in views.items():
        direction = direction.normalized()
        cam.location = centre + direction
        look_at(cam, centre)
        bpy.context.view_layer.update()
        rot = cam.matrix_world.to_3x3()
        right, up = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
        dist = max(max(c.dot(direction) + abs(c.dot(right)) / tan_h, c.dot(direction) + abs(c.dot(up)) / tan_v)
                   for c in corners) * 1.15
        cam.location = centre + direction * dist
        scene.render.filepath = os.path.join(os.path.abspath(opts["out"]), opts["prefix"] + name + ".png")
        bpy.ops.render.render(write_still=True)
        print("wrote", scene.render.filepath)


main()
