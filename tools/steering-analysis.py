"""How does NFS Most Wanted respond to steering (and throttle)? Two independent measurements, compared.

    python tools/steering-analysis.py [telemetry.csv]     (default: the newest in telemetry/)

B, the game's own controls: InputBridge finds the player's InputControls in memory during each race and
logs `game_steer` / `game_gas` next to what it sent (`steer`, `rt`). Comparing them shows what the game
does to the input before physics: a deadzone, a curve, less steering at speed, smoothing (delay).

A, the car's movement: `turn_rate` (degrees per second) comes from the car's position. Grouping it by
steering input and speed shows the same things from the outside, through the physics.

Then A and B are compared: do they agree on where steering starts to act and how linear it is?
Clean samples only: in a forward gear, no brake, steering held steady over the window.
"""
import csv
import glob
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEER_BINS = [(0.0, 0.03), (0.03, 0.08), (0.08, 0.15), (0.15, 0.25), (0.25, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 0.95), (0.95, 1.01)]
SPEED_BANDS = [(10, 60), (60, 120), (120, 400)]
UNKNOWN_GAME = -9
UNKNOWN_TURN = -999


def load(path):
    rows = []
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            rows.append({k: float(v) for k, v in r.items()})
    return rows


def median(vals):
    return statistics.median(vals) if vals else float('nan')


def cell(vals, fmt='{:5.1f}'):
    return (fmt.format(median(vals)) + f'/{len(vals):<4}') if len(vals) >= 5 else f'{"-":>5}/{len(vals):<4}'


def bin_label(lo, hi):
    return f'{int(lo * 100)}-{min(int(hi * 100), 100)}%'


def steady(rows, i, key, window=5, tol=0.03):
    """True if rows[i-window..i][key] stays within tol (input held, not moving)."""
    if i < window:
        return False
    vals = [rows[j][key] for j in range(i - window, i + 1)]
    return max(vals) - min(vals) <= tol


def table(title, rows, input_key, value_fn, bins, value_fmt='{:5.1f}'):
    print(f'\n{title}')
    print(f'  {"speed":>12} | ' + ' | '.join(f'{bin_label(lo, hi):^10}' for lo, hi in bins))
    for lo_s, hi_s in SPEED_BANDS:
        band = [r for r in rows if lo_s <= r['speed_kmh'] < hi_s]
        if not band:
            continue
        cells = []
        for lo, hi in bins:
            vals = [value_fn(r) for r in band if lo <= abs(r[input_key]) < hi]
            vals = [v for v in vals if v is not None]
            cells.append(f'{cell(vals, value_fmt):^10}')
        print(f'  {str(lo_s) + "-" + str(hi_s) + " km/h":>12} | ' + ' | '.join(cells))


def best_lag(rows, a_key, b_key, max_lag=30):
    """Lag (samples) at which b follows a most closely; each sample is 20 ms."""
    best = (0, -2.0)
    a = [r[a_key] for r in rows]
    b = [r[b_key] for r in rows]
    for lag in range(0, max_lag + 1):
        xs, ys = a[:len(a) - lag] if lag else a, b[lag:]
        if len(xs) < 50:
            break
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        var = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        corr = cov / var if var else 0
        if corr > best[1]:
            best = (lag, corr)
    return best


def first_active_bin(rows, input_key, value_fn, threshold, min_speed=30):
    """The smallest input bin whose median response exceeds threshold (where the input starts to act)."""
    band = [r for r in rows if r['speed_kmh'] >= min_speed]
    for lo, hi in STEER_BINS:
        vals = [value_fn(r) for r in band if lo <= abs(r[input_key]) < hi]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 5 and median(vals) > threshold:
            return (lo, hi)
    return None


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, 'telemetry', 'nfsmw-telemetry-*.csv')))
        if not files:
            sys.exit('No telemetry CSV found in telemetry/.')
        path = files[-1]
    rows = load(path)
    if not rows or 'turn_rate' not in rows[0]:
        sys.exit(f'{path}: no steering columns (recorded before steering telemetry existed).')
    print(f'{path}: {len(rows)} samples, {rows[-1]["time_s"] - rows[0]["time_s"]:.0f} s')

    # --- checks -----------------------------------------------------------------------------------------
    # Position sanity: distance travelled per second vs the speedometer.
    ratios = []
    for a, b in zip(rows, rows[25:]):
        dt = b['time_s'] - a['time_s']
        if 0.4 < dt < 0.6 and a['speed_kmh'] > 30:
            dist = math.hypot(b['pos_x'] - a['pos_x'], b['pos_z'] - a['pos_z'])
            ratios.append(dist / dt * 3.6 / a['speed_kmh'])
    print(f'\nCheck: speed from position / speedometer = {median(ratios):.2f} (1.00 = position addresses are right; '
          f'{len(ratios)} samples)')

    turning = [r for r in rows if r['turn_rate'] != UNKNOWN_TURN]
    game = [r for r in rows if r['game_steer'] != UNKNOWN_GAME]
    print(f'Turn rate available in {len(turning) * 100 // max(len(rows), 1)}% of samples; '
          f'game controls found in {len(game) * 100 // max(len(rows), 1)}%.')

    # Turn-rate sign: make "positive" mean "turning the way the stick points".
    fwd = [r for r in turning if r['speed_kmh'] > 20 and abs(r['steer']) > 0.3]
    same = sum(1 for r in fwd if (r['turn_rate'] > 0) == (r['steer'] > 0))
    flip = -1 if fwd and same < len(fwd) / 2 else 1
    if fwd:
        print(f'Turn direction matches the stick in {max(same, len(fwd) - same) * 100 // len(fwd)}% of '
              f'hard-steering samples{" (sign flipped)" if flip < 0 else ""}.')

    clean_idx = [i for i, r in enumerate(rows) if r['gear'] >= 1 and r['lt'] < 0.05 and r['speed_kmh'] >= 10
                 and steady(rows, i, 'steer')]
    clean = [rows[i] for i in clean_idx]

    # --- B: what the game does to the input ---------------------------------------------------------------
    if game:
        g_clean = [r for r in clean if r['game_steer'] != UNKNOWN_GAME]
        table('B1. GAME STEERING vs what InputBridge sent: median |game steering| % by |steer|', g_clean, 'steer',
              lambda r: abs(r['game_steer']) * 100, STEER_BINS, '{:5.0f}')
        lag, corr = best_lag(game, 'steer', 'game_steer')
        print(f'  Delay: game steering follows ours best {lag * 20} ms later (correlation {corr:+.2f}).')
        print('\nB2. GAME GAS vs RT sent: median game gas % by RT')
        for lo, hi in [(0, 0.05), (0.05, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]:
            vals = [r['game_gas'] * 100 for r in game if lo <= r['rt'] < hi]
            print(f'  RT {bin_label(lo, hi):>8}: game gas {cell(vals, "{:5.0f}")}')
    else:
        print('\nB: the game\'s controls weren\'t found in this log (the finder needs full throttle straight, a '
              'release, then hard steering, during a race).')

    # --- A: how the car turns --------------------------------------------------------------------------------
    a_clean = [r for r in clean if r['turn_rate'] != UNKNOWN_TURN]
    table('A1. CAR TURN RATE: median |turn rate| (deg/s) by |steer| sent', a_clean, 'steer',
          lambda r: r['turn_rate'] * flip * (1 if r['steer'] >= 0 else -1), STEER_BINS)
    if game:
        ag = [r for r in a_clean if r['game_steer'] != UNKNOWN_GAME]
        table('A2. CAR TURN RATE by |game steering| (after the game\'s processing)', ag, 'game_steer',
              lambda r: r['turn_rate'] * flip * (1 if r['game_steer'] >= 0 else -1), STEER_BINS)

    # --- A vs B ------------------------------------------------------------------------------------------------
    print('\nA vs B')
    a_start = first_active_bin(a_clean, 'steer', lambda r: abs(r['turn_rate']), 2.0)
    print(f'  A: the car starts turning (> 2 deg/s, 30+ km/h) at |steer| {bin_label(*a_start) if a_start else "?"}')
    if game:
        b_start = first_active_bin([r for r in clean if r['game_steer'] != UNKNOWN_GAME], 'steer',
                                   lambda r: abs(r['game_steer']), 0.02)
        print(f'  B: the game\'s steering becomes non-zero at |steer| {bin_label(*b_start) if b_start else "?"}')
        for lo_s, hi_s in SPEED_BANDS:
            band = [r for r in clean if lo_s <= r['speed_kmh'] < hi_s and r['game_steer'] != UNKNOWN_GAME]
            full = [abs(r['game_steer']) for r in band if abs(r['steer']) >= 0.95]
            half = [abs(r['game_steer']) for r in band if 0.4 <= abs(r['steer']) < 0.6]
            ta = [abs(r['turn_rate']) for r in band if abs(r['steer']) >= 0.95 and r['turn_rate'] != UNKNOWN_TURN]
            th = [abs(r['turn_rate']) for r in band if 0.4 <= abs(r['steer']) < 0.6 and r['turn_rate'] != UNKNOWN_TURN]
            if full and half:
                print(f'  {lo_s}-{hi_s} km/h: half stick gives {median(half) / median(full) * 100:.0f}% of full-lock game '
                      f'steering (B)' + (f', {median(th) / median(ta) * 100:.0f}% of full-lock turn rate (A)' if ta and th else ''))
    print('\nReading it: B1 shows the game\'s own deadzone (0 in the first columns), curve and any reduction at '
          'speed (full-lock column smaller in faster rows). A1 shows the result on the road. If the deadzone '
          'columns agree, AntiDeadzone can cancel it; if half stick gives much less than half, lower Curve.')


if __name__ == '__main__':
    main()
