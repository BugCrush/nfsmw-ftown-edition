"""Writes a corrected copy of the Longnose Cab mod's DBModelParts.bin (nfsmods 3803).

    python tools/cars/packages/longnosecab/fix_parts.py

The mod's body kits carry the Golf GTI template's labels GTI_CV, GTI_01_CV .. GTI_05_CV where the game expects the
car's own (LONGNOSECAB_CV ...): in the game's parts table every working car's body has <CAR>_CV, and the truck's body
was never drawn, in the menu or in races. Renaming LONGNOSECAB to TOMAHAWK and GTI to TOMAHAWK turns this file into the
Tomahawk mod's byte for byte (same template; the Tomahawk's body shows), so the labels are the only defect.

The file is Binary's serialized form: 'gMpB', size (len - 8), 2, a hash, size (len - 20), 'RAWW', 0x1001,
size (len - 36), size (len - 20), then the records with null-terminated strings, so the sizes are rewritten.
"""
import os
import re
import struct

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
MOD = os.path.join(REPO, ".superpowers", "downloads", "cars", "3803", "files", "Longnose Cab Semi Truck (Addon)",
                   "Binary Files", "_CarParts", "DBModelParts.bin")
OUT = os.path.join(REPO, ".superpowers", "downloads", "cars", "3803", "fixed", "DBModelParts.bin")
SIZE_FIELDS = {4: 8, 16: 20, 28: 36, 32: 20}  # byte offset of a size field: how much less than the file length


def fix(data):
    body, n = re.subn(rb"GTI(_0\d)?_CV", lambda m: b"LONGNOSECAB" + (m.group(1) or b"") + b"_CV", data[36:])
    out = bytearray(data[:36] + body)
    for at, less in SIZE_FIELDS.items():
        assert struct.unpack_from("<I", data, at)[0] == len(data) - less, "unexpected header at %d" % at
        struct.pack_into("<I", out, at, len(out) - less)
    return bytes(out), n


def main():
    data = open(MOD, "rb").read()
    out, n = fix(data)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "wb").write(out)
    print("%d labels renamed; %d -> %d bytes; written %s" % (n, len(data), len(out), OUT))


if __name__ == "__main__":
    main()
