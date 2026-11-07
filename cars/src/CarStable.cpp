// CarStable.asi - keeps the profile loading when cars are added to or removed from the game.
//
// The save holds the whole car stable and a fingerprint of the game's default stable; a car added or removed changes
// the fingerprint and the game refuses the profile as damaged (docs/cars-notes.md). This plugin, at three places in
// speed.exe v1.3:
//  1. 0x5AB9A5 (the call that makes the fingerprint at start): keeps a copy of the default stable and records the
//     fingerprint in CarStable.fingerprints;
//  2. 0x5ACBFA (the compare in UserProfile::LoadFromBuffer): also accepts a fingerprint on the known list
//     ([CarStable] Known in the .ini, and every fingerprint in CarStable.fingerprints);
//  3. 0x5ACD5D (the load succeeded): if the fingerprint differed, brings the loaded stable in line with the game's
//     cars (cars/src/stable.h: new cars added, removed cars and references to them dropped).
// The game saves the profile with the new fingerprint, so the next load needs no help. Every site's bytes are
// checked first; if any differ, nothing is patched and the log says WRONGBYTES.
// Settings: CarStable.ini [CarStable] Enabled (1), Known (fingerprints, separated by spaces or commas).
// Log: CarStable.log.
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <vector>

#include "stable.h"

static FILE* g_log;
static DWORD g_startTick;
static char g_iniPath[MAX_PATH], g_fpPath[MAX_PATH], g_dumpPath[MAX_PATH], g_pendingPath[MAX_PATH];
static int g_maxDrop = 3;

static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    fprintf(g_log, "[%8.3f] ", (GetTickCount() - g_startTick) / 1000.0);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log, fmt, args);
    va_end(args);
    fputc('\n', g_log);
    fflush(g_log);
}

// The game's addresses (speed.exe v1.3).
static const DWORD kFEDatabasePtr = 0x91CF90;
static const DWORD kCrcCall = 0x5AB9A5, kCrc = 0x45CA60;
static const DWORD kCompare = 0x5ACBFA, kEqualPath = 0x5ACC00, kRefusePath = 0x5ACD51;
static const DWORD kLoaded = 0x5ACD5D, kLoadedNext = 0x5ACD63;
static const DWORD kGetDefaultCar = 0x57FB50;
static const BYTE kCompareBytes[6] = {0x0F, 0x85, 0x51, 0x01, 0x00, 0x00};
static const BYTE kLoadedBytes[6] = {0x8A, 0x44, 0x24, 0x40, 0x84, 0xC0};
static const DWORD kProfileStable = 0x414, kProfileCurrentCar = 0xA8;
static const DWORD kQuickRace = 0x1C, kQuickRaceSize = 0x18, kQuickRaceCar = 0x10;

static std::vector<uint32_t> g_known;
static BYTE g_defaults[cars::kStableSize];
static bool g_haveDefaults;
static DWORD g_current;
static bool g_pending;  // this load's fingerprint differed and was accepted

static DWORD FEDatabase() { return *(DWORD*)kFEDatabasePtr; }

static void ParseFingerprints(const char* text)
{
    const char* p = text;
    while (*p)
    {
        char* end;
        unsigned long v = strtoul(p, &end, 16);
        if (end == p)
        {
            ++p;
            continue;
        }
        bool seen = false;
        for (uint32_t k : g_known) seen |= k == v;
        if (!seen) g_known.push_back((uint32_t)v);
        p = end;
    }
}

static void LoadKnown()
{
    char ini[1024];
    GetPrivateProfileStringA("CarStable", "Known", "", ini, sizeof(ini), g_iniPath);
    ParseFingerprints(ini);
    FILE* f = fopen(g_fpPath, "r");
    if (f)
    {
        char line[64];
        while (fgets(line, sizeof(line), f)) ParseFingerprints(line);
        fclose(f);
    }
}

// 1. Called instead of bCalculateCrc32 at 0x5AB9A5 (cdecl, the caller cleans up).
static BYTE g_compareJump[6], g_loadedJump[6];
static bool g_sitesChecked;

// Plugins loaded after this one (the Unlimiter, X360Stuff, ...) could overwrite our sites; by the time the game makes
// its fingerprint every plugin has loaded, so the sites are checked once more then.
static void CheckSitesStillOurs()
{
    if (g_sitesChecked)
        return;
    g_sitesChecked = true;
    if (memcmp((const void*)kCompare, g_compareJump, 6))
        Log("OVERWRITTEN 0x%08lX: another module changed our fingerprint check; old saves will be refused",
            (unsigned long)kCompare);
    if (memcmp((const void*)kLoaded, g_loadedJump, 6))
        Log("OVERWRITTEN 0x%08lX: another module changed our after-load step; accepted saves will not be brought up "
            "to date", (unsigned long)kLoaded);
}

extern "C" DWORD __cdecl StableCrc(const void* buffer, int size, DWORD seed)
{
    CheckSitesStillOurs();
    DWORD crc = ((DWORD(__cdecl*)(const void*, int, DWORD))kCrc)(buffer, size, seed);
    if (size == cars::kStableSize)
    {
        memcpy(g_defaults, buffer, cars::kStableSize);
        g_haveDefaults = true;
        g_current = crc;
        // A copy of the default stable, to see what differs between two car sets (tools/cars/stable-diff.py).
        FILE* dump = fopen(g_dumpPath, "wb");
        if (dump)
        {
            fwrite(g_defaults, 1, cars::kStableSize, dump);
            fclose(dump);
        }
        int cars = 0;
        for (int i = 0; i < cars::kMaxCars; i++) cars += cars::Stable(g_defaults).valid(i);
        bool known = false;
        for (uint32_t k : g_known) known |= k == crc;
        Log("fingerprint of the game's cars: 0x%08lX (%d cars in the default stable)%s", (unsigned long)crc, cars,
            known ? "" : ", new: recorded");
        if (!known)
        {
            g_known.push_back(crc);
            FILE* f = fopen(g_fpPath, "a");
            if (f)
            {
                fprintf(f, "0x%08lX\n", (unsigned long)crc);
                fclose(f);
            }
        }
    }
    return crc;
}

// 2. Called at the compare with the save's fingerprint. Returns 1 to load, 0 to refuse.
extern "C" int __cdecl CheckFingerprint(DWORD saved)
{
    DWORD current = *(DWORD*)(FEDatabase() + 8);
    g_pending = false;
    if (saved == current)
    {
        // cars that did not fit at an earlier load (stable full) are retried although the save is up to date
        DWORD attr = GetFileAttributesA(g_pendingPath);
        g_pending = attr != INVALID_FILE_ATTRIBUTES && g_haveDefaults;
        Log("profile: fingerprint 0x%08lX equal%s", (unsigned long)saved,
            g_pending ? "; cars pending from an earlier load: retried" : "");
        return 1;
    }
    if (cars::fingerprint_accepted(saved, current, g_known) && g_haveDefaults)
    {
        Log("profile: fingerprint 0x%08lX differs from 0x%08lX; known: accepted", (unsigned long)saved,
            (unsigned long)current);
        g_pending = true;
        return 1;
    }
    Log("profile: fingerprint 0x%08lX differs from 0x%08lX; not known: refused (as the game does)", (unsigned long)saved,
        (unsigned long)current);
    return 0;
}

static void LogKeys(const char* what, const std::vector<uint32_t>& keys)
{
    char line[1024];
    int n = 0;
    for (size_t i = 0; i < keys.size() && n < (int)sizeof(line) - 16; i++)
        n += sprintf(line + n, " 0x%08lX", (unsigned long)keys[i]);
    line[n] = 0;
    Log("%s:%s", what, line);
}

// 3. Called when the load succeeded, with the profile and the player. Returns 0 to refuse the load after all.
extern "C" int __cdecl ProfileLoaded(BYTE* profile, int player)
{
    if (!g_pending || player < 0 || player > 1)
        return 1;
    g_pending = false;
    DWORD db = FEDatabase();
    uint32_t defaultCar = ((DWORD(__thiscall*)(DWORD))kGetDefaultCar)(db);
    uint32_t qr[11];
    for (int i = 0; i < 11; i++) qr[i] = *(DWORD*)(db + kQuickRace + kQuickRaceSize * i + kQuickRaceCar + 4 * player);
    uint32_t* current = (uint32_t*)(profile + kProfileCurrentCar);
    uint8_t* stable = profile + kProfileStable;
    cars::ReconcileResult r = cars::reconcile(stable, g_defaults, current, qr, defaultCar, g_maxDrop);
    if (r.guard_tripped)
    {
        Log("DROP-GUARD: %d cars of the save are unknown to the game (more than MaxDrop = %d): nothing changed, the "
            "profile is refused (as the game would); a damaged car database? Look before raising MaxDrop.",
            (int)r.dropped_keys.size(), g_maxDrop);
        LogKeys("unknown cars", r.dropped_keys);
        return 0;
    }
    for (int i = 0; i < 11; i++) *(DWORD*)(db + kQuickRace + kQuickRaceSize * i + kQuickRaceCar + 4 * player) = qr[i];
    if (!r.dropped_keys.empty())
        LogKeys("dropped", r.dropped_keys);
    if (r.not_added_full)
    {
        LogKeys("not added", r.not_added_keys);
        FILE* f = fopen(g_pendingPath, "w");
        if (f)
        {
            for (uint32_t k : r.not_added_keys) fprintf(f, "0x%08lX\n", (unsigned long)k);
            fclose(f);
        }
        Log("kept pending in CarStable.pending: retried at every load until they fit (free a car slot)");
    }
    else
        DeleteFileA(g_pendingPath);
    cars::Stable s(stable);
    int freeCars = 0, freeCustom = 0;
    for (int i = 0; i < cars::kMaxCars; i++) freeCars += !s.valid(i);
    for (int i = 0; i < cars::kMaxCustom; i++) freeCustom += s.custom_handle(i) == cars::kNoSmall;
    Log("stable: added=%d dropped=%d not added (stable full)=%d%s quick race reset=%d; free: %d of 200 cars, %d of 75 "
        "customisations",
        r.added, r.dropped, r.not_added_full, r.reset_current ? "; current car reset;" : ";", r.reset_quickrace,
        freeCars, freeCustom);
    return 1;
}

// Code caves, inside this plugin's image so PatchMap names CarStable.asi as the owner.
static BYTE g_caves[128];

static bool Readable(DWORD address, DWORD size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((const void*)(UINT_PTR)address, &info, sizeof(info)) || info.State != MEM_COMMIT)
        return false;
    if (info.Protect & (PAGE_NOACCESS | PAGE_GUARD))
        return false;
    return address + size <= (DWORD)(UINT_PTR)info.BaseAddress + info.RegionSize;
}

static bool Same(DWORD at, const BYTE* bytes, int n)
{
    if (!Readable(at, n) || memcmp((const void*)at, bytes, n))
    {
        const BYTE* b = (const BYTE*)at;
        if (Readable(at, n))
            Log("WRONGBYTES 0x%08lX: %02X %02X %02X %02X %02X %02X; nothing patched", (unsigned long)at, b[0], b[1], b[2],
                b[3], b[4], b[5]);
        else
            Log("WRONGBYTES 0x%08lX: cannot be read; nothing patched", (unsigned long)at);
        return false;
    }
    return true;
}

static bool Write(DWORD at, const BYTE* bytes, int n)
{
    DWORD old;
    if (!VirtualProtect((void*)at, n, PAGE_EXECUTE_READWRITE, &old))
        return false;
    memcpy((void*)at, bytes, n);
    VirtualProtect((void*)at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)at, n);
    return true;
}

static void Install()
{
    BYTE crcCall[5] = {0xE8};
    *(DWORD*)(crcCall + 1) = kCrc - (kCrcCall + 5);
    if (!Same(kCrcCall, crcCall, 5) || !Same(kCompare, kCompareBytes, 6) || !Same(kLoaded, kLoadedBytes, 6))
        return;
    DWORD old;
    if (!VirtualProtect(g_caves, sizeof(g_caves), PAGE_EXECUTE_READWRITE, &old))
    {
        Log("refused: no executable memory for the code; nothing patched");
        return;
    }
    BYTE* p = g_caves;
    auto rel = [&](DWORD target) {
        *(DWORD*)p = target - (DWORD)(UINT_PTR)(p + 4);
        p += 4;
    };
    // Compare: pushad; push esi; call CheckFingerprint; add esp,4; test eax,eax; popad; je refuse; jmp equal
    BYTE* compareCave = p;
    *p++ = 0x60;
    *p++ = 0x56;
    *p++ = 0xE8; rel((DWORD)(UINT_PTR)&CheckFingerprint);
    *p++ = 0x83; *p++ = 0xC4; *p++ = 0x04;
    *p++ = 0x85; *p++ = 0xC0;
    *p++ = 0x61;
    *p++ = 0x0F; *p++ = 0x84; rel(kRefusePath);
    *p++ = 0xE9; rel(kEqualPath);
    // Loaded: pushad; push [esp+0x64] (player, 0x44 + 0x20 for pushad); push ebp; call ProfileLoaded; add esp,8;
    // test eax,eax; popad (keeps the flags); je refuse (the drop guard: same frame as the compare's refusal);
    // mov al,[esp+0x40]; test al,al; jmp next
    BYTE* loadedCave = p;
    *p++ = 0x60;
    *p++ = 0xFF; *p++ = 0x74; *p++ = 0x24; *p++ = 0x64;
    *p++ = 0x55;
    *p++ = 0xE8; rel((DWORD)(UINT_PTR)&ProfileLoaded);
    *p++ = 0x83; *p++ = 0xC4; *p++ = 0x08;
    *p++ = 0x85; *p++ = 0xC0;
    *p++ = 0x61;
    *p++ = 0x0F; *p++ = 0x84; rel(kRefusePath);
    memcpy(p, kLoadedBytes, 6); p += 6;
    *p++ = 0xE9; rel(kLoadedNext);
    FlushInstructionCache(GetCurrentProcess(), g_caves, sizeof(g_caves));

    BYTE newCrc[5] = {0xE8};
    *(DWORD*)(newCrc + 1) = (DWORD)(UINT_PTR)&StableCrc - (kCrcCall + 5);
    BYTE compareJump[6] = {0xE9, 0, 0, 0, 0, 0x90};
    *(DWORD*)(compareJump + 1) = (DWORD)(UINT_PTR)compareCave - (kCompare + 5);
    BYTE loadedJump[6] = {0xE9, 0, 0, 0, 0, 0x90};
    *(DWORD*)(loadedJump + 1) = (DWORD)(UINT_PTR)loadedCave - (kLoaded + 5);
    memcpy(g_compareJump, compareJump, 6);
    memcpy(g_loadedJump, loadedJump, 6);
    if (!Write(kCrcCall, newCrc, 5) || !Write(kCompare, compareJump, 6) || !Write(kLoaded, loadedJump, 6))
    {
        Log("refused: the game's code could not be made writable (a site may be half patched)");
        return;
    }
    Log("patched 0x%08lX, 0x%08lX, 0x%08lX; %d known fingerprint(s)", (unsigned long)kCrcCall, (unsigned long)kCompare,
        (unsigned long)kLoaded, (int)g_known.size());
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    char path[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    g_startTick = GetTickCount();
    strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    strcpy(dot, ".fingerprints");
    strcpy(g_fpPath, path);
    strcpy(dot, ".defaults.bin");
    strcpy(g_dumpPath, path);
    strcpy(dot, ".pending");
    strcpy(g_pendingPath, path);
    strcpy(dot, ".log");
    g_log = fopen(path, "w");
    Log("CarStable loaded");
    if (!GetPrivateProfileIntA("CarStable", "Enabled", 1, g_iniPath))
    {
        Log("disabled (Enabled = 0): the game is left as it is");
        return TRUE;
    }
    g_maxDrop = GetPrivateProfileIntA("CarStable", "MaxDrop", 3, g_iniPath);
    LoadKnown();
    Install();
    return TRUE;
}
