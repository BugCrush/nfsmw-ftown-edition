"""Task 3's pictures: each raised chain unrolled along its length (side view), and the flyovers from above.

    .tools/cityenv/Scripts/python tools/citymap/render_levels.py <area dir>

<area dir>/levels-side.png: one strip per raised chain, s (metres from foot A) to the right, height up (exaggerated
x5): the road profile (black), the ground (brown), the roads crossing under it (red ticks with their clearance), the
bridge ways (blue band) and the pillars (grey). <area dir>/levels-top-<name>.png: the elevated surface over the
ground roads with walls (parapets blue, embankments brown) and pillars.
"""
import json
import os
import sys

from PIL import Image, ImageDraw

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.citymap import levels, render, roadmodel  # noqa: E402


def side(L, out_png):
    chains = L.raised_chains
    W, ROW, EX, PPM = 1500, 120, 5.0, 1500 / max(c.length for c in chains)
    img = Image.new("RGB", (W + 40, ROW * len(chains) + 30), (255, 255, 255))
    d = ImageDraw.Draw(img)
    pil = L.pillars()
    from shapely.geometry import Point
    for k, c in enumerate(chains):
        y0 = ROW * (k + 1)

        def px(s, z):
            return (20 + s * PPM, y0 - 20 - z * EX)

        d.line([px(0, 0), px(c.length, 0)], fill=(150, 110, 60), width=2)
        for (a, b), br in zip(c.part_s, c.bridge):
            if br:
                d.rectangle([px(a, 0)[0], y0 - 14, px(b, 0)[0], y0 - 10], fill=(70, 90, 220))
        pts = [px(s, c.z(s)) for s in [i * c.length / 600 for i in range(601)]]
        d.line(pts, fill=(0, 0, 0), width=2)
        for fp, top in pil:
            s = c.line.project(fp.centroid)
            if c.line.distance(fp.centroid) < 0.5:
                d.line([px(s, 0), px(s, top)], fill=(140, 140, 140), width=1)
        for s, rid in c.crossings:
            d.line([px(s, 0), px(s, c.z(s))], fill=(220, 30, 30), width=2)
            d.text((px(s, 0)[0] - 10, y0 - 12), "%.1f" % c.z(s), fill=(220, 30, 30))
        d.text((20, y0 - ROW + 8), "%s, %.0f m: %s" % (c.name, c.length, "; ".join(c.foot_notes)), fill=(0, 0, 0))
    d.text((20, ROW * len(chains) + 8), "Side views (height x%.0f): road (black), ground (brown), bridge ways (blue), "
           "crossing roads with the deck's height over them (red), pillars (grey)." % EX, fill=(0, 0, 0))
    img.save(out_png)
    return out_png


def tops(L, area):
    out = []
    from shapely.geometry import LineString
    import shapely
    walls = L.walls()
    par = shapely.union_all([LineString([w.a, w.b]).buffer(0.4) for w in walls if w.kind == "parapet"])
    emb = shapely.union_all([LineString([w.a, w.b]).buffer(0.4) for w in walls if w.kind == "embankment"])
    pil = shapely.union_all([fp for fp, _t in L.pillars()])
    seen = set()
    for c in L.raised_chains:
        if c.name in seen:
            continue
        seen.add(c.name)
        for tag, s in (("a", 0.0), ("mid", c.length / 2), ("b", c.length)):
            x, y = c.line.interpolate(s).coords[0]
            name = "%s-%s" % (c.name.lower().replace(" ", "-"), tag)
            out.append(render.closeup(os.path.join(area, "levels-top-%s.png" % name), (x, y), 100.0,
                                      [(L.ground_polygon, (90, 90, 96, 200)), (L.elevated, (60, 60, 200, 150)),
                                       (par, (20, 40, 230, 255)), (emb, (150, 100, 40, 255)), (pil, (0, 0, 0, 255))],
                                      [(r.points, (220, 30, 30), 1) for r in L.model.roads], ppm=3.0,
                                      title="%s: ground roads grey, elevated blue, parapets dark blue, embankment walls "
                                            "brown, pillars black; 200 m across" % name))
    return out


def main(argv):
    area = argv[0]
    with open(os.path.join(area, "osm.json"), encoding="utf-8") as f:
        m = roadmodel.build(json.load(f))
    L = levels.build(m)
    print(side(L, os.path.join(area, "levels-side.png")))
    print("\n".join(tops(L, area)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
