"""Writes release/downloads.json from the research draft (release/downloads-work/downloads.draft.json, made by hashing
the official archives and the user's extractions of them).

    python release/tools/make_downloads_json.py

Keeps, per item: the installer's id, name, author, official page, download link, archive(s) (file, size, sha256),
contents (path, size, sha256), the anchor (a distinctive file of the contents), `mirror` (where the installer places
the item in its copy of the repo layout, release/installer/ftedition/steps.py), `tool_dir` for tools inside a folder,
and the licence note. DXVK and the ASI loader are left out: they ship in the package (their licences allow it).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASE = os.path.dirname(HERE)
DRAFT = os.path.join(RELEASE, "downloads-work", "downloads.draft.json")
OUT = os.path.join(RELEASE, "downloads.json")

# draft id -> (installer id, anchor, mirror (repo-relative) or None, tool_dir or None)
MAP = {
    "x360pack-complex": ("x360_complex", "Install-Part-1.nfsms", None, None),
    "x360pack-easy": ("x360_easy_cache", "GLOBAL/GlobalMemoryFile.bin", None, None),
    "x360-movies": ("x360_movies", "MOVIES/attract_movie_english_ntsc.vp6", None, None),
    "vinyls-1024-simple": ("vinyls_1024", "Binary/CARS/TEXTURES.BIN", None, None),
    "retex": ("retex", "TexturePacks/ReTex/meta.json", None, None),
    "unlimiter": ("unlimiter", "_NFSMW-Unlimiter-Part1-Binarius.endlauncher", ".superpowers/downloads/unlimiter/release", None),
    "challenger71": ("car_challenger71", "1971 Dodge Challenger RT 440/_CHALLENGER71-Part1-Binary.end",
                     ".superpowers/downloads/cars/754/files", None),
    "flipcar": ("car_flipcar", "Binary Data Install.end", ".superpowers/downloads/cars/5194/files", None),
    "chiron": ("car_chiron", "First mod/GLOBAL/GlobalB.lzc", ".superpowers/downloads/cars/697/files", None),
    "raptor": ("car_raptor", "Ford F-150 SVT Raptor v1.2.3/Raptor_BinaryInstall.end",
               ".superpowers/downloads/cars/1696/files", None),
    "longnosecab": ("car_longnosecab", "Longnose Cab Semi Truck (Addon)/install longnose cab.nfsms",
                    ".superpowers/downloads/cars/3803/files", None),
    "tomahawk": ("car_tomahawk", "Binary Files/_CarParts/CarTypeInfos.bin", ".superpowers/downloads/cars/5882/files", None),
    "attribulator": ("attribulator", "release_windows/Attribulator.CLI.dll", None, "release_windows"),
    "binarius": ("binarius", "Binarius.dll", None, None),
    "dotnet-x86": ("dotnet_x86", "dotnet.exe", None, None),
}


def main():
    draft = json.load(open(DRAFT, encoding="utf-8"))
    items = []
    for it in draft["items"]:
        if it["id"] not in MAP:
            continue
        iid, anchor, mirror, tool_dir = MAP[it["id"]]
        paths = {c["path"] for c in it["contents"]}
        if anchor not in paths:
            raise SystemExit("%s: anchor %s not in contents" % (it["id"], anchor))
        arch = it.get("archive")
        if isinstance(arch, dict):
            arch = [arch]
        out = {"id": iid, "name": it["name"], "author": it["author"], "page": it["page"],
               "download": it.get("download"), "anchor": anchor,
               "archive": [{"name": a["file"], "size": a["size"], "sha256": a["sha256"]} for a in arch] if arch else None,
               "contents": [{"path": c["path"], "size": c["size"], "sha256": c["sha256"]} for c in it["contents"]],
               "licence_note": it.get("licence", "")}
        if mirror:
            out["mirror"] = mirror
        if tool_dir:
            out["tool_dir"] = tool_dir
        items.append(out)
    missing = set(v[0] for v in MAP.values()) - {i["id"] for i in items}
    if missing:
        raise SystemExit("draft lacks %s" % sorted(missing))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"schema": 1, "note": "Every third-party file the F-Town Edition installer uses, pinned to the "
                   "official release (sha256). Made by release/tools/make_downloads_json.py.", "items": items}, f, indent=1)
        f.write("\n")
    print("%d items -> %s" % (len(items), OUT))


if __name__ == "__main__":
    main()
