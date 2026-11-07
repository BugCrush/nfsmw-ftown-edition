"""Tests for tools/cars/drive-stats.py. Run: python tools/cars/tests/test_drive_stats.py

Known answers from a made-up drive: 0 -> 250 km/h at 25 km/h per second, a hit at t=12 s that takes 40 km/h off in
0.1 s with no brake, a braking at t=20 s (60 km/h off in 0.5 s with the brake) that is not a hit.
"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ds", os.path.join(HERE, "..", "drive-stats.py"))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

HEADER = "time_s,rt_raw,lt_raw,rt,lt,steer_raw,steer,speed_kmh,rpm,gear,nitrous,pos_x,pos_y,pos_z,turn_rate,game_steer,game_gas,game_brake,game_handbrake,game_nos\n"


def drive():
    rows, v, t = [], 0.0, 0.0
    while t <= 25.0:
        brake = 0.0
        if t < 10:
            v = 25.0 * t
        elif 12.0 <= t < 12.1:
            v = 250.0 - 400.0 * (t - 12.0)  # a hit: 40 km/h off in 0.1 s
        elif 12.1 <= t < 20:
            v = 210.0
        elif 20 <= t < 20.5:
            v, brake = 210.0 - 120.0 * (t - 20), 1.0  # braking
        elif t >= 20.5:
            v = 150.0
        else:
            v = 250.0
        rows.append("%.3f,0,0,0,0,0,0,%.2f,5000,4,0,0,0,0,0,0,1,%.1f,0,0\n" % (t, v, brake))
        t = round(t + 0.02, 3)
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    f.write(HEADER + "".join(rows))
    f.close()
    return f.name


class DriveStats(unittest.TestCase):
    def setUp(self):
        self.s = ds.stats(drive(), 0, 25)

    def test_top_speed(self):
        self.assertAlmostEqual(self.s["top_kmh"], 250.0, delta=0.6)

    def test_acceleration_times(self):
        self.assertAlmostEqual(self.s["t_0_100"], 4.0, delta=0.05)
        self.assertAlmostEqual(self.s["t_0_200"], 8.0, delta=0.05)

    def test_one_hit_found_and_braking_ignored(self):
        self.assertEqual(len(self.s["hits"]), 1)
        t, before, lost = self.s["hits"][0]
        self.assertAlmostEqual(t, 12.0, delta=0.05)
        self.assertAlmostEqual(before, 250.0, delta=1)
        self.assertAlmostEqual(lost, 40.0, delta=1.5)


if __name__ == "__main__":
    sys.exit(unittest.main())
