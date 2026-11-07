"""Pictures of the connection for checking by eye (docs/ftown-connection-research.md "The connection: decisions").

    .tools/cityenv/Scripts/python tools/citymap/render_connector.py <out dir>

- connection-plan.png: Rockport's drivable sections, road network and collision (read from the game, read only), the
  zones the connection swaps and adds, the road, F-Town's box before and after the move;
- view-*.png: a driver's eye along the road (render_city.view): the connector's own triangles, Rockport's drawn
  scenery of the junction zone's visible list (.superpowers/research/connection/north-tris.pkl, coloured by height)
  and, near F-Town, the city's.
The pictures hold the game's geometry: keep them under .superpowers/ (git-ignored).
"""
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (REPO, os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.citymap import connector as cn, render_city  # noqa: E402

TRIS = os.path.join(REPO, ".superpowers", "research", "connection", "north-tris.pkl")


def rockport_tris(visible):
    if not os.path.exists(TRIS):
        return []
    out = []
    for p0, p1, p2, n in pickle.load(open(TRIS, "rb")):
        if n not in visible:
            continue
        z = (p0[2] + p1[2] + p2[2]) / 3
        v = max(0.0, min(1.0, (z - 140.0) / 100.0))
        out.append(((p0, p1, p2), (int(70 + 80 * v), int(110 + 40 * v), int(60 + 30 * v))))
    return out


def plan(p, out_png, info):
    from PIL import Image, ImageDraw
    from world import bun
    bounds = bun.boundaries(cn.L2RA)
    S = 0.25
    X0, Y0, X1, Y1 = -2000.0, -1700.0, 6000.0, 13800.0
    img = Image.new("RGB", (int((X1 - X0) * S), int((Y1 - Y0) * S)), (250, 250, 250))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return ((x - X0) * S, (Y1 - y) * S)

    for n, b in bounds.items():
        if bun.is_drivable(n):
            col = (228, 234, 248)
            if n in (cn.SOURCE_ZONE,) + cn.SUBSTITUTES:
                col = (200, 225, 200)
            d.polygon([P(*q) for q in b.points], fill=col, outline=(180, 190, 220))
    ours = cn.our_zone_points(bounds, info)
    d.polygon([P(*q) for q in ours], fill=(250, 230, 190), outline=(200, 140, 40))
    try:
        from tools.citymap import connection_sites as cs
        net = cs.load_network(cn.GAME)
        nodes = [(n.pos[2], -n.pos[0]) for n in net.nodes]
        for s in net.segments:
            a, b = nodes[s.nodes[0]], nodes[s.nodes[1]]
            d.line([P(*a), P(*b)], fill=(240, 140, 20) if s.road != 149 else (220, 0, 160), width=1)
    except (OSError, ValueError):
        pass
    pts = [p.at(p.length * i / 200.0) for i in range(201)]
    d.line([P(*q) for q in pts], fill=(200, 0, 0), width=5)
    bx = info["edge_box"]
    d.rectangle([P(bx[0], bx[3]), P(bx[2], bx[1])], outline=(0, 140, 70), width=3)
    d.rectangle([P(bx[0], bx[3] + 2432.0), P(bx[2], bx[1] + 2432.0)], outline=(150, 200, 170), width=1)
    d.text((P(bx[0], bx[3])[0] + 6, P(bx[0], bx[3])[1] + 6), "F-Town (moved 2,432 m south; faint: before)",
           fill=(0, 120, 60))
    for name, n in (("G3 703", cn.SOURCE_ZONE), ("G26 726", cn.SUBSTITUTES[0]), ("G23 723", cn.SUBSTITUTES[1])):
        c = bounds[n].centre
        d.text(P(*c), name, fill=(40, 100, 40))
    d.text(P(ours[0][0] + 20, (ours[0][1] + ours[2][1]) / 2), "B26 226 (ours)", fill=(160, 100, 20))
    d.text(P(cn.JUNCTION[0] + 30, cn.JUNCTION[1] - 60), "the T (883, 4548), z 202.7", fill=(200, 0, 0))
    d.text((10, img.size[1] - 40), "The connection: Rockport's drivable sections (blue; green: the zones swapped), our "
           "zone (orange), road network (orange lines; magenta: road 149), the connector (red, %.0f m), F-Town's box "
           "(green). 1 km = 250 px" % p.length, fill=(0, 0, 0))
    img.save(out_png)


def connector_tris():
    return render_city.placed_triangles(cn.OUT_BUN)


def main(out):
    os.makedirs(out, exist_ok=True)
    info = cn.city_info()
    p = cn.path(info)
    plan(p, os.path.join(out, "connection-plan.png"), info)
    from world import bun
    visible = set(bun.drivable_sections(cn.L2RA)[cn.SOURCE_ZONE])
    link = connector_tris()
    rock = rockport_tris(visible)
    wrote = []
    for name, s, back, up in (("junction", 0.0, -60.0, 3.0), ("valley", 400.0, 0.0, 2.0),
                              ("hull", 1150.0, 0.0, 2.0), ("descent", 1900.0, 0.0, 2.0),
                              ("ftown", p.length - 250.0, 0.0, 2.0)):
        c, t = p.at(max(0.0, s)), p.tangent(max(0.0, s))
        eye = (c[0] + t[0] * back, c[1] + t[1] * back, p.z(max(0.0, s)) + up)
        heading = math.degrees(math.atan2(t[1], t[0]))
        tris = link + [r for r in rock if math.dist(r[0][0][:2], eye[:2]) < 900.0]
        if name == "ftown":
            city = render_city.placed_triangles(cn.CITY)
            tris += [q for q in city if math.dist(q[0][0][:2], eye[:2]) < 700.0]
        out_png = os.path.join(out, "view-%s.png" % name)
        render_city.view(tris, eye, heading, -2.0, out_png, "the connector at %.0f m (%s), looking along it" % (s, name),
                         far=900.0)
        wrote.append(out_png)
    print("\n".join([os.path.join(out, "connection-plan.png")] + wrote))


if __name__ == "__main__":
    main(sys.argv[1])
