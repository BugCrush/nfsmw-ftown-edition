"""Collision packs (chunk 0x3B801): read into a model with every byte the files carry, written back, and new ones made.

Part 1's reader (tools/world/collision.py) decodes what the game reads; this module also keeps what the writer cannot
derive (EA's tool left memory leftovers in the files: see "kept as data" below) so that all 390 of Rockport's packs
write back byte-identical (tools/world/tests/test_collision_write.py). Layout, checked over all 390 (docs/ftown-
notes.md, "Part 2: writers"; offsets d+N are from the CARP chunk header, i.e. after the chunk's 0x11 run):

    chunk data: 0x11 run to 16 (from the section's start), then
    d+0   bChunkCarpHeader: u32 size (from d+16, = the CARP data rounded up to 256), u32 section number, u32 flags 0,
          u32 last address 0 (the game sets flags 1 and the address when it resolves the pack, WCollisionPack.cpp:46)
    d+16  UGroup 'CARP' (tag, bits 0x2A, 0 data, offset 1)
    d+32  UGroup 'Arti' (tag, bits 0x12, data count, offset 1)
    d+48  UData x count, sorted by tag: 'Name' (bits size << 8 | 2, count 0), 'ca' + index (size << 8 | 3, count 1)
          per article, 'ci' (size << 8 | 3, count = instances); offset = data start - the UData's own address
    0xAA filler up to the next multiple of 256 from d+16, then the name (the section number as text, NUL), 0xAA to 16,
    the articles back to back (each a multiple of 64 bytes), the instances (0x40 each), 0xAA to the CARP size

    article: header (u16 strips, u16 strips size, u16 barriers, u16 barriers size = 32 x n, u8 resolved 0, u8 surfaces,
    u16 surfaces size = 4 x n, u16 intermediate object index, s16 flags), strip spheres (centre 3 floats, u16 radius in
    1/16 m, u16 offset of the strip from the header's end), the strips back to back (8 bytes per vertex: s16 x, y, z
    / 128 from the sphere centre, u16: vertex 0 = the vertex count, vertex 1 = the strip flags, vertex k >= 2 = triangle
    k - 2's surface (u8 index into the article's surfaces, u8 flags)), padding to 16, barriers (point 0: x, y, z,
    u32 surface word; point 1: x, y, z, 1 / horizontal length), surfaces (u32 vlt32 hashes), padding to 64

Kept as data (not derivable): the instances' raw bytes (their +0x10 iteration stamp and +0x1C article pointer are
run-time leftovers in the files) except the article index, which is rewritten; each article's padding bytes after its
strips and after its surfaces (memory leftovers in most), its intermediate object index and flags; the spheres'
centres and radii; each barrier's words (1 / length is not exactly 1 / length in 3,527 of 45,815).

All coordinates are the physics convention (y up), as in the files.
"""
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
for p in (CARBUILD, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk  # noqa: E402

COLLISION_PACK = 0x3B801
TAG_CARP, TAG_ARTI, TAG_NAME = 0x43415250, 0x41727469, 0x4E616D65
TYPE_CA, TYPE_CI, TYPE_CO = 0x6361, 0x6369, 0x636F
ROOT_BITS, ARTI_BITS = 0x2A, 0x12
FILL = 0xAA
ASPHALT = 0x19DB2F1E  # vlt32("asphalt"), docs/ftown-notes.md Task 4
STRIP_UP_RIGHT = 1  # WCollisionStrip kUpFacing: the first triangle tested with InTriR, then alternating
STRIP_EITHER = 2  # kFacingUnknown: every triangle tested with InTri (either winding)
BARRIER_SURFACE_FLAGS = 0x02  # the CollisionSurface flags byte of 41,607 of Rockport's 45,815 barriers
MAX_SPAN = 255.0  # metres a strip vertex may lie from its sphere centre (s16 / 128 = +-256 m)
TILE = 64.0  # metres: the article (instance) size new packs are cut into


@dataclass
class Strip:
    centre: Tuple[float, float, float]  # local
    radius: int  # 1/16 m
    verts: List[Tuple[int, int, int]]  # s16 / 128 from the centre
    flags: int
    surfaces: List[int]  # u16 per triangle (u8 index, u8 flags)

    def points(self):
        c = self.centre
        return [(x / 128.0 + c[0], y / 128.0 + c[1], z / 128.0 + c[2]) for x, y, z in self.verts]


@dataclass
class Barrier:
    p0: Tuple[float, float, float]
    word: int  # u32: u8 surface index, u8 flags, 2 bytes
    p1: Tuple[float, float, float]
    inv_length: float


@dataclass
class Article:
    strips: List[Strip]
    barriers: List[Barrier]
    surfaces: List[int]
    intermediate: int = 0
    flags: int = 0
    strip_pad: bytes = b""  # the bytes between the last strip and the barriers (to 16)
    tail: bytes = b""  # the bytes after the surfaces (to 64)


@dataclass
class Instance:
    raw: bytes  # 0x40 bytes; +0x1A (article index) is rewritten by the writer

    def f(self, off, n=1):
        v = struct.unpack_from("<%df" % n, self.raw, off)
        return v if n > 1 else v[0]

    @property
    def r0(self):
        return self.f(0, 3)

    @property
    def r2(self):
        return self.f(0x20, 3)

    @property
    def t(self):
        return self.f(0x30, 3)

    @property
    def width(self):
        return self.f(0x0C)

    @property
    def length(self):
        return self.f(0x2C)

    @property
    def height(self):
        return self.f(0x14)

    @property
    def radius(self):
        return self.f(0x3C)

    @property
    def flags(self):
        return struct.unpack_from("<H", self.raw, 0x12)[0]

    @property
    def article(self):
        return struct.unpack_from("<H", self.raw, 0x1A)[0]


@dataclass
class Pack:
    section: int
    name: str
    articles: List[Article]
    instances: List[Instance]
    pos: int = 0


# ---------------------------------------------------------------- reading

def _udatas(d):
    _tag, _bits, count, off = struct.unpack_from("<4I", d, 32)
    base = 32 + 16 * off
    out = []
    for i in range(count):
        u = base + 16 * i
        tag, bits, n, o = struct.unpack_from("<4I", d, u)
        out.append((tag, bits, n, u + o, bits >> 8))
    return base, out


def _read_article(a):
    ns, ss, ne, es, resolved, nsu, sus, inter, flags = struct.unpack_from("<4HBBHHh", a, 0)
    if resolved or es != 32 * ne or sus != 4 * nsu:
        raise ValueError("article header not as the writer makes it")
    strips = []
    end = 16 * ns
    for k in range(ns):
        cx, cy, cz, radius, off = struct.unpack_from("<3fHH", a, 16 + 16 * k)
        if off != end:
            raise ValueError("strips are not back to back")
        n = struct.unpack_from("<H", a, 16 + off + 6)[0]
        raw = [struct.unpack_from("<3hH", a, 16 + off + 8 * j) for j in range(n)]
        strips.append(Strip((cx, cy, cz), radius, [v[:3] for v in raw], raw[1][3], [v[3] for v in raw[2:]]))
        end = off + 8 * n
    if ss != (end + 15) // 16 * 16:
        raise ValueError("strips size %d for %d bytes" % (ss, end))
    pad = a[16 + end:16 + ss]
    base = 16 + ss
    barriers = []
    for b in range(ne):
        x0, y0, z0, word, x1, y1, z1, inv = struct.unpack_from("<3fI4f", a, base + 32 * b)
        barriers.append(Barrier((x0, y0, z0), word, (x1, y1, z1), inv))
    sb = base + es
    surfaces = list(struct.unpack_from("<%dI" % nsu, a, sb))
    used = sb + sus
    if len(a) != (used + 63) // 64 * 64:
        raise ValueError("article of %d bytes for %d used" % (len(a), used))
    return Article(strips, barriers, surfaces, inter, flags, pad, a[used:])


def read_pack(chunk_data, pos=0):
    """Pack of a 0x3B801 chunk's data, which starts at `pos` from the section's (2,048-aligned) start."""
    run = (-pos) % 16
    if chunk_data[:run] != b"\x11" * run:
        raise ValueError("collision pack: expected %d bytes of 0x11" % run)
    d = chunk_data[run:]
    size, section, flags, last = struct.unpack_from("<4I", d, 0)
    if flags or last or len(d) != 16 + size:
        raise ValueError("collision pack header not as the writer makes it")
    if struct.unpack_from("<4I", d, 16) != (TAG_CARP, ROOT_BITS, 0, 1):
        raise ValueError("CARP group not as the writer makes it")
    if struct.unpack_from("<2I", d, 32) != (TAG_ARTI, ARTI_BITS) or struct.unpack_from("<I", d, 44)[0] != 1:
        raise ValueError("Arti group not as the writer makes it")
    _base, uds = _udatas(d)
    name, articles, instances = None, [], []
    for tag, bits, n, start, sz in uds:
        data = d[start:start + sz]
        if tag == TAG_NAME:
            name = data.split(b"\0")[0].decode("ascii")
        elif tag >> 16 == TYPE_CA:
            if tag & 0xFFFF != len(articles):
                raise ValueError("articles not numbered 0..n-1 in order")
            articles.append(_read_article(data))
        elif tag >> 16 == TYPE_CI:
            instances = [Instance(data[k:k + 0x40]) for k in range(0, len(data), 0x40)]
        else:
            raise ValueError("collision data 0x%08X the writer does not know" % tag)
    return Pack(section, name, articles, instances, pos)


# ---------------------------------------------------------------- writing

def _article_bytes(art):
    ns = len(art.strips)
    body = bytearray()
    spheres = bytearray()
    for st in art.strips:
        if len(st.verts) < 3 or len(st.surfaces) != len(st.verts) - 2:
            raise ValueError("a strip needs 3+ vertices and a surface per triangle")
        spheres += struct.pack("<3fHH", *st.centre, st.radius, 16 * ns + len(body))
        for j, v in enumerate(st.verts):
            w = len(st.verts) if j == 0 else st.flags if j == 1 else st.surfaces[j - 2]
            body += struct.pack("<3hH", *v, w)
    strips = bytes(spheres) + bytes(body)
    ss = (len(strips) + 15) // 16 * 16
    pad = art.strip_pad if len(art.strip_pad) == ss - len(strips) else bytes(ss - len(strips))
    barriers = b"".join(struct.pack("<3fI4f", *b.p0, b.word, *b.p1, b.inv_length) for b in art.barriers)
    surfaces = struct.pack("<%dI" % len(art.surfaces), *art.surfaces)
    head = struct.pack("<4HBBHHh", ns, ss, len(art.barriers), len(barriers), 0, len(art.surfaces), len(surfaces),
                       art.intermediate, art.flags)
    out = head + strips + pad + barriers + surfaces
    size = (len(out) + 63) // 64 * 64
    tail = art.tail if len(art.tail) == size - len(out) else bytes(size - len(out))
    return out + tail


def write_pack(pack, pos=None):
    """The 0x3B801 Chunk of a Pack whose data will start at `pos` (default: where it was read)."""
    pos = pack.pos if pos is None else pos
    arts = [_article_bytes(a) for a in pack.articles]
    insts = bytearray()
    for k, inst in enumerate(pack.instances):
        r = bytearray(inst.raw)
        struct.pack_into("<H", r, 0x1A, k)
        insts += r
    name = pack.name.encode("ascii") + b"\0"
    count = 1 + len(arts) + 1
    array = 48
    arr_end = array + 16 * count
    name_at = 16 + (arr_end - 16 + 255) // 256 * 256
    blocks = [(TAG_NAME, 2, 0, name)] + [((TYPE_CA << 16) | k, 3, 1, a) for k, a in enumerate(arts)] + \
             [((TYPE_CI << 16), 3, len(pack.instances), bytes(insts))]
    starts = []
    p = name_at
    for i, (_t, _b, _n, data) in enumerate(blocks):
        starts.append(p)
        p += len(data)
        if i == 0:
            p = (p + 15) // 16 * 16
    end = p
    size = (end - 16 + 255) // 256 * 256
    d = bytearray([FILL]) * (16 + size)
    struct.pack_into("<4I", d, 0, size, pack.section, 0, 0)
    struct.pack_into("<4I", d, 16, TAG_CARP, ROOT_BITS, 0, 1)
    struct.pack_into("<4I", d, 32, TAG_ARTI, ARTI_BITS, count, 1)
    for i, ((tag, bits, n, data), start) in enumerate(zip(blocks, starts)):
        u = array + 16 * i
        struct.pack_into("<4I", d, u, tag, (len(data) << 8) | bits, n, start - u)
        d[start:start + len(data)] = data
    return Chunk(COLLISION_PACK, b"\x11" * ((-pos) % 16) + bytes(d))


# ---------------------------------------------------------------- new packs

def grid_faces(x0, z0, x1, z1, y, step):
    """A flat rectangle at height y (physics) as triangles in rows of `step` cells, in strip order."""
    out = []
    nx = int(round((x1 - x0) / step))
    nz = int(round((z1 - z0) / step))
    for j in range(nz):
        za, zb = z0 + j * step, z0 + (j + 1) * step
        for i in range(nx):
            xa, xb = x0 + i * step, x0 + (i + 1) * step
            a, b, c, e = (xa, y, za), (xa, y, zb), (xb, y, za), (xb, y, zb)
            out += [(a, b, c), (b, c, e)]
    return out


def ramp_faces(x0, z0, x1, z1, y0, y1, step):
    """A ramp from x0 (height y0) to x1 (height y1), z0..z1 wide, in rows of `step` along x (strip order)."""
    out = []
    n = int(round((x1 - x0) / step))
    for i in range(n):
        xa, xb = x0 + i * step, x0 + (i + 1) * step
        ya, yb = y0 + (y1 - y0) * i / n, y0 + (y1 - y0) * (i + 1) / n
        a, b, c, e = (xa, ya, z0), (xa, ya, z1), (xb, yb, z0), (xb, yb, z1)
        out += [(a, b, c), (b, c, e)]
    return out


def _pt_dir(p1, p2, t):
    """PtDir4 (WWorldMath.h:38) in the xz plane."""
    return (p1[0] - p2[0]) * (t[2] - p2[2]) - (t[0] - p2[0]) * (p1[2] - p2[2])


def _right(tri):
    """True when InTriR (every PtDir4 <= 0) holds for the triangle's interior."""
    c = tuple(sum(p[a] for p in tri) / 3.0 for a in range(3))
    return _pt_dir(tri[0], tri[1], c) <= 0


def _strips(tris):
    """Join triangles in order into strips: the next triangle joins when it holds the strip's last two vertices and
    winds the other way from the strip's last triangle (as MakeNextFace and FindFaceInTriStrip's alternating test
    expect, WCollisionMgr.cpp:77-104). Each strip: (vertices, first triangle InTriR)."""
    return [(v, r) for v, r, _i in _strips_indexed(tris)]


def _strips_indexed(tris):
    """_strips, each strip also with the input index of every triangle it holds, in order."""
    out = []
    for n, t in enumerate(tris):
        if out:
            verts, right, idx = out[-1]
            a, b = verts[-2], verts[-1]
            if a in t and b in t and len(verts) < 64:
                new = [p for p in t if p != a and p != b]
                if len(new) == 1:
                    k = len(verts) - 2  # this triangle's number in the strip
                    want = right if k % 2 == 0 else not right
                    cand = verts + [new[0]]
                    span = _box(cand)
                    if _right((a, b, new[0])) == want and max(span[3 + i] - span[i] for i in range(3)) < 2 * MAX_SPAN:
                        verts.append(new[0])
                        idx.append(n)
                        continue
        out.append(([t[0], t[1], t[2]], _right(t), [n]))
    return out


def _box(pts):
    return tuple(min(p[a] for p in pts) for a in range(3)) + tuple(max(p[a] for p in pts) for a in range(3))


def _q(v, unit=1 / 128.0):
    return round(v / unit) * unit


def _article(tris, barriers, centre, surface, tri_surfaces=None, tri_flags=None):
    """One article: `surface` for the barriers and (without tri_surfaces) every face; tri_surfaces, one hash per
    triangle, gives each face its own (the article lists each hash once; a face's word is its index); tri_flags, one
    byte per triangle, goes in the word's high byte (the CollisionSurface flags: 4 = the wheels' query does not stop
    at this face but looks on for the closest, WWorldPos::FindClosestFace(WCollisionTriList) 0x779170; Rockport sets
    it where faces lie over each other). A barrier is (a, b, bottom, top) or (a, b, bottom, top, flags): flags 0x02
    (default, 41,607 of Rockport's) blocks only bodies on the side its normal points to (the right of a -> b in
    render coordinates), 0x12 blocks both sides (WCollisionMgr::Collide, WCollisionMgr.cpp:774)."""
    surfaces = [surface]
    if tri_surfaces is not None:
        for h in tri_surfaces:
            if h not in surfaces:
                surfaces.append(h)
        if len(surfaces) > 255:
            raise ValueError("more than 255 surfaces in an article")
    strips = []
    for verts, right, idx in _strips_indexed(tris):
        local = [(p[0] - centre[0], p[1] - centre[1], p[2] - centre[2]) for p in verts]
        b = _box(local)
        c = tuple(_q((b[a] + b[3 + a]) / 2) for a in range(3))
        q = []
        for p in local:
            v = tuple(int(round((p[a] - c[a]) * 128)) for a in range(3))
            if not all(-32768 <= x <= 32767 for x in v):
                raise ValueError("a strip vertex lies more than 256 m from its centre")
            q.append(v)
        far = max(math.hypot(x / 128.0, z / 128.0) for x, _y, z in q)
        words = [0] * (len(q) - 2) if tri_surfaces is None else [surfaces.index(tri_surfaces[i]) for i in idx]
        if tri_flags is not None:
            words = [w | (tri_flags[i] << 8) for w, i in zip(words, idx)]
        strips.append(Strip(c, min(0xFFFF, int(math.ceil(far * 16)) + 1), q, STRIP_UP_RIGHT if right else 0, words))
    bars = []
    for bar in barriers:
        a, b, bottom, top = bar[:4]
        flags = bar[4] if len(bar) > 4 else BARRIER_SURFACE_FLAGS
        p0 = (a[0] - centre[0], bottom - centre[1], a[1] - centre[2])
        p1 = (b[0] - centre[0], top - centre[1], b[1] - centre[2])
        length = math.hypot(p1[0] - p0[0], p1[2] - p0[2])
        bars.append(Barrier(p0, flags << 8, p1, 1.0 / length))
    return Article(strips, bars, surfaces)


def _instance(centre, pts, article):
    w = max(abs(p[0]) for p in pts) + 0.01
    h = max(abs(p[1]) for p in pts) + 1.0
    L = max(abs(p[2]) for p in pts) + 0.01
    raw = struct.pack("<4fHHfHHI4f4f", 1.0, 0.0, 0.0, w, 0, 0, h, 0, article, 0, 0.0, 0.0, 1.0, L,
                      -centre[0], -centre[1], -centre[2], math.hypot(w, L))
    return Instance(raw)


def make_pack(section_number, faces, barriers, surface=ASPHALT, tile=TILE, face_surfaces=None, face_flags=None):
    """A Pack for `section_number` from triangles (p0, p1, p2) and barriers ((x0, z0), (x1, z1), bottom, top[, flags]),
    all physics. Cut into `tile` m tiles (64 by default) by each triangle's centre (a barrier by its midpoint); one
    article and one instance per tile (identity rotation, the instance's origin at the tile's geometry centre, box =
    the geometry's extents + 0.01 m (height + 1 m), radius = hypot(width, length) as Rockport's); triangles joined into
    strips in the order given. face_surfaces: one surface hash per face (default: `surface` for all); face_flags: one
    flags byte per face (default 0; see _article)."""
    tiles = {}

    def key(x, z):
        return (int(math.floor(x / tile)), int(math.floor(z / tile)))

    if face_surfaces is not None and len(face_surfaces) != len(faces):
        raise ValueError("%d faces, %d surfaces" % (len(faces), len(face_surfaces)))
    if face_flags is not None and len(face_flags) != len(faces):
        raise ValueError("%d faces, %d flags" % (len(faces), len(face_flags)))
    for n, t in enumerate(faces):
        cx = sum(p[0] for p in t) / 3.0
        cz = sum(p[2] for p in t) / 3.0
        e = tiles.setdefault(key(cx, cz), ([], [], [], []))
        e[0].append(t)
        e[2].append(surface if face_surfaces is None else face_surfaces[n])
        e[3].append(0 if face_flags is None else face_flags[n])
    for bar in barriers:
        a, b = bar[0], bar[1]
        tiles.setdefault(key((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), ([], [], [], []))[1].append(bar)
    articles, instances = [], []
    for k in sorted(tiles):
        tris, bars, surfs, flags = tiles[k]
        pts = [p for t in tris for p in t]
        for bar in bars:
            a, b, lo, hi = bar[:4]
            pts += [(a[0], lo, a[1]), (b[0], hi, b[1])]
        bx = _box(pts)
        centre = tuple(_q((bx[a] + bx[3 + a]) / 2, 0.25) for a in range(3))
        art = _article(tris, bars, centre, surface, None if face_surfaces is None else surfs,
                       None if face_flags is None else flags)
        local = []
        for st in art.strips:
            local += st.points()
        for b in art.barriers:
            local += [b.p0, b.p1]
        instances.append(_instance(centre, local, len(articles)))
        articles.append(art)
    return Pack(section_number, str(section_number), articles, instances, 0)
