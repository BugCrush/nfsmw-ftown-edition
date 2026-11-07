"""Read and write the controller bindings stored in an NFS Most Wanted profile save.

    python tools/mw-controls.py show [profile]
    python tools/mw-controls.py apply [profile]      # writes LAYOUT below

The profile defaults to the only one in the game's SAVE folder. The game must be closed:
it rewrites the save from memory. Before writing, the original is copied to
tools/save-backups/<profile>-<timestamp> (not committed).

Save format (worked out from a real save, see docs/dev-log.md, "The game"):
  - bytes 0-3 "20CM", 4-7 file size, 8-11 version (8), 12-15 data length
  - the last 16 bytes are MD5(bytes 52 .. size-16)
  - the controls table is 19 records of 48 bytes, in the Controls menu's order. Per record
    (offsets from the record start): +0 keyboard key (DirectInput scancode),
    +8/+12 secondary key (flag, scancode), +20 controller binding type, +28 controller index.
    Controller binding types: 0 none, 2 button (index = button), 3 D-pad (0 up, 1 right,
    2 down, 3 left), 4/5 linear axis negative/positive half (index 0 X, 1 Y, 2 Z),
    6/7 rotation axis negative/positive half (index 0 Rx, 1 Ry, 2 Rz).
    The Controls menu also displays 4/5 with index 3-5 as Rx/Ry/Rz, but races don't read them.
"""
import datetime
import hashlib
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAVE_DIR = ROOT / "Need For Speed Most Wanted Black Edition" / "SAVE" / "NFS Most Wanted"
BACKUP_DIR = ROOT / "tools" / "save-backups"

ACTIONS = [
    "Accelerate", "Brake / Reverse", "Steer Left", "Steer Right", "Handbrake", "Speedbreaker", "N2O",
    "Shift Down", "Shift Up", "Reset Car Position", "Engage Event", "View Blacklist", "View World Map",
    "View SMS Messages", "Play Next Song", "Change Camera View", "Look Behind", "Pull Camera Back", "Pause",
]
RECORD_SIZE = 48
TABLE_MARKER = struct.pack("<II", 0x54245655, 1)  # precedes the first record
TYPE_OFS, INDEX_OFS = 20, 28

NONE, BUTTON, DPAD, AXIS_NEG, AXIS_POS, ROT_NEG, ROT_POS = 0, 2, 3, 4, 5, 6, 7
BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "Back", "Start", "LS click", "RS click"]
DPAD_DIRS = ["up", "right", "down", "left"]
# With InputBridge: Z = LT, Rx = RT, both resting at centre (pressed = positive half);
# Ry = right stick Y (up = negative), Rz = right stick X.
AXES = ["LS X", "LS Y", "LT (Z)"]
ROT_AXES = ["RT (Rx)", "RS Y (Ry)", "RS X (Rz)"]

# The chosen layout: Xbox 360 console layout with A and B swapped (N2O on A, handbrake on B).
LAYOUT = {
    "Accelerate": (ROT_POS, 0),           # RT
    "Brake / Reverse": (AXIS_POS, 2),     # LT
    "Steer Left": (AXIS_NEG, 0),          # left stick left
    "Steer Right": (AXIS_POS, 0),         # left stick right
    "Handbrake": (BUTTON, 1),             # B
    "Speedbreaker": (BUTTON, 2),          # X
    "N2O": (BUTTON, 0),                   # A
    "Shift Down": (ROT_POS, 1),           # right stick down
    "Shift Up": (ROT_NEG, 1),             # right stick up
    "Reset Car Position": (BUTTON, 6),    # Back
    "Engage Event": (DPAD, 0),            # D-pad up
    "View Blacklist": (DPAD, 2),          # D-pad down
    "View World Map": (DPAD, 3),          # D-pad left
    "View SMS Messages": (DPAD, 1),       # D-pad right
    "Play Next Song": (BUTTON, 9),        # right stick click
    "Change Camera View": (BUTTON, 5),    # RB
    "Look Behind": (BUTTON, 4),           # LB
    "Pull Camera Back": (BUTTON, 3),       # Y
    "Pause": (BUTTON, 7),                 # Start
}


def describe(kind, index):
    if kind == NONE:
        return "---"
    if kind == BUTTON:
        return BUTTONS[index] if index < len(BUTTONS) else f"button {index}"
    if kind == DPAD:
        return f"D-pad {DPAD_DIRS[index]}" if index < 4 else f"D-pad {index}"
    if kind in (ROT_NEG, ROT_POS):
        axis = ROT_AXES[index] if index < len(ROT_AXES) else f"rotation {index}"
        return f"{axis} {'-' if kind == ROT_NEG else '+'}"
    if kind in (AXIS_NEG, AXIS_POS):
        axis = AXES[index] if index < len(AXES) else f"axis {index}"
        return f"{axis} {'-' if kind == AXIS_NEG else '+'}"
    return f"type {kind} index {index}"


def find_profile(name):
    if name:
        path = SAVE_DIR / name / name
        if not path.exists():
            sys.exit(f"No profile save at {path}")
        return path
    profiles = [p / p.name for p in SAVE_DIR.iterdir() if (p / p.name).is_file()]
    if len(profiles) != 1:
        sys.exit(f"Found {len(profiles)} profiles in {SAVE_DIR}; name one explicitly.")
    return profiles[0]


def checksum(data):
    return hashlib.md5(data[52:-16]).digest()


def load(path):
    data = bytearray(path.read_bytes())
    if data[:4] != b"20CM" or struct.unpack_from("<I", data, 4)[0] != len(data):
        sys.exit(f"{path} doesn't look like an NFS Most Wanted save.")
    if checksum(data) != data[-16:]:
        sys.exit(f"{path}: checksum mismatch; refusing to touch a save we don't understand.")
    marker = data.find(TABLE_MARKER)
    if marker < 0 or data.find(TABLE_MARKER, marker + 1) >= 0:
        sys.exit("Couldn't locate the controls table uniquely.")
    return data, marker + len(TABLE_MARKER)


def show(data, table):
    for i, action in enumerate(ACTIONS):
        rec = table + i * RECORD_SIZE
        kind, index = struct.unpack_from("<I", data, rec + TYPE_OFS)[0], struct.unpack_from("<I", data, rec + INDEX_OFS)[0]
        key = struct.unpack_from("<I", data, rec)[0]
        print(f"  {action:<20} controller: {describe(kind, index):<16} (type {kind}, index {index})   key: 0x{key:02X}")


def game_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq speed.exe"], capture_output=True, text=True).stdout
    return "speed.exe" in out.lower()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("show", "apply"):
        sys.exit(__doc__)
    path = find_profile(sys.argv[2] if len(sys.argv) > 2 else None)
    data, table = load(path)
    print(f"{path}")

    if sys.argv[1] == "show":
        show(data, table)
        return

    if game_running():
        sys.exit("Close the game first: it overwrites the save with its own copy of the bindings.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{path.name}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(path, backup)
    print(f"Backup: {backup}")

    for i, action in enumerate(ACTIONS):
        kind, index = LAYOUT[action]
        rec = table + i * RECORD_SIZE
        struct.pack_into("<I", data, rec + TYPE_OFS, kind)
        struct.pack_into("<I", data, rec + INDEX_OFS, index)
    data[-16:] = checksum(data)
    path.write_bytes(data)
    print("Applied layout:")
    show(data, table)


if __name__ == "__main__":
    main()
