"""The chunk tree of the game's binary files (GEOMETRY.BIN, TEXTURES.BIN and others).

Each chunk is `u32 id, u32 size` followed by `size` bytes. An id with the top bit set (0x80000000) is a container whose
bytes are more chunks; any other id is a leaf holding raw bytes. Id 0 is padding (alignment) and is kept exactly like
any other leaf, so `write_chunks(read_chunks(data)) == data` for every well-formed file.

A container whose size field is too small for its children (the Raptor add-on) keeps the stored size in `size` and
the children that really belong to it; the stored size is written back unchanged.

A container whose bytes do not split exactly into child chunks (seen in compressed packs, where JDLZ blocks follow
the header inside the solid list) is kept as raw bytes: `children` is None and `data` holds them.

Also holds the game's name hash (bStringHash).
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

CONTAINER = 0x80000000


@dataclass
class Chunk:
    id: int
    data: Optional[bytes] = None
    children: Optional[List["Chunk"]] = field(default=None)
    size: Optional[int] = None  # the size field as stored, only when it differs from the content's length

    @property
    def is_container(self):
        return self.children is not None

    def __repr__(self):
        if self.children is not None:
            return "Chunk(0x%08X, %d children)" % (self.id, len(self.children))
        return "Chunk(0x%08X, %d bytes)" % (self.id, len(self.data or b""))


def bstringhash(name):
    """The game's string hash: h = 0xFFFFFFFF; h = h * 33 + c for every byte."""
    if isinstance(name, str):
        name = name.encode("ascii")
    h = 0xFFFFFFFF
    for c in name:
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def _parse(data, start, end):
    """Children in data[start:end], or None when the bytes are not an exact chunk list."""
    out = []
    off = start
    while off < end:
        if off + 8 > end:
            return None
        cid, size = struct.unpack_from("<II", data, off)
        body = off + 8
        if body + size > end:
            return None
        if cid & CONTAINER:
            kids = _parse(data, body, body + size) if body + size <= end else None
            if kids is None:
                # A size field that is too small (the Raptor add-on's solid list is 2,204 bytes short of its last
                # solid): if the children tile exactly up to the parent's end, they belong to this container.
                wide = _parse(data, body, end)
                if wide is not None and body + size < end:
                    out.append(Chunk(cid, None, wide, size))
                    off = end
                    continue
            out.append(Chunk(cid, None, kids) if kids is not None else Chunk(cid, bytes(data[body:body + size])))
        else:
            out.append(Chunk(cid, bytes(data[body:body + size])))
        off = body + size
    return out


def read_chunks(data):
    """The chunk list of a whole file (raises ValueError if the file is not a chunk list)."""
    out = _parse(data, 0, len(data))
    if out is None:
        raise ValueError("not a chunk list (sizes do not add up to the file length %d)" % len(data))
    return out


def chunk_bytes(chunk):
    if chunk.children is not None:
        body = write_chunks(chunk.children)
    else:
        body = chunk.data or b""
    size = len(body) if chunk.size is None else chunk.size
    return struct.pack("<II", chunk.id, size) + body


def write_chunks(chunks):
    return b"".join(chunk_bytes(c) for c in chunks)


def find(chunks, chunk_id):
    """Every chunk with this id, depth-first in file order."""
    out = []
    for c in chunks:
        if c.id == chunk_id:
            out.append(c)
        if c.children is not None:
            out.extend(find(c.children, chunk_id))
    return out


def find_one(chunks, chunk_id):
    found = find(chunks, chunk_id)
    return found[0] if found else None
