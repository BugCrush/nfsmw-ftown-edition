"""Which code ranges a newly added plugin took from another module, comparing two PatchMap logs.

    python tools/cars/patch-overlap.py <PatchMap.log before> <PatchMap.log after> <new module, e.g. NFSMWUnlimiter.asi>

A range in the "after" log owned by the new module overlaps a range the "before" log gave to another module:
printed as TAKEN (exit code 1). Ranges the new module owns that nothing patched before are counted only.
"""
import re
import sys


def ranges(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    lens = {int(s, 16): int(n) for s, n in re.findall(r"^RANGE start=(0x[0-9A-Fa-f]+) len=(\d+)", text, re.M)}
    owners = {int(s, 16): o.split("+")[0] for s, o in re.findall(r"^OWNER start=(0x[0-9A-Fa-f]+) owner=(\S+)", text, re.M)}
    return [(s, lens.get(s, 1), owners.get(s, "-")) for s in sorted(lens)]


def overlaps(before, after, module):
    taken, fresh = [], 0
    for s, n, o in after:
        if o != module:
            continue
        hit = [(bs, bn, bo) for bs, bn, bo in before if bo != module and bs < s + n and s < bs + bn]
        if hit:
            taken.append(((s, n), hit))
        else:
            fresh += 1
    return taken, fresh


def changed_extents(before, after):
    """Ranges in the "after" log that overlap a "before" range without being the same range, whoever owns them.
    PatchMap names an owner from the first jump in a range, so a later module overwriting a new one's patch keeps
    its name in both logs; the range's extent changing is what shows it."""
    out = []
    same = {(s, n) for s, n, _ in before}
    for s, n, o in after:
        if (s, n) in same:
            continue
        hit = [(bs, bn, bo) for bs, bn, bo in before if bs < s + n and s < bs + bn]
        if hit:
            out.append(((s, n, o), hit))
    return out


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    before, after = ranges(sys.argv[1]), ranges(sys.argv[2])
    taken, fresh = overlaps(before, after, sys.argv[3])
    for (s, n), hit in taken:
        print("TAKEN 0x%06X+%d from %s" % (s, n, ", ".join("%s (0x%06X+%d)" % (o, bs, bn) for bs, bn, o in hit)))
    changed = [c for c in changed_extents(before, after) if c[0][2] != sys.argv[3]]
    for (s, n, o), hit in changed:
        print("CHANGED 0x%06X+%d (%s) was %s" % (s, n, o, ", ".join("0x%06X+%d (%s)" % (bs, bn, bo) for bs, bn, bo in hit)))
    print("%s: %d ranges new, %d taken from other modules, %d other modules' ranges changed shape" % (
        sys.argv[3], fresh, len(taken), len(changed)))
    return 1 if taken or changed else 0


if __name__ == "__main__":
    sys.exit(main())
