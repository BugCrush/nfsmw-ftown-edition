"""build_package.py: the public .ini changes and the forbidden-content check."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_package  # noqa: E402

REPO = build_package.REPO
GAME_SCRIPTS = os.path.join(REPO, "Need For Speed Most Wanted Black Edition", "scripts")


def _read(name):
    return open(os.path.join(GAME_SCRIPTS, name), "rb").read()


def test_release_ini_has_no_home():
    out = build_package.release_ini("FTownLoader.ini", _read("FTownLoader.ini"))
    assert b"SafeHouseIcon = 0\r\n" in out
    text, floats = build_package.forbidden_patterns()
    assert text, "release/private/forbidden.json is needed for this test"
    for t in text:
        assert t.lower() not in out.lower(), t
    assert out.count(b"\r\n") == out.count(b"\n"), "CRLF kept"


def test_release_ini_telemetry_off():
    out = build_package.release_ini("InputBridge.ini", _read("InputBridge.ini"))
    assert b"\r\nLog = 0\r\n" in out and b"..\\..\\telemetry" not in out
    assert b"StateChanges = 0" in out
    assert out.count(b"\r\n") == out.count(b"\n")


def test_release_ini_music_folder_in_game():
    out = build_package.release_ini("MusicBridge.ini", _read("MusicBridge.ini"))
    assert b"Folder = ..\\CUSTOM SONGS\r\n" in out and b"Calls = 0" in out


def test_release_ini_carstable_comment():
    out = build_package.release_ini("CarStable.ini", _read("CarStable.ini"))
    assert b"the user" not in out and b"Known = 0x0B28303D" in out


def test_forbidden_check_finds_home_and_names():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "ok.txt"), "wb").write(b"fine")
    assert build_package.forbidden_hits(d) == []
    text, floats = build_package.forbidden_patterns()
    open(os.path.join(d, "bad.ini"), "wb").write(b"x = " + text[0] + b"\r\n")
    open(os.path.join(d, "bad.bin"), "wb").write(b"\0\0" + floats[0] + b"\0")
    open(os.path.join(d, "GfxProbe.asi"), "wb").write(b"x")
    hits = build_package.forbidden_hits(d)
    for name in ("bad.ini", "bad.bin", "GfxProbe.asi"):
        assert any(name in h for h in hits), hits
