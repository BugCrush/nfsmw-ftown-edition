"""gamecheck.py: the refusals before any change, on synthetic game folders."""
import hashlib
import os
import stat
import struct
import tempfile

from ftedition import gamecheck

CODE = bytes(range(256)) * 4  # pretend code section


def _pe(code=CODE):
    """A minimal PE32 file: one section .text at RVA 0x1000, raw offset 0x400, image base 0x400000."""
    pe_off = 0x80
    head = bytearray(0x400)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, pe_off)
    head[pe_off:pe_off + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", head, pe_off + 4, 0x14C, 1, 0, 0, 0, 0xE0, 0x010F)
    opt = pe_off + 24
    struct.pack_into("<H", head, opt, 0x10B)
    struct.pack_into("<I", head, opt + 28, 0x400000)
    sec = opt + 0xE0
    head[sec:sec + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", head, sec + 8, len(code), 0x1000, len(code), 0x400)
    return bytes(head) + code


def _site(va, n, code=CODE):
    off = va - 0x401000
    return {"va": va, "len": n, "sha256": hashlib.sha256(code[off:off + n]).hexdigest()}


SITES = [_site(0x401010, 16), _site(0x401200, 32)]


def _game(name="game"):
    root = os.path.join(tempfile.mkdtemp(), name)
    os.makedirs(os.path.join(root, "GLOBAL"))
    open(os.path.join(root, "speed.exe"), "wb").write(_pe())
    open(os.path.join(root, "GLOBAL", "attributes.bin"), "wb").write(b"database")
    return root


ORIG = {"GLOBAL/attributes.bin": [8, hashlib.sha256(b"database").hexdigest()]}


def _refused(fn, *words):
    try:
        fn()
    except gamecheck.Refused as e:
        for w in words:
            assert w in str(e), str(e)
        return
    raise AssertionError("not refused")


def test_good_game_passes():
    gamecheck.check(_game(), SITES, ORIG, running=lambda: False)


def test_paths_with_spaces():
    gamecheck.check(_game("Need For Speed Most Wanted ünï"), SITES, ORIG, running=lambda: False)


def test_wrong_exe_refused():
    g = _game()
    os.remove(os.path.join(g, "speed.exe"))
    _refused(lambda: gamecheck.check(g, SITES, ORIG, running=lambda: False), "speed.exe")
    code = bytearray(CODE)
    code[0x10] ^= 0xFF
    open(os.path.join(g, "speed.exe"), "wb").write(_pe(bytes(code)))
    _refused(lambda: gamecheck.check(g, SITES, ORIG, running=lambda: False), "1.3")


def test_large_address_flag_ignored():
    g = _game()
    data = bytearray(open(os.path.join(g, "speed.exe"), "rb").read())
    data[0x80 + 22] |= 0x20
    open(os.path.join(g, "speed.exe"), "wb").write(bytes(data))
    gamecheck.check(g, SITES, ORIG, running=lambda: False)


def test_running_refused():
    _refused(lambda: gamecheck.check(_game(), SITES, ORIG, running=lambda: True), "running")


def test_changed_original_refused():
    g = _game()
    open(os.path.join(g, "GLOBAL", "attributes.bin"), "wb").write(b"modded db")
    _refused(lambda: gamecheck.check(g, SITES, ORIG, running=lambda: False), "GLOBAL/attributes.bin", "Black Edition")


def test_readonly_game_refused():
    g = _game()
    real = gamecheck._writable
    gamecheck._writable = lambda path: False
    try:
        _refused(lambda: gamecheck.check(g, SITES, ORIG, running=lambda: False), "write")
    finally:
        gamecheck._writable = real


def test_writable_probe_leaves_nothing():
    g = _game()
    before = sorted(os.listdir(g))
    assert gamecheck._writable(g)
    assert sorted(os.listdir(g)) == before
