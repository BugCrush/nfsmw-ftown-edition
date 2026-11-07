"""Builds WorldProbe.asi and its stand-in, runs every variant and checks it.

    python world/tests/run.py [variant ...]

Each variant runs in world/tests/out/<variant>/ (git-ignored) with its own WorldProbe.ini, made from
world/WorldProbe.ini (the file that is installed) with the variant's changes. Exit code 1 if any check fails.
The stand-in (standin.cpp) prints HOOK, TELEPORT, VELOCITY, SPIN and HEIGHTCALLS lines.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
INI = os.path.join(ROOT, "world", "WorldProbe.ini")
SITES = ["0x00663D35", "0x00667650", "0x0047EF0A", "0x0047EF12", "0x006F8FB0", "0x006F9050", "0x006F9060",
         "0x006F9020", "0x007897C0", "0x0072CA00", "0x007318B4", "0x007318CA", "0x00772CF1", "0x006959FD"]

# variant: (ini changes {(section, key): value}, stand-in arguments, checks)
VARIANTS = {
    # the expected bytes everywhere, default ini: every check ok, POS lines in both conventions, no teleport
    "same": ({("Log", "IntervalMs"): "20", ("Log", "Sections"): "1", ("Log", "Scenery"): "1"}, [],
             {"out_has": ["HOOK patched"], "out_not": ["TELEPORT"],
              "log_has": ["check ok %s" % s for s in SITES] + [
                  "teleport off", "player found",
                  "POS physics (-2400.00, 113.00, 1700.00) render (1700.00, 2400.00, 113.00)",
                  "telemetry (1700.00, 113.00, -2400.00)", "speed 96.6 km/h", "section C9",
                  "height 112.50 (car 0.50 above)", "packs 2", "scenery 2 [Z1 A1]"],
              "log_not": ["WRONGBYTES", "TELEPORT", "packs -1", "unavailable"], "min_pos": 3}),
    # one address differs: WRONGBYTES, no hook, no reads, no teleport even with the key and Enabled = 1
    "wrongbytes": ({("Teleport", "Enabled"): "1", ("Log", "IntervalMs"): "20"}, ["wrongbytes", "key"],
                   {"out_has": ["HOOK untouched", "HEIGHTCALLS 0"], "out_not": ["TELEPORT", "VELOCITY"],
                    "log_has": ["WRONGBYTES 0x007897C0", "WorldProbe does nothing"],
                    "log_not": ["POS", "hooked", "TELEPORT"], "max_pos": 0}),
    # review: an instruction tying a data address (0x9AA478) differs: nothing done
    "wrongdata": ({("Teleport", "Enabled"): "1", ("Log", "IntervalMs"): "20"}, ["wrongdata", "key"],
                  {"out_has": ["HOOK untouched", "HEIGHTCALLS 0"], "out_not": ["TELEPORT"],
                   "log_has": ["WRONGBYTES 0x007318CA", "WorldProbe does nothing"], "log_not": ["POS", "hooked"],
                   "max_pos": 0}),
    # review: a vtable slot holds another value: nothing done
    "wrongslot": ({("Teleport", "Enabled"): "1", ("Log", "IntervalMs"): "20"}, ["wrongslot", "key"],
                  {"out_has": ["HOOK untouched", "HEIGHTCALLS 0"], "out_not": ["TELEPORT"],
                   "log_has": ["WRONGBYTES 0x008B0BE0", "WorldProbe does nothing"], "log_not": ["POS", "hooked"],
                   "max_pos": 0}),
    # review: Enabled = 1 and the key down while the game window is not in front: no teleport
    "background": ({("Teleport", "Enabled"): "1", ("Log", "IntervalMs"): "20"}, ["key", "background"],
                   {"out_has": ["HOOK patched"], "out_not": ["TELEPORT", "VELOCITY"],
                    "log_has": ["TELEPORT ON", "key ignored: the game window is not in front"],
                    "log_not": ["TELEPORT from"]}),
    # the shipped ini (Enabled = 0) and the key pressed: no teleport call
    "teleport-off": ({}, ["key"],
                     {"out_has": ["HOOK patched"], "out_not": ["TELEPORT", "VELOCITY"],
                      "log_has": ["teleport off"], "log_not": ["TELEPORT"]}),
    # Enabled = 1 and the key pressed: SetPosition receives exactly the ini's X, Y, Z in physics order
    # (-Y, Z, X), once (the key is down two frames: one edge), velocities zeroed, then fast logging
    "teleport-on": ({("Teleport", "Enabled"): "1", ("Teleport", "FastIntervalMs"): "1", ("Log", "Sections"): "1"},
                    ["key", "frames=60"],
                    {"out_has": ["HOOK patched", "TELEPORT -11500.000 100.000 2000.000", "VELOCITY 0.0 0.0 0.0",
                                 "SPIN 0.0 0.0 0.0"],
                     "log_has": ["TELEPORT ON", "TELEPORT from physics (-2400.00, 113.00, 1700.00) to render "
                                 "(2000.00, 11500.00, 100.00) = physics (-11500.00, 100.00, 2000.00): set; velocity "
                                 "zeroed", "render (2000.00, 11500.00, 100.00)", "section none", "height no face"],
                     "log_not": ["packs -1", "unavailable"], "teleports": 1, "min_pos": 10}),
    # WorldProbe 2, cost: a COST line every 10 POS lines with every part's last/max (default ini: section and
    # scenery off)
    "cost": ({("Log", "IntervalMs"): "1"}, [],
             {"log_has": ["COST over 10 POS lines (us last/max):", "section off", "scenery off", "per frame"],
              "log_re": [r"COST .*player \d+/\d+ .*height \d+/\d+ .*packs \d+/\d+ .*format \d+/\d+ "
                         r".*write \d+/\d+ .*total \d+/\d+"],
              "min_pos": 20}),
    # the shipped ini: the parts that cost or change game state are not called
    "defaults-cheap": ({("Log", "IntervalMs"): "1"}, [],
                       {"out_has": ["FINDDRIVABLECALLS 0"], "pos_not": ["section ", "scenery "],
                        "pos_has": ["height 112.50 (car 0.50 above)", "packs 2"], "min_pos": 10}),
    # every part on: section and scenery appear, FindDrivableSection is called
    "all-parts": ({("Log", "IntervalMs"): "1", ("Log", "Sections"): "1", ("Log", "Scenery"): "1"}, [],
                  {"out_re": [r"FINDDRIVABLECALLS [1-9]"], "pos_has": ["section C9", "scenery 2 [Z1 A1]"],
                   "min_pos": 10}),
    # a pointer into memory that is reserved but not committed: the read faults, WorldProbe catches it
    "badptr": ({("Log", "IntervalMs"): "1"}, ["badptr"],
               {"out_has": ["HOOK patched"], "log_has": ["FAULT reading"], "log_not": ["player found"]}),
    # one timed VirtualQuery on the player object at "player found" (the evidence for the cost of version 1)
    "vqprobe": ({}, [], {"log_re": [r"VQPROBE player object: region of \d+ KB, VirtualQuery took [\d.]+ us"]}),
    # the player car's body is an RBVehicle (IRigidBody vtable 0x8AC880, as in the game): velocity zeroed
    "rigidbody": ({("Teleport", "Enabled"): "1"}, ["key", "rbvehicle"],
                  {"out_has": ["VELOCITY 0.0 0.0 0.0", "SPIN 0.0 0.0 0.0"],
                   "log_has": ["check ok 0x008AC8E0", "velocity zeroed (rigid body vtable 0x008AC880)"],
                   "log_not": ["not zeroed"]}),
    # RBVehicle's +0x60 slot differs: that part off (velocity not zeroed), everything else runs
    "wrongbytes-rb": ({("Teleport", "Enabled"): "1", ("Log", "IntervalMs"): "20"}, ["key", "rbvehicle", "wrongrb"],
                      {"out_has": ["HOOK patched", "TELEPORT -11500.000 100.000 2000.000"], "out_not": ["VELOCITY"],
                       "log_has": ["WRONGBYTES 0x008AC8E0", "velocity not zeroed"], "min_pos": 3}),
    # after a teleport: one FRAME line per frame for 30 frames, then POS lines; our own jump is not a JUMP
    "frames": ({("Teleport", "Enabled"): "1", ("Teleport", "FastIntervalMs"): "1000"}, ["key", "frames=60"],
               {"log_has": ["FRAME 1 +", "FRAME 30 +", "render (2000.00, 11500.00, 100.00)"],
                "log_re": [r"FRAME 1 \+[\d.]+ ms physics \(-11500\.00, 100\.00, 2000\.00\) render \(2000\.00, "
                           r"11500\.00, 100\.00\) speed [\d.]+ km/h"],
                "log_not": ["FRAME 31 ", "JUMP"], "frame_lines": 30}),
    # F10: straight up from where the car is, by AboveMetres (20): physics y 113 -> 133
    "above": ({("Teleport", "Enabled"): "1"}, ["abovekey"],
              {"out_has": ["TELEPORT -2400.000 133.000 1700.000"],
               "log_has": ["TELEPORT above (20.0 m up) from physics (-2400.00, 113.00, 1700.00) to physics "
                           "(-2400.00, 133.00, 1700.00)"],
               "teleports": 1}),
    # the "game" resets the car at frame 2 (no player yet) and frame 20: every function of the reset path is logged
    # with its caller, the original runs (ORIGINAL lines, RESULT 1), and the JUMP names the last watched call
    "reset-watch": ({("Log", "IntervalMs"): "20"}, ["resetcall"],
                    {"out_has": ["ORIGINAL ResetVehicle manual 0", "ORIGINAL ResetTo manual 0",
                                 "ORIGINAL SetVehicleOnGround -2400.0 113.0 1650.0", "RESULT 1"],
                     "out_not": ["RESULT 0"],
                     "log_has": ["watching 0x006B08C0 ResetCar::ResetVehicle", "watching 0x006A45F0 ResetCar::ResetTo",
                                 "watching 0x00685810 PVehicle::SetVehicleOnGround",
                                 "watching 0x00696FB0 RigidBody::SetPosition",
                                 "WATCH ResetCar::ResetVehicle (other) manual 0",
                                 "WATCH ResetCar::ResetVehicle (player) manual 0",
                                 "WATCH ResetCar::ResetTo (player) to physics (-2400.00, 113.00, 1650.00) manual 0",
                                 "WATCH PVehicle::SetVehicleOnGround (player) to physics (-2400.00, 113.00, 1650.00)",
                                 "WATCH RigidBody::SetPosition (player) to physics (-2400.00, 113.00, 1650.00)",
                                 "-> 1"],
                     "log_re": [r"WATCH ResetCar::ResetVehicle \(player\) manual 0 from 0x[0-9A-F]{8}",
                                r"JUMP from render \(1700\.00, 2400\.00, 113\.00\) to render \(1650\.00, 2400\.00, "
                                r"113\.00\): 50\.0 m in one frame, not by WorldProbe; last watched call: "
                                r"RigidBody::SetPosition \(player\) 0 frames before"],
                     "log_not": ["WRONGBYTES"], "min_pos": 3}),
    # ResetTo's bytes differ: that watch is off, the other three watch, the original still runs, POS lines go on
    "wrongbytes-reset": ({("Log", "IntervalMs"): "20"}, ["resetcall", "wrongreset"],
                         {"out_has": ["ORIGINAL ResetVehicle manual 0", "ORIGINAL ResetTo manual 0", "RESULT 1"],
                          "log_has": ["WRONGBYTES 0x006A45F0", "watch off: ResetCar::ResetTo",
                                      "watching 0x006B08C0 ResetCar::ResetVehicle",
                                      "WATCH ResetCar::ResetVehicle (player)", "WATCH PVehicle::SetVehicleOnGround",
                                      "hooked 0x00663D35"],
                          "log_not": ["WATCH ResetCar::ResetTo"], "min_pos": 3}),
    # [Watch] Reset = 0: no watch installed, the reset path runs as before
    "watch-off": ({("Log", "IntervalMs"): "20", ("Watch", "Reset"): "0"}, ["resetcall"],
                  {"out_has": ["ORIGINAL ResetVehicle manual 0", "ORIGINAL SetVehicleOnGround", "RESULT 1"],
                   "log_has": ["watches off ([Watch] Reset = 0)"], "log_not": ["WATCH ", "watching"]}),
    # review: 300 resets of other cars (traffic, cops) before the player's must not use up the WATCH lines
    # (small fixes: PerCallerLines raised here, else the 300 calls from one place stop at the per-caller limit first
    # and the OtherLines budget this variant is about is never reached)
    "watch-budget": ({("Log", "IntervalMs"): "20", ("Watch", "PerCallerLines"): "1000"}, ["resetcall", "othercalls"],
                     {"log_has": ["WATCH PVehicle::SetVehicleOnGround (other)",
                                  "WATCH: further calls for other cars are counted, not logged ([Watch] OtherLines = 20)",
                                  "WATCH ResetCar::ResetVehicle (player) manual 0",
                                  "WATCH RigidBody::SetPosition (player) to physics (-2400.00, 113.00, 1650.00)"]}),
    # review: after WorldProbe's teleport (which goes through RigidBody::SetPosition, as in the game) a JUMP by
    # anything unwatched says so, instead of naming WorldProbe's own call
    "teleport-jump": ({("Teleport", "Enabled"): "1"}, ["key", "jump", "frames=60"],
                      {"log_has": ["WATCH RigidBody::SetPosition (player, WorldProbe's teleport)",
                                   "m in one frame, not by WorldProbe; no watched call before it"],
                       "log_not": ["last watched call: RigidBody::SetPosition (player, WorldProbe's teleport)"]}),
    # small fixes (runs E, F): the start grid calls RigidBody::SetPosition hundreds of times from two places in the
    # countdown; each place gets PerCallerLines (10) lines, the rest are counted per place, and the player's reset
    # later still gets its lines; the counts per place are in the WATCH callers summary
    "watch-percaller": ({("Log", "IntervalMs"): "20"}, ["resetcall", "gridhold"],
                        {"log_has": ["WATCH ResetCar::ResetVehicle (player) manual 0",
                                     "WATCH RigidBody::SetPosition (player) to physics (-2400.00, 113.00, 1650.00)",
                                     "are counted, not logged ([Watch] PerCallerLines = 10)"],
                         "log_re": [r"WATCH callers: .*RigidBody::SetPosition from 0x[0-9A-F]{8}: 10 logged, 140 "
                                    r"counted.*RigidBody::SetPosition from 0x[0-9A-F]{8}: 10 logged, 140 counted"],
                         "count": {"WATCH RigidBody::SetPosition (player) to physics (-2400.00, 113.00, 1700.00)": 20}}),
    # small fixes: the player's budget (here 5 lines) is renewed at any JUMP, not only at WorldProbe's teleports, so
    # the reset after it is logged
    "watch-jump-renew": ({("Log", "IntervalMs"): "20", ("Watch", "MaxLines"): "5",
                          ("Watch", "PerCallerLines"): "200"},
                         ["resetcall", "gridhold", "jump", "resetat=30", "frames=40"],
                         {"log_re": [r"100\.0 m in one frame, not by WorldProbe; [^\n]*; watch lines renewed"],
                          "log_has": ["WATCH ResetCar::ResetVehicle (player) manual 0"]}),
    # city fixes: the player's reset (frame 20; the player exists from frame 5) dumps the ring first: the 15 frames
    # it holds, oldest first, with the face found 1 m above the car; the other car's reset (frame 2) dumps nothing
    "ring-reset": ({("Log", "IntervalMs"): "1000"}, ["resetcall"],
                   {"log_has": ["ring: the last 200 frames (face on) dumped at a reset of the player's car or a fall "
                                "through the surface (0.20 m under the face above it, the face 2.0 m lower than the "
                                "frame before, or gone)",
                                "RING last 15 frames before ResetCar::ResetVehicle (player) (oldest first; ms before now)",
                                "RING 0 -", "RING -14 -"],
                    "log_re": [r"RING -14 -\d+\.\d ms render \(1700\.00, 2400\.00, 113\.00\) speed 96\.6 km/h face "
                               r"112\.50 \(car 0\.50 above\)"],
                    "count": {"RING last": 1, "] RING ": 16}}),
    # the car falls 4 m in 20 frames through the stand-in's face at 112.50 (car at 113.00): one dump when it is more
    # than 0.2 m under it (frame 33: 112.40 is not yet, 112.20 is), the further frames of the fall skipped (one a
    # second) and said so; a car going down at speed (the grade) never dumps: ring-off and ring-reset have none
    "ring-drop": ({("Log", "IntervalMs"): "1000"}, ["drop", "frames=80"],
                  {"log_re": [r"RING last \d+ frames before a fall through the surface: the car 0\.[3-4]\d m under "
                              r"the face found above it",
                              r"RING dump skipped \(one a second; further ones in this second not noted\): a fall"],
                   "count": {"RING last": 1, "RING dump skipped": 1}, "log_not": ["face none"]}),
    # a bigger ring than the frames seen: it prints what it has; Frames = 0: no RING lines at all, no reads
    "ring-off": ({("Log", "IntervalMs"): "1000", ("Ring", "Frames"): "0"}, ["resetcall", "drop", "frames=80"],
                 {"log_has": ["ring off ([Ring] Frames = 0)", "WATCH ResetCar::ResetVehicle (player)"],
                  "log_not": ["] RING "]}),
    # the car moves 100 m in one frame without a WorldProbe teleport: JUMP
    "jump": ({("Log", "IntervalMs"): "20"}, ["jump"],
             {"log_has": ["JUMP from render (1700.00, 2400.00, 113.00) to render (1800.00, 2400.00, 113.00): "
                          "100.0 m in one frame"]}),
}


def make_ini(changes):
    with open(INI, "rb") as f:
        data = f.read().decode("ascii")
    section = None
    lines = []
    applied = set()
    for line in data.split("\r\n"):
        m = re.match(r"\[(\w+)\]", line)
        if m:
            section = m.group(1)
        k = re.match(r"(\w+)\s*=", line)
        if k and (section, k.group(1)) in changes:
            line = "%s = %s" % (k.group(1), changes[(section, k.group(1))])
        lines.append(line)
        if k and (section, k.group(1)) in changes:
            applied.add((section, k.group(1)))
    missing = set(changes) - applied
    if missing:
        raise SystemExit("world/WorldProbe.ini has no key %s: document it there first" % sorted(missing))
    return "\r\n".join(lines).encode("ascii")


def main():
    names = sys.argv[1:] or list(VARIANTS)
    with open(INI, "rb") as f:
        raw = f.read()
    if raw.count(b"\r\n") != raw.count(b"\n"):
        print("world/WorldProbe.ini is not CRLF throughout")
        return 1
    subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "world", "src", "build.bat"), ZIG])
    exe = os.path.join(HERE, "standin.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", "standin.cpp", "-o", exe, "-w",
                           "-Wl,--image-base=0x400000", "-Wl,--no-dynamicbase"], cwd=HERE)
    failed = 0
    for name in names:
        changes, args, want = VARIANTS[name]
        out = os.path.join(HERE, "out", name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        shutil.copy(exe, out)
        shutil.copy(os.path.join(ROOT, "world", "src", "WorldProbe.asi"), out)
        with open(os.path.join(out, "WorldProbe.ini"), "wb") as f:
            f.write(make_ini(changes))
        result = subprocess.run([os.path.join(out, "standin.exe")] + args, cwd=out, capture_output=True, text=True,
                                timeout=60)
        logp = os.path.join(out, "WorldProbe.log")
        log = open(logp, encoding="latin-1").read() if os.path.exists(logp) else ""
        fails = []
        if result.returncode != 0:
            fails.append("stand-in exit %d: %s" % (result.returncode, result.stdout[-300:]))
        for t in want.get("out_has", []):
            if t not in result.stdout:
                fails.append("output lacks %r" % t)
        for t in want.get("out_not", []):
            if t in result.stdout:
                fails.append("output has %r" % t)
        for t in want.get("log_has", []):
            if t not in log:
                fails.append("log lacks %r" % t)
        for t in want.get("log_not", []):
            if t in log:
                fails.append("log has %r" % t)
        for r in want.get("out_re", []):
            if not re.search(r, result.stdout):
                fails.append("output lacks /%s/" % r)
        for r in want.get("log_re", []):
            if not re.search(r, log):
                fails.append("log lacks /%s/" % r)
        pos_lines = [l for l in log.splitlines() if "] POS " in l]
        for t in want.get("pos_not", []):
            if any(t in l for l in pos_lines):
                fails.append("a POS line has %r" % t)
        for t in want.get("pos_has", []):
            if not pos_lines or not all(t in l for l in pos_lines):
                fails.append("not every POS line has %r" % t)
        for t, n in want.get("count", {}).items():
            if log.count(t) != n:
                fails.append("log has %r %d times, want %d" % (t, log.count(t), n))
        nframe = log.count("] FRAME ")
        if "frame_lines" in want and nframe != want["frame_lines"]:
            fails.append("%d FRAME lines, want %d" % (nframe, want["frame_lines"]))
        npos = log.count("] POS ")
        if "min_pos" in want and npos < want["min_pos"]:
            fails.append("%d POS lines, want at least %d" % (npos, want["min_pos"]))
        if "max_pos" in want and npos > want["max_pos"]:
            fails.append("%d POS lines, want at most %d" % (npos, want["max_pos"]))
        if "teleports" in want and result.stdout.count("TELEPORT ") != want["teleports"]:
            fails.append("%d teleports, want %d" % (result.stdout.count("TELEPORT "), want["teleports"]))
        print("%-12s %s" % (name, "PASS" if not fails else "FAIL"))
        for f in fails:
            print("    " + f)
        failed += bool(fails)
    print("%d/%d variants pass" % (len(names) - failed, len(names)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
