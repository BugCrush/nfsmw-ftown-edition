"""Compares our build of a companion with the author's binary: which .ini keys each contains as text, and which
identifiers from the author's .pdb are absent from the upstream source (a sign the author's build is newer).

Usage: python compare-build.py <ours.asi> <author.asi> <author .ini or .json> <source dir> [author.pdb]
Exit code 1 if the author's binary reads a key ours lacks, or the .pdb names functions the source lacks.
"""
import os
import re
import sys

ours, author, ini, src = sys.argv[1:5]
pdb = sys.argv[5] if len(sys.argv) > 5 else None


def texts(path, n=4):
    data = open(path, "rb").read()
    ascii_ = {m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{%d,}" % n, data)}
    wide = {m.group().decode("utf-16-le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % n, data)}
    return ascii_ | wide


def ini_keys(path):
    keys = set()
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line) or re.match(r'^"([A-Za-z_][A-Za-z0-9_]*)"\s*:', line)
        if m:
            keys.add(m.group(1))
    return keys


def has(strings, key):
    return any(key in s for s in strings)


t_ours, t_author = texts(ours), texts(author)
problems = 0
print("key                               author  ours")
for k in sorted(ini_keys(ini)):
    a, o = has(t_author, k), has(t_ours, k)
    if a and not o:
        problems += 1
    print("%-34s %-7s %s%s" % (k, "yes" if a else "-", "yes" if o else "-", "   <-- missing in ours" if a and not o else ""))

if pdb:
    source = ""
    for dirpath, _, names in os.walk(src):
        for n in names:
            if n.endswith((".cpp", ".h", ".hpp")):
                source += open(os.path.join(dirpath, n), encoding="utf-8", errors="replace").read()
    idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", source))
    pdb_names = {s for s in texts(pdb, 6) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{5,}", s)}
    # Only names that look like this project's own functions: present in the author's binary's symbol space and
    # following the source's naming (contain an upper-case letter and an underscore or CamelCase).
    candidates = sorted(n for n in pdb_names - idents
                        if re.search(r"(Xenon|Emitter|Particle|Effect|Spark|Contrail|TexWizard|Texture|Hook|Init)", n))
    print("\n.pdb names related to the plugin and absent from the source: %d" % len(candidates))
    for n in candidates[:60]:
        print("   ", n)
    problems += len(candidates)
sys.exit(1 if problems else 0)
