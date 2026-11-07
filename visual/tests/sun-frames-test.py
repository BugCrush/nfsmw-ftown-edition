"""Known-answer test of the sun's place from the game's own frames (visual/src/sun.h; docs/visual-notes.md, "The sun's
place from the game's own matrix"). Exit code 0 = pass.

    python visual/tests/sun-frames-test.py              (embedded frame data)
    python visual/tests/sun-frames-test.py --captures   (also re-extracts it from gfx-captures/ and compares)

The frames: GfxProbe's dissections 2 and 3 of the 2026-10-23 race (gfx-captures/baseline/run-20261023-001109/,
git-ignored, so their numbers are copied in below by `tools/sun-check.py --json`).

What VisualBridge reads in the game, and how each is stood in for here:
- the light direction (0x8F2404): as logged in that race's SUN lines, steady all race;
- the main view's world-to-clip matrix (view 1 = 0x919650, its eViewPlatInfo + 0x80): RECONSTRUCTED from the frame
  as the main view's vertex constants c0-c3 (the most common on the main picture: scenery and sky, which have no
  object matrix of their own), transposed into the memory layout (row vectors: clip = (p, 1) * M). Speed.exe builds
  it at 0x6CF400 as camera matrix times projection; the constants are that times nothing else (or the same with a
  z bias, plat + 0x100, which changes only the z column, unused here);
- view 1's camera (for the fallback, [Depth] FovY): RECONSTRUCTED from the same matrix (projection divided out).

Known answers, from the game's own transforms (computed here in Python, independently of sun.h):
1. The sun: behind the camera in both frames (no marker, no rays). The race-1 build said "on" at (0.640, 0.089)
   and (0.260, 0.001): it read view 3, the rear-view mirror (logged camera forward about 180 degrees from the frame's).
2. The direction from the camera to the player's car (its own matrix in the frame puts its origin on screen): the
   frame's matrix through SunScreenClip must put it where the car's own transform does, within 0.03. This checks the
   arithmetic (row vectors, which columns are right, up and forward, the screen's y pointing down) and the memory
   layout the matrix is read in (the constants transposed); it does NOT show that speed.exe keeps that matrix at
   plat + 0x80, because the matrix used here is the frame's constants, not a read of plat + 0x80. The address was
   confirmed by the race of 2026-10-28 (`proj=game` all race, the ShowSun cross on the sun's glare).
3. The fallback (camera + tangents) with the frame's true field of view agrees too; with FovY 62 it does not
   (the game widens the view: 76.0 and 83.7 degrees up and down in these frames).
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
SUN = [0.752, -0.504, 0.426]
RUN = os.path.join(ROOT, "gfx-captures", "baseline", "run-20261023-001109")

# tools/sun-check.py --json <dissect-N/calls.txt>: c0..c3 (row by row) of the main view and of the player's car.
FRAMES = {
    2: {"time": 84.0, "old": (0.640, 0.089), "logged_forward": (0.956, -0.294, -0.002),
        "view": [0.0406913, 0.753798, 1.37249e-06, -1642.37, 0.00836339, -0.000454158, 1.279, -204.635,
                 -0.998592, 0.0532147, 0.00695592, 994.498, -0.998559, 0.0532129, 0.00695569, 994.965],
        "car": [0.0452817, -0.752719, -0.0351311, -0.00500488, -0.00465414, -0.0599094, 1.27763, -2.21554,
                0.998187, 0.0604193, 0.00687702, 5.45825, 0.998153, 0.0604173, 0.00687679, 5.95813]},
    3: {"time": 122.0, "old": (0.260, 0.001), "logged_forward": (0.491, -0.870, -0.052),
        "view": [0.547754, 0.368507, 8.81585e-06, -1121.53, -0.000731776, 0.00106025, 1.11742, -199.978,
                 -0.558869, 0.829296, -0.000686743, -2053.06, -0.55885, 0.829268, -0.00068672, -2052.49],
        "car": [0.00794557, -0.657507, 0.0587927, -0.00598145, 0.00892552, 0.0996244, 1.11294, -1.9007,
                0.999926, 0.0121037, -0.00863468, 5.83545, 0.999893, 0.0121033, -0.00863439, 6.33545]},
}

failures = []


def expect(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def solve3(a, b):
    """Solve a 3x3 system a x = b (Cramer)."""
    det = lambda m: (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                     + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det(a)
    out = []
    for k in range(3):
        m = [row[:] for row in a]
        for r in range(3):
            m[r][k] = b[r]
        out.append(det(m) / d)
    return out


def build_cli():
    out = os.path.join(HERE, "out", "sun-test")
    os.makedirs(out, exist_ok=True)
    exe = os.path.join(out, "sun-cli.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O2", "sun-cli.cpp", "-o", exe], cwd=HERE)
    return exe


def cli(exe, mode, m, d, extra=()):
    args = [exe, mode] + ["%.9g" % v for v in m] + ["%.9g" % v for v in d] + ["%.9g" % v for v in extra]
    words = subprocess.run(args, capture_output=True, text=True, check=True).stdout.split()
    on = words[0] == "on"
    return on, (float(words[1]), float(words[2])) if on else None, words[4] == "1"


def main():
    if "--captures" in sys.argv:
        for n, frame in FRAMES.items():
            got = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sun-check.py"), "--json",
                                             os.path.join(RUN, "dissect-%d" % n, "calls.txt")],
                                            capture_output=True, text=True, check=True).stdout)
            expect(got["view"] == frame["view"] and got["car"] == frame["car"], "frame %d: embedded data matches the capture" % n)
    exe = build_cli()
    for n, frame in FRAMES.items():
        c = frame["view"]
        rows = [c[i * 4:i * 4 + 4] for i in range(4)]
        # The memory layout VisualBridge reads (row vectors): M[r][j] = c_j[r].
        memory = [rows[j][r] for r in range(4) for j in range(4)]
        dot3 = lambda a, b: sum(a[i] * b[i] for i in range(3))
        norm = lambda a: math.sqrt(dot3(a, a))
        forward = [v / norm(rows[3]) for v in rows[3][:3]]
        fov_x, fov_y = (math.degrees(2 * math.atan(norm(rows[3]) / norm(rows[k]))) for k in (0, 1))
        print("frame %d (%.0f s): main view forward (%.3f, %.3f, %.3f), field of view %.1f x %.1f deg" % (
            n, frame["time"], forward[0], forward[1], forward[2], fov_x, fov_y))

        # 1. The sun: behind the camera by the game's own matrix; the new code agrees, the race-1 code did not.
        w = dot3(rows[3], SUN)
        expect(w < 0, "frame %d: the game's matrix puts the sun behind the camera (c3.d = %.3f)" % (n, w))
        on, at, plausible = cli(exe, "clip", memory, SUN)
        expect(plausible, "frame %d: the game's matrix passes ClipMatrixPlausible" % n)
        expect(not on, "frame %d: SunScreenClip says not on screen (expected: behind), got %s" % (n, at))
        print("     frame %d: the race-1 build said on screen at %s (logged): wrong, the sun was behind" % (n, frame["old"]))
        lf = frame["logged_forward"]
        angle = math.degrees(math.acos(max(-1, min(1, dot3(lf, forward) / norm(lf)))))
        expect(angle > 150, "frame %d: the race-1 camera (0x919730, view 3) looked %.0f deg away from the main view: "
               "the rear-view mirror" % (n, angle))

        # 2. A direction that is on screen: from the camera to the player's car.
        car = frame["car"]
        car_at = (0.5 + 0.5 * car[3] / car[15], 0.5 - 0.5 * car[7] / car[15])
        a3 = [rows[0][:3], rows[1][:3], rows[3][:3]]
        camera = solve3(a3, [-rows[0][3], -rows[1][3], -rows[3][3]])  # where clip x, y and w are 0
        car_world = solve3(a3, [car[3] - rows[0][3], car[7] - rows[1][3], car[15] - rows[3][3]])
        to_car = [car_world[i] - camera[i] for i in range(3)]
        on, at, _ = cli(exe, "clip", memory, to_car)
        expect(on and abs(at[0] - car_at[0]) < 0.03 and abs(at[1] - car_at[1]) < 0.03,
               "frame %d: towards the car: expected (%.3f, %.3f) from its own transform, got %s" % (n, car_at[0], car_at[1], at))

        # 3. The fallback: view 1's camera (reconstructed: projection divided out) with tangents.
        sx, sy = norm(rows[0]), norm(rows[1])
        cam = [0.0] * 16
        for r in range(4):
            cam[r * 4 + 0] = rows[0][r] / sx
            cam[r * 4 + 1] = -rows[1][r] / sy
            cam[r * 4 + 2] = rows[3][r]
        cam[15] = 1.0
        on, at, _ = cli(exe, "camera", cam, to_car, (1 / sx, 1 / sy))
        expect(on and abs(at[0] - car_at[0]) < 0.03 and abs(at[1] - car_at[1]) < 0.03,
               "frame %d: fallback with the frame's true field of view: towards the car (%.3f, %.3f), got %s" % (n, car_at[0], car_at[1], at))
        on, at, _ = cli(exe, "camera", cam, SUN, (1 / sx, 1 / sy))
        expect(not on, "frame %d: fallback with view 1's camera: the sun behind too, got %s" % (n, at))
        tan62 = math.tan(math.radians(31))
        on, at62, _ = cli(exe, "camera", cam, to_car, (tan62 * 16 / 9, tan62))
        print("     frame %d: for comparison, the fallback with FovY 62 puts the car at %s (the game's view is wider)" % (n, at62))
    print("sun-frames-test: %s (%d failed)" % ("FAIL" if failures else "PASS", len(failures)))
    sys.exit(1 if failures else 0)


main()
