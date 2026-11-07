"""X0's catalogue for F-Town's street life (docs/ftown-notes.md "Street life (2026-11-04)").

    .tools/cityenv/Scripts/python tools/citymap/x0props.py ["<game dir>"]     (rewrites x0props.json)

Rockport's library section **X0** (in TRACKS\\STREAML2RA.BUN) holds 2,331 solids: trees and bushes (XT_), street
objects (XO_), walls, signs, buildings, and many breakable props' pieces. The streamer keeps X0 loaded at zone 0, so
on F-Town too (notes Q3), and a scenery instance names its model by the solid's name hash, found in whatever pack is
loaded (`new eModel(hash)`, Scenery.cpp:404; notes Task 3). F-Town's instances therefore reference X0's trees and
objects **by hash only**: nothing of X0 is copied into our file. If X0 were not loaded, the model has no solid: the game
still takes a draw record for the instance but `eView::Render` (0x6DA9B0: `mov esi, [ecx+0xC]; test esi, esi; je`)
draws nothing, and DrawAScenery's density test skips a null solid (no crash in either).

This module lists X0's **whole models** (names of a detail set, `X?_<name>_<n><level>_...`: A/B the near model, C a
cheaper one, Z the lowest; breakable props' fragments and damaged states left out), their kind, mesh and triangle
counts, the solid's Density (+0x9C) and box, how Rockport's own scenery uses each (instances per detail slot, the most
common exclude flags at slot 0), and the **picks** for a north-Indian street.

**How a pick is drawn** (DrawAScenery 0x729120): our infos name the pick in slot 0 only (slots 1-3 empty), so the main
view draws it close up and nothing far away (an empty slot returns before a draw record is taken), and the shadow and
reflection views (slot 3 or 2) never draw it. The distance where it stops is set by the info's Radius, read only by
the pixel-size test (Scenery.cpp:711): a model of 40 triangles or more switches to slot 2 when (radius + 6) H /
(d - radius - 6) / max(Density, 6) < 8.7; one of 39 or fewer never switches and is drawn until that pixel size is 17.
"""
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools")
for p in (REPO, TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from world import bun, scenery  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
CATALOGUE = os.path.join(HERE, "x0props.json")
VIEW_H = 1000.0  # build_city.VIEW_H (the main view's H, assumed); kept here so the catalogue needs no city

WHOLE = re.compile(r"^X[TO]_[A-Z0-9_.]+?_\d([ABCZ])_")
NOT_WHOLE = re.compile(r"FRAG|DMG|_PART|PAPER|SMACK")

# role -> (X0 model, scale range, draw distance in m at VIEW_H, solid). Chosen from the catalogue for a north-Indian
# street: Rockport's broad-leaved trees are autumn-coloured (red, orange, brown leaves, in the game's own textures and
# in the Xbox 360 pack's replacements alike: measured from the decoded textures, opaque texels); its green trees are the
# conifers. The juniper, a dark-green column, stands for the Ashoka trees that line Indian roads (Polyalthia
# longifolia), alone or as Rockport's row of junipers (one instance, one mesh for a row of five); the broad autumn tree
# for a flowering gulmohar (red crowns, the fewer); a small shrub for the planted medians; a plain bench, the plain bus
# shelter (a roof on walls, no glass or banners), a green bin. A model of 39 triangles or fewer has no draw distance of
# its own (None): it is drawn until its pixel size is 17 (module doc).
#
# Run I fixes, item 4 (docs/ftown-notes.md "Run I fixes: the city side"): the user found the broad fall tree (screenshot
# 119) "very good" and the junipers "very weird", and asked for "more real looking different trees, but of the same
# species". The junipers are gone; the street trees are X0's three whole fall trees of one family (the same leaf
# material `treeleaves`, CollegeTrees trunks): FALLTREE2D (the good one), FALLTREED and FALLTREES, each scaled to a
# 13.5 m tree (box tops 30.1, 25.4, 29.9 m) times 0.80-1.25 per instance (TREE_SCALE), turned and leaning a little
# (streetlife). The speed camera (item 8): Rockport's photo radar, placed by tools/citymap/race_barriers.py.
TREE_H = 13.5
TREE_SCALE = (0.80, 1.25)


def _tree(top):
    return tuple(round(TREE_H / top * f, 3) for f in TREE_SCALE)


PICKS = {
    "tree_broad": ("XT_CT_FALLTREE2D_1B_JG_00", _tree(30.092), 450.0, True),
    "tree_fall_d": ("XT_CT_FALLTREED_1B_JG_00", _tree(25.416), 450.0, True),
    "tree_fall_s": ("XT_CT_FALLTREES_1B_JG_00", _tree(29.91), 450.0, True),
    "speedcam": ("XO_PHOTORADAR_1B_MD_00", (1.0, 1.0), 300.0, False),
    "bush": ("XT_CT_BUSH_1B_JG_00", (0.11, 0.15), None, False),
    "bench": ("XO_PARKBENCHA_1B_00", (1.0, 1.0), 150.0, False),
    "shelter": ("XO_BUSSHELTERD_1B_00", (1.0, 1.0), 300.0, True),
    "bin": ("XO_GARBAGEBINGREEN_1B_MK_00", (1.0, 1.0), 120.0, False),
}
MASK_FLAGS = 0x2000280  # never: 0x80 terrain, 0x200 no matrix, 0x2000000 (+10 pixels: drawn farther)
# the low byte as the tiles' 0x8060 (DrawAScenery: (bits ^ 0x60) & the view's flags, Scenery.cpp:695): drawn in every
# view the tiles are (Rockport's small objects have 0x00 or 0x01 there: left out of some views, which not known)
DRAWN_EVERYWHERE = 0x60


def whole(name):
    m = WHOLE.match(name)
    return bool(m) and not NOT_WHOLE.search(name)


def level(name):
    return WHOLE.match(name).group(1)


def kind(name):
    n = name.upper()
    if n.startswith("XT_"):
        if "TREELINE" in n:
            return "treeline"
        if re.search(r"TREE|POPLAR|CEDAR|MAPLE|REDWOOD|SPRUCE|JUNIPER|CANOPY|PALM", n):
            return "tree"
        if re.search(r"BUSH|HEDGE|FERN", n):
            return "bush"
        if "GRASS" in n:
            return "grass"
        return "plant"
    for key, k in (("BENCH", "bench"), ("SHELTER", "shelter"), ("BIN", "bin"), ("TRASH", "bin"),
                   ("DUMPSTER", "bin"), ("BOLLARD", "bollard"), ("BIKE", "bike"), ("BARREL", "barrel"),
                   ("BOX", "box"), ("PLANTER", "planter"), ("CHAIR", "chair"), ("TABLE", "table")):
        if key in n:
            return k
    return "object"


def num_polys(so):
    return struct.unpack_from("<h", so.header, 0x14)[0]


def density(so):
    return struct.unpack_from("<f", so.header, 0x9C)[0]


def _x0_section(game):
    l2ra = os.path.join(game, "TRACKS", "L2RA.BUN")
    stream = os.path.join(game, "TRACKS", "STREAML2RA.BUN")
    secs = bun.sections(l2ra)
    return stream, secs, [s for s in secs if s.name == "X0"][0]


def read_x0(game=GAME):
    """{name hash: scenery.Solid} of X0 (read only)."""
    stream, _secs, s = _x0_section(game)
    return scenery.read_section(bun.read_range(stream, s.offset, s.size)).solids


def usage(game, hashes):
    """{hash: (Counter of slots, Counter of slot-0 exclude flags)} over Rockport's scenery sections."""
    stream, secs, _x = _x0_section(game)
    slots = collections.defaultdict(collections.Counter)
    flags = collections.defaultdict(collections.Counter)
    for s in secs:
        if s.name == "X0":
            continue
        for c, pos in scenery.with_positions(bun.read_range(stream, s.offset, s.size), 0):
            if c.id != scenery.SCENERY_SECTION:
                continue
            sc = scenery.read_scenery(c, pos)
            for inst in sc.instances:
                hs = sc.infos[inst.info_index].solid_hashes
                for k, h in enumerate(hs):
                    if h in hashes:
                        slots[h][k] += 1
                if hs[0] in hashes:
                    flags[hs[0]][inst.exclude_flags] += 1
    return slots, flags


def _r(v, n=3):
    return round(float(v), n)


def catalogue(game=GAME):
    solids = read_x0(game)
    keep = {h: so for h, so in solids.items() if whole(so.name)}
    slots, flags = usage(game, set(keep))
    models = []
    for h, so in sorted(keep.items(), key=lambda kv: kv[1].name):
        fl = flags.get(h)
        top = sorted(fl.items(), key=lambda kv: (-kv[1], kv[0]))[0] if fl else None
        models.append({"name": so.name, "hash": "%08X" % h, "kind": kind(so.name), "level": level(so.name),
                       "meshes": len(so.meshes), "tris": num_polys(so), "density": _r(density(so), 4),
                       "box": [_r(v) for v in so.bbox], "materials": list(so.mesh_names),
                       "use": {str(k): v for k, v in sorted(slots.get(h, {}).items())},
                       "flags": "%X" % top[0] if top else None})
    by_name = {m["name"]: m for m in models}
    picks = {}
    for role, (name, scale, draw, solid) in sorted(PICKS.items()):
        m = by_name[name]
        if draw is None:  # 39 triangles or fewer: never switches; drawn until 17 pixels with radius 0
            draw = _r(6.0 + 6.0 * VIEW_H / 17.0, 1)
        picks[role] = {"name": name, "hash": m["hash"], "scale": list(scale), "draw": draw, "solid": solid,
                       "flags": "%X" % ((int(m["flags"], 16) & ~MASK_FLAGS & ~0xFF) | DRAWN_EVERYWHERE)}
    return {"source": "X0 (section 2400) of TRACKS\\STREAML2RA.BUN: names, hashes, counts and boxes only",
            "view_h": VIEW_H, "models": models, "picks": picks}


def load():
    if "_cat" not in _cache:
        with open(CATALOGUE) as f:
            _cache["_cat"] = json.load(f)
    return _cache["_cat"]


_cache = {}


def pick(role):
    return load()["picks"][role]


def model(name_or_hash):
    for m in load()["models"]:
        if m["name"] == name_or_hash or m["hash"] == name_or_hash:
            return m
    raise KeyError(name_or_hash)


def info_radius(role):
    """The info Radius that makes the game stop drawing the pick at its draw distance (VIEW_H; module doc)."""
    p = pick(role)
    m = model(p["name"])
    if m["tris"] <= 39:
        return 0.0
    R = p["draw"] / (1.0 + VIEW_H / (8.7 * max(6.0, m["density"])))
    return max(0.0, R - 6.0)


def slots(role):
    """The info's four detail slots: the pick in slot 0 only."""
    return (int(pick(role)["hash"], 16), 0, 0, 0)


def flags(role):
    return int(pick(role)["flags"], 16)


def library():
    """{name hash: {"meshes", "density", "tris", "kinds", "name"}} of every catalogued model, for the per-view proxy
    (tools/citymap/view_proxy.py) of instances whose solid is X0's."""
    return {int(m["hash"], 16): {"meshes": m["meshes"], "density": m["density"], "tris": m["tris"],
                                 "kinds": list(m["materials"]), "name": m["name"]} for m in load()["models"]}


def main(argv):
    game = argv[0] if argv else GAME
    cat = catalogue(game)
    with open(CATALOGUE, "w", newline="\n") as f:
        json.dump(cat, f, indent=1)
        f.write("\n")
    n = collections.Counter(m["kind"] for m in cat["models"])
    print("%d whole models %s; picks %s" % (len(cat["models"]), dict(n.most_common()),
                                            {r: p["name"] for r, p in cat["picks"].items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
