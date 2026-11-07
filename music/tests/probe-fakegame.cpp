// Tests MusicProbe's call logging without the game: this program places small stand-in functions at
// the exact addresses the probe wraps in speed.exe (the picker's signature, the event lookup, the
// stream channel's function table), loads MusicProbe.asi, calls them the way the game does, and
// checks that every call still returns what the stand-in function returns and that the log has it.
// Build (from music\tests): zig c++ -target x86-windows-gnu -w probe-fakegame.cpp -o probe-fakegame.exe
//                           -Wl,--image-base,0x10000000      (keeps this program off the game's addresses)
// Run next to MusicProbe.asi (and MusicProbe.ini, if present). Exit code 0 = all passed.
#include <windows.h>
#include <stdio.h>
#include <string.h>

static int failures;
static void Check(bool ok, const char* what, long got)
{
    printf("  %s %s (%ld / 0x%lX)\n", ok ? "ok  " : "FAIL", what, got, (unsigned long)got);
    if (!ok)
        ++failures;
}

static bool Place(UINT_PTR addr, const void* bytes, size_t size)
{
    // VirtualAlloc works in 64 KB blocks; asking again for a block we already have just returns it.
    void* block = VirtualAlloc((void*)(addr & ~0xFFFFu), 0x10000, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!block) // already reserved (by us, or by the system): commit just the pages we need
        block = VirtualAlloc((void*)(addr & ~0xFFFu), 0x2000, MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    if (!block)
        return false;
    memcpy((void*)addr, bytes, size);
    return true;
}

typedef void*(__cdecl* LookupFn)(DWORD id, DWORD mask);
typedef int(__fastcall* Fn0)(void* self, void* edx);
typedef int(__fastcall* Fn1)(void* self, void* edx, int a);
typedef int(__fastcall* Fn5)(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e);

int main(int argc, char** argv)
{
    static DWORD record[11] = { 0x11, 0x22, 0x33, 0x01ABCDEF, 0x55, 0x11000001, 0x000F0400, 0x01FFFFFF, 0x11000001, 0x00030400, 0x00FF0619 };
    const BYTE picker[10] = { 0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x50, 0x01, 0x00, 0x00 };
    const BYTE lookup[] = { 0x55, 0x8B, 0xEC, 0xA1, 0x64, 0x29, 0x9C, 0x00, 0x5D, 0xC3 };  // returns [0x9C2964]
    const BYTE play[] = { 0x8B, 0x44, 0x24, 0x04, 0x03, 0x44, 0x24, 0x14, 0xC2, 0x14, 0x00 }; // a + e, ret 0x14
    const BYTE stop[] = { 0xB8, 0x55, 0x00, 0x00, 0x00, 0xC3 };                             // 0x55
    const BYTE pause[] = { 0x8B, 0x44, 0x24, 0x04, 0xC2, 0x04, 0x00 };                       // a, ret 4
    const BYTE timeLeft[] = { 0x8B, 0x44, 0x24, 0x04, 0x05, 0xE8, 0x03, 0x00, 0x00, 0xC2, 0x04, 0x00 }; // a + 1000
    const DWORD pRecord = (DWORD)(UINT_PTR)record, aStop = 0x82B5A0, aPause = 0x82A580, aLeft = 0x82B460, aPlay = 0x82B4A0,
                aVolume = 0x82B290;
    bool placed = Place(0x4F4CD0, picker, sizeof(picker)) && Place(0x82BFD0, lookup, sizeof(lookup))
        && Place(0x82B4A0, play, sizeof(play)) && Place(0x82B5A0, stop, sizeof(stop)) && Place(0x82A580, pause, sizeof(pause))
        && Place(0x82B460, timeLeft, sizeof(timeLeft)) && Place(0x82B290, pause, sizeof(pause))
        && Place(0x9C2964, &pRecord, 4) && Place(0x8C5F3C, &aStop, 4) && Place(0x8C5F40, &aPause, 4)
        && Place(0x8C5F50, &aLeft, 4) && Place(0x8C5F58, &aPlay, 4) && Place(0x8C5F60, &aVolume, 4);
    if (!placed)
    {
        // Windows puts this process's stack and heaps at random addresses, sometimes on top of the
        // ones we need. Start again (a new process gets a new layout), a limited number of times.
        int attempt = argc > 1 ? atoi(argv[1]) : 0;
        if (attempt >= 30)
        {
            printf("could not place the stand-in functions at the game's addresses in 30 attempts\n");
            return 2;
        }
        char self[MAX_PATH], command[MAX_PATH + 32];
        GetModuleFileNameA(nullptr, self, MAX_PATH);
        snprintf(command, sizeof(command), "\"%s\" %d", self, attempt + 1);
        STARTUPINFOA si = { sizeof(si) };
        PROCESS_INFORMATION pi;
        if (!CreateProcessA(nullptr, command, nullptr, nullptr, TRUE, 0, nullptr, nullptr, &si, &pi))
            return 2;
        WaitForSingleObject(pi.hProcess, INFINITE);
        DWORD code = 2;
        GetExitCodeProcess(pi.hProcess, &code);
        return (int)code;
    }

    HMODULE probe = LoadLibraryA("MusicProbe.asi");
    Check(probe != nullptr, "MusicProbe.asi loaded", probe != nullptr);
    if (!probe)
        return 1;

    DWORD self[8] = {};
    Check(*(DWORD*)0x8C5F58 != aPlay, "the play slot now points at the wrapper", *(long*)0x8C5F58);
    void* found = ((LookupFn)0x82BFD0)(0x01ABCDEF, 0x00FFFFFF);
    Check(found == record, "lookup still returns the game's record", (long)(UINT_PTR)found);
    int r = (*(Fn5*)0x8C5F58)(self, nullptr, 7, 2, 3, 4, 30);
    Check(r == 37, "play passes five arguments through and returns the result", r);
    r = (*(Fn0*)0x8C5F3C)(self, nullptr);
    Check(r == 0x55, "stop", r);
    r = (*(Fn1*)0x8C5F40)(self, nullptr, 1);
    Check(r == 1, "pause", r);
    r = (*(Fn1*)0x8C5F50)(self, nullptr, 3);
    Check(r == 1003, "time left", r);
    for (int i = 0; i < 50; ++i)
        (*(Fn1*)0x8C5F50)(self, nullptr, 3);
    r = (*(Fn1*)0x8C5F60)(self, nullptr, 96);
    Check(r == 96, "volume", r);
    Sleep(200);

    // The log must show each call once (the 50 repeated time-left calls are folded into one line).
    char path[MAX_PATH];
    GetModuleFileNameA(probe, path, MAX_PATH);
    strcpy(strrchr(path, '.'), ".log");
    FILE* f = fopen(path, "rb");
    static char text[65536];
    size_t n = f ? fread(text, 1, sizeof(text) - 1, f) : 0;
    if (f)
        fclose(f);
    text[n] = 0;
    const char* expect[] = { "call logging: lookup wrapped", "call logging: play wrapped", "call logging: volume wrapped",
        "lookup id=01ABCDEF mask=00FFFFFF", "00FF0619]", "args=00000007 00000002 00000003 00000004 0000001E -> 00000025",
        "stop   channel=", "pause  channel=", "slot=3 -> 1003 ms", "volume channel=", " 96 (of 127)" };
    for (const char* e : expect)
        Check(strstr(text, e) != nullptr, e, 0);
    int leftLines = 0;
    for (const char* p = text; (p = strstr(p, "left   channel=")) != nullptr; ++p)
        ++leftLines;
    Check(leftLines == 1, "51 identical time-left calls give one log line", leftLines);

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
