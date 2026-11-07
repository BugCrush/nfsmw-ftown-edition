"""Textured renders of a built F-Town city file, drawn from the file itself (its solids placed by its scenery
instances, its own texture pack decoded), for comparing the landmarks with the user's photos.

    .tools/cityenv/Scripts/python tools/citymap/render_tex.py <city.bun> <out.png> x y z heading pitch [fov]

A pinhole camera (render metres, heading in degrees counter-clockwise from +x, pitch up), triangles clipped at the
near plane, a z-buffer, perspective-correct texture coordinates, nearest texels (wrapping), each texel times its
vertex colour over VC_ONE (render_city.py's: Rockport's ground grey = 1), a little haze. Slot-0 models only (what the
main view draws near). Back faces: drawn too, or with --cull (`cull=True`) left out as the game does: a triangle is
drawn from the side its right-hand normal (B - A) x (C - A) faces (docs/ftown-notes.md "Run H fixes"). Slot: --slot N
renders that model slot instead (2: the far level).

    .tools/cityenv/Scripts/python tools/citymap/render_tex.py <city.bun> <out.png> x y z heading pitch [fov] [--cull]
"""
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image  # noqa: E402

from chunks import read_chunks  # noqa: E402
from world import scenery, texpack  # noqa: E402

SKY = np.array([150, 185, 220], dtype=float)
VC_ONE = 72.0
HAZE = 900.0


def dxt1_decode(data, w, h):
    """(h, w, 3) uint8 of DXT1 mip 0 (numpy)."""
    blk = np.frombuffer(data[:w * h // 2], dtype="<u4").reshape(-1, 2)
    c0 = (blk[:, 0] & 0xFFFF).astype(np.int32)
    c1 = (blk[:, 0] >> 16).astype(np.int32)

    def rgb(v):
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)
    a, b = rgb(c0), rgb(c1)
    four = (c0 > c1)[:, None]
    p2 = np.where(four, (2 * a + b) // 3, (a + b) // 2)
    p3 = np.where(four, (a + 2 * b) // 3, 0)
    pal = np.stack([a, b, p2, p3], 1)
    idx = (blk[:, 1][:, None] >> (2 * np.arange(16, dtype=np.uint32))[None, :]) & 3
    px = pal[np.arange(len(blk))[:, None], idx]
    return px.reshape(h // 4, w // 4, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 3).astype(np.uint8)


class Scene:
    def __init__(self, path, slot=0, library=None, skip=(), extra=()):
        """slot: the model slot drawn for every instance, or "lod": slot 0 or 2 per instance and view by the game's
        rule (DrawAScenery 0x729120: slot 2 when the distance is 25 m or more and pixel size / max(Density, 6) < 8.7
        for a near model of 40 triangles or more; build_city.VIEW_H). library: x0_library()'s (solids, textures) for
        instances whose model the file names by hash only (the street life); their alpha-tested leaves are drawn.
        skip: info name prefixes left out (("FTS_", "FTV_"): the city without its street life). extra: more files whose
        chunks are read beside the city's (a race barrier file: its panels name X0 models)."""
        top = []
        for p_ in (path,) + tuple(extra):
            with open(p_, "rb") as f:
                top += list(scenery.with_positions(read_chunks(f.read()), 0))
        sols, scs = {}, []
        self.tex = {}
        for c, p in top:
            if c.id == scenery.SOLID_LIST:
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        so = scenery.read_solid(k, kp)
                        sols[so.name_hash] = so
            elif c.id == scenery.SCENERY_SECTION:
                scs.append(scenery.read_scenery(c, p))
            elif c.id == texpack.PACK:
                for t in texpack.read_pack(c, p).textures:
                    w, h = struct.unpack_from("<hh", t.info, 0x44)
                    self.tex[t.name_hash] = dxt1_decode(t.data, w, h)
        if library is not None:
            lsols, ltex = library
            for h, so in lsols.items():
                sols.setdefault(h, so)
            for h, t in ltex.items():
                self.tex.setdefault(h, t)
        P, UV, C, T, TAG = [], [], [], [], []
        texid = {h: k for k, h in enumerate(self.tex)}
        self.tex_list = list(self.tex.values())
        self.inst_info = []  # (position, radius + 6, near Density, near triangles) per instance, for "lod"
        slots = (0, 2) if slot == "lod" else (slot,)
        for sc in scs:
            for inst in sc.instances:
                info = sc.infos[inst.info_index]
                if skip and info.name.startswith(tuple(skip)):
                    continue
                ni = len(self.inst_info)
                s0 = sols.get(info.solid_hashes[0])
                self.inst_info.append((np.array(inst.matrix[3][:3], dtype=float), info.radius + 6.0,
                                       struct.unpack_from("<f", s0.header, 0x9C)[0] if s0 else 0.0,
                                       struct.unpack_from("<h", s0.header, 0x14)[0] if s0 else 0))
                for sl in slots:
                    so = sols.get(info.solid_hashes[sl])
                    if so is None:
                        continue
                    self._add(so, inst, texid, P, UV, C, T, TAG, ni * 4 + sl)
        self.P = np.concatenate(P)
        self.UV = np.concatenate(UV)
        self.C = np.concatenate(C)
        self.T = np.concatenate(T)
        self.TAG = np.concatenate(TAG)
        self.lod = slot == "lod"
        cc = self.C
        self.rgb = np.stack([(cc >> 16) & 255, (cc >> 8) & 255, cc & 255], -1).astype(float) / VC_ONE
        self.centre = self.P.mean(1)
        self.normal = np.cross(self.P[:, 1] - self.P[:, 0], self.P[:, 2] - self.P[:, 0])

    @staticmethod
    def _add(so, inst, texid, P, UV, C, T, TAG, tag):
        m = np.array(inst.matrix, dtype=float)
        for k, mesh in enumerate(so.meshes):
            th = so.textures[mesh.texture_slots[0]]
            st = so.stride(mesh.buffer)
            buf = so.vertex_buffers[mesh.buffer]
            nv = mesh.vertex_count
            raw = np.frombuffer(buf, dtype=np.uint8, count=nv * st, offset=mesh.vertex_offset * st)
            raw = raw.reshape(nv, st)
            pos = raw[:, 0:12].copy().view("<f4").astype(float)
            col = raw[:, 24:28].copy().view("<u4")[:, 0]
            uv = raw[:, 28:36].copy().view("<f4").astype(float)
            tri = np.array(so.triangles(k), dtype=np.int64)
            if not len(tri):
                continue
            wp = pos @ m[:3, :3] + m[3, :3]
            P.append(wp[tri])
            UV.append(uv[tri])
            C.append(col[tri[:, 0]])
            T.append(np.full(len(tri), texid.get(th, -1)))
            TAG.append(np.full(len(tri), tag))

    def _lod_mask(self, eye, view_h=1000.0):
        """Triangles of the slot each instance draws from `eye` (the game's rule, see __init__)."""
        want = []
        for pos, R, dens, ntri in self.inst_info:
            d = float(np.linalg.norm(pos - eye))
            px = view_h if d - R <= R else R * view_h / (d - R)
            want.append(2 if ntri > 39 and d >= 25.0 and px / max(6.0, dens) < 8.7 else 0)
        want = np.array(want)
        return want[self.TAG // 4] == self.TAG % 4

    def view(self, eye, heading, pitch, W=640, H=400, fov=70.0, far=600.0, cull=False):
        eye = np.array(eye, dtype=float)
        h, p = math.radians(heading), math.radians(pitch)
        fwd = np.array([math.cos(h) * math.cos(p), math.sin(h) * math.cos(p), math.sin(p)])
        right = np.array([math.sin(h), -math.cos(h), 0.0])
        up = np.cross(right, fwd)
        f = (W / 2) / math.tan(math.radians(fov) / 2)
        near = 0.3
        keep = np.linalg.norm(self.centre - eye, axis=1) < far + 50
        if self.lod:
            keep &= self._lod_mask(eye)
        idx = np.nonzero(keep)[0]
        rel = self.P[idx] - eye
        cz = rel @ fwd
        idx = idx[(cz > near).any(1)]
        if cull:
            idx = idx[((eye[None, :] - self.centre[idx]) * self.normal[idx]).sum(1) > 0]
        img = np.tile(SKY, (H, W, 1))
        zb = np.full((H, W), np.inf)
        ys, xs = np.mgrid[0:H, 0:W]
        for k in idx:
            tri = self.P[k] - eye
            cam = np.stack([tri @ right, tri @ up, tri @ fwd], -1)
            uv = self.UV[k]
            poly = _clip(cam, uv, near)
            if poly is None:
                continue
            pc, puv = poly
            sx = W / 2 + f * pc[:, 0] / pc[:, 2]
            sy = H / 2 - f * pc[:, 1] / pc[:, 2]
            for a in range(1, len(pc) - 1):
                _raster(img, zb, xs, ys, sx[[0, a, a + 1]], sy[[0, a, a + 1]], pc[[0, a, a + 1], 2],
                        puv[[0, a, a + 1]], self.tex_list[self.T[k]] if self.T[k] >= 0 else None, self.rgb[k], W, H)
        d = np.where(np.isinf(zb), far, zb)
        fog = np.clip(d / HAZE, 0, 1)[..., None] * 0.6
        img = img * (1 - fog) + SKY * fog
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def dxt_rgba(data, w, h, comp):
    """(h, w, 4) uint8 of mip 0 of a DXT1 (TextureInfo +0x4A 0x22: alpha 0 where a 3-colour block picks index 3),
    DXT3 (0x24) or DXT5 (0x26) texture: Rockport's textures for the street life's renders (read only, not kept)."""
    w4, h4 = max(4, w), max(4, h)
    n = (w4 // 4) * (h4 // 4)
    bs = 8 if comp == 0x22 else 16
    raw = np.frombuffer(data[:n * bs], dtype=np.uint8).reshape(n, bs)
    col = raw[:, bs - 8:].copy().view("<u4").reshape(n, 2)
    c0 = (col[:, 0] & 0xFFFF).astype(np.int32)
    c1 = (col[:, 0] >> 16).astype(np.int32)

    def rgb(v):
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)
    a, b = rgb(c0), rgb(c1)
    four = ((c0 > c1) | (comp != 0x22))[:, None]
    pal = np.stack([a, b, np.where(four, (2 * a + b) // 3, (a + b) // 2), np.where(four, (a + 2 * b) // 3, 0)], 1)
    idx = (col[:, 1][:, None] >> (2 * np.arange(16, dtype=np.uint32))[None, :]) & 3
    px = pal[np.arange(n)[:, None], idx]
    if comp == 0x22:
        alpha = np.where((~four[:, 0])[:, None] & (idx == 3), 0, 255)
    elif comp == 0x24:
        nib = raw[:, :8]
        alpha = np.stack([(nib[:, k // 2] >> (4 * (k % 2))) & 15 for k in range(16)], 1) * 17
    else:
        a0, a1 = raw[:, 0].astype(int), raw[:, 1].astype(int)
        bits = np.zeros(n, dtype=np.uint64)
        for k in range(6):
            bits |= raw[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
        ai = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None, :]) & np.uint64(7)).astype(int)
        big = (a0 > a1)[:, None]
        lerp7 = ((7 - ai) * a0[:, None] + ai * a1[:, None]) // 7
        lerp5 = ((5 - ai) * a0[:, None] + ai * a1[:, None]) // 5
        alpha = np.where(ai == 0, a0[:, None], np.where(ai == 1, a1[:, None],
                         np.where(big, lerp7, np.where(ai == 6, 0, np.where(ai == 7, 255, lerp5)))))
    out = np.concatenate([px, alpha[..., None]], -1)
    out = out.reshape(h4 // 4, w4 // 4, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(h4, w4, 4)
    return out[:h, :w].astype(np.uint8)


def x0_library(game):
    """({hash: Solid} of X0, {texture hash: (h, w, 4)} of Y0's and X0's packs) for renders with the street life's
    instances drawn (their models are X0's; nothing of it is written anywhere)."""
    from world import bun
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    stream = os.path.join(game, "TRACKS", "STREAML2RA.BUN")
    sols, tex = {}, {}
    for s in bun.sections(l2ra):
        if s.name not in ("X0", "Y0"):
            continue
        for c, p in scenery.with_positions(bun.read_range(stream, s.offset, s.size), 0):
            if c.id == scenery.SOLID_LIST and s.name == "X0":
                for k, kp in scenery.with_positions(c.children, p):
                    if k.id == scenery.SOLID:
                        so = scenery.read_solid(k, kp)
                        sols[so.name_hash] = so
            elif c.id == texpack.PACK:
                for t in texpack.read_pack(c, p).textures:
                    w, h = struct.unpack_from("<hh", t.info, 0x44)
                    try:
                        tex[t.name_hash] = dxt_rgba(t.data, w, h, t.info[0x4A])
                    except ValueError:
                        pass
    return sols, tex


def _clip(cam, uv, near):
    inside = cam[:, 2] > near
    if inside.all():
        return cam, uv
    if not inside.any():
        return None
    out_p, out_uv = [], []
    for i in range(3):
        j = (i + 1) % 3
        a, b = cam[i], cam[j]
        if a[2] > near:
            out_p.append(a)
            out_uv.append(uv[i])
        if (a[2] > near) != (b[2] > near):
            t = (near - a[2]) / (b[2] - a[2])
            out_p.append(a + (b - a) * t)
            out_uv.append(uv[i] + (uv[j] - uv[i]) * t)
    return np.array(out_p), np.array(out_uv)


def _raster(img, zb, xs, ys, sx, sy, z, uv, tex, rgb, W, H):
    x0, x1 = int(max(0, math.floor(sx.min()))), int(min(W - 1, math.ceil(sx.max())))
    y0, y1 = int(max(0, math.floor(sy.min()))), int(min(H - 1, math.ceil(sy.max())))
    if x0 > x1 or y0 > y1:
        return
    px = xs[y0:y1 + 1, x0:x1 + 1] + 0.5
    py = ys[y0:y1 + 1, x0:x1 + 1] + 0.5
    d = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
    if abs(d) < 1e-9:
        return
    l0 = ((sy[1] - sy[2]) * (px - sx[2]) + (sx[2] - sx[1]) * (py - sy[2])) / d
    l1 = ((sy[2] - sy[0]) * (px - sx[2]) + (sx[0] - sx[2]) * (py - sy[2])) / d
    l2 = 1 - l0 - l1
    m = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
    if not m.any():
        return
    iz = l0 / z[0] + l1 / z[1] + l2 / z[2]
    depth = 1.0 / iz
    sub = zb[y0:y1 + 1, x0:x1 + 1]
    m &= depth < sub
    if not m.any():
        return
    if tex is not None:
        u = (l0 * uv[0, 0] / z[0] + l1 * uv[1, 0] / z[1] + l2 * uv[2, 0] / z[2]) * depth
        v = (l0 * uv[0, 1] / z[0] + l1 * uv[1, 1] / z[1] + l2 * uv[2, 1] / z[2]) * depth
        th, tw, ch = tex.shape
        tu = (np.floor((u % 1.0) * tw).astype(np.int64)) % tw
        tv = (np.floor((v % 1.0) * th).astype(np.int64)) % th
        if ch == 4:  # an alpha-tested texture (X0's leaves, for the street life's renders)
            m &= tex[tv, tu, 3] >= 128
            if not m.any():
                return
        col = tex[tv[m], tu[m], :3].astype(float) * rgb
    else:
        col = np.full((int(m.sum()), 3), 128.0) * rgb
    blk = img[y0:y1 + 1, x0:x1 + 1]
    blk[m] = col
    sub[m] = depth[m]


def main(argv):
    cull = "--cull" in argv
    argv = [a for a in argv if a != "--cull"]
    slot = 0
    if "--slot" in argv:
        i = argv.index("--slot")
        slot = argv[i + 1] if argv[i + 1] == "lod" else int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 7:
        print(__doc__)
        return 1
    sc = Scene(argv[0], slot)
    x, y, z, hd, pt = map(float, argv[2:7])
    fov = float(argv[7]) if len(argv) > 7 else 70.0
    sc.view((x, y, z), hd, pt, fov=fov, cull=cull).save(argv[1])
    print(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
