"""Reads PatchMap.log and says, for each place our own plugins patch (tools/x360/our-patches.txt), whose patch
is there now: ours, another module's ("taken by ..."), or none ("not patched": our plugin did not install it).

Usage: python patchmap_check.py <PatchMap.log> [our-patches.txt]   Exit code 1 if any place is taken by another
module. Lines of our-patches.txt: `<0xADDRESS | DLL!function> <our module> <what it is>`; '#' starts a comment.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _module(name):
    return name.split("+")[0]


def parse(log_path):
    text = open(log_path, encoding="utf-8", errors="replace").read()
    ranges = [(int(s, 16), int(n)) for s, n in re.findall(r"^RANGE start=(0x[0-9A-Fa-f]+) len=(\d+)", text, re.M)]
    owners = {int(s, 16): o for s, o in re.findall(r"^OWNER start=(0x[0-9A-Fa-f]+) owner=(\S+)", text, re.M)}
    imports = {i.lower(): m for i, m in re.findall(r"^IMPORT slot=0x[0-9A-Fa-f]+ import=(\S+) module=(\S+)", text, re.M)}
    return ranges, owners, imports


def check(log_path, ours_path):
    ranges, owners, imports = parse(log_path)
    rows = []
    for line in open(ours_path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        where, module, what = line.split(None, 2)
        if where.lower().startswith("0x"):
            addr = int(where, 16)
            hit = [s for s, n in ranges if s <= addr < s + n]
            owner = _module(owners.get(hit[0], "-")) if hit else None
        else:
            owner = _module(imports[where.lower()]) if where.lower() in imports else None
        if owner is None:
            verdict = "not patched"
        elif owner.lower() in [m.lower() for m in module.split("|")]:
            verdict = "ours"  # "A.asi|B.asi": a place two of our plugins share (one wraps the other)
        else:
            verdict = "taken by %s" % owner
        rows.append({"where": where, "module": module, "what": what, "verdict": verdict})
    return rows


def main(argv):
    ours = argv[1] if len(argv) > 1 else os.path.join(HERE, "our-patches.txt")
    rows = check(argv[0], ours)
    for r in rows:
        print("%-36s %-18s %-22s %s" % (r["where"], r["module"], r["what"], r["verdict"]))
    return 1 if any(r["verdict"].startswith("taken by") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
