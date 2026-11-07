"""Read-only: reads speed.exe's shadow settings from the running game's memory (no writes, no key presses).

    python tools/diag/shadow-max.py

Prints the game's shadow detail (0x901830), the menu's highest shadow level (0x9018B8), the effects' highest level
(0x982C3C), the shadow map type (0x982C08), and for each entry of the game's effect table (0x93DE78..0x93DEF0) its
pointer and the fields the shadow maximum is computed from (+0x38, max level; +0x40, a flag byte). Found in
speed.exe at 0x6D2367-0x6D24D5 (docs/visual-notes.md, "Shadows").
"""
import ctypes
import ctypes.wintypes as w
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = w.HANDLE
k32.ReadProcessMemory.argtypes = [w.HANDLE, w.LPCVOID, w.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq speed.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
rows = [r for r in out.splitlines() if r.lower().startswith('"speed.exe"')]
if not rows:
    print("speed.exe is not running")
    sys.exit(1)
pid = int(rows[0].split('","')[1])
handle = k32.OpenProcess(0x0010 | 0x0400, False, pid)  # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
if not handle:
    print("cannot open speed.exe (error %d)" % ctypes.get_last_error())
    sys.exit(1)


def read(address, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(handle, address, buf, size, ctypes.byref(got)) or got.value != size:
        return None
    return buf.raw


def u32(address):
    data = read(address, 4)
    return None if data is None else struct.unpack("<i", data)[0]


print("pid %d" % pid)
for name, address in (("shadow detail", 0x901830), ("menu shadow max", 0x9018B8), ("effects' max level", 0x982C3C),
                      ("shadow map type", 0x982C08)):
    print("%-20s 0x%06X = %s" % (name, address, u32(address)))
for i, slot in enumerate(range(0x93DE78, 0x93DEF4, 4)):
    p = u32(slot)
    if not p:
        print("effect[%2d] 0x%06X -> %s" % (i, slot, p))
        continue
    p &= 0xFFFFFFFF
    fields = read(p, 0x48)
    if fields is None:
        print("effect[%2d] 0x%06X -> 0x%08X (unreadable)" % (i, slot, p))
        continue
    levels = struct.unpack_from("<8i", fields, 0x18)
    print("effect[%2d] 0x%06X -> 0x%08X  +0x38=%d  +0x40=%d  +0x18..0x34=%s" % (
        i, slot, p, struct.unpack_from("<i", fields, 0x38)[0], fields[0x40], list(levels)))
