"""The controller bindings in an NFS Most Wanted (v1.3) profile save: read, check, and write our layout.

Used by tools/mw-controls.py (the command line) and by the mod package's installer (release/installer/ftedition/
profiles.py). Nothing here touches files: every function takes and returns the save's bytes.

Save format (worked out from real saves; see docs/dev-log.md "Bindings" and docs/controller-notes.md):
  - bytes 0-3 "20CM", 4-7 file size, 8-11 version (8), 12-15 data length
  - the last 16 bytes are MD5(bytes 52 .. size-16)
  - the controls block: a 4-byte hash of the controller's product name when the profile was saved (speed.exe
    0x460BC0; "Controller (Controller(XBOX 360 For Windows))" gives 0x54245655, no controller 0xFFFFFFFF), then 19
    records of 48 bytes in the Controls menu's order. A record is four slots of (type, device, code), 12 bytes each:
    keyboard, second key, controller, second controller (speed.exe's live table at 0x91F418 has the same records with
    a 4-byte name pointer in front). TABLE below points at the first record's keyboard code (+4), so per record:
    +0 keyboard key (DirectInput scancode), +8/+12 second key (flag, scancode), +20 controller type, +24 controller
    device, +28 controller index, +32..+43 second controller.
    Controller binding types: 0 none, 2 button (index = button), 3 D-pad (0 up, 1 right, 2 down, 3 left), 4/5 linear
    axis negative/positive half (index 0 X, 1 Y, 2 Z), 6/7 rotation axis negative/positive half (index 0 Rx, 1 Ry,
    2 Rz). The Controls menu also displays 4/5 with index 3-5 as Rx/Ry/Rz, but races don't read them.
  - In every v1.3 save seen the block starts at byte 0xF4C8 (the file is 63,596 bytes); find_table() checks the
    records' shape there and searches the file only if that fails, and refuses anything ambiguous.
"""
import hashlib
import struct

ACTIONS = [
    "Accelerate", "Brake / Reverse", "Steer Left", "Steer Right", "Handbrake", "Speedbreaker", "N2O",
    "Shift Down", "Shift Up", "Reset Car Position", "Engage Event", "View Blacklist", "View World Map",
    "View SMS Messages", "Play Next Song", "Change Camera View", "Look Behind", "Pull Camera Back", "Pause",
]
RECORD_SIZE = 48
BLOCK_OFFSET = 0xF4C8       # the controls block (hash, then the records) in v1.3 saves
TYPE_OFS, DEVICE_OFS, INDEX_OFS, SECOND_OFS = 20, 24, 28, 32

NONE, BUTTON, DPAD, AXIS_NEG, AXIS_POS, ROT_NEG, ROT_POS = 0, 2, 3, 4, 5, 6, 7
BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "Back", "Start", "LS click", "RS click"]
DPAD_DIRS = ["up", "right", "down", "left"]
# With InputBridge: Z = LT, Rx = RT, both resting at centre (pressed = positive half);
# Ry = right stick Y (up = negative), Rz = right stick X.
AXES = ["LS X", "LS Y", "LT (Z)"]
ROT_AXES = ["RT (Rx)", "RS Y (Ry)", "RS X (Rz)"]

# The chosen layout: Xbox 360 console layout with A and B swapped (N2O on A, handbrake on B). InputBridge writes the
# same into the game's defaults ([Controls] DefaultLayout, kDefaultLayout in input/src/InputBridge.cpp).
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
    "Pull Camera Back": (BUTTON, 3),      # Y
    "Pause": (BUTTON, 7),                 # Start
}


class SaveError(Exception):
    pass


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


def checksum(data):
    return hashlib.md5(bytes(data[52:-16])).digest()


def _records_ok(data, table):
    """Whether 19 records at `table` (the first record's keyboard code) look like bindings."""
    start = table - 4  # the first record's keyboard type
    if start < 56 or start + 19 * RECORD_SIZE > len(data) - 16:
        return False
    keyboard = 0
    for i in range(19):
        slots = struct.unpack_from("<12I", data, start + i * RECORD_SIZE)
        k_type, k_code, k_dev, s_flag, s_code, s_dev = slots[:6]
        c_type, c_dev, c_index, c2_type, c2_dev, c2_index = slots[6:]
        if k_type not in (0, 1) or k_code > 0xFF or k_dev or s_flag not in (0, 1) or s_code > 0xFF or s_dev:
            return False
        if c_type > 9 or c_dev > 15 or c_index > 255 or c2_type > 9 or c2_dev > 15 or c2_index > 255:
            return False
        keyboard += k_type == 1
    return keyboard >= 10


def find_table(data):
    """The offset of the first record's keyboard code (the old tool's 'table'); raises SaveError."""
    fixed = BLOCK_OFFSET + 8
    if _records_ok(data, fixed):
        return fixed
    hits = [t for t in range(60, len(data), 4) if _records_ok(data, t)]
    if len(hits) != 1:
        raise SaveError("couldn't locate the controls table (%d candidates)" % len(hits))
    return hits[0]


def parse(data):
    """Checks a whole save; returns the table offset. Raises SaveError for anything not understood."""
    if len(data) < 100 or data[:4] != b"20CM" or struct.unpack_from("<I", data, 4)[0] != len(data):
        raise SaveError("doesn't look like an NFS Most Wanted save")
    if checksum(data) != bytes(data[-16:]):
        raise SaveError("checksum mismatch; refusing to touch a save we don't understand")
    return find_table(data)


def bindings(data, table):
    """[(type, index)] of the 19 controller slots."""
    return [(struct.unpack_from("<I", data, table + i * RECORD_SIZE + TYPE_OFS)[0],
             struct.unpack_from("<I", data, table + i * RECORD_SIZE + INDEX_OFS)[0]) for i in range(19)]


def has_layout(data):
    """Whether the save's controller slots are exactly our layout (second controller slots empty)."""
    table = parse(data)
    for i, action in enumerate(ACTIONS):
        rec = table + i * RECORD_SIZE
        kind, dev, index = struct.unpack_from("<3I", data, rec + TYPE_OFS)
        if (kind, index) != LAYOUT[action] or dev or any(struct.unpack_from("<3I", data, rec + SECOND_OFS)):
            return False
    return True


def with_layout(data):
    """The save with our layout in the 19 controller slots (device 0, second controller slots cleared) and its MD5
    recomputed; keyboard bindings and everything else unchanged."""
    data = bytearray(data)
    table = parse(data)
    for i, action in enumerate(ACTIONS):
        kind, index = LAYOUT[action]
        rec = table + i * RECORD_SIZE
        struct.pack_into("<3I", data, rec + TYPE_OFS, kind, 0, index)
        struct.pack_into("<3I", data, rec + SECOND_OFS, 0, 0, 0)
    data[-16:] = checksum(data)
    return bytes(data)


def show_lines(data, table):
    out = []
    for i, action in enumerate(ACTIONS):
        rec = table + i * RECORD_SIZE
        kind, index = struct.unpack_from("<I", data, rec + TYPE_OFS)[0], struct.unpack_from("<I", data, rec + INDEX_OFS)[0]
        key = struct.unpack_from("<I", data, rec)[0]
        out.append(f"  {action:<20} controller: {describe(kind, index):<16} (type {kind}, index {index})   key: 0x{key:02X}")
    return out
