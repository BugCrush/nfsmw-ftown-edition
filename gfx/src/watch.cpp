// GfxProbe: values in the game's own memory. "Driving" (flow state 6, not paused) is the clock for
// screenshots and dissections; the [Watch] list in the .ini names further addresses to log on change.
#include "probe.h"

bool g_driving;
DWORD g_drivingMs;

enum { kMaxWatch = 32 };
struct Watch
{
    char name[32];
    DWORD address;
    char type; // 'b' u8, 'u' u32, 'i' i32, 'f' f32
    DWORD last;
    bool has;
    DWORD second;
    int lines;
};
static Watch g_watch[kMaxWatch];
static int g_watchCount;

static void Format(const Watch& w, DWORD raw, char* out, size_t size)
{
    if (w.type == 'f')
    {
        float f;
        memcpy(&f, &raw, 4);
        snprintf(out, size, "%g", f);
    }
    else if (w.type == 'i')
        snprintf(out, size, "%ld", (long)raw);
    else
        snprintf(out, size, "%lu", (unsigned long)raw);
}

// [Watch] lines are "name = address,type" with type u8, u32, i32 or f32.
void WatchInit()
{
    static char section[8192];
    GetPrivateProfileSectionA("Watch", section, sizeof(section), g_iniPath);
    for (char* entry = section; *entry && g_watchCount < kMaxWatch; entry += strlen(entry) + 1)
    {
        char line[160];
        snprintf(line, sizeof(line), "%s", entry);
        char* equals = strchr(line, '=');
        if (!equals)
            continue;
        *equals = 0;
        char* name = line;
        while (*name == ' ')
            ++name;
        for (char* end = equals - 1; end >= name && *end == ' '; --end)
            *end = 0;
        char* rest;
        DWORD address = strtoul(equals + 1, &rest, 0);
        while (*rest == ',' || *rest == ' ')
            ++rest;
        char type = !strncmp(rest, "u8", 2) ? 'b' : !strncmp(rest, "u32", 3) ? 'u' : !strncmp(rest, "i32", 3) ? 'i'
            : !strncmp(rest, "f32", 3) ? 'f' : 0;
        if (!type)
        {
            Log("WATCH name=%s OFF unknown type (use u8, u32, i32 or f32)", name);
            continue;
        }
        if (!Readable(address, type == 'b' ? 1 : 4))
        {
            Log("WATCH name=%s OFF address=0x%08lX not readable", name, (unsigned long)address);
            continue;
        }
        Watch& w = g_watch[g_watchCount++];
        memset(&w, 0, sizeof(w));
        snprintf(w.name, sizeof(w.name), "%s", name);
        w.address = address;
        w.type = type;
        Log("WATCH name=%s address=0x%08lX type=%s", w.name, (unsigned long)address, rest);
    }
}

// Once a frame. Changes are logged, at most ten lines a second per value.
void WatchTick()
{
    DWORD second = GetTickCount() / 1000;
    for (int i = 0; i < g_watchCount; ++i)
    {
        Watch& w = g_watch[i];
        DWORD raw = w.type == 'b' ? *(const BYTE*)(UINT_PTR)w.address : *(const DWORD*)(UINT_PTR)w.address;
        if (w.has && raw == w.last)
            continue;
        if (w.second != second)
        {
            w.second = second;
            w.lines = 0;
        }
        if (++w.lines <= 10)
        {
            char now[32], was[32] = "-";
            Format(w, raw, now, sizeof(now));
            if (w.has)
                Format(w, w.last, was, sizeof(was));
            Log("WATCH name=%s value=%s was=%s", w.name, now, was);
        }
        else if (w.lines == 11)
            Log("WATCH name=%s more changes this second not shown", w.name);
        w.last = raw;
        w.has = true;
    }
}

// Once a frame: is the player driving, and for how long in total since the game started.
void DrivingTick()
{
    static bool checked, usable;
    static DWORD last;
    if (!checked)
    {
        checked = true;
        usable = Readable(g_cfg.drivingAddress, 4) && (!g_cfg.pausedAddress || Readable(g_cfg.pausedAddress, 1));
        if (!usable)
            Log("DRIVING off: 0x%08lX or 0x%08lX is not readable; no screenshots or dissections",
                (unsigned long)g_cfg.drivingAddress, (unsigned long)g_cfg.pausedAddress);
    }
    DWORD now = GetTickCount();
    bool driving = usable && *(const DWORD*)(UINT_PTR)g_cfg.drivingAddress == g_cfg.drivingValue
        && (!g_cfg.pausedAddress || *(const BYTE*)(UINT_PTR)g_cfg.pausedAddress == 0);
    if (driving && g_driving)
    {
        DWORD step = now - last;
        g_drivingMs += step > 250 ? 250 : step; // a long stall (loading, alt-tab) is not driving time
    }
    if (driving != g_driving)
        Log("DRIVING state=%d t=%.1f", driving ? 1 : 0, g_drivingMs / 1000.0);
    g_driving = driving;
    last = now;
}
