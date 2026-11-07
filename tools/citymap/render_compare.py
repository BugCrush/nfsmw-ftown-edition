"""Comparison sheets: textured renders of the built city (tools/citymap/render_tex.py) beside the user's photos.

    .tools/cityenv/Scripts/python tools/citymap/render_compare.py <city.bun> <out.png> metro|landmarks

The sheet uses the photos, so it is written under .superpowers/ (git-ignored) only.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from tools.citymap import landmarks, render_tex  # noqa: E402

# (title, photo number, eye (render x, y, z), heading, pitch): eye heights 1.5 m over the ground (100)
METRO = [
    ("Neelam Chowk Ajronda from the south", 35, (1400.0, 10840.0, 101.5), 90.0, 12.0),
    ("Bata Chowk from Mathura Road", 40, (1470.0, 9790.0, 101.5), -80.0, 8.0),
    ("Old Faridabad from the east", 51, (1352.0, 12470.0, 101.5), 190.0, 12.0),
]


def landmark_views(ex, model, min_d=18.0, max_d=60.0):
    """(title, photo, eye, heading, pitch) for every photo face of the building landmarks (from its facing road, or
    18-60 m before it), the mural (15 m off its longest stretch) and the sign (12 m before it, from its traffic)."""
    lines = landmarks.road_lines(model)
    out = []
    seen = set()
    for lm in ex.landmarks:
        if lm.kind in ("hospital", "commercial", "market", "mall"):
            for f in lm.faces:
                if (lm.key, f.edge_index) in seen:
                    continue
                seen.add((lm.key, f.edge_index))
                p, q = landmarks.edges(lm.footprint)[f.edge_index]
                n = landmarks.outward(p, q)
                _ang, dist = landmarks.facing_angle(lm.footprint, f, lines)
                # on the facing road (the review: further out, another building can stand in between)
                d = min(max_d, max(8.0, dist + 1.0))
                mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                eye = (mid[0] + n[0] * d, mid[1] + n[1] * d, 101.5)
                hd = math.degrees(math.atan2(-n[1], -n[0]))
                zt = (f.z[0] + f.z[1]) / 2 if f.z else lm.height_m * 0.5  # aim at the crop's middle
                pt = math.degrees(math.atan2(zt - 1.5, d))
                out.append(("%s (%s)" % (lm.name, f.name), f.photo, eye, hd, pt))
    lb = ex.landmark_result
    if lb.mural_parts:
        best = max((t for p in lb.mural_parts for t in p.tris), key=lambda t: max(v[2] for v in t))
        c = ((best[0][0] + best[1][0] + best[2][0]) / 3, (best[0][1] + best[1][1] + best[2][1]) / 3)
        from tools.citymap import parts as P
        nn = P.normal(best)
        # the mural faces out: its right-hand normal points to the viewer (parts.quad, Run H fixes)
        eye = (c[0] + nn[0] * 16.0, c[1] + nn[1] * 16.0, 101.5)
        out.append(("Neelam Flyover mural", 36, eye, math.degrees(math.atan2(-nn[1], -nn[0])) - 25.0, 6.0))
    if lb.sign_at:
        x, y = lb.sign_at
        out.append(("Sector 16A sign", 32, (x - 10.0, y - 6.0, 101.5), math.degrees(math.atan2(6.0, 10.0)), 6.0))
    return out


def sheet(scene, views, out, W=560, H=350):
    files = landmarks.photo_files()
    rows = []
    for title, photo, eye, hd, pt in views:
        img = scene.view(eye, hd, pt, W, H)
        ph = None
        if photo and files:
            with Image.open(os.path.join(landmarks.PHOTOS, files[photo])) as im:
                ph = im.convert("RGB")
            k = min(W / ph.size[0], H / ph.size[1])
            ph = ph.resize((max(1, int(ph.size[0] * k)), max(1, int(ph.size[1] * k))))
        rows.append((title, photo, img, ph))
    sheet_ = Image.new("RGB", (2 * W + 30, (H + 24) * len(rows) + 6), (30, 30, 30))
    dr = ImageDraw.Draw(sheet_)
    for k, (title, photo, img, ph) in enumerate(rows):
        y = 6 + k * (H + 24)
        dr.text((10, y), "%s (render)   |   photo %s" % (title, photo), fill=(255, 255, 255))
        sheet_.paste(img, (10, y + 16))
        if ph is not None:
            sheet_.paste(ph, (W + 20, y + 16))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sheet_.save(out)
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    scene = render_tex.Scene(argv[0])
    if argv[2] in ("landmarks", "all"):
        from tools.citymap import build_city
        area = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
        _proj, model, _L, _bl, city, _r = build_city.geometry(area)
        views = landmark_views(city.extras, model)
        if argv[2] == "all":
            views = METRO + views
    else:
        views = METRO if argv[2] == "metro" else json.loads(open(argv[2]).read())
    print(sheet(scene, views, argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
