"""Rockport's world colours, measured from the game's files (read only; numbers only, no pixels kept), for F-Town's
textures and vertex colours (docs/ftown-notes.md "City fixes (2026-11-03)", fault 3).

    .tools/cityenv/Scripts/python tools/citymap/rockport_colours.py [out.json]

1. Textures by name (every world texture pack of every section of STREAML2RA.BUN): grass, dirt (dirt, gravel, mud,
   earth), sidewalk, concrete, plaster (stucco, plaster): mip 0 decoded (the colour of DXT1/3/5), per texture the
   mean colour, luminance (Rec. 601), chroma (max - min channel per pixel, averaged) and grain (mean |dL| between
   horizontal neighbours); per category the medians.
2. Vertex colours of kind-0 (36-byte vertex) meshes, area weighted: terrain instances (exclude flag 0x80) by texture
   prefix (SHD_ shadow decals, TRNS_ road lanes, ...), non-terrain upward ground (normal z > 0.9) and walls
   (|normal z| < 0.25).
"""
import json
import os
import re
import statistics
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

from world import bun, scenery, texpack  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")
CATEGORIES = {"grass": r"GRASS|LAWN|TURF", "dirt": r"DIRT|SOIL|MUD|GRAVEL|EARTH", "sidewalk": r"SIDEWALK|SDWLK|SWALK",
              "concrete": r"CONC|CEMENT", "plaster": r"PLASTER|STUCCO|STCO"}


def decode(t):
    """Mip 0 of a world texture as an (h, w, 3) float array (DXT1/3/5 colour), or None for other formats."""
    w, h = struct.unpack_from("<hh", t.info, 0x44)
    comp = t.info[0x4A]
    if comp not in (0x22, 0x24, 0x26) or w < 4 or h < 4:
        return None
    bs = 8 if comp == 0x22 else 16
    n = (w // 4) * (h // 4)
    raw = np.frombuffer(t.data[:n * bs], dtype=np.uint8).reshape(n, bs)[:, bs - 8:]
    c0 = raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
    c1 = raw[:, 2].astype(np.int32) | (raw[:, 3].astype(np.int32) << 8)
    idx = raw[:, 4:8].copy().view(np.uint32)[:, 0]

    def rgb(c):
        r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], 1).astype(np.float64)
    a, b = rgb(c0), rgb(c1)
    four = (c0 > c1) | (bs == 16)
    pal = np.stack([a, b, np.where(four[:, None], (2 * a + b) / 3, (a + b) / 2),
                    np.where(four[:, None], (a + 2 * b) / 3, 0)], 1)
    k = np.stack([(idx >> (2 * j)) & 3 for j in range(16)], 1).astype(np.int64)
    px = np.take_along_axis(pal, k[:, :, None], 1)
    return px.reshape(h // 4, w // 4, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 3)


def stats(img):
    """Mean colour, luminance, chroma (per pixel, averaged) and grain of an (h, w, 3) image."""
    L = 0.299 * img[..., 0] + 0.587 * img[..., 1] + 0.114 * img[..., 2]
    return {"mean": [round(float(v), 1) for v in img.reshape(-1, 3).mean(0)], "lum": round(float(L.mean()), 1),
            "chroma": round(float((img.max(2) - img.min(2)).mean()), 1),
            "grain": round(float(np.abs(np.diff(L, axis=1)).mean()), 1)}


def measure():
    seen, names = {}, {}
    vc = {}

    def add(key, col, area):
        s = vc.setdefault(key, [np.zeros(4), 0.0])
        s[0] += (col * area[:, None]).sum(0)
        s[1] += area.sum()
    for s in bun.sections(L2RA):
        solids, scs = {}, []
        for c, p in scenery.with_positions(bun.read_range(STREAM, s.offset, s.size), 0):
            if c.id == texpack.PACK:
                try:
                    pk = texpack.read_pack(c, p)
                except ValueError:
                    continue
                for t in pk.textures:
                    nm = t.info[0x0C:0x24].split(b"\0")[0].decode("latin-1")
                    names[t.name_hash] = nm
                    if nm in seen:
                        continue
                    for cat, pat in CATEGORIES.items():
                        if re.search(pat, nm):
                            img = decode(t)
                            if img is not None:
                                seen[nm] = (cat, stats(img))
                            break
            elif c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        try:
                            so = scenery.read_solid(k, kp)
                        except (ValueError, struct.error):
                            continue
                        solids[so.name_hash] = so
            elif c.id == scenery.SCENERY_SECTION:
                scs.append(scenery.read_scenery(c, p))
        for sc in scs:
            for inst in sc.instances:
                so = solids.get(sc.infos[inst.info_index].solid_hashes[0])
                if so is None:
                    continue
                R = np.array([r[:3] for r in inst.matrix[:3]])
                for k, m in enumerate(so.meshes):
                    if m.kind != 0 or so.stride(m.buffer) != 36:
                        continue
                    tri = np.array(so.triangles(k), dtype=np.int64)
                    if not len(tri):
                        continue
                    buf = so.vertex_buffers[m.buffer]
                    vs = np.frombuffer(buf[m.vertex_offset * 36:(m.vertex_offset + m.vertex_count) * 36],
                                       dtype=np.uint8).reshape(-1, 36)
                    wp = vs[:, 0:12].copy().view(np.float32).reshape(-1, 3).astype(np.float64) @ R
                    col = vs[:, 24:28].astype(np.float64)[:, [2, 1, 0, 3]]  # B, G, R, A -> R, G, B, A
                    A, B, C = wp[tri[:, 0]], wp[tri[:, 1]], wp[tri[:, 2]]
                    nrm = np.cross(B - A, C - A)
                    area = 0.5 * np.linalg.norm(nrm, axis=1)
                    nz = np.abs(nrm[:, 2]) / np.maximum(1e-9, 2 * area)
                    tc = (col[tri[:, 0]] + col[tri[:, 1]] + col[tri[:, 2]]) / 3
                    if inst.exclude_flags & 0x80:
                        th = so.textures[m.texture_slots[0]] if m.texture_slots[0] < len(so.textures) else 0
                        add("terrain " + names.get(th, "?").split("_")[0], tc, area)
                    else:
                        g, w = nz > 0.9, nz < 0.25
                        add("ground (non-terrain)", tc[g], area[g])
                        add("walls (non-terrain)", tc[w], area[w])
    out = {"textures": {}, "vertex_colours": {}}
    for cat in CATEGORIES:
        rs = [st for c, st in seen.values() if c == cat]
        if rs:
            out["textures"][cat] = {
                "n": len(rs), "lum": statistics.median(r["lum"] for r in rs),
                "lum_quartiles": [sorted(r["lum"] for r in rs)[len(rs) // 4],
                                  sorted(r["lum"] for r in rs)[3 * len(rs) // 4]],
                "chroma": statistics.median(r["chroma"] for r in rs),
                "grain": statistics.median(r["grain"] for r in rs),
                "mean": [round(statistics.median(r["mean"][i] for r in rs), 1) for i in range(3)]}
    for key, (s, a) in sorted(vc.items(), key=lambda kv: -kv[1][1]):
        if a > 1e4:
            out["vertex_colours"][key] = {"m2": round(a), "rgba": [round(v) for v in (s / a).tolist()]}
    return out


def main(argv):
    out = measure()
    text = json.dumps(out, indent=1)
    print(text)
    if argv:
        with open(argv[0], "w", newline="\n") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
