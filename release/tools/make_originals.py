"""Writes the installer's game checks (hashes only, no game bytes):

- release/installer/originals.json: {rel: [size, sha256]} of every Black Edition file the install changes, taken from
  the unmodded backup's hash list for the files that differ in the user's finished game (EA's folders only: our
  plugins, DXVK, saves and logs are not the game's);
- release/installer/exe-sites.json: the sha256 of 16 bytes at code sites our plugins patch (tools/x360/our-patches.txt)
  in the backup's speed.exe (version 1.3).

    python release/tools/make_originals.py
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "release", "installer"))
from ftedition import gamecheck  # noqa: E402

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
BACKUP = os.path.join(REPO, "Need For Speed Most Wanted Black Edition - backup before x360")
HASHES = os.path.join(REPO, "telemetry", "backup-before-x360", "game-before-x360-20261015.sha256")
EA_DIRS = ("CARS/", "FRONTEND/", "GLOBAL/", "LANGUAGES/", "MOVIES/", "SOUND/", "TRACKS/", "FX/", "NIS/")
SITES = (0x4DF330, 0x4F4CD0, 0x82BFD0, 0x517070, 0x6DE680)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    backup = {}
    for line in open(HASHES, encoding="utf-8"):
        h, p = line.rstrip("\n").split(" ", 1)
        backup[p.lstrip("*").lstrip("./").replace("\\", "/")] = h
    originals = {}
    for rel, h in sorted(backup.items()):
        if not rel.upper().startswith(tuple(d.upper() for d in EA_DIRS)):
            continue
        g = os.path.join(GAME, *rel.split("/"))
        if os.path.isfile(g) and (os.path.getsize(g) != os.path.getsize(os.path.join(BACKUP, *rel.split("/")))
                                  or sha(g) != h):
            originals[rel] = [os.path.getsize(os.path.join(BACKUP, *rel.split("/"))), h]
    out = os.path.join(REPO, "release", "installer", "originals.json")
    json.dump(originals, open(out, "w", encoding="utf-8", newline="\n"), indent=0, sort_keys=True)
    print("%d originals -> %s" % (len(originals), out))

    read = gamecheck._va_reader(open(os.path.join(BACKUP, "speed.exe"), "rb").read())
    sites = [{"va": va, "len": 16, "sha256": hashlib.sha256(read(va, 16)).hexdigest()} for va in SITES]
    out = os.path.join(REPO, "release", "installer", "exe-sites.json")
    json.dump(sites, open(out, "w", encoding="utf-8", newline="\n"), indent=1)
    print("%d code sites -> %s" % (len(sites), out))


if __name__ == "__main__":
    main()
