"""JDLZ, the LZ compression EA used in NFS Most Wanted packs (add-on car packs compress their solids and textures).

Header (16 bytes): b"JDLZ", 0x02 0x10 0x00 0x00, u32 uncompressed size, u32 compressed size (the whole blob including
this header). Then a byte stream steered by two flag bytes: flags1 says literal (bit 0) or back-reference (bit 1);
for a back-reference flags2 picks the short form (4-bit distance, 12-bit length) or the long form (11-bit distance
+ 17, 5-bit length). A flag byte is read when its shifted value has dropped to 1 (eight bits used).

`compress_literal` writes valid JDLZ made only of literals: no size gain, but the game's decompressor reads it.
"""
import struct

MAGIC = b"JDLZ\x02\x10\x00\x00"


def sizes(blob):
    """(uncompressed size, compressed size) from the header."""
    if blob[:4] != b"JDLZ":
        raise ValueError("not a JDLZ blob: %r" % bytes(blob[:4]))
    return struct.unpack_from("<II", blob, 8)


def decompress(blob):
    size, csize = sizes(blob)
    inp = blob
    end = min(len(inp), csize)
    out = bytearray()
    f1 = f2 = 1
    i = 16
    while i < end and len(out) < size:
        if f1 == 1:
            f1 = inp[i] | 0x100
            i += 1
        if f2 == 1:
            f2 = inp[i] | 0x100
            i += 1
        if f1 & 1:
            if f2 & 1:
                length = (inp[i + 1] | ((inp[i] & 0xF0) << 4)) + 3
                t = (inp[i] & 0x0F) + 1
            else:
                t = (inp[i + 1] | ((inp[i] & 0xE0) << 3)) + 17
                length = (inp[i] & 0x1F) + 3
            i += 2
            if t > len(out):
                raise ValueError("JDLZ back-reference before the start at input %d" % i)
            for _ in range(length):
                out.append(out[-t])
            f2 >>= 1
        else:
            out.append(inp[i])
            i += 1
        f1 >>= 1
    if len(out) < size:
        raise ValueError("JDLZ data ended at %d of %d bytes" % (len(out), size))
    return bytes(out[:size])


def compress_literal(data):
    """Valid JDLZ holding `data` as literals only (flags2 is read once and never consumed)."""
    body = bytearray()
    for k in range(0, len(data), 8):
        body.append(0)  # flags1: eight literals
        if k == 0:
            body.append(0)  # flags2, read together with the first flags1
        body += data[k:k + 8]
    return MAGIC + struct.pack("<II", len(data), 16 + len(body)) + bytes(body)
