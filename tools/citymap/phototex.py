"""Crops of the user's photos for F-Town's landmarks: since 2026-11-04 a reference and measuring tool only (the user:
the photos "were for you to take reference from and actually build the look of the building yourself"). The city
build no longer uses these crops: the faces are drawn by tools/citymap/landmark_tex.py (docs/ftown-notes.md "Own
looks and a lived-in city"); the build still uses this module's DXT1 encoder and its colour-range rule on our own
pixels. The photos and everything made from them stay out of git: the outputs go to
.superpowers/citymap/faridabad/phototex/, git-ignored.

    .tools/cityenv/Scripts/python tools/citymap/phototex.py [out dir]      (builds every texture and sheet.png)

For each face of the registry (tools/citymap/landmarks/registry.json):
1. the photo's "patch" rectangles (Google's labels and pins over a facade) are filled from the columns either side;
2. the crop quad (corners in the photo's pixels, top left, top right, bottom right, bottom left) is rectified to the
   face's texture size by a perspective transform (at twice the size, then halved: no aliasing on signboards);
3. an optional "clean_bottom" fraction is replaced by the rows above it, mirrored (cars and people at a facade's foot);
4. colour matched to Rockport's walls: the mean luminance brought inside LUM by one scale for all channels, the mean
   chroma held under CHROMA_MAX by mixing towards grey (docs/ftown-notes.md "Landmarks and street furniture");
5. written as PNG (the pixels) and as DXT1 with a full mip chain (what the texture pack carries), with a manifest of
   sha256 per texture. Deterministic: two builds are identical (test_phototex).
"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.citymap import landmarks  # noqa: E402

OUT = os.path.join(REPO, ".superpowers", "citymap", "faridabad", "phototex")
LUM = (65.0, 100.0)  # mean luminance of a texture (Rockport: walls 73, plaster 85.9, sidewalk 94.6)
LUM_TARGET = (72.0, 92.0)  # where the scale brings a photo whose mean falls outside
CHROMA_MAX = 48.0
CHROMA_TARGET = 44.0
PREFIX = "FTL_"


def texture_name(face_name):
    return (PREFIX + face_name)[:23]


def _565(c):
    c = c.astype(np.int32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _from565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)


def dxt1_encode(img):
    """DXT1 of an (h, w, 3) uint8 image, the same bytes as tools/world/texpack.py's dxt1_encode (block endpoints the
    darkest and brightest pixel by 3r + 6g + b, the first one on a tie; each pixel the nearest of the four colours,
    the first on a tie), vectorised."""
    h, w, _ = img.shape
    blk = img.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
    lum = blk[..., 0] * 3 + blk[..., 1] * 6 + blk[..., 2]
    hi = blk[np.arange(len(blk)), lum.argmax(1)]
    lo = blk[np.arange(len(blk)), lum.argmin(1)]
    c0, c1 = _565(hi), _565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    a, b = _from565(c0), _from565(c1)
    pal = np.stack([a, b, (2 * a + b) // 3, (a + 2 * b) // 3], 1)  # c0 > c1: four colours
    d = ((blk[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(2)
    bits = (idx.astype(np.uint64) << (2 * np.arange(16, dtype=np.uint64))[None, :]).sum(1).astype(np.uint32)
    bits = np.where(c0 == c1, 0, bits).astype(np.uint32)
    out = np.zeros((len(blk), 2), dtype=np.uint32)
    out[:, 0] = (c0.astype(np.uint32) & 0xFFFF) | ((c1.astype(np.uint32) & 0xFFFF) << 16)
    out[:, 1] = bits
    return out.astype("<u4").tobytes()


def encode_list(px, w, h):
    """dxt1_encode for texpack.new_texture(encode=...): pixels [(r, g, b)] row by row."""
    return dxt1_encode(np.asarray(px, dtype=np.uint8).reshape(h, w, 3))


def mips(img):
    """[(h, w, 3) uint8] mip 0 down to 8 pixels on the shorter side, each the 2 x 2 rounded mean of the one above (as
    texpack._half)."""
    out = [img]
    cur = img.astype(np.int32)
    while min(cur.shape[:2]) >= 16:
        cur = (cur[0::2, 0::2] + cur[0::2, 1::2] + cur[1::2, 0::2] + cur[1::2, 1::2] + 2) // 4
        out.append(cur.astype(np.uint8))
    return out


def dxt1_with_mips(img):
    return b"".join(dxt1_encode(m) for m in mips(img))


def _patch(arr, rects):
    """Fill each rectangle row by row with a linear blend of the columns just outside it (left and right)."""
    h, w, _ = arr.shape
    for x0, y0, x1, y1 in rects:
        x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
        left = arr[y0:y1, max(0, x0 - 1)].astype(float)
        right = arr[y0:y1, min(w - 1, x1)].astype(float)
        if x0 == 0:
            left = right
        if x1 >= w:
            right = left
        t = (np.arange(x0, x1) - x0 + 0.5) / max(1, x1 - x0)
        arr[y0:y1, x0:x1] = (left[:, None, :] * (1 - t)[None, :, None] + right[:, None, :] * t[None, :, None]).round()
    return arr


def _coeffs(quad, w, h):
    """PIL's PERSPECTIVE coefficients mapping the output rectangle (w x h) onto the quad in the source."""
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    A, B = [], []
    for (x, y), (u, v) in zip(dst, quad):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        B.append(v)
    return [float(c) for c in np.linalg.solve(np.array(A, dtype=float), np.array(B, dtype=float))]


def colour_match(arr):
    """(the matched image, (luminance, chroma) before, after)."""
    px = arr.astype(float)
    lum0 = float((px @ np.array([0.299, 0.587, 0.114])).mean())
    ch0 = float((px.max(-1) - px.min(-1)).mean())
    target = min(max(lum0, LUM_TARGET[0]), LUM_TARGET[1])
    px = px * (target / max(1.0, lum0))
    ch = float((np.clip(px, 0, 255).max(-1) - np.clip(px, 0, 255).min(-1)).mean())
    if ch > CHROMA_TARGET:
        grey = (px @ np.array([0.299, 0.587, 0.114]))[..., None]
        k = CHROMA_TARGET / ch
        px = grey + (px - grey) * k
    out = np.clip(px, 0, 255).round().astype(np.uint8)
    o = out.astype(float)
    return out, (lum0, ch0), (float((o @ np.array([0.299, 0.587, 0.114])).mean()), float((o.max(-1) - o.min(-1)).mean()))


def crop(face, reg, photos_dir=landmarks.PHOTOS):
    """The rectified, cleaned crop of a face (registry dict) as an (h, w, 3) uint8 array, before colour matching."""
    files = landmarks.photo_files(photos_dir)
    with Image.open(os.path.join(photos_dir, files[face["photo"]])) as im:
        arr = np.array(im.convert("RGB"))
    _block, patch = landmarks.overlays(reg, face["photo"])
    arr = _patch(arr, patch)
    w, h = face["tex"]
    big = Image.fromarray(arr).transform((2 * w, 2 * h), Image.Transform.PERSPECTIVE,
                                         _coeffs([tuple(c) for c in face["corners"]], 2 * w, 2 * h),
                                         Image.Resampling.BICUBIC)
    out = np.array(big.resize((w, h), Image.Resampling.BOX))
    cb = face.get("clean_bottom", 0.0)
    if cb:
        n = min(int(round(h * cb)), h // 2)
        out[h - n:] = out[h - 2 * n:h - n][::-1].copy()
    return out


def faces(reg):
    """[(texture name, face dict)], one per texture name (faces naming one texture must agree on its crop)."""
    seen = {}
    for d in reg["landmarks"]:
        for k, f in enumerate(d.get("faces", [])):
            name = texture_name(f.get("name") or "%s_%d" % (d["key"], k))
            spec = (f["photo"], tuple(map(tuple, f["corners"])), tuple(f["tex"]), f.get("clean_bottom", 0.0))
            if name in seen and seen[name][0] != spec:
                raise ValueError("%s: two faces name one texture with different crops" % name)
            seen.setdefault(name, (spec, f))
    return [(n, s[1]) for n, s in seen.items()]


def spec_hash(face, reg):
    """sha256 of everything a face's texture is made from: its photo, crop, size, the photo's overlays and the colour
    constants (a build rebuilds a texture whose spec changed)."""
    block, patch = landmarks.overlays(reg, face["photo"])
    spec = [face["photo"], face["corners"], face["tex"], face.get("clean_bottom", 0.0), block, patch,
            LUM_TARGET, CHROMA_TARGET, 2]
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def make(face, reg, photos_dir=landmarks.PHOTOS, out_dir=OUT, name=None):
    """Builds one face's texture into out_dir: (record for the manifest)."""
    name = name or texture_name(face["name"])
    img, before, after = colour_match(crop(face, reg, photos_dir))
    os.makedirs(out_dir, exist_ok=True)
    png = name.lower() + ".png"
    Image.fromarray(img).save(os.path.join(out_dir, png), optimize=False)
    dxt = dxt1_with_mips(img)
    with open(os.path.join(out_dir, name.lower() + ".dxt"), "wb") as f:
        f.write(dxt)
    return {"png": png, "dxt": name.lower() + ".dxt", "size": [img.shape[1], img.shape[0]], "photo": face["photo"],
            "spec": spec_hash(face, reg),
            "sha256": hashlib.sha256(img.tobytes()).hexdigest(), "dxt_sha256": hashlib.sha256(dxt).hexdigest(),
            "before": [round(v, 1) for v in before], "after": [round(v, 1) for v in after]}


def build_all(reg, photos_dir=landmarks.PHOTOS, out_dir=OUT):
    """Every face texture into out_dir and manifest.json there: {"textures": {name: record}}."""
    man = {"textures": {}}
    for name, f in faces(reg):
        man["textures"][name] = make(f, reg, photos_dir, out_dir, name)
    with open(os.path.join(out_dir, "manifest.json"), "w", newline="\n") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    return man


def specs(out_dir=OUT):
    """{texture name: spec hash} of a built set ({} when never built)."""
    p = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return {n: r.get("spec") for n, r in json.load(f)["textures"].items()}


def load(out_dir=OUT):
    """{texture name: (w, h, (h, w, 3) array)} of a built set, or {} when it was never built (no photos)."""
    p = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        man = json.load(f)
    out = {}
    for name, rec in man["textures"].items():
        with Image.open(os.path.join(out_dir, rec["png"])) as im:
            arr = np.array(im.convert("RGB"))
        out[name] = (arr.shape[1], arr.shape[0], arr)
    return out


def sheet(reg, out_dir=OUT, photos_dir=landmarks.PHOTOS, path=None):
    """Each texture beside its photo with the crop quad drawn: sheet.png in out_dir (git-ignored, like the photos)."""
    files = landmarks.photo_files(photos_dir)
    rows = []
    for name, f in faces(reg):
        with Image.open(os.path.join(photos_dir, files[f["photo"]])) as im:
            ph = im.convert("RGB")
        dr = ImageDraw.Draw(ph)
        q = [tuple(c) for c in f["corners"]]
        dr.line(q + [q[0]], fill=(255, 0, 255), width=max(2, ph.size[0] // 200))
        block, patch = landmarks.overlays(reg, f["photo"])
        for r in block:
            dr.rectangle(r, outline=(255, 0, 0), width=2)
        for r in patch:
            dr.rectangle(r, outline=(0, 255, 255), width=2)
        s = 300.0 / max(ph.size)
        ph = ph.resize((int(ph.size[0] * s), int(ph.size[1] * s)))
        with Image.open(os.path.join(out_dir, name.lower() + ".png")) as t:
            tex = t.convert("RGB")
        k = min(500.0 / tex.size[0], 300.0 / tex.size[1])
        tex = tex.resize((int(tex.size[0] * k), int(tex.size[1] * k)), Image.Resampling.NEAREST)
        rows.append((name, ph, tex))
    W, H = 840, 320
    out = Image.new("RGB", (W * 2, H * ((len(rows) + 1) // 2)), (40, 40, 40))
    dr = ImageDraw.Draw(out)
    for k, (name, ph, tex) in enumerate(rows):
        x, y = (k % 2) * W, (k // 2) * H
        out.paste(ph, (x + 5, y + 15))
        out.paste(tex, (x + 320, y + 15))
        dr.text((x + 5, y + 2), name, fill=(255, 255, 255))
    path = path or os.path.join(out_dir, "sheet.png")
    out.save(path)
    return path


def main(argv):
    out = argv[0] if argv else OUT
    reg = landmarks.read()
    man = build_all(reg, landmarks.PHOTOS, out)
    for n, r in man["textures"].items():
        print(n, r["size"], "photo", r["photo"], "lum/chroma", r["before"], "->", r["after"])
    print(sheet(reg, out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
