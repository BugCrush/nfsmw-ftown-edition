"""Writes a copy of the game's GlobalB.lzc with the Longnose Cab's car type marked skinnable (one byte).

    python tools/cars/packages/longnosecab/skinnable.py <game dir>

The truck's CarTypeInfo has Skinnable = 0 (byte 0xC7 of its 0xD0-byte record in chunk 0x00034600); every racing car
and every working add-on has 1, and the game's other non-skinnable cars ship a <CAR>_SKIN1 texture the truck lacks
(docs/cars-notes.md). The copy is written to .superpowers/downloads/cars/3803/fixed/GlobalB.lzc and installed by
tools/cars/install.py (cars.yaml longnosecab-skinnable), which backs up the original. Nothing moves or changes size.
"""
import os
import struct
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
OUT = os.path.join(REPO, ".superpowers", "downloads", "cars", "3803", "fixed", "GlobalB.lzc")
CAR_TYPES, RECORD, SKINNABLE, USAGE = 0x00034600, 0xD0, 0xC7, 0x94


def record_offset(data, name):
    p = 0
    while p + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, p)
        if cid == CAR_TYPES:
            start = p + 8
            while data[start] == 0x11:  # alignment padding
                start += 1
            found = [start + i * RECORD for i in range((p + 8 + size - start) // RECORD)
                     if data[start + i * RECORD:start + i * RECORD + 16].split(b"\0")[0] == name.encode()]
            if len(found) != 1:
                raise SystemExit("expected one %s record, found %d" % (name, len(found)))
            return found[0]
        p += 8 + size
    raise SystemExit("no car type chunk")


def main():
    src = os.path.join(sys.argv[1], "GLOBAL", "GlobalB.lzc")
    data = bytearray(open(src, "rb").read())
    at = record_offset(data, "LONGNOSECAB")
    assert struct.unpack_from("<i", data, at + USAGE)[0] == 0, "not a racer"
    assert data[at + SKINNABLE] == 0, "already skinnable (%d)" % data[at + SKINNABLE]
    gti = record_offset(data, "GTI")
    assert data[gti + SKINNABLE] == 1, "layout check failed: the GTI should read 1"
    data[at + SKINNABLE] = 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "wb").write(data)
    print("Skinnable 0 -> 1 at file offset 0x%X; written %s" % (at + SKINNABLE, OUT))


if __name__ == "__main__":
    main()
