"""Makes the clean test game: a copy of the pre-Xbox-360 backup stripped back to the repack as installed.

    python release/tools/make_clean_copy.py [--force]

What the repack had is known from the repo's first commit (a4d5685, 2026-09-27): its game-manifest.txt hashed every
file of the game folder, and that commit added only DXVK (d3d9.dll, dxvk.conf), FpsRecorder and a .bak of the Widescreen
Fix's .ini beside the repack's own files. So the repack shipped the Ultimate ASI Loader (dinput8.dll) and an old build of
the Widescreen Fix (.asi, .ini, buttons .tpk): those are kept, the .ini put back from our .bak (the repack's original).
Removed: DXVK and its log, every plugin of ours and its files and logs, and SAVE (the user's profile; the game makes
the folder on first start). The result is checked file by file against that first manifest.
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
BACKUP = os.path.join(REPO, "Need For Speed Most Wanted Black Edition - backup before x360")
CLEAN = os.path.join(REPO, "Need For Speed Most Wanted Black Edition - clean test")
OURS_IN_FIRST = {"d3d9.dll", "dxvk.conf", "scripts/FpsRecorder.asi", "scripts/FpsRecorder.ini",
                 "scripts/NFSMostWanted.WidescreenFix.ini.bak"}
REMOVE = ["d3d9.dll", "dxvk.conf", "speed_d3d9.log", "SAVE"]
SCRIPTS_KEEP = {"nfsmostwanted.widescreenfix.asi", "nfsmostwanted.widescreenfix.ini", "buttons-playstation.tpk",
                "buttons-xbox.tpk"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def first_manifest():
    text = subprocess.run(["git", "-C", REPO, "show", "a4d5685:game-manifest.txt"], capture_output=True, check=True).stdout
    out = {}
    for line in text.decode("utf-8-sig").splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            out[rel.strip()] = h
    return out


def tree(root):
    out = {}
    for dp, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = p
    return out


def strip(root):
    s = os.path.join(root, "scripts")
    ini, bak = os.path.join(s, "NFSMostWanted.WidescreenFix.ini"), os.path.join(s, "NFSMostWanted.WidescreenFix.ini.bak")
    shutil.copyfile(bak, ini)
    for n in os.listdir(s):
        if n.lower() not in SCRIPTS_KEEP:
            os.remove(os.path.join(s, n))
    for n in REMOVE:
        p = os.path.join(root, n)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)


def verify(root):
    want = {rel: h for rel, h in first_manifest().items() if rel not in OURS_IN_FIRST}
    want["scripts/NFSMostWanted.WidescreenFix.ini"] = first_manifest()["scripts/NFSMostWanted.WidescreenFix.ini.bak"]
    have = tree(root)
    # the first manifest left out every .log (tools/game-manifest.ps1); the two under Support are the repack's help logs
    extra = sorted(rel for rel in set(have) - set(want) if not (rel.startswith("Support/") and rel.endswith(".log")))
    missing = sorted(set(want) - set(have))
    differ = sorted(rel for rel in want if rel in have and sha(have[rel]) != want[rel])
    return extra, missing, differ


def main(argv):
    if os.path.exists(CLEAN):
        if "--force" not in argv:
            raise SystemExit("%s exists (use --force to make it again)" % CLEAN)
        shutil.rmtree(CLEAN)
    shutil.copytree(BACKUP, CLEAN)
    strip(CLEAN)
    extra, missing, differ = verify(CLEAN)
    print("clean copy: %d files; extra %s; missing %s; differing %s" % (len(tree(CLEAN)), extra, missing, differ))
    if extra or missing or differ:
        raise SystemExit("the clean copy does not match the repack's first manifest")


if __name__ == "__main__":
    main(sys.argv[1:])
