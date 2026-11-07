"""GfxProbe's 15 s summaries beside WorldProbe's positions: per window the frame time, draw calls a frame and the main
scene's draws and triangles, and where the car was (docs/ftown-notes.md "Run H fixes (2026-11-04)", fault 4).

    python tools/citymap/gfx_windows.py <GfxProbe.log> <WorldProbe.log>

Both plugins' clocks start at their load (a few ms apart at the game's start); a window is the 15 s before its line.
"""
import re
import sys

LINE = re.compile(r"^\[\s*([0-9.]+)\]\s+(.*)$")


def windows(gfx):
    out, cur = [], None
    for raw in open(gfx, encoding="utf-8", errors="replace"):
        m = LINE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        t, rest = float(m.group(1)), m.group(2)
        if rest.startswith("--- last"):
            mm = re.search(r"(\d+) frames, (\d+) draw calls \((\d+) per frame\)", rest)
            cur = {"t": t, "frames": int(mm.group(1)), "draws": int(mm.group(3)), "stages": {}}
            out.append(cur)
        elif cur is not None and rest.startswith("STAGE"):
            kv = dict(re.findall(r"(\w+)=([^ ]+)", rest))
            key = "%s/%s" % (kv["target"], kv["visit"])
            cur["stages"][key] = (float(kv["draws"]), float(kv["tris"]), float(kv.get("out_ms", 0)))
        elif cur is not None and rest.startswith("TIME"):
            kv = dict(re.findall(r"(\w+)=([^ ]+)", rest))
            cur["frame_ms"] = float(kv["frame_ms"])
    return out


def positions(wp):
    out = []
    for raw in open(wp, encoding="utf-8", errors="replace"):
        m = LINE.match(raw.rstrip("\r\n"))
        if m and " POS " in " " + m.group(2):
            r = re.search(r"render \(([-0-9.]+), ([-0-9.]+), ([-0-9.]+)\).*speed ([0-9.]+)", m.group(2))
            if r:
                out.append((float(m.group(1)),) + tuple(float(x) for x in r.groups()))
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    ws, ps = windows(argv[0]), positions(argv[1])
    print("%8s %6s %8s %6s %9s %9s %7s  %s" % ("t", "frames", "frame_ms", "draws", "scene", "scene_tri", "shadow",
                                                "car (render x, y, z; km/h, median over the window)"))
    for w in ws:
        sc = w["stages"].get("T8/2", (0, 0, 0))
        sh = sum(v[0] for k, v in w["stages"].items() if k.startswith("T20/"))
        inw = [p for p in ps if w["t"] - 15.0 < p[0] <= w["t"]]
        if inw:
            inw.sort(key=lambda p: p[4])
            mid = inw[len(inw) // 2]
            where = "(%.0f, %.0f, %.1f; %.0f)" % (mid[1], mid[2], mid[3], mid[4])
        else:
            where = "-"
        print("%8.1f %6d %8.2f %6d %9.0f %9.0f %7.0f  %s" % (w["t"], w["frames"], w.get("frame_ms", 0), w["draws"],
                                                            sc[0], sc[1], sh, where))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
