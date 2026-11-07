// InputBridge.asi - sits between the game and DirectInput.
//
// The game imports DirectInput8Create from DINPUT8.dll; we patch that import-table entry and wrap
// every DirectInput object it creates in a proxy.
//
// For an Xbox controller, the proxy becomes a virtual controller fed by XInput:
//   - X/Y = left stick, Z = LT only, Rx = RT only, Ry = right stick Y, Rz = right stick X.
//     Triggers rest at the axis centre and go to max when pressed, so the Controls menu sees
//     them as two separate half-axes. Rz doesn't exist on the real DirectInput device; we add
//     it and park the right stick's X there, which the game doesn't use. (RT is on Rx rather
//     than Rz for a historical reason: see docs/controller-notes.md, "Bindings".)
//   - The left stick and both triggers are shaped first ([Steering], [Triggers]).
//   - Buttons 0-9 and the POV hat keep DirectInput's standard Xbox layout.
//   - Force feedback is reported as supported. Effects the game creates are simulated here and
//     mixed into the controller's two rumble motors by a background thread, along with a shift
//     kick and a nitrous buzz of our own.
// Other devices (keyboard, mouse) are passed through unchanged; everything is logged.
//
// It also reads the car's speed, RPM, gear, nitrous and position from game memory (telemetry):
// a CSV per race, an on-screen panel, and a finder for the game's own InputControls struct.
//
// Settings: InputBridge.ini next to this .asi. Log: InputBridge.log (overwritten each launch).
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <xinput.h>
#include <math.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
#include <string>
#include <algorithm>
#include <shlwapi.h>

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

// ---------------------------------------------------------------------------------------------
// Settings

// Rumble events: how the game's force-feedback effects are grouped for tuning.
enum RumbleEvent { EvImpact, EvSurface, EvHeavySurface, EvConstant, EvSteering, EvCount };
static const char* kEventNames[EvCount] = { "Impact", "Surface", "HeavySurface", "Constant", "Steering" };
enum MotorMask { MotorLeft = 1, MotorRight = 2, MotorBoth = 3 };

struct EventSettings
{
    float scale;
    int motors;
    float length; // multiplies the duration of effects that have one (1.0 = as the game asks)
};

struct Settings
{
    bool virtualController = true;
    bool rumble = true;
    float strength = 1.0f;
    float minLevel = 0.15f;
    float curve = 0.75f;
    float blend = 0.3f; // simultaneous effects: strongest + Blend x the others (1 = add them up)
    DWORD periodSplitMs = 50;
    DWORD impactMaxMs = 1000;
    EventSettings events[EvCount] = {
        { 2.5f, MotorBoth, 1.0f },  // Impact
        { 1.6f, MotorRight, 1.0f }, // Surface
        { 2.0f, MotorLeft, 1.0f },  // HeavySurface
        { 1.5f, MotorLeft, 1.0f },  // Constant
        { 0.0f, MotorLeft, 1.0f },  // Steering
    };
    // Vibrations InputBridge adds itself, from the controller (only during a race).
    float shiftScale = 0.9f;
    int shiftMotors = MotorLeft;
    DWORD shiftMs = 90;
    float nitrousScale = 0.35f;
    int nitrousMotors = MotorRight;
    WORD nitrousButton = 0x1000; // XINPUT_GAMEPAD_A
    // Trigger shaping (both LT and RT), as fractions of full travel.
    float triggerDeadzone = 0.04f;
    float triggerFullAt = 0.95f;
    float rtCurve = 0.5f; // MW's throttle is steep: half RT gave ~15% of full acceleration (telemetry)
    float ltCurve = 1.0f; // braking not measured yet
    // Left stick (steering) shaping, radial, as fractions of full deflection.
    float stickDeadzone = 0.08f;
    float stickOuter = 0.95f;     // full lock at this deflection
    float stickCurve = 1.3f;      // 1 = linear, >1 gentler near the centre
    float stickAntiDeadzone = 0.0f;
    // Test-only: replace the pad with a scripted loop (2 s full throttle, 2 s released, 2 s hard right,
    // with a 0.2 s right stick click at 5 s), so the controls finder and the next-song request can be
    // tested without a player. Never set this for play.
    bool debugFakePad = false;
    // The game acts on its "next song" button only in the menus. When this button (0-9, as in the
    // bindings table; 9 = right stick click) goes down, we ask MusicBridge, which does it during a
    // race. -1 = off.
    int nextSongButton = 9;
    // Telemetry: CSV log during races and an on-screen panel next to DXVK's frame-time graph.
    bool telemetryLog = true;
    bool overlay = true;
    bool overlayOnlyInFront = true; // hide the panel when the game isn't the foreground window
    int overlayX = 440;        // pixels from the game window's left edge
    int overlayBottom = 32;    // pixels from the game window's bottom edge
    float overlayOpacity = 0.85f;
    float overlayBackground = 0.35f;
    int telemetryKeep = 10;
    char telemetryDir[MAX_PATH] = "..\\..\\telemetry";
    bool logState = true;
    // [Controls] DefaultLayout: the game's default controller bindings (what a new profile and the Controls menu's
    // "restore defaults" get) become our layout when the pad is one we make virtual. Read at start only.
    bool defaultLayout = false;
};
static Settings g_cfg;
static char g_iniPath[MAX_PATH];

static float IniFloat(const char* path, const char* section, const char* key, float def)
{
    char buf[32], defBuf[32];
    snprintf(defBuf, sizeof(defBuf), "%g", def);
    GetPrivateProfileStringA(section, key, defBuf, buf, sizeof(buf), path);
    return (float)atof(buf);
}

static int IniMotors(const char* path, const char* section, int def)
{
    char buf[16];
    GetPrivateProfileStringA(section, "Motor", "", buf, sizeof(buf), path);
    if (_stricmp(buf, "Left") == 0) return MotorLeft;
    if (_stricmp(buf, "Right") == 0) return MotorRight;
    if (_stricmp(buf, "Both") == 0) return MotorBoth;
    return def;
}

static WORD IniButton(const char* path, const char* section, WORD def)
{
    static const struct { const char* name; WORD mask; } kButtons[] = {
        { "A", 0x1000 }, { "B", 0x2000 }, { "X", 0x4000 }, { "Y", 0x8000 },
        { "LB", 0x0100 }, { "RB", 0x0200 }, { "Back", 0x0020 }, { "Start", 0x0010 },
        { "LS", 0x0040 }, { "RS", 0x0080 },
    };
    char buf[16];
    GetPrivateProfileStringA(section, "Button", "", buf, sizeof(buf), path);
    for (const auto& b : kButtons)
        if (_stricmp(buf, b.name) == 0)
            return b.mask;
    return def;
}

static void LoadSettings(const char* path)
{
    Settings defaults;
    g_cfg.virtualController = GetPrivateProfileIntA("Controller", "VirtualController", 1, path) != 0;
    g_cfg.rumble = GetPrivateProfileIntA("Rumble", "Enabled", 1, path) != 0;
    g_cfg.strength = IniFloat(path, "Rumble", "Strength", defaults.strength);
    g_cfg.minLevel = IniFloat(path, "Rumble", "MinLevel", defaults.minLevel);
    g_cfg.curve = IniFloat(path, "Rumble", "Curve", defaults.curve);
    g_cfg.blend = IniFloat(path, "Rumble", "Blend", defaults.blend);
    g_cfg.periodSplitMs = GetPrivateProfileIntA("Rumble", "PeriodSplitMs", defaults.periodSplitMs, path);
    g_cfg.impactMaxMs = GetPrivateProfileIntA("Rumble", "ImpactMaxMs", defaults.impactMaxMs, path);
    for (int i = 0; i < EvCount; ++i)
    {
        char section[32];
        snprintf(section, sizeof(section), "Rumble.%s", kEventNames[i]);
        g_cfg.events[i].scale = IniFloat(path, section, "Scale", defaults.events[i].scale);
        g_cfg.events[i].motors = IniMotors(path, section, defaults.events[i].motors);
        g_cfg.events[i].length = IniFloat(path, section, "Length", defaults.events[i].length);
    }
    g_cfg.shiftScale = IniFloat(path, "Rumble.Shift", "Scale", defaults.shiftScale);
    g_cfg.shiftMotors = IniMotors(path, "Rumble.Shift", defaults.shiftMotors);
    g_cfg.shiftMs = GetPrivateProfileIntA("Rumble.Shift", "LengthMs", defaults.shiftMs, path);
    g_cfg.nitrousScale = IniFloat(path, "Rumble.Nitrous", "Scale", defaults.nitrousScale);
    g_cfg.nitrousMotors = IniMotors(path, "Rumble.Nitrous", defaults.nitrousMotors);
    g_cfg.nitrousButton = IniButton(path, "Rumble.Nitrous", defaults.nitrousButton);
    g_cfg.triggerDeadzone = IniFloat(path, "Triggers", "Deadzone", defaults.triggerDeadzone);
    g_cfg.triggerFullAt = IniFloat(path, "Triggers", "FullAt", defaults.triggerFullAt);
    // "Curve" sets both; RTCurve / LTCurve override it per trigger.
    float both = IniFloat(path, "Triggers", "Curve", -1.0f);
    g_cfg.rtCurve = IniFloat(path, "Triggers", "RTCurve", both > 0 ? both : defaults.rtCurve);
    g_cfg.ltCurve = IniFloat(path, "Triggers", "LTCurve", both > 0 ? both : defaults.ltCurve);
    g_cfg.stickDeadzone = IniFloat(path, "Steering", "Deadzone", defaults.stickDeadzone);
    g_cfg.stickOuter = IniFloat(path, "Steering", "OuterDeadzone", defaults.stickOuter);
    g_cfg.stickCurve = IniFloat(path, "Steering", "Curve", defaults.stickCurve);
    g_cfg.stickAntiDeadzone = IniFloat(path, "Steering", "AntiDeadzone", defaults.stickAntiDeadzone);
    g_cfg.debugFakePad = GetPrivateProfileIntA("Debug", "FakePad", 0, path) != 0;
    g_cfg.nextSongButton = (int)GetPrivateProfileIntA("Music", "NextSongButton", defaults.nextSongButton, path);
    g_cfg.telemetryLog = GetPrivateProfileIntA("Telemetry", "Log", 1, path) != 0;
    g_cfg.overlay = GetPrivateProfileIntA("Telemetry", "Overlay", 1, path) != 0;
    g_cfg.overlayOnlyInFront = GetPrivateProfileIntA("Telemetry", "OverlayOnlyInFront", 1, path) != 0;
    g_cfg.overlayX = GetPrivateProfileIntA("Telemetry", "OverlayX", defaults.overlayX, path);
    g_cfg.overlayBottom = GetPrivateProfileIntA("Telemetry", "OverlayBottom", defaults.overlayBottom, path);
    g_cfg.overlayOpacity = IniFloat(path, "Telemetry", "OverlayOpacity", defaults.overlayOpacity);
    g_cfg.overlayBackground = IniFloat(path, "Telemetry", "OverlayBackground", defaults.overlayBackground);
    g_cfg.telemetryKeep = GetPrivateProfileIntA("Telemetry", "KeepLast", defaults.telemetryKeep, path);
    GetPrivateProfileStringA("Telemetry", "Dir", defaults.telemetryDir, g_cfg.telemetryDir, MAX_PATH, path);
    g_cfg.logState = GetPrivateProfileIntA("Log", "StateChanges", 1, path) != 0;
    g_cfg.defaultLayout = GetPrivateProfileIntA("Controls", "DefaultLayout", 0, path) != 0;
}

// ---------------------------------------------------------------------------------------------
// Logging

static FILE* g_log;
static CRITICAL_SECTION g_logLock;
static DWORD g_startTick;

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

static const char* HrName(HRESULT hr)
{
    static char buf[16];
    switch ((DWORD)hr)
    {
    case (DWORD)DI_OK: return "DI_OK";
    case (DWORD)S_FALSE: return "S_FALSE";
    case (DWORD)DIERR_INPUTLOST: return "DIERR_INPUTLOST";
    case (DWORD)DIERR_NOTACQUIRED: return "DIERR_NOTACQUIRED";
    case (DWORD)DIERR_INVALIDPARAM: return "DIERR_INVALIDPARAM";
    case (DWORD)DIERR_UNSUPPORTED: return "DIERR_UNSUPPORTED";
    case (DWORD)DIERR_NOTFOUND: return "DIERR_NOTFOUND";
    case (DWORD)DIERR_OTHERAPPHASPRIO: return "DIERR_OTHERAPPHASPRIO";
    case (DWORD)DIERR_DEVICENOTREG: return "DIERR_DEVICENOTREG";
    case (DWORD)DIERR_NOTEXCLUSIVEACQUIRED: return "DIERR_NOTEXCLUSIVEACQUIRED";
    case (DWORD)E_NOINTERFACE: return "E_NOINTERFACE";
    }
    snprintf(buf, sizeof(buf), "0x%08lX", (unsigned long)hr);
    return buf;
}

struct GuidName { const GUID* guid; const char* name; };
static const GuidName kGuidNames[] = {
    { &GUID_XAxis, "XAxis" }, { &GUID_YAxis, "YAxis" }, { &GUID_ZAxis, "ZAxis" },
    { &GUID_RxAxis, "RxAxis" }, { &GUID_RyAxis, "RyAxis" }, { &GUID_RzAxis, "RzAxis" },
    { &GUID_Slider, "Slider" }, { &GUID_Button, "Button" }, { &GUID_Key, "Key" },
    { &GUID_POV, "POV" }, { &GUID_Unknown, "Unknown" },
    { &GUID_SysKeyboard, "SysKeyboard" }, { &GUID_SysMouse, "SysMouse" },
    { &GUID_ConstantForce, "ConstantForce" }, { &GUID_RampForce, "RampForce" },
    { &GUID_Square, "Square" }, { &GUID_Sine, "Sine" }, { &GUID_Triangle, "Triangle" },
    { &GUID_SawtoothUp, "SawtoothUp" }, { &GUID_SawtoothDown, "SawtoothDown" },
    { &GUID_Spring, "Spring" }, { &GUID_Damper, "Damper" }, { &GUID_Inertia, "Inertia" },
    { &GUID_Friction, "Friction" }, { &GUID_CustomForce, "CustomForce" },
    { &IID_IDirectInput8A, "IID_IDirectInput8A" }, { &IID_IDirectInput8W, "IID_IDirectInput8W" },
    { &IID_IDirectInputDevice8A, "IID_IDirectInputDevice8A" },
    { &IID_IDirectInputDevice8W, "IID_IDirectInputDevice8W" },
    { &IID_IDirectInputEffect, "IID_IDirectInputEffect" },
};

// Returns a readable name for a GUID. Uses a small ring of buffers so several can appear in one Log call.
static const char* GuidStr(const GUID* g)
{
    if (!g)
        return "null";
    for (const GuidName& n : kGuidNames)
        if (IsEqualGUID(*g, *n.guid))
            return n.name;
    static char ring[4][40];
    static int next;
    char* buf = ring[next++ & 3];
    snprintf(buf, 40, "{%08lX-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}", (unsigned long)g->Data1,
        g->Data2, g->Data3, g->Data4[0], g->Data4[1], g->Data4[2], g->Data4[3], g->Data4[4],
        g->Data4[5], g->Data4[6], g->Data4[7]);
    return buf;
}

// DIPROP_* values are small integers cast to GUID pointers, not real GUIDs.
static UINT_PTR PropId(REFGUID prop) { return (UINT_PTR)&prop; }
static const UINT_PTR kPropRange = 4, kPropDeadzone = 5, kPropSaturation = 6, kPropFFGain = 7, kPropAutocenter = 9;

static const char* PropName(REFGUID prop)
{
    static const char* names[] = { "?", "BUFFERSIZE", "AXISMODE", "GRANULARITY", "RANGE", "DEADZONE",
        "SATURATION", "FFGAIN", "FFLOAD", "AUTOCENTER", "CALIBRATIONMODE" };
    static char buf[16];
    UINT_PTR id = PropId(prop);
    if (id > 0 && id < sizeof(names) / sizeof(names[0]))
        return names[id];
    snprintf(buf, sizeof(buf), "prop#%u", (unsigned)id);
    return buf;
}

static const char* HowStr(const DIPROPHEADER* h)
{
    static char buf[48];
    const char* how = h->dwHow == DIPH_DEVICE ? "device" : h->dwHow == DIPH_BYOFFSET ? "offset"
        : h->dwHow == DIPH_BYID ? "id" : h->dwHow == DIPH_BYUSAGE ? "usage" : "?";
    snprintf(buf, sizeof(buf), "%s %lu", how, (unsigned long)h->dwObj);
    return buf;
}

static void LogEffect(const char* what, const GUID* type, const DIEFFECT* e, DWORD flags)
{
    if (!e)
    {
        Log("  %s type=%s (no params) flags=0x%lX", what, GuidStr(type), (unsigned long)flags);
        return;
    }
    Log("  %s type=%s flags=0x%lX duration=%lu gain=%lu trigger=%ld axes=%lu dirs=[%ld,%ld] envelope=%s typeSpecificSize=%lu",
        what, GuidStr(type), (unsigned long)flags, (unsigned long)e->dwDuration, (unsigned long)e->dwGain,
        (long)e->dwTriggerButton, (unsigned long)e->cAxes,
        e->rglDirection && e->cAxes > 0 ? e->rglDirection[0] : 0,
        e->rglDirection && e->cAxes > 1 ? e->rglDirection[1] : 0,
        e->lpEnvelope ? "yes" : "no", (unsigned long)e->cbTypeSpecificParams);
    if (e->lpEnvelope)
        Log("    envelope attack=%lu/%luus fade=%lu/%luus", (unsigned long)e->lpEnvelope->dwAttackLevel,
            (unsigned long)e->lpEnvelope->dwAttackTime, (unsigned long)e->lpEnvelope->dwFadeLevel,
            (unsigned long)e->lpEnvelope->dwFadeTime);
    if (!e->lpvTypeSpecificParams)
        return;
    if (e->cbTypeSpecificParams == sizeof(DICONSTANTFORCE))
        Log("    constant magnitude=%ld", ((DICONSTANTFORCE*)e->lpvTypeSpecificParams)->lMagnitude);
    else if (e->cbTypeSpecificParams == sizeof(DIRAMPFORCE))
        Log("    ramp start=%ld end=%ld", ((DIRAMPFORCE*)e->lpvTypeSpecificParams)->lStart,
            ((DIRAMPFORCE*)e->lpvTypeSpecificParams)->lEnd);
    else if (e->cbTypeSpecificParams == sizeof(DIPERIODIC))
    {
        DIPERIODIC* p = (DIPERIODIC*)e->lpvTypeSpecificParams;
        Log("    periodic magnitude=%lu offset=%ld phase=%lu period=%luus", (unsigned long)p->dwMagnitude,
            p->lOffset, (unsigned long)p->dwPhase, (unsigned long)p->dwPeriod);
    }
    else if (e->cbTypeSpecificParams >= sizeof(DICONDITION))
    {
        DICONDITION* c = (DICONDITION*)e->lpvTypeSpecificParams;
        Log("    condition offset=%ld posCoeff=%ld negCoeff=%ld posSat=%lu negSat=%lu deadband=%ld",
            c->lOffset, c->lPositiveCoefficient, c->lNegativeCoefficient,
            (unsigned long)c->dwPositiveSaturation, (unsigned long)c->dwNegativeSaturation, c->lDeadBand);
    }
}

// Per-device read statistics, logged every 5 seconds by the rumble thread (index = device id).
static const int kMaxDevices = 16;
static volatile LONG g_reads[kMaxDevices], g_lastZ[kMaxDevices], g_lastRx[kMaxDevices];

static void LogReadStats()
{
    char line[256];
    size_t len = snprintf(line, sizeof(line), "Reads in last 5s:");
    for (int i = 1; i < kMaxDevices; ++i)
    {
        LONG n = InterlockedExchange(&g_reads[i], 0);
        if (n)
            len += snprintf(line + len, sizeof(line) - len, " dev%d=%ld (Z=%ld Rx=%ld)", i, n, g_lastZ[i], g_lastRx[i]);
    }
    Log("%s", line);
}

// ---------------------------------------------------------------------------------------------
// XInput

static volatile LONG g_padIndex = -1; // XInput slot of the active controller, -1 if none
// The last controller state the game was given, for the rumble thread. Reading XInput again from that
// thread gave button states that flickered on and off every ~30 ms, while the game's reads were steady.
static volatile LONG g_padButtons, g_padRY;
static volatile LONG g_padLT, g_padRT, g_padLX; // raw trigger 0..255 and left stick X, for telemetry
static volatile LONG g_inRace;                  // set by the rumble thread from the game's damper
// Nitrous from telemetry: whether the tank level can be read, and when it last fell (= nitrous firing).
static volatile LONG g_nitrousKnown, g_nitrousDrainTick;

// Left stick through [Steering], radially so diagonals aren't sticky: below Deadzone -> 0, the rest
// rescaled so full lock is at OuterDeadzone, then Curve (>1 gentler near the centre), then lifted by
// AntiDeadzone (to cancel a deadzone inside the game). In and out are -1..1, Y up positive.
static void ShapeStick(float x, float y, float* outX, float* outY)
{
    float m = sqrtf(x * x + y * y);
    float dz = g_cfg.stickDeadzone, outer = std::max(g_cfg.stickOuter, dz + 0.01f);
    if (m <= dz)
    {
        *outX = *outY = 0;
        return;
    }
    float v = std::min((m - dz) / (outer - dz), 1.0f);
    if (g_cfg.stickCurve > 0)
        v = powf(v, g_cfg.stickCurve);
    v = g_cfg.stickAntiDeadzone + (1 - g_cfg.stickAntiDeadzone) * v;
    *outX = x / m * v;
    *outY = y / m * v;
}

static volatile LONG g_steerShaped; // what the game got for steering, x10000, for telemetry

// Trigger travel 0..255 -> 0..1 through [Triggers]: nothing below Deadzone, full at FullAt, the
// trigger's curve between (1 = linear, <1 more of the game's range early in the travel, >1 less).
static float ShapeTrigger(BYTE t, float curve)
{
    float dz = g_cfg.triggerDeadzone, full = std::max(g_cfg.triggerFullAt, dz + 0.01f);
    float v = std::min(std::max((t / 255.0f - dz) / (full - dz), 0.0f), 1.0f);
    if (v > 0 && curve > 0)
        v = powf(v, curve);
    return v;
}

// Reads the active controller, rescanning the four slots at most once a second when none is connected.
static bool ReadPad(XINPUT_STATE* state)
{
    LONG index = g_padIndex;
    if (index >= 0 && XInputGetState(index, state) == ERROR_SUCCESS)
        return true;
    static DWORD lastScan;
    DWORD now = GetTickCount();
    if (index >= 0 || now - lastScan >= 1000)
    {
        lastScan = now;
        for (DWORD i = 0; i < XUSER_MAX_COUNT; ++i)
            if (XInputGetState(i, state) == ERROR_SUCCESS)
            {
                if ((LONG)i != index)
                    Log("XInput controller found in slot %lu", (unsigned long)i);
                g_padIndex = (LONG)i;
                return true;
            }
        if (index >= 0)
            Log("XInput controller disconnected");
        g_padIndex = -1;
    }
    return false;
}

// ---------------------------------------------------------------------------------------------
// Force feedback simulation

enum EffectCategory { CatConstant, CatRamp, CatPeriodic, CatCondition, CatOther };

static EffectCategory CategoryOf(const GUID& g)
{
    if (IsEqualGUID(g, GUID_ConstantForce)) return CatConstant;
    if (IsEqualGUID(g, GUID_RampForce)) return CatRamp;
    if (IsEqualGUID(g, GUID_Square) || IsEqualGUID(g, GUID_Sine) || IsEqualGUID(g, GUID_Triangle)
        || IsEqualGUID(g, GUID_SawtoothUp) || IsEqualGUID(g, GUID_SawtoothDown)) return CatPeriodic;
    if (IsEqualGUID(g, GUID_Spring) || IsEqualGUID(g, GUID_Damper) || IsEqualGUID(g, GUID_Inertia)
        || IsEqualGUID(g, GUID_Friction)) return CatCondition;
    return CatOther;
}

// Device-wide force feedback state. The game uses a single controller, so one global is enough.
struct FFState
{
    bool actuatorsOn = true;
    bool paused = false;
    DWORD gain = DI_FFNOMINALMAX;
    HWND window = nullptr;
};
static FFState g_ff;
static CRITICAL_SECTION g_ffLock;

class VirtualEffect;
static std::vector<VirtualEffect*> g_effects; // all live effects, guarded by g_ffLock

class VirtualEffect : public IDirectInputEffect
{
public:
    VirtualEffect(const GUID& type, void* owner, int id)
        : m_type(type), m_cat(CategoryOf(type)), m_isDamper(IsEqualGUID(type, GUID_Damper) != 0), m_owner(owner), m_id(id)
    {
        EnterCriticalSection(&g_ffLock);
        g_effects.push_back(this);
        LeaveCriticalSection(&g_ffLock);
    }

    // IUnknown
    STDMETHOD(QueryInterface)(REFIID riid, void** out)
    {
        if (IsEqualGUID(riid, IID_IDirectInputEffect) || IsEqualGUID(riid, IID_IUnknown))
        {
            AddRef();
            *out = this;
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHOD_(ULONG, AddRef)() { return InterlockedIncrement(&m_refs); }
    STDMETHOD_(ULONG, Release)()
    {
        LONG n = InterlockedDecrement(&m_refs);
        if (n == 0)
        {
            EnterCriticalSection(&g_ffLock);
            g_effects.erase(std::remove(g_effects.begin(), g_effects.end(), this), g_effects.end());
            LeaveCriticalSection(&g_ffLock);
            Log("Effect#%d released (starts=%d setParams=%d)", m_id, m_starts, m_sets);
            delete this;
        }
        return n;
    }

    // IDirectInputEffect
    STDMETHOD(Initialize)(HINSTANCE, DWORD, REFGUID) { return DI_OK; }
    STDMETHOD(GetEffectGuid)(LPGUID g)
    {
        *g = m_type;
        return DI_OK;
    }
    STDMETHOD(GetParameters)(LPDIEFFECT e, DWORD flags)
    {
        EnterCriticalSection(&g_ffLock);
        if (flags & DIEP_DURATION) e->dwDuration = m_duration;
        if (flags & DIEP_GAIN) e->dwGain = m_gain;
        if (flags & DIEP_STARTDELAY && e->dwSize >= sizeof(DIEFFECT)) e->dwStartDelay = m_startDelay;
        if (flags & DIEP_TRIGGERBUTTON) e->dwTriggerButton = DIEB_NOTRIGGER;
        if (flags & DIEP_ENVELOPE && e->lpEnvelope)
        {
            if (m_hasEnvelope) *e->lpEnvelope = m_envelope;
            else e->lpEnvelope = nullptr;
        }
        if (flags & DIEP_TYPESPECIFICPARAMS && e->lpvTypeSpecificParams)
            memcpy(e->lpvTypeSpecificParams, &m_params, std::min<DWORD>(e->cbTypeSpecificParams, m_paramsSize));
        LeaveCriticalSection(&g_ffLock);
        return DI_OK;
    }
    STDMETHOD(SetParameters)(LPCDIEFFECT e, DWORD flags)
    {
        if (++m_sets <= 5 || m_sets % 200 == 0)
        {
            Log("Effect#%d SetParameters #%d", m_id, m_sets);
            LogEffect("params", &m_type, e, flags);
        }
        Apply(e, flags);
        if (flags & DIEP_START)
            Start(1, 0);
        return DI_OK;
    }
    STDMETHOD(Start)(DWORD iterations, DWORD flags)
    {
        if (++m_starts <= 5 || m_starts % 200 == 0)
            Log("Effect#%d Start #%d (%s) iterations=%lu flags=0x%lX", m_id, m_starts, kEventNames[EventOf()],
                (unsigned long)iterations, (unsigned long)flags);
        if (flags & DIES_SOLO)
            StopAllFor(m_owner);
        EnterCriticalSection(&g_ffLock);
        m_playing = true;
        m_iterations = iterations;
        m_startTick = GetTickCount();
        LeaveCriticalSection(&g_ffLock);
        return DI_OK;
    }
    STDMETHOD(Stop)()
    {
        m_playing = false;
        return DI_OK;
    }
    STDMETHOD(GetEffectStatus)(LPDWORD status)
    {
        EnterCriticalSection(&g_ffLock);
        *status = LevelNow() >= 0 ? DIEGES_PLAYING : 0;
        LeaveCriticalSection(&g_ffLock);
        return DI_OK;
    }
    STDMETHOD(Download)() { return DI_OK; }
    STDMETHOD(Unload)()
    {
        m_playing = false;
        return DI_OK;
    }
    STDMETHOD(Escape)(LPDIEFFESCAPE) { return DIERR_UNSUPPORTED; }

    void Apply(LPCDIEFFECT e, DWORD flags)
    {
        if (!e)
            return;
        EnterCriticalSection(&g_ffLock);
        if (flags & DIEP_DURATION) m_duration = e->dwDuration;
        if (flags & DIEP_GAIN) m_gain = e->dwGain;
        if (flags & DIEP_STARTDELAY && e->dwSize >= sizeof(DIEFFECT)) m_startDelay = e->dwStartDelay;
        if (flags & DIEP_ENVELOPE)
        {
            m_hasEnvelope = e->lpEnvelope != nullptr;
            if (m_hasEnvelope) m_envelope = *e->lpEnvelope;
        }
        if (flags & DIEP_TYPESPECIFICPARAMS && e->lpvTypeSpecificParams)
        {
            m_paramsSize = std::min<DWORD>(e->cbTypeSpecificParams, sizeof(m_params));
            memcpy(&m_params, e->lpvTypeSpecificParams, m_paramsSize);
        }
        LeaveCriticalSection(&g_ffLock);
    }

    // Which tuning group this effect belongs to, from its shape.
    RumbleEvent EventOf() const
    {
        if (m_cat == CatCondition)
            return EvSteering;
        if (m_duration != INFINITE && m_duration / 1000 <= g_cfg.impactMaxMs)
            return EvImpact;
        if (m_cat == CatPeriodic)
            return m_params.periodic.dwPeriod / 1000 < g_cfg.periodSplitMs ? EvSurface : EvHeavySurface;
        return EvConstant;
    }

    // Current level (the game's magnitude times its gain, 0..1, times the event's Scale) and the
    // motors it drives. Returns a negative level when the effect is not playing. Caller holds g_ffLock.
    float LevelNow(int* motors = nullptr)
    {
        if (!m_playing)
            return -1;
        const EventSettings& ev = g_cfg.events[EventOf()];
        double length = m_duration == INFINITE ? 1.0 : std::max(ev.length, 0.05f);
        double t = (double)(GetTickCount() - m_startTick) - m_startDelay / 1000.0; // ms into playback
        if (t < 0)
            return 0;
        double durMs = m_duration == INFINITE ? INFINITY : m_duration / 1000.0 * length;
        double totalMs = m_iterations == INFINITE ? INFINITY : durMs * m_iterations;
        if (t > totalMs)
        {
            m_playing = false;
            return -1;
        }
        double tIt = isinf(durMs) || durMs <= 0 ? t : fmod(t, durMs);

        double base = 0;
        switch (m_cat)
        {
        case CatConstant:
            base = labs(m_params.constant.lMagnitude);
            break;
        case CatRamp:
        {
            double f = isinf(durMs) || durMs <= 0 ? 0 : tIt / durMs;
            base = fabs(m_params.ramp.lStart + (m_params.ramp.lEnd - m_params.ramp.lStart) * f);
            break;
        }
        case CatPeriodic:
            base = m_params.periodic.dwMagnitude + labs(m_params.periodic.lOffset);
            break;
        case CatCondition:
            base = std::max(labs(m_params.condition.lPositiveCoefficient), labs(m_params.condition.lNegativeCoefficient));
            break;
        default:
            return 0;
        }

        if (m_hasEnvelope && m_cat != CatCondition)
        {
            double attackMs = m_envelope.dwAttackTime / 1000.0 * length, fadeMs = m_envelope.dwFadeTime / 1000.0 * length;
            if (attackMs > 0 && tIt < attackMs)
                base = m_envelope.dwAttackLevel + (base - m_envelope.dwAttackLevel) * (tIt / attackMs);
            else if (!isinf(durMs) && fadeMs > 0 && tIt > durMs - fadeMs)
                base = base + (m_envelope.dwFadeLevel - base) * ((tIt - (durMs - fadeMs)) / fadeMs);
        }
        if (motors)
            *motors = ev.motors;
        return (float)(std::min(base, 10000.0) / 10000.0 * (m_gain / 10000.0) * ev.scale);
    }

    void* Owner() const { return m_owner; }

    // The game plays a damper (steering weight) only while a race is running, and stops it when
    // paused or back in the menus. Caller holds g_ffLock.
    bool IsRaceSignal() { return m_isDamper && LevelNow() >= 0; }

    static void StopAllFor(void* owner)
    {
        EnterCriticalSection(&g_ffLock);
        for (VirtualEffect* e : g_effects)
            if (e->m_owner == owner)
                e->m_playing = false;
        LeaveCriticalSection(&g_ffLock);
    }

private:
    LONG m_refs = 1;
    GUID m_type;
    EffectCategory m_cat;
    bool m_isDamper;
    void* m_owner;
    int m_id;
    int m_starts = 0, m_sets = 0;
    volatile bool m_playing = false;
    DWORD m_iterations = 1, m_startTick = 0;
    DWORD m_duration = INFINITE, m_gain = DI_FFNOMINALMAX, m_startDelay = 0;
    bool m_hasEnvelope = false;
    DIENVELOPE m_envelope = {};
    union
    {
        DICONSTANTFORCE constant;
        DIRAMPFORCE ramp;
        DIPERIODIC periodic;
        DICONDITION condition;
    } m_params = {};
    DWORD m_paramsSize = 0;
};

// Maps one effect's level to motor power: clamp to 1, apply the response curve (below 1 lifts weak
// effects more than strong ones), and raise anything felt to at least MinLevel, because the
// motors barely spin below ~15%.
static float Shape(float level)
{
    if (level <= 0.001f)
        return 0;
    level = powf(std::min(level, 1.0f), g_cfg.curve);
    return std::max(level, g_cfg.minLevel);
}

// One motor's mix: the strongest effect plus Blend x the others, so a second effect is felt as a
// step up without everything stacking to 100%.
struct MotorMix
{
    float strongest = 0, total = 0;
    void Add(float shaped)
    {
        strongest = std::max(strongest, shaped);
        total += shaped;
    }
    float Result() const { return std::min(strongest + g_cfg.blend * (total - strongest), 1.0f); }
};

// Reloads the .ini when it changes, so rumble can be tuned while the game runs.
static void ReloadSettingsIfChanged()
{
    static FILETIME last;
    WIN32_FILE_ATTRIBUTE_DATA info;
    if (!GetFileAttributesExA(g_iniPath, GetFileExInfoStandard, &info))
        return;
    if (last.dwLowDateTime == 0 && last.dwHighDateTime == 0)
    {
        last = info.ftLastWriteTime;
        return;
    }
    if (CompareFileTime(&info.ftLastWriteTime, &last) == 0)
        return;
    last = info.ftLastWriteTime;
    LoadSettings(g_iniPath);
    Log("Settings reloaded: strength=%.2f minLevel=%.2f curve=%.2f blend=%.2f impact=%.2f surface=%.2f heavySurface=%.2f constant=%.2f steering=%.2f shift=%.2f nitrous=%.2f",
        g_cfg.strength, g_cfg.minLevel, g_cfg.curve, g_cfg.blend, g_cfg.events[EvImpact].scale, g_cfg.events[EvSurface].scale,
        g_cfg.events[EvHeavySurface].scale, g_cfg.events[EvConstant].scale, g_cfg.events[EvSteering].scale,
        g_cfg.shiftScale, g_cfg.nitrousScale);
    Log("  triggers: deadzone=%.2f fullAt=%.2f rtCurve=%.2f ltCurve=%.2f", g_cfg.triggerDeadzone, g_cfg.triggerFullAt,
        g_cfg.rtCurve, g_cfg.ltCurve);
    Log("  steering: deadzone=%.2f outer=%.2f curve=%.2f antiDeadzone=%.2f", g_cfg.stickDeadzone, g_cfg.stickOuter,
        g_cfg.stickCurve, g_cfg.stickAntiDeadzone);
    Log("  music: nextSongButton=%d", g_cfg.nextSongButton);
}

// Vibrations InputBridge adds itself: a short kick when the right stick is flicked to shift, and a
// buzz while the nitrous button is held. Only during a race (the game's damper is playing), since
// the same inputs navigate menus. `gain` is the master strength.
static void AddSyntheticRumble(bool inRace, float gain, MotorMix& left, MotorMix& right)
{
    static int zone;              // right stick: -1 down, 0 centre, +1 up
    static DWORD shiftUntil;
    static bool wasInRace, nitrousOn;
    if (inRace != wasInRace)
    {
        Log("Race %s (game damper %s)", inRace ? "started" : "ended/paused", inRace ? "playing" : "stopped");
        wasInRace = inRace;
    }

    if (g_padIndex < 0)
        return;
    DWORD now = GetTickCount();

    // Flick past 75% to shift; back under 40% to re-arm.
    LONG ry = g_padRY;
    int newZone = ry > 24500 ? 1 : ry < -24500 ? -1 : (ry > -13000 && ry < 13000) ? 0 : zone;
    if (newZone != 0 && zone == 0 && inRace && g_cfg.shiftScale > 0)
    {
        shiftUntil = now + g_cfg.shiftMs;
        Log("Synthetic: shift kick (%s)", newZone > 0 ? "up" : "down");
    }
    zone = newZone;
    if ((LONG)(shiftUntil - now) > 0)
    {
        if (g_cfg.shiftMotors & MotorLeft) left.Add(Shape(g_cfg.shiftScale * gain));
        if (g_cfg.shiftMotors & MotorRight) right.Add(Shape(g_cfg.shiftScale * gain));
    }

    // Buzz while nitrous is actually firing: the tank level fell within the last 100 ms (read from game
    // memory by the telemetry thread), so an empty tank or a press the game ignores stays silent.
    // If the level can't be read, fall back to the button, with 60 ms of grace after release.
    static DWORD nitrousHeldAt;
    if (inRace && (g_padButtons & g_cfg.nitrousButton))
        nitrousHeldAt = now;
    bool firing = g_nitrousKnown ? (g_nitrousDrainTick && now - (DWORD)g_nitrousDrainTick < 100)
                                 : (nitrousHeldAt && now - nitrousHeldAt < 60);
    bool nitrous = inRace && g_cfg.nitrousScale > 0 && firing;
    if (nitrous != nitrousOn)
    {
        Log("Synthetic: nitrous buzz %s", nitrous ? "on" : "off");
        nitrousOn = nitrous;
    }
    if (nitrous)
    {
        if (g_cfg.nitrousMotors & MotorLeft) left.Add(Shape(g_cfg.nitrousScale * gain));
        if (g_cfg.nitrousMotors & MotorRight) right.Add(Shape(g_cfg.nitrousScale * gain));
    }
}

// Mixes all playing effects into motor speeds ~100 times a second and sends them to the controller.
static DWORD WINAPI RumbleThread(LPVOID)
{
    WORD lastLeft = 0, lastRight = 0;
    DWORD lastSend = 0, lastLog = 0, lastStats = GetTickCount();
    for (;;)
    {
        Sleep(10);
        if (GetTickCount() - lastStats >= 5000)
        {
            LogReadStats();
            lastStats = GetTickCount();
        }
        static DWORD lastReloadCheck;
        if (GetTickCount() - lastReloadCheck >= 1000)
        {
            ReloadSettingsIfChanged();
            lastReloadCheck = GetTickCount();
        }
        MotorMix leftMix, rightMix;
        EnterCriticalSection(&g_ffLock);
        bool active = g_cfg.rumble && g_ff.actuatorsOn && !g_ff.paused;
        float gain = g_ff.gain / 10000.0f * g_cfg.strength;
        HWND wnd = g_ff.window;
        bool inRace = false;
        for (VirtualEffect* e : g_effects)
            inRace = inRace || e->IsRaceSignal();
        g_inRace = inRace && !g_ff.paused;
        if (active)
            for (VirtualEffect* e : g_effects)
            {
                int motors = 0;
                float level = e->LevelNow(&motors);
                if (level <= 0)
                    continue;
                float shaped = Shape(level * gain);
                if (motors & MotorLeft) leftMix.Add(shaped);
                if (motors & MotorRight) rightMix.Add(shaped);
            }
        LeaveCriticalSection(&g_ffLock);
        if (active)
            AddSyntheticRumble(inRace && !g_ff.paused, gain, leftMix, rightMix);
        float left = leftMix.Result(), right = rightMix.Result();

        // DirectInput stops force feedback when the game loses focus; do the same.
        if (wnd && GetAncestor(GetForegroundWindow(), GA_ROOT) != GetAncestor(wnd, GA_ROOT))
            left = right = 0;

        XINPUT_VIBRATION vib;
        vib.wLeftMotorSpeed = (WORD)(left * 65535);
        vib.wRightMotorSpeed = (WORD)(right * 65535);
        LONG index = g_padIndex;
        DWORD now = GetTickCount();
        if (index >= 0 && (vib.wLeftMotorSpeed != lastLeft || vib.wRightMotorSpeed != lastRight || now - lastSend > 1000))
        {
            XInputSetState(index, &vib);
            lastSend = now;
            if ((abs(vib.wLeftMotorSpeed - lastLeft) > 3000 || abs(vib.wRightMotorSpeed - lastRight) > 3000)
                && now - lastLog > 200)
            {
                Log("Rumble left=%u right=%u", vib.wLeftMotorSpeed, vib.wRightMotorSpeed);
                lastLog = now;
            }
            lastLeft = vib.wLeftMotorSpeed;
            lastRight = vib.wRightMotorSpeed;
        }
    }
}

static void StartTelemetry();

static void EnsureRumbleThread()
{
    static LONG started;
    if (InterlockedExchange(&started, 1) == 0)
    {
        HANDLE t = CreateThread(nullptr, 0, RumbleThread, nullptr, 0, nullptr);
        if (t)
            CloseHandle(t);
        Log("Rumble thread started");
        StartTelemetry();
    }
}

// ---------------------------------------------------------------------------------------------
// Pass-through effect proxy (for force-feedback devices we don't virtualize, e.g. a real wheel)

class EffectProxy : public IDirectInputEffect
{
public:
    EffectProxy(IDirectInputEffect* real, const GUID& type, int id) : m_real(real), m_type(type), m_id(id) {}

    STDMETHOD(QueryInterface)(REFIID riid, void** out) { return m_real->QueryInterface(riid, out); }
    STDMETHOD_(ULONG, AddRef)() { return m_real->AddRef(); }
    STDMETHOD_(ULONG, Release)()
    {
        ULONG n = m_real->Release();
        if (n == 0)
            delete this;
        return n;
    }
    STDMETHOD(Initialize)(HINSTANCE a, DWORD b, REFGUID c) { return m_real->Initialize(a, b, c); }
    STDMETHOD(GetEffectGuid)(LPGUID g) { return m_real->GetEffectGuid(g); }
    STDMETHOD(GetParameters)(LPDIEFFECT e, DWORD f) { return m_real->GetParameters(e, f); }
    STDMETHOD(SetParameters)(LPCDIEFFECT e, DWORD f)
    {
        HRESULT hr = m_real->SetParameters(e, f);
        if (++m_sets <= 5 || m_sets % 200 == 0)
        {
            Log("Effect#%d SetParameters #%d -> %s", m_id, m_sets, HrName(hr));
            LogEffect("params", &m_type, e, f);
        }
        return hr;
    }
    STDMETHOD(Start)(DWORD iterations, DWORD flags) { return m_real->Start(iterations, flags); }
    STDMETHOD(Stop)() { return m_real->Stop(); }
    STDMETHOD(GetEffectStatus)(LPDWORD s) { return m_real->GetEffectStatus(s); }
    STDMETHOD(Download)() { return m_real->Download(); }
    STDMETHOD(Unload)() { return m_real->Unload(); }
    STDMETHOD(Escape)(LPDIEFFESCAPE e) { return m_real->Escape(e); }

private:
    IDirectInputEffect* m_real;
    GUID m_type;
    int m_id;
    int m_sets = 0;
};

// ---------------------------------------------------------------------------------------------
// Device proxy

enum DeviceKind { KindUnknown, KindKeyboard, KindMouse, KindJoystick };
enum Axis { AxX, AxY, AxZ, AxRx, AxRy, AxRz, AxCount };
static const char* kAxisNames[AxCount] = { "X", "Y", "Z", "Rx", "Ry", "Rz" };

static int s_deviceCount, s_effectCount;

static bool ContainsNoCase(const char* s, const char* sub)
{
    for (; *s; ++s)
        if (_strnicmp(s, sub, strlen(sub)) == 0)
            return true;
    return false;
}

class DeviceProxy : public IDirectInputDevice8A
{
public:
    DeviceProxy(IDirectInputDevice8A* real, const GUID& instance) : m_real(real), m_id(++s_deviceCount)
    {
        for (int i = 0; i < AxCount; ++i)
        {
            m_min[i] = 0;
            m_max[i] = 65535;
        }
        DIDEVICEINSTANCEA info = { sizeof(info) };
        if (SUCCEEDED(real->GetDeviceInfo(&info)))
        {
            BYTE type = GET_DIDEVICE_TYPE(info.dwDevType);
            m_kind = type == DI8DEVTYPE_KEYBOARD ? KindKeyboard : type == DI8DEVTYPE_MOUSE ? KindMouse : KindJoystick;
            m_virtual = m_kind == KindJoystick && g_cfg.virtualController && ContainsNoCase(info.tszProductName, "XBOX");
            Log("Device#%d created: \"%s\" instance=%s%s", m_id, info.tszProductName, GuidStr(&instance),
                m_virtual ? " -> VIRTUAL (XInput-backed, separate triggers, force feedback)" : "");
        }
    }

    // IUnknown
    STDMETHOD(QueryInterface)(REFIID riid, void** out)
    {
        if (IsEqualGUID(riid, IID_IDirectInputDevice8A) || IsEqualGUID(riid, IID_IUnknown))
        {
            AddRef();
            *out = this;
            return S_OK;
        }
        HRESULT hr = m_real->QueryInterface(riid, out);
        Log("Device#%d QueryInterface(%s) -> %s (unwrapped)", m_id, GuidStr(&riid), HrName(hr));
        return hr;
    }
    STDMETHOD_(ULONG, AddRef)() { return m_real->AddRef(); }
    STDMETHOD_(ULONG, Release)()
    {
        ULONG n = m_real->Release();
        if (n == 0)
        {
            Log("Device#%d released (GetDeviceState=%lu)", m_id, m_stateCalls);
            if (m_virtual)
                VirtualEffect::StopAllFor(this);
            delete this;
        }
        return n;
    }

    // IDirectInputDevice8A
    STDMETHOD(GetCapabilities)(LPDIDEVCAPS caps)
    {
        HRESULT hr = m_real->GetCapabilities(caps);
        if (SUCCEEDED(hr) && m_virtual)
        {
            if (caps->dwAxes < AxCount)
                caps->dwAxes = AxCount;
            caps->dwFlags |= DIDC_FORCEFEEDBACK | DIDC_FFATTACK | DIDC_FFFADE | DIDC_STARTDELAY;
            caps->dwFFSamplePeriod = 10000;
            caps->dwFFMinTimeResolution = 10000;
        }
        Log("Device#%d GetCapabilities -> %s axes=%lu flags=0x%08lX", m_id, HrName(hr),
            SUCCEEDED(hr) ? (unsigned long)caps->dwAxes : 0, SUCCEEDED(hr) ? (unsigned long)caps->dwFlags : 0);
        return hr;
    }
    STDMETHOD(EnumObjects)(LPDIENUMDEVICEOBJECTSCALLBACKA cb, LPVOID ref, DWORD flags)
    {
        Log("Device#%d EnumObjects flags=0x%08lX", m_id, (unsigned long)flags);
        if (!m_virtual)
            return m_real->EnumObjects(cb, ref, flags);

        // The real driver has no force-feedback actuators and no Rz axis; add both.
        EnumCtx ctx = { this, cb, ref, (flags & DIDFT_FFACTUATOR) != 0, false };
        HRESULT hr = m_real->EnumObjects(EnumObjectsFilter, &ctx, flags & ~(DIDFT_FFACTUATOR | DIDFT_FFEFFECTTRIGGER));
        bool wantsAxes = DIDFT_GETTYPE(flags) == 0 || (flags & DIDFT_ABSAXIS);
        if (SUCCEEDED(hr) && !ctx.stopped && wantsAxes && !ctx.actuatorsOnly)
        {
            DIDEVICEOBJECTINSTANCEA rz = { sizeof(rz) };
            FillRzObject(&rz);
            cb(&rz, ref);
        }
        return hr;
    }
    STDMETHOD(GetProperty)(REFGUID prop, LPDIPROPHEADER header)
    {
        int axis = m_virtual ? AxisOf(header) : -1;
        HRESULT hr;
        if (axis >= 0 && PropId(prop) == kPropRange && header->dwSize == sizeof(DIPROPRANGE))
        {
            ((DIPROPRANGE*)header)->lMin = m_min[axis];
            ((DIPROPRANGE*)header)->lMax = m_max[axis];
            hr = DI_OK;
        }
        else if (m_virtual && PropId(prop) == kPropFFGain && header->dwSize == sizeof(DIPROPDWORD))
        {
            ((DIPROPDWORD*)header)->dwData = g_ff.gain;
            hr = DI_OK;
        }
        else if (axis == AxRz && header->dwSize == sizeof(DIPROPDWORD))
        {
            ((DIPROPDWORD*)header)->dwData = 0;
            hr = DI_OK;
        }
        else
            hr = m_real->GetProperty(prop, header);
        LogProperty("GetProperty", prop, header, hr);
        return hr;
    }
    STDMETHOD(SetProperty)(REFGUID prop, LPCDIPROPHEADER header)
    {
        HRESULT hr;
        UINT_PTR id = PropId(prop);
        if (!m_virtual)
            hr = m_real->SetProperty(prop, header);
        else if (id == kPropRange && header->dwSize == sizeof(DIPROPRANGE))
        {
            const DIPROPRANGE* r = (const DIPROPRANGE*)header;
            int axis = AxisOf(header);
            for (int i = 0; i < AxCount; ++i)
                if (header->dwHow == DIPH_DEVICE || i == axis)
                {
                    m_min[i] = r->lMin;
                    m_max[i] = r->lMax;
                }
            // Rz is ours; the real device doesn't know it.
            hr = axis == AxRz ? DI_OK : m_real->SetProperty(prop, header);
        }
        else if (id == kPropFFGain && header->dwSize == sizeof(DIPROPDWORD))
        {
            g_ff.gain = ((const DIPROPDWORD*)header)->dwData;
            hr = DI_OK;
        }
        else if (id == kPropAutocenter)
            hr = DI_OK;
        else if ((id == kPropDeadzone || id == kPropSaturation) && AxisOf(header) == AxRz)
            hr = DI_OK;
        else
            hr = m_real->SetProperty(prop, header);
        LogProperty("SetProperty", prop, header, hr);
        return hr;
    }
    STDMETHOD(Acquire)()
    {
        HRESULT hr = m_real->Acquire();
        if (hr != m_lastAcquire || ++m_acquires <= 3)
            Log("Device#%d Acquire -> %s", m_id, HrName(hr));
        m_lastAcquire = hr;
        return hr;
    }
    STDMETHOD(Unacquire)()
    {
        Log("Device#%d Unacquire", m_id);
        if (m_virtual)
            VirtualEffect::StopAllFor(this);
        return m_real->Unacquire();
    }
    STDMETHOD(GetDeviceState)(DWORD size, LPVOID data)
    {
        HRESULT hr = m_real->GetDeviceState(size, data);
        if (m_id < kMaxDevices)
            InterlockedIncrement(&g_reads[m_id]);
        if (FAILED(hr) && (++m_stateFails <= 5 || m_stateFails % 500 == 0))
            Log("Device#%d GetDeviceState failed #%lu -> %s", m_id, m_stateFails, HrName(hr));
        if (++m_stateCalls <= 2)
            Log("Device#%d GetDeviceState size=%lu -> %s", m_id, (unsigned long)size, HrName(hr));
        if (SUCCEEDED(hr) && m_kind == KindJoystick && size >= sizeof(DIJOYSTATE) && m_standardFormat)
        {
            if (m_virtual)
                FillFromXInput((DIJOYSTATE*)data);
            if (m_id < kMaxDevices)
            {
                g_lastZ[m_id] = ((DIJOYSTATE*)data)->lZ;
                g_lastRx[m_id] = ((DIJOYSTATE*)data)->lRx;
            }
            if (g_cfg.logState)
                LogJoystickChanges((const DIJOYSTATE*)data);
        }
        return hr;
    }
    STDMETHOD(GetDeviceData)(DWORD objSize, LPDIDEVICEOBJECTDATA data, LPDWORD count, DWORD flags)
    {
        HRESULT hr = m_real->GetDeviceData(objSize, data, count, flags);
        if (++m_dataCalls <= 2)
            Log("Device#%d GetDeviceData -> %s count=%lu", m_id, HrName(hr), count ? (unsigned long)*count : 0);
        return hr;
    }
    STDMETHOD(SetDataFormat)(LPCDIDATAFORMAT fmt)
    {
        HRESULT hr = m_real->SetDataFormat(fmt);
        // We only rewrite state for the standard DIJOYSTATE/DIJOYSTATE2 layouts.
        m_standardFormat = (fmt->dwDataSize == sizeof(DIJOYSTATE) || fmt->dwDataSize == sizeof(DIJOYSTATE2))
            && fmt->dwNumObjs > 0 && fmt->rgodf[0].pguid && IsEqualGUID(*fmt->rgodf[0].pguid, GUID_XAxis)
            && fmt->rgodf[0].dwOfs == 0;
        m_formatSet = SUCCEEDED(hr);
        Log("Device#%d SetDataFormat dataSize=%lu objects=%lu -> %s%s", m_id, (unsigned long)fmt->dwDataSize,
            (unsigned long)fmt->dwNumObjs, HrName(hr), m_standardFormat ? " (standard joystick layout)" : "");
        return hr;
    }
    STDMETHOD(SetEventNotification)(HANDLE e) { return m_real->SetEventNotification(e); }
    STDMETHOD(SetCooperativeLevel)(HWND wnd, DWORD flags)
    {
        HRESULT hr = m_real->SetCooperativeLevel(wnd, flags);
        if (m_virtual && wnd)
            g_ff.window = wnd;
        Log("Device#%d SetCooperativeLevel flags=0x%lX%s%s%s%s -> %s", m_id, (unsigned long)flags,
            (flags & DISCL_EXCLUSIVE) ? " EXCLUSIVE" : "", (flags & DISCL_NONEXCLUSIVE) ? " NONEXCLUSIVE" : "",
            (flags & DISCL_FOREGROUND) ? " FOREGROUND" : "", (flags & DISCL_BACKGROUND) ? " BACKGROUND" : "",
            HrName(hr));
        return hr;
    }
    STDMETHOD(GetObjectInfo)(LPDIDEVICEOBJECTINSTANCEA info, DWORD obj, DWORD how)
    {
        if (m_virtual && IsRz(obj, how))
        {
            FillRzObject(info);
            return DI_OK;
        }
        HRESULT hr = m_real->GetObjectInfo(info, obj, how);
        if (SUCCEEDED(hr) && m_virtual)
            MarkActuator(info);
        return hr;
    }
    STDMETHOD(GetDeviceInfo)(LPDIDEVICEINSTANCEA info) { return m_real->GetDeviceInfo(info); }
    STDMETHOD(RunControlPanel)(HWND wnd, DWORD flags) { return m_real->RunControlPanel(wnd, flags); }
    STDMETHOD(Initialize)(HINSTANCE inst, DWORD ver, REFGUID g) { return m_real->Initialize(inst, ver, g); }
    STDMETHOD(CreateEffect)(REFGUID type, LPCDIEFFECT params, LPDIRECTINPUTEFFECT* out, LPUNKNOWN outer)
    {
        int id = ++s_effectCount;
        HRESULT hr;
        if (m_virtual)
        {
            VirtualEffect* e = new VirtualEffect(type, this, id);
            e->Apply(params, DIEP_ALLPARAMS);
            *out = e;
            hr = DI_OK;
            EnsureRumbleThread();
            if (params && (params->dwFlags & DIEP_START))
                e->Start(1, 0);
        }
        else
        {
            hr = m_real->CreateEffect(type, params, out, outer);
            if (SUCCEEDED(hr) && out && *out)
                *out = new EffectProxy(*out, type, id);
        }
        Log("Device#%d CreateEffect -> %s (Effect#%d)", m_id, HrName(hr), id);
        LogEffect("create", &type, params, 0);
        return hr;
    }
    STDMETHOD(EnumEffects)(LPDIENUMEFFECTSCALLBACKA cb, LPVOID ref, DWORD type)
    {
        Log("Device#%d EnumEffects type=0x%lX", m_id, (unsigned long)type);
        if (!m_virtual)
            return m_real->EnumEffects(cb, ref, type);
        for (const GuidName& n : kGuidNames)
        {
            if (CategoryOf(*n.guid) == CatOther)
                continue;
            DIEFFECTINFOA info;
            FillEffectInfo(&info, *n.guid, n.name);
            if (type != DIEFT_ALL && DIEFT_GETTYPE(info.dwEffType) != type)
                continue;
            if (cb(&info, ref) == DIENUM_STOP)
                break;
        }
        return DI_OK;
    }
    STDMETHOD(GetEffectInfo)(LPDIEFFECTINFOA info, REFGUID g)
    {
        if (!m_virtual)
            return m_real->GetEffectInfo(info, g);
        if (CategoryOf(g) == CatOther)
            return DIERR_DEVICENOTREG;
        FillEffectInfo(info, g, GuidStr(&g));
        return DI_OK;
    }
    STDMETHOD(GetForceFeedbackState)(LPDWORD state)
    {
        if (!m_virtual)
            return m_real->GetForceFeedbackState(state);
        *state = DIGFFS_POWERON | (g_ff.actuatorsOn ? DIGFFS_ACTUATORSON : DIGFFS_ACTUATORSOFF)
            | (g_ff.paused ? DIGFFS_PAUSED : 0);
        return DI_OK;
    }
    STDMETHOD(SendForceFeedbackCommand)(DWORD cmd)
    {
        HRESULT hr;
        if (m_virtual)
        {
            if (cmd & (DISFFC_RESET | DISFFC_STOPALL)) VirtualEffect::StopAllFor(this);
            if (cmd & DISFFC_PAUSE) g_ff.paused = true;
            if (cmd & DISFFC_CONTINUE) g_ff.paused = false;
            if (cmd & DISFFC_SETACTUATORSON) g_ff.actuatorsOn = true;
            if (cmd & DISFFC_SETACTUATORSOFF) g_ff.actuatorsOn = false;
            hr = DI_OK;
        }
        else
            hr = m_real->SendForceFeedbackCommand(cmd);
        Log("Device#%d SendForceFeedbackCommand 0x%lX -> %s", m_id, (unsigned long)cmd, HrName(hr));
        return hr;
    }
    STDMETHOD(EnumCreatedEffectObjects)(LPDIENUMCREATEDEFFECTOBJECTSCALLBACK cb, LPVOID ref, DWORD f)
    {
        if (!m_virtual)
            return m_real->EnumCreatedEffectObjects(cb, ref, f);
        EnterCriticalSection(&g_ffLock);
        std::vector<VirtualEffect*> mine;
        for (VirtualEffect* e : g_effects)
            if (e->Owner() == this)
                mine.push_back(e);
        LeaveCriticalSection(&g_ffLock);
        for (VirtualEffect* e : mine)
            if (cb(e, ref) == DIENUM_STOP)
                break;
        return DI_OK;
    }
    STDMETHOD(Escape)(LPDIEFFESCAPE e) { return m_real->Escape(e); }
    STDMETHOD(Poll)() { return m_real->Poll(); }
    STDMETHOD(SendDeviceData)(DWORD size, LPCDIDEVICEOBJECTDATA data, LPDWORD count, DWORD f) { return m_real->SendDeviceData(size, data, count, f); }
    STDMETHOD(EnumEffectsInFile)(LPCSTR file, LPDIENUMEFFECTSINFILECALLBACK cb, LPVOID ref, DWORD f) { return m_real->EnumEffectsInFile(file, cb, ref, f); }
    STDMETHOD(WriteEffectToFile)(LPCSTR file, DWORD n, LPDIFILEEFFECT e, DWORD f) { return m_real->WriteEffectToFile(file, n, e, f); }
    STDMETHOD(BuildActionMap)(LPDIACTIONFORMATA fmt, LPCSTR user, DWORD f) { return m_real->BuildActionMap(fmt, user, f); }
    STDMETHOD(SetActionMap)(LPDIACTIONFORMATA fmt, LPCSTR user, DWORD f) { return m_real->SetActionMap(fmt, user, f); }
    STDMETHOD(GetImageInfo)(LPDIDEVICEIMAGEINFOHEADERA info) { return m_real->GetImageInfo(info); }

private:
    struct EnumCtx
    {
        DeviceProxy* self;
        LPDIENUMDEVICEOBJECTSCALLBACKA cb;
        LPVOID ref;
        bool actuatorsOnly;
        bool stopped;
    };

    static BOOL CALLBACK EnumObjectsFilter(LPCDIDEVICEOBJECTINSTANCEA obj, LPVOID p)
    {
        EnumCtx* ctx = (EnumCtx*)p;
        DIDEVICEOBJECTINSTANCEA copy = *obj;
        bool actuator = MarkActuator(&copy);
        if (ctx->actuatorsOnly && !actuator)
            return DIENUM_CONTINUE;
        BOOL result = ctx->cb(&copy, ctx->ref);
        if (result == DIENUM_STOP)
            ctx->stopped = true;
        return result;
    }

    // The left stick's X and Y axes act as the force-feedback actuators, like a wheel's steering axis.
    static bool MarkActuator(LPDIDEVICEOBJECTINSTANCEA obj)
    {
        if (!IsEqualGUID(obj->guidType, GUID_XAxis) && !IsEqualGUID(obj->guidType, GUID_YAxis))
            return false;
        obj->dwType |= DIDFT_FFACTUATOR;
        obj->dwFlags |= DIDOI_FFACTUATOR;
        if (obj->dwSize >= sizeof(DIDEVICEOBJECTINSTANCEA))
        {
            obj->dwFFMaxForce = DI_FFNOMINALMAX;
            obj->dwFFForceResolution = 1;
        }
        return true;
    }

    void FillRzObject(LPDIDEVICEOBJECTINSTANCEA obj)
    {
        DWORD size = obj->dwSize ? obj->dwSize : sizeof(*obj);
        memset(obj, 0, size);
        obj->dwSize = size;
        obj->guidType = GUID_RzAxis;
        obj->dwOfs = m_formatSet ? DIJOFS_RZ : 36; // 36 is unused in the driver's native layout
        obj->dwType = DIDFT_ABSAXIS | DIDFT_MAKEINSTANCE(AxRz);
        obj->dwFlags = DIDOI_ASPECTPOSITION;
        strcpy(obj->tszName, "Z Rotation (right stick X)");
        if (size >= sizeof(DIDEVICEOBJECTINSTANCEA))
        {
            obj->wUsagePage = 0x01;
            obj->wUsage = 0x35;
        }
    }

    bool IsRz(DWORD obj, DWORD how) const
    {
        if (how == DIPH_BYID)
            return (DIDFT_GETTYPE(obj) & DIDFT_ABSAXIS) && DIDFT_GETINSTANCE(obj) == AxRz;
        if (how == DIPH_BYOFFSET)
            return m_formatSet && obj == DIJOFS_RZ;
        return false;
    }

    // Which of our six axes a property header refers to, or -1.
    int AxisOf(LPCDIPROPHEADER h) const
    {
        if (h->dwHow == DIPH_BYID && (DIDFT_GETTYPE(h->dwObj) & DIDFT_ABSAXIS))
        {
            DWORD inst = DIDFT_GETINSTANCE(h->dwObj);
            return inst < AxCount ? (int)inst : -1;
        }
        if (h->dwHow == DIPH_BYOFFSET && h->dwObj <= DIJOFS_RZ && h->dwObj % 4 == 0)
            return (int)(h->dwObj / 4);
        return -1;
    }

    static void FillEffectInfo(LPDIEFFECTINFOA info, const GUID& g, const char* name)
    {
        memset(info, 0, sizeof(*info));
        info->dwSize = sizeof(*info);
        info->guid = g;
        switch (CategoryOf(g))
        {
        case CatConstant: info->dwEffType = DIEFT_CONSTANTFORCE | DIEFT_FFATTACK | DIEFT_FFFADE; break;
        case CatRamp: info->dwEffType = DIEFT_RAMPFORCE | DIEFT_FFATTACK | DIEFT_FFFADE; break;
        case CatPeriodic: info->dwEffType = DIEFT_PERIODIC | DIEFT_FFATTACK | DIEFT_FFFADE; break;
        case CatCondition: info->dwEffType = DIEFT_CONDITION; break;
        default: break;
        }
        info->dwStaticParams = DIEP_ALLPARAMS;
        info->dwDynamicParams = DIEP_ALLPARAMS;
        strncpy(info->tszName, name, MAX_PATH - 1);
    }

    LONG Scale(int axis, LONG v, LONG vMin, LONG vMax) const
    {
        return m_min[axis] + (LONG)((LONGLONG)(v - vMin) * (m_max[axis] - m_min[axis]) / (vMax - vMin));
    }
    LONG Centre(int axis) const { return m_min[axis] + (m_max[axis] - m_min[axis]) / 2; }
    // Shaped trigger (see ShapeTrigger) -> centre..max of the axis.
    LONG Trigger(int axis, BYTE t) const
    {
        float curve = axis == AxRx ? g_cfg.rtCurve : g_cfg.ltCurve; // RT drives Rx, LT drives Z
        return Centre(axis) + (LONG)((m_max[axis] - Centre(axis)) * ShapeTrigger(t, curve) + 0.5f);
    }
    static LONG Invert(SHORT v) { return v == -32768 ? 32767 : -v; }
    // -1..1 -> the axis's min..max around its centre.
    LONG Signed(int axis, float v) const
    {
        LONG c = Centre(axis);
        return v >= 0 ? c + (LONG)((m_max[axis] - c) * v + 0.5f) : c - (LONG)((c - m_min[axis]) * -v + 0.5f);
    }

    void FillFromXInput(DIJOYSTATE* s)
    {
        XINPUT_STATE xs;
        if (!ReadPad(&xs))
        {
            // No XInput pad: keep the real state, but park our extra axis at rest.
            s->lRz = Centre(AxRz);
            return;
        }
        XINPUT_GAMEPAD g = xs.Gamepad;
        if (g_cfg.debugFakePad)
        {
            DWORD phase = (GetTickCount() - g_startTick) % 6000;
            g.bRightTrigger = phase < 2000 ? 255 : 0;
            g.bLeftTrigger = 0;
            g.sThumbLX = phase >= 4000 ? 32767 : 0;
            g.sThumbLY = 0;
            if (phase >= 5000 && phase < 5200)
                g.wButtons |= XINPUT_GAMEPAD_RIGHT_THUMB;
        }
        g_padButtons = g.wButtons;
        g_padRY = g.sThumbRY;
        g_padLT = g.bLeftTrigger;
        g_padRT = g.bRightTrigger;
        g_padLX = g.sThumbLX;
        float lx, ly;
        ShapeStick(std::max(g.sThumbLX / 32767.0f, -1.0f), std::max(g.sThumbLY / 32767.0f, -1.0f), &lx, &ly);
        g_steerShaped = (LONG)(lx * 10000);
        s->lX = Signed(AxX, lx);
        s->lY = Signed(AxY, -ly); // DirectInput Y grows downwards
        s->lZ = Trigger(AxZ, g.bLeftTrigger);
        s->lRx = Trigger(AxRx, g.bRightTrigger);
        s->lRy = Scale(AxRy, Invert(g.sThumbRY), -32768, 32767);
        s->lRz = Scale(AxRz, g.sThumbRX, -32768, 32767);

        static const WORD kButtons[10] = { XINPUT_GAMEPAD_A, XINPUT_GAMEPAD_B, XINPUT_GAMEPAD_X, XINPUT_GAMEPAD_Y,
            XINPUT_GAMEPAD_LEFT_SHOULDER, XINPUT_GAMEPAD_RIGHT_SHOULDER, XINPUT_GAMEPAD_BACK, XINPUT_GAMEPAD_START,
            XINPUT_GAMEPAD_LEFT_THUMB, XINPUT_GAMEPAD_RIGHT_THUMB };
        memset(s->rgbButtons, 0, sizeof(s->rgbButtons));
        for (int i = 0; i < 10; ++i)
            s->rgbButtons[i] = (g.wButtons & kButtons[i]) ? 0x80 : 0;

        // Next song: the game acts on that button only in the menus (its input dispatcher never
        // sees it during a race). We are on the game's own thread here, so on the press we ask
        // MusicBridge, which knows the game's music code and ignores the request in the menus.
        static bool nextSongWasDown;
        bool nextSongDown = g_cfg.nextSongButton >= 0 && g_cfg.nextSongButton < 10 && (g.wButtons & kButtons[g_cfg.nextSongButton]);
        if (nextSongDown && !nextSongWasDown)
        {
            typedef int(__cdecl* NextSongFn)();
            HMODULE music = GetModuleHandleA("MusicBridge.asi");
            NextSongFn next = music ? (NextSongFn)GetProcAddress(music, "MusicBridge_NextSong") : nullptr;
            int result = next ? next() : -1;
            if (result != 0) // 0 = MusicBridge left it to the game (menus, paused)
                Log("Next song (button %d): %s", g_cfg.nextSongButton, result > 0 ? "asked MusicBridge" : "MusicBridge is not loaded");
        }
        nextSongWasDown = nextSongDown;

        bool up = g.wButtons & XINPUT_GAMEPAD_DPAD_UP, down = g.wButtons & XINPUT_GAMEPAD_DPAD_DOWN;
        bool left = g.wButtons & XINPUT_GAMEPAD_DPAD_LEFT, right = g.wButtons & XINPUT_GAMEPAD_DPAD_RIGHT;
        DWORD pov = (DWORD)-1;
        if (up && right) pov = 4500;
        else if (right && down) pov = 13500;
        else if (down && left) pov = 22500;
        else if (left && up) pov = 31500;
        else if (up) pov = 0;
        else if (right) pov = 9000;
        else if (down) pov = 18000;
        else if (left) pov = 27000;
        s->rgdwPOV[0] = pov;
    }

    void LogProperty(const char* what, REFGUID prop, LPCDIPROPHEADER h, HRESULT hr)
    {
        const char* name = PropName(prop);
        if (h && h->dwSize == sizeof(DIPROPRANGE) && PropId(prop) == kPropRange)
        {
            const DIPROPRANGE* r = (const DIPROPRANGE*)h;
            Log("Device#%d %s %s [%s] min=%ld max=%ld -> %s", m_id, what, name, HowStr(h), r->lMin, r->lMax, HrName(hr));
        }
        else if (h && h->dwSize == sizeof(DIPROPDWORD))
            Log("Device#%d %s %s [%s] value=%lu -> %s", m_id, what, name, HowStr(h),
                (unsigned long)((const DIPROPDWORD*)h)->dwData, HrName(hr));
        else
            Log("Device#%d %s %s -> %s", m_id, what, name, HrName(hr));
    }

    // Logs axis/button/POV changes, ignoring small axis noise, at most ~20 lines per second.
    void LogJoystickChanges(const DIJOYSTATE* s)
    {
        LONG axes[AxCount] = { s->lX, s->lY, s->lZ, s->lRx, s->lRy, s->lRz };
        if (!m_haveLast)
        {
            m_last = *s;
            m_haveLast = true;
            Log("Device#%d initial X=%ld Y=%ld Z=%ld Rx=%ld Ry=%ld Rz=%ld POV=%ld", m_id, axes[0], axes[1], axes[2],
                axes[3], axes[4], axes[5], (long)s->rgdwPOV[0]);
            return;
        }
        LONG last[AxCount] = { m_last.lX, m_last.lY, m_last.lZ, m_last.lRx, m_last.lRy, m_last.lRz };
        char line[256] = "";
        size_t len = 0;
        bool changed = false;
        for (int i = 0; i < AxCount; ++i)
        {
            LONG noise = (m_max[i] - m_min[i]) / 20;
            if (labs(axes[i] - last[i]) >= noise)
            {
                len += snprintf(line + len, sizeof(line) - len, " %s=%ld", kAxisNames[i], axes[i]);
                changed = true;
            }
        }
        for (int i = 0; i < 32; ++i)
            if ((s->rgbButtons[i] & 0x80) != (m_last.rgbButtons[i] & 0x80))
            {
                len += snprintf(line + len, sizeof(line) - len, " btn%d=%s", i, (s->rgbButtons[i] & 0x80) ? "down" : "up");
                changed = true;
            }
        if (s->rgdwPOV[0] != m_last.rgdwPOV[0])
        {
            len += snprintf(line + len, sizeof(line) - len, " POV=%ld", (long)s->rgdwPOV[0]);
            changed = true;
        }
        if (!changed)
            return;
        DWORD now = GetTickCount();
        if (now - m_lastLogTick < 50)
            return; // keep m_last so the change is reported on the next allowed tick
        m_lastLogTick = now;
        m_last = *s;
        Log("Device#%d state%s", m_id, line);
    }

    IDirectInputDevice8A* m_real;
    int m_id;
    DeviceKind m_kind = KindUnknown;
    bool m_virtual = false;
    bool m_standardFormat = false;
    bool m_formatSet = false;
    LONG m_min[AxCount], m_max[AxCount];
    DWORD m_stateCalls = 0, m_dataCalls = 0, m_stateFails = 0;
    int m_acquires = 0;
    HRESULT m_lastAcquire = S_OK;
    DIJOYSTATE m_last = {};
    bool m_haveLast = false;
    DWORD m_lastLogTick = 0;
};

// ---------------------------------------------------------------------------------------------
// DirectInput proxy

struct EnumForward { LPDIENUMDEVICESCALLBACKA cb; LPVOID ref; };
static BOOL CALLBACK EnumAndLog(LPCDIDEVICEINSTANCEA dev, LPVOID ref)
{
    if (GET_DIDEVICE_TYPE(dev->dwDevType) != DI8DEVTYPE_DEVICE) // skip the many HID receivers in the log
        Log("  enumerated \"%s\" devType=0x%08lX", dev->tszProductName, (unsigned long)dev->dwDevType);
    EnumForward* f = (EnumForward*)ref;
    return f->cb(dev, f->ref);
}

class DirectInputProxy : public IDirectInput8A
{
public:
    explicit DirectInputProxy(IDirectInput8A* real) : m_real(real) {}

    STDMETHOD(QueryInterface)(REFIID riid, void** out)
    {
        if (IsEqualGUID(riid, IID_IDirectInput8A) || IsEqualGUID(riid, IID_IUnknown))
        {
            AddRef();
            *out = this;
            return S_OK;
        }
        return m_real->QueryInterface(riid, out);
    }
    STDMETHOD_(ULONG, AddRef)() { return m_real->AddRef(); }
    STDMETHOD_(ULONG, Release)()
    {
        ULONG n = m_real->Release();
        if (n == 0)
            delete this;
        return n;
    }
    STDMETHOD(CreateDevice)(REFGUID guid, LPDIRECTINPUTDEVICE8A* out, LPUNKNOWN outer)
    {
        HRESULT hr = m_real->CreateDevice(guid, out, outer);
        Log("CreateDevice(%s) -> %s", GuidStr(&guid), HrName(hr));
        if (SUCCEEDED(hr) && out && *out)
            *out = new DeviceProxy(*out, guid);
        return hr;
    }
    STDMETHOD(EnumDevices)(DWORD type, LPDIENUMDEVICESCALLBACKA cb, LPVOID ref, DWORD flags)
    {
        Log("EnumDevices type=0x%lX flags=0x%lX", (unsigned long)type, (unsigned long)flags);
        EnumForward f = { cb, ref };
        return m_real->EnumDevices(type, EnumAndLog, &f, flags);
    }
    STDMETHOD(GetDeviceStatus)(REFGUID g) { return m_real->GetDeviceStatus(g); }
    STDMETHOD(RunControlPanel)(HWND wnd, DWORD f) { return m_real->RunControlPanel(wnd, f); }
    STDMETHOD(Initialize)(HINSTANCE inst, DWORD ver) { return m_real->Initialize(inst, ver); }
    STDMETHOD(FindDevice)(REFGUID g, LPCSTR name, LPGUID out) { return m_real->FindDevice(g, name, out); }
    STDMETHOD(EnumDevicesBySemantics)(LPCSTR user, LPDIACTIONFORMATA fmt, LPDIENUMDEVICESBYSEMANTICSCBA cb, LPVOID ref, DWORD f)
    {
        return m_real->EnumDevicesBySemantics(user, fmt, cb, ref, f);
    }
    STDMETHOD(ConfigureDevices)(LPDICONFIGUREDEVICESCALLBACK cb, LPDICONFIGUREDEVICESPARAMSA p, DWORD f, LPVOID ref)
    {
        return m_real->ConfigureDevices(cb, p, f, ref);
    }

private:
    IDirectInput8A* m_real;
};

// ---------------------------------------------------------------------------------------------
// Telemetry: the car's speed, RPM, gear and nitrous read from the game's memory, logged with the
// controller inputs to CSV during races, and shown in a small panel next to DXVK's frame-time graph.
// Addresses (speed.exe v1.3) from github.com/muki01/NFS_Most_Wanted_Telemetry_Dashboard (MIT).
// All reads go through ReadProcessMemory, so a wrong address reads as "unavailable", never a crash.

struct TelemetrySample
{
    bool valid;      // speed read succeeded
    float speedKmh;
    float rpm;       // < 0 unavailable
    int gear;        // -1 reverse, 0 neutral, 1.. gears; -99 unavailable
    float nitrous;   // 0..1, < 0 unavailable
    bool posValid;   // car position read succeeded
    float x, y, z;   // metres; y is height
};

static bool ReadMem(UINT_PTR addr, void* out, SIZE_T size)
{
    SIZE_T got = 0;
    return addr && ReadProcessMemory(GetCurrentProcess(), (LPCVOID)addr, out, size, &got) && got == size;
}

// base -> [ptr + off0] -> [ptr + off1] ... -> ptr + offLast: the address of the final field.
static UINT_PTR FollowChain(UINT_PTR base, const DWORD* offs, int count)
{
    DWORD ptr;
    if (!ReadMem(base, &ptr, 4) || !ptr)
        return 0;
    for (int i = 0; i < count - 1; ++i)
        if (!ReadMem(ptr + offs[i], &ptr, 4) || !ptr)
            return 0;
    return ptr + offs[count - 1];
}

static TelemetrySample ReadTelemetry()
{
    TelemetrySample t = { false, 0, -1, -99, -1, false, 0, 0, 0 };
    UINT_PTR exe = (UINT_PTR)GetModuleHandleA(nullptr);
    float f;
    int i;
    if (!ReadMem(exe + 0x514654, &f, 4) || !isfinite(f))
        return t;
    t.valid = true;
    t.speedKmh = fabsf(f) * 1.609344f; // the game stores mph
    static const DWORD rpm[] = { 0x4, 0x4, 0x6C, 0x12C };
    static const DWORD gear[] = { 0x68, 0x4, 0x8, 0x10, 0x84 };
    static const DWORD nitrous[] = { 0x68, 0x4, 0x8, 0x10, 0xF8 };
    if (ReadMem(FollowChain(exe + 0x50D670, rpm, 4), &f, 4) && isfinite(f))
        t.rpm = fabsf(f);
    if (ReadMem(FollowChain(exe + 0x50D670, gear, 5), &i, 4) && i >= 0 && i < 12)
        t.gear = i - 1; // the game: 0 reverse, 1 neutral, 2 first...
    if (ReadMem(FollowChain(exe + 0x50D670, nitrous, 5), &f, 4) && isfinite(f) && f >= -0.01f && f <= 1.01f)
        t.nitrous = f;
    float pos[3]; // z, y (height), x: consecutive floats in the game
    if (ReadMem(exe + 0x5386D8, pos, sizeof(pos)) && isfinite(pos[0]) && isfinite(pos[1]) && isfinite(pos[2]))
    {
        t.posValid = true;
        t.z = pos[0];
        t.y = pos[1];
        t.x = pos[2];
    }
    return t;
}

// The game's own processed controls (option B). The player's InputControls (layout from
// github.com/s-b-repo/nfsmw-2005-sdk: 36 bytes; +4 steering -1..1, +20 gas 0..1, +24 brake 0..1,
// +28 handbrake, +33 nitrous flag) holds the controls as the car receives them, after the game's own
// processing. Its address changes per race, so it's found by narrowing memory down with what we know
// the player is doing:
//   1. full throttle, no brake, wheel straight (held 0.3 s): scan writable memory for that shape;
//   2. throttle released (held 0.3 s): keep candidates whose gas dropped below 0.1;
//   3. steering hard (> 70%, held 0.3 s): keep candidates whose steering moved the same way;
//   4. verify: watch the survivors during normal driving and lock the one whose steering and gas
//      move together with ours (correlation), since several can pass steps 1-3.
// It's re-found after every race start (a race "ends" only after 2 s without the game's damper).
enum FinderState { FindIdle, FindWaitScan, FindScanning, FindWaitRelease, FindWaitSteer, FindVerify, FindLocked };
static const char* kFinderNames[] = { "idle", "waiting for full throttle", "scanning", "waiting for throttle release",
    "waiting for hard steering", "verifying", "locked" };
static volatile LONG g_finderState = FindIdle;
static std::vector<UINT_PTR> g_candidates; // written by the scan thread, then the telemetry thread
static volatile LONG g_scanDone;
static UINT_PTR g_controlsAddr;
static const int kCtlSize = 36;

struct GameControls
{
    bool valid;
    float steer, gas, brake, handbrake;
    int nos;
};

static bool ControlsInRange(const BYTE* p)
{
    const float* f = (const float*)p;
    for (int i = 0; i < 8; ++i)
        if (!isfinite(f[i]) || f[i] < -1.01f || f[i] > 1.01f)
            return false;
    return f[5] >= -0.001f && f[6] >= -0.001f && f[7] >= -0.001f && p[32] <= 1 && p[33] <= 1;
}

static bool LooksLikeFullGas(const BYTE* p)
{
    const float* f = (const float*)p;
    return ControlsInRange(p) && f[5] >= 0.9f && f[6] <= 0.05f && fabsf(f[1]) < 0.2f;
}

static DWORD WINAPI ControlsScanThread(LPVOID)
{
    DWORD t0 = GetTickCount();
    std::vector<UINT_PTR> found;
    std::vector<BYTE> buf(1 << 20);
    SIZE_T scanned = 0;
    MEMORY_BASIC_INFORMATION mbi;
    for (UINT_PTR a = 0x10000; a < 0x7FFE0000 && VirtualQuery((LPCVOID)a, &mbi, sizeof(mbi));
         a = (UINT_PTR)mbi.BaseAddress + mbi.RegionSize)
    {
        bool writable = mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))
            && (mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE | PAGE_WRITECOPY));
        UINT_PTR base = (UINT_PTR)mbi.BaseAddress, end = base + mbi.RegionSize;
        if (!writable || ((UINT_PTR)buf.data() >= base && (UINT_PTR)buf.data() < end))
            continue; // skip our own scan buffer
        for (UINT_PTR chunk = base; chunk < end; chunk += buf.size() - kCtlSize)
        {
            SIZE_T len = std::min<SIZE_T>(buf.size(), end - chunk), got = 0;
            if (!ReadProcessMemory(GetCurrentProcess(), (LPCVOID)chunk, buf.data(), len, &got) || got < (SIZE_T)kCtlSize)
                break;
            scanned += got;
            for (SIZE_T i = 0; i + kCtlSize <= got; i += 4)
                if (LooksLikeFullGas(&buf[i]) && found.size() < 2000000)
                    found.push_back(chunk + i);
            if (len < buf.size())
                break;
        }
    }
    std::sort(found.begin(), found.end());
    found.erase(std::unique(found.begin(), found.end()), found.end());
    Log("Controls finder: scanned %u MB in %lu ms, %u candidates", (unsigned)(scanned >> 20),
        (unsigned long)(GetTickCount() - t0), (unsigned)found.size());
    g_candidates.swap(found);
    InterlockedExchange(&g_scanDone, 1);
    return 0;
}

// Running correlation between a candidate's field and what we sent.
struct Corr
{
    double n = 0, sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    void Add(double x, double y)
    {
        n += 1; sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y;
    }
    double VarX() const { return n > 1 ? sxx / n - (sx / n) * (sx / n) : 0; }
    double Value() const
    {
        double vx = sxx - sx * sx / n, vy = syy - sy * sy / n;
        return n > 1 && vx > 0 && vy > 0 ? (sxy - sx * sy / n) / sqrt(vx * vy) : 0;
    }
};
struct Track
{
    UINT_PTR addr;
    Corr steer, gas;
    bool dead;
};
static std::vector<Track> g_tracks;

// Keeps the candidates whose current bytes pass `keep`.
template <typename Pred> static size_t FilterCandidates(Pred keep)
{
    std::vector<UINT_PTR> kept;
    BYTE p[kCtlSize];
    for (UINT_PTR a : g_candidates)
        if (ReadMem(a, p, kCtlSize) && ControlsInRange(p) && keep((const float*)p))
            kept.push_back(a);
    g_candidates.swap(kept);
    return g_candidates.size();
}

static void SetFinderState(FinderState st)
{
    if (g_finderState != st)
        Log("Controls finder: %s", kFinderNames[st]);
    g_finderState = st;
}

// Runs once per telemetry sample (50 Hz) with what the game is being given.
static GameControls StepControlsFinder(bool inRace, bool raceStarted, float rt, float lt, float steer)
{
    GameControls c = { false, 0, 0, 0, 0, 0 };
    static DWORD condSince, retryAfter;
    DWORD now = GetTickCount();
    auto held = [&](bool cond) {
        if (!cond)
        {
            condSince = 0;
            return false;
        }
        if (!condSince)
            condSince = now;
        return now - condSince >= 300;
    };

    if (raceStarted && g_finderState != FindScanning)
    {
        g_controlsAddr = 0;
        g_candidates.clear();
        condSince = 0;
        SetFinderState(FindWaitScan);
    }
    if (!inRace && g_finderState != FindScanning && g_finderState != FindLocked)
        return c;

    switch ((FinderState)g_finderState)
    {
    case FindWaitScan:
        if (now >= retryAfter && held(rt >= 0.99f && lt < 0.01f && fabsf(steer) < 0.05f))
        {
            condSince = 0;
            g_scanDone = 0;
            SetFinderState(FindScanning);
            HANDLE th = CreateThread(nullptr, 0, ControlsScanThread, nullptr, 0, nullptr);
            if (th)
                CloseHandle(th);
        }
        break;
    case FindScanning:
        if (g_scanDone)
            SetFinderState(g_candidates.empty() ? FindWaitScan : FindWaitRelease);
        break;
    case FindWaitRelease:
        if (held(rt < 0.01f))
        {
            condSince = 0;
            size_t n = FilterCandidates([](const float* f) { return f[5] < 0.1f; });
            Log("Controls finder: %u candidates after throttle release", (unsigned)n);
            if (n)
                SetFinderState(FindWaitSteer);
            else
            {
                retryAfter = now + 3000;
                SetFinderState(FindWaitScan);
            }
        }
        break;
    case FindWaitSteer:
        if (held(fabsf(steer) > 0.7f))
        {
            condSince = 0;
            float sign = steer > 0 ? 1.0f : -1.0f;
            size_t n = FilterCandidates([sign](const float* f) { return f[1] * sign > 0.2f; });
            Log("Controls finder: %u candidates after steering", (unsigned)n);
            if (n && n <= 2000)
            {
                g_tracks.clear();
                for (UINT_PTR a : g_candidates)
                    g_tracks.push_back({ a, {}, {}, false });
                SetFinderState(FindVerify);
            }
            else
            {
                retryAfter = now + 3000;
                SetFinderState(FindWaitScan);
            }
        }
        break;
    case FindVerify:
    {
        // Sample every survivor; once our steering and throttle have both varied enough (and at least
        // 4 s passed), lock the one that follows them best.
        BYTE p[kCtlSize];
        size_t alive = 0;
        for (Track& tr : g_tracks)
        {
            if (tr.dead)
                continue;
            if (!ReadMem(tr.addr, p, kCtlSize) || !ControlsInRange(p))
            {
                tr.dead = true;
                continue;
            }
            const float* f = (const float*)p;
            tr.steer.Add(steer, f[1]);
            tr.gas.Add(rt, f[5]);
            ++alive;
        }
        if (!alive)
        {
            Log("Controls finder: no candidate survived verification; searching again");
            retryAfter = now + 3000;
            SetFinderState(FindWaitScan);
            break;
        }
        const Track& any = *std::find_if(g_tracks.begin(), g_tracks.end(), [](const Track& t) { return !t.dead; });
        if (any.steer.n < 200 || any.steer.VarX() < 0.05 || any.gas.VarX() < 0.05)
            break; // not enough driving yet
        std::vector<const Track*> ranked;
        for (const Track& tr : g_tracks)
            if (!tr.dead)
                ranked.push_back(&tr);
        std::sort(ranked.begin(), ranked.end(), [](const Track* a, const Track* b) {
            return a->steer.Value() + a->gas.Value() > b->steer.Value() + b->gas.Value();
        });
        for (size_t i = 0; i < ranked.size() && i < 5; ++i)
            Log("  candidate %p: steering corr %+.2f, gas corr %+.2f", (void*)ranked[i]->addr, ranked[i]->steer.Value(),
                ranked[i]->gas.Value());
        if (ranked[0]->steer.Value() >= 0.7 && ranked[0]->gas.Value() >= 0.7)
        {
            g_controlsAddr = ranked[0]->addr;
            Log("Controls finder: locked %p after %.0f samples", (void*)g_controlsAddr, ranked[0]->steer.n);
            SetFinderState(FindLocked);
        }
        else
        {
            Log("Controls finder: no candidate follows the inputs closely enough; searching again");
            retryAfter = now + 3000;
            SetFinderState(FindWaitScan);
        }
        g_tracks.clear();
        break;
    }
    case FindLocked:
    {
        BYTE p[kCtlSize];
        if (!ReadMem(g_controlsAddr, p, kCtlSize) || !ControlsInRange(p))
        {
            Log("Controls finder: locked address no longer looks like controls; searching again");
            g_controlsAddr = 0;
            SetFinderState(FindWaitScan);
            break;
        }
        const float* f = (const float*)p;
        c = { true, f[1], f[5], f[6], f[7], p[33] };
        break;
    }
    default:
        break;
    }
    return c;
}

// Recent history for the on-screen graph: 10 s at 50 Hz.
static const int kHistory = 500;
struct HistoryPoint { float speed, rt, lt; };
static HistoryPoint g_history[kHistory];
static int g_historyNext;
static TelemetrySample g_latest;
static float g_latestRt, g_latestLt, g_latestSteer, g_latestTurn; // turn: deg/s, NAN if unknown
static GameControls g_latestGame;
static CRITICAL_SECTION g_telemetryLock;

static FILE* OpenTelemetryCsv()
{
    char dir[MAX_PATH], full[MAX_PATH];
    GetModuleFileNameA((HMODULE)&__ImageBase, dir, MAX_PATH);
    *strrchr(dir, '\\') = 0;
    if (PathIsRelativeA(g_cfg.telemetryDir))
    {
        char joined[MAX_PATH * 2];
        snprintf(joined, sizeof(joined), "%s\\%s", dir, g_cfg.telemetryDir);
        GetFullPathNameA(joined, MAX_PATH, full, nullptr);
    }
    else
        GetFullPathNameA(g_cfg.telemetryDir, MAX_PATH, full, nullptr);
    CreateDirectoryA(full, nullptr);

    // Keep the newest KeepLast-1 files so the new one makes KeepLast.
    if (g_cfg.telemetryKeep > 0)
    {
        std::vector<std::string> files;
        WIN32_FIND_DATAA fd;
        char pattern[MAX_PATH + 32];
        snprintf(pattern, sizeof(pattern), "%s\\nfsmw-telemetry-*.csv", full);
        HANDLE find = FindFirstFileA(pattern, &fd);
        if (find != INVALID_HANDLE_VALUE)
        {
            do { files.push_back(fd.cFileName); } while (FindNextFileA(find, &fd));
            FindClose(find);
        }
        std::sort(files.begin(), files.end());
        for (int i = 0; i + (g_cfg.telemetryKeep - 1) < (int)files.size(); ++i)
            DeleteFileA((std::string(full) + "\\" + files[i]).c_str());
    }

    SYSTEMTIME st;
    GetLocalTime(&st);
    char path[MAX_PATH + 64];
    snprintf(path, sizeof(path), "%s\\nfsmw-telemetry-%04d%02d%02d-%02d%02d%02d.csv", full, st.wYear, st.wMonth,
        st.wDay, st.wHour, st.wMinute, st.wSecond);
    FILE* f = fopen(path, "w");
    if (f)
    {
        fprintf(f, "time_s,rt_raw,lt_raw,rt,lt,steer_raw,steer,speed_kmh,rpm,gear,nitrous,"
                   "pos_x,pos_y,pos_z,turn_rate,game_steer,game_gas,game_brake,game_handbrake,game_nos\n");
        Log("Telemetry: logging to %s", path);
    }
    else
        Log("Telemetry: can't create %s", path);
    return f;
}

// Samples at 50 Hz: history for the overlay always, CSV rows while in a race.
static DWORD WINAPI TelemetryThread(LPVOID)
{
    FILE* csv = nullptr;
    DWORD start = GetTickCount(), lastFlush = 0, lastLog = 0;
    bool wasInRace = false;
    for (;;)
    {
        Sleep(20);
        TelemetrySample t = ReadTelemetry();
        BYTE rtRaw = (BYTE)g_padRT, ltRaw = (BYTE)g_padLT;
        float rt = ShapeTrigger(rtRaw, g_cfg.rtCurve), lt = ShapeTrigger(ltRaw, g_cfg.ltCurve);
        float steerRaw = std::max(-1.0f, std::min(1.0f, (LONG)g_padLX / 32767.0f));
        float steer = (LONG)g_steerShaped / 10000.0f;
        bool inRace = g_inRace != 0;
        DWORD tick = GetTickCount();

        // Turn rate (option A): how fast the direction of travel changes, from the car's position.
        // Compares the last 0.25 s of movement with the 0.25 s before it; needs > ~7 km/h.
        static const int kPos = 32;
        static float px[kPos], pz[kPos];
        static DWORD pt[kPos];
        static int pn, pCount;
        float turn = NAN;
        if (t.posValid)
        {
            px[pn] = t.x;
            pz[pn] = t.z;
            pt[pn] = tick;
            pn = (pn + 1) % kPos;
            pCount = std::min(pCount + 1, kPos);
            if (pCount >= 26)
            {
                int i0 = (pn - 1 + kPos) % kPos, i1 = (pn - 13 + kPos) % kPos, i2 = (pn - 25 + kPos) % kPos;
                float ax = px[i1] - px[i2], az = pz[i1] - pz[i2], bx = px[i0] - px[i1], bz = pz[i0] - pz[i1];
                float dt = (pt[i0] - pt[i1]) / 1000.0f;
                if (dt > 0 && sqrtf(ax * ax + az * az) > 0.5f && sqrtf(bx * bx + bz * bz) > 0.5f)
                    turn = atan2f(ax * bz - az * bx, ax * bx + az * bz) * 57.29578f / dt;
            }
        }
        else
            pCount = 0;

        // The game briefly stops and restarts its damper now and then; for the finder a race only ends
        // after 2 s without it, so those blips don't reset the search.
        static DWORD lastInRace;
        static bool finderInRace;
        if (inRace)
            lastInRace = tick;
        bool raceNow = inRace || (lastInRace && tick - lastInRace < 2000);
        bool raceBegan = raceNow && !finderInRace;
        GameControls game = StepControlsFinder(raceNow, raceBegan, rt, lt, steer);
        finderInRace = raceNow;

        // Screenshots for before/after comparisons: while the car sits on the grid at race start, ask
        // GfxProbe (if installed) for a frame at 1, 2 and 3 s. Same race -> same spot and view.
        static HANDLE captureEvent = CreateEventA(nullptr, FALSE, FALSE, "NFSMW_GfxCapture");
        static DWORD gridSince;
        static int gridShots = 3;
        if (raceBegan)
        {
            gridShots = 0;
            gridSince = 0;
        }
        if (gridShots < 3 && inRace && t.valid)
        {
            if (t.speedKmh > 5)
                gridShots = 3; // moving: no more for this race
            else if (t.speedKmh < 1)
            {
                if (!gridSince)
                    gridSince = tick;
                if (tick - gridSince >= 1000u * (gridShots + 1))
                {
                    ++gridShots;
                    if (captureEvent)
                        SetEvent(captureEvent);
                    Log("Capture request %d/3 on the grid: position x=%.1f y=%.1f z=%.1f", gridShots, t.x, t.y, t.z);
                }
            }
        }

        // Nitrous fires only while its level is falling (it drains >= 0.001 per 20 ms, refills slower).
        static float prevNitrous = -1;
        g_nitrousKnown = t.nitrous >= 0;
        if (t.nitrous >= 0 && prevNitrous >= 0 && t.nitrous < prevNitrous - 0.0005f)
            g_nitrousDrainTick = (LONG)GetTickCount();
        prevNitrous = t.nitrous;

        EnterCriticalSection(&g_telemetryLock);
        g_latest = t;
        g_latestRt = rt;
        g_latestLt = lt;
        g_latestSteer = steer;
        g_latestTurn = turn;
        g_latestGame = game;
        g_history[g_historyNext] = { t.valid ? t.speedKmh : 0, rt, lt };
        g_historyNext = (g_historyNext + 1) % kHistory;
        LeaveCriticalSection(&g_telemetryLock);

        DWORD now = GetTickCount();
        if (inRace && !wasInRace)
            Log("Telemetry at race start: valid=%d speed=%.1f km/h rpm=%.0f gear=%d nitrous=%.2f", t.valid,
                t.speedKmh, t.rpm, t.gear, t.nitrous);
        wasInRace = inRace;
        if (inRace && now - lastLog >= 5000)
        {
            Log("Telemetry: speed=%.1f km/h rpm=%.0f gear=%d nitrous=%.2f rt=%.2f lt=%.2f", t.speedKmh, t.rpm, t.gear,
                t.nitrous, rt, lt);
            lastLog = now;
        }

        if (!g_cfg.telemetryLog || !inRace)
            continue;
        if (!csv)
            csv = OpenTelemetryCsv();
        if (!csv)
            continue;
        fprintf(csv, "%.3f,%u,%u,%.3f,%.3f,%.3f,%.3f,%.2f,%.0f,%d,%.3f,%.3f,%.3f,%.3f,%.2f,%.3f,%.3f,%.3f,%.3f,%d\n",
            (now - start) / 1000.0, rtRaw, ltRaw, rt, lt, steerRaw, steer, t.valid ? t.speedKmh : -1.0f, t.rpm, t.gear,
            t.nitrous, t.posValid ? t.x : 0.0f, t.posValid ? t.y : 0.0f, t.posValid ? t.z : 0.0f,
            isfinite(turn) ? turn : -999.0f, game.valid ? game.steer : -9.0f, game.valid ? game.gas : -9.0f,
            game.valid ? game.brake : -9.0f, game.valid ? game.handbrake : -9.0f, game.valid ? game.nos : -9);
        if (now - lastFlush >= 1000)
        {
            fflush(csv);
            lastFlush = now;
        }
    }
}

// The on-screen panel: a click-through, never-focused, topmost layered window over the game's
// borderless window, drawn with GDI. Shown only during a race and while the game is in front.
static const int kPanelW = 340, kPanelH = 136;

static void DrawPanel(HDC dc, DWORD* pixels)
{
    memset(pixels, 0, kPanelW * kPanelH * 4);
    TelemetrySample t;
    float rt, lt, steer, turn;
    GameControls game;
    HistoryPoint hist[kHistory];
    int next;
    EnterCriticalSection(&g_telemetryLock);
    t = g_latest;
    rt = g_latestRt;
    lt = g_latestLt;
    steer = g_latestSteer;
    turn = g_latestTurn;
    game = g_latestGame;
    memcpy(hist, g_history, sizeof(hist));
    next = g_historyNext;
    LeaveCriticalSection(&g_telemetryLock);

    static HFONT font = CreateFontA(-15, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, NONANTIALIASED_QUALITY, 0, "Consolas");
    static HFONT small = CreateFontA(-12, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, NONANTIALIASED_QUALITY, 0, "Consolas");
    SetBkMode(dc, TRANSPARENT);
    SelectObject(dc, font);

    char line[128], gear[8];
    if (t.gear == -99) strcpy(gear, "-");
    else if (t.gear == -1) strcpy(gear, "R");
    else if (t.gear == 0) strcpy(gear, "N");
    else snprintf(gear, sizeof(gear), "%d", t.gear);
    SetTextColor(dc, RGB(255, 255, 255));
    if (t.valid)
        snprintf(line, sizeof(line), "%3.0f km/h  %5.0f rpm  G%s", t.speedKmh, t.rpm < 0 ? 0.0f : t.rpm, gear);
    else
        snprintf(line, sizeof(line), "speed: unavailable");
    TextOutA(dc, 6, 3, line, (int)strlen(line));
    snprintf(line, sizeof(line), "RT %3.0f%%  LT %3.0f%%", rt * 100, lt * 100);
    SetTextColor(dc, RGB(220, 220, 220));
    TextOutA(dc, 6, 21, line, (int)strlen(line));
    if (t.nitrous >= 0)
    {
        snprintf(line, sizeof(line), "N2O %3.0f%%", t.nitrous * 100);
        SetTextColor(dc, RGB(120, 190, 255));
        TextOutA(dc, 250, 21, line, (int)strlen(line));
    }

    // Steering: what we send -> what the game's controls hold -> how fast the car turns.
    char gamePart[40], turnPart[24];
    if (game.valid)
        snprintf(gamePart, sizeof(gamePart), "game %+4.0f%%", game.steer * 100);
    else
    {
        LONG st = g_finderState;
        snprintf(gamePart, sizeof(gamePart), "game %s", st == FindScanning ? "scan" : st == FindWaitRelease ? "2/4"
            : st == FindWaitSteer ? "3/4" : st == FindVerify ? "4/4" : "1/4");
    }
    if (isfinite(turn))
        snprintf(turnPart, sizeof(turnPart), "%+5.0f\xB0/s", turn);
    else
        strcpy(turnPart, "   --");
    snprintf(line, sizeof(line), "STR %+4.0f%%  %s  %s", steer * 100, gamePart, turnPart);
    SetTextColor(dc, RGB(255, 220, 90));
    TextOutA(dc, 6, 39, line, (int)strlen(line));

    // Graph: last 10 s. Speed (cyan) scaled to the window's peak; RT (green) and LT (red) 0-100%.
    const int gx = 6, gy = 60, gw = kPanelW - 12, gh = kPanelH - 66;
    float peak = 100;
    for (const HistoryPoint& h : hist)
        peak = std::max(peak, h.speed);
    peak = ceilf(peak / 50) * 50;
    HPEN frame = CreatePen(PS_SOLID, 1, RGB(90, 90, 90));
    SelectObject(dc, frame);
    SelectObject(dc, GetStockObject(NULL_BRUSH));
    Rectangle(dc, gx - 1, gy - 1, gx + gw + 1, gy + gh + 1);
    SelectObject(dc, small);
    SetTextColor(dc, RGB(150, 150, 150));
    snprintf(line, sizeof(line), "%.0f km/h", peak);
    TextOutA(dc, gx + gw - 70, gy + 1, line, (int)strlen(line));

    POINT pts[kHistory];
    struct Series { COLORREF color; int which; } series[] = { { RGB(255, 80, 80), 2 }, { RGB(90, 220, 90), 1 }, { RGB(0, 220, 255), 0 } };
    for (const Series& sr : series)
    {
        for (int i = 0; i < kHistory; ++i)
        {
            const HistoryPoint& h = hist[(next + i) % kHistory];
            float v = sr.which == 0 ? h.speed / peak : sr.which == 1 ? h.rt : h.lt;
            pts[i].x = gx + i * (gw - 1) / (kHistory - 1);
            pts[i].y = gy + gh - 1 - (int)(std::min(std::max(v, 0.0f), 1.0f) * (gh - 2));
        }
        HPEN pen = CreatePen(PS_SOLID, sr.which == 0 ? 2 : 1, sr.color);
        HGDIOBJ old = SelectObject(dc, pen);
        Polyline(dc, pts, kHistory);
        SelectObject(dc, old);
        DeleteObject(pen);
    }
    SelectObject(dc, GetStockObject(BLACK_PEN));
    DeleteObject(frame);

    // GDI doesn't write alpha: give drawn pixels the content opacity and the rest the background one.
    BYTE contentA = (BYTE)(std::min(std::max(g_cfg.overlayOpacity, 0.0f), 1.0f) * 255);
    BYTE backA = (BYTE)(std::min(std::max(g_cfg.overlayBackground, 0.0f), 1.0f) * 255);
    for (int i = 0; i < kPanelW * kPanelH; ++i)
    {
        DWORD c = pixels[i] & 0xFFFFFF;
        if (!c)
        {
            pixels[i] = (DWORD)backA << 24;
            continue;
        }
        BYTE r = (BYTE)((c >> 16) * contentA / 255), g = (BYTE)(((c >> 8) & 0xFF) * contentA / 255), b = (BYTE)((c & 0xFF) * contentA / 255);
        pixels[i] = ((DWORD)contentA << 24) | ((DWORD)r << 16) | ((DWORD)g << 8) | b;
    }
}

static DWORD WINAPI OverlayThread(LPVOID)
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = (HINSTANCE)&__ImageBase;
    wc.lpszClassName = "InputBridgeTelemetry";
    RegisterClassA(&wc);
    HWND wnd = CreateWindowExA(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        wc.lpszClassName, "", WS_POPUP, 0, 0, kPanelW, kPanelH, nullptr, nullptr, wc.hInstance, nullptr);
    if (!wnd)
    {
        Log("Telemetry overlay: CreateWindow failed (%lu)", GetLastError());
        return 0;
    }
    HDC screen = GetDC(nullptr);
    HDC mem = CreateCompatibleDC(screen);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof(bi.bmiHeader);
    bi.bmiHeader.biWidth = kPanelW;
    bi.bmiHeader.biHeight = -kPanelH; // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    DWORD* pixels = nullptr;
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, (void**)&pixels, nullptr, 0);
    SelectObject(mem, bmp);
    Log("Telemetry overlay ready");

    bool shown = false;
    for (;;)
    {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        Sleep(50);

        HWND game = g_ff.window;
        bool show = g_cfg.overlay && g_inRace && game
            && (!g_cfg.overlayOnlyInFront || GetAncestor(GetForegroundWindow(), GA_ROOT) == GetAncestor(game, GA_ROOT));
        if (!show)
        {
            if (shown)
            {
                ShowWindow(wnd, SW_HIDE);
                Log("Telemetry overlay hidden");
            }
            shown = false;
            continue;
        }
        RECT rc;
        GetClientRect(GetAncestor(game, GA_ROOT), &rc);
        POINT origin = { rc.left + g_cfg.overlayX, rc.bottom - g_cfg.overlayBottom - kPanelH };
        ClientToScreen(GetAncestor(game, GA_ROOT), &origin);

        DrawPanel(mem, pixels);
        POINT src = { 0, 0 };
        SIZE size = { kPanelW, kPanelH };
        BLENDFUNCTION blend = { AC_SRC_OVER, 0, 255, AC_SRC_ALPHA };
        BOOL drawn = UpdateLayeredWindow(wnd, screen, &origin, &size, mem, &src, 0, &blend, ULW_ALPHA);
        if (!shown)
        {
            Log("Telemetry overlay shown at %ld,%ld (game client %ldx%ld), draw %s", origin.x, origin.y, rc.right, rc.bottom,
                drawn ? "ok" : "FAILED");
            SetWindowPos(wnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
            shown = true;
        }
    }
}

static void StartTelemetry()
{
    static LONG started;
    if (InterlockedExchange(&started, 1))
        return;
    InitializeCriticalSection(&g_telemetryLock);
    HANDLE t = CreateThread(nullptr, 0, TelemetryThread, nullptr, 0, nullptr);
    if (t)
        CloseHandle(t);
    t = CreateThread(nullptr, 0, OverlayThread, nullptr, 0, nullptr);
    if (t)
        CloseHandle(t);
}

// ---------------------------------------------------------------------------------------------
// Import hook

typedef HRESULT(WINAPI* DirectInput8CreateFn)(HINSTANCE, DWORD, REFIID, LPVOID*, LPUNKNOWN);
static DirectInput8CreateFn g_realCreate;

static HRESULT WINAPI HookedDirectInput8Create(HINSTANCE inst, DWORD version, REFIID riid, LPVOID* out, LPUNKNOWN outer)
{
    HRESULT hr = g_realCreate(inst, version, riid, out, outer);
    Log("DirectInput8Create(version=0x%04lX, %s) -> %s", (unsigned long)version, GuidStr(&riid), HrName(hr));
    if (SUCCEEDED(hr) && out && *out)
    {
        if (IsEqualGUID(riid, IID_IDirectInput8A))
            *out = new DirectInputProxy((IDirectInput8A*)*out);
        else
            Log("  not the ANSI interface; passing through unwrapped");
    }
    return hr;
}

// Replaces the game's import of DINPUT8.dll!DirectInput8Create. Returns false if not found.
static bool PatchImport()
{
    BYTE* base = (BYTE*)GetModuleHandleW(nullptr);
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); imp->Name; ++imp)
    {
        if (lstrcmpiA((const char*)(base + imp->Name), "dinput8.dll") != 0)
            continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA* funcs = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++funcs)
        {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            IMAGE_IMPORT_BY_NAME* byName = (IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData);
            if (strcmp((const char*)byName->Name, "DirectInput8Create") != 0)
                continue;
            DWORD old;
            VirtualProtect(&funcs->u1.Function, sizeof(funcs->u1.Function), PAGE_READWRITE, &old);
            g_realCreate = (DirectInput8CreateFn)funcs->u1.Function;
            funcs->u1.Function = (UINT_PTR)HookedDirectInput8Create;
            VirtualProtect(&funcs->u1.Function, sizeof(funcs->u1.Function), old, &old);
            return true;
        }
    }
    return false;
}

// ---------------------------------------------------------------------------------------------
// Default controller layout ([Controls] DefaultLayout)
//
// speed.exe v1.3 keeps the bindings in a live table at 0x91F418: 24 records of 0x34 bytes, the first 19 in the
// Controls menu's order (the 48 bytes a profile save stores per action are a record's +4..+0x33). Each record
// has four slots of (type, device, code): +4 keyboard, +0x10 second key, +0x1C controller, +0x28 second
// controller. The controller's defaults are not data: the function at 0x63CD80 hashes the pad's product name
// (the joystick object at *0x91F150, name at +0x114), picks hard-coded bindings for a few known pads or a generic
// set (A accelerate, X brake, no shifting...), and writes the controller slots of all 24 records. The game calls it
// when its input starts (0x63F850, so a new profile gets them), from the Controls menu's "restore defaults"
// (0x51D702), and when a loaded profile was saved with another pad (0x56E27D). Details: docs/controller-notes.md.
//
// We put a jump at 0x63CD80: the game's function runs as before, then, if the pad is one we make virtual (its name
// contains "XBOX", as for DeviceProxy), the 19 actions' controller slots become our layout and the second
// controller slots are cleared. Records 19-23 (menu navigation) stay the game's. The bytes are checked first.

struct LayoutEntry { DWORD type, index; };
// The chosen layout, in the Controls menu's order; the same as tools/mw-controls.py LAYOUT.
static const LayoutEntry kDefaultLayout[19] = {
    { 7, 0 }, // Accelerate: RT (Rx positive half)
    { 5, 2 }, // Brake / Reverse: LT (Z positive half)
    { 4, 0 }, // Steer Left: left stick left
    { 5, 0 }, // Steer Right: left stick right
    { 2, 1 }, // Handbrake: B
    { 2, 2 }, // Speedbreaker: X
    { 2, 0 }, // N2O: A
    { 7, 1 }, // Shift Down: right stick down
    { 6, 1 }, // Shift Up: right stick up
    { 2, 6 }, // Reset Car Position: Back
    { 3, 0 }, // Engage Event: D-pad up
    { 3, 2 }, // View Blacklist: D-pad down
    { 3, 3 }, // View World Map: D-pad left
    { 3, 1 }, // View SMS Messages: D-pad right
    { 2, 9 }, // Play Next Song: right stick click
    { 2, 5 }, // Change Camera View: RB
    { 2, 4 }, // Look Behind: LB
    { 2, 3 }, // Pull Camera Back: Y
    { 2, 7 }, // Pause: Start
};

static const DWORD kDefaultsFunc = 0x63CD80;   // the game's "controller defaults for this pad"
static const DWORD kBindingTable = 0x91F418;   // the live bindings table
static const DWORD kBindingStride = 0x34;
static const DWORD kJoystickPtr = 0x91F150;    // the first joystick object
static const DWORD kJoystickName = 0x114;      // its product name, inside the object
static BYTE* g_defaultsStub;                   // our code: the game's function, then ApplyDefaultLayout
static LONG g_defaultLayoutCalls;

// Reads game memory without risking a crash on an unmapped address.
static bool SafeRead(DWORD address, void* out, SIZE_T size)
{
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(UINT_PTR)address, out, size, &got) && got == size;
}

static bool BytesAre(DWORD address, const BYTE* expected, SIZE_T size)
{
    BYTE buf[32];
    return size <= sizeof(buf) && SafeRead(address, buf, size) && memcmp(buf, expected, size) == 0;
}

extern "C" void __cdecl ApplyDefaultLayout()
{
    LONG call = InterlockedIncrement(&g_defaultLayoutCalls);
    DWORD pad = 0;
    char name[128] = "";
    if (!SafeRead(kJoystickPtr, &pad, sizeof(pad)) || !pad)
    {
        Log("Default layout (call %ld): no controller; the game's defaults kept", call);
        return;
    }
    for (int i = 0; i < (int)sizeof(name) - 1; ++i)
        if (!SafeRead(pad + kJoystickName + i, &name[i], 1) || !name[i])
        {
            name[i] = 0;
            break;
        }
    name[sizeof(name) - 1] = 0;
    if (!g_cfg.virtualController || !ContainsNoCase(name, "XBOX"))
    {
        Log("Default layout (call %ld): controller \"%s\" is not one we make virtual; the game's defaults kept", call, name);
        return;
    }
    for (int i = 0; i < 19; ++i)
    {
        DWORD* rec = (DWORD*)(UINT_PTR)(kBindingTable + i * kBindingStride);
        rec[7] = kDefaultLayout[i].type;  // +0x1C controller: type, device 0, index
        rec[8] = 0;
        rec[9] = kDefaultLayout[i].index;
        rec[10] = rec[11] = rec[12] = 0;  // +0x28 second controller: none
    }
    Log("Default layout (call %ld): controller \"%s\": our layout written (RT accelerate, LT brake, right stick shifts)", call, name);
}

// Installs the jump at 0x63CD80. Returns a short description for the log.
static const char* InstallDefaultLayout()
{
    // The function's first instructions (mov eax, [0x91F150]; sub esp, 0x240), and three places that confirm the
    // table's address and record size: its copy loop's start (mov eax, 0x91F440) and end (cmp eax, 0x91F920), and
    // the bindings accessor 0x628CB0 (mov eax, [esp+4]; imul eax, eax, 0x34; add eax, 0x91F41C).
    static const BYTE entry[] = { 0xA1, 0x50, 0xF1, 0x91, 0x00, 0x81, 0xEC, 0x40, 0x02, 0x00, 0x00 };
    static const BYTE loopStart[] = { 0xB8, 0x40, 0xF4, 0x91, 0x00 };
    static const BYTE loopEnd[] = { 0x3D, 0x20, 0xF9, 0x91, 0x00 };
    static const BYTE accessor[] = { 0x8B, 0x44, 0x24, 0x04, 0x6B, 0xC0, 0x34, 0x05, 0x1C, 0xF4, 0x91, 0x00 };
    if (!BytesAre(kDefaultsFunc, entry, sizeof(entry)))
        return "refused: the bytes at 0x63CD80 are not the game's own (another version of speed.exe, or another module changed them)";
    if (!BytesAre(0x63EE8E, loopStart, sizeof(loopStart)) || !BytesAre(0x63EEC4, loopEnd, sizeof(loopEnd)) ||
        !BytesAre(0x628CB0, accessor, sizeof(accessor)))
        return "refused: the bindings table is not where speed.exe v1.3 keeps it";
    // Our code, in one executable block:
    //   stub:  call tramp; pushad; call ApplyDefaultLayout; popad; ret
    //   tramp: mov eax, [0x91F150]; jmp 0x63CD85        (the game's first instruction, then the rest of it)
    BYTE* code = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!code)
        return "failed: no memory for the hook";
    BYTE* p = code;
    BYTE* tramp = code + 32;
    *p++ = 0xE8; *(DWORD*)p = (DWORD)(tramp - (p + 4)); p += 4;
    *p++ = 0x60;
    *p++ = 0xE8; *(DWORD*)p = (DWORD)((BYTE*)&ApplyDefaultLayout - (p + 4)); p += 4;
    *p++ = 0x61;
    *p++ = 0xC3;
    memcpy(tramp, entry, 5);
    tramp[5] = 0xE9;
    *(DWORD*)(tramp + 6) = (DWORD)((kDefaultsFunc + 5) - (DWORD)(UINT_PTR)(tramp + 10));
    FlushInstructionCache(GetCurrentProcess(), code, 64);
    g_defaultsStub = code;
    DWORD old;
    BYTE* target = (BYTE*)(UINT_PTR)kDefaultsFunc;
    if (!VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &old))
        return "failed: could not make 0x63CD80 writable";
    target[0] = 0xE9;
    *(DWORD*)(target + 1) = (DWORD)(code - (target + 5));
    VirtualProtect(target, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), target, 5);
    return "installed at 0x63CD80";
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_DETACH)
    {
        // Don't leave the controller vibrating when the game exits.
        LONG index = g_padIndex;
        if (index >= 0)
        {
            XINPUT_VIBRATION off = {};
            XInputSetState(index, &off);
        }
        return TRUE;
    }
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);

    char exe[MAX_PATH];
    GetModuleFileNameA(nullptr, exe, MAX_PATH);
    const char* exeName = strrchr(exe, '\\') ? strrchr(exe, '\\') + 1 : exe;

    char path[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    if (dot)
        strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    LoadSettings(path);
    if (dot)
        strcpy(dot, ".log");

    InitializeCriticalSection(&g_logLock);
    InitializeCriticalSection(&g_ffLock);
    g_startTick = GetTickCount();
    char prevPath[MAX_PATH];
    strcpy(prevPath, path);
    strcpy(strrchr(prevPath, '.'), ".prev.log");
    MoveFileExA(path, prevPath, MOVEFILE_REPLACE_EXISTING); // keep the previous session's log
    g_log = fopen(path, "w");
    Log("InputBridge stage 2, host=%s virtualController=%d rumble=%d strength=%.2f", exeName,
        g_cfg.virtualController, g_cfg.rumble, g_cfg.strength);
    Log("Import hook %s", PatchImport() ? "installed" : "NOT FOUND (DirectInput8Create not imported)");
    Log("Default layout ([Controls] DefaultLayout): %s", g_cfg.defaultLayout ? InstallDefaultLayout() : "off");
    return TRUE;
}
