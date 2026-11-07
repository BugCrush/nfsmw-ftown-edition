"""What is inside the shaders GfxProbe saved, and the effect resources inside an executable.

    python tools/fx-inspect.py shader <file.bin>... [--json]
        For each compiled shader: its version and the named constants it expects (from the constant
        table the compiler embeds), with the register set and slot each one uses.

    python tools/fx-inspect.py effects <program.exe> --out <folder>
        Copies every RCDATA resource of the program into <folder> (named resources keep their name,
        numbered ones are called by their number) and says for each whether it is text or binary.
        Read-only towards the program. For speed.exe the output is game data: keep <folder> out of git.
"""
import json
import os
import struct
import sys

REGISTER_SETS = {0: "bool", 1: "int", 2: "float", 3: "sampler"}


def cstring(data, offset):
    end = data.index(b"\0", offset)
    return data[offset:end].decode("latin-1")


def parse_shader(data):
    tokens = struct.unpack_from("<%dI" % (len(data) // 4), data)
    version = tokens[0]
    info = {"version": "%s_%d_%d" % ("vs" if version >> 16 == 0xFFFE else "ps", (version >> 8) & 0xFF, version & 0xFF),
            "bytes": len(data), "creator": "", "constants": [], "preshader": []}
    i = 1
    while i < len(tokens) and tokens[i] & 0xFFFF == 0xFFFE:  # comment blocks precede the instructions
        words = tokens[i] >> 16
        body = data[(i + 1) * 4:(i + 1 + words) * 4]
        if body[:4] == b"CTAB":
            table = body[4:]
            size, creator, _version, count, first, _flags, _target = struct.unpack_from("<7I", table)
            info["creator"] = cstring(table, creator)
            for k in range(count):
                name, regset, index, regcount, _reserved, _type, _default = struct.unpack_from("<IHHHHII", table, first + k * 20)
                info["constants"].append({"name": cstring(table, name), "set": REGISTER_SETS.get(regset, str(regset)),
                                          "index": index, "count": regcount})
        elif body[:4] == b"PRES":
            # A preshader: arithmetic on settings that the effect library does on the processor before the
            # draw (e.g. colour * exposure). It is a small program of its own with its own constant table;
            # the settings it reads appear there, not in the main table.
            if len(body) >= 8:
                info["preshader"] = parse_shader(body[4:])["constants"]
        i += 1 + words
    return info


def rcdata(data):
    """Yields (name, bytes) for every RCDATA resource of a PE file."""
    u16 = lambda o: struct.unpack_from("<H", data, o)[0]
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]
    pe = u32(0x3C)
    sections = u16(pe + 6)
    optional = pe + 24
    first_section = optional + u16(pe + 20)
    resource_rva = u32(optional + 96 + 2 * 8)
    if not resource_rva:
        return

    def offset(rva):
        for s in range(sections):
            o = first_section + s * 40
            vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
            if va <= rva < va + max(vsize, rsize):
                return raw + rva - va
        raise ValueError("address 0x%X is in no section" % rva)

    base = offset(resource_rva)

    def entries(directory):
        count = u16(directory + 12) + u16(directory + 14)
        for i in range(count):
            yield u32(directory + 16 + i * 8), u32(directory + 20 + i * 8)

    def name_of(value):
        if value & 0x80000000:
            o = base + (value & 0x7FFFFFFF)
            return data[o + 2:o + 2 + u16(o) * 2].decode("utf-16-le")
        return value

    for type_name, type_dir in entries(base):
        if name_of(type_name) != 10:  # RT_RCDATA
            continue
        for res_name, res_dir in entries(base + (type_dir & 0x7FFFFFFF)):
            for _language, leaf in entries(base + (res_dir & 0x7FFFFFFF)):
                rva, size = u32(base + leaf), u32(base + leaf + 4)
                start = offset(rva)
                yield str(name_of(res_name)), data[start:start + size]
                break


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "shader":
        files = [a for a in sys.argv[2:] if not a.startswith("--")]
        infos = []
        for path in files:
            info = parse_shader(open(path, "rb").read())
            info["file"] = os.path.basename(path)
            infos.append(info)
        if "--json" in sys.argv:
            print(json.dumps(infos, indent=1))
            return
        for info in infos:
            print("%s  %s  %d bytes  %s" % (info["file"], info["version"], info["bytes"], info["creator"]))
            for c in info["constants"]:
                print("    %-32s %-7s slot %3d x%d" % (c["name"], c["set"], c["index"], c["count"]))
            for c in info["preshader"]:
                print("    %-32s read by the preshader" % c["name"])
    elif len(sys.argv) == 5 and sys.argv[1] == "effects" and sys.argv[3] == "--out":
        data = open(sys.argv[2], "rb").read()
        os.makedirs(sys.argv[4], exist_ok=True)
        found = 0
        for name, body in rcdata(data):
            found += 1
            text = all(b in (9, 10, 13) or 32 <= b < 127 for b in body[:512])
            target = os.path.join(sys.argv[4], name + ".fx")
            with open(target, "wb") as f:
                f.write(body)
            print("%-36s %8d bytes  %s  %s" % (name, len(body), "text" if text else "binary", body[:8].hex()))
        print("%d RCDATA resources written to %s" % (found, sys.argv[4]))
    else:
        print(__doc__)
        sys.exit(2)


main()
