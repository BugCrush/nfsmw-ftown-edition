"""Scenery sections (chunk 0x80034100) written from tools/world/scenery.py's model, and new ones made.

Layout, checked over all 947 of Rockport's scenery sections (tools/world/tests/test_scenery_write.py; findings in
docs/ftown-notes.md, "Part 2: writers"):

    0x80034100 scenery section (its data starts at 8 mod 16 in every file: the header's data is 16-aligned)
      0x34101 ScenerySectionHeader, 60 bytes: zeros but +0x0C the section number (all 947; the other fields are
              run-time state: ChunksLoaded +0x08, the table pointers and counts +0x18..+0x34, Scenery.hpp:214)
      0x34103 instances, 0x40 each, after a 0x11 run to 16 (GetAlignedData(16), Scenery.cpp:323)
      0x34102 infos, 0x48 each (name NUL-padded to 24 bytes, the model pointers +0x28..+0x37 and +0x44 zero)
      0x34105 tree nodes, 0x24 each (box, s16 child count, 5 s16 child codes, unused ones 0; code >= 0 = an
              instance, < 0 = the node at -code; the root is node 0, Scenery.cpp:866 TreeCull)
      0x34106 override hookups (377 sections; kept as data)
      0x34107 preculler records, 0x80 bytes of "not visible" bits each (Scenery.hpp:180); record 0 has no bit set in
              all 947 sections

The loader takes the chunks by id in any order (LoaderScenery, Scenery.cpp:276-390); the writer keeps the files'
order. Coordinates are the world files' (render: x, y horizontal, z up).
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
for p in (CARBUILD, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, chunk_bytes  # noqa: E402
from world.scenery import (ALIGN, PRECULLER, SCENERY_HEADER, SCENERY_HOOKS, SCENERY_INFOS, SCENERY_INSTANCES,  # noqa: E402
                           SCENERY_SECTION, SCENERY_TREE, Info, Instance, Scenery, transform)

HEADER_SIZE = 60
MAX_CHILDREN = 5
# ExcludeFlags of Rockport's drawn road terrain instances (TRN_ solids at the origin with road materials): 0x2E0 in
# 1,712 of 2,027 (docs/ftown-notes.md, "Part 2: writers")
ROAD_EXCLUDE_FLAGS = 0x2E0
NO_LIGHTING_CONTEXT = -1  # all 2,027 of those instances


def parse_tree(data):
    """[(box (6 floats), [child codes])] of a 0x34105 chunk."""
    out = []
    for i in range(0, len(data), 0x24):
        box = struct.unpack_from("<6f", data, i)
        n, *codes = struct.unpack_from("<h5h", data, i + 0x18)
        if any(codes[n:]):
            raise ValueError("tree node %d: unused child codes are not zero" % (i // 0x24))
        out.append((box, codes[:n]))
    return out


def tree_bytes(nodes):
    out = bytearray()
    for box, kids in nodes:
        if len(kids) > MAX_CHILDREN:
            raise ValueError("a tree node has %d children (5 at most)" % len(kids))
        codes = list(kids) + [0] * (MAX_CHILDREN - len(kids))
        out += struct.pack("<6fh5h", *box, len(kids), *codes)
    return bytes(out)


def info_bytes(info):
    name = info.name.encode("latin-1")
    if len(name) > 23:
        raise ValueError("info name %r longer than 23 bytes" % info.name)
    return (name + bytes(24 - len(name)) + struct.pack("<4I", *info.solid_hashes) + bytes(16) +
            struct.pack("<fII", info.radius, info.checksum, info.hierarchy) + bytes(4))


def instance_bytes(inst):
    m = inst.matrix
    rot = []
    for r in range(3):
        for a in range(3):
            v = int(round(m[r][a] * 8192.0))
            if not -32768 <= v <= 32767 or v / 8192.0 != m[r][a]:
                raise ValueError("rotation %r is not an s16 / 8192" % (m[r][a],))
            rot.append(v)
    return (struct.pack("<6f", *inst.bbox) + struct.pack("<Ihh", inst.exclude_flags, inst.preculler, inst.lighting) +
            struct.pack("<3f", *m[3][:3]) + struct.pack("<9h", *rot) + struct.pack("<h", inst.info_index))


def write_section(sc, pos=8):
    """The 0x80034100 Chunk of a Scenery whose data starts at `pos` from an aligned origin (the section's start).
    The header's data must be 16-aligned (pos % 16 == 8), as in every Rockport file: the loader takes it with
    GetAlignedData(16)."""
    if (pos + 8) % 16:
        raise ValueError("scenery section data at %d: the header would not be 16-aligned" % pos)
    header = bytearray(sc.header if sc.header else bytes(HEADER_SIZE))
    struct.pack_into("<i", header, 0x0C, sc.number)
    parts = [(SCENERY_HEADER, bytes(header)),
             (SCENERY_INSTANCES, b"".join(instance_bytes(i) for i in sc.instances)),
             (SCENERY_INFOS, b"".join(info_bytes(i) for i in sc.infos)),
             (SCENERY_TREE, tree_bytes(parse_tree(sc.tree)))]
    for cid in (SCENERY_HOOKS, PRECULLER):
        if cid in sc.other:
            parts.append((cid, sc.other[cid]))
    extra = set(sc.other) - {SCENERY_HOOKS, PRECULLER}
    if extra:
        raise ValueError("scenery chunks the writer does not know: %s" % sorted("0x%X" % x for x in extra))
    kids = []
    p = pos
    for cid, data in parts:
        a = ALIGN.get(cid)
        if a:
            data = b"\x11" * ((-(p + 8)) % a) + data
        c = Chunk(cid, data)
        kids.append(c)
        p += len(chunk_bytes(c))
    return Chunk(SCENERY_SECTION, None, kids)


def _solid_points(so):
    return [struct.unpack_from("<3f", m.vertices, i * m.stride) for m in so.meshes for i in range(m.vertex_count)]


def build_tree(boxes):
    """Tree nodes over instance boxes: node 0 the root, at most 5 children a node; groups split along the longer
    horizontal axis of their centres."""
    nodes = []

    def union(idx):
        return tuple(min(boxes[i][a] for i in idx) for a in range(3)) + \
            tuple(max(boxes[i][3 + a] for i in idx) for a in range(3))

    def make(idx):
        me = len(nodes)
        nodes.append(None)
        if len(idx) <= MAX_CHILDREN:
            nodes[me] = (union(idx), list(idx))
            return me
        box = union(idx)
        axis = 0 if box[3] - box[0] >= box[4] - box[1] else 1
        idx = sorted(idx, key=lambda i: boxes[i][axis] + boxes[i][3 + axis])
        groups = MAX_CHILDREN
        size = math.ceil(len(idx) / groups)
        kids = []
        for g in range(0, len(idx), size):
            part = idx[g:g + size]
            kids.append(-make(part) if len(part) > 1 else part[0])
        nodes[me] = (box, kids)
        return me

    if not boxes:
        raise ValueError("a scenery section needs instances")
    make(list(range(len(boxes))))
    return nodes


def make_section(number, models, solids, props=()):
    """A Scenery for section `number`: one info and one instance per model (info name, the four detail levels' solid
    name hashes, a 4x4 matrix as scenery.Instance has, and optionally the instance's exclude flags), `solids` {name
    hash: solids.WorldSolid} for the boxes and
    radii. Instances as Rockport's road terrain: exclude flags 0x2E0, no lighting context (-1), preculler record 0
    (one record with no hidden bits: DrawAScenery 0x729120 reads table[index] with no check whenever preculling is
    on, so the table must exist); the instance box is the solid's vertices placed by the matrix; the info radius is
    the farthest vertex from the instance's position (the pixel-size test measures from there, Scenery.cpp:704)."""
    infos, instances, boxes = [], [], []
    for k, model in enumerate(models):
        name, hashes, matrix = model[:3]
        flags = model[3] if len(model) > 3 else ROAD_EXCLUDE_FLAGS
        so = solids[hashes[0]]
        pts = [transform(matrix, p) for p in _solid_points(so)]
        radius = max(math.sqrt(sum(p[a] ** 2 for a in range(3))) for p in _solid_points(so))
        box = tuple(min(p[a] for p in pts) for a in range(3)) + tuple(max(p[a] for p in pts) for a in range(3))
        box = tuple(struct.unpack("<f", struct.pack("<f", v))[0] for v in box)
        infos.append(Info(name, tuple(hashes), float(struct.unpack("<f", struct.pack("<f", radius))[0]),
                          so.name_hash, 0))
        instances.append(Instance(k, tuple(tuple(float(v) for v in r) for r in matrix), box, flags, 0,
                                  NO_LIGHTING_CONTEXT))
        boxes.append(box)
    # props (F-Town's street life, docs/ftown-notes.md "Street life (2026-11-04)"): (info name, the four slots' hashes,
    # info radius, the model's box (x0, y0, z0, x1, y1, z1), matrix, exclude flags); the model is named by hash only
    # (held by another loaded pack), so the box and radius are given; one info per (name, slots, radius)
    # (and optionally a seventh item: the info's hierarchy name hash, as Rockport's smackable poles' infos carry:
    # F-Town's breakable poles, 2026-11-05)
    shared = {}
    for prop in props:
        name, hashes, radius, mbox, matrix, flags = prop[:6]
        hier = prop[6] if len(prop) > 6 else 0
        key = (name, tuple(hashes), float(radius), hier)
        if key not in shared:
            shared[key] = len(infos)
            infos.append(Info(name, tuple(hashes), float(struct.unpack("<f", struct.pack("<f", radius))[0]),
                              hashes[0], hier))
        corners = [(x, y, z) for x in (mbox[0], mbox[3]) for y in (mbox[1], mbox[4]) for z in (mbox[2], mbox[5])]
        pts = [transform(matrix, p) for p in corners]
        box = tuple(min(p[a] for p in pts) for a in range(3)) + tuple(max(p[a] for p in pts) for a in range(3))
        box = tuple(struct.unpack("<f", struct.pack("<f", v))[0] for v in box)
        instances.append(Instance(shared[key], tuple(tuple(float(v) for v in r) for r in matrix), box, flags, 0,
                                  NO_LIGHTING_CONTEXT))
        boxes.append(box)
    tree = tree_bytes(build_tree(boxes))
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<i", header, 0x0C, number)
    return Scenery(number, bytes(header), infos, instances, tree, {PRECULLER: bytes(0x80)})
