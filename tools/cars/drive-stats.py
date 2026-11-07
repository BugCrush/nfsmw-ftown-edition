"""Top speed, acceleration and hits from an InputBridge telemetry recording (telemetry/nfsmw-telemetry-*.csv).

    python tools/cars/drive-stats.py <telemetry.csv> [from_s to_s]

The window is a race's time span (tools/split-races.py prints it). A "hit" is a sudden speed loss while neither
brake is pressed: at least 15 km/h within 0.25 s; its size is the speed lost over the following 0.5 s. A heavier car
loses less speed per hit (the other car takes more of the impact), so this is our number for ramming power.
"""
import csv
import sys

DROP_KMH, DROP_WINDOW, LOSS_WINDOW = 15.0, 0.25, 0.5


def read(path, t0=None, t1=None):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = float(r["time_s"])
            if (t0 is None or t >= t0) and (t1 is None or t <= t1):
                rows.append((t, float(r["speed_kmh"]), float(r["game_brake"]), float(r["game_handbrake"])))
    return rows


def _time_to(rows, target):
    for i, (t, v, _, _) in enumerate(rows):
        if v >= target:
            start = None
            for j in range(i, -1, -1):
                if rows[j][1] <= 0.5:  # standing still: the launch starts here
                    start = rows[j][0]
                    break
            return None if start is None else t - start
    return None


def stats(path, t0=None, t1=None):
    rows = read(path, t0, t1)
    hits, i = [], 0
    while i < len(rows):
        t, v = rows[i][0], rows[i][1]
        j, low, braked = i, v, False
        while j < len(rows) and rows[j][0] - t <= DROP_WINDOW:
            low = min(low, rows[j][1])
            braked |= rows[j][2] > 0.2 or rows[j][3] > 0.5
            j += 1
        if v - low >= DROP_KMH and not braked:
            k = i
            while k + 1 < len(rows) and rows[k + 1][1] >= v - 1.0:
                k += 1  # the hit starts where the speed begins to fall
            start_t, start_v = rows[k][0], rows[k][1]
            end = min((r[1] for r in rows[k:] if r[0] - start_t <= LOSS_WINDOW), default=start_v)
            hits.append((start_t, start_v, start_v - end))
            while i < len(rows) and rows[i][0] - start_t < 1.0:
                i += 1
            continue
        i += 1
    return {"top_kmh": max((r[1] for r in rows), default=0.0), "t_0_100": _time_to(rows, 100.0),
            "t_0_200": _time_to(rows, 200.0), "hits": hits}


def main():
    if len(sys.argv) not in (2, 4):
        sys.exit(__doc__)
    t0, t1 = (float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) == 4 else (None, None)
    s = stats(sys.argv[1], t0, t1)
    fmt = lambda x: "-" if x is None else "%.1f s" % x
    print("top speed %.1f km/h; 0-100 %s; 0-200 %s" % (s["top_kmh"], fmt(s["t_0_100"]), fmt(s["t_0_200"])))
    for t, v, lost in s["hits"]:
        print("  hit at %.1f s from %.0f km/h: lost %.0f km/h (%.0f%%)" % (t, v, lost, 100.0 * lost / max(v, 1)))
    if s["hits"]:
        print("%d hits; average loss %.0f%% of the speed" % (
            len(s["hits"]), sum(100.0 * l / max(v, 1) for _, v, l in s["hits"]) / len(s["hits"])))


if __name__ == "__main__":
    main()
