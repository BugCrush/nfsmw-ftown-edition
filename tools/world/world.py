"""World research command line (read-only on the game).

    python tools/world/world.py sections <game dir>             one line per streaming section
    python tools/world/world.py extent <game dir>               Rockport's extent from the section boundaries
    python tools/world/world.py map <game dir> <out.png> [x y]  boundaries top-down (optionally a marked point)
    python tools/world/world.py render <game dir> <section> <out.png>   a section's drawn geometry, top-down
    python tools/world/world.py render-collision <game dir> <section> <out.png>   the same with its collision

Coordinates are the world's as stored in the files: x and y horizontal, the convention of the boundaries
(bVector2 = the x, y of the game's z-up world; see docs/ftown-notes.md). Output images belong under .superpowers/world/
(git-ignored: they are drawn from the game's data).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from world import bun  # noqa: E402


def paths(game):
    return os.path.join(game, "TRACKS", "L2RA.BUN"), os.path.join(game, "TRACKS", "STREAML2RA.BUN")


def extent(bounds, drivable_only=False):
    pts = [p for n, b in bounds.items() if not drivable_only or bun.is_drivable(n) for p in b.points]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def cmd_sections(game):
    l2ra, _ = paths(game)
    bounds = bun.boundaries(l2ra)
    for s in sorted(bun.sections(l2ra), key=lambda s: s.offset):
        has = [n for n in bounds if bun.combined_number(n, {s.number}) == s.number]
        print("%-4s %5d  offset 0x%08X  size %9d  centre (%9.1f, %9.1f) r %7.1f  boundary %s" %
              (s.name, s.number, s.offset, s.size, s.centre[0], s.centre[1], s.radius,
               ",".join(bun.section_name(n) for n in has) or "-"))


def cmd_extent(game):
    l2ra, _ = paths(game)
    bounds = bun.boundaries(l2ra)
    for label, only in (("all boundaries", False), ("drivable sections", True)):
        x0, x1, y0, y1 = extent(bounds, only)
        print("%-18s x %9.1f .. %9.1f (%6.0f m)   y %9.1f .. %9.1f (%6.0f m)" % (label, x0, x1, x1 - x0, y0, y1,
                                                                                 y1 - y0))


def draw_map(game, out, mark=None, size=2000):
    from PIL import Image, ImageDraw
    l2ra, _ = paths(game)
    bounds = bun.boundaries(l2ra)
    x0, x1, y0, y1 = extent(bounds)
    if mark:
        x0, x1 = min(x0, mark[0] - 500), max(x1, mark[0] + 500)
        y0, y1 = min(y0, mark[1] - 500), max(y1, mark[1] + 500)
    pad = 300
    x0 -= pad
    y0 -= pad
    x1 += pad
    y1 += pad
    scale = size / max(x1 - x0, y1 - y0)
    w, h = int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1
    img = Image.new("RGB", (w, h + 60), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def px(p):  # x to the right, y up
        return (p[0] - x0) * scale, (y1 - p[1]) * scale

    # 1 km grid
    import math
    for gx in range(int(math.floor(x0 / 1000)), int(math.ceil(x1 / 1000)) + 1):
        d.line([px((gx * 1000, y0)), px((gx * 1000, y1))], fill=(230, 230, 230))
        d.text(px((gx * 1000 + 20, y0 + 40)), "x=%d" % (gx * 1000), fill=(150, 150, 150))
    for gy in range(int(math.floor(y0 / 1000)), int(math.ceil(y1 / 1000)) + 1):
        d.line([px((x0, gy * 1000)), px((x1, gy * 1000))], fill=(230, 230, 230))
        d.text(px((x0 + 20, gy * 1000 + 40)), "y=%d" % (gy * 1000), fill=(150, 150, 150))
    for n, b in sorted(bounds.items(), key=lambda kv: bun.is_drivable(kv[0])):
        drivable = bun.is_drivable(n)
        colour = (30, 90, 200) if drivable else (200, 140, 40)
        pts = [px(p) for p in b.points]
        d.polygon(pts, outline=colour, fill=(220, 232, 250) if drivable else None)
        if drivable:
            d.text(px(b.centre), bun.section_name(n), fill=(0, 0, 0))
    if mark:
        cx, cy = px(mark)
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(220, 0, 0), width=3)
        d.text((cx + 10, cy - 6), "candidate (%.0f, %.0f)" % mark, fill=(220, 0, 0))
    d.text((10, h + 8), "Rockport section boundaries (L2RA.BUN 0x34152), top-down: +x right, +y up (the file's x, y). "
           "Blue = drivable sections (name), orange = scenery-only/panorama. Grid 1 km.", fill=(0, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    return x0, x1, y0, y1


def library_solids(game):
    """{hash: Solid} of the library sections (letters X and V), where most instances' solids live."""
    from world import scenery
    l2ra, stream = paths(game)
    lib = {}
    for s in bun.sections(l2ra):
        if s.letter in "XV":
            lib.update(scenery.read_section(bun.read_range(stream, s.offset, s.size)).solids)
    return lib


def section_triangles(game, name, drivable_only=True):
    from world import scenery
    l2ra, stream = paths(game)
    s = {x.name: x for x in bun.sections(l2ra)}[name]
    data = scenery.read_section(bun.read_range(stream, s.offset, s.size))
    return scenery.placed_triangles(data, library_solids(game), drivable_only), data


def render_section(game, name, out):
    from world import scenery
    tris, data = section_triangles(game, name)
    numbers = ", ".join(bun.section_name(sc.number) for sc in data.sceneries)
    return scenery.render_top(tris, out, title="Section %s (scenery %s; LOD scenery left out), %d triangles" %
                              (name, numbers, len(tris)))


def render_collision(game, name, out):
    """The section's drawn geometry with its collision triangles (blue outlines) and barriers (red) on top."""
    from PIL import Image, ImageDraw
    from world import collision, scenery
    tris, data = section_triangles(game, name)
    x0, x1, y0, y1, scale = scenery.render_top(tris, out, title="Section %s with collision" % name)
    img = Image.open(out)
    d = ImageDraw.Draw(img)
    l2ra, stream = paths(game)
    s = {x.name: x for x in bun.sections(l2ra)}[name]
    packs = collision.packs_in(bun.read_range(stream, s.offset, s.size))

    def px(p):
        r = collision.to_render(p)
        return (r[0] - x0) * scale, (y1 - r[1]) * scale

    nt = nb = 0
    for p in packs:
        for a, b, c, _, _ in collision.triangles(p):
            d.polygon([px(a), px(b), px(c)], outline=(40, 110, 230))
            nt += 1
        for a, b, _, _, _ in collision.barriers(p):
            d.line([px(a), px(b)], fill=(230, 30, 30), width=3)
            nb += 1
    h = img.size[1]
    d.rectangle([0, h - 20, img.size[0], h], fill=(255, 255, 255))
    d.text((8, h - 16), "Blue outlines: %d collision triangles; red: %d barriers (packs %s)" %
           (nt, nb, ", ".join(bun.section_name(p.section) for p in packs)), fill=(0, 0, 0))
    img.save(out)
    return nt, nb


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "sections":
        cmd_sections(argv[1])
    elif argv[0] == "extent":
        cmd_extent(argv[1])
    elif argv[0] == "render":
        render_section(argv[1], argv[2], argv[3])
        print("wrote", argv[3])
    elif argv[0] == "render-collision":
        print("collision triangles %d, barriers %d" % render_collision(argv[1], argv[2], argv[3]))
        print("wrote", argv[3])
    elif argv[0] == "map":
        mark = (float(argv[3]), float(argv[4])) if len(argv) >= 5 else None
        draw_map(argv[1], argv[2], mark)
        print("wrote", argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
