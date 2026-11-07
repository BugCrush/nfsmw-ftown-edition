"""Copies the pack's files into a game folder by manifest, checking every result.

Targets are matched case-insensitively (the game's names mix case, the pack's are upper case). A JSON record
of every file added or replaced, with its previous sha256, is written before each copy, so a stop half-way
still says exactly what to restore from the backup.
"""
import hashlib
import json
import os
import shutil
import subprocess


class Refused(Exception):
    pass


class Failed(Exception):
    pass


def game_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    return "speed.exe" in out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def find(root, rel):
    """The existing path for rel under root, matching each part case-insensitively, or None."""
    cur = root
    for part in rel.replace("\\", "/").split("/"):
        if not os.path.isdir(cur):
            return None
        match = [e for e in os.listdir(cur) if e.lower() == part.lower()]
        if not match:
            return None
        cur = os.path.join(cur, match[0])
    return cur


def _target(root, rel):
    """Existing path (its case kept), or a new path under the deepest existing folder (its case kept)."""
    found = find(root, rel)
    if found:
        return found
    parts = rel.replace("\\", "/").split("/")
    cur = root
    for part in parts[:-1]:
        nxt = find(cur, part)
        cur = nxt if nxt else os.path.join(cur, part)
    return os.path.join(cur, parts[-1])


def plan(actions, pack_root, target_root):
    steps = []
    for line in actions:
        words = line.split()
        if words[0] == "folder_create":
            continue
        if words[0] != "file_copy" or len(words) != 3:
            raise ValueError("unknown action: " + line)
        src = find(pack_root, words[1])
        dst = _target(target_root, words[2])
        h = sha256(src) if src else None
        if src is None:
            kind = "missing"
        elif not os.path.exists(dst):
            kind = "adds"
        elif sha256(dst) == h:
            kind = "same"
        else:
            kind = "replaces"
        steps.append({"src": src or words[1], "dst": dst, "rel": words[2], "kind": kind, "sha256": h})
    return steps


def install(steps, target_root, record_path, check_game=True):
    if check_game and game_running():
        raise Refused("speed.exe is running: close the game first")
    record, copied, skipped = [], 0, 0

    def save():
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1)

    save()
    for s in steps:
        if s["kind"] == "same":
            skipped += 1
            continue
        if s["sha256"] is None:
            raise Failed("%s: source missing (%s)" % (s["rel"], s["src"]))
        old = sha256(s["dst"]) if os.path.exists(s["dst"]) else None
        record.append({"rel": s["rel"], "dst": s["dst"], "old_sha256": old, "new_sha256": s["sha256"]})
        save()
        os.makedirs(os.path.dirname(s["dst"]), exist_ok=True)
        try:
            shutil.copyfile(s["src"], s["dst"])
        except OSError as e:
            raise Failed("%s: %s" % (s["rel"], e))
        if sha256(s["dst"]) != s["sha256"]:
            raise Failed("%s: hash after copy differs" % s["rel"])
        copied += 1
    return {"copied": copied, "skipped": skipped}
