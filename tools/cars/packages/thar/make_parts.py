"""The Thar's car parts list (DBModelParts.bin, Binary's serialized form) from the Longnose Cab mod's template.

    python tools/cars/packages/thar/make_parts.py [<out dir>]

The template (nfsmods 3803) is the one the Tomahawk mod shares byte for byte after renaming, and the Tomahawk's body
showed in the game. Every LONGNOSECAB becomes THAR, and the body kits' leftover GTI_CV .. GTI_05_CV labels become
THAR_CV .. THAR_05_CV (the game wants the car's own <CAR>_CV; docs/cars-notes.md), with Binary's four header size
fields rewritten for the new length (../longnosecab/fix_parts.py: the same renaming for the truck). Only KIT00 exists in
the model: the Unlimiter file THAR.ini hides and never randomises the other kits.
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "longnosecab"))
from fix_parts import SIZE_FIELDS  # noqa: E402  (byte offset of each size field: how much less than the length)

TEMPLATE = os.path.join(REPO, ".superpowers", "downloads", "cars", "3803", "files", "Longnose Cab Semi Truck (Addon)",
                        "Binary Files", "_CarParts", "DBModelParts.bin")
OUT_DIR = os.path.join(REPO, ".superpowers", "carbuild", "thar", "package")
HEADER = 36


def rewrite(data, body):
    """data's 36-byte header over a new body, with the size fields following the new length."""
    out = bytearray(data[:HEADER] + body)
    for at, less in SIZE_FIELDS.items():
        if struct.unpack_from("<I", data, at)[0] != len(data) - less:
            raise ValueError("unexpected Binary header at %d" % at)
        struct.pack_into("<I", out, at, len(out) - less)
    return bytes(out)


def make(data, car=b"THAR"):
    body = re.sub(rb"GTI(_0\d)?_CV", lambda m: car + (m.group(1) or b"") + b"_CV", data[HEADER:])
    body = body.replace(b"LONGNOSECAB", car)
    return rewrite(data, body)


def main(argv):
    out_dir = argv[0] if argv else OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "DBModelParts.bin")
    with open(TEMPLATE, "rb") as f:
        data = make(f.read())
    with open(out, "wb") as f:
        f.write(data)
    return out


if __name__ == "__main__":
    print(main(sys.argv[1:]))
