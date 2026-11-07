"""Pictures of the built city for checking by eye (Pillow only).

- top(...): polygons drawn top-down over the OSM drawing map.png (tools/citymap/draw.py: 0.35 px per metre, north up),
  in map.png's own pixel frame, so the built roads can be compared with OSM's lines.
- closeup(...): the same polygons at a chosen centre and scale (px per metre), with the OSM centre lines on top.
"""
import math

from PIL import Image, ImageDraw

from tools.citymap import geo

S, W, N, E = 28.385, 77.305, 28.420, 77.332
MAP_SCALE = 0.35
MAP_LAT0 = (S + N) / 2


def map_px(proj, x, y):
    """Render metres -> map.png pixel (draw.py's frame: 111,320 m per degree, cos of the box's middle latitude)."""
    lat, lon = proj.to_latlon(x, y)
    return ((lon - W) * 111320 * math.cos(math.radians(MAP_LAT0)) * MAP_SCALE, (N - lat) * 111320 * MAP_SCALE)


def _rings(geom):
    polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    for p in polys:
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        yield list(p.exterior.coords), [list(i.coords) for i in p.interiors]


def top(map_png, out_png, layers, lines=(), scale_up=2):
    """layers: [(geometry, (r, g, b, a))] drawn in order over map.png (upscaled by `scale_up`); lines: [(points,
    colour, width)] in render metres."""
    proj = geo.Projection()
    base = Image.open(map_png).convert("RGBA")
    base = base.resize((base.width * scale_up, base.height * scale_up))
    for geom, col in layers:
        over = Image.new("RGBA", base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for ext, holes in _rings(geom):
            d.polygon([tuple(c * scale_up for c in map_px(proj, *p)) for p in ext], fill=col)
            for h in holes:
                d.polygon([tuple(c * scale_up for c in map_px(proj, *p)) for p in h], fill=(0, 0, 0, 0))
        base = Image.alpha_composite(base, over)
    d = ImageDraw.Draw(base)
    for pts, col, w in lines:
        d.line([tuple(c * scale_up for c in map_px(proj, *p)) for p in pts], fill=col, width=w)
    base.convert("RGB").save(out_png)
    return out_png


def closeup(out_png, centre, half, layers, lines=(), ppm=4.0, title=""):
    """A square of 2 x half metres round `centre` (render x, y) at `ppm` pixels per metre."""
    n = int(2 * half * ppm)
    img = Image.new("RGBA", (n, n + 24), (245, 243, 238, 255))

    def px(p):
        return ((p[0] - centre[0] + half) * ppm, (centre[1] + half - p[1]) * ppm)

    for geom, col in layers:
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for ext, holes in _rings(geom):
            d.polygon([px(p) for p in ext], fill=col)
            for h in holes:
                d.polygon([px(p) for p in h], fill=(0, 0, 0, 0))
        img = Image.alpha_composite(img, over)
    d = ImageDraw.Draw(img)
    for pts, col, w in lines:
        d.line([px(p) for p in pts], fill=col, width=w)
    d.rectangle([0, n, n, n + 24], fill=(255, 255, 255, 255))
    d.text((6, n + 6), title, fill=(0, 0, 0, 255))
    img.convert("RGB").save(out_png)
    return out_png
