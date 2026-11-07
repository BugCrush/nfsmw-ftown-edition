"""Cost of one effect in the stand-in benchmark: splits the BENCH seconds (stdout of run.py scene-bench-*-toggle)
into the stretches where the toggled effect was on and off (VisualBridge.log "toggle: <name> on/off") and compares
frames a second and the milliseconds per frame spent preparing (work) and waiting in Present.

    python visual/tests/bench-compare.py <stdout.txt> <VisualBridge.log>
    python visual/tests/bench-compare.py <stdout.txt> <VisualBridge.log> --ready "wet shaders compiled"
    python visual/tests/bench-compare.py --test

The stand-in's clock (BENCH t=) starts when its device is made; the plugin's clock starts when it is loaded, a
moment earlier: the offset is taken from the plugin's "hooks installed" line (the first effect, made right after the
device). Seconds within 0.5 s of a switch are left out.
"""
import re
import sys


def bench_lines(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"BENCH t=(\d+) frames=(\d+) work_ms=([\d.]+) present_ms=([\d.]+)", line)
        if m and int(m.group(2)) > 0:
            out.append((int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))))
    return out


def plugin_lines(text):
    start, switches = 0.0, []
    for line in text.splitlines():
        m = re.match(r"\[\s*([\d.]+)\] (.*)", line)
        if not m:
            continue
        t, rest = float(m.group(1)), m.group(2)
        if rest.startswith("hooks installed"):
            start = t
        s = re.match(r"toggle: (\w+) (on|off)", rest)
        if s:
            switches.append((t, s.group(2) == "on"))
    return start, switches


def ready_time(text, marker):
    """The plugin time of the first log line containing `marker`, or None."""
    for line in text.splitlines():
        m = re.match(r"\[\s*([\d.]+)\] (.*)", line)
        if m and marker in m.group(2):
            return float(m.group(1))
    return None


def state(switches, t):
    """On/off over the stand-in second [t, t+1) in plugin time, or None if it contains a switch (+-0.5 s)."""
    current = None
    for when, on in switches:
        if when <= t - 0.5:
            current = on
        elif when < t + 1.5:
            return None
    return current


def compare(bench, start, switches, ready=None):
    groups = {True: [], False: []}
    for t, frames, work, present in bench:
        if t < 2:
            continue  # start-up: shader compiling, first frames
        if ready is not None and t + start < ready + 0.5:
            continue  # the effect is not working yet (--ready)
        s = state(switches, t + start)
        if s is not None:
            groups[s].append((frames, work, present))
    out = {}
    for s, rows in groups.items():
        if rows:
            n = len(rows)
            out[s] = (sum(r[0] for r in rows) / n, sum(r[1] for r in rows) / n, sum(r[2] for r in rows) / n, n)
    return out


def self_test():
    # On in plugin seconds [0,3), off [3,6), ...; plugin starts 0.2 s before the stand-in. On: 100 fps, off: 120.
    switches = [(3.0 * k + 0.0, k % 2 == 0) for k in range(9)]
    bench = []
    for t in range(24):
        on = (int(t + 0.2) // 3) % 2 == 0
        bench.append((t, 100 if on else 120, 1.0, 9.0 if on else 7.3))
    r = compare(bench, 0.2, switches)
    assert abs(r[True][0] - 100) < 1e-9 and abs(r[False][0] - 120) < 1e-9, r
    lines = "BENCH t=3 frames=99 work_ms=1.00 present_ms=9.00\nnoise\n"
    assert bench_lines(lines) == [(3, 99, 1.0, 9.0)]
    start, sw = plugin_lines("[   0.200] hooks installed (first effect: X)\n[   3.000] toggle: aa off\n")
    assert start == 0.2 and sw == [(3.0, False)], (start, sw)
    # --ready: the effect only works from a logged moment (wet's shaders compile on a worker thread): seconds before
    # it are left out. Here "on" before plugin second 9 cost nothing (as if not ready): with ready at 9 only the real
    # "on" seconds count.
    bench2 = [(t, (100 if t + 0.2 >= 9 else 120) if (int(t + 0.2) // 3) % 2 == 0 else 120, 1.0, 8.0) for t in range(24)]
    assert ready_time("[   9.000] wet shaders compiled (5900 ms)\n", "wet shaders compiled") == 9.0
    r = compare(bench2, 0.2, switches, ready=9.0)
    assert abs(r[True][0] - 100) < 1e-9 and abs(r[False][0] - 120) < 1e-9, r
    r = compare(bench2, 0.2, switches)
    assert r[True][0] > 100, r  # without --ready the unready seconds dilute the cost
    print("self-test passed")


def main():
    if "--test" in sys.argv:
        self_test()
        return
    bench = bench_lines(open(sys.argv[1], encoding="utf-8", errors="replace").read())
    log = open(sys.argv[2], encoding="utf-8", errors="replace").read()
    start, switches = plugin_lines(log)
    ready = None
    if "--ready" in sys.argv:
        marker = sys.argv[sys.argv.index("--ready") + 1]
        ready = ready_time(log, marker)
        if ready is None:
            sys.exit("no log line contains %r: the effect never got ready" % marker)
        print("from plugin second %.1f (%s)" % (ready, marker))
    r = compare(bench, start, switches, ready)
    for s in (False, True):
        if s in r:
            fps, work, present, n = r[s]
            print("effect %-3s: %2d s  %.0f frames/s  %.2f ms a frame (work %.2f, Present %.2f)"
                  % ("on" if s else "off", n, fps, 1000.0 / fps, work, present))
    if True in r and False in r:
        print("cost: %.3f ms a frame (%.0f -> %.0f frames/s)" % (1000.0 / r[True][0] - 1000.0 / r[False][0], r[False][0], r[True][0]))


main()
