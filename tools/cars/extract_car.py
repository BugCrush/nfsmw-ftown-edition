"""Exports one car's collections (car parts, collision, car type) from a GlobalB.lzc with Nikki, in the form
Binarius's `import` reads (tools/cars/nikki-export, built by its build.bat). The input is copied first and never
opened for writing.

    python tools/cars/extract_car.py <GlobalB.lzc> <CAR> <out dir> [manager ...]
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOTNET = os.path.join(ROOT, ".tools", "dotnet-x86", "dotnet.exe")
EXPORTER = os.path.join(HERE, "nikki-export", "out", "NikkiExport.dll")
MANAGERS = ("DBModelParts", "Collisions", "CarTypeInfos")


class Failed(Exception):
    pass


def extract_car(globalb, car, out_dir, managers=MANAGERS):
    if not os.path.exists(EXPORTER):
        subprocess.run(["cmd", "/c", os.path.join(HERE, "nikki-export", "build.bat")], check=True)
    work = tempfile.mkdtemp()
    try:
        copy = os.path.join(work, os.path.basename(globalb))
        shutil.copy(globalb, copy)
        p = subprocess.run([DOTNET, "exec", EXPORTER, copy, os.path.abspath(out_dir), car] + list(managers),
                           capture_output=True, text=True, cwd=os.path.dirname(EXPORTER))
        if p.returncode != 0:
            raise Failed("NikkiExport failed (exit %d): %s%s" % (p.returncode, p.stdout[-800:], p.stderr[-800:]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {m: os.path.join(out_dir, m + ".bin") for m in managers}


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    for m, p in extract_car(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:] or MANAGERS).items():
        print(m, p, os.path.getsize(p))
