"""Builds FTownEditionInstaller.exe (one file, console) with PyInstaller into release/build/exe/.

    .tools/releaseenv/Scripts/python release/build_exe.py

The repo tools the installer reuses (tools/x360, tools/cars, tools/textures, tools/carbuild, tools/controls and two car packages) are
put on PyInstaller's search path and their modules named, so the frozen installer imports them as the source does.
The payload is not inside the .exe: it sits beside it, readable, in the package folder.
"""
import os
import sys

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PATHS = [os.path.join(HERE, "installer")] + [os.path.join(REPO, *p) for p in (
    ("tools", "x360"), ("tools", "cars"), ("tools", "textures"), ("tools", "carbuild"), ("tools", "controls"),
    ("tools", "cars", "packages", "thar"), ("tools", "cars", "packages", "longnosecab"))]
MODULES = ["files", "memfile", "nfsms", "part1", "part2", "ups", "vlt_order", "vlthash", "stage1", "stage2", "stage4",
           "stage5", "stages", "install", "endscript", "extract_car", "parts", "retex", "assemble", "chunks",
           "conventions", "geometry", "textures", "interior", "jdlz", "donor", "describe", "make_parts", "make_cartype",
           "fix_parts", "skinnable", "mwsave", "yaml"]


def main():
    entry = os.path.join(HERE, "installer", "run_installer.py")
    args = [entry, "--onefile", "--console", "--name", "FTownEditionInstaller", "--noconfirm", "--clean",
            "--distpath", os.path.join(HERE, "build", "exe"), "--workpath", os.path.join(HERE, "build", "work"),
            "--specpath", os.path.join(HERE, "build")]
    for p in PATHS:
        args += ["--paths", p]
    for m in MODULES:
        args += ["--hidden-import", m]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    sys.exit(main())
