// MusicProbe.asi - diagnostic only: how the game lists, enables and picks its EA Trax songs.
//
// It changes no behaviour. Two parts, both writing to scripts\MusicProbe.log (the previous launch is
// kept as MusicProbe.prev.log):
//  - Watching: a thread reads the game's memory 100 times a second through ReadProcessMemory (a wrong
//    address reads as "unavailable", never a crash) and logs every change.
//  - Call logging ([Probe] LogCalls in MusicProbe.ini, on by default): six of the music system's
//    functions are wrapped so each call is logged and then passed on unchanged: the event lookup
//    (function entry) and the stream channel's play, stop, pause, time-remaining and set-volume
//    (function-table slots). Nothing is installed unless the game's bytes are exactly as expected.
//
// Addresses are for speed.exe v1.3 (MD5 c0516b48...), from our own disassembly and from
// XNFSMusicPlayer by xan1242 (MIT). If the code at the song picker doesn't match, the probe stays idle.
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "Detour.h"

static const UINT_PTR kPicker = 0x4F4CD0;          // picks the next song for a context
static const UINT_PTR kTrackCount = 0x8F42C4;      // int: number of songs in the list
static const UINT_PTR kListBegin = 0x9123D0;       // pointer to an array of pointers to song entries
static const UINT_PTR kListEnd = 0x9123D4;
static const UINT_PTR kContexts = 0x8F2080;        // two 24-byte records: menus and races
static const UINT_PTR kSettingsRoot = 0x91CF90;    // [[root]+0x10]+0x324 = per-song modes in the profile
static const UINT_PTR kPaused = 0x91CAE4;          // byte
static const UINT_PTR kFlowState = 0x925E90;       // int: game flow state (menus, loading, racing...)
static const BYTE kPickerCode[10] = { 0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x50, 0x01, 0x00, 0x00 };

struct SongEntry { UINT_PTR title, album, artist, mode; DWORD id; };                    // 20 bytes
struct Context { DWORD enabled, left; int count, last, chosen; DWORD random; };          // 24 bytes
struct SavedMode { int number; BYTE mode; BYTE pad[3]; };                                // 8 bytes

static FILE* g_log;
static DWORD g_startTick;
static CRITICAL_SECTION g_logLock; // the wrapped functions are called from the game's threads

static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    EnterCriticalSection(&g_logLock);
    fprintf(g_log, "[%8.3f] ", (GetTickCount() - g_startTick) / 1000.0);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log, fmt, args);
    va_end(args);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_logLock);
}

static bool ReadMem(UINT_PTR addr, void* out, SIZE_T size)
{
    SIZE_T got = 0;
    return addr && ReadProcessMemory(GetCurrentProcess(), (LPCVOID)addr, out, size, &got) && got == size;
}

// Reads a C string from the game; bytes outside plain ASCII are shown as \xNN so the log shows
// exactly what the game stores.
static void ReadText(UINT_PTR addr, char* out, size_t outSize)
{
    char raw[96] = {};
    size_t n = 0;
    while (n < sizeof(raw) - 1 && ReadMem(addr + n, raw + n, 1) && raw[n])
        ++n;
    size_t o = 0;
    for (size_t i = 0; i < n && o + 5 < outSize; ++i)
    {
        unsigned char c = (unsigned char)raw[i];
        if (c >= 32 && c < 127)
            out[o++] = (char)c;
        else
            o += snprintf(out + o, outSize - o, "\\x%02X", c);
    }
    out[o] = 0;
}

static bool ReadEntry(int index, SongEntry* entry)
{
    UINT_PTR begin = 0, ptr = 0;
    return ReadMem(kListBegin, &begin, 4) && ReadMem(begin + index * 4, &ptr, 4) && ReadMem(ptr, entry, sizeof(*entry));
}

static void DumpList(int count)
{
    Log("track list: %d songs", count);
    for (int i = 0; i < count; ++i)
    {
        SongEntry e;
        if (!ReadEntry(i, &e))
        {
            Log("  %2d: unreadable", i);
            continue;
        }
        char title[400], album[400], artist[400], mode[400];
        ReadText(e.title, title, sizeof(title));
        ReadText(e.album, album, sizeof(album));
        ReadText(e.artist, artist, sizeof(artist));
        ReadText(e.mode, mode, sizeof(mode));
        Log("  %2d: id=%08lX mode=%s title=[%s] artist=[%s] album=[%s]", i, (unsigned long)e.id, mode, title, artist, album);
    }
}

static void LogContext(int index, const Context& c, int count)
{
    char title[400] = "-";
    SongEntry e;
    if (c.chosen >= 0 && c.chosen < count && ReadEntry(c.chosen, &e))
        ReadText(e.title, title, sizeof(title));
    Log("context %d: enabled=%08lX left=%08lX count=%d last=%d chosen=%d [%s] random=%lu", index, (unsigned long)c.enabled,
        (unsigned long)c.left, c.count, c.last, c.chosen, title, (unsigned long)c.random);
}

// ---------------------------------------------------------------------------------------------
// Call logging: each wrapper logs, then calls the game's own function with the same arguments and
// returns its result. The stream channel's functions take `this` in ecx and clean their own stack,
// which is what __fastcall does once a dummy edx parameter is added.

static const UINT_PTR kLookup = 0x82BFD0;       // event lookup: (id, mask) -> record, or 0
static const BYTE kLookupCode[8] = { 0x55, 0x8B, 0xEC, 0xA1, 0x64, 0x29, 0x9C, 0x00 };
static const UINT_PTR kSlotStop = 0x8C5F3C, kSlotPause = 0x8C5F40, kSlotTimeLeft = 0x8C5F50, kSlotPlay = 0x8C5F58,
                      kSlotVolume = 0x8C5F60;
static const UINT_PTR kStop = 0x82B5A0, kPause = 0x82A580, kTimeLeft = 0x82B460, kPlay = 0x82B4A0, kVolume = 0x82B290;

typedef void*(__cdecl* LookupFn)(DWORD id, DWORD mask);
typedef int(__fastcall* ChannelFn0)(void* self, void* edx);
typedef int(__fastcall* ChannelFn1)(void* self, void* edx, int a);
typedef int(__fastcall* ChannelFn5)(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e);
static LookupFn g_lookup;

// A call that repeats with the same key is logged once a second at most, with the number skipped.
struct Throttle { DWORD key, lastTick, skipped; };
static bool ShouldLog(Throttle* t, DWORD key, DWORD* skipped)
{
    DWORD now = GetTickCount();
    if (key == t->key && now - t->lastTick < 1000)
    {
        InterlockedIncrement((LONG*)&t->skipped);
        return false;
    }
    *skipped = InterlockedExchange((LONG*)&t->skipped, 0);
    t->key = key;
    t->lastTick = now;
    return true;
}

static void* __cdecl WrapLookup(DWORD id, DWORD mask)
{
    void* record = g_lookup(id, mask);
    static Throttle throttle;
    DWORD skipped;
    if (ShouldLog(&throttle, id ^ mask ^ (record ? 1u : 0u), &skipped))
    {
        DWORD r[11] = {};
        if (record)
            ReadMem((UINT_PTR)record, r, sizeof(r));
        Log("lookup id=%08lX mask=%08lX -> %p [%08lX %08lX %08lX %08lX %08lX %08lX %08lX %08lX %08lX %08lX %08lX] thread=%lu (+%lu same)",
            (unsigned long)id, (unsigned long)mask, record, (unsigned long)r[0], (unsigned long)r[1], (unsigned long)r[2],
            (unsigned long)r[3], (unsigned long)r[4], (unsigned long)r[5], (unsigned long)r[6], (unsigned long)r[7],
            (unsigned long)r[8], (unsigned long)r[9], (unsigned long)r[10], GetCurrentThreadId(), (unsigned long)skipped);
    }
    return record;
}

static int __fastcall WrapPlay(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e)
{
    int result = ((ChannelFn5)kPlay)(self, edx, a, b, c, d, e);
    Log("play   channel=%p args=%08lX %08lX %08lX %08lX %08lX -> %08X thread=%lu", self, (unsigned long)a, (unsigned long)b,
        (unsigned long)c, (unsigned long)d, (unsigned long)e, result, GetCurrentThreadId());
    return result;
}

static int __fastcall WrapStop(void* self, void* edx)
{
    int result = ((ChannelFn0)kStop)(self, edx);
    Log("stop   channel=%p -> %08X thread=%lu", self, result, GetCurrentThreadId());
    return result;
}

static int __fastcall WrapPause(void* self, void* edx, int a)
{
    int result = ((ChannelFn1)kPause)(self, edx, a);
    Log("pause  channel=%p arg=%d -> %08X thread=%lu", self, a, result, GetCurrentThreadId());
    return result;
}

static int __fastcall WrapTimeLeft(void* self, void* edx, int slot)
{
    int result = ((ChannelFn1)kTimeLeft)(self, edx, slot);
    static Throttle throttle;
    DWORD skipped;
    if (ShouldLog(&throttle, (DWORD)(UINT_PTR)self ^ (DWORD)slot, &skipped))
        Log("left   channel=%p slot=%d -> %d ms (+%lu calls)", self, slot, result, (unsigned long)skipped);
    return result;
}

static int __fastcall WrapVolume(void* self, void* edx, int volume)
{
    int result = ((ChannelFn1)kVolume)(self, edx, volume);
    Log("volume channel=%p %d (of 127) -> %08X thread=%lu", self, volume, result, GetCurrentThreadId());
    return result;
}

static void InstallCallLogging()
{
    g_lookup = (LookupFn)InstallDetour((void*)kLookup, (void*)WrapLookup, sizeof(kLookupCode), kLookupCode);
    Log("call logging: lookup %s", g_lookup ? "wrapped" : "NOT wrapped (code differs)");
    struct { const char* name; UINT_PTR slot, original; void* wrapper; } slots[] = {
        { "play", kSlotPlay, kPlay, (void*)WrapPlay },           { "stop", kSlotStop, kStop, (void*)WrapStop },
        { "pause", kSlotPause, kPause, (void*)WrapPause },       { "time left", kSlotTimeLeft, kTimeLeft, (void*)WrapTimeLeft },
        { "volume", kSlotVolume, kVolume, (void*)WrapVolume },
    };
    for (auto& s : slots)
        Log("call logging: %s %s", s.name,
            SwapPointer((void**)s.slot, (void*)s.original, s.wrapper) ? "wrapped" : "NOT wrapped (slot differs)");
}

static bool IsGame()
{
    BYTE code[sizeof(kPickerCode)];
    return ReadMem(kPicker, code, sizeof(code)) && memcmp(code, kPickerCode, sizeof(code)) == 0;
}

static DWORD WINAPI Watch(void*)
{

    int lastCount = -2, lastFlow = -2, lastPaused = -2;
    Context lastCtx[2];
    memset(lastCtx, 0xEE, sizeof(lastCtx));
    SavedMode lastModes[64];
    memset(lastModes, 0xEE, sizeof(lastModes));
    UINT_PTR lastBegin = 0;

    for (;;)
    {
        int count = -1, flow = -1;
        BYTE paused = 0;
        UINT_PTR begin = 0, end = 0;
        ReadMem(kTrackCount, &count, 4);
        ReadMem(kListBegin, &begin, 4);
        ReadMem(kListEnd, &end, 4);
        if (count > 0 && begin && (int)((end - begin) / 4) == count && (count != lastCount || begin != lastBegin))
        {
            DumpList(count);
            lastCount = count;
            lastBegin = begin;
        }

        if (ReadMem(kFlowState, &flow, 4) && flow != lastFlow)
        {
            Log("flow state %d -> %d", lastFlow, flow);
            lastFlow = flow;
        }
        if (ReadMem(kPaused, &paused, 1) && paused != lastPaused)
        {
            Log("paused = %d", paused);
            lastPaused = paused;
        }

        Context ctx[2];
        if (ReadMem(kContexts, ctx, sizeof(ctx)))
            for (int i = 0; i < 2; ++i)
                if (memcmp(&ctx[i], &lastCtx[i], sizeof(Context)) != 0)
                {
                    LogContext(i, ctx[i], count);
                    lastCtx[i] = ctx[i];
                }

        UINT_PTR root = 0, profile = 0;
        SavedMode modes[64];
        int n = count > 64 ? 64 : count;
        if (n > 0 && ReadMem(kSettingsRoot, &root, 4) && ReadMem(root + 0x10, &profile, 4)
            && ReadMem(profile + 0x324, modes, n * sizeof(SavedMode)) && memcmp(modes, lastModes, n * sizeof(SavedMode)) != 0)
        {
            char line[1024] = "";
            size_t len = 0;
            for (int i = 0; i < n && len + 16 < sizeof(line); ++i)
                len += snprintf(line + len, sizeof(line) - len, " %d:%d", modes[i].number, modes[i].mode);
            Log("saved modes (number:mode; 0 off, 1 menus, 2 races, 3 all):%s", line);
            memcpy(lastModes, modes, n * sizeof(SavedMode));
        }
        Sleep(10);
    }
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    char path[MAX_PATH], prev[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    strcpy(dot, ".prev.log");
    strcpy(prev, path);
    strcpy(dot, ".log");
    MoveFileExA(path, prev, MOVEFILE_REPLACE_EXISTING);
    InitializeCriticalSection(&g_logLock);
    g_startTick = GetTickCount();
    g_log = fopen(path, "w");
    Log("MusicProbe loaded.");
    if (!IsGame())
    {
        Log("Not speed.exe v1.3 (the code at 0x4F4CD0 doesn't match): idle.");
        return TRUE;
    }
    strcpy(dot, ".ini");
    if (GetPrivateProfileIntA("Probe", "LogCalls", 1, path))
        InstallCallLogging();
    else
        Log("call logging: off (MusicProbe.ini)");
    Log("speed.exe v1.3 recognised; watching.");
    CloseHandle(CreateThread(nullptr, 0, Watch, nullptr, 0, nullptr));
    return TRUE;
}
