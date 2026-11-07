"""Stage 4 of the Xbox 360 pack install, the extras the user chose on 2026-10-19 (docs/x360-install-manifest.md,
"Stage 4"):

- the pack's options 11 and 12: its music (SOUND\\PFDATA\\MW_Music.mpf/.mus) and 87 engine sounds (SOUND\\ENGINE);
- the Xbox 360 converted movies (nfsmods mod 3006, 1280x720 / 1024x576 instead of 1024x512), with
  X360Stuff.ini [VIDEO] WidescreenMovies = 1;
- Recompiled Vinyls 1024x Simple (nfsmods mod 629): its CARS\\<car>\\VINYLS.BIN and CARS\\TEXTURES.BIN copied. Not its
  "fix names and add entries for cut vinyls" step: that inserts part entries into GLOBAL\\GlobalB.lzc, which shifts
  the part indices the save's car records hold (FECustomizationRecord::InstalledPartIndices) and so the save's
  fingerprint (a CRC32 of the whole default car stable, FEDatabase.cpp): every profile then reads as damaged
  (found in the game on 2026-10-19);
- speed.exe marked large-address-aware, so the 32-bit game may use 4 GB instead of 2 (1024x vinyls are about 35 MB
  per car instead of 2);
- the memory files unlocked as the vinyl mod's `unlock_memory all` does (Endscript UnlockMemoryCommand, Nikki
  MemoryUnlock): GLOBAL\\GlobalMemoryFile.bin becomes the empty 366-byte cache (Binarius's LongUnlock output, which is
  the pack's own copy in its Easy download; every file is then read from disk, and the Black Edition's cached
  copies were byte-identical to the disk files, manifest "memory file"), InGameMemoryFile.bin and
  PermanentMemoryFile.bin (and CarHeaders/FrontEnd if present) become 16-byte unlocked files (FastUnlock).

Not included, by the user's choice: the Xbox 360 UI texts (mod 4860).
Usage: python stage4.py <target folder> [--game]   (--game: refuses while the game runs)
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import files  # noqa: E402
import stage1  # noqa: E402
import stages  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESEARCH = os.path.join(ROOT, ".superpowers", "visual-research")
PACK_FILES = os.path.join(RESEARCH, "x360-complex", "ModData", "Files")
EMPTY_CACHE = os.path.join(RESEARCH, "x360-easy", "GLOBAL", "GlobalMemoryFile.bin")  # 366 bytes
EXTRAS = os.path.join(RESEARCH, "extras")
MOVIES = os.path.join(EXTRAS, "movies", "MOVIES")
VINYLS = os.path.join(EXTRAS, "vinyls", "1024-simple", "x", "Binary")
LAA = 0x0020  # IMAGE_FILE_LARGE_ADDRESS_AWARE in the PE file header's Characteristics
X360STUFF_SETTINGS = {("VIDEO", "WidescreenMovies"): "1"}
UNLOCKED = struct.pack("<4I", 0, 0, 0x53219999, 0)  # MemoryUnlock.FastUnlock
FAST_UNLOCK = ["CarHeadersMemoryFile.bin", "FrontEndMemoryFile.bin", "InGameMemoryFile.bin", "PermanentMemoryFile.bin"]


def copies(target):
    """[(source, game-relative path)] for the music, engines, movies and vinyl texture files. A car's VINYLS.BIN is
    copied only where the game has one, as the mod's own script does (`if file_exists ... move_file`): the game
    has none for BMWM3CSL and SKYLINE."""
    out = [(os.path.join(PACK_FILES, "SOUND", "PFDATA", n), "SOUND\\PFDATA\\" + n) for n in ("MW_Music.mpf", "MW_Music.mus")]
    eng = os.path.join(PACK_FILES, "SOUND", "ENGINE")
    out += [(os.path.join(eng, n), "SOUND\\ENGINE\\" + n) for n in sorted(os.listdir(eng))]
    out += [(os.path.join(MOVIES, n), "MOVIES\\" + n) for n in sorted(os.listdir(MOVIES)) if n.endswith(".vp6")]
    out.append((os.path.join(VINYLS, "CARS", "TEXTURES.BIN"), r"CARS\TEXTURES.BIN"))
    for car in sorted(os.listdir(os.path.join(VINYLS, "CARS"))):
        p = os.path.join(VINYLS, "CARS", car, "VINYLS.BIN")
        rel = "CARS\\%s\\VINYLS.BIN" % car
        if os.path.isfile(p) and files.find(target, rel):
            out.append((p, rel))
    return out


def large_address_aware(data):
    """The same .exe bytes with the large-address-aware flag set (unchanged if it already is)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    chars = struct.unpack_from("<H", data, pe + 22)[0]
    out = bytearray(data)
    struct.pack_into("<H", out, pe + 22, chars | LAA)
    return bytes(out)


def unlocked_memory_files(target):
    """{game-relative path: new bytes} for the memory files the game has, as `unlock_memory all` writes them."""
    out = {r"GLOBAL\GlobalMemoryFile.bin": open(EMPTY_CACHE, "rb").read()}
    for n in FAST_UNLOCK:
        out["GLOBAL\\" + n] = UNLOCKED
    return {rel: data for rel, data in out.items() if files.find(target, rel)}


def _write_recorded(rec, target, rel, new, check_game):
    path = files.find(target, rel)
    old = open(path, "rb").read()
    if new == old:
        return
    if check_game and files.game_running():
        raise stage1.Refused("speed.exe is running: close the game first")
    rec.add(rel, files.sha256_bytes(old), files.sha256_bytes(new))
    open(path, "wb").write(new)


def run(target, record_dir, check_game=True):
    target, record_dir = os.path.abspath(target), os.path.abspath(record_dir)
    stages.require_stage1(target)
    if check_game and files.game_running():
        raise stage1.Refused("speed.exe is running: close the game first")
    stage1.check_record_dir(record_dir)
    os.makedirs(record_dir, exist_ok=True)

    # 1. Files, and the movie setting (recorded in <record>/copies/)
    x360ini = files.find(target, r"scripts\X360Stuff.ini")
    s = stages.install_companion(target, copies(target), {r"scripts\X360Stuff.ini": (x360ini, X360STUFF_SETTINGS)},
                                 os.path.join(record_dir, "copies"), check_game=check_game)
    rec = stage1.Record(record_dir, "stage-progress.json")
    for e in s["files"]:
        rec.add(e["rel"], e["old_sha256"], e["new_sha256"])

    # 2. Memory files unlocked
    for rel, data in unlocked_memory_files(target).items():
        _write_recorded(rec, target, rel, data, check_game)

    # 3. speed.exe may use 4 GB
    exe = files.find(target, "speed.exe")
    _write_recorded(rec, target, "speed.exe", large_address_aware(open(exe, "rb").read()), check_game)

    summary = {"target": target, "files": rec.entries}
    with open(os.path.join(record_dir, "stage-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary


if __name__ == "__main__":
    record = os.path.join(ROOT, "telemetry", "x360-stage4-record-" + time.strftime("%Y%m%d-%H%M%S"))
    s = run(sys.argv[1], record, check_game="--game" in sys.argv)
    print("%d files added or changed; record in %s" % (len(s["files"]), record))
