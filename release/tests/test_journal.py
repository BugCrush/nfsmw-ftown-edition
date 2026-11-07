"""journal.py: backups, created files, outside changes and a byte-exact uninstall, on synthetic game folders."""
import hashlib
import os
import tempfile

from ftedition import journal


def _game():
    g = os.path.join(tempfile.mkdtemp(), "My Game")
    for rel, data in {"speed.exe": b"exe", "GLOBAL/a.bin": b"aaa", "GLOBAL/b.bin": b"bbb", "TRACKS/t.bun": b"track",
                      "SAVE/profile": b"save"}.items():
        p = os.path.join(g, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
    return g


def _tree(g):
    out = {}
    for dp, _, names in os.walk(g):
        for n in names:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, g).replace(os.sep, "/")] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def _w(g, rel, data):
    p = os.path.join(g, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)


def _install(g):
    j = journal.Journal.open(g)
    with j.step("one", ["GLOBAL/*"]):
        _w(g, "GLOBAL/a.bin", b"changed")
        _w(g, "GLOBAL/new.bin", b"new")
    with j.step("two", ["GLOBAL/*", "scripts/**"]):
        _w(g, "GLOBAL/a.bin", b"changed again")
        _w(g, "scripts/sub/Mod.asi", b"plugin")
    j.finish({"note": "test"})
    return j


def test_uninstall_byte_exact():
    g = _game()
    before = _tree(g)
    _install(g)
    assert _tree(g) != before
    report = journal.uninstall(g)
    assert _tree(g) == before, (_tree(g), before)
    assert not os.path.exists(os.path.join(g, "scripts")), "created folders removed"
    assert report["restored"] == ["GLOBAL/a.bin"], report


def test_backup_on_first_touch_only():
    g = _game()
    _install(g)
    b = os.path.join(g, journal.FOLDER, "backup", "GLOBAL", "a.bin")
    assert open(b, "rb").read() == b"aaa"
    assert not os.path.exists(os.path.join(g, journal.FOLDER, "backup", "GLOBAL", "b.bin")), "unchanged: no backup kept"


def test_outside_change_fails():
    g = _game()
    j = journal.Journal.open(g)
    try:
        with j.step("bad", ["GLOBAL/*"]):
            _w(g, "TRACKS/t.bun", b"oops")
    except journal.Failed as e:
        assert "TRACKS/t.bun" in str(e)
    else:
        raise AssertionError("a change outside the step's area must fail")


def test_journal_restores_after_failed_step():
    g = _game()
    before = _tree(g)
    j = journal.Journal.open(g)
    try:
        with j.step("crash", ["GLOBAL/*"]):
            _w(g, "GLOBAL/b.bin", b"half written")
            _w(g, "GLOBAL/partial.bin", b"x")
            raise RuntimeError("tool failed")
    except RuntimeError:
        pass
    try:
        journal.Journal.open(g)
    except journal.Refused as e:
        assert "uninstall" in str(e)
    else:
        raise AssertionError("an install that stopped half-way must refuse a new install")
    journal.uninstall(g)
    assert _tree(g) == before


def test_second_install_refused():
    g = _game()
    _install(g)
    try:
        journal.Journal.open(g)
    except journal.Refused as e:
        assert "already installed" in str(e)
    else:
        raise AssertionError("second install must be refused")


def test_uninstall_without_record_refused():
    try:
        journal.uninstall(_game())
    except journal.Refused as e:
        assert "not installed" in str(e)
    else:
        raise AssertionError("must refuse")


def test_uninstall_reports_edited_file():
    g = _game()
    before = _tree(g)
    _install(g)
    _w(g, "scripts/sub/Mod.asi", b"player edited")
    _w(g, "GLOBAL/a.bin", b"player edited too")
    report = journal.uninstall(g)
    assert set(report["edited_after_install"]) == {"scripts/sub/Mod.asi", "GLOBAL/a.bin"}, report
    assert _tree(g) == before


def test_game_made_files_kept():
    g = _game()
    _install(g)
    _w(g, "scripts/FTownTimes.txt", b"times")
    _w(g, "SAVE/profile", b"saved again")
    journal.uninstall(g)
    assert open(os.path.join(g, "scripts", "FTownTimes.txt"), "rb").read() == b"times"
    assert open(os.path.join(g, "SAVE", "profile"), "rb").read() == b"saved again"


def test_work_folder_ignored():
    g = _game()
    j = journal.Journal.open(g)
    with j.step("w", ["GLOBAL/*"]):
        _w(g, journal.WORK + "/tmp.bin", b"scratch")
    j.finish({})
