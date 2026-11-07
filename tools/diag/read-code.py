"""Read-only: prints the bytes at addresses in the running speed.exe and, for a jmp/call (E9/E8) there, the module
its target lands in. No writes, no key presses.

    python tools/diag/read-code.py <hex address>[:<length>] ...

Example: python tools/diag/read-code.py 0x75FC83:16 0x75E6F4:12
"""
import ctypes
import ctypes.wintypes as w
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
k32.OpenProcess.restype = w.HANDLE
k32.ReadProcessMemory.argtypes = [w.HANDLE, w.LPCVOID, w.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, ctypes.POINTER(w.HMODULE), w.DWORD, ctypes.POINTER(w.DWORD), w.DWORD]
psapi.GetModuleBaseNameA.argtypes = [w.HANDLE, w.HMODULE, ctypes.c_char_p, w.DWORD]


class ModuleInfo(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("size", w.DWORD), ("entry", ctypes.c_void_p)]


psapi.GetModuleInformation.argtypes = [w.HANDLE, w.HMODULE, ctypes.POINTER(ModuleInfo), w.DWORD]


def open_game():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq speed.exe", "/FO", "CSV", "/NH"], capture_output=True,
                         text=True).stdout
    rows = [r for r in out.splitlines() if r.lower().startswith('"speed.exe"')]
    if not rows:
        sys.exit("speed.exe is not running")
    handle = k32.OpenProcess(0x0010 | 0x0400, False, int(rows[0].split('","')[1]))
    if not handle:
        sys.exit("cannot open speed.exe (error %d)" % ctypes.get_last_error())
    return handle


def modules(handle):
    arr = (w.HMODULE * 1024)()
    need = w.DWORD()
    psapi.EnumProcessModulesEx(handle, arr, ctypes.sizeof(arr), ctypes.byref(need), 0x01)  # LIST_MODULES_32BIT
    result = []
    for i in range(need.value // ctypes.sizeof(w.HMODULE)):
        name = ctypes.create_string_buffer(260)
        psapi.GetModuleBaseNameA(handle, arr[i], name, 260)
        info = ModuleInfo()
        psapi.GetModuleInformation(handle, arr[i], ctypes.byref(info), ctypes.sizeof(info))
        result.append((info.base or 0, info.size, name.value.decode()))
    return result


def owner(mods, address):
    for base, size, name in mods:
        if base <= address < base + size:
            return "%s+0x%X" % (name, address - base)
    return "no module"


def main():
    handle = open_game()
    mods = modules(handle)
    for arg in sys.argv[1:]:
        addr_s, _, len_s = arg.partition(":")
        address, length = int(addr_s, 16), int(len_s or "8")
        buf = ctypes.create_string_buffer(length)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(handle, address, buf, length, ctypes.byref(got)):
            print("0x%06X: unreadable" % address)
            continue
        data = buf.raw[:got.value]
        print("0x%06X: %s" % (address, " ".join("%02X" % b for b in data)))
        for i in range(len(data) - 4):
            if data[i] in (0xE8, 0xE9):
                target = (address + i + 5 + struct.unpack_from("<i", data, i + 1)[0]) & 0xFFFFFFFF
                if not (0x400000 <= target < 0xA00000):
                    print("    +%d %s -> 0x%08X (%s)" % (i, "call" if data[i] == 0xE8 else "jmp", target,
                                                       owner(mods, target)))


if __name__ == "__main__":
    main()
