"""Builds CarStable.asi and its stand-in, runs every variant and checks it.

    python cars/tests/run.py [variant ...]

Each variant runs in cars/tests/out/<variant>/ (git-ignored) with its own CarStable.ini. Exit code 1 if any check
fails. The stand-in (standin.cpp) prints LOAD, STABLE, CURRENT, QR5 and FREECUSTOM lines.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
USER_FP = "0x0B28303D"
STOCK = "10001"

# variant: (ini Enabled, stand-in arguments, checks)
VARIANTS = {
    # the save matches the game: loads, nothing changes
    "same": ("1", ["defaults=AB", "loaded=AB", "fp=current"],
             {"LOAD": "ok", "STABLE": "0:A:%s 1:B:%s" % (STOCK, STOCK), "log_has": ["equal"],
              "log_not": ["added=", "WRONGBYTES"]}),
    # a car was added to the game; the save's fingerprint is the user's known one: loads, C added
    "known": ("1", ["defaults=ABC", "loaded=AB", "fp=" + USER_FP],
              {"LOAD": "ok", "STABLE": "0:A:%s 1:B:%s 2:C:%s" % (STOCK, STOCK, STOCK),
               "log_has": ["accepted", "added=1 dropped=0"]}),
    # a fingerprint nobody knows: refused as the game refuses it, nothing loaded
    "unknown": ("1", ["defaults=ABC", "loaded=AB", "fp=0x12345678"],
                {"LOAD": "refused", "STABLE": "", "log_has": ["refused"], "log_not": ["added="]}),
    # car B was removed from the game; the save holds stock B and a bought B (current car, Quick Race 5)
    "removed": ("1", ["defaults=A", "loaded=AB", "owned=B", "fp=" + USER_FP],
                {"LOAD": "ok", "STABLE": "0:A:%s" % STOCK, "CURRENT": "0", "QR5": "0", "FREECUSTOM": "75",
                 "log_has": ["added=0 dropped=2", "current car reset", "quick race reset=1"]}),
    # the compare's bytes are not the game's: nothing patched, the game refuses the known save as it would
    "wrongbytes": ("1", ["defaults=ABC", "loaded=AB", "fp=" + USER_FP, "wrongbytes"],
                   {"LOAD": "refused", "log_has": ["WRONGBYTES 0x005ACBFA"], "log_not": ["patched 0x"]}),
    # Enabled = 0: like no plugin
    "disabled": ("0", ["defaults=ABC", "loaded=AB", "fp=" + USER_FP],
                 {"LOAD": "refused", "log_has": ["disabled"], "log_not": ["patched 0x"]}),
    # review 2: a save whose cars are mostly unknown to the game now (a broken database): more drops than MaxDrop (3)
    # -> the load is refused, nothing dropped, the cars named
    "dropguard": ("1", ["defaults=A", "loaded=ABCDE", "fp=" + USER_FP],
                  {"LOAD": "refused", "log_has": ["DROP-GUARD", "0x00000045"], "log_not": ["stable: added="]}),
    # review 3: the stable is full: the car that did not fit is named and kept pending ...
    "full": ("1", ["defaults=ABC", "loaded=AB", "fp=" + USER_FP, "fill"],
             {"LOAD": "ok", "log_has": ["not added (stable full)=1", "not added: 0x00000043", "pending"],
              "file_has": ("CarStable.pending", "0x00000043")}),
    # ... and a later load retries it although the fingerprint is now equal
    "pending": ("1", ["defaults=ABC", "loaded=AB", "fp=current"],
                {"LOAD": "ok", "STABLE": "0:A:%s 1:B:%s 2:C:%s" % (STOCK, STOCK, STOCK),
                 "log_has": ["pending", "added=1"], "file_absent": "CarStable.pending",
                 "prefile": ("CarStable.pending", "0x00000043\n")}),
    # review 5: a plugin loaded later overwrites one of our sites: said at the first fingerprint (after all plugins)
    "overwritten": ("1", ["defaults=AB", "loaded=AB", "fp=current", "overwrite"],
                    {"LOAD": "ok", "log_has": ["OVERWRITTEN 0x005ACD5D"]}),
}


def lines(stdout):
    out = {}
    for line in stdout.splitlines():
        key, _, rest = line.partition(" ")
        out[key] = rest.strip()
    return out


def check(variant, stdout, log, fingerprints):
    fails = []
    got = lines(stdout)
    want = VARIANTS[variant][2]
    for key in ("LOAD", "STABLE", "CURRENT", "QR5", "FREECUSTOM"):
        if key in want and got.get(key, "") != want[key]:
            fails.append("%s: got %r, want %r" % (key, got.get(key), want[key]))
    for text in want.get("log_has", []):
        if text not in log:
            fails.append("log lacks %r" % text)
    for text in want.get("log_not", []):
        if text in log:
            fails.append("log has %r" % text)
    if VARIANTS[variant][0] == "1" and variant != "wrongbytes":
        fp = got.get("FINGERPRINT", "")
        if fp.upper().replace("0X", "0x") not in fingerprints.upper().replace("0X", "0x"):
            fails.append("CarStable.fingerprints lacks the current fingerprint %s" % fp)
    return fails


def main():
    names = sys.argv[1:] or list(VARIANTS)
    subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "cars", "src", "build.bat"), ZIG])
    exe = os.path.join(HERE, "standin.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", "standin.cpp", "-o", exe, "-w",
                           "-Wl,--image-base=0x400000", "-Wl,--no-dynamicbase"], cwd=HERE)
    failed = 0
    for name in names:
        out = os.path.join(HERE, "out", name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        shutil.copy(exe, out)
        shutil.copy(os.path.join(ROOT, "cars", "src", "CarStable.asi"), out)
        with open(os.path.join(out, "CarStable.ini"), "wb") as f:
            f.write(("[CarStable]\r\nEnabled = %s\r\nKnown = %s\r\n" % (VARIANTS[name][0], USER_FP)).encode())
        pre = VARIANTS[name][2].get("prefile")
        if pre:
            with open(os.path.join(out, pre[0]), "w") as f:
                f.write(pre[1])
        result = subprocess.run([os.path.join(out, "standin.exe")] + VARIANTS[name][1], cwd=out,
                                capture_output=True, text=True, timeout=60)

        def read(fname):
            p = os.path.join(out, fname)
            return open(p, encoding="latin-1").read() if os.path.exists(p) else ""

        log, fps = read("CarStable.log"), read("CarStable.fingerprints")
        dump = os.path.join(out, "CarStable.defaults.bin")
        dump_size = os.path.getsize(dump) if os.path.exists(dump) else -1
        fails = check(name, result.stdout, log, fps) if result.returncode == 0 else \
            ["stand-in exit %d: %s" % (result.returncode, result.stdout[-300:])]
        want = VARIANTS[name][2]
        if "file_has" in want and want["file_has"][1] not in read(want["file_has"][0]):
            fails.append("%s lacks %r" % want["file_has"])
        if "file_absent" in want and os.path.exists(os.path.join(out, want["file_absent"])):
            fails.append("%s still exists" % want["file_absent"])
        if VARIANTS[name][0] == "1" and name != "wrongbytes" and dump_size != 0x8CC8:
            fails.append("CarStable.defaults.bin is %d bytes, want 0x8CC8 (the default stable)" % dump_size)
        print("%-10s %s" % (name, "PASS" if not fails else "FAIL"))
        for f in fails:
            print("    " + f)
        failed += bool(fails)
    print("%d/%d variants pass" % (len(names) - failed, len(names)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
