"""stages.py on small fake game folders: refusals, idempotence, and that only the named settings change."""
import json
import os
import tempfile
import zlib

import files
import stage1
import stages

STAGE1_TRACK = b"pretend track"  # tests patch STAGE1_TRACK_CRC to this file's CRC32


def _game(track=STAGE1_TRACK, ini=None):
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "TRACKS"))
    os.makedirs(os.path.join(root, "scripts"))
    open(os.path.join(root, "TRACKS", "STREAML2RA.BUN"), "wb").write(track)
    if ini is not None:
        open(os.path.join(root, "scripts", "Mod.ini"), "wb").write(ini)
    return root


def _build():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "Mod.asi"), "wb").write(b"MZ plugin")
    open(os.path.join(d, "Mod.ini"), "wb").write(b"[MAIN]\r\nA = 1\r\nB = 1\r\n")
    return d


def _run(game, build, record=None, check_game=False):
    record = record or os.path.join(tempfile.mkdtemp(), "rec")
    return stages.install_companion(
        game, [(os.path.join(build, "Mod.asi"), r"scripts\Mod.asi")],
        {r"scripts\Mod.ini": (os.path.join(build, "Mod.ini"), {("MAIN", "B"): "0"})},
        record, check_game=check_game)


def _with_crc(fn):
    real = stages.STAGE1_TRACK_CRC
    stages.STAGE1_TRACK_CRC = zlib.crc32(STAGE1_TRACK)
    try:
        return fn()
    finally:
        stages.STAGE1_TRACK_CRC = real


def test_refuses_without_stage1():
    game = _game(track=b"original track")
    try:
        _with_crc(lambda: stages.require_stage1(game))
    except stage1.Refused as e:
        assert "stage 1" in str(e)
    else:
        raise AssertionError("expected Refused")


def test_installs_files_and_settings_with_a_record():
    game, build = _game(), _build()
    record = os.path.join(tempfile.mkdtemp(), "rec")
    s = _with_crc(lambda: _run(game, build, record))
    assert open(os.path.join(game, "scripts", "Mod.asi"), "rb").read() == b"MZ plugin"
    assert open(os.path.join(game, "scripts", "Mod.ini"), "rb").read() == b"[MAIN]\r\nA = 1\r\nB = 0\r\n"
    rels = [e["rel"] for e in s["files"]]
    assert r"scripts\Mod.asi" in rels and r"scripts\Mod.ini" in rels
    assert json.load(open(os.path.join(record, "stage-progress.json"))) == s["files"]


def test_second_run_changes_nothing():
    game, build = _game(), _build()
    _with_crc(lambda: _run(game, build))
    before = {n: files.sha256(os.path.join(game, "scripts", n)) for n in os.listdir(os.path.join(game, "scripts"))}
    s = _with_crc(lambda: _run(game, build))
    assert s["files"] == []
    after = {n: files.sha256(os.path.join(game, "scripts", n)) for n in os.listdir(os.path.join(game, "scripts"))}
    assert before == after


def test_keeps_the_users_other_keys():
    game, build = _game(ini=b"[MAIN]\r\nA = 1\r\nB = 1\r\nFoo = 7\r\n"), _build()
    _with_crc(lambda: _run(game, build))
    assert open(os.path.join(game, "scripts", "Mod.ini"), "rb").read() == b"[MAIN]\r\nA = 1\r\nB = 0\r\nFoo = 7\r\n"


def test_refuses_while_game_runs():
    game, build = _game(), _build()
    real = files.game_running
    files.game_running = lambda: True
    try:
        _with_crc(lambda: _run(game, build, check_game=True))
    except (stage1.Refused, files.Refused):
        pass
    else:
        raise AssertionError("expected a refusal")
    finally:
        files.game_running = real
    assert not os.path.exists(os.path.join(game, "scripts", "Mod.asi"))


def test_refuses_a_used_record_folder():
    game, build = _game(), _build()
    record = os.path.join(tempfile.mkdtemp(), "rec")
    _with_crc(lambda: _run(game, build, record))
    try:
        _with_crc(lambda: _run(game, build, record))
    except stage1.Refused as e:
        assert "already" in str(e)
    else:
        raise AssertionError("expected Refused")
