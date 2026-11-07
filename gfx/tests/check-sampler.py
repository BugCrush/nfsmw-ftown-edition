"""Checks GfxProbe.log from the d3d9-sampler stand-in.  python gfx/tests/check-sampler.py <out folder> [--dxvk]"""
import glob
import os
import sys

out = sys.argv[1]
dxvk = "--dxvk" in sys.argv
log = open(os.path.join(out, "GfxProbe.log"), encoding="utf-8", errors="replace").read()
failures = []


def expect(ok, what):
    if not ok:
        failures.append(what)


expect("device hooks installed" in log, "device hooks installed")
expect("100.0% of draws: min=anisotropic mag=linear mip=linear maxAnisotropy=4" in log, "all draws 4x anisotropic")
expect("effective anisotropy: 4x=100.0%" in log, "effective anisotropy 4x")
expect(log.count("Capture saved:") == 2, "two captures saved, got %d" % log.count("Capture saved:"))
bmps = glob.glob(os.path.join(out, "test", "*.bmp"))
expect(len(bmps) == 2, "two BMP files in test\\, got %d" % len(bmps))
for path in bmps:
    expect(os.path.getsize(path) == 54 + 640 * 480 * 3, "640x480 24-bit BMP: " + path)
expect(bool(glob.glob(os.path.join(out, "*_d3d9.log"))) == dxvk, "DXVK log present only with --dxvk")
print("FAIL\n  " + "\n  ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
