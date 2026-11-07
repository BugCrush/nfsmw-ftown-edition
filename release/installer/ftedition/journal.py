"""The install record: every game file a step may change is backed up before its first change, every file a step
creates is listed, and a change outside a step's declared area stops the install (nothing could undo it).

<game>\\FTownEdition-backup\\journal.json holds the state ("installing" until finish(), then "installed"), the original
size and sha256 of each backed-up file, the created files and folders, and after finish() the sha256 of every touched
file as installed (so uninstall can say which ones the player changed since). The journal is written after every
step, also when a step fails, so `uninstall` restores a half-finished install as well.

Uninstall restores every backup (checked by sha256), deletes every file the install created and the folders it
created once empty, and removes the backup folder. Files the game made after the install (saves, logs, times) are not
the install's and stay.
"""
import contextlib
import fnmatch
import hashlib
import json
import os
import shutil

FOLDER = "FTownEdition-backup"
WORK = "FTownEdition-work"
JOURNAL = "journal.json"


class Refused(Exception):
    pass


class Failed(Exception):
    pass


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _scan(game):
    """{rel: (size, mtime_ns)} of every file, and the set of folders, outside our own two folders."""
    files, dirs = {}, set()
    skip = {FOLDER.lower(), WORK.lower()}
    for dp, dnames, names in os.walk(game):
        if dp == game:
            dnames[:] = [d for d in dnames if d.lower() not in skip]
        rel_dir = os.path.relpath(dp, game).replace(os.sep, "/")
        if rel_dir != ".":
            dirs.add(rel_dir)
        for n in names:
            p = os.path.join(dp, n)
            st = os.stat(p)
            rel = n if rel_dir == "." else rel_dir + "/" + n
            files[rel] = (st.st_size, st.st_mtime_ns)
    return files, dirs


def _matches(rel, globs):
    r = rel.lower()
    for g in globs:
        g = g.lower()
        if g.endswith("/**"):
            if r.startswith(g[:-2]):
                return True
        elif fnmatch.fnmatchcase(r, g) and r.count("/") == g.count("/"):
            return True
    return False


class Journal:
    def __init__(self, game, data):
        self.game = os.path.abspath(game)
        self.dir = os.path.join(self.game, FOLDER)
        self.data = data

    @classmethod
    def open(cls, game):
        path = os.path.join(game, FOLDER, JOURNAL)
        if os.path.exists(path):
            state = json.load(open(path, encoding="utf-8")).get("state")
            if state == "installed":
                raise Refused("F-Town Edition is already installed in this game folder (uninstall it first)")
            raise Refused("an earlier install stopped half-way: run the installer's uninstall first, then install again")
        os.makedirs(os.path.join(game, FOLDER, "backup"), exist_ok=True)
        j = cls(game, {"state": "installing", "backed": {}, "created": [], "created_dirs": [], "steps": []})
        j._save()
        return j

    def _save(self):
        tmp = os.path.join(self.dir, JOURNAL + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, os.path.join(self.dir, JOURNAL))

    def _backup(self, rel):
        if rel in self.data["backed"] or rel in self.data["created"]:
            return
        src = os.path.join(self.game, *rel.split("/"))
        dst = os.path.join(self.dir, "backup", *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        digest = _sha(src)
        if _sha(dst) != digest:
            raise Failed("backup of %s failed (copy differs)" % rel)
        self.data["backed"][rel] = {"size": os.path.getsize(src), "sha256": digest, "step": None}

    @contextlib.contextmanager
    def step(self, name, may_change):
        before, dirs_before = _scan(self.game)
        new_backups = []
        for rel in before:
            if _matches(rel, may_change) and rel not in self.data["backed"] and rel not in self.data["created"]:
                self._backup(rel)
                new_backups.append(rel)
        self._save()
        error = None
        try:
            yield self
        except BaseException as e:
            error = e
            raise
        finally:
            after, dirs_after = _scan(self.game)
            for rel in sorted(set(after) - set(before)):
                if rel not in self.data["created"] and rel not in self.data["backed"]:
                    self.data["created"].append(rel)
            for d in sorted(dirs_after - dirs_before):
                if d not in self.data["created_dirs"]:
                    self.data["created_dirs"].append(d)
            outside = sorted(rel for rel in before if rel not in self.data["backed"] and rel not in self.data["created"]
                             and (rel not in after or after[rel] != before[rel]))
            # drop this step's backups of files it left unchanged
            for rel in new_backups:
                p = os.path.join(self.game, *rel.split("/"))
                if os.path.exists(p) and after.get(rel) == before.get(rel) and _sha(p) == self.data["backed"][rel]["sha256"]:
                    os.remove(os.path.join(self.dir, "backup", *rel.split("/")))
                    del self.data["backed"][rel]
                else:
                    self.data["backed"][rel]["step"] = name
            self.data["steps"].append({"name": name, "ok": error is None and not outside,
                                       "error": None if error is None else repr(error)})
            self._save()
            if outside and error is None:
                raise Failed("step %s changed files outside its area (restore them from a backup of the game): %s"
                             % (name, ", ".join(outside)))

    def finish(self, summary):
        installed = {}
        for rel in list(self.data["backed"]) + self.data["created"]:
            p = os.path.join(self.game, *rel.split("/"))
            installed[rel] = _sha(p) if os.path.exists(p) else None
        self.data["installed"] = installed
        self.data["summary"] = summary
        self.data["state"] = "installed"
        self._save()


def uninstall(game):
    game = os.path.abspath(game)
    folder = os.path.join(game, FOLDER)
    path = os.path.join(folder, JOURNAL)
    if not os.path.exists(path):
        raise Refused("F-Town Edition is not installed in %s (no %s\\%s)" % (game, FOLDER, JOURNAL))
    data = json.load(open(path, encoding="utf-8"))
    installed = data.get("installed", {})
    edited = []
    for rel in list(data["backed"]) + data["created"]:
        p = os.path.join(game, *rel.split("/"))
        if rel in installed and os.path.exists(p) and installed[rel] is not None and _sha(p) != installed[rel]:
            edited.append(rel)
    restored = []
    for rel, info in sorted(data["backed"].items()):
        src = os.path.join(folder, "backup", *rel.split("/"))
        dst = os.path.join(game, *rel.split("/"))
        if _sha(src) != info["sha256"]:
            raise Failed("the backup of %s is damaged; nothing more restored" % rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if _sha(dst) != info["sha256"]:
            raise Failed("restoring %s failed" % rel)
        restored.append(rel)
    removed = []
    for rel in data["created"]:
        p = os.path.join(game, *rel.split("/"))
        if os.path.exists(p):
            os.remove(p)
            removed.append(rel)
    for d in sorted(data["created_dirs"], key=lambda d: -d.count("/")):
        p = os.path.join(game, *d.split("/"))
        if os.path.isdir(p) and not os.listdir(p):
            os.rmdir(p)
    shutil.rmtree(os.path.join(game, WORK), ignore_errors=True)
    shutil.rmtree(folder)
    return {"restored": restored, "removed": removed, "edited_after_install": sorted(edited)}
