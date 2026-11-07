// Stand-in for speed.exe to test GfxProbe.asi: a D3D9 device with a 4x multisampled back buffer
// (like the game with anti-aliasing), stage 0 set to anisotropic filtering with MaxAnisotropy 4,
// one triangle drawn per frame for ~4 s, and two capture requests (the NFSMW_GfxCapture event).
// Run next to GfxProbe.asi; to test under DXVK, put DXVK's 32-bit d3d9.dll next to it as well.
// Expect in GfxProbe.log: "100% of draws: min=anisotropic ... maxAnisotropy=4" and two captures.
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>

struct Vertex { float x, y, z, rhw; DWORD color; };

int main()
{
    HMODULE probe = LoadLibraryA("GfxProbe.asi");
    printf("probe=%p\n", (void*)probe);
    HWND wnd = CreateWindowExA(0, "STATIC", "d3d9-sampler", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 50, 50, 660, 520,
        nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = 640;
    pp.BackBufferHeight = 480;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.MultiSampleType = D3DMULTISAMPLE_4_SAMPLES;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_ONE;
    IDirect3DDevice9* dev = nullptr;
    HRESULT hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev);
    printf("device hr=0x%08lx\n", hr);
    if (FAILED(hr))
        return 1;

    dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_ANISOTROPIC);
    dev->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    dev->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
    dev->SetSamplerState(0, D3DSAMP_MAXANISOTROPY, 4);
    dev->SetRenderState(D3DRS_LIGHTING, FALSE);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
    const Vertex tri[3] = { { 320, 60, 0.5f, 1, 0xFFFF0000 }, { 580, 420, 0.5f, 1, 0xFF00FF00 }, { 60, 420, 0.5f, 1, 0xFF0000FF } };

    HANDLE capture = OpenEventA(EVENT_MODIFY_STATE, FALSE, "NFSMW_GfxCapture");
    DWORD start = GetTickCount();
    int frames = 0, requested = 0;
    while (GetTickCount() - start < 17000)
    {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        dev->Clear(0, nullptr, D3DCLEAR_TARGET, D3DCOLOR_XRGB(20, 20, 40), 1.0f, 0);
        dev->BeginScene();
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, tri, sizeof(Vertex));
        dev->EndScene();
        DWORD t = GetTickCount() - start;
        if (capture && requested < 2 && t > 1000u * (requested + 1))
        {
            SetEvent(capture);
            ++requested;
        }
        dev->Present(nullptr, nullptr, nullptr, nullptr);
        ++frames;
    }
    printf("presented %d frames, requested %d captures\n", frames, requested);
    return 0;
}
