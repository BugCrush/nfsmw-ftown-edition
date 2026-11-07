"""A real Rockport section moved to the F-Town place: the loader's known-good test data (Part 2, Task 5).

    python tools/world/relocate.py "<game dir>" C9 .superpowers/world/ftown-reloc.bun

The output is game data (EA's geometry and textures): write it only under .superpowers/world/ (git-ignored).

What it does: the section's scenery section, every solid its instances use (its own and the library sections', found
by name hash), every texture those solids name (from any section's world texture pack), and its collision pack, are
put in one file in the slab's layout (tools/world/slab.py assemble), renumbered to the slab's numbers (scenery and pack
2101) and moved by one vector so the section's streaming centre lands on render (2000, 11500) and its road height
there on z = 100. Instances at the origin with an identity matrix carry world-space solids (notes Task 3): those
solids' vertices and boxes move; other instances move by their matrix (their solids are model-space, unchanged).
Collision instances move by their translation (their rotation is identity in all of Rockport, notes "Part 2").
Every solid and texture is renamed (FTR_<name>, FTR_<hash>) so the file registers no name Rockport has loaded at the
same time (the car is still in Rockport when it is loaded). Every instance points at preculler record 0 (no hidden
bits in any section); the override hookups (0x34106) are left out (they name override records of section C9).
"""
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import bstringhash, write_chunks  # noqa: E402
from world import bun, collision, collision_write, heightcheck, scenery, slab, solids, texpack  # noqa: E402
from world.scenery import Info, Instance, Scenery, transform  # noqa: E402

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


@dataclass
class Reloc:
    chunks: list
    shift: tuple
    centre: tuple
    road_height: float
    original_pack: object
    original_ref: object
    original_placed: list
    textures_not_found: set
    rockport_solid_hashes: set = field(default_factory=set)
    rockport_texture_hashes: set = field(default_factory=set)
    spawn: tuple = None


def _f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def placed_vertices(data, library=None):
    """Every vertex of every instance's highest-detail solid, placed by its matrix, in instance and solid order."""
    out = []
    for sc in data.sceneries:
        for inst in sc.instances:
            h = sc.infos[inst.info_index].solid_hashes[0]
            so = data.solids.get(h) or (library or {}).get(h)
            if so is None:
                continue
            for k in range(len(so.meshes)):
                out.extend(transform(inst.matrix, p) for p in so.positions(k))
    return out


def _shift_solid(ws, s):
    """A WorldSolid with every vertex position, mesh box and header box moved by s (render)."""
    meshes = []
    for m in ws.meshes:
        v = bytearray(m.vertices)
        for i in range(m.vertex_count):
            o = i * m.stride
            x, y, z = struct.unpack_from("<3f", v, o)
            struct.pack_into("<3f", v, o, x + s[0], y + s[1], z + s[2])
        e = bytearray(m.entry)
        box = struct.unpack_from("<6f", e, 0)
        struct.pack_into("<6f", e, 0, *(box[a] + s[a % 3] for a in range(6)))
        meshes.append(solids.WorldMesh(bytes(e), bytes(v), m.stride, m.indices, m.name))
    h = bytearray(ws.header)
    for off in (0x20, 0x30):
        p = struct.unpack_from("<3f", h, off)
        struct.pack_into("<3f", h, off, p[0] + s[0], p[1] + s[1], p[2] + s[2])
    return solids.WorldSolid(ws.name, bytes(h), ws.textures, ws.shaders, ws.extras, ws.mesh_header, meshes,
                             ws.name_tail)


def _index_world(stream, sections, want_solids, want_textures):
    """{hash: WorldSolid} and {hash: WorldTexture} for the wanted hashes, searching library sections (X, V) first,
    then every section; plus every solid and texture hash Rockport has (for the collision test)."""
    found_s, found_t = {}, {}
    all_s, all_t = set(), set()
    order = sorted(sections, key=lambda s: (s.letter not in "XV", s.name))
    for s in order:
        chunks = bun.read_range(stream, s.offset, s.size)
        for c, pos in scenery.with_positions(chunks, 0):
            if c.id == scenery.SOLID_LIST:
                lst = solids.read_list(c, pos)
                for ws in lst.solids:
                    all_s.add(ws.name_hash)
                    if ws.name_hash in want_solids and ws.name_hash not in found_s:
                        found_s[ws.name_hash] = ws
            elif c.id == texpack.PACK:
                for t in texpack.read_pack(c, pos).textures:
                    all_t.add(t.name_hash)
                    if t.name_hash in want_textures and t.name_hash not in found_t:
                        found_t[t.name_hash] = t
    return found_s, found_t, all_s, all_t


def relocate(game_dir, name="C9", target=None):
    target = target or (slab.CENTRE[0], slab.CENTRE[1], slab.TOP)
    l2ra = os.path.join(game_dir, "TRACKS", "L2RA.BUN")
    stream = os.path.join(game_dir, "TRACKS", "STREAML2RA.BUN")
    sections = bun.sections(l2ra)
    sec = {s.name: s for s in sections}[name]
    chunks = bun.read_range(stream, sec.offset, sec.size)
    d = scenery.read_section(chunks)
    pos = scenery.with_positions(chunks, 0)
    cdata, cpos = [(c.data, p) for c, p in pos if c.id == collision.COLLISION_PACK][0]
    opack = collision_write.read_pack(cdata, cpos)
    oref = collision.read_pack(cdata, cpos)
    cx, cy = sec.centre
    # the road point nearest the centre: the centre of the nearest asphalt face (C9's streaming centre itself has no
    # face under it); its height is the section's road height
    best = None
    for t in collision.triangles(oref):
        if t[3] != collision_write.ASPHALT:
            continue
        c = collision.to_render(tuple(sum(p[a] for p in t[:3]) / 3.0 for a in range(3)))
        dd = (c[0] - cx) ** 2 + (c[1] - cy) ** 2
        if best is None or dd < best[0]:
            best = (dd, c)
    road = best[1]
    pr = collision.to_physics(road)
    h = heightcheck.height_at(opack, pr[0], pr[2], road[2] + 1.0)
    s = (_f32(target[0] - cx), _f32(target[1] - cy), _f32(target[2] - h))
    ps = collision.to_physics(s)
    if len(d.sceneries) != 1:
        raise ValueError("section %s holds %d scenery sections; this tool moves one" % (name, len(d.sceneries)))
    sc = d.sceneries[0]
    # which solids are world-space (used by origin instances) and which model-space
    use = {}
    for inst in sc.instances:
        kind = "origin" if inst.matrix == IDENTITY else "placed"
        for hh in sc.infos[inst.info_index].solid_hashes:
            if hh not in scenery.NO_MODEL:
                use.setdefault(hh, set()).add(kind)
    both = [hh for hh, k in use.items() if len(k) > 1]
    if both:
        raise ValueError("%d solids are used both at the origin and placed by a matrix" % len(both))
    own = {}
    for c, p in pos:
        if c.id == scenery.SOLID_LIST:
            for ws in solids.read_list(c, p).solids:
                own[ws.name_hash] = ws
    want = set(use)
    tex_want = set()
    found_s, _ft, all_s, all_t = _index_world(stream, sections, want - set(own), set())
    lib = dict(found_s)
    lib.update(own)
    # a few solid references name solids that are nowhere in the region file (491 of 287,376 in Rockport, notes
    # Task 3): they stay as they are (unresolved there as here) and are reported
    missing_solids = want - set(lib)
    want = want - missing_solids
    for hh in want:
        tex_want.update(lib[hh].textures)
    _fs, found_t, _a, _b = _index_world(stream, sections, set(), tex_want)
    # the original's placed vertices, for the test (library solids as scenery.Solid through the reader)
    orig_placed = _placed_from_world(sc, lib)
    # rename and move
    sol_name = {hh: "FTR_" + lib[hh].name for hh in want}
    sol_hash = {hh: bstringhash(n) for hh, n in sol_name.items()}
    tex_hash = {t: bstringhash("FTR_%08X" % t) for t in found_t}
    new_solids = []
    for hh in sorted(want):
        ws = lib[hh]
        if "origin" in use[hh]:
            ws = _shift_solid(ws, s)
        ws = solids.WorldSolid(sol_name[hh], ws.header, [tex_hash.get(t, t) for t in ws.textures], ws.shaders,
                               ws.extras, ws.mesh_header, ws.meshes, ws.name_tail)
        new_solids.append(ws)
    by_new = {ws.name_hash: ws for ws in new_solids}
    infos = []
    origin_infos = {inst.info_index for inst in sc.instances if inst.matrix == IDENTITY}
    for k, info in enumerate(sc.infos):
        hs = tuple(sol_hash.get(x, x) if x not in scenery.NO_MODEL else x for x in info.solid_hashes)
        radius = info.radius
        if k in origin_infos and hs[0] in by_new:
            ws = by_new[hs[0]]
            far = 0.0
            for m in ws.meshes:
                for i in range(m.vertex_count):
                    x, y, z = struct.unpack_from("<3f", m.vertices, i * m.stride)
                    far = max(far, (x * x + y * y + z * z) ** 0.5)
            radius = _f32(far)
        infos.append(Info(info.name, hs, radius, info.checksum, info.hierarchy))
    insts = []
    for inst in sc.instances:
        m = inst.matrix
        if m != IDENTITY:
            m = m[:3] + ((_f32(m[3][0] + s[0]), _f32(m[3][1] + s[1]), _f32(m[3][2] + s[2]), 1.0),)
        box = tuple(_f32(inst.bbox[a] + s[a % 3]) for a in range(6))
        insts.append(Instance(inst.info_index, m, box, inst.exclude_flags, 0, inst.lighting))
    from world import scenery_write
    nodes = scenery_write.parse_tree(sc.tree)
    nodes = [(tuple(_f32(b[a] + s[a % 3]) for a in range(6)), kids) for b, kids in nodes]
    header = bytearray(sc.header)
    struct.pack_into("<i", header, 0x0C, slab.SECTION_NUMBER)
    other = {scenery.PRECULLER: sc.other.get(scenery.PRECULLER, bytes(0x80))}
    new_sc = Scenery(slab.SECTION_NUMBER, bytes(header), infos, insts, scenery_write.tree_bytes(nodes), other)
    # collision
    new_insts = []
    for inst in opack.instances:
        r = bytearray(inst.raw)
        t = struct.unpack_from("<3f", r, 0x30)
        struct.pack_into("<3f", r, 0x30, _f32(t[0] - ps[0]), _f32(t[1] - ps[1]), _f32(t[2] - ps[2]))
        new_insts.append(collision_write.Instance(bytes(r)))
    npack = collision_write.Pack(slab.PACK_NUMBER, str(slab.PACK_NUMBER), opack.articles, new_insts, 0)
    # textures
    texs = []
    for t, wt in sorted(found_t.items()):
        info = bytearray(wt.info)
        nm = ("FTR_%08X" % t).encode("ascii")
        info[0x0C:0x24] = nm + bytes(24 - len(nm))
        struct.pack_into("<I", info, 0x24, tex_hash[t])
        texs.append(texpack.WorldTexture(bytes(info), wt.comp, wt.data))
    tpack = texpack.new_pack("FTOWNRELOC", "FTown\\FTownReloc.tpk", texs)
    slist = solids.new_list(new_solids, "FTown_Reloc_%s.bin" % name, "U1")
    out = slab.assemble(tpack, slist, new_sc, npack)
    r = Reloc(out, s, (cx, cy), h, opack, oref, orig_placed, tex_want - set(found_t), all_s, all_t)
    r.solids_not_found = missing_solids
    sp = (road[0] + s[0], road[1] + s[1])
    r.spawn = (sp[0], sp[1], _road_at(npack, (sp[0], sp[1], h + s[2])) + 1.0, 0.0)
    r.road_point = road
    return r


def _placed_from_world(sc, lib):
    """Placed vertices of the original from WorldSolids (same order as placed_vertices over the reader's model)."""
    out = []
    for inst in sc.instances:
        hh = sc.infos[inst.info_index].solid_hashes[0]
        ws = lib.get(hh)
        if ws is None:
            continue
        for m in ws.meshes:
            for i in range(m.vertex_count):
                out.append(transform(inst.matrix, struct.unpack_from("<3f", m.vertices, i * m.stride)))
    return out


def _road_at(pack, point):
    """The face height 1 m above `point` (render) finds, as the game's query does."""
    p = collision.to_physics((point[0], point[1], point[2] + 1.0))
    h = heightcheck.height_at(pack, p[0], p[2], p[1])
    if h is None:
        raise ValueError("no face under the spawn point")
    return h


def spawn(r):
    """(render x, y, z, heading): 1 m above the relocated road point nearest the section's centre, heading 0 (+x)."""
    return r.spawn


def write(r, out_path):
    data = write_chunks(r.chunks)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    game, name, out = argv
    r = relocate(game, name)
    n = write(r, out)
    print("wrote %s (%d bytes): shift render (%.3f, %.3f, %.3f); road height %.3f; spawn render (%.2f, %.2f, %.2f); "
          "%d solids and %d textures not found in the region file" % (out, n, r.shift[0], r.shift[1], r.shift[2],
                                                                   r.road_height, r.spawn[0], r.spawn[1], r.spawn[2],
                                                                   len(r.solids_not_found),
                                                                   len(r.textures_not_found)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
