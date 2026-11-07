"""Before/after of F-Town's minimap as the HUD shows it (Run I fixes, item 3): the chops decoded from two built files
(ftown-minimap.bun), a 400 m square around a point cut out and magnified to the HUD's size (a chop spans 128 of the
HUD's 640 x 480 units: at 1,260 lines about 336 pixels), bilinear as the GPU samples.

    .tools/cityenv/Scripts/python tools/citymap/render_minimap.py <before.bun> <after.bun> <out.png> [x y ...]
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image  # noqa: E402

from chunks import bstringhash, read_chunks  # noqa: E402
from world.texpack import read_pack  # noqa: E402

from tools.citymap import minimap  # noqa: E402

HUD_PX_PER_M = 336.0 / (minimap.WIDTH / 8)  # one chop (WIDTH / 8 m) over about 336 screen pixels


def picture(path):
    with open(path, "rb") as f:
        pack = read_pack(read_chunks(f.read())[0], 8)
    by = {t.name_hash: t for t in pack.textures}
    t0 = by[bstringhash("%s_CHOP0" % minimap.HEADER)]
    ch = struct.unpack_from("<h", t0.info, 0x44)[0]
    img = np.zeros((ch * 8, ch * 8, 3), np.uint8)
    for n in range(64):
        r, c = divmod(n, 8)
        t = by[bstringhash("%s_CHOP%d" % (minimap.HEADER, n))]
        img[r * ch:(r + 1) * ch, c * ch:(c + 1) * ch] = minimap.dxt3_decode(t.data, ch, ch)[..., :3]
    return img


def crop(img, x, y, metres=400.0):
    side = img.shape[0]
    mx, my = minimap.to_map(x, y)
    half = metres / minimap.WIDTH * side / 2
    box = (mx * side - half, my * side - half, mx * side + half, my * side + half)
    out = int(metres * HUD_PX_PER_M)
    return Image.fromarray(img).resize((out, out), Image.Resampling.BILINEAR, box=box)


def main(argv):
    before, after, out = argv[:3]
    pts = [float(v) for v in argv[3:]] or [1470.0, 9560.0, 2095.0, 12500.0, 1372.0, 10820.0]
    pics = [picture(before), picture(after)]
    tiles = [[crop(p, pts[k], pts[k + 1]) for p in pics] for k in range(0, len(pts), 2)]
    w, h = tiles[0][0].size
    sheet = Image.new("RGB", (2 * w + 10, len(tiles) * (h + 10)), (255, 255, 255))
    for i, (a, b) in enumerate(tiles):
        sheet.paste(a, (0, i * (h + 10)))
        sheet.paste(b, (w + 10, i * (h + 10)))
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
