"""Stage 1 of the Xbox 360 pack install (spec docs/superpowers/specs/2026-10-15-x360-pack-install-design.md):
options 1-10, the pack's own plugin, our builds of the companions, VisualBridge switched off. Runs on any folder:
a copy (the rehearsal) or the game.

Every check runs before anything changes: the game closed, the track file still the one the patch expects,
every pack file and build present. A second run therefore refuses at once and changes nothing.

Order: VisualBridge off -> part 1 (database) -> part 1's file copies (our builds in place of the bundled
Xenon Effects / TexWizard) -> part 2 (packed files, Binarius) -> part 3 (track file) -> Widescreen Fix (only if
a build is given). Every file added or replaced is recorded with its old and new sha256 in <record>.

Usage: python stage1.py <target folder> [--game]   (--game: target is the game folder; refuses while it runs)
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import files  # noqa: E402
import memfile  # noqa: E402
import nfsms  # noqa: E402
import part1  # noqa: E402
import part2  # noqa: E402
import ups  # noqa: E402
import vlt_order  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OPTIONS = {"music": False, "sfx": False}  # options 11 and 12 off; 1-10 keep their default (on)
WSF = "NFSMostWanted.WidescreenFix.asi"
# Keys the new Widescreen Fix build adds, set so they change nothing (spec): no console gamma curve, no SMAA, no
# anti-aliasing-bug lines, no right-stick camera (the pack asks for that too). Other new keys keep their defaults.
# FixHUD and FMVWidescreenMode must be 0: X360Stuff.asi checks them at start-up and exits otherwise (it handles the
# widescreen HUD and the game's native widescreen videos itself); seen in the game on 2026-10-16.
# HUDWidescreenMode is an old-build key the new build ignores, but X360Stuff reads the .ini and checks it too.
WSF_OVERRIDES = {("MAIN", "FixHUD"): "0", ("MAIN", "FMVWidescreenMode"): "0", ("MAIN", "HUDWidescreenMode"): "0",
                 ("GRAPHICS", "ConsoleGamma"): "0", ("GRAPHICS", "SMAA"): "0", ("GRAPHICS", "HideAABug"): "0",
                 ("CAMERA", "Enable"): "0"}


class Refused(Exception):
    pass


BACKUP_HASHES = r"D:\projects\nfsmwbe\telemetry\backup-before-x360\game-before-x360-20261015.sha256"
# Game files stage 1 changes in place; each must still be the backup's (untouched) before a run starts.
ORIGINALS = [r"GLOBAL\attributes.bin", r"GLOBAL\GlobalB.lzc", r"GLOBAL\InGameA.bun", r"GLOBAL\DYNTEX.BIN",
             r"GLOBAL\InGameB.lzc", r"GLOBAL\HUDTEXRACE.BIN", r"GLOBAL\HUDTEXTURESPHOTOFINISH.BIN",
             r"FRONTEND\FrontB.lzc", r"TRACKS\STREAML2RA.BUN", r"GLOBAL\GlobalMemoryFile.bin"]
PART2_FILES = ORIGINALS[1:8]
# The Black Edition's GlobalMemoryFile.bin caches these; the cached copies win over the pack's files on disk (the
# sky stayed black, 2026-10-16/18). attributes.bin can be read from disk only in the original's layout (vlt_order):
# the profile's fingerprint depends on the order the game walks the car collections (2026-10-18).
UNCACHE = [r"GLOBAL\attributes.bin", r"GLOBAL\GlobalB.lzc", r"GLOBAL\DYNTEX.BIN"]


class Record:
    """Every file added or replaced, written to <dir>/stage1-progress.json after each entry, so a run that stops
    half-way (an error, a crash, a power cut) still says what to restore from the backup."""

    def __init__(self, directory, name="stage1-progress.json"):
        self.path = os.path.join(directory, name)
        self.entries = []
        self._save()

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=1)

    def add(self, rel, old, new):
        self.entries.append({"rel": rel, "old_sha256": old, "new_sha256": new})
        self._save()

    def add_pending(self, rels, old_hashes):
        """Files a long step may change; recorded before it starts with new_sha256 'pending'."""
        for rel in rels:
            self.entries.append({"rel": rel, "old_sha256": old_hashes.get(rel), "new_sha256": "pending"})
        self._save()

    def resolve_pending(self, target):
        """After the step: pending files get their new hash, or are dropped if unchanged."""
        kept = []
        for e in self.entries:
            if e["new_sha256"] == "pending":
                path = files.find(target, e["rel"])
                now = files.sha256(path) if path else None
                if now == e["old_sha256"]:
                    continue
                e["new_sha256"] = now
            kept.append(e)
        self.entries = kept
        self._save()


def check_record_dir(record_dir):
    if os.path.isdir(record_dir) and os.listdir(record_dir):
        raise Refused("the record folder %s is already used (an earlier run?); restore or move it first" % record_dir)


def check_originals(target, hash_list, rels):
    """Refuses if any of `rels` differs from the backup's hash list (stage 1 or part of it already ran)."""
    original = {}
    for line in open(hash_list, encoding="utf-8"):
        h, p = line.rstrip("\n").split(" ", 1)
        original[p.lstrip("*").lstrip("./").replace("/", "\\").lower()] = h
    for rel in rels:
        path = files.find(target, rel)
        if path is None or files.sha256(path) != original.get(rel.lower()):
            raise Refused("%s is not the original file any more (stage 1, or part of it, already ran here?)" % rel)


COMPANIONS = os.path.join(ROOT, "companions")
WSF_DEFAULT_INI = os.path.join(COMPANIONS, "WidescreenFix", "out", "NFSMostWanted.WidescreenFix.ini")


def default_builds():
    """Our builds that replace or join the pack's files. Xenon Effects is absent on purpose: the pack's bundled
    build is installed (the user's decision, 2026-10-15; companions/README.md). The Widescreen Fix is included
    once companions/WidescreenFix has built it."""
    builds = {"TexWizard.asi": os.path.join(COMPANIONS, "texwizard", "out", "TexWizard.asi")}
    wsf = os.path.join(COMPANIONS, "WidescreenFix", "out", WSF)
    if os.path.isfile(wsf):
        builds[WSF] = wsf
    return builds


def set_ini_value(data, section, key, value):
    """Sets key = value in [section] of CRLF .ini bytes, keeping every other byte. KeyError if absent."""
    lines = data.split(b"\r\n")
    current, found = None, False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(b"[") and s.endswith(b"]"):
            current = s[1:-1].decode("latin-1")
            continue
        m = re.match(rb"^(\s*)" + re.escape(key.encode()) + rb"(\s*=\s*)(.*)$", line)
        if m and current == section:
            lines[i] = m.group(1) + key.encode() + m.group(2) + value.encode()
            found = True
    if not found:
        raise KeyError("%s/%s not found" % (section, key))
    return b"\r\n".join(lines)


def merge_ini(current, upstream_text, overrides):
    """Our current .ini (bytes, CRLF) with every key the new build's default .ini has that ours lacks added (its
    default value, or the override given), and the overrides applied. Our own values are kept."""
    have = {}
    section = None
    for line in current.decode("latin-1").split("\r\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        elif "=" in s and not s.startswith(";"):
            have[(section, s.split("=", 1)[0].strip())] = True
    out = current.rstrip(b"\r\n").decode("latin-1")
    additions, section = {}, None
    for line in upstream_text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        elif "=" in s and not s.startswith(";"):
            key, val = s.split("=", 1)
            key = key.strip()
            if (section, key) not in have:
                val = overrides.get((section, key), val.split(";")[0].strip())
                additions.setdefault(section, []).append("%s = %s" % (key, val))
    data = (out + "\r\n").encode("latin-1")
    for sec, entries in additions.items():
        if re.search(r"^\[%s\]\s*$" % re.escape(sec), data.decode("latin-1"), re.M):
            lines = data.decode("latin-1").split("\r\n")
            idx = max(i for i, l in enumerate(lines) if l.strip() == "[%s]" % sec)
            end = idx + 1
            while end < len(lines) and not lines[end].strip().startswith("["):
                end += 1
            while end > idx + 1 and not lines[end - 1].strip():
                end -= 1
            lines[end:end] = entries
            data = "\r\n".join(lines).encode("latin-1")
        else:
            data = data.rstrip(b"\r\n") + ("\r\n\r\n[%s]\r\n" % sec + "\r\n".join(entries) + "\r\n").encode("latin-1")
    for (sec, key), val in overrides.items():
        try:
            data = set_ini_value(data, sec, key, val)
        except KeyError:
            pass
    return data


def _preflight(target, pack, builds, check_game):
    if check_game and files.game_running():
        raise Refused("speed.exe is running: close the game first")
    track = files.find(target, r"TRACKS\STREAML2RA.BUN")
    if not track:
        raise Refused("no TRACKS\\STREAML2RA.BUN in %s" % target)
    info = ups.read(open(os.path.join(pack, "Install-Part-3.ups"), "rb").read())
    crc = ups.crc32_file(track)
    if crc == info["crc_out"]:
        raise Refused("stage 1 is already installed here (the track file is already patched)")
    if crc != info["crc_in"]:
        raise Refused("the track file is not the one the patch expects (CRC32 %08x, expected %08x)" % (crc, info["crc_in"]))
    for name, path in builds.items():
        if not os.path.isfile(path):
            raise Refused("build missing: %s (%s)" % (name, path))
    for p in ("Install-Part-1.nfsms", "Install-Part-2.end", r"ModData\script.end", r"ModData\Files\scripts\X360Stuff.asi"):
        if not files.find(pack, p):
            raise Refused("pack file missing: %s" % p)
    for p in ("_ChoicesX360", "ModData", part2.LAUNCHER):
        if os.path.exists(os.path.join(target, p)):
            raise Refused("%s exists in the target (left from an earlier run?)" % p)


def run(target, pack, builds, record_dir, check_game=True, wsf_default_ini=WSF_DEFAULT_INI, hash_list=BACKUP_HASHES):
    # Absolute paths throughout: part 2 hands paths to Binarius, which runs in its own folder.
    target, pack, record_dir = os.path.abspath(target), os.path.abspath(pack), os.path.abspath(record_dir)
    _preflight(target, pack, builds, check_game)
    if hash_list and os.path.isfile(hash_list):
        check_originals(target, hash_list, ORIGINALS)
    check_record_dir(record_dir)
    os.makedirs(record_dir, exist_ok=True)
    work = os.path.join(record_dir, "work")
    os.makedirs(work, exist_ok=True)
    rec = Record(record_dir)

    def install(steps, name):
        step_record = os.path.join(record_dir, name + ".json")
        try:
            files.install(steps, target, step_record, check_game=check_game)
        finally:  # copies made before a failure are in the step's record: carry them over either way
            for e in json.load(open(step_record, encoding="utf-8")):
                rec.add(e["rel"], e["old_sha256"], e["new_sha256"])

    def write_ini(path, rel, new):
        if check_game and files.game_running():
            raise Refused("speed.exe is running: close the game first")
        old = open(path, "rb").read()
        if new != old:
            rec.add(rel, files.sha256_bytes(old), files.sha256_bytes(new))
            open(path, "wb").write(new)

    # 1. VisualBridge off (the pack has its own exposure and bloom)
    vb = files.find(target, r"scripts\VisualBridge.ini")
    if vb:
        write_ini(vb, r"scripts\VisualBridge.ini", set_ini_value(open(vb, "rb").read(), "Look", "Enabled", "0"))

    # 2. Part 1: the database
    r1 = part1.run(files.find(target, "GLOBAL"), pack, OPTIONS, os.path.join(work, "part1"))
    # Back into the original's layout, so the profile's fingerprint (the car walk order) stays the same
    original_db = open(files.find(target, r"GLOBAL\attributes.bin"), "rb").read()
    ordered = vlt_order.match(open(r1["attributes_bin"], "rb").read(), original_db)
    if vlt_order.walk_orders(ordered) != vlt_order.walk_orders(original_db):
        raise RuntimeError("the reordered database still walks differently from the original")
    with open(r1["attributes_bin"], "wb") as f:
        f.write(ordered)
    install(files.plan([r"file_copy result\attributes.bin GLOBAL\attributes.bin"], os.path.join(work, "part1"), target),
            "part1-database")

    # 3. Part 1's file copies; the markers are part 2's business; our builds replace the bundled plugins
    _db, actions, opts = nfsms.expand(os.path.join(pack, "Install-Part-1.nfsms"), pack, OPTIONS)
    actions = [a for a in actions if "_ChoicesX360" not in a]
    steps = files.plan(actions, pack, target)
    for s in steps:
        name = os.path.basename(s["dst"])
        if name in builds:
            s["src"], s["sha256"] = builds[name], files.sha256(builds[name])
            s["kind"] = "same" if os.path.exists(s["dst"]) and files.sha256(s["dst"]) == s["sha256"] else "replaces"
    install(steps, "part1-files")

    # 4. Part 2: textures in the packed files (Binarius). The files it may change are recorded as pending
    #    before it starts, so even a crash during the run leaves a usable record.
    old = {rel: files.sha256(files.find(target, rel)) for rel in PART2_FILES}
    rec.add_pending(PART2_FILES, old)
    markers = {m: opts.get(m, False) for m in part2.MARKER_OPTIONS}
    try:
        r2 = part2.run(target, pack, markers, check_game=check_game)
    finally:
        rec.resolve_pending(target)
    if r2["error_log"].strip():
        raise RuntimeError("part 2 reported errors (changed files are in the record):\n" + r2["error_log"])

    # 4b. The memory file: stop it caching the files part 2 changed
    gmf = files.find(target, r"GLOBAL\GlobalMemoryFile.bin")
    new_gmf = memfile.disable(open(gmf, "rb").read(), UNCACHE, memfile.used_hashes_of(target))
    with open(os.path.join(work, "GlobalMemoryFile.bin"), "wb") as f:
        f.write(new_gmf)
    install(files.plan([r"file_copy GlobalMemoryFile.bin GLOBAL\GlobalMemoryFile.bin"], work, target), "memfile")

    # 5. Part 3: the track file, through a checked new file
    new_track = os.path.join(work, "STREAML2RA.BUN")
    ups.apply_file(os.path.join(pack, "Install-Part-3.ups"), files.find(target, r"TRACKS\STREAML2RA.BUN"), new_track)
    install(files.plan([r"file_copy STREAML2RA.BUN TRACKS\STREAML2RA.BUN"], work, target), "part3-track")
    os.remove(new_track)

    # 6. Widescreen Fix: only when a build of ours is given
    if WSF in builds:
        install(files.plan([r"file_copy %s scripts\%s" % (WSF, WSF)], os.path.dirname(builds[WSF]), target), "wsf")
        ini = files.find(target, r"scripts\NFSMostWanted.WidescreenFix.ini")
        if ini and wsf_default_ini and os.path.isfile(wsf_default_ini):
            upstream = open(wsf_default_ini, encoding="utf-8", errors="replace").read()
            write_ini(ini, r"scripts\NFSMostWanted.WidescreenFix.ini",
                      merge_ini(open(ini, "rb").read(), upstream, WSF_OVERRIDES))

    shutil.rmtree(work, ignore_errors=True)
    summary = {"target": target, "options": {k: v for k, v in opts.items()}, "dropped_db_lines": r1["dropped"],
               "builds": {k: files.sha256(v) for k, v in builds.items()}, "files": rec.entries}
    with open(os.path.join(record_dir, "stage1-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary


if __name__ == "__main__":
    target = sys.argv[1]
    builds = default_builds()
    print("builds:", ", ".join(sorted(builds)))
    import time
    record = os.path.join(ROOT, "telemetry", "x360-stage1-record-" + time.strftime("%Y%m%d-%H%M%S"))
    s = run(target, os.path.join(ROOT, ".superpowers", "visual-research", "x360-complex"), builds, record,
            check_game="--game" in sys.argv)
    print("%d files added or replaced; record in %s" % (len(s["files"]), record))
