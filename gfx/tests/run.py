"""Builds a GfxProbe stand-in and runs it in its own folder, next to the built GfxProbe.asi.

    python gfx/tests/run.py sampler [--dxvk]
    python gfx/tests/run.py frame   [--dxvk | --off] [--notrace]   (--off --notrace: everything off, as installed)
    python gfx/tests/run.py bench   [--dxvk] [--off] [--asi <other GfxProbe.asi>]   (prints a frame rate)
    python gfx/tests/run.py frame --dxvk --tint    (also builds and loads gfx/spike/TintProof.asi)

--dxvk copies the game's 32-bit DXVK d3d9.dll beside the stand-in. The folder is
gfx/tests/out/<name>-<plain|dxvk>/ (git-ignored); its path is printed last.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
GAME = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition")

SAMPLER_INI = """[Capture]
Dir = .
Label = test
"""

FRAME_INI = """[Capture]
Dir = .
Label = test
[Log]
ReportSeconds = 4
[Parts]
Filtering = 1
FrameMap = 1
Effects = 1
EffectValues = 1
Resources = 1
Shaders = 1
Timing = 1
Shots = 1
Dissect = 1
Watch = 1
Panel = 1
[Timing]
EveryNFrames = 1
[Panel]
OnlyInFront = 0
Snapshot = 1
[Shots]
Interval = 2
Max = 40
[Dissect]
At = 3
[Trace]
TargetWidth = 256
Max = 4
"""

TESTS = {
    "sampler": {"src": "d3d9-sampler.cpp", "rc": None, "libs": ["-ld3d9", "-luser32"], "ini": SAMPLER_INI},
    # Not a pass/fail test: prints the frame rate of a race-sized frame. Compare all parts on, --off, and
    # --asi <another GfxProbe.asi> (for example the first GfxProbe kept in telemetry/).
    "bench": {"src": "d3d9-bench.cpp", "rc": "d3d9-frame.rc", "libs": ["-ld3d9", "-ld3dx9_26", "-luser32"],
              "ini": FRAME_INI},
    "frame": {"src": "d3d9-frame.cpp", "rc": "d3d9-frame.rc", "libs": ["-ld3d9", "-ld3dx9_26", "-luser32"],
              "ini": FRAME_INI},
}


def main():
    name = sys.argv[1]
    dxvk = "--dxvk" in sys.argv
    off = "--off" in sys.argv  # every [Parts] switch at 0
    test = TESTS[name]
    asi = sys.argv[sys.argv.index("--asi") + 1] if "--asi" in sys.argv else os.path.join(ROOT, "gfx", "src", "GfxProbe.asi")
    tint = "--tint" in sys.argv  # the throwaway tint proof as a second plugin beside GfxProbe
    notrace = "--notrace" in sys.argv  # [Trace] TargetWidth = 0, as installed in the game
    kind = ("off" if off else "tint" if tint else "dxvk" if dxvk else "plain") + ("-notrace" if notrace else "")
    if name == "bench":
        kind = ("dxvk" if dxvk else "plain") + ("-off" if off else "") + ("-otherasi" if "--asi" in sys.argv else "")
    out = os.path.join(HERE, "out", "%s-%s" % (name, kind))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    exe = os.path.join(out, "d3d9-%s.exe" % name)
    objects = [test["src"]]
    if test["rc"]:
        res = os.path.join(out, "stand-in.res")
        subprocess.check_call([ZIG, "rc", test["rc"], res], cwd=HERE)
        objects.append(res)
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O2"] + objects + test["libs"]
                          + ["-o", exe, "-w"], cwd=HERE)
    shutil.copy(asi, os.path.join(out, "GfxProbe.asi"))
    if dxvk:
        shutil.copy(os.path.join(GAME, "d3d9.dll"), out)
    if tint:
        subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-shared", "-O2", "TintProof.cpp", "-ld3d9",
                               "-luser32", "-o", os.path.join(out, "TintProof.asi"), "-w"], cwd=os.path.join(ROOT, "gfx", "spike"))
        with open(os.path.join(out, "TintProof.ini"), "wb") as f:
            f.write(b"[Tint]\r\nEnabled = 1\r\nColour = 0x40FF00FF\r\nAfter = IDI_TESTA_FX\r\nBefore = IDI_TESTB_FX\r\n")
    with open(os.path.join(out, "GfxProbe.ini"), "wb") as f:
        ini = test["ini"].replace("= 1", "= 0") if off else test["ini"]
        if notrace:
            ini = ini.replace("TargetWidth = 256", "TargetWidth = 0")
        f.write(ini.replace("\n", "\r\n").encode("ascii"))
    result = subprocess.run([exe], cwd=out, timeout=180, capture_output=True, text=True)
    print(result.stdout)
    print(out)
    sys.exit(result.returncode)


main()
