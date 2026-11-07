"""Names for speed.exe v1.3's functions, from the nfsmw decompilation's symbol map (read-only).

The map (`config/SPEED_EXE_1_3/symbols.json`, an IDA export) has "functions" (start, size, name: 46,360) and "names"
(addr, name, is_func: 45,110). Names are MSVC-mangled (`?FindLoader@bChunkLoader@@SAPAV1@I@Z`); matching is by
case-insensitive regex on the raw name.

    python tools/world/syms.py name <regex>     every function or name matching
    python tools/world/syms.py addr <hex>       the function containing an address
"""
import bisect
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT = os.path.join(REPO, ".superpowers", "visual-research", "repos", "nfsmw", "config", "SPEED_EXE_1_3",
                       "symbols.json")


class Symbols:
    def __init__(self, data):
        funcs = sorted((int(f["start"], 16), int(f["size"], 16), f["name"]) for f in data["functions"])
        self._starts = [f[0] for f in funcs]
        self._funcs = funcs
        names = {}
        for f in funcs:
            names[(f[0], f[2])] = True
        for n in data.get("names", []):
            names[(int(n["addr"], 16), n["name"])] = True
        self._names = sorted(names)

    def functions(self):
        return [(a, n) for a, _, n in self._funcs]

    def by_name(self, pattern):
        rx = re.compile(pattern, re.I)
        return [(a, n) for a, n in self._names if rx.search(n)]

    def at(self, addr):
        i = bisect.bisect_right(self._starts, addr) - 1
        if i < 0:
            return None
        start, size, name = self._funcs[i]
        if start <= addr < start + max(size, 1):
            return start, name
        return None


_cache = {}


def load(path=None):
    path = path or DEFAULT
    if path not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache[path] = Symbols(json.load(f))
    return _cache[path]


def main(argv):
    if len(argv) != 2 or argv[0] not in ("name", "addr"):
        print(__doc__)
        return 2
    s = load()
    if argv[0] == "name":
        for a, n in s.by_name(argv[1]):
            print("%08X  %s" % (a, n))
    else:
        hit = s.at(int(argv[1], 16))
        print("%08X  %s" % hit if hit else "no function contains that address")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
