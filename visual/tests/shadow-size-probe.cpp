// What a larger shadow map costs before the game is asked to make one (docs/visual-notes.md, "Shadows").
// Makes the same pair speed.exe makes at 0x6C8770 when g_ShadowDetail > 0 (with the Widescreen Fix's sizes and
// ShadowMapTextureFormat = 1): a colour render target (A8R8G8B8) and an INTZ depth texture, one level each, in the
// default pool, at each size given; reports whether each was made and how much of this 32-bit process's address
// space and committed memory it took (the game is a 32-bit process too, large-address-aware: 4 GB of addresses).
//     shadow-size-probe.exe 5461x4096 8192x6144 10922x8192 16384x16384
// Run it beside DXVK's d3d9.dll to measure DXVK (the game's back end), or without for Windows' own Direct3D.
#include <windows.h>
#include <psapi.h>
#include <d3d9.h>
#include <stdio.h>

static void Memory(SIZE_T* reserved, SIZE_T* committed)
{
    *reserved = *committed = 0;
    MEMORY_BASIC_INFORMATION info;
    for (BYTE* p = nullptr; VirtualQuery(p, &info, sizeof(info)); p = (BYTE*)info.BaseAddress + info.RegionSize)
    {
        if (info.State != MEM_FREE)
            *reserved += info.RegionSize;
        if (info.State == MEM_COMMIT)
            *committed += info.RegionSize;
        if ((UINT_PTR)info.BaseAddress + info.RegionSize < (UINT_PTR)info.BaseAddress)
            break;
    }
}

int main(int argc, char** argv)
{
    HWND wnd = CreateWindowExA(0, "STATIC", "shadow-size-probe", WS_OVERLAPPEDWINDOW, 0, 0, 640, 480, nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DCAPS9 caps = {};
    d3d->GetDeviceCaps(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, &caps);
    printf("caps MaxTextureWidth=%lu MaxTextureHeight=%lu\n", (unsigned long)caps.MaxTextureWidth, (unsigned long)caps.MaxTextureHeight);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = 640;
    pp.BackBufferHeight = 480;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    IDirect3DDevice9* dev = nullptr;
    if (FAILED(d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev)))
    {
        printf("device FAILED\n");
        return 1;
    }
    printf("available texture memory (device's estimate) %u MiB\n", dev->GetAvailableTextureMem() / (1024 * 1024));
    const D3DFORMAT intz = (D3DFORMAT)MAKEFOURCC('I', 'N', 'T', 'Z');
    for (int i = 1; i < argc; ++i)
    {
        unsigned w = 0, h = 0;
        if (sscanf(argv[i], "%ux%u", &w, &h) != 2)
            continue;
        SIZE_T r0, c0, r1, c1, r2, c2;
        Memory(&r0, &c0);
        IDirect3DTexture9* colour = nullptr, * depth = nullptr;
        HRESULT hc = dev->CreateTexture(w, h, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &colour, nullptr);
        HRESULT hd = dev->CreateTexture(w, h, 1, D3DUSAGE_DEPTHSTENCIL, intz, D3DPOOL_DEFAULT, &depth, nullptr);
        // Use them once, as the game does every frame (bind, clear), so a back end that makes memory lazily has made it.
        IDirect3DSurface9* cs = nullptr, * ds = nullptr;
        if (colour) colour->GetSurfaceLevel(0, &cs);
        if (depth) depth->GetSurfaceLevel(0, &ds);
        if (cs && ds)
        {
            dev->SetRenderTarget(0, cs);
            dev->SetDepthStencilSurface(ds);
            dev->BeginScene();
            dev->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
            dev->EndScene();
            dev->Present(nullptr, nullptr, nullptr, nullptr);
        }
        Memory(&r1, &c1);
        double mib = 1024.0 * 1024.0;
        printf("size %ux%u colour hr=0x%08lX depth hr=0x%08lX on-card %.1f MiB (4+4 bytes a pixel) address space %+.1f MiB committed %+.1f MiB "
               "available texture memory now %u MiB\n", w, h, (unsigned long)hc, (unsigned long)hd, (double)w * h * 8 / mib,
               ((double)r1 - (double)r0) / mib, ((double)c1 - (double)c0) / mib, dev->GetAvailableTextureMem() / (1024 * 1024));
        IDirect3DSurface9* back = nullptr;
        dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back);
        dev->SetRenderTarget(0, back);
        dev->SetDepthStencilSurface(nullptr);
        if (back) back->Release();
        if (cs) cs->Release();
        if (ds) ds->Release();
        if (colour) colour->Release();
        if (depth) depth->Release();
        Memory(&r2, &c2);
        printf("  after release: address space %+.1f MiB committed %+.1f MiB against before\n", ((double)r2 - (double)r0) / mib, ((double)c2 - (double)c0) / mib);
    }
    SIZE_T r, c;
    Memory(&r, &c);
    printf("process address space in use %.0f MiB, committed %.0f MiB\n", r / 1048576.0, c / 1048576.0);
    dev->Release();
    d3d->Release();
    return 0;
}
