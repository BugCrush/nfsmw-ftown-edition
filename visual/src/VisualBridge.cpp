// VisualBridge.asi - works on the finished 3D picture before the HUD: ambient occlusion and a depth view from
// the scene's depth; auto-exposure and bloom (the Xbox 360 look, part 1; off since the pack is installed).
//
// When it runs, once a frame, whichever comes first:
//  - at the End of an effect technique named in [Game] Final (the Xbox 360 pack's "visualtreatment") while the
//    back buffer is the target: the pack's effects are made from memory, so their names are unknown and they
//    are known by their techniques' names instead;
//  - at the first Begin of a [Game] Before effect (the game's own HUD effects, IDI_FE_FX, IDI_FE_MASK_FX) while
//    the back buffer is the target and after a [Game] After effect (the game's glow pass) has run.
// There it copies the picture, applies what is switched on and draws the result back. The game then draws its
// HUD on top. Every piece of device state it touches is saved first and put back afterwards.
// The scene's depth: the INTZ depth texture the pack (X360Stuff) fills in its depth pre-pass, found when it is
// bound as the depth buffer in the frame (SetDepthStencilSurface).
// Settings: VisualBridge.ini (re-read when the file changes). Log: VisualBridge.log.
// Works on DXVK and on Windows' own Direct3D (whose state blocks wipe call-table hooks: they are put back).
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "shaders.h"
#include "sun.h"

// ---------------------------------------------------------------------------------------------
// Log and settings

static FILE* g_log;
static DWORD g_startTick;
static char g_iniPath[MAX_PATH];
static FILETIME g_iniTime;

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

struct Config
{
    bool enabled, exposure, bloom, ao, aa, haze, shafts, wet, split, identity, showDepth, showSun, aoHalf, sunFlipX, sunFlipY;
    float middleGrey, speedUp, speedDown, minScale, maxScale;
    float threshold, bloomScale, blurWidth;
    float aoStrength, aoRadius, depthNear, depthFar, fovY;
    bool depthFromGame;
    float aaStrength;
    float hazeStart, hazeEnd, hazeAmount, hazeColour[3];
    float shaftsStrength, shaftsLength, shaftsColour[3];
    // [Wet]: how much of the reflected colour is mixed in, steps and metres a ray goes, how upward a surface must face,
    // the screen-edge fade band, and the world's up direction ([Wet] UpAxis x, y or z).
    float wetStrength, wetMaxDistance, wetMinUp, wetEdgeFade, wetBlur, wetUp[3];
    int wetBlurSteps;
    int wetSteps;
    char wetUpAxis;
    DWORD sunView, sunCameraOffset, sunDirection; // [Sun]: where the game keeps the main view and the sun
    DWORD sunPlatOffset, sunClipOffset; // [Sun]: the view's platform info pointer, and its world-to-clip matrix in it
    DWORD sunInfo; // [Sun] Info: the game's SunInfo pointer; 0 there means no sun entry (the direction is a leftover)
    char finalShader[32];
    int toggleSeconds; // [Test] ToggleSeconds: > 0 switches the effects off and on every that many seconds
    // [Test] AOShowcase: with ToggleSeconds, occlusion steps through three sharpness levels ([AOShowcase] HalfN,
    // RadiusN), Blinks off-and-on blinks each, so they can be compared in one race.
    bool aoShowcase;
    bool failFullSizeAO; // [Test] FailFullSizeAO: the full-size occlusion targets are not made (stand-in tests of a failure)
    int showcaseBlinks;
    bool showcaseHalf[3];
    float showcaseRadius[3];
    char toggleOnly[16]; // [Test] ToggleOnly: "all" (every effect switches) or the one effect that does (ao, aa, ...)
    char after[8][48], before[8][48], final[8][48], passThrough[8][48];
    int afterCount, beforeCount, finalCount, passThroughCount;
};
static Config g_cfg;

// What runs in this pass: the settings after [Test] ToggleSeconds / ToggleOnly (see ToggledOn).
static struct { bool exposure, bloom, identity, ao, showDepth, aa, haze, shafts, showSun, wet; } g_on;
// The occlusion's size and reach for this pass: [AO] HalfResolution and Radius, or the showcase level's (see
// ShowcaseLevel); g_showcaseLevel is 1-3 while the showcase runs, else 0.
static bool g_aoHalfNow = true;
static float g_aoRadiusNow = 1.0f;
static int g_showcaseLevel;

static float IniFloat(const char* section, const char* key, const char* fallback)
{
    char text[32];
    GetPrivateProfileStringA(section, key, fallback, text, sizeof(text), g_iniPath);
    return (float)atof(text);
}

static int SplitNames(char* text, char names[][48])
{
    int count = 0;
    for (char* token = strtok(text, ", "); token && count < 8; token = strtok(nullptr, ", "))
        snprintf(names[count++], 48, "%s", token);
    return count;
}

static float Clamp(float v, float lo, float hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

// "r,g,b" with each 0..255, to 0..1.
static void IniColour(const char* section, const char* key, const char* fallback, float out[3])
{
    char text[48];
    GetPrivateProfileStringA(section, key, fallback, text, sizeof(text), g_iniPath);
    int r = 0, g = 0, b = 0;
    if (sscanf(text, "%d , %d , %d", &r, &g, &b) != 3)
        sscanf(fallback, "%d , %d , %d", &r, &g, &b);
    out[0] = Clamp(r / 255.0f, 0, 1);
    out[1] = Clamp(g / 255.0f, 0, 1);
    out[2] = Clamp(b / 255.0f, 0, 1);
}

static DWORD IniAddress(const char* section, const char* key, const char* fallback)
{
    char text[32];
    GetPrivateProfileStringA(section, key, fallback, text, sizeof(text), g_iniPath);
    return strtoul(text, nullptr, 0);
}

static void ReadConfig()
{
    char text[256];
    g_cfg.enabled = GetPrivateProfileIntA("Look", "Enabled", 1, g_iniPath) != 0;
    // Exposure and bloom change the pack's look, which the user keeps: off unless switched on.
    g_cfg.exposure = GetPrivateProfileIntA("Parts", "Exposure", 0, g_iniPath) != 0;
    g_cfg.bloom = GetPrivateProfileIntA("Parts", "Bloom", 0, g_iniPath) != 0;
    g_cfg.ao = GetPrivateProfileIntA("Parts", "AO", 0, g_iniPath) != 0;
    g_cfg.aa = GetPrivateProfileIntA("Parts", "AA", 0, g_iniPath) != 0;
    // How much of the smoothed colour replaces the pixel's own at an edge (0.75: thin lines keep most of their
    // contrast; docs/dev-log.md, "Picture: VisualBridge").
    g_cfg.aaStrength = Clamp(IniFloat("AA", "Strength", "0.75"), 0.0f, 1.0f);
    // Distance haze: nothing nearer than Start (metres), Amount of the way to Colour at End and beyond; the sky never.
    g_cfg.haze = GetPrivateProfileIntA("Parts", "Haze", 0, g_iniPath) != 0;
    g_cfg.hazeStart = Clamp(IniFloat("Haze", "Start", "150"), 0.0f, 100000.0f);
    g_cfg.hazeEnd = IniFloat("Haze", "End", "1500");
    if (g_cfg.hazeEnd < g_cfg.hazeStart + 1) g_cfg.hazeEnd = g_cfg.hazeStart + 1;
    g_cfg.hazeAmount = Clamp(IniFloat("Haze", "Amount", "0.15"), 0.0f, 1.0f);
    IniColour("Haze", "Colour", "200,210,225", g_cfg.hazeColour);
    // Light shafts: rays from the sun's place on screen through the gaps in what stands in front of the sky.
    g_cfg.shafts = GetPrivateProfileIntA("Parts", "Shafts", 0, g_iniPath) != 0;
    g_cfg.shaftsStrength = Clamp(IniFloat("Shafts", "Strength", "0.35"), 0.0f, 2.0f);
    g_cfg.shaftsLength = Clamp(IniFloat("Shafts", "Length", "0.6"), 0.05f, 1.0f);
    IniColour("Shafts", "Colour", "255,240,210", g_cfg.shaftsColour);
    g_cfg.showSun = GetPrivateProfileIntA("Debug", "ShowSun", 0, g_iniPath) != 0;
    // Wet reflections: drawn in the pass-through's draw, from depth and the main view's matrix (docs/visual-notes.md,
    // "Wet reflections"). The game's world has z up (evidence in the notes); the stand-in's has y up.
    g_cfg.wet = GetPrivateProfileIntA("Parts", "Wet", 0, g_iniPath) != 0;
    g_cfg.wetStrength = Clamp(IniFloat("Wet", "Strength", "0.25"), 0.0f, 1.0f);
    g_cfg.wetSteps = (int)Clamp((float)GetPrivateProfileIntA("Wet", "Steps", 16, g_iniPath), 1, 64);
    g_cfg.wetMaxDistance = Clamp(IniFloat("Wet", "MaxDistance", "40"), 1.0f, 1000.0f);
    g_cfg.wetMinUp = Clamp(IniFloat("Wet", "MinUp", "0.9"), 0.0f, 0.999f);
    g_cfg.wetEdgeFade = Clamp(IniFloat("Wet", "EdgeFade", "0.1"), 0.001f, 0.5f);
    // How soft the reflection is: the radius in pixels of the ring of extra samples around each reflected point (0 = sharp).
    g_cfg.wetBlur = Clamp(IniFloat("Wet", "Blur", "0"), 0.0f, 16.0f);
    // Steps for the four neighbours' rays of the blur (each covers MaxDistance in fewer, longer steps): fewer = cheaper.
    g_cfg.wetBlurSteps = (int)Clamp((float)GetPrivateProfileIntA("Wet", "BlurSteps", 8, g_iniPath), 1, 64);
    if (g_cfg.wetBlurSteps > g_cfg.wetSteps) g_cfg.wetBlurSteps = g_cfg.wetSteps;
    {
        char axis[8];
        GetPrivateProfileStringA("Wet", "UpAxis", "z", axis, sizeof(axis), g_iniPath);
        char c = (char)(axis[0] | 0x20);
        if (c != 'x' && c != 'y' && c != 'z')
        {
            Log("[Wet] UpAxis = %s is not x, y or z: z used", axis);
            c = 'z';
        }
        g_cfg.wetUpAxis = c;
        for (int i = 0; i < 3; ++i)
            g_cfg.wetUp[i] = (c - 'x') == i ? 1.0f : 0.0f;
    }
    // Found in speed.exe v1.3 (docs/visual-notes.md, "Camera and sun" and "The sun's place from the game's own
    // matrix"): the views are 0x70 bytes each from 0x9195E0 (eGetView, 0x405F80), so view 1 (EVIEW_PLAYER1, the
    // main view) is 0x919650 (0x919730, used in race 1, is view 3: the rear-view mirror). The view's platform info
    // pointer at +0, whose world-to-clip matrix at +0x80 the game rebuilds every frame (0x6CF400); its camera pointer
    // at +0x40 (the fallback, with [Depth] FovY); the sun's direction (WorldLightDirectionVector) at 0x8F2404.
    g_cfg.sunView = IniAddress("Sun", "View", "0x919650");
    g_cfg.sunPlatOffset = IniAddress("Sun", "PlatOffset", "0x0");
    g_cfg.sunClipOffset = IniAddress("Sun", "ClipOffset", "0x80");
    g_cfg.sunCameraOffset = IniAddress("Sun", "CameraOffset", "0x40");
    g_cfg.sunDirection = IniAddress("Sun", "Direction", "0x8F2404");
    g_cfg.sunInfo = IniAddress("Sun", "Info", "0x916054");
    g_cfg.sunFlipX = GetPrivateProfileIntA("Sun", "FlipX", 0, g_iniPath) != 0;
    g_cfg.sunFlipY = GetPrivateProfileIntA("Sun", "FlipY", 0, g_iniPath) != 0;
    g_cfg.split = GetPrivateProfileIntA("Test", "SplitScreen", 0, g_iniPath) != 0;
    g_cfg.identity = GetPrivateProfileIntA("Test", "Identity", 0, g_iniPath) != 0;
    g_cfg.toggleSeconds = GetPrivateProfileIntA("Test", "ToggleSeconds", 0, g_iniPath);
    // 0 (off) or 1 to 3600: the .ini is reread while the game runs, and a typo such as 536870912 would make
    // ToggleSeconds * 1000 wrap to 0 in 32 bits and divide by zero.
    if (g_cfg.toggleSeconds < 0 || g_cfg.toggleSeconds > 3600)
    {
        int used = g_cfg.toggleSeconds < 0 ? 0 : 3600;
        Log("[Test] ToggleSeconds = %d is outside 0..3600: %d used", g_cfg.toggleSeconds, used);
        g_cfg.toggleSeconds = used;
    }
    GetPrivateProfileStringA("Test", "ToggleOnly", "all", g_cfg.toggleOnly, sizeof(g_cfg.toggleOnly), g_iniPath);
    {
        // A misspelt name would switch nothing while the log still says it does: a cost measured on noise.
        static const char* const kNames[] = { "all", "exposure", "bloom", "identity", "ao", "depth", "aa", "haze", "shafts", "sun", "wet" };
        bool known = false;
        for (const char* n : kNames)
            known |= !lstrcmpiA(g_cfg.toggleOnly, n);
        if (!known)
        {
            Log("[Test] ToggleOnly = %s is not an effect's name (all, ao, aa, shafts, haze, wet, sun, depth, exposure, "
                "bloom, identity): every effect switches instead", g_cfg.toggleOnly);
            lstrcpyA(g_cfg.toggleOnly, "all");
        }
    }
    g_cfg.showDepth = GetPrivateProfileIntA("Debug", "ShowDepth", 0, g_iniPath) != 0;
    g_cfg.middleGrey = Clamp(IniFloat("Exposure", "MiddleGrey", "0.30"), 0.01f, 0.95f);
    g_cfg.speedUp = IniFloat("Exposure", "SpeedUp", "3.0");
    g_cfg.speedDown = IniFloat("Exposure", "SpeedDown", "1.0");
    g_cfg.minScale = IniFloat("Exposure", "Min", "0.7");
    g_cfg.maxScale = IniFloat("Exposure", "Max", "1.5");
    g_cfg.threshold = IniFloat("Bloom", "Threshold", "0.8");
    g_cfg.bloomScale = IniFloat("Bloom", "Scale", "0.6");
    g_cfg.blurWidth = IniFloat("Bloom", "Width", "1.5");
    // A negative speed would make the adapted value run away and never come back.
    if (g_cfg.speedUp < 0) g_cfg.speedUp = 0;
    if (g_cfg.speedDown < 0) g_cfg.speedDown = 0;
    if (g_cfg.maxScale < g_cfg.minScale) g_cfg.maxScale = g_cfg.minScale;
    g_cfg.aoStrength = Clamp(IniFloat("AO", "Strength", "0.6"), 0.0f, 1.0f);
    g_cfg.aoRadius = Clamp(IniFloat("AO", "Radius", "1.0"), 0.05f, 10.0f);
    g_cfg.aoHalf = GetPrivateProfileIntA("AO", "HalfResolution", 1, g_iniPath) != 0;
    g_cfg.aoShowcase = GetPrivateProfileIntA("Test", "AOShowcase", 0, g_iniPath) != 0;
    if (g_cfg.aoShowcase && g_cfg.toggleSeconds <= 0)
        Log("[Test] AOShowcase = 1 but ToggleSeconds = 0: the showcase steps with the toggle, so it does nothing");
    g_cfg.failFullSizeAO = GetPrivateProfileIntA("Test", "FailFullSizeAO", 0, g_iniPath) != 0;
    g_cfg.showcaseBlinks = (int)Clamp((float)GetPrivateProfileIntA("AOShowcase", "Blinks", 5, g_iniPath), 1, 100);
    {
        static const char* const kHalf[3] = { "Half1", "Half2", "Half3" };
        static const char* const kRadius[3] = { "Radius1", "Radius2", "Radius3" };
        static const char* const kRadiusDefault[3] = { "1.0", "0.6", "0.35" };
        for (int i = 0; i < 3; ++i)
        {
            g_cfg.showcaseHalf[i] = GetPrivateProfileIntA("AOShowcase", kHalf[i], i == 0 ? 1 : 0, g_iniPath) != 0;
            g_cfg.showcaseRadius[i] = Clamp(IniFloat("AOShowcase", kRadius[i], kRadiusDefault[i]), 0.05f, 10.0f);
        }
    }
    // The game's camera: near 0.5 m and far 10,000 m in the decompilation's Camera constructor; the field of
    // view is the vertical one in degrees (77 degrees across at 4:3 there, about 62 up and down).
    g_cfg.depthNear = Clamp(IniFloat("Depth", "Near", "0.5"), 0.01f, 100.0f);
    g_cfg.depthFar = IniFloat("Depth", "Far", "10000");
    if (g_cfg.depthFar < g_cfg.depthNear * 2) g_cfg.depthFar = g_cfg.depthNear * 2;
    // 1 = the near and far planes from the main view's own matrix each frame (Near/Far above only when it cannot be
    // read); 0 = Near/Far as set. The game's values are logged either way (the SUN line's planes=).
    g_cfg.depthFromGame = GetPrivateProfileIntA("Depth", "FromGame", 0, g_iniPath) != 0;
    g_cfg.fovY = Clamp(IniFloat("Depth", "FovY", "62"), 10.0f, 150.0f);
    GetPrivateProfileStringA("Test", "FinalShader", "Final", g_cfg.finalShader, sizeof(g_cfg.finalShader), g_iniPath);
    GetPrivateProfileStringA("Game", "After", "IDI_OVERBRIGHT_FX", text, sizeof(text), g_iniPath);
    g_cfg.afterCount = SplitNames(text, g_cfg.after);
    GetPrivateProfileStringA("Game", "Before", "IDI_FE_FX,IDI_FE_MASK_FX", text, sizeof(text), g_iniPath);
    g_cfg.beforeCount = SplitNames(text, g_cfg.before);
    GetPrivateProfileStringA("Game", "Final", "visualtreatment,visualtreatment_branching", text, sizeof(text), g_iniPath);
    g_cfg.finalCount = SplitNames(text, g_cfg.final);
    // The pack's pass-through: hdr.fx's technique that draws the treated picture onto the back buffer.
    GetPrivateProfileStringA("Game", "PassThrough", "screen_passthru", text, sizeof(text), g_iniPath);
    g_cfg.passThroughCount = SplitNames(text, g_cfg.passThrough);
}

static bool IniChanged()
{
    WIN32_FILE_ATTRIBUTE_DATA data;
    if (!GetFileAttributesExA(g_iniPath, GetFileExInfoStandard, &data))
        return false;
    if (!CompareFileTime(&data.ftLastWriteTime, &g_iniTime))
        return false;
    g_iniTime = data.ftLastWriteTime;
    return true;
}

// ---------------------------------------------------------------------------------------------
// Hooking (as GfxProbe does it). Windows' own Direct3D rewrites a device's whole call table when a state block
// is recorded (D3DX effects record one at Begin), which removes every hook; they are put back after it. Three
// cases: our hook is in place (nothing to do); the entry is back to what we first found there (the table was
// rewritten: put our hook back); something else is there (another plugin hooked on top of us and calls us in
// turn: leave it, or the two would call each other for ever).

enum { kMaxHooked = 32 };
static struct { void** entry; void* hook; void* original; } g_hooked[kMaxHooked];
static int g_hookedCount;

static void WriteEntry(void** entry, void* value)
{
    DWORD old;
    // The effect library's table is in its code section: keep the page executable while it is writable.
    VirtualProtect(entry, sizeof(void*), PAGE_EXECUTE_READWRITE, &old);
    *entry = value;
    VirtualProtect(entry, sizeof(void*), old, &old);
}

static void* HookSlot(void* object, int slot, void* hook)
{
    void** entry = &(*(void***)object)[slot];
    if (*entry == hook)
        return nullptr;
    for (int i = 0; i < g_hookedCount; ++i)
        if (g_hooked[i].entry == entry && g_hooked[i].hook == hook)
        {
            if (*entry == g_hooked[i].original)
                WriteEntry(entry, hook);
            return nullptr;
        }
    void* original = *entry;
    if (g_hookedCount < kMaxHooked)
        g_hooked[g_hookedCount++] = { entry, hook, original };
    WriteEntry(entry, hook);
    return original;
}

static bool PatchImport(const char* dll, const char* func, void* hook, void** original)
{
    BYTE* base = (BYTE*)GetModuleHandleW(nullptr);
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); imp->Name; ++imp)
    {
        if (lstrcmpiA((const char*)(base + imp->Name), dll) != 0)
            continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA* funcs = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++funcs)
        {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            if (strcmp((const char*)((IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData))->Name, func) != 0)
                continue;
            DWORD old;
            VirtualProtect(&funcs->u1.Function, sizeof(void*), PAGE_READWRITE, &old);
            *original = (void*)funcs->u1.Function;
            funcs->u1.Function = (UINT_PTR)hook;
            VirtualProtect(&funcs->u1.Function, sizeof(void*), old, &old);
            return true;
        }
    }
    return false;
}

// ---------------------------------------------------------------------------------------------
// The scene's depth: the INTZ depth texture bound as the depth buffer this frame (X360Stuff's pre-pass).
// Only its address is kept, never a reference: the pack releases it before a device Reset, and a reference
// held here would make that Reset fail. It is used only in the frame in which it was seen bound.

static const D3DFORMAT kIntz = (D3DFORMAT)MAKEFOURCC('I', 'N', 'T', 'Z');
static const GUID kIIDTexture = { 0x85c31227, 0x3de5, 0x4f00, { 0x9b, 0x3a, 0xf1, 0x1a, 0xc3, 0x8c, 0x18, 0xb5 } };
static IDirect3DSurface9* g_depthSurface; // the INTZ surface last found
static IDirect3DTexture9* g_depthTexture; // its texture
static UINT g_depthWidth, g_depthHeight;
static bool g_depthThisFrame; // bound at least once since the last Present
static UINT g_backWidth, g_backHeight; // the back buffer's size (0 = not read yet; read again after a Reset)

static void ForgetDepth()
{
    g_depthSurface = nullptr;
    g_depthTexture = nullptr;
    g_depthThisFrame = false;
    g_backWidth = g_backHeight = 0;
}

// Only an INTZ depth texture the size of the back buffer counts as the scene's depth: another one (a shadow map,
// say) bound in the same frame must not take its place. Surfaces that do not count are not remembered: a freed
// surface's address can come back as the pack's depth texture.
static void NoteDepth(IDirect3DDevice9* dev, IDirect3DSurface9* surface)
{
    if (surface == g_depthSurface)
    {
        g_depthThisFrame = true;
        return;
    }
    if (!g_backWidth)
    {
        IDirect3DSurface9* back = nullptr;
        D3DSURFACE_DESC bd;
        if (SUCCEEDED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) && SUCCEEDED(back->GetDesc(&bd)))
        {
            g_backWidth = bd.Width;
            g_backHeight = bd.Height;
        }
        if (back)
            back->Release();
    }
    D3DSURFACE_DESC desc;
    IDirect3DTexture9* texture = nullptr;
    if (SUCCEEDED(surface->GetDesc(&desc)) && desc.Format == kIntz && desc.Width == g_backWidth && desc.Height == g_backHeight
        && SUCCEEDED(surface->GetContainer(kIIDTexture, (void**)&texture)) && texture)
    {
        texture->Release(); // the surface's owner keeps it alive; see above
        g_depthSurface = surface;
        g_depthTexture = texture;
        g_depthWidth = desc.Width;
        g_depthHeight = desc.Height;
        g_depthThisFrame = true;
        Log("depth: INTZ %ux%u found (bound as the depth buffer)", desc.Width, desc.Height);
    }
}

// The scene's depth for this frame as a texture, or null when there is none (then every effect that needs it
// skips itself): seen bound in this frame and the size of the picture.
static IDirect3DTexture9* SceneDepth(IDirect3DDevice9* dev, UINT width, UINT height)
{
    (void)dev;
    if (!g_depthThisFrame || !g_depthTexture || g_depthWidth != width || g_depthHeight != height)
        return nullptr;
    return g_depthTexture;
}

// ---------------------------------------------------------------------------------------------
// The sun on screen: the game's main camera and sun direction, read from its memory each frame (checked readable
// first: an address that is wrong for this build reads as "no sun").

static bool Readable(DWORD address, size_t size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!address || !VirtualQuery((const void*)(UINT_PTR)address, &info, sizeof(info)) || info.State != MEM_COMMIT)
        return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE
        | PAGE_EXECUTE_WRITECOPY;
    if (!(info.Protect & readable) || (info.Protect & (PAGE_GUARD | PAGE_NOACCESS)))
        return false;
    return (UINT_PTR)address + size <= (UINT_PTR)info.BaseAddress + info.RegionSize;
}

// Like Readable, and the memory may be written (not read-only data or code).
static bool Writable(DWORD address, size_t size)
{
    MEMORY_BASIC_INFORMATION info;
    if (!Readable(address, size) || !VirtualQuery((const void*)(UINT_PTR)address, &info, sizeof(info)))
        return false;
    return (info.Protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0;
}

// The main view's world-to-clip matrix as the game drew this frame (view 1's platform info + 0x80; docs/visual-notes.md,
// "The sun's place from the game's own matrix"), copied out and checked: false when it cannot be read or is not a view's.
static bool ReadViewClip(float clip[16])
{
    DWORD platAt = g_cfg.sunView + g_cfg.sunPlatOffset;
    if (!Readable(platAt, 4))
        return false;
    DWORD plat = *(const DWORD*)(UINT_PTR)platAt;
    if (!plat || !Readable(plat + g_cfg.sunClipOffset, 16 * sizeof(float)))
        return false;
    memcpy(clip, (const void*)(UINT_PTR)(plat + g_cfg.sunClipOffset), 16 * sizeof(float));
    return ClipMatrixPlausible(clip);
}

// The tangents of half the main view's field of view, across and up/down, for turning depth into positions
// (occlusion): from the view's own matrix as the game drew this frame (the game widens its view at speed, about
// 106 x 76 degrees while racing), else from [Depth] FovY. Which one is logged when it changes.
static void ViewTans(UINT width, UINT height, float* tanX, float* tanY)
{
    static int lastSource = -1;
    float clip[16];
    int source = 0;
    if (ReadViewClip(clip))
    {
        float n0 = sqrtf(clip[0] * clip[0] + clip[4] * clip[4] + clip[8] * clip[8]);
        float n1 = sqrtf(clip[1] * clip[1] + clip[5] * clip[5] + clip[9] * clip[9]);
        float n3 = sqrtf(clip[3] * clip[3] + clip[7] * clip[7] + clip[11] * clip[11]);
        if (n0 > 0 && n1 > 0)
        {
            *tanX = n3 / n0;
            *tanY = n3 / n1;
            source = 1;
        }
    }
    if (!source)
    {
        *tanY = tanf(g_cfg.fovY * 3.14159265f / 360);
        *tanX = *tanY * width / height;
    }
    if (source != lastSource)
    {
        if (source)
            Log("view field of view: from the game's view (%.1f x %.1f degrees)", 2 * atanf(*tanX) * 57.2957795f,
                2 * atanf(*tanY) * 57.2957795f);
        else
            Log("view field of view: from [Depth] FovY (%.1f degrees up/down): the view's matrix cannot be read", g_cfg.fovY);
        lastSource = source;
    }
}

// The camera's near and far planes, to turn stored depth into metres: from the main view's own matrix
// (ClipNearFar) when [Depth] FromGame = 1 and it can be read, else [Depth] Near/Far. The game's values, when readable,
// are kept for the log (g_gameNear/Far, 0 when not), and which source is used is logged whenever it changes.
static float g_gameNear, g_gameFar;

static void DepthPlanes(float* nearOut, float* farOut)
{
    static int lastSource = -1;
    float clip[16], n = 0, f = 0;
    bool game = ReadViewClip(clip) && ClipNearFar(clip, &n, &f);
    g_gameNear = game ? n : 0;
    g_gameFar = game ? f : 0;
    int source = game && g_cfg.depthFromGame ? 1 : 0;
    *nearOut = source ? n : g_cfg.depthNear;
    *farOut = source ? f : g_cfg.depthFar;
    if (source != lastSource)
    {
        if (source)
            Log("depth planes: from the game's view (near %.3f far %.0f)", n, f);
        else
            Log("depth planes: from [Depth] Near/Far (%.3f, %.0f)%s", g_cfg.depthNear, g_cfg.depthFar,
                g_cfg.depthFromGame ? ": the view's matrix cannot be read" : "");
        lastSource = source;
    }
}

struct Sun
{
    bool on;          // in front of the camera
    float x, y;       // screen place, 0..1 (outside = off screen)
    float facing;     // cosine between the view's direction and the sun
    float fade;       // 1 = well inside the screen and in front; 0 = no rays
    float dir[3], forward[3];
    DWORD camera, info;
    // Which projection gave the place: the game's own world-to-clip matrix for the view (true), or the fallback, the
    // view's camera with [Depth] FovY (false); with the game's, its field of view across and up/down (degrees).
    bool game;
    bool projected; // either projection ran (false: no sun entry, or nothing readable: the SUN line says proj=none)
    float gameFovX, gameFovY;
    // For the log: the camera's own field of view (a 16-bit angle at camera+0xC4, 65536 = 360 degrees) and the
    // view's (a float at view+0x1C).
    unsigned cameraFov;
    float viewFov;
};

static Sun ReadSun(UINT width, UINT height)
{
    Sun sun = {};
    // No sun entry (SunInfo 0): the game then leaves the last direction in memory and its own GetSunPos (0x4FD4F0)
    // says "no sun"; so do we.
    if (!Readable(g_cfg.sunInfo, 4))
        return sun;
    sun.info = *(const DWORD*)(UINT_PTR)g_cfg.sunInfo;
    if (!sun.info || !Readable(g_cfg.sunDirection, 12))
        return sun;
    memcpy(sun.dir, (const void*)(UINT_PTR)g_cfg.sunDirection, sizeof(sun.dir));
    if (Readable(g_cfg.sunView + 0x1C, 4))
        sun.viewFov = *(const float*)(UINT_PTR)(g_cfg.sunView + 0x1C);
    DWORD cameraAt = g_cfg.sunView + g_cfg.sunCameraOffset;
    const float* m = nullptr;
    if (Readable(cameraAt, 4))
    {
        sun.camera = *(const DWORD*)(UINT_PTR)cameraAt;
        if (Readable(sun.camera, 64))
            m = (const float*)(UINT_PTR)sun.camera;
        if (Readable(sun.camera + 0xC4, 2))
            sun.cameraFov = *(const unsigned short*)(UINT_PTR)(sun.camera + 0xC4);
    }
    // The game's own matrix for this view, as it drew this frame: it carries the field of view the game is using
    // (wider at speed), so nothing is assumed. Copied first, then checked: not a view matrix means the fallback.
    float clip[16];
    sun.game = ReadViewClip(clip);
    if (sun.game)
    {
        ClipFov(clip, &sun.gameFovX, &sun.gameFovY);
        float n = sqrtf(clip[3] * clip[3] + clip[7] * clip[7] + clip[11] * clip[11]);
        for (int i = 0; i < 3; ++i)
            sun.forward[i] = clip[i * 4 + 3] / n;
        sun.on = SunScreenClip(clip, sun.dir, &sun.x, &sun.y, &sun.facing);
        sun.projected = true;
    }
    else
    {
        if (!m)
            return sun;
        for (int i = 0; i < 3; ++i)
            sun.forward[i] = m[i * 4 + 2];
        float tanY = tanf(g_cfg.fovY * 3.14159265f / 360), tanX = tanY * width / height;
        sun.on = SunScreen(m, sun.dir, tanX, tanY, &sun.x, &sun.y, &sun.facing);
        sun.projected = true;
    }
    if (!sun.on)
        return sun;
    if (g_cfg.sunFlipX) sun.x = 1 - sun.x;
    if (g_cfg.sunFlipY) sun.y = 1 - sun.y;
    // Full rays while the sun is on screen; fading out to nothing a quarter of the screen beyond its edges, and as
    // the sun nears the side of the view (no streaks from the screen's edge).
    float outside = fmaxf(fmaxf(fabsf(sun.x - 0.5f), fabsf(sun.y - 0.5f)) - 0.5f, 0.0f);
    sun.fade = Clamp(1 - outside / 0.25f, 0, 1) * Clamp((sun.facing - 0.1736f) / 0.2f, 0, 1);
    return sun;
}

static Sun g_sun;      // this frame's, read at the pass
static Sun g_sunShown; // the last one read, for the log

// ---------------------------------------------------------------------------------------------
// Shaders and textures

enum { kDown4, kLogLum, kAdapt, kBright, kBlur, kFinal, kShaderCount };
static const char* const kShaderName[kShaderCount] = { "Down4", "LogLum", "Adapt", "Bright", "Blur", "Final" };
static IDirect3DPixelShader9* g_shader[kShaderCount];
static bool g_shadersTried, g_shadersReady;
enum { kDepthView, kAO, kAOBlur, kAOApply, kAOFactor, kSmooth, kHaze, kShaftsMask, kShaftsApply, kWet, kSmoothWet, kShader3Count };
static const char* const kShader3Name[kShader3Count] = { "DepthView", "AO", "AOBlur", "AOApply", "AOFactor", "Smooth", "Haze",
    "ShaftsMask", "ShaftsApply", "Wet", "SmoothWet" };
enum { kFirstWetShader = kWet };
static IDirect3DPixelShader9* g_shader3[kShader3Count];
static IDirect3DVertexShader9* g_pass3VS;
static bool g_shaders3Tried, g_shaders3Ready;

struct Target
{
    IDirect3DTexture9* texture;
    IDirect3DSurface9* surface;
    UINT width, height;
};
enum { kScene, kQuarter, kLum64, kLum16, kLum4, kLum1, kAdaptedA, kAdaptedB, kBloomA, kBloomB, kWork, kOccA, kOccB, kTargetCount };
// kWork, kOccA and kOccB are made only when an effect that reads depth runs (EnsureDepthResources).
enum { kFirstDepthTarget = kWork };
static Target g_target[kTargetCount];
static IDirect3DSurface9* g_readback; // 1x1 in system memory, for the log
static bool g_resourcesReady, g_resourcesFailed, g_firstFrame;
static bool g_depthResourcesReady, g_depthResourcesFailed;
static Target g_shaftsTarget; // the rays at a quarter of the picture's size (made when shafts first run)
static bool g_shaftsFailed;
static int g_adaptedNow; // kAdaptedA or kAdaptedB: which one holds the current value

// Graphics-card time of an effect, from timestamp queries read back a few frames later (never waited for): one set
// for the occlusion (ao_ms), one for the edge smoothing (aa_ms).
enum { kTimers = 4 };
struct TimerSet
{
    struct { IDirect3DQuery9* disjoint, * start, * end, * frequency; bool pending; } slot[kTimers];
    int next;
    bool made, failed;
    double sum;
    int count;
};
static TimerSet g_aoTimer, g_aaTimer, g_shaftsTimer, g_wetTimer;

static void TimerRelease(TimerSet& set)
{
    for (auto& t : set.slot)
    {
        if (t.disjoint) t.disjoint->Release();
        if (t.start) t.start->Release();
        if (t.end) t.end->Release();
        if (t.frequency) t.frequency->Release();
        t = {};
    }
    set.made = set.failed = false;
}

// Makes the queries once; false (and nothing timed) where the device has none.
static bool TimerMake(IDirect3DDevice9* dev, TimerSet& set, const char* name)
{
    if (set.made || set.failed)
        return set.made;
    for (auto& t : set.slot)
        if (FAILED(dev->CreateQuery(D3DQUERYTYPE_TIMESTAMPDISJOINT, &t.disjoint)) || FAILED(dev->CreateQuery(D3DQUERYTYPE_TIMESTAMP, &t.start))
            || FAILED(dev->CreateQuery(D3DQUERYTYPE_TIMESTAMP, &t.end)) || FAILED(dev->CreateQuery(D3DQUERYTYPE_TIMESTAMPFREQ, &t.frequency)))
        {
            TimerRelease(set);
            set.failed = true;
            Log("timing queries not available: %s_ms stays -1", name);
            return false;
        }
    set.made = true;
    return true;
}

// Starts timing; returns the slot to end it with, or -1 (no queries, or all still waiting for their results).
static int TimerBegin(TimerSet& set)
{
    auto& t = set.slot[set.next];
    if (!set.made || t.pending)
        return -1;
    t.disjoint->Issue(D3DISSUE_BEGIN);
    t.start->Issue(D3DISSUE_END);
    return set.next;
}

static void TimerEnd(TimerSet& set, int which)
{
    if (which < 0)
        return;
    auto& t = set.slot[which];
    t.end->Issue(D3DISSUE_END);
    t.disjoint->Issue(D3DISSUE_END);
    t.frequency->Issue(D3DISSUE_END);
    t.pending = true;
    set.next = (set.next + 1) % kTimers;
}

typedef HRESULT(WINAPI* CompileFn)(LPCSTR, UINT, const D3DXMACRO*, ID3DXInclude*, LPCSTR, LPCSTR, DWORD, ID3DXBuffer**,
    ID3DXBuffer**, ID3DXConstantTable**);

static CompileFn Compiler()
{
    HMODULE library = GetModuleHandleA("d3dx9_26.dll");
    return library ? (CompileFn)GetProcAddress(library, "D3DXCompileShader") : nullptr;
}

static void CompileShaders(IDirect3DDevice9* dev)
{
    g_shadersTried = true;
    CompileFn compile = Compiler();
    if (!compile)
    {
        Log("shaders FAILED: d3dx9_26.dll is not loaded");
        return;
    }
    for (int i = 0; i < kShaderCount; ++i)
    {
        const char* name = i == kFinal ? g_cfg.finalShader : kShaderName[i];
        ID3DXBuffer* code = nullptr, * errors = nullptr;
        HRESULT hr = compile(kShaderSource, (UINT)strlen(kShaderSource), nullptr, nullptr, name, "ps_2_0", 0, &code, &errors, nullptr);
        if (SUCCEEDED(hr))
            hr = dev->CreatePixelShader((const DWORD*)code->GetBufferPointer(), &g_shader[i]);
        if (FAILED(hr))
        {
            Log("shader %s FAILED: 0x%08lX %s", name, (unsigned long)hr, errors ? (const char*)errors->GetBufferPointer() : "");
            return;
        }
        if (code) code->Release();
    }
    g_shadersReady = true;
    Log("shaders compiled");
}

static bool WetShadersReady(IDirect3DDevice9* dev);

// The depth passes' shaders, compiled the first time one of them is wanted.
static void CompileShaders3(IDirect3DDevice9* dev)
{
    g_shaders3Tried = true;
    CompileFn compile = Compiler();
    if (!compile)
        return;
    for (int i = -1; i < kFirstWetShader; ++i)
    {
        const char* name = i < 0 ? "Pass3VS" : kShader3Name[i];
        ID3DXBuffer* code = nullptr, * errors = nullptr;
        HRESULT hr = compile(kShader3Source, (UINT)strlen(kShader3Source), nullptr, nullptr, name, i < 0 ? "vs_3_0" : "ps_3_0", 0,
            &code, &errors, nullptr);
        if (SUCCEEDED(hr))
            hr = i < 0 ? dev->CreateVertexShader((const DWORD*)code->GetBufferPointer(), &g_pass3VS)
                       : dev->CreatePixelShader((const DWORD*)code->GetBufferPointer(), &g_shader3[i]);
        if (FAILED(hr))
        {
            Log("shader %s FAILED: 0x%08lX %s", name, (unsigned long)hr, errors ? (const char*)errors->GetBufferPointer() : "");
            return;
        }
        if (code) code->Release();
    }
    g_shaders3Ready = true;
    Log("depth shaders compiled");
    // With wet reflections on, their slow compile starts now on the worker thread, after this one: the compiler does
    // one compile at a time (a compile here waited for the worker's when both ran at once).
    if (g_cfg.wet)
        WetShadersReady(nullptr);
}

// The wet reflections' two shaders. Compiling them takes seconds with the game's compiler (SmoothWet about 5 s on
// this laptop, `visual/tests/shader-compile-time.cpp`), which would stall the game's frame: they are compiled on a
// worker thread the first time reflections are wanted (compiling needs no device), and made into shaders on the game's
// thread once ready. Until then the pass-through's draw is smoothing alone (or the pack's own).
static bool g_wetShadersTried, g_wetShadersReady;
static volatile LONG g_wetCompileState; // 0 not started or running, 1 compiled, -1 failed
static ID3DXBuffer* g_wetCode[kShader3Count];
static char g_wetCompileError[256];
static DWORD g_wetCompileMs;

static DWORD WINAPI CompileWetWorker(LPVOID)
{
    CompileFn compile = Compiler();
    DWORD start = GetTickCount();
    LONG result = 1;
    for (int i = kFirstWetShader; i < kShader3Count && compile; ++i)
    {
        ID3DXBuffer* errors = nullptr;
        HRESULT hr = compile(kShader3Source, (UINT)strlen(kShader3Source), nullptr, nullptr, kShader3Name[i], "ps_3_0", 0, &g_wetCode[i],
            &errors, nullptr);
        if (FAILED(hr))
        {
            snprintf(g_wetCompileError, sizeof(g_wetCompileError), "%s 0x%08lX %s", kShader3Name[i], (unsigned long)hr,
                errors ? (const char*)errors->GetBufferPointer() : "");
            result = -1;
            break;
        }
        if (errors) errors->Release();
    }
    if (!compile)
        result = -1;
    g_wetCompileMs = GetTickCount() - start;
    InterlockedExchange(&g_wetCompileState, result);
    return 0;
}

// Called on the game's thread: starts the compile once, and makes the shaders when it is done. True when ready.
static bool WetShadersReady(IDirect3DDevice9* dev)
{
    if (g_wetShadersReady)
        return true;
    if (!g_wetShadersTried)
    {
        g_wetShadersTried = true;
        HANDLE thread = CreateThread(nullptr, 0, CompileWetWorker, nullptr, 0, nullptr);
        if (!thread)
        {
            InterlockedExchange(&g_wetCompileState, -1);
            snprintf(g_wetCompileError, sizeof(g_wetCompileError), "no worker thread");
        }
        else
        {
            CloseHandle(thread);
            Log("wet shaders: compiling on a worker thread");
        }
        return false;
    }
    LONG state = InterlockedCompareExchange(&g_wetCompileState, 0, 0);
    if (state == 0 || !dev)
        return false;
    if (state < 0)
    {
        static bool logged;
        if (!logged)
            Log("wet shaders FAILED: %s: wet reflections stay off", g_wetCompileError);
        logged = true;
        return false;
    }
    bool made = true;
    for (int i = kFirstWetShader; i < kShader3Count && made; ++i)
        if (FAILED(dev->CreatePixelShader((const DWORD*)g_wetCode[i]->GetBufferPointer(), &g_shader3[i])))
        {
            Log("wet shader %s could not be made: wet reflections stay off", kShader3Name[i]);
            made = false;
        }
    // The compiled code is no longer needed once the shaders exist (or cannot be made); on a failure the ones already
    // made are released too.
    for (int i = kFirstWetShader; i < kShader3Count; ++i)
    {
        if (g_wetCode[i])
            g_wetCode[i]->Release();
        g_wetCode[i] = nullptr;
        if (!made && g_shader3[i])
        {
            g_shader3[i]->Release();
            g_shader3[i] = nullptr;
        }
    }
    if (!made)
    {
        InterlockedExchange(&g_wetCompileState, -1);
        return false;
    }
    g_wetShadersReady = true;
    Log("wet shaders compiled (%lu ms, on the worker thread)", (unsigned long)g_wetCompileMs);
    return true;
}

static void ReleaseTarget(Target& t)
{
    if (t.surface) t.surface->Release();
    if (t.texture) t.texture->Release();
    t = {};
}

static void ReleaseDepthResources()
{
    for (int i = kFirstDepthTarget; i < kTargetCount; ++i)
        ReleaseTarget(g_target[i]);
    TimerRelease(g_aoTimer);
    TimerRelease(g_shaftsTimer);
    ReleaseTarget(g_shaftsTarget);
    g_shaftsFailed = false;
    g_depthResourcesReady = false;
}

static void ReleaseResources()
{
    for (int i = 0; i < kFirstDepthTarget; ++i)
        ReleaseTarget(g_target[i]);
    if (g_readback) g_readback->Release();
    g_readback = nullptr;
    g_resourcesReady = false;
    ReleaseDepthResources();
    TimerRelease(g_aaTimer);
    TimerRelease(g_wetTimer);
}

static bool MakeTarget(IDirect3DDevice9* dev, int which, UINT width, UINT height, D3DFORMAT format)
{
    Target& t = which < 0 ? g_shaftsTarget : g_target[which];
    t.width = width;
    t.height = height;
    return SUCCEEDED(dev->CreateTexture(width, height, 1, D3DUSAGE_RENDERTARGET, format, D3DPOOL_DEFAULT, &t.texture, nullptr))
        && SUCCEEDED(t.texture->GetSurfaceLevel(0, &t.surface));
}

// The picture copy is 8-bit like the picture; everything computed from it is 16-bit floating point so
// that exposure can push values above white before the bloom threshold is taken.
static bool EnsureResources(IDirect3DDevice9* dev, UINT width, UINT height)
{
    if (g_resourcesReady && g_target[kScene].width == width && g_target[kScene].height == height)
        return true;
    if (g_resourcesFailed)
        return false;
    ReleaseResources();
    const D3DFORMAT wide = D3DFMT_A16B16G16R16F;
    bool ok = MakeTarget(dev, kScene, width, height, D3DFMT_A8R8G8B8)
        && MakeTarget(dev, kQuarter, width / 4, height / 4, wide) && MakeTarget(dev, kLum64, 64, 64, wide)
        && MakeTarget(dev, kLum16, 16, 16, wide) && MakeTarget(dev, kLum4, 4, 4, wide) && MakeTarget(dev, kLum1, 1, 1, wide)
        && MakeTarget(dev, kAdaptedA, 1, 1, D3DFMT_A32B32G32R32F) && MakeTarget(dev, kAdaptedB, 1, 1, D3DFMT_A32B32G32R32F)
        && MakeTarget(dev, kBloomA, width / 4, height / 4, wide) && MakeTarget(dev, kBloomB, width / 4, height / 4, wide)
        && SUCCEEDED(dev->CreateOffscreenPlainSurface(1, 1, D3DFMT_A32B32G32R32F, D3DPOOL_SYSTEMMEM, &g_readback, nullptr));
    if (!ok)
    {
        ReleaseResources();
        g_resourcesFailed = true;
        Log("resources FAILED for %ux%u: the effect stays off", width, height);
        return false;
    }
    // Nothing may be read before it is written: start every target black.
    for (int i = 0; i < kFirstDepthTarget; ++i)
        dev->ColorFill(g_target[i].surface, nullptr, 0);
    g_resourcesReady = true;
    g_firstFrame = true;
    g_adaptedNow = kAdaptedA;
    Log("resources created %ux%u", width, height);
    return true;
}

// The work picture (8-bit, the size of the picture) and the occlusion at half or full size (16-bit floating
// point: visibility and distance), and the timing queries.
static bool EnsureDepthResources(IDirect3DDevice9* dev, UINT width, UINT height)
{
    UINT ow = g_aoHalfNow ? width / 2 : width, oh = g_aoHalfNow ? height / 2 : height;
    if (g_depthResourcesReady && g_target[kWork].width == width && g_target[kWork].height == height && g_target[kOccA].width == ow
        && g_target[kOccA].height == oh)
        return true;
    if (g_depthResourcesFailed)
        return false;
    ReleaseDepthResources();
    bool ok = !(g_cfg.failFullSizeAO && !g_aoHalfNow) && MakeTarget(dev, kWork, width, height, D3DFMT_A8R8G8B8)
        && MakeTarget(dev, kOccA, ow, oh, D3DFMT_A16B16G16R16F)
        && MakeTarget(dev, kOccB, ow, oh, D3DFMT_A16B16G16R16F);
    if (!ok)
    {
        ReleaseDepthResources();
        g_depthResourcesFailed = true;
        Log("depth resources FAILED for %ux%u: occlusion and the depth view stay off", width, height);
        return false;
    }
    for (int i = kFirstDepthTarget; i < kTargetCount; ++i)
        dev->ColorFill(g_target[i].surface, nullptr, 0);
    TimerMake(dev, g_aoTimer, "ao");
    g_depthResourcesReady = true;
    Log("ao resolution %ux%u", ow, oh);
    return true;
}

// Reads back whichever timings have arrived; never waits.
static void CollectTimings(TimerSet& set)
{
    if (!set.made)
        return;
    for (auto& timer : set.slot)
    {
        if (!timer.pending)
            continue;
        BOOL disjoint = TRUE;
        UINT64 start = 0, end = 0, frequency = 0;
        if (timer.disjoint->GetData(&disjoint, sizeof(disjoint), 0) != S_OK || timer.start->GetData(&start, sizeof(start), 0) != S_OK
            || timer.end->GetData(&end, sizeof(end), 0) != S_OK || timer.frequency->GetData(&frequency, sizeof(frequency), 0) != S_OK)
            continue;
        timer.pending = false;
        if (!disjoint && frequency && end >= start)
        {
            set.sum += (double)(end - start) * 1000.0 / (double)frequency;
            ++set.count;
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Device state: everything the pass changes, saved before and put back after

static const D3DRENDERSTATETYPE kRenderStates[] = { D3DRS_ZENABLE, D3DRS_ZWRITEENABLE, D3DRS_ALPHABLENDENABLE,
    D3DRS_SRCBLEND, D3DRS_DESTBLEND, D3DRS_BLENDOP, D3DRS_SEPARATEALPHABLENDENABLE,
    D3DRS_ALPHATESTENABLE, D3DRS_CULLMODE, D3DRS_FOGENABLE, D3DRS_STENCILENABLE, D3DRS_SCISSORTESTENABLE,
    D3DRS_COLORWRITEENABLE, D3DRS_SRGBWRITEENABLE, D3DRS_CLIPPLANEENABLE, D3DRS_FILLMODE };
static const D3DSAMPLERSTATETYPE kSamplerStates[] = { D3DSAMP_MINFILTER, D3DSAMP_MAGFILTER, D3DSAMP_MIPFILTER,
    D3DSAMP_ADDRESSU, D3DSAMP_ADDRESSV, D3DSAMP_SRGBTEXTURE };
enum { kRenderStateCount = sizeof(kRenderStates) / sizeof(kRenderStates[0]),
       kSamplerStateCount = sizeof(kSamplerStates) / sizeof(kSamplerStates[0]), kStages = 4, kConstants = 18 };

struct Saved
{
    IDirect3DSurface9* target;
    IDirect3DSurface9* depth;
    D3DVIEWPORT9 viewport;
    RECT scissor;
    DWORD texCoordIndex, texTransform; // texture stage 0: our quad's coordinates go through the fixed vertex path
    IDirect3DVertexShader9* vertexShader;
    IDirect3DPixelShader9* pixelShader;
    IDirect3DVertexDeclaration9* declaration;
    DWORD fvf;
    IDirect3DVertexBuffer9* stream;
    UINT streamOffset, streamStride;
    IDirect3DBaseTexture9* texture[kStages];
    DWORD sampler[kStages][kSamplerStateCount];
    DWORD render[kRenderStateCount];
    float constants[kConstants][4];
    int intConstant[8]; // i0, i1 (the wet shaders' loop counts)
};

static void SaveState(IDirect3DDevice9* dev, Saved& s)
{
    memset(&s, 0, sizeof(s));
    dev->GetRenderTarget(0, &s.target);
    dev->GetDepthStencilSurface(&s.depth);
    dev->GetViewport(&s.viewport);
    dev->GetScissorRect(&s.scissor);
    dev->GetTextureStageState(0, D3DTSS_TEXCOORDINDEX, &s.texCoordIndex);
    dev->GetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, &s.texTransform);
    dev->GetVertexShader(&s.vertexShader);
    dev->GetPixelShader(&s.pixelShader);
    dev->GetVertexDeclaration(&s.declaration);
    dev->GetFVF(&s.fvf);
    dev->GetStreamSource(0, &s.stream, &s.streamOffset, &s.streamStride);
    for (int i = 0; i < kStages; ++i)
    {
        dev->GetTexture(i, &s.texture[i]);
        for (int k = 0; k < kSamplerStateCount; ++k)
            dev->GetSamplerState(i, kSamplerStates[k], &s.sampler[i][k]);
    }
    for (int k = 0; k < kRenderStateCount; ++k)
        dev->GetRenderState(kRenderStates[k], &s.render[k]);
    dev->GetPixelShaderConstantF(0, s.constants[0], kConstants);
    dev->GetPixelShaderConstantI(0, s.intConstant, 2);
}

static void RestoreState(IDirect3DDevice9* dev, Saved& s)
{
    dev->SetRenderTarget(0, s.target);
    dev->SetDepthStencilSurface(s.depth);
    dev->SetViewport(&s.viewport);
    dev->SetScissorRect(&s.scissor); // SetRenderTarget resets it, like the viewport
    dev->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, s.texCoordIndex);
    dev->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, s.texTransform);
    dev->SetVertexShader(s.vertexShader);
    dev->SetPixelShader(s.pixelShader);
    // A declaration and a vertex format are two ways of saying the same thing; setting one replaces the
    // other. Put back whichever the game had: its declaration if there was one, else its format.
    if (s.declaration)
        dev->SetVertexDeclaration(s.declaration);
    else if (s.fvf)
        dev->SetFVF(s.fvf);
    else
        dev->SetVertexDeclaration(nullptr);
    dev->SetStreamSource(0, s.stream, s.streamOffset, s.streamStride); // DrawPrimitiveUP clears stream 0
    for (int i = 0; i < kStages; ++i)
    {
        dev->SetTexture(i, s.texture[i]);
        for (int k = 0; k < kSamplerStateCount; ++k)
            dev->SetSamplerState(i, kSamplerStates[k], s.sampler[i][k]);
    }
    for (int k = 0; k < kRenderStateCount; ++k)
        dev->SetRenderState(kRenderStates[k], s.render[k]);
    dev->SetPixelShaderConstantF(0, s.constants[0], kConstants);
    dev->SetPixelShaderConstantI(0, s.intConstant, 2);
    if (s.target) s.target->Release();
    if (s.depth) s.depth->Release();
    if (s.vertexShader) s.vertexShader->Release();
    if (s.pixelShader) s.pixelShader->Release();
    if (s.declaration) s.declaration->Release();
    if (s.stream) s.stream->Release();
    for (int i = 0; i < kStages; ++i)
        if (s.texture[i]) s.texture[i]->Release();
}

// ---------------------------------------------------------------------------------------------
// The pass

struct QuadVertex { float x, y, z, rhw, u, v; };

static void Quad(IDirect3DDevice9* dev, float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1)
{
    // Half a pixel up and left: with that, pixel centres land on texel centres.
    const QuadVertex quad[4] = { { x0 - 0.5f, y0 - 0.5f, 0.5f, 1, u0, v0 }, { x1 - 0.5f, y0 - 0.5f, 0.5f, 1, u1, v0 },
                                 { x0 - 0.5f, y1 - 0.5f, 0.5f, 1, u0, v1 }, { x1 - 0.5f, y1 - 0.5f, 0.5f, 1, u1, v1 } };
    dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(QuadVertex));
}

// The same quad for the shader-model-3 passes, whose vertex shader takes clip-space positions (x and y from
// -1 to 1, y up); the same half-pixel shift.
static void Quad3(IDirect3DDevice9* dev, UINT width, UINT height, float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1)
{
    float w = (float)width, h = (float)height;
    float cx0 = (x0 - 0.5f) / w * 2 - 1, cx1 = (x1 - 0.5f) / w * 2 - 1;
    float cy0 = 1 - (y0 - 0.5f) / h * 2, cy1 = 1 - (y1 - 0.5f) / h * 2;
    const QuadVertex quad[4] = { { cx0, cy0, 0.5f, 1, u0, v0 }, { cx1, cy0, 0.5f, 1, u1, v0 },
                                 { cx0, cy1, 0.5f, 1, u0, v1 }, { cx1, cy1, 0.5f, 1, u1, v1 } };
    dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(QuadVertex));
}

static void BindTexture(IDirect3DDevice9* dev, int stage, IDirect3DBaseTexture9* texture, D3DTEXTUREFILTERTYPE filter)
{
    dev->SetTexture(stage, texture);
    dev->SetSamplerState(stage, D3DSAMP_MINFILTER, filter);
    dev->SetSamplerState(stage, D3DSAMP_MAGFILTER, filter);
}

static void Bind(IDirect3DDevice9* dev, int stage, int which, D3DTEXTUREFILTERTYPE filter)
{
    BindTexture(dev, stage, g_target[which].texture, filter);
}

// One full-target draw with one of our shaders. c0 is the shader's own four numbers.
static void Draw(IDirect3DDevice9* dev, int into, int shader, float a, float b, float c, float d)
{
    const float c0[4] = { a, b, c, d };
    dev->SetRenderTarget(0, g_target[into].surface);
    dev->SetPixelShader(g_shader[shader]);
    dev->SetPixelShaderConstantF(0, c0, 1);
    Quad(dev, 0, 0, (float)g_target[into].width, (float)g_target[into].height, 0, 0, 1, 1);
}

// The same with a shader-model-3 pixel shader (the vertex shader and format are set by the caller).
static void Draw3(IDirect3DDevice9* dev, int into, int shader, float a, float b, float c, float d)
{
    const float c0[4] = { a, b, c, d };
    dev->SetRenderTarget(0, g_target[into].surface);
    dev->SetPixelShader(g_shader3[shader]);
    dev->SetPixelShaderConstantF(0, c0, 1);
    Quad3(dev, g_target[into].width, g_target[into].height, 0, 0, (float)g_target[into].width, (float)g_target[into].height, 0, 0, 1, 1);
}

// The occlusion's numbers that do not change per draw. kIntensity sets how dark a fully closed-in corner gets
// before Strength; chosen on the stand-in's wall-and-floor scene (docs/dev-log.md, "Picture: VisualBridge").
static const float kAOIntensity = 2.0f, kAOBias = 0.01f, kAORelativeBias = 0.002f, kAOFadeStart = 100.0f, kAOFadeEnd = 200.0f;

// Depth view or occlusion into kWork, from the picture copy (kScene) and the scene's depth. Returns false when
// nothing was drawn (then the picture copy is used as it is). With `onto` (the direct path: occlusion is the only
// effect), the occlusion is instead multiplied straight onto that surface, the game's picture, with no copy.
static bool RunDepthPasses(IDirect3DDevice9* dev, IDirect3DTexture9* depth, UINT width, UINT height,
                           IDirect3DSurface9* onto = nullptr)
{
    if (!g_shaders3Tried)
        CompileShaders3(dev);
    if (!g_shaders3Ready || !EnsureDepthResources(dev, width, height))
        return false;
    float tanX, tanY;
    ViewTans(width, height, &tanX, &tanY);
    // Stored depth from this value up is sky: in the game at about 8 km, beyond anything drawn but the sky.
    float planeNear, planeFar;
    DepthPlanes(&planeNear, &planeFar);
    const float c4[4] = { planeNear, planeFar, 0.99999f, kAORelativeBias };
    const float c5[4] = { tanX, tanY, 1.0f / width, 1.0f / height };
    dev->SetPixelShaderConstantF(4, c4, 1);
    dev->SetPixelShaderConstantF(5, c5, 1);
    dev->SetVertexShader(g_pass3VS);
    dev->SetFVF(D3DFVF_XYZW | D3DFVF_TEX1);
    BindTexture(dev, 3, depth, D3DTEXF_POINT);
    if (g_on.showDepth)
        Draw3(dev, kWork, kDepthView, 0, 0, 0, 0);
    else
    {
        int timer = TimerBegin(g_aoTimer);
        const Target& occ = g_target[kOccA];
        float ow = (float)occ.width, oh = (float)occ.height, r = g_aoRadiusNow;
        const float c1[4] = { (oh / 2) / tanY, oh / 8, 1 / ow, 1 / oh };
        const float c2[4] = { kAOFadeStart, kAOFadeEnd, 0, 0 };
        dev->SetPixelShaderConstantF(1, c1, 1);
        dev->SetPixelShaderConstantF(2, c2, 1);
        Draw3(dev, kOccA, kAO, r, r * r, kAOBias, kAOIntensity / powf(r, 6) * 5 / 12);
        Bind(dev, 0, kOccA, D3DTEXF_POINT);
        Draw3(dev, kOccB, kAOBlur, 1 / ow, 0, 0, 0);
        Bind(dev, 0, kOccB, D3DTEXF_POINT);
        Draw3(dev, kOccA, kAOBlur, 0, 1 / oh, 0, 0);
        Bind(dev, 1, kOccA, D3DTEXF_POINT);
        if (onto)
        {
            // The picture times the factor; its alpha is left alone (colour writes are red, green, blue only).
            const float c0[4] = { g_cfg.aoStrength, 0, 1 / ow, 1 / oh };
            dev->SetRenderTarget(0, onto);
            dev->SetPixelShader(g_shader3[kAOFactor]);
            dev->SetPixelShaderConstantF(0, c0, 1);
            dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
            dev->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
            dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
            dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ZERO);
            dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_SRCCOLOR);
            dev->SetRenderState(D3DRS_COLORWRITEENABLE, D3DCOLORWRITEENABLE_RED | D3DCOLORWRITEENABLE_GREEN | D3DCOLORWRITEENABLE_BLUE);
            Quad3(dev, width, height, 0, 0, (float)width, (float)height, 0, 0, 1, 1);
            dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
        }
        else
        {
            Bind(dev, 0, kScene, D3DTEXF_POINT);
            Draw3(dev, kWork, kAOApply, g_cfg.aoStrength, 0, 1 / ow, 1 / oh);
        }
        TimerEnd(g_aoTimer, timer);
    }
    BindTexture(dev, 3, nullptr, D3DTEXF_POINT);
    dev->SetVertexShader(nullptr);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    return true;
}

// The state every draw of ours starts from (after SaveState): no depth buffer, no depth test, blending, alpha test,
// culling, fog, stencil, scissor or clip planes; all colour channels written; clamped, unfiltered-mip sampling.
static void PlainState(IDirect3DDevice9* dev)
{
    dev->SetDepthStencilSurface(nullptr); // our targets are smaller than the game's depth buffer
    dev->SetVertexShader(nullptr);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    dev->SetRenderState(D3DRS_ZENABLE, FALSE);
    dev->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    dev->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    dev->SetRenderState(D3DRS_FOGENABLE, FALSE);
    dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    dev->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    dev->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
    dev->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    dev->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
    dev->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    for (int i = 0; i < kStages; ++i)
    {
        dev->SetSamplerState(i, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        dev->SetSamplerState(i, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        dev->SetSamplerState(i, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        dev->SetSamplerState(i, D3DSAMP_SRGBTEXTURE, FALSE);
    }
}

static LONG g_frames, g_passes, g_noDepth, g_aaDraws;
static bool g_aoRan; // the occlusion pass ran in this pass (the showcase's level squares are drawn only then)

// Haze, light shafts and the sun marker, drawn straight onto the treated picture (`onto`), from x0 to the right edge
// (x0 = half the width in split screen). Depth-based parts skip themselves without depth.
static void RunOnto(IDirect3DDevice9* dev, IDirect3DTexture9* depth, UINT width, UINT height, IDirect3DSurface9* onto, float x0)
{
    float w = (float)width, h = (float)height;
    bool rays = depth && g_on.shafts && g_sun.on && g_sun.fade > 0;
    if ((depth && g_on.haze) || rays)
    {
        if (!g_shaders3Tried)
            CompileShaders3(dev);
        if (g_shaders3Ready)
        {
            float planeNear, planeFar;
            DepthPlanes(&planeNear, &planeFar);
            const float c4[4] = { planeNear, planeFar, 0.99999f, kAORelativeBias };
            const float c5[4] = { 0, 0, 1.0f / w, 1.0f / h };
            dev->SetPixelShaderConstantF(4, c4, 1);
            dev->SetPixelShaderConstantF(5, c5, 1);
            dev->SetVertexShader(g_pass3VS);
            dev->SetFVF(D3DFVF_XYZW | D3DFVF_TEX1);
            BindTexture(dev, 3, depth, D3DTEXF_POINT);
            if (g_on.haze)
            {
                const float c0[4] = { g_cfg.hazeStart, g_cfg.hazeEnd, g_cfg.hazeAmount, 0 };
                const float c1[4] = { g_cfg.hazeColour[0], g_cfg.hazeColour[1], g_cfg.hazeColour[2], 1 };
                dev->SetRenderTarget(0, onto);
                dev->SetPixelShader(g_shader3[kHaze]);
                dev->SetPixelShaderConstantF(0, c0, 1);
                dev->SetPixelShaderConstantF(1, c1, 1);
                dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
                dev->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
                dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
                dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
                dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
                dev->SetRenderState(D3DRS_COLORWRITEENABLE, D3DCOLORWRITEENABLE_RED | D3DCOLORWRITEENABLE_GREEN | D3DCOLORWRITEENABLE_BLUE);
                Quad3(dev, width, height, x0, 0, w, h, x0 / w, 0, 1, 1);
                dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
                dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
            }
            if (rays && !g_shaftsTarget.texture && !g_shaftsFailed)
            {
                if (!MakeTarget(dev, -1, width / 4, height / 4, D3DFMT_A8R8G8B8))
                {
                    ReleaseTarget(g_shaftsTarget); // a texture without its surface must not be used
                    g_shaftsFailed = true;
                    Log("shafts target FAILED: light shafts stay off");
                }
                else
                    TimerMake(dev, g_shaftsTimer, "shafts");
            }
            if (rays && g_shaftsTarget.texture && g_shaftsTarget.surface)
            {
                int timer = TimerBegin(g_shaftsTimer);
                const float c0[4] = { g_sun.x, g_sun.y, g_cfg.shaftsLength, w / h };
                const float c1[4] = { 0.35f, 0, 0, 0 };
                dev->SetRenderTarget(0, g_shaftsTarget.surface);
                dev->SetPixelShader(g_shader3[kShaftsMask]);
                dev->SetPixelShaderConstantF(0, c0, 1);
                dev->SetPixelShaderConstantF(1, c1, 1);
                Quad3(dev, g_shaftsTarget.width, g_shaftsTarget.height, 0, 0, (float)g_shaftsTarget.width, (float)g_shaftsTarget.height, 0, 0, 1, 1);
                float k = g_cfg.shaftsStrength * g_sun.fade;
                const float a0[4] = { g_cfg.shaftsColour[0] * k, g_cfg.shaftsColour[1] * k, g_cfg.shaftsColour[2] * k, 1 };
                dev->SetRenderTarget(0, onto);
                BindTexture(dev, 1, g_shaftsTarget.texture, D3DTEXF_LINEAR);
                dev->SetPixelShader(g_shader3[kShaftsApply]);
                dev->SetPixelShaderConstantF(0, a0, 1);
                dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
                dev->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
                dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
                dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
                dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
                dev->SetRenderState(D3DRS_COLORWRITEENABLE, D3DCOLORWRITEENABLE_RED | D3DCOLORWRITEENABLE_GREEN | D3DCOLORWRITEENABLE_BLUE);
                Quad3(dev, width, height, x0, 0, w, h, x0 / w, 0, 1, 1);
                dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
                dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
                TimerEnd(g_shaftsTimer, timer);
                BindTexture(dev, 1, nullptr, D3DTEXF_POINT);
            }
            BindTexture(dev, 3, nullptr, D3DTEXF_POINT);
            dev->SetVertexShader(nullptr);
            dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
        }
    }
    // [Test] AOShowcase: 1 to 3 small white squares top left while occlusion is on: the level being shown.
    if (g_showcaseLevel && g_aoRan)
    {
        D3DRECT squares[3];
        for (int i = 0; i < g_showcaseLevel; ++i)
            squares[i] = { 20 + i * 20, 50, 32 + i * 20, 62 };
        dev->SetRenderTarget(0, onto);
        dev->Clear((DWORD)g_showcaseLevel, squares, D3DCLEAR_TARGET, D3DCOLOR_XRGB(255, 255, 255), 1.0f, 0);
    }
    // [Debug] ShowSun: a magenta cross where the sun is computed to be (checks the view and sun addresses): arms
    // 1/36 of the picture's height each way (30 pixels at 1080), 1/180 thick (7 pixels at 1080).
    if (g_on.showSun && g_sun.on)
    {
        LONG px = (LONG)floorf(g_sun.x * w), py = (LONG)floorf(g_sun.y * h);
        // On either half in split screen: it marks where the sun is, it does not belong to one side.
        if (px >= 0 && px < (LONG)w && py >= 0 && py < (LONG)h)
        {
            LONG arm = (LONG)h / 36 > 4 ? (LONG)h / 36 : 4, half = (LONG)h / 360 > 1 ? (LONG)h / 360 : 1;
            D3DRECT mark[2] = { { px - arm, py - half, px + arm + 1, py + half + 1 },
                                { px - half, py - arm, px + half + 1, py + arm + 1 } };
            // Kept inside the picture (Clear takes no rectangle outside the target).
            for (D3DRECT& r : mark)
            {
                r.x1 = r.x1 < 0 ? 0 : r.x1;
                r.y1 = r.y1 < 0 ? 0 : r.y1;
                r.x2 = r.x2 > (LONG)w ? (LONG)w : r.x2;
                r.y2 = r.y2 > (LONG)h ? (LONG)h : r.y2;
            }
            dev->SetRenderTarget(0, onto);
            dev->Clear(2, mark, D3DCLEAR_TARGET, D3DCOLOR_XRGB(255, 0, 255), 1.0f, 0);
        }
    }
}
static LONGLONG g_lastPassTicks; // the high-resolution clock at the last pass
static bool g_depthMissingLogged;

static void RunLook(IDirect3DDevice9* dev)
{
    // First everything that can fail, before any state is touched.
    IDirect3DSurface9* picture = nullptr;
    D3DSURFACE_DESC desc;
    if (FAILED(dev->GetRenderTarget(0, &picture)) || FAILED(picture->GetDesc(&desc)))
    {
        if (picture)
            picture->Release();
        return;
    }
    bool look = g_on.exposure || g_on.bloom || g_on.identity;
    bool wantsDepth = g_on.ao || g_on.showDepth || g_on.haze || g_on.shafts;
    if (g_on.shafts || g_on.showSun)
        g_sunShown = g_sun = ReadSun(desc.Width, desc.Height);
    IDirect3DTexture9* depth = wantsDepth ? SceneDepth(dev, desc.Width, desc.Height) : nullptr;
    if (wantsDepth && !depth)
    {
        ++g_noDepth;
        if (!g_depthMissingLogged && g_depthTexture && (g_depthWidth != desc.Width || g_depthHeight != desc.Height))
            Log("scene depth is %ux%u but the picture is %ux%u: the effects that need it skip themselves",
                g_depthWidth, g_depthHeight, desc.Width, desc.Height);
        else if (!g_depthMissingLogged)
            Log("no scene depth in this frame: the effects that need it skip themselves until it is back");
        g_depthMissingLogged = true;
    }
    else if (depth)
        g_depthMissingLogged = false;
    if (!look && !depth && !g_on.showSun)
    {
        picture->Release();
        return; // nothing to do: the picture stays exactly the game's
    }
    // The direct path: occlusion, haze and shafts, over the whole picture. No copy of the picture is made; each is
    // drawn straight onto it with blending (occlusion multiplied, haze mixed in, rays added): in the 1920x1080 bench
    // stand-in the copy-based path cost about 0.7 ms a frame more, all of it work for DXVK and the graphics card.
    bool direct = !g_on.showDepth && !look && !g_cfg.split;
    // The direct path needs none of the exposure and bloom targets (nor the picture copy): they are not made.
    bool ready = direct || (EnsureResources(dev, desc.Width, desc.Height)
        && SUCCEEDED(dev->StretchRect(picture, nullptr, g_target[kScene].surface, nullptr, D3DTEXF_NONE)));
    picture->Release();
    if (!ready)
        return;
    Saved saved;
    SaveState(dev, saved);
    PlainState(dev);
    float w = (float)desc.Width, h = (float)desc.Height;
    g_aoRan = false;

    // Depth first: occlusion (or the depth view) makes the work picture that everything after starts from.
    if (direct)
    {
        if (depth && g_on.ao)
            g_aoRan = RunDepthPasses(dev, depth, desc.Width, desc.Height, saved.target);
        RunOnto(dev, depth, desc.Width, desc.Height, saved.target, 0);
        RestoreState(dev, saved);
        ++g_passes;
        return;
    }
    int source = kScene;
    if (depth && (g_on.ao || g_on.showDepth) && RunDepthPasses(dev, depth, desc.Width, desc.Height))
    {
        source = kWork;
        g_aoRan = g_on.ao && !g_on.showDepth;
    }

    bool exposure = g_on.exposure && !g_on.identity, bloom = g_on.bloom && !g_on.identity;
    const float c1[4] = { g_cfg.middleGrey, g_cfg.minScale, g_cfg.maxScale, exposure ? 1.0f : 0.0f };
    dev->SetPixelShaderConstantF(1, c1, 1);
    float qw = (float)g_target[kQuarter].width, qh = (float)g_target[kQuarter].height;

    if (look)
    {
        // Brightness: the picture at quarter size, then 64, 16, 4, 1 pixels of average log luminance.
        Bind(dev, 0, source, D3DTEXF_LINEAR);
        Draw(dev, kQuarter, kDown4, 1 / w, 1 / h, 0, 0);
        Bind(dev, 0, kQuarter, D3DTEXF_LINEAR);
        Draw(dev, kLum64, kLogLum, 1.0f / 192, 1.0f / 192, 0, 0);
        Bind(dev, 0, kLum64, D3DTEXF_LINEAR);
        Draw(dev, kLum16, kDown4, 1.0f / 64, 1.0f / 64, 0, 0);
        Bind(dev, 0, kLum16, D3DTEXF_LINEAR);
        Draw(dev, kLum4, kDown4, 1.0f / 16, 1.0f / 16, 0, 0);
        Bind(dev, 0, kLum4, D3DTEXF_LINEAR);
        Draw(dev, kLum1, kDown4, 1.0f / 4, 1.0f / 4, 0, 0);

        // Adaptation: from last frame's value towards the measured one.
        LARGE_INTEGER now, frequency;
        QueryPerformanceCounter(&now);
        QueryPerformanceFrequency(&frequency);
        float seconds = g_lastPassTicks ? (float)((double)(now.QuadPart - g_lastPassTicks) / (double)frequency.QuadPart) : 0.0f;
        g_lastPassTicks = now.QuadPart;
        // After a gap (menus, loading, the effect switched off) the old value says nothing about this scene:
        // start again from what is measured, as on the first frame. Otherwise the picture flashes.
        if (seconds > 0.25f)
            g_firstFrame = true;
        int next = g_adaptedNow == kAdaptedA ? kAdaptedB : kAdaptedA;
        Bind(dev, 0, kLum1, D3DTEXF_POINT);
        Bind(dev, 1, g_adaptedNow, D3DTEXF_POINT);
        Draw(dev, next, kAdapt, seconds, g_cfg.speedUp, g_cfg.speedDown, g_firstFrame ? 1.0f : 0.0f);
        g_adaptedNow = next;
        g_firstFrame = false;
    }
    Bind(dev, 1, g_adaptedNow, D3DTEXF_POINT);

    // Bloom: what is brighter than the threshold after exposure, blurred across and down, twice.
    if (bloom)
    {
        Bind(dev, 0, kQuarter, D3DTEXF_LINEAR);
        Draw(dev, kBloomA, kBright, g_cfg.threshold, 0, 0, 0);
        for (int round = 1; round <= 2; ++round)
        {
            float step = g_cfg.blurWidth * round;
            Bind(dev, 0, kBloomA, D3DTEXF_LINEAR);
            Draw(dev, kBloomB, kBlur, step / qw, 0, 0, 0);
            Bind(dev, 0, kBloomB, D3DTEXF_LINEAR);
            Draw(dev, kBloomA, kBlur, 0, step / qh, 0, 0);
        }
    }

    // The result, drawn over the picture: all of it, or the right half in the split-screen test mode.
    const float c0[4] = { bloom ? g_cfg.bloomScale : 0.0f, 0, 0, 0 };
    dev->SetRenderTarget(0, saved.target);
    Bind(dev, 0, source, D3DTEXF_POINT);
    Bind(dev, 2, kBloomA, D3DTEXF_LINEAR);
    dev->SetPixelShader(g_shader[kFinal]);
    dev->SetPixelShaderConstantF(0, c0, 1);
    dev->SetRenderState(D3DRS_COLORWRITEENABLE, D3DCOLORWRITEENABLE_RED | D3DCOLORWRITEENABLE_GREEN | D3DCOLORWRITEENABLE_BLUE);
    if (g_cfg.split)
    {
        Quad(dev, w / 2, 0, w, h, 0.5f, 0, 1, 1);
        const D3DRECT line = { (LONG)(w / 2) - 1, 0, (LONG)(w / 2) + 1, (LONG)h };
        dev->Clear(1, &line, D3DCLEAR_TARGET, D3DCOLOR_XRGB(128, 128, 128), 1.0f, 0);
    }
    else
        Quad(dev, 0, 0, w, h, 0, 0, 1, 1);
    if (!g_on.showDepth)
        RunOnto(dev, depth, desc.Width, desc.Height, saved.target, g_cfg.split ? w / 2 : 0);
    RestoreState(dev, saved);
    ++g_passes;
}

// Edge smoothing, drawn in place of the pack's pass-through: the treated picture (`picture`, the treatment's
// screen-sized target) through the Smooth shader onto the current target (the back buffer), colour and alpha, as
// the pass-through would have drawn it. In split screen only the right half (the game's own draw has already
// covered the screen). The device state is saved and put back. False if the shader is not ready (then the caller
// lets the game's draw run).
static IDirect3DTexture9* g_finalTexture; // the treatment's target this frame (no reference kept; null after Present)
static const float kAASubpixel = 0.75f, kAAEdgeThreshold = 0.166f, kAAEdgeThresholdMin = 0.0833f;

// Why the reflections did not run in the last replaced draw (for the SUN line): 0 they ran, 1 no valid matrix,
// 2 no scene depth, 3 its shaders failed.
static int g_wetOff;

// The main view's matrix for the reflections: the matrix, its inverse and the camera's place in the world (where
// clip x, y and w are all 0: the inverse's third row, divided through). False when any of them is not usable.
static bool WetMatrices(float clip[16], float inverse[16], float camera[3])
{
    if (!ReadViewClip(clip) || !Invert4(clip, inverse) || !(fabsf(inverse[11]) > 1e-12f))
        return false;
    for (int i = 0; i < 3; ++i)
    {
        camera[i] = inverse[8 + i] / inverse[11];
        if (!(camera[i] == camera[i]) || !(fabsf(camera[i]) < 1e7f))
            return false;
    }
    return true;
}

static bool RunSmoothing(IDirect3DDevice9* dev, IDirect3DTexture9* picture, bool split)
{
    if (!g_shaders3Tried)
        CompileShaders3(dev);
    D3DSURFACE_DESC desc;
    if (!g_shaders3Ready || FAILED(picture->GetLevelDesc(0, &desc)))
        return false;
    // Reflections need this frame's depth and a valid view matrix; without them, smoothing alone (or, with smoothing
    // off, the pack's own draw).
    float clip[16], inverse[16], camera[3];
    IDirect3DTexture9* depth = g_on.wet ? SceneDepth(dev, desc.Width, desc.Height) : nullptr;
    bool wet = false;
    if (g_on.wet)
    {
        bool ready = WetShadersReady(dev); // starts their compile the first time
        g_wetOff = !WetMatrices(clip, inverse, camera) ? 1 : !depth ? 2 : !ready ? 3 : 0;
        wet = g_wetOff == 0;
    }
    else if (g_cfg.wet)
        g_wetOff = 4; // switched off by [Test] ToggleSeconds: the SUN line says so instead of keeping the last state
    if (!g_on.aa && !wet)
        return false;
    TimerSet& timerSet = wet ? g_wetTimer : g_aaTimer;
    TimerMake(dev, timerSet, wet ? "wet" : "aa");
    Saved saved;
    SaveState(dev, saved);
    PlainState(dev);
    float w = (float)desc.Width, h = (float)desc.Height;
    const float c0[4] = { g_cfg.aaStrength, kAASubpixel, kAAEdgeThreshold, kAAEdgeThresholdMin };
    const float c5[4] = { 0, 0, 1 / w, 1 / h };
    dev->SetVertexShader(g_pass3VS);
    dev->SetFVF(D3DFVF_XYZW | D3DFVF_TEX1);
    dev->SetPixelShader(g_shader3[wet ? (g_on.aa ? kSmoothWet : kWet) : kSmooth]);
    dev->SetPixelShaderConstantF(0, c0, 1);
    dev->SetPixelShaderConstantF(5, c5, 1);
    if (wet)
    {
        // Stored depth from 0.99999 up is sky; a crossing deeper than 0.3 m + 2% of the distance is a ray passing
        // behind something.
        float planeNear, planeFar;
        DepthPlanes(&planeNear, &planeFar);
        const float c4[4] = { planeNear, planeFar, 0.99999f, kAORelativeBias };
        const float c14[4] = { g_cfg.wetStrength, (float)g_cfg.wetSteps, g_cfg.wetMaxDistance, g_cfg.wetMinUp };
        const float c15[4] = { g_cfg.wetEdgeFade, 0.02f, 0.3f, g_cfg.wetBlur };
        const float c16[4] = { g_cfg.wetUp[0], g_cfg.wetUp[1], g_cfg.wetUp[2], (float)g_cfg.wetBlurSteps };
        const float c17[4] = { camera[0], camera[1], camera[2], 1 };
        dev->SetPixelShaderConstantF(4, c4, 1);
        dev->SetPixelShaderConstantF(6, clip, 4);
        dev->SetPixelShaderConstantF(10, inverse, 4);
        dev->SetPixelShaderConstantF(14, c14, 1);
        dev->SetPixelShaderConstantF(15, c15, 1);
        dev->SetPixelShaderConstantF(16, c16, 1);
        dev->SetPixelShaderConstantF(17, c17, 1);
        // i0: the steps along each ray; i1: the rays averaged per pixel (5 with Blur: its own and four neighbours'; 1 when sharp). Loop counts
        // from constants keep the shader compiler from unrolling them (five unrolled ray marches did not compile in 18 s).
        const int loops[8] = { g_cfg.wetSteps, 0, 1, 0, g_cfg.wetBlur > 0 ? 5 : 1, 0, 1, 0 };
        dev->SetPixelShaderConstantI(0, loops, 2);
        BindTexture(dev, 3, depth, D3DTEXF_POINT);
    }
    BindTexture(dev, 0, picture, D3DTEXF_LINEAR);
    int timer = TimerBegin(timerSet);
    if (split)
        Quad3(dev, desc.Width, desc.Height, w / 2, 0, w, h, 0.5f, 0, 1, 1);
    else
        Quad3(dev, desc.Width, desc.Height, 0, 0, w, h, 0, 0, 1, 1);
    TimerEnd(timerSet, timer);
    if (wet)
        BindTexture(dev, 3, nullptr, D3DTEXF_POINT);
    if (split)
    {
        const D3DRECT line = { (LONG)(w / 2) - 1, 0, (LONG)(w / 2) + 1, (LONG)h };
        dev->Clear(1, &line, D3DCLEAR_TARGET, D3DCOLOR_XRGB(128, 128, 128), 1.0f, 0);
    }
    RestoreState(dev, saved);
    return true;
}

// Once a second: frames, passes and what the exposure is doing; also picks up a changed .ini.
static void EverySecond(IDirect3DDevice9* dev)
{
    static DWORD last;
    DWORD now = GetTickCount();
    if (now - last < 1000)
        return;
    last = now;
    if (IniChanged())
    {
        ReadConfig();
        Log("settings reloaded: enabled=%d exposure=%d bloom=%d ao=%d aa=%d haze=%d shafts=%d showdepth=%d showsun=%d split=%d "
            "strength=%.2f radius=%.2f half=%d aa_strength=%.2f toggleSeconds=%d toggleOnly=%s aoShowcase=%d wet=%d wet_strength=%.2f "
            "wet_steps=%d wet_distance=%.0f wet_minup=%.2f wet_up=%c wet_blur=%.1f", g_cfg.enabled,
            g_cfg.exposure, g_cfg.bloom, g_cfg.ao, g_cfg.aa, g_cfg.haze, g_cfg.shafts, g_cfg.showDepth, g_cfg.showSun, g_cfg.split,
            g_cfg.aoStrength, g_cfg.aoRadius, g_cfg.aoHalf, g_cfg.aaStrength, g_cfg.toggleSeconds, g_cfg.toggleOnly,
            g_cfg.aoShowcase ? 1 : 0, g_cfg.wet, g_cfg.wetStrength, g_cfg.wetSteps, g_cfg.wetMaxDistance, g_cfg.wetMinUp,
            g_cfg.wetUpAxis, g_cfg.wetBlur);
    }
    float adapted = 0, measured = 0;
    D3DLOCKED_RECT lock;
    // Read back (which makes the processor wait for the graphics card) only when exposure is being worked out.
    if ((g_cfg.exposure || g_cfg.bloom || g_cfg.identity) && g_resourcesReady
        && SUCCEEDED(dev->GetRenderTargetData(g_target[g_adaptedNow].surface, g_readback))
        && SUCCEEDED(g_readback->LockRect(&lock, nullptr, D3DLOCK_READONLY)))
    {
        adapted = ((const float*)lock.pBits)[0];
        measured = ((const float*)lock.pBits)[1];
        g_readback->UnlockRect();
    }
    // The same number the shader computes (see shaders.h, Exposure).
    float bounded = adapted < 0.001f ? 0.001f : adapted > 0.98f ? 0.98f : adapted;
    float scale = logf(1 - g_cfg.middleGrey) / logf(1 - bounded);
    scale = scale < g_cfg.minScale ? g_cfg.minScale : scale > g_cfg.maxScale ? g_cfg.maxScale : scale;
    char extra[192] = "";
    size_t used = 0;
    if (g_cfg.ao || g_cfg.showDepth)
        used += snprintf(extra + used, sizeof(extra) - used, " nodepth=%ld ao_ms=%.3f", g_noDepth,
            g_aoTimer.count ? g_aoTimer.sum / g_aoTimer.count : -1.0);
    if (g_cfg.aa)
        used += snprintf(extra + used, sizeof(extra) - used, " aa=%ld aa_ms=%.3f", g_aaDraws,
            g_aaTimer.count ? g_aaTimer.sum / g_aaTimer.count : -1.0);
    if (g_cfg.shafts)
        used += snprintf(extra + used, sizeof(extra) - used, " shafts_ms=%.3f",
            g_shaftsTimer.count ? g_shaftsTimer.sum / g_shaftsTimer.count : -1.0);
    // wet_ms: the replaced pass-through draw's time when it carried reflections (with smoothing in it when AA is on).
    if (g_cfg.wet)
        used += snprintf(extra + used, sizeof(extra) - used, " wet_ms=%.3f", g_wetTimer.count ? g_wetTimer.sum / g_wetTimer.count : -1.0);
    Log("LOOK frames=%ld passes=%ld lum=%.4f adapted=%.4f exposure=%.3f%s", g_frames, g_passes, measured, adapted,
        g_cfg.exposure ? scale : 1.0f, extra);
    g_frames = g_passes = g_noDepth = g_aaDraws = 0;
    g_aoTimer.sum = g_aaTimer.sum = g_shaftsTimer.sum = g_wetTimer.sum = 0;
    g_aoTimer.count = g_aaTimer.count = g_shaftsTimer.count = g_wetTimer.count = 0;
    // The sun as last read: where it is and what it was computed from (for checking the addresses in a race).
    if (g_cfg.shafts || g_cfg.showSun || g_cfg.wet)
    {
        const Sun& s = g_sunShown;
        static const char* const kWetState[5] = { "on", "off(matrix)", "off(depth)", "off(shader)", "off(toggle)" }; // shader: compiling, or failed
        Log("SUN on=%d x=%.3f y=%.3f facing=%.3f fade=%.2f sun=(%.3f,%.3f,%.3f) forward=(%.3f,%.3f,%.3f) camera=0x%08lX "
            "info=0x%08lX proj=%s game_fov=%.1fx%.1f camera_fov=%u (%.1f deg) view_fov=%.3f fovy=%.1f planes=%.3f/%.0f%s%s", s.on ? 1 : 0,
            s.x, s.y, s.facing, s.fade, s.dir[0], s.dir[1], s.dir[2], s.forward[0], s.forward[1], s.forward[2], (unsigned long)s.camera,
            (unsigned long)s.info, s.game ? "game" : s.projected ? "fovy" : "none", s.gameFovX, s.gameFovY, s.cameraFov, s.cameraFov * 360.0f / 65536.0f,
            s.viewFov, g_cfg.fovY, g_gameNear, g_gameFar, g_cfg.wet ? " wet=" : "", g_cfg.wet ? kWetState[g_wetOff] : "");
    }
}

// ---------------------------------------------------------------------------------------------
// Effects: what is known about each one the game uses

enum { kMaxFx = 128 };
struct FxInfo
{
    ID3DXEffect* fx;
    bool after, before, finalCandidate; // finalCandidate: it has a technique named in [Game] Final
    bool passCandidate;                 // it has a technique named in [Game] PassThrough
    char name[48];                      // its resource name, or "(from memory)"
};
static FxInfo g_fx[kMaxFx];
static int g_fxCount;
static IDirect3DDevice9* g_device;
static bool g_afterSeen, g_doneThisFrame, g_busy;
static ID3DXEffect* g_finalOpen; // a Final technique has begun on the back buffer and not yet ended
static ID3DXEffect* g_passOpen;  // the pass-through has begun on the back buffer after the treatment, not yet ended
static bool g_aaDone, g_aaLogged;  // the pass-through's draw was handled this frame; the replacement was logged
static char g_passPoint[96];

static bool IsFinalName(const char* name)
{
    for (int i = 0; i < g_cfg.finalCount; ++i)
        if (name && !lstrcmpiA(name, g_cfg.final[i]))
            return true;
    return false;
}

static bool IsPassThroughName(const char* name)
{
    for (int i = 0; i < g_cfg.passThroughCount; ++i)
        if (name && !lstrcmpiA(name, g_cfg.passThrough[i]))
            return true;
    return false;
}

static void Forget(ID3DXEffect* fx)
{
    for (int i = 0; i < g_fxCount; ++i)
        if (g_fx[i].fx == fx)
        {
            g_fx[i] = g_fx[--g_fxCount];
            return;
        }
}

// Records an effect: by its resource name if it has one, and whether one of its techniques is a Final one.
static FxInfo* Learn(ID3DXEffect* fx, const char* resource)
{
    Forget(fx); // the library hands out the addresses of released effects again
    if (g_fxCount == kMaxFx)
        return nullptr;
    FxInfo* f = &g_fx[g_fxCount++];
    memset(f, 0, sizeof(*f));
    f->fx = fx;
    snprintf(f->name, sizeof(f->name), "%s", resource ? resource : "(from memory)");
    for (int i = 0; resource && i < g_cfg.afterCount; ++i)
        f->after |= !lstrcmpiA(resource, g_cfg.after[i]);
    for (int i = 0; resource && i < g_cfg.beforeCount; ++i)
        f->before |= !lstrcmpiA(resource, g_cfg.before[i]);
    D3DXEFFECT_DESC desc = {};
    if (SUCCEEDED(fx->GetDesc(&desc)))
        for (UINT i = 0; i < desc.Techniques; ++i)
        {
            D3DXTECHNIQUE_DESC technique = {};
            D3DXHANDLE handle = fx->GetTechnique(i);
            if (handle && SUCCEEDED(fx->GetTechniqueDesc(handle, &technique)))
            {
                f->finalCandidate |= IsFinalName(technique.Name);
                f->passCandidate |= IsPassThroughName(technique.Name);
            }
        }
    return f;
}

static FxInfo* Find(ID3DXEffect* fx)
{
    for (int i = 0; i < g_fxCount; ++i)
        if (g_fx[i].fx == fx)
            return &g_fx[i];
    return nullptr;
}

static const char* CurrentTechnique(ID3DXEffect* fx)
{
    D3DXTECHNIQUE_DESC technique = {};
    D3DXHANDLE handle = fx->GetCurrentTechnique();
    return handle && SUCCEEDED(fx->GetTechniqueDesc(handle, &technique)) ? technique.Name : nullptr;
}

// One frame in every 30 seconds is written to the log as the list of effect techniques begun on the back buffer
// (ORDER line), with where the pass ran: the evidence for where the hook point is in a frame we cannot see.
static bool g_recordOrder;
static char g_order[1024];

static void OrderNote(const char* text)
{
    size_t used = strlen(g_order);
    if (used + strlen(text) + 2 < sizeof(g_order))
        snprintf(g_order + used, sizeof(g_order) - used, used ? " %s" : "%s", text);
}

static bool TargetIsBackBuffer(IDirect3DDevice9* dev)
{
    IDirect3DSurface9* target = nullptr, * back = nullptr;
    bool same = SUCCEEDED(dev->GetRenderTarget(0, &target)) && SUCCEEDED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back))
        && target == back;
    if (target) target->Release();
    if (back) back->Release();
    return same;
}

// [Test] ToggleSeconds: the effects run for that many seconds, then not for as many, and so on, each switch logged
// with its time, so that one race's frame-time recording can be split into on and off stretches: the cost with the
// same car, traffic and route. [Test] ToggleOnly = all (the default) switches every effect ("toggle: effects
// on/off"); a name (ao, aa, shafts, haze) switches only that one ("toggle: ao on/off") and leaves the others as set,
// so the cost measured is that effect's alone.
static bool ToggleAll()
{
    return !lstrcmpiA(g_cfg.toggleOnly, "all");
}

static bool ToggledOn()
{
    if (g_cfg.toggleSeconds <= 0)
        return true;
    static int last = -1;
    int on = (int)(((GetTickCount() - g_startTick) / (DWORD)(g_cfg.toggleSeconds * 1000)) % 2 == 0);
    if (on != last)
    {
        Log("toggle: %s %s", ToggleAll() ? "effects" : g_cfg.toggleOnly, on ? "on" : "off");
        last = on;
    }
    return on != 0;
}

// A setting after the toggle: an effect the toggle covers is on only in the "on" stretches.
static bool Switched(bool setting, const char* name)
{
    if (!setting || !g_cfg.enabled)
        return false;
    return (ToggleAll() || !lstrcmpiA(g_cfg.toggleOnly, name)) ? ToggledOn() : true;
}

// [Test] AOShowcase: the level (1-3) for this moment: each lasts Blinks off-and-on blinks of ToggleSeconds, then the
// next, and round again; each change logged with its settings. 0 when the showcase is off.
static int g_showcaseLast; // the level last logged; 0 while the showcase is off, so the next one is logged again

static int ShowcaseLevel()
{
    if (!g_cfg.aoShowcase || g_cfg.toggleSeconds <= 0)
    {
        g_showcaseLast = 0;
        return 0;
    }
    DWORD period = (DWORD)g_cfg.toggleSeconds * 2000u * (DWORD)g_cfg.showcaseBlinks;
    int level = (int)(((GetTickCount() - g_startTick) / period) % 3) + 1;
    int& last = g_showcaseLast;
    if (level != last)
    {
        Log("showcase: level %d (half=%d radius=%.2f)", level, g_cfg.showcaseHalf[level - 1] ? 1 : 0,
            g_cfg.showcaseRadius[level - 1]);
        last = level;
    }
    return level;
}

// Works out g_on for this moment; true when anything in the pass on the finished picture is to run.
static bool Wanted()
{
    if (g_cfg.toggleSeconds > 0)
        ToggledOn(); // the switch is logged when it happens, whatever is on
    g_showcaseLevel = ShowcaseLevel();
    bool half = g_showcaseLevel ? g_cfg.showcaseHalf[g_showcaseLevel - 1] : g_cfg.aoHalf;
    // A new occlusion size ([AO] HalfResolution changed, or a showcase level of the other size) gets a fresh try at
    // making its targets: a failure at one size says nothing about the other.
    if (half != g_aoHalfNow)
        g_depthResourcesFailed = false;
    g_aoHalfNow = half;
    g_aoRadiusNow = g_showcaseLevel ? g_cfg.showcaseRadius[g_showcaseLevel - 1] : g_cfg.aoRadius;
    g_on.exposure = Switched(g_cfg.exposure, "exposure");
    g_on.bloom = Switched(g_cfg.bloom, "bloom");
    g_on.identity = Switched(g_cfg.identity, "identity");
    g_on.ao = Switched(g_cfg.ao, "ao");
    g_on.showDepth = Switched(g_cfg.showDepth, "depth");
    g_on.aa = Switched(g_cfg.aa, "aa"); // not part of this pass: it runs in the pass-through (see HookDrawUP)
    g_on.haze = Switched(g_cfg.haze, "haze");
    g_on.shafts = Switched(g_cfg.shafts, "shafts");
    g_on.showSun = Switched(g_cfg.showSun, "sun");
    g_on.wet = Switched(g_cfg.wet, "wet"); // like aa: in the pass-through's draw (see HookDrawUP)
    return g_on.exposure || g_on.bloom || g_on.identity || g_on.ao || g_on.showDepth || g_on.haze || g_on.shafts || g_on.showSun;
}

static void RunPass(const char* point)
{
    g_doneThisFrame = true;
    g_busy = true; // our own draws must not start another pass
    if (strcmp(point, g_passPoint))
    {
        snprintf(g_passPoint, sizeof(g_passPoint), "%s", point);
        Log("pass point: %s", point);
    }
    if (g_recordOrder)
        OrderNote("[PASS]");
    if (!g_shadersTried)
        CompileShaders(g_device);
    if (g_shadersReady)
        RunLook(g_device);
    g_busy = false;
}

typedef HRESULT(WINAPI* FxBeginFn)(ID3DXEffect*, UINT*, DWORD);
typedef HRESULT(WINAPI* FxEndFn)(ID3DXEffect*);
typedef ULONG(WINAPI* FxReleaseFn)(ID3DXEffect*);
static FxBeginFn g_fxBegin;
static FxEndFn g_fxEnd;
static FxReleaseFn g_fxRelease;

static HRESULT WINAPI HookFxBegin(ID3DXEffect* fx, UINT* passes, DWORD flags)
{
    if (g_device && !g_busy)
    {
        FxInfo* f = Find(fx);
        if (!f)
            f = Learn(fx, nullptr);
        if (f && f->after)
            g_afterSeen = true;
        bool onBack = (f && f->before || g_recordOrder) && TargetIsBackBuffer(g_device);
        // The ORDER line: the treatment's techniques wherever they draw, and everything begun on the back buffer.
        if (g_recordOrder && (onBack || f && f->finalCandidate))
        {
            char text[112];
            const char* technique = CurrentTechnique(fx);
            snprintf(text, sizeof(text), "%s/%s%s", f ? f->name : "?", technique ? technique : "?", onBack ? "" : "(texture)");
            OrderNote(text);
        }
        bool want = Wanted();
        if (f && want && !g_doneThisFrame && f->before && onBack && g_afterSeen)
        {
            char point[96];
            snprintf(point, sizeof(point), "begin of %s on the back buffer, after the After effect", f->name);
            RunPass(point);
        }
        // The pack's treatment draws the finished picture into a texture of its own, which a pass-through then
        // copies onto the back buffer: wherever it draws, the pass runs on its target when it ends (and edge
        // smoothing needs to know that target), so it is followed whenever anything is on.
        else if (f && (want || g_on.aa || g_on.wet) && f->finalCandidate && IsFinalName(CurrentTechnique(fx)))
            g_finalOpen = fx;
        // The pass-through, after the treatment in this frame, onto the back buffer: its draw is smoothing's.
        if (f && (g_on.aa || g_on.wet) && f->passCandidate && g_finalTexture && !g_aaDone && IsPassThroughName(CurrentTechnique(fx))
            && TargetIsBackBuffer(g_device))
            g_passOpen = fx;
    }
    return g_fxBegin(fx, passes, flags);
}

static HRESULT WINAPI HookFxEnd(ID3DXEffect* fx)
{
    HRESULT hr = g_fxEnd(fx);
    if (fx == g_finalOpen && !g_busy)
    {
        g_finalOpen = nullptr;
        // Only on a target the size of the screen: that is the finished picture, not a part of it.
        IDirect3DSurface9* target = nullptr, * back = nullptr;
        D3DSURFACE_DESC td = {}, bd = {};
        bool whole = SUCCEEDED(g_device->GetRenderTarget(0, &target)) && SUCCEEDED(target->GetDesc(&td))
            && SUCCEEDED(g_device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) && SUCCEEDED(back->GetDesc(&bd))
            && td.Width == bd.Width && td.Height == bd.Height;
        bool onBack = target && target == back;
        if (back) back->Release();
        const char* technique = CurrentTechnique(fx);
        char point[96];
        if (onBack)
            snprintf(point, sizeof(point), "end of technique %s on the back buffer", technique ? technique : "?");
        else
            snprintf(point, sizeof(point), "end of technique %s on a %ux%u texture", technique ? technique : "?", td.Width, td.Height);
        if (whole && !onBack && target)
        {
            // The treated picture, for the pass-through's smoothing (only the address: valid until Present).
            IDirect3DTexture9* texture = nullptr;
            if (SUCCEEDED(target->GetContainer(kIIDTexture, (void**)&texture)) && texture)
            {
                g_finalTexture = texture;
                texture->Release();
            }
        }
        if (target) target->Release();
        if (whole && Wanted() && !g_doneThisFrame)
            RunPass(point);
    }
    if (fx == g_passOpen)
        g_passOpen = nullptr;
    return hr;
}

static ULONG WINAPI HookFxRelease(ID3DXEffect* fx)
{
    ULONG left = g_fxRelease(fx);
    if (left == 0)
    {
        Forget(fx);
        if (g_finalOpen == fx)
            g_finalOpen = nullptr;
        if (g_passOpen == fx)
            g_passOpen = nullptr;
    }
    return left;
}

// ---------------------------------------------------------------------------------------------
// Device hooks: Present, Reset, the depth buffer, and the state-block pair that wipes them on Windows' Direct3D

enum { kReset = 16, kPresent = 17, kSetDepthStencilSurface = 39, kBeginStateBlock = 60, kEndStateBlock = 61, kDrawPrimitiveUP = 83 };
enum { kFxRelease = 2, kFxBegin = 63, kFxEnd = 67 };
typedef HRESULT(WINAPI* PresentFn)(IDirect3DDevice9*, const RECT*, const RECT*, HWND, const RGNDATA*);
typedef HRESULT(WINAPI* ResetFn)(IDirect3DDevice9*, D3DPRESENT_PARAMETERS*);
typedef HRESULT(WINAPI* SetDepthStencilFn)(IDirect3DDevice9*, IDirect3DSurface9*);
typedef HRESULT(WINAPI* BeginStateBlockFn)(IDirect3DDevice9*);
typedef HRESULT(WINAPI* EndStateBlockFn)(IDirect3DDevice9*, IDirect3DStateBlock9**);
typedef HRESULT(WINAPI* DrawUPFn)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, const void*, UINT);
static DrawUPFn g_drawUP;
static PresentFn g_present;
static ResetFn g_reset;
static SetDepthStencilFn g_setDepthStencil;
static BeginStateBlockFn g_beginStateBlock;
static EndStateBlockFn g_endStateBlock;

static HRESULT WINAPI HookReset(IDirect3DDevice9* dev, D3DPRESENT_PARAMETERS* pp);
static HRESULT WINAPI HookPresent(IDirect3DDevice9* dev, const RECT* src, const RECT* dst, HWND wnd, const RGNDATA* dirty)
{
    g_afterSeen = g_doneThisFrame = false;
    g_finalOpen = nullptr;
    g_passOpen = nullptr;
    g_finalTexture = nullptr;
    g_aaDone = false;
    g_depthThisFrame = false;
    ++g_frames;
    if (g_recordOrder)
    {
        Log("ORDER %s", g_order[0] ? g_order : "(no effect began on the back buffer)");
        g_recordOrder = false;
    }
    static DWORD lastOrder;
    DWORD now = GetTickCount();
    if (Wanted() && (!lastOrder || now - lastOrder >= 30000))
    {
        lastOrder = now;
        g_recordOrder = true;
        g_order[0] = 0;
    }
    CollectTimings(g_aoTimer);
    CollectTimings(g_aaTimer);
    CollectTimings(g_shaftsTimer);
    CollectTimings(g_wetTimer);
    EverySecond(dev);
    return g_present(dev, src, dst, wnd, dirty);
}

// The game resets the device when it loses the screen (alt-tab). Everything we made must go first.
static HRESULT WINAPI HookReset(IDirect3DDevice9* dev, D3DPRESENT_PARAMETERS* pp)
{
    // Logged on every Reset, whatever was made (haze alone makes nothing to release).
    Log("reset: resources released");
    ReleaseResources();
    ForgetDepth();
    g_resourcesFailed = g_depthResourcesFailed = false;
    return g_reset(dev, pp);
}

// The pack's pass-through draws the treated picture onto the back buffer with one DrawPrimitiveUP. Inside the
// recognised pass (see HookFxBegin), the first such draw whose stage-0 texture is the treated picture is replaced by
// the smoothing draw (or, in split screen, followed by it on the right half). Any other draw goes through unchanged.
static HRESULT WINAPI HookDrawUP(IDirect3DDevice9* dev, D3DPRIMITIVETYPE type, UINT count, const void* data, UINT stride)
{
    if (g_passOpen && !g_busy && !g_aaDone && g_finalTexture)
    {
        IDirect3DBaseTexture9* bound = nullptr;
        dev->GetTexture(0, &bound);
        bool picture = bound && bound == (IDirect3DBaseTexture9*)g_finalTexture;
        if (bound)
            bound->Release();
        if (picture)
        {
            g_aaDone = true;
            g_busy = true;
            HRESULT hr = D3D_OK;
            if (g_cfg.split)
                hr = g_drawUP(dev, type, count, data, stride);
            bool smoothed = RunSmoothing(dev, g_finalTexture, g_cfg.split);
            if (!smoothed && !g_cfg.split)
                hr = g_drawUP(dev, type, count, data, stride);
            // The draw replaced was a DrawPrimitiveUP, which leaves stream 0 unset: leave the device as it would have.
            if (smoothed && !g_cfg.split)
                dev->SetStreamSource(0, nullptr, 0, 0);
            g_busy = false;
            if (smoothed)
            {
                ++g_aaDraws;
                if (g_recordOrder)
                    OrderNote("[AA]");
                if (!g_aaLogged)
                {
                    g_aaLogged = true;
                    Log("aa: replacing the pass-through (its draw onto the back buffer)%s", g_cfg.split ? ", right half (split screen)" : "");
                }
            }
            return hr;
        }
    }
    return g_drawUP(dev, type, count, data, stride);
}

static HRESULT WINAPI HookSetDepthStencil(IDirect3DDevice9* dev, IDirect3DSurface9* surface)
{
    if (surface && !g_busy)
        NoteDepth(dev, surface);
    return g_setDepthStencil(dev, surface);
}

static void InstallDeviceHooks(IDirect3DDevice9* dev);

static HRESULT WINAPI HookEndStateBlock(IDirect3DDevice9* dev, IDirect3DStateBlock9** out)
{
    HRESULT hr = g_endStateBlock(dev, out);
    InstallDeviceHooks(dev);
    return hr;
}

// While a state block is being recorded the table holds the recording versions of the calls, which must not be
// mixed with the originals we saved: only the End hook goes back in then; the rest after End.
static HRESULT WINAPI HookBeginStateBlock(IDirect3DDevice9* dev)
{
    HRESULT hr = g_beginStateBlock(dev);
    void* p = HookSlot(dev, kEndStateBlock, (void*)HookEndStateBlock);
    if (p)
        g_endStateBlock = (EndStateBlockFn)p;
    return hr;
}

static void InstallDeviceHooks(IDirect3DDevice9* dev)
{
    void* p;
    if ((p = HookSlot(dev, kPresent, (void*)HookPresent))) g_present = (PresentFn)p;
    if ((p = HookSlot(dev, kReset, (void*)HookReset))) g_reset = (ResetFn)p;
    if ((p = HookSlot(dev, kSetDepthStencilSurface, (void*)HookSetDepthStencil))) g_setDepthStencil = (SetDepthStencilFn)p;
    if ((p = HookSlot(dev, kBeginStateBlock, (void*)HookBeginStateBlock))) g_beginStateBlock = (BeginStateBlockFn)p;
    if ((p = HookSlot(dev, kEndStateBlock, (void*)HookEndStateBlock))) g_endStateBlock = (EndStateBlockFn)p;
    if ((p = HookSlot(dev, kDrawPrimitiveUP, (void*)HookDrawUP))) g_drawUP = (DrawUPFn)p;
}

typedef HRESULT(WINAPI* CreateEffectFn)(IDirect3DDevice9*, HMODULE, LPCSTR, const D3DXMACRO*, ID3DXInclude*, DWORD,
    ID3DXEffectPool*, ID3DXEffect**, ID3DXBuffer**);
static CreateEffectFn g_createEffect;

static HRESULT WINAPI HookCreateEffect(IDirect3DDevice9* dev, HMODULE module, LPCSTR resource, const D3DXMACRO* defines,
    ID3DXInclude* include, DWORD flags, ID3DXEffectPool* pool, ID3DXEffect** out, ID3DXBuffer** errors)
{
    HRESULT hr = g_createEffect(dev, module, resource, defines, include, flags, pool, out, errors);
    if (FAILED(hr) || !out || !*out || IS_INTRESOURCE(resource))
        return hr;
    if (!g_device)
    {
        g_device = dev;
        InstallDeviceHooks(dev);
        void* p;
        if ((p = HookSlot(*out, kFxBegin, (void*)HookFxBegin))) g_fxBegin = (FxBeginFn)p;
        if ((p = HookSlot(*out, kFxEnd, (void*)HookFxEnd))) g_fxEnd = (FxEndFn)p;
        if ((p = HookSlot(*out, kFxRelease, (void*)HookFxRelease))) g_fxRelease = (FxReleaseFn)p;
        Log("hooks installed (first effect: %s)", resource);
    }
    Learn(*out, resource);
    return hr;
}

// [Shadows] Unlock: the game's world shadows with the Xbox 360 pack's shaders. speed.exe sets the Video menu's highest
// shadow level (0x9018B8) in 0x6D2100 from its shader effects' quality levels, which it reads from a "shadowLevel" tag
// on the techniques of its own shaders; the pack's shaders have none and X360Stuff picks techniques itself, so every
// effect reports 0, the menu greys Shadow Detail out, the game lowers the setting to 0 and draws no shadow map
// (docs/visual-notes.md, "Shadows are greyed out"). Both calls of 0x6D2100 (0x6DB0D5, 0x6DFA02) are rerouted through
// ShadowMaxWrapper, which runs the game's function and then lifts a 0 maximum to Level (2, its value before the pack).
// Only the menu's maximum is changed: the effects' level (0x982C3C) also picks shader techniques while drawing.
static void(__cdecl* g_shadowMaxFunction)();
static DWORD g_shadowMaxAddress;
static int g_shadowLevel;

static void __cdecl ShadowMaxWrapper()
{
    g_shadowMaxFunction();
    if (!Readable(g_shadowMaxAddress, 4))
        return;
    int* max = (int*)(UINT_PTR)g_shadowMaxAddress;
    if (*max <= 0 && !Writable(g_shadowMaxAddress, 4))
    {
        static bool logged;
        if (!logged)
            Log("shadows: the highest shadow level at 0x%08lX cannot be written ([Shadows] MaxAddress?): left at %d",
                (unsigned long)g_shadowMaxAddress, *max);
        logged = true;
    }
    else if (*max <= 0)
    {
        Log("shadows: the game set the highest shadow level to %d; lifted to %d", *max, g_shadowLevel);
        *max = g_shadowLevel;
    }
}

static void InstallShadowUnlock()
{
    if (!GetPrivateProfileIntA("Shadows", "Unlock", 0, g_iniPath))
        return;
    g_shadowMaxFunction = (void(__cdecl*)())(UINT_PTR)IniAddress("Shadows", "Function", "0x6D2100");
    g_shadowMaxAddress = IniAddress("Shadows", "MaxAddress", "0x9018B8");
    g_shadowLevel = GetPrivateProfileIntA("Shadows", "Level", 2, g_iniPath);
    if (g_shadowLevel < 1) g_shadowLevel = 1;
    if (g_shadowLevel > 2) g_shadowLevel = 2;
    char text[256];
    GetPrivateProfileStringA("Shadows", "CallSites", "0x6DB0D5,0x6DFA02", text, sizeof(text), g_iniPath);
    for (char* part = strtok(text, ", "); part; part = strtok(nullptr, ", "))
    {
        DWORD site = strtoul(part, nullptr, 0);
        BYTE* at = (BYTE*)(UINT_PTR)site;
        if (!Readable(site, 5) || at[0] != 0xE8 ||
            (DWORD)(site + 5 + *(INT32*)(at + 1)) != (DWORD)(UINT_PTR)g_shadowMaxFunction)
        {
            Log("shadows: call site 0x%08lX is not a call to 0x%08lX: left alone", (unsigned long)site,
                (unsigned long)(UINT_PTR)g_shadowMaxFunction);
            continue;
        }
        DWORD old;
        if (!VirtualProtect(at, 5, PAGE_EXECUTE_READWRITE, &old))
        {
            Log("shadows: call site 0x%08lX cannot be written: left alone", (unsigned long)site);
            continue;
        }
        *(INT32*)(at + 1) = (INT32)((BYTE*)&ShadowMaxWrapper - (at + 5));
        VirtualProtect(at, 5, old, &old);
        FlushInstructionCache(GetCurrentProcess(), at, 5);
        Log("shadows: call site 0x%08lX rerouted through VisualBridge (highest shadow level kept at least %d)",
            (unsigned long)site, g_shadowLevel);
    }
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
    IniChanged();
    ReadConfig();
    Log("VisualBridge loaded: enabled=%d exposure=%d bloom=%d ao=%d aa=%d haze=%d shafts=%d wet=%d showdepth=%d showsun=%d split=%d "
        "identity=%d", g_cfg.enabled, g_cfg.exposure, g_cfg.bloom, g_cfg.ao, g_cfg.aa, g_cfg.haze, g_cfg.shafts, g_cfg.wet,
        g_cfg.showDepth, g_cfg.showSun, g_cfg.split, g_cfg.identity);
    if (g_cfg.wet)
        Log("wet settings: strength=%.2f blur=%.1f blur_steps=%d steps=%d distance=%.0f minup=%.2f", g_cfg.wetStrength, g_cfg.wetBlur,
            g_cfg.wetBlurSteps, g_cfg.wetSteps, g_cfg.wetMaxDistance, g_cfg.wetMinUp);
    bool ok = PatchImport("d3dx9_26.dll", "D3DXCreateEffectFromResourceA", (void*)HookCreateEffect, (void**)&g_createEffect);
    Log("effect import hook %s", ok ? "installed" : "NOT FOUND: the effect stays off");
    InstallShadowUnlock();
    return TRUE;
}
