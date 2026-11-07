"""Long frames in a PresentMon recording, each beside what the plugins logged around it (docs/ftown-notes.md "Run H
fixes (2026-11-04)", fault 5).

    python tools/citymap/long_frames.py <nfsmw-fps-*.csv> <log dir> [--min-ms 200] [--offset S] [--window LO HI]

The recording's clock (TimeInMs, from PresentMon's start) is put on the plugins' clock (seconds since their load) by
`--offset` (plugin = recording - offset); without it, the offset is found from FTownLoader's LOADED line (F8: the
city's read, the longest frame within 3 s of it). Prints each frame of at least --min-ms with WorldProbe's POS (place,
speed) before it and every other plugin line within 2 s. With --window LO HI (plugin seconds) prints that span's
average FPS, 1% low (the frame time at the 99th percentile) and the frames over 20 ms.
"""
import csv
import glob
import os
import re
import sys

LINE = re.compile(r"^\[\s*([0-9.]+)\]\s+(.*)$")


def frames(path):
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append((float(row["TimeInMs"]) / 1000.0, float(row["MsBetweenPresents"]),
                            float(row["MsCPUBusy"]) if row.get("MsCPUBusy") not in (None, "NA") else float("nan"),
                            float(row["MsGPUBusy"]) if row.get("MsGPUBusy") not in (None, "NA") else float("nan")))
            except (KeyError, ValueError):
                continue
    return out


def logs(d):
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.log"))):
        name = os.path.basename(p)
        if name.endswith(".prev.log") or name in ("fps-recorder.log",):
            continue
        for raw in open(p, encoding="utf-8", errors="replace"):
            m = LINE.match(raw.rstrip("\r\n"))
            if m:
                out.append((float(m.group(1)), name[:-4], m.group(2)))
    out.sort()
    return out


def offset_from_f8(fr, lines):
    f8 = [t for t, n, s in lines if n == "FTownLoader" and s.startswith("LOADED")]
    if not f8:
        return None
    best = max(((ms, t) for t, ms, _c, _g in fr), key=lambda x: x[0])  # fallback: the longest frame
    cands = [(ms, t) for t, ms, _c, _g in fr]
    # try offsets that put the longest frame near F8 for each candidate in the top 20
    top = sorted(cands, reverse=True)[:20]
    for ms, t in top:
        off = t - f8[0]
        if 0.0 <= off <= 30.0:
            return off
    return best[1] - f8[0]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    min_ms, off, window = 200.0, None, None
    if "--min-ms" in argv:
        i = argv.index("--min-ms")
        min_ms = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--offset" in argv:
        i = argv.index("--offset")
        off = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--window" in argv:
        i = argv.index("--window")
        window = (float(argv[i + 1]), float(argv[i + 2]))
        argv = argv[:i] + argv[i + 2 + 1:]
    fr = frames(argv[0])
    lines = logs(argv[1])
    if off is None:
        off = offset_from_f8(fr, lines) or 0.0
    print("offset: plugin seconds = recording seconds - %.3f" % off)
    pos = [(t, s) for t, n, s in lines if n == "WorldProbe" and s.startswith("POS")]
    if window:
        sel = [ms for t, ms, _c, _g in fr if window[0] <= t - off <= window[1]]
        if sel:
            s = sorted(sel)
            p99 = s[min(len(s) - 1, int(0.99 * len(s)))]
            print("window %.1f-%.1f s: %d frames, %.1f FPS average, 1%% low %.1f FPS; frames over 20 ms: %d, over "
                  "50 ms: %d" % (window[0], window[1], len(sel), 1000.0 * len(sel) / sum(sel), 1000.0 / p99,
                                 sum(1 for x in sel if x > 20), sum(1 for x in sel if x > 50)))
    for t, ms, cpu, gpu in fr:
        if ms < min_ms:
            continue
        pt = t - off
        before = [p for p in pos if p[0] <= pt]
        where = before[-1][1][:110] if before else "-"
        print("\n%.3f s (recording %.3f): %.0f ms (CPU busy %.1f, GPU busy %.1f)  last POS: %s" % (
            pt, t, ms, cpu, gpu, where))
        for lt, n, s in lines:
            if pt - 2.0 - ms / 1000.0 <= lt <= pt + 2.0 and n != "WorldProbe" or (
                    n == "WorldProbe" and abs(lt - pt) <= 2.0 and not s.startswith("POS")):
                if pt - 2.0 - ms / 1000.0 <= lt <= pt + 2.0:
                    print("   %9.3f %-12s %s" % (lt, n, s[:150]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
