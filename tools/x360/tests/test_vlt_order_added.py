"""vlt_order.match_added: a database with added collections (new cars) keeps the original's export order and table
sizes for everything the original has; the added collections come after. Known answer: an Attribulator edit of the
game's current attributes.bin that adds one pvehicle collection ("carstabletest", under "racers")."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import part1  # noqa: E402
import vlt_order  # noqa: E402
import vlthash  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RECORDS = os.path.join(ROOT, "telemetry", "cars-records", "game")
WORK = os.path.join(tempfile.gettempdir(), "nfsmwbe-vlt-added-fixture")
PVEHICLE = 0x4A97EC8F


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _frozen_global():
    """The game's database files as they were before any car, from the install records (frozen): attributes.bin from
    before the Challenger (the Unlimiter does not change it), fe_attrib.bin from before the Unlimiter, gameplay.bin
    from the game (no install changes it)."""
    d = os.path.join(WORK, "frozen")
    if not os.path.isdir(d):
        os.makedirs(d)
        shutil.copy(os.path.join(RECORDS, "challenger71-20261031", "before", "GLOBAL", "attributes.bin"),
                    os.path.join(d, "attributes.bin"))
        shutil.copy(os.path.join(RECORDS, "unlimiter-20261031", "before", "GLOBAL", "FE_ATTRIB.bin"),
                    os.path.join(d, "fe_attrib.bin"))
        shutil.copy(os.path.join(ROOT, "Need For Speed Most Wanted Black Edition", "GLOBAL", "gameplay.bin"),
                    os.path.join(d, "gameplay.bin"))
    return d


GAME_GLOBAL = None  # set on first use


def _game_global():
    global GAME_GLOBAL
    if GAME_GLOBAL is None:
        GAME_GLOBAL = _frozen_global()
    return GAME_GLOBAL


def _edited():
    """The original attributes.bin with one pvehicle collection added by Attribulator (made once, then reused)."""
    out = os.path.join(WORK, "out", "main", "attributes.bin")
    if not os.path.exists(out):
        src = os.path.join(WORK, "in")
        part1._copy_inputs(_game_global(), src)
        script = os.path.join(WORK, "add.nfsms")
        with open(script, "w", newline="\n") as f:
            f.write("add_node pvehicle racers carstabletest\n")
        part1._attribulator("apply-script-bin", "-i", src, "-o", os.path.join(WORK, "out"), "-p", "MOST_WANTED",
                            "-s", script)
    return _read(out)


def test_match_added_keeps_original_walk():
    ref, edited = _read(os.path.join(_game_global(), "attributes.bin")), _edited()
    out = vlt_order.match_added(edited, ref)
    ref_walk, out_walk = vlt_order.walk_orders(ref), vlt_order.walk_orders(out)
    new_key = vlthash.vlt32("carstabletest")
    for cls, keys in ref_walk.items():
        kept = [k for k in out_walk[cls] if k in set(keys)]
        assert kept == keys, "class %08X walks its original collections differently" % cls
    assert new_key in out_walk[PVEHICLE]
    assert len(out_walk[PVEHICLE]) == len(ref_walk[PVEHICLE]) + 1
    # the original's exports come first, in the original's order
    po, pm = vlt_order.parse(ref), vlt_order.parse(out)
    n = len(po["exports"])
    assert [vlt_order.ident(e) for e in pm["exports"][:n]] == [vlt_order.ident(e) for e in po["exports"]]
    assert vlt_order.ident(pm["exports"][n]) == ("collection", PVEHICLE, new_key)


def test_match_added_refuses_missing():
    ref, edited = _read(os.path.join(_game_global(), "attributes.bin")), _edited()
    try:
        vlt_order.match_added(ref, edited)  # the "edited" lacks carstabletest, which its "reference" has
    except ValueError as e:
        assert "missing" in str(e)
    else:
        raise AssertionError("match_added accepted a file that lacks a collection of the reference")


def test_match_unchanged_still_refuses_extra():
    ref, edited = _read(os.path.join(_game_global(), "attributes.bin")), _edited()
    try:
        vlt_order.match(edited, ref)
    except ValueError as e:
        assert "extra" in str(e)
    else:
        raise AssertionError("match accepted an added collection")


def test_match_added_on_a_vault_without_a_database_export():
    # fe_attrib.bin (the frontend vault) has classes and collections but no database entry of its own
    names = {n.lower(): n for n in os.listdir(_game_global())}
    fe = _read(os.path.join(_game_global(), names["fe_attrib.bin"]))
    assert vlt_order.parse(fe)["db_pos"] is None
    assert vlt_order.match_added(fe, fe) == fe
