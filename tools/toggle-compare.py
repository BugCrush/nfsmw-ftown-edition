"""Cost of VisualBridge's effects inside one race: splits a frame-time recording into the stretches where the
effects were on and off ([Test] ToggleSeconds; VisualBridge.log "toggle: effects on/off" lines) and compares them.

    python tools/toggle-compare.py <nfsmw-fps-*.csv> <VisualBridge.log> --from <s> --to <s> [--offset <s>] [--margin 2]
    python tools/toggle-compare.py --test

--from/--to: the driving window in the recording's seconds (as for fps-summary.py). --offset: seconds the
recording starts before the plugins' clock. Without it the tool finds the offset itself: the effects can only add
graphics-card time, so it takes the offset (from -10 to 10 s, in half seconds) at which the graphics card's time
differs most between on and off, and prints the result there and at the offsets around it (in race 6 the recording
started about 2 s after the plugins' clock, not the 4 s once assumed). --margin: seconds left out after each switch
and before the next, so a small error in the offset cannot mix the two states.
"""
import csv
import re
import sys


def switches(log_lines):
    """[(plugin seconds, on?)] from the log's toggle lines: "toggle: effects on" (everything switches) or
    "toggle: <name> on" ([Test] ToggleOnly names one effect: ao, aa, shafts, haze)."""
    out = []
    for line in log_lines:
        m = re.match(r"\[\s*([\d.]+)\] toggle: \w+ (on|off)", line)
        if m:
            out.append((float(m.group(1)), m.group(2) == "on"))
    return out


def state_at(sw, t, margin):
    """True/False for on/off at plugin time t, or None within margin of a switch or before the first."""
    for i, (start, on) in enumerate(sw):
        end = sw[i + 1][0] if i + 1 < len(sw) else float("inf")
        if start + margin <= t < end - margin:
            return on
    return None


def summarise(frames):
    """frames: frame times in ms. Average FPS, 1% low FPS, number of frames."""
    if not frames:
        return None
    n = len(frames)
    avg = 1000.0 * n / sum(frames)
    worst = sorted(frames, reverse=True)[:max(1, n // 100)]
    low = 1000.0 * len(worst) / sum(worst)
    return avg, low, n


def compare(rows, sw, start, end, offset, margin):
    """rows: [(recording seconds, frame ms, cpu ms, gpu ms)]. Returns {True: stats, False: stats}."""
    groups = {True: [], False: []}
    for t, ms, cpu, gpu in rows:
        if not start <= t < end:
            continue
        s = state_at(sw, t - offset, margin)
        if s is not None:
            groups[s].append((ms, cpu, gpu))
    out = {}
    for state, g in groups.items():
        if g:
            avg, low, n = summarise([x[0] for x in g])
            out[state] = (avg, low, n, sum(x[1] for x in g) / n, sum(x[2] for x in g) / n)
    return out


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):  # PresentMon writes NA where it has no value
        return None


def read_csv(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    t0 = float(rows[0]["TimeInMs"])
    out = []
    for r in rows:
        values = [number(r["TimeInMs"]), number(r["MsBetweenPresents"]), number(r["MsCPUBusy"]), number(r["MsGPUBusy"])]
        if None not in values:
            out.append(((values[0] - t0) / 1000.0, values[1], values[2], values[3]))
    return out


def find_offset(rows, sw, start, end, margin):
    """The offset (seconds, -10 to 10 in halves) at which the graphics card's time differs most, on minus off; when
    several offsets tie (the margin hides small offset errors), the middle of them."""
    gpu = {}
    for k in range(-20, 21):
        r = compare(rows, sw, start, end, k / 2.0, margin)
        if True in r and False in r:
            gpu[k / 2.0] = r[True][4] - r[False][4]
    top = max(gpu.values())
    tied = sorted(o for o, g in gpu.items() if g >= top - 1e-9)
    return tied[len(tied) // 2]


def self_test():
    # 120 s recording, plugin clock 4 s behind; effects on for 10 s, off for 10 s from plugin time 0.
    # On: 13 ms frames (12 ms CPU, 6 ms GPU); off: 11 ms frames (11 ms CPU, 5 ms GPU).
    sw = [(10.0 * k, k % 2 == 0) for k in range(12)]
    rows, t = [], 0.0
    while t < 120:
        on = state_at(sw, t - 4, 0)
        ms = 13.0 if on else 11.0
        rows.append((t, ms, 12.0 if on else 11.0, 6.0 if on else 5.0))
        t += ms / 1000.0
    r = compare(rows, sw, 5, 115, 4, 2)
    on, off = r[True], r[False]
    assert abs(on[0] - 1000 / 13.0) < 0.01 and abs(off[0] - 1000 / 11.0) < 0.01, r
    assert abs(on[3] - 12.0) < 1e-9 and abs(off[4] - 5.0) < 1e-9, r
    # a 1 s clock error is absorbed by the 2 s margin
    r2 = compare(rows, sw, 5, 115, 3, 2)
    assert abs(r2[True][0] - 1000 / 13.0) < 0.01 and abs(r2[False][0] - 1000 / 11.0) < 0.01, r2
    # without an offset the tool finds it: the graphics card's on/off difference is largest at the true 4 s
    # (anything within the margin gives the same answer, so 3 to 5 are all right)
    found = find_offset(rows, sw, 5, 115, 2)
    assert 3 <= found <= 5, found
    # a recording with NA values reads without them
    assert number("NA") is None and number("1.5") == 1.5
    # both line forms: everything switching ("effects") and one named effect ([Test] ToggleOnly)
    lines = ["[  10.000] toggle: effects on", "[  20.000] toggle: effects off", "[  30.000] toggle: aa on",
             "[  40.000] toggle: shafts off", "[  41.000] LOOK frames=1"]
    assert switches(lines) == [(10.0, True), (20.0, False), (30.0, True), (40.0, False)], switches(lines)
    print("self-test passed")


def main():
    if "--test" in sys.argv:
        self_test()
        return
    args = sys.argv[1:]
    opt = lambda name, default: float(args[args.index(name) + 1]) if name in args else default
    rows = read_csv(args[0])
    sw = switches(open(args[1], encoding="utf-8", errors="replace").read().splitlines())
    start, end, margin = opt("--from", 0), opt("--to", 1e9), opt("--margin", 2)
    if "--offset" in args:
        offset = opt("--offset", 0)
    else:
        offset = find_offset(rows, sw, start, end, margin)
        print("offset found: %.1f s (the recording's start before the plugins' clock)" % offset)
        for o in (offset - 2, offset - 1, offset + 1, offset + 2):
            n = compare(rows, sw, start, end, o, margin)
            if True in n and False in n:
                print("  at %+.1f s: cost %.1f FPS average, CPU %+.2f ms, GPU %+.2f ms"
                      % (o, n[False][0] - n[True][0], n[True][3] - n[False][3], n[True][4] - n[False][4]))
    r = compare(rows, sw, start, end, offset, margin)
    for state in (False, True):
        if state in r:
            avg, low, n, cpu, gpu = r[state]
            print("effects %-3s: %6d frames  average %.1f FPS  1%% low %.1f FPS  CPU %.2f ms  GPU %.2f ms"
                  % ("on" if state else "off", n, avg, low, cpu, gpu))
    if True in r and False in r:
        print("cost: %.1f FPS average, %.1f FPS 1%% low, CPU %+.2f ms, GPU %+.2f ms"
              % (r[False][0] - r[True][0], r[False][1] - r[True][1], r[True][3] - r[False][3], r[True][4] - r[False][4]))


main()
