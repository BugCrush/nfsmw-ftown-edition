"""The player's third-party downloads, found by content.

release/downloads.json lists every item the installer takes from another author's release: its official page, the
archive as published (name, size, sha256) where there is one archive, and `contents`: every file the installer uses,
as a path relative to the item's root with its size and sha256. `anchor` is one of those paths.

The player may put the downloads anywhere under the folders given, with any names (browsers rename, Google Drive zips
folders under changing names). An item is found when a file with the anchor's size and hash exists and every other
file of `contents` sits at its path relative to the anchor's root with the right size and hash. A .zip archive with
the pinned hash is extracted into the work folder and searched there; a .rar or .7z must be extracted by the player
(the message names it). The downloads folders are only read.
"""
import hashlib
import json
import os
import zipfile

REQUIRED = ("id", "name", "page", "anchor", "contents")


class Found:
    def __init__(self, item, root):
        self.item, self.root = item, root

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def __repr__(self):
        return "Found(%s, %s)" % (self.item["id"], self.root)


class Missing:
    def __init__(self, item, reason):
        self.item, self.reason = item, reason

    def __repr__(self):
        return "Missing(%s: %s)" % (self.item["id"], self.reason)


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = {}
    for it in data["items"]:
        for k in REQUIRED:
            if k not in it:
                raise ValueError("downloads.json: item %s has no %s" % (it.get("id"), k))
        if it["anchor"] not in {c["path"] for c in it["contents"]}:
            raise ValueError("downloads.json: item %s: anchor %s is not in its contents" % (it["id"], it["anchor"]))
        items[it["id"]] = it
    return items


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _Index:
    """Files under the roots, by size; hashes computed once, only for sizes some item needs."""

    def __init__(self, roots, sizes, skip=()):
        self.by_size = {}
        skip = [os.path.normcase(os.path.abspath(s)) for s in skip]
        for root in roots:
            for dp, dirs, names in os.walk(root):
                if any(os.path.normcase(os.path.abspath(dp)).startswith(s) for s in skip):
                    dirs[:] = []
                    continue
                for n in names:
                    p = os.path.join(dp, n)
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        continue
                    if size in sizes:
                        self.by_size.setdefault(size, []).append(p)
        self._hash = {}

    def hash(self, p):
        if p not in self._hash:
            self._hash[p] = sha256(p)
        return self._hash[p]

    def find(self, size, digest):
        return [p for p in self.by_size.get(size, []) if self.hash(p) == digest]


def _root_of(anchor_path, anchor_rel):
    root = anchor_path
    for _ in anchor_rel.split("/"):
        root = os.path.dirname(root)
    return root


def _check(item, root):
    """None if every file of item is under root as listed, else the first problem."""
    for c in item["contents"]:
        p = os.path.join(root, *c["path"].split("/"))
        if not os.path.isfile(p):
            return "%s is missing" % c["path"]
        if os.path.getsize(p) != c["size"] or sha256(p) != c["sha256"]:
            return "%s is not the tested version" % c["path"]
    return None


def _match(item, index):
    a = next(c for c in item["contents"] if c["path"] == item["anchor"])
    problems = []
    for p in index.find(a["size"], a["sha256"]):
        root = _root_of(p, a["path"])
        problem = _check(item, root)
        if problem is None:
            return root, None
        problems.append(problem)
    return None, (problems[0] if problems else None)


def _by_name(item, roots):
    """A file named like the anchor (any version), for a better message."""
    want = item["anchor"].split("/")[-1].lower()
    for root in roots:
        for dp, _, names in os.walk(root):
            for n in names:
                if n.lower() == want:
                    return os.path.join(dp, n)
    return None


def _archives(item):
    a = item.get("archive")
    return [] if not a else (a if isinstance(a, list) else [a])


def locate(items, roots, work):
    """{id: Found | Missing} for every item. work: a folder the installer owns (zips are extracted there)."""
    roots = [r for r in roots if os.path.isdir(r)]
    sizes = set()
    for it in items.values():
        sizes.update(c["size"] for c in it["contents"])
        sizes.update(a["size"] for a in _archives(it))
    index = _Index(roots, sizes, skip=[work])
    out = {}
    for iid, it in items.items():
        page = it["page"]
        root, problem = _match(it, index)
        if root:
            out[iid] = Found(it, root)
            continue
        archives = []
        for a in _archives(it):  # every archive of the item (the .NET runtime comes as two zips)
            hits = index.find(a["size"], a["sha256"])
            if hits:
                archives.append(hits[0])
        zips = [a for a in archives if a.lower().endswith(".zip")]
        if zips and len(zips) == len(_archives(it)):
            dest = os.path.join(work, "downloads", iid)
            os.makedirs(dest, exist_ok=True)
            for a in zips:
                with zipfile.ZipFile(a) as z:
                    z.extractall(dest)
            sub = _Index([dest], {c["size"] for c in it["contents"]})
            root, problem = _match(it, sub)
            if root:
                out[iid] = Found(it, root)
                continue
        if archives and len(zips) < len(archives):
            names = ", ".join(os.path.basename(a) for a in archives if not a.lower().endswith(".zip"))
            reason = ("%s (%s) is downloaded but not extracted: extract %s with 7-Zip into the downloads folder"
                      % (it["name"], page, names))
        elif archives and len(archives) < len(_archives(it)):
            reason = "%s: download every file listed (%s); found only %s" % (
                it["name"], page, ", ".join(os.path.basename(a) for a in archives))
        elif problem:
            reason = "%s: %s (get the tested version from %s)" % (it["name"], problem, page)
        else:
            other = _by_name(it, roots)
            if other:
                reason = ("%s: %s is there but is not the tested version (get the tested version from %s)"
                          % (it["name"], other, page))
            else:
                reason = "%s is not in the downloads folder (download it from %s)" % (it["name"], page)
        out[iid] = Missing(it, reason)
    return out
