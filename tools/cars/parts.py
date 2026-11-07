"""The game's car part list (GLOBAL\\GlobalB.lzc, chunk 0x80034602) and the part indices a profile save uses.

A customisation record in the save stores its installed parts as positions in this list (docs/cars-notes.md). If
installing a car moves any part the save uses, the user's cars show other parts. Layout from Nikki's
DBModelPartManager (MostWanted): sub-blocks 0x34603 header, 0x34606 strings, 0x3460B models (one name hash per car
model), 0x34604 parts (14 bytes each: name hash u32, group u8, upgrade group u16, model index u8, debug name offset
u16 (x4 into strings), attribute offset u16, struct offset u16), grouped model by model.

    python tools/cars/parts.py diff <GlobalB.lzc before> <GlobalB.lzc after> <profile save>
        SAME, or one line per used index whose part changed (exit code 1).
    python tools/cars/parts.py count <GlobalB.lzc>
"""
import collections
import struct
import sys

PARTS_CHUNK = 0x80034602
SUB_STRINGS, SUB_MODELS, SUB_ARRAY = 0x34606, 0x3460B, 0x34604
RECORD = 14
# The save: the profile buffer's fingerprint is at file offset 0x5A2D, then the name (0x20), the playlist (0xF0), the
# options (0x84) and the car stable (0x8CC8) (UserProfile::LoadFromBuffer, 0x5ACBF1..0x5ACC64).
SAVE_FINGERPRINT = 0x5A2D
SAVE_STABLE = SAVE_FINGERPRINT + 4 + 0x20 + 0xF0 + 0x84
CUSTOM_OFS, CUSTOM_SIZE, CUSTOM_SLOTS = 0xFA0, 0x198, 139

Part = collections.namedtuple("Part", "index model model_hash name_hash name")


def _chunk(data):
    p = 0
    while p + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, p)
        if cid == PARTS_CHUNK:
            return p, size
        p += 8 + size
    raise ValueError("no car part chunk (0x80034602)")


def _subs(data):
    start, size = _chunk(data)
    subs, q = {}, start + 8
    while q + 8 <= start + 8 + size:
        cid, sz = struct.unpack_from("<II", data, q)
        subs.setdefault(cid, (q, sz))
        q += 8 + sz
    return subs


def read_parts_bytes(data):
    subs = _subs(data)
    s_at, s_size = subs[SUB_STRINGS]
    strings = data[s_at + 8:s_at + 8 + s_size]
    m_at, m_size = subs[SUB_MODELS]
    models = struct.unpack_from("<%dI" % (m_size // 4), data, m_at + 8)
    a_at, a_size = subs[SUB_ARRAY]
    out = []
    for i in range(a_size // RECORD):
        name_hash, _, _, model, name_ofs, _, _ = struct.unpack_from("<IBHBHHH", data, a_at + 8 + i * RECORD)
        end = strings.find(b"\0", name_ofs * 4)
        name = strings[name_ofs * 4:end].decode("latin-1")
        out.append(Part(i, model, models[model] if model < len(models) else None, name_hash, name))
    return out


def read_parts(globalb_lzc):
    return read_parts_bytes(open(globalb_lzc, "rb").read())


def save_indices(profile):
    """(VehicleKey of the car using it, customisation slot, part slot, part index) for every installed part."""
    s = open(profile, "rb").read()
    owner = {}
    for i in range(200):
        handle, _, vkey, _, custom, _ = struct.unpack_from("<IIIIBB", s, SAVE_STABLE + i * 0x14)
        if handle != 0xFFFFFFFF and custom != 0xFF:
            owner.setdefault(custom, vkey)
    out = []
    for c in range(75):
        rec = SAVE_STABLE + CUSTOM_OFS + c * CUSTOM_SIZE
        if s[rec + 0x194] == 0xFF:
            continue
        for slot, index in enumerate(struct.unpack_from("<%dh" % CUSTOM_SLOTS, s, rec)):
            if index >= 0:
                out.append((owner.get(c), c, slot, index))
    return out


def diff(before, after, used):
    """[(index, part before, part after)] for each used index whose part (model, name) differs or is gone."""
    changed = []
    for index in sorted({i for _, _, _, i in used}):
        a = before[index] if index < len(before) else None
        b = after[index] if index < len(after) else None
        key = lambda p: None if p is None else (p.model_hash, p.name_hash, p.name)
        if key(a) != key(b):
            changed.append((index, a, b))
    return changed


def insert_part_for_test(data, at):
    """A copy of the file's bytes with one made-up part inserted at position `at` (for tests only)."""
    data = bytearray(data)
    start, size = _chunk(data)
    a_at, a_size = _subs(bytes(data))[SUB_ARRAY]
    rec = bytearray(data[a_at + 8 + at * RECORD:a_at + 8 + (at + 1) * RECORD])
    struct.pack_into("<I", rec, 0, 0xDEADBEEF)
    pos = a_at + 8 + at * RECORD
    data[pos:pos] = rec
    struct.pack_into("<I", data, a_at + 4, a_size + RECORD)
    struct.pack_into("<I", data, start + 4, size + RECORD)
    return bytes(data)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "count":
        p = read_parts(sys.argv[2])
        print("%d parts, %d models" % (len(p), len({x.model for x in p})))
        return 0
    if len(sys.argv) != 5 or sys.argv[1] != "diff":
        sys.exit(__doc__)
    used = save_indices(sys.argv[4])
    changed = diff(read_parts(sys.argv[2]), read_parts(sys.argv[3]), used)
    if not changed:
        print("SAME (%d used indices, all name the same part)" % len({u[3] for u in used}))
        return 0
    for index, a, b in changed:
        print("index %d: %s -> %s" % (index, a and a.name, b and b.name))
    print("%d used indices changed" % len(changed))
    return 1


if __name__ == "__main__":
    sys.exit(main())
