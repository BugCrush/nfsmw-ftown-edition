"""Parser for GfxProbe.log's machine-readable lines: "[  12.345] TAG key=value key=value ...".

parse(path)    -> [(seconds, tag, {key: value})]; other lines (plain sentences) are skipped.
reports(lines) -> one dict per periodic report: {"t": seconds, "FRAMEMAP": {...}, "STAGE": [...],
                  "LABEL": [...], "SHAPE": [...], "COPY": [...], "TIME": [...], "MSAA": [...]}

A value runs to the next " key=" token. After path= or dir= the rest of the line is the value (paths may
contain spaces and "=").
"""
import re

LINE = re.compile(r"^\[\s*([\d.]+)\]\s+([A-Z]+)\s+(\S+=.*)$")
KEY = re.compile(r"^([a-z_0-9]+)=(.*)$")
REST_OF_LINE = ("path", "dir")
REPORT_TAGS = ("STAGE", "LABEL", "SHAPE", "COPY", "TIME", "MSAA", "OVERFLOW", "FXCHANGE")


def parse(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = LINE.match(raw.rstrip("\r\n"))
            if not m:
                continue
            fields, key = {}, None
            tokens = m.group(3).split(" ")
            for i, token in enumerate(tokens):
                k = KEY.match(token)
                if k and key not in REST_OF_LINE:
                    key = k.group(1)
                    fields[key] = k.group(2)
                    if key in REST_OF_LINE:
                        fields[key] = " ".join([k.group(2)] + tokens[i + 1:])
                        break
                elif key:
                    fields[key] += " " + token
            out.append((float(m.group(1)), m.group(2), fields))
    return out


def reports(lines):
    out = []
    for t, tag, fields in lines:
        if tag == "FRAMEMAP":
            out.append({"t": t, "FRAMEMAP": fields, **{name: [] for name in REPORT_TAGS}})
        elif tag in REPORT_TAGS and out:
            out[-1][tag].append(fields)
    return out


def parse_calls(path):
    """A dissection's calls.txt: "call key=value key=value ..." per line -> [(call, {key: value})]."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            tokens = raw.rstrip("\r\n").split(" ")
            if not tokens or not tokens[0]:
                continue
            fields, key = {}, None
            for token in tokens[1:]:
                k = KEY.match(token)
                if k:
                    key = k.group(1)
                    fields[key] = k.group(2)
                elif key:
                    fields[key] += " " + token
            out.append((tokens[0], fields))
    return out
