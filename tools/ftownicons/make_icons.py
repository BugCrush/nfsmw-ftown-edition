"""F-Town's menu icons (Run I item 13): the user's three logos as one texture pack FTownLoader hands to the game.

    .tools/cityenv/Scripts/python tools/ftownicons/make_icons.py [icons dir] [out file]

Inputs (the user's own, git-ignored `icons/`): ftown-morning.png (the "F town" wordmark, black on white), ftown-evening.png
(white on black), freeroam.png (a black glyph on transparent). Output (git-ignored, rebuilt by this script):
`ftown/ftown-icons.bun`, one texture pack chunk 0xB3300000 (its data at 8, as ftown-minimap.bun) holding

    FTOWN_ICON_MORNING   the "F-Town" map entry
    FTOWN_ICON_EVENING   the "F-Town (Evening)" map entry
    FTOWN_ICON_FREEROAM  the "Free Roam" mode (drawn white on transparent: the game's mode icons are light glyphs on the
                         dark menu, a black glyph would not show)

128 x 128 DXT3 (explicit alpha), one mip level; the TextureInfo's +0x4F..+0x67 and the format record are those of the
game's own mode icon MODE_ICON_DRAG (GLOBAL\\GLOBALB.BUN, 64 x 64 DXT3, one level). The front end looks icons up by name
hash (IconOption 0x586FA0) in every loaded pack: FTownLoader loads this one with LoadChunks when the Quick Race menu
is first built.
"""
import hashlib
import os
import struct
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(REPO, "tools", "carbuild"), os.path.join(REPO, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import bstringhash, chunk_bytes  # noqa: E402
from logo import _dxt3  # noqa: E402
from world import texpack  # noqa: E402

ICONS = os.path.join(REPO, "icons")
OUT = os.path.join(REPO, "ftown", "ftown-icons.bun")
SIDE = 128
NAMES = [("FTOWN_ICON_MORNING", "ftown-morning.png", "as is"),
         ("FTOWN_ICON_EVENING", "ftown-evening.png", "as is"),
         ("FTOWN_ICON_FREEROAM", "freeroam.png", "white")]
COMP_DXT3 = 0x24
CLASS_HASH = 0x001A93CF
# MODE_ICON_DRAG's TextureInfo +0x4F..+0x57 and +0x58..+0x67, and its format record (GLOBALB.BUN)
FLAGS_4F = bytes.fromhex("000005000000020100")
SCROLL_58 = bytes.fromhex("00010000000000000000000100010000")
FORMAT = bytes.fromhex("0000000000000000010000000500000006000000445854330000000000000000")


def prepare(path, mode):
    """The logo as a SIDE x SIDE RGBA picture: opaque logos scaled whole; a glyph on transparent drawn white."""
    im = Image.open(path).convert("RGBA").resize((SIDE, SIDE), Image.LANCZOS)
    if mode == "white":
        alpha = im.getchannel("A")
        im = Image.merge("RGBA", (Image.new("L", im.size, 255),) * 3 + (alpha,))
    return im


def texture(name, im):
    data = _dxt3(im)
    info = bytearray(texpack.TI)
    raw = name.encode("ascii")[:23]
    info[0x0C:0x0C + len(raw)] = raw
    shift = SIDE.bit_length() - 1
    struct.pack_into("<III", info, 0x24, bstringhash(name), CLASS_HASH, 0)
    struct.pack_into("<iiiii", info, 0x30, 0, 0, len(data), 0, len(data))
    struct.pack_into("<hhBBBBhB", info, 0x44, SIDE, SIDE, shift, shift, COMP_DXT3, 0, 0, 1)
    info[0x4F:0x58] = FLAGS_4F
    info[0x58:0x68] = SCROLL_58
    return texpack.WorldTexture(bytes(info), FORMAT, data)


def build(icons=ICONS):
    tex = [texture(name, prepare(os.path.join(icons, f), mode)) for name, f, mode in NAMES]
    pack = texpack.new_pack("FTOWNICONS", "ftown-icons.tpk", tex)
    return chunk_bytes(texpack.write_pack(pack, 8))


def main():
    icons = sys.argv[1] if len(sys.argv) > 1 else ICONS
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    blob = build(icons)
    with open(out, "wb") as f:
        f.write(blob)
    print("%s: %d bytes, sha256 %s; %s" % (out, len(blob), hashlib.sha256(blob).hexdigest(),
                                           ", ".join("%s 0x%08X" % (n, bstringhash(n)) for n, _, _ in NAMES)))


if __name__ == "__main__":
    main()
