"""Adds or removes the ReTex texture pack (C i P H E R, 2.02) as a second TexWizard pack, with a record and an exact undo.

    python tools/textures/retex.py install <game folder> <extracted ReTex folder> <records folder>
    python tools/textures/retex.py undo <game folder> <records folder>

install: copies <extracted>/TexturePacks/ReTex/{TEXTURES.BIN, meta.json} to <game>/TexturePacks/ReTex/ and lists
"TexturePacks\\ReTex" after the existing packs in <game>/scripts/TexWizard.json (TexWizard: the last listed pack wins
for a texture two packs both replace). Nothing else is copied: not ReTex's own TexWizard.asi or TexWizard.json (ours
stay), not its optional flare settings (they edit the game's database). The pack's files are not changed (its licence
forbids it). The record (JSON, one per install) holds TexWizard.json's previous bytes and the copied files' SHA-256.
undo: restores TexWizard.json byte for byte and removes the copied files (and TexturePacks if install made it);
refuses if TexWizard.json or a copied file changed since the install. Refuses while speed.exe runs.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PACK = "TexturePacks\\ReTex"
FILES = ("TEXTURES.BIN", "meta.json")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def game_running():
    """True when speed.exe runs, or when that cannot be found out (a failed tasklist counts as running: safer)."""
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq speed.exe"], capture_output=True, text=True)
    except OSError:
        return True
    return result.returncode != 0 or "speed.exe" in result.stdout.lower()


def fail(message):
    print("refused: " + message)
    sys.exit(1)


def latest_record(records):
    names = sorted(n for n in os.listdir(records) if n.startswith("retex-") and n.endswith(".json")) if os.path.isdir(records) else []
    for name in reversed(names):
        record = json.load(open(os.path.join(records, name)))
        if not record.get("undone"):
            return os.path.join(records, name), record
    return None, None


def with_pack(data):
    """TexWizard.json's bytes with PACK appended to "packs", in the file's own line endings."""
    text = data.decode("utf-8")
    packs = json.loads(text)["packs"]
    if PACK in packs:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    root = json.loads(text)
    root["packs"] = packs + [PACK]
    body = json.dumps(root, indent=2).replace("\n", newline)
    return body.encode("utf-8")


def install(game, source, records):
    if game_running():
        fail("the game is running; close it first")
    path, _ = latest_record(records)
    if path:
        fail("already installed (record %s); undo first" % path)
    json_path = os.path.join(game, "scripts", "TexWizard.json")
    before = open(json_path, "rb").read()
    after = with_pack(before)
    if after is None:
        fail("TexWizard.json already lists " + PACK)
    src = os.path.join(source, "TexturePacks", "ReTex")
    for name in FILES:
        if not os.path.isfile(os.path.join(src, name)):
            fail("missing " + os.path.join(src, name))
    root_dir = os.path.join(game, "TexturePacks")
    made_root = not os.path.exists(root_dir)
    dest = os.path.join(root_dir, "ReTex")
    if os.path.exists(dest):
        fail(dest + " exists already")
    # The record goes first (marked unfinished), then the files, then TexWizard.json; any failure rolls back what was
    # done and drops the record, so a failed install leaves nothing behind and a later install is not refused.
    os.makedirs(records, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(records, "retex-%s.json" % stamp)
    record = {"installed": stamp, "game": os.path.abspath(game), "made_texturepacks": made_root,
              "texwizard_json_before": base64.b64encode(before).decode(), "texwizard_json_after_sha256": hashlib.sha256(after).hexdigest(),
              "copied": {}, "unfinished": True}
    json.dump(record, open(path, "w"), indent=2)
    try:
        os.makedirs(dest)
        for name in FILES:
            shutil.copyfile(os.path.join(src, name), os.path.join(dest, name))
            record["copied"][name] = sha(os.path.join(dest, name))
            if record["copied"][name] != sha(os.path.join(src, name)):
                raise IOError("copy of %s differs from the source" % name)
        open(json_path, "wb").write(after)
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        if made_root and os.path.isdir(root_dir) and not os.listdir(root_dir):
            os.rmdir(root_dir)
        if open(json_path, "rb").read() != before:
            open(json_path, "wb").write(before)
        os.remove(path)
        fail("install failed and was rolled back (%s)" % e)
    del record["unfinished"]
    json.dump(record, open(path, "w"), indent=2)
    copied = record["copied"]
    print("installed: %s listed after the existing packs; %s; record %s" % (PACK, ", ".join("%s %s" % (n, copied[n][:16]) for n in FILES), path))


def undo(game, records):
    if game_running():
        fail("the game is running; close it first")
    path, record = latest_record(records)
    if not path:
        fail("no install record in " + records)
    if os.path.normcase(os.path.abspath(game)) != os.path.normcase(record["game"]):
        fail("%s is not the game folder of the record %s (%s)" % (game, path, record["game"]))
    json_path = os.path.join(game, "scripts", "TexWizard.json")
    if hashlib.sha256(open(json_path, "rb").read()).hexdigest() != record["texwizard_json_after_sha256"]:
        fail("TexWizard.json changed since the install; restore it by hand from the record " + path)
    dest = os.path.join(game, "TexturePacks", "ReTex")
    for name, digest in record["copied"].items():
        if sha(os.path.join(dest, name)) != digest:
            fail("%s changed since the install" % name)
    extra = sorted(set(os.listdir(dest)) - set(record["copied"]))
    if extra:
        fail("%s holds extra files not from the install (%s); move them out first" % (dest, ", ".join(extra)))
    open(json_path, "wb").write(base64.b64decode(record["texwizard_json_before"]))
    for name in record["copied"]:
        os.remove(os.path.join(dest, name))
    os.rmdir(dest)
    if record["made_texturepacks"] and not os.listdir(os.path.join(game, "TexturePacks")):
        os.rmdir(os.path.join(game, "TexturePacks"))
    record["undone"] = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    json.dump(record, open(path, "w"), indent=2)
    print("undone: TexWizard.json restored, ReTex removed; record " + path)


if __name__ == "__main__":  # importable (the release installer reuses with_pack)
    if len(sys.argv) == 5 and sys.argv[1] == "install":
        install(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 4 and sys.argv[1] == "undo":
        undo(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)
