"""Car builder command line.

    python tools/carbuild/carbin.py dump <GEOMETRY.BIN or TEXTURES.BIN> <folder>
        a car file as a description folder (car.json for a model, textures.json for textures; both can share a folder)
    python tools/carbuild/carbin.py build <folder> <GEOMETRY.BIN or TEXTURES.BIN> [--compressed | --raw]
        a description folder as a car file in the game's layout; with both descriptions in the folder, the output
        name picks (TEXTURES.BIN -> textures)
    python tools/carbuild/carbin.py render <folder> <out dir> [--textures <folder>]... [--all-parts] [--wheels]
        front, side, rear and three-quarter PNGs (1280x720) of the description, by portable Blender (headless)
    python tools/carbuild/carbin.py prep tools/carbuild/cars/thar.json [--out <dir>]
        the car's source .blend (read only) as game parts in an intermediate folder (Blender, blender_prep.py)
    python tools/carbuild/carbin.py assemble tools/carbuild/cars/thar.json [--prep <dir>] [--out <dir>]
        the intermediate folder as the car's GEOMETRY.BIN and TEXTURES.BIN (donor: the game's GTI, read only), their
        description folder (desc/) and wheel_report.json (the values for the car's ecar and tires)

Never point the output at the game folder without the user's go-ahead (project rule).
"""
import argparse
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BLENDER = os.path.join(REPO, ".tools", "blender-4.3.2-windows-x64", "blender.exe")
sys.path.insert(0, HERE)

import describe  # noqa: E402
from geometry import read_geometry, write_geometry  # noqa: E402
from textures import PACK, read_textures, write_textures  # noqa: E402


def cmd_dump(args):
    with open(args.file, "rb") as f:
        data = f.read()
    if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == PACK:
        pack = read_textures(data)
        describe.dump_textures(pack, args.folder)
        print("%s: %d textures -> %s" % (args.file, len(pack.textures), args.folder))
    else:
        pack = read_geometry(data)
        describe.dump(pack, args.folder)
        print("%s: %d solids -> %s" % (args.file, len(pack.solids), args.folder))


def _wants_textures(folder, out):
    has_geo = os.path.exists(os.path.join(folder, "car.json"))
    has_tex = os.path.exists(os.path.join(folder, "textures.json"))
    if has_geo and has_tex:
        return os.path.basename(out).upper().startswith("TEXTURES")
    if not (has_geo or has_tex):
        raise SystemExit("%s holds no car.json or textures.json" % folder)
    return has_tex


def cmd_build(args):
    if _wants_textures(args.folder, args.file):
        pack = describe.load_textures(args.folder)
        mode = True if args.compressed else False if args.raw else None
        data = write_textures(pack, compressed=mode)
        what = "%d textures" % len(pack.textures)
    else:
        if args.raw:
            raise SystemExit("--raw is for textures (geometry is written uncompressed unless --compressed)")
        pack = describe.load(args.folder)
        data = write_geometry(pack, compressed=args.compressed)
        what = "%d solids" % len(pack.solids)
    with open(args.file, "wb") as f:
        f.write(data)
    print("%s: %s, %d bytes -> %s" % (args.folder, what, len(data), args.file))


def _render_run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(("parts:", "source objects:", "textures available:", "extent:", "wrote",
                               "wheel centre z")) or "Error" in line:
            print(line)
    if r.returncode != 0 or "Error" in r.stdout:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit("Blender failed (exit %d)" % r.returncode)
    return r.stdout


def _extent(log):
    """The framing box a render printed ("extent: min (x, y, z) max (x, y, z)")."""
    line = [l for l in log.splitlines() if l.startswith("extent:")][-1]
    nums = line.replace("extent: min", "").replace("max", "").replace("(", " ").replace(")", " ").replace(",", " ")
    return [float(x) for x in nums.split()]


VIEWS = ("front", "side", "rear", "three_quarter")


def compare_sheet(out):
    """compare_sheet.png: the source's four views above the built car's, each 640 x 360."""
    from PIL import Image, ImageDraw
    sheet = Image.new("RGB", (4 * 640, 2 * 360 + 40), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for row, (prefix, label) in enumerate((("source_", "source (.blend)"), ("built_", "built (GEOMETRY.BIN)"))):
        for col, v in enumerate(VIEWS):
            img = Image.open(os.path.join(out, prefix + v + ".png")).convert("RGB").resize((640, 360))
            sheet.paste(img, (col * 640, 20 + row * 380))
            draw.text((col * 640 + 8, row * 380 + 4), "%s - %s" % (label, v), fill=(0, 0, 0))
    path = os.path.join(out, "compare_sheet.png")
    sheet.save(path)
    print("wrote", path)


def cmd_render(args):
    view = os.path.join(HERE, "blender_view.py")
    out = os.path.abspath(args.out)
    cmd = [args.blender, "-b", "--factory-startup", "--python", view, "--", os.path.abspath(args.folder), out]
    for t in args.textures:
        cmd += ["--textures", os.path.abspath(t)]
    if args.all_parts:
        cmd.append("--all-parts")
    if args.wheels:
        cmd.append("--wheels")
    if args.wheels_at:
        cmd += ["--wheels-at", os.path.abspath(args.wheels_at)]
    if args.cabin:
        cmd.append("--cabin")
    if args.hide_interior:
        cmd.append("--hide-interior")
    if args.wheel_z is not None:
        cmd += ["--wheel-z", repr(args.wheel_z)]
    if args.select:
        cmd.append("--select")
    if args.masks and not args.compare:
        cmd.append("--masks")
    if not args.compare:
        _render_run(cmd)
        return
    # the built car, then its source from the same cameras (the built car's framing box), then the sheet
    cfg, work = _config(args.compare)
    prep = os.path.abspath(args.prep or os.path.join(work, "prep"))
    log = _render_run(cmd + ["--prefix", "built_", "--masks"])
    box = ["%.6f" % x for x in _extent(log)]
    _render_run([args.blender, "-b", os.path.join(REPO, cfg["source"]), "--factory-startup", "--python", view, "--",
                 os.path.abspath(args.folder), out, "--source", os.path.abspath(args.compare), "--prep", prep,
                 "--box"] + box + ["--prefix", "source_", "--masks"])
    compare_sheet(out)


def _blender_run(cmd, keep=("part ", "wrote")):
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(keep) or "Error" in line:
            print(line)
    if r.returncode != 0 or "Traceback" in r.stdout + r.stderr:
        sys.stderr.write(r.stdout[-4000:] + r.stderr[-3000:])
        raise SystemExit("Blender failed (exit %d)" % r.returncode)


def _config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    name = cfg["car"].lower()
    return cfg, os.path.join(REPO, ".superpowers", "carbuild", name)


def cmd_prep(args):
    cfg, work = _config(args.config)
    out = os.path.abspath(args.out or os.path.join(work, "prep"))
    source = os.path.join(REPO, cfg["source"])
    _blender_run([args.blender, "-b", source, "--factory-startup", "--python-exit-code", "1", "--python",
                  os.path.join(HERE, "blender_prep.py"), "--", os.path.abspath(args.config), out])


def cmd_assemble(args):
    import assemble
    cfg, work = _config(args.config)
    prep = os.path.abspath(args.prep or os.path.join(work, "prep"))
    out = os.path.abspath(args.out or os.path.join(work, "out"))
    game_cars = os.path.join(REPO, "Need For Speed Most Wanted Black Edition", "CARS")
    gpack, tpack, report = assemble.run(cfg, prep, out, game_cars)
    describe.dump(gpack, os.path.join(out, "desc"))
    describe.dump_textures(tpack, os.path.join(out, "desc"))
    print("%s: %d solids, %d textures -> %s" % (cfg["car"], len(gpack.solids), len(tpack.textures), out))
    print("wheel: W %.4f, TireSkidWidth %.4f, axles %.3f / %.3f, physics tyre %s" % (
        report["W"], report["TireSkidWidth"], report["front_axle_x"], report["rear_axle_x"], report["physics_tyre"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump", help="car file -> description folder")
    p.add_argument("file")
    p.add_argument("folder")
    p.set_defaults(func=cmd_dump)
    p = sub.add_parser("build", help="description folder -> car file")
    p.add_argument("folder")
    p.add_argument("file")
    p.add_argument("--compressed", action="store_true", help="literal JDLZ blocks (geometry and textures)")
    p.add_argument("--raw", action="store_true", help="textures: every decodable texture stored uncompressed (RAWW)")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("render", help="description folder -> PNG views (Blender)")
    p.add_argument("folder")
    p.add_argument("out")
    p.add_argument("--textures", action="append", default=[], help="another texture description (e.g. CARS/TEXTURES.BIN's)")
    p.add_argument("--all-parts", action="store_true", help="every part, not only detail level A of kit 00")
    p.add_argument("--wheels", action="store_true", help="include tyres and brakes (they sit at the origin)")
    p.add_argument("--wheels-at", help="wheel_report.json: the tyre at its four positions, as the game draws it")
    p.add_argument("--cabin", action="store_true", help="also close cabin views with the windows left out")
    p.add_argument("--masks", action="store_true", help="also black-on-white silhouettes (always with --compare)")
    p.add_argument("--hide-interior", action="store_true", help="leave the KIT00_INTERIOR and KIT00_DRIVER parts out")
    p.add_argument("--wheel-z", type=float, help="with --wheels-at: the wheel centres' z instead of the report's")
    p.add_argument("--select", action="store_true", help="only a low front-right three-quarter view (select.png), "
                   "as the car select shows the car")
    p.add_argument("--compare", metavar="CONFIG", help="car config: also render its source .blend from the same "
                   "cameras (source_/built_/mask_ views and compare_sheet.png)")
    p.add_argument("--prep", help="with --compare: the preparation folder (default .superpowers/carbuild/<car>/prep)")
    p.add_argument("--blender", default=BLENDER)
    p.set_defaults(func=cmd_render)
    p = sub.add_parser("prep", help="car config (cars/<car>.json) -> intermediate folder of game parts (Blender)")
    p.add_argument("config")
    p.add_argument("--out", help="default .superpowers/carbuild/<car>/prep")
    p.add_argument("--blender", default=BLENDER)
    p.set_defaults(func=cmd_prep)
    p = sub.add_parser("assemble", help="intermediate folder -> GEOMETRY.BIN, TEXTURES.BIN, desc/, wheel_report.json")
    p.add_argument("config")
    p.add_argument("--prep", help="default .superpowers/carbuild/<car>/prep")
    p.add_argument("--out", help="default .superpowers/carbuild/<car>/out")
    p.set_defaults(func=cmd_assemble)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
