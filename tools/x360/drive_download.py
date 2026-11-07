"""Downloads a public Google Drive folder recursively, file by file, keeping its layout (read-only on Drive).

Usage: python drive-download.py <folder id> <output dir>
Skips files that already exist with a non-zero size, so it can be re-run after an interruption.
"""
import html
import os
import re
import subprocess
import sys

import gdown


def listing(folder_id):
    page = subprocess.run(["curl", "-s", "-L", "https://drive.google.com/embeddedfolderview?id=%s" % folder_id],
                          capture_output=True).stdout.decode("utf-8", "replace")
    pattern = r'<a href="([^"]+)"[^>]*>.*?<div class="flip-entry-title">(.*?)</div>'
    return [(html.unescape(m.group(2)), m.group(1)) for m in re.finditer(pattern, page, re.S)]


def fetch_plain(file_id, target):
    """Direct download; returns False (and leaves nothing behind) if Drive answered with a web page instead."""
    part = target + ".part"
    subprocess.run(["curl", "-s", "-L", "-o", part,
                    "https://drive.google.com/uc?export=download&id=%s" % file_id])
    if os.path.exists(part):
        with open(part, "rb") as f:
            head = f.read(512).lstrip().lower()
        if os.path.getsize(part) > 0 and not head.startswith((b"<!doctype html", b"<html")):
            os.replace(part, target)
            return True
        os.remove(part)
    return False


def walk(folder_id, out, failures):
    os.makedirs(out, exist_ok=True)
    for name, link in listing(folder_id):
        sub = re.search(r"/folders/([\w-]+)", link)
        if sub:
            walk(sub.group(1), os.path.join(out, name), failures)
            continue
        fid = re.search(r"/file/d/([\w-]+)", link) or re.search(r"[?&]id=([\w-]+)", link)
        target = os.path.join(out, name)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            continue
        if not fid:
            failures.append((target, "no id in " + link))
            continue
        if not fetch_plain(fid.group(1), target):
            try:  # big files answer with a confirm page; gdown knows that step
                got = gdown.download(id=fid.group(1), output=target, quiet=True)
                if not got:
                    failures.append((target, "download returned nothing"))
            except Exception as e:  # keep going; report at the end
                failures.append((target, repr(e)))
        print("ok " if os.path.exists(target) else "FAIL ", target, flush=True)


failures = []
walk(sys.argv[1], sys.argv[2], failures)
print("failures: %d" % len(failures))
for f in failures:
    print("  ", *f)
