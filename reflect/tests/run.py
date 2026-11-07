"""Builds ReflectRate.asi and its stand-in, runs every variant and checks it.

    python reflect/tests/run.py [variant ...]

The stand-in (standin.cpp) puts a loop shaped like the game's face loop at the game's addresses and prints, per
frame, which of the six faces were drawn (MASKS lines: bit 0 = front, 1 right, 2 back, 3 left, 4 up, 5 down).
Each variant runs in reflect/tests/out/<variant>/ (git-ignored). Exit code 1 if any check fails.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
ALL = 0x3F

# variant: (FacesPerFrame, Pattern, stand-in arguments)
VARIANTS = {
    "even3": ("3", "even", []),
    "alternate": ("3", "alternate", []),
    "balanced": ("3", "balanced", []),
    "balancedoff": ("3", "balanced", ["leftoff"]),
    # no Pattern line in the .ini: the built-in default must be the shipped choice, balanced
    "nopattern": ("3", None, []),
    "six": ("6", "even", []),
    "two": ("2", "even", []),
    "wrongbytes": ("3", "even", ["wrongbytes"]),
    "leftoff": ("3", "even", ["leftoff"]),
    # [Shadow] Every = 2: the shadow map drawn every other frame (both after a start or a gap); "shadowwrong": the call
    # at 0x6DEC72 goes elsewhere, so the plugin must leave it alone.
    "shadow2": ("3", "balanced", []),
    "shadowwrong": ("3", "balanced", ["shadowwrong"]),
    "shadownoaccess": ("3", "balanced", ["shadownoaccess"]),
}
SHADOW_EVERY = {"shadow2": "2", "shadowwrong": "2", "shadownoaccess": "2"}


def shadow_frames(stdout, batch):
    for line in stdout.splitlines():
        if line.startswith("SHADOWS batch=%d " % batch):
            return line.split()[2]
    return ""


def check_shadow(variant, stdout, log, expect):
    runs = [shadow_frames(stdout, 1), shadow_frames(stdout, 2)]
    expect([len(r) for r in runs] == [100, 10], "the shadow map's frames were recorded (100 and 10), got %s" % [len(r) for r in runs])
    if variant != "shadow2":
        expect(all(set(r) == {"1"} for r in runs), "the shadow map is drawn every frame, got %s" % runs)
        expect("shadow call patched=no" in stdout, "the shadow call is left as it is")
        if variant == "shadowwrong":
            expect("shadow map: call at 0x006DEC72 is not the game's" in log, "the log says why it was left alone")
        if variant == "shadownoaccess":
            expect("shadow map: call at 0x006DEC72 cannot be read" in log, "the log says the call cannot be read")
        return
    expect("shadow call patched=yes" in stdout, "the shadow call goes through the plugin")
    expect("shadow map: drawn every 2nd frame (call at 0x006DEC72 rerouted)" in log, "the log names it")
    for name, r in (("first batch", runs[0]), ("after the gap", runs[1])):
        expect(r[:2] == "11", "%s: drawn in the first two frames, got %s" % (name, r[:2]))
        steady = r[2:]
        expect("00" not in steady and "11" not in steady, "%s: then every other frame, got %s" % (name, steady))
    expect("shadow drawn=" in log, "the once-a-second line counts the shadow map too")


def masks(stdout, batch):
    for line in stdout.splitlines():
        if line.startswith("MASKS batch=%d" % batch):
            return [int(m, 16) for m in line.split()[2:]]
    return []


def bits(m):
    return bin(m).count("1")


def check(variant, stdout, log):
    fails = []

    def expect(ok, what):
        if not ok:
            fails.append(what)

    per, pattern, args = VARIANTS[variant]
    check_shadow(variant, stdout, log, expect)
    pattern = pattern or "balanced"  # the built-in default
    first, second = masks(stdout, 1), masks(stdout, 2)
    expect(len(first) == 100 and len(second) == 10, "100 and 10 frames ran, got %d and %d" % (len(first), len(second)))
    if not first or not second:
        return fails
    if variant in ("six", "wrongbytes", "shadownoaccess"):
        # shadownoaccess: the whole 4 KB page (the face loop's too) was unreadable while the plugin loaded.
        expect(all(m == ALL for m in first + second), "every face every frame, got %s" % sorted(set(first + second)))
        expect("patched=no" in stdout, "the game's bytes are left alone")
        why = {"wrongbytes": "refused", "six": "off", "shadownoaccess": "cannot be read; nothing changed"}[variant]
        expect(why in log, "the log says why: %s" % log.strip().splitlines()[-1:])
        return fails
    expect("patched=yes" in stdout, "the patch is in")
    expect("jump lands in the plugin" in stdout, "the jump lands inside ReflectRate.asi (so PatchMap names it as ours)")
    expect("patched at 0x006DE680" in log, "the log names the patch")
    off = 1 << 3 if "leftoff" in args else 0
    want = ALL & ~off
    for name, run in (("first batch", first), ("after the gap", second)):
        # After a start or a gap every face is drawn twice in a row, so none shows a stale or empty picture.
        expect(run[0] == want and run[1] == want, "%s: the first two frames draw every face, got %02x %02x" % (name, run[0], run[1]))
        if pattern == "balanced":
            # Back and left one frame, front, right, up and down the next: equal processor time by the measured
            # per-face cost (race 2: 1.52 against 1.59 ms); each face at most one frame old.
            steady = run[2:]
            expect(set(steady) <= {0b001100 & want, 0b110011 & want}, "%s: back and left, then the other four, got %s"
                   % (name, sorted("%02x" % m for m in set(steady))))
            expect(all(steady[i] != steady[i - 1] for i in range(1, len(steady))), "%s: the two groups take turns" % name)
            continue
        window = 2 if pattern == "alternate" else 6 // int(per)  # a face is never older than this many frames
        for i in range(2, len(run)):
            expect(run[i] & off == 0, "%s frame %d: a switched-off face is never drawn" % (name, i))
            seen = 0
            for m in run[max(0, i - window + 1):i + 1]:
                seen |= m
            expect(seen & want == want, "%s frames to %d: every face drawn at least once in %d frames, got %02x" % (name, i, window, seen))
        steady = run[2:]
        n = 4 if pattern == "alternate" else int(per)
        allowed = (n, n - 1) if off else (n,)  # with a face switched off, the frames it was due in draw one fewer
        expect(all(bits(m) in allowed for m in steady), "%s: %d faces a frame, got %s" % (name, n, sorted(set(bits(m) for m in steady))))
        if pattern == "alternate":
            expect(all(m & 0b101 == 0b101 for m in steady), "%s: front and back every frame" % name)
    expect("faces drawn=" in log and "skipped=" in log, "the once-a-second line is written")
    return fails


def main():
    out_root = os.path.join(HERE, "out")
    subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "reflect", "src", "build.bat"), ZIG])
    exe = os.path.join(out_root, "standin.exe")
    os.makedirs(out_root, exist_ok=True)
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", "standin.cpp", "-o", exe, "-w",
                           "-Wl,--image-base=0x400000", "-Wl,--no-dynamicbase"], cwd=HERE)
    failed = 0
    for variant in sys.argv[1:] or VARIANTS:
        per, pattern, args = VARIANTS[variant]
        out = os.path.join(out_root, variant)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        shutil.copy(exe, out)
        shutil.copy(os.path.join(ROOT, "reflect", "src", "ReflectRate.asi"), out)
        with open(os.path.join(out, "ReflectRate.ini"), "wb") as f:
            text = "[Reflection]\r\nFacesPerFrame = %s\r\n" % per + ("Pattern = %s\r\n" % pattern if pattern else "")
            if variant in SHADOW_EVERY:
                text += "[Shadow]\r\nEvery = %s\r\n" % SHADOW_EVERY[variant]
            f.write(text.encode("ascii"))
        result = subprocess.run([os.path.join(out, "standin.exe")] + args, cwd=out, capture_output=True, text=True, timeout=60)
        logpath = os.path.join(out, "ReflectRate.log")
        log = open(logpath).read() if os.path.isfile(logpath) else ""
        fails = check(variant, result.stdout, log) if result.returncode == 0 else ["stand-in exit %d: %s" % (result.returncode, result.stdout[-300:])]
        print("%s: %s" % (variant, "PASS" if not fails else "FAIL\n  " + "\n  ".join(fails[:8])))
        failed += bool(fails)
    print("%d failed" % failed)
    sys.exit(1 if failed else 0)


main()
