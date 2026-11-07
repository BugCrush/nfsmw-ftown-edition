"""Copy the game folder to a test copy and check every file arrived intact.

    python tools/cars/make-test-copy.py <game dir> <dest dir>

Refuses while speed.exe runs or when <dest> already exists (never overwrites a test copy).
"""
import hashlib
import os
import shutil
import subprocess
import sys


class Refused(Exception):
    pass


def _speed_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True)
    if out.returncode != 0:
        return True  # can't tell: treat as running
    return "speed.exe" in out.stdout.lower()


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_copy(src, dest, game_running=_speed_running):
    if game_running():
        raise Refused("speed.exe is running: close the game first")
    if os.path.exists(dest):
        raise Refused("%s already exists" % dest)
    shutil.copytree(src, dest)
    n = 0
    for root, _, files in os.walk(src):
        for name in files:
            a = os.path.join(root, name)
            b = os.path.join(dest, os.path.relpath(a, src))
            if os.path.getsize(a) != os.path.getsize(b) or _sha(a) != _sha(b):
                raise Refused("copy differs: %s" % os.path.relpath(a, src))
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        print("%d files, all match" % make_copy(sys.argv[1], sys.argv[2]))
    except Refused as e:
        sys.exit("refused: %s" % e)
