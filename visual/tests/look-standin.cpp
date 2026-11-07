// Stand-in for speed.exe to test VisualBridge.asi, with GfxProbe.asi beside it as the camera.
// Picture (640x480): grey background (64, from 6 s on 160), a white 16x16 patch at (472..488, 232..248),
// a light-grey (230) 16x16 box at (400..416, 420..436),
// and after the "before" effect begins, a grey-128 triangle standing in for the HUD. Effect A (the
// "after" effect) draws into a texture first, effect B (the "before" effect) begins on the back buffer.
// Modes (first argument): "hostile" = an A8R8G8B8 back buffer with 4x multisampling, cleared with alpha
// 0x40, and before the "before" effect begins every piece of device state set to something unusual, as
// the game leaves it; after the effect ends each is read back and mismatches are printed (STATE lines),
// and once the back buffer's alpha is read back (ALPHA line). "gap" = effect A is not drawn from 4.5 s
// to 7.2 s, so no pass runs across the brightness step.
// "scene" = the game's frame as it is with the Xbox 360 pack: a depth pre-pass into a 640x480 INTZ depth texture
// (as X360Stuff does), the scene drawn on the back buffer with the ordinary depth buffer, then an effect made
// from memory (D3DXCreateEffect, so VisualBridge cannot learn its name) runs its "downscale4x4alphaluminance"
// technique on a small target; the back buffer is copied to a texture, its "visualtreatment" technique draws
// that copy into a second 640x480 texture and a grey-90 marker at (40..56, 440..456) on it, and its
// "screen_passthru" technique copies that texture onto the back buffer (as the pack does: treatment into T1, then
// a pass-through); then the HUD triangle. The scene: camera at the origin looking along +z, 60
// degrees vertical field of view, near 0.5, far 1000; a floor (grey 128) 1 m below the camera up to a wall
// (grey 160) 10 m away and 4 m high; above it sky (cleared to grey 200, depth 1). "nointz" with "scene": no
// depth texture is made (the pre-pass is skipped). "hostile" with "scene": the hostile state is set before the
// treatment begins and read back after it ends, and other unusual state around the pass-through (read back after it,
// "after the pass-through" STATE lines; ALPHA2 = the back buffer's alpha after it). "nopass" with "scene": the treated
// picture is copied to the back buffer without the pass-through technique. Also in "scene": a black triangle with a
// hard diagonal edge and a black one-pixel line on the sky (for edge smoothing). "sun", "sunbehind", "sunside": the
// stand-in's camera and a sun direction for light shafts (see g_view); with "noplat" the view has no platform info,
// with "badplat" its world-to-clip matrix is all zero (VisualBridge must fall back to the camera and [Depth] FovY).
// "reload": [Test] AOShowcase is written to 0 at 4.5 s and back to 1 at 10.2 s (the .ini reread while running).
// "wet" (scene): a bright box on the floor 5 m ahead and a low box with a flat top, for wet reflections, with the
// view's matrix as in "sun"; "edge": the bright box at the left edge of the screen; "badmatrix": as "badplat".
// At 9 s the device is reset once. "Driving" from 0.5 s so GfxProbe takes a screenshot every second.
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>
#include <string.h>

static volatile DWORD g_flow = 3;
static volatile BYTE g_paused = 0;

struct V { float x, y, z; };
struct VC { float x, y, z, rhw; DWORD color; };

static void IniWrite(const char* file, const char* section, const char* key, const char* value)
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    strcpy(strrchr(path, '\\') + 1, file);
    WritePrivateProfileStringA(section, key, value, path);
}

static void Box(IDirect3DDevice9* dev, float x0, float y0, float x1, float y1, DWORD color)
{
    const VC quad[4] = { { x0 - 0.5f, y0 - 0.5f, 0.5f, 1, color }, { x1 - 0.5f, y0 - 0.5f, 0.5f, 1, color },
                         { x0 - 0.5f, y1 - 0.5f, 0.5f, 1, color }, { x1 - 0.5f, y1 - 0.5f, 0.5f, 1, color } };
    dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(VC));
}

struct VD { float x, y, z; DWORD color; };

// The scene's floor and wall, in view space (the stand-in's view and world transforms are identity).
// The picture's size: 640x480, or 1920x1080 in the "bench" mode, which also draws the scene g_repeat times per
// pass (about 600 draws a frame: a frame time near the game's), presents without waiting for the screen and prints frames per
// second (BENCH lines), to measure what VisualBridge costs the processor.
static UINT g_w = 640, g_h = 480;
static int g_repeat = 1;
static bool g_bench;
// "wet": a bright box standing on the floor 5 m ahead (x -1..1, up to 0.5 m above the camera), and a low box to the
// right whose flat top is 0.4 m above the floor; "edge" with it: the bright box at the screen's left edge instead and
// no low box.
static bool g_wet, g_wetEdge;

static void Scene(IDirect3DDevice9* dev)
{
    const VD floor[4] = { { -40, -1, 0.6f, 0xFF808080 }, { 40, -1, 0.6f, 0xFF808080 }, { -40, -1, 10, 0xFF808080 }, { 40, -1, 10, 0xFF808080 } };
    const VD wall[4] = { { -40, -1, 10, 0xFFA0A0A0 }, { 40, -1, 10, 0xFFA0A0A0 }, { -40, 3, 10, 0xFFA0A0A0 }, { 40, 3, 10, 0xFFA0A0A0 } };
    dev->SetVertexShader(nullptr);
    dev->SetPixelShader(nullptr);
    dev->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE);
    dev->SetRenderState(D3DRS_ZENABLE, TRUE);
    dev->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    dev->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    const float bx0 = g_wetEdge ? -5.0f : -1.0f, bx1 = g_wetEdge ? -3.0f : 1.0f;
    const VD box[4] = { { bx0, -1, 5, 0xFFFFFFFF }, { bx1, -1, 5, 0xFFFFFFFF }, { bx0, 0.5f, 5, 0xFFFFFFFF }, { bx1, 0.5f, 5, 0xFFFFFFFF } };
    const VD lowFront[4] = { { 1.2f, -1, 3, 0xFF5A5A5A }, { 2.0f, -1, 3, 0xFF5A5A5A }, { 1.2f, -0.6f, 3, 0xFF5A5A5A }, { 2.0f, -0.6f, 3, 0xFF5A5A5A } };
    const VD lowTop[4] = { { 1.2f, -0.6f, 3, 0xFF646464 }, { 2.0f, -0.6f, 3, 0xFF646464 }, { 1.2f, -0.6f, 3.6f, 0xFF646464 }, { 2.0f, -0.6f, 3.6f, 0xFF646464 } };
    for (int i = 0; i < g_repeat; ++i)
    {
        dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, floor, sizeof(VD));
        dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, wall, sizeof(VD));
        if (g_wet)
        {
            dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, box, sizeof(VD));
            if (!g_wetEdge)
            {
                dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, lowFront, sizeof(VD));
                dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, lowTop, sizeof(VD));
            }
        }
    }
    dev->SetRenderState(D3DRS_ZENABLE, FALSE);
}

static const char kTreatment[] =
    "float4 VS(float4 p : POSITION) : POSITION { return p; }\n"
    "float4 PS() : COLOR { return float4(0, 1, 0, 1); }\n"
    "technique downscale4x4alphaluminance { pass P0 { VertexShader = compile vs_2_0 VS(); PixelShader = compile ps_2_0 PS(); } }\n"
    "technique visualtreatment { pass P0 { } }\n"
    "technique screen_passthru { pass P0 { } }\n";

struct VT { float x, y, z, rhw, u, v; };

// The whole target drawn from a texture, texel for texel (fixed function: the texture's colour as it is).
static void Copy(IDirect3DDevice9* dev, IDirect3DTexture9* from, float w, float h)
{
    const VT quad[4] = { { -0.5f, -0.5f, 0.5f, 1, 0, 0 }, { w - 0.5f, -0.5f, 0.5f, 1, 1, 0 },
                         { -0.5f, h - 0.5f, 0.5f, 1, 0, 1 }, { w - 0.5f, h - 0.5f, 0.5f, 1, 1, 1 } };
    dev->SetTexture(0, from);
    dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    dev->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    dev->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    dev->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(VT));
    dev->SetTexture(0, nullptr);
    dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    dev->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
}

// The "sun" modes: a view, a camera and a sun direction laid out as speed.exe keeps them (docs/visual-notes.md,
// "Camera and sun"): the view holds the camera's address at +0x40; the camera starts with its world-to-camera matrix
// for row vectors, camera x to the right, y down the screen, z forward. The stand-in's camera looks along +z with +y
// up, so camera x = world x, camera y = -world y, camera z = world z.
// The view's platform info (eViewPlatInfo; its address at view + 0): the game rebuilds its world-to-clip matrix at
// + 0x80 every frame (camera matrix times projection, row vectors). The stand-in's world is its view space, so that
// matrix is the stand-in's own projection (camera (1, -1, 1) times the game's projection with -y).
static BYTE g_view[0x70];
static float g_plat[0x1A0 / 4];
static float g_camera[64];
static float g_sunDirection[4];
// The "shadows" modes: the menu's highest shadow level (0x9018B8 in the game, 2 before the game's check) and the
// game's function that sets it from the shader effects (0x6D2100; 0 with the Xbox 360 pack's shaders).
static int g_fakeShadowMax = 2, g_fakeShadowCalls = 0;
static void __cdecl FakeShadowMax()
{
    g_fakeShadowMax = 0;
    ++g_fakeShadowCalls;
}

// The game's SunInfo pointer (0x916054): non-zero when a sun entry exists; 0 in the "noinfo" mode.
static DWORD g_sunInfo;

static int g_mismatches;
static void Same(const char* what, DWORD got, DWORD wanted)
{
    if (got != wanted)
    {
        ++g_mismatches;
        printf("STATE mismatch: %s is 0x%lX, was set to 0x%lX\n", what, (unsigned long)got, (unsigned long)wanted);
    }
}

static const D3DRENDERSTATETYPE kHostile[] = { D3DRS_ALPHABLENDENABLE, D3DRS_ALPHATESTENABLE, D3DRS_FOGENABLE, D3DRS_STENCILENABLE,
    D3DRS_SRGBWRITEENABLE, D3DRS_SCISSORTESTENABLE, D3DRS_ZENABLE, D3DRS_ZWRITEENABLE };

int main(int argc, char** argv)
{
    bool hostile = false, gap = false, scene = false, nointz = false, intz2 = false, nopass = false, reload = false;
    for (int i = 1; i < argc; ++i)
    {
        reload |= !strcmp(argv[i], "reload");
        hostile |= !strcmp(argv[i], "hostile");
        gap |= !strcmp(argv[i], "gap");
        scene |= !strcmp(argv[i], "scene");
        nointz |= !strcmp(argv[i], "nointz");
        intz2 |= !strcmp(argv[i], "intz2");
        nopass |= !strcmp(argv[i], "nopass");
        g_bench |= !strcmp(argv[i], "bench");
    }
    if (g_bench)
    {
        g_w = 1920;
        g_h = 1080;
        g_repeat = 150;
    }
    char text[64];
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_flow);
    IniWrite("GfxProbe.ini", "Game", "DrivingAddress", text);
    IniWrite("GfxProbe.ini", "Game", "DrivingValue", "6");
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_paused);
    IniWrite("GfxProbe.ini", "Game", "PausedAddress", text);
    bool sun = false, sunBehind = false, sunSide = false, sunLeft = false, noInfo = false, noPlat = false, badPlat = false;
    for (int i = 1; i < argc; ++i)
    {
        noInfo |= !strcmp(argv[i], "noinfo");
        noPlat |= !strcmp(argv[i], "noplat");
        badPlat |= !strcmp(argv[i], "badplat") || !strcmp(argv[i], "badmatrix");
        g_wet |= !strcmp(argv[i], "wet");
        g_wetEdge |= !strcmp(argv[i], "edge");
        sun |= !strcmp(argv[i], "sun");
        sunBehind |= !strcmp(argv[i], "sunbehind");
        sunSide |= !strcmp(argv[i], "sunside");
        sunLeft |= !strcmp(argv[i], "sunleft");
    }
    // "shadows": a stand-in for the game's shadow-maximum function (0x6D2100 sets the menu's highest shadow level to 0
    // with the Xbox 360 pack's shaders) and its two call sites, as call instructions in a code block; VisualBridge's
    // [Shadows] Unlock must reroute both through its wrapper, which lifts the maximum back to Level. "shadowswrong":
    // the .ini names a different function, so neither site matches and nothing may be patched.
    bool shadows = false, shadowsWrong = false, shadowsReadOnly = false;
    for (int i = 1; i < argc; ++i)
    {
        shadows |= !strcmp(argv[i], "shadows");
        shadowsWrong |= !strcmp(argv[i], "shadowswrong");
        shadowsReadOnly |= !strcmp(argv[i], "shadowsro");
    }
    BYTE* shadowCode = nullptr;
    if (shadows || shadowsWrong || shadowsReadOnly)
    {
        shadowCode = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        for (int site = 0; site < 2; ++site)
        {
            BYTE* at = shadowCode + site * 5;
            at[0] = 0xE8;
            *(INT32*)(at + 1) = (INT32)((BYTE*)&FakeShadowMax - (at + 5));
        }
        shadowCode[10] = 0xC3;
        snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)((BYTE*)&FakeShadowMax + (shadowsWrong ? 1 : 0)));
        IniWrite("VisualBridge.ini", "Shadows", "Function", text);
        snprintf(text, sizeof(text), "0x%08lX,0x%08lX", (unsigned long)(UINT_PTR)shadowCode, (unsigned long)(UINT_PTR)(shadowCode + 5));
        IniWrite("VisualBridge.ini", "Shadows", "CallSites", text);
        // "shadowsro": the maximum's address points at a read-only page holding 0 (a wrong [Shadows] MaxAddress, say
        // into the game's constants): the wrapper must not write there (no crash) and must say so.
        DWORD* readOnly = nullptr;
        if (shadowsReadOnly)
        {
            readOnly = (DWORD*)VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            *readOnly = 0;
            DWORD old;
            VirtualProtect(readOnly, 4096, PAGE_READONLY, &old);
        }
        snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)(readOnly ? (void*)readOnly : (void*)&g_fakeShadowMax));
        IniWrite("VisualBridge.ini", "Shadows", "MaxAddress", text);
    }
    // The wet modes need the view's matrix too (world positions from depth); their sun is behind the camera.
    if (sun || sunBehind || sunSide || sunLeft || g_wet)
    {
        const float matrix[16] = { 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };
        memcpy(g_camera, matrix, sizeof(matrix));
        *(float**)(g_view + 0x40) = g_camera;
        if (!noPlat)
            *(float**)(g_view + 0) = g_plat;
        if (!badPlat)
        {
            D3DXMATRIX clip;
            D3DXMatrixPerspectiveFovLH(&clip, D3DX_PI / 3, (float)g_w / (float)g_h, 0.5f, 1000.0f);
            memcpy((BYTE*)g_plat + 0x80, &clip, sizeof(clip));
        }
        // sun: up and a little right, above the wall (screen about (0.630, 0.110)); behind: behind the camera;
        // side: in front but far off the right edge (screen x about 1.47).
        // left: the same height, left of the centre (screen about (0.370, 0.110)).
        const float up[3] = { 0.2f, 0.45f, 1 }, behind[3] = { 0.1f, 0.3f, -1 }, side[3] = { 1.5f, 0.3f, 1 }, left[3] = { -0.2f, 0.45f, 1 };
        memcpy(g_sunDirection, sun ? up : (sunBehind || g_wet) ? behind : sunLeft ? left : side, sizeof(up));
        snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)g_view);
        IniWrite("VisualBridge.ini", "Sun", "View", text);
        IniWrite("VisualBridge.ini", "Sun", "CameraOffset", "0x40");
        snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)g_sunDirection);
        IniWrite("VisualBridge.ini", "Sun", "Direction", text);
        g_sunInfo = noInfo ? 0 : (DWORD)(UINT_PTR)g_camera; // any non-zero address stands for "an entry exists"
        snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_sunInfo);
        IniWrite("VisualBridge.ini", "Sun", "Info", text);
    }
    LoadLibraryA("GfxProbe.asi");
    HMODULE look = LoadLibraryA("VisualBridge.asi");
    printf("look=%p\n", (void*)look);
    if (shadowCode)
    {
        ((void (*)())shadowCode)();
        printf("SHADOWMAX %d calls %d\n", g_fakeShadowMax, g_fakeShadowCalls);
    }

    HWND wnd = CreateWindowExA(0, "STATIC", "look-standin", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 50, 50, g_w + 20, g_h + 40,
        nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = g_w;
    pp.BackBufferHeight = g_h;
    pp.BackBufferFormat = hostile ? D3DFMT_A8R8G8B8 : D3DFMT_X8R8G8B8;
    pp.MultiSampleType = hostile ? D3DMULTISAMPLE_4_SAMPLES : D3DMULTISAMPLE_NONE;
    pp.EnableAutoDepthStencil = TRUE;
    pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = g_bench ? D3DPRESENT_INTERVAL_IMMEDIATE : D3DPRESENT_INTERVAL_ONE;
    IDirect3DDevice9* dev = nullptr;
    if (FAILED(d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev)))
        return 1;
    ID3DXEffect* fxA = nullptr, * fxB = nullptr;
    D3DXCreateEffectFromResourceA(dev, nullptr, "IDI_TESTA_FX", nullptr, nullptr, 0, nullptr, &fxA, nullptr);
    D3DXCreateEffectFromResourceA(dev, nullptr, "IDI_TESTB_FX", nullptr, nullptr, 0, nullptr, &fxB, nullptr);
    if (!fxA || !fxB)
        return 2;
    IDirect3DTexture9* target = nullptr;
    IDirect3DSurface9* targetSurface = nullptr, * back = nullptr, * autoDepth = nullptr;
    dev->CreateTexture(256, 256, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &target, nullptr);
    target->GetSurfaceLevel(0, &targetSurface);
    dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back);
    dev->GetDepthStencilSurface(&autoDepth);

    // Things for the scene mode: the effect made from memory, the depth texture and the pre-pass's colour target.
    ID3DXEffect* fxC = nullptr;
    IDirect3DTexture9* intz = nullptr;
    IDirect3DSurface9* intzSurface = nullptr, * prepass = nullptr, * intz2Surface = nullptr;
    IDirect3DTexture9* intz2Tex = nullptr;
    // As the pack does it: the finished main view is copied out of the back buffer ("resolved", the pack's T2), the
    // treatment draws from it into "treated" (the pack's T1), and a pass-through draws that onto the back buffer.
    IDirect3DTexture9* resolved = nullptr, * treated = nullptr;
    IDirect3DSurface9* resolvedSurface = nullptr, * treatedSurface = nullptr;
    const D3DFORMAT kIntz = (D3DFORMAT)MAKEFOURCC('I', 'N', 'T', 'Z');
    auto makeSceneTargets = [&]() {
        dev->CreateTexture(g_w, g_h, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &resolved, nullptr);
        dev->CreateTexture(g_w, g_h, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &treated, nullptr);
        resolved->GetSurfaceLevel(0, &resolvedSurface);
        treated->GetSurfaceLevel(0, &treatedSurface);
        if (nointz)
            return;
        HRESULT hr = dev->CreateTexture(g_w, g_h, 1, D3DUSAGE_DEPTHSTENCIL, kIntz, D3DPOOL_DEFAULT, &intz, nullptr);
        if (SUCCEEDED(hr))
            intz->GetSurfaceLevel(0, &intzSurface);
        dev->CreateRenderTarget(g_w, g_h, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &prepass, nullptr);
        if (intz2 && SUCCEEDED(dev->CreateTexture(256, 256, 1, D3DUSAGE_DEPTHSTENCIL, kIntz, D3DPOOL_DEFAULT, &intz2Tex, nullptr)))
            intz2Tex->GetSurfaceLevel(0, &intz2Surface);
        printf("scene: INTZ depth texture hr=0x%08lx\n", (unsigned long)hr);
    };
    if (scene)
    {
        ID3DXBuffer* errors = nullptr;
        if (FAILED(D3DXCreateEffect(dev, kTreatment, (UINT)strlen(kTreatment), nullptr, nullptr, 0, nullptr, &fxC, &errors)))
        {
            printf("treatment effect FAILED %s\n", errors ? (const char*)errors->GetBufferPointer() : "");
            return 4;
        }
        makeSceneTargets();
    }
    D3DXMATRIX projection, identity;
    D3DXMatrixPerspectiveFovLH(&projection, D3DX_PI / 3, (float)g_w / (float)g_h, 0.5f, 1000.0f);
    D3DXMatrixIdentity(&identity);

    // Things for the hostile mode: a vertex and an index buffer, a declaration, shaders, a texture.
    IDirect3DVertexBuffer9* vb = nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    IDirect3DVertexDeclaration9* decl = nullptr;
    IDirect3DVertexShader9* vs = nullptr;
    IDirect3DPixelShader9* ps = nullptr;
    IDirect3DTexture9* odd = nullptr;
    const D3DVERTEXELEMENT9 elements[] = { { 0, 0, D3DDECLTYPE_FLOAT3, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0 }, D3DDECL_END() };
    dev->CreateVertexBuffer(64, 0, 0, D3DPOOL_MANAGED, &vb, nullptr);
    dev->CreateIndexBuffer(64, 0, D3DFMT_INDEX16, D3DPOOL_MANAGED, &ib, nullptr);
    dev->CreateVertexDeclaration(elements, &decl);
    dev->CreateTexture(8, 8, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &odd, nullptr);
    ID3DXBuffer* code = nullptr;
    const char* vsText = "float4 main(float4 p : POSITION) : POSITION { return p; }";
    const char* psText = "float4 k0; float4 main() : COLOR { return k0; }";
    if (SUCCEEDED(D3DXCompileShader(vsText, (UINT)strlen(vsText), nullptr, nullptr, "main", "vs_2_0", 0, &code, nullptr, nullptr)))
        dev->CreateVertexShader((const DWORD*)code->GetBufferPointer(), &vs);
    if (SUCCEEDED(D3DXCompileShader(psText, (UINT)strlen(psText), nullptr, nullptr, "main", "ps_2_0", 0, &code, nullptr, nullptr)))
        dev->CreatePixelShader((const DWORD*)code->GetBufferPointer(), &ps);
    const float constants[4][4] = { { 1, 2, 3, 4 }, { 5, 6, 7, 8 }, { 9, 10, 11, 12 }, { 13, 14, 15, 16 } };
    float wideConstants[14][4];
    for (int i = 0; i < 14; ++i)
        for (int j = 0; j < 4; ++j)
            wideConstants[i][j] = 100.0f + i * 4 + j;
    const int intConstants[2][4] = { { 7, 3, 2, 0 }, { 9, 1, 3, 0 } };
    const RECT scissor = { 10, 10, 200, 200 };
    const D3DVIEWPORT9 window = { 50, 50, 300, 200, 0.0f, 1.0f };
    bool alphaRead = false;

    const V small[3] = { { -1.0f, 1.0f, 0.5f }, { -0.8f, 1.0f, 0.5f }, { -1.0f, 0.8f, 0.5f } };
    const VC hud[3] = { { 540, 400, 0.5f, 1, 0xFF808080 }, { 620, 400, 0.5f, 1, 0xFF808080 }, { 540, 460, 0.5f, 1, 0xFF808080 } };
    DWORD start = GetTickCount();
    int frames = 0;
    bool resetDone = false;
    for (;;)
    {
        DWORD t = GetTickCount() - start;
        // The wet modes run 45.5 s: the reflections' shaders take about 25-30 s to compile on a worker thread (with
        // the blur's ray loop), and the checks need screenshots after that. A loaded machine can push the compile
        // past the window: the test then fails on "wet shaders compiled", which is a timing failure, not a regression.
        if (t >= (g_bench ? (g_wet ? 65500u : 24500u) : g_wet ? 45500u : 14500u))
            break;
        // BENCH: frames in the second, and the average milliseconds a frame spends preparing (up to Present) and
        // inside Present (where DXVK waits when the graphics card is behind).
        static DWORD benchSecond, benchFrames;
        static double benchWork, benchPresent;
        LARGE_INTEGER qpf, frameStart;
        QueryPerformanceFrequency(&qpf);
        QueryPerformanceCounter(&frameStart);
        if (g_bench && t / 1000 != benchSecond)
        {
            printf("BENCH t=%lu frames=%lu work_ms=%.2f present_ms=%.2f\n", (unsigned long)benchSecond, (unsigned long)benchFrames,
                benchFrames ? benchWork / benchFrames : 0.0, benchFrames ? benchPresent / benchFrames : 0.0);
            benchSecond = t / 1000;
            benchFrames = 0;
            benchWork = benchPresent = 0;
        }
        ++benchFrames;
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        g_flow = t >= 500 ? 6 : 3;
        // "reload": the occlusion showcase switched off at 4.5 s and on again at 10.2 s, as a user editing the .ini
        // while the game runs (VisualBridge rereads it when the file changes).
        static int reloads;
        if (reload && ((reloads == 0 && t >= 4500) || (reloads == 1 && t >= 10200)))
        {
            IniWrite("VisualBridge.ini", "Test", "AOShowcase", reloads == 0 ? "0" : "1");
            ++reloads;
        }
        if (t >= 9000 && !resetDone && !g_bench)
        {
            // What the game does on alt-tab: everything in the default pool goes, then Reset.
            resetDone = true;
            back->Release();
            if (autoDepth) autoDepth->Release();
            targetSurface->Release();
            target->Release();
            fxA->OnLostDevice();
            fxB->OnLostDevice();
            if (fxC) fxC->OnLostDevice();
            if (intzSurface) intzSurface->Release();
            if (intz2Surface) intz2Surface->Release();
            if (intz2Tex) intz2Tex->Release();
            intz2Surface = nullptr;
            intz2Tex = nullptr;
            if (intz) intz->Release();
            if (prepass) prepass->Release();
            if (resolvedSurface) resolvedSurface->Release();
            if (treatedSurface) treatedSurface->Release();
            if (resolved) resolved->Release();
            if (treated) treated->Release();
            intzSurface = prepass = resolvedSurface = treatedSurface = nullptr;
            resolved = treated = nullptr;
            intz = nullptr;
            // Who answers the device's Reset, Present and DrawPrimitiveUP right now (call-table entries 16, 17, 83):
            // evidence for a Reset that fails because a plugin's hook was not in the table.
            {
                void** table = *(void***)dev;
                const int slots[3] = { 16, 17, 83 };
                printf("RESETHOOK");
                for (int slot : slots)
                {
                    HMODULE owner = nullptr;
                    char name[MAX_PATH] = "?";
                    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCSTR)table[slot], &owner) && owner)
                    {
                        GetModuleFileNameA(owner, name, MAX_PATH);
                        const char* base = strrchr(name, '\\');
                        memmove(name, base ? base + 1 : name, strlen(base ? base + 1 : name) + 1);
                    }
                    printf(" %d=%s", slot, name);
                }
                printf("\n");
            }
            HRESULT hr = dev->Reset(&pp);
            printf("reset hr=0x%08lx\n", hr);
            if (FAILED(hr))
                return 3;
            fxA->OnResetDevice();
            fxB->OnResetDevice();
            if (fxC) fxC->OnResetDevice();
            if (scene)
                makeSceneTargets();
            dev->CreateTexture(256, 256, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &target, nullptr);
            target->GetSurfaceLevel(0, &targetSurface);
            dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back);
            dev->GetDepthStencilSurface(&autoDepth);
        }
        DWORD grey = t >= 6000 ? 160 : 64;
        UINT passes = 0;
        dev->BeginScene();
        dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
        dev->SetRenderState(D3DRS_LIGHTING, FALSE);
        dev->SetRenderState(D3DRS_ZENABLE, FALSE);
        dev->SetRenderTarget(0, targetSurface);
        dev->SetDepthStencilSurface(nullptr);
        dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(10, 200, 30), 1.0f, 0);
        dev->SetFVF(D3DFVF_XYZ);
        if (scene)
        {
            dev->SetTransform(D3DTS_PROJECTION, &projection);
            dev->SetTransform(D3DTS_VIEW, &identity);
            dev->SetTransform(D3DTS_WORLD, &identity);
            // The depth pre-pass, as X360Stuff does it: its own colour target, the INTZ texture as depth.
            // "intz2": another, smaller INTZ depth texture bound and cleared first; VisualBridge must keep to
            // the one the size of the picture.
            if (intz2 && intz2Surface)
            {
                dev->SetRenderTarget(0, targetSurface);
                dev->SetDepthStencilSurface(intz2Surface);
                dev->Clear(0, nullptr, D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
            }
            if (intzSurface)
            {
                dev->SetRenderTarget(0, prepass);
                dev->SetDepthStencilSurface(intzSurface);
                dev->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
                Scene(dev);
            }
            // The scene on the back buffer with the ordinary depth buffer.
            dev->SetRenderTarget(0, back);
            dev->SetDepthStencilSurface(autoDepth);
            dev->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER | D3DCLEAR_STENCIL, D3DCOLOR_ARGB(0x40, 200, 200, 200), 1.0f, 0);
            Scene(dev);
            // Edge smoothing's test features, in the 3D picture before the treatment, on the sky: a black triangle
            // whose long edge (from (620,20) to (340,100)) is a hard stair-step, and a black line one pixel thick
            // from (20,60) to (300,70), like a wire.
            {
                const VC triangle[3] = { { 340 - 0.5f, 20 - 0.5f, 0.5f, 1, 0xFF000000 }, { 620 - 0.5f, 20 - 0.5f, 0.5f, 1, 0xFF000000 },
                                         { 340 - 0.5f, 100 - 0.5f, 0.5f, 1, 0xFF000000 } };
                const VC wire[4] = { { 20 - 0.5f, 60 - 0.5f, 0.5f, 1, 0xFF000000 }, { 300 - 0.5f, 70 - 0.5f, 0.5f, 1, 0xFF000000 },
                                     { 20 - 0.5f, 61 - 0.5f, 0.5f, 1, 0xFF000000 }, { 300 - 0.5f, 71 - 0.5f, 0.5f, 1, 0xFF000000 } };
                dev->SetVertexShader(nullptr);
                dev->SetPixelShader(nullptr);
                dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
                dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, triangle, sizeof(VC));
                dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, wire, sizeof(VC));
            }
            // The treatment's small-target technique: not the one VisualBridge waits for.
            dev->SetRenderTarget(0, targetSurface);
            dev->SetFVF(D3DFVF_XYZ);
            fxC->SetTechnique("downscale4x4alphaluminance");
            fxC->Begin(&passes, 0);
            fxC->BeginPass(0);
            dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, small, sizeof(V));
            fxC->EndPass();
            fxC->End();
            // The finished main view copied out; the treatment's picture starts as that copy.
            dev->StretchRect(back, nullptr, resolvedSurface, nullptr, D3DTEXF_NONE);
            dev->SetRenderTarget(0, treatedSurface);
            dev->SetDepthStencilSurface(nullptr);
            Copy(dev, resolved, (float)g_w, (float)g_h);
        }
        else if (!(gap && t >= 4500 && t < 7200))
        {
            fxA->SetTechnique("Main");
            fxA->Begin(&passes, 0);
            fxA->BeginPass(0);
            dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, small, sizeof(V));
            fxA->EndPass();
            fxA->End();
        }

        if (!scene)
        {
            dev->SetRenderTarget(0, back);
            dev->SetDepthStencilSurface(autoDepth); // as in the game: the main depth buffer is bound here
            dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_ARGB(0x40, grey, grey, grey), 1.0f, 0);
            dev->SetVertexShader(nullptr);
            dev->SetPixelShader(nullptr);
            dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
            Box(dev, 472, 232, 488, 248, 0xFFFFFFFF);
            Box(dev, 400, 420, 416, 436, 0xFFE6E6E6); // light grey 230: must never be pushed to white
        }
        else
        {
            dev->SetVertexShader(nullptr);
            dev->SetPixelShader(nullptr);
            dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
        }
        if (hostile)
        {
            // Everything the game might have left set when its HUD begins.
            dev->SetStreamSource(0, vb, 0, 12);
            dev->SetIndices(ib);
            dev->SetVertexDeclaration(decl);
            dev->SetVertexShader(vs);
            dev->SetPixelShader(ps);
            dev->SetPixelShaderConstantF(0, constants[0], 4);
            for (DWORD stage = 0; stage < 4; ++stage)
            {
                dev->SetTexture(stage, odd);
                dev->SetSamplerState(stage, D3DSAMP_MINFILTER, D3DTEXF_ANISOTROPIC);
                dev->SetSamplerState(stage, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
                dev->SetSamplerState(stage, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
                dev->SetSamplerState(stage, D3DSAMP_ADDRESSU, D3DTADDRESS_MIRROR);
                dev->SetSamplerState(stage, D3DSAMP_ADDRESSV, D3DTADDRESS_MIRROR);
                dev->SetSamplerState(stage, D3DSAMP_SRGBTEXTURE, TRUE);
            }
            for (D3DRENDERSTATETYPE state : kHostile)
                dev->SetRenderState(state, TRUE);
            dev->SetRenderState(D3DRS_COLORWRITEENABLE, D3DCOLORWRITEENABLE_RED);
            dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_CW);
            dev->SetRenderState(D3DRS_CLIPPLANEENABLE, 1);
            dev->SetRenderState(D3DRS_FILLMODE, D3DFILL_WIREFRAME);
            dev->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 1);
            dev->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT2);
            dev->SetScissorRect(&scissor);
            dev->SetViewport(&window);
        }
        if (scene)
        {
            // The treatment, into "treated"; VisualBridge's pass runs when it ends.
            fxC->SetTechnique("visualtreatment");
            fxC->Begin(&passes, 0);
            fxC->BeginPass(0);
            if (!hostile)
                Box(dev, 40, 440, 56, 456, 0xFF5A5A5A);
            fxC->EndPass();
            fxC->End();
        }
        else
        {
            fxB->SetTechnique("Bright");
            fxB->Begin(&passes, 0); // VisualBridge's pass runs here: after effect A, on the back buffer
            fxB->BeginPass(0);
            fxB->EndPass();
            fxB->End();
        }
        if (hostile)
        {
            // Read everything back: it must be what was set above.
            DWORD value = 0, fvf = 0;
            IDirect3DVertexBuffer9* gotVb = nullptr;
            IDirect3DIndexBuffer9* gotIb = nullptr;
            IDirect3DVertexDeclaration9* gotDecl = nullptr;
            IDirect3DVertexShader9* gotVs = nullptr;
            IDirect3DPixelShader9* gotPs = nullptr;
            IDirect3DSurface9* gotTarget = nullptr, * gotDepth = nullptr;
            UINT offset = 0, stride = 0;
            float gotConstants[4][4] = {};
            RECT gotScissor = {};
            D3DVIEWPORT9 gotWindow = {};
            dev->GetStreamSource(0, &gotVb, &offset, &stride);
            dev->GetIndices(&gotIb);
            dev->GetVertexDeclaration(&gotDecl);
            dev->GetVertexShader(&gotVs);
            dev->GetPixelShader(&gotPs);
            dev->GetRenderTarget(0, &gotTarget);
            dev->GetDepthStencilSurface(&gotDepth);
            dev->GetPixelShaderConstantF(0, gotConstants[0], 4);
            dev->GetScissorRect(&gotScissor);
            dev->GetViewport(&gotWindow);
            Same("stream 0 buffer", (DWORD)(UINT_PTR)gotVb, (DWORD)(UINT_PTR)vb);
            Same("stream 0 stride", stride, 12);
            Same("index buffer", (DWORD)(UINT_PTR)gotIb, (DWORD)(UINT_PTR)ib);
            Same("vertex declaration", (DWORD)(UINT_PTR)gotDecl, (DWORD)(UINT_PTR)decl);
            Same("vertex shader", (DWORD)(UINT_PTR)gotVs, (DWORD)(UINT_PTR)vs);
            Same("pixel shader", (DWORD)(UINT_PTR)gotPs, (DWORD)(UINT_PTR)ps);
            Same("render target", (DWORD)(UINT_PTR)gotTarget, (DWORD)(UINT_PTR)(scene ? treatedSurface : back));
            Same("depth buffer", (DWORD)(UINT_PTR)gotDepth, (DWORD)(UINT_PTR)(scene ? nullptr : autoDepth));
            Same("pixel shader constants", memcmp(gotConstants, constants, sizeof(constants)) != 0, 0);
            Same("scissor rectangle", memcmp(&gotScissor, &scissor, sizeof(scissor)) != 0, 0);
            Same("viewport", memcmp(&gotWindow, &window, sizeof(window)) != 0, 0);
            for (DWORD stage = 0; stage < 4; ++stage)
            {
                IDirect3DBaseTexture9* gotTexture = nullptr;
                dev->GetTexture(stage, &gotTexture);
                Same("texture", (DWORD)(UINT_PTR)gotTexture, (DWORD)(UINT_PTR)odd);
                if (gotTexture) gotTexture->Release();
                dev->GetSamplerState(stage, D3DSAMP_MINFILTER, &value); Same("min filter", value, D3DTEXF_ANISOTROPIC);
                dev->GetSamplerState(stage, D3DSAMP_MAGFILTER, &value); Same("mag filter", value, D3DTEXF_POINT);
                dev->GetSamplerState(stage, D3DSAMP_MIPFILTER, &value); Same("mip filter", value, D3DTEXF_LINEAR);
                dev->GetSamplerState(stage, D3DSAMP_ADDRESSU, &value); Same("address u", value, D3DTADDRESS_MIRROR);
                dev->GetSamplerState(stage, D3DSAMP_ADDRESSV, &value); Same("address v", value, D3DTADDRESS_MIRROR);
                dev->GetSamplerState(stage, D3DSAMP_SRGBTEXTURE, &value); Same("sRGB texture", value, TRUE);
            }
            for (D3DRENDERSTATETYPE state : kHostile)
            {
                dev->GetRenderState(state, &value);
                Same("a render state switched on", value, TRUE);
            }
            dev->GetRenderState(D3DRS_COLORWRITEENABLE, &value); Same("colour write mask", value, D3DCOLORWRITEENABLE_RED);
            dev->GetRenderState(D3DRS_CULLMODE, &value); Same("cull mode", value, D3DCULL_CW);
            dev->GetRenderState(D3DRS_CLIPPLANEENABLE, &value); Same("clip planes", value, 1);
            dev->GetRenderState(D3DRS_FILLMODE, &value); Same("fill mode", value, D3DFILL_WIREFRAME);
            dev->GetTextureStageState(0, D3DTSS_TEXCOORDINDEX, &value); Same("texture coordinate index", value, 1);
            dev->GetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, &value); Same("texture transform flags", value, D3DTTFF_COUNT2);
            if (gotVb) gotVb->Release();
            if (gotIb) gotIb->Release();
            if (gotDecl) gotDecl->Release();
            if (gotVs) gotVs->Release();
            if (gotPs) gotPs->Release();
            if (gotTarget) gotTarget->Release();
            if (gotDepth) gotDepth->Release();
            // The back buffer's alpha must still be what the clear put there.
            if (t >= 4000 && !alphaRead)
            {
                alphaRead = true;
                IDirect3DSurface9* resolved = nullptr, * memory = nullptr;
                D3DLOCKED_RECT lock;
                if (SUCCEEDED(dev->CreateRenderTarget(g_w, g_h, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &resolved, nullptr))
                    && SUCCEEDED(dev->StretchRect(back, nullptr, resolved, nullptr, D3DTEXF_NONE))
                    && SUCCEEDED(dev->CreateOffscreenPlainSurface(g_w, g_h, D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &memory, nullptr))
                    && SUCCEEDED(dev->GetRenderTargetData(resolved, memory)) && SUCCEEDED(memory->LockRect(&lock, nullptr, D3DLOCK_READONLY)))
                {
                    const DWORD* row = (const DWORD*)((const BYTE*)lock.pBits + 100 * lock.Pitch);
                    printf("ALPHA left=0x%02lX right=0x%02lX\n", (unsigned long)(row[100] >> 24), (unsigned long)(row[400] >> 24));
                    memory->UnlockRect();
                }
                if (memory) memory->Release();
                if (resolved) resolved->Release();
            }
            // Back to plain state for the stand-in's own HUD draw.
            dev->SetStreamSource(0, nullptr, 0, 0);
            dev->SetIndices(nullptr);
            for (DWORD stage = 0; stage < 4; ++stage)
            {
                dev->SetTexture(stage, nullptr);
                dev->SetSamplerState(stage, D3DSAMP_SRGBTEXTURE, FALSE);
            }
            for (D3DRENDERSTATETYPE state : kHostile)
                dev->SetRenderState(state, FALSE);
            dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
            dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
            dev->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
            dev->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
            dev->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
            dev->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
            const D3DVIEWPORT9 full = { 0, 0, g_w, g_h, 0.0f, 1.0f };
            dev->SetViewport(&full);
        }
        dev->SetVertexShader(nullptr);
        dev->SetPixelShader(nullptr);
        dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
        if (scene)
        {
            // The pack's pass-through: the treated picture onto the back buffer, then the HUD with the depth buffer.
            // "nopass": the same copy without the pass-through technique (nothing for edge smoothing to replace).
            dev->SetRenderTarget(0, back);
            if (hostile)
            {
                // State the pass-through's draw does not depend on, set to unusual values; read back after it.
                // c0-c17 and i0-i1: everything the wet reflections set (the review of 2026-10-30, item 1).
                dev->SetStreamSource(0, vb, 0, 12);
                dev->SetIndices(ib);
                dev->SetPixelShaderConstantF(0, constants[0], 4);
                dev->SetPixelShaderConstantF(4, wideConstants[0], 14);
                dev->SetPixelShaderConstantI(0, intConstants[0], 2);
                for (DWORD stage = 1; stage < 4; ++stage)
                {
                    dev->SetTexture(stage, odd);
                    dev->SetSamplerState(stage, D3DSAMP_MINFILTER, D3DTEXF_ANISOTROPIC);
                    dev->SetSamplerState(stage, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
                    dev->SetSamplerState(stage, D3DSAMP_ADDRESSU, D3DTADDRESS_MIRROR);
                    dev->SetSamplerState(stage, D3DSAMP_SRGBTEXTURE, TRUE);
                }
                dev->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_MIRROR);
                dev->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
                dev->SetScissorRect(&scissor);
                dev->SetRenderState(D3DRS_CLIPPLANEENABLE, 1);
                dev->SetRenderState(D3DRS_ALPHAREF, 0x33);
            }
            if (nopass)
                Copy(dev, treated, (float)g_w, (float)g_h);
            else
            {
                fxC->SetTechnique("screen_passthru");
                fxC->Begin(&passes, 0);
                fxC->BeginPass(0);
                Copy(dev, treated, (float)g_w, (float)g_h);
                fxC->EndPass();
                fxC->End();
            }
            if (hostile)
            {
                DWORD value = 0;
                IDirect3DVertexBuffer9* gotVb = nullptr;
                IDirect3DIndexBuffer9* gotIb = nullptr;
                IDirect3DSurface9* gotTarget = nullptr;
                UINT offset = 0, stride = 0;
                float gotConstants[4][4] = {}, gotWide[14][4] = {};
                int gotInts[2][4] = {};
                RECT gotScissor = {};
                dev->GetStreamSource(0, &gotVb, &offset, &stride);
                dev->GetIndices(&gotIb);
                dev->GetRenderTarget(0, &gotTarget);
                dev->GetPixelShaderConstantF(0, gotConstants[0], 4);
                dev->GetPixelShaderConstantF(4, gotWide[0], 14);
                dev->GetPixelShaderConstantI(0, gotInts[0], 2);
                Same("after the pass-through: pixel shader constants c4-c17", memcmp(gotWide, wideConstants, sizeof(wideConstants)) != 0, 0);
                Same("after the pass-through: integer constants i0-i1", memcmp(gotInts, intConstants, sizeof(intConstants)) != 0, 0);
                dev->GetScissorRect(&gotScissor);
                Same("after the pass-through: stream 0 buffer", (DWORD)(UINT_PTR)gotVb, (DWORD)(UINT_PTR)vb);
                Same("after the pass-through: index buffer", (DWORD)(UINT_PTR)gotIb, (DWORD)(UINT_PTR)ib);
                Same("after the pass-through: render target", (DWORD)(UINT_PTR)gotTarget, (DWORD)(UINT_PTR)back);
                Same("after the pass-through: pixel shader constants", memcmp(gotConstants, constants, sizeof(constants)) != 0, 0);
                Same("after the pass-through: scissor rectangle", memcmp(&gotScissor, &scissor, sizeof(scissor)) != 0, 0);
                for (DWORD stage = 1; stage < 4; ++stage)
                {
                    IDirect3DBaseTexture9* gotTexture = nullptr;
                    dev->GetTexture(stage, &gotTexture);
                    Same("after the pass-through: texture", (DWORD)(UINT_PTR)gotTexture, (DWORD)(UINT_PTR)odd);
                    if (gotTexture) gotTexture->Release();
                    dev->GetSamplerState(stage, D3DSAMP_MINFILTER, &value); Same("after the pass-through: min filter", value, D3DTEXF_ANISOTROPIC);
                    dev->GetSamplerState(stage, D3DSAMP_MAGFILTER, &value); Same("after the pass-through: mag filter", value, D3DTEXF_POINT);
                    dev->GetSamplerState(stage, D3DSAMP_ADDRESSU, &value); Same("after the pass-through: address u", value, D3DTADDRESS_MIRROR);
                    dev->GetSamplerState(stage, D3DSAMP_SRGBTEXTURE, &value); Same("after the pass-through: sRGB texture", value, TRUE);
                }
                dev->GetSamplerState(0, D3DSAMP_ADDRESSU, &value); Same("after the pass-through: stage 0 address u", value, D3DTADDRESS_MIRROR);
                dev->GetSamplerState(0, D3DSAMP_MIPFILTER, &value); Same("after the pass-through: stage 0 mip filter", value, D3DTEXF_LINEAR);
                dev->GetRenderState(D3DRS_CLIPPLANEENABLE, &value); Same("after the pass-through: clip planes", value, 1);
                dev->GetRenderState(D3DRS_ALPHAREF, &value); Same("after the pass-through: alpha reference", value, 0x33);
                if (gotVb) gotVb->Release();
                if (gotIb) gotIb->Release();
                if (gotTarget) gotTarget->Release();
                dev->SetStreamSource(0, nullptr, 0, 0);
                dev->SetIndices(nullptr);
                for (DWORD stage = 1; stage < 4; ++stage)
                {
                    dev->SetTexture(stage, nullptr);
                    dev->SetSamplerState(stage, D3DSAMP_SRGBTEXTURE, FALSE);
                    dev->SetSamplerState(stage, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
                }
                dev->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
                dev->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
                dev->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
                // The back buffer's alpha after the pass-through (the treated picture's, carried over), once.
                static bool alpha2Read;
                if (t >= 4000 && !alpha2Read)
                {
                    alpha2Read = true;
                    IDirect3DSurface9* plain = nullptr, * memory = nullptr;
                    D3DLOCKED_RECT lock;
                    if (SUCCEEDED(dev->CreateRenderTarget(g_w, g_h, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &plain, nullptr))
                        && SUCCEEDED(dev->StretchRect(back, nullptr, plain, nullptr, D3DTEXF_NONE))
                        && SUCCEEDED(dev->CreateOffscreenPlainSurface(g_w, g_h, D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &memory, nullptr))
                        && SUCCEEDED(dev->GetRenderTargetData(plain, memory)) && SUCCEEDED(memory->LockRect(&lock, nullptr, D3DLOCK_READONLY)))
                    {
                        const DWORD* sky = (const DWORD*)((const BYTE*)lock.pBits + 100 * lock.Pitch);
                        const DWORD* edge = (const DWORD*)((const BYTE*)lock.pBits + 50 * lock.Pitch);
                        const DWORD* floor = (const DWORD*)((const BYTE*)lock.pBits + 400 * lock.Pitch);
                        printf("ALPHA2 sky=0x%02lX edge=0x%02lX floor=0x%02lX\n", (unsigned long)(sky[100] >> 24),
                            (unsigned long)(edge[515] >> 24), (unsigned long)(floor[320] >> 24));
                        memory->UnlockRect();
                    }
                    if (memory) memory->Release();
                    if (plain) plain->Release();
                }
            }
            dev->SetDepthStencilSurface(autoDepth);
        }
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, hud, sizeof(VC));
        dev->EndScene();
        LARGE_INTEGER beforePresent, afterPresent;
        QueryPerformanceCounter(&beforePresent);
        dev->Present(nullptr, nullptr, nullptr, nullptr);
        QueryPerformanceCounter(&afterPresent);
        benchWork += (double)(beforePresent.QuadPart - frameStart.QuadPart) * 1000.0 / (double)qpf.QuadPart;
        benchPresent += (double)(afterPresent.QuadPart - beforePresent.QuadPart) * 1000.0 / (double)qpf.QuadPart;
        ++frames;
    }
    printf("STATE mismatches=%d\n", g_mismatches);
    printf("presented %d frames\n", frames);
    return 0;
}
