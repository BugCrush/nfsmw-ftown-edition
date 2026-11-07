"""Splits one session's telemetry log into races (the car back at the start line) and reports, per race, the driving
window (telemetry seconds), and from the FPS recording (offset seconds) the frame rate, 1% low, processor and
graphics-card time, and how many frames sit at the 72 FPS vsync step.

Usage: python tools/split-races.py <telemetry.csv> <fps.csv> <offset> [--start X,Y]
       python tools/split-races.py --test     (known-answer check on a made-up session)

--start: the start line's map position (pos_x, pos_y in the telemetry); the default is the fixed race's start
(Sprint "Diamond & Union", read from the 2026-10-28 session).
"""
import csv
import os
import sys
import tempfile

DEFAULT_START = (1640.566, 150.1)


def find_races(rows, start):
    """Races from telemetry rows (dicts): a race starts where the car stands still at the start line and has moved
    (over 5 km/h) before it stands there again. Returns [{"from", "to"}] in telemetry seconds."""
    races, cur = [], None
    for r in rows:
        t, x, y, v = float(r["time_s"]), float(r["pos_x"]), float(r["pos_y"]), float(r["speed_kmh"])
        at_start = abs(x - start[0]) < 1 and abs(y - start[1]) < 1
        if at_start and v < 1:
            if cur is None or cur["moving"]:
                cur = {"from": t, "to": t, "moving": False}
                races.append(cur)
            cur["from"] = t
        elif cur is not None:
            cur["to"] = t
            cur["moving"] |= v > 5
    return [{"from": r["from"], "to": r["to"]} for r in races if r["moving"]]


def summarise(frames, a, b, t0):
    """Frame-rate numbers for the recording's frames from a to b seconds after its first frame; None if none fall there."""
    sel = [f for f in frames if a <= (float(f["TimeInMs"]) - t0) / 1000 < b]
    if not sel:
        return None
    dt = [float(f["MsBetweenPresents"]) for f in sel]
    n = len(dt)
    worst = sorted(dt, reverse=True)[:max(1, n // 100)]
    return {"fps": 1000 * n / sum(dt), "low": 1000 * len(worst) / sum(worst),
            "cpu": sum(float(f["MsCPUBusy"]) for f in sel) / n, "gpu": sum(float(f["MsGPUBusy"]) for f in sel) / n,
            "capped": sum(1 for x in dt if abs(x - 13.889) < 0.35) / n}


def report(tel, fps, offset, start=DEFAULT_START):
    rows = list(csv.DictReader(open(tel)))
    frames = list(csv.DictReader(open(fps, encoding="utf-8-sig")))
    lines = []
    if not frames:
        return ["the FPS recording has no frames"]
    t0 = float(frames[0]["TimeInMs"])
    races = find_races(rows, start)
    if not races:
        lines.append("no race found: the car never stood at the start line (%.3f, %.3f) and then drove off (try --start)" % start)
    for i, race in enumerate(races):
        s = summarise(frames, race["from"] + offset, race["to"] + offset, t0)
        head = "race %d: telemetry %.0f-%.0f s (%d s)" % (i + 1, race["from"], race["to"], race["to"] - race["from"])
        if s is None:
            lines.append(head + ": no frames of the FPS recording in this window (check the offset)")
        else:
            lines.append(head + ": %.1f FPS, 1%% low %.1f, CPU %.2f ms, GPU %.2f ms, at 72 FPS step %.0f%%"
                         % (s["fps"], s["low"], s["cpu"], s["gpu"], 100 * s["capped"]))
    return lines


def self_test():
    """A made-up session: the car at the start 0-10 s, driving 10-70 s, back at the start 70-80 s, driving 80-120 s.
    The recording starts 5 s after the telemetry (offset 5) with 10 ms frames in the first race and 20 ms frames
    (GPU 3 ms) in the second. Known answers: two races, 100 and 50 FPS. With a wrong offset of 1000 s, both windows
    are empty and say so; with a wrong start position, no race."""
    folder = tempfile.mkdtemp()
    tel, fps = os.path.join(folder, "tel.csv"), os.path.join(folder, "fps.csv")
    with open(tel, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "pos_x", "pos_y", "speed_kmh"])
        for t in range(0, 121):
            at = t < 10 or 70 <= t < 80
            w.writerow([t, DEFAULT_START[0] if at else 2000, DEFAULT_START[1] if at else 300, 0 if at else 100])
    with open(fps, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["TimeInMs", "MsBetweenPresents", "MsCPUBusy", "MsGPUBusy"])
        ms = 0.0
        while ms < 130000:
            t = ms / 1000 - 5  # telemetry seconds
            dt = 20.0 if t >= 79 else 10.0
            w.writerow(["%.1f" % ms, dt, dt - 1, 3 if dt == 20 else 2])
            ms += dt
    failures = []
    got = report(tel, fps, 5)
    if len(got) != 2 or "100.0 FPS" not in got[0] or "50.0 FPS" not in got[1] or "GPU 3.00 ms" not in got[1]:
        failures.append("two races at 100 and 50 FPS: %s" % got)
    if "telemetry 9-69 s" not in got[0]:
        failures.append("race 1 from 9 to 69 s: %s" % got[:1])
    empty = report(tel, fps, 1000)
    if len(empty) != 2 or not all("no frames" in line for line in empty):
        failures.append("an empty window says so: %s" % empty)
    none = report(tel, fps, 5, start=(0.0, 0.0))
    if len(none) != 1 or "no race found" not in none[0]:
        failures.append("a wrong start finds no race: %s" % none)
    print("split-races self-test: %s" % ("FAIL\n  " + "\n  ".join(failures) if failures else "PASS"))
    return 1 if failures else 0


def main():
    if "--test" in sys.argv:
        sys.exit(self_test())
    args = [a for a in sys.argv[1:]]
    start = DEFAULT_START
    if "--start" in args:
        i = args.index("--start")
        start = tuple(float(v) for v in args[i + 1].split(","))
        del args[i:i + 2]
    if len(args) != 3:
        sys.exit(__doc__)
    for line in report(args[0], args[1], float(args[2]), start):
        print(line)


main()
