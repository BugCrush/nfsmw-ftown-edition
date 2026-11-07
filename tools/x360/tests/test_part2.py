"""Part 2 (Binarius) on a copy of the game's GLOBAL, FRONTEND and LANGUAGES folders. Slow (a minute or two)."""
import os
import subprocess

import files
import part2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PACK = os.path.join(ROOT, ".superpowers", "visual-research", "x360-complex")
BACKUP = r"D:\projects\nfsmwbe\Need For Speed Most Wanted Black Edition - backup before x360"
GAME = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition")
COPY = r"D:\projects\nfsmwbe\.superpowers\work\part2-copy"
ALLOWED = {r"global\globalb.lzc", r"global\ingamea.bun", r"global\dyntex.bin", r"global\ingameb.lzc",
           r"global\hudtexrace.bin", r"global\hudtexturesphotofinish.bin", r"frontend\frontb.lzc"}
MARKERS = {m: True for m in ("lightmaterials", "lightflares", "particletextures", "platforms", "x360textures",
                             "uitextures")}


def _fresh_copy():
    for d in ("GLOBAL", "FRONTEND", "LANGUAGES"):
        subprocess.run(["robocopy", os.path.join(BACKUP, d), os.path.join(COPY, d), "/MIR", "/NP", "/NFL", "/NDL",
                        "/NJH", "/NJS"], capture_output=True)


def _hashes(root, sub):
    out = {}
    for dirpath, _, names in os.walk(os.path.join(root, sub)):
        for n in names:
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, root).lower()] = files.sha256(p)
    return out


def test_part2_on_a_copy():
    _fresh_copy()
    game_before = _hashes(GAME, "GLOBAL")
    result = part2.run(COPY, PACK, MARKERS)
    assert result["error_log"].strip() == "", result["error_log"]
    changed = {c.lower() for c in result["changed"]}
    assert changed <= ALLOWED, changed - ALLOWED
    assert {r"global\globalb.lzc", r"global\ingamea.bun"} <= changed, changed
    for leftover in ("_ChoicesX360", "ModData", "Install-Part-2.end", "x360-part2.end"):
        assert not os.path.exists(os.path.join(COPY, leftover)), leftover
    assert _hashes(GAME, "GLOBAL") == game_before


def test_no_markers_changes_only_the_always_parts():
    """With every option off, only the always-run part (PC textures, flags, sky renames) applies."""
    _fresh_copy()
    result = part2.run(COPY, PACK, {m: False for m in MARKERS})
    assert result["error_log"].strip() == "", result["error_log"]
    assert {c.lower() for c in result["changed"]} <= {r"global\globalb.lzc", r"global\ingamea.bun"}
