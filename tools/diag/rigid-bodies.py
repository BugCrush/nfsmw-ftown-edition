"""Read-only: during a race, lists the weight of every physics body in the running speed.exe (no writes, no keys).

    python tools/diag/rigid-bodies.py <out.txt> [minutes]

The game keeps its bodies in RigidBody::mMaps (0x9376C8, 64 slots; RigidBody::Get 0x68BA30). A body's data block is reached
through +0x78 and one more pointer; the weight is at +0x2C in it (read from the PC code, see below). Every
2 seconds, for each body: the float at data+0x2C, and the speed (data+0x20..0x28, m/s). A line is written whenever
the set of weights changes. Stops when the game exits.
"""
import ctypes
import importlib.util
import math
import os
import struct
import sys
import time

spec = importlib.util.spec_from_file_location("rc", os.path.join(os.path.dirname(os.path.abspath(__file__)), "read-code.py"))
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

# PC layout from RigidBody::SetMass (0x6970C0, called on the IRigidBody at body + 0x48): mov eax,[ecx+0x30];
# mov ecx,[eax]; mass at [ecx+0x2C]. So from the body: pointer at +0x78, then one more pointer, then the data.
MAPS, SLOTS, DATA_OFS, MASS_OFS, VEL_OFS = 0x9376C8, 64, 0x78, 0x2C, 0x20


def main():
    out, minutes = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 30
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            h = rc.open_game()
            break
        except SystemExit:
            time.sleep(2)
    else:
        return

    def read(a, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not rc.k32.ReadProcessMemory(h, a, buf, n, ctypes.byref(got)) or got.value != n:
            return None
        return buf.raw

    def alive():
        code = ctypes.c_ulong()
        return rc.k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259  # STILL_ACTIVE

    last = None
    with open(out, "w") as f:
        f.write("%s  watching speed.exe\n" % time.strftime("%H:%M:%S"))
        f.flush()
        while time.time() < deadline and alive():
            maps = read(MAPS, SLOTS * 4)
            if maps is None:
                time.sleep(1)  # memory not readable yet (the game is still starting): try again
                continue
            bodies = []
            for i, b in enumerate(struct.unpack("<%dI" % SLOTS, maps)):
                if not b:
                    continue
                p = read(b + DATA_OFS, 4)
                q = read(struct.unpack("<I", p)[0], 4) if p and struct.unpack("<I", p)[0] else None
                data = read(struct.unpack("<I", q)[0], 0x40) if q and struct.unpack("<I", q)[0] else None
                if not data:
                    continue
                mass = struct.unpack_from("<f", data, MASS_OFS)[0]
                vx, vy, vz = struct.unpack_from("<3f", data, VEL_OFS)
                kmh = math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6 if all(map(math.isfinite, (vx, vy, vz))) else -1
                bodies.append((i, round(mass, 1), round(kmh)))
            key = sorted(m for _, m, _ in bodies)
            if bodies and key != last:
                f.write("%s  %d bodies: %s\n" % (time.strftime("%H:%M:%S"), len(bodies),
                                                  "  ".join("#%d %.0f kg %d km/h" % b for b in bodies)))
                f.flush()
                last = key
            time.sleep(2)


if __name__ == "__main__":
    main()
