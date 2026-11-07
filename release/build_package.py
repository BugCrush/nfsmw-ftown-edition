"""Assembles the public package: release/dist/NFSMW F-Town Edition/ (installer, payload, README, credits, licences)
and release/dist/NFSMW-FTown-Edition-<version>.zip.

    python release/build_package.py [--no-exe]

The payload holds only our own files and the open-source pieces whose licences allow it (audit table in
docs/superpowers/plans/2026-11-07-modpack.md). Every file is listed in payload-manifest.json with its sha256. The
build stops if a forbidden file (diagnostics, the user's times, unshipped F-Town files) or forbidden content (the home
location, the profile name, the user's e-mail) is in the package.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "installer"))
from ftedition import VERSION  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
SCRIPTS = os.path.join(GAME, "scripts")
DIST = os.path.join(HERE, "dist")
NAME = "NFSMW F-Town Edition"
OUT = os.path.join(DIST, NAME)
RESEARCH = os.path.join(REPO, ".superpowers", "visual-research", "repos")
WORK_LICENCES = os.path.join(HERE, "downloads-work", "dl", "licenses")

FTOWN_DATA = ["ftown-barriers.bun", "ftown-barriers-drag.bun", "ftown-barriers-speedtrap.bun", "ftown-barriers-sprint.bun",
              "ftown-city.bun", "ftown-connect.bin", "ftown-connector.bun", "ftown-evening.bin", "ftown-events.json",
              "ftown-icons.bun", "ftown-minimap.bun", "ftown-roadnet.bin", "ftown-smackables.bun", "ftown-traffic.json"]
PLUGINS = ["InputBridge.asi", "InputBridge.ini", "MusicBridge.asi", "MusicBridge.ini", "VisualBridge.asi",
           "VisualBridge.ini", "ReflectRate.asi", "ReflectRate.ini"]
# Plugins taken from the repo's build instead of the game's scripts folder: InputBridge with the default-layout patch
# ([Controls] DefaultLayout, 2026-11-07; stand-in tested in input/tests/default-layout.py), newer than the game's copy.
PLUGIN_SOURCES = {"InputBridge.asi": os.path.join(REPO, "input", "src", "InputBridge.asi")}

# Diagnostics are not shipped: GfxProbe, WorldProbe, ExitTrace, FpsRecorder, MusicProbe, PatchMap (logs which plugin
# patches which bytes; for our conflict checks only), and no logs.
FORBIDDEN_NAMES = ("gfxprobe", "worldprobe", "exittrace", "fpsrecorder", "musicprobe", "patchmap", "ftowntimes",
                   "ftown-reloc", "ftown-slab", ".log", "presentmon", "musicbridge.songs")
PRIVATE = os.path.join(HERE, "private", "forbidden.json")  # personal details to keep out (not in the public source)


def forbidden_patterns():
    """(text patterns, float32 byte patterns) from release/private/forbidden.json; empty where it does not exist."""
    if not os.path.exists(PRIVATE):
        return [], []
    d = json.load(open(PRIVATE, encoding="utf-8"))
    return [t.encode() for t in d["text"]], [struct.pack("<f", v) for v in d["floats"]]


# ------------------------------------------------------------------------------------------------ public .ini files

def _replace(data, old, new):
    if data.count(old) != 1:
        raise ValueError("expected one %r" % old)
    return data.replace(old, new)


def _ftown_minimap_block(data):
    """The [Minimap] safe-house comment and keys (from the comment line naming the safe house to the SafeHouse line)."""
    start = data.index(b"; Run K item 1: the safe house")
    key = data.index(b"\r\nSafeHouse" + b" = ", start) + 2  # (split: the joined text is a forbidden pattern)
    end = data.index(b"\r\n", key) + 2
    if b"SafeHouseIcon = 1\r\n" not in data[start:end]:
        raise ValueError("unexpected [Minimap] safe-house block")
    return start, end


FTOWN_COMMENT_NEW = (b"; A place of your own on F-Town's minimap, shown with the game's safe-house icon: set SafeHouseIcon to 1 and add\r\n"
                     b"; the key SafeHouse with the value x, y (F-Town's render metres; the plugin's log prints the car's position).\r\n"
                     b"SafeHouseIcon = 0\r\n")


INPUT_CONTROLS = (b"\r\n[Controls]\r\n"
                  b"; 1 = the game's default controller bindings (a new profile, and Restore Defaults in the Controls menu)\r\n"
                  b"; become the mod's layout for an Xbox pad: RT accelerate, LT brake, left stick steer, right stick up/down\r\n"
                  b"; shift up/down, A nitrous, B handbrake, X speedbreaker, Y pull camera back, LB look behind, RB camera,\r\n"
                  b"; Back reset, Start pause, D-pad events/blacklist/map/messages, right stick click next song.\r\n"
                  b"; 0 = the game's own defaults. Read when the game starts.\r\n"
                  b"DefaultLayout = 1\r\n")


def release_ini(name, data):
    """The public version of one of our .ini files (CRLF kept)."""
    if name == "FTownLoader.ini":
        start, end = _ftown_minimap_block(data)
        return data[:start] + FTOWN_COMMENT_NEW + data[end:]
    if name == "InputBridge.ini":
        data = _replace(data, b"\r\nLog = 1\r\nDir = ..\\..\\telemetry\r\nKeepLast = 10000\r\n",
                        b"\r\nLog = 0\r\nDir = telemetry\r\nKeepLast = 50\r\n")
        data = _replace(data, b"\r\nVirtualController = 1\r\n", b"\r\nVirtualController = 1\r\n" + INPUT_CONTROLS)
        return _replace(data, b"StateChanges = 1", b"StateChanges = 0")
    if name == "MusicBridge.ini":
        data = _replace(data, b"Folder = ..\\..\\CUSTOM SONGS\r\n", b"Folder = ..\\CUSTOM SONGS\r\n")
        return _replace(data, b"Calls = 1", b"Calls = 0")
    if name == "CarStable.ini":
        return _replace(data, b"; 0x0B28303D: the user's profile before any add-on car (2026-10-31).",
                        b"; 0x0B28303D: the Black Edition's own car list (a profile saved before any add-on car).")
    return data


def forbidden_hits(root, check_names=True):
    hits = []
    FORBIDDEN_TEXT, FORBIDDEN_FLOATS = forbidden_patterns()
    for dp, _, files in os.walk(root):
        for n in files:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            if check_names and any(f in n.lower() for f in FORBIDDEN_NAMES):
                hits.append("%s: forbidden file" % rel)
                continue
            data = open(p, "rb").read()
            low = data.lower()
            for b in FORBIDDEN_TEXT:
                if b.lower() in low:
                    hits.append("%s: contains %r" % (rel, b))
            for b in FORBIDDEN_FLOATS:
                if b in data:
                    hits.append("%s: contains the float bytes %r" % (rel, b))
    return hits


# ------------------------------------------------------------------------------------------------ assembly

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _put(src, rel, data=None):
    dst = os.path.join(OUT, "payload", *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if data is None:
        shutil.copyfile(src, dst)
    else:
        open(dst, "wb").write(data)


def _same(a, b, what):
    if sha(a) != sha(b):
        raise SystemExit("%s: %s differs from the game's installed copy %s" % (what, a, b))


def payload():
    root = os.path.join(OUT, "payload")
    if os.path.isdir(root):
        shutil.rmtree(root)
    # root of the game: the ASI loader (the repack's build of ThirteenAG's MIT loader, as tested), DXVK (identical to
    # the official 3.1.1 x32/d3d9.dll), our dxvk.conf (the frame-rate counter)
    for n in ("dinput8.dll", "d3d9.dll", "dxvk.conf"):
        _put(os.path.join(GAME, n), "root/" + n)
    # our builds of open-source companions, each checked against what the user's game runs
    comp = os.path.join(REPO, "companions")
    builds = {"TexWizard.asi": os.path.join(comp, "texwizard", "out", "TexWizard.asi"),
              "NFSMostWanted.WidescreenFix.asi": os.path.join(comp, "WidescreenFix", "out", "NFSMostWanted.WidescreenFix.asi"),
              "NFSMostWanted.WidescreenFix.ini": os.path.join(comp, "WidescreenFix", "out", "NFSMostWanted.WidescreenFix.ini"),
              "NFSMostWanted.WidescreenFix.tpk": os.path.join(comp, "WidescreenFix", "out", "NFSMostWanted.WidescreenFix.tpk"),
              "NFSMWHDReflections.asi": os.path.join(comp, "NFSHDReflections", "out", "NFSMWHDReflections.asi"),
              "NFSMWHDReflections.ini": os.path.join(comp, "NFSHDReflections", "out", "NFSMWHDReflections.ini"),
              "NFSMWFEShadows.asi": os.path.join(comp, "NFSMWFEShadows", "out", "NFSMWFEShadows.asi"),
              "NFSMWFEShadows.ini": os.path.join(comp, "NFSMWFEShadows", "out", "NFSMWFEShadows.ini")}
    for n, src in builds.items():
        if n.endswith((".asi", ".tpk")):
            _same(src, os.path.join(SCRIPTS, n), n)
        _put(src, "builds/" + n)
    for n in PLUGINS:
        src = PLUGIN_SOURCES.get(n, os.path.join(SCRIPTS, n))
        _put(src, "plugins/" + n, release_ini(n, open(src, "rb").read()) if n.endswith(".ini") else None)
    for n in ("CarStable.asi", "CarStable.ini"):
        src = os.path.join(SCRIPTS, n)
        _put(src, "carstable/" + n, release_ini(n, open(src, "rb").read()) if n.endswith(".ini") else None)
    # F-Town: the loader built without a built-in safe-house place (ftown/src), its public .ini, its data
    _put(os.path.join(REPO, "ftown", "src", "FTownLoader.asi"), "ftown/FTownLoader.asi")
    _put(None, "ftown/FTownLoader.ini", release_ini("FTownLoader.ini", open(os.path.join(SCRIPTS, "FTownLoader.ini"), "rb").read()))
    for n in FTOWN_DATA:
        _put(os.path.join(SCRIPTS, n), "ftown/" + n)
    # the add-on cars: our packages, tuning, the Thar's parts (from the CC-BY model) and logos
    pk = os.path.join(REPO, "tools", "cars", "packages")
    for car, names in {"chiron": ["chiron-launcher.end", "install.end", "strings.end"],
                       "longnosecab": ["install.end", "launcher.end", "strings.end"],
                       "thar": ["install.end", "launcher.end", "strings.end", "THAR.ini", "thar.nfsms"]}.items():
        for n in names:
            _put(os.path.join(pk, car, n), "cars/tools-cars/packages/%s/%s" % (car, n))
    tuning = os.path.join(HERE, "installer", "tuning")
    for n in sorted(os.listdir(tuning)):
        _put(os.path.join(tuning, n), "cars/tools-cars/tuning/" + n)
    _put(os.path.join(HERE, "installer", "cars-release.yaml"), "cars/cars-release.yaml")
    _put(os.path.join(REPO, "tools", "carbuild", "cars", "thar.json"), "cars/thar/thar.json")
    prep = os.path.join(REPO, ".superpowers", "carbuild", "thar", "prep")
    for n in sorted(os.listdir(prep)):
        _put(os.path.join(prep, n), "cars/thar/prep/" + n)
    logo = os.path.join(REPO, ".superpowers", "carbuild", "thar", "package", "logo")
    for n in sorted(os.listdir(logo)):
        _put(os.path.join(logo, n), "cars/thar/logo/" + n)
    nikki = os.path.join(REPO, "tools", "cars", "nikki-export", "out")
    for n in ("NikkiExport.dll", "NikkiExport.runtimeconfig.json"):
        _put(os.path.join(nikki, n), "tools/nikki-export/" + n)
    # settings and the installer's data
    _put(os.path.join(HERE, "installer", "settings.json"), "settings/settings.json")
    for n in ("downloads.json",):
        _put(os.path.join(HERE, n), "data/" + n)
    for n in ("originals.json", "exe-sites.json"):
        _put(os.path.join(HERE, "installer", n), "data/" + n)


def licences():
    d = os.path.join(OUT, "licences")
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    copies = {"DXVK (zlib).txt": os.path.join(WORK_LICENCES, "dxvk-LICENSE"),
              "Ultimate ASI Loader (MIT).txt": os.path.join(WORK_LICENCES, "ual-license"),
              "Widescreen Fixes Pack (MIT).txt": os.path.join(RESEARCH, "wfp", "license"),
              "TexWizard (GPL-3.0).txt": os.path.join(RESEARCH, "texwizard", "LICENSE"),
              "NFSHDReflections (GPL-3.0).txt": os.path.join(RESEARCH, "NFSHDReflections", "LICENSE"),
              "NFSMWFEShadows (GPL-3.0).txt": os.path.join(RESEARCH, "NFSMWFEShadows", "LICENSE")}
    for n, src in copies.items():
        shutil.copyfile(src, os.path.join(d, n))
    pkg = os.path.join(HERE, "package")
    for n in os.listdir(pkg):
        shutil.copyfile(os.path.join(pkg, n), os.path.join(OUT, n))


def manifest():
    entries = []
    for dp, _, names in os.walk(OUT):
        for n in sorted(names):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, OUT).replace(os.sep, "/")
            if rel == "payload-manifest.json":
                continue
            entries.append({"path": rel, "size": os.path.getsize(p), "sha256": sha(p)})
    json.dump({"version": VERSION, "files": entries}, open(os.path.join(OUT, "payload-manifest.json"), "w"), indent=1)
    return entries


def build_exe():
    subprocess.run([sys.executable, os.path.join(HERE, "build_exe.py")], check=True)
    shutil.copyfile(os.path.join(HERE, "build", "exe", "FTownEditionInstaller.exe"), os.path.join(OUT, "FTownEditionInstaller.exe"))


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    payload()
    licences()
    if "--no-exe" not in argv:
        build_exe()
    hits = forbidden_hits(OUT)
    if hits:
        raise SystemExit("forbidden content in the package:\n  " + "\n  ".join(hits))
    entries = manifest()
    z = os.path.join(DIST, "NFSMW-FTown-Edition-%s.zip" % VERSION)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for e in entries + [{"path": "payload-manifest.json"}]:
            f.write(os.path.join(OUT, *e["path"].split("/")), NAME + "/" + e["path"])
    print("%d files, %.1f MB in %s; zip %s (%.1f MB)" % (len(entries), sum(e["size"] for e in entries) / 1e6, OUT, z,
                                                      os.path.getsize(z) / 1e6))


if __name__ == "__main__":
    main(sys.argv[1:])
