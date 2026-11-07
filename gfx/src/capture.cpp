// GfxProbe: saving a surface as a 24-bit BMP, and the race-start captures InputBridge asks for.
#include "probe.h"
#include <math.h>

bool g_own;
static HANDLE g_captureEvent;

void CaptureInit()
{
    g_captureEvent = CreateEventA(nullptr, FALSE, FALSE, "NFSMW_GfxCapture");
}

// Copies src (resolved if multisampled, converted to 8 bits per channel if wider) into system memory and
// writes it to path. On failure returns false and puts the failing step into note.
bool SaveSurface(IDirect3DDevice9* dev, IDirect3DSurface9* src, const char* path, char* note, size_t noteSize)
{
    g_own = true;
    IDirect3DSurface9* resolved = nullptr, * mem = nullptr;
    D3DSURFACE_DESC desc = {};
    D3DLOCKED_RECT lock;
    const char* failed = nullptr;
    D3DFORMAT format = D3DFMT_A8R8G8B8;
    if (FAILED(src->GetDesc(&desc)))
        failed = "GetDesc";
    else if (desc.Usage & D3DUSAGE_DEPTHSTENCIL)
        failed = "depth buffer (not saved)";
    else
    {
        if (desc.Format == D3DFMT_X8R8G8B8 || desc.Format == D3DFMT_A8R8G8B8)
            format = desc.Format;
        if (FAILED(dev->CreateRenderTarget(desc.Width, desc.Height, format, D3DMULTISAMPLE_NONE, 0, FALSE, &resolved, nullptr)))
            failed = "CreateRenderTarget";
        else if (FAILED(dev->StretchRect(src, nullptr, resolved, nullptr, D3DTEXF_NONE)))
            failed = "StretchRect";
        else if (FAILED(dev->CreateOffscreenPlainSurface(desc.Width, desc.Height, format, D3DPOOL_SYSTEMMEM, &mem, nullptr)))
            failed = "CreateOffscreenPlainSurface";
        else if (FAILED(dev->GetRenderTargetData(resolved, mem)))
            failed = "GetRenderTargetData";
        else if (FAILED(mem->LockRect(&lock, nullptr, D3DLOCK_READONLY)))
            failed = "LockRect";
    }
    if (!failed)
    {
        FILE* f = fopen(path, "wb");
        if (f)
        {
            DWORD rowBytes = (desc.Width * 3 + 3) & ~3u;
            BITMAPFILEHEADER fh = { 0x4D42, (DWORD)(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + rowBytes * desc.Height),
                0, 0, sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) };
            BITMAPINFOHEADER ih = { sizeof(ih), (LONG)desc.Width, (LONG)desc.Height, 1, 24, BI_RGB, rowBytes * desc.Height, 0, 0, 0, 0 };
            fwrite(&fh, sizeof(fh), 1, f);
            fwrite(&ih, sizeof(ih), 1, f);
            BYTE* row = new BYTE[rowBytes]();
            for (int y = (int)desc.Height - 1; y >= 0; --y) // BMP rows run bottom-up
            {
                const BYTE* line = (const BYTE*)lock.pBits + y * lock.Pitch;
                for (UINT x = 0; x < desc.Width; ++x)
                    memcpy(row + x * 3, line + x * 4, 3); // BGRX -> BGR
                fwrite(row, rowBytes, 1, f);
            }
            delete[] row;
            fclose(f);
        }
        else
            failed = "fopen";
        mem->UnlockRect();
    }
    if (mem) mem->Release();
    if (resolved) resolved->Release();
    if (note)
        snprintf(note, noteSize, "%s", failed ? failed : "");
    g_own = false;
    return !failed;
}

// The back buffer has no DXVK HUD or telemetry panel in it.
void CaptureGridIfRequested(IDirect3DDevice9* dev)
{
    static int count;
    if (!g_captureEvent || WaitForSingleObject(g_captureEvent, 0) != WAIT_OBJECT_0)
        return;
    IDirect3DSurface9* back = nullptr;
    D3DSURFACE_DESC desc = {};
    if (FAILED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) || FAILED(back->GetDesc(&desc)))
    {
        Log("Capture FAILED at GetBackBuffer");
        if (back) back->Release();
        return;
    }
    char dir[MAX_PATH], sub[MAX_PATH + 80], path[MAX_PATH + 160], note[64];
    ResolvePath(g_cfg.captureDir, dir);
    CreateDirectoryA(dir, nullptr);
    snprintf(sub, sizeof(sub), "%s\\%s", dir, g_cfg.label);
    CreateDirectoryA(sub, nullptr);
    SYSTEMTIME st;
    GetLocalTime(&st);
    snprintf(path, sizeof(path), "%s\\%04d%02d%02d-%02d%02d%02d-%02d.bmp", sub, st.wYear, st.wMonth, st.wDay, st.wHour,
        st.wMinute, st.wSecond, ++count);
    if (SaveSurface(dev, back, path, note, sizeof(note)))
        Log("Capture saved: %s (%ux%u, multisample %d)", path, desc.Width, desc.Height, (int)desc.MultiSampleType);
    else
        Log("Capture FAILED at %s", note);
    back->Release();
}

// A screenshot of the finished frame every Interval seconds of driving, Max per game start.
void ShotsTick(IDirect3DDevice9* dev)
{
    static int count;
    static DWORD next;
    if (!next)
        next = (DWORD)g_cfg.shotInterval * 1000;
    if (!g_driving || count >= g_cfg.maxShots || g_drivingMs < next)
        return;
    next += (DWORD)g_cfg.shotInterval * 1000;
    IDirect3DSurface9* back = nullptr;
    if (FAILED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)))
        return;
    char dir[MAX_PATH + 200], path[MAX_PATH + 260], note[64];
    snprintf(dir, sizeof(dir), "%s\\shots", RunDir());
    CreateDirectoryA(dir, nullptr);
    snprintf(path, sizeof(path), "%s\\shot-%03d-t%04lu.bmp", dir, ++count, (unsigned long)(g_drivingMs / 1000));
    LONGLONG before = Ticks();
    bool ok = SaveSurface(dev, back, path, note, sizeof(note));
    Log("SHOT n=%d t=%.1f ms=%.1f ok=%d path=%s", count, g_drivingMs / 1000.0, TicksToMs(Ticks() - before), ok ? 1 : 0, path);
    if (!ok)
        Log("SHOT n=%d FAILED at %s", count, note);
    back->Release();
}

static float HalfToFloat(WORD h)
{
    int exponent = (h >> 10) & 31, mantissa = h & 1023;
    float v;
    if (exponent == 0)
        v = ldexpf((float)mantissa, -24);
    else if (exponent == 31)
        v = mantissa ? NAN : INFINITY;
    else
        v = ldexpf((float)(mantissa + 1024), exponent - 25);
    return (h & 0x8000) ? -v : v;
}

// For targets that hold more than 8 bits per channel: the smallest, largest and average value over the
// colour channels, read in the target's own format (the BMP clips everything above 1).
bool SurfaceRange(IDirect3DDevice9* dev, IDirect3DSurface9* src, float* minOut, float* maxOut, float* meanOut)
{
    D3DSURFACE_DESC desc;
    if (FAILED(src->GetDesc(&desc)))
        return false;
    int channels, bytes; // channels stored per pixel, bytes per channel
    switch ((DWORD)desc.Format)
    {
    case D3DFMT_R16F: channels = 1; bytes = 2; break;
    case D3DFMT_G16R16F: channels = 2; bytes = 2; break;
    case D3DFMT_A16B16G16R16F: channels = 4; bytes = 2; break;
    case D3DFMT_R32F: channels = 1; bytes = 4; break;
    case D3DFMT_G32R32F: channels = 2; bytes = 4; break;
    case D3DFMT_A32B32G32R32F: channels = 4; bytes = 4; break;
    default: return false;
    }
    int used = channels > 3 ? 3 : channels; // not the alpha channel
    g_own = true;
    IDirect3DSurface9* resolved = nullptr, * mem = nullptr, * from = src;
    D3DLOCKED_RECT lock;
    bool ok = true;
    if (desc.MultiSampleType != D3DMULTISAMPLE_NONE)
    {
        ok = SUCCEEDED(dev->CreateRenderTarget(desc.Width, desc.Height, desc.Format, D3DMULTISAMPLE_NONE, 0, FALSE, &resolved, nullptr))
            && SUCCEEDED(dev->StretchRect(src, nullptr, resolved, nullptr, D3DTEXF_NONE));
        from = resolved;
    }
    ok = ok && SUCCEEDED(dev->CreateOffscreenPlainSurface(desc.Width, desc.Height, desc.Format, D3DPOOL_SYSTEMMEM, &mem, nullptr))
        && SUCCEEDED(dev->GetRenderTargetData(from, mem)) && SUCCEEDED(mem->LockRect(&lock, nullptr, D3DLOCK_READONLY));
    if (ok)
    {
        float lowest = INFINITY, highest = -INFINITY;
        double sum = 0;
        LONGLONG count = 0;
        for (UINT y = 0; y < desc.Height; ++y)
        {
            const BYTE* pixel = (const BYTE*)lock.pBits + y * lock.Pitch;
            for (UINT x = 0; x < desc.Width; ++x, pixel += channels * bytes)
                for (int c = 0; c < used; ++c)
                {
                    float v;
                    if (bytes == 2)
                        v = HalfToFloat(*(const WORD*)(pixel + c * 2));
                    else
                        memcpy(&v, pixel + c * 4, 4);
                    if (!isfinite(v))
                        continue;
                    if (v < lowest) lowest = v;
                    if (v > highest) highest = v;
                    sum += v;
                    ++count;
                }
        }
        mem->UnlockRect();
        ok = count > 0;
        if (ok)
        {
            *minOut = lowest;
            *maxOut = highest;
            *meanOut = (float)(sum / count);
        }
    }
    if (mem) mem->Release();
    if (resolved) resolved->Release();
    g_own = false;
    return ok;
}
