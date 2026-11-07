"""Read and write the controller bindings stored in an NFS Most Wanted profile save.

    python tools/mw-controls.py show [profile] [--save-dir <SAVE\\NFS Most Wanted folder>]
    python tools/mw-controls.py apply [profile] [--save-dir <...>]     # writes the layout (tools/controls/mwsave.py)

The profile defaults to the only one in the game's SAVE folder (the main game's, or --save-dir). The game must be
closed: it rewrites the save from memory. Before writing, the original is copied to
tools/save-backups/<profile>-<timestamp> (not committed).

The save format, the layout and the code that reads and writes them are in tools/controls/mwsave.py (shared with the
mod package's installer). The layout: RT accelerate, LT brake, left stick steer, B handbrake, X speedbreaker,
A nitrous, right stick down/up shift, Back reset, D-pad events/blacklist/map/SMS, RS click next song, RB camera,
LB look behind, Y pull camera back, Start pause.
"""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "controls"))
import mwsave  # noqa: E402
from mwsave import ACTIONS, LAYOUT, describe, checksum  # noqa: E402,F401  (kept importable from here)

SAVE_DIR = ROOT / "Need For Speed Most Wanted Black Edition" / "SAVE" / "NFS Most Wanted"
BACKUP_DIR = ROOT / "tools" / "save-backups"


def find_profile(name, save_dir=SAVE_DIR):
    if name:
        path = save_dir / name / name
        if not path.exists():
            sys.exit(f"No profile save at {path}")
        return path
    profiles = [p / p.name for p in save_dir.iterdir() if (p / p.name).is_file()]
    if len(profiles) != 1:
        sys.exit(f"Found {len(profiles)} profiles in {save_dir}; name one explicitly.")
    return profiles[0]


def load(path):
    data = bytearray(path.read_bytes())
    try:
        table = mwsave.parse(data)
    except mwsave.SaveError as e:
        sys.exit(f"{path}: {e}")
    return data, table


def show(data, table):
    for line in mwsave.show_lines(data, table):
        print(line)


def game_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq speed.exe"], capture_output=True, text=True).stdout
    return "speed.exe" in out.lower()


def main():
    args = sys.argv[1:]
    save_dir = SAVE_DIR
    if "--save-dir" in args:
        i = args.index("--save-dir")
        save_dir = Path(args[i + 1])
        del args[i:i + 2]
    if not args or args[0] not in ("show", "apply"):
        sys.exit(__doc__)
    path = find_profile(args[1] if len(args) > 1 else None, save_dir)
    data, table = load(path)
    print(f"{path}")

    if args[0] == "show":
        show(data, table)
        print("  (our layout)" if mwsave.has_layout(data) else "  (not our layout)")
        return

    if game_running():
        sys.exit("Close the game first: it overwrites the save with its own copy of the bindings.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{path.name}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(path, backup)
    print(f"Backup: {backup}")
    new = mwsave.with_layout(data)
    path.write_bytes(new)
    print("Applied layout:")
    show(new, table)


if __name__ == "__main__":
    main()
