"""The game's car-stable fingerprint depends on the order in which it walks the pvehicle collections, which depends on
the order of the database's exports and on each class's table size. Known answers from the real files (2026-10-18)."""
import os

import vlt_order

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORIGINAL = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition - backup before x360", "GLOBAL", "attributes.bin")
# our Attribulator-edited database as installed on 2026-10-16 (sha256 847f1b55...), copied for the investigation
EDITED = os.path.join(ROOT, ".superpowers", "sdd", "x360-profile", "edited", "attributes.bin")
EASY = os.path.join(ROOT, ".superpowers", "visual-research", "x360-easy", "GLOBAL", "attributes.bin")
PVEHICLE = 0x4A97EC8F


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def test_exports_of_the_original():
    v = vlt_order.parse(_read(ORIGINAL))
    kinds = [e["kind"] for e in v["exports"]]
    assert len(kinds) == 2367
    assert kinds.count("database") == 1 and kinds.count("class") == 57 and kinds.count("collection") == 2309
    assert v["classes"][PVEHICLE]["capacity"] == 222
    assert sum(1 for e in v["exports"] if e["kind"] == "collection" and e["cls"] == PVEHICLE) == 113


def test_rewritten_databases_walk_pvehicle_differently():
    orig = vlt_order.walk_orders(_read(ORIGINAL))
    for other in (EDITED, EASY):
        if os.path.exists(other):
            assert vlt_order.walk_orders(_read(other))[PVEHICLE] != orig[PVEHICLE], other


def test_attribulator_output_shrinks_the_pvehicle_table():
    if os.path.exists(EDITED):
        assert vlt_order.parse(_read(EDITED))["classes"][PVEHICLE]["capacity"] == 113


def test_matching_the_original_with_itself_changes_nothing():
    data = _read(ORIGINAL)
    assert vlt_order.match(data, data) == data


def test_matched_file_walks_every_class_like_the_original():
    if not os.path.exists(EDITED):
        return
    orig, edited = _read(ORIGINAL), _read(EDITED)
    out = vlt_order.match(edited, orig)
    assert len(out) == len(edited)
    assert vlt_order.walk_orders(out) == vlt_order.walk_orders(orig)
    po, pm = vlt_order.parse(orig), vlt_order.parse(out)
    assert [vlt_order.ident(e) for e in pm["exports"]] == [vlt_order.ident(e) for e in po["exports"]]
    # the export entries are only permuted: same multiset of (id, type, size, offset) as the edited file
    pe = vlt_order.parse(edited)
    assert sorted(e["raw"] for e in pm["exports"]) == sorted(e["raw"] for e in pe["exports"])
    # outside the export table and the capacity words, not one byte changes
    allowed = set(range(pe["exp_pos"], pe["exp_pos"] + 20 * len(pe["exports"])))
    for c in pe["classes"].values():
        allowed |= set(range(c["cap_pos"], c["cap_pos"] + 4))
    allowed |= set(range(pe["db_pos"], pe["db_pos"] + 8))
    assert all(a == b for i, (a, b) in enumerate(zip(edited, out)) if i not in allowed)
