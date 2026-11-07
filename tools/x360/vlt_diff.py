"""Compares two Attribulator YAML unpacks collection by collection.

Usage: python vlt_diff.py <dir A> <dir B> [class ...]
Prints, per class with any difference: collections only in A, only in B, and collections whose fields differ.
With class names given, prints every differing field value for those classes.
"""
import os
import sys

import yaml

DB = os.path.join("main", "attributes", "db")


def _name(n):
    return "0x%08X" % n if isinstance(n, int) else str(n)  # YAML reads unquoted 0x... as a number


def load(root, filename):
    path = os.path.join(root, DB, filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        items = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []
    return {_name(i["Name"]): i.get("Data") or {} for i in items}


def diff(a_root, b_root):
    """class -> (only in A, only in B, {collection: [fields that differ]}) for classes with any difference."""
    out = {}
    names = sorted(set(os.listdir(os.path.join(a_root, DB))) | set(os.listdir(os.path.join(b_root, DB))))
    for filename in names:
        a, b = load(a_root, filename), load(b_root, filename)
        only_a = sorted(set(a) - set(b))
        only_b = sorted(set(b) - set(a))
        changed = {}
        for n in set(a) & set(b):
            fields = sorted((f for f in set(a[n]) | set(b[n]) if a[n].get(f) != b[n].get(f)), key=str)
            if fields:
                changed[n] = fields
        if only_a or only_b or changed:
            out[filename[:-4]] = (only_a, only_b, changed)
    return out


if __name__ == "__main__":
    a_root, b_root, detail = sys.argv[1], sys.argv[2], set(sys.argv[3:])
    totals = [0, 0, 0]
    for cls, (only_a, only_b, changed) in diff(a_root, b_root).items():
        totals = [totals[0] + len(only_a), totals[1] + len(only_b), totals[2] + len(changed)]
        print("%-24s only-A %4d  only-B %4d  changed %4d" % (cls, len(only_a), len(only_b), len(changed)))
        if cls in detail:
            a, b = load(a_root, cls + ".yml"), load(b_root, cls + ".yml")
            for n in only_a:
                print("    only A:", n)
            for n in only_b:
                print("    only B:", n)
            for n, fields in sorted(changed.items()):
                for f in fields:
                    print("    %s.%s: %r -> %r" % (n, f, a[n].get(f), b[n].get(f)))
    print("TOTAL only-A %d  only-B %d  changed %d" % tuple(totals))
