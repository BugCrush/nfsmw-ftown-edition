"""Part 2 of the pack's Complex Installation: Binarius applies ModData\\script.end to the game's packed files.

How Binarius's command line works (read in nlgxzef/Binarius 7145caf, Binary/Program.cs and Binary/CLI.cs):
`Binarius.exe <user|modder> <launcher> <endscript>` loads the launcher (a VERSN1 JSON file), resolves its
"Directory" relative to the launcher's folder, loads the "Files" and "Links" it lists, applies the endscript,
and saves. It accepts only launchers marked "Usage": "Modder" (the window's user mode takes "User" ones and
otherwise runs the same load / apply / save). The pack's Install-Part-2.end is a "User" launcher, so we write
an identical one marked "Modder" (same Files, Links and endscript) beside the files.

The endscript asks `file_exists absolute _ChoicesX360\\<option>.bin` to know which options were chosen
(part 1 normally leaves those markers), and finds its textures and materials relative to its own folder, so
ModData is copied next to the target for the run and removed afterwards, with the markers and the launcher.

Usage: python part2.py <target root> <pack root> [option=0|1 ...]
"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import files  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BINARIUS_DIR = os.path.join(ROOT, ".tools", "binarius-2.10.4")
DOTNET_X86 = os.path.join(ROOT, ".tools", "dotnet-x86")
MARKER_OPTIONS = ("lightmaterials", "lightflares", "particletextures", "platforms", "x360textures", "uitextures")
LAUNCHER = "x360-part2.end"


def _hashes(root):
    out = {}
    for sub in ("GLOBAL", "FRONTEND"):
        for dirpath, _, names in os.walk(os.path.join(root, sub)):
            for n in names:
                p = os.path.join(dirpath, n)
                out[os.path.relpath(p, root)] = files.sha256(p)
    return out


def _launcher(pack_root, target_root):
    """The pack's VERSN1 launcher with Usage set to Modder and Directory set to the target folder."""
    # Binarius reads these values without JSON unescaping (the pack's file has bare backslashes), so the file is
    # edited as text: a JSON-escaped "GLOBAL\\GLOBALB.LZC" would become a different file name inside Binarius
    # and every script command on it would fail with "was never loaded".
    with open(os.path.join(pack_root, "Install-Part-2.end"), encoding="utf-8-sig") as f:
        text = f.read()
    usage, directory = '"Usage": "User"', '"Directory": ""'
    if text.count(usage) != 1 or text.count(directory) != 1:
        raise RuntimeError("Install-Part-2.end is not the expected launcher (Usage/Directory lines)")
    return text.replace(usage, '"Usage": "Modder"').replace(directory, '"Directory": "%s"' % os.path.abspath(target_root))


def _drop_version_line(script_path):
    """Binarius 2.10.4's command line never sets its own version (Program.cs sets Endscript.Version.Value only on
    the window's path), so a `version x.y.z` line fails with a null reference. The line only checks that
    Binarius is at least that version; 2.10.4 is newer than the 2.8.3 the pack asks for. Only our temporary
    copy of the script is changed."""
    with open(script_path, "rb") as f:
        lines = f.read().split(b"\n")
    kept = [l for l in lines if not l.strip().lower().startswith(b"version ")]
    if len(lines) - len(kept) != 1:
        raise RuntimeError("expected exactly one version line in %s, found %d" % (script_path, len(lines) - len(kept)))
    with open(script_path, "wb") as f:
        f.write(b"\n".join(kept))


class Failed(Exception):
    """Part 2 did not complete. `changed` lists the files Binarius changed anyway (it saves even after errors),
    so they can be recorded and restored."""

    def __init__(self, message, changed):
        super().__init__(message)
        self.changed = changed


def run(target_root, pack_root, marker_options, check_game=True):
    # Absolute paths: Binarius runs in its own folder and opens the launcher and script relative to it.
    target_root, pack_root = os.path.abspath(target_root), os.path.abspath(pack_root)
    if check_game and files.game_running():
        raise Failed("speed.exe is running: close the game first", [])
    created = [os.path.join(target_root, n) for n in ("_ChoicesX360", "ModData", LAUNCHER)]
    for p in created:
        if os.path.exists(p):
            raise Failed("%s already exists in the target; remove it first" % p, [])
    before = _hashes(target_root)
    main_log = error_log = output = ""
    failure = None
    try:
        os.makedirs(created[0])
        for m in MARKER_OPTIONS:
            if marker_options.get(m):
                shutil.copy(os.path.join(pack_root, "ModData", "null.bin"), os.path.join(created[0], m + ".bin"))
        shutil.copytree(os.path.join(pack_root, "ModData"), created[1],
                        ignore=shutil.ignore_patterns("Files"))  # Files is part 1's copies, not needed here
        _drop_version_line(os.path.join(created[1], "script.end"))
        with open(created[2], "w", encoding="utf-8", newline="\r\n") as f:
            f.write(_launcher(pack_root, target_root))
        for log in ("MainLog.txt", "EndError.log"):
            if os.path.exists(os.path.join(BINARIUS_DIR, log)):
                os.remove(os.path.join(BINARIUS_DIR, log))
        env = dict(os.environ, **{"DOTNET_ROOT(x86)": DOTNET_X86, "DOTNET_ROLL_FORWARD": "Major"})
        p = subprocess.run([os.path.join(BINARIUS_DIR, "Binarius.exe"), "modder", created[2],
                            os.path.join(created[1], "script.end")],
                           cwd=BINARIUS_DIR, env=env, capture_output=True, text=True, timeout=1800,
                           stdin=subprocess.DEVNULL)
        read = lambda n: open(os.path.join(BINARIUS_DIR, n), encoding="utf-8", errors="replace").read() \
            if os.path.exists(os.path.join(BINARIUS_DIR, n)) else ""
        main_log, error_log = read("MainLog.txt"), read("EndError.log")
        output = p.stdout + p.stderr
        if p.returncode != 0 or "successfully applied" not in output:
            error_log = (error_log + "\n" + output).strip() or "Binarius exit code %d" % p.returncode
    except Exception as e:  # a timeout, a missing file, ...: still find out what changed, then report
        failure = e
    finally:
        for c in created:
            if os.path.isdir(c):
                shutil.rmtree(c)
            elif os.path.exists(c):
                os.remove(c)
    after = _hashes(target_root)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if failure is not None:
        raise Failed("part 2 failed: %s: %s" % (type(failure).__name__, failure), changed) from failure
    return {"changed": changed, "main_log": main_log, "error_log": error_log, "output": output}


if __name__ == "__main__":
    opts = {m: True for m in MARKER_OPTIONS}
    opts.update({k: v == "1" for k, v in (a.split("=") for a in sys.argv[3:])})
    r = run(sys.argv[1], sys.argv[2], opts)
    print(r["output"])
    print("changed:", *r["changed"], sep="\n  ")
    print("errors:", r["error_log"] or "none")
