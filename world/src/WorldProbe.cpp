// WorldProbe.asi (version 2) - F-Town stage 1 diagnostic: logs where the player's car is and what the world holds
// around it, and (only when [Teleport] Enabled = 1) moves the car when a key is pressed while a LocalPlayer exists
// (a race, its pause menu or results screen) and the game's window is in front.
//
// Findings and addresses: docs/ftown-notes.md, Task 5 (Q5, Q6), Task 6, Task 7 and "WorldProbe 2". speed.exe v1.3
// only: every address is checked against the expected bytes first. Version 1's sites (the core: the frame hook, the
// player, the position, the height and section queries, the data addresses) are all-or-nothing: if any differs the
// log says WRONGBYTES and the plugin does nothing at all. Every address added in version 2 belongs to one optional
// part; a mismatch there turns off that part only.
//
// Once a frame on the game thread: MainLoop (0x663D30) calls MainLoopBreakpoint (0x667650, a bare ret) at 0x663D35;
// that call is pointed at Frame(), which calls MainLoopBreakpoint and then does its work.
// The player: LocalPlayer from the player list (count 0x92D884, array 0x92D87C), its vtable 0x8B0B10 or 0x8B0BD0:
// +0x0C GetPosition (physics convention, y up), +0x10 SetPosition (the game's own teleport: the rigid body's
// position), +0x04 GetSimable -> ISimable +0x54 GetRigidBody -> the IRigidBody (RigidBody vtable 0x8A9818, or the
// player car's RBVehicle IRigidBody vtable 0x8AC880) +0x60 SetLinearVelocity, +0x64 SetAngularVelocity.
// Positions are logged in both conventions: physics (x, y up, z) and render / world files (x, y, z up) = (z, -x, y).
//
// Cost (version 1 stalled the game 100-150 ms per POS line): memory reads are no longer guarded by VirtualQuery,
// whose cost grows with the size of the memory region (about 3.4 us per MB, measured), but by a copy routine whose
// faults a vectored exception handler turns into a failed read. The log file stays open, buffered, and is flushed at
// most once a second (and when the player goes and at exit). Every 10 POS lines a COST line gives each part's time.
//
// Settings: WorldProbe.ini (every key documented there). Log: WorldProbe.log.
#include <windows.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ---------------------------------------------------------------- reads that cannot crash

// WpSafeCopy(dst, src, n): 1 = copied, 0 = a fault inside the copy (the handler below resumes at WpSafeCopyFault).
extern "C" int __cdecl WpSafeCopy(void* dst, const void* src, unsigned n);
extern "C" char WpSafeCopyRead[], WpSafeCopyDone[], WpSafeCopyFault[];
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _WpSafeCopy\n"
        ".globl _WpSafeCopyRead\n"
        ".globl _WpSafeCopyDone\n"
        ".globl _WpSafeCopyFault\n"
        "_WpSafeCopy:\n"
        "  push esi\n"
        "  push edi\n"
        "  mov edi, [esp + 12]\n"
        "  mov esi, [esp + 16]\n"
        "  mov ecx, [esp + 20]\n"
        "_WpSafeCopyRead:\n"
        "  rep movsb\n"
        "_WpSafeCopyDone:\n"
        "  mov eax, 1\n"
        "  pop edi\n"
        "  pop esi\n"
        "  ret\n"
        "_WpSafeCopyFault:\n"
        "  xor eax, eax\n"
        "  pop edi\n"
        "  pop esi\n"
        "  ret\n"
        ".att_syntax prefix\n");

static volatile DWORD g_faultAddress;
static int g_faults;

static LONG CALLBACK OnFault(EXCEPTION_POINTERS* e)
{
    DWORD code = e->ExceptionRecord->ExceptionCode;
    DWORD eip = e->ContextRecord->Eip;
    if ((code == EXCEPTION_ACCESS_VIOLATION || code == STATUS_GUARD_PAGE_VIOLATION) &&
        eip >= (DWORD)(UINT_PTR)WpSafeCopyRead && eip < (DWORD)(UINT_PTR)WpSafeCopyDone)
    {
        g_faultAddress = e->ExceptionRecord->NumberParameters >= 2 ? (DWORD)e->ExceptionRecord->ExceptionInformation[1]
                                                                   : 0;
        e->ContextRecord->Eip = (DWORD)(UINT_PTR)WpSafeCopyFault;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

// ---------------------------------------------------------------- time and the log

static FILE* g_log;
static char g_iniPath[MAX_PATH];
static LARGE_INTEGER g_qpcFreq, g_qpcStart;
static double g_lastFlushUs = -1e18;
static bool g_dirty;
static double g_formatUs, g_writeUs, g_flushUs = -1;  // the last Log() call's parts; the last flush (-1 = none)
static CRITICAL_SECTION g_logLock;

static double NowUs()
{
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return (double)(t.QuadPart - g_qpcStart.QuadPart) * 1e6 / (double)g_qpcFreq.QuadPart;
}

static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    EnterCriticalSection(&g_logLock);
    double t0 = NowUs();
    char line[1400];
    int k = snprintf(line, sizeof(line), "[%9.3f] ", t0 / 1e6);
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(line + k, sizeof(line) - k - 1, fmt, args);
    va_end(args);
    k = (n < 0 || k + n > (int)sizeof(line) - 2) ? (int)sizeof(line) - 2 : k + n;
    line[k++] = '\n';
    double t1 = NowUs();
    fwrite(line, 1, k, g_log);
    double t2 = NowUs();
    g_formatUs = t1 - t0;
    g_writeUs = t2 - t1;
    g_dirty = true;
    LeaveCriticalSection(&g_logLock);
}

// Flushes the log if anything is waiting and a second has passed since the last flush (or always with force).
static void MaybeFlush(bool force)
{
    if (!g_log || !g_dirty)
        return;
    double now = NowUs();
    if (!force && now - g_lastFlushUs < 1e6)
        return;
    EnterCriticalSection(&g_logLock);
    fflush(g_log);
    g_dirty = false;
    g_lastFlushUs = NowUs();
    g_flushUs = g_lastFlushUs - now;
    LeaveCriticalSection(&g_logLock);
}

static bool SafeRead(DWORD address, void* out, DWORD size)
{
    if (address < 0x10000 || address + size < address)
        return false;
    if (WpSafeCopy(out, (const void*)(UINT_PTR)address, size))
        return true;
    if (++g_faults <= 10)
        Log("FAULT reading 0x%08lX (at 0x%08lX; caught, that read is skipped)", (unsigned long)address,
            (unsigned long)g_faultAddress);
    return false;
}

// ---------------------------------------------------------------- the game's addresses (speed.exe v1.3)

static const DWORD kHookSite = 0x663D35, kBreakpoint = 0x667650;
static const DWORD kPlayerCount = 0x92D884, kPlayerArray = 0x92D87C;
static const DWORD kPlayerVtbl1 = 0x8B0B10, kPlayerVtbl2 = 0x8B0BD0;
static const DWORD kRigidBodyVtbl = 0x8A9818;
static const DWORD kHeightAtPoint = 0x7897C0;
static const DWORD kFindDrivable = 0x72CA00, kVisibleSectionManager = 0x9A3B50;
static const DWORD kSceneryList = 0x9AA478;
static const DWORD kCollisionPackList = 0x9B38A0;
static const int kCollisionPackMax = 2700;
static const DWORD kSpeedMph = 0x914654, kTelemetryPos = 0x9386D8;

struct Site
{
    DWORD at;
    BYTE bytes[12];
    int n;
    const char* what;
};

static const Site kSites[] = {
    {0x663D35, {0xE8, 0x16, 0x39, 0x00, 0x00}, 5, "MainLoop's call to MainLoopBreakpoint (the per-frame hook)"},
    {0x667650, {0xC3}, 1, "MainLoopBreakpoint (ret)"},
    {0x47EF0A, {0x39, 0x1D, 0x84, 0xD8, 0x92, 0x00}, 6, "ICEGetPlayerCarTransform: cmp [player count 0x92D884]"},
    {0x47EF12, {0xA1, 0x7C, 0xD8, 0x92, 0x00}, 5, "ICEGetPlayerCarTransform: mov eax, [player array 0x92D87C]"},
    {0x6F8FB0, {0x83, 0xE9, 0x20, 0xE9, 0x78, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer GetSimable thunk"},
    {0x6F9050, {0x83, 0xE9, 0x20, 0xE9, 0xA8, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer GetPosition thunk"},
    {0x6F9060, {0x83, 0xE9, 0x20, 0xE9, 0xB8, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer SetPosition thunk"},
    {0x6F9020, {0x8B, 0x41, 0x18, 0x85, 0xC0}, 5, "LocalPlayer::SetPosition"},
    {0x7897C0, {0x83, 0xEC, 0x48, 0x56, 0x68, 0xCD, 0xCC, 0xCC, 0x3C}, 9, "WCollisionMgr::GetWorldHeightAtPoint"},
    {0x72CA00, {0x51, 0x53, 0x55, 0x8B, 0x6C, 0x24, 0x10, 0x8D, 0x59, 0x10}, 10,
     "VisibleSectionManager::FindDrivableSection(bVector2*)"},
    // instructions of the game that hold the data addresses WorldProbe uses (review: tie every data address to
    // checked bytes); 0x914654 (speed) has no such instruction and is read only through the guarded copy
    {0x7318B4, {0xB9, 0x50, 0x3B, 0x9A, 0x00}, 5, "WhatSectionsShouldWeDraw: mov ecx, TheVisibleSectionManager 0x9A3B50"},
    {0x7318CA, {0x8B, 0x3D, 0x78, 0xA4, 0x9A, 0x00}, 6,
     "WhatSectionsShouldWeDraw: mov edi, [ScenerySectionHeaderList 0x9AA478]"},
    {0x772CF1, {0x8B, 0x0D, 0xA0, 0x38, 0x9B, 0x00}, 6, "UnLoadCollisionPack: mov ecx, [mCollisionPackList 0x9B38A0]"},
    {0x6959FD, {0x81, 0xC1, 0xC8, 0x86, 0x93, 0x00}, 6,
     "add ecx, 0x9386C8 (the block holding the telemetry position at +0x10, 0x9386D8)"},
};

struct Slot
{
    DWORD table, offset, value;
    const char* what;
};

static const Slot kSlots[] = {
    {kPlayerVtbl1, 0x04, 0x6F8FB0, "LocalPlayer vtable 1 +0x04 GetSimable"},
    {kPlayerVtbl1, 0x0C, 0x6F9050, "LocalPlayer vtable 1 +0x0C GetPosition"},
    {kPlayerVtbl1, 0x10, 0x6F9060, "LocalPlayer vtable 1 +0x10 SetPosition"},
    {kPlayerVtbl2, 0x04, 0x6F8FB0, "LocalPlayer vtable 2 +0x04 GetSimable"},
    {kPlayerVtbl2, 0x0C, 0x6F9050, "LocalPlayer vtable 2 +0x0C GetPosition"},
    {kPlayerVtbl2, 0x10, 0x6F9060, "LocalPlayer vtable 2 +0x10 SetPosition"},
    {kRigidBodyVtbl, 0x20, 0x671180, "RigidBody vtable +0x20 GetPosition"},
    {kRigidBodyVtbl, 0x5C, 0x696FB0, "RigidBody vtable +0x5C SetPosition"},
    {kRigidBodyVtbl, 0x60, 0x696FD0, "RigidBody vtable +0x60 SetLinearVelocity"},
    {kRigidBodyVtbl, 0x64, 0x696FF0, "RigidBody vtable +0x64 SetAngularVelocity"},
};

static bool ReadDword(DWORD address, DWORD* out) { return SafeRead(address, out, 4); }

static bool ReadFloats(DWORD address, float* out, int n)
{
    if (!SafeRead(address, out, 4 * n))
        return false;
    for (int i = 0; i < n; i++)
        if (!isfinite(out[i]))
            return false;
    return true;
}

static bool BytesAre(DWORD at, const BYTE* bytes, int n, const char* what)
{
    BYTE b[16];
    if (SafeRead(at, b, n) && !memcmp(b, bytes, n))
    {
        Log("check ok 0x%08lX %s", (unsigned long)at, what);
        return true;
    }
    if (SafeRead(at, b, n))
    {
        char hex[64];
        int k = 0;
        for (int i = 0; i < n; i++) k += sprintf(hex + k, " %02X", b[i]);
        Log("WRONGBYTES 0x%08lX %s:%s", (unsigned long)at, what, hex);
    }
    else
        Log("WRONGBYTES 0x%08lX %s: cannot be read", (unsigned long)at, what);
    return false;
}

static bool SlotIs(DWORD table, DWORD offset, DWORD value, const char* what)
{
    DWORD v = 0;
    if (ReadDword(table + offset, &v) && v == value)
    {
        Log("check ok 0x%08lX %s = 0x%08lX", (unsigned long)(table + offset), what, (unsigned long)v);
        return true;
    }
    Log("WRONGBYTES 0x%08lX %s: 0x%08lX, expected 0x%08lX", (unsigned long)(table + offset), what, (unsigned long)v,
        (unsigned long)value);
    return false;
}

static bool CheckAll()
{
    bool ok = true;
    for (const Site& s : kSites) ok &= BytesAre(s.at, s.bytes, s.n, s.what);
    for (const Slot& s : kSlots) ok &= SlotIs(s.table, s.offset, s.value, s.what);
    return ok;
}

// Version 2's optional parts: each has its own checks; a mismatch turns off that part only.
static bool g_rbVehicleOk;
static void CheckOptional()
{
    g_rbVehicleOk = true;
    g_rbVehicleOk &= SlotIs(0x8AC880, 0x5C, 0x696FB0, "RBVehicle IRigidBody vtable +0x5C SetPosition");
    g_rbVehicleOk &= SlotIs(0x8AC880, 0x60, 0x696FD0, "RBVehicle IRigidBody vtable +0x60 SetLinearVelocity");
    g_rbVehicleOk &= SlotIs(0x8AC880, 0x64, 0x696FF0, "RBVehicle IRigidBody vtable +0x64 SetAngularVelocity");
    if (!g_rbVehicleOk)
        Log("part off: velocity zeroing for an RBVehicle body (RBVehicle's IRigidBody slots differ)");
}

// ---------------------------------------------------------------- settings

static DWORD g_interval = 1000, g_fastInterval = 100, g_fastSeconds = 30;
static bool g_teleportEnabled;
static int g_key = 0x78;
static float g_target[3];  // render / world-file convention: x, y horizontal, z up
static bool g_logSections, g_logHeight = true, g_logPacks = true, g_logScenery, g_probeVq = true;
static int g_aboveKey = 0x79, g_frameLines = 30;
static float g_aboveMetres = 20, g_jumpMetres = 20;
static bool g_watchReset = true;
static int g_watchMax = 200, g_otherMax = 20, g_perCallerMax = 10;
// the ring of the last frames (city fixes): dumped when the player's car is reset or drops fast
static const int kRingMax = 600;
static int g_ringFrames = 200;
static bool g_ringFace = true;
static float g_belowMetres = 0.2f, g_faceDropMetres = 2.0f;

static float IniFloat(const char* section, const char* key, float def)
{
    char buf[64];
    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_iniPath);
    if (!buf[0])
        return def;
    return (float)atof(buf);
}

static bool IniBool(const char* section, const char* key, int def)
{
    return GetPrivateProfileIntA(section, key, def, g_iniPath) == 1;
}

static void LoadSettings()
{
    g_interval = GetPrivateProfileIntA("Log", "IntervalMs", 1000, g_iniPath);
    g_logSections = IniBool("Log", "Sections", 0);
    g_logHeight = IniBool("Log", "Height", 1);
    g_logPacks = IniBool("Log", "Packs", 1);
    g_logScenery = IniBool("Log", "Scenery", 0);
    g_probeVq = IniBool("Log", "ProbeVirtualQuery", 1);
    g_teleportEnabled = IniBool("Teleport", "Enabled", 0);
    char buf[32];
    GetPrivateProfileStringA("Teleport", "Key", "0x78", buf, sizeof(buf), g_iniPath);
    g_key = (int)strtoul(buf, nullptr, 0);
    g_target[0] = IniFloat("Teleport", "X", 0);
    g_target[1] = IniFloat("Teleport", "Y", 0);
    g_target[2] = IniFloat("Teleport", "Z", 0);
    g_fastSeconds = GetPrivateProfileIntA("Teleport", "FastSeconds", 30, g_iniPath);
    g_fastInterval = GetPrivateProfileIntA("Teleport", "FastIntervalMs", 100, g_iniPath);
    GetPrivateProfileStringA("Teleport", "AboveKey", "0x79", buf, sizeof(buf), g_iniPath);
    g_aboveKey = (int)strtoul(buf, nullptr, 0);
    g_aboveMetres = IniFloat("Teleport", "AboveMetres", 20);
    g_frameLines = GetPrivateProfileIntA("Teleport", "FrameLines", 30, g_iniPath);
    g_jumpMetres = IniFloat("Watch", "JumpMetres", 20);
    g_watchReset = IniBool("Watch", "Reset", 1);
    g_watchMax = GetPrivateProfileIntA("Watch", "MaxLines", 200, g_iniPath);
    g_otherMax = GetPrivateProfileIntA("Watch", "OtherLines", 20, g_iniPath);
    g_perCallerMax = GetPrivateProfileIntA("Watch", "PerCallerLines", 10, g_iniPath);
    g_ringFrames = GetPrivateProfileIntA("Ring", "Frames", 200, g_iniPath);
    if (g_ringFrames < 0)
        g_ringFrames = 0;
    if (g_ringFrames > kRingMax)
        g_ringFrames = kRingMax;
    g_ringFace = IniBool("Ring", "Face", 1);
    g_belowMetres = IniFloat("Ring", "BelowMetres", 0.2f);
    g_faceDropMetres = IniFloat("Ring", "FaceDropMetres", 2.0f);
}

// The key test. In the game this is GetAsyncKeyState; the stand-in test (world/tests/standin.cpp) exports
// WorldProbeTestKey so a key press can be simulated inside its own process (speed.exe exports no such function).
typedef int(__cdecl* TestKeyFn)(int);
static TestKeyFn g_testKey;
typedef int(__cdecl* TestForegroundFn)();
static TestForegroundFn g_testForeground;

// The key counts only while the game's own window is in front (review: F9 pressed in another window must not move
// the car). The stand-in, which has no window, exports WorldProbeTestForeground instead.
static bool GameInFront()
{
    if (g_testForeground)
        return g_testForeground() != 0;
    HWND w = GetForegroundWindow();
    DWORD pid = 0;
    if (w)
        GetWindowThreadProcessId(w, &pid);
    return pid == GetCurrentProcessId();
}

static bool KeyDown(int vk)
{
    if (g_testKey)
        return g_testKey(vk) != 0;
    return (GetAsyncKeyState(vk) & 0x8000) != 0;
}

// ---------------------------------------------------------------- the game's objects

typedef const float*(__thiscall* GetPositionFn)(void*);
typedef bool(__thiscall* SetPositionFn)(void*, const float*);
typedef void*(__thiscall* GetPtrFn)(void*);
typedef void(__thiscall* SetVecFn)(void*, const float*);
typedef bool(__thiscall* HeightFn)(void*, const float*, float*, float*);
typedef void*(__thiscall* FindDrivableFn)(void*, const float*);

static DWORD Vtbl(void* obj)
{
    DWORD v = 0;
    ReadDword((DWORD)(UINT_PTR)obj, &v);
    return v;
}

static void* Player()
{
    DWORD count = 0, array = 0, player = 0;
    if (!ReadDword(kPlayerCount, &count) || count == 0 || count > 8)
        return nullptr;
    if (!ReadDword(kPlayerArray, &array) || !ReadDword(array, &player) || !player)
        return nullptr;
    DWORD v = Vtbl((void*)(UINT_PTR)player);
    if (v != kPlayerVtbl1 && v != kPlayerVtbl2)
        return nullptr;
    return (void*)(UINT_PTR)player;
}

static bool PlayerPosition(void* player, float* p)
{
    const float* pos = ((GetPositionFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x0C)))(player);
    return pos && ReadFloats((DWORD)(UINT_PTR)pos, p, 3);
}

// The player car's body is an RBVehicle (RBVehicle::Construct 0x6B9490): the IRigidBody that GetRigidBody returns has
// RBVehicle's IRigidBody vtable 0x8AC880 (symbol ??_7RBVehicle@@6BIRigidBody@@@), not RigidBody's 0x8A9818, which
// version 1 required (in the game it logged "no RigidBody"). Both vtables' setters are the same functions
// (+0x5C 0x696FB0, +0x60 0x696FD0, +0x64 0x696FF0); RBVehicle's three slots are checked at start (g_rbVehicleOk).
static const DWORD kRBVehicleRigidBodyVtbl = 0x8AC880;

static void* PlayerSimable(void* player)
{
    return ((GetPtrFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x04)))(player);
}

// The player's IRigidBody, or null; *vtbl gets its vtable (0 if there is no body).
static void* PlayerRigidBody(void* player, DWORD* vtbl)
{
    *vtbl = 0;
    void* simable = PlayerSimable(player);
    DWORD sv = simable ? Vtbl(simable) : 0;
    DWORD fn = 0;
    if (!sv || !ReadDword(sv + 0x54, &fn) || !fn)
        return nullptr;
    void* rb = ((GetPtrFn)(UINT_PTR)fn)(simable);
    return rb && (*vtbl = Vtbl(rb)) != 0 ? rb : nullptr;
}

static bool RigidBodyKnown(DWORD vtbl)
{
    return vtbl == kRigidBodyVtbl || (g_rbVehicleOk && vtbl == kRBVehicleRigidBodyVtbl);
}

static int DrivableSection(const float* render)
{
    float v2[2] = {render[0], render[1]};
    void* s = ((FindDrivableFn)(UINT_PTR)kFindDrivable)((void*)(UINT_PTR)kVisibleSectionManager, v2);
    DWORD n = 0;
    if (!s || !ReadDword((DWORD)(UINT_PTR)s + 0x0C, &n))
        return 0;
    return (short)(n & 0xFFFF);
}

static void SectionName(int number, char* out)
{
    if (number <= 0)
        strcpy(out, "none");
    else
        sprintf(out, "%c%d", (char)(number / 100 + 'A' - 1), number % 100);
}

static void LoadedScenery(char* out, int size, int* count)
{
    // ScenerySectionHeaderList: a circular bTList whose sentinel is the list itself; number at +0x0C
    DWORD node = 0;
    int n = 0, k = 0;
    out[0] = 0;
    if (!ReadDword(kSceneryList, &node))
        return;
    for (int guard = 0; node && node != kSceneryList && guard < 4000; guard++)
    {
        DWORD number = 0;
        if (!ReadDword(node + 0x0C, &number))
            break;
        n++;
        if (k < size - 12)
        {
            char name[16];
            SectionName((int)number, name);
            k += sprintf(out + k, k ? " %s" : "%s", name);
        }
        if (!ReadDword(node, &node))
            break;
    }
    *count = n;
}

static int LoadedPacks()
{
    static DWORD packs[kCollisionPackMax];
    DWORD list = 0;
    if (!ReadDword(kCollisionPackList, &list) || !SafeRead(list, packs, sizeof(packs)))
        return -1;
    int n = 0;
    for (int i = 0; i < kCollisionPackMax; i++) n += packs[i] != 0;
    return n;
}

// ---------------------------------------------------------------- cost: each part's last and max time

enum Part { kPlayerPart, kReadPart, kSectionPart, kHeightPart, kPacksPart, kSceneryPart, kFormatPart, kWritePart,
            kFlushPart, kTotalPart, kParts };
static const char* const kPartNames[kParts] = {"player", "read", "section", "height", "packs", "scenery", "format",
                                               "write", "flush", "total"};
static double g_last[kParts], g_max[kParts];
static bool g_ran[kParts];
static int g_posLines, g_frameCount;
static double g_frameLast, g_frameMax;

static void Took(Part p, double us)
{
    g_last[p] = us;
    if (us > g_max[p])
        g_max[p] = us;
    g_ran[p] = true;
}

static void LogCost()
{
    char text[600];
    int k = 0;
    for (int p = 0; p < kParts; p++)
    {
        if (g_ran[p])
            k += sprintf(text + k, " %s %.0f/%.0f", kPartNames[p], g_last[p], g_max[p]);
        else
            k += sprintf(text + k, " %s %s", kPartNames[p], p == kFlushPart ? "none" : "off");
    }
    Log("COST over 10 POS lines (us last/max):%s; per frame without a POS line %.0f/%.0f over %d frames; faults %d",
        text, g_frameLast, g_frameMax, g_frameCount, g_faults);
    memset(g_last, 0, sizeof(g_last));
    memset(g_max, 0, sizeof(g_max));
    memset(g_ran, 0, sizeof(g_ran));
    g_frameMax = 0;
    g_frameCount = 0;
}

// ---------------------------------------------------------------- once a frame

static DWORD g_lastLog, g_fastUntil;
static bool g_keyWasDown, g_hadPlayer;

static void LogState(void* player)
{
    double t0 = NowUs();
    float p[3];
    if (!PlayerPosition(player, p))
    {
        Log("POS unavailable");
        return;
    }
    float r[3] = {p[2], -p[0], p[1]};
    double t1 = NowUs();
    Took(kPlayerPart, t1 - t0);
    float tel[3] = {0, 0, 0}, mph = 0;
    bool haveTel = ReadFloats(kTelemetryPos, tel, 3);
    bool haveSpeed = ReadFloats(kSpeedMph, &mph, 1);
    double t2 = NowUs();
    Took(kReadPart, t2 - t1);
    char section[40] = "";
    if (g_logSections)
    {
        char name[16];
        SectionName(DrivableSection(r), name);
        sprintf(section, " section %s", name);
        Took(kSectionPart, NowUs() - t2);
    }
    char height[64] = "";
    if (g_logHeight)
    {
        double t = NowUs();
        float probe[3] = {p[0], p[1] + 1.0f, p[2]}, h = 0, normal[3] = {0, 0, 0};
        DWORD mgr[2] = {0, 3};
        bool face = ((HeightFn)(UINT_PTR)kHeightAtPoint)(mgr, probe, &h, normal);
        if (face)
            sprintf(height, " height %.2f (car %.2f above)", h, p[1] - h);
        else
            strcpy(height, " height no face");
        Took(kHeightPart, NowUs() - t);
    }
    char packs[24] = "";
    if (g_logPacks)
    {
        double t = NowUs();
        sprintf(packs, " packs %d", LoadedPacks());
        Took(kPacksPart, NowUs() - t);
    }
    char scenery[420] = "";
    if (g_logScenery)
    {
        double t = NowUs();
        char names[400];
        int nscenery = 0;
        LoadedScenery(names, sizeof(names), &nscenery);
        snprintf(scenery, sizeof(scenery), " scenery %d [%s]", nscenery, names);
        Took(kSceneryPart, NowUs() - t);
    }
    Log("POS physics (%.2f, %.2f, %.2f) render (%.2f, %.2f, %.2f) telemetry %s(%.2f, %.2f, %.2f) speed %s%.1f km/h"
        "%s%s%s%s",
        p[0], p[1], p[2], r[0], r[1], r[2], haveTel ? "" : "unavailable ", tel[0], tel[1], tel[2],
        haveSpeed ? "" : "unavailable ", fabsf(mph) * 1.609344f, section, height, packs, scenery);
    Took(kFormatPart, g_formatUs);
    Took(kWritePart, g_writeUs);
    Took(kTotalPart, NowUs() - t0);
    if (++g_posLines % 10 == 0)
        LogCost();
}

// per-frame state: the car's position last frame (for JUMP), the FRAME lines after a teleport
static float g_prev[3];
static bool g_havePrev;
static int g_framesLeft, g_frameNo;
static double g_teleportUs;
static bool g_inTeleport;  // set while WorldProbe's own SetPosition runs (the watches name it)
static void WatchTeleported();  // the watches: a teleport renews the player's lines and forgets the last call

// Moves the car to t (physics convention), zeroes its velocity, starts the FRAME lines. The log line reads
// "TELEPORT <label>from physics (...) to <toRender>physics (...)": label "" or "above (20.0 m up) ", toRender
// "render (x, y, z) = " for the far target (version 1's text) or "".
static void Teleport(void* player, const float* t, const char* label, const char* toRender)
{
    float before[3] = {0, 0, 0};
    PlayerPosition(player, before);
    WatchTeleported();
    g_inTeleport = true;
    bool ok =((SetPositionFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x10)))(player, t);
    g_inTeleport = false;
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    char velocity[160];
    if (rb && RigidBodyKnown(vtbl))
    {
        static const float zero[3] = {0, 0, 0};
        ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x60)))(rb, zero);
        ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x64)))(rb, zero);
        sprintf(velocity, "zeroed (rigid body vtable 0x%08lX)", (unsigned long)vtbl);
    }
    else if (rb && vtbl == kRBVehicleRigidBodyVtbl)
        sprintf(velocity, "not zeroed (rigid body vtable 0x%08lX: RBVehicle's slots did not check out)",
                (unsigned long)vtbl);
    else if (rb)
        sprintf(velocity, "not zeroed (rigid body vtable 0x%08lX is neither RigidBody's 0x%08lX nor RBVehicle's 0x%08lX)",
                (unsigned long)vtbl, (unsigned long)kRigidBodyVtbl, (unsigned long)kRBVehicleRigidBodyVtbl);
    else
        strcpy(velocity, "not zeroed (no rigid body)");
    Log("TELEPORT %sfrom physics (%.2f, %.2f, %.2f) to %sphysics (%.2f, %.2f, %.2f): %s; velocity %s; %d FRAME "
        "lines, then a POS line every %lu ms for %lu s",
        label, before[0], before[1], before[2], toRender, t[0], t[1], t[2],
        ok ? "set" : "SetPosition returned false", velocity, g_frameLines, (unsigned long)g_fastInterval,
        (unsigned long)g_fastSeconds);
    g_fastUntil = GetTickCount() + g_fastSeconds * 1000;
    g_lastLog = 0;
    g_framesLeft = g_frameLines;
    g_frameNo = 0;
    g_teleportUs = NowUs();
    // the next frame's JUMP test starts from where the car is now (a move back by the game is then a JUMP)
    g_havePrev = PlayerPosition(player, g_prev);
}

static void TeleportFar(void* player)
{
    float t[3] = {-g_target[1], g_target[2], g_target[0]};  // physics = (-render y, render z, render x)
    char toRender[96];
    sprintf(toRender, "render (%.2f, %.2f, %.2f) = ", g_target[0], g_target[1], g_target[2]);
    Teleport(player, t, "", toRender);
}

static void TeleportAbove(void* player)
{
    float p[3];
    if (!PlayerPosition(player, p))
    {
        Log("TELEPORT above: the car's position cannot be read; nothing done");
        return;
    }
    float t[3] = {p[0], p[1] + g_aboveMetres, p[2]};
    char label[48];
    sprintf(label, "above (%.1f m up) ", g_aboveMetres);
    Teleport(player, t, label, "");
}

static void ProbeVirtualQuery(void* player)
{
    MEMORY_BASIC_INFORMATION info;
    double t0 = NowUs();
    SIZE_T got = VirtualQuery(player, &info, sizeof(info));
    double us = NowUs() - t0;
    Log("VQPROBE player object: region of %lu KB, VirtualQuery took %.1f us (version 1 made about 2 such calls per "
        "loaded scenery section and 5 more every frame)",
        got ? (unsigned long)(info.RegionSize >> 10) : 0UL, us);
}

static bool g_aboveWasDown;

// ---------------------------------------------------------------- watching the reset path (log only)
//
// Found in the decompilation (Physics/Behaviors/ResetCar.cpp) and checked in the PC code (docs/ftown-notes.md,
// "WorldProbe 2"): ResetCar::Check (0x6B07C0) calls IResetable::ResetVehicle(false) through call [edx+8] at
// 0x6B0884 = ResetCar::ResetVehicle 0x6B08C0 (ResetCar vtable slot 0x8ABA18; `this` is ResetCar + 0x4C); it calls
// ResetCar::ResetTo 0x6A45F0 at 0x6B0960 (owner ISimable at [this + 0x34]), which calls IVehicle::SetVehicleOnGround
// through call [edx+0x68] at 0x6A4631 = PVehicle::SetVehicleOnGround 0x685810 (slot 0x8AA890; `this` - 0x80 is the
// vehicle's ISimable). The body's own setter is RigidBody::SetPosition 0x696FB0 (RBVehicle IRigidBody slot 0x8AC8DC).
// Each watch: a 5-byte jmp at the function's start to a __fastcall hook (the same stack as the game's __thiscall),
// which logs and calls a trampoline (the overwritten whole instructions, none position-dependent, then a jmp back).

static int g_watchLines, g_watchSuppressed;
static void* g_playerSimable;  // cached once a frame while a player exists (null otherwise)
static void* g_playerRb;
static unsigned g_frameCounter;
static const char* g_lastWatchName;
static const char* g_lastWatchWho;
static unsigned g_lastWatchFrame;

static const char* Who(DWORD simable)
{
    return simable && (void*)(UINT_PTR)simable == g_playerSimable ? "player" : "other";
}

// The last watched call, for the JUMP line. WorldProbe's own SetPosition is not noted (review: otherwise every JUMP
// after a teleport would name it), and a teleport forgets the earlier ones.
static void WatchNote(const char* name, const char* who)
{
    if (g_inTeleport)
        return;
    g_lastWatchName = name;
    g_lastWatchWho = who;
    g_lastWatchFrame = g_frameCounter;
}

// Two budgets (review: traffic and cop spawns call SetVehicleOnGround all through a race and must not use up the
// player's lines): the player's MaxLines, renewed at every player found and every teleport, and OtherLines for other
// cars, after which their calls are only counted (the count is logged at player gone).
static int g_otherLines, g_otherSuppressed;

// Small fixes (2026-11-03; runs E and F: the start grid's RigidBody::SetPosition calls from 0x6912BA and 0x6A7768 used
// up all 200 player lines in the countdown): a third limit, PerCallerLines per watched function and return address
// until the lines are renewed; the rest are counted per caller and listed in "WATCH callers" lines at player gone
// (and when the game exits). The player's lines are renewed at player found, at a teleport and at every JUMP.
struct Caller
{
    const char* name;
    DWORD from;
    int lines;    // lines since the last renewal
    int logged;   // in this race
    int counted;  // calls not logged in this race (this caller's limit or the budget)
    bool noticed;
};
static Caller g_callers[64];
static int g_callerCount, g_callersUntracked;

static void WatchRenew()
{
    g_watchLines = 0;
    for (int i = 0; i < g_callerCount; i++) g_callers[i].lines = 0;
}

static void WatchTeleported()
{
    WatchRenew();
    g_lastWatchName = nullptr;
}

static Caller* FindCaller(const char* name, DWORD from)
{
    for (int i = 0; i < g_callerCount; i++)
        if (g_callers[i].name == name && g_callers[i].from == from)
            return &g_callers[i];
    if (g_callerCount == (int)(sizeof(g_callers) / sizeof(g_callers[0])))
        return nullptr;  // not tracked: only the budgets limit it
    Caller* c = &g_callers[g_callerCount++];
    memset(c, 0, sizeof(*c));
    c->name = name;
    c->from = from;
    return c;
}

static void LogCallers()
{
    char text[1200];
    int k = 0, n = 0;
    for (int i = 0; i < g_callerCount; i++)
    {
        const Caller& c = g_callers[i];
        if (!c.counted)
            continue;
        k += snprintf(text + k, sizeof(text) - k, "%s%s from 0x%08lX: %d logged, %d counted", n % 8 ? "; " : "",
                      c.name, (unsigned long)c.from, c.logged, c.counted);
        if (++n % 8 == 0)
            Log("WATCH callers: %s", text), k = 0;
    }
    if (k)
        Log("WATCH callers: %s", text);
    if (g_callersUntracked)
        Log("WATCH callers: %d calls from callers past the first %d not tracked per caller", g_callersUntracked,
            (int)(sizeof(g_callers) / sizeof(g_callers[0])));
    g_callerCount = g_callersUntracked = 0;
}

static void WatchVLog(const char* fmt, va_list args)
{
    char text[600];
    vsnprintf(text, sizeof(text), fmt, args);
    Log("WATCH %s", text);
}

// A call's first line; true when it was logged (its result line is then logged too, WatchResult).
static bool WatchLog(const char* name, DWORD from, const char* who, const char* fmt, ...)
{
    Caller* c = FindCaller(name, from);
    if (!c)
        g_callersUntracked++;
    if (c && c->lines >= g_perCallerMax)
    {
        c->counted++;
        if (!c->noticed)
        {
            c->noticed = true;
            Log("WATCH: further calls of %s from 0x%08lX are counted, not logged ([Watch] PerCallerLines = %d)", name,
                (unsigned long)from, g_perCallerMax);
        }
        return false;
    }
    if (who[0] == 'o')
    {
        if (g_otherLines >= g_otherMax)
        {
            if (c)
                c->counted++;
            if (g_otherSuppressed++ == 0)
                Log("WATCH: further calls for other cars are counted, not logged ([Watch] OtherLines = %d)",
                    g_otherMax);
            return false;
        }
        g_otherLines++;
    }
    else if (g_watchLines >= g_watchMax)
    {
        if (c)
            c->counted++;
        g_watchSuppressed++;
        return false;
    }
    else
        g_watchLines++;
    if (c)
        c->lines++, c->logged++;
    va_list args;
    va_start(args, fmt);
    WatchVLog(fmt, args);
    va_end(args);
    return true;
}

static void WatchResult(bool logged, const char* fmt, ...)
{
    if (!logged)
        return;
    va_list args;
    va_start(args, fmt);
    WatchVLog(fmt, args);
    va_end(args);
}

static void PositionText(const float* pos, char* out)
{
    float p[3];
    if (pos && ReadFloats((DWORD)(UINT_PTR)pos, p, 3))
        sprintf(out, "physics (%.2f, %.2f, %.2f)", p[0], p[1], p[2]);
    else
        strcpy(out, "(position unreadable)");
}

// ---------------------------------------------------------------- the ring of the last frames
//
// Every frame while a player exists: the time, the car's position (physics), its speed and the face the game's
// height query finds 1 m above it ([Ring] Face: one GetWorldHeightAtPoint a frame, 14-18 us typical on F-Town in
// run G's COST lines). Dumped as RING lines, oldest first, when the player's car is reset (the ResetVehicle watch)
// or falls through the surface: the car more than BelowMetres under the face found above it (run G: 0.55 m under the
// deck), or that face more than FaceDropMetres lower than the frame before, or gone (the ground under the car lost).
// A car driving down a ramp or over a crest does neither (review: a height-lost test fired on every fast descent).
// At most one dump a second per kind (reset, fall); a dump skipped for that is logged in one line. Without Face only
// the reset dumps.
struct RingEntry
{
    double us;
    float p[3];
    float kmh;
    float face;
    bool haveFace;
};
static RingEntry g_ring[kRingMax];
static int g_ringNext, g_ringCount;
static double g_ringQuietUntil[2] = {-1e18, -1e18};  // 0 reset, 1 fall
static bool g_ringSkipNoted[2];

static void RingClear() { g_ringNext = g_ringCount = 0; }

static void RingDump(int kind, const char* why)
{
    if (!g_ringFrames || !g_ringCount)
        return;
    double now = NowUs();
    if (now < g_ringQuietUntil[kind])
    {
        if (!g_ringSkipNoted[kind])
            Log("RING dump skipped (one a second; further ones in this second not noted): %s", why);
        g_ringSkipNoted[kind] = true;
        return;
    }
    g_ringQuietUntil[kind] = now + 1e6;
    g_ringSkipNoted[kind] = false;
    Log("RING last %d frames before %s (oldest first; ms before now)", g_ringCount, why);
    for (int k = 0; k < g_ringCount; k++)
    {
        const RingEntry& e = g_ring[(g_ringNext - g_ringCount + k + g_ringFrames) % g_ringFrames];
        char face[64];
        if (!g_ringFace)
            strcpy(face, "");
        else if (e.haveFace)
            sprintf(face, " face %.2f (car %.2f above)", e.face, e.p[1] - e.face);
        else
            strcpy(face, " face none");
        Log("RING %d -%.1f ms render (%.2f, %.2f, %.2f) speed %.1f km/h%s", k + 1 - g_ringCount, (now - e.us) / 1000.0,
            e.p[2], -e.p[0], e.p[1], e.kmh, face);
    }
}

// one frame into the ring; then the fall tests (see above)
static void RingAdd(const float* p)
{
    if (!g_ringFrames)
        return;
    RingEntry& e = g_ring[g_ringNext];
    e.us = NowUs();
    memcpy(e.p, p, sizeof(e.p));
    float mph = 0;
    ReadFloats(kSpeedMph, &mph, 1);
    e.kmh = fabsf(mph) * 1.609344f;
    e.haveFace = false;
    if (g_ringFace)
    {
        float probe[3] = {p[0], p[1] + 1.0f, p[2]}, h = 0, normal[3] = {0, 0, 0};
        DWORD mgr[2] = {0, 3};
        e.haveFace = ((HeightFn)(UINT_PTR)kHeightAtPoint)(mgr, probe, &h, normal);
        e.face = h;
    }
    g_ringNext = (g_ringNext + 1) % g_ringFrames;
    if (g_ringCount < g_ringFrames)
        g_ringCount++;
    if (!e.haveFace && !g_ringFace)
        return;
    char why[120] = "";
    if (e.haveFace && p[1] - e.face < -g_belowMetres)
        sprintf(why, "a fall through the surface: the car %.2f m under the face found above it", e.face - p[1]);
    else if (g_ringCount > 1)
    {
        const RingEntry& o = g_ring[(g_ringNext - 2 + 2 * g_ringFrames) % g_ringFrames];
        if (o.haveFace && e.haveFace && o.face - e.face > g_faceDropMetres)
            sprintf(why, "a fall: the face under the car %.2f m lower than the frame before", o.face - e.face);
        else if (o.haveFace && !e.haveFace)
            strcpy(why, "a fall: no face under the car (one the frame before)");
    }
    if (why[0])
        RingDump(1, why);
}

static void* g_trResetVehicle;
static void* g_trResetTo;
static void* g_trOnGround;
static void* g_trSetPosition;

static bool __fastcall HkResetVehicle(BYTE* self, void* edx, int manual)
{
    DWORD from = (DWORD)(UINT_PTR)__builtin_return_address(0), owner = 0;
    ReadDword((DWORD)(UINT_PTR)self - 0x4C + 0x34, &owner);
    const char* who = Who(owner);
    WatchNote("ResetCar::ResetVehicle", who);
    if (!strcmp(who, "player"))
        RingDump(0, "ResetCar::ResetVehicle (player)");
    bool logged = WatchLog("ResetCar::ResetVehicle", from, who, "ResetCar::ResetVehicle (%s) manual %d from 0x%08lX",
                           who, manual & 0xFF, (unsigned long)from);
    bool r = ((bool(__fastcall*)(void*, void*, int))g_trResetVehicle)(self, edx, manual);
    WatchResult(logged, "ResetCar::ResetVehicle (%s) -> %d", who, r ? 1 : 0);
    return r;
}

static bool __fastcall HkResetTo(BYTE* self, void* edx, const float* pos, const float* dir, int manual)
{
    DWORD from = (DWORD)(UINT_PTR)__builtin_return_address(0), owner = 0;
    ReadDword((DWORD)(UINT_PTR)self + 0x34, &owner);
    const char* who = Who(owner);
    char to[64];
    PositionText(pos, to);
    WatchNote("ResetCar::ResetTo", who);
    bool logged = WatchLog("ResetCar::ResetTo", from, who, "ResetCar::ResetTo (%s) to %s manual %d from 0x%08lX", who,
                           to, manual & 0xFF, (unsigned long)from);
    bool r = ((bool(__fastcall*)(void*, void*, const float*, const float*, int))g_trResetTo)(self, edx, pos, dir,
                                                                                            manual);
    WatchResult(logged, "ResetCar::ResetTo (%s) -> %d", who, r ? 1 : 0);
    return r;
}

static bool __fastcall HkOnGround(BYTE* self, void* edx, const float* pos, const float* dir)
{
    DWORD from = (DWORD)(UINT_PTR)__builtin_return_address(0);
    const char* who = Who((DWORD)(UINT_PTR)self - 0x80);
    char to[64];
    PositionText(pos, to);
    WatchNote("PVehicle::SetVehicleOnGround", who);
    bool logged = WatchLog("PVehicle::SetVehicleOnGround", from, who, "PVehicle::SetVehicleOnGround (%s) to %s from "
                           "0x%08lX", who, to, (unsigned long)from);
    bool r = ((bool(__fastcall*)(void*, void*, const float*, const float*))g_trOnGround)(self, edx, pos, dir);
    WatchResult(logged, "PVehicle::SetVehicleOnGround (%s) -> %d", who, r ? 1 : 0);
    return r;
}

// Called for every body in the game: only the player's is logged (one pointer compare for the others).
static void __fastcall HkSetPosition(void* self, void* edx, const float* pos)
{
    if (self && self == g_playerRb)
    {
        DWORD from = (DWORD)(UINT_PTR)__builtin_return_address(0);
        char to[64];
        PositionText(pos, to);
        const char* who = g_inTeleport ? "player, WorldProbe's teleport" : "player";
        WatchNote("RigidBody::SetPosition", who);
        WatchLog("RigidBody::SetPosition", from, who, "RigidBody::SetPosition (%s) to %s from 0x%08lX", who, to,
                 (unsigned long)from);
    }
    ((void(__fastcall*)(void*, void*, const float*))g_trSetPosition)(self, edx, pos);
}

struct Watch
{
    const char* name;
    DWORD at;
    BYTE bytes[8];
    int steal;  // whole instructions overwritten by the jmp (>= 5)
    DWORD tieAt;
    BYTE tie[5];
    int tieN;
    const char* tieWhat;
    DWORD slotAt, slotValue;
    const char* slotWhat;
    void* hook;
    void** trampoline;
};

static const Watch kWatches[] = {
    {"ResetCar::ResetVehicle", 0x6B08C0, {0x83, 0xEC, 0x20, 0x53, 0x8B, 0x5C, 0x24, 0x28}, 8,
     0x6B0884, {0xFF, 0x52, 0x08}, 3, "ResetCar::Check: call [edx+8] (IResetable::ResetVehicle)",
     0x8ABA18, 0x6B08C0, "ResetCar vtable +0x08 ResetVehicle", (void*)&HkResetVehicle, &g_trResetVehicle},
    {"ResetCar::ResetTo", 0x6A45F0, {0x6A, 0xFF, 0x68, 0xAF, 0xC9, 0x87, 0x00}, 7,
     0x6B0960, {0xE8, 0x8B, 0x3C, 0xFF, 0xFF}, 5, "ResetCar::ResetVehicle: call ResetCar::ResetTo",
     0, 0, nullptr, (void*)&HkResetTo, &g_trResetTo},
    {"PVehicle::SetVehicleOnGround", 0x685810, {0x6A, 0xFF, 0x64, 0xA1, 0x00, 0x00, 0x00, 0x00}, 8,
     0x6A4631, {0xFF, 0x52, 0x68}, 3, "ResetCar::ResetTo: call [edx+0x68] (IVehicle::SetVehicleOnGround)",
     0x8AA890, 0x685810, "IVehicle vtable +0x68 SetVehicleOnGround", (void*)&HkOnGround, &g_trOnGround},
    {"RigidBody::SetPosition", 0x696FB0, {0x8B, 0x41, 0x30, 0x8B, 0x08}, 5,
     0, {0}, 0, nullptr,
     0x8AC8DC, 0x696FB0, "RBVehicle IRigidBody vtable +0x5C SetPosition", (void*)&HkSetPosition, &g_trSetPosition},
};

static bool Detour(DWORD at, int steal, void* hook, void** trampoline)
{
    BYTE* t = (BYTE*)VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t)
        return false;
    memcpy(t, (const void*)(UINT_PTR)at, steal);
    t[steal] = 0xE9;
    *(DWORD*)(t + steal + 1) = (at + steal) - ((DWORD)(UINT_PTR)t + steal + 5);
    FlushInstructionCache(GetCurrentProcess(), t, 32);
    *trampoline = t;
    DWORD old;
    if (!VirtualProtect((void*)(UINT_PTR)at, steal, PAGE_EXECUTE_READWRITE, &old))
        return false;
    BYTE* p = (BYTE*)(UINT_PTR)at;
    BYTE jmp[8];
    jmp[0] = 0xE9;
    *(DWORD*)(jmp + 1) = (DWORD)(UINT_PTR)hook - (at + 5);
    for (int i = 5; i < steal; i++) jmp[i] = 0x90;
    memcpy(p, jmp, steal);
    VirtualProtect(p, steal, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, steal);
    return true;
}

static void InstallWatches()
{
    if (!g_watchReset)
    {
        Log("watches off ([Watch] Reset = 0)");
        return;
    }
    for (const Watch& w : kWatches)
    {
        bool ok = BytesAre(w.at, w.bytes, w.steal, w.name);
        if (w.tieN)
            ok &= BytesAre(w.tieAt, w.tie, w.tieN, w.tieWhat);
        if (w.slotWhat)
            ok &= SlotIs(w.slotAt, 0, w.slotValue, w.slotWhat);
        if (!ok)
            Log("watch off: %s (WRONGBYTES above)", w.name);
        else if (!Detour(w.at, w.steal, w.hook, w.trampoline))
            Log("watch off: %s (the code could not be made writable)", w.name);
        else
            Log("watching 0x%08lX %s (log only; the game's function still runs)", (unsigned long)w.at, w.name);
    }
}

// what the JUMP line names as the likely cause
static const char* JumpCause()
{
    static char text[160];
    if (!g_lastWatchName)
        return "; no watched call before it";
    snprintf(text, sizeof(text), "; last watched call: %s (%s) %u frames before", g_lastWatchName, g_lastWatchWho,
             g_frameCounter - g_lastWatchFrame);
    return text;
}

static void FrameWork()
{
    void* player = Player();
    if (!player)
    {
        if (g_hadPlayer)
        {
            Log("player gone (race over or menus)");
            MaybeFlush(true);
        }
        g_hadPlayer = false;
        g_framesLeft = 0;
        RingClear();
        g_playerSimable = g_playerRb = nullptr;
        if (g_watchSuppressed || g_otherSuppressed)
        {
            Log("WATCH: %d more calls for the player ([Watch] MaxLines = %d) and %d for other cars ([Watch] "
                "OtherLines = %d) not logged",
                g_watchSuppressed, g_watchMax, g_otherSuppressed, g_otherMax);
            g_watchSuppressed = g_otherSuppressed = 0;
        }
        LogCallers();
        return;
    }
    if (g_watchReset)
    {
        // for the watches' "player" test: the player car's ISimable and IRigidBody (two virtual calls a frame)
        DWORD vtbl;
        g_playerSimable = PlayerSimable(player);
        g_playerRb = PlayerRigidBody(player, &vtbl);
    }
    if (!g_hadPlayer)
    {
        WatchRenew();
        g_otherLines = 0;
        Log("player found (LocalPlayer 0x%08lX)", (unsigned long)(UINT_PTR)player);
        if (g_probeVq)
            ProbeVirtualQuery(player);
    }
    if (!g_hadPlayer)
        g_havePrev = false;
    g_hadPlayer = true;
    bool teleported = false;
    if (g_teleportEnabled)
    {
        bool down = KeyDown(g_key), aboveDown = KeyDown(g_aboveKey);
        if ((down && !g_keyWasDown) || (aboveDown && !g_aboveWasDown))
        {
            if (!GameInFront())
                Log("key ignored: the game window is not in front");
            else if (down && !g_keyWasDown)
                TeleportFar(player), teleported = true;
            else
                TeleportAbove(player), teleported = true;
        }
        g_keyWasDown = down;
        g_aboveWasDown = aboveDown;
    }
    // every frame: the car's position (cheap: one virtual call and a 12-byte copy), for JUMP and the FRAME lines
    float p[3];
    bool havePos = PlayerPosition(player, p);
    if (havePos && !teleported)
    {
        if (g_havePrev)
        {
            float dx = p[0] - g_prev[0], dy = p[1] - g_prev[1], dz = p[2] - g_prev[2];
            float d = sqrtf(dx * dx + dy * dy + dz * dz);
            if (d > g_jumpMetres)
            {
                // small fixes: a JUMP renews the player's lines (FTownLoader's teleports and the game's resets get
                // fresh ones, not only WorldProbe's own teleports)
                Log("JUMP from render (%.2f, %.2f, %.2f) to render (%.2f, %.2f, %.2f): %.1f m in one frame, not by "
                    "WorldProbe%s%s",
                    g_prev[2], -g_prev[0], g_prev[1], p[2], -p[0], p[1], d, JumpCause(),
                    g_watchReset ? "; watch lines renewed" : "");
                WatchRenew();
                RingClear();  // not a drop: the ring starts again at the new place
            }
        }
        memcpy(g_prev, p, sizeof(g_prev));
        g_havePrev = true;
        RingAdd(p);
    }
    else if (teleported)
        RingClear();
    if (g_framesLeft > 0 && !teleported)
    {
        float mph = 0;
        ReadFloats(kSpeedMph, &mph, 1);
        g_frameNo++;
        g_framesLeft--;
        if (havePos)
            Log("FRAME %d +%.1f ms physics (%.2f, %.2f, %.2f) render (%.2f, %.2f, %.2f) speed %.1f km/h", g_frameNo,
                (NowUs() - g_teleportUs) / 1000.0, p[0], p[1], p[2], p[2], -p[0], p[1], fabsf(mph) * 1.609344f);
        else
            Log("FRAME %d +%.1f ms position unavailable", g_frameNo, (NowUs() - g_teleportUs) / 1000.0);
        g_lastLog = 0;  // the POS lines start right after the last FRAME line
        return;
    }
    if (teleported || g_framesLeft > 0)
        return;
    DWORD now = GetTickCount();
    DWORD interval = (g_fastUntil && (int)(g_fastUntil - now) > 0) ? g_fastInterval : g_interval;
    if (!g_lastLog || now - g_lastLog >= interval)
    {
        g_lastLog = now;
        LogState(player);
        return;
    }
}

extern "C" void __cdecl Frame()
{
    ((void(__cdecl*)())(UINT_PTR)kBreakpoint)();
    double t0 = NowUs();
    int lines = g_posLines;
    FrameWork();
    if (g_posLines == lines)
    {
        g_frameLast = NowUs() - t0;
        if (g_frameLast > g_frameMax)
            g_frameMax = g_frameLast;
        g_frameCount++;
    }
    g_frameCounter++;
    double f0 = NowUs();
    double before = g_lastFlushUs;
    MaybeFlush(false);
    if (g_lastFlushUs != before)
        Took(kFlushPart, NowUs() - f0);
}

static bool Install()
{
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)&Frame - (kHookSite + 5);
    DWORD old;
    if (!VirtualProtect((void*)(UINT_PTR)kHookSite, 5, PAGE_EXECUTE_READWRITE, &old))
        return false;
    memcpy((void*)(UINT_PTR)kHookSite, call, 5);
    VirtualProtect((void*)(UINT_PTR)kHookSite, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)(UINT_PTR)kHookSite, 5);
    return true;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_DETACH)
    {
        if (g_log)
        {
            LogCallers();
            Log("WorldProbe unloading");
            MaybeFlush(true);
        }
        return TRUE;
    }
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    InitializeCriticalSection(&g_logLock);
    QueryPerformanceFrequency(&g_qpcFreq);
    QueryPerformanceCounter(&g_qpcStart);
    AddVectoredExceptionHandler(1, OnFault);
    char path[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    strcpy(dot, ".log");
    g_log = fopen(path, "w");
    if (g_log)
        setvbuf(g_log, nullptr, _IOFBF, 1 << 16);
    Log("WorldProbe 2 loaded (F-Town stage 1 diagnostic)");
    LoadSettings();
    g_testKey = (TestKeyFn)(void*)GetProcAddress(GetModuleHandleA(nullptr), "WorldProbeTestKey");
    g_testForeground = (TestForegroundFn)(void*)GetProcAddress(GetModuleHandleA(nullptr), "WorldProbeTestForeground");
    if (!CheckAll())
    {
        Log("WRONGBYTES: not the expected speed.exe v1.3 (or another module changed it); WorldProbe does nothing");
        MaybeFlush(true);
        return TRUE;
    }
    CheckOptional();
    if (!Install())
    {
        Log("refused: the hook site could not be made writable; WorldProbe does nothing");
        MaybeFlush(true);
        return TRUE;
    }
    if (g_teleportEnabled)
        Log("hooked 0x%08lX; log every %lu ms; TELEPORT ON: key 0x%02X moves the car to render (%.2f, %.2f, %.2f), "
            "key 0x%02X %.1f m straight up",
            (unsigned long)kHookSite, (unsigned long)g_interval, g_key, g_target[0], g_target[1], g_target[2],
            g_aboveKey, g_aboveMetres);
    else
        Log("hooked 0x%08lX; log every %lu ms; teleport off ([Teleport] Enabled = 0)", (unsigned long)kHookSite,
            (unsigned long)g_interval);
    Log("parts: section %s, height %s, packs %s, scenery %s", g_logSections ? "on" : "off", g_logHeight ? "on" : "off",
        g_logPacks ? "on" : "off", g_logScenery ? "on" : "off");
    if (g_ringFrames)
        Log("ring: the last %d frames (face %s) dumped at a reset of the player's car or a fall through the surface "
            "(%.2f m under the face above it, the face %.1f m lower than the frame before, or gone)", g_ringFrames,
            g_ringFace ? "on" : "off", g_belowMetres, g_faceDropMetres);
    else
        Log("ring off ([Ring] Frames = 0)");
    InstallWatches();
    MaybeFlush(true);
    return TRUE;
}
