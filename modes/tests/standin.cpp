// Stand-in for speed.exe to test DisplayModes.asi. In the order the ASI loader would, it loads DisplayModes.asi and
// the stand-in Widescreen Fix (mockfix.cpp, as NFSMostWanted.WidescreenFix.asi), asks the Fix for its mode list as
// the real Fix does at load, makes the Fix's "current settings" read, creates a borderless 1920x1080-style window,
// has the Fix place it for the chosen size (as after a Reset), then creates a Direct3D 9 device with a back buffer of
// that size in that window (d3d9.dll next to the stand-in = DXVK; none = Windows' own), draws a test pattern and
// presents it.
//
// Arguments: order=first|after|none (DisplayModes before the Fix, after it, or not at all; default first),
// reset (one device Reset at frame 10), size=WxH (the chosen size, default 2560x1440), ms=Q (back buffer multisampled as the game makes it: type
// NONMASKABLE, quality Q = the game's FSAA level; DXVK gives it 2^Q samples), hold=MS (keep presenting this long after READY, for a screen capture).
// Output lines: FIXLIST n list, OWNLIST n list (the stand-in's own enumeration: must be Windows' only), CURRENT w h,
// WINDOW x y w h CLIENT w h, DEVICE hr, BACKBUFFER w h, PRESENT frames failed first_hr, READY.
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

typedef int (*MockListFn)(char*, int);
typedef void (*MockPlaceFn)(HWND, int, int);
typedef void (*MockCurrentFn)(int*, int*);
typedef IDirect3D9*(WINAPI* CreateFn)(UINT);

static int OwnList(char* out, int size)
{
    DEVMODEW dm;
    int n = 0;
    out[0] = 0;
    DWORD largest = 0;
    for (DWORD i = 0;; i++)
    {
        memset(&dm, 0, sizeof(dm));
        dm.dmSize = sizeof(dm);
        if (!EnumDisplaySettingsW(NULL, i, &dm))
            break;
        n++;
        if (dm.dmPelsWidth * dm.dmPelsHeight > largest)
        {
            largest = dm.dmPelsWidth * dm.dmPelsHeight;
            snprintf(out, size, "largest=%lux%lu", dm.dmPelsWidth, dm.dmPelsHeight);
        }
    }
    return n;
}

// The test pattern, in back-buffer pixels; modes/tests/run.py draws the same one (keep the two in step).
static BYTE Pattern(int x, int y)
{
    // Everything inside 1920x1080, so every size shows all of it. Line spacing 13: odd, and prime to the 4- and
    // 7-pixel periods of the 2560 and 2240 shrinks, so the 64 lines fall at every sub-pixel position.
    if (x < 400 && y < 400)
        return ((x + y) & 1) ? 255 : 0;                                       // one-pixel checkerboard
    if (y >= 450 && y < 700 && x >= 450 && x < 450 + 13 * 64)
        return ((x - 450) % 13 == 0) ? 255 : 0;                               // one-pixel vertical lines
    if (x >= 1350 && x < 1700 && y < 13 * 64)
        return (y % 13 == 0) ? 255 : 0;                                       // one-pixel horizontal lines
    if (y >= 850 && y < 1050 && x < 1400)
        return (y - 850 == x / 7) ? 255 : 0;                                  // thin shallow diagonal
    return 0;
}

static LRESULT CALLBACK Proc(HWND w, UINT m, WPARAM a, LPARAM b)
{
    return DefWindowProcW(w, m, a, b);
}

int main(int argc, char** argv)
{
    const char* order = "first";
    int bw = 2560, bh = 1440, hold = 0, ms = 0, reset = 0;
    for (int i = 1; i < argc; i++)
    {
        if (!strncmp(argv[i], "order=", 6)) order = argv[i] + 6;
        else if (!strncmp(argv[i], "size=", 5)) sscanf(argv[i] + 5, "%dx%d", &bw, &bh);
        else if (!strncmp(argv[i], "hold=", 5)) hold = atoi(argv[i] + 5);
        else if (!strncmp(argv[i], "ms=", 3)) ms = atoi(argv[i] + 3);
        else if (!strcmp(argv[i], "reset")) reset = 1;
    }
    SetProcessDPIAware();  // as the Fix does before it makes the window
    setvbuf(stdout, NULL, _IONBF, 0);

    if (!strcmp(order, "first") && !LoadLibraryA("DisplayModes.asi")) { printf("cannot load DisplayModes.asi\n"); return 2; }
    HMODULE fix = LoadLibraryA("NFSMostWanted.WidescreenFix.asi");
    if (!fix) { printf("cannot load the stand-in Fix\n"); return 2; }
    if (!strcmp(order, "after") && !LoadLibraryA("DisplayModes.asi")) { printf("cannot load DisplayModes.asi\n"); return 2; }
    MockListFn list = (MockListFn)GetProcAddress(fix, "MockList");
    MockPlaceFn place = (MockPlaceFn)GetProcAddress(fix, "MockPlace");
    MockCurrentFn current = (MockCurrentFn)GetProcAddress(fix, "MockCurrent");

    static char text[65536];
    int n = list(text, sizeof(text));
    printf("FIXLIST %d%s\n", n, text);
    n = OwnList(text, sizeof(text));
    printf("OWNLIST %d %s\n", n, text);
    int cw = 0, ch = 0;
    current(&cw, &ch);
    printf("CURRENT %d %d\n", cw, ch);

    WNDCLASSW wc = {};
    wc.lpfnWndProc = Proc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"DisplayModesStandin";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);
    // The Fix's borderless window: made at the screen's height (WindowedMode 4), styles without caption or frame.
    HWND wnd = CreateWindowExW(WS_EX_TOPMOST, wc.lpszClassName, L"DisplayModes stand-in", WS_POPUP | WS_VISIBLE, 0, 0,
                               GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN), NULL, NULL, wc.hInstance, NULL);
    place(wnd, bw, bh);
    SetWindowPos(wnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);  // on top for the capture
    MSG msg;
    while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
    RECT wr, cr;
    GetWindowRect(wnd, &wr);
    GetClientRect(wnd, &cr);
    printf("WINDOW %ld %ld %ld %ld CLIENT %ld %ld\n", wr.left, wr.top, wr.right - wr.left, wr.bottom - wr.top, cr.right, cr.bottom);

    // Direct3DCreate9 is imported (as speed.exe does), so DisplayModes can hook the import; d3d9.dll next to the
    // stand-in (DXVK) is found first.
    HMODULE d3d = GetModuleHandleA("d3d9.dll");
    char d3dPath[MAX_PATH] = "";
    GetModuleFileNameA(d3d, d3dPath, sizeof(d3dPath));
    printf("D3D9 %s\n", d3dPath);
    IDirect3D9* d9 = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.BackBufferWidth = bw;
    pp.BackBufferHeight = bh;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.Windowed = TRUE;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    if (ms > 0)
    {
        DWORD levels = 0;
        HRESULT ok = d9->CheckDeviceMultiSampleType(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, D3DFMT_X8R8G8B8, TRUE,
                                                    D3DMULTISAMPLE_NONMASKABLE, &levels);
        printf("MSAA quality %d asked; nonmaskable levels %lu (0x%08lX)\n", ms, levels, (unsigned long)ok);
        if (levels && (DWORD)ms >= levels)
        {
            // Windows' Direct3D numbers the levels per driver; the game would fail and retry without (0x6DB190).
            ms = (int)levels - 1;
            printf("MSAA quality lowered to %d\n", ms);
        }
        pp.MultiSampleType = D3DMULTISAMPLE_NONMASKABLE;
        pp.MultiSampleQuality = ms;
    }
    IDirect3DDevice9* dev = NULL;
    HRESULT hr = d9->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev);
    printf("DEVICE 0x%08lX\n", (unsigned long)hr);
    if (FAILED(hr)) return 3;
    IDirect3DSurface9* bb = NULL;
    dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    D3DSURFACE_DESC desc;
    bb->GetDesc(&desc);
    printf("BACKBUFFER %u %u\n", desc.Width, desc.Height);

    // The pattern as a texture drawn over the whole back buffer (one texel per pixel, point sampled): works whether
    // or not the back buffer is multisampled (every sample of a pixel gets the texel).
    IDirect3DTexture9 *sys = NULL, *gpu = NULL;
    dev->CreateTexture(bw, bh, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_SYSTEMMEM, &sys, NULL);
    dev->CreateTexture(bw, bh, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_DEFAULT, &gpu, NULL);
    D3DLOCKED_RECT lr;
    sys->LockRect(0, &lr, NULL, 0);
    for (int y = 0; y < bh; y++)
    {
        DWORD* row = (DWORD*)((BYTE*)lr.pBits + y * lr.Pitch);
        for (int x = 0; x < bw; x++)
        {
            BYTE v = Pattern(x, y);
            row[x] = 0xFF000000u | (v << 16) | (v << 8) | v;
        }
    }
    sys->UnlockRect(0);
    HRESULT up = dev->UpdateTexture(sys, gpu);
    printf("UPLOAD 0x%08lX\n", (unsigned long)up);
    struct V { float x, y, z, w, u, v; };
    const V quad[4] = { { -0.5f, -0.5f, 0, 1, 0, 0 }, { bw - 0.5f, -0.5f, 0, 1, 1, 0 },
                        { -0.5f, bh - 0.5f, 0, 1, 0, 1 }, { bw - 0.5f, bh - 0.5f, 0, 1, 1, 1 } };

    int frames = 0, failed = 0;
    HRESULT firstBad = S_OK;
    DWORD readyAt = 0, start = GetTickCount();
    for (;;)
    {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        dev->BeginScene();
        dev->SetRenderTarget(0, bb);
        dev->SetRenderState(D3DRS_ZENABLE, FALSE);
        dev->SetRenderState(D3DRS_LIGHTING, FALSE);
        dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
        dev->SetTexture(0, gpu);
        dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
        dev->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
        dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(V));
        dev->EndScene();
        hr = dev->Present(NULL, NULL, NULL, NULL);
        frames++;
        if (FAILED(hr) && !failed++) firstBad = hr;
        if (reset && frames == 10)
        {
            // As the game does after a Video menu change: release default-pool objects, Reset, make them again.
            gpu->Release();
            gpu = NULL;
            bb->Release();
            HRESULT r = dev->Reset(&pp);
            printf("RESET 0x%08lX\n", (unsigned long)r);
            if (FAILED(r)) return 4;
            dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
            dev->CreateTexture(bw, bh, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_DEFAULT, &gpu, NULL);
            dev->UpdateTexture(sys, gpu);
        }
        if (frames == 30)
        {
            printf("PRESENT %d %d 0x%08lX\n", frames, failed, (unsigned long)firstBad);
            printf("READY\n");
            readyAt = GetTickCount();
        }
        if (readyAt && GetTickCount() - readyAt >= (DWORD)hold) break;
        if (GetTickCount() - start > 20000) break;
        Sleep(10);
    }
    printf("DONE %d %d\n", frames, failed);
    gpu->Release(); sys->Release(); bb->Release(); dev->Release(); d9->Release();
    DestroyWindow(wnd);
    return 0;
}
