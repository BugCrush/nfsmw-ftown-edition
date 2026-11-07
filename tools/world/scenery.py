"""What a streaming section draws: its scenery sections (0x80034100) and its world solids (0x80134000), read only.

A streaming section of STREAML2RA.BUN (tools/world/bun.py) is a run of top-level chunks: texture packs (0xB3300000),
solid lists (0x80134000), one or more scenery sections (0x80034100: a drivable section and its LOD section travel
together, e.g. A41 holds A1 and A41), and per-section packs (0x3B801 collision, 0x80036000 triggers, 0x34159,
0x34027, ...).

Scenery records (decompilation World/Scenery.hpp; loader LoaderScenery, World/Scenery.cpp:265-430):
- 0x34101 ScenerySectionHeader (0x3C): +0x0C section number, +0x10 polygons in memory, +0x14 polygons in world.
- 0x34102 SceneryInfo (0x48 each, Scenery.hpp:167): +0x00 debug name (24), +0x18 four solid name hashes (detail
  levels high, medium, low, reflection), +0x28 four model pointers (run time), +0x38 radius, +0x3C mesh checksum,
  +0x40 hierarchy name hash.
- 0x34103 SceneryInstance (0x40 each, data aligned to 16: GetAlignedData(16), Scenery.cpp:323; Scenery.hpp:40-113):
  +0x00 bbox min (3 floats), +0x0C bbox max, +0x18 exclude flags, +0x1C s16 preculler info, +0x1E s16 lighting
  context, +0x20 position (3 floats), +0x2C rotation (9 s16, x 1/8192 = a 3x3 matrix, rows v0 v1 v2), +0x3E s16 info
  number (into this scenery section's infos).
- 0x34105 SceneryTreeNode (0x24 each): bbox (6 floats), s16 child count, 5 s16 child codes.
- 0x34106 override hooks (4 each), 0x34107 preculler infos (0x80 each).

World solids differ from the car format (docs/carbuild-format.md) in ways recorded in docs/ftown-notes.md and checked
over every section in tools/world/tests/test_scenery.py; `read_solid` reads them here instead of
tools/carbuild/geometry.py.
"""
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
if CARBUILD not in sys.path:
    sys.path.insert(0, CARBUILD)

from chunks import Chunk, chunk_bytes  # noqa: E402

SCENERY_SECTION = 0x80034100
SCENERY_HEADER = 0x34101
SCENERY_INFOS = 0x34102
SCENERY_INSTANCES = 0x34103
SCENERY_TREE = 0x34105
SCENERY_HOOKS = 0x34106
PRECULLER = 0x34107

SOLID_LIST = 0x80134000
LIST_HEADER = 0x80134001
LIST_INFO = 0x134002
LIST_INDEX = 0x134003
LIST_DIRECTORY = 0x134004
SOLID = 0x80134010
SOLID_HEADER = 0x134011
TEXTURES = 0x134012
SHADERS = 0x134013
MESHES = 0x80134100
MESH_HEADER = 0x134900
VERTICES = 0x134B01
ENTRIES = 0x134B02
INDICES = 0x134B03
MESH_NAME = 0x134C02

# leaves whose data starts with a run of 0x11 bytes aligning it in memory (section data is loaded 2,048-aligned, so
# positions from the section's start count); found over every section (test_scenery.py)
ALIGN = {SCENERY_INSTANCES: 16, SOLID_HEADER: 16, 0x13401A: 16, MESH_HEADER: 16, ENTRIES: 16, INDICES: 16,
         VERTICES: 128}
VERTEX_STRIDE = 36
NAME_AT = 0xA0
NO_MODEL = (0, 0xBE43EDBB, 0x90F70174)  # name hashes LoaderScenery skips (Scenery.cpp:396)


def unpad(cid, data, pos):
    """data without its alignment run; `pos` = the data's position from an aligned origin."""
    a = ALIGN.get(cid)
    if not a:
        return data
    run = (-pos) % a
    if data[:run] != b"\x11" * run:
        raise ValueError("chunk 0x%X at +0x%X: expected %d bytes of 0x11" % (cid, pos, run))
    return data[run:]


def with_positions(chunks, start):
    """(chunk, data position) for each chunk of a list starting at `start`."""
    out = []
    pos = start
    for c in chunks:
        out.append((c, pos + 8))
        pos += len(chunk_bytes(c))
    return out


@dataclass
class Info:
    name: str
    solid_hashes: tuple
    radius: float
    checksum: int
    hierarchy: int


@dataclass
class Instance:
    info_index: int
    matrix: tuple  # 4x4 row-major: rows v0, v1, v2 (rotation), v3 (position, 1)
    bbox: tuple
    exclude_flags: int
    preculler: int
    lighting: int

    @property
    def position(self):
        """The matrix's translation. (0, 0, 0) for most terrain/road instances, whose solids are stored in world
        coordinates (docs/ftown-notes.md); use `centre` for where an instance is."""
        return self.matrix[3][:3]

    @property
    def centre(self):
        """Centre of the instance's world box (+0x00..+0x17)."""
        return tuple((self.bbox[a] + self.bbox[3 + a]) / 2 for a in range(3))


@dataclass
class Scenery:
    number: int
    header: bytes
    infos: List[Info]
    instances: List[Instance]
    tree: bytes
    other: Dict[int, bytes] = field(default_factory=dict)


@dataclass
class Mesh:
    raw: bytes
    bbox: tuple
    texture_slots: tuple
    shader_index: int
    flags: int
    vertex_count: int
    triangle_count: int
    index_offset: int
    index_count: int
    kind: int = 0  # +0x30: the vertex format group (0, 5, 6: 36 bytes; 1, 3: 60 bytes; 19: 44 bytes)
    buffer: int = 0  # which vertex buffer (0x134B01) of the solid this mesh reads
    vertex_offset: int = 0  # first vertex of this mesh inside its buffer


@dataclass
class Solid:
    name: str
    name_hash: int
    header: bytes
    textures: List[int]
    shaders: Optional[List[int]]
    mesh_header: Optional[bytes]
    meshes: List[Mesh]
    vertex_buffers: List[bytes]
    indices: Optional[bytes]
    mesh_names: List[str]
    other: List[Chunk] = field(default_factory=list)

    @property
    def bbox(self):
        v = struct.unpack_from("<8f", self.header, 0x20)
        return v[0:3] + v[4:7]

    def stride(self, b):
        """Bytes per vertex of buffer b: its length / the vertex count of the meshes reading it."""
        n = sum(m.vertex_count for m in self.meshes if m.buffer == b)
        return len(self.vertex_buffers[b]) // n if n else 0

    def positions(self, k):
        """Vertex positions of mesh k (the first 12 bytes of every vertex, whatever the stride)."""
        m = self.meshes[k]
        buf, st = self.vertex_buffers[m.buffer], self.stride(m.buffer)
        return [struct.unpack_from("<3f", buf, (m.vertex_offset + i) * st) for i in range(m.vertex_count)]

    def triangles(self, k):
        """Triangle list of mesh k as indices into its own vertices (0 = the mesh's first vertex)."""
        m = self.meshes[k]
        idx = struct.unpack_from("<%dH" % m.index_count, self.indices, m.index_offset * 2)
        o = m.vertex_offset
        return [(idx[i] - o, idx[i + 1] - o, idx[i + 2] - o) for i in range(0, len(idx), 3)]

    def world_triangles(self, matrix):
        """Every triangle of the solid placed by an instance matrix: [(p0, p1, p2, mesh index)]."""
        out = []
        for k in range(len(self.meshes)):
            ps = [transform(matrix, p) for p in self.positions(k)]
            for a, b, c in self.triangles(k):
                out.append((ps[a], ps[b], ps[c], k))
        return out


def assign_buffers(meshes):
    """World solids keep one vertex buffer per run of consecutive meshes with the same +0x30 kind (all 20,377
    solids of Rockport, test_scenery.py): set each mesh's buffer and its first vertex in that buffer."""
    b, prev, offset = -1, None, 0
    for m in meshes:
        if m.kind != prev:
            b += 1
            prev = m.kind
            offset = 0
        m.buffer = b
        m.vertex_offset = offset
        offset += m.vertex_count
    return b + 1


@dataclass
class SceneryData:
    sceneries: List[Scenery]
    solids: Dict[int, Solid]
    solid_lists: List[Chunk]
    other: List[Chunk]

    @property
    def infos(self):
        return [i for s in self.sceneries for i in s.infos]

    @property
    def instances(self):
        return [i for s in self.sceneries for i in s.instances]


def parse_mesh(raw):
    bbox = struct.unpack_from("<6f", raw, 0)
    vc, tc, io = struct.unpack_from("<3I", raw, 0x3C)
    return Mesh(raw, bbox, tuple(raw[0x18:0x1D]), raw[0x1D], struct.unpack_from("<I", raw, 0x38)[0], vc, tc, io,
                struct.unpack_from("<I", raw, 0x5C)[0], struct.unpack_from("<I", raw, 0x30)[0])


def read_solid(c, pos):
    """A world Solid from a 0x80134010 chunk whose data starts at `pos` (from the section's start)."""
    f = dict(header=None, textures=[], shaders=None, mesh_header=None, meshes=[], vertex_buffers=[], indices=None,
             mesh_names=[], other=[])
    for k, kpos in with_positions(c.children, pos):
        if k.id == SOLID_HEADER:
            f["header"] = unpad(k.id, k.data, kpos)
        elif k.id == TEXTURES:
            f["textures"] = [struct.unpack_from("<I", k.data, i)[0] for i in range(0, len(k.data), 8)]
        elif k.id == SHADERS:
            f["shaders"] = [struct.unpack_from("<I", k.data, i)[0] for i in range(0, len(k.data), 8)]
        elif k.id == MESHES:
            for m, mpos in with_positions(k.children, kpos):
                d = unpad(m.id, m.data, mpos) if m.data is not None else None
                if m.id == MESH_HEADER:
                    f["mesh_header"] = d
                elif m.id == ENTRIES:
                    if len(d) % 104:
                        raise ValueError("mesh entries: %d bytes" % len(d))
                    f["meshes"] = [parse_mesh(d[i:i + 104]) for i in range(0, len(d), 104)]
                elif m.id == INDICES:
                    f["indices"] = d
                elif m.id == VERTICES:
                    f["vertex_buffers"].append(d)
                elif m.id == MESH_NAME:
                    f["mesh_names"].append(m.data.split(b"\0")[0].decode("latin-1"))
                else:
                    raise ValueError("unknown chunk 0x%X in a mesh container" % m.id)
        else:
            f["other"].append(k)
    nbuf = assign_buffers(f["meshes"])
    if f["meshes"] and nbuf != len(f["vertex_buffers"]):
        raise ValueError("%d vertex buffers, %d mesh runs" % (len(f["vertex_buffers"]), nbuf))
    h = f["header"]
    name = h[NAME_AT:].split(b"\0")[0].decode("latin-1")
    return Solid(name=name, name_hash=struct.unpack_from("<I", h, 0x10)[0], **f)


def read_scenery(c, pos):
    header = infos = None
    instances, tree, other = [], b"", {}
    for k, kpos in with_positions(c.children, pos):
        if k.id == SCENERY_HEADER:
            header = k.data
        elif k.id == SCENERY_INFOS:
            if len(k.data) % 0x48:
                raise ValueError("scenery infos: %d bytes" % len(k.data))
            infos = []
            for i in range(0, len(k.data), 0x48):
                r = k.data[i:i + 0x48]
                infos.append(Info(r[:24].split(b"\0")[0].decode("latin-1"), struct.unpack_from("<4I", r, 0x18),
                                  struct.unpack_from("<f", r, 0x38)[0], struct.unpack_from("<I", r, 0x3C)[0],
                                  struct.unpack_from("<I", r, 0x40)[0]))
        elif k.id == SCENERY_INSTANCES:
            d = unpad(k.id, k.data, kpos)
            if len(d) % 0x40:
                raise ValueError("scenery instances: %d bytes" % len(d))
            for i in range(0, len(d), 0x40):
                r = d[i:i + 0x40]
                bbox = struct.unpack_from("<6f", r, 0)
                excl, pre, light = struct.unpack_from("<Ihh", r, 0x18)
                p = struct.unpack_from("<3f", r, 0x20)
                rot = [v / 8192.0 for v in struct.unpack_from("<9h", r, 0x2C)]
                info, = struct.unpack_from("<h", r, 0x3E)
                m = (tuple(rot[0:3]) + (0.0,), tuple(rot[3:6]) + (0.0,), tuple(rot[6:9]) + (0.0,), p + (1.0,))
                instances.append(Instance(info, m, bbox, excl, pre, light))
        elif k.id == SCENERY_TREE:
            tree = k.data
        else:
            other[k.id] = k.data
    number = struct.unpack_from("<i", header, 0x0C)[0]
    return Scenery(number, header, infos or [], instances, tree, other)


def read_section(chunks, start=0):
    """SceneryData of a streaming section's top-level chunks (as bun.read_range returns them)."""
    sceneries, solids, lists, other = [], {}, [], []
    for c, pos in with_positions(chunks, start):
        if c.id == SCENERY_SECTION:
            sceneries.append(read_scenery(c, pos))
        elif c.id == SOLID_LIST:
            lists.append(c)
            for k, kpos in with_positions(c.children, pos):
                if k.id == SOLID:
                    s = read_solid(k, kpos)
                    solids[s.name_hash] = s
        elif c.id != 0:
            other.append(c)
    return SceneryData(sceneries, solids, lists, other)


def transform(m, p):
    """A model point (x, y, z) through an instance matrix (row vectors: p' = p.x v0 + p.y v1 + p.z v2 + v3)."""
    return tuple(p[0] * m[0][a] + p[1] * m[1][a] + p[2] * m[2][a] + m[3][a] for a in range(3))


def instance_positions(data):
    return [i.position for i in data.instances]


def surface_kind(material):
    """A coarse class of a mesh's material name (0x134C02), for drawing and for Task 4's road check."""
    m = material.upper()
    if "SIDEWALK" in m or "CURB" in m:
        return "sidewalk"
    if "PAVEMENT" in m or "ROAD" in m or "ASPHALT" in m or "_RO_" in m or m.startswith("SPEC_RO_"):
        return "road"
    if "GRASS" in m:
        return "grass"
    return "other"


def placed_triangles(data, library=None, drivable_only=True, numbers=None):
    """[(p0, p1, p2, kind, solid name)] for every instance's highest detail solid in this section (solids looked up in
    the section, then in `library`: {hash: Solid} from the X/V library sections). With `drivable_only` the LOD
    scenery sections (sub-number 40..79) are left out."""
    out = []
    for sc in data.sceneries:
        if numbers is not None and sc.number not in numbers:
            continue
        if drivable_only and 40 <= sc.number % 100 < 80:
            continue
        for inst in sc.instances:
            info = sc.infos[inst.info_index]
            h = info.solid_hashes[0]
            so = data.solids.get(h) or (library or {}).get(h)
            if so is None:
                continue
            for p0, p1, p2, k in so.world_triangles(inst.matrix):
                name = so.mesh_names[k] if k < len(so.mesh_names) else ""
                out.append((p0, p1, p2, surface_kind(name), so.name))
    return out


def render_top(tris, out, size=1600, title=""):
    """Top-down picture of triangles (+x right, +y up), coloured by kind."""
    from PIL import Image, ImageDraw
    xs = [p[0] for t in tris for p in t[:3]]
    ys = [p[1] for t in tris for p in t[:3]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    scale = size / max(x1 - x0, y1 - y0, 1)
    w, h = int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1
    img = Image.new("RGB", (w, h + 40), (255, 255, 255))
    d = ImageDraw.Draw(img)
    fill = {"road": (70, 70, 80), "sidewalk": (170, 170, 150), "grass": (150, 200, 140), "other": (225, 215, 200)}
    order = {"other": 0, "grass": 1, "sidewalk": 2, "road": 3}
    for t in sorted(tris, key=lambda t: (order[t[3]], (t[0][2] + t[1][2] + t[2][2]))):
        pts = [((p[0] - x0) * scale, (y1 - p[1]) * scale) for p in t[:3]]
        d.polygon(pts, fill=fill[t[3]])
    d.text((8, h + 6), "%s  x %.0f..%.0f  y %.0f..%.0f (m, +x right, +y up). Dark: road materials, beige: sidewalk/curb,"
           " green: grass, light: other." % (title, x0, x1, y0, y1), fill=(0, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    return x0, x1, y0, y1, scale
