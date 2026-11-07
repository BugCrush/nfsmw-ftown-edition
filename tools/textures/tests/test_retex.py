"""Known-answer tests for tools/textures/retex.py on a fake game folder (no game data).
    python tools/textures/tests/test_retex.py
"""
import json
import os
import shutil
import subprocess
import sys
import stat
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "retex.py")
ORIGINAL_JSON = b'{\r\n  "packs":\r\n  [\r\n    "TRACKS\\\\TexWizardX360"\r\n  ]\r\n}'
failed = 0


def expect(ok, what):
    global failed
    print(("  ok   " if ok else "  FAIL ") + what)
    failed += 0 if ok else 1


def run(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True)


def make(root):
    game = os.path.join(root, "game")
    os.makedirs(os.path.join(game, "scripts"))
    os.makedirs(os.path.join(game, "TRACKS", "TexWizardX360"))
    open(os.path.join(game, "scripts", "TexWizard.json"), "wb").write(ORIGINAL_JSON)
    pack = os.path.join(root, "extracted", "TexturePacks", "ReTex")
    os.makedirs(pack)
    open(os.path.join(pack, "TEXTURES.BIN"), "wb").write(b"\xB3\x30\x00\x00" + os.urandom(5000))
    open(os.path.join(pack, "meta.json"), "wb").write(b'{"textures": [["A", "B"]]}')
    os.makedirs(os.path.join(root, "extracted", "SCRIPTS"))
    open(os.path.join(root, "extracted", "SCRIPTS", "TexWizard.asi"), "wb").write(b"theirs")
    return game, os.path.join(root, "extracted"), os.path.join(root, "records")


scratch = os.path.join(HERE, "..", "..", "..", ".superpowers", "tmp")
os.makedirs(scratch, exist_ok=True)
root = tempfile.mkdtemp(dir=scratch)
try:
    game, src, records = make(root)
    print("install")
    r = run("install", game, src, records)
    expect(r.returncode == 0, "install succeeds: " + r.stdout[-300:] + r.stderr[-300:])
    packs = json.loads(open(os.path.join(game, "scripts", "TexWizard.json"), "rb").read().decode())["packs"]
    expect(packs == ["TRACKS\\TexWizardX360", "TexturePacks\\ReTex"], "ReTex listed after the Xbox 360 pack: %s" % packs)
    expect(b"\r\n" in open(os.path.join(game, "scripts", "TexWizard.json"), "rb").read(), "TexWizard.json keeps CRLF")
    copied = os.path.join(game, "TexturePacks", "ReTex", "TEXTURES.BIN")
    expect(open(copied, "rb").read() == open(os.path.join(src, "TexturePacks", "ReTex", "TEXTURES.BIN"), "rb").read(),
           "TEXTURES.BIN copied byte for byte")
    expect(not os.path.exists(os.path.join(game, "scripts", "TexWizard.asi")), "their TexWizard.asi is not copied")
    expect(len(os.listdir(records)) == 1, "one record written")
    print("install twice")
    r = run("install", game, src, records)
    expect(r.returncode != 0 and "already" in r.stdout + r.stderr, "a second install refuses")
    print("undo")
    r = run("undo", game, records)
    expect(r.returncode == 0, "undo succeeds: " + r.stdout[-300:] + r.stderr[-300:])
    expect(open(os.path.join(game, "scripts", "TexWizard.json"), "rb").read() == ORIGINAL_JSON, "TexWizard.json back byte for byte")
    expect(not os.path.exists(os.path.join(game, "TexturePacks")), "TexturePacks removed (it did not exist before)")
    print("changed json refuses undo")
    run("install", game, src, records)
    open(os.path.join(game, "scripts", "TexWizard.json"), "ab").write(b" ")
    r = run("undo", game, records)
    expect(r.returncode != 0 and "changed" in r.stdout + r.stderr, "undo refuses when TexWizard.json changed since install")
    print("undo refuses with an extra file in the pack folder, changing nothing")
    root2 = tempfile.mkdtemp(dir=scratch)
    game2, src2, records2 = make(root2)
    run("install", game2, src2, records2)
    installed_json = open(os.path.join(game2, "scripts", "TexWizard.json"), "rb").read()
    open(os.path.join(game2, "TexturePacks", "ReTex", "extra.txt"), "w").write("not ours")
    r = run("undo", game2, records2)
    expect(r.returncode != 0 and "extra" in r.stdout + r.stderr, "undo refuses: %s" % (r.stdout + r.stderr)[-200:])
    expect(open(os.path.join(game2, "scripts", "TexWizard.json"), "rb").read() == installed_json, "TexWizard.json untouched")
    expect(os.path.isfile(os.path.join(game2, "TexturePacks", "ReTex", "TEXTURES.BIN")), "the pack's files untouched")
    os.remove(os.path.join(game2, "TexturePacks", "ReTex", "extra.txt"))
    print("undo refuses another game folder than the record's")
    other = os.path.join(root2, "othergame")
    shutil.copytree(game2, other)
    r = run("undo", other, records2)
    expect(r.returncode != 0 and "not the game folder of the record" in r.stdout + r.stderr, "undo refuses: %s" % (r.stdout + r.stderr)[-200:])
    r = run("undo", game2, records2)
    expect(r.returncode == 0, "undo of the right folder still works")
    print("a failed install leaves nothing behind")
    json_path = os.path.join(game2, "scripts", "TexWizard.json")
    before = open(json_path, "rb").read()
    os.chmod(json_path, stat.S_IREAD)  # the write of TexWizard.json fails
    r = run("install", game2, src2, records2)
    os.chmod(json_path, stat.S_IREAD | stat.S_IWRITE)
    expect(r.returncode != 0, "the install reports failure")
    expect(not os.path.exists(os.path.join(game2, "TexturePacks")), "no TexturePacks folder left behind")
    expect(open(json_path, "rb").read() == before, "TexWizard.json unchanged")
    names = [n for n in os.listdir(records2) if n.endswith(".json")]
    pending = [n for n in names if not json.load(open(os.path.join(records2, n))).get("undone")]
    expect(pending == [], "no record of an install that did not happen, got %s" % pending)
    r = run("install", game2, src2, records2)
    expect(r.returncode == 0, "a later install works: %s" % (r.stdout + r.stderr)[-200:])
    shutil.rmtree(root2, ignore_errors=True)
finally:
    shutil.rmtree(root, ignore_errors=True)
print("FAIL (%d)" % failed if failed else "PASS")
sys.exit(1 if failed else 0)
