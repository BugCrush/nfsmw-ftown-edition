"""Borrowing a game car's interior and driver for a car built without them (the Thar; plan
docs/superpowers/plans/2026-11-02-thar-fixes-ride-height-interior.md, Tasks 2 and 3).

Every game racer has `<CAR>_KIT00_INTERIOR_<A..D>` (dashboard, seats, door cards, headliner; one texture of its own,
`<CAR>_INTERIOR`, at A and B) and `<CAR>_KIT00_DRIVER_<A, C>` (the same 1,168-triangle driver in every car, textured
with the global DRIVER_PLAYER; C a 4-triangle cut-out). The police cars have a driver only, painted on their skin.

Fit (measured, `choose_donor`): the donor's cabin is mapped onto the new car's glasshouse (`glasshouse`: between its
rear window and the bottom of its windscreen, inside its side windows, above its floor panel, below its roof) by
- z: the donor's window sill (lowest point of its front side windows) onto the new car's;
- x: the donor's windscreen base (front window's largest x) onto the new car's;
- y: centred; the donor's steering side is kept (left-hand drive as in the game);
- scale: one for every axis, the largest <= 1 that keeps the cabin inside the side windows, floor, roof and in front of
  the rear window, but not below MIN_SCALE: what then still lies behind the rear window (at most MAX_CLAMP) is pressed
  onto the window's plane (`clamp_x`).
- textures: the game loads a car's own textures by name from a fixed list (<CAR>_SKIN1, _MISC, _INTERIOR,
  _INTERIOR_N, _BADGING, _DRIVER, ...: Unlimiter CarRenderInfo.h GetUsedCarTextureInfo; every game car's pack holds
  only such names), so the donor's own textures become <CAR>_INTERIOR(_N); a donor whose interior or driver uses any
  other texture of its own (the SL500's _MISC would clash with the new car's palette) is passed over.
The donor needing the least change and filling the cabin wins (score: the largest |1 - scale|, plus the clamped depth,
plus the length left empty in front of the rear window: a two-seater ending 0.65 m short of it is no fit).
Every interior's front lies at its windscreen base: none reaches under the hood.
"""
import os
import struct

from chunks import Chunk, bstringhash, read_chunks
from geometry import VERTEX, Solid, finalize, read_geometry, solid_header
from textures import Texture, read_textures

MIN_SCALE = 0.85  # the plan's bound: at most 15% from 1.0 on any axis
MAX_CLAMP = 0.05  # m of cabin pressed onto the rear window's plane at most
PARTS = ("KIT00_INTERIOR", "KIT00_DRIVER")
# the game's racers (as donor.STOCK_RACERS) and the plan's tall-cabin police SUVs
CANDIDATES = ("911TURBO", "997S", "A3", "A4", "BMWM3GTR", "BMWM3GTRE46", "CAMARO", "CARRERAGT", "CAYMANS", "CLIO",
              "CLK500", "COBALTSS", "CORVETTE", "CORVETTEC6R", "CTS", "DB9", "ECLIPSEGT", "ELISE", "FORDGT",
              "GALLARDO", "GTI", "GTO", "IMPREZAWRX", "IS300", "LANCEREVO8", "MONARO", "MURCIELAGO", "MUSTANGGT",
              "PUNTO", "RX7", "RX8", "SL500", "SL65", "SLR", "SUPRA", "TT", "VIPER", "COPSUV", "COPSUVL")
TEX_HASHES = 0x33310002
SOLID_UNDECODED = (0x134017, 0x134018, 0x134019)


def is_interior_part(name, car):
    return any(name.startswith("%s_%s_" % (car, p)) and len(name) == len(car) + len(p) + 3 for p in PARTS)


def _points(solids):
    return [p for s in solids for m in s.meshes() for p in s.positions(m)]


def _box(ps):
    return [min(p[k] for p in ps) for k in range(3)] + [max(p[k] for p in ps) for k in range(3)]


def _solids(pack, car, *parts):
    by = {s.name: s for s in pack.solids}
    return [by[car + "_" + p] for p in parts if car + "_" + p in by]


def anchors(pack, car):
    """(windscreen base x, window sill z) of a car: the front window's largest x, its front side windows' lowest z."""
    fw = _box(_points(_solids(pack, car, "KIT00_FRONT_WINDOW_A")))
    side = _box(_points(_solids(pack, car, "KIT00_FRONT_LEFT_WINDOW_A", "KIT00_FRONT_RIGHT_WINDOW_A")))
    return fw[3], side[2]


def glasshouse(pack, car):
    """The box the borrowed cabin must stay in: x from the rear window (its largest x) to the windscreen base, |y|
    inside the side windows (their smallest |y|), z from the top of the floor panel (BASE_A) to the roof (the body's
    top)."""
    rear = _box(_points(_solids(pack, car, "KIT00_REAR_WINDOW_A")))
    base = _box(_points(_solids(pack, car, "BASE_A")))
    body = _box(_points(_solids(pack, car, "KIT00_BODY_A")))
    inner = min(abs(p[1]) for s in _solids(pack, car, "KIT00_FRONT_LEFT_WINDOW_A", "KIT00_FRONT_RIGHT_WINDOW_A",
                                           "KIT00_REAR_LEFT_WINDOW_A", "KIT00_REAR_RIGHT_WINDOW_A")
                for m in s.meshes() for p in s.positions(m))
    front, _ = anchors(pack, car)
    return [rear[3], -inner, base[5], front, inner, body[5]]


def cabin_box(pack, car):
    """The donor's interior and driver as one box, every detail level (a far level can be wider than A: the
    Gallardo's INTERIOR_D)."""
    return _box(_points(interior_parts(pack, car)))


def interior_parts(pack, car):
    """Every level of the car's interior and driver solids, in the pack's order."""
    return [s for s in pack.solids if is_interior_part(s.name, car)]


def candidates(cars_dir, names):
    """({car: pack} of the cars that have an interior, a driver and the windows to fit them by, {car: reason})."""
    usable, excluded = {}, {}
    for car in names:
        path = os.path.join(cars_dir, car, "GEOMETRY.BIN")
        if not os.path.exists(path):
            excluded[car] = "no GEOMETRY.BIN"
            continue
        with open(path, "rb") as f:
            pack = read_geometry(f.read())
        have = {s.name for s in pack.solids}
        missing = [n for n in ("KIT00_INTERIOR_A", "KIT00_DRIVER_A", "KIT00_FRONT_WINDOW_A",
                               "KIT00_FRONT_LEFT_WINDOW_A", "KIT00_FRONT_RIGHT_WINDOW_A") if car + "_" + n not in have]
        if missing:
            excluded[car] = "no " + ", ".join(missing)
        else:
            usable[car] = pack
    return usable, excluded


def fit(donor_pack, car, gh, target_anchors):
    """The transform mapping a donor's cabin into the glasshouse `gh` (see the module notes)."""
    cab = cabin_box(donor_pack, car)
    dfw, dsill = anchors(donor_pack, car)
    tfw, tsill = target_anchors
    limits = [1.0, gh[4] / max(-cab[1], cab[4]), (gh[5] - tsill) / (cab[5] - dsill), (tsill - gh[2]) / (dsill - cab[2])]
    across = min(limits)
    sx_fit = (tfw - gh[0]) / (dfw - cab[0])
    # one scale on every axis (the plan's preference: seats, wheel and driver keep their proportions); not below
    # MIN_SCALE, where what is left behind the rear window is pressed onto it
    sx = sy = sz = max(MIN_SCALE, min(across, sx_fit))
    offset = (tfw - sx * dfw, 0.0, tsill - sz * dsill)
    rear = sx * cab[0] + offset[0]
    clamp = max(0.0, gh[0] - rear)
    gap = max(0.0, rear - gh[0])  # cabin length left empty in front of the rear window
    if cab[3] > dfw + 1e-6 or across < MIN_SCALE:
        clamp = float("inf")  # past its own windscreen (through the hood), or too wide or tall even at MIN_SCALE
    score = max(abs(1 - s) for s in (sx, sy, sz)) + clamp + gap
    return {"scale": (sx, sy, sz), "offset": offset, "clamp_x": gh[0], "clamp_depth": clamp, "rear_gap": gap,
            "score": score,
            "donor_anchors": (dfw, dsill), "target_anchors": tuple(target_anchors)}


def donor_textures(cars_dir, car):
    with open(os.path.join(cars_dir, car, "TEXTURES.BIN"), "rb") as f:
        return {t.name_hash: t for t in read_textures(f.read()).textures}


def shared_texture_hashes(cars_dir):
    """Name hashes of the shared car pack CARS/TEXTURES.BIN."""
    with open(os.path.join(cars_dir, "TEXTURES.BIN"), "rb") as f:
        return {t.name_hash for t in read_textures(f.read()).textures}


def global_texture_hashes(global_dir):
    """Name hashes of every texture in the game's GLOBAL packs (each pack's 0x33310002 list), files that are not chunk
    files skipped."""
    out = set()

    def walk(cs):
        for c in cs:
            if c.id == TEX_HASHES:
                out.update(struct.unpack_from("<%dI" % (len(c.data) // 4), c.data)[0::2])
            if c.children:
                walk(c.children)
    for n in sorted(os.listdir(global_dir)):
        p = os.path.join(global_dir, n)
        if not os.path.isfile(p) or not n.lower().endswith((".bun", ".lzc", ".bin")):
            continue
        with open(p, "rb") as f:
            data = f.read()
        try:
            walk(read_chunks(data))
        except Exception:
            continue
    return out


def ineligible(cars_dir, car, pack=None, elsewhere=None):
    """Why a car's interior and driver cannot be borrowed (None when they can): an undecodable (HUFF) texture of its
    own, an own texture other than <CAR>_INTERIOR(_N) (the game loads a car's own textures by name), or a texture found
    in none of its pack, the shared car pack and the GLOBAL packs."""
    if pack is None:
        with open(os.path.join(cars_dir, car, "GEOMETRY.BIN"), "rb") as f:
            pack = read_geometry(f.read())
    parts = interior_parts(pack, car)
    if not parts:
        return "no interior or driver parts"
    if elsewhere is None:
        elsewhere = shared_texture_hashes(cars_dir) | global_texture_hashes(os.path.join(os.path.dirname(cars_dir),
                                                                                          "GLOBAL"))
    own = donor_textures(cars_dir, car)
    if any(h in own and own[h].data is None for s in parts for h in s.textures):
        return "HUFF interior or driver texture"
    foreign = sorted({own[h].name for s in parts for h in s.textures
                      if h in own and h not in (bstringhash(car + "_INTERIOR"), bstringhash(car + "_INTERIOR_N"))})
    if foreign:
        return "own textures other than _INTERIOR: " + ", ".join(foreign)
    lost = sorted({h for s in parts for h in s.textures if h not in own and h not in elsewhere})
    if lost:
        return "textures found nowhere: " + ", ".join("0x%08X" % h for h in lost)
    return None


def choose_donor(target_pack, cars_dir, names=CANDIDATES, target="THAR"):
    """{"car", "transform", "others": {car: transform}, "excluded", "substituted"}: the usable donor whose cabin needs
    the least change; donors with an undecodable (HUFF) interior/driver texture of their own, or one found in none of
    the donor's pack, the shared car pack and the GLOBAL packs (the Gallardo's INTERIOR_B names 0xCF523D8A), are
    passed over."""
    usable, excluded = candidates(cars_dir, names)
    elsewhere = shared_texture_hashes(cars_dir) | global_texture_hashes(os.path.join(os.path.dirname(cars_dir),
                                                                                      "GLOBAL"))
    gh = glasshouse(target_pack, target)
    ta = anchors(target_pack, target)
    fits = {}
    for car, pack in sorted(usable.items()):
        reason = ineligible(cars_dir, car, pack, elsewhere)
        if reason:
            excluded[car] = reason
            continue
        fits[car] = fit(pack, car, gh, ta)
    best = min(sorted(fits), key=lambda c: fits[c]["score"])
    return {"car": best, "transform": fits[best], "others": {c: t for c, t in fits.items() if c != best},
            "excluded": excluded, "substituted": [], "glasshouse": gh}


def _apply(t, p, n):
    sx, sy, sz = t["scale"]
    ox, oy, oz = t["offset"]
    q = [sx * p[0] + ox, sy * p[1] + oy, sz * p[2] + oz]
    if q[0] < t["clamp_x"]:
        q[0] = t["clamp_x"]
    m = (n[0] / sx, n[1] / sy, n[2] / sz)  # normals take the inverse scale
    k = (m[0] ** 2 + m[1] ** 2 + m[2] ** 2) ** 0.5 or 1.0
    return q, (m[0] / k, m[1] / k, m[2] / k)


def texture_renames(donor, car):
    """{donor texture hash: (new name, new hash)}: the donor's own interior textures under the new car's names."""
    return {bstringhash(donor + sfx): (car + sfx, bstringhash(car + sfx)) for sfx in ("_INTERIOR", "_INTERIOR_N")}


def renamed_texture(t, name, placement):
    """A copy of a decoded texture under another name (header +0x0C name cut to 23, +0x24 the full name's hash, +0x30
    image placement), stored uncompressed (RAWW) by the writer."""
    if t.data is None:
        raise ValueError("texture 0x%08X is not decoded (HUFF)" % t.name_hash)
    h = bytearray(t.header)
    raw = name.encode("ascii")[:23]
    h[0x0C:0x24] = raw + bytes(24 - len(raw))
    nh = bstringhash(name)
    struct.pack_into("<I", h, 0x24, nh)
    struct.pack_into("<I", h, 0x30, placement)
    return Texture(name=raw.decode("ascii"), name_hash=nh, width=t.width, height=t.height, fmt=t.fmt,
                   mipmaps=t.mipmaps, data=t.data, header=bytes(h), codec="RAWW", size=len(t.data) + len(h))


def transplant(donor_pack, donor, car, t):
    """The donor's interior and driver solids renamed `<car>_...` (hashes recomputed), every vertex moved by the
    transform `t`, boxes refreshed; meshes and shader lists kept, the donor's own interior textures renamed
    (`texture_renames`). The undecoded chunks 0x134017..0x134019 are left out (sized to the donor's geometry; the
    working add-ons have none)."""
    ren = texture_renames(donor, car)
    out = []
    for s in interior_parts(donor_pack, donor):
        name = car + s.name[len(donor):]
        buf = bytearray(s.vertices)
        for k, v in enumerate(VERTEX.iter_unpack(s.vertices)):
            q, n = _apply(t, v[0:3], v[3:6])
            VERTEX.pack_into(buf, k * VERTEX.size, *q, *n, *v[6:])
        h = bstringhash(name)
        new = Solid(name=name, name_hash=h, header=solid_header(s.header, name, h, (0,) * 6),
                    textures=[ren[x][1] if x in ren else x for x in s.textures], shaders=list(s.shaders),
                    mesh_header=s.mesh_header,
                    mesh_entries=list(s.mesh_entries), vertices=bytes(buf), indices=s.indices,
                    other=[Chunk(c.id, c.data) for c in s.other if c.id not in SOLID_UNDECODED],
                    mesh_names=list(s.mesh_names))
        new.mesh_entries = _mesh_boxes(new)
        finalize(new)
        out.append(new)
    return out


def _mesh_boxes(s):
    """Mesh entries with their boxes (+0x00, vertex extents + 0.01 m) recomputed for the moved vertices."""
    out = []
    for m, raw in zip(s.meshes(), s.mesh_entries):
        ps = s.positions(m)
        lo = [min(p[k] for p in ps) - 0.01 for k in range(3)]
        hi = [max(p[k] for p in ps) + 0.01 for k in range(3)]
        r = bytearray(raw)
        struct.pack_into("<6f", r, 0, *(lo + hi))
        out.append(bytes(r))
    return out
