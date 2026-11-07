"""The Black Edition's GLOBAL\\GlobalMemoryFile.bin caches whole files and the start of others; the cached copies win
over the files on disk. Known answers from the real file (2026-10-18)."""
import os
import struct
import tempfile

import memfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BACKUP = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - backup before x360")
ORIGINAL = os.path.join(BACKUP, "GLOBAL", "GlobalMemoryFile.bin")


def test_bstringhash_known_names():
    assert memfile.bhash(r"GLOBAL\GLOBALB.LZC") == 0x4C939B36
    assert memfile.bhash(r"GLOBAL\ATTRIBUTES.BIN") == 0x9775379A
    assert memfile.bhash(r"GLOBAL\DYNTEX.BIN") == 0x29EE288F


def test_entries_of_the_black_edition_file():
    entries = memfile.entries(open(ORIGINAL, "rb").read())
    assert len(entries) == 24
    by_hash = {e["hash"]: e for e in entries}
    assert by_hash[0x9775379A]["size"] == 689728 and by_hash[0x9775379A]["offset"] == 0x380
    assert by_hash[0x4C939B36]["size"] == 1520744


def test_disable_changes_only_the_named_hashes():
    data = open(ORIGINAL, "rb").read()
    out = memfile.disable(data, [r"GLOBAL\GlobalB.lzc", r"GLOBAL\DYNTEX.BIN"], used_hashes=set())
    diff = [i for i in range(len(data)) if data[i] != out[i]]
    assert len(out) == len(data) and len(diff) == 8
    names = {e["hash"] for e in memfile.entries(out)}
    assert 0x4C939B36 not in names and 0x29EE288F not in names and 0x9775379A in names


def test_disable_never_picks_a_hash_a_file_has():
    data = open(ORIGINAL, "rb").read()
    out = memfile.disable(data, [r"GLOBAL\GlobalB.lzc"], used_hashes={0xDEAD0001, 0xDEAD0002})
    assert 0xDEAD0003 in {e["hash"] for e in memfile.entries(out)}


def test_disable_refuses_a_name_not_cached():
    data = open(ORIGINAL, "rb").read()
    try:
        memfile.disable(data, [r"GLOBAL\NOSUCH.BIN"], used_hashes=set())
    except ValueError as e:
        assert "NOSUCH" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_disable_twice_is_a_no_op_error():
    data = open(ORIGINAL, "rb").read()
    out = memfile.disable(data, [r"GLOBAL\GlobalB.lzc"], used_hashes=set())
    try:
        memfile.disable(out, [r"GLOBAL\GlobalB.lzc"], used_hashes=set())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError: already disabled")


def test_rejects_a_file_that_is_not_a_memory_file():
    try:
        memfile.entries(b"\0" * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
