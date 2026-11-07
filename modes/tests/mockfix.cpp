// Stand-in for the Widescreen Fix, built as NFSMostWanted.WidescreenFix.asi (the name DisplayModes.asi looks for).
// It makes the two calls of the real Fix that matter here, the same way (source: ThirteenAG/WidescreenFixesPack
// 708f752): MockList (built at load) = includes/stdafx.cpp GetResolutionsList(false) (EnumDisplayDevices over adapters and monitors,
// EnumDisplaySettings(NULL, i) with a zeroed DEVMODE, sorted, one entry per size); MockPlace = Resolution.ixx
// sub_6DB0D0's borderless branch (window = the chosen size, centred on the desktop, SetWindowPos from this module).
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

struct Res { int w, h, r; };

static int Cmp(const void* a, const void* b)
{
    const Res* x = (const Res*)a;
    const Res* y = (const Res*)b;
    if (x->w != y->w) return x->w - y->w;
    if (x->h != y->h) return x->h - y->h;
    return y->r - x->r;  // highest refresh first, as the Fix keeps it
}

// Built once while loading, as the real Fix does (its Init runs from its own load, before the next plugin loads).
static char g_list[65536];
static int g_count;

static int BuildList(char* out, int size)
{
    static Res list[4096];
    int n = 0;
    DISPLAY_DEVICEW dd = { sizeof(dd) };
    for (DWORD dev = 0; EnumDisplayDevicesW(NULL, dev, &dd, 0); dev++)
    {
        DISPLAY_DEVICEW mon = { sizeof(mon) };
        for (DWORD m = 0; EnumDisplayDevicesW(dd.DeviceName, m, &mon, 0); m++)
        {
            DEVMODEW dm = { 0 };
            for (DWORD i = 0; EnumDisplaySettingsW(NULL, i, &dm) != 0 && n < 4096; i++)
                list[n++] = { (int)dm.dmPelsWidth, (int)dm.dmPelsHeight, (int)dm.dmDisplayFrequency };
        }
    }
    qsort(list, n, sizeof(Res), Cmp);
    int u = 0;
    for (int i = 0; i < n; i++)
        if (!u || list[u - 1].w != list[i].w || list[u - 1].h != list[i].h)
            list[u++] = list[i];
    out[0] = 0;
    for (int i = 0; i < u; i++)
        snprintf(out + strlen(out), size - strlen(out), " %dx%d@%d", list[i].w, list[i].h, list[i].r);
    return u;
}

extern "C" __declspec(dllexport) int MockList(char* out, int size)
{
    snprintf(out, size, "%s", g_list);
    return g_count;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
        g_count = BuildList(g_list, sizeof(g_list));
    return TRUE;
}

extern "C" __declspec(dllexport) void MockPlace(HWND wnd, int width, int height)
{
    HMONITOR monitor = MonitorFromWindow(GetDesktopWindow(), MONITOR_DEFAULTTONEAREST);
    MONITORINFO info = { sizeof(info) };
    GetMonitorInfoW(monitor, &info);
    int deskW = info.rcMonitor.right - info.rcMonitor.left, deskH = info.rcMonitor.bottom - info.rcMonitor.top;
    int left = (deskW - width) / 2, top = (deskH - height) / 2;
    SetWindowPos(wnd, HWND_NOTOPMOST, left, top, width, height, SWP_SHOWWINDOW);
}

// The Fix's "current settings" read (includes/windowed.hpp): must come back unchanged.
extern "C" __declspec(dllexport) void MockCurrent(int* w, int* h)
{
    DEVMODEW dm = { 0 };
    dm.dmSize = sizeof(dm);
    EnumDisplaySettingsW(NULL, ENUM_CURRENT_SETTINGS, &dm);
    *w = (int)dm.dmPelsWidth;
    *h = (int)dm.dmPelsHeight;
}
