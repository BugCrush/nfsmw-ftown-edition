"""Stage 1 rehearsed on a full copy of the game folder (from the backup; about 3 GB, several minutes), plus the
small .ini helpers on known input."""
import json
import os
import subprocess
import tempfile

import files
import stage1
import ups

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PACK = os.path.join(ROOT, ".superpowers", "visual-research", "x360-complex")
BACKUP = r"D:\projects\nfsmwbe\Need For Speed Most Wanted Black Edition - backup before x360"
BACKUP_HASHES = r"D:\projects\nfsmwbe\telemetry\backup-before-x360\game-before-x360-20261015.sha256"
COPY = r"D:\projects\nfsmwbe\Need For Speed Most Wanted Black Edition - rehearsal"
RECORD = r"D:\projects\nfsmwbe\.superpowers\work\rehearsal-record"
# Xenon Effects: the pack's bundled build (the user's decision, 2026-10-15); TexWizard and the Widescreen Fix: ours.
BUILDS = stage1.default_builds()
BUNDLED = os.path.join(PACK, "ModData", "Files", "scripts")


def test_set_ini_value_keeps_crlf_and_other_lines():
    text = b"; c\r\n[Look]\r\n; 1 = on\r\nEnabled = 1\r\n\r\n[Parts]\r\nEnabled = 1\r\n"
    out = stage1.set_ini_value(text, "Look", "Enabled", "0")
    assert out == b"; c\r\n[Look]\r\n; 1 = on\r\nEnabled = 0\r\n\r\n[Parts]\r\nEnabled = 1\r\n"
    assert stage1.set_ini_value(out, "Look", "Enabled", "0") == out


def test_set_ini_value_refuses_missing_key():
    try:
        stage1.set_ini_value(b"[Look]\r\nOther = 1\r\n", "Look", "Enabled", "0")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_merge_ini_carries_values_and_adds_new_keys():
    current = b"[MAIN]\r\nFixHUD = 1 ; c\r\nScaling = 1\r\n[MISC]\r\nShadowsRes = 4096\r\n"
    upstream = "[MAIN]\nFixHUD = 0\nScaling = 0\nConsoleGamma = 2\n[MISC]\nShadowsRes = 1024\nNewThing = 5\n[CAMERA]\nEnable = 1\n"
    out = stage1.merge_ini(current, upstream, {("MAIN", "ConsoleGamma"): "0", ("CAMERA", "Enable"): "0"})
    text = out.decode()
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert "FixHUD = 1" in text and "Scaling = 1" in text and "ShadowsRes = 4096" in text
    assert "ConsoleGamma = 0" in text and "NewThing = 5" in text
    assert "[CAMERA]\r\nEnable = 0" in text


def test_record_is_on_disk_after_every_entry():
    d = tempfile.mkdtemp()
    rec = stage1.Record(d)
    rec.add(r"GLOBAL\a.bin", "old1", "new1")
    on_disk = json.load(open(os.path.join(d, "stage1-progress.json"), encoding="utf-8"))
    assert on_disk == [{"rel": r"GLOBAL\a.bin", "old_sha256": "old1", "new_sha256": "new1"}]
    rec.add_pending([r"GLOBAL\b.bin"], {r"GLOBAL\b.bin": "oldb"})
    on_disk = json.load(open(os.path.join(d, "stage1-progress.json"), encoding="utf-8"))
    assert on_disk[1] == {"rel": r"GLOBAL\b.bin", "old_sha256": "oldb", "new_sha256": "pending"}


def test_used_record_folder_is_refused():
    d = tempfile.mkdtemp()
    stage1.check_record_dir(d)  # empty: fine
    open(os.path.join(d, "stage1-progress.json"), "w").write("[]")
    try:
        stage1.check_record_dir(d)
    except stage1.Refused as e:
        assert "already" in str(e)
    else:
        raise AssertionError("expected Refused")


def test_files_already_modified_are_refused():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "GLOBAL"))
    open(os.path.join(root, "GLOBAL", "attributes.bin"), "wb").write(b"original")
    hashes = os.path.join(tempfile.mkdtemp(), "list.sha256")
    open(hashes, "w").write("%s *./GLOBAL/attributes.bin\n" % files.sha256_bytes(b"original"))
    stage1.check_originals(root, hashes, [r"GLOBAL\attributes.bin"])  # unchanged: fine
    open(os.path.join(root, "GLOBAL", "attributes.bin"), "wb").write(b"modified")
    try:
        stage1.check_originals(root, hashes, [r"GLOBAL\attributes.bin"])
    except stage1.Refused as e:
        assert "attributes.bin" in str(e)
    else:
        raise AssertionError("expected Refused")


def _hash_list(root):
    out = {}
    for dirpath, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, root).replace("/", "\\").lower()] = files.sha256(p)
    return out


def test_rehearsal_on_a_full_copy():
    subprocess.run(["robocopy", BACKUP, COPY, "/MIR", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"], capture_output=True)
    if os.path.exists(RECORD):
        import shutil
        shutil.rmtree(RECORD)
    # A relative target, as in the real command (`stage1.py "Need For Speed Most Wanted Black Edition" --game`).
    cwd = os.getcwd()
    os.chdir(os.path.dirname(COPY))
    try:
        summary = stage1.run(os.path.basename(COPY), PACK, BUILDS, RECORD, check_game=False)
    finally:
        os.chdir(cwd)
    assert not any(e["new_sha256"] == "pending" for e in summary["files"])
    assert json.load(open(os.path.join(RECORD, "stage1-progress.json"), encoding="utf-8")) == summary["files"]

    g = lambda rel: files.find(COPY, rel)
    assert ups.crc32_file(g(r"TRACKS\STREAML2RA.BUN")) == 0xAE90F386
    assert len([n for n in os.listdir(g(r"FX\COMPILED")) if n.endswith(".fx.o")]) == 18
    for n in ("X360Stuff.asi", "X360Stuff.ini", "NFSMW_XenonEffects.asi", "NFSMW_XenonEffects.ini", "XenonEffects.tpk",
              "TexWizard.json"):
        assert files.sha256(g("scripts\\" + n)) == files.sha256(os.path.join(BUNDLED, n)), n
    assert "NFSMW_XenonEffects.asi" not in BUILDS
    for n, built in BUILDS.items():
        assert files.sha256(g("scripts\\" + n)) == files.sha256(built), n
    assert files.sha256(g(r"scripts\TexWizard.asi")) != files.sha256(os.path.join(BUNDLED, "TexWizard.asi"))
    if stage1.WSF in BUILDS:
        wsf_ini = open(g(r"scripts\NFSMostWanted.WidescreenFix.ini"), "rb").read()
        for line in (b"FixHUD = 0", b"FMVWidescreenMode = 0", b"HUDWidescreenMode = 0", b"Scaling = 1", b"ImproveShadowLOD = 0", b"ShadowsRes = 4096", b"SkipIntro = 0",
                     b"ConsoleGamma = 0", b"SMAA = 0", b"HideAABug = 0"):
            assert line in wsf_ini, line
        assert b"[CAMERA]\r\nEnable = 0" in wsf_ini
        assert files.sha256(g(r"scripts\NFSMostWanted.WidescreenFix.asi")) == files.sha256(BUILDS[stage1.WSF])
        assert b"\n" not in wsf_ini.replace(b"\r\n", b"")
    # The Black Edition's memory file must no longer cache attributes.bin, GlobalB.lzc and DYNTEX.BIN (the pack
    # changes all three; cached copies win over the disk and the sky stays black).
    import memfile
    import vlt_order
    cached = {e["hash"] for e in memfile.entries(open(g(r"GLOBAL\GlobalMemoryFile.bin"), "rb").read())}
    assert 0x4C939B36 not in cached and 0x29EE288F not in cached and 0x9775379A not in cached
    # The installed database walks every class like the original (else the profile reads as damaged) ...
    original_db = open(os.path.join(BACKUP, "GLOBAL", "attributes.bin"), "rb").read()
    installed_db = open(g(r"GLOBAL\attributes.bin"), "rb").read()
    assert vlt_order.walk_orders(installed_db) == vlt_order.walk_orders(original_db)
    # ... and still holds the pack's 66 changed collections
    import part1
    import shutil as _sh
    import vlt_diff
    d1, d2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    for d, db in ((d1, original_db), (d2, installed_db)):
        open(os.path.join(d, "attributes.bin"), "wb").write(db)
        for f in ("fe_attrib.bin", "gameplay.bin"):
            src = [n for n in os.listdir(os.path.join(BACKUP, "GLOBAL")) if n.lower() == f][0]
            _sh.copy(os.path.join(BACKUP, "GLOBAL", src), os.path.join(d, f))
    diff = vlt_diff.diff(part1.unpack(d1, tempfile.mkdtemp()), part1.unpack(d2, tempfile.mkdtemp()))
    assert sum(len(v[2]) for v in diff.values()) == 66 and not any(v[0] or v[1] for v in diff.values())
    vb = open(g(r"scripts\VisualBridge.ini"), "rb").read()
    assert b"\r\nEnabled = 0\r\n" in vb and b"\n" not in vb.replace(b"\r\n", b"")
    for leftover in ("_ChoicesX360", "ModData", "x360-part2.end"):
        assert not os.path.exists(os.path.join(COPY, leftover)), leftover

    # Exactly the files the summary lists changed; nothing else in the copy differs from the backup.
    before = {}
    for line in open(BACKUP_HASHES, encoding="utf-8"):
        h, p = line.rstrip("\n").split(" ", 1)
        before[p.lstrip("*").lstrip("./").replace("/", "\\").lower()] = h
    after = _hash_list(COPY)
    differing = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    listed = {e["rel"].lower() for e in summary["files"]}
    assert differing == listed, (sorted(differing - listed), sorted(listed - differing))
    assert r"sound\pfdata\mw_music.mus" not in differing  # option 11 off
    assert not any(p.startswith("sound\\engine\\") for p in differing)  # option 12 off
    assert json.load(open(os.path.join(RECORD, "stage1-summary.json")))["files"] == summary["files"]

    # A second run refuses before changing anything.
    snapshot = _hash_list(COPY)
    try:
        stage1.run(COPY, PACK, BUILDS, RECORD + "-2", check_game=False)
    except stage1.Refused as e:
        assert "already" in str(e), e
    else:
        raise AssertionError("expected Refused")
    assert _hash_list(COPY) == snapshot
