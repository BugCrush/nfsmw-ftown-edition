"""Smackable spawner packs (chunk 0x34027) and F-Town's override entries: the breakable poles' file
(docs/ftown-notes.md "Breakable poles (2026-11-05)"; plan docs/superpowers/plans/2026-11-05-ftown-breakable-poles.md).

A pack (`BCHUNK_SPEED_SMOKEABLE_SPAWNER`, loader 0x6829D0 in speed.exe v1.3) holds its data at `(chunk + 0x17) & ~0xF`
(a run of 0x11 bytes before it, as Rockport's files): header u32 0x0B, u32 0x0B, s16 section, s16 first unique id,
s16 count, u8 swapped (0), u8 0; then `count` records of 0x40 bytes (`Physics/SmokeableInfo.hpp`): +0x00 orientation
quaternion (physics axes), +0x10 position (x, y, z, 1; physics), +0x20 model and +0x24 collision volume (`vlt32` of the
mixed-case model name), +0x28 attributes (`vlt32` of a `smackable` collection: "trafficlight"), +0x2C the override
entry's number, +0x30 unique id, +0x34 exclude flags, +0x38 run-time model pointer (0), +0x3C 0.

The override table (`SceneryOverrideInfoTable`, [0x9A3A64], count [0x9A3A68]) is Rockport's (L2RA.BUN chunk 0x34108,
22,340 entries of {s16 section, s16 instance, u16 flags}); FTownLoader appends ours after it. Our file therefore starts
with a chunk of id 0 (`LoadChunks` skips id 0) holding them: b"FTSM", u32 version 1, u32 base (22,340: our first
entry's number), u32 count, then count entries `<hhH`, padded to 4. Record k of the file (packs in order) has
+0x2C = base + k and its entry is entry k.
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
if CARBUILD not in sys.path:
    sys.path.insert(0, CARBUILD)

from chunks import Chunk, chunk_bytes, read_chunks, write_chunks  # noqa: E402

SPAWNER = 0x34027
RECORD = 0x40
MAGIC = b"FTSM"
VERSION = 1
ROCKPORT_OVERRIDES = 22340  # L2RA.BUN chunk 0x34108 / 6
MAX_RECORDS = 2048  # the game's live scenery models (0x681540: cmp [0x92617C], 0x800) and a pack's smashed bits
EXCLUDE = 0x40108000  # Rockport's most common for its poles; none of the loader's bits 0x1, 0x4, 0x40000, 0x80000
LOADER_BITS = 0x1 | 0x4 | 0x40000 | 0x80000


def quaternion(heading):
    """The record's orientation for a model whose x axis points at render heading `heading` (radians, from +x
    counter-clockwise): a turn about physics y, (0, -sin(h/2), 0, cos(h/2)) (Rockport's records against their
    instances' matrices)."""
    return (0.0, -math.sin(heading / 2.0), 0.0, math.cos(heading / 2.0))


def make_record(q, pos, model, collision, attributes, override, uid, exclude=EXCLUDE):
    """A 0x40-byte record: q the quaternion (x, y, z, w), pos the physics position (x, y, z)."""
    if exclude & LOADER_BITS:
        raise ValueError("exclude flags 0x%08X carry a bit the loader skips records by" % exclude)
    return struct.pack("<4f4f6I8x", *q, pos[0], pos[1], pos[2], 1.0, model, collision, attributes, override, uid,
                       exclude)


def read_record(r):
    q = struct.unpack_from("<4f", r, 0)
    p = struct.unpack_from("<4f", r, 0x10)
    model, coll, attr, ov, uid, excl, ptr, pad = struct.unpack_from("<8I", r, 0x20)
    return {"q": q, "pos": p[:3], "w": p[3], "model": model, "collision": coll, "attributes": attr, "override": ov,
            "uid": uid, "exclude": excl, "pointer": ptr, "pad": pad}


def pack_chunk(section, first_uid, records, pos):
    """The 0x34027 Chunk whose data starts at `pos` from a 16-aligned origin (the file's start: FTownLoader's buffer
    is 64 KB aligned)."""
    if not 0 < len(records) <= MAX_RECORDS:
        raise ValueError("%d records in a pack (1..%d)" % (len(records), MAX_RECORDS))
    run = (-pos) % 16
    head = struct.pack("<IIhhhBB", 0x0B, 0x0B, section, first_uid, len(records), 0, 0)
    return Chunk(SPAWNER, b"\x11" * run + head + b"".join(records))


def read_pack(data, pos):
    """(section, first uid, [record dict]) of a pack's chunk data at `pos`."""
    run = (-pos) % 16
    if data[:run] != b"\x11" * run:
        raise ValueError("a spawner pack without its 0x11 run")
    a, b, section, first, count, swapped, _z = struct.unpack_from("<IIhhhBB", data, run)
    if (a, b) != (0x0B, 0x0B) or swapped:
        raise ValueError("not a spawner pack header")
    base = run + 16
    if base + RECORD * count > len(data):
        raise ValueError("the records run past the pack")
    return section, first, [read_record(data[base + RECORD * k: base + RECORD * (k + 1)]) for k in range(count)]


def override_chunk(entries, base=ROCKPORT_OVERRIDES):
    body = MAGIC + struct.pack("<III", VERSION, base, len(entries)) + \
        b"".join(struct.pack("<hhH", s, i, f) for s, i, f in entries)
    return Chunk(0, body + bytes((-len(body)) % 4))


def write_file(packs, entries, base=ROCKPORT_OVERRIDES):
    """bytes of the file: the override chunk, then one pack per (section, first uid, [record bytes])."""
    out, pos = [override_chunk(entries, base)], 0
    pos = len(chunk_bytes(out[0]))
    for section, first, recs in packs:
        c = pack_chunk(section, first, recs, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return write_chunks(out)


def read_file(data):
    """(base, [(section, instance, flags)], [(section, first uid, [record])])."""
    top = read_chunks(data)
    if not top or top[0].id != 0 or top[0].data[:4] != MAGIC:
        raise ValueError("no FTSM override chunk first")
    d = top[0].data
    version, base, n = struct.unpack_from("<III", d, 4)
    if version != VERSION:
        raise ValueError("FTSM version %d" % version)
    entries = [struct.unpack_from("<hhH", d, 16 + 6 * k) for k in range(n)]
    packs, pos = [], len(chunk_bytes(top[0]))
    for c in top[1:]:
        if c.id == SPAWNER:
            packs.append(read_pack(c.data, pos + 8))
        elif c.id != 0:
            raise ValueError("chunk 0x%X in a spawner file" % c.id)
        pos += len(chunk_bytes(c))
    return base, entries, packs
