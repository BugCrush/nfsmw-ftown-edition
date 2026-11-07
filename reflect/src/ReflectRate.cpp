// ReflectRate.asi - draws only some of the car reflection's six faces each frame, to save processor time.
//
// The game redraws all six faces of the reflection (a cube map: views 16-21, front, right, back, left, up, down)
// every frame. In its face loop (speed.exe v1.3, 0x6DE675 .. 0x6DE85B) each face starts with a test "is this view
// switched on?" at 0x6DE680; this plugin puts a jump to its own code there, which first asks whether the face is
// due this frame and then does the game's test. A face that is not due is skipped whole: its picture is not
// cleared or drawn into and keeps the one from the frame before. Found and explained in docs/visual-notes.md,
// "The car reflection's six faces". The original bytes are checked first; if they differ (another module, another
// game version) nothing is changed and the log says so.
// Settings: ReflectRate.ini [Reflection] FacesPerFrame (6 = every face every frame: the plugin stays out), Pattern.
// Log: ReflectRate.log, once a second while faces are being drawn: faces drawn=<n> skipped=<n>.
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static FILE* g_log;
static DWORD g_startTick;

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

// The game's addresses (speed.exe v1.3, image base 0x400000).
static const DWORD kSite = 0x6DE680;  // cmp byte [esi+8], bl ; je kSkip  (9 bytes)
static const DWORD kDraw = 0x6DE689;  // the face is drawn from here
static const DWORD kSkip = 0x6DE84C;  // next face
static const DWORD kViews = 0x9196C0; // the 22 views, 0x70 bytes each
static const DWORD kViewSize = 0x70;
static const BYTE kOriginal[9] = { 0x38, 0x5E, 0x08, 0x0F, 0x84, 0xC3, 0x01, 0x00, 0x00 };
enum { kFirstFace = 16, kFaces = 6 };

// Which faces are due. "even": FacesPerFrame of the six each frame, spread so that each face is drawn every
// 6 / FacesPerFrame frames (3: front, back and up one frame; right, left and down the next). "alternate": front
// and back every frame, right and left one frame, up and down the next (the fallback if "even" shows a flicker).
// "balanced": back and left one frame, front, right, up and down the next, so both frames carry the same
// processor time. Time is not proportional to draws: every face costs about 0.25 ms to set up besides its
// draws. GfxProbe, race 2 (2026-10-20), per face in + between: front 0.50, right 0.44, back 1.20, left 0.31,
// up 0.32, down 0.33 ms, so 1.52 against 1.59 ms. ("Back alone" was 1.20 against 1.90 and frame times still
// alternated in the clean race; "even" was 2.02 against 1.08.)
enum Pattern { kEven, kAlternate, kBalanced };
static int g_period = 2; // even: a face is drawn when (frame + face) % period == 0
static Pattern g_pattern = kEven;
static unsigned g_frame;
static int g_warm;          // frames still to come in which every face is drawn
static bool g_drawAll;      // this frame draws every face
static DWORD g_lastLoopTick, g_lastLogTick;
static long g_drawn, g_skipped;

// Called by the code at kSite for every face, before the game's own test. Returns 0 to skip the face.
extern "C" int __cdecl FaceDue(DWORD view)
{
    int face = (int)((view - kViews) / kViewSize) - kFirstFace;
    if (face < 0 || face >= kFaces)
        return 1;
    if (face == 0)
    {
        // A new frame. After a gap (start, menus, loading, a device reset) the faces may be empty or out of date:
        // draw them all in the first two frames before skipping any.
        DWORD now = GetTickCount();
        if (!g_lastLoopTick || now - g_lastLoopTick > 500)
            g_warm = 2;
        g_lastLoopTick = now;
        ++g_frame;
        g_drawAll = g_warm > 0;
        if (g_warm)
            --g_warm;
        if (!g_lastLogTick)
            g_lastLogTick = now;
        if (now - g_lastLogTick >= 1000)
        {
            if (g_drawn || g_skipped)
                Log("faces drawn=%ld skipped=%ld", g_drawn, g_skipped);
            g_drawn = g_skipped = 0;
            g_lastLogTick = now;
        }
    }
    bool due;
    if (g_drawAll)
        due = true;
    else if (g_pattern == kAlternate)
        due = face == 0 || face == 2 || ((face == 1 || face == 3) == ((g_frame & 1) == 0));
    else if (g_pattern == kBalanced)
        due = (face == 2 || face == 3) == ((g_frame & 1) == 0);
    else
        due = (g_frame + face) % g_period == 0;
    if (due)
        ++g_drawn;
    else
        ++g_skipped;
    return due;
}

// The code the jump at kSite goes to:
//   pushad; push esi; call FaceDue; add esp, 4; test eax, eax; popad   (popad keeps the flags, restores eax)
//   je kSkip; cmp byte [esi+8], bl; je kSkip; jmp kDraw
// It lives inside this plugin's own image (not in memory of its own), so that PatchMap names the patch's owner
// as ReflectRate.asi.
static BYTE g_cave[64];

static BYTE* MakeCave()
{
    BYTE* cave = g_cave;
    DWORD old;
    if (!VirtualProtect(cave, sizeof(g_cave), PAGE_EXECUTE_READWRITE, &old))
        return nullptr;
    BYTE* p = cave;
    auto rel = [&](DWORD target) { *(DWORD*)p = target - (DWORD)(UINT_PTR)(p + 4); p += 4; };
    *p++ = 0x60;                                         // pushad
    *p++ = 0x56;                                         // push esi
    *p++ = 0xE8; rel((DWORD)(UINT_PTR)&FaceDue);         // call FaceDue
    *p++ = 0x83; *p++ = 0xC4; *p++ = 0x04;               // add esp, 4
    *p++ = 0x85; *p++ = 0xC0;                            // test eax, eax
    *p++ = 0x61;                                         // popad
    *p++ = 0x0F; *p++ = 0x84; rel(kSkip);                // je kSkip
    memcpy(p, kOriginal, 3); p += 3;                     // cmp byte [esi+8], bl
    *p++ = 0x0F; *p++ = 0x84; rel(kSkip);                // je kSkip
    *p++ = 0xE9; rel(kDraw);                             // jmp kDraw
    FlushInstructionCache(GetCurrentProcess(), cave, 64);
    return cave;
}

static char g_iniPath[MAX_PATH];

// True when [address, address + size) is committed memory that can be read (not unmapped, guarded or no-access).
static bool Readable(DWORD address, DWORD size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((const void*)(UINT_PTR)address, &info, sizeof(info)) || info.State != MEM_COMMIT)
        return false;
    if (info.Protect & (PAGE_NOACCESS | PAGE_GUARD))
        return false;
    return address + size <= (DWORD)(UINT_PTR)info.BaseAddress + info.RegionSize;
}

static void Install()
{
    int per = GetPrivateProfileIntA("Reflection", "FacesPerFrame", 3, g_iniPath);
    char pattern[32];
    GetPrivateProfileStringA("Reflection", "Pattern", "balanced", pattern, sizeof(pattern), g_iniPath);
    g_pattern = !lstrcmpiA(pattern, "alternate") ? kAlternate : !lstrcmpiA(pattern, "balanced") ? kBalanced : kEven;
    if (per >= 6)
    {
        Log("FacesPerFrame=%d: every face every frame, the game is left as it is (off)", per);
        return;
    }
    if (g_pattern == kEven)
    {
        // Only counts that divide six spread evenly: 1, 2, 3 (and 6, off). 4 and 5 become 3.
        if (per < 1) per = 1;
        if (per > 3) per = 3;
        g_period = 6 / per;
    }
    if (!Readable(kSite, sizeof(kOriginal)))
    {
        Log("refused: the code at 0x%08lX cannot be read; nothing changed", (unsigned long)kSite);
        return;
    }
    if (memcmp((const void*)kSite, kOriginal, sizeof(kOriginal)))
    {
        const BYTE* b = (const BYTE*)kSite;
        Log("refused: the bytes at 0x%08lX are %02X %02X %02X %02X %02X %02X %02X %02X %02X, not the game's own; nothing changed",
            (unsigned long)kSite, b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8]);
        return;
    }
    BYTE* cave = MakeCave();
    if (!cave)
    {
        Log("refused: no memory for the code; nothing changed");
        return;
    }
    BYTE jump[9] = { 0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90, 0x90 };
    *(DWORD*)(jump + 1) = (DWORD)(UINT_PTR)cave - (kSite + 5);
    DWORD old;
    if (!VirtualProtect((void*)kSite, sizeof(jump), PAGE_EXECUTE_READWRITE, &old))
    {
        Log("refused: the code at 0x%08lX cannot be made writable; nothing changed", (unsigned long)kSite);
        return;
    }
    memcpy((void*)kSite, jump, sizeof(jump));
    VirtualProtect((void*)kSite, sizeof(jump), old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)kSite, sizeof(jump));
    if (g_pattern == kAlternate)
        Log("patched at 0x%08lX: front and back every frame, the sides every other frame (Pattern=alternate)", (unsigned long)kSite);
    else if (g_pattern == kBalanced)
        Log("patched at 0x%08lX: back and left one frame, the other four the next (Pattern=balanced)", (unsigned long)kSite);
    else
        Log("patched at 0x%08lX: %d of 6 faces a frame, each face every %d frames (Pattern=even)", (unsigned long)kSite,
            6 / g_period, g_period);
}

// [Shadow] Every: the game draws its shadow map through the call at 0x6DEC72 (call 0x6E54E0, the main view and a
// matrix, two arguments, the caller cleans up), right after the main view. Found with GfxProbe's target trace
// (2026-10-30: the switch to the 5461x4096 map came from 0x6BD3D1, called from 0x6E44C0, called from 0x6E54E0).
// With Every = N the call goes through ShadowDraw, which lets every Nth CALL through (all after a start or a gap).
// Caution (race, 2026-10-30): the game makes this call TWICE a frame, so Every = 2 skips the same one of the two every
// frame (that pass may never be redrawn after the warm-up), not alternate frames; it saved about 2 FPS. Installed at 1
// (off). A frame-based skip would need a per-frame signal. The call's bytes are checked first.
static const DWORD kShadowSite = 0x6DEC72, kShadowDraw = 0x6E54E0;
static int g_shadowEvery = 1, g_shadowWarm;
static unsigned g_shadowFrame;
static DWORD g_shadowLastTick, g_shadowLogTick;
static long g_shadowDrawn, g_shadowSkipped;

extern "C" void __cdecl ShadowDraw(DWORD view, DWORD matrix)
{
    DWORD now = GetTickCount();
    if (!g_shadowLastTick || now - g_shadowLastTick > 500)
        g_shadowWarm = 2;
    g_shadowLastTick = now;
    bool due = g_shadowWarm > 0 || (++g_shadowFrame % (unsigned)g_shadowEvery) == 0;
    if (g_shadowWarm)
        --g_shadowWarm;
    if (due)
    {
        ++g_shadowDrawn;
        ((void(__cdecl*)(DWORD, DWORD))kShadowDraw)(view, matrix);
    }
    else
        ++g_shadowSkipped;
    if (!g_shadowLogTick)
        g_shadowLogTick = now;
    if (now - g_shadowLogTick >= 1000)
    {
        Log("shadow drawn=%ld skipped=%ld", g_shadowDrawn, g_shadowSkipped);
        g_shadowDrawn = g_shadowSkipped = 0;
        g_shadowLogTick = now;
    }
}

static void InstallShadow()
{
    g_shadowEvery = GetPrivateProfileIntA("Shadow", "Every", 1, g_iniPath);
    if (g_shadowEvery <= 1)
    {
        Log("shadow map: drawn every frame (Every=1, the game is left as it is)");
        return;
    }
    if (g_shadowEvery > 4)
        g_shadowEvery = 4;
    const BYTE* site = (const BYTE*)kShadowSite;
    if (!Readable(kShadowSite, 5))
    {
        Log("shadow map: call at 0x%08lX cannot be read; left alone", (unsigned long)kShadowSite);
        return;
    }
    if (site[0] != 0xE8 || kShadowSite + 5 + *(const DWORD*)(site + 1) != kShadowDraw)
    {
        Log("shadow map: call at 0x%08lX is not the game's (%02X %02X %02X %02X %02X); left alone", (unsigned long)kShadowSite,
            site[0], site[1], site[2], site[3], site[4]);
        return;
    }
    DWORD old;
    if (!VirtualProtect((void*)kShadowSite, 5, PAGE_EXECUTE_READWRITE, &old))
    {
        Log("shadow map: call at 0x%08lX cannot be made writable; left alone", (unsigned long)kShadowSite);
        return;
    }
    *(DWORD*)(kShadowSite + 1) = (DWORD)(UINT_PTR)&ShadowDraw - (kShadowSite + 5);
    VirtualProtect((void*)kShadowSite, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)kShadowSite, 5);
    Log("shadow map: drawn every %s frame (call at 0x%08lX rerouted)", g_shadowEvery == 2 ? "2nd" : g_shadowEvery == 3 ? "3rd" : "4th",
        (unsigned long)kShadowSite);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    char path[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    strcpy(dot, ".log");
    g_startTick = GetTickCount();
    g_log = fopen(path, "w");
    strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    Log("ReflectRate loaded");
    Install();
    InstallShadow();
    return TRUE;
}
