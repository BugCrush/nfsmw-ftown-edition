"""Task 5's pictures: the built city file seen from driver height, drawn from the file itself (its solids placed by
its scenery instances), so what is checked is what the game is handed.

    .tools/cityenv/Scripts/python tools/citymap/render_city.py <city.bun> <area dir> [prefix]

Writes <area dir>/<prefix>route-start.png, ...neelam-chowk.png, ...mathura-flyover.png and ...top.png (prefix "view-";
the high detail models top-down over the whole area). A pinhole camera (70 degrees across), painter's order, each
triangle coloured by its texture's mean colour (decoded from the file's own texture pack) times its vertex colour over
VC_ONE (Rockport's kind-0 ground grey = 1), a little fog; no lighting of our own beyond the baked colours.
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PIL import Image, ImageDraw  # noqa: E402

from chunks import read_chunks  # noqa: E402
from world import scenery, texpack  # noqa: E402

from tools.citymap import textures  # noqa: E402

SKY = (150, 185, 220)
VC_ONE = 72.0  # a vertex colour channel of 72 (Rockport's kind-0 ground grey) leaves the texture's colour as it is


def placed_triangles(path):
    """[(p0, p1, p2 render, (r, g, b))] of every instance's slot-0 model."""
    with open(path, "rb") as f:
        data = f.read()
    top = list(scenery.with_positions(read_chunks(data), 0))
    sols, scs = {}, []
    for c, p in top:
        if c.id == scenery.SOLID_LIST:
            for k, kp in scenery.with_positions(c.children, p):
                if k.id == scenery.SOLID:
                    so = scenery.read_solid(k, kp)
                    sols[so.name_hash] = so
        elif c.id == scenery.SCENERY_SECTION:
            scs.append(scenery.read_scenery(c, p))
    means = {}
    for c, p in top:
        if c.id == texpack.PACK:
            for t in texpack.read_pack(c, p).textures:
                w, h = struct.unpack_from("<hh", t.info, 0x44)
                means[t.name_hash] = textures.mean(texpack.dxt1_decode(t.data, w, h))
    out = []
    for sc in scs:
        for inst in sc.instances:
            so = sols.get(sc.infos[inst.info_index].solid_hashes[0])
            if so is None:
                continue
            m = inst.matrix
            for k, mesh in enumerate(so.meshes):
                base = means.get(so.textures[mesh.texture_slots[0]], (128, 128, 128))
                ps = so.positions(k)
                st = so.stride(mesh.buffer)
                buf = so.vertex_buffers[mesh.buffer]
                cols = [struct.unpack_from("<I", buf, (mesh.vertex_offset + i) * st + 24)[0]
                        for i in range(mesh.vertex_count)]
                for i, j, l in so.triangles(k):
                    tri = tuple(scenery.transform(m, ps[v]) for v in (i, j, l))
                    cv = cols[i]
                    f = tuple(((cv >> sh) & 255) / VC_ONE for sh in (16, 8, 0))
                    out.append((tri, tuple(min(255, int(b * x)) for b, x in zip(base, f))))
    return out


def view(tris, eye, heading, pitch, out_png, title, W=1280, H=720, far=700.0):
    img = Image.new("RGB", (W, H), SKY)
    d = ImageDraw.Draw(img)
    h, pt = math.radians(heading), math.radians(pitch)
    fwd = (math.cos(h) * math.cos(pt), math.sin(h) * math.cos(pt), math.sin(pt))
    right = (math.sin(h), -math.cos(h), 0.0)
    up = (right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
          right[0] * fwd[1] - right[1] * fwd[0])
    f = W / 2 / math.tan(math.radians(35))

    def cam(p):
        v = (p[0] - eye[0], p[1] - eye[1], p[2] - eye[2])
        return (sum(v[i] * right[i] for i in range(3)), sum(v[i] * up[i] for i in range(3)),
                sum(v[i] * fwd[i] for i in range(3)))

    faces = []
    for tri, col in tris:
        c = [cam(p) for p in tri]
        if all(q[2] < 0.3 for q in c):
            continue
        dist = sum(math.dist(p, eye) for p in tri) / 3
        if dist > far:
            continue
        poly = []
        for k in range(3):
            a, b = c[k], c[(k + 1) % 3]
            if a[2] >= 0.3:
                poly.append(a)
            if (a[2] >= 0.3) != (b[2] >= 0.3):
                s = (0.3 - a[2]) / (b[2] - a[2])
                poly.append(tuple(a[i] + (b[i] - a[i]) * s for i in range(3)))
        if len(poly) < 3:
            continue
        pts = [(W / 2 + f * q[0] / q[2], H / 2 - f * q[1] / q[2]) for q in poly]
        faces.append((dist, pts, col))
    for dist, pts, col in sorted(faces, key=lambda e: -e[0]):
        fog = min(1.0, dist / 900.0)
        d.polygon(pts, fill=tuple(int(c * (1 - fog) + s * fog) for c, s in zip(col, SKY)))
    d.rectangle([0, H - 22, W, H], fill=(255, 255, 255))
    d.text((8, H - 18), title, fill=(0, 0, 0))
    img.save(out_png)
    return out_png


def top(tris, box, out_png, ppm=0.6):
    x0, y0, x1, y1 = box
    W, H = int((x1 - x0) * ppm), int((y1 - y0) * ppm)
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for tri, col in sorted(tris, key=lambda e: max(p[2] for p in e[0])):
        d.polygon([((p[0] - x0) * ppm, (y1 - p[1]) * ppm) for p in tri], fill=col)
    img.save(out_png)
    return out_png


def main(argv):
    city, area = argv[0], argv[1]
    prefix = argv[2] if len(argv) > 2 else "view-"
    sys.path.insert(0, REPO)
    from tools.citymap import levels, roadmodel
    with open(os.path.join(os.path.dirname(os.path.abspath(city)), "ftown-city.json")) as f:
        info = json.load(f)
    tris = placed_triangles(city)
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        m = roadmodel.build(json.load(f))
    L = levels.build(m)
    out = []
    s0 = info["spawns"][0]
    out.append(view(tris, (s0["x"], s0["y"], s0["z"] + 0.5), s0["heading"], -4.0,
                    os.path.join(area, prefix + "route-start.png"),
                    "F-Town from the route start (DND-KMP exit), 1.5 m up, heading %.0f deg" % s0["heading"]))
    chowk = next(r for r in m.roads if r.name == "Neelam Chowk")
    neelam = next(c for c in L.raised_chains if c.name == "Neelam Flyover")
    cx = sum(p[0] for p in chowk.points) / len(chowk.points)
    cy = sum(p[1] for p in chowk.points) / len(chowk.points)
    mid = neelam.line.interpolate(neelam.length / 2)
    hd = math.degrees(math.atan2(mid.y - cy, mid.x - cx))
    r = max(math.dist((cx, cy), p) for p in chowk.points)
    eye = (cx - math.cos(math.radians(hd)) * (r + 20), cy - math.sin(math.radians(hd)) * (r + 20), 101.5)
    out.append(view(tris, eye, hd, -2.0, os.path.join(area, prefix + "neelam-chowk.png"),
                    "Neelam Chowk, 1.5 m up, looking at the Neelam Flyover"))
    mat = max((c for c in L.raised_chains if c.name == "Mathura Road Flyover"), key=lambda c: c.length)
    s = mat.length * 0.35
    p, q = mat.line.interpolate(s), mat.line.interpolate(s + 5.0)
    out.append(view(tris, (p.x, p.y, 100.0 + mat.z(s) + 1.5), math.degrees(math.atan2(q.y - p.y, q.x - p.x)), -3.0,
                    os.path.join(area, prefix + "mathura-flyover.png"),
                    "On the Mathura Road Flyover, 1.5 m above the deck (%.1f m up), along it" % mat.z(s)))
    out.append(top(tris, info["edge_box"], os.path.join(area, prefix + "top.png")))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
