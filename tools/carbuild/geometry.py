"""GEOMETRY.BIN (a car's model) to a GeometryPack and back.

Layout of the game's own packs (all of them round-trip byte-identical through `write_geometry`; docs/carbuild-format.md):

    0x80134000 solid list
        0x00000000 (empty)
        0x80134001 header: 0x134002 info (144 bytes), 0x134003 index (hash, 0 per solid, sorted by hash),
                           0x134004 directory (hash, file offset, size, size, 0, 0 per solid, sorted by hash),
                           0x80134008 (empty)
        0x00000000 padding so the next solid starts at a multiple of 128 in the file
        0x80134010 solid, padding, solid, ... (the last solid is not padded inside the list)
    then the top-level chunks after the list (kept as they were read: `GeometryPack.extra`)

A solid holds 0x134011 header (the name at +0xA0), 0x134012 texture hashes, 0x134013 shader hashes, optionally
0x13401A, the mesh container 0x80134100 (0x134900 mesh header, 0x134B02 mesh entries, 0x134B03 indices, 0x134B01
vertices, one 0x134C02 name per mesh), and optionally 0x134017..0x134019. Some leaves start with a run of 0x11 bytes
that aligns their data in the file (16 or 128 bytes); the reader drops the run and the writer puts it back where the
data lands, so the fields here hold data only.

Compressed packs (the add-on tools' packs) hold each solid in its own JDLZ block, found through the directory; they
read into the same GeometryPack and are written back uncompressed in the game's layout unless `compressed=True`.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

import jdlz
from chunks import Chunk, bstringhash, read_chunks, write_chunks, chunk_bytes

SOLID_LIST = 0x80134000
HEADER = 0x80134001
INFO = 0x134002
INDEX = 0x134003
DIRECTORY = 0x134004
HEADER_END = 0x80134008
SOLID = 0x80134010
SOLID_HEADER = 0x134011
TEXTURES = 0x134012
SHADERS = 0x134013
SOLID_1A = 0x13401A
MESHES = 0x80134100
MESH_HEADER = 0x134900
VERTICES = 0x134B01
ENTRIES = 0x134B02
INDICES = 0x134B03
MESH_NAME = 0x134C02

NAME_AT = 0xA0  # the solid's name in 0x134011, after the fixed header
ENTRY_SIZE = 104
SOLID_ALIGN = 128
# leaves whose data is aligned in the file by a leading run of 0x11 bytes
ALIGN = {SOLID_1A: 16, MESH_HEADER: 16, ENTRIES: 16, INDICES: 16, VERTICES: 128}
COMPRESSED_FLAG = 0x100


VERTEX_STRIDE = 36  # every mesh of every game and add-on car (docs/carbuild-format.md)
VERTEX = struct.Struct("<3f3f4s2f")  # position, normal, colour (D3DCOLOR, B G R A), uv


@dataclass
class Mesh:
    """One 104-byte mesh entry of 0x134B02 (fields at: bbox +0x00, texture slots +0x18..+0x1C, shader +0x1D,
    flags +0x38, vertex count +0x3C, triangle count +0x40, index offset +0x44, index count +0x5C). The mesh's
    vertices follow those of the meshes before it (`vertex_offset`); its indices count from the solid's first vertex.
    """
    texture_index: int
    shader_index: int
    vertex_offset: int
    vertex_count: int
    index_offset: int
    index_count: int
    stride: int
    flags: int
    raw: bytes
    texture_slots: tuple = ()
    triangle_count: int = 0

    @property
    def bbox(self):
        return struct.unpack_from("<6f", self.raw, 0)

    def to_raw(self, bbox=None):
        """The 104 bytes with this mesh's decoded fields written over `raw` (`texture_index` is slot 0)."""
        if len(self.raw) != ENTRY_SIZE:
            raise ValueError("mesh entry: %d bytes, must be %d" % (len(self.raw), ENTRY_SIZE))
        if len(self.texture_slots) != 5:
            raise ValueError("mesh entry: %d texture slots, must be 5" % len(self.texture_slots))
        out = bytearray(self.raw)
        if bbox is not None:
            struct.pack_into("<6f", out, 0, *bbox)
        out[0x18:0x1D] = bytes((self.texture_index,) + tuple(self.texture_slots[1:]))
        out[0x1D] = self.shader_index
        struct.pack_into("<I", out, 0x38, self.flags)
        struct.pack_into("<3I", out, 0x3C, self.vertex_count, self.triangle_count, self.index_offset)
        struct.pack_into("<I", out, 0x5C, self.index_count)
        return bytes(out)

    @classmethod
    def parse(cls, raw, vertex_offset):
        vc, tc, io = struct.unpack_from("<3I", raw, 0x3C)
        return cls(texture_index=raw[0x18], shader_index=raw[0x1D], vertex_offset=vertex_offset, vertex_count=vc,
                   index_offset=io, index_count=struct.unpack_from("<I", raw, 0x5C)[0], stride=VERTEX_STRIDE,
                   flags=struct.unpack_from("<I", raw, 0x38)[0], raw=raw, texture_slots=tuple(raw[0x18:0x1D]),
                   triangle_count=tc)


@dataclass
class Solid:
    name: str
    name_hash: int
    header: bytes
    textures: Optional[List[int]]
    shaders: Optional[List[int]]
    mesh_header: Optional[bytes]
    mesh_entries: Optional[List[bytes]]
    vertices: Optional[bytes]  # None in one game solid that has no vertex chunk
    indices: Optional[bytes]
    other: List[Chunk] = field(default_factory=list)
    mesh_names: List[str] = field(default_factory=list)

    @property
    def bbox(self):
        """min x, y, z, max x, y, z (header +0x20)."""
        v = struct.unpack_from("<8f", self.header, 0x20)
        return v[0:3] + v[4:7]

    def meshes(self):
        out, offset = [], 0
        for raw in self.mesh_entries or []:
            m = Mesh.parse(raw, offset)
            out.append(m)
            offset += m.vertex_count
        return out

    def _vertices(self, mesh):
        start = mesh.vertex_offset * VERTEX_STRIDE
        return VERTEX.iter_unpack(self.vertices[start:start + mesh.vertex_count * VERTEX_STRIDE])

    def positions(self, mesh):
        return [v[0:3] for v in self._vertices(mesh)]

    def normals(self, mesh):
        return [v[3:6] for v in self._vertices(mesh)]

    def colors(self, mesh):
        """Vertex colours as (r, g, b, a) bytes (stored as D3DCOLOR: b, g, r, a)."""
        return [(v[6][2], v[6][1], v[6][0], v[6][3]) for v in self._vertices(mesh)]

    def uvs(self, mesh):
        return [v[7:9] for v in self._vertices(mesh)]

    def triangles(self, mesh):
        """Triangle list (the format stores lists: index count = 3 x triangle count everywhere), as indices into the
        mesh's own vertices (index - vertex_offset)."""
        idx = struct.unpack_from("<%dH" % mesh.index_count, self.indices, mesh.index_offset * 2)
        o = mesh.vertex_offset
        return [(idx[k] - o, idx[k + 1] - o, idx[k + 2] - o) for k in range(0, len(idx), 3)]


BBOX_MARGIN = 0.01  # the game's tools store each solid's box as the vertex extents + 0.01 m (docs/carbuild-format.md)


def extents_bbox(s, margin=BBOX_MARGIN):
    """The solid's box by the game's convention: its vertex extents grown by `margin` on every side."""
    ps = [p for m in s.meshes() for p in s.positions(m)]
    if not ps:
        return tuple(s.bbox)
    lo = [min(p[a] for p in ps) - margin for a in range(3)]
    hi = [max(p[a] for p in ps) + margin for a in range(3)]
    return tuple(lo + hi)


def _expected(s):
    """(mesh header fields +0x0C flags OR, +0x10 count, +0x2C total indices; padded indices; box) for a solid."""
    ms = s.meshes()
    flags = 0
    for m in ms:
        flags |= m.flags
    total = len(s.indices) // 2 if s.indices is not None else 0
    if s.indices is not None and ms:
        total = max(m.index_offset + m.index_count for m in ms)
    indices = s.indices
    if indices is not None:
        indices = indices[:total * 2] + bytes((-total * 2) % 4)
    return flags, len(ms), total, indices, extents_bbox(s)


def check(s):
    """Disagreements between a solid's bookkeeping and its meshes (empty list = consistent): the mesh header's
    flags OR, mesh count and index total, the indices' 4-byte padding, and the box (extents + 0.01 m, 0.1 mm)."""
    out = []
    if s.mesh_header is None or s.mesh_entries is None:
        return out
    flags, count, total, indices, bbox = _expected(s)
    mh = struct.unpack_from("<12I", s.mesh_header)
    if mh[3] != flags:
        out.append("%s: mesh header flags 0x%X, meshes OR to 0x%X" % (s.name, mh[3], flags))
    if mh[4] != count:
        out.append("%s: mesh header count %d, %d meshes" % (s.name, mh[4], count))
    if mh[11] != total:
        out.append("%s: mesh header index total %d, meshes use %d" % (s.name, mh[11], total))
    if indices != s.indices:
        out.append("%s: indices %d bytes, expected %d (padded to 4)" % (s.name, len(s.indices), len(indices)))
    if s.vertices and any(abs(a - b) > 1e-4 for a, b in zip(s.bbox, bbox)):
        out.append("%s: box %s, vertex extents + 0.01 give %s" % (s.name, tuple(round(x, 4) for x in s.bbox),
                                                                  tuple(round(x, 4) for x in bbox)))
    return out


def finalize(s):
    """Fill in a solid's bookkeeping from its meshes, as the game's tools do: the mesh header's flags OR (+0x0C),
    mesh count (+0x10) and index total (+0x2C), the indices' padding to 4 bytes, and the box (extents + 0.01 m).
    For parts we build or edit; the game's own solids already agree (`check` is empty for them)."""
    if s.mesh_header is None or s.mesh_entries is None:
        return s
    flags, count, total, indices, bbox = _expected(s)
    mh = bytearray(s.mesh_header)
    struct.pack_into("<I", mh, 0x0C, flags)
    struct.pack_into("<I", mh, 0x10, count)
    struct.pack_into("<I", mh, 0x2C, total)
    s.mesh_header = bytes(mh)
    s.indices = indices
    if s.vertices and any(abs(a - b) > 1e-4 for a, b in zip(s.bbox, bbox)):
        # a box already within 0.1 mm is kept: the game's tools round in single precision, one unit apart
        s.header = solid_header(s.header, s.name, s.name_hash, bbox)
    return s


def solid_header(header, name, name_hash, bbox):
    """A 0x134011 header with these name, hash and bounding box written over `header` (the name is zero-terminated
    and padded to a multiple of 4, as in every game pack)."""
    out = bytearray(header[:NAME_AT])
    struct.pack_into("<I", out, 0x10, name_hash)
    struct.pack_into("<3f", out, 0x20, *bbox[0:3])
    struct.pack_into("<3f", out, 0x30, *bbox[3:6])
    raw = name.encode("ascii") + b"\0"
    return bytes(out) + raw + bytes((-len(raw)) % 4)


@dataclass
class GeometryPack:
    info: bytes
    solids: List[Solid]
    extra: List[Chunk] = field(default_factory=list)  # top-level chunks after the solid list


# ---------------------------------------------------------------- reading

def _hashes(data):
    return [struct.unpack_from("<I", data, k)[0] for k in range(0, len(data), 8)]


def _unpad(cid, data, pos):
    """Data of an aligned leaf without its 0x11 run; `pos` is where the leaf's data starts, relative to an aligned
    origin (the solid's start)."""
    run = (-pos) % ALIGN[cid]
    if data[:run] not in (b"\x11" * run, bytes(run)):  # the Raptor add-on's tool pads with zeros
        raise ValueError("chunk 0x%X: expected %d alignment bytes at +%d" % (cid, run, pos))
    return data[run:]


def _read_solid(solid_chunk):
    """A Solid from a 0x80134010 chunk; leaf positions are measured from the solid chunk's own start."""
    f = dict(textures=None, shaders=None, other=[], mesh_names=[], mesh_header=None, mesh_entries=None, vertices=None,
             indices=None)
    pos = 8  # past the solid chunk's header
    for c in solid_chunk.children:
        body = pos + 8
        if c.id == SOLID_HEADER:
            f["header"] = c.data
        elif c.id == TEXTURES:
            f["textures"] = _hashes(c.data)
        elif c.id == SHADERS:
            f["shaders"] = _hashes(c.data)
        elif c.id == SOLID_1A:
            f["other"].append(Chunk(c.id, _unpad(c.id, c.data, body)))
        elif c.id == MESHES:
            mpos = body
            for m in c.children:
                mbody = mpos + 8
                if m.id == MESH_HEADER:
                    f["mesh_header"] = _unpad(m.id, m.data, mbody)
                elif m.id == ENTRIES:
                    raw = _unpad(m.id, m.data, mbody)
                    if len(raw) % ENTRY_SIZE:
                        raise ValueError("mesh entries: %d bytes is not a multiple of 104" % len(raw))
                    f["mesh_entries"] = [raw[k:k + ENTRY_SIZE] for k in range(0, len(raw), ENTRY_SIZE)]
                elif m.id == INDICES:
                    f["indices"] = _unpad(m.id, m.data, mbody)
                elif m.id == VERTICES:
                    f["vertices"] = _unpad(m.id, m.data, mbody)
                elif m.id == MESH_NAME:
                    f["mesh_names"].append(m.data.split(b"\0")[0].decode("ascii"))
                else:
                    raise ValueError("unknown chunk 0x%X in a mesh container" % m.id)
                mpos = mbody + len(m.data)
        else:
            f["other"].append(c)
        pos = body + len(chunk_bytes(c)) - 8
    header = f["header"]
    name = header[NAME_AT:].split(b"\0")[0].decode("ascii")
    return Solid(name=name, name_hash=struct.unpack_from("<I", header, 0x10)[0], **f)


def _read_compressed_list(raw):
    """The solid list of a compressed pack: its header chunks, then JDLZ blocks at the directory's offsets."""
    head = []
    off = 0
    while off < len(raw):
        cid, size = struct.unpack_from("<II", raw, off)
        if cid == HEADER:
            head = read_chunks(raw[off:off + 8 + size])
            break
        off += 8 + size
    return head


def read_geometry(data):
    top = read_chunks(data)
    lists = [c for c in top if c.id == SOLID_LIST]
    if not lists:
        raise ValueError("no solid list (0x80134000)")
    sl = lists[0]
    extra = top[top.index(sl) + 1:]
    solids = []
    if sl.children is not None:
        header = [c for c in sl.children if c.id == HEADER][0]
        solid_chunks = [c for c in sl.children if c.id == SOLID]
        if any(c.id == SOLID for c in extra):
            # the Chiron add-on keeps its solids beside the list (after a 0x80134008), each behind padding: they are
            # taken into the pack, and written back inside the list in the game's layout
            solid_chunks += [c for c in extra if c.id == SOLID]
            extra = [c for c in extra if c.id not in (SOLID, 0, HEADER_END)]
        solids = [_read_solid(c) for c in solid_chunks]
    else:
        # compressed: the list's bytes are the header chunks followed by JDLZ blocks (offsets from the file start)
        header = _read_compressed_list(sl.data)[0]
        directory = [c for c in header.children if c.id == DIRECTORY][0].data
        entries = [struct.unpack_from("<6I", directory, k) for k in range(0, len(directory), 24)]
        for h, off, csize, usize, flags, _ in sorted(entries, key=lambda e: e[1]):
            block = data[off:off + csize]
            raw = jdlz.decompress(block) if flags & COMPRESSED_FLAG else block
            if len(raw) != usize:
                raise ValueError("block at 0x%X: %d bytes, directory says %d" % (off, len(raw), usize))
            solids.append(_read_solid(read_chunks(raw[:8 + struct.unpack_from("<I", raw, 4)[0]])[0]))
        extra = []
    info = [c for c in header.children if c.id == INFO][0].data
    return GeometryPack(info=info, solids=solids, extra=extra)


# ---------------------------------------------------------------- writing

def pad_chunk(pos, align):
    """An id-0 chunk that makes the next chunk start at a multiple of `align` (b"" when it already does)."""
    gap = (-pos) % align
    if gap == 0:
        return b""
    if gap < 8:
        gap += align
    return struct.pack("<II", 0, gap - 8) + bytes(gap - 8)


def _leaf(cid, data):
    return struct.pack("<II", cid, len(data)) + data


def _aligned_leaf(cid, data, pos):
    """A leaf whose data starts aligned; `pos` is where the chunk's header goes (relative to an aligned origin)."""
    run = (-(pos + 8)) % ALIGN[cid]
    return _leaf(cid, b"\x11" * run + data)


def _name_chunk(name):
    raw = name.encode("ascii") + b"\0"
    raw += bytes((-len(raw)) % 4)
    return _leaf(MESH_NAME, raw)


def solid_bytes(s):
    """The 0x80134010 chunk of a solid, laid out as if it starts at an aligned offset."""
    out = bytearray(8)
    out += _leaf(SOLID_HEADER, s.header)
    if s.textures is not None:
        out += _leaf(TEXTURES, b"".join(struct.pack("<II", h, 0) for h in s.textures))
    if s.shaders is not None:
        out += _leaf(SHADERS, b"".join(struct.pack("<II", h, 0) for h in s.shaders))
    after = []
    for c in s.other:
        if c.id == SOLID_1A:
            out += _aligned_leaf(c.id, c.data, len(out))
        else:
            after.append(c)
    mstart = len(out)
    out += bytes(8)
    for cid, data in ((MESH_HEADER, s.mesh_header),
                      (ENTRIES, None if s.mesh_entries is None else b"".join(s.mesh_entries)),
                      (INDICES, s.indices), (VERTICES, s.vertices)):
        if data is not None:
            out += _aligned_leaf(cid, data, len(out))
    for n in s.mesh_names:
        out += _name_chunk(n)
    struct.pack_into("<II", out, mstart, MESHES, len(out) - mstart - 8)
    for c in after:
        out += chunk_bytes(c)
    struct.pack_into("<II", out, 0, SOLID, len(out) - 8)
    return bytes(out)


def _header_chunk(info, solids, offsets, sizes, usizes, flags):
    order = sorted(range(len(solids)), key=lambda k: solids[k].name_hash)
    index = b"".join(struct.pack("<II", solids[k].name_hash, 0) for k in order)
    directory = b"".join(struct.pack("<6I", solids[k].name_hash, offsets[k], sizes[k], usizes[k], flags, 0)
                         for k in order)
    return write_chunks([Chunk(HEADER, None, [Chunk(INFO, info), Chunk(INDEX, index), Chunk(DIRECTORY, directory),
                                              Chunk(HEADER_END, None, [])])])


def write_geometry(pack, compressed=False):
    """Bytes of a GEOMETRY.BIN in the game's layout (or with literal JDLZ blocks when `compressed`)."""
    info = bytearray(pack.info)
    struct.pack_into("<I", info, 0x0C, len(pack.solids))
    blobs = [solid_bytes(s) for s in pack.solids]
    if compressed:
        blobs_out = [jdlz.compress_literal(b) for b in blobs]
        flags = COMPRESSED_FLAG
    else:
        blobs_out = blobs
        flags = 0
    n = len(pack.solids)
    zero = [0] * n
    # the header's size does not depend on the offsets, so lay out once with zeros, then fill them in
    head_len = len(_header_chunk(bytes(info), pack.solids, zero, zero, zero, flags))
    pos = 8 + 8 + head_len  # list header, empty id-0 chunk, header
    offsets, body = [], bytearray()
    for k, b in enumerate(blobs_out):
        pad = pad_chunk(pos, SOLID_ALIGN)
        body += pad
        pos += len(pad)
        offsets.append(pos)
        body += b
        pos += len(b)
    if compressed:
        tail = pad_chunk(pos, SOLID_ALIGN)
        body += tail
        pos += len(tail)
    extra = write_chunks(pack.extra)
    total = pos + len(extra)
    if not compressed:
        struct.pack_into("<I", info, 0x68, total)
    header = _header_chunk(bytes(info), pack.solids, offsets, [len(b) for b in blobs_out], [len(b) for b in blobs],
                           flags)
    content = bytes(8) + header + bytes(body)
    return struct.pack("<II", SOLID_LIST, len(content)) + content + extra
