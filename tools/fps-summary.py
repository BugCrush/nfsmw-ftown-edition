"""Frame-rate summary of one stretch of an FpsRecorder (PresentMon) recording.

    python tools/fps-summary.py fps-capture/nfsmw-fps-<stamp>.csv --from 60 --to 890
    python tools/fps-summary.py --test

--from/--to are seconds from the start of the recording (default: the whole file). Use the same
stretch of the same race when comparing two recordings. "1% low" is the frame rate of the slowest 1%
of frames (the 99th percentile frame time), the usual measure of stutter.
"""
import csv
import io
import sys


def summarise(rows, start_s, end_s):
    frame_ms, cpu_ms, gpu_ms = [], [], []
    for row in rows:
        try:
            t = float(row["TimeInMs"]) / 1000.0
            ms = float(row["MsBetweenPresents"])
        except (KeyError, ValueError):
            continue
        if t < start_s or t > end_s or ms <= 0:
            continue
        frame_ms.append(ms)
        for column, out in (("MsCPUBusy", cpu_ms), ("MsGPUBusy", gpu_ms)):
            try:
                out.append(float(row[column]))
            except (KeyError, ValueError):
                pass
    if not frame_ms:
        return None
    ordered = sorted(frame_ms)
    p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
    mean = sum(frame_ms) / len(frame_ms)
    return {
        "frames": len(frame_ms),
        "seconds": sum(frame_ms) / 1000.0,
        "avg_fps": 1000.0 / mean,
        "low1_fps": 1000.0 / p99,
        "median_ms": ordered[len(ordered) // 2],
        "cpu_ms": sum(cpu_ms) / len(cpu_ms) if cpu_ms else float("nan"),
        "gpu_ms": sum(gpu_ms) / len(gpu_ms) if gpu_ms else float("nan"),
    }


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def run_test():
    # 100 s at exactly 100 FPS, with 2% of frames taking 40 ms (so the slowest 1% are 40 ms = 25 FPS),
    # then 50 s at 50 FPS that the window must leave out.
    out = io.StringIO()
    out.write("Application,TimeInMs,MsBetweenPresents,MsCPUBusy,MsGPUBusy\n")
    t = 0.0
    while t < 100000:
        ms = 40.0 if int(t / 10) % 50 == 0 else 10.0
        out.write(f"speed.exe,{t:.4f},{ms},8.0,5.0\n")
        t += 10.0
    while t < 150000:
        out.write(f"speed.exe,{t:.4f},20.0,18.0,5.0\n")
        t += 20.0
    out.write("speed.exe,151000,NA,NA,NA\n")
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    s = summarise(rows, 0, 99.99)
    whole = summarise(rows, 0, 1e9)
    checks = [
        ("frames in the window", s["frames"], 10000),
        ("average FPS (10000 frames, 200 of them 40 ms)", round(s["avg_fps"], 1), round(1000 / 10.6, 1)),
        ("1% low FPS", round(s["low1_fps"], 1), 25.0),
        ("median frame time", s["median_ms"], 10.0),
        ("CPU ms", s["cpu_ms"], 8.0),
        ("GPU ms", s["gpu_ms"], 5.0),
        ("the window leaves out the 50 FPS part", whole["frames"], 12500),
        ("an empty window gives nothing", summarise(rows, 500, 600), None),
    ]
    failures = 0
    for name, got, want in checks:
        ok = got == want
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} (want {want})")
    print(f"{failures} failures")
    return 1 if failures else 0


def main():
    args = sys.argv[1:]
    if "--test" in args:
        return run_test()
    if not args:
        print(__doc__)
        return 2
    start_s = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    end_s = float(args[args.index("--to") + 1]) if "--to" in args else 1e12
    s = summarise(read_rows(args[0]), start_s, end_s)
    if not s:
        print("no frames in that stretch")
        return 1
    print(f"{args[0]}")
    print(f"  {s['frames']} frames over {s['seconds']:.1f} s")
    print(f"  average {s['avg_fps']:.1f} FPS, 1% low {s['low1_fps']:.1f} FPS, median frame {s['median_ms']:.2f} ms")
    print(f"  CPU busy {s['cpu_ms']:.2f} ms, GPU busy {s['gpu_ms']:.2f} ms per frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
