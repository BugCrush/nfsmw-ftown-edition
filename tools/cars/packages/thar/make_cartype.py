"""The Thar's car type (CarTypeInfos.bin, Binary's serialized form) from the Tomahawk mod's.

    python tools/cars/packages/thar/make_cartype.py [<out dir>]

Binary serializes a CarTypeInfo as its header (gMpB ... RAWW, sizes as in DBModelParts) and the record with the car
type name and the maker name as null-terminated strings, then the remaining fields (Binary computes the name hash and
the model folder from the name). The Tomahawk's (nfsmods 5882) is a racer (usage 0 before CarMemTypeHash "Racing") and
skinnable (the byte before the last four; the Longnose Cab's 0 there drew no body): the same bytes as the Chiron's apart
from the names and the last four. TOMAHAWK becomes THAR and DODGE becomes MAHINDRA, and the last four (DefaultBasePaint,
the paint a new or Quick Race Thar wears) become CHROME01_PAINT, the game's silver chrome (the user: "make the default
colour chrome").
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
from make_parts import HEADER, OUT_DIR, rewrite  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "tools", "carbuild"))
from chunks import bstringhash  # noqa: E402

TEMPLATE = os.path.join(REPO, ".superpowers", "downloads", "cars", "5882", "files", "Binary Files", "_CarParts",
                        "CarTypeInfos.bin")
NAMES = (b"TOMAHAWK\0DODGE\0", b"THAR\0MAHINDRA\0")
DEFAULT_PAINT = "CHROME01_PAINT"


def make(data):
    body = data[HEADER:]
    if not body.startswith(NAMES[0]):
        raise ValueError("not the Tomahawk's car type: %r" % body[:20])
    if body[-5] != 1:
        raise ValueError("the template is not skinnable")
    rest = body[len(NAMES[0]):-4] + struct.pack("<I", bstringhash(DEFAULT_PAINT))
    return rewrite(data, NAMES[1] + rest)


def main(argv):
    out_dir = argv[0] if argv else OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "CarTypeInfos.bin")
    with open(TEMPLATE, "rb") as f:
        data = make(f.read())
    with open(out, "wb") as f:
        f.write(data)
    return out


if __name__ == "__main__":
    print(main(sys.argv[1:]))
