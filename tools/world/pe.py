"""speed.exe as an image: read bytes at a game address (read-only), sections, and a capstone check.

Plain `python` has no capstone; `decode_first` runs a short helper under `.tools/pyenv/Scripts/python` (which has it)
when the import fails, so the tests run under either interpreter.
"""
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PYENV = os.path.join(REPO, ".tools", "pyenv", "Scripts", "python.exe")


class Image:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        optsz = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
        self.sections = []  # (name, va, vsize, raw, rsize)
        for i in range(nsec):
            o = pe + 24 + optsz + i * 40
            name = d[o:o + 8].rstrip(b"\0").decode()
            vsize, va, rsize, raw = struct.unpack_from("<IIII", d, o + 8)
            self.sections.append((name, self.base + va, vsize, raw, rsize))

    def section_of(self, addr):
        for s in self.sections:
            if s[1] <= addr < s[1] + max(s[2], s[4]):
                return s[0]
        return None

    def offset(self, addr):
        for name, va, vsize, raw, rsize in self.sections:
            if va <= addr < va + max(vsize, rsize):
                return raw + (addr - va) if addr - va < rsize else None
        return None

    def read(self, addr, n):
        o = self.offset(addr)
        if o is None:
            raise ValueError("0x%08X is not in the file" % addr)
        return self.data[o:o + n]


_HELPER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from pe import Image
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
img = Image(sys.argv[2])
md = Cs(CS_ARCH_X86, CS_MODE_32)
out = {}
for a in json.loads(sys.stdin.read()):
    try:
        b = img.read(a, 16)
    except ValueError:
        out[str(a)] = None
        continue
    ins = list(md.disasm(b, a, count=1))
    out[str(a)] = (ins[0].mnemonic + " " + ins[0].op_str) if ins and ins[0].address == a else None
print(json.dumps(out))
"""


def decode_first(exe, addrs):
    """{addr: 'mnemonic operands' of the first instruction, or None if it does not decode}."""
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    except ImportError:
        r = subprocess.run([PYENV, "-c", _HELPER, HERE, exe], input=json.dumps(list(addrs)), capture_output=True,
                           text=True, check=True)
        return {int(k): v for k, v in json.loads(r.stdout).items()}
    img = Image(exe)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    out = {}
    for a in addrs:
        try:
            b = img.read(a, 16)
        except ValueError:
            out[a] = None
            continue
        ins = list(md.disasm(b, a, count=1))
        out[a] = (ins[0].mnemonic + " " + ins[0].op_str) if ins and ins[0].address == a else None
    return out
