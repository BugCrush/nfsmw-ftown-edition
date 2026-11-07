"""Shared by the later stages of the Xbox 360 pack install (plan docs/superpowers/plans/2026-10-18-x360-pack-part2.md):
check that stage 1 is installed, copy a stage's files through files.install (recorded, refuses while the game
runs), and set the named keys of its .ini files (CRLF kept, every other line untouched). A second run changes
nothing. The record is <record>/stage-progress.json (after every entry) and stage-summary.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import files  # noqa: E402
import stage1  # noqa: E402
import ups  # noqa: E402

STAGE1_TRACK_CRC = 0xAE90F386  # STREAML2RA.BUN after part 3


def require_stage1(target):
    track = files.find(target, r"TRACKS\STREAML2RA.BUN")
    if not track or ups.crc32_file(track) != STAGE1_TRACK_CRC:
        raise stage1.Refused("stage 1 is not installed in %s (the track file is not the patched one)" % target)


def install_companion(target, copies, inis, record_dir, check_game=True):
    """copies: [(source file, game-relative path)]; inis: {game-relative .ini: (default .ini, {(section, key): value})}.
    The default .ini is copied only when the game has none; existing values other than the named keys stay."""
    target, record_dir = os.path.abspath(target), os.path.abspath(record_dir)
    require_stage1(target)
    if check_game and files.game_running():
        raise stage1.Refused("speed.exe is running: close the game first")
    stage1.check_record_dir(record_dir)
    os.makedirs(record_dir, exist_ok=True)
    rec = stage1.Record(record_dir, "stage-progress.json")

    wanted = list(copies) + [(default, rel) for rel, (default, _s) in inis.items() if files.find(target, rel) is None]
    steps = []
    for src, rel in wanted:
        steps += files.plan(["file_copy %s %s" % (os.path.basename(src), rel)], os.path.dirname(src), target)
    step_record = os.path.join(record_dir, "copies.json")
    try:
        files.install(steps, target, step_record, check_game=check_game)
    finally:
        for e in json.load(open(step_record, encoding="utf-8")):
            rec.add(e["rel"], e["old_sha256"], e["new_sha256"])

    for rel, (_default, settings) in inis.items():
        path = files.find(target, rel)
        old = open(path, "rb").read()
        new = old
        for (section, key), value in settings.items():
            new = stage1.set_ini_value(new, section, key, value)
        if new != old:
            if check_game and files.game_running():
                raise stage1.Refused("speed.exe is running: close the game first")
            rec.add(rel, files.sha256_bytes(old), files.sha256_bytes(new))
            open(path, "wb").write(new)

    summary = {"target": target, "files": rec.entries}
    with open(os.path.join(record_dir, "stage-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary
