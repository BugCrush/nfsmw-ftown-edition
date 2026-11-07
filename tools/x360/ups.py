"""UPS patches (byuu's format): read, create (for tests), apply with every CRC32 checked.

apply_file never writes the output unless the patch's own CRC, the input's CRC and the output's CRC all match.
There is deliberately no way to "ignore" a mismatching input (the pack's readme suggests it; it is how the
"crashes when going into races" problem arises).
Usage: python ups.py <patch.ups> <input> <output>
"""
import os
import sys
import zlib


class Mismatch(Exception):
    pass


def _encode(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def _decode(data, pos):
    value, shift = 0, 1
    while True:
        b = data[pos]
        pos += 1
        value += (b & 0x7F) * shift
        if b & 0x80:
            return value, pos
        shift <<= 7
        value += shift


def read(data):
    if data[:4] != b"UPS1":
        raise Mismatch("patch: not a UPS1 file")
    in_size, pos = _decode(data, 4)
    out_size, pos = _decode(data, pos)
    end = len(data) - 12
    records, offset = [], 0
    while pos < end:
        skip, pos = _decode(data, pos)
        offset += skip
        start = pos
        while data[pos] != 0:
            pos += 1
        records.append((offset, data[start:pos]))
        offset += pos - start + 1  # the terminating zero stands for one unchanged byte
        pos += 1
    crc_in, crc_out, crc_patch = (int.from_bytes(data[end + i:end + i + 4], "little") for i in (0, 4, 8))
    return {"in_size": in_size, "out_size": out_size, "records": records,
            "crc_in": crc_in, "crc_out": crc_out, "crc_patch": crc_patch}


def create(a, b):
    out = bytearray(b"UPS1" + _encode(len(a)) + _encode(len(b)))
    n = max(len(a), len(b))
    pa, pb = a.ljust(n, b"\0"), b.ljust(n, b"\0")
    last, i = 0, 0
    while i < n:
        if pa[i] == pb[i]:
            i += 1
            continue
        out += _encode(i - last)
        while i < n and pa[i] != pb[i]:
            out.append(pa[i] ^ pb[i])
            i += 1
        out.append(0)
        i += 1
        last = i
    out += zlib.crc32(a).to_bytes(4, "little") + zlib.crc32(b).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def crc32_file(path):
    c = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            c = zlib.crc32(block, c)
    return c


def apply_file(patch_path, in_path, out_path):
    data = open(patch_path, "rb").read()
    if len(data) < 16 or zlib.crc32(data[:-4]) != int.from_bytes(data[-4:], "little"):
        raise Mismatch("patch: its own CRC32 does not match (damaged download?)")
    info = read(data)
    crc_in, size_in = crc32_file(in_path), os.path.getsize(in_path)
    if crc_in == info["crc_out"] and size_in == info["out_size"] and info["crc_in"] != info["crc_out"]:
        raise Mismatch("input: already patched (CRC32 %08x is the patch's output)" % crc_in)
    if crc_in != info["crc_in"] or size_in != info["in_size"]:
        raise Mismatch("input: CRC32 %08x / %d bytes, the patch expects %08x / %d bytes"
                       % (crc_in, size_in, info["crc_in"], info["in_size"]))
    part = out_path + ".part"
    try:
        with open(in_path, "rb") as src, open(part, "wb") as dst:
            for block in iter(lambda: src.read(1 << 24), b""):
                dst.write(block)
        with open(part, "r+b") as f:
            f.truncate(max(size_in, info["out_size"]))  # grow with zeros if the output is longer
            for offset, xor in info["records"]:
                f.seek(offset)
                old = f.read(len(xor)).ljust(len(xor), b"\0")
                f.seek(offset)
                f.write(bytes(x ^ y for x, y in zip(old, xor)))
            f.truncate(info["out_size"])
        crc_out = crc32_file(part)
        if crc_out != info["crc_out"]:
            raise Mismatch("output: CRC32 %08x, the patch expects %08x" % (crc_out, info["crc_out"]))
        os.replace(part, out_path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return {"crc_in": crc_in, "crc_out": crc_out, "changed_bytes": sum(len(x) for _, x in info["records"])}


if __name__ == "__main__":
    r = apply_file(*sys.argv[1:4])
    print("ok: %08x -> %08x, %d bytes changed" % (r["crc_in"], r["crc_out"], r["changed_bytes"]))
