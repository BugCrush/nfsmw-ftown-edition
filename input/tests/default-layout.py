"""Tests InputBridge's [Controls] DefaultLayout on the stand-in default-layout.cpp (see its header).

    python input/tests/default-layout.py [variant ...]

Builds InputBridge.asi (input/src/build.bat) and the stand-in with Zig (.tools/zig/zig.exe), runs each variant in its
own folder under input/tests/out-default-layout/, and checks the bindings table the stand-in prints against
tools/mw-controls.py's LAYOUT (the layout written into existing profiles), and InputBridge.log.
"""
import importlib.util
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
OUT = os.path.join(HERE, "out-default-layout")

spec = importlib.util.spec_from_file_location("mw_controls", os.path.join(ROOT, "tools", "mw-controls.py"))
mwc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mwc)

# The game's generic defaults (slot2 type, index) for the 19 actions, as the stand-in writes them.
GENERIC = [(2, 0), (2, 2), (4, 0), (5, 0), (2, 1), (2, 3), (2, 6), (0, 0), (0, 0), (2, 5), (3, 0), (3, 2), (3, 3), (3, 1),
           (0, 0), (0, 0), (2, 4), (0, 0), (2, 7)]
MENU = {19: (3, 0, 3, 4, 0, 0), 20: (3, 0, 1, 5, 0, 0), 21: (3, 0, 0, 4, 0, 1), 22: (3, 0, 2, 5, 0, 1), 23: (0,) * 6}

# variant: (ini value, stand-in arguments, ours expected, log text expected)
VARIANTS = {
    "xbox": (1, ["xbox"], True, ["Default layout ([Controls] DefaultLayout): installed at 0x63CD80",
                                 "Default layout (call 1): controller \"Controller (Controller(XBOX 360 For Windows))\": our layout written",
                                 "Default layout (call 2)"]),
    "off": (0, ["xbox"], False, ["Default layout ([Controls] DefaultLayout): off"]),
    "wheel": (1, ["wheel"], False, ["installed at 0x63CD80", "is not one we make virtual; the game's defaults kept"]),
    "nopad": (1, ["nopad"], False, ["installed at 0x63CD80", "no controller; the game's defaults kept"]),
    "wrongbytes": (1, ["xbox", "wrongbytes"], False, ["refused: the bytes at 0x63CD80 are not the game's own"]),
    "wrongtable": (1, ["xbox", "wrongtable"], False, ["refused: the bindings table is not where speed.exe v1.3 keeps it"]),
}


def check(name, stdout, log, ours, texts):
    fails = []
    recs = {}
    calls = None
    for line in stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["CALLS"]:
            calls = int(parts[1])
        elif parts[:1] == ["REC"]:
            recs[int(parts[1])] = [int(x) for x in parts[2:]]
    if calls != 2:
        fails.append("the game's function ran %r times, expected 2 (our hook must call it each time)" % calls)
    if sorted(recs) != list(range(24)):
        return fails + ["records printed: %s" % sorted(recs)]
    for i in range(19):
        r = recs[i]
        if r[1:3] != [1, 0x10 + i]:
            fails.append("record %d: keyboard slot changed: %s" % (i, r[1:4]))
        if ours:
            kind, index = mwc.LAYOUT[mwc.ACTIONS[i]]
            want = [kind, 0, index, 0, 0, 0]
        else:
            want = [GENERIC[i][0], 0, GENERIC[i][1], 0, 0, 0]
            if i == 2:
                want[3], want[5] = 3, 3  # the stand-in's second-controller binding, kept when we stay out
        if r[7:13] != want:
            fails.append("record %d (%s): controller slots %s, expected %s" % (i, mwc.ACTIONS[i], r[7:13], want))
    for i, want in MENU.items():
        if tuple(recs[i][7:13]) != want:
            fails.append("record %d (menu): %s, expected the game's %s" % (i, recs[i][7:13], list(want)))
    for t in texts:
        if t not in log:
            fails.append("log lacks %r" % t)
    return fails


def main():
    subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "input", "src", "build.bat"), ZIG])
    os.makedirs(OUT, exist_ok=True)
    exe = os.path.join(OUT, "default-layout.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", "default-layout.cpp", "-o", exe, "-w",
                           "-Wl,--image-base=0x400000", "-Wl,--no-dynamicbase"], cwd=HERE)
    failed = 0
    for name in sys.argv[1:] or VARIANTS:
        value, args, ours, texts = VARIANTS[name]
        d = os.path.join(OUT, name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        shutil.copy(exe, d)
        shutil.copy(os.path.join(ROOT, "input", "src", "InputBridge.asi"), d)
        with open(os.path.join(d, "InputBridge.ini"), "wb") as f:
            f.write(("[Controls]\r\nDefaultLayout = %d\r\n[Telemetry]\r\nLog = 0\r\nOverlay = 0\r\n" % value).encode("ascii"))
        r = subprocess.run([os.path.join(d, "default-layout.exe")] + args, cwd=d, capture_output=True, text=True, timeout=60)
        logpath = os.path.join(d, "InputBridge.log")
        log = open(logpath, encoding="latin-1").read() if os.path.isfile(logpath) else ""
        fails = check(name, r.stdout, log, ours, texts) if r.returncode == 0 else \
            ["stand-in exit %d: %s" % (r.returncode, (r.stdout + r.stderr)[-300:])]
        print("%s: %s" % (name, "PASS" if not fails else "FAIL\n  " + "\n  ".join(fails[:10])))
        failed += bool(fails)
    print("%d failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
