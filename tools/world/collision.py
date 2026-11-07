"""World collision packs (WCollisionAssets, chunk 0x3B801), read only.

One pack per streaming section of STREAML2RA.BUN, filed by the game in WCollisionAssets::mCollisionPackList[section
number] (World/Common/WCollisionAssets.cpp:183 LoadCollisionPack; up to 2,700 packs, COLLISION_PACK_MAX).

Layout (decompilation World/WCollision.h, WCollisionPack.h, World/Common/WCollisionPack.cpp, Libs/Support/Utility/
UGroup.hpp, Libs/Support/Miscellaneous/CARP.h; the byte-level details marked "bytes" were read from the files and are
checked over every pack in tools/world/tests/test_collision.py):

    chunk data, aligned to 16 by a run of 0x11 bytes (GetAlignedData(16))
    bChunkCarpHeader (16): u32 size of what follows, u32 section number, u32 flags (1 = resolved), u32 last address
    UGroup 'CARP' (16): u32 tag, u32 bits (bit0 indexed, bit1 embedded, bit2 allocated, bit3 data sorted, bit4 groups
        sorted, bits 5.. group count), u32 data count, u32 offset (bytes: the child array starts at this + 16 x offset)
      UGroup 'Arti': its UData array (16 each): u32 tag (type << 16 | index), u32 bits (bit0 indexed, bit1
        embedded, bits 8.. size in bytes of the whole data, bytes), u32 count, u32 offset (bytes from the UData)
        'Name' the pack's name (the section number as text, bytes)
        'ca' + index: one WCollisionArticle per render instance index
        'ci': WCollisionInstance x count (0x40 each)
        'co': WCollisionObject x count (0x70 each), when present

WCollisionInstance (CARP.h:278): +0x00 inverse matrix row 0 (x, y, z) and width, +0x10 u16 iteration stamp, +0x12
u16 flags (bit0 y axis not up, bit1 dynamic: cross product needed for row 1), +0x14 height, +0x18 u16 group number,
+0x1A u16 article index, +0x1C article pointer (run time), +0x20 inverse row 2 and length, +0x30 inverse translation
and radius. A world point w goes to local l = w.x r0 + w.y r1 + w.z r2 + t (row vectors; r1 = (0, 1, 0) unless the
flags say otherwise); the instance's position is -(t . r0, t . r1, t . r2) (WCollision.cpp:34 CalcPosition).

WCollisionArticle (WCollision.h:110): u16 strip count, u16 strips size, u16 edge (barrier) count, u16 edges size,
u8 resolved, u8 surface count, u16 surfaces size, u16 intermediate object, s16 flags; then the strip spheres (16 each:
centre x, y, z, u16 radius, u16 offset: strip data at article + 16 + offset), the strips (packed vertices, 8 each:
s16 x, y, z / 128 + the sphere centre, u16 surface; vertex 0's surface field = vertex count, vertex 1's = strip
flags, triangle k takes vertex k + 2's surface), the barriers (32 each: two Vector4 points; point 0's w holds the
barrier's surface (CollisionSurface: u8 index, u8 flags), point 1's w = 1 / horizontal length), then the surfaces (u32
name hashes, resolved by SimSurface::Lookup, WCollisionPack.cpp:65).

**All coordinates here are the physics convention (y up)**: render (x, y, z) = (z, -x, y) of physics, physics =
(-render y, render z, render x) (bConvertToBond, bWare/Inc/bMath.hpp:1014).
"""
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

COLLISION_PACK = 0x3B801


def tag_text(tag):
    t = tag >> 16
    return bytes([(t >> 8) & 0xFF, t & 0xFF]).decode("latin-1")


def to_render(p):
    """physics (x, y up, z) -> render/world files (x, y, z up)."""
    return (p[2], -p[0], p[1])


def to_physics(p):
    """render (x, y, z up) -> physics (x, y up, z)."""
    return (-p[1], p[2], p[0])


@dataclass
class UData:
    tag: int
    bits: int
    count: int
    data: bytes

    @property
    def type(self):
        return tag_text(self.tag) if self.bits & 1 else struct.pack(">I", self.tag).decode("latin-1")

    @property
    def index(self):
        return self.tag & 0xFFFF


@dataclass
class Barrier:
    p0: tuple  # local (x, y, z)
    p1: tuple
    surface: int  # u8 index into the article's surfaces
    surface_flags: int
    inv_length: float


@dataclass
class Strip:
    verts: List[tuple]  # local (x, y, z)
    surfaces: List[int]  # per triangle: u8 surface index
    flags: int


@dataclass
class Article:
    index: int
    header: tuple
    strips: List[Strip]
    barriers: List[Barrier]
    surfaces: List[int]  # name hashes
    tail: bytes  # bytes after the declared parts (not decoded)


@dataclass
class CInstance:
    raw: bytes
    r0: tuple
    width: float
    flags: int
    height: float
    group: int
    article: int
    r2: tuple
    length: float
    t: tuple
    radius: float

    @property
    def r1(self):
        if self.flags & 3:
            a, b = self.r2, self.r0  # Crossxyz(row2, row0) (WCollision.cpp:57)
            return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        return (0.0, 1.0, 0.0)

    @property
    def position(self):
        t = self.t
        return tuple(-(t[0] * r[0] + t[1] * r[1] + t[2] * r[2]) for r in (self.r0, self.r1, self.r2))

    def to_world(self, l):
        """local -> physics world: w_i = (l - t) . r_i."""
        d = (l[0] - self.t[0], l[1] - self.t[1], l[2] - self.t[2])
        return tuple(d[0] * r[0] + d[1] * r[1] + d[2] * r[2] for r in (self.r0, self.r1, self.r2))


@dataclass
class CollisionPack:
    section: int
    flags: int
    carp_size: int
    name: str
    data: List[UData]
    articles: Dict[int, Article]
    instances: List[CInstance]
    objects: List[bytes] = field(default_factory=list)


def _parse_article(index, d):
    h = struct.unpack_from("<4HBBHHh", d, 0)
    nstrips, strips_size, nedges, edges_size, _resolved, nsurf, surf_size, _inter, _flags = h
    strips = []
    for i in range(nstrips):
        cx, cy, cz, radius, off = struct.unpack_from("<3fHH", d, 16 + i * 16)
        o = 16 + off
        n = struct.unpack_from("<H", d, o + 6)[0]
        flags = struct.unpack_from("<H", d, o + 14)[0]
        verts, surfs = [], []
        for k in range(n):
            x, y, z, s = struct.unpack_from("<3hH", d, o + 8 * k)
            verts.append((x / 128.0 + cx, y / 128.0 + cy, z / 128.0 + cz))
            if k >= 2:
                surfs.append(s & 0xFF)
        strips.append(Strip(verts, surfs, flags))
    barriers = []
    base = 16 + strips_size
    for i in range(nedges):
        x0, y0, z0 = struct.unpack_from("<3f", d, base + 32 * i)
        s, sf = struct.unpack_from("<BB", d, base + 32 * i + 12)
        x1, y1, z1, inv = struct.unpack_from("<4f", d, base + 32 * i + 16)
        barriers.append(Barrier((x0, y0, z0), (x1, y1, z1), s, sf, inv))
    sbase = base + edges_size
    surfaces = [struct.unpack_from("<I", d, sbase + 4 * i)[0] for i in range(nsurf)]
    return Article(index, h, strips, barriers, surfaces, d[sbase + surf_size:])


def _parse_instance(r):
    r0x, r0y, r0z, width = struct.unpack_from("<4f", r, 0)
    _stamp, flags = struct.unpack_from("<HH", r, 0x10)
    height, = struct.unpack_from("<f", r, 0x14)
    group, art = struct.unpack_from("<HH", r, 0x18)
    r2 = struct.unpack_from("<4f", r, 0x20)
    t = struct.unpack_from("<4f", r, 0x30)
    return CInstance(bytes(r), (r0x, r0y, r0z), width, flags, height, group, art, r2[:3], r2[3], t[:3], t[3])


def read_pack(chunk_data, pos):
    """A CollisionPack from a 0x3B801 chunk's data, which starts at `pos` from the section's (2,048-aligned) start."""
    run = (-pos) % 16
    if chunk_data[:run] != b"\x11" * run:
        raise ValueError("collision pack: expected %d bytes of 0x11 at +0x%X" % (run, pos))
    d = chunk_data[run:]
    carp_size, section, flags, _last = struct.unpack_from("<4I", d, 0)
    if carp_size + 16 > len(d):
        raise ValueError("collision pack: carp size %d past the chunk (%d)" % (carp_size, len(d) - 16))
    g = 16
    tag, bits, dcount, off = struct.unpack_from("<4I", d, g)
    if tag != 0x43415250:  # 'CARP'
        raise ValueError("collision pack: root tag 0x%08X" % tag)
    ngroups = bits >> 5
    if ngroups != 1 or dcount != 0:
        raise ValueError("collision pack: root has %d groups and %d data" % (ngroups, dcount))
    a = g + 16 * off
    atag, abits, acount, aoff = struct.unpack_from("<4I", d, a)
    if atag != 0x41727469:  # 'Arti'
        raise ValueError("collision pack: group tag 0x%08X" % atag)
    datas = []
    base = a + 16 * aoff + 16 * (abits >> 5)
    for i in range(acount):
        u = base + 16 * i
        utag, ubits, ucount, uoff = struct.unpack_from("<4I", d, u)
        size = ubits >> 8
        start = u + uoff
        if not ubits & 2 or start + size > len(d):
            raise ValueError("collision pack: data %d not embedded or past the end" % i)
        datas.append(UData(utag, ubits, ucount, d[start:start + size]))
    name, articles, instances, objects = "", {}, [], []
    for u in datas:
        t = u.type
        if t == "Name":
            name = u.data.split(b"\0")[0].decode("latin-1")
        elif t == "ca":
            articles[u.index] = _parse_article(u.index, u.data)
        elif t == "ci":
            if len(u.data) != 0x40 * u.count:
                raise ValueError("collision instances: %d bytes for %d" % (len(u.data), u.count))
            instances = [_parse_instance(u.data[k:k + 0x40]) for k in range(0, len(u.data), 0x40)]
        elif t == "co":
            objects = [u.data[k:k + 0x70] for k in range(0, len(u.data), 0x70)]
    return CollisionPack(section, flags, carp_size, name, datas, articles, instances, objects)


@dataclass
class UGroupNode:
    tag: int
    bits: int
    groups: list
    data: List[UData]

    @property
    def name(self):
        return struct.pack(">I", self.tag).decode("latin-1") if not self.bits & 1 else tag_text(self.tag)


def read_ugroup(d, g):
    """A serialized UGroup at offset g of d, with its child groups and data (layout in the module docstring)."""
    tag, bits, dcount, off = struct.unpack_from("<4I", d, g)
    n = bits >> 5
    arr = g + 16 * off
    groups = [read_ugroup(d, arr + 16 * i) for i in range(n)]
    datas = []
    base = arr + 16 * n
    for i in range(dcount):
        u = base + 16 * i
        utag, ubits, ucount, uoff = struct.unpack_from("<4I", d, u)
        size = ubits >> 8
        start = u + uoff
        datas.append(UData(utag, ubits, ucount, d[start:start + size] if ubits & 2 else b""))
    return UGroupNode(tag, bits, groups, datas)


# WGridNode as stored: 0x14 bytes (list pointer, u16 node index, u16 pad, u8 counts[4], u16 offsets[4]) before its
# element tags. The decompilation says "total size: 0x1C" (WGridNode.h:41); the bytes say 0x14 (all 2,779 nodes of
# L2RA.BUN tile the 'CGcn' data exactly with 0x14, test_collision.py), so the bytes win.
GRID_NODE_HEADER = 0x14


@dataclass
class GridInfo:
    min: tuple  # physics (x, y, z, w)
    edge: float
    rows: int
    cols: int
    nodes: int  # nodes stored (cells with static content)
    node_indices: list
    elements: list = field(default_factory=list)  # per node: [(type 0..3, tag)]
    data_size: int = 0
    consumed: int = 0

    @property
    def max(self):
        return (self.min[0] + self.cols * self.edge, self.min[2] + self.rows * self.edge)


def read_world_grid(chunk_data, pos):
    """WGrid of the track's UppleUWorld chunk 0x3B800 in L2RA.BUN (World/Common/WWorld.cpp:23 Loader, WGrid.cpp:27
    Init: group 'CDat', data 'CGrd' = a WGrid (min Vector4, edge, 1/edge, rows, cols) and 'CGcn' = the stored nodes,
    each WGridNode (0x1C: list pointer, u16 node index, u16 pad, u8 counts[4], u16 offsets[4]) then 4-byte element
    tags. Columns run along physics x, rows along physics z (GetRowCol, WGrid.h:59)."""
    run = (-pos) % 16
    d = chunk_data[run:]
    root = read_ugroup(d, 0)

    def find_group(g, name):
        if g.name == name:
            return g
        for k in g.groups:
            r = find_group(k, name)
            if r:
                return r
        return None

    cdat = find_group(root, "CDat")
    if cdat is None:
        raise ValueError("no CDat group (root %s)" % root.name)
    grd = [u for u in cdat.data if u.type == "CGrd"]
    cn = [u for u in cdat.data if u.type == "CGcn"]
    g = grd[0].data
    mn = struct.unpack_from("<4f", g, 0)
    edge, _inv = struct.unpack_from("<2f", g, 0x10)
    rows, cols = struct.unpack_from("<2I", g, 0x18)
    idx, elems = [], []
    o = 0
    nd = cn[0].data if cn else b""
    if cn:
        for _ in range(cn[0].count):
            ni, = struct.unpack_from("<H", nd, o + 4)
            counts = struct.unpack_from("<4B", nd, o + 8)
            offs = struct.unpack_from("<4H", nd, o + 12)
            idx.append(ni)
            el = []
            for t in range(4):
                for k in range(counts[t]):
                    el.append((t, struct.unpack_from("<I", nd, o + GRID_NODE_HEADER + offs[t] + 4 * k)[0]))
            elems.append(el)
            o += GRID_NODE_HEADER + 4 * sum(counts)
    return GridInfo(mn, edge, rows, cols, len(idx), idx, elems, len(nd), o)


def grid_cell(grid, p):
    """(row, col) of a physics point, clamped to the grid's edge like WGrid::GetRowCol / RangeCheckROWCOL
    (WGrid.h:41-62): a point outside the grid lands in an edge cell."""
    col = int((p[0] - grid.min[0]) / grid.edge)
    row = int((p[2] - grid.min[2]) / grid.edge)
    col = 0 if col < 0 else min(col, grid.cols - 1)
    row = 0 if row < 0 else min(row, grid.rows - 1)
    return row, col


def packs_in(chunks, start=0):
    """Every collision pack among a section's top-level chunks."""
    from world.scenery import with_positions
    return [read_pack(c.data, pos) for c, pos in with_positions(chunks, start) if c.id == COLLISION_PACK]


def triangles(pack):
    """[(p0, p1, p2, surface hash, instance index)] in physics world coordinates."""
    out = []
    for n, inst in enumerate(pack.instances):
        art = pack.articles.get(inst.article)
        if art is None:
            continue
        for s in art.strips:
            w = [inst.to_world(v) for v in s.verts]
            for k in range(len(w) - 2):
                idx = s.surfaces[k]
                h = art.surfaces[idx] if idx < len(art.surfaces) else None
                out.append((w[k], w[k + 1], w[k + 2], h, n))
    return out


def barriers(pack):
    """[(a, b, height, surface hash, instance index)] in physics world coordinates; height = |a.y - b.y| as
    WCollisionBarrier::GetHeight (WCollision.h:198)."""
    out = []
    for n, inst in enumerate(pack.instances):
        art = pack.articles.get(inst.article)
        if art is None:
            continue
        for b in art.barriers:
            pa, pb = inst.to_world(b.p0), inst.to_world(b.p1)
            h = art.surfaces[b.surface] if b.surface < len(art.surfaces) else None
            out.append((pa, pb, abs(pa[1] - pb[1]), h, n))
    return out
