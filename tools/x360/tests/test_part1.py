"""Part 1 against real files: our database (copied) and the pack's own finished database (known answer)."""
import os
import shutil
import tempfile

import part1
import vlt_diff

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PACK = os.path.join(ROOT, ".superpowers", "visual-research", "x360-complex")
EASY_ATTR = os.path.join(ROOT, ".superpowers", "visual-research", "x360-easy", "GLOBAL", "attributes.bin")
# The original database: the game folder holds the pack's since stage 1 (2026-10-16).
GAME_GLOBAL = r"D:\projects\nfsmwbe\Need For Speed Most Wanted Black Edition - backup before x360\GLOBAL"


def _copy_global():
    d = tempfile.mkdtemp()
    for n in os.listdir(GAME_GLOBAL):
        if n.lower() in ("attributes.bin", "fe_attrib.bin", "gameplay.bin"):
            shutil.copy(os.path.join(GAME_GLOBAL, n), os.path.join(d, n.lower()))
    return d


def test_all_options_equal_the_packs_own_database():
    """Known answer: with every option on, our part 1 equals the pack's finished attributes.bin."""
    src = _copy_global()
    result = part1.run(src, PACK, {}, tempfile.mkdtemp())
    assert result["dropped"] == {"visualrgbtweaker/default (no such class)": 48}, result["dropped"]
    assert result["applied"] == 1028, result["applied"]
    easy = tempfile.mkdtemp()
    for n in ("fe_attrib.bin", "gameplay.bin"):
        shutil.copy(os.path.join(src, n), os.path.join(easy, n))
    shutil.copy(EASY_ATTR, os.path.join(easy, "attributes.bin"))
    a = part1.unpack(os.path.dirname(result["attributes_bin"]), tempfile.mkdtemp())
    b = part1.unpack(easy, tempfile.mkdtemp())
    assert vlt_diff.diff(a, b) == {}


def test_only_attributes_bin_is_returned_and_source_untouched():
    src = _copy_global()
    before = {n: open(os.path.join(src, n), "rb").read() for n in os.listdir(src)}
    result = part1.run(src, PACK, {}, tempfile.mkdtemp())
    assert os.path.basename(result["attributes_bin"]) == "attributes.bin"
    assert {n: open(os.path.join(src, n), "rb").read() for n in os.listdir(src)} == before


def test_ours_against_result_is_the_66_entries():
    src = _copy_global()
    result = part1.run(src, PACK, {}, tempfile.mkdtemp())
    d = vlt_diff.diff(part1.unpack(src, tempfile.mkdtemp()),
                      part1.unpack(os.path.dirname(result["attributes_bin"]), tempfile.mkdtemp()))
    assert {k: len(v[2]) for k, v in d.items()} == {"emitterdata": 37, "emittergroup": 4, "light_flares_cg": 15,
                                                    "timeofdaylighting": 6, "visuallook": 4}
    assert all(not v[0] and not v[1] for v in d.values())
