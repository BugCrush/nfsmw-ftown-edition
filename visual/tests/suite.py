"""Runs every VisualBridge stand-in variant and its check, on DXVK and (with --native) on Windows' own Direct3D.

    python visual/tests/suite.py [--native] [--only <word>]

Reference variants (none, hostile-off, scene-off, ...) run before the variants compared against them.
Prints one PASS/FAIL line per variant and a total; exits 1 if any failed. Full output: visual/tests/out/suite-*.txt.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["none", "off", "identity", "split-identity", "broken", "exposure", "split-exposure", "bloom", "both",
         "hostile-off", "hostile-identity", "hostile-split", "gap-exposure",
         "scene-off", "scene-identity", "scene-depth", "scene-ao", "scene-ao-full", "scene-split-ao", "scene-toggle", "scene-ao-showcase",
         "scene-ao-showcase-notoggle", "scene-ao-showcase-fullfail", "scene-reload-ao-showcase", "scene-toggle-huge", "scene-toggle-wrap",
         "scene-toggle-only",
         "scene-nointz-off", "scene-nointz-ao", "scene-hostile-off", "scene-hostile-ao", "scene-intz2-ao",
         "scene-aa", "scene-split-aa", "scene-nopass-off", "scene-aa-nopass", "scene-hostile-aa", "scene-ao-aa",
         "scene-toggle-only-aa",
         "scene-haze", "scene-split-haze", "scene-ao-haze", "scene-nointz-haze", "scene-hostile-haze", "scene-toggle-only-haze",
         "scene-sun-off", "scene-sun-shafts", "scene-sun-split-shafts", "scene-sunbehind-shafts", "scene-sun-noinfo-shafts", "scene-sunside-shafts",
         "scene-sun-showsun", "scene-sunleft-split-showsun", "scene-sun-wrongfov-showsun", "scene-sun-noplat-showsun",
         "scene-sun-badplat-showsun", "scene-shadows-unlock", "scene-shadows-off", "scene-shadowswrong-unlock", "scene-shadowsro-unlock", "scene-sun-ao-fov60","scene-sun-ao-wrongfov", "scene-sun-badplat-ao", "scene-sun-ao-wrongnear", "scene-sun-ao-wrongnear-off", "scene-sun-badplat-ao-fromgame", "scene-sun-hostile-off", "scene-sun-hostile-shafts",
         "scene-wet-disabled", "scene-wet-aaonly", "scene-wet", "scene-wet-noaa", "scene-wet-blur", "scene-wet-toggle", "scene-wet-off", "scene-wet-badmatrix",
         "scene-wet-edge-ref", "scene-wet-edge", "scene-split-wet", "scene-hostile-wet"]


def main():
    extra = ["--native"] if "--native" in sys.argv else []
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    log = open(os.path.join(HERE, "out", "suite%s.txt" % ("-native" if extra else "")), "w")
    failed = []
    for variant in ORDER:
        if only and only not in variant and not variant.endswith("-off") and variant != "none":
            continue
        run = subprocess.run([sys.executable, os.path.join(HERE, "run.py"), variant] + extra, capture_output=True, text=True)
        check = subprocess.run([sys.executable, os.path.join(HERE, "check-look.py"), variant] + extra, capture_output=True, text=True)
        log.write(run.stdout + run.stderr + check.stdout + check.stderr)
        line = check.stdout.strip().splitlines()[0] if check.stdout.strip() else "%s: FAIL (no output) %s" % (variant, check.stderr[-200:])
        if run.returncode != 0:
            line += "  (stand-in exit %d)" % run.returncode
        print(line, flush=True)
        if check.returncode != 0 or run.returncode != 0:
            failed.append(variant)
    print("%d failed%s" % (len(failed), ": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)


main()
