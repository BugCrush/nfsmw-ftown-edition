"""The game's GLOBAL\\GlobalMemoryFile.bin: a cache the game preloads. The Black Edition's holds whole copies of
small files (attributes.bin, GlobalB.lzc, LANGUAGES\\English.bin, ...) and the opening bytes of large ones
(DYNTEX.BIN, CARS\\...), and a cached copy wins over the file on disk. So files the Xbox 360 pack changes on
disk are never read while their cache entries exist (found 2026-10-18: the pack's sky stayed black until the
GlobalB.lzc entry was disabled).

Layout (worked out from the Black Edition's file): 0, 0, magic 0x53219999, entry count (the last entry has hash
0), 16 header bytes, then 20-byte entries from 0x20: address, name hash (bStringHash of the upper-case path),
offset in this file, file size, bytes stored. disable() replaces an entry's hash with one no file has, so the
game no longer finds it and reads the file from disk; nothing else moves.

Usage: python memfile.py <in.bin> <out.bin> <game folder> REL ...
"""
import os
import struct
import sys

MAGIC = 0x53219999
FIRST, SIZE = 0x20, 20
REPLACEMENT_BASE = 0xDEAD0001


def bhash(text):
    h = 0xFFFFFFFF
    for c in text.encode("latin-1"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def entries(data):
    if len(data) < FIRST or struct.unpack_from("<I", data, 8)[0] != MAGIC:
        raise ValueError("not a GlobalMemoryFile (magic missing)")
    count = struct.unpack_from("<I", data, 12)[0]
    out = []
    for i in range(count - 1):  # the last entry is the end marker
        addr, h, off, size, stored = struct.unpack_from("<5I", data, FIRST + SIZE * i)
        out.append({"index": i, "address": addr, "hash": h, "offset": off, "size": size, "stored": stored})
    return out


def used_hashes_of(game_root):
    used = set()
    for dp, _, names in os.walk(game_root):
        for n in names:
            used.add(bhash(os.path.relpath(os.path.join(dp, n), game_root).upper()))
    return used


def disable(data, rels, used_hashes):
    out = bytearray(data)
    ents = {e["hash"]: e for e in entries(data)}
    taken = set(used_hashes) | set(ents)
    replacement = REPLACEMENT_BASE
    for rel in rels:
        e = ents.get(bhash(rel.upper()))
        if e is None:
            raise ValueError("%s is not cached in this file (already disabled?)" % rel)
        while replacement in taken:
            replacement += 1
        struct.pack_into("<I", out, FIRST + SIZE * e["index"] + 4, replacement)
        taken.add(replacement)
    return bytes(out)


if __name__ == "__main__":
    src, dst, game, rels = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    data = open(src, "rb").read()
    open(dst, "wb").write(disable(data, rels, used_hashes_of(game)))
    print("disabled:", ", ".join(rels))
