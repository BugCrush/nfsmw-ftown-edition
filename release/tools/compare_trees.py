"""Compares the installed clean test copy with the user's main game, file by file (read only on both).

    python release/tools/compare_trees.py [<installed> [<reference>]]

Prints, for every file that differs or exists on one side only, its path and the reason, grouped by the expected
differences (EXPECTED below: diagnostics, logs, the user's saves, settings we ship differently) and the rest. Exit 1
if anything outside EXPECTED differs.
"""
import fnmatch
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
INSTALLED = os.path.join(REPO, "Need For Speed Most Wanted Black Edition - clean test")
REFERENCE = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")

# (pattern, why): differences we expect between a fresh public install and the user's own game
EXPECTED = [
    ("FTownEdition-backup/**", "the installer's backup and record (only in the test copy)"),
    ("SAVE/**", "the user's profile (a new player has none)"),
    ("*.log", "logs written by playing"),
    ("scripts/*.log", "logs written by playing"),
    ("gfx-captures/**", "GfxProbe's screenshots (diagnostic, not shipped)"),
    ("fps-capture/**", "FpsRecorder's recordings (diagnostic, not shipped)"),
    ("scripts/GfxProbe.*", "diagnostic, not shipped"),
    ("scripts/ExitTrace.*", "diagnostic, not shipped"),
    ("scripts/FpsRecorder.*", "diagnostic, not shipped"),
    ("scripts/MusicBridge.songs.ini", "the user's per-song settings"),
    ("scripts/FTownTimes.txt", "the user's race times"),
    ("scripts/CarStable.defaults.bin", "written by CarStable at the game's start"),
    ("scripts/CarStable.fingerprints", "written by CarStable at the game's start"),
    ("scripts/CarStable.pending", "written by CarStable at the game's start"),
    ("scripts/FTownLoader.asi", "the public build: no built-in safe-house place"),
    ("scripts/FTownLoader.ini", "the public .ini: safe-house icon off, no place"),
    ("scripts/InputBridge.ini", "public defaults: telemetry off, state-change logging off"),
    ("scripts/MusicBridge.ini", "public defaults: songs folder in the game folder, call logging off"),
    ("scripts/CarStable.ini", "a comment reworded"),
    ("scripts/NFSMostWanted.WidescreenFix.ini.bak", "the repo's copy of the repack's .ini (not the game's)"),
    ("scripts/ftown-reloc.bun", "not shipped"),
    ("scripts/ftown-slab.bun", "not shipped"),
]


EXPECTED.append(("scripts/NFSMWUnlimiter.asi", "the official Unlimiter release (the user's game runs our build from source)"))

# files that may differ in a few bytes only, with the reason; checked byte by byte (same size, differences inside
# the given range, or at most `limit` single bytes)
NEAR = {
    "GLOBAL/attributes.bin": ((0xB0, 0xD0), None, "Attribulator writes the time of its run into the header; contents equal"),
    "GLOBAL/FE_ATTRIB.bin": ((0xB0, 0xD0), None, "Attribulator writes the time of its run into the header; contents equal"),
    "GLOBAL/DYNTEX.BIN": (None, None, "textures"),
    # every texture file Binarius writes can show this, run to run (stage 1's part 2, the Unlimiter)
    "GLOBAL/HUDTEXTURESPHOTOFINISH.BIN": (None, None, "textures"),
    "GLOBAL/HUDTEXRACE.BIN": (None, None, "textures"),
    "GLOBAL/InGameA.bun": (None, None, "textures"),
    "GLOBAL/InGameB.lzc": (None, None, "textures"),
    "FRONTEND/FrontB.lzc": (None, None, "textures"),
    "CARS/TEXTURES.BIN": (None, None, "textures"),
}


def same_textures(pa, pb):
    """True when two texture packs hold the same textures (pixels and headers after decompression)."""
    sys.path.insert(0, os.path.join(REPO, "tools", "carbuild"))
    from textures import read_textures
    try:
        a, b = read_textures(open(pa, "rb").read()), read_textures(open(pb, "rb").read())
    except (ValueError, IndexError, KeyError):
        return 0, False  # not a plain texture pack: reported as unexpected
    if len(a.textures) != len(b.textures):
        return 0, False
    n = 0
    for x, y in zip(a.textures, b.textures):
        if x.blob != y.blob:
            n += 1
            if x.name_hash != y.name_hash or x.data is None or x.data != y.data or x.header != y.header:
                return n, False
    return n, True


def near(rel, pa, pb):
    rule = NEAR.get(rel)
    if not rule:
        return None
    a, b = open(pa, "rb").read(), open(pb, "rb").read()
    if len(a) != len(b):
        return None
    diffs = [i for i in range(len(a)) if a[i] != b[i]]
    rng, limit, reason = rule
    if reason == "textures":
        n, ok = same_textures(pa, pb)
        return ("%d bytes in %d Binarius-compressed texture blocks; decompressed pixels and headers identical"
                % (len(diffs), n)) if ok else None
    if rng and all(rng[0] <= i < rng[1] for i in diffs):
        return "%s (%d bytes at 0x%X..0x%X)" % (reason, len(diffs), diffs[0], diffs[-1])
    if limit and len(diffs) <= limit:
        return "%s (%d bytes)" % (reason, len(diffs))
    return None


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tree(root):
    out = {}
    for dp, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = p
    return out


def why(rel):
    for pat, reason in EXPECTED:
        if pat.endswith("/**") and rel.lower().startswith(pat[:-2].lower()):
            return reason
        if fnmatch.fnmatch(rel.lower(), pat.lower()) and rel.count("/") == pat.count("/"):
            return reason
    return None


def main(argv):
    a = argv[0] if argv else INSTALLED
    b = argv[1] if len(argv) > 1 else REFERENCE
    ta, tb = tree(a), tree(b)
    lower_a = {k.lower(): k for k in ta}
    lower_b = {k.lower(): k for k in tb}
    expected, unexpected, same = [], [], 0
    for rel in sorted(set(lower_a) | set(lower_b)):
        ka, kb = lower_a.get(rel), lower_b.get(rel)
        if ka and kb:
            if os.path.getsize(ta[ka]) == os.path.getsize(tb[kb]) and sha(ta[ka]) == sha(tb[kb]):
                same += 1
                continue
            what = "differs"
        else:
            what = "only in the test copy" if ka else "only in the main game"
        rel_name = ka or kb
        reason = why(rel_name) or (near(rel_name, ta[ka], tb[kb]) if ka and kb else None)
        (expected if reason else unexpected).append((rel_name, what, reason))
    print("identical: %d files" % same)
    print("expected differences: %d" % len(expected))
    for rel, what, reason in expected:
        print("  %-60s %-22s %s" % (rel, what, reason))
    print("UNEXPECTED differences: %d" % len(unexpected))
    for rel, what, _ in unexpected:
        print("  %-60s %s" % (rel, what))
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
