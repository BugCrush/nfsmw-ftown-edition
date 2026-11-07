"""The install steps, in the spec's order, each a thin wrapper around the repo's tested install code.

Every step declares the downloads it needs, the steps it depends on, and the game files it may change (the journal
backs those up first and stops on a change anywhere else). A step whose download is missing, or whose dependency was
skipped, is skipped with the reason; the others still run.

The repo tools find their inputs under the repo's layout (tools/cars/cars.yaml names sources such as
.superpowers/downloads/cars/754/files, the Chiron and Thar packages reach them by relative paths). The installer
rebuilds that layout in <work>\\mirror: the payload's packages and tuning scripts at tools/cars/..., each found download
copied to the path downloads.json names as its `mirror`, the Thar's generated files at .superpowers/carbuild/thar/....
The downloads folder itself is never written to.
"""
import json
import os
import shutil
import sys

from . import toolpaths  # noqa: F401  (sys.path for the repo tools)

import yaml


class Skip(Exception):
    pass


class Ctx:
    def __init__(self, game, payload, work, found, journal, log=print):
        self.game, self.payload, self.work, self.found, self.journal, self.log = game, payload, work, found, journal, log
        self.mirror = os.path.join(work, "mirror")
        self.done, self.skipped = [], {}
        self.tools = None

    def p(self, *parts):
        return os.path.join(self.payload, *parts)

    def dl(self, iid):
        f = self.found.get(iid)
        if f is None or not hasattr(f, "root"):
            raise Skip(getattr(f, "reason", "%s is not available" % iid))
        return f

    def mirrored(self, iid):
        """The download copied to its mirror path (once); returns that path."""
        f = self.dl(iid)
        dest = os.path.join(self.mirror, *f.item["mirror"].split("/"))
        if not os.path.isdir(dest):
            for c in f.item["contents"]:
                d = os.path.join(dest, *c["path"].split("/"))
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(f.path(c["path"]), d)
        return dest

    def record(self, name):
        d = os.path.join(self.work, "records", name)
        if os.path.isdir(d):
            shutil.rmtree(d)
        return d


class Step:
    def __init__(self, sid, title, run, may_change, needs=(), after=(), tools=False):
        self.id, self.title, self.run, self.may_change = sid, title, run, list(may_change)
        self.needs, self.after, self.tools = list(needs), list(after), tools


TOOL_ITEMS = ("attribulator", "binarius", "dotnet_x86")


def setup_tools(ctx):
    """The player's Attribulator, Binarius and .NET runtime copied into the work folder (Binarius writes its logs
    beside itself) and every reused module pointed at them."""
    if ctx.tools:
        return ctx.tools
    dirs = {}
    for iid in TOOL_ITEMS:
        f = ctx.dl(iid)
        dest = os.path.join(ctx.work, "tools", iid)
        if not os.path.isdir(dest):
            shutil.copytree(os.path.join(f.root, *f.item.get("tool_dir", ".").split("/")), dest)
        dirs[iid] = dest
    toolpaths.configure(dirs["attribulator"], dirs["binarius"], dirs["dotnet_x86"])
    import extract_car
    nikki = os.path.join(ctx.work, "tools", "nikki-export")
    if not os.path.isdir(nikki):
        shutil.copytree(ctx.p("tools", "nikki-export"), nikki)
        for n in ("Nikki.dll", "CoreExtensions.dll", "LZCompressLib.dll"):
            shutil.copy(os.path.join(dirs["binarius"], n), nikki)
    extract_car.DOTNET = os.path.join(dirs["dotnet_x86"], "dotnet.exe")
    extract_car.EXPORTER = os.path.join(nikki, "NikkiExport.dll")
    os.environ["DOTNET_ROOT(x86)"] = dirs["dotnet_x86"]
    os.environ["DOTNET_ROLL_FORWARD"] = "Major"
    ctx.tools = dirs
    return dirs


def _copy(ctx, src, rel):
    dst = os.path.join(ctx.game, *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


# ---------------------------------------------------------------------------------------------------- the steps

def run_asi_loader(ctx):
    _copy(ctx, ctx.p("root", "dinput8.dll"), "dinput8.dll")


def run_dxvk(ctx):
    _copy(ctx, ctx.p("root", "d3d9.dll"), "d3d9.dll")
    _copy(ctx, ctx.p("root", "dxvk.conf"), "dxvk.conf")


def run_laa(ctx):
    import stage4
    exe = os.path.join(ctx.game, "speed.exe")
    data = open(exe, "rb").read()
    new = stage4.large_address_aware(data)
    if new != data:
        open(exe, "wb").write(new)


def run_x360_stage1(ctx):
    import stage1
    pack = ctx.dl("x360_complex").root
    builds = {"TexWizard.asi": ctx.p("builds", "TexWizard.asi"),
              stage1.WSF: ctx.p("builds", stage1.WSF)}
    stage1.run(ctx.game, pack, builds, ctx.record("x360-stage1"), check_game=False,
               wsf_default_ini=ctx.p("builds", "NFSMostWanted.WidescreenFix.ini"), hash_list=None)


def run_x360_stage2(ctx):
    import stage2
    stage2.OUT = {"hd": ctx.p("builds"), "fe": ctx.p("builds")}
    stage2.run(ctx.game, ctx.record("x360-stage2"), check_game=False)


def _stage4_paths(ctx, cache=False):
    import stage4
    pack = ctx.dl("x360_complex").root
    stage4.PACK_FILES = os.path.join(pack, "ModData", "Files")
    if cache:
        item = ctx.dl("x360_easy_cache")
        stage4.EMPTY_CACHE = item.path(item.item["anchor"])
    return stage4


def run_x360_sounds(ctx):
    """The pack's options 11 and 12: its music and engine sounds (stage 4, first part)."""
    import stages
    s4 = _stage4_paths(ctx)
    eng = os.path.join(s4.PACK_FILES, "SOUND", "ENGINE")
    copies = [(os.path.join(s4.PACK_FILES, "SOUND", "PFDATA", n), "SOUND\\PFDATA\\" + n) for n in ("MW_Music.mpf", "MW_Music.mus")]
    copies += [(os.path.join(eng, n), "SOUND\\ENGINE\\" + n) for n in sorted(os.listdir(eng))]
    stages.install_companion(ctx.game, copies, {}, ctx.record("x360-sounds"), check_game=False)


def run_x360_movies(ctx):
    import stages
    movies = os.path.join(ctx.dl("x360_movies").root, "MOVIES")
    copies = [(os.path.join(movies, n), "MOVIES\\" + n) for n in sorted(os.listdir(movies)) if n.endswith(".vp6")]
    ini = os.path.join(ctx.game, "scripts", "X360Stuff.ini")
    stages.install_companion(ctx.game, copies, {r"scripts\X360Stuff.ini": (ini, {("VIDEO", "WidescreenMovies"): "1"})},
                             ctx.record("x360-movies"), check_game=False)


def run_vinyls(ctx):
    import files
    import stages
    root = os.path.join(ctx.dl("vinyls_1024").root, "Binary")
    copies = [(os.path.join(root, "CARS", "TEXTURES.BIN"), r"CARS\TEXTURES.BIN")]
    for car in sorted(os.listdir(os.path.join(root, "CARS"))):
        p = os.path.join(root, "CARS", car, "VINYLS.BIN")
        rel = "CARS\\%s\\VINYLS.BIN" % car
        if os.path.isfile(p) and files.find(ctx.game, rel):
            copies.append((p, rel))
    stages.install_companion(ctx.game, copies, {}, ctx.record("vinyls"), check_game=False)


def run_memory_unlock(ctx):
    import files
    s4 = _stage4_paths(ctx, cache=True)
    for rel, data in s4.unlocked_memory_files(ctx.game).items():
        p = files.find(ctx.game, rel)
        if open(p, "rb").read() != data:
            open(p, "wb").write(data)


def run_x360_stage5(ctx):
    import stage5
    stage5.run(ctx.game, ctx.record("x360-stage5"), check_game=False)


def run_retex(ctx):
    sys.argv = sys.argv[:1]  # retex.py reads its command line only when run as a program; keep that true
    import retex
    src = os.path.join(ctx.dl("retex").root, "TexturePacks", "ReTex")
    for name in retex.FILES:
        _copy(ctx, os.path.join(src, name), "TexturePacks/ReTex/" + name)
    json_path = os.path.join(ctx.game, "scripts", "TexWizard.json")
    after = retex.with_pack(open(json_path, "rb").read())
    if after is not None:
        open(json_path, "wb").write(after)


# ------------------------------------------------------------------------------------------------- add-on cars

def _cars_config(ctx):
    with open(ctx.p("cars", "cars-release.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def _prepare_mirror(ctx):
    """The payload's car packages and tuning scripts at their repo paths inside the mirror (once)."""
    dest = os.path.join(ctx.mirror, "tools", "cars")
    if not os.path.isdir(dest):
        shutil.copytree(ctx.p("cars", "tools-cars"), dest)
    return dest


def install_car(ctx, name, entry):
    import install as cars_install
    setup_tools(ctx)
    _prepare_mirror(ctx)
    for iid in entry.get("downloads", []):
        ctx.mirrored(iid)
    cars_install.ROOT = ctx.mirror
    car = {k: v for k, v in entry.items() if k != "downloads"}
    car["source"] = os.path.join(ctx.mirror, *entry["source"].split("/"))
    cars_install.install(name, car, ctx.game, ctx.record("car-" + name), game_running=lambda: False)


def _car_runner(name):
    def run(ctx):
        cfg = _cars_config(ctx)
        entry = cfg[name]
        pre = entry.get("prepare")
        if pre:
            PREPARE[pre](ctx, entry)
        install_car(ctx, name, entry)
    return run


def prepare_chiron(ctx, entry):
    """The Chiron's car parts and car type, exported from the mod's own GlobalB.lzc (read only) as cars.yaml says."""
    import extract_car
    setup_tools(ctx)
    root = ctx.mirrored("car_chiron")
    out = os.path.join(ctx.mirror, ".superpowers", "downloads", "cars", "697", "extracted")
    if not os.path.isdir(out):
        os.makedirs(out)
        extract_car.extract_car(os.path.join(root, "First mod", "GLOBAL", "GlobalB.lzc"), "CHIRON", out,
                                ("DBModelParts", "CarTypeInfos"))


def prepare_longnosecab_skinnable(ctx, entry):
    import skinnable
    skinnable.OUT = os.path.join(ctx.mirror, *entry["source"].split("/"), "GlobalB.lzc")
    saved = sys.argv
    sys.argv = [saved[0], ctx.game]
    try:
        skinnable.main()
    finally:
        sys.argv = saved


def prepare_longnosecab_bodykits(ctx, entry):
    """The mod's LONGNOSECAB.ini with BodyKits = 0 in [Parts] and [RandomParts] (its model has only KIT00)."""
    src = os.path.join(ctx.mirrored("car_longnosecab"), "Longnose Cab Semi Truck (Addon)", "Binary Files", "_Main",
                       "scripts", "UnlimiterData", "LONGNOSECAB.ini")
    dest_dir = os.path.join(ctx.mirror, *entry["source"].split("/"))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "LONGNOSECAB.ini")
    data = open(src, "rb").read()
    # the Unlimiter's file has // comments before its first section, which configparser cannot read: change the two
    # values in place, every other byte kept ([Parts] and [RandomParts] are its only BodyKits keys)
    if data.count(b"BodyKits = 1 ") != 2:
        raise RuntimeError("LONGNOSECAB.ini is not the expected file (BodyKits lines)")
    with open(dest, "wb") as f:
        f.write(data.replace(b"BodyKits = 1 ", b"BodyKits = 0 "))


def prepare_thar(ctx, entry):
    """The Thar built on the player's machine: its parts list and car type from the Longnose Cab and Tomahawk mods'
    templates, its model and textures assembled from our shipped parts and the player's own CARS folder (the GTI's
    collision header, the SL65's interior and driver), its logos from the payload."""
    import assemble
    import make_cartype
    import make_parts
    make_parts.TEMPLATE = os.path.join(ctx.mirrored("car_longnosecab"), "Longnose Cab Semi Truck (Addon)",
                                       "Binary Files", "_CarParts", "DBModelParts.bin")
    make_cartype.TEMPLATE = os.path.join(ctx.mirrored("car_tomahawk"), "Binary Files", "_CarParts", "CarTypeInfos.bin")
    base = os.path.join(ctx.mirror, ".superpowers", "carbuild", "thar")
    package, out = os.path.join(base, "package"), os.path.join(base, "out")
    make_parts.main([package])
    make_cartype.main([package])
    logo = os.path.join(package, "logo")
    if os.path.isdir(logo):
        shutil.rmtree(logo)
    shutil.copytree(ctx.p("cars", "thar", "logo"), logo)
    with open(ctx.p("cars", "thar", "thar.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assemble.run(cfg, ctx.p("cars", "thar", "prep"), out, os.path.join(ctx.game, "CARS"))


PREPARE = {"chiron": prepare_chiron, "longnosecab-skinnable": prepare_longnosecab_skinnable,
           "longnosecab-bodykits": prepare_longnosecab_bodykits, "thar": prepare_thar}

CAR_AREA = ["GLOBAL/*", "FRONTEND/*", "LANGUAGES/*", "scripts/**", "CARS/*"]


def car_steps(order):
    """One step per cars-release.yaml entry, in the file's order (the order the user's game got them)."""
    out = []
    for name, entry in order:
        area = CAR_AREA + ["CARS/%s/**" % c for c in entry.get("car_folders", [])]
        needs = list(TOOL_ITEMS) + list(entry.get("downloads", []))
        out.append(Step("car-" + name, entry.get("title", name), _car_runner(name), area, needs=needs,
                        after=["x360_stage1"] + ["car-" + a for a in entry.get("after", [])], tools=True))
    return out


# ------------------------------------------------------------------------------------------------- our files

def _copy_tree(ctx, src_dir, rel_dir):
    for dp, _, names in os.walk(src_dir):
        for n in names:
            rel = os.path.relpath(os.path.join(dp, n), src_dir).replace(os.sep, "/")
            _copy(ctx, os.path.join(dp, n), rel_dir + "/" + rel)


def run_companions(ctx):
    """The Widescreen Fix's texture file (its .asi came with stage 1)."""
    _copy(ctx, ctx.p("builds", "NFSMostWanted.WidescreenFix.tpk"), "scripts/NFSMostWanted.WidescreenFix.tpk")


def run_carstable(ctx):
    _copy_tree(ctx, ctx.p("carstable"), "scripts")


def run_our_plugins(ctx):
    _copy_tree(ctx, ctx.p("plugins"), "scripts")


def run_ftown(ctx):
    _copy_tree(ctx, ctx.p("ftown"), "scripts")


def run_settings(ctx):
    """Our settings: value changes in other authors' .ini files (their files stay theirs; settings.py). A file the
    game lacks is first copied from the payload's default where settings.json names one (a game without the
    repack's Widescreen Fix .ini)."""
    from . import settings
    with open(ctx.p("settings", "settings.json"), encoding="utf-8") as f:
        changes = json.load(f)
    for rel, sections in changes.items():
        path = os.path.join(ctx.game, *rel.split("/"))
        if not os.path.exists(path):
            if "_default" not in sections:
                ctx.log("note: %s is not there; its settings are left out" % rel)
                continue
            _copy(ctx, ctx.p(*sections["_default"].split("/")), rel)
        data = open(path, "rb").read()
        new, missing = settings.apply(data, sections)
        for m in missing:
            ctx.log("note: %s has no %s (another version of that plugin); left as it is" % (rel, m))
        if new != data:
            open(path, "wb").write(new)


# ------------------------------------------------------------------------------------------------- the list

X360_AREA = ["GLOBAL/*", "FRONTEND/*", "FRONTEND/PLATFORMS/*", "TRACKS/STREAML2RA.BUN", "TRACKS/TexWizardX360/**",
             "FX/**", "scripts/**"]


def all_steps(cars_order):
    s = [
        Step("asi_loader", "ASI loader", run_asi_loader, ["dinput8.dll"]),
        Step("dxvk", "DXVK", run_dxvk, ["d3d9.dll", "dxvk.conf"]),
        Step("laa", "4 GB memory flag on speed.exe", run_laa, ["speed.exe"]),
        Step("x360_stage1", "Xbox 360 Stuff Pack (database, textures, track, plugins)", run_x360_stage1, X360_AREA,
             needs=["x360_complex"] + list(TOOL_ITEMS), tools=True),
        Step("x360_stage2", "HD Reflections and Front-End Shadows", run_x360_stage2, ["scripts/**"], after=["x360_stage1"]),
        Step("x360_sounds", "Xbox 360 music and engine sounds", run_x360_sounds,
             ["SOUND/PFDATA/MW_Music.*", "SOUND/ENGINE/*"], needs=["x360_complex"], after=["x360_stage1"]),
        Step("x360_movies", "Xbox 360 cutscenes", run_x360_movies, ["MOVIES/*", "scripts/X360Stuff.ini"],
             needs=["x360_movies"], after=["x360_stage1"]),
        Step("vinyls", "1024x vinyls", run_vinyls, ["CARS/TEXTURES.BIN", "CARS/*/VINYLS.BIN"], needs=["vinyls_1024"],
             after=["x360_stage1"]),
        Step("memory_unlock", "memory files unlocked", run_memory_unlock, ["GLOBAL/*MemoryFile.bin"],
             needs=["x360_complex", "x360_easy_cache"], after=["x360_stage1"]),
        Step("x360_stage5", "Xbox 360 pack settings", run_x360_stage5, ["scripts/*.ini"], after=["x360_stage2"]),
        Step("retex", "ReTex 2.02 textures", run_retex, ["TexturePacks/**", "scripts/TexWizard.json"], needs=["retex"],
             after=["x360_stage1"]),
        Step("companions", "Widescreen Fix textures", run_companions, ["scripts/**"]),
    ]
    s += car_steps(cars_order)
    s += [
        Step("carstable", "CarStable", run_carstable, ["scripts/**"]),
        Step("our_plugins", "our plugins", run_our_plugins, ["scripts/**"]),
        Step("ftown", "F-Town", run_ftown, ["scripts/**"]),
        Step("settings", "our settings", run_settings, ["scripts/**", "dxvk.conf"]),
    ]
    return s


def load_cars_order(payload):
    """[(name, entry)] in cars-release.yaml's order (YAML mappings keep their order in PyYAML)."""
    with open(os.path.join(payload, "cars", "cars-release.yaml"), encoding="utf-8") as f:
        return list(yaml.safe_load(f).items())


def run_all(ctx, steps, log=print):
    """Runs the steps in order, each inside the journal. Returns (done ids, {skipped id: reason})."""
    for st in steps:
        missing = [n for n in st.needs if not hasattr(ctx.found.get(n), "root")]
        blocked = [a for a in st.after if a in ctx.skipped]
        if missing:
            reasons = [getattr(ctx.found.get(n), "reason", n) for n in missing]
            ctx.skipped[st.id] = "; ".join(reasons)
            log("SKIP  %s: %s" % (st.title, ctx.skipped[st.id]))
            continue
        if blocked:
            ctx.skipped[st.id] = "needs %s, which was skipped" % ", ".join(blocked)
            log("SKIP  %s: %s" % (st.title, ctx.skipped[st.id]))
            continue
        log("....  %s" % st.title)
        if st.tools:
            setup_tools(ctx)  # before the step: the reused modules' own defaults point at a developer's folders
        with ctx.journal.step(st.id, st.may_change):
            st.run(ctx)
        ctx.done.append(st.id)
        log("DONE  %s" % st.title)
    return ctx.done, ctx.skipped
