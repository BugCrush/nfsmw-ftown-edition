"""Checks that refuse before anything changes: the game version, the game running, write permission, and the Black
Edition files the installer changes being the ones it was tested on.

The game version is checked on code, not on the whole speed.exe (copies differ, e.g. in the large-address flag or a
patched start-up): the sha256 of a few code sites our plugins patch must equal those of speed.exe 1.3. The files the
installer changes (originals.json, hashes only) must be the Black Edition's: the Xbox 360 pack's track patch, the
database order and the save fingerprint were all tested on exactly those.
"""
import hashlib
import os
import struct
import subprocess
import uuid


class Refused(Exception):
    pass


def game_running():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    except OSError:
        return False
    return "speed.exe" in out


def _writable(path):
    probe = os.path.join(path, "ftedition-write-test-%s.tmp" % uuid.uuid4().hex[:8])
    try:
        with open(probe, "wb") as f:
            f.write(b"x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _va_reader(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[:2] != b"MZ" or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a Windows program")
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x10B:
        raise ValueError("not a 32-bit program")
    base = struct.unpack_from("<I", data, opt + 28)[0]
    secs = []
    for i in range(nsec):
        s = opt + opt_size + 40 * i
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, s + 8)
        secs.append((rva, max(vsize, rsize), raw))

    def read(va, n):
        rva = va - base
        for start, size, raw in secs:
            if start <= rva < start + size:
                off = raw + rva - start
                return data[off:off + n]
        raise ValueError("address 0x%X is outside the program" % va)
    return read


def check_exe(game, sites):
    exe = os.path.join(game, "speed.exe")
    if not os.path.isfile(exe):
        raise Refused("no speed.exe in %s: choose the Need for Speed Most Wanted game folder" % game)
    with open(exe, "rb") as f:
        data = f.read()
    try:
        read = _va_reader(data)
        for s in sites:
            if hashlib.sha256(read(s["va"], s["len"])).hexdigest() != s["sha256"]:
                raise ValueError("code at 0x%X differs" % s["va"])
    except (ValueError, struct.error) as e:
        raise Refused("speed.exe is not Need for Speed Most Wanted version 1.3 (%s); this mod needs the 1.3 game" % e)


def check_originals(game, originals):
    for rel, (size, digest) in sorted(originals.items()):
        p = os.path.join(game, *rel.split("/"))
        if not os.path.isfile(p):
            p = _find(game, rel)
        ok = p is not None and os.path.getsize(p) == size and _sha256(p) == digest
        if not ok:
            raise Refused("%s is not the file this mod was tested with. The installer was tested on the Black Edition "
                          "1.3 files, unmodded; restore the game's original files (or reinstall the game) and run it "
                          "again. Other versions are untested." % rel)


def _find(root, rel):
    cur = root
    for part in rel.split("/"):
        if not os.path.isdir(cur):
            return None
        m = [e for e in os.listdir(cur) if e.lower() == part.lower()]
        if not m:
            return None
        cur = os.path.join(cur, m[0])
    return cur if os.path.isfile(cur) else None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(game, sites, originals, running=game_running):
    if not os.path.isdir(game):
        raise Refused("%s is not a folder" % game)
    if running():
        raise Refused("the game (speed.exe) is running: close it first")
    check_exe(game, sites)
    if not _writable(game):
        raise Refused("cannot write to %s: run the installer as a user who may change the game folder (for a game "
                      "under Program Files, run it as administrator)" % game)
    check_originals(game, originals)
