"""Our settings in other authors' .ini files: one value changed at a time, every other byte kept.

settings.json: {"<game-relative .ini>": {"_default": "<payload-relative file copied when the game has none>",
                                         "<section>": {"<key>": "<value>"}}}
A key the file does not have is reported and skipped (an older or newer build of that plugin). The value is replaced
in place: the line's own spacing, its trailing comment and the comment's column are kept (where the new value fits),
and so are the file's line endings (CRLF or LF).
"""
import re

_SECTION = re.compile(rb"^\s*\[([^\]]+)\]\s*$")


def set_value(data, section, key, value):
    """(new bytes, True) with key = value in [section], or (data, False) when the key is not there."""
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.split(nl)
    current = None
    pat = re.compile(rb"^(\s*" + re.escape(key.encode()) + rb"\s*=\s*)([^;\s]*)(\s*)(;.*)?$")
    for i, line in enumerate(lines):
        m = _SECTION.match(line)
        if m:
            current = m.group(1).decode("latin-1").strip()
            continue
        if current != section:
            continue
        m = pat.match(line)
        if not m:
            continue
        head, comment = m.group(1), m.group(4)
        new = head + value.encode()
        if comment is not None:
            column = len(line) - len(comment)
            new += b" " * max(1, column - len(new)) + comment
        else:
            new += m.group(3)
        lines[i] = new
        return nl.join(lines), True
    return data, False


def apply(data, sections):
    """data with every key of {section: {key: value}} set; returns (bytes, [missing "section/key"])."""
    missing = []
    for section, keys in sections.items():
        if section.startswith("_"):
            continue
        for key, value in keys.items():
            data, ok = set_value(data, section, key, value)
            if not ok:
                missing.append("%s/%s" % (section, key))
    return data, missing
