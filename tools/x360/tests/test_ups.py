import os
import tempfile
import zlib

import ups

PACK_UPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".superpowers",
                        "visual-research", "x360-complex", "Install-Part-3.ups")


def _files(**contents):
    d = tempfile.mkdtemp()
    for name, data in contents.items():
        open(os.path.join(d, name), "wb").write(data)
    return lambda n: os.path.join(d, n)


def _roundtrip(a, b):
    p = _files(a=a, patch=ups.create(a, b))
    info = ups.apply_file(p("patch"), p("a"), p("o"))
    assert open(p("o"), "rb").read() == b
    assert info["crc_out"] == zlib.crc32(b)


def test_same_size_changes_at_start_and_end():
    a = bytes(range(256)) * 4
    b = bytearray(a)
    b[0] ^= 0xFF
    b[-1] ^= 0x01
    b[500] = 0
    _roundtrip(a, bytes(b))


def test_growing_and_shrinking():
    _roundtrip(b"hello world", b"hello world, and more")
    _roundtrip(b"hello world, and more", b"hello")


def test_identical_files():
    _roundtrip(b"same" * 100, b"same" * 100)


def test_wrong_input_is_refused_and_nothing_written():
    p = _files(a=b"zzzzzz", patch=ups.create(b"abcdef", b"abXdef"))
    try:
        ups.apply_file(p("patch"), p("a"), p("o"))
    except ups.Mismatch as e:
        assert "input" in str(e)
    else:
        raise AssertionError("expected Mismatch")
    assert not os.path.exists(p("o")) and not os.path.exists(p("o") + ".part")


def test_corrupt_patch_is_refused():
    patch = bytearray(ups.create(b"abcdef", b"abXdef"))
    patch[6] ^= 1
    p = _files(a=b"abcdef", patch=bytes(patch))
    try:
        ups.apply_file(p("patch"), p("a"), p("o"))
    except ups.Mismatch as e:
        assert "patch" in str(e)
    else:
        raise AssertionError("expected Mismatch")


def test_applying_twice_is_refused():
    p = _files(a=b"abXdef", patch=ups.create(b"abcdef", b"abXdef"))  # input already patched
    try:
        ups.apply_file(p("patch"), p("a"), p("o"))
    except ups.Mismatch as e:
        assert "already" in str(e)
    else:
        raise AssertionError("expected Mismatch")


def test_pack_patch_header():
    """Known answer, read on 2026-10-15."""
    info = ups.read(open(PACK_UPS, "rb").read())
    assert (info["in_size"], info["out_size"]) == (532663556, 532663556)
    assert (info["crc_in"], info["crc_out"], info["crc_patch"]) == (0xBD947661, 0xAE90F386, 0x36873054)
    assert len(info["records"]) == 899
    assert sum(len(x) for _, x in info["records"]) == 1873
