// GfxProbe: the log file, the clock, paths and names.
#include "probe.h"
#include <shlwapi.h>

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

static FILE* g_log;
static CRITICAL_SECTION g_logLock;
static DWORD g_startTick;
static LONGLONG g_frequency = 1;

void LogOpen(const char* path)
{
    InitializeCriticalSection(&g_logLock);
    g_startTick = GetTickCount();
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    g_frequency = f.QuadPart;
    g_log = fopen(path, "w");
}

void Log(const char* fmt, ...)
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

LONGLONG Ticks()
{
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return t.QuadPart;
}

double TicksToMs(LONGLONG ticks)
{
    return ticks * 1000.0 / g_frequency;
}

void ResolvePath(const char* relative, char* out)
{
    char dir[MAX_PATH], joined[MAX_PATH * 2];
    GetModuleFileNameA((HMODULE)&__ImageBase, dir, MAX_PATH);
    *strrchr(dir, '\\') = 0;
    if (PathIsRelativeA(relative))
        snprintf(joined, sizeof(joined), "%s\\%s", dir, relative);
    else
        snprintf(joined, sizeof(joined), "%s", relative);
    GetFullPathNameA(joined, MAX_PATH, out, nullptr);
}

// <Dir>\<Label>\run-YYYYMMDD-HHMMSS, created the first time something needs it.
const char* RunDir()
{
    static char dir[MAX_PATH + 160];
    if (!dir[0])
    {
        char base[MAX_PATH], sub[MAX_PATH + 80];
        ResolvePath(g_cfg.captureDir, base);
        CreateDirectoryA(base, nullptr);
        snprintf(sub, sizeof(sub), "%s\\%s", base, g_cfg.label);
        CreateDirectoryA(sub, nullptr);
        SYSTEMTIME st;
        GetLocalTime(&st);
        snprintf(dir, sizeof(dir), "%s\\run-%04d%02d%02d-%02d%02d%02d", sub, st.wYear, st.wMonth, st.wDay, st.wHour,
            st.wMinute, st.wSecond);
        CreateDirectoryA(dir, nullptr);
        Log("RUN dir=%s", dir);
    }
    return dir;
}

const char* FormatName(D3DFORMAT format)
{
    switch ((DWORD)format)
    {
    case 20: return "R8G8B8";
    case 21: return "A8R8G8B8";
    case 22: return "X8R8G8B8";
    case 23: return "R5G6B5";
    case 25: return "A1R5G5B5";
    case 26: return "A4R4G4B4";
    case 28: return "A8";
    case 31: return "A2B10G10R10";
    case 32: return "A8B8G8R8";
    case 34: return "G16R16";
    case 35: return "A2R10G10B10";
    case 36: return "A16B16G16R16";
    case 50: return "L8";
    case 51: return "A8L8";
    case 60: return "V8U8";
    case 63: return "Q8W8V8U8";
    case 70: return "D16_LOCKABLE";
    case 71: return "D32";
    case 75: return "D24S8";
    case 77: return "D24X8";
    case 80: return "D16";
    case 81: return "L16";
    case 83: return "D24FS8";
    case 111: return "R16F";
    case 112: return "G16R16F";
    case 113: return "A16B16G16R16F";
    case 114: return "R32F";
    case 115: return "G32R32F";
    case 116: return "A32B32G32R32F";
    }
    // Four-character codes (DXT1, INTZ, ...) are printed as text; anything else as a number.
    static char text[4][16];
    static int next;
    char* out = text[next++ & 3];
    DWORD v = (DWORD)format;
    bool printable = true;
    for (int i = 0; i < 4; ++i)
    {
        BYTE c = (BYTE)(v >> (i * 8));
        if (c < 0x20 || c > 0x7E)
            printable = false;
    }
    if (printable)
        snprintf(out, 16, "%c%c%c%c", (char)v, (char)(v >> 8), (char)(v >> 16), (char)(v >> 24));
    else
        snprintf(out, 16, "fmt%lu", (unsigned long)v);
    return out;
}

bool Readable(DWORD address, DWORD bytes)
{
    MEMORY_BASIC_INFORMATION info;
    if (!address || !VirtualQuery((void*)(UINT_PTR)address, &info, sizeof(info)))
        return false;
    if (info.State != MEM_COMMIT || (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return false;
    return address + bytes <= (DWORD)(UINT_PTR)info.BaseAddress + info.RegionSize;
}
