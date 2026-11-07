"""The car-select logos of an add-on car, as DDS files for Binarius's `bind_textures` into FRONTEND\\FrontB.lzc.

    python tools/carbuild/logo.py <maker logo .png> <out dir>

The game looks a logo up by name (speed.exe; docs/carbuild-format.md "Logos in the car select"):
  - the maker's: CARSELECT_MANUFACTURER_<maker> (FECarRecord::GetManuLogoHash 0x591330), where the maker is the
    frontend entry's parent node (the Unlimiter's manufacturer hook); 128 x 64 in every game and add-on logo;
  - the model's: SECONDARY_LOGO_<frontend CollectionName> (FECarRecord::GetLogoHash 0x591240); 256 x 64 in the game,
    512 x 128 in the Chiron add-on;
  - both hashed upper-cased (0x5AF1C0); a missing one falls back to GENERIC_LOGO_128 / _256.
Written as the Chiron add-on's (the one we know Binarius binds and the game shows): DXT3 with a full mip chain, the maker
logo in its own colours, the model logo a white wordmark. A .png of each (what the DDS was made from) is written beside
it, and preview.png shows both on a dark background.
"""
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

MAKER_SIZE = (128, 64)
MODEL_SIZE = (512, 128)
FONT = r"C:/Windows/Fonts/arialbd.ttf"


def _fit(im, size, fill_h=0.94, fill_w=0.94):
    """The picture scaled to fit inside size (keeping its proportions), centred on a transparent canvas."""
    im = im.crop(im.getchannel("A").getbbox())
    scale = min(size[0] * fill_w / im.size[0], size[1] * fill_h / im.size[1])
    im = im.resize((max(1, round(im.size[0] * scale)), max(1, round(im.size[1] * scale))), Image.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.alpha_composite(im, ((size[0] - im.size[0]) // 2, (size[1] - im.size[1]) // 2))
    return out


def twin_peaks(src_png):
    """The 2021 SUV logo: the left part of Commons' "Mahindra Automotive new logo" (the right part is the electric
    range's infinity mark), cut at the widest fully transparent gap of columns."""
    im = Image.open(src_png).convert("RGBA")
    a = im.getchannel("A")
    w, h = im.size
    cols = [a.crop((x, 0, x + 1, h)).getextrema()[1] for x in range(w)]
    gaps, start = [], None
    for x, c in enumerate(cols + [255]):
        if c < 8 and start is None:
            start = x
        elif c >= 8 and start is not None:
            if start > 0 and x < w:
                gaps.append((x - start, start, x))
            start = None
    if not gaps:
        return im
    _, cut, _ = max(gaps)
    return im.crop((0, 0, cut, h))


def wordmark(text, size):
    """White capital letters, the model logo the game's own cars carry (a name in the car's typeface)."""
    big = Image.new("RGBA", (size[0] * 4, size[1] * 4), (0, 0, 0, 0))
    font = ImageFont.truetype(FONT, size[1] * 3)
    d = ImageDraw.Draw(big)
    d.text((size[0] * 2, size[1] * 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return _fit(big, size, fill_h=0.6, fill_w=0.7)


# ---------------------------------------------------------------- DXT3

def _rgb565(c):
    return ((c[0] >> 3) << 11) | ((c[1] >> 2) << 5) | (c[2] >> 3)


def _unpack565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _block(px):
    """One 4x4 DXT3 block from 16 (r, g, b, a) pixels: explicit 4-bit alpha, then a colour block whose two end colours
    are the extremes along the widest channel range of the block's visible pixels (alpha at least half the block's
    highest: the download's edges carry nearly transparent pixels of any colour, which must not pick the colours)."""
    alpha = 0
    for i, p in enumerate(px):
        alpha |= ((p[3] * 15 + 127) // 255) << (4 * i)
    top = max(p[3] for p in px)
    seen = [p for p in px if p[3] > 0 and p[3] * 2 >= top] or px
    lo = [min(p[k] for p in seen) for k in range(3)]
    hi = [max(p[k] for p in seen) for k in range(3)]
    axis = max(range(3), key=lambda k: hi[k] - lo[k])
    c0 = max(seen, key=lambda p: (p[axis], sum(p[:3])))
    c1 = min(seen, key=lambda p: (p[axis], sum(p[:3])))
    v0, v1 = _rgb565(c0), _rgb565(c1)
    if v0 < v1:
        v0, v1 = v1, v0
    if v0 == v1:
        idx = 0
    else:
        e0, e1 = _unpack565(v0), _unpack565(v1)
        pal = [e0, e1, tuple((2 * a + b) // 3 for a, b in zip(e0, e1)), tuple((a + 2 * b) // 3 for a, b in zip(e0, e1))]
        idx = 0
        for i, p in enumerate(px):
            best = min(range(4), key=lambda k: sum((p[j] - pal[k][j]) ** 2 for j in range(3)))
            idx |= best << (2 * i)
    return struct.pack("<QHHI", alpha, v0, v1, idx)


def _dxt3(im):
    w, h = im.size
    px = im.load()
    out = bytearray()
    for by in range(0, max(h, 4), 4):
        for bx in range(0, max(w, 4), 4):
            out += _block([px[min(bx + x, w - 1), min(by + y, h - 1)] for y in range(4) for x in range(4)])
    return bytes(out)


def write_dds_dxt3(im, path):
    """A DXT3 DDS with every mip level down to 1 x 1 (as the Chiron's logos), each level a box-filtered half."""
    im = im.convert("RGBA")
    w, h = im.size
    levels, data, cur = 0, b"", im
    while True:
        data += _dxt3(cur)
        levels += 1
        if cur.size == (1, 1):
            break
        cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)), Image.BOX)
    linear = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    pf = struct.pack("<II4sI4I", 32, 0x4, b"DXT3", 0, 0, 0, 0, 0)
    head = struct.pack("<7I", 124, flags, h, w, linear, 0, levels) + bytes(44) + pf + \
        struct.pack("<4I", 0x1000 | 0x400008, 0, 0, 0) + bytes(4)
    with open(path, "wb") as f:
        f.write(b"DDS " + head + data)


def make_logo_textures(src_png, out_dir, maker="MAHINDRA", car="THAR", model_text="THAR"):
    """Writes CARSELECT_MANUFACTURER_<maker>.dds (the maker logo from src_png) and SECONDARY_LOGO_<car>.dds (a
    white wordmark) into out_dir, each with the .png it was made from; returns the two DDS paths."""
    os.makedirs(out_dir, exist_ok=True)
    pictures = {"CARSELECT_MANUFACTURER_%s" % maker.upper(): _fit(twin_peaks(src_png), MAKER_SIZE),
                "SECONDARY_LOGO_%s" % car.upper(): wordmark(model_text, MODEL_SIZE)}
    out = []
    for name, im in pictures.items():
        im.save(os.path.join(out_dir, name + ".png"))
        dds = os.path.join(out_dir, name + ".dds")
        write_dds_dxt3(im, dds)
        out.append(dds)
    preview = Image.new("RGBA", (MODEL_SIZE[0], MAKER_SIZE[1] * 2 + MODEL_SIZE[1] + 24), (40, 44, 52, 255))
    preview.alpha_composite(pictures["CARSELECT_MANUFACTURER_%s" % maker.upper()].resize(
        (MAKER_SIZE[0] * 2, MAKER_SIZE[1] * 2), Image.NEAREST), ((MODEL_SIZE[0] - MAKER_SIZE[0] * 2) // 2, 8))
    preview.alpha_composite(pictures["SECONDARY_LOGO_%s" % car.upper()], (0, MAKER_SIZE[1] * 2 + 16))
    preview.save(os.path.join(out_dir, "preview.png"))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    for p in make_logo_textures(sys.argv[1], sys.argv[2]):
        print(p)
