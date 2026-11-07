// GfxProbe.asi - diagnostic only: what texture filtering the game uses, and clean screenshots.
//
// Hooks: speed.exe's import of d3d9.dll!Direct3DCreate9 -> IDirect3D9::CreateDevice (vtable) ->
// the device's SetSamplerState, the four Draw* calls and Present (vtable). Nothing is changed;
// every call is forwarded as is. It sits above DXVK, so it sees what the GAME asks for, not what
// DXVK may override (DXVK prints its own overrides in speed_d3d9.log).
//
// Filtering: every 8th draw call, the stage-0 sampler state is read back (GetSamplerState, so state
// blocks are covered) and counted. GfxProbe.log gets a summary every 15 s: which filter combinations
// the draws used, and the effective anisotropy (MaxAnisotropy where the min filter is anisotropic,
// otherwise 1).
//
// Screenshots: when the named event NFSMW_GfxCapture is signalled (InputBridge does that on the grid
// at race start), the next presented frame's back buffer is saved as a BMP into
// <Dir>\<Label>\ (settings in GfxProbe.ini). The back buffer has no DXVK HUD or telemetry panel.
// Source layout: see probe.h.
#include "probe.h"
#include <stdlib.h>

Settings g_cfg;
char g_iniPath[MAX_PATH];

static bool IniBool(const char* section, const char* key, bool fallback)
{
    return GetPrivateProfileIntA(section, key, fallback ? 1 : 0, g_iniPath) != 0;
}

// Reads a number written as decimal or 0x-prefixed hexadecimal.
static DWORD IniNumber(const char* section, const char* key, DWORD fallback)
{
    char text[64];
    if (!GetPrivateProfileStringA(section, key, "", text, sizeof(text), g_iniPath))
        return fallback;
    return strtoul(text, nullptr, 0);
}

static void ReadSettings()
{
    strcpy(g_cfg.captureDir, "..\\..\\gfx-captures");
    strcpy(g_cfg.label, "baseline");
    GetPrivateProfileStringA("Capture", "Dir", g_cfg.captureDir, g_cfg.captureDir, MAX_PATH, g_iniPath);
    GetPrivateProfileStringA("Capture", "Label", g_cfg.label, g_cfg.label, sizeof(g_cfg.label), g_iniPath);
    g_cfg.reportSeconds = (int)IniNumber("Log", "ReportSeconds", 15);
    if (g_cfg.reportSeconds < 1)
        g_cfg.reportSeconds = 15;
    g_cfg.filtering = IniBool("Parts", "Filtering", true);
    g_cfg.frameMap = IniBool("Parts", "FrameMap", true);
    g_cfg.effects = IniBool("Parts", "Effects", true);
    g_cfg.effectValues = IniBool("Parts", "EffectValues", true);
    g_cfg.resources = IniBool("Parts", "Resources", true);
    g_cfg.shaders = IniBool("Parts", "Shaders", true);
    g_cfg.timing = IniBool("Parts", "Timing", true);
    g_cfg.shots = IniBool("Parts", "Shots", true);
    g_cfg.dissect = IniBool("Parts", "Dissect", true);
    g_cfg.watch = IniBool("Parts", "Watch", true);
    g_cfg.panel = IniBool("Parts", "Panel", true);
    // [Trace] TargetWidth: when the game switches to a drawing target this many pixels wide, log where the call came
    // from (its caller and the program's return addresses on the stack), once per distinct place, at most Max lines.
    g_cfg.traceWidth = (int)IniNumber("Trace", "TargetWidth", 0);
    g_cfg.traceMax = (int)IniNumber("Trace", "Max", 8);
    g_cfg.timingEvery = (int)IniNumber("Timing", "EveryNFrames", 1);
    if (g_cfg.timingEvery < 1)
        g_cfg.timingEvery = 1;
    g_cfg.panelX = (int)IniNumber("Panel", "X", 790);
    g_cfg.panelBottom = (int)IniNumber("Panel", "Bottom", 32);
    char number[32];
    GetPrivateProfileStringA("Panel", "Opacity", "0.85", number, sizeof(number), g_iniPath);
    g_cfg.panelOpacity = (float)atof(number);
    GetPrivateProfileStringA("Panel", "Background", "0.35", number, sizeof(number), g_iniPath);
    g_cfg.panelBackground = (float)atof(number);
    g_cfg.panelOnlyInFront = IniBool("Panel", "OnlyInFront", true);
    g_cfg.panelSnapshot = IniBool("Panel", "Snapshot", false);
    g_cfg.shotInterval = (int)IniNumber("Shots", "Interval", 10);
    if (g_cfg.shotInterval < 1)
        g_cfg.shotInterval = 10;
    g_cfg.maxShots = (int)IniNumber("Shots", "Max", 40);
    char at[128];
    GetPrivateProfileStringA("Dissect", "At", "3,30,60", at, sizeof(at), g_iniPath);
    for (char* p = at; *p && g_cfg.dissectCount < 8;)
    {
        g_cfg.dissectAt[g_cfg.dissectCount++] = (int)strtol(p, &p, 10);
        while (*p == ',' || *p == ' ')
            ++p;
    }
    g_cfg.drivingAddress = IniNumber("Game", "DrivingAddress", 0x925E90);
    g_cfg.drivingValue = IniNumber("Game", "DrivingValue", 6);
    g_cfg.pausedAddress = IniNumber("Game", "PausedAddress", 0x91CAE4);
    // The time split and the dissection are built on the stage counters.
    if ((g_cfg.timing || g_cfg.dissect || g_cfg.panel) && !g_cfg.frameMap)
    {
        g_cfg.frameMap = true;
        Log("FrameMap switched on because Timing, Dissect or Panel needs it");
    }
}

typedef HRESULT(WINAPI* CreateDeviceFn)(IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
static CreateDeviceFn g_createDevice;
enum { kCreateDevice = 16 };

static HRESULT WINAPI HookCreateDevice(IDirect3D9* d3d, UINT adapter, D3DDEVTYPE type, HWND wnd, DWORD flags,
    D3DPRESENT_PARAMETERS* pp, IDirect3DDevice9** out)
{
    HRESULT hr = g_createDevice(d3d, adapter, type, wnd, flags, pp, out);
    Log("CreateDevice -> 0x%08lX flags=0x%lX %ux%u multisample=%d", (unsigned long)hr, (unsigned long)flags,
        pp ? pp->BackBufferWidth : 0, pp ? pp->BackBufferHeight : 0, pp ? (int)pp->MultiSampleType : 0);
    if (FAILED(hr) || !out || !*out)
        return hr;
    IDirect3DDevice9* dev = *out;
    D3DCAPS9 caps;
    if (SUCCEEDED(dev->GetDeviceCaps(&caps)))
        Log("  device caps: MaxAnisotropy=%lu, anisotropic min filter %s, mag filter %s", (unsigned long)caps.MaxAnisotropy,
            (caps.TextureFilterCaps & D3DPTFILTERCAPS_MINFANISOTROPIC) ? "yes" : "no",
            (caps.TextureFilterCaps & D3DPTFILTERCAPS_MAGFANISOTROPIC) ? "yes" : "no");
    InstallDeviceHooks(dev);
    if (g_cfg.panel)
        PanelStart(pp && pp->hDeviceWindow ? pp->hDeviceWindow : wnd);
    return hr;
}

typedef IDirect3D9*(WINAPI* Direct3DCreate9Fn)(UINT);
static Direct3DCreate9Fn g_realCreate9;

static IDirect3D9* WINAPI HookedDirect3DCreate9(UINT sdk)
{
    IDirect3D9* d3d = g_realCreate9(sdk);
    Log("Direct3DCreate9(%u) -> %p", sdk, (void*)d3d);
    if (d3d)
    {
        void* p = HookSlot(d3d, kCreateDevice, (void*)HookCreateDevice);
        if (p)
            g_createDevice = (CreateDeviceFn)p;
    }
    return d3d;
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
    LogOpen(path);
    strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    ReadSettings();
    CaptureInit();
    FrameInit();
    if (g_cfg.watch)
        WatchInit();
    Log("GfxProbe loaded; captures go to %s\\%s", g_cfg.captureDir, g_cfg.label);
    Log("Import hook %s", PatchImport("d3d9.dll", "Direct3DCreate9", (void*)HookedDirect3DCreate9, (void**)&g_realCreate9)
        ? "installed" : "NOT FOUND (Direct3DCreate9 not imported)");
    if (g_cfg.effects)
        EffectsInit();
    return TRUE;
}
