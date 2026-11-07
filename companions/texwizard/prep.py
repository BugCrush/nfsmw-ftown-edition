"""Copies TexWizard's source (R-033/texwizard) at the recorded commit into src/ for our Zig build. No source
changes are needed (checked 2026-10-15).

Usage: python prep.py [clone dir]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CLONE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".superpowers", "visual-research", "repos", "texwizard")
COMMIT = "51e7d29c070aa8f9b7c3b44b78fadfda299777a3"

head = subprocess.run(["git", "-C", CLONE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
if head != COMMIT:
    sys.exit("prep: clone is at %s, expected %s; refusing" % (head, COMMIT))
src = os.path.join(HERE, "src")
if os.path.exists(src):
    shutil.rmtree(src)
shutil.copytree(CLONE, src, ignore=shutil.ignore_patterns(".git"))
print("prep: commit %s copied unchanged" % COMMIT[:7])
