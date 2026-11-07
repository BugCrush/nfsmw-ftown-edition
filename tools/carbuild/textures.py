"""TEXTURES.BIN (a car's texture pack) to a TexturePack and back; DDS export.

Layout of the game's packs (all of them round-trip byte-identical through `write_textures`; docs/carbuild-format.md):

    0xB3300000 pack
        0x00000000 padding to 64
        0xB3310000 info: 0x33310001 header (124 bytes: version 5, pack name, file name, hash at +0x60),
                         0x33310002 (texture hash, 0) per texture, sorted by hash,
                         0x33310003 (texture hash, file offset, stored size, size, 0x100, 0) per texture, sorted
        0x00000000 padding to 128
        0xB3320000 data: 0x33320001 (0, 0, 1, the header's hash, 0, 0), padding to 128,
                         0x33320002: 120 bytes of 0x11, then one block per texture, each starting at a multiple of
                         64 in the file; the chunk ends at the next multiple of 64 after the last block

Every texture is its own block: "JDLZ" (compressed), "HUFF" (EA Huffman, not decoded here: kept as stored) or "RAWW"
(stored; written by the Raptor add-on's tool). A block holds the pixel data (all mip levels, largest first) followed
by a 156-byte header: the game's TextureInfo (124 bytes: name at +0x0C, hash +0x24, sizes, width +0x44, height
+0x46, compression +0x4A, mip levels +0x4E) and 32 more bytes (D3D format or FourCC at +0x90).

The bytes between blocks are not always zeros (left-over compressor output), so a texture read from a file keeps its
stored block and the bytes after it, and writes them back unchanged as long as its data and header are unchanged.
"""
import hashlib
import struct
from dataclasses import dataclass, field
from typing import List, Optional

import jdlz
from chunks import read_chunks, find

PACK = 0xB3300000
INFO = 0xB3310000
HEADER = 0x33310001
HASHES = 0x33310002
DIRECTORY = 0x33310003
DATA = 0xB3320000
DATA_HEADER = 0x33320001
DATA_BLOCKS = 0x33320002
BLOCK_FLAGS = 0x100
TRAILER = 156
D3DFMT_A8R8G8B8 = 21
FORMATS = {b"DXT1": "DXT1", b"DXT3": "DXT3", b"DXT5": "DXT5", struct.pack("<I", D3DFMT_A8R8G8B8): "A8R8G8B8"}


@dataclass
class Texture:
    name: str
    name_hash: int
    width: int
    height: int
    fmt: Optional[str]
    mipmaps: int
    data: Optional[bytes]  # all mip levels; None for a HUFF block (not decoded)
    header: Optional[bytes]  # the 156 bytes after the data
    codec: str = "RAWW"
    blob: Optional[bytes] = None  # the block as stored in the file it was read from
    slack: bytes = b""  # the bytes after the stored block, up to the next one
    size: int = 0  # the block's decoded size (data + header)
    digest: Optional[bytes] = None  # of data + header when read; a change makes the writer re-encode

    def block(self):
        return self.data + self.header

    def stored_block_valid(self):
        if self.blob is None:
            return False
        if self.data is None:
            return True  # HUFF: nothing decoded, nothing could have changed
        return hashlib.sha1(self.block()).digest() == self.digest


@dataclass
class TexturePack:
    name: str
    filename: str
    textures: List[Texture]
    raw_parts: dict = field(default_factory=dict)  # "info": the 0x33310001 bytes


def mip_chain_size(width, height, fmt, levels):
    total = 0
    w, h = width, height
    for _ in range(levels):
        if fmt == "DXT1":
            total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
        elif fmt in ("DXT3", "DXT5"):
            total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        elif fmt == "A8R8G8B8":
            total += w * h * 4
        else:
            raise ValueError("unknown texture format %r" % fmt)
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def _cstr(b):
    return b.split(b"\0")[0].decode("latin-1")


def _texture_from_block(name_hash, codec, blob, size):
    if codec == "JDLZ":
        block = jdlz.decompress(blob)
    elif codec == "RAWW":
        block = blob[16:16 + size]
    else:
        return Texture(name="", name_hash=name_hash, width=0, height=0, fmt=None, mipmaps=0, data=None, header=None,
                       codec=codec, blob=blob, size=size)
    if len(block) != size:
        raise ValueError("texture 0x%08X: %d bytes, directory says %d" % (name_hash, len(block), size))
    data, header = block[:-TRAILER], block[-TRAILER:]
    w, h = struct.unpack_from("<2H", header, 0x44)
    return Texture(name=_cstr(header[0x0C:0x24]), name_hash=name_hash, width=w, height=h,
                   fmt=FORMATS.get(header[0x90:0x94]), mipmaps=header[0x4E], data=data, header=header, codec=codec,
                   blob=blob, size=size, digest=hashlib.sha1(block).digest())


def read_textures(data):
    top = read_chunks(data)
    infos = find(top, INFO)
    if not infos and top and top[0].id == PACK and top[0].children is None:
        # the Chiron add-on's pack: the info chunk, then the blocks without a data container; the pack's bytes do
        # not split into chunks past the info, so take the chunks that do
        raw, off = top[0].data, 0
        while off + 8 <= len(raw):
            cid, size = struct.unpack_from("<II", raw, off)
            if cid == INFO:
                infos = read_chunks(raw[off:off + 8 + size])
                break
            off += 8 + size
    if not infos:
        raise ValueError("no texture pack info (0xB3310000)")
    info = infos[0]
    header = [c for c in info.children if c.id == HEADER][0].data
    directory = [c for c in info.children if c.id == DIRECTORY][0].data
    entries = [struct.unpack_from("<6I", directory, k) for k in range(0, len(directory), 24)]
    entries.sort(key=lambda e: e[1])  # file order
    blocks = find(top, DATA_BLOCKS)
    data_end = None
    if blocks:
        # where the data chunk ends, to keep the bytes after the last block
        data_end = _chunk_end(data, DATA_BLOCKS)
    textures = []
    for k, (h, off, csize, size, flags, _) in enumerate(entries):
        blob = data[off:off + csize]
        codec = blob[:4].decode("latin-1")
        if codec not in ("JDLZ", "HUFF", "RAWW"):
            raise ValueError("texture 0x%08X: unknown block %r" % (h, blob[:4]))
        t = _texture_from_block(h, codec, blob, size)
        nxt = entries[k + 1][1] if k + 1 < len(entries) else data_end
        t.slack = data[off + csize:nxt] if nxt is not None and nxt >= off + csize else b""
        textures.append(t)
    # the three padding chunks of the game's layout (before the info, before the data container, inside it): their
    # bytes are not always zeros (packs written by Binarius carry "Binary by MaxHwoy | Automated" in the last one)
    pads = []
    pack_chunk = top[0] if top and top[0].id == PACK and top[0].children is not None else None
    if pack_chunk is not None:
        pads = [c.data for c in pack_chunk.children if c.id == 0]
        for c in pack_chunk.children:
            if c.id == DATA:
                pads += [k.data for k in c.children if k.id == 0]
    return TexturePack(name=_cstr(header[4:0x20]), filename=_cstr(header[0x20:0x60]), textures=textures,
                       raw_parts={"info": header, "pads": pads})


def _chunk_end(data, chunk_id):
    """End offset of the first chunk with this id (walking containers that nest exactly)."""
    def walk(off, end):
        while off + 8 <= end:
            cid, size = struct.unpack_from("<II", data, off)
            if cid == chunk_id:
                return off + 8 + size
            if cid & 0x80000000 and off + 8 + size <= end:
                r = walk(off + 8, off + 8 + size)
                if r is not None:
                    return r
            off += 8 + size
        return None
    return walk(0, len(data))


# ---------------------------------------------------------------- writing

def _pad(pos, align, keep=None):
    """An id-0 chunk up to the next multiple of `align`; its bytes are `keep` when that has the right length."""
    gap = (-pos) % align
    if gap == 0:
        return b""
    if gap < 8:
        gap += align
    body = keep if keep is not None and len(keep) == gap - 8 else bytes(gap - 8)
    return struct.pack("<II", 0, gap - 8) + body


def _encode(t, compressed):
    """(codec, stored block) for a texture."""
    if compressed is None and t.stored_block_valid():
        return t.codec, t.blob
    if t.data is None:
        if t.blob is None:
            raise ValueError("texture 0x%08X has neither data nor a stored block" % t.name_hash)
        return t.codec, t.blob  # HUFF: can only be kept
    block = t.block()
    if compressed:
        return "JDLZ", jdlz.compress_literal(block)
    if compressed is None and t.codec == "JDLZ":
        return "JDLZ", jdlz.compress_literal(block)
    return "RAWW", b"RAWW\x01\x10\x00\x00" + struct.pack("<II", len(block), len(block) + 16) + block


def write_textures(pack, compressed=None):
    """Bytes of a TEXTURES.BIN in the game's layout. compressed=None keeps every texture as stored (re-encoding only
    changed ones, in their codec); False stores every decodable texture as RAWW; True as literal JDLZ."""
    info = bytearray(pack.raw_parts["info"])
    name = pack.name.encode("latin-1")[:27]
    info[4:0x20] = name + bytes(0x1C - len(name))
    filename = pack.filename.encode("latin-1")[:63]
    if _cstr(bytes(info[0x20:0x60])) != pack.filename:
        # the pack's key is bStringHash of its file name in every game pack: a renamed pack gets its own key
        h = 0xFFFFFFFF
        for c in filename:
            h = (h * 33 + c) & 0xFFFFFFFF
        struct.pack_into("<I", info, 0x60, h)
    info[0x20:0x60] = filename + bytes(0x40 - len(filename))
    pack_hash = struct.unpack_from("<I", info, 0x60)[0]

    encoded = [_encode(t, compressed) for t in pack.textures]
    n = len(pack.textures)
    # decoded size: the stored one for a block kept as stored (HUFF has no other), else the block we encoded
    sizes = [t.size if (blob is t.blob or t.data is None) else len(t.block())
             for t, (_, blob) in zip(pack.textures, encoded)]
    order = sorted(range(n), key=lambda k: pack.textures[k].name_hash)
    hashes = b"".join(struct.pack("<II", pack.textures[k].name_hash, 0) for k in order)

    def info_chunk(offsets):
        directory = b"".join(struct.pack("<6I", pack.textures[k].name_hash, offsets[k], len(encoded[k][1]),
                                         sizes[k], BLOCK_FLAGS, 0)
                             for k in order)
        body = (struct.pack("<II", HEADER, len(info)) + bytes(info) + struct.pack("<II", HASHES, len(hashes)) +
                hashes + struct.pack("<II", DIRECTORY, len(directory)) + directory)
        return struct.pack("<II", INFO, len(body)) + body

    kept = list(pack.raw_parts.get("pads", [])) + [None] * 3
    pos = 8
    pre = _pad(pos, 64, kept[0])
    pos += len(pre)
    info_len = len(info_chunk([0] * n))
    pos += info_len
    mid = _pad(pos, 128, kept[1])
    pos += len(mid)
    data_pos = pos  # 0xB3320000
    pos += 8
    dhead = struct.pack("<II", DATA_HEADER, 24) + struct.pack("<3I", 0, 0, 1) + struct.pack("<I", pack_hash) + bytes(8)
    pos += len(dhead)
    dpad = _pad(pos, 128, kept[2])
    pos += len(dpad)
    pos += 8  # 0x33320002 header
    blocks = bytearray(b"\x11" * ((-pos) % 128))
    pos += len(blocks)
    offsets = [0] * n
    for k, (codec, blob) in enumerate(encoded):
        offsets[k] = pos
        blocks += blob
        pos += len(blob)
        gap = (-pos) % 64
        t = pack.textures[k]
        keep = compressed is None and t.stored_block_valid() and len(t.slack) == gap
        blocks += t.slack if keep else bytes(gap)
        pos += gap
    data_chunk = (struct.pack("<II", DATA, len(dhead) + len(dpad) + 8 + len(blocks)) + dhead + dpad +
                  struct.pack("<II", DATA_BLOCKS, len(blocks)) + bytes(blocks))
    body = pre + info_chunk(offsets) + mid + data_chunk
    assert 8 + len(pre) + info_len + len(mid) == data_pos
    return struct.pack("<II", PACK, len(body)) + body


def new_texture(name, width, height, bgra, donor_header, placement=0):
    """An uncompressed (A8R8G8B8, one mip level) texture made from pixel bytes (B, G, R, A per pixel, top row first)
    and a donor's 156-byte header: the name (cut to 23 characters, as the game's packs do; the hash stays the full
    name's), hash, image placement (+0x30) and sizes (+0x38, +0x40), width and height (+0x44, +0x46, log2 at +0x48),
    compression 0x20 (+0x4A), one mip level (+0x4E), D3D format 21 (+0x90) are written over the donor's bytes."""
    if len(bgra) != width * height * 4:
        raise ValueError("%s: %d bytes for %dx%d" % (name, len(bgra), width, height))
    if width & (width - 1) or height & (height - 1):
        raise ValueError("%s: %dx%d is not a power of two" % (name, width, height))
    h = bytearray(donor_header)
    raw = name.encode("ascii")[:23]
    h[0x0C:0x24] = raw + bytes(24 - len(raw))
    full = 0xFFFFFFFF
    for c in name.encode("ascii"):
        full = (full * 33 + c) & 0xFFFFFFFF
    struct.pack_into("<I", h, 0x24, full)
    struct.pack_into("<I", h, 0x30, placement)
    struct.pack_into("<I", h, 0x38, len(bgra))
    struct.pack_into("<I", h, 0x40, len(bgra))
    struct.pack_into("<2H", h, 0x44, width, height)
    h[0x48], h[0x49] = width.bit_length() - 1, height.bit_length() - 1
    h[0x4A] = 0x20
    h[0x4E] = 1
    h[0x4F] = 0
    struct.pack_into("<I", h, 0x90, D3DFMT_A8R8G8B8)
    return Texture(name=raw.decode("ascii"), name_hash=full, width=width, height=height, fmt="A8R8G8B8", mipmaps=1,
                   data=bytes(bgra), header=bytes(h), codec="RAWW", size=len(bgra) + TRAILER)


# ---------------------------------------------------------------- DDS

def to_dds(t):
    """A DDS file of the texture (all its mip levels)."""
    if t.data is None:
        raise ValueError("texture 0x%08X is not decoded (%s)" % (t.name_hash, t.codec))
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000  # caps, height, width, pixel format, mipmap count
    caps = 0x1000 | (0x400008 if t.mipmaps > 1 else 0)
    if t.fmt == "A8R8G8B8":
        flags |= 0x8  # pitch
        pitch = t.width * 4
        pf = struct.pack("<II4sI4I", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    else:
        flags |= 0x80000  # linear size
        pitch = mip_chain_size(t.width, t.height, t.fmt, 1)
        pf = struct.pack("<II4sI4I", 32, 0x4, t.fmt.encode(), 0, 0, 0, 0, 0)
    head = struct.pack("<7I", 124, flags, t.height, t.width, pitch, 0, max(1, t.mipmaps)) + bytes(44) + pf + \
        struct.pack("<4I", caps, 0, 0, 0) + bytes(4)
    return b"DDS " + head + t.data
