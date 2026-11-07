// Shared declarations for GfxProbe.asi. One file per purpose; this header is what they offer each other.
#pragma once
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

struct Settings
{
    char captureDir[MAX_PATH];
    char label[64];
    int reportSeconds;
    bool filtering, frameMap, effects, effectValues, resources, shaders, timing, shots, dissect, watch, panel;
    int timingEvery; // time one frame in this many (1 = every frame)
    int panelX, panelBottom;
    float panelOpacity, panelBackground;
    bool panelOnlyInFront, panelSnapshot;
    int shotInterval, maxShots;
    int dissectAt[8], dissectCount;
    DWORD drivingAddress, drivingValue, pausedAddress;
    int traceWidth, traceMax; // [Trace]: log where switches to a target this wide come from (0 = off)
};
extern Settings g_cfg;
extern char g_iniPath[MAX_PATH];
// True while the probe itself calls the device (saving an image): the hooks then forward and count nothing.
extern bool g_own;

// log.cpp
void LogOpen(const char* path);
void Log(const char* fmt, ...);
LONGLONG Ticks();
double TicksToMs(LONGLONG ticks);
void ResolvePath(const char* relative, char* out);
const char* RunDir();
const char* FormatName(D3DFORMAT format);
bool Readable(DWORD address, DWORD bytes);

// hooks.cpp
void* HookSlot(void* object, int slot, void* hook);
bool PatchImport(const char* dll, const char* func, void* hook, void** original);
void InstallDeviceHooks(IDirect3DDevice9* dev);

// filtering.cpp
const char* FilterName(DWORD f);
void FilteringOnSetSamplerState(DWORD stage, D3DSAMPLERSTATETYPE type, DWORD value);
void FilteringOnDraw(IDirect3DDevice9* dev);
void FilteringOnPresent();
void FilteringReport();

// capture.cpp
void CaptureInit();
bool SaveSurface(IDirect3DDevice9* dev, IDirect3DSurface9* src, const char* path, char* note, size_t noteSize);
void CaptureGridIfRequested(IDirect3DDevice9* dev);
// resources.cpp
int TargetId(IDirect3DDevice9* dev, IDirect3DSurface9* surface);
void TargetDescribe(int id, char* out, size_t size);
char TargetKindCode(int id); // first letter of the kind: b(ackbuffer), c(ube), t(exture), d(epth), s(urface); 0 if unknown
void ResourcesOnCreateTexture(UINT width, UINT height, UINT levels, DWORD usage, D3DFORMAT format, bool cube);
void ResourcesOnCreateSurface(const char* kind, UINT width, UINT height, D3DFORMAT format, int multisample);
void ResourcesOnCreateShader(const DWORD* code, void* shader, bool vertex);
void ResourcesReport();
DWORD ShaderHash(void* shader);

// effects.cpp
void EffectsInit();
void EffectsTick();
void EffectsReport();

// frame.cpp
void FrameInit();
void FrameBegin(IDirect3DDevice9* dev, bool allowTiming);
void FrameEnd(bool driving);
void FramePresentDone(LONGLONG ticks);
void FrameSetTarget(int target);
void FrameDraw(D3DPRIMITIVETYPE type, UINT primitives);
void FrameClear();
void FrameCopy(int src, int dst);
void FrameMsaa(DWORD value);
bool FrameStageActive();
int FrameStageNumber();
void FrameReport();
int LabelRegister(const char* fx, const char* tech);
const char* LabelFx(int label);
const char* LabelTech(int label);
// The effect and technique in use (0 = none) and the pass, set by effects.cpp.
extern int g_curLabel, g_curPass;

// Time split. On a timed frame every hook calls TimeEnter on entry and TimeLeave on exit: the time since
// the previous clock read goes to the current stage, as "between calls" (the game's own work) on entry and
// as "inside the call" on exit.
extern bool g_timingFrame;
extern LONGLONG g_lastTick;
extern LONGLONG* g_tickIn;
extern LONGLONG* g_tickOut;
extern LONG g_timedCalls;
inline void TimeEnter()
{
    if (g_timingFrame)
    {
        LONGLONG t = Ticks();
        *g_tickOut += t - g_lastTick;
        g_lastTick = t;
        ++g_timedCalls;
    }
}
inline void TimeLeave()
{
    if (g_timingFrame)
    {
        LONGLONG t = Ticks();
        *g_tickIn += t - g_lastTick;
        g_lastTick = t;
    }
}

// watch.cpp
extern bool g_driving;
extern DWORD g_drivingMs;
void WatchInit();
void DrivingTick();
void WatchTick();

// capture.cpp (screenshots)
void ShotsTick(IDirect3DDevice9* dev);

int FrameTarget();                                                           // frame.cpp
void DescribeTexture(IDirect3DBaseTexture9* texture, char* out, size_t size); // effects.cpp
bool SurfaceRange(IDirect3DDevice9* dev, IDirect3DSurface9* src, float* minOut, float* maxOut, float* meanOut); // capture.cpp

// dissect.cpp
extern bool g_dissecting;
bool DissectWanted();
void DissectStart();
void DissectFinish(IDirect3DDevice9* dev);
void DissectLine(const char* fmt, ...);
void DissectSaveTarget(IDirect3DDevice9* dev);
void DissectDraw(IDirect3DDevice9* dev, const char* call, D3DPRIMITIVETYPE type, UINT primitives);
void DissectState(D3DRENDERSTATETYPE state, DWORD value);
void DissectConstants(bool vertex, UINT reg, const float* data, UINT count);

// frame.cpp, for the live panel: the last frames boiled down to the jobs a frame does.
// Jobs: 0 shadows, 1 car reflection, 2 main view, 3 game logic, 4 screen effects, 5 HUD.
enum { kJobs = 6, kLiveHistory = 100 };
struct LiveData
{
    float draws[kJobs], tris[kJobs], ms[kJobs]; // per frame, smoothed over the last few frames
    float frameMs, presentMs;
    float history[kLiveHistory][3];             // draws of jobs 0-2, one point every 100 ms
    int historyNext;
};
void FrameLiveGet(LiveData* out);

// panel.cpp
void PanelStart(HWND game);
