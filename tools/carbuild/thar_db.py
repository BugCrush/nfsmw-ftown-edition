"""Writes the Mahindra Thar's database script (tools/cars/packages/thar/thar.nfsms) from the tuned Raptor in the game.

    python tools/carbuild/thar_db.py [<game dir>]

The Thar is a copy of the tuned Raptor's database entries (pvehicle, engine, transmission, tires, chassis, brakes and
induction in both upgrade stages, ecar, frontend) with the user's numbers (docs/superpowers/specs/
2026-11-01-own-car-build-design.md; plan part 3 Global Constraints):
  - MASS 5,000 kg; torque 1.25 x the Raptor's in both stages;
  - the Raptor's revs, gears, differential, torque split, handling (brake lock, roll centre, aero centre, weight
    bias, shock valving, digression, progression, blowout), drag 0.22, grip scale 1; but STEERING 1 in both stages
    and TENSOR_SCALE Y 2 (second test-copy race: slow to turn at speed), YAW_SPEED 0.5 and YAW_CONTROL lowered to
    [0.2, 0.4, 0.45, 0.5] / top [0.3, 0.5, 0.7, 0.8] (third race: still a little slow at speed);
  - final gears x (Thar tyre radius / Raptor tyre radius) = 0.834, so a turn of the engine moves it as far as the
    Raptor (the wheel report's figure);
  - springs, shocks (compression, rebound), anti-roll bars, brakes and handbrake x 5000/7000;
  - tyres 245/50 R19 (the model's wheel), RIDE_HEIGHT 9.3 inches (the tuned Raptor's; the wheel report's
    ride_height_cm, a misnomer kept for the model's placement), ecar FECompressions at the model's wheel centre and
    ecar RideHeight that lowers the drawn body so a race draws the wheels there too, WheelWell above the tyre top
    at full bump so races never clamp them (conventions.py), and its own physics
    geometry: WHEEL_BASE, FRONT_AXLE and TRACK_WIDTH from its wheels, as every game car's match its own ecar wheels
    (centre-to-centre track = 2|Y| - TireSkidWidth);
  - ecar TireOffsets and TireSkidWidth from the wheel report; the Raptor's cameras (its ecar links) kept;
  - MODEL THAR (one name in Attribulator: the Binarius part copies a collision under THAR);
  - frontend: maker `mahindra` (a copy of `toyota`, the game's Asian region `japan`), car `thar` copied from the
    Raptor's, manufacturer number 30 (unused; the Unlimiter names makers from the node), price 70,000 (the Raptor:
    60,000; the Thar is quicker). UnlockedAt and IsCustomizable come from cars.yaml's overrides.
The game folder is only read: the database files are copied and unpacked under the cache folder.
"""
import hashlib
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "tools", "cars", "packages", "thar", "thar.nfsms")
DB_FILES = ("attributes.bin", "fe_attrib.bin", "gameplay.bin")

SOURCE, CAR = "raptor", "thar"
STAGES = ((SOURCE, CAR), (SOURCE + "_top", CAR + "_top"))
STAGED = ("engine", "transmission", "tires", "chassis", "brakes")
MASS = 5000
TORQUE_FACTOR = 1.25
SPRING_FACTOR = 5000.0 / 7000.0  # the Thar's mass over the tuned Raptor's
SCALED_BY_MASS = (("chassis", "SPRING_STIFFNESS"), ("chassis", "SHOCK_STIFFNESS"), ("chassis", "SHOCK_EXT_STIFFNESS"),
                  ("chassis", "SWAYBAR_STIFFNESS"), ("brakes", "BRAKES"), ("brakes", "EBRAKE"))
TYRE = {"SECTION_WIDTH": 245, "ASPECT_RATIO": 50, "RIM_SIZE": 19}
GRIP_SCALE = 1
DRAG = 0.22
MAKER, MAKER_TEMPLATE, REGION = "mahindra", "toyota", "japan"
MANUFACTURER = 30
COST = 70000
# handling (second test-copy race: slow to turn at speed): yaw torque scale against the yaw inertia scale, as the
# 911 Turbo's and the Lancer's ratio (0.23); the wheel angle as the stock stage's; YAW_CONTROL stays the Raptor's
YAW_SPEED = 0.5
STEERING = 1
# third test-copy race ("just slightly work on the handling a bit more"; 120-200 km/h turning p90 28.4 deg/s, the
# Challenger 34.5 with YAW_CONTROL [0.06, 0.1, 0.1, 0.15]): the Raptor's anti-slide rear grip (YAW_CONTROL, growing
# with speed) lowered towards the Golf/Gallardo range, keeping some (the user disliked the truck's drifting)
YAW_CONTROL = {"": (0.2, 0.4, 0.45, 0.5), "_top": (0.3, 0.5, 0.7, 0.8)}
TENSOR_Y = 2  # the GTI's (the Thar uses the GTI's collision box); the Raptor's 2.87 was set for a 5.5 m pickup


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


def game_unpack(game, cache_root):
    """An Attribulator unpack (YAML) of copies of the game's three database files, cached under cache_root by the
    digest of all three. Returns the unpack folder."""
    sys.path.insert(0, os.path.join(REPO, "tools", "x360"))
    import part1
    paths = [_find(game, "GLOBAL/" + f) for f in DB_FILES]
    if None in paths:
        raise DatabaseUnavailable("game database files missing under " + game)
    if not (os.path.exists(part1.ATTRIBULATOR) and os.path.exists(part1.DOTNET_X86)):
        raise DatabaseUnavailable("Attribulator missing at " + part1.ATTRIBULATOR)
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            h.update(f.read())
    folder = os.path.join(cache_root, "db3-" + h.hexdigest()[:16])
    yml = os.path.join(folder, "yml")
    if not os.path.exists(os.path.join(yml, "info.yml")):
        src = os.path.join(folder, "in")
        os.makedirs(src, exist_ok=True)
        for f, p in zip(DB_FILES, paths):
            shutil.copy(p, os.path.join(src, f))
        if os.path.exists(yml):
            shutil.rmtree(yml)
        part1.unpack(src, yml)
    return yml


def _collections(unpack_dir, cls):
    import glob
    import yaml
    sys.path.insert(0, os.path.join(REPO, "tools", "x360"))
    from vlthash import vlt32
    out = {}
    for path in glob.glob(os.path.join(unpack_dir, "main", "*", "*", cls + ".yml")):
        with open(path, encoding="utf-8") as f:
            for it in yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []:
                out[it["Name"]] = it
    return out, vlt32


def _get(unpack_dir, cls, name):
    """A collection's Data by name (or by the name's hash, as stage children are stored)."""
    colls, vlt32 = _collections(unpack_dir, cls)
    for key in (name, vlt32(name)):
        if key in colls:
            return colls[key].get("Data") or {}
    raise KeyError("%s %s not in the database" % (cls, name))


def num(v):
    """The shortest decimal that is the same single-precision number (the database stores floats)."""
    v = float(v)
    for n in range(4, 10):
        s = "%.*g" % (n, v)
        if struct.pack("<f", float(s)) == struct.pack("<f", v):
            return s
    return repr(v)


def rest_compressions(unpack_dir):
    """The Thar's spring compression at rest (m) per stage and axle: its mass on the Raptor's springs x SPRING_FACTOR,
    the Raptor's progression, weight bias and travel."""
    import conventions
    out = []
    for src, _ in STAGES:
        ch = _get(unpack_dir, "chassis", src)
        bias = ch["FRONT_WEIGHT_BIAS"] / 100.0
        for axle, share in (("Front", bias / 2), ("Rear", (1 - bias) / 2)):
            out.append(conventions.rest_compression(ch["SPRING_STIFFNESS"][axle] * SPRING_FACTOR,
                                                    ch["SPRING_PROGRESSION"][axle], MASS * conventions.G * share,
                                                    ch["TRAVEL"][axle]))
    return out


def ecar_ride_height(unpack_dir, wheels):
    """ecar RideHeight (inches) that makes a race draw the wheel centres at the model's (on average over both stages
    and axles); RIDE_HEIGHT itself stays as the physics was driven."""
    import conventions
    cs = rest_compressions(unpack_dir)
    c = sum(cs) / len(cs)
    return (wheels["W"] - wheels["ride_height_cm"] * conventions.INCH + c - wheels["wheel_centre_z"]) / conventions.INCH


def wheel_well(unpack_dir, wheels):
    """ecar WheelWell (inches, up to the next half inch) at the tyre top with the suspension at full travel (the most
    travel, the least rest compression of both stages)."""
    import math
    import conventions
    travel = max(_get(unpack_dir, "chassis", src)["TRAVEL"][a] for src, _ in STAGES for a in ("Front", "Rear"))
    top = wheels["wheel_centre_z"] + travel * conventions.INCH - min(rest_compressions(unpack_dir)) + wheels["W"]
    return math.ceil(top / conventions.INCH * 2) / 2


def write_script(unpack_dir, wheel_report, out_path):
    """Writes the script to out_path and returns its command lines."""
    with open(wheel_report) as f:
        wheels = json.load(f)
    final_factor = wheels["final_gear_ratio_vs_raptor"]
    lines = ["game MW"]
    add = lines.append
    # the copies: classes with two upgrade stages, induction's three levels, the drawn car, the menu entry
    for cls in STAGED:
        add("copy_node %s %s default %s" % (cls, SOURCE, CAR))
        add("copy_node %s %s_top %s %s_top" % (cls, SOURCE, CAR, CAR))
    add("copy_node induction %s_base default %s_base" % (SOURCE, CAR))
    add("copy_node induction %s_top %s_base %s_top" % (SOURCE, CAR, CAR))
    add("copy_node pvehicle %s racers %s" % (SOURCE, CAR))
    add("copy_node ecar %s racers %s" % (SOURCE, CAR))
    add("copy_node frontend %s %s %s" % (MAKER_TEMPLATE, REGION, MAKER))
    add("update_field frontend %s manufacturer %d" % (MAKER, MANUFACTURER))
    add("copy_node frontend %s %s %s" % (SOURCE, MAKER, CAR))
    add("update_field frontend %s manufacturer %d" % (CAR, MANUFACTURER))
    add("update_field frontend %s Cost %d" % (CAR, COST))
    # the car points at its own collections
    for part in ("Visual", "Collision", "Collision64"):
        add("update_field pvehicle %s MODEL %s %s" % (CAR, part, CAR.upper()))
    for cls in STAGED:
        add("update_field pvehicle %s %s[0] Collection %s" % (CAR, cls, CAR))
        add("update_field pvehicle %s %s[1] Collection %s_top" % (CAR, cls, CAR))
    add("update_field pvehicle %s induction[1] Collection %s_base" % (CAR, CAR))
    add("update_field pvehicle %s induction[2] Collection %s_top" % (CAR, CAR))
    add("update_field pvehicle %s frontend Collection %s" % (CAR, CAR))
    add("update_field pvehicle %s MASS %s" % (CAR, num(MASS)))
    # the user's numbers, stage by stage from the Raptor's own values
    for src, dst in STAGES:
        engine = _get(unpack_dir, "engine", src)
        for i, t in enumerate(engine["TORQUE"]["Data"]):
            add("update_field engine %s TORQUE[%d] %s" % (dst, i, num(t * TORQUE_FACTOR)))
        trans = _get(unpack_dir, "transmission", src)
        add("update_field transmission %s FINAL_GEAR %s" % (dst, num(trans["FINAL_GEAR"] * final_factor)))
        for cls, field in SCALED_BY_MASS:
            v = _get(unpack_dir, cls, src)[field]
            if isinstance(v, dict):
                for axle in ("Front", "Rear"):
                    add("update_field %s %s %s %s %s" % (cls, dst, field, axle, num(v[axle] * SPRING_FACTOR)))
            else:
                add("update_field %s %s %s %s" % (cls, dst, field, num(v * SPRING_FACTOR)))
        for axle in ("Front", "Rear"):
            for field, value in TYRE.items():
                add("update_field tires %s %s %s %d" % (dst, field, axle, value))
            add("update_field tires %s GRIP_SCALE %s %s" % (dst, axle, num(GRIP_SCALE)))
            add("update_field chassis %s RIDE_HEIGHT %s %s" % (dst, axle, num(wheels["ride_height_cm"])))
            add("update_field chassis %s TRACK_WIDTH %s %s" % (
                dst, axle, num(2 * abs(wheels["TireOffsets"][0]["Y"]) - wheels["TireSkidWidth"])))
        add("update_field chassis %s WHEEL_BASE %s" % (dst, num(wheels["wheelbase"])))
        add("update_field chassis %s FRONT_AXLE %s" % (dst, num(wheels["front_axle_x"])))
        add("update_field chassis %s DRAG_COEFFICIENT %s" % (dst, num(DRAG)))
        add("update_field tires %s YAW_SPEED %s" % (dst, num(YAW_SPEED)))
        add("update_field tires %s STEERING %s" % (dst, num(STEERING)))
        for i, value in enumerate(YAW_CONTROL[dst[len(CAR):]]):
            add("update_field tires %s YAW_CONTROL[%d] %s" % (dst, i, num(value)))
    add("update_field pvehicle %s TENSOR_SCALE Y %s" % (CAR, num(TENSOR_Y)))
    # the wheels as drawn
    for i, t in enumerate(wheels["TireOffsets"]):
        for m in ("X", "Y", "Z", "W"):
            add("update_field ecar %s TireOffsets[%d] %s %s" % (CAR, i, m, num(t[m])))
    for i in range(4):
        add("update_field ecar %s TireSkidWidth[%d] %s" % (CAR, i, num(wheels["TireSkidWidth"])))
    # the wheels' height: the car select draws them at FECompressions, a race at W - RIDE_HEIGHT + c - RideHeight
    # (conventions.py); both at the model's own wheel centre
    target = wheels["wheel_centre_z"]
    for i in range(2):
        add("update_field ecar %s FECompressions[%d] %s" % (CAR, i, num(round(target, 4))))
    add("update_field ecar %s RideHeight %s" % (CAR, num(round(ecar_ride_height(unpack_dir, wheels), 2))))
    # the racers' WheelWell (22.5 in, inherited) would pull the Thar's tyres down 8.5 cm in races; its own sits above the
    # tyre top at full bump, so it never clamps (the Raptor's ecar has no WheelWell of its own: added)
    add("add_field ecar %s WheelWell" % CAR)
    add("update_field ecar %s WheelWell %s" % (CAR, num(wheel_well(unpack_dir, wheels))))
    header = [l.strip() for l in __doc__.strip().splitlines()[2:]]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("// Mahindra Thar (our own build), generated by tools/carbuild/thar_db.py; do not edit by hand.\n")
        for h in header:
            f.write(("// " + h).rstrip() + "\n")
        f.write("\n".join(lines) + "\n")
    return lines


def main(argv):
    game = argv[0] if argv else os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
    unpack = game_unpack(game, os.path.join(REPO, ".superpowers", "carbuild", "cache"))
    lines = write_script(unpack, os.path.join(REPO, ".superpowers", "carbuild", "thar", "out", "wheel_report.json"), OUT)
    print("%d lines written to %s" % (len(lines), OUT))


if __name__ == "__main__":
    main(sys.argv[1:])
