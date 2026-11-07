import json
import os
import tempfile

import files


def _tree(spec):
    root = tempfile.mkdtemp()
    for rel, data in spec.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
    return root


def test_case_insensitive_target_is_replaced_not_duplicated():
    pack = _tree({"ModData/Files/GLOBAL/GLOBALB.LZC": b"new"})
    game = _tree({"GLOBAL/GlobalB.lzc": b"old"})
    steps = files.plan(["file_copy ModData\\Files\\GLOBAL\\GLOBALB.LZC GLOBAL\\GLOBALB.LZC"], pack, game)
    assert steps[0]["kind"] == "replaces" and steps[0]["dst"].endswith(os.path.join("GLOBAL", "GlobalB.lzc"))
    files.install(steps, game, os.path.join(game, "record.json"), check_game=False)
    assert os.listdir(os.path.join(game, "GLOBAL")) == ["GlobalB.lzc"]
    assert open(os.path.join(game, "GLOBAL", "GlobalB.lzc"), "rb").read() == b"new"


def test_new_file_goes_under_existing_folder_case():
    pack = _tree({"x.fx.o": b"fx"})
    game = _tree({"Fx/keep.txt": b"k"})
    steps = files.plan(["file_copy x.fx.o FX\\COMPILED\\x.fx.o"], pack, game)
    assert steps[0]["kind"] == "adds"
    assert steps[0]["dst"] == os.path.join(game, "Fx", "COMPILED", "x.fx.o")


def test_record_lists_old_hash_before_copy():
    pack = _tree({"a.bin": b"new", "b.bin": b"added"})
    game = _tree({"x/a.bin": b"old"})
    steps = files.plan(["file_copy a.bin x\\a.bin", "file_copy b.bin x\\b.bin"], pack, game)
    files.install(steps, game, os.path.join(game, "rec.json"), check_game=False)
    rec = json.load(open(os.path.join(game, "rec.json")))
    assert [r["rel"] for r in rec] == ["x\\a.bin", "x\\b.bin"]
    assert rec[0]["old_sha256"] is not None and rec[1]["old_sha256"] is None


def test_second_run_changes_nothing():
    pack = _tree({"a.bin": b"new"})
    game = _tree({"x/a.bin": b"old"})
    acts = ["file_copy a.bin x\\a.bin"]
    files.install(files.plan(acts, pack, game), game, os.path.join(game, "r1.json"), check_game=False)
    steps = files.plan(acts, pack, game)
    assert steps[0]["kind"] == "same"
    r = files.install(steps, game, os.path.join(game, "r2.json"), check_game=False)
    assert r == {"copied": 0, "skipped": 1}


def test_stops_at_first_failure_with_complete_record():
    pack = _tree({"a.bin": b"1", "c.bin": b"3"})
    game = _tree({})
    steps = files.plan(["file_copy a.bin a.bin", "file_copy missing.bin b.bin", "file_copy c.bin c.bin"], pack, game)
    try:
        files.install(steps, game, os.path.join(game, "rec.json"), check_game=False)
    except files.Failed as e:
        assert "missing.bin" in str(e)
    else:
        raise AssertionError("expected Failed")
    rec = json.load(open(os.path.join(game, "rec.json")))
    assert [r["rel"] for r in rec] == ["a.bin"]
    assert not os.path.exists(os.path.join(game, "c.bin"))


def test_refuses_while_game_runs():
    real = files.game_running
    files.game_running = lambda: True
    try:
        files.install([], tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "r.json"))
    except files.Refused:
        pass
    else:
        raise AssertionError("expected Refused")
    finally:
        files.game_running = real


def test_folder_create_and_unknown_action():
    pack, game = _tree({}), _tree({})
    assert files.plan(["folder_create FX\\COMPILED"], pack, game) == []
    try:
        files.plan(["file_move a b"], pack, game)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_sha256_bytes_matches_file_hash():
    root = _tree({"a.bin": b"hello"})
    assert files.sha256_bytes(b"hello") == files.sha256(os.path.join(root, "a.bin"))
    assert files.sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_game_running_reads_tasklist():
    assert files.game_running() in (True, False)
