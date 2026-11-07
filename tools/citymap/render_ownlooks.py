"""Before/after renders of the own looks (docs/ftown-notes.md "Own looks and a lived-in city (2026-11-04)"): the same
eyes in two city files, the game's detail levels per instance (render_tex "lod"), back faces culled, X0's trees and
objects drawn from the game's own files (read only: render_tex.x0_library); and the stations' drawn faces from their
roads beside their photos. Everything stays under .superpowers/ (git-ignored: it holds the photos and Rockport's
textures).

    .tools/cityenv/Scripts/python tools/citymap/render_ownlooks.py <before.bun> <after.bun> <out dir>

Writes <out dir>/ownlooks-streets.png (street views, before left, after right) and <out dir>/ownlooks-stations.png
(each station face, render left, photo right).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import build_city, landmarks, render_tex  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")


def street_eyes(city, model):
    """(title, eye, heading, pitch): a market, sector lanes (the longest boundary wall's lane, a lane with poles),
    a view over the roofs from the Neelam Flyover's deck, and two landmark viewpoints."""
    import shapely
    out = [("Sector 16 Market's inner road", (2095.0, 12500.0, 101.5), 45.0, 0.0)]
    ex = city.extras
    if ex.boundary:
        lanes = city.G
        a, b = max(ex.boundary, key=lambda s: math.dist(*s))
        d = ((b[0] - a[0]) / math.dist(a, b), (b[1] - a[1]) / math.dist(a, b))
        n = (-d[1], d[0])
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for sg in (1, -1):  # the lane side: the side whose point 3 m out is on a carriageway
            eye = (mid[0] + n[0] * 3.0 * sg - d[0] * 25, mid[1] + n[1] * 3.0 * sg - d[1] * 25)
            if lanes.contains(shapely.Point(eye)):
                out.append(("a sector lane with boundary walls and gates", (eye[0], eye[1], 101.5),
                            math.degrees(math.atan2(d[1], d[0])) + 8 * sg, 2.0))
                break
    pr = getattr(ex, "poles", None)
    if pr and pr.wire_lines:
        (x0, y0), (x1, y1) = max(pr.wire_lines[len(pr.wire_lines) // 3:len(pr.wire_lines) // 3 + 200],
                                 key=lambda w: math.dist(*w))
        hd = math.degrees(math.atan2(y1 - y0, x1 - x0))
        out.append(("a lane under the wires", (x0 - (x1 - x0) * 0.6, y0 - (y1 - y0) * 0.6 + 0.0, 101.4), hd, 6.0))
    # over Sector 16's roofs from 25 m up (mumties, water tanks, parapets), and from a Mathura Road flyover deck
    out.append(("over Sector 16's roofs, 25 m up", (1950.0, 12250.0, 125.0), 40.0, -14.0))
    for c in city.L.raised_chains:
        if c.name == "Mathura Road Flyover":
            pt = c.line.interpolate(c.line.length * 0.5)
            p2 = c.line.interpolate(c.line.length * 0.5 + 5.0)
            hd = math.degrees(math.atan2(p2.y - pt.y, p2.x - pt.x))
            out.append(("from a Mathura Road Flyover deck", (pt.x, pt.y, 100.0 + 7.0 + 1.5), hd, 0.0))
            break
    for v in build_city.VIEWPOINTS:
        if v["name"] in ("Old Fbd station", "Neelam Chowk"):
            out.append((v["name"], (v["x"], v["y"], 101.5), v["heading"], 0.0))
    return out


def station_eyes(city, model):
    """(title, photo, eye, heading, pitch) for every station face: from 30 m in front, aimed at the face's middle."""
    out = []
    for lm in city.extras.landmarks:
        if lm.kind != "station":
            continue
        seen = set()
        for f in lm.faces:
            if f.edge_index in seen:
                continue
            seen.add(f.edge_index)
            p, q = landmarks.edges(lm.footprint)[f.edge_index]
            n = landmarks.outward(p, q)
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            _ang, dist = landmarks.facing_angle(lm.footprint, f, landmarks.road_lines(model))
            d = min(45.0, max(12.0, dist + 1.0))  # on the facing road (further out, something can stand between)
            zt = (f.z[0] + f.z[1]) / 2 if f.z else 9.0
            out.append(("%s (%s)" % (lm.name, f.name), f.photo, (mid[0] + n[0] * d, mid[1] + n[1] * d, 101.5),
                        math.degrees(math.atan2(-n[1], -n[0])), math.degrees(math.atan2(zt - 1.5, d))))
    return out


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    before, after, out_dir = argv
    os.makedirs(out_dir, exist_ok=True)
    _proj, model, _L, _bl, city, _r = build_city.geometry(AREA)
    lib = render_tex.x0_library(GAME) if os.path.isdir(GAME) else None
    W, H = 560, 350
    scenes = [render_tex.Scene(before, "lod", lib), render_tex.Scene(after, "lod", lib)]
    vs = street_eyes(city, model)
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(vs) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, eye, hd, pt) in enumerate(vs):
        y = 6 + r * (H + 24)
        dr.text((10, y), "%s   |   before (street life) left, own looks right" % title, fill=(255, 255, 255))
        for c, sc in enumerate(scenes):
            sheet.paste(sc.view(eye, hd, pt, W, H, fov=75.0, far=900.0, cull=True), (10 + c * (W + 10), y + 16))
    p1 = os.path.join(out_dir, "ownlooks-streets.png")
    sheet.save(p1)
    files = landmarks.photo_files()
    st = station_eyes(city, model)
    sheet = Image.new("RGB", (2 * W + 30, (H + 24) * len(st) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    for r, (title, photo, eye, hd, pt) in enumerate(st):
        y = 6 + r * (H + 24)
        dr.text((10, y), "%s (render)   |   photo %s" % (title, photo), fill=(255, 255, 255))
        sheet.paste(scenes[1].view(eye, hd, pt, W, H, fov=60.0, far=900.0, cull=True), (10, y + 16))
        if files and photo in files:
            with Image.open(os.path.join(landmarks.PHOTOS, files[photo])) as im:
                ph = im.convert("RGB")
            k = min(W / ph.size[0], H / ph.size[1])
            sheet.paste(ph.resize((max(1, int(ph.size[0] * k)), max(1, int(ph.size[1] * k)))), (W + 20, y + 16))
    p2 = os.path.join(out_dir, "ownlooks-stations.png")
    sheet.save(p2)
    print(p1)
    print(p2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
