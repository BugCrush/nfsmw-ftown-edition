"""Lists readable strings (6+ characters) in the author's binary that our build does not contain, skipping
compiler/runtime noise, plus the keys of a JSON file and whether each binary contains them.

Usage: python strings-diff.py <ours> <author's> [json file ...]
"""
import json
import re
import sys

NOISE = re.compile(r"(api-ms-|VCRUNTIME|MSVCP|\.pdb|std::|Microsoft|KERNEL32|__|\.dll|RSDS|GCTL|\.text|\.rdata|"
                   r"\.data|\.rsrc|\.reloc|\.idata|bad |invalid |vector|string too|exception|allocator|"
                   r"Unknown exception|ios_base|locale|\$|@)", re.I)


def texts(path):
    data = open(path, "rb").read()
    a = {m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{6,}", data)}
    w = {m.group().decode("utf-16-le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){6,}", data)}
    return a | w


def keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            keys(v, out)
    return out


ours, author = texts(sys.argv[1]), texts(sys.argv[2])
missing = sorted(s for s in author - ours if not NOISE.search(s) and re.search(r"[A-Za-z]{4}", s))
print("strings in the author's binary missing from ours: %d" % len(missing))
for s in missing[:80]:
    print("   ", repr(s))
for path in sys.argv[3:]:
    ks = keys(json.load(open(path, encoding="utf-8")), set())
    print("\nkeys of %s:" % path)
    for k in sorted(ks):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            print("   %-24s author %-4s ours %s" % (k, "yes" if any(k in s for s in author) else "-",
                                                   "yes" if any(k in s for s in ours) else "-"))
