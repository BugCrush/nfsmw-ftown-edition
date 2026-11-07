"""Read-only disassembly helper for speed.exe v1.3 (analysis only; it never writes to the game).

Needs the capstone package: run it with .tools/pyenv/Scripts/python (python -m venv .tools/pyenv,
then pip install capstone). Addresses are hexadecimal, as the game sees them (image base 0x400000).

    mwdis.py secs                      the executable's sections
    mwdis.py dis <start> <end>         disassemble a range; quoted text is a string an operand points at
    mwdis.py dw <addr> <count>         dump 32-bit values (pointers to strings are shown)
    mwdis.py str <addr>                the C string at an address
    mwdis.py xref <addr>               every place the 4 bytes of this address appear (data references)
    mwdis.py calls <addr>              every call/jmp in the code that lands on this address
    mwdis.py find <text>               where an ASCII string occurs
    mwdis.py bytes <hex bytes>         where a byte sequence occurs, e.g. "bytes 3C 24" (cmp al, '$')
"""
import os
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = os.environ.get("MW_EXE") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                               "Need For Speed Most Wanted Black Edition", "speed.exe")
data = open(EXE, "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
optsz = struct.unpack_from("<H", data, pe + 20)[0]
base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
secs = []
for i in range(nsec):
    o = pe + 24 + optsz + i * 40
    name = data[o:o + 8].rstrip(b"\0").decode()
    vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
    secs.append((name, base + va, vsize, raw, rsize))


def off(addr):
    for name, va, vsize, raw, rsize in secs:
        if va <= addr < va + max(vsize, rsize):
            if addr - va >= rsize:
                return None
            return raw + (addr - va)
    return None


def cstr(addr, limit=120):
    o = off(addr)
    if o is None:
        return None
    end = data.find(b"\0", o, o + limit)
    s = data[o:end if end >= 0 else o + limit]
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return s.decode()
    return None


cmd = sys.argv[1]
if cmd == "secs":
    for s in secs:
        print(s[0], hex(s[1]), hex(s[2]), hex(s[3]), hex(s[4]))
elif cmd == "dis":
    a, b = int(sys.argv[2], 16), int(sys.argv[3], 16)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    o = off(a)
    for ins in md.disasm(data[o:o + (b - a)], a):
        note = ""
        for tok in ins.op_str.replace("[", " ").replace("]", " ").replace(",", " ").split():
            if tok.startswith("0x"):
                try:
                    v = int(tok, 16)
                except ValueError:
                    continue
                s = cstr(v) if v > base + 0x1000 else None
                if s:
                    note = '   ; "%s"' % s
        print("%08X  %-8s %s%s" % (ins.address, ins.mnemonic, ins.op_str, note))
elif cmd == "str":
    print(repr(cstr(int(sys.argv[2], 16), 400)))
elif cmd == "dw":
    a, n = int(sys.argv[2], 16), int(sys.argv[3])
    o = off(a)
    if o is None:
        print("not in file (uninitialised data)")
    else:
        for i in range(n):
            v = struct.unpack_from("<I", data, o + i * 4)[0]
            s = cstr(v) if v > base + 0x1000 else None
            print("%08X: %08X %s" % (a + i * 4, v, ('"%s"' % s) if s else ""))
elif cmd == "xref":
    target = struct.pack("<I", int(sys.argv[2], 16))
    for name, va, vsize, raw, rsize in secs:
        i = raw
        while True:
            i = data.find(target, i, raw + rsize)
            if i < 0:
                break
            print("%s %08X" % (name, va + (i - raw)))
            i += 1
elif cmd == "calls":
    # every "call rel32" / "jmp rel32" in .text that lands on the address
    target = int(sys.argv[2], 16)
    name, va, vsize, raw, rsize = secs[0]
    for i in range(raw, raw + rsize - 5):
        if data[i] in (0xE8, 0xE9):
            rel = struct.unpack_from("<i", data, i + 1)[0]
            if va + (i - raw) + 5 + rel == target:
                print("%s %08X" % ("call" if data[i] == 0xE8 else "jmp ", va + (i - raw)))
elif cmd in ("find", "bytes"):
    needle = bytes.fromhex("".join(sys.argv[2:])) if cmd == "bytes" else sys.argv[2].encode()
    i = 0
    while True:
        i = data.find(needle, i)
        if i < 0:
            break
        for name, va, vsize, raw, rsize in secs:
            if raw <= i < raw + rsize:
                print("%s %08X" % (name, va + (i - raw)))
        i += 1
