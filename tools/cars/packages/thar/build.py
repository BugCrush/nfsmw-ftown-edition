"""Builds the Thar package's generated files (git-ignored, under .superpowers) before an install.

    python tools/cars/packages/thar/build.py [<out dir>]

Writes DBModelParts.bin (make_parts.py), CarTypeInfos.bin (make_cartype.py) and logo/ with the two car-select logos
(tools/carbuild/logo.py) into <out dir> (default .superpowers/carbuild/thar/package, where install.end reads them).
The logo folder gets the DDS files only: Binarius's bind_textures takes every file in it. The model files come from
Part 2 (.superpowers/carbuild/thar/out: carbin.py assemble tools/carbuild/cars/thar.json).
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "carbuild"))
import logo  # noqa: E402
import make_cartype  # noqa: E402
import make_parts  # noqa: E402

LOGO_SRC = os.path.join(REPO, ".superpowers", "downloads", "cars", "thar", "logo", "Mahindra_Automotive_new_logo.png")


def build(out_dir=make_parts.OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    files = [make_parts.main([out_dir]), make_cartype.main([out_dir])]
    logo_dir = os.path.join(out_dir, "logo")
    if os.path.exists(logo_dir):
        shutil.rmtree(logo_dir)
    os.makedirs(logo_dir)
    work = tempfile.mkdtemp(prefix="thar-logo-")
    try:
        for dds in logo.make_logo_textures(LOGO_SRC, work):
            files.append(shutil.copy(dds, os.path.join(logo_dir, os.path.basename(dds))))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return files


if __name__ == "__main__":
    for f in build(*sys.argv[1:2]):
        print(f)
