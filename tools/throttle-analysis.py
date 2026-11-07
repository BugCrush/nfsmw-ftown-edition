"""Does NFS Most Wanted use analog throttle and brake? Measures it from InputBridge telemetry.

    python tools/throttle-analysis.py [--raw] [telemetry.csv]     (default: the newest in telemetry/)

By default samples are grouped by the trigger value the game received (after InputBridge's [Triggers]
shaping): that measures the game. With --raw they're grouped by how far the trigger was physically
pressed: that measures how the trigger feels with the current shaping.

For every sample it computes the car's acceleration (km/h per second, over a 0.3 s window), keeps only
clean samples, groups them by trigger position, and compares the groups within the same speed band,
because a car accelerates less at higher speed whatever the throttle.

Throttle samples: RT held steady (moved < 5% over the window), LT released, a forward gear, 5+ km/h,
                  nitrous not in use (its level not falling).
Brake samples:    LT held steady, RT released, a forward gear (LT in reverse accelerates backwards),
                  10+ km/h, nitrous not in use.

If acceleration rises with RT position inside a speed band, the game uses analog throttle. If 30% RT
accelerates as hard as 100%, the game treats any press as full.
"""
import csv
import glob
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_S = 0.3
TRIGGER_BINS = [(0.05, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 0.95), (0.95, 1.01)]
SPEED_BANDS = [(5, 40), (40, 80), (80, 130), (130, 400)]


def load(path):
    rows = []
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if float(r['speed_kmh']) < 0:
                continue  # speed unavailable
            rows.append({k: float(v) for k, v in r.items()})
    return rows


def with_acceleration(rows):
    """Pairs each sample with the one WINDOW_S later; returns (sample, accel km/h/s, trigger drift)."""
    out = []
    j = 0
    for i, a in enumerate(rows):
        j = max(j, i + 1)
        while j < len(rows) and rows[j]['time_s'] - a['time_s'] < WINDOW_S:
            j += 1
        if j >= len(rows):
            break
        b = rows[j]
        dt = b['time_s'] - a['time_s']
        if dt > WINDOW_S * 2:
            continue  # gap in the log (pause, menu)
        out.append((a, b, (b['speed_kmh'] - a['speed_kmh']) / dt))
    return out


def spearman(xs, ys):
    """Rank correlation, -1..1: does y go up when x goes up?"""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        for rank, k in enumerate(order):
            r[k] = rank
        return r
    if len(xs) < 3:
        return float('nan')
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var if var else float('nan')


def report(title, samples, trigger, sign):
    """samples: (row, accel) with the trigger in row[trigger]; sign flips braking to positive."""
    print(f'\n{title}')
    print(f'  {"speed band":>13} | ' + ' | '.join(f'{str(int(lo*100)) + "-" + str(min(int(hi*100), 100)) + "%":^10}' for lo, hi in TRIGGER_BINS)
          + ' | correlation')
    for lo_s, hi_s in SPEED_BANDS:
        band = [(r, a * sign) for r, a in samples if lo_s <= r['speed_kmh'] < hi_s]
        if not band:
            continue
        cells = []
        for lo, hi in TRIGGER_BINS:
            vals = [a for r, a in band if lo <= r[trigger] < hi]
            cells.append(f'{statistics.median(vals):5.1f}/{len(vals):<4}' if len(vals) >= 5 else f'{"-":>5}/{len(vals):<4}')
        rho = spearman([r[trigger] for r, _ in band], [a for _, a in band])
        print(f'  {str(lo_s) + "-" + str(hi_s) + " km/h":>13} | ' + ' | '.join(cells) + f' | {rho:+.2f} (n={len(band)})')
    everything = [(r, a * sign) for r, a in samples]
    rho = spearman([r[trigger] for r, _ in everything], [a for _, a in everything])
    print(f'  cells: median km/h per second / number of samples. Overall correlation {rho:+.2f} (n={len(everything)}).')


def main():
    args = [a for a in sys.argv[1:] if a != '--raw']
    raw = '--raw' in sys.argv[1:]
    if args:
        path = args[0]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, 'telemetry', 'nfsmw-telemetry-*.csv')))
        if not files:
            sys.exit('No telemetry CSV found in telemetry/.')
        path = files[-1]
    rows = load(path)
    print(f'{path}: {len(rows)} samples, {rows[-1]["time_s"] - rows[0]["time_s"]:.0f} s' if rows else f'{path}: no samples')
    if not rows:
        return
    if raw:
        for r in rows:  # group by physical trigger travel instead of what the game received
            r['rt'], r['lt'] = r['rt_raw'] / 255, r['lt_raw'] / 255
        print('Grouped by physical trigger travel (--raw).')
    pairs = with_acceleration(rows)

    def no_nitrous(a, b):
        return not (a['nitrous'] >= 0 and b['nitrous'] >= 0 and b['nitrous'] < a['nitrous'] - 0.001)

    throttle = [(a, acc) for a, b, acc in pairs
                if a['lt'] < 0.05 and b['lt'] < 0.05 and a['gear'] >= 1 and a['speed_kmh'] >= 5
                and a['rt'] >= 0.05 and abs(b['rt'] - a['rt']) < 0.05 and no_nitrous(a, b)]
    brake = [(a, acc) for a, b, acc in pairs
             if a['rt'] < 0.05 and b['rt'] < 0.05 and a['gear'] >= 1 and b['gear'] >= 1 and a['speed_kmh'] >= 10
             and a['lt'] >= 0.05 and abs(b['lt'] - a['lt']) < 0.05 and no_nitrous(a, b)]

    report('THROTTLE: acceleration (km/h per second) by RT position', throttle, 'rt', 1)
    report('BRAKE: deceleration (km/h per second) by LT position', brake, 'lt', -1)
    print('\nReading it: within a speed band, if the numbers grow left to right (and the correlation is clearly '
          'positive), the game uses the partial trigger position. Flat rows mean any press counts as full.')


if __name__ == '__main__':
    main()
