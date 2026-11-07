"""Prepares the cleaned public source snapshot in release/public-repo/ (git-ignored). Nothing is pushed or created on
GitHub: the user approves FILELIST.txt first.

    python release/make_public_repo.py

Starts from the files git tracks in this private repo, leaves out what must not go public (the game folder, in-game
screenshots, logs and telemetry, the registry export, the development log and notes, CLAUDE.md, third-party
binaries, unshipped F-Town data, the private patterns file), applies a few scrubs (the safe-house place and the
profile name in a handful of source files; the public FTownLoader.ini), puts the public README and the MIT licence at
the top, and refuses to finish while any file still holds a forbidden pattern (release/private/forbidden.json).
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "public-repo")
sys.path.insert(0, HERE)
import build_package  # noqa: E402

EXCLUDE_PREFIXES = ("screenshots-from-game/", "Need For Speed Most Wanted Black Edition/", "registry/", "docs/",
                    ".claude/", "release/private/", "release/public/")
EXCLUDE_FILES = {"game-manifest.txt", "CLAUDE.md", "README.md", "fps-capture/PresentMon.exe", "ftown/ftown-slab.bun",
                 "tools/citymap/render_runk.py", "tools/export-registry.ps1"}
INCLUDE_DOCS = {"docs/carbuild-format.md"}


def _sub_once(text, pattern, repl, flags=0):
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit("scrub pattern not found: %s" % pattern)
    return new


def scrub(rel, data):
    """The public version of a tracked file (bytes)."""
    if rel == "ftown/FTownLoader.ini":
        return build_package.release_ini("FTownLoader.ini", data)
    if rel == "tools/citymap/minimap.py":
        t = data.decode("utf-8")
        t = _sub_once(t, r"# Run J, item 6: the user.s home.*?\nSAFE_HOUSE_OSM = \d+\n",
                      "# Where FTownLoader may show the game's safe-house icon (render metres): set in FTownLoader.ini\n"
                      "# [Minimap] (SafeHouseIcon, SafeHouse); none in the public source.\nSAFE_HOUSE = (0.0, 0.0)\n",
                      re.S)
        return t.encode("utf-8")
    if rel == "tools/citymap/tests/test_minimap.py":
        t = data.decode("utf-8")
        t = _sub_once(t, r"    def test_safe_house_icon_not_painted\(self\):.*?(?=\n    def )", "", re.S)
        return t.encode("utf-8")
    if rel in ("tools/carbuild/rehearsal.py", "tools/carbuild/tests/test_thar_rehearsal.py", "tools/cars/tests/test_parts.py"):
        with open(build_package.PRIVATE, encoding="utf-8") as f:
            profile = json.load(f)["profile_name"].encode()
        return data.replace(profile, b"player")
    if rel == ".gitignore":
        # the public repo carries the menu logos (icons/): not ignored there
        t = data.decode("utf-8")
        t = _sub_once(t, r"# the user's own logos for F-Town's menus \(icons/\)[^\n]*\n/icons/\r?\n", "")
        return t.encode("utf-8")
    if rel == "tools/citymap/landmarks/registry.json":
        # the user's photo file names carry when they were shared: the public copy names them by number only
        t = data.decode("utf-8")
        t, n = re.subn(r'("(\d+)": \{"file": )"[^"]*"', lambda m: '%s"photo-%s.jpeg"' % (m.group(1), m.group(2)), t)
        if n == 0:
            raise SystemExit("scrub pattern not found: registry.json photo file names")
        return t.encode("utf-8")
    return data


def tracked():
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def selected(files):
    keep = []
    for rel in files:
        if rel in EXCLUDE_FILES:
            continue
        if rel.startswith(EXCLUDE_PREFIXES) and rel not in INCLUDE_DOCS:
            continue
        keep.append(rel)
    return keep


def main():
    if os.path.isdir(OUT):
        # the published repository's .git (created 2026-11-07) is kept: the snapshot is rewritten around it
        for name in os.listdir(OUT):
            if name == ".git":
                continue
            p = os.path.join(OUT, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    files = selected(tracked())
    for rel in files:
        src = os.path.join(REPO, *rel.split("/"))
        dst = os.path.join(OUT, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as f:
            data = scrub(rel, f.read())
        with open(dst, "wb") as f:
            f.write(data)
    shutil.copyfile(os.path.join(HERE, "public", "README.md"), os.path.join(OUT, "README.md"))
    shutil.copyfile(os.path.join(HERE, "package", "LICENSE"), os.path.join(OUT, "LICENSE"))
    files += ["README.md", "LICENSE"]
    # the F-Town menu logos (git-ignored here; the user chose to publish them, 2026-11-07): the source of
    # tools/ftownicons/make_icons.py
    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)
    for name in sorted(os.listdir(os.path.join(REPO, "icons"))):
        if name.lower().endswith(".png"):
            shutil.copyfile(os.path.join(REPO, "icons", name), os.path.join(OUT, "icons", name))
            files.append("icons/" + name)
    # screenshots for the public README (release/public/screenshots/, chosen 2026-11-08: no home mark in view)
    os.makedirs(os.path.join(OUT, "screenshots"), exist_ok=True)
    for name in sorted(os.listdir(os.path.join(HERE, "public", "screenshots"))):
        shutil.copyfile(os.path.join(HERE, "public", "screenshots", name), os.path.join(OUT, "screenshots", name))
        files.append("screenshots/" + name)
    # the trailer (the user's edit, 2026-11-08; re-encoded without its file metadata) and its poster frame
    os.makedirs(os.path.join(OUT, "media"), exist_ok=True)
    for name in sorted(os.listdir(os.path.join(HERE, "public", "media"))):
        shutil.copyfile(os.path.join(HERE, "public", "media", name), os.path.join(OUT, "media", name))
        files.append("media/" + name)
    hits = build_package.forbidden_hits(OUT, check_names=False)  # source: diagnostics' sources may be public
    listing = sorted(files)
    with open(os.path.join(OUT, "FILELIST.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# Files of the public source snapshot (%d), for the user's approval before anything is published\n"
                % len(listing))
        f.write("\n".join(listing) + "\n")
    print("%d files in %s" % (len(listing), OUT))
    if hits:
        print("FORBIDDEN CONTENT:\n  " + "\n  ".join(hits))
        return 1
    print("forbidden-pattern check: 0 hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
