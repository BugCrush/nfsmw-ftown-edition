"""World texture packs (chunk 0xB3300000 in the streaming sections): read, written back, and new ones made.

Rockport's sections carry their textures in another layout than a car's TEXTURES.BIN (tools/carbuild/textures.py,
compressed blocks per texture with a directory): the TextureInfo records themselves (Ecstasy/Texture.hpp:193, 0x7C
bytes) and the pixel data stored as is (DXT) in one data chunk. Checked over all 477 packs (tools/world/tests/
test_texpack.py; findings in docs/ftown-notes.md, "Part 2: writers"):

    0xB3300000 pack (at a multiple of 128 in every section)
      0x00000000 padding (zeros) so the info starts at a multiple of 64
      0xB3310000 info:
        0x33310001 TexturePackHeader (124 bytes: version 5, name, file name, +0x60 bStringHash(file name), rest 0)
        0x33310002 keys: (texture name hash, 0) per texture, in the TextureInfo order
        0x33310004 TextureInfo x n (124 each; the first 12 bytes and +0x68.. are run-time, zero)
        0x33310005 format record x n (32 each: +0x08 0 or 1, +0x0C 5, +0x10 6 or 2, +0x14 FourCC 'DXT1/3/5')
      0x00000000 padding (zeros) so the data container starts at a multiple of 128
      0xB3320000 data:
        0x33320001 (24 bytes: 0, 0, 1, the header's file name hash, 0, 0)
        0x00000000 padding (zeros) so the next chunk starts at a multiple of 128
        0x33320002 a 0x11 run to 128, then every texture's mip chain at TextureInfo +0x30 (ImagePlacement, a multiple of
                   128, in TextureInfo order, zeros between), +0x38 its size; the chunk ends at the last texture's end

The writer regenerates the paddings, the keys, the file name hash (header and data header), every ImagePlacement and
ImageSize, the 0x11 run and the gaps; everything else of a TextureInfo and format record is kept as data.
"""
import os
import struct
import sys
from dataclasses import dataclass
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
for p in (CARBUILD, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, bstringhash, chunk_bytes  # noqa: E402

PACK = 0xB3300000
INFO = 0xB3310000
HEADER = 0x33310001
KEYS = 0x33310002
INFOS = 0x33310004
COMPS = 0x33310005
DATA = 0xB3320000
DATA_HEADER = 0x33320001
DATA_BLOCK = 0x33320002
TI = 0x7C
COMP_DXT1 = 0x22  # TextureInfo +0x4A for every DXT1 texture of Rockport (1,544); 0x24 DXT3, 0x26 DXT5
# TextureInfo +0x28 ClassNameHash, +0x4F..+0x57 and +0x58..+0x67 of the DXT1 textures Rockport's kind-0 meshes use
# (16,218, 11,003 and 16,290 of 16,293 references; docs/ftown-notes.md): the class hash is never read by the game's
# code (only declared, Texture.hpp:283)
CLASS_HASH = 0x001A93CF
FLAGS_4F = bytes.fromhex("030000000000000001")
SCROLL_58 = bytes.fromhex("00010000000000000000000100010000")
FORMAT_DXT1 = struct.pack("<5I4s2I", 0, 0, 0, 5, 6, b"DXT1", 0, 0)  # 16,284 of those references


@dataclass
class WorldTexture:
    info: bytes  # 124 bytes; +0x30 placement and +0x38 size rewritten
    comp: bytes  # 32 bytes
    data: bytes  # the mip chain

    @property
    def name_hash(self):
        return struct.unpack_from("<I", self.info, 0x24)[0]


@dataclass
class WorldTexturePack:
    header: bytes  # 124 bytes; +0x60 rewritten from the file name
    textures: List[WorldTexture]
    pos: int = 0

    @property
    def filename(self):
        return self.header[0x20:0x60].split(b"\0")[0]

    @property
    def filename_hash(self):
        return bstringhash(self.filename)


def _positions(kids, start):
    out, p = [], start
    for c in kids:
        out.append((c, p))
        p += len(chunk_bytes(c))
    return out


def read_pack(chunk, pos=0):
    """WorldTexturePack of a 0xB3300000 chunk whose data starts at `pos` (from the section's start)."""
    if chunk.id != PACK or chunk.children is None:
        raise ValueError("not a world texture pack")
    header = infos = comps = None
    block = bpos = None
    for c, cpos in _positions(chunk.children, pos):
        if c.id == 0:
            if c.data.strip(b"\0"):
                raise ValueError("texture pack padding is not zeros")
        elif c.id == INFO:
            for k in c.children:
                if k.id == HEADER:
                    header = k.data
                elif k.id == INFOS:
                    infos = k.data
                elif k.id == COMPS:
                    comps = k.data
                elif k.id != KEYS:
                    raise ValueError("unknown texture info chunk 0x%X" % k.id)
        elif c.id == DATA:
            for k, kpos in _positions(c.children, cpos + 8):
                if k.id == DATA_BLOCK:
                    block, bpos = k.data, kpos + 8
        else:
            raise ValueError("unknown texture pack chunk 0x%X" % c.id)
    run = (-bpos) % 128
    if block[:run] != b"\x11" * run:
        raise ValueError("texture data does not start with its 0x11 run")
    data = block[run:]
    n = len(infos) // TI
    textures = []
    for i in range(n):
        info = infos[i * TI:(i + 1) * TI]
        place, size = struct.unpack_from("<i", info, 0x30)[0], struct.unpack_from("<i", info, 0x38)[0]
        textures.append(WorldTexture(info, comps[i * 32:(i + 1) * 32], data[place:place + size]))
    return WorldTexturePack(header, textures, pos)


def _pad(chunk_start, align):
    """A zero padding chunk starting at `chunk_start` so the next chunk starts at a multiple of `align`."""
    gap = (-(chunk_start + 8)) % align
    return Chunk(0, bytes(gap))


def write_pack(pack, pos=None):
    """The 0xB3300000 Chunk of a pack whose data will start at `pos` (default: where it was read)."""
    pos = pack.pos if pos is None else pos
    fhash = pack.filename_hash
    header = bytearray(pack.header)
    struct.pack_into("<I", header, 0x60, fhash)
    blob = bytearray()
    infos = bytearray()
    for t in pack.textures:
        place = (len(blob) + 127) // 128 * 128
        blob += bytes(place - len(blob)) + t.data
        info = bytearray(t.info)
        struct.pack_into("<i", info, 0x30, place)
        struct.pack_into("<i", info, 0x38, len(t.data))
        infos += info
    keys = b"".join(struct.pack("<II", t.name_hash, 0) for t in pack.textures)
    comps = b"".join(t.comp for t in pack.textures)
    info_chunk = Chunk(INFO, None, [Chunk(HEADER, bytes(header)), Chunk(KEYS, keys), Chunk(INFOS, bytes(infos)),
                                    Chunk(COMPS, comps)])
    kids = []
    p = pos
    pad1 = _pad(p, 64)
    kids.append(pad1)
    p += len(chunk_bytes(pad1))
    kids.append(info_chunk)
    p += len(chunk_bytes(info_chunk))
    pad2 = _pad(p, 128)
    kids.append(pad2)
    p += len(chunk_bytes(pad2))
    dh = Chunk(DATA_HEADER, struct.pack("<6I", 0, 0, 1, fhash, 0, 0))
    q = p + 8 + len(chunk_bytes(dh))
    pad3 = _pad(q, 128)
    q += len(chunk_bytes(pad3))
    run = (-(q + 8)) % 128
    kids.append(Chunk(DATA, None, [dh, pad3, Chunk(DATA_BLOCK, b"\x11" * run + bytes(blob))]))
    return Chunk(PACK, None, kids)


# ---------------------------------------------------------------- new textures

def mip_sizes(w, h):
    """DXT1 bytes per mip level, down to 8 pixels on the shorter side (Rockport's 256 x 256 have 6 levels)."""
    out = []
    while min(w, h) >= 8:
        out.append(max(1, w // 4) * max(1, h // 4) * 8)
        w, h = w // 2, h // 2
    return out


def _565(c):
    r, g, b = c
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _from565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _palette(c0, c1):
    a, b = _from565(c0), _from565(c1)
    if c0 > c1:
        return [a, b, tuple((2 * a[i] + b[i]) // 3 for i in range(3)), tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
    return [a, b, tuple((a[i] + b[i]) // 2 for i in range(3)), (0, 0, 0)]


def dxt1_encode(px, w, h):
    """DXT1 (opaque, 4-colour blocks) of pixels [(r, g, b)] row by row: endpoints the block's darkest and brightest
    pixels, each pixel the nearest of the four colours."""
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = [px[(by + y) * w + bx + x] for y in range(4) for x in range(4)]
            lum = [p[0] * 3 + p[1] * 6 + p[2] for p in block]
            hi, lo = block[lum.index(max(lum))], block[lum.index(min(lum))]
            c0, c1 = _565(hi), _565(lo)
            if c0 < c1:
                c0, c1 = c1, c0
            if c0 == c1:
                out += struct.pack("<HHI", c0, c1, 0)  # one colour: every pixel index 0
                continue
            pal = _palette(c0, c1)
            idx = 0
            for k, p in enumerate(block):
                best = min(range(4), key=lambda j: sum((p[i] - pal[j][i]) ** 2 for i in range(3)))
                idx |= best << (2 * k)
            out += struct.pack("<HHI", c0, c1, idx)
    return bytes(out)


def dxt1_decode(data, w, h):
    px = [None] * (w * h)
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            c0, c1, idx = struct.unpack_from("<HHI", data, o)
            o += 8
            pal = _palette(c0, c1)
            for k in range(16):
                px[(by + k // 4) * w + bx + k % 4] = pal[(idx >> (2 * k)) & 3]
    return px


def _half(px, w, h):
    out = []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            q = [px[y * w + x], px[y * w + x + 1], px[(y + 1) * w + x], px[(y + 1) * w + x + 1]]
            out.append(tuple((sum(c[i] for c in q) + 2) // 4 for i in range(3)))
    return out


def new_texture(name, w, h, px, encode=None):
    """A WorldTexture (DXT1 with a full mip chain) from pixels [(r, g, b)] row by row, top row first; the TextureInfo
    filled as Rockport's DXT1 world textures are (CLASS_HASH, FLAGS_4F, SCROLL_58, FORMAT_DXT1); the debug name is cut
    to 23 characters, the hash is the full name's (as in Rockport's packs). encode: a DXT1 encoder with
    dxt1_encode's arguments and bytes (tools/citymap/phototex.py has a vectorised one giving the same bytes)."""
    if w & (w - 1) or h & (h - 1) or min(w, h) < 8:
        raise ValueError("%s: %dx%d is not a power of two of at least 8" % (name, w, h))
    encode = encode or dxt1_encode
    data = bytearray()
    cw, ch, cur = w, h, list(px)
    for _ in mip_sizes(w, h):
        data += encode(cur, cw, ch)
        if cw >= 2 and ch >= 2:
            cur = _half(cur, cw, ch)
            cw, ch = cw // 2, ch // 2
    sizes = mip_sizes(w, h)
    info = bytearray(TI)
    raw = name.encode("ascii")[:23]
    info[0x0C:0x0C + len(raw)] = raw
    struct.pack_into("<III", info, 0x24, bstringhash(name), CLASS_HASH, 0)
    struct.pack_into("<iiiii", info, 0x30, 0, 0, len(data), 0, sizes[0])
    struct.pack_into("<hhBBBBhB", info, 0x44, w, h, w.bit_length() - 1, h.bit_length() - 1, COMP_DXT1, 0, 0,
                     len(sizes))
    info[0x4F:0x58] = FLAGS_4F
    info[0x58:0x68] = SCROLL_58
    return WorldTexture(bytes(info), FORMAT_DXT1, bytes(data))


def new_pack(name, filename, textures):
    """A WorldTexturePack (version 5) of new textures, sorted by name hash as Rockport's are."""
    h = bytearray(124)
    struct.pack_into("<I", h, 0, 5)
    n = name.encode("ascii")[:27]
    h[4:4 + len(n)] = n
    f = filename.encode("ascii")[:63]
    h[0x20:0x20 + len(f)] = f
    return WorldTexturePack(bytes(h), sorted(textures, key=lambda t: t.name_hash), 0)
