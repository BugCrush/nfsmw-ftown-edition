"""F-Town's breakable poles (docs/ftown-notes.md "Breakable poles (2026-11-05)"; plan
docs/superpowers/plans/2026-11-05-ftown-breakable-poles.md). The user (screenshots 126, 127): "they should be breakable
like the poles in rockport"; the choice "Mix".

- **Which pole is which** (`classify`): the medians' lamps of a pair of main carriageways (motorway, trunk, primary,
  secondary, tertiary; links with their road) are Rockport's own street lights from X0, by hash: Mathura Road's railing
  medians XO_StreetLightCb (10.7 m, a 6.5 m arm), the planted ones XO_StreetLightC (8.7 m, a 3.1 m arm), the arms
  alternating over the two carriageways; the sector roads' lamps stay ours (the triangular lantern, photo 01) and break
  in one piece; every traffic signal is X0's mast, XO_TrafficLightB (a 3.5 m arm) or XO_TrafficLightA (7.0 m) by a road
  10 m wide or more, its arm over the road. The electricity poles (tools/citymap/poles.py) stay solid: Rockport has no
  breakable electricity pole and their wires would hang in the air.
- **Each pole its own scenery instance** with no barrier (a car meets the game's trigger, not a wall): X0's model in
  slot 0 alone (as the street life: nothing far, nothing in the shadow and reflection views) with its hierarchy (the B
  model's hash, as Rockport's: the fragments' hierarchies are in L2RA.BUN, loaded with the track), drawn to DRAW m;
  our lantern one solid of ours (`lantern_solid`, in the first district that has one) named by every lantern instance.
  Exclude flags INSTANCE_FLAGS (low 16 bits = the override entry's flags, as every Rockport pole's).
- **The spawner records** (tools/world/smackables.py) in ftown-smackables.bun: per pole its physics position and the
  quaternion of its model's x axis, model and collision volume (X0's own name; the lantern borrows XO_LightPoleA's
  volume, 9.0 m, by name), attributes `trafficlight` (all five of Rockport's kinds use it), the override entry (its
  district's section, its instance, OVERRIDE_FLAGS).
"""
import math
import os
import sys
from dataclasses import dataclass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (TOOLS, os.path.join(TOOLS, "x360"), os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from vlthash import vlt32  # noqa: E402

MAIN_KINDS = ("motorway", "trunk", "primary", "secondary", "tertiary")
WIDE_SIGNAL = 10.0  # m of road width from which a signal gets the long arm
DRAW = 300.0  # m: the poles' draw distance at the view's H (as the bus shelters)
INSTANCE_FLAGS = 0x40108060  # Rockport's pole flags 0x40108000 with the street life's low byte 0x60
OVERRIDE_FLAGS = INSTANCE_FLAGS & 0xFFFF  # = the instance's low 16 bits (AssignOverrides writes them back)
ATTRIBUTES = "trafficlight"
LANTERN_SOLID = "FTB_LANTERN_LAMP"
LANTERN_VOLUME = "XO_LightPoleA_1b_00"
FIRST_UID = 20000  # unique ids of our records (Rockport's packs' first ids run to 6,667 of 13,484 records)

# role: (X0 model (the B level, its solid name), the mixed-case name the records' model and volume hash, kind)
ROLES = {
    "light_c": ("XO_STREETLIGHTC_1B_00", "XO_StreetLightC_1b_00"),
    "light_cb": ("XO_STREETLIGHTCB_1B_00", "XO_StreetLightCb_1b_00"),
    "signal_a": ("XO_TRAFFICLIGHTA_1B_00", "XO_TrafficLightA_1b_00"),
    "signal_b": ("XO_TRAFFICLIGHTB_1B_00", "XO_TrafficLightB_1b_00"),
    "lantern": (None, LANTERN_VOLUME),
}


@dataclass
class Breakable:
    role: str
    x: float
    y: float
    z: float  # above the ground (the median's top, or 0)
    heading: float  # radians: the model's x axis in render
    road: str  # the road kind it stands by


def family(kind):
    return (kind or "").replace("_link", "")


def median_role(kind_a, kind_b, railing):
    """The role of a median's lamp between carriageways of these kinds."""
    if railing:
        return "light_cb"
    if family(kind_a) in MAIN_KINDS or family(kind_b) in MAIN_KINDS:
        return "light_c"
    return "lantern"


def signal_role(width_m):
    return "signal_a" if width_m >= WIDE_SIGNAL else "signal_b"


def arm_heading(to_x, to_y):
    """The model heading whose arm (X0's poles reach along their model's -y) points along (to_x, to_y)."""
    return math.atan2(to_y, to_x) + math.pi / 2.0


def x0_model(role):
    from tools.citymap import x0props
    return x0props.model(ROLES[role][0])


def solid_hash(role):
    """The slot-0 solid's name hash (X0's, or our lantern's)."""
    from chunks import bstringhash
    if role == "lantern":
        return bstringhash(LANTERN_SOLID)
    return int(x0_model(role)["hash"], 16)


def hierarchy(role):
    """The info's hierarchy hash: the B model's (Rockport's own infos, L2RA's 0x8003410B); none for the lantern."""
    return 0 if role == "lantern" else solid_hash(role)


def volume(role):
    return vlt32(ROLES[role][1])


def model_stats(role):
    """{"tris", "meshes", "density", "box"} of the slot-0 model."""
    if role == "lantern":
        return lantern_stats()
    m = x0_model(role)
    return {"tris": m["tris"], "meshes": m["meshes"], "density": m["density"], "box": m["box"]}


def info_radius(role, H=1000.0):
    """The info Radius that stops the main view drawing the pole DRAW m away (x0props.info_radius's rule)."""
    m = model_stats(role)
    if m["tris"] <= 39:
        return 0.0
    R = DRAW / (1.0 + H / (8.7 * max(6.0, m["density"])))
    return max(0.0, R - 6.0)


def footprint(role, x, y, heading):
    """The plan hull of the pole's model as placed (for the wires' keep-off)."""
    from shapely.geometry import MultiPoint
    b = model_stats(role)["box"]
    c, s = math.cos(heading), math.sin(heading)
    pts = [(x + px * c - py * s, y + px * s + py * c) for px in (b[0], b[3]) for py in (b[1], b[4])]
    return MultiPoint(pts).convex_hull


def height(role):
    return model_stats(role)["box"][5]


# ---------------------------------------------------------------- our lantern lamp as a solid of its own

_LANTERN = {}


def lantern_groups():
    """[(texture hash, mesh name, tris, uvs, colours)]: the sector lamp (furniture_models.lamp_sector) at its foot,
    x along the road, in the furniture atlas, its lantern lit by the evening's lamp class (as when baked)."""
    from chunks import bstringhash
    from tools.citymap import evening, textures
    from tools.citymap import furniture_models as FM
    from tools.citymap import parts as P
    placed = FM.place(FM.lamp_sector(), 0.0, 0.0, 0.0, 0.0)
    tris = [t for t, _c in placed]
    uvs = [tuple([textures.furniture_uv(c)] * 3) for _t, c in placed]
    cols = []
    for t, (_t, cell) in zip(tris, placed):
        col = P.lit(t, 72.0)  # furniture.FURN_GREY
        if cell == "lantern":
            col = evening.glow(col, "lamp")
        cols.append(col)
    name = textures.NAMES["furniture"]
    return [(bstringhash(name), name, tris, uvs, cols)]


def lantern_solid():
    from world import solids
    if "solid" not in _LANTERN:
        _LANTERN["solid"] = solids.make_solid_multi(LANTERN_SOLID, lantern_groups())
    return _LANTERN["solid"]


def lantern_stats():
    import struct
    so = lantern_solid()
    pts = [p for _h, _n, tris, _u, _c in lantern_groups() for t in tris for p in t]
    box = [min(p[a] for p in pts) for a in range(3)] + [max(p[a] for p in pts) for a in range(3)]
    return {"tris": struct.unpack_from("<h", so.header, 0x14)[0], "meshes": len(so.meshes),
            "density": struct.unpack_from("<f", so.header, 0x9C)[0], "box": box}


# ---------------------------------------------------------------- the records

def record(b, foot, override, uid):
    """The spawner record of pole b, its foot at render `foot` (x, y, z: its instance's position)."""
    from world import smackables
    from world.collision import to_physics
    pos = to_physics(foot)
    return smackables.make_record(smackables.quaternion(b.heading), pos, volume(b.role), volume(b.role),
                                  vlt32(ATTRIBUTES), override, uid)
