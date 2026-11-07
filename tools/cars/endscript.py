"""Flattens a Binary/Binarius endscript for Binarius's command line, which cannot answer menus.

`append <file>` lines are replaced by that file's lines (paths relative to the main script's folder, as Binarius
resolves them), and each `combobox "a" "b" ... "prompt"` block is replaced by the lines of the label chosen for that
prompt. Version, watermark and [VERSNx] lines are dropped (the command line fails on `version`, see
tools/x360/part2.py); the result starts with one [VERSN2]. `if ... end` blocks are kept as they are.

    flatten(main_script, base_dir, choices={prompt: label}, drop=(line prefixes to leave out)) -> [lines]
"""
import os
import re

QUOTED = re.compile(r'"([^"]*)"')


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return [l.rstrip("\r\n").strip() for l in f]


def _combobox(lines, i, choices):
    """lines[i] is the combobox line: returns (chosen lines, index after the block's end)."""
    labels = QUOTED.findall(lines[i])
    prompt, options = labels[-1], labels[:-1]
    if prompt not in choices:
        raise ValueError("no choice given for the menu %r (options: %s)" % (prompt, ", ".join(options)))
    want = choices[prompt]
    if want not in options:
        raise ValueError("menu %r has no option %r (options: %s)" % (prompt, want, ", ".join(options)))
    branches, current, depth, j = {}, None, 0, i + 1
    while j < len(lines):
        l = lines[j]
        word = l.split()[0] if l else ""
        if depth == 0 and l.startswith('"') and QUOTED.fullmatch(l):
            current = QUOTED.fullmatch(l).group(1)
            branches[current] = []
        elif depth == 0 and word == "end":
            return branches.get(want, []), j + 1
        else:
            if word == "if":
                depth += 1
            elif word == "end":
                depth -= 1
            if current is not None:
                branches[current].append(l)
        j += 1
    raise ValueError("menu %r has no closing end" % prompt)


def _expand(lines, base_dir, choices, drop):
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        word = l.split()[0] if l else ""
        if word == "combobox":
            chosen, i = _combobox(lines, i, choices)
            out += _expand(chosen, base_dir, choices, drop)
            continue
        i += 1
        if not l or l.startswith("[VERSN") or word in ("version", "watermark"):
            continue
        if word == "append":
            rel = l.split(None, 1)[1].strip().strip('"')
            out += _expand(_read(os.path.join(base_dir, rel.replace("\\", os.sep))), base_dir, choices, drop)
            continue
        if any(l.startswith(p) for p in drop):
            continue
        out.append(l)
    return out


def flatten(main_script, base_dir, choices, drop=()):
    return ["[VERSN2]"] + _expand(_read(main_script), base_dir, choices, tuple(drop))
