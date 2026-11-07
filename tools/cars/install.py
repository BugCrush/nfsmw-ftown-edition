"""Installs one add-on car (or the Unlimiter's game-file part) into a game folder, with a record to undo it.

    python tools/cars/install.py install <car> <game dir> <record dir>
    python tools/cars/install.py undo <game dir> <record dir>

<car> is an entry of tools/cars/cars.yaml. Steps, each optional per car:
  1. binarius: the mod's endscript flattened (tools/cars/endscript.py: menus answered from `choices`, lines in `drop`
     left out), run by Binarius's command line with a "Modder" copy of the mod's launcher (tools/x360/part2.py
     explains why);
  2. vlt: the mod's ModScript expanded (tools/x360/nfsms.py, `options`), names resolved against the game's database,
     `overrides` added for the car's frontend entry (`frontend`), applied with Attribulator; attributes.bin and
     fe_attrib.bin then put back in the game's layout with the added collections after (vlt_order.match_added);
  3. copies: [source relative path, game relative path], source paths relative to `source` (or the repo for
     paths starting with "repo:");
  4. ini: {game relative .ini: {section: {key: value}}} set after the copies.
Before anything runs, GLOBAL, FRONTEND, LANGUAGES and scripts are copied into the record; afterwards only the
originals of files that changed are kept. A memory file (GLOBAL\\*MemoryFile.bin) that still caches a changed file
makes the install fail (the game would not read the change). Sources under a "First mod" folder are refused (the
Chiron's whole-file replacements would undo the Xbox 360 pack).
"""
import configparser
import glob
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "x360"))
sys.path.insert(0, HERE)
import endscript  # noqa: E402
import memfile  # noqa: E402
import nfsms  # noqa: E402
import part1  # noqa: E402
import vlt_order  # noqa: E402

WATCH = ("GLOBAL", "FRONTEND", "LANGUAGES", "scripts")
BINARIUS_DIR = os.path.join(ROOT, ".tools", "binarius-2.10.4")
DOTNET_X86 = os.path.join(ROOT, ".tools", "dotnet-x86")
DB_FILES = ("attributes.bin", "fe_attrib.bin", "gameplay.bin")


class Refused(Exception):
    pass


class Failed(Exception):
    pass


def _speed_running():
    p = subprocess.run(["tasklist"], capture_output=True, text=True)
    return p.returncode != 0 or "speed.exe" in p.stdout.lower()


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _files(root, subdirs=None):
    out = {}
    tops = [os.path.join(root, d) for d in subdirs] if subdirs else [root]
    for top in tops:
        for dp, _, names in os.walk(top):
            for n in names:
                p = os.path.join(dp, n)
                out[_rel(root, p)] = p
    return out


def _find(root, rel):
    """The existing path for rel under root, matching each part case-insensitively."""
    cur = root
    for part in rel.replace("\\", "/").split("/"):
        names = {n.lower(): n for n in os.listdir(cur)} if os.path.isdir(cur) else {}
        if part.lower() not in names:
            return None
        cur = os.path.join(cur, names[part.lower()])
    return cur


def _source(car, rel):
    if rel.startswith("repo:"):
        return os.path.join(ROOT, rel[5:])
    return os.path.join(car["source"], rel)


def _check_sources(car):
    rels = [c[0] for c in car.get("copies", [])]
    for key in ("binarius", "vlt"):
        if key in car:
            rels += [v for k, v in car[key].items() if k in ("launcher", "base", "script")]
    for rel in rels:
        if "first mod" in rel.replace("\\", "/").lower().split("/"):
            raise Refused("refused: %s is under the mod's 'First mod' folder (whole game files)" % rel)


def _modder_launcher(text, game, script_lines=None):
    """The mod's launcher (VERSN1 JSON) marked Usage Modder, with Directory set to the game folder, and with the
    [VERSN1] line Binarius 2.10.4 requires (the Unlimiter's .endlauncher has none). With the flattened script's
    lines, the "Files" Binarius loads (and re-saves) are cut to those the script names."""
    usage = '"Usage": "User"'
    if text.count(usage) != 1:
        raise Failed("the launcher is not marked Usage User")
    directory = text[text.index('"Directory"'):].split("\n")[0].rstrip(",\r ")
    text = text.replace(usage, '"Usage": "Modder"').replace(directory, '"Directory": "%s"' % game)
    # Binarius must not load (and re-save) the databases: our database step owns them and their layout
    text = re.sub(r'\{[^{}]*"LoadType":\s*"(Attributes|FeAttrib)"[^{}]*\}\s*,?\s*', "", text)
    if script_lines is not None:
        named = "\n".join(script_lines).upper().replace("/", "\\")

        def keep(m):
            return m.group(0) if m.group(1).upper().replace("/", "\\") in named else ""
        files = re.search(r'"Files":\s*\[(.*?)\]', text, re.S)
        if files:
            body = re.sub(r'\s*"([^"]+)"\s*,?', keep, files.group(1))
            text = text[:files.start(1)] + body + "\n  " + text[files.end(1):]
    return text if text.lstrip().startswith("[VERSN1]") else "[VERSN1]\n\n" + text


def _run_binarius(car, game):
    b = car["binarius"]
    base = os.path.join(car["source"], b["base"])
    lines = endscript.flatten(os.path.join(base, b["script"]), base, b.get("choices", {}), b.get("drop", ()))
    script = os.path.join(base, "_ours-install.end")
    launcher = os.path.join(base, "_ours-launcher.end")
    with open(os.path.join(car["source"], b["launcher"]), encoding="utf-8-sig") as f:
        text = _modder_launcher(f.read(), os.path.abspath(game), lines)
    try:
        with open(script, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(lines) + "\n")
        with open(launcher, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
        env = dict(os.environ, **{"DOTNET_ROOT(x86)": DOTNET_X86, "DOTNET_ROLL_FORWARD": "Major"})
        p = subprocess.run([os.path.join(BINARIUS_DIR, "Binarius.exe"), "modder", launcher, script], cwd=BINARIUS_DIR,
                           env=env, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
        out = p.stdout + p.stderr
        if p.returncode != 0 or "successfully applied" not in out:
            err = os.path.join(BINARIUS_DIR, "EndError.log")
            raise Failed("Binarius failed (exit %d):\n%s\n%s" % (
                p.returncode, out[-2000:], open(err, errors="replace").read()[-2000:] if os.path.exists(err) else ""))
        return out
    finally:
        for p in (script, launcher):
            if os.path.exists(p):
                os.remove(p)


def _skip_classes(lines, skip):
    """Leaves out database lines of the given classes (e.g. the Unlimiter's light-flare values: the Xbox 360 pack's
    flares stay as they are)."""
    return [l for l in lines if not (len(l.split()) > 1 and l.split()[0] != "game" and l.split()[1] in skip)]


def _run_vlt(car, game, work):
    v = car["vlt"]
    src = os.path.join(work, "in")
    os.makedirs(src)
    gdir = _find(game, "GLOBAL")
    names = {}
    for f in DB_FILES:
        p = _find(game, "GLOBAL/" + f)
        names[f] = os.path.basename(p)
        shutil.copy(p, os.path.join(src, f))
    db, _actions, _opts = nfsms.expand(os.path.join(car["source"], v["script"]), car["source"], v.get("options", {}))
    db = _skip_classes(db, v.get("skip_classes", []))
    for field, value in car.get("overrides", {}).items():
        db.append("update_field frontend %s %s %s" % (car["frontend"], field, value))
    classes = {l.split()[1] for l in db if l.split()[0] in nfsms.DB_COMMANDS + ("add_node", "add_field", "copy_node")}
    ours = part1.unpack(src, os.path.join(work, "in-yml"))
    kept, dropped = nfsms.resolve(db, nfsms.load_collections(ours, classes), nfsms.load_hashed_fields(ours, classes))
    layout = nfsms.load_layout(ours)
    kept = nfsms.translate(kept, nfsms.load_field_shapes(ours, classes))
    kept = nfsms.drop_past_resized(nfsms.size_new_arrays(nfsms.base_fields(kept, layout), layout))
    kept = nfsms.keep_collection_names(nfsms.link_classes(kept, nfsms.load_link_classes(ours, classes)))
    for (cls, node), (visual, coll) in nfsms.model_collisions(db).items():
        # one name in Attribulator: the car's Binarius part must provide a collision named <visual> (copied from <coll>)
        print("note: %s %s shows model %s with %s's collision; a collision named %s must exist" % (
            cls, node, visual, coll, visual))
    if dropped:
        raise Failed("database lines refer to collections that do not exist: %s" % dropped)
    script = os.path.join(work, "car.nfsms")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(kept) + "\n")
    out = os.path.join(work, "out")
    os.makedirs(out)
    part1._attribulator("apply-script-bin", "-i", src, "-o", out, "-p", "MOST_WANTED", "-s", script)
    # Attribulator writes every file it loaded, edited or not: keep only the files holding a class the script edits
    # (the unpack's folders say which file a class lives in: main/attributes, main/fe_attrib, main/gameplay).
    edited = {os.path.relpath(p, os.path.join(ours, "main")).split(os.sep)[0] + ".bin"
              for c in classes for p in glob.glob(os.path.join(ours, "main", "*", "*", c + ".yml"))}
    for f in DB_FILES:
        if f not in edited:
            continue
        new = open(os.path.join(out, "main", f), "rb").read()
        old = open(os.path.join(src, f), "rb").read()
        if new == old:
            continue
        if f in ("attributes.bin", "fe_attrib.bin"):
            new = vlt_order.match_added(new, old)
        with open(os.path.join(gdir, names[f]), "wb") as fh:
            fh.write(new)
    return len(kept)


def _set_ini(path, values):
    cp = configparser.ConfigParser(inline_comment_prefixes=None, interpolation=None)
    cp.optionxform = str
    raw = open(path, encoding="utf-8-sig").read()
    cp.read_string(raw)
    lines = raw.splitlines()
    for section, kv in values.items():
        for key, value in kv.items():
            # keep the file as it is except the one value (comments after it included)
            sec = None
            for i, l in enumerate(lines):
                s = l.strip()
                if s.startswith("[") and s.endswith("]"):
                    sec = s[1:-1]
                elif sec == section and s.split("=")[0].strip() == key:
                    rest = l.split("=", 1)[1]
                    comment = rest[rest.index("//"):] if "//" in rest else ""
                    lines[i] = "%s = %s%s" % (key, value, (" " * 8 + comment) if comment else "")
                    break
            else:
                raise Failed("%s has no %s in [%s]" % (path, key, section))
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def _memfile_check(game, changed):
    cached = []
    gdir = _find(game, "GLOBAL")
    for n in os.listdir(gdir):
        if not n.lower().endswith("memoryfile.bin"):
            continue
        try:
            hashes = {e["hash"] for e in memfile.entries(open(os.path.join(gdir, n), "rb").read())}
        except ValueError:
            continue
        for rel in changed:
            if memfile.bhash(rel.replace("/", "\\").upper()) in hashes:
                cached.append("%s caches %s" % (n, rel))
    return cached


def install(name, car, game, record, game_running=_speed_running):
    if game_running():
        raise Refused("refused: speed.exe is running; close the game first")
    if os.path.exists(record):
        raise Refused("refused: the record folder %s exists already" % record)
    _check_sources(car)
    game, record = os.path.abspath(game), os.path.abspath(record)  # Attribulator and Binarius run elsewhere
    os.makedirs(os.path.join(record, "before"))
    before = {}
    watched = _files(game, [d for d in WATCH if os.path.isdir(os.path.join(game, d))])
    # files directly in CARS (the shared TEXTURES.BIN the Unlimiter rewrites); the car folders below are new files
    cars_dir = _find(game, "CARS")
    if cars_dir:
        for n in os.listdir(cars_dir):
            if os.path.isfile(os.path.join(cars_dir, n)):
                watched[_rel(game, os.path.join(cars_dir, n))] = os.path.join(cars_dir, n)
    # and every existing file a copy will overwrite, wherever it is (a car's VINYLS.BIN)
    for _, dst in car.get("copies", []):
        existing = _find(game, dst)
        if existing and os.path.isfile(existing):
            watched[_rel(game, existing)] = existing
    for rel, p in watched.items():
        dest = os.path.join(record, "before", rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(p, dest)
        before[rel] = _sha(p)
    all_before = set(_files(game))
    # size and time of every file, to catch a change outside the backed-up folders (nothing could undo it)
    stamps = {}
    for rel, p in _files(game).items():
        st = os.stat(p)
        stamps[rel] = (st.st_size, st.st_mtime_ns)
    log = {}
    try:
        # the database first: it works on copies and writes the game's files only once Attribulator succeeded
        if "vlt" in car:
            log["vlt_lines"] = _run_vlt(car, game, os.path.join(record, "work"))
        if "binarius" in car:
            log["binarius"] = _run_binarius(car, game)[-500:]
        for src, dst in car.get("copies", []):
            target = os.path.join(game, dst)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy(_source(car, src), target)  # a fresh time, so the outside-change check sees every write
        for rel, values in car.get("ini", {}).items():
            _set_ini(_find(game, rel), values)
    finally:
        after_files = _files(game)
        changed = sorted(r for r, h in before.items() if r in after_files and _sha(after_files[r]) != h)
        removed = sorted(r for r in before if r not in after_files)
        created = sorted(r for r in after_files if r not in all_before)
        for rel in before:
            if rel not in changed and rel not in removed:
                os.remove(os.path.join(record, "before", rel))
        for dp, dirs, files in os.walk(os.path.join(record, "before"), topdown=False):
            if not os.listdir(dp):
                os.rmdir(dp)
        shutil.rmtree(os.path.join(record, "work"), ignore_errors=True)
        not_undoable = sorted(r for r, (size, mtime) in stamps.items() if r not in before and r in after_files and
                              (os.stat(after_files[r]).st_size, os.stat(after_files[r]).st_mtime_ns) != (size, mtime))
        manifest = {"car": name, "game": game, "record": record, "changed": {r: [before[r], _sha(after_files[r])] for r in changed},
                    "removed": removed, "created": {r: _sha(after_files[r]) for r in created},
                    "not_undoable": not_undoable, "log": log}
        with open(os.path.join(record, "record.json"), "w") as f:
            json.dump(manifest, f, indent=1)
    if not_undoable:
        raise Failed("files outside the backed-up folders changed and cannot be undone by this record (restore them "
                     "from a backup): %s" % ", ".join(not_undoable))
    cached = _memfile_check(game, changed + created)
    if cached:
        raise Failed("a memory file still caches a changed file, the game would not see it: %s" % "; ".join(cached))
    return {"changed": changed, "created": sorted(created), "removed": removed}


def undo(game, record, game_running=_speed_running):
    if game_running():
        raise Refused("refused: speed.exe is running; close the game first")
    m = json.load(open(os.path.join(record, "record.json")))
    game = os.path.abspath(game)
    if os.path.normcase(m["game"]) != os.path.normcase(game):
        raise Refused("refused: the record is for %s, not %s" % (m["game"], game))
    for rel, (_, after) in m["changed"].items():
        if _sha(os.path.join(game, rel)) != after:
            raise Refused("refused: %s changed since the install; nothing undone" % rel)
    for rel, after in m["created"].items():
        p = os.path.join(game, rel)
        if os.path.exists(p) and _sha(p) != after:
            raise Refused("refused: %s changed since the install; nothing undone" % rel)
    for rel in list(m["changed"]) + m["removed"]:
        shutil.copy2(os.path.join(record, "before", rel), os.path.join(game, rel))
    for rel in m["created"]:
        p = os.path.join(game, rel)
        if os.path.exists(p):
            os.remove(p)
        d = os.path.dirname(p)
        while d != game and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)


def load_config():
    import yaml
    with open(os.path.join(HERE, "cars.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for car in cfg.values():
        car["source"] = os.path.join(ROOT, car["source"])
    return cfg


def main(argv):
    if len(argv) == 4 and argv[0] == "install":
        cfg = load_config()
        if argv[1] not in cfg:
            sys.exit("no car %r in cars.yaml (%s)" % (argv[1], ", ".join(cfg)))
        r = install(argv[1], cfg[argv[1]], argv[2], argv[3])
        print("changed:", *r["changed"], sep="\n  ")
        print("created: %d files" % len(r["created"]))
        return 0
    if len(argv) == 3 and argv[0] == "undo":
        undo(argv[1], argv[2])
        print("undone")
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (Refused, Failed) as e:
        sys.exit(str(e))
