"""Stage 1 then stage 2 on a fresh full copy of the backup (several minutes). Stage 3 (HUD Adapter) was dropped by
the user on 2026-10-19: it moved the HUD inward (docs/x360-install-manifest.md, "Stage 3")."""
import os
import shutil
import subprocess

import files
import stage1
import stage2
import stage4
import stage5

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PACK = os.path.join(ROOT, ".superpowers", "visual-research", "x360-complex")
BACKUP = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - backup before x360")
COPY = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - rehearsal")
WORK = os.path.join(ROOT, ".superpowers", "work")


def _hashes(root):
    out = {}
    for dp, _, ns in os.walk(root):
        for n in ns:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, root).lower()] = files.sha256(p)
    return out


def test_stage2_after_stage1_on_a_copy():
    subprocess.run(["robocopy", BACKUP, COPY, "/MIR", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"], capture_output=True)
    for d in ("rehearsal-record", "rehearsal-stage2-record", "rehearsal-stage2-record-2",
              "rehearsal-stage4-record", "rehearsal-stage4-record-2",
              "rehearsal-stage5-record", "rehearsal-stage5-record-2"):
        shutil.rmtree(os.path.join(WORK, d), ignore_errors=True)
    stage1.run(COPY, PACK, stage1.default_builds(), os.path.join(WORK, "rehearsal-record"), check_game=False)
    before = _hashes(COPY)
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:  # relative target, as the real command
        s = stage2.run(os.path.basename(COPY), os.path.join(WORK, "rehearsal-stage2-record"), check_game=False)
    finally:
        os.chdir(cwd)
    after = _hashes(COPY)
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    assert changed == {r"scripts\nfsmwhdreflections.asi", r"scripts\nfsmwhdreflections.ini",
                       r"scripts\nfsmwfeshadows.asi", r"scripts\nfsmwfeshadows.ini"}, changed
    assert {e["rel"].lower() for e in s["files"]} == changed
    g = lambda rel: files.find(COPY, rel)
    for name, out in (("NFSMWHDReflections.asi", stage2.OUT["hd"]), ("NFSMWFEShadows.asi", stage2.OUT["fe"])):
        assert files.sha256(g("scripts\\" + name)) == files.sha256(os.path.join(out, name))
    hd = open(g(r"scripts\NFSMWHDReflections.ini"), "rb").read()
    fe = open(g(r"scripts\NFSMWFEShadows.ini"), "rb").read()
    assert b"\r\nCubemapBrightnessFix = 0\r\n" in hd and b"\r\nRestoreWaterReflections = 0\r\n" in hd
    assert b"\r\nForceEnableMirror = 0\r\n" in hd  # the user's choice: no forced mirror
    assert b"\r\nAutoRes = 1" in hd and b"\r\nImproveReflectionLOD = 1" in hd  # the author's defaults kept
    assert b"RestoreShadows = 1" in fe.split(b"\r\n")  # the author's file ends without a line break
    assert b"\n" not in fe.replace(b"\r\n", b"") and b"\n" not in hd.replace(b"\r\n", b"")
    second = stage2.run(COPY, os.path.join(WORK, "rehearsal-stage2-record-2"), check_game=False)
    assert second["files"] == [] and _hashes(COPY) == after

    # stage 4 on top: exactly its files, the four edited ones, the cache and the .exe
    s4 = stage4.run(COPY, os.path.join(WORK, "rehearsal-stage4-record"), check_game=False)
    after4 = _hashes(COPY)
    changed4 = {p for p in set(after) | set(after4) if after.get(p) != after4.get(p)}
    # never the part list or the language files: the save's fingerprint covers the part indices
    expected = {r.lower() for _, r in stage4.copies(COPY)} | {
        r"scripts\x360stuff.ini", r"global\globalmemoryfile.bin", r"global\ingamememoryfile.bin",
        r"global\permanentmemoryfile.bin", "speed.exe"}
    assert changed4 == expected, (changed4 - expected, expected - changed4)
    # as `unlock_memory all` writes them: the pack's empty 366-byte cache, 16 bytes for the others
    for rel, size in ((r"GLOBAL\GlobalMemoryFile.bin", 366), (r"GLOBAL\InGameMemoryFile.bin", 16),
                      (r"GLOBAL\PermanentMemoryFile.bin", 16), (r"GLOBAL\FrontEndMemoryFile.bin", 16)):
        assert os.path.getsize(files.find(COPY, rel)) == size, rel
    assert {e["rel"].lower() for e in s4["files"]} == expected
    for src, rel in stage4.copies(COPY):
        assert after4[rel.lower()] == files.sha256(src), rel
    assert b"\r\nWidescreenMovies = 1\r\n" in open(files.find(COPY, r"scripts\X360Stuff.ini"), "rb").read()
    again = stage4.run(COPY, os.path.join(WORK, "rehearsal-stage4-record-2"), check_game=False)
    assert again["files"] == [] and _hashes(COPY) == after4

    # stage 5: only the three settings files, only the named keys
    stage5.run(COPY, os.path.join(WORK, "rehearsal-stage5-record"), check_game=False)
    after5 = _hashes(COPY)
    changed5 = {p for p in set(after4) | set(after5) if after4.get(p) != after5.get(p)}
    assert changed5 == {r"scripts\x360stuff.ini", r"scripts\nfsmwhdreflections.ini", r"scripts\nfsmwfeshadows.ini"}
    x = open(files.find(COPY, r"scripts\X360Stuff.ini"), "rb").read()
    for line in (b"FEScalingMode = 0", b"CarsInAllCubemapFaces = 1", b"UseFullLODShaderOnTrafficAndCops = 1"):
        assert b"\r\n" + line + b"\r\n" in x, line
    assert b"\r\nRestoreShadows = 1\r\n" in open(files.find(COPY, r"scripts\NFSMWHDReflections.ini"), "rb").read()
    assert b"\r\nRestoreCars = 0" in open(files.find(COPY, r"scripts\NFSMWHDReflections.ini"), "rb").read()
    assert b"\r\nRenderCarShadows = 1\r\n" in open(files.find(COPY, r"scripts\NFSMWFEShadows.ini"), "rb").read()
    again5 = stage5.run(COPY, os.path.join(WORK, "rehearsal-stage5-record-2"), check_game=False)
    assert again5["files"] == [] and _hashes(COPY) == after5
