"""part2.run's edge cases with a stand-in for Binarius (fast): relative target paths, a failure that still
changed files, refusing while the game runs. The real Binarius run is in test_part2.py."""
import os
import subprocess
import tempfile

import files
import part2

LAUNCHER = '[VERSN1]\r\n\r\n{\r\n  "Usage": "User",\r\n  "Game": "MostWanted",\r\n  "Directory": "",\r\n' \
           '  "Endscript": "ModData\\script.end",\r\n  "Files": [\r\n    "GLOBAL\\GLOBALB.LZC"\r\n  ]\r\n}\r\n'


def _pack_and_game():
    root = tempfile.mkdtemp()
    pack, game = os.path.join(root, "pack"), os.path.join(root, "game")
    os.makedirs(os.path.join(pack, "ModData"))
    open(os.path.join(pack, "Install-Part-2.end"), "w", newline="").write(LAUNCHER)
    open(os.path.join(pack, "ModData", "script.end"), "w", newline="").write("[VERSN2]\nversion 2.8.3\n\n// x\n")
    open(os.path.join(pack, "ModData", "null.bin"), "wb").write(b"0")
    for sub in ("GLOBAL", "FRONTEND"):
        os.makedirs(os.path.join(game, sub))
    open(os.path.join(game, "GLOBAL", "GlobalB.lzc"), "wb").write(b"before")
    return root, pack, game


class FakeBinarius:
    """Replaces subprocess.run for part2: records the arguments, changes a file, then succeeds or times out."""

    def __init__(self, game, fail=False):
        self.game, self.fail, self.args = game, fail, None

    def __call__(self, args, **kw):
        self.args = args
        open(os.path.join(self.game, "GLOBAL", "GlobalB.lzc"), "wb").write(b"after")
        if self.fail:
            raise subprocess.TimeoutExpired(args, 1800)
        return subprocess.CompletedProcess(args, 0, "Script script.end has been successfully applied.", "")


def _with_fake(fake, fn):
    real = part2.subprocess.run
    part2.subprocess.run = fake
    try:
        return fn()
    finally:
        part2.subprocess.run = real


def test_relative_target_gives_binarius_absolute_existing_paths():
    root, pack, game = _pack_and_game()
    fake = FakeBinarius(game)
    cwd = os.getcwd()
    os.chdir(root)
    try:
        r = _with_fake(fake, lambda: part2.run("game", pack, {}, check_game=False))
    finally:
        os.chdir(cwd)
    launcher, script = fake.args[2], fake.args[3]
    assert os.path.isabs(launcher) and os.path.isabs(script), fake.args
    assert r["changed"] == [os.path.join("GLOBAL", "GlobalB.lzc")]


def test_failure_still_reports_what_changed_and_cleans_up():
    root, pack, game = _pack_and_game()
    fake = FakeBinarius(game, fail=True)
    try:
        _with_fake(fake, lambda: part2.run(game, pack, {}, check_game=False))
    except part2.Failed as e:
        assert e.changed == [os.path.join("GLOBAL", "GlobalB.lzc")], e.changed
        assert "Timeout" in str(e) or "timed out" in str(e), str(e)
    else:
        raise AssertionError("expected part2.Failed")
    for leftover in ("_ChoicesX360", "ModData", part2.LAUNCHER):
        assert not os.path.exists(os.path.join(game, leftover)), leftover


def test_refuses_while_game_runs_before_touching_anything():
    root, pack, game = _pack_and_game()
    real = files.game_running
    files.game_running = lambda: True
    try:
        part2.run(game, pack, {})
    except part2.Failed as e:
        assert "running" in str(e) and e.changed == []
    else:
        raise AssertionError("expected part2.Failed")
    finally:
        files.game_running = real
    assert sorted(os.listdir(game)) == ["FRONTEND", "GLOBAL"]
