"""World solid lists (chunk 0x80134000): read into a model and written back, and new solids made from triangles.

The writer rebuilds everything structural from the model: the alignment runs of 0x11 bytes (from the list's position:
the game loads section data 2,048-aligned), the padding chunk before the list header, the solid count in the info,
the index (the solids' name hashes, sorted), each solid's name hash, texture and shader counts and name padding, the
mesh header's counts, each mesh entry's vertex, triangle and index counts and index offset, the vertex buffers (one
per run of meshes with the same +0x30 kind) and the index buffer (indices stored relative to each mesh's first vertex
in the model). Every one of Rockport's 3,305 lists writes back byte-identical (tools/world/tests/test_solids.py).

Layout of a list, checked over all 3,305 (docs/ftown-notes.md, "Part 2: writers"):

    0x80134000 list
      0x00000000 padding: makes the next chunk start at a multiple of 16
      0x80134001 header: 0x134002 info (144 bytes: +0x08 29, +0x0C solid count, +0x10 source file name (56),
                 +0x48 a section name (8), +0x68 a number in 78 lists (0 in the rest), +0x70 0x80),
                 0x134003 index ((name hash, 0) per solid, sorted by hash), 0x80134008 (empty)
      0x80134010 solid, sorted by name hash, one per solid:
        0x134011 header (0x11 run to 16): the game's eSolid (Ecstasy/Ecstasy.hpp:81): +0x0C version 22, +0x0E flags,
                 +0x10 name hash (bStringHash of the name), +0x14 polygon count (s16; one more than the meshes'
                 triangles in 8 of 20,377 solids, so kept as data), +0x16 0, +0x19 texture count, +0x1A shader
                 (light material) count, +0x20 box min, +0x30 box max (vertex extents + 0.01 m in all but the 19
                 empty solids), +0x40 pivot matrix, +0x88/+0x8C 0xEA550 (a bTList left by EA's tool, all solids),
                 +0x98 volume (the box's), +0x9C density (polygons / volume), +0xA0 name, NUL-padded to 4
        0x134012 textures ((hash, 0) each), 0x134013 shaders (in 355 solids), 0x13401A (20 solids, 0x11 run to 16)
        0x80134100 meshes:
          0x134900 mesh header (0x11 run to 16; 48 bytes: +0x08 18, +0x0C strip flags, +0x10 mesh count,
                   +0x18 vertex buffer count, +0x2C index count)
          0x134B02 mesh entries (0x11 run to 16; 104 bytes each: box, texture slots +0x18, +0x1D 0xFF, +0x30 kind,
                   +0x38 flags, +0x3C vertex count, +0x40 triangle count, +0x44 first index, +0x5C index count)
          0x134B03 indices (0x11 run to 16; u16, padded with zeros to 4 bytes)
          0x134B01 vertex buffer x n (0x11 run to 128)
          0x134C02 mesh name x meshes (NUL-padded: size = (len // 4 + 1) x 4)

Coordinates are the world files' (render: x, y horizontal, z up).
"""
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
for p in (CARBUILD, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, bstringhash, chunk_bytes  # noqa: E402,F401
from world.scenery import (ALIGN, ENTRIES, INDICES, LIST_HEADER, LIST_INDEX, LIST_INFO, MESH_HEADER, MESH_NAME,  # noqa: E402
                           MESHES, SHADERS, SOLID, SOLID_HEADER, SOLID_LIST, TEXTURES, VERTICES, unpad,
                           with_positions)

LIST_END = 0x80134008
HEADER_SIZE = 0xA0  # the eSolid fields before the name
ENTRY_SIZE = 104
MAX_TRIS_PER_MESH = 1000
# the most common vertex colour of Rockport's mesh-kind-0 road solids: bytes 64 59 52 FF, 131,897 of 137,276
# vertices (docs/ftown-notes.md, "Part 2: writers")
ROAD_COLOUR = 0xFF525964
MODEL_LIST_LEFTOVER = 0xEA550  # eSolid +0x88/+0x8C in all 20,377 of Rockport's solids
INFO_SIZE = 144


@dataclass
class WorldMesh:
    entry: bytes  # the 104-byte entry; counts and the first index are rewritten by the writer
    vertices: bytes
    stride: int
    indices: Tuple[int, ...]  # relative to this mesh's first vertex
    name: str

    @property
    def kind(self):
        return struct.unpack_from("<I", self.entry, 0x30)[0]

    @property
    def vertex_count(self):
        return len(self.vertices) // self.stride if self.stride else 0


@dataclass
class WorldSolid:
    name: str
    header: bytes  # the first 0xA0 bytes of the eSolid header (name hash, counts rewritten by the writer)
    textures: List[int]
    shaders: Optional[List[int]]
    extras: List[Tuple[int, bytes]]  # other chunks between the texture/shader lists and the meshes (unpadded data)
    mesh_header: bytes
    meshes: List[WorldMesh]
    name_tail: bytes = b""  # bytes after the name's NUL in the header (all zero in Rockport's files)

    @property
    def name_hash(self):
        return bstringhash(self.name)


@dataclass
class WorldSolidList:
    info: bytes  # 144 bytes; the solid count at +0x0C is rewritten
    solids: List[WorldSolid]
    pos: int = 0  # data position of the list chunk from an aligned origin (the section's start)


# ---------------------------------------------------------------- reading

def _names_padded(raw):
    return raw.split(b"\0")[0].decode("latin-1")


def _read_solid(c, pos):
    header = textures = None
    shaders, extras, mesh_header = None, [], b""
    meshes = []
    for k, kpos in with_positions(c.children, pos):
        if k.id == SOLID_HEADER:
            header = unpad(k.id, k.data, kpos)
        elif k.id == TEXTURES:
            textures = [struct.unpack_from("<I", k.data, i)[0] for i in range(0, len(k.data), 8)]
        elif k.id == SHADERS:
            shaders = [struct.unpack_from("<I", k.data, i)[0] for i in range(0, len(k.data), 8)]
        elif k.id == MESHES:
            entries, idx, buffers, names = [], b"", [], []
            for m, mpos in with_positions(k.children, kpos):
                d = unpad(m.id, m.data, mpos)
                if m.id == MESH_HEADER:
                    mesh_header = d
                elif m.id == ENTRIES:
                    entries = [d[i:i + ENTRY_SIZE] for i in range(0, len(d), ENTRY_SIZE)]
                elif m.id == INDICES:
                    idx = d
                elif m.id == VERTICES:
                    buffers.append(d)
                elif m.id == MESH_NAME:
                    names.append(m.data)
                else:
                    raise ValueError("unknown chunk 0x%X in a mesh container" % m.id)
            if len(names) != len(entries):
                raise ValueError("%d mesh names for %d meshes" % (len(names), len(entries)))
            meshes = _split_meshes(entries, idx, buffers, names)
        else:
            if k.data is None:
                raise ValueError("unexpected container 0x%X in a solid" % k.id)
            extras.append((k.id, unpad(k.id, k.data, kpos)))
    name_raw = header[HEADER_SIZE:]
    name = _names_padded(name_raw)
    tail = name_raw[len(name) + 1:]
    if tail.strip(b"\0"):
        raise ValueError("solid %s: bytes after the name" % name)
    sol = WorldSolid(name, header[:HEADER_SIZE], textures or [], shaders, extras, mesh_header, meshes)
    if struct.unpack_from("<I", header, 0x10)[0] != sol.name_hash:
        raise ValueError("solid %s: name hash differs from bStringHash(name)" % name)
    return sol


def _split_meshes(entries, idx, buffers, names):
    """WorldMesh per entry: each buffer holds the vertices of a run of meshes with the same kind, in order."""
    out = []
    b, prev, voff = -1, None, 0
    for e, nm in zip(entries, names):
        kind = struct.unpack_from("<I", e, 0x30)[0]
        vc, tc, io = struct.unpack_from("<3I", e, 0x3C)
        ic = struct.unpack_from("<I", e, 0x5C)[0]
        if kind != prev:
            b, prev, voff = b + 1, kind, 0
        out.append([e, b, voff, vc, io, ic, nm])
        voff += vc
    counts = {}
    for e, b, voff, vc, io, ic, nm in out:
        counts[b] = counts.get(b, 0) + vc
    meshes = []
    for e, b, voff, vc, io, ic, nm in out:
        stride = len(buffers[b]) // counts[b] if counts[b] else 0
        if stride * counts[b] != len(buffers[b]):
            raise ValueError("vertex buffer %d: %d bytes for %d vertices" % (b, len(buffers[b]), counts[b]))
        verts = buffers[b][voff * stride:(voff + vc) * stride]
        ind = struct.unpack_from("<%dH" % ic, idx, io * 2)
        meshes.append(WorldMesh(e, verts, stride, tuple(i - voff for i in ind), _names_padded(nm)))
        if _name_chunk(meshes[-1].name) != nm:
            raise ValueError("mesh name %r is not padded as the writer pads" % meshes[-1].name)
    return meshes


def read_list(chunk, pos=0):
    """WorldSolidList of a 0x80134000 chunk whose data starts at `pos` (from the section's 2,048-aligned start)."""
    if chunk.id != SOLID_LIST:
        raise ValueError("not a solid list: 0x%X" % chunk.id)
    info = None
    sols = []
    for k, kpos in with_positions(chunk.children, pos):
        if k.id == 0:
            if k.data.strip(b"\0") or len(k.data) != _pad_len(kpos):
                raise ValueError("list padding not as the writer makes it")
        elif k.id == LIST_HEADER:
            for h in k.children:
                if h.id == LIST_INFO:
                    info = h.data
        elif k.id == SOLID:
            sols.append(_read_solid(k, kpos))
        else:
            raise ValueError("unknown chunk 0x%X in a solid list" % k.id)
    return WorldSolidList(info, sols, pos)


# ---------------------------------------------------------------- writing

def _pad_len(data_pos):
    """Length of the padding chunk's data so the chunk after it starts at a multiple of 16."""
    return (-data_pos) % 16


def _aligned(cid, data, data_pos):
    a = ALIGN.get(cid)
    run = (-data_pos) % a if a else 0
    return b"\x11" * run + data


def _leaf(cid, data, data_pos):
    return Chunk(cid, _aligned(cid, data, data_pos))


def _name_chunk(name):
    raw = name.encode("latin-1")
    return raw + bytes((len(raw) // 4 + 1) * 4 - len(raw))


class _Writer:
    """Builds children in order, tracking each chunk's data position."""

    def __init__(self, data_pos):
        self.pos = data_pos  # where the next chunk's header starts
        self.out = []

    def leaf(self, cid, data):
        c = _leaf(cid, data, self.pos + 8)
        self.out.append(c)
        self.pos += len(chunk_bytes(c))
        return c

    def add(self, c):
        self.out.append(c)
        self.pos += len(chunk_bytes(c))


def _write_solid(s, data_pos):
    w = _Writer(data_pos)
    h = bytearray(s.header)
    struct.pack_into("<I", h, 0x10, s.name_hash)
    h[0x19] = len(s.textures)
    h[0x1A] = len(s.shaders or [])
    name = s.name.encode("latin-1")
    body = bytes(h) + name + b"\0"
    body += bytes((-len(body)) % 4)
    w.leaf(SOLID_HEADER, body)
    w.leaf(TEXTURES, b"".join(struct.pack("<II", t, 0) for t in s.textures))
    if s.shaders is not None:
        w.leaf(SHADERS, b"".join(struct.pack("<II", t, 0) for t in s.shaders))
    for cid, data in s.extras:
        w.leaf(cid, data)
    w.add(_write_meshes(s, w.pos + 8))
    return Chunk(SOLID, None, w.out)


def _write_meshes(s, data_pos):
    w = _Writer(data_pos)
    buffers, entries, indices = [], [], []
    prev, voff, io = None, 0, 0
    for m in s.meshes:
        if m.kind != prev:
            buffers.append(bytearray())
            prev, voff = m.kind, 0
        buffers[-1] += m.vertices
        e = bytearray(m.entry)
        ic = len(m.indices)
        struct.pack_into("<3I", e, 0x3C, m.vertex_count, ic // 3, io)
        struct.pack_into("<I", e, 0x5C, ic)
        entries.append(bytes(e))
        indices.extend(i + voff for i in m.indices)
        voff += m.vertex_count
        io += ic
    mh = bytearray(s.mesh_header)
    struct.pack_into("<I", mh, 0x10, len(s.meshes))
    struct.pack_into("<I", mh, 0x18, len(buffers))
    struct.pack_into("<I", mh, 0x2C, len(indices))
    w.leaf(MESH_HEADER, bytes(mh))
    w.leaf(ENTRIES, b"".join(entries))
    ind = struct.pack("<%dH" % len(indices), *indices)
    w.leaf(INDICES, ind + bytes((-len(ind)) % 4))
    for b in buffers:
        w.leaf(VERTICES, bytes(b))
    for m in s.meshes:
        w.add(Chunk(MESH_NAME, _name_chunk(m.name)))
    return Chunk(MESHES, None, w.out)


def write_list(lst, pos=None):
    """The 0x80134000 Chunk of a list whose data will start at `pos` (default: the position it was read at)."""
    pos = lst.pos if pos is None else pos
    w = _Writer(pos)
    w.add(Chunk(0, bytes(_pad_len(pos + 8))))
    sols = sorted(lst.solids, key=lambda s: s.name_hash)
    info = bytearray(lst.info)
    struct.pack_into("<I", info, 0x0C, len(sols))
    index = b"".join(struct.pack("<II", s.name_hash, 0) for s in sols)
    w.add(Chunk(LIST_HEADER, None, [Chunk(LIST_INFO, bytes(info)), Chunk(LIST_INDEX, index),
                                    Chunk(LIST_END, None, [])]))
    for s in sols:
        w.add(_write_solid(s, w.pos + 8))
    return Chunk(SOLID_LIST, None, w.out)


# ---------------------------------------------------------------- new solids

def new_list(solids, file_name, section_name=""):
    """A WorldSolidList of new solids. The info's constants are the ones every Rockport list has (+0x08 29,
    +0x70 0x80); +0x10 the source file name, +0x48 a section name."""
    info = bytearray(INFO_SIZE)
    struct.pack_into("<I", info, 0x08, 29)
    fn = file_name.encode("ascii")[:55]
    info[0x10:0x10 + len(fn)] = fn
    sn = section_name.encode("ascii")[:7]
    info[0x48:0x48 + len(sn)] = sn
    struct.pack_into("<I", info, 0x70, 0x80)
    return WorldSolidList(bytes(info), list(solids), 0)


def _normal(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    L = math.sqrt(sum(x * x for x in n))
    return tuple(x / L for x in n) if L else (0.0, 0.0, 1.0)


def _box(points, margin=0.01):
    lo = [min(p[a] for p in points) - margin for a in range(3)]
    hi = [max(p[a] for p in points) + margin for a in range(3)]
    return lo, hi


def make_solid(name, tris, uvs, texture_hash, colour=ROAD_COLOUR, mesh_name=None):
    """A WorldSolid of triangles (p0, p1, p2) in world (render) coordinates with uvs ((u, v) x 3) per triangle, one
    texture, pre-lit vertex colour `colour` (u32: bytes B, G, R, A in the file). One mesh per 1,000 triangles, mesh
    kind 0 with 36-byte vertices (position, unit normal, colour, uv; the normal of the triangle, counter-clockwise seen
    from above = up), three vertices per triangle (none shared). The header is filled as Rockport's are: version 22,
    box = vertex extents + 0.01 m, volume = the box's, density = polygons / volume, identity pivot."""
    if len(tris) != len(uvs):
        raise ValueError("%d triangles, %d uv triples" % (len(tris), len(uvs)))
    if not tris:
        raise ValueError("a solid needs triangles")
    if 3 * len(tris) > 0xFFFF:
        raise ValueError("%d triangles: more vertices than 16-bit indices reach" % len(tris))
    meshes = []
    for start in range(0, len(tris), MAX_TRIS_PER_MESH):
        part = tris[start:start + MAX_TRIS_PER_MESH]
        puv = uvs[start:start + MAX_TRIS_PER_MESH]
        verts = bytearray()
        for (a, b, c), (ua, ub, uc) in zip(part, puv):
            n = _normal(a, b, c)
            for p, uv in ((a, ua), (b, ub), (c, uc)):
                verts += struct.pack("<3f3fI2f", p[0], p[1], p[2], n[0], n[1], n[2], colour, uv[0], uv[1])
        lo, hi = _box([p for t in part for p in t], 0.0)
        e = bytearray(ENTRY_SIZE)
        struct.pack_into("<6f", e, 0, *(lo + hi))
        e[0x1D] = 0xFF
        struct.pack_into("<I", e, 0x30, 0)
        struct.pack_into("<I", e, 0x38, 0x4000)  # ESTRIP_HAS_NORMALS: every Rockport kind-0 road mesh (1,979)
        meshes.append(WorldMesh(bytes(e), bytes(verts), 36, tuple(range(3 * len(part))),
                                mesh_name or name))
    lo, hi = _box([p for t in tris for p in t])
    lo32 = [struct.unpack("<f", struct.pack("<f", x))[0] for x in lo]
    hi32 = [struct.unpack("<f", struct.pack("<f", x))[0] for x in hi]
    vol = (hi32[0] - lo32[0]) * (hi32[1] - lo32[1]) * (hi32[2] - lo32[2])
    h = bytearray(HEADER_SIZE)
    h[0x0C] = 22
    struct.pack_into("<hh", h, 0x14, len(tris), 0)
    struct.pack_into("<4f", h, 0x20, lo[0], lo[1], lo[2], 0.0)
    struct.pack_into("<4f", h, 0x30, hi[0], hi[1], hi[2], 0.0)
    struct.pack_into("<16f", h, 0x40, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    struct.pack_into("<II", h, 0x88, MODEL_LIST_LEFTOVER, MODEL_LIST_LEFTOVER)
    struct.pack_into("<ff", h, 0x98, vol, len(tris) / vol if vol else 0.0)
    mh = bytearray(48)
    struct.pack_into("<II", mh, 0x08, 18, 0x4000)
    return WorldSolid(name, bytes(h), [texture_hash], None, [], bytes(mh), meshes)


def _header(tris, all_pts):
    lo, hi = _box(all_pts)
    lo32 = [struct.unpack("<f", struct.pack("<f", x))[0] for x in lo]
    hi32 = [struct.unpack("<f", struct.pack("<f", x))[0] for x in hi]
    vol = (hi32[0] - lo32[0]) * (hi32[1] - lo32[1]) * (hi32[2] - lo32[2])
    h = bytearray(HEADER_SIZE)
    h[0x0C] = 22
    struct.pack_into("<hh", h, 0x14, tris, 0)
    struct.pack_into("<4f", h, 0x20, lo[0], lo[1], lo[2], 0.0)
    struct.pack_into("<4f", h, 0x30, hi[0], hi[1], hi[2], 0.0)
    struct.pack_into("<16f", h, 0x40, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    struct.pack_into("<II", h, 0x88, MODEL_LIST_LEFTOVER, MODEL_LIST_LEFTOVER)
    struct.pack_into("<ff", h, 0x98, vol, tris / vol if vol else 0.0)
    return bytes(h)


def make_solid_multi(name, groups):
    """A WorldSolid of several materials: groups [(texture hash, mesh name, triangles, uvs, colours)], triangles
    (p0, p1, p2) in the solid's own coordinates (counter-clockwise seen from the side they face), uvs ((u, v) x 3) and
    one pre-lit colour (u32) per triangle, or a tuple of three (one per vertex: F-Town's dusty road edges, Run I fixes).
    As make_solid (kind 0, 36-byte vertices, the triangle's normal, mesh flags
    0x4000, at most 1,000 triangles a mesh) but: the solid lists every group's texture once and each mesh's five
    texture slots name its own (as all of Rockport's multi-texture kind-0 world meshes do: slots equal), and a mesh
    shares vertices between its triangles (same position, normal, colour and uv: one vertex). All meshes are one
    vertex buffer with 16-bit indices: more than 65,535 vertices in a solid raises."""
    textures, meshes, all_pts, ntris, nverts = [], [], [], 0, 0
    for tex, mesh_name, tris, uvs, cols in groups:
        if not tris:
            continue
        if not (len(tris) == len(uvs) == len(cols)):
            raise ValueError("%s: %d triangles, %d uvs, %d colours" % (mesh_name, len(tris), len(uvs), len(cols)))
        if tex not in textures:
            textures.append(tex)
        slot = textures.index(tex)
        for start in range(0, len(tris), MAX_TRIS_PER_MESH):
            part = tris[start:start + MAX_TRIS_PER_MESH]
            verts, index, idx = bytearray(), {}, []
            for t, uv, col in zip(part, uvs[start:start + MAX_TRIS_PER_MESH], cols[start:start + MAX_TRIS_PER_MESH]):
                n = _normal(*t)
                for p, q, c in zip(t, uv, col if isinstance(col, tuple) else (col, col, col)):
                    rec = struct.pack("<3f3fI2f", p[0], p[1], p[2], n[0], n[1], n[2], c, q[0], q[1])
                    k = index.get(rec)
                    if k is None:
                        k = index[rec] = len(index)
                        verts += rec
                    idx.append(k)
            nverts += len(index)
            if nverts > 0xFFFF:
                raise ValueError("%s: %d vertices, more than 16-bit indices reach" % (name, nverts))
            pts = [p for t in part for p in t]
            lo, hi = _box(pts, 0.0)
            e = bytearray(ENTRY_SIZE)
            struct.pack_into("<6f", e, 0, *(lo + hi))
            e[0x18:0x1D] = bytes([slot]) * 5
            e[0x1D] = 0xFF
            struct.pack_into("<I", e, 0x30, 0)
            struct.pack_into("<I", e, 0x38, 0x4000)
            meshes.append(WorldMesh(bytes(e), bytes(verts), 36, tuple(idx), mesh_name))
            all_pts += pts
            ntris += len(part)
    if not meshes:
        raise ValueError("a solid needs triangles")
    if ntris > 0x7FFF:
        raise ValueError("%s: %d triangles, more than the header's s16 count" % (name, ntris))
    mh = bytearray(48)
    struct.pack_into("<II", mh, 0x08, 18, 0x4000)
    return WorldSolid(name, _header(ntris, all_pts), textures, None, [], bytes(mh), meshes)
