// Stand-in for speed.exe to measure what GfxProbe.asi costs: a frame shaped like a race frame in call
// counts (about 4,000 draws, each inside an effect's Begin/BeginPass/EndPass/End with a setting changed
// and a few state and constant writes, spread over nine targets), presented as fast as possible for 8 s.
// It prints the frame rate of seconds 2 to 8. Run it with the probe's parts on, with all parts off
// (run.py bench --off), and with another GfxProbe.asi beside it, and compare. Uses a.fx and b.fx.
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>
#include <string.h>

static volatile DWORD g_flow = 6; // "driving" from the start, like the game's flow state
static volatile BYTE g_paused = 0;

struct V { float x, y, z; };

static void IniWrite(const char* section, const char* key, const char* value)
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    strcpy(strrchr(path, '\\') + 1, "GfxProbe.ini");
    WritePrivateProfileStringA(section, key, value, path);
}

int main()
{
    char text[64];
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_flow);
    IniWrite("Game", "DrivingAddress", text);
    IniWrite("Game", "DrivingValue", "6");
    snprintf(text, sizeof(text), "0x%08lX", (unsigned long)(UINT_PTR)&g_paused);
    IniWrite("Game", "PausedAddress", text);
    // No screenshots or dissections: this measures the steady cost only.
    IniWrite("Shots", "Interval", "1000");
    IniWrite("Dissect", "At", "1000");

    HMODULE probe = LoadLibraryA("GfxProbe.asi");
    HWND wnd = CreateWindowExA(0, "STATIC", "d3d9-bench", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 50, 50, 660, 520,
        nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = 640;
    pp.BackBufferHeight = 480;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev = nullptr;
    if (FAILED(d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev)))
        return 1;
    ID3DXEffect* fx[2] = {};
    D3DXCreateEffectFromResourceA(dev, nullptr, "IDI_TESTA_FX", nullptr, nullptr, 0, nullptr, &fx[0], nullptr);
    D3DXCreateEffectFromResourceA(dev, nullptr, "IDI_TESTB_FX", nullptr, nullptr, 0, nullptr, &fx[1], nullptr);
    if (!fx[0] || !fx[1])
        return 2;

    enum { kTargets = 8, kDrawsPerTarget = 450 };
    IDirect3DTexture9* texture[kTargets] = {};
    IDirect3DSurface9* surface[kTargets] = {}, * back = nullptr;
    for (int i = 0; i < kTargets; ++i)
    {
        dev->CreateTexture(256, 256, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &texture[i], nullptr);
        if (!texture[i])
            return 3;
        texture[i]->GetSurfaceLevel(0, &surface[i]);
    }
    dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back);

    const V tri[3] = { { -0.1f, 0.1f, 0.5f }, { 0.1f, 0.1f, 0.5f }, { 0.0f, -0.1f, 0.5f } };
    const float constant[4] = { 0.25f, 0.5f, 0.75f, 1.0f };
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    dev->SetFVF(D3DFVF_XYZ);
    printf("probe=%p\n", (void*)probe);

    DWORD start = GetTickCount(), measuredFrom = 0;
    int frames = 0, measured = 0;
    for (;;)
    {
        DWORD t = GetTickCount() - start;
        if (t >= 8000)
            break;
        if (t >= 2000 && !measuredFrom)
            measuredFrom = t;
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        dev->BeginScene();
        for (int target = 0; target <= kTargets; ++target)
        {
            dev->SetRenderTarget(0, target < kTargets ? surface[target] : back);
            dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(20, 20, 40), 1.0f, 0);
            for (int i = 0; i < kDrawsPerTarget; ++i)
            {
                ID3DXEffect* effect = fx[i & 1];
                UINT passes = 0;
                D3DXVECTOR4 value((float)i, 0, 0, 1);
                if (i & 1)
                    effect->SetVector("g_vSpin", &value);
                else
                    effect->SetVector("g_vTint", &value);
                dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
                dev->SetVertexShaderConstantF(40, constant, 1);
                dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
                // Without saving and restoring all device state around each effect, which no game does per draw.
                effect->Begin(&passes, D3DXFX_DONOTSAVESTATE | D3DXFX_DONOTSAVESHADERSTATE | D3DXFX_DONOTSAVESAMPLERSTATE);
                effect->BeginPass(0);
                dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, tri, sizeof(V));
                effect->EndPass();
                effect->End();
            }
        }
        dev->EndScene();
        dev->Present(nullptr, nullptr, nullptr, nullptr);
        ++frames;
        if (measuredFrom)
            ++measured;
    }
    double seconds = (GetTickCount() - start - measuredFrom) / 1000.0;
    printf("draws per frame %d\n", (kTargets + 1) * kDrawsPerTarget);
    printf("BENCH fps=%.1f frame_ms=%.3f (%d frames in %.1f s)\n", measured / seconds, 1000.0 * seconds / measured, measured, seconds);
    return 0;
}
