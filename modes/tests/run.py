"""Builds DisplayModes.asi, the stand-in Widescreen Fix and the stand-in, runs every variant and checks it.

    python modes/tests/run.py [--native] [variant ...]

Each variant runs in modes/tests/out/<variant>[-native]/ (git-ignored). Under DXVK the game's d3d9.dll is copied in
(read from the game folder, never changed there); with --native none is, so Windows' own Direct3D answers.
The stand-in's window covers the screen for about a second per variant. Exit code 1 if any check fails.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
GAME = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition")
BUILD = os.path.join(HERE, "out", "build")
EXTRA = ["2240x1260", "2560x1440"]

# variant: (load order, chosen size, .ini text or None for no .ini)
VARIANTS = {
    "none": ("none", "2560x1440", None),          # what happens without the plugin
    "first": ("first", "2560x1440", None),        # the shipped case: defaults, loaded before the Fix
    "first-2240": ("first", "2240x1260", None),
    "first-1920": ("first", "1920x1080", None),   # a size that fits: the window is left as the Fix places it
    "after": ("after", "2560x1440", None),        # loaded after the Fix: too late for the list, says so
    "nofit": ("first", "2560x1440", "[Window]\r\nFitToScreen = 0\r\n"),
    "custom": ("first", "2560x1440", "[Modes]\r\n; one bad entry, one Windows already has, one new\r\n"
               "Add = 3200x1800, banana, 1920x1080\r\n"),
    # our own shrink at Present (DXVK only; with --native it must stay off and say so)
    "reset": ("first", "2560x1440", None),        # a device Reset in the middle: our copy is released first
    "ms3": ("first", "2560x1440", None),          # the game's anti-aliased back buffer (NONMASKABLE, quality 3)
    "noarea": ("first", "2560x1440", "[Shrink]\r\nArea = 0\r\n"),
}
ARGS = {"reset": ["reset"], "ms3": ["ms=3"]}


def build():
    os.makedirs(BUILD, exist_ok=True)
    if "--keep-plugin" not in sys.argv:  # --keep-plugin: test whatever DisplayModes.asi is there (e.g. a stub)
        subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "modes", "src", "build.bat"), ZIG])
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-shared", "-O1", os.path.join(HERE, "mockfix.cpp"),
                           "-luser32", "-o", os.path.join(BUILD, "NFSMostWanted.WidescreenFix.asi"), "-w"])
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", os.path.join(HERE, "standin.cpp"),
                           "-ld3d9", "-luser32", "-lgdi32", "-o", os.path.join(BUILD, "standin.exe"), "-w"])


def prepare(variant, native):
    out = os.path.join(HERE, "out", variant + ("-native" if native else ""))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for f in ("standin.exe", "NFSMostWanted.WidescreenFix.asi"):
        shutil.copy(os.path.join(BUILD, f), out)
    shutil.copy(os.path.join(ROOT, "modes", "src", "DisplayModes.asi"), out)
    if not native:
        shutil.copy(os.path.join(GAME, "d3d9.dll"), out)
    ini = VARIANTS[variant][2] if variant in VARIANTS else None
    if ini:
        with open(os.path.join(out, "DisplayModes.ini"), "wb") as f:
            f.write(ini.encode())
    return out


def run(variant, native, extra_args=()):
    order, size, _ = VARIANTS.get(variant, ("first", "2560x1440", None))
    out = prepare(variant, native)
    args = ["order=" + order, "size=" + size] + ARGS.get(variant, []) + list(extra_args)
    r = subprocess.run([os.path.join(out, "standin.exe")] + args, cwd=out,
                       capture_output=True, text=True, timeout=60)
    log_path = os.path.join(out, "DisplayModes.log")
    log = open(log_path).read() if os.path.exists(log_path) else ""
    return r, log


def field(stdout, name):
    for line in stdout.splitlines():
        if line.startswith(name + " ") or line == name:
            return line.split()[1:]
    return None


def sizes(listing):
    return [s.split("@")[0] for s in listing[1:]]


def check(variant, native, r, log, base, base_own):
    fails = []

    def expect(ok, what):
        if not ok:
            fails.append(what)

    out = r.stdout
    order, size, ini = VARIANTS[variant]
    expect(r.returncode == 0, "exit code 0, got %d" % r.returncode)
    fix, own, cur = field(out, "FIXLIST"), field(out, "OWNLIST"), field(out, "CURRENT")
    win = field(out, "WINDOW")
    if not (fix and own and cur and win):
        return fails + ["output incomplete: %s" % out[-400:]]
    real = sizes(base) if base else None
    got = sizes(fix)
    want_extra = EXTRA if order == "first" else []
    if variant == "custom":
        want_extra = ["3200x1800"]
    if real is not None:
        expect(got == real + want_extra, "the Fix's list is Windows' (%d) then %s; got the last ones %s"
               % (len(real), want_extra, got[-4:]))
    # Windows' own count can differ between runs (384 once, 128 otherwise, without any plugin: --native, 2026-10-22),
    # so the check is that nothing larger than Windows' largest mode reaches the stand-in's own code.
    expect(own[1:] == base_own[1:], "the stand-in's own enumeration is Windows' %s, got %s" % (base_own, own))
    expect(cur == ["1920", "1080"] or real is None or cur == real[-1].split("x"),
           "the Fix's current-settings read is Windows' (%s)" % cur)
    if want_extra:
        refresh = [s.split("@")[1] for s in fix[1:] if s.split("@")[0] in want_extra]
        top = [s.split("@")[1] for s in fix[1:] if s.split("@")[0] == "1920x1080"]
        expect(refresh and top and set(refresh) == set(top), "extra modes carry the desktop's refresh %s, got %s" % (top, refresh))
        expect(re.search(r"modes: asked by NFSMostWanted\.WidescreenFix\.asi: Windows lists \d+ \(largest 1920x1080\); "
                         r"told \d+, added: " + " ".join(want_extra), log), "the log line names what was asked and told")
    if variant == "after":
        expect("loaded before this plugin" in log, "the log says the plugin loaded too late")
    if variant == "custom":
        expect('ignored "banana' in log, "the bad entry is named in the log")
    w, h = map(int, size.split("x"))
    x, y, ww, wh, _, cw, ch = win[0], win[1], win[2], win[3], win[4], win[5], win[6]
    fitted = order != "none" and variant != "nofit"
    if fitted:
        expect([x, y, ww, wh, cw, ch] == ["0", "0", "1920", "1080", "1920", "1080"],
               "the window fills the screen and no more: %s" % win)
        if w > 1920:
            expect("window: the Fix asked for %dx%d" % (w, h) in log, "the log names the fitted window")
        else:
            expect("window: the Fix asked for" not in log, "a size that fits is left alone")
    else:
        # Without the fit the window is whatever Windows makes of the Fix's request: recorded, not judged.
        print("    window without the fit: %s" % " ".join(win))
    expect(field(out, "DEVICE") == ["0x00000000"], "device created at %s: %s" % (size, field(out, "DEVICE")))
    expect(field(out, "BACKBUFFER") == [str(w), str(h)], "back buffer is the chosen size: %s" % field(out, "BACKBUFFER"))
    if variant == "reset":
        expect(field(out, "RESET") == ["0x00000000"], "the Reset succeeded: %s" % field(out, "RESET"))
    shrinks = w > 1920 and order != "none" and variant != "noarea"
    if native and order != "none" and variant != "noarea":
        expect("Windows' own Direct3D (not DXVK)" in log and "area average" not in log, "our shrink is off on Windows' Direct3D")
    elif shrinks and variant != "nofit":
        kind = "multisampled" if variant == "ms3" else "single sample"
        expect("shrink: %dx%d back buffer (%s) -> 1920x1080 window, area average" % (w, h, kind) in log,
               "the log says our shrink took over")
        expect("shrink: shader did not compile" not in log, "the shader compiled")
    else:
        expect("area average" not in log, "no shrink of ours")
    if variant == "noarea":
        expect("Area = 0" in log, "the log says the shrink is switched off")
    pres = field(out, "PRESENT")
    expect(pres is not None and pres[1] == "0", "every present succeeded: %s" % pres)
    d3d = (field(out, "D3D9") or ["?"])[0].lower()
    expect(("system32" in d3d or "syswow64" in d3d) if native else d3d.startswith(os.path.join(HERE, "out").lower()),
           "the right d3d9.dll: %s" % d3d)
    return fails


def main():
    native = "--native" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(VARIANTS)
    build()
    r, _ = run("none", native)
    base, base_own = field(r.stdout, "FIXLIST"), field(r.stdout, "OWNLIST")
    failed = 0
    for v in names:
        r, log = run(v, native)
        fails = check(v, native, r, log, base, base_own)
        print("%-12s %s" % (v + ("-native" if native else ""), "ok" if not fails else "FAIL"))
        for f in fails:
            print("    " + f)
        failed += bool(fails)
    print("%d failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
