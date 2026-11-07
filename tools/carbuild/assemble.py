"""Assembling a car's game files from the preparation folder (blender_prep.py's output): the car builder's step 3.

    python tools/carbuild/carbin.py assemble tools/carbuild/cars/thar.json [--prep <dir>] [--out <dir>]

Writes GEOMETRY.BIN, TEXTURES.BIN, desc/ (both as description folders) and wheel_report.json into the output folder.
The game's files are only read (the donor car, the GTI, and the shared CARS/TEXTURES.BIN); nothing is installed.

- Each part and level becomes a solid `<CAR>_<PART>_<LOD>`. Its header's undecoded fields, its mesh header and its
  meshes' undecoded bytes come from the donor's solid of the same part and level (all of the Thar's parts and levels
  exist in the GTI) and from a donor mesh with the same shader; the name, hash, box, counts (+0x14 triangles, +0x19
  textures, +0x1A shaders), vertices, indices and mesh fields are ours.
- One mesh per material role and colour, split at 1,000 triangles (no mesh in the game's own cars has more).
- Roles (config `materials`, `part_materials`): a game shader, the mesh flags the GTI uses for it, and the textures:
  the paint (CARSKIN) uses `<CAR>_SKIN1` in every slot, which the game paints over (white, 256 x 256); flat colours use
  `<CAR>_MISC`, a 64 x 64 palette of 8 x 8 cells (config `palette`), the mesh's UVs at its cell's centre; windows use
  the game's own WINDOW_FRONT; lamps use the game's light texture names (HEADLIGHT_LEFT, BRAKELIGHT_GLASS_RIGHT, ...)
  that it swaps at run time for `<CAR>_KIT00_HEADLIGHT_OFF` / `_ON`, `..._GLASS_OFF` / `_ON` (Unlimiter
  CarRenderInfo.h), which our pack provides as flat colours (config `lights`).
- Position markers (chunk 0x13401A, 80 bytes each: name hash, 3 zeros, a 4x4 matrix whose last row is the position):
  the light flares and reverse lights on BASE (on the Thar's own lamps: the centre of the largest lamp facing the
  right way in that part), the exhaust on KIT00_BODY (config `exhaust`), the brake markers on the tyre (the GTI's).
  The GTI's 0x134017..0x134019 chunks (not decoded, sized to its own geometry) are left out: the working add-ons
  (Longnose Cab, Raptor) have none.
- Textures are uncompressed A8R8G8B8 (RAWW blocks), headers from a game A8R8G8B8 texture (opaque) or the GTI's brake
  light glass (with alpha), in a pack named as the GTI's with the file name
  `Global\\Pipeline\\CarTemplateTextures_<CAR>.tpk`.
"""
import fnmatch
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import conventions  # noqa: E402
from chunks import Chunk, bstringhash  # noqa: E402
from geometry import (BBOX_MARGIN, SOLID_1A, VERTEX, GeometryPack, Mesh, Solid, check, finalize,  # noqa: E402
                      read_geometry, solid_header, write_geometry)
from textures import TexturePack, new_texture, read_textures, write_textures  # noqa: E402

MESH_LIMIT = 1000  # triangles per mesh: the most any mesh in the game's own cars has (39,330 meshes)
ROLES = {  # role: (shader, mesh flags as the GTI's meshes with that shader have them)
    "paint": ("CARSKIN", 0x14180),
    "dullplastic": ("DULLPLASTIC", 0x14180),
    "chrome": ("CHROME", 0x14180),
    "window": ("WINDSHIELD", 0x4180),
    "rubber": ("RUBBER", 0x4180),  # 99 game tyre meshes use RUBBER with 0x4180 and one texture in every slot
    "rim": ("MAGSILVER", 0x4180),
    "brakedisc": ("BRAKEDISC", 0x4180),
    "headlight": ("HEADLIGHTREFLECTOR", 0x4180),
    "headlight_glass": ("HEADLIGHTGLASS", 0x14180),
    "brakelight": ("BRAKELIGHT", 0x4180),
    "brakelight_glass": ("BRAKELIGHTGLASS", 0x14180),
}
MARKER_SIZE = 80
WHITE = 0xFFFFFFFF
RAPTOR_TYRE_RADIUS = 0.436  # the tuned Raptor's tyre, 315/70 R17 (spec "Calls made after the builder check")


# ---------------------------------------------------------------- inputs

def read_level(folder, entry):
    """Triangles of one part level: [((p0, p1, p2), (n0, n1, n2), material index)]."""
    t = entry["triangles"]
    with open(os.path.join(folder, entry["file"]), "rb") as f:
        data = f.read()
    n = t * 3
    pos = struct.unpack_from("<%df" % (n * 3), data, 0)
    nor = struct.unpack_from("<%df" % (n * 3), data, n * 12)
    mat = struct.unpack_from("<%dH" % t, data, n * 32)
    out = []
    for k in range(t):
        ps = tuple(tuple(pos[(3 * k + c) * 3:(3 * k + c) * 3 + 3]) for c in range(3))
        ns = tuple(tuple(nor[(3 * k + c) * 3:(3 * k + c) * 3 + 3]) for c in range(3))
        out.append((ps, ns, mat[k]))
    return out


def role_of(part, material, cfg):
    """(role, palette colour or None) of a material in a part."""
    for rule in cfg.get("part_materials", []):
        if any(fnmatch.fnmatchcase(part, p) for p in rule["parts"]):
            m = rule["materials"].get(material) or rule["materials"].get("*")
            if m:
                return m["role"], m.get("colour")
    m = cfg["materials"].get(material)
    if m is None:
        raise ValueError("%s: material %r has no role in the config" % (part, material))
    return m["role"], m.get("colour")


def side_of(part):
    return "RIGHT" if "_RIGHT_" in part else "LEFT"


# ---------------------------------------------------------------- textures

PALETTE_CELLS = 8  # 8 x 8 cells of 8 x 8 pixels: 64 x 64


def palette_cells(cfg):
    names = sorted(cfg["palette"])
    if len(names) > PALETTE_CELLS * PALETTE_CELLS:
        raise ValueError("too many palette colours")
    return {n: k for k, n in enumerate(names)}


def palette_uv(cell):
    row, col = divmod(cell, PALETTE_CELLS)
    return ((col + 0.5) / PALETTE_CELLS, (row + 0.5) / PALETTE_CELLS)


def palette_pixels(cfg, cells):
    size = PALETTE_CELLS * 8
    px = bytearray(size * size * 4)
    for name, cell in cells.items():
        r, g, b = cfg["palette"][name][:3]
        row, col = divmod(cell, PALETTE_CELLS)
        for y in range(row * 8, row * 8 + 8):
            for x in range(col * 8, col * 8 + 8):
                o = (y * size + x) * 4
                px[o:o + 4] = bytes((b, g, r, 255))
    return bytes(px)


def flat(width, height, rgba):
    r, g, b, a = rgba
    return bytes((b, g, r, a)) * (width * height)


def light_names(car):
    return {"headlight_off": car + "_KIT00_HEADLIGHT_OFF", "headlight_on": car + "_KIT00_HEADLIGHT_ON",
            "headlight_glass_off": car + "_KIT00_HEADLIGHT_GLASS_OFF",
            "headlight_glass_on": car + "_KIT00_HEADLIGHT_GLASS_ON",
            "brakelight_off": car + "_KIT00_BRAKELIGHT_OFF", "brakelight_on": car + "_KIT00_BRAKELIGHT_ON",
            "brakelight_glass_off": car + "_KIT00_BRAKELIGHT_GLASS_OFF",
            "brakelight_glass_on": car + "_KIT00_BRAKELIGHT_GLASS_ON"}


def build_textures(cfg, donor_pack, shared_pack):
    car = cfg["car"]
    opaque = [t for t in shared_pack.textures if t.fmt == "A8R8G8B8"][0].header
    glass = [t for t in donor_pack.textures if t.name.startswith(cfg["donor"] + "_KIT00_BRAKELIGHT_GL")][0].header
    cells = palette_cells(cfg)
    items = [(car + "_SKIN1", 256, 256, flat(256, 256, (255, 255, 255, 255)), opaque),
             (car + "_MISC", 64, 64, palette_pixels(cfg, cells), opaque)]
    for key, name in sorted(light_names(car).items()):
        rgba = cfg["lights"][key]
        items.append((name, 16, 16, flat(16, 16, rgba), glass if rgba[3] < 255 else opaque))
    textures, placement = [], 0
    for name, w, h, px, donor in items:
        textures.append(new_texture(name, w, h, px, donor, placement))
        placement += len(px)
    pack = TexturePack(name=donor_pack.name, filename="Global\\Pipeline\\CarTemplateTextures_%s.tpk" % car,
                       textures=textures, raw_parts={"info": donor_pack.raw_parts["info"], "pads": []})
    return pack, cells


def role_slots(role, part, car):
    """The five texture slot names of a role in a part, as the GTI's meshes have them."""
    s = side_of(part)
    if role == "paint":
        return [car + "_SKIN1"] * 5
    if role == "window":
        return ["WINDOW_FRONT"] * 5
    if role == "headlight":
        return ["HEADLIGHT_" + s] * 5
    if role == "brakelight":
        return ["BRAKELIGHT_" + s] * 5
    if role == "headlight_glass":
        return ["HEADLIGHT_GLASS_" + s] * 4 + [car + "_KIT00_HEADLIGHT_GLASS_OFF"]
    if role == "brakelight_glass":
        return ["BRAKELIGHT_GLASS_" + s] * 4 + [car + "_KIT00_BRAKELIGHT_GLASS_OFF"]
    return [car + "_MISC"] * 5


# ---------------------------------------------------------------- markers

def _area(ps):
    u = [ps[1][k] - ps[0][k] for k in range(3)]
    v = [ps[2][k] - ps[0][k] for k in range(3)]
    w = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return math.sqrt(sum(x * x for x in w)) / 2


def lamp_centre(tris, facing, link=0.04):
    """The area-weighted centre of the largest lamp in a part: triangles facing `facing` (+1 front, -1 rear: the
    normal's x), grouped by corner proximity (`link` m), the group with the most area."""
    sel = [t for t in tris if sum(n[0] for n in t[1]) / 3 * facing > 0.3]
    if not sel:
        sel = tris
    parent = list(range(len(sel)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cents = [[sum(p[k] for p in t[0]) / 3 for k in range(3)] for t in sel]
    for i in range(len(sel)):
        for j in range(i + 1, len(sel)):
            if any(math.dist(p, q) < link for p in sel[i][0] for q in sel[j][0]):
                parent[root(i)] = root(j)
    groups = {}
    for i, t in enumerate(sel):
        groups.setdefault(root(i), []).append(i)
    best = max(groups.values(), key=lambda g: sum(_area(sel[i][0]) for i in g))
    area = sum(_area(sel[i][0]) for i in best)
    return [sum(_area(sel[i][0]) * cents[i][k] for i in best) / area for k in range(3)]


def marker_bytes(name, position, template):
    rec = bytearray(template)
    struct.pack_into("<I", rec, 0, bstringhash(name))
    struct.pack_into("<3f", rec, 16 + 48, *position)
    return bytes(rec)


def donor_markers(solid):
    out = {}
    for c in solid.other:
        if c.id == SOLID_1A:
            for k in range(0, len(c.data), MARKER_SIZE):
                rec = c.data[k:k + MARKER_SIZE]
                out.setdefault(struct.unpack_from("<I", rec, 0)[0], rec)
    return out


# ---------------------------------------------------------------- solids

def build_solid(car, part, lod, tris, materials, cfg, donor, cells, donor_meshes):
    name = "%s_%s_%s" % (car, part, lod)
    dname = "%s_%s_%s" % (cfg["donor"], part, lod)
    if dname not in donor:
        raise ValueError("the donor has no %s" % dname)
    d = donor[dname]
    groups = {}
    for t in tris:
        role, colour = role_of(part, materials[t[2]], cfg)
        if role not in ROLES:
            raise ValueError("%s: unknown role %r" % (part, role))
        groups.setdefault((role, colour), []).append(t)
    textures, shaders, entries, names, vbuf, ibuf = [], [], [], [], bytearray(), []
    vbase = 0
    for (role, colour), group in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        shader, flags = ROLES[role]
        sh = bstringhash(shader)
        if sh not in shaders:
            shaders.append(sh)
        slots = []
        for tname in role_slots(role, part, car):
            h = bstringhash(tname)
            if h not in textures:
                textures.append(h)
            slots.append(textures.index(h))
        if role in ("paint", "window") or role.startswith(("headlight", "brakelight")):
            uv = (0.5, 0.5)
        else:
            if colour not in cells:
                raise ValueError("%s: role %s needs a palette colour (got %r)" % (part, role, colour))
            uv = palette_uv(cells[colour])
        for start in range(0, len(group), MESH_LIMIT):
            chunk = group[start:start + MESH_LIMIT]
            index, verts, idx = {}, [], []
            for ps, ns, _ in chunk:
                for p, n in zip(ps, ns):
                    key = (p, n)
                    if key not in index:
                        index[key] = len(verts)
                        verts.append(key)
                    idx.append(vbase + index[key])
            if vbase + len(verts) > 65536:
                raise ValueError("%s: more than 65,536 vertices" % name)
            for p, n in verts:
                vbuf += VERTEX.pack(*p, *n, struct.pack("<I", WHITE), *uv)
            lo = [min(p[k] for p, _ in verts) - BBOX_MARGIN for k in range(3)]
            hi = [max(p[k] for p, _ in verts) + BBOX_MARGIN for k in range(3)]
            raw = donor_meshes.get(sh, bytes(104))
            m = Mesh(texture_index=slots[0], shader_index=shaders.index(sh), vertex_offset=vbase,
                     vertex_count=len(verts), index_offset=len(ibuf), index_count=len(idx), stride=36, flags=flags,
                     raw=raw, texture_slots=tuple(slots), triangle_count=len(chunk))
            entries.append(m.to_raw(bbox=lo + hi))
            names.append(role.upper() if colour is None else "%s_%s" % (role.upper(), colour.upper()))
            ibuf += idx
            vbase += len(verts)
    header = bytearray(solid_header(d.header, name, bstringhash(name), (0,) * 6))
    struct.pack_into("<I", header, 0x14, len(tris))
    header[0x19], header[0x1A] = len(textures), len(shaders)
    # +0x98 x +0x9C = the triangle count on every game solid (an area-like figure and a density); the Chiron and
    # Raptor add-ons write (1.0, triangles), which the game loads: ours, not the donor's
    struct.pack_into("<2f", header, 0x98, 1.0, float(len(tris)))
    s = Solid(name=name, name_hash=bstringhash(name), header=bytes(header), textures=textures, shaders=shaders,
              mesh_header=d.mesh_header, mesh_entries=entries, vertices=bytes(vbuf),
              indices=struct.pack("<%dH" % len(ibuf), *ibuf), other=[], mesh_names=names)
    finalize(s)
    return s


COVER_SHADER = "PLAINNOTHING"
COVER_INSET = 0.002  # m inside the tyre's inner sidewall plane
COVER_TEXTURE = 0xE38806E3  # global (GLOBALB), the round dark mask every game tyre's inner face carries


def _cover_mesh(solid):
    for m in solid.meshes():
        if solid.shaders[m.shader_index] == bstringhash(COVER_SHADER) and m.triangle_count == 2:
            return m
    return None


def _tyre_radius(solid, skip=None):
    return max(max(abs(p[0]), abs(p[2])) for m in solid.meshes() if m is not skip for p in solid.positions(m))


def add_tyre_cover(s, donor_solid):
    """Closes a tyre solid's inner face as the game's tyres do: the donor level's 2-triangle PLAINNOTHING square
    (texture 0xE38806E3, its own flags, normals, colours and UVs), centred on the axle 2 mm inside the tyre's inner
    sidewall plane (not in it: same-depth surfaces flicker; not beyond it: the box width sets the tyre's scale)."""
    dm = _cover_mesh(donor_solid)
    if dm is None:
        raise ValueError("%s has no inner cover" % donor_solid.name)
    # half width: the largest square whose corners stay inside the tyre (it still holds the alloy's disc), so it hides
    # nothing beside the tyre whether or not the global texture masks the corners (the game's own squares are a little
    # larger: 0.84 of the radius at the GTI's A, the full radius at C)
    half = _tyre_radius(s) / math.sqrt(2)
    y = max(p[1] for m in s.meshes() for p in s.positions(m)) - COVER_INSET
    dv = donor_solid.vertices[dm.vertex_offset * VERTEX.size:(dm.vertex_offset + dm.vertex_count) * VERTEX.size]
    vbuf = bytearray()
    for k in range(dm.vertex_count):
        px, py, pz, nx, ny, nz, col, u, v = VERTEX.unpack_from(dv, k * VERTEX.size)
        vbuf += VERTEX.pack(math.copysign(half, px), y, math.copysign(half, pz), nx, ny, nz, col, u, v)
    tris = donor_solid.triangles(dm)
    sh = bstringhash(COVER_SHADER)
    textures, shaders = list(s.textures), list(s.shaders)
    if sh not in shaders:
        shaders.append(sh)
    if COVER_TEXTURE not in textures:
        textures.append(COVER_TEXTURE)
    vbase = len(s.vertices) // VERTEX.size
    old_idx = list(struct.unpack("<%dH" % (len(s.indices) // 2), s.indices))
    count = sum(m.index_count for m in s.meshes())
    old_idx = old_idx[:count]  # finalize pads the indices to 4 bytes again
    idx = [vbase + i for t in tris for i in t]
    slot = textures.index(COVER_TEXTURE)
    m = Mesh(texture_index=slot, shader_index=shaders.index(sh), vertex_offset=vbase, vertex_count=dm.vertex_count,
             index_offset=count, index_count=len(idx), stride=VERTEX.size, flags=dm.flags, raw=dm.raw,
             texture_slots=(slot,) * 5, triangle_count=len(tris))
    lo = [-half - BBOX_MARGIN, y - BBOX_MARGIN, -half - BBOX_MARGIN]
    hi = [half + BBOX_MARGIN, y + BBOX_MARGIN, half + BBOX_MARGIN]
    header = bytearray(s.header)
    tri_total = struct.unpack_from("<I", header, 0x14)[0] + len(tris)
    struct.pack_into("<I", header, 0x14, tri_total)
    header[0x19], header[0x1A] = len(textures), len(shaders)
    struct.pack_into("<2f", header, 0x98, 1.0, float(tri_total))
    s.header, s.textures, s.shaders = bytes(header), textures, shaders
    s.mesh_entries = list(s.mesh_entries) + [m.to_raw(bbox=lo + hi)]
    s.mesh_names = list(s.mesh_names) + ["TYRE_COVER"]
    s.vertices = bytes(s.vertices) + bytes(vbuf)
    s.indices = struct.pack("<%dH" % (len(old_idx) + len(idx)), *(old_idx + idx))
    finalize(s)
    return s


def add_markers(solids, cfg, donor, levels_a):
    """Position markers on BASE (lights), KIT00_BODY (exhaust) and the tyre (brakes), on every level, as the GTI
    carries them on every level of those parts."""
    car, dn = cfg["car"], cfg["donor"]
    base_marks = donor_markers(donor["%s_BASE_A" % dn])
    template = next(iter(base_marks.values()))
    marks = {"BASE": [], "KIT00_BODY": [], "KIT00_FRONT_TIRE": []}
    for side in ("LEFT", "RIGHT"):
        marks["BASE"].append(("%s_HEADLIGHT" % side, lamp_centre(levels_a["KIT00_%s_HEADLIGHT_GLASS" % side], +1)))
        marks["BASE"].append(("%s_BRAKELIGHT" % side, lamp_centre(levels_a["KIT00_%s_BRAKELIGHT_GLASS" % side], -1)))
        marks["BASE"].append(("%s_REVERSE" % side, lamp_centre(levels_a["KIT00_%s_BRAKELIGHT" % side], -1)))
    body = [p for t in levels_a["KIT00_BODY"] for p in t[0]]
    ex = cfg["exhaust"]
    # x from the body's rear, z above the body's lowest point (the origin's height before ride_height_cm moved it)
    marks["KIT00_BODY"].append((ex["name"], [min(p[0] for p in body) + ex["x_from_rear"], ex["y"],
                                             min(p[2] for p in body) + ex["z"]]))
    tyre_marks = donor_markers(donor["%s_KIT00_FRONT_TIRE_A" % dn])
    out = {}
    for s in solids:
        part = s.name[len(car) + 1:-2]
        if part in ("BASE", "KIT00_BODY"):
            data = b"".join(marker_bytes(n, p, base_marks.get(bstringhash(n), template)) for n, p in marks[part])
        elif part == "KIT00_FRONT_TIRE":
            data = b"".join(tyre_marks.values())
        else:
            continue
        s.other = [Chunk(SOLID_1A, data)]
        out[s.name] = marks.get(part)
    return marks


# ---------------------------------------------------------------- wheel report

def wheel_report(wheel, levels_a, materials_tyre, cfg):
    r = wheel["radius"]
    w = wheel["width"]
    W = r + conventions.BOX_MARGIN  # draws the model at its own size (the game scales by W / box half length)
    skid = w + 2 * conventions.BOX_MARGIN  # likewise across (TireSkidWidth / box width)
    c = wheel["centres"]
    # |Y| is the right tyre's outer face; the left one lands 2 margins further in (speed.exe 0x74F221), so split it
    order = (("FL", 1), ("FR", -1), ("RR", -1), ("RL", 1))
    offsets = [{"X": c[k][0], "Y": sign * (wheel["outer_y"][k] + conventions.BOX_MARGIN), "Z": 0.0, "W": W}
               for k, sign in order]
    body = [p for t in levels_a["KIT00_BODY"] for p in t[0]]
    zc = sum(c[k][2] for k in c) / 4
    gaps = []
    for o in offsets:
        side = [abs(p[1]) for p in body if (p[1] > 0) == (o["Y"] > 0) and abs(p[0] - o["X"]) < W and p[2] < zc + W]
        gaps.append((max(side) if side else 0.0) - abs(o["Y"]))
    rim = [p for t in levels_a[wheel["tyre_part"]] if role_of(wheel["tyre_part"], materials_tyre[t[2]], cfg)[0] == "rim"
           for p in t[0]]
    rim_r = max(math.hypot(p[0], p[2]) for p in rim) if rim else r * 0.65
    section = int(round((w * 1000 - 5) / 10.0)) * 10 + 5
    rim_in = int(round(2 * rim_r / 0.0254 - 1))  # the rim's nominal size: the visible lip is about an inch larger
    aspect = int(round((r - rim_in * 0.0254 / 2) / (section / 1000.0) * 100 / 5.0)) * 5
    phys_r = rim_in * 0.0254 / 2 + section * aspect / 100000.0
    return {
        "TireOffsets": offsets, "TireSkidWidth": skid, "W": W, "model_radius": r, "model_width": w,
        "front_axle_x": c["FL"][0], "rear_axle_x": c["RL"][0], "wheelbase": c["FL"][0] - c["RL"][0],
        "track_outer_faces": 2 * wheel["outer_y"]["FL"], "wheel_centre_z": zc,
        "ride_height_cm_for_wheel_rule": round(100 * (W - zc), 1), "ride_height_cm": cfg.get("ride_height_cm"),
        "body_min_z": min(p[2] for p in body),
        "body_side_minus_Y": gaps, "rim_radius_visible": rim_r,
        "physics_tyre": {"section_width_mm": section, "aspect_ratio": aspect, "rim_in": rim_in, "radius": phys_r},
        "final_gear_ratio_vs_raptor": phys_r / RAPTOR_TYRE_RADIUS,
        "notes": "TireOffsets order as the game's: front left, front right, rear right, rear left. W and "
                 "TireSkidWidth draw the tyre model at its own size; Y puts the outer faces 1 cm either side of "
                 "the measured face. ride_height_cm_for_wheel_rule: chassis RIDE_HEIGHT that puts the wheel centre "
                 "at z = W - RIDE_HEIGHT/100 (conventions.py; read from the models, not the game's code).",
    }


# ---------------------------------------------------------------- borrowed interior and driver

def borrow_interior(cfg, solids, tpack, game_cars):
    """The interior and driver of the config's `interior.donor` (a game car), fitted into the new car's glasshouse
    (interior.fit) and renamed; its own interior texture copied into `tpack` as <CAR>_INTERIOR. Returns (solids,
    report)."""
    import interior
    car, donor = cfg["car"], cfg["interior"]["donor"]
    with open(os.path.join(game_cars, donor, "GEOMETRY.BIN"), "rb") as f:
        dpack = read_geometry(f.read())
    reason = interior.ineligible(game_cars, donor, dpack)
    if reason:
        raise ValueError("%s's interior cannot be borrowed: %s" % (donor, reason))
    target = GeometryPack(info=None, solids=solids, extra=[])
    gh = interior.glasshouse(target, car)
    t = interior.fit(dpack, donor, gh, interior.anchors(target, car))
    if t["clamp_depth"] > interior.MAX_CLAMP:
        raise ValueError("%s's cabin does not fit the %s: %s" % (donor, car, t))
    parts = interior.transplant(dpack, donor, car, t)
    own = interior.donor_textures(game_cars, donor)
    placement = sum(len(x.data) for x in tpack.textures if x.data is not None)
    copied = []
    for dh, (name, nh) in sorted(interior.texture_renames(donor, car).items(), key=lambda kv: kv[1][0]):
        if dh in own and any(nh in s.textures for s in parts):
            tex = interior.renamed_texture(own[dh], name, placement)
            placement += len(tex.data)
            tpack.textures.append(tex)
            copied.append({"from": own[dh].name, "to": name, "format": tex.fmt, "size": [tex.width, tex.height],
                           "mipmaps": tex.mipmaps})
    report = {"donor": donor, "glasshouse": gh, "transform": t, "solids": [s.name for s in parts],
              "textures_copied": copied,
              "textures_referenced": sorted({"0x%08X" % h for s in parts for h in s.textures}),
              "notes": "Fitted by interior.fit: donor sill onto the car's, windscreen base onto its, one scale; "
                       "glasshouse = rear window x, -|y|, floor panel top, windscreen base x, |y|, roof."}
    return parts, report


# ---------------------------------------------------------------- main

def run(cfg, prep, out, game_cars):
    with open(os.path.join(prep, "parts.json"), encoding="utf-8") as f:
        info = json.load(f)
    with open(os.path.join(prep, "wheel.json"), encoding="utf-8") as f:
        wheel = json.load(f)
    car, dn = cfg["car"], cfg["donor"]
    with open(os.path.join(game_cars, dn, "GEOMETRY.BIN"), "rb") as f:
        dpack = read_geometry(f.read())
    with open(os.path.join(game_cars, dn, "TEXTURES.BIN"), "rb") as f:
        dtex = read_textures(f.read())
    with open(os.path.join(game_cars, "TEXTURES.BIN"), "rb") as f:
        shared = read_textures(f.read())
    donor = {s.name: s for s in dpack.solids}
    donor_meshes = {}
    for s in dpack.solids:
        for m in s.meshes():
            donor_meshes.setdefault(s.shaders[m.shader_index], m.raw)
    for role, (shader, _) in ROLES.items():
        if bstringhash(shader) not in donor_meshes:
            raise ValueError("the donor has no mesh with shader %s" % shader)
    tpack, cells = build_textures(cfg, dtex, shared)
    solids, levels_a = [], {}
    for part in sorted(info["parts"]):
        p = info["parts"][part]
        for lod in sorted(p["levels"]):
            tris = read_level(prep, p["levels"][lod])
            if lod == "A":
                levels_a[part] = tris
            solids.append(build_solid(car, part, lod, tris, p["materials"], cfg, donor, cells, donor_meshes))
            if part == wheel["tyre_part"]:
                # the donor's same level, else its farthest level that has a cover (the GTI's D has none)
                covered = sorted(n[-1] for n, d in donor.items() if n.startswith("%s_%s_" % (dn, part)) and
                                 _cover_mesh(d) is not None)
                add_tyre_cover(solids[-1], donor["%s_%s_%s" % (dn, part, lod if lod in covered else covered[-1])])
    marks = add_markers(solids, cfg, donor, levels_a)
    interior_report = None
    if cfg.get("interior"):
        borrowed, interior_report = borrow_interior(cfg, solids, tpack, game_cars)
        solids += borrowed
    problems = [x for s in solids for x in check(s)]
    if problems:
        raise ValueError("inconsistent solids: %s" % problems[:5])
    gpack = GeometryPack(info=dpack.info, solids=solids, extra=[])
    os.makedirs(out, exist_ok=True)
    geo = write_geometry(gpack)
    tex = write_textures(tpack, compressed=False)
    with open(os.path.join(out, "GEOMETRY.BIN"), "wb") as f:
        f.write(geo)
    with open(os.path.join(out, "TEXTURES.BIN"), "wb") as f:
        f.write(tex)
    report = wheel_report(wheel, levels_a, info["parts"][wheel["tyre_part"]]["materials"], cfg)
    report["markers"] = {k: [[n, [round(c, 4) for c in pos]] for n, pos in v] for k, v in marks.items()}
    with open(os.path.join(out, "wheel_report.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)
    ipath = os.path.join(out, "interior_report.json")
    if interior_report is not None:
        with open(ipath, "w", encoding="utf-8", newline="\n") as f:
            json.dump(interior_report, f, indent=1)
    elif os.path.exists(ipath):
        os.remove(ipath)
    return gpack, tpack, report
