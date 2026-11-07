"""The game's conventions for a car model's origin and wheels, measured on the game's own cars.

Evidence (tests/test_conventions.py, 17 racers, the SEMI and the Longnose Cab; docs/carbuild-format.md "Origin and
wheels"):

- TYRE_SIDE = +1: a racer's tyre solid (<CAR>_KIT00_FRONT_TIRE_A) is centred on its axle in x and z, and in y it
  starts at its outer-face plane (y within 4 cm of 0) and extends to +y by the tyre's width. The game draws it scaled
  to TireSkidWidth / box width across and TireOffsets W / (box length / 2) in radius (speed.exe 0x755C4A: the model's
  box, i.e. vertex extents + 0.01 m a side), at y = Y + k*y_m on the right (Y < 0) and y = Y - skid + k*y_m on the left
  (0x74F221..0x74F235), so both tyres cover |y| in [|Y| - skid, |Y|]: |TireOffsets Y| is the outer face. On every racer
  the body's side at the wheel lies 0..6 cm outside that face.
- ORIGIN_Z = "body_min": the origin's height is the body's lowest point (KIT00_BODY_A lowest z within 0.08 m of 0 on
  every racer). Where the game draws the wheel centres (speed.exe, the nfsmw decompilation; race_wheel_centre_z,
  fe_wheel_centre_z): in a race at z = Z + W - RIDE_HEIGHT*0.0254 + c - ecar RideHeight*0.0254 (RIDE_HEIGHT and
  RideHeight in inches, c the spring's rest compression), in the car select at z = Z + FECompressions; the two agree
  within a median 1.3 cm on 25 racers. (Part 2's W - RIDE_HEIGHT/100 was a fit to fender gaps, not the game's rule.)
  The physics holds the collision box's bottom RIDE_HEIGHT - c above the road, and a race draws the wheels on the road
  only when that bottom is at z = TireOffsets Z in the model (every racer's collision: pivot y = half height).
- ORIGIN_X = "body_centre": the origin is the middle of the body's length (within 0.2 m), not the axles' midpoint
  (that is up to 0.25 m off).
- The SEMI and other traffic models keep a centred tyre; the Thar follows the racers.
"""

import hashlib
import os
import shutil
import sys

TYRE_SIDE = +1
ORIGIN_Z = "body_min"
ORIGIN_X = "body_centre"
BOX_MARGIN = 0.01  # the game's tools grow every solid's box by this (docs/carbuild-format.md)
DB_FILES = ("attributes.bin", "fe_attrib.bin", "gameplay.bin")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


class DatabaseUnavailable(Exception):
    pass


def _find(root, rel):
    cur = root
    for part in rel.split("/"):
        names = {n.lower(): n for n in os.listdir(cur)} if os.path.isdir(cur) else {}
        if part.lower() not in names:
            return None
        cur = os.path.join(cur, names[part.lower()])
    return cur


def load_database(game, cache_root):
    """The game's ecar and chassis collections as {car name (lower case): Data}, from an Attribulator unpack of the
    game's GLOBAL database files (copied first; the game folder is only read). Cached under cache_root by the digest of
    attributes.bin. Raises DatabaseUnavailable when the files or Attribulator are missing."""
    import yaml
    paths = [_find(game, "GLOBAL/" + f) for f in DB_FILES]
    if None in paths:
        raise DatabaseUnavailable("game database files missing under " + game)
    sys.path.insert(0, os.path.join(REPO, "tools", "x360"))
    import part1
    if not (os.path.exists(part1.ATTRIBULATOR) and os.path.exists(part1.DOTNET_X86)):
        raise DatabaseUnavailable("Attribulator missing at " + part1.ATTRIBULATOR)
    with open(paths[0], "rb") as f:
        key = hashlib.sha256(f.read()).hexdigest()[:16]
    folder = os.path.join(cache_root, "db-" + key)
    yml = os.path.join(folder, "yml")
    db_dir = os.path.join(yml, "main", "attributes", "db")
    if not os.path.exists(os.path.join(db_dir, "chassis.yml")):
        src = os.path.join(folder, "in")
        os.makedirs(src, exist_ok=True)
        for f, p in zip(DB_FILES, paths):
            shutil.copy(p, os.path.join(src, f))
        if os.path.exists(yml):
            shutil.rmtree(yml)
        part1.unpack(src, yml)
    out = {"parents": {}}
    for cls in ("ecar", "chassis", "tires", "pvehicle"):
        with open(os.path.join(db_dir, cls + ".yml"), encoding="utf-8") as f:
            items = yaml.safe_load(f)
        out[cls] = {c["Name"]: c.get("Data") or {} for c in items}
        out["parents"][cls] = {c["Name"]: c.get("ParentName") for c in items}
    return out


def _points(solid):
    return [p for m in solid.meshes() for p in solid.positions(m)]


def tyre_span(y, skid, tyre_y, margin=BOX_MARGIN):
    """Where the game draws a tyre across the car, as (inner |y|, outer |y|), for TireOffsets Y = y, TireSkidWidth
    skid, and a tyre model spanning tyre_y = (min y, max y) (speed.exe 0x74F221 and 0x755C4A; see the module notes)."""
    ymin, ymax = tyre_y
    k = skid / ((ymax - ymin) + 2 * margin)
    if y < 0:
        a, b = y + k * ymin, y + k * ymax
    else:
        a, b = y - skid + k * ymin, y - skid + k * ymax
    lo, hi = sorted((abs(a), abs(b)))
    return lo, hi


def wheel_centre_z(w, ride_height_cm, z=0.0):
    """The fender-fit placement Part 2 read from the models (W - RIDE_HEIGHT/100): not the game's rule (see
    race_wheel_centre_z); kept because it fixed where the Thar's model was placed against its origin (+0.307 m)."""
    return w - ride_height_cm / 100.0 + z


# ---- the game's own vertical wheel placement (speed.exe and the nfsmw decompilation; docs/carbuild-format.md)
INCH = 0.0254  # chassis RIDE_HEIGHT and TRAVEL and ecar RideHeight are inches (INCH2METERS; 0.0254 at 0x8A9388)
LBIN_TO_NM = 175.1268  # SPRING_STIFFNESS is lb/in (LBIN2NM)
G = 9.81


def rest_compression(spring_lbin, progression, load_n, travel_in=None):
    """The suspension's compression (m) at rest: SuspensionRacer's spring force k c (1 + progression c) carrying
    load_n, capped at the travel (inches) where the spring bottoms out."""
    k = spring_lbin * LBIN_TO_NM
    a = k * progression
    c = (-k + (k * k + 4 * a * load_n) ** 0.5) / (2 * a) if a else load_n / k
    if travel_in is not None:
        c = min(c, travel_in * INCH)
    return c


def race_wheel_centre_z(w, ride_height_in, compression, ecar_ride_height_in=0.0, z=0.0):
    """Where a race draws the wheel centre in the model's coordinates: CarRenderConn's tyre matrix z = Z + (sim
    compression) + (W - physics radius), the sim's compression = suspension compression - RIDE_HEIGHT + physics radius
    (DrawCar), and the body raised by ecar RideHeight (UpdateRenderMatrix, 0x7471AD)."""
    return z + w - ride_height_in * INCH + compression - ecar_ride_height_in * INCH


def wheel_well_drop(tyre_tops, wheel_well_in):
    """How far a race lowers every tyre (and raises the body): CarRenderConn::UpdateRenderMatrix (0x74736D..0x747425)
    compares the highest tyre top (centre z + W) with ecar WheelWell (inches; 0 switches it off; racers inherit 22.5)."""
    ww = (wheel_well_in or 0) * INCH
    top = max(tyre_tops)
    return top - ww if ww > 0 and top > ww else 0.0


def fe_wheel_centre_z(fe_compression, z=0.0):
    """Where the front end (car select) draws the wheel centre: TireOffsets Z + FECompressions[axle] (0x737AD0); the
    car's origin is set W - (Z + FECompressions) - 0.025 above the floor (0x7A97AC)."""
    return z + fe_compression


def attr(db, cls, name, key):
    """A database field with the parents' values inherited (Attribulator's ParentName)."""
    while name:
        data = db[cls].get(name)
        if data is None:
            return None
        if key in data:
            return data[key]
        name = db["parents"][cls].get(name)
    return None


def wheel_centres(name, db):
    """Per wheel (FL, FR, RR, RL) of a car in the database: its race, car-select and fender-fit wheel centre z."""
    offsets = attr(db, "ecar", name, "TireOffsets")["Data"]
    fec = attr(db, "ecar", name, "FECompressions")["Data"]
    erh = attr(db, "ecar", name, "RideHeight") or 0.0
    rh, spring = attr(db, "chassis", name, "RIDE_HEIGHT"), attr(db, "chassis", name, "SPRING_STIFFNESS")
    prog, travel = attr(db, "chassis", name, "SPRING_PROGRESSION"), attr(db, "chassis", name, "TRAVEL")
    bias = attr(db, "chassis", name, "FRONT_WEIGHT_BIAS") / 100.0
    mass = attr(db, "pvehicle", name, "MASS")
    out = []
    for i, t in enumerate(offsets):
        axle = "Rear" if i > 1 else "Front"
        share = (1 - bias if i > 1 else bias) / 2
        c = rest_compression(spring[axle], prog[axle], mass * G * share, travel[axle])
        out.append({"race": race_wheel_centre_z(t["W"], rh[axle], c, erh, t["Z"]),
                    "fe": fe_wheel_centre_z(fec[i // 2], t["Z"]), "old": wheel_centre_z(t["W"], rh[axle], t["Z"]),
                    "compression": c, "W": t["W"]})
    drop = wheel_well_drop([w["race"] + w["W"] for w in out], attr(db, "ecar", name, "WheelWell"))
    for w in out:
        w["race"] -= drop
        w["clamped"] = drop > 0
    return out


def wheel_rule(car, pack, db):
    """Measurements of one game car against the rules: its ecar TireOffsets (X, Y, Z, W per wheel), TireSkidWidth,
    chassis RIDE_HEIGHT (cm, front and rear), its tyre model's y range and radius, its body's lowest z, the middle of
    its length, the body's side at each wheel (largest |y| of body vertices within the wheel's length and below its
    top, on the wheel's side) and the gap from each tyre's top to the fender above it (None where no body vertex is
    above the tyre)."""
    name = car.upper()
    e = db["ecar"][car.lower()]
    offsets = [(t["X"], t["Y"], t["Z"], t["W"]) for t in e["TireOffsets"]["Data"]]
    skid = list(e["TireSkidWidth"]["Data"])
    rh = db["chassis"].get(car.lower(), {}).get("RIDE_HEIGHT", {"Front": 0, "Rear": 0})
    by = {s.name: s for s in pack.solids}
    tyre = _points(by[name + "_KIT00_FRONT_TIRE_A"])
    body = _points(by[name + "_KIT00_BODY_A"])
    tyre_y = (min(p[1] for p in tyre), max(p[1] for p in tyre))
    radius = (max(max(p[0] for p in tyre) - min(p[0] for p in tyre),
                  max(p[2] for p in tyre) - min(p[2] for p in tyre))) / 2
    sides, gaps = [], []
    for i, (x, y, z, w) in enumerate(offsets):
        zc = wheel_centre_z(w, rh["Rear"] if i > 1 else rh["Front"], z)
        same = [p for p in body if (p[1] > 0) == (y > 0)]
        side = [abs(p[1]) for p in same if abs(p[0] - x) < w and p[2] < zc + w]
        sides.append(max(side) if side else 0.0)
        lo, hi = abs(y) - skid[i], abs(y)
        above = [p[2] for p in same if abs(p[0] - x) < 0.04 and lo <= abs(p[1]) <= hi and p[2] > zc]
        gaps.append(min(above) - (zc + w) if above else None)
    return {
        "offsets": offsets, "skid": skid, "ride_height_cm": (rh["Front"], rh["Rear"]),
        "tyre_y": tyre_y, "tyre_radius": radius,
        "body_min_z": min(p[2] for p in body),
        "body_mid_x": (min(p[0] for p in body) + max(p[0] for p in body)) / 2,
        "body_side": sides, "fender_gap": gaps,
    }
