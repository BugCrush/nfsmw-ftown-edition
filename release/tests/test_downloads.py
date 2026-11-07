"""downloads.py: finding the player's third-party files by content, on small synthetic folders."""
import hashlib
import json
import os
import tempfile
import zipfile

from ftedition import downloads


def _item(files, anchor, archive=None, id_="mod"):
    return {"id": id_, "name": "A mod", "author": "someone", "page": "https://example.org/mod",
            "archive": archive, "anchor": anchor, "needed_by": ["x"],
            "contents": [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in files.items()]}


FILES = {"Install.txt": b"anchor file", "Data/a.bin": b"aaaa", "Data/b.bin": b"bbbbbb"}


def _write(root, files):
    for p, b in files.items():
        full = os.path.join(root, *p.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(b)


def test_find_by_content_ignores_names():
    dl = tempfile.mkdtemp()
    root = os.path.join(dl, "renamed by the browser (1)", "nested")
    _write(root, FILES)
    _write(dl, {"unrelated.txt": b"aaaa"})  # same size as a needed file, other content
    found = downloads.locate({"mod": _item(FILES, "Install.txt")}, [dl], tempfile.mkdtemp())
    assert isinstance(found["mod"], downloads.Found), found["mod"]
    assert os.path.normcase(found["mod"].root) == os.path.normcase(root)


def test_wrong_hash_refused():
    dl = tempfile.mkdtemp()
    bad = dict(FILES, **{"Data/b.bin": b"bbbbbX"})
    _write(dl, bad)
    found = downloads.locate({"mod": _item(FILES, "Install.txt")}, [dl], tempfile.mkdtemp())
    m = found["mod"]
    assert isinstance(m, downloads.Missing)
    assert "Data/b.bin" in m.reason and "https://example.org/mod" in m.reason, m.reason


def test_missing_item():
    found = downloads.locate({"mod": _item(FILES, "Install.txt")}, [tempfile.mkdtemp()], tempfile.mkdtemp())
    assert isinstance(found["mod"], downloads.Missing)
    assert "https://example.org/mod" in found["mod"].reason


def test_zip_is_read_directly():
    dl, src = tempfile.mkdtemp(), tempfile.mkdtemp()
    z = os.path.join(src, "mod.zip")
    with zipfile.ZipFile(z, "w") as f:
        for p, b in FILES.items():
            f.writestr("Mod v1/" + p, b)
    data = open(z, "rb").read()
    os.replace(z, os.path.join(dl, "whatever-name.zip"))
    arch = {"name": "mod.zip", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    work = tempfile.mkdtemp()
    found = downloads.locate({"mod": _item(FILES, "Install.txt", arch)}, [dl], work)
    assert isinstance(found["mod"], downloads.Found), found["mod"]
    assert os.path.normcase(found["mod"].root).startswith(os.path.normcase(work))


def test_unextracted_rar_message():
    dl = tempfile.mkdtemp()
    data = b"Rar!\x1a\x07\x00 pretend archive"
    open(os.path.join(dl, "mod.rar"), "wb").write(data)
    arch = {"name": "mod.rar", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    found = downloads.locate({"mod": _item(FILES, "Install.txt", arch)}, [dl], tempfile.mkdtemp())
    m = found["mod"]
    assert isinstance(m, downloads.Missing) and "7-Zip" in m.reason and "mod.rar" in m.reason, m.reason


def test_load_checks_fields():
    p = os.path.join(tempfile.mkdtemp(), "d.json")
    json.dump({"items": [_item(FILES, "Install.txt")]}, open(p, "w"))
    items = downloads.load(p)
    assert set(items) == {"mod"}
    json.dump({"items": [dict(_item(FILES, "Nope.txt"))]}, open(p, "w"))
    try:
        downloads.load(p)
    except ValueError as e:
        assert "anchor" in str(e)
    else:
        raise AssertionError("an anchor outside contents must be rejected")


def test_shipped_downloads_json_is_consistent():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "downloads.json")
    if not os.path.exists(path):
        raise AssertionError("release/downloads.json missing")
    items = downloads.load(path)
    for i in items.values():
        assert i["page"].startswith("https://"), i["id"]
        assert i["contents"], i["id"]


def test_two_zips_extract_into_one_root():
    dl, work = tempfile.mkdtemp(), tempfile.mkdtemp()
    arch = []
    for name, part in (("runtime.zip", {"Install.txt": FILES["Install.txt"], "Data/a.bin": FILES["Data/a.bin"]}),
                       ("desktop.zip", {"Data/b.bin": FILES["Data/b.bin"]})):
        z = os.path.join(dl, name)
        with zipfile.ZipFile(z, "w") as f:
            for p, b in part.items():
                f.writestr(p, b)
        data = open(z, "rb").read()
        arch.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    found = downloads.locate({"mod": _item(FILES, "Install.txt", arch)}, [dl], work)
    assert isinstance(found["mod"], downloads.Found), found["mod"]
    os.remove(os.path.join(dl, "desktop.zip"))
    found = downloads.locate({"mod": _item(FILES, "Install.txt", arch)}, [dl], tempfile.mkdtemp())
    assert isinstance(found["mod"], downloads.Missing) and "desktop.zip" not in found["mod"].reason
