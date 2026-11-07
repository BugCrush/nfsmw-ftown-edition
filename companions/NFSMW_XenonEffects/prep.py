"""Prepares Xenon Effects' source for our Zig build: copies the upstream clone at the recorded commit into src/
and makes two mechanical changes, each counted, so Clang accepts the Microsoft-style inline assembly:

1. Characters outside ASCII (arrows in assembly comments) become '?'. Only lines where a comment (';' or '//')
   starts before the first such character are changed; anything else is refused.
2. `ds : name` memory operands become `name`. ds is the default segment for these operands, so the instruction
   is the same (test-ds.cpp checks the encoding); Clang's assembler rejects the explicit prefix in this form.

Usage: python prep.py [clone dir]
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CLONE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".superpowers", "visual-research", "repos",
                                                           "NFSMW_XenonEffects")
COMMIT = "b5070080c75a7dfc555deca0a5e005311954dbfd"
MINI_COMMIT = "a1ff72e8898db8b53282e9eb7c7ec5973519787e"
DS_EXPECTED = 45  # 47 lines carry "ds :"; the two in the form ds:[x] are accepted by Clang and left alone
DS = re.compile(r"\bds\s*:\s*(?=[A-Za-z_])")


def head(path):
    return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def main():
    if head(CLONE) != COMMIT or head(os.path.join(CLONE, "includes", "mINI")) != MINI_COMMIT:
        sys.exit("prep: clone is not at %s (mINI %s); refusing" % (COMMIT, MINI_COMMIT))
    src = os.path.join(HERE, "src")
    if os.path.exists(src):
        shutil.rmtree(src)
    shutil.copytree(CLONE, src, ignore=shutil.ignore_patterns(".git", "tests"))

    path = os.path.join(src, "dllmain.cpp")
    text = open(path, "rb").read().decode("utf-8-sig")
    lines, ascii_fixed = [], 0
    for n, line in enumerate(text.split("\n"), 1):
        bad = [i for i, ch in enumerate(line) if ord(ch) > 127]
        if bad:
            comment = min([i for i in (line.find(";"), line.find("//")) if i >= 0], default=-1)
            if comment < 0 or comment > bad[0]:
                sys.exit("prep: non-ASCII outside a comment at dllmain.cpp:%d; refusing" % n)
            line = "".join(ch if ord(ch) < 128 else "?" for ch in line)
            ascii_fixed += 1
        lines.append(line)
    text = "\n".join(lines)
    text, ds_fixed = DS.subn("", text)
    if ds_fixed != DS_EXPECTED:
        sys.exit("prep: expected %d 'ds :' operands, found %d; refusing" % (DS_EXPECTED, ds_fixed))
    open(path, "wb").write(text.encode("ascii"))
    print("prep: commit %s, %d comment lines made ASCII, %d 'ds :' prefixes removed" % (COMMIT[:7], ascii_fixed, ds_fixed))


main()
