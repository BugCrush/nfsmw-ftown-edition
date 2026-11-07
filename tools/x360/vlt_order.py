"""Make a rewritten GLOBAL\\attributes.bin load into the same in-memory tables as the original.

Why: the game fingerprints the profile save with a CRC32 of its default car stable
(cFrontendDatabase::iDefaultStableHash, built in FEPlayerCarDB::Default, speed.exe 0x590D30..0x591080). That stable
is filled by walking the pvehicle class's collection table in slot order (0x456B00 / 0x456B20). The table is a
hash map (insert 0x456220, grow 0x456390) whose start size comes from the class's load data (+4) and whose slot
order depends on the order the collections are inserted, which is the order of the vault's export table (ExpN,
walked by 0x457670). Attribulator and NFS-VltEd both rewrite the export table in a different order (Attribulator
also writes smaller table sizes), so the walk changes, the CRC changes, and the game rejects every existing save
as damaged even though no car changed.

match(edited, reference) returns the edited file with its export entries put in the reference's order (matched by
class key and collection key) and the table sizes copied from the reference. Nothing else changes.

Usage:
    python vlt_order.py check <attributes.bin> <reference attributes.bin>     classes whose walk differs
    python vlt_order.py match <edited attributes.bin> <reference> <out>
    python vlt_order.py match-added <edited attributes.bin> <reference> <out>   (the edited file adds collections)
"""
import struct
import sys

DATABASE, CLASS, COLLECTION = 0xCBBC628F, 0x5E970CBC, 0x8E112EB7  # export types (load-data type hashes)
KINDS = {DATABASE: "database", CLASS: "class", COLLECTION: "collection"}


def parse(data):
    """The 'db' vault of a VPAK attributes.bin: export entries (in file order), classes, positions."""
    if data[:4] != b"VPAK":
        raise ValueError("not a VPAK attributes.bin")
    vlt_size, vlt_ofs = struct.unpack_from("<I", data, 0x18)[0], struct.unpack_from("<I", data, 0x20)[0]
    p, end, exp = vlt_ofs, vlt_ofs + vlt_size, None
    while p + 8 <= end:
        tag, size = struct.unpack_from("<4sI", data, p)
        if tag == b"NpxE":  # "ExpN" stored little-endian
            exp = p
        if size == 0:
            break
        p += size
    if exp is None:
        raise ValueError("no export table")
    count = struct.unpack_from("<I", data, exp + 8)[0]
    exports, classes, db_pos = [], {}, None
    for i in range(count):
        pos = exp + 12 + 20 * i
        raw = data[pos:pos + 20]
        eid, etype, _, size, ofs = struct.unpack("<5I", raw)
        load = vlt_ofs + ofs
        e = {"kind": KINDS.get(etype, "other"), "type": etype, "id": eid, "raw": raw, "load": load}
        if etype == COLLECTION:
            e["key"], e["cls"] = struct.unpack_from("<II", data, load)
        elif etype == CLASS:
            e["key"] = struct.unpack_from("<I", data, load)[0]
            classes[e["key"]] = {"capacity": struct.unpack_from("<I", data, load + 4)[0], "cap_pos": load + 4}
        elif etype == DATABASE:
            db_pos = load
        exports.append(e)
    return {"exports": exports, "classes": classes, "exp_pos": exp + 12, "db_pos": db_pos}


def ident(e):
    """What an export is, independent of the tool that wrote it (export ids differ between writers)."""
    if e["kind"] == "collection":
        return ("collection", e["cls"], e["key"])
    if e["kind"] == "class":
        return ("class", e["key"])
    return (e["kind"], e["type"], e["id"])


def _grow(cap):
    return ((cap * 20 >> 4) + 3) & ~3


class HashMap:
    """Attrib::HashMap as speed.exe builds it: key % size, linear probing, grow by 1.25 when full or when a key
    needed more than 40 probes; a grow re-inserts the old slots in slot order."""

    def __init__(self, cap):
        self.cap, self.slots, self.count, self.worst = 0, [], 0, 0
        if cap:
            self.rehash(cap)

    def rehash(self, cap):
        old = self.slots
        while True:
            self.cap, self.slots, self.count, self.worst = cap, [None] * cap, 0, 0
            for k in old:
                if k is not None:
                    self.insert(k)
            if self.worst * 2 <= 0x50:
                return
            cap = _grow(cap)

    def insert(self, key):
        if self.count == self.cap:
            self.rehash(_grow(self.cap))
        i, probe = key % self.cap, 0
        while self.slots[i] is not None:
            if self.slots[i] == key:
                return
            i, probe = (i + 1) % self.cap, probe + 1
        self.slots[i] = key
        self.worst = max(self.worst, probe)
        self.count += 1


def walk_orders(data):
    """class key -> the order in which the game walks that class's collections."""
    v = parse(data)
    maps = {k: HashMap(c["capacity"]) for k, c in v["classes"].items()}
    for e in v["exports"]:
        if e["kind"] == "collection":
            m = maps[e["cls"]]
            m.insert(e["key"])
            if m.worst * 2 > 0x50:  # 0x458058: grow after a collection that needed too many probes
                m.rehash(_grow(m.cap))
    return {k: [s for s in m.slots if s is not None] for k, m in maps.items()}


def match(edited, reference):
    pe, pr = parse(edited), parse(reference)
    by_ident = {}
    for e in pe["exports"]:
        if ident(e) in by_ident:
            raise ValueError("duplicate export %r" % (ident(e),))
        by_ident[ident(e)] = e
    ref_ids = [ident(e) for e in pr["exports"]]
    if sorted(ref_ids) != sorted(by_ident):
        missing = set(ref_ids) - set(by_ident)
        extra = set(by_ident) - set(ref_ids)
        raise ValueError("export sets differ: %d missing, %d extra" % (len(missing), len(extra)))
    out = bytearray(edited)
    table = b"".join(by_ident[i]["raw"] for i in ref_ids)
    out[pe["exp_pos"]:pe["exp_pos"] + len(table)] = table
    for key, c in pe["classes"].items():
        struct.pack_into("<I", out, c["cap_pos"], pr["classes"][key]["capacity"])
    # database load data: +0 class-table size, +4 a second size; NFS-VltEd keeps the original values too
    out[pe["db_pos"]:pe["db_pos"] + 8] = reference[pr["db_pos"]:pr["db_pos"] + 8]
    return bytes(out)


def match_added(edited, reference):
    """Like match, for an edited file that also has collections the reference lacks (added cars): the reference's
    exports first in the reference's order, then the added ones in the edited file's order; table sizes of the
    reference's classes from the reference. Refuses if the edited file lacks anything the reference has."""
    pe, pr = parse(edited), parse(reference)
    by_ident, order = {}, []
    for e in pe["exports"]:
        i = ident(e)
        if i in by_ident:
            raise ValueError("duplicate export %r" % (i,))
        by_ident[i] = e
        order.append(i)
    ref_ids = [ident(e) for e in pr["exports"]]
    missing = [i for i in ref_ids if i not in by_ident]
    if missing:
        raise ValueError("export sets differ: %d missing (the edited file lacks e.g. %r)" % (len(missing), missing[0]))
    ref_set = set(ref_ids)
    added = [i for i in order if i not in ref_set]
    out = bytearray(edited)
    table = b"".join(by_ident[i]["raw"] for i in ref_ids + added)
    out[pe["exp_pos"]:pe["exp_pos"] + len(table)] = table
    for key, c in pe["classes"].items():
        if key in pr["classes"]:
            struct.pack_into("<I", out, c["cap_pos"], pr["classes"][key]["capacity"])
    # only attributes.bin carries the database entry; fe_attrib.bin and gameplay.bin have none
    if pe["db_pos"] is not None and pr["db_pos"] is not None and len(pe["classes"]) == len(pr["classes"]):
        out[pe["db_pos"]:pe["db_pos"] + 8] = reference[pr["db_pos"]:pr["db_pos"] + 8]
    return bytes(out)


def _main(argv):
    if len(argv) == 3 and argv[0] == "check":
        a, r = walk_orders(open(argv[1], "rb").read()), walk_orders(open(argv[2], "rb").read())
        diff = sorted(k for k in r if a.get(k) != r[k])
        print("%d of %d classes walk differently%s" % (len(diff), len(r), (": " + " ".join("%08X" % k for k in diff))
                                                       if diff else ""))
        return 1 if diff else 0
    if len(argv) == 4 and argv[0] in ("match", "match-added"):
        fn = match if argv[0] == "match" else match_added
        out = fn(open(argv[1], "rb").read(), open(argv[2], "rb").read())
        with open(argv[3], "wb") as f:
            f.write(out)
        print("wrote", argv[3], len(out), "bytes")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
