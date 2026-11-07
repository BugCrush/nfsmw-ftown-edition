"""Our controller layout in the player's existing profiles.

A new profile gets our layout from InputBridge ([Controls] DefaultLayout patches the game's defaults). A profile made
before the install keeps the bindings it was saved with, so the installer offers (default yes) to write our layout into
each profile in the game folder's SAVE\\NFS Most Wanted\\<name>\\<name> (the Widescreen Fix keeps saves there), and
nowhere else. The save format and the layout are tools/controls/mwsave.py's (the same code as tools/mw-controls.py):
only the 19 controller slots change and the save's MD5 is recomputed. Each changed save is backed up through the
journal first; uninstall puts it back only if the player has not played since.
"""
import os

from . import toolpaths  # noqa: F401  (sys.path for the repo tools)

import mwsave

SAVE_REL = "SAVE/NFS Most Wanted"


def find(game):
    """Relative paths ("SAVE/NFS Most Wanted/<name>/<name>") of the profile saves in the game folder."""
    root = os.path.join(game, *SAVE_REL.split("/"))
    if not os.path.isdir(root):
        return []
    return ["%s/%s/%s" % (SAVE_REL, n, n) for n in sorted(os.listdir(root)) if os.path.isfile(os.path.join(root, n, n))]


def apply(game, journal, log):
    """Writes our layout into every profile that lacks it. Returns {rel: "changed" | "already" | "skipped: why"}."""
    out = {}
    for rel in find(game):
        path = os.path.join(game, *rel.split("/"))
        name = rel.split("/")[-1]
        with open(path, "rb") as f:
            before = f.read()
        try:
            if mwsave.has_layout(before):
                out[rel] = "already"
                log("  profile %s: already has our controller layout" % name)
                continue
            after = mwsave.with_layout(before)
        except mwsave.SaveError as e:
            out[rel] = "skipped: %s" % e
            log("  profile %s: left as it is (%s)" % (name, e))
            continue
        journal.profile_backup(rel, before, after)
        with open(path, "wb") as f:
            f.write(after)
        out[rel] = "changed"
        log("  profile %s: our controller layout written (the original is kept for uninstall)" % name)
    if not out:
        log("  no profiles yet: a new profile gets our layout from InputBridge")
    return out
