"""profiles.py and tools/controls/mwsave.py: our controller layout in existing profile saves, the journal's record of
each changed save, and uninstall putting a save back only if it was not played since (synthetic saves and folders)."""
import hashlib
import os
import struct
import tempfile

from ftedition import __main__ as cli
from ftedition import journal, profiles, steps

import mwsave

# The game's generic defaults (what a new profile got before the fix), type and index per action.
GENERIC = [(2, 0), (2, 2), (4, 0), (5, 0), (2, 1), (2, 3), (2, 6), (0, 0), (0, 0), (2, 5), (3, 0), (3, 2), (3, 3), (3, 1),
           (0, 0), (0, 0), (2, 4), (0, 0), (2, 7)]
KEYS = [0xC8, 0xD0, 0xCB, 0xCD, 0x39, 0x9D, 0x38, 0x1D, 0x2A, 0x13, 0x1C, 0x30, 0x32, 0x0F, 0x14, 0x2E, 0x26, 0x19, 0x01]


def make_save(block_at=mwsave.BLOCK_OFFSET, pad_hash=0x54245655, seed=b"career"):
    """A save shaped like v1.3's: header, filler, the controls block (hash + 19 records), MD5."""
    data = bytearray(63596)
    data[:4] = b"20CM"
    struct.pack_into("<III", data, 4, len(data), 8, len(data) - 36)
    for i in range(60, block_at, 7):  # some non-zero filler that is not binding-shaped
        data[i] = (seed[i % len(seed)] * 31 + i) & 0xFF
    struct.pack_into("<I", data, block_at, pad_hash)
    for i in range(19):
        rec = block_at + 4 + i * 48
        struct.pack_into("<12I", data, rec, 1, KEYS[i], 0, 1 if i in (5, 6) else 0, 0x22 if i == 5 else 0x2D if i == 6 else 0,
                         0, GENERIC[i][0], 0, GENERIC[i][1], 0, 0, 0)
    struct.pack_into("<I", data, block_at + 4 + 19 * 48, 0xD93645BF)  # what follows the block in real saves
    data[-16:] = mwsave.checksum(data)
    return bytes(data)


def _game(saves):
    g = os.path.join(tempfile.mkdtemp(), "My Game")
    os.makedirs(g)
    open(os.path.join(g, "speed.exe"), "wb").write(b"exe")
    for name, data in saves.items():
        d = os.path.join(g, "SAVE", "NFS Most Wanted", name)
        os.makedirs(d)
        open(os.path.join(d, name), "wb").write(data)
    return g


def _read(g, name):
    return open(os.path.join(g, "SAVE", "NFS Most Wanted", name, name), "rb").read()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def test_layout_written_only_into_controller_slots():
    before = make_save()
    assert not mwsave.has_layout(before)
    after = mwsave.with_layout(before)
    assert mwsave.has_layout(after) and len(after) == len(before)
    table = mwsave.parse(after)  # checksum valid
    assert table == mwsave.BLOCK_OFFSET + 8
    assert mwsave.bindings(after, table) == [mwsave.LAYOUT[a] for a in mwsave.ACTIONS]
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    slots = set()
    for i in range(19):
        rec = table + i * 48
        slots.update(range(rec + mwsave.TYPE_OFS, rec + mwsave.SECOND_OFS + 12))
    slots.update(range(len(before) - 16, len(before)))
    assert set(changed) <= slots, "only controller slots and the MD5 change"
    assert mwsave.with_layout(after) == after, "applying twice changes nothing"


def test_layout_matches_the_users_profile_layout():
    # the layout the user plays with, as tools/mw-controls.py showed it on the clean test's profile (2026-11-07)
    want = [(7, 0), (5, 2), (4, 0), (5, 0), (2, 1), (2, 2), (2, 0), (7, 1), (6, 1), (2, 6), (3, 0), (3, 2), (3, 3), (3, 1),
            (2, 9), (2, 5), (2, 4), (2, 3), (2, 7)]
    assert [mwsave.LAYOUT[a] for a in mwsave.ACTIONS] == want


def test_table_found_for_any_pad_and_elsewhere():
    for h in (0x54245655, 0x3F5996E0, 0xFFFFFFFF):
        s = make_save(pad_hash=h)
        assert mwsave.parse(s) == mwsave.BLOCK_OFFSET + 8, hex(h)
    moved = make_save(block_at=0xE000)
    assert mwsave.parse(moved) == 0xE008
    assert mwsave.has_layout(mwsave.with_layout(moved))


def test_damaged_or_foreign_saves_refused():
    s = bytearray(make_save())
    s[100] ^= 1
    for bad in (bytes(s), b"not a save at all" * 10):
        try:
            mwsave.parse(bad)
        except mwsave.SaveError:
            continue
        raise AssertionError("accepted a save it doesn't understand")


def _install_profiles(g, answer=True):
    j = journal.Journal.open(g)
    ctx = steps.Ctx(g, "payload", "work", {}, j, log=lambda m: None)
    ctx.profiles = answer
    with j.step("profiles", []):
        steps.run_profiles(ctx)
    j.finish({"profiles": ctx.profile_results})
    return ctx.profile_results


def test_install_writes_layout_with_backups():
    generic, ours = make_save(), mwsave.with_layout(make_save(seed=b"other"))
    broken = bytearray(make_save())
    broken[-1] ^= 0xFF
    g = _game({"Alice": generic, "Bob": ours, "Carol": bytes(broken)})
    res = _install_profiles(g)
    rel = "SAVE/NFS Most Wanted/%s/%s"
    assert res[rel % ("Alice", "Alice")] == "changed", res
    assert res[rel % ("Bob", "Bob")] == "already", res
    assert res[rel % ("Carol", "Carol")].startswith("skipped"), res
    assert mwsave.has_layout(_read(g, "Alice")) and _read(g, "Bob") == ours and _read(g, "Carol") == bytes(broken)
    backup = os.path.join(g, journal.FOLDER, "profiles", "SAVE", "NFS Most Wanted", "Alice", "Alice")
    assert open(backup, "rb").read() == generic
    import json
    data = json.load(open(os.path.join(g, journal.FOLDER, journal.JOURNAL), encoding="utf-8"))
    assert list(data["profiles"]) == [rel % ("Alice", "Alice")]
    assert data["profiles"][rel % ("Alice", "Alice")] == {"before": _sha(generic), "after": _sha(_read(g, "Alice"))}
    assert not data["backed"] and not data["created"], "saves are not install files"


def test_uninstall_restores_unplayed_profile():
    generic = make_save()
    g = _game({"Alice": generic})
    _install_profiles(g)
    r = journal.uninstall(g)
    assert _read(g, "Alice") == generic
    assert r["profiles_restored"] == ["SAVE/NFS Most Wanted/Alice/Alice"] and not r["profiles_kept"], r
    assert not os.path.exists(os.path.join(g, journal.FOLDER))


def test_uninstall_keeps_played_profile():
    generic = make_save()
    g = _game({"Alice": generic, "Dave": make_save(seed=b"dave")})
    _install_profiles(g)
    played = mwsave.with_layout(make_save(seed=b"more career"))  # the game rewrote it after a session
    open(os.path.join(g, "SAVE", "NFS Most Wanted", "Alice", "Alice"), "wb").write(played)
    os.remove(os.path.join(g, "SAVE", "NFS Most Wanted", "Dave", "Dave"))  # the player deleted a profile
    r = journal.uninstall(g)
    assert _read(g, "Alice") == played, "a played save is the player's: kept"
    assert not os.path.exists(os.path.join(g, "SAVE", "NFS Most Wanted", "Dave", "Dave")), "not brought back"
    assert sorted(r["profiles_kept"]) == ["SAVE/NFS Most Wanted/Alice/Alice", "SAVE/NFS Most Wanted/Dave/Dave"], r
    assert not r["profiles_restored"]


def test_player_says_no():
    generic = make_save()
    g = _game({"Alice": generic})
    res = _install_profiles(g, answer=False)
    assert res == {} and _read(g, "Alice") == generic


def test_no_save_folder():
    g = _game({})
    assert _install_profiles(g) == {}


def test_profiles_step_place():
    import yaml
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(repo, "release", "installer", "cars-release.yaml"), encoding="utf-8") as f:
        order = list(yaml.safe_load(f).items())
    st = steps.all_steps(order)
    ids = [s.id for s in st]
    assert ids.index("our_plugins") < ids.index("profiles") < ids.index("settings")
    assert st[ids.index("profiles")].may_change == [] and "our_plugins" in st[ids.index("profiles")].after


def test_cli_profiles_answer():
    seen = {}

    def fake_install(game, roots, profiles=True):
        seen["profiles"] = profiles
        return [], {}
    real = cli.app.install
    cli.app.install = fake_install
    try:
        assert cli.main(["install", "--game", "g", "--downloads", "d"]) == 0 and seen["profiles"] is True
        assert cli.main(["install", "--game", "g", "--downloads", "d", "--profiles", "no"]) == 0 and seen["profiles"] is False
    finally:
        cli.app.install = real
