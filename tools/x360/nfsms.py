"""Expands an NFS-VltEd installer ModScript into plain Attribulator commands and file actions.

The installer's own commands (ui_text, ui_control, ui_option, script, file_copy, folder_create) are handled
here; everything else is a database command for Attribulator. Names are written the way Attribulator's
Most Wanted profile spells them: hash-only fields and collections as 0x%08X.
"""
import glob
import os

import yaml

from vlthash import vlt32

# Field names NFS-VltEd knows but Attribulator holds only as hashes (tests/test_vlthash.py proves each).
HASHED_FIELDS = {"BlackBloomCurve": "0xAAACCDF3", "ColourBloomCurve": "0x1D521C97", "DetailMapCurve": "0x51376819",
                 "feCarPartInfo": "0x1002EA65"}
DB_COMMANDS = ("update_field", "resize_field")


def _upper_hex(name):
    return "0x" + name[2:].upper() if name.lower().startswith("0x") else name


def _field_names(words):
    if words[0] in DB_COMMANDS and len(words) > 3:
        # a field may carry an index: feCarPartInfo[1]
        base, bracket, index = words[3].partition("[")
        f = _upper_hex(base)
        words = words[:3] + [HASHED_FIELDS.get(f, f) + bracket + index] + words[4:]
    return " ".join(words)


def expand(script_path, pack_root, overrides):
    """Returns (database lines, file actions, options) for the given option overrides (name -> bool)."""
    options, db_lines, actions = {}, [], []
    radio = set()  # radiobutton groups: options[group] is the chosen value (a string), not a bool

    def on(key):
        return options[key[0]] == key[1] if isinstance(key, tuple) else options[key]

    def run(path, active):
        stack = []
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                # ui_text, ui_image, ...: the installer's display; only ui_control and ui_option matter here
                if not line or line.startswith(("#", "//")) or (line.startswith("ui_") and
                                                                 not line.startswith(("ui_control", "ui_option"))):
                    continue
                words = line.split()
                cmd = words[0]
                if cmd == "ui_control":
                    if words[1] == "radiobutton":
                        # ui_control radiobutton <group> <value> "label": one of the group's values is chosen
                        radio.add(words[2])
                        if words[2] not in options:
                            options[words[2]] = overrides.get(words[2], words[3])
                        continue
                    name = words[2]
                    options[name] = overrides.get(name, words[3] == "true")
                    continue
                if cmd == "ui_option":
                    key = (words[1], words[2]) if words[1] in radio and len(words) > 2 else words[1]
                    if stack and stack[-1] == key:
                        stack.pop()
                    else:
                        stack.append(key)
                    continue
                if not active or not all(on(o) for o in stack):
                    continue
                if cmd == "script":
                    # the pack writes `script ModData\x.nfsms` (from the pack root); car mods write
                    # `script "Attributes\x.nfsms"` relative to the including script's folder
                    rel = line.split(None, 1)[1].strip().strip('"').replace("\\", os.sep)
                    near = os.path.join(os.path.dirname(path), rel)
                    run(near if os.path.exists(near) else os.path.join(pack_root, rel), True)
                elif cmd in ("file_copy", "folder_create"):
                    actions.append(line)
                else:
                    db_lines.append(_field_names(words))
        if stack:
            raise ValueError("unclosed ui_option in %s: %s" % (path, stack))

    run(script_path, True)
    return db_lines, actions, options


def load_collections(unpack_dir, classes):
    """class -> set of collection names as the unpack spells them (YAML hex numbers normalised), or None."""
    out = {}
    for cls in classes:
        # every vault: main/attributes/db/<cls>.yml, main/fe_attrib/frontend/frontend.yml, main/gameplay/<v>/...
        paths = glob.glob(os.path.join(unpack_dir, "main", "*", "*", cls + ".yml"))
        if not paths:
            out[cls] = None
            continue
        out[cls] = set()
        for path in paths:
            with open(path, encoding="utf-8") as f:
                items = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []
            out[cls] |= {"0x%08X" % n if isinstance(n, int) else str(n) for n in (i["Name"] for i in items)}
    return out


def _resolve_name(names, name):
    if name in names:
        return name
    if name.lower().startswith("0x"):
        upper = _upper_hex(name)
        return upper if upper in names else None
    hashed = "0x%08X" % vlt32(name)
    return hashed if hashed in names else None


def resolve(db_lines, collections, hashed_fields=None):
    """Rewrites collection names to the unpack's spelling; drops lines whose class or collection is absent.
    hashed_fields (class -> {"0x%08X"}, load_hashed_fields) lets field names the database holds only as hashes be
    written as their hash."""
    kept, dropped = [], {}
    collections = {k: (set(v) if v is not None else None) for k, v in collections.items()}
    for line in db_lines:
        w = line.split()
        if w[0] == "add_node" and len(w) >= 4:
            # add_node <class> <parent> <name>: the parent must exist; the new name is known from here on
            names = collections.get(w[1])
            found = _resolve_name(names, w[2]) if names is not None else None
            if not found:
                key = "%s/%s%s" % (w[1], w[2], " (no such class)" if names is None else "")
                dropped[key] = dropped.get(key, 0) + 1
                continue
            w[2] = found
            names.add(w[3])
            kept.append(" ".join(w))
            continue
        if w[0] == "copy_node" and len(w) >= 5:
            # copy_node <class> <source> <parent> <name>: source and parent must exist; the copy is known from here on
            names = collections.get(w[1])
            missing = None
            for i in (2, 3):
                found = _resolve_name(names, w[i]) if names is not None else None
                if not found:
                    missing = w[i]
                    break
                w[i] = found
            if missing is not None:
                key = "%s/%s%s" % (w[1], missing, " (no such class)" if names is None else "")
                dropped[key] = dropped.get(key, 0) + 1
                continue
            names.add(w[4])
            kept.append(" ".join(w))
            continue
        if w[0] in DB_COMMANDS or w[0] == "add_field":
            names = collections.get(w[1])
            found = _resolve_name(names, w[2]) if names is not None else None
            if not found:
                key = "%s/%s%s" % (w[1], w[2], " (no such class)" if names is None else "")
                dropped[key] = dropped.get(key, 0) + 1
                continue
            w[2] = found
            if len(w) > 3 and hashed_fields and hashed_fields.get(w[1]):
                # a field the database holds only as a hash (CameraInfo_Hood -> 0xD74C1435); the index stays
                base, bracket, index = w[3].partition("[")
                hashed = "0x%08X" % vlt32(base)
                if not base.lower().startswith("0x") and hashed in hashed_fields[w[1]]:
                    w[3] = hashed + bracket + index
            line = " ".join(w)
        kept.append(line)
    return kept, dropped


def _shape(value):
    if isinstance(value, dict):
        if "Data" in value and isinstance(value["Data"], list):  # an array: the shape of its elements
            elems = [e for e in value["Data"] if isinstance(e, dict)]
            return set(elems[0]) if elems else "scalar"
        return set(value)
    return "scalar"


def load_field_shapes(unpack_dir, classes):
    """class -> field -> "scalar" or the set of member names of the field (or of its array's elements)."""
    out = {}
    for cls in classes:
        shapes = {}
        for path in glob.glob(os.path.join(unpack_dir, "main", "*", "*", cls + ".yml")):
            with open(path, encoding="utf-8") as f:
                items = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []
            for it in items:
                for k, v in (it.get("Data") or {}).items():
                    name = "0x%08X" % k if isinstance(k, int) else str(k)
                    if name not in shapes or (shapes[name] == "scalar" and isinstance(_shape(v), set)):
                        shapes[name] = _shape(v)
        out[cls] = shapes
    return out


# VltEd's names for members Attribulator (VaultLib) spells otherwise, tried against Attribulator 2.0.0 on 2026-10-31.
STRING_KEY_MEMBERS = ("Collision64", "Collision", "Visual")  # StringKey64 (MODEL): the value is set as a whole
UPGRADE_SPEC_MEMBERS = {"Class": "ReferencedRow Class", "Collection": "ReferencedRow Collection",
                        "Level": "UpgradeLevel"}  # ShiftSND, TurboSND: a reference plus an upgrade level
MEMBER_ALIASES = {"MaxG": "MaxGs"}  # CarBodyMotion (BodyDive, BodyRoll, BodySquat)


def model_collisions(lines):
    """(class, collection) -> (visual name, collision name) where a script sets a StringKey64 field's collision part
    to another name than its visual part (the Chiron: Visual CHIRON, Collision FORDGT). Attribulator holds one name, so
    the collision the mod wanted must be provided under the visual name (copy_collection in Binarius)."""
    visual, collision = {}, {}
    for w in (l.split() for l in lines):
        if w[0] == "update_field" and len(w) == 6 and w[4] in STRING_KEY_MEMBERS:
            (visual if w[4] == "Visual" else collision)[(w[1], w[2])] = w[5]
    return {k: (visual[k], collision[k]) for k in visual if k in collision and collision[k] != visual[k]}


def translate(lines, shapes):
    """Rewrites VltEd member paths in update_field lines into Attribulator's, by the field's shape in our database."""
    with_visual = {(w[1], w[2], w[3]) for w in (l.split() for l in lines)
                   if w[0] == "update_field" and len(w) == 6 and w[4] == "Visual"}
    out = []
    for line in lines:
        w = line.split()
        if w[0] == "update_field" and len(w) >= 6:
            field = w[3].partition("[")[0]
            shape = shapes.get(w[1], {}).get(field)
            member = w[4]
            if shape == "scalar" and member in STRING_KEY_MEMBERS:
                # one name for the whole field: the visual one wins (see model_collisions for the collision part)
                if member != "Visual" and (w[1], w[2], w[3]) in with_visual:
                    continue
                w = w[:4] + w[5:]
            elif isinstance(shape, set) and "ReferencedRow" in shape and member in UPGRADE_SPEC_MEMBERS:
                w = w[:4] + UPGRADE_SPEC_MEMBERS[member].split() + w[5:]
            elif isinstance(shape, set) and member not in shape and MEMBER_ALIASES.get(member) in shape:
                w = w[:4] + [MEMBER_ALIASES[member]] + w[5:]
            line = " ".join(w)
        out.append(line)
    return out


def load_layout(unpack_dir):
    """class -> field -> True if the field is a base field (InLayout: every collection has it), from info.yml."""
    with open(os.path.join(unpack_dir, "info.yml"), encoding="utf-8") as f:
        info = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}
    out = {}
    for cls in info.get("Classes", []):
        fields = {}
        for fld in cls.get("Fields") or []:
            name = "0x%08X" % fld["Name"] if isinstance(fld["Name"], int) else str(fld["Name"])
            fields[name] = "InLayout" in str(fld.get("Flags", ""))
        out[str(cls["Name"])] = fields
    return out


def base_fields(lines, layout):
    """VltEd accepts add_field for base fields; Attribulator refuses ("is a base field"): every collection has them,
    so a size becomes resize_field and a plain add_field is left out."""
    out = []
    for line in lines:
        w = line.split()
        if w[0] == "add_field" and len(w) >= 4 and layout.get(w[1], {}).get(w[3]):
            if len(w) >= 5:
                out.append("resize_field %s %s %s %s" % (w[1], w[2], w[3], w[4]))
            continue
        out.append(line)
        if w[0] == "add_field" and len(w) >= 5:
            # Attribulator's add_node copies the parent's fields: add_field then finds the field and keeps its size
            out.append("resize_field %s %s %s %s" % (w[1], w[2], w[3], w[4]))
    return out


def size_new_arrays(lines, layout=None):
    """For collections the script creates (add_node), an array field it writes by index without add_field first is
    given room for the highest index it uses (Attribulator would create it with one element; VltEd sizes it):
    resize_field for a base field, add_field otherwise."""
    layout = layout or {}
    created, declared, need = set(), set(), {}
    for line in lines:
        w = line.split()
        if w[0] == "add_node" and len(w) >= 4:
            created.add((w[1], w[3]))
        elif w[0] in ("add_field", "resize_field") and len(w) >= 4:
            declared.add((w[1], w[2], w[3]))
        elif w[0] == "update_field" and len(w) >= 4 and (w[1], w[2]) in created and "[" in w[3]:
            field, _, index = w[3].partition("[")
            key = (w[1], w[2], field)
            need[key] = max(need.get(key, 0), int(index.rstrip("]")) + 1)
    out, done = [], set()
    for line in lines:
        w = line.split()
        if w[0] in ("add_field", "resize_field") and len(w) >= 4:
            done.add((w[1], w[2], w[3]))
        if w[0] == "update_field" and len(w) >= 4 and "[" in w[3]:
            key = (w[1], w[2], w[3].partition("[")[0])
            # sized only if no add_field/resize_field for it came earlier (VltEd scripts often resize after writing)
            if key in need and key not in done:
                cmd = "resize_field" if layout.get(key[0], {}).get(key[2]) else "add_field"
                out.append("%s %s %s %s %d" % (cmd, key[0], key[1], key[2], need[key]))
                done.add(key)
        out.append(line)
    return out


def load_link_classes(unpack_dir, classes):
    """class -> link field -> the class its links point to in our data (the most common non-empty ClassKey)."""
    from collections import Counter
    out = {}
    for cls in classes:
        seen = {}
        for path in glob.glob(os.path.join(unpack_dir, "main", "*", "*", cls + ".yml")):
            with open(path, encoding="utf-8") as f:
                items = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []
            for it in items:
                for k, v in (it.get("Data") or {}).items():
                    name = "0x%08X" % k if isinstance(k, int) else str(k)
                    refs = v.get("Data") if isinstance(v, dict) and isinstance(v.get("Data"), list) else [v]
                    for r in refs:
                        if isinstance(r, dict) and "ClassKey" in r and "CollectionKey" in r and r["ClassKey"]:
                            seen.setdefault(name, Counter())[str(r["ClassKey"])] += 1
        out[cls] = {f: c.most_common(1)[0][0] for f, c in seen.items()}
    return out


def link_classes(lines, classes):
    """A link field set by `Collection` alone (VltEd knows the field's class) also gets its `Class` (Attribulator
    keeps the class per value and would leave it empty: the game then finds nothing)."""
    has_class = {(w[1], w[2], w[3]) for w in (l.split() for l in lines)
                 if w[0] == "update_field" and len(w) == 6 and w[4] == "Class"}
    out = []
    for line in lines:
        out.append(line)
        w = line.split()
        if w[0] == "update_field" and len(w) == 6 and w[4] == "Collection" and (w[1], w[2], w[3]) not in has_class:
            target = classes.get(w[1], {}).get(w[3].partition("[")[0])
            if target:
                out.append("update_field %s %s %s Class %s" % (w[1], w[2], w[3], target))
                has_class.add((w[1], w[2], w[3]))
    return out


def drop_past_resized(lines):
    """After `resize_field <class> <collection> <field> N`, writes to index N or above of that field are left out (the
    Tomahawk shrinks GEAR_RATIO to 4 and zeroes entries 4-7; VltEd ignores them, Attribulator stops)."""
    size, out = {}, []
    for line in lines:
        w = line.split()
        if w[0] == "resize_field" and len(w) >= 5:
            size[(w[1], w[2], w[3])] = int(w[4])
        elif w[0] == "update_field" and len(w) >= 4 and "[" in w[3]:
            field, _, index = w[3].partition("[")
            limit = size.get((w[1], w[2], field))
            if limit is not None and int(index.rstrip("]")) >= limit:
                continue
        out.append(line)
    return out


def keep_collection_names(lines):
    """Attribulator's `copy_fields <class> <source> <target> base` copies the CollectionName field as well; VltEd
    leaves the target its own. The game builds names from it (SECONDARY_LOGO_<CollectionName>: the Flip Car showed
    the Clio's logo), so the target's own name is written back after the copy."""
    out = []
    for line in lines:
        out.append(line)
        w = line.split()
        if w[0] == "copy_fields" and len(w) >= 4:
            out.append("update_field %s %s CollectionName %s" % (w[1], w[3], w[3]))
    return out


def load_hashed_fields(unpack_dir, classes):
    """class -> the field names its unpack writes as hashes ("0x%08X"), from the collections' Data keys."""
    out = {}
    for cls in classes:
        keys = set()
        for path in glob.glob(os.path.join(unpack_dir, "main", "*", "*", cls + ".yml")):
            with open(path, encoding="utf-8") as f:
                items = yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or []
            for it in items:
                for k in (it.get("Data") or {}):
                    if isinstance(k, int):
                        keys.add("0x%08X" % k)
                    elif str(k).lower().startswith("0x"):
                        keys.add(_upper_hex(str(k)))
        out[cls] = keys
    return out
