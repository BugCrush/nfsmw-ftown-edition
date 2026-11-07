// Stand-in for speed.exe to test GfxProbe.asi's frame map, effects, resources, game values, screenshots
// and dissection. Every frame has exactly these contents (checked by check-frame.py):
//   stage 1: a 64x64 A16B16G16R16F target, cleared to (255,128,0), no draws
//   stage 2: a 256x256 A8R8G8B8 texture target, cleared to (10,200,30); 3 draws of 1 triangle, effect A "Main"
//   stage 3: the 640x480 back buffer, cleared to (200,20,40); 5 draws of 2 triangles with effect B
//            "Bright", 1 draw of 1 triangle with no effect, then one copy from the texture target into
//            the top-left 64x64
// Timeline: "driving" from 1 s; at 5 s the watched value goes 7 -> 9, effect B's g_fExposure 0.5 -> 0.75
// and g_tDiffuse is set; "paused" from 8 s to 10 s; one grid capture is requested at 6 s; ends at 12.5 s
// (9.5 s of driving: four screenshots at 2 s intervals, with a margin). g_spinner changes every frame.
// Before loading the probe it writes its own addresses into GfxProbe.ini ([Game], [Watch]).
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>
#include <string.h>

static volatile DWORD g_flow = 3;   // 6 = driving, like the game's flow state
static volatile BYTE g_paused = 0;
static volatile DWORD g_testValue = 7;
static volatile DWORD g_spinner = 0;

struct V { float x, y, z; };
struct VC { float x, y, z, rhw; DWORD color; };

static void IniWrite(const char* section, const char* key, const char* value)
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    strcpy(strrchr(path, '\\') + 1, "GfxProbe.ini");
    WritePrivateProfileStringA(section, key, value, path);
}

static ID3DXEffect* LoadEffect(IDirect3DDevice9* dev, const char* resource, ID3DXEffectPool* pool)
{
    ID3DXEffect* fx = nullptr;
    ID3DXBuffer* errors = nullptr;
    HRESULT hr = D3DXCreateEffectFromResourceA(dev, nullptr, resource, nullptr, nullptr, 0, pool, &fx, &errors);
    if (FAILED(hr))
        printf("effect failed hr=0x%08lx %s\n", hr, errors ? (const char*)errors->GetBufferPointer() : "");
    return fx;
}

int main()
{
    char text[64];
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_flow);
    IniWrite("Game", "DrivingAddress", text);
    IniWrite("Game", "DrivingValue", "6");
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_paused);
    IniWrite("Game", "PausedAddress", text);
    snprintf(text, sizeof(text), "0x%08lX,u32", (unsigned long)(UINT_PTR)&g_testValue);
    IniWrite("Watch", "testvalue", text);
    IniWrite("Watch", "nowhere", "0x00000010,u32");
    snprintf(text, sizeof(text), "0x%08lX,u32", (unsigned long)(UINT_PTR)&g_spinner);
    IniWrite("Watch", "spinner", text);

    HMODULE probe = LoadLibraryA("GfxProbe.asi");
    printf("probe=%p\n", (void*)probe);
    LoadLibraryA("TintProof.asi"); // only present in the tint-proof run (run.py --tint)
    HWND wnd = CreateWindowExA(0, "STATIC", "d3d9-frame", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 50, 50, 660, 520,
        nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = 640;
    pp.BackBufferHeight = 480;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_ONE;
    IDirect3DDevice9* dev = nullptr;
    HRESULT hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev);
    printf("device hr=0x%08lx\n", hr);
    if (FAILED(hr))
        return 1;

    ID3DXEffectPool* pool = nullptr;
    D3DXCreateEffectPool(&pool);
    // Effect A is loaded, released and loaded again: the probe must end with one record for it.
    ID3DXEffect* fxA = LoadEffect(dev, "IDI_TESTA_FX", pool);
    if (fxA)
        fxA->Release();
    fxA = LoadEffect(dev, "IDI_TESTA_FX", pool);
    ID3DXEffect* fxB = LoadEffect(dev, "IDI_TESTB_FX", pool);
    ID3DXEffect* fxNumbered = LoadEffect(dev, MAKEINTRESOURCEA(77), pool);
    if (!fxA || !fxB || !fxNumbered)
        return 2;

    // One vertex and one pixel shader created directly, as a game without effects would.
    const char* vsText = "float4 main(float4 p : POSITION) : POSITION { return p; }";
    const char* psText = "float4 kTestColor; float4 main() : COLOR { return kTestColor; }";
    ID3DXBuffer* code = nullptr;
    IDirect3DVertexShader9* vs = nullptr;
    IDirect3DPixelShader9* ps = nullptr;
    if (SUCCEEDED(D3DXCompileShader(vsText, (UINT)strlen(vsText), nullptr, nullptr, "main", "vs_2_0", 0, &code, nullptr, nullptr)))
        dev->CreateVertexShader((const DWORD*)code->GetBufferPointer(), &vs);
    if (SUCCEEDED(D3DXCompileShader(psText, (UINT)strlen(psText), nullptr, nullptr, "main", "ps_2_0", 0, &code, nullptr, nullptr)))
        dev->CreatePixelShader((const DWORD*)code->GetBufferPointer(), &ps);
    printf("direct shaders vs=%p ps=%p\n", (void*)vs, (void*)ps);

    IDirect3DTexture9* target = nullptr, * wide = nullptr, * plain1 = nullptr, * plain2 = nullptr;
    IDirect3DSurface9* targetSurface = nullptr, * wideSurface = nullptr, * back = nullptr;
    dev->CreateTexture(256, 256, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &target, nullptr);
    dev->CreateTexture(64, 64, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A16B16G16R16F, D3DPOOL_DEFAULT, &wide, nullptr);
    dev->CreateTexture(32, 32, 1, 0, D3DFMT_DXT1, D3DPOOL_MANAGED, &plain1, nullptr);
    dev->CreateTexture(32, 32, 1, 0, D3DFMT_DXT1, D3DPOOL_MANAGED, &plain2, nullptr);
    if (!target || !wide)
        return 3;
    target->GetSurfaceLevel(0, &targetSurface);
    wide->GetSurfaceLevel(0, &wideSurface);
    dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back);

    const V small[3] = { { -1.0f, 1.0f, 0.5f }, { -0.8f, 1.0f, 0.5f }, { -1.0f, 0.8f, 0.5f } };
    const V quad[6] = { { 0.6f, 1.0f, 0.5f }, { 1.0f, 1.0f, 0.5f }, { 0.6f, 0.6f, 0.5f },
                        { 1.0f, 1.0f, 0.5f }, { 1.0f, 0.6f, 0.5f }, { 0.6f, 0.6f, 0.5f } };
    const VC corner[3] = { { 540, 400, 0.5f, 1, 0xFFFFFFFF }, { 620, 400, 0.5f, 1, 0xFFFFFFFF }, { 540, 460, 0.5f, 1, 0xFFFFFFFF } };
    const float constant[4] = { 0.25f, 0.5f, 0.75f, 1.0f };
    const RECT copyTo = { 0, 0, 64, 64 };
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    dev->SetRenderState(D3DRS_LIGHTING, FALSE);
    dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);

    HANDLE capture = OpenEventA(EVENT_MODIFY_STATE, FALSE, "NFSMW_GfxCapture");
    DWORD start = GetTickCount();
    int frames = 0;
    bool changed = false, requested = false;
    for (;;)
    {
        DWORD t = GetTickCount() - start;
        if (t >= 12500)
            break;
        ++g_spinner;
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        g_flow = t >= 1000 ? 6 : 3;
        g_paused = (t >= 8000 && t < 10000) ? 1 : 0;
        if (t >= 5000 && !changed)
        {
            changed = true;
            g_testValue = 9;
            fxB->SetFloat("g_fExposure", 0.75f);
            fxB->SetTexture("g_tDiffuse", target);
        }
        if (t >= 6000 && !requested && capture)
        {
            requested = true;
            SetEvent(capture);
        }

        UINT passes = 0;
        dev->BeginScene();
        dev->SetRenderTarget(0, wideSurface);
        dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(255, 128, 0), 1.0f, 0);

        dev->SetRenderTarget(0, targetSurface);
        dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(10, 200, 30), 1.0f, 0);
        dev->SetFVF(D3DFVF_XYZ);
        fxA->SetTechnique("Main");
        fxA->Begin(&passes, 0);
        fxA->BeginPass(0);
        for (int i = 0; i < 3; ++i)
            dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, small, sizeof(V));
        fxA->EndPass();
        fxA->End();

        dev->SetRenderTarget(0, back);
        dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(200, 20, 40), 1.0f, 0);
        dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
        dev->SetVertexShaderConstantF(40, constant, 1);
        D3DXVECTOR4 spin((float)frames, 0, 0, 0);
        fxB->SetVector("g_vSpin", &spin);
        fxB->SetTechnique("Bright");
        fxB->Begin(&passes, 0);
        fxB->BeginPass(0);
        for (int i = 0; i < 5; ++i)
            dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 2, quad, sizeof(V));
        fxB->EndPass();
        fxB->End();
        dev->SetVertexShader(nullptr);
        dev->SetPixelShader(nullptr);
        dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, corner, sizeof(VC));
        dev->StretchRect(targetSurface, nullptr, back, &copyTo, D3DTEXF_NONE);
        dev->EndScene();
        dev->Present(nullptr, nullptr, nullptr, nullptr);
        ++frames;
    }
    // Review focus: more distinct targets than the probe numbers. 130 small targets, each made current once.
    IDirect3DSurface9* many[130] = {};
    for (int i = 0; i < 130; ++i)
    {
        dev->CreateRenderTarget(8 + i, 8, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &many[i], nullptr);
        if (many[i])
            dev->SetRenderTarget(0, many[i]);
    }
    dev->SetRenderTarget(0, back);
    printf("presented %d frames\n", frames);
    return 0;
}
