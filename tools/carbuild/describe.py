"""A car model as a "description" folder, the form later parts edit, and back.

    car.json            the pack: info, extra chunks, and per solid its decoded fields by name (name, hash, box,
                        texture and shader hashes, mesh fields) plus the undecoded bytes as hex
    vertices/<k>_<solid>.bin   the solid's vertex buffer (36 bytes per vertex, docs/carbuild-format.md)
    indices/<k>_<solid>.bin    its 16-bit indices
    obj/<k>_<solid>.obj        a viewing copy: one object per solid, one group per mesh (not read back)

`load(folder)` starts from the hex and writes the named fields over it, so editing car.json's fields takes effect,
and `write_geometry(load(dump(pack)))` gives the same bytes as `write_geometry(pack)`.
"""
import json
import os
import re
import struct

from chunks import Chunk
from geometry import GeometryPack, Mesh, Solid, solid_header

FORMAT = "carbuild-geometry-description"
VERSION = 1


def _hex(b):
    return None if b is None else b.hex()


def _unhex(s):
    return None if s is None else bytes.fromhex(s)


def _chunk_json(c):
    if c.children is not None:
        d = {"id": "0x%08X" % c.id, "children": [_chunk_json(k) for k in c.children]}
        if c.size is not None:
            d["size"] = c.size
        return d
    if c.data and not any(c.data):
        return {"id": "0x%08X" % c.id, "zeros": len(c.data)}
    return {"id": "0x%08X" % c.id, "data": c.data.hex()}


def _chunk_from(d):
    cid = int(d["id"], 16)
    if "children" in d:
        return Chunk(cid, None, [_chunk_from(k) for k in d["children"]], d.get("size"))
    if "zeros" in d:
        return Chunk(cid, bytes(d["zeros"]))
    return Chunk(cid, bytes.fromhex(d["data"]))


def file_stem(k, name):
    return "%04d_%s" % (k, re.sub(r"[^A-Za-z0-9_.-]", "_", name))


def _mesh_json(m):
    return {"bbox": list(m.bbox), "texture_slots": list(m.texture_slots), "shader_index": m.shader_index,
            "flags": "0x%X" % m.flags, "vertex_count": m.vertex_count, "triangle_count": m.triangle_count,
            "index_offset": m.index_offset, "index_count": m.index_count, "raw": m.raw.hex()}


def _mesh_raw(d):
    m = Mesh(texture_index=d["texture_slots"][0], shader_index=d["shader_index"], vertex_offset=0,
             vertex_count=d["vertex_count"], index_offset=d["index_offset"], index_count=d["index_count"], stride=36,
             flags=int(d["flags"], 16), raw=bytes.fromhex(d["raw"]), texture_slots=tuple(d["texture_slots"]),
             triangle_count=d["triangle_count"])
    return m.to_raw(d["bbox"])


def write_obj(s, path):
    """One object per solid, one group per mesh (named by its mesh name and shader index); indices are global to
    the solid so a mesh that borrows other meshes' vertices still draws."""
    lines = ["# %s (carbuild viewing copy; coordinates as stored in the game)" % s.name, "o " + s.name]
    meshes = s.meshes()
    for m in meshes:
        for p in s.positions(m):
            lines.append("v %r %r %r" % p)
    for m in meshes:
        for u, v in s.uvs(m):
            lines.append("vt %r %r" % (u, 1.0 - v))
    for m in meshes:
        for n in s.normals(m):
            lines.append("vn %r %r %r" % n)
    for k, m in enumerate(meshes):
        label = s.mesh_names[k] if k < len(s.mesh_names) else "mesh%d" % k
        tex = s.textures[m.texture_index] if s.textures and m.texture_index < len(s.textures) else 0
        shader = s.shaders[m.shader_index] if s.shaders and m.shader_index < len(s.shaders) else 0
        lines.append("g %s_%d" % (re.sub(r"\s", "_", label), k))
        lines.append("usemtl tex_%08X_shader_%08X" % (tex, shader))
        o = m.vertex_offset + 1
        for t in s.triangles(m):
            a, b, c = (i + o for i in t)
            lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (a, a, a, b, b, b, c, c, c))
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def dump(pack, folder):
    for sub in ("vertices", "indices", "obj"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    solids = []
    for k, s in enumerate(pack.solids):
        stem = file_stem(k, s.name)
        d = {"name": s.name, "name_hash": "0x%08X" % s.name_hash, "bbox": list(s.bbox), "header": s.header.hex(),
             "textures": None if s.textures is None else ["0x%08X" % h for h in s.textures],
             "shaders": None if s.shaders is None else ["0x%08X" % h for h in s.shaders],
             "mesh_header": _hex(s.mesh_header),
             "meshes": None if s.mesh_entries is None else [_mesh_json(m) for m in s.meshes()],
             "mesh_names": s.mesh_names, "other": [_chunk_json(c) for c in s.other],
             "vertices": None, "indices": None}
        for key, data in (("vertices", s.vertices), ("indices", s.indices)):
            if data is not None:
                rel = "%s/%s.bin" % (key, stem)
                with open(os.path.join(folder, rel), "wb") as f:
                    f.write(data)
                d[key] = rel
        if s.vertices:
            write_obj(s, os.path.join(folder, "obj", stem + ".obj"))
        solids.append(d)
    doc = {"format": FORMAT, "version": VERSION, "info": pack.info.hex(),
           "extra": [_chunk_json(c) for c in pack.extra], "solids": solids}
    with open(os.path.join(folder, "car.json"), "w", newline="\n") as f:
        json.dump(doc, f, indent=1)


def _read_bin(folder, rel):
    if rel is None:
        return None
    with open(os.path.join(folder, rel), "rb") as f:
        return f.read()


def load(folder):
    with open(os.path.join(folder, "car.json")) as f:
        doc = json.load(f)
    if doc.get("format") != FORMAT:
        raise ValueError("%s: not a geometry description" % folder)
    solids = []
    for d in doc["solids"]:
        name_hash = int(d["name_hash"], 16)
        header = solid_header(bytes.fromhex(d["header"]), d["name"], name_hash, d["bbox"])
        solids.append(Solid(
            name=d["name"], name_hash=name_hash, header=header,
            textures=None if d["textures"] is None else [int(h, 16) for h in d["textures"]],
            shaders=None if d["shaders"] is None else [int(h, 16) for h in d["shaders"]],
            mesh_header=_unhex(d["mesh_header"]),
            mesh_entries=None if d["meshes"] is None else [_mesh_raw(m) for m in d["meshes"]],
            vertices=_read_bin(folder, d["vertices"]), indices=_read_bin(folder, d["indices"]),
            other=[_chunk_from(c) for c in d["other"]], mesh_names=list(d["mesh_names"])))
    return GeometryPack(info=bytes.fromhex(doc["info"]), solids=solids,
                        extra=[_chunk_from(c) for c in doc["extra"]])


# ---------------------------------------------------------------- textures

TEX_FORMAT = "carbuild-textures-description"


def dump_textures(pack, folder):
    """textures.json (pack fields, per texture its decoded fields and header as hex) plus, per texture,
    textures/<k>_<name>.bin (pixel data, all mip levels), a viewing .dds, and stored/<k>.blk (the block as stored,
    then the bytes after it) so unchanged textures build back exactly."""
    from textures import to_dds
    for sub in ("textures", "stored"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    items = []
    for k, t in enumerate(pack.textures):
        stem = file_stem(k, t.name or "%08X" % t.name_hash)
        d = {"name": t.name, "name_hash": "0x%08X" % t.name_hash, "width": t.width, "height": t.height,
             "fmt": t.fmt, "mipmaps": t.mipmaps, "codec": t.codec, "size": t.size, "header": _hex(t.header),
             "data": None, "stored": None}
        if t.data is not None:
            d["data"] = "textures/%s.bin" % stem
            with open(os.path.join(folder, d["data"]), "wb") as f:
                f.write(t.data)
            with open(os.path.join(folder, "textures", stem + ".dds"), "wb") as f:
                f.write(to_dds(t))
        if t.blob is not None and t.stored_block_valid():
            d["stored"] = "stored/%04d.blk" % k
            d["stored_size"] = len(t.blob)
            d["stored_digest"] = None if t.digest is None else t.digest.hex()
            with open(os.path.join(folder, d["stored"]), "wb") as f:
                f.write(t.blob + t.slack)
        items.append(d)
    doc = {"format": TEX_FORMAT, "version": VERSION, "name": pack.name, "filename": pack.filename,
           "info": pack.raw_parts["info"].hex(), "pads": [p.hex() for p in pack.raw_parts.get("pads", [])],
           "textures": items}
    with open(os.path.join(folder, "textures.json"), "w", newline="\n") as f:
        json.dump(doc, f, indent=1)


def load_textures(folder):
    """The pack back; a texture whose data or header no longer matches its stored block is re-encoded on write."""
    from textures import Texture, TexturePack
    with open(os.path.join(folder, "textures.json")) as f:
        doc = json.load(f)
    if doc.get("format") != TEX_FORMAT:
        raise ValueError("%s: not a texture description" % folder)
    out = []
    for d in doc["textures"]:
        data = _read_bin(folder, d["data"])
        header = _unhex(d["header"])
        blob, slack = None, b""
        if d["stored"] is not None:
            raw = _read_bin(folder, d["stored"])
            blob, slack = raw[:d["stored_size"]], raw[d["stored_size"]:]
        t = Texture(name=d["name"], name_hash=int(d["name_hash"], 16), width=d["width"], height=d["height"],
                    fmt=d["fmt"], mipmaps=d["mipmaps"], data=data, header=header, codec=d["codec"], blob=blob,
                    slack=slack, size=d["size"])
        if blob is not None and d.get("stored_digest"):
            t.digest = bytes.fromhex(d["stored_digest"])  # valid for exactly the data and header it was dumped with
        out.append(t)
    return TexturePack(name=doc["name"], filename=doc["filename"], textures=out,
                       raw_parts={"info": bytes.fromhex(doc["info"]), "pads": [bytes.fromhex(p) for p in doc["pads"]]})
