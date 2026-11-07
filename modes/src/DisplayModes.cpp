// DisplayModes.asi: offers the game's Video menu sizes larger than the screen (supersampling), and keeps the window
// on the screen when one of them is chosen.
//
// How the menu gets its list (docs/visual-notes.md, "Supersampling through extra display modes"): the Widescreen Fix
// replaces the game's six fixed sizes with Windows' display modes, read once while it loads, through
// EnumDisplaySettingsW(NULL, 0, 1, 2, ...) until the call fails. This plugin patches EnumDisplaySettingsW in user32
// (the hot-patch space in front of it) and, only for calls made from the Widescreen Fix's own code, answers the indexes
// after Windows' last mode with the sizes in [Modes] Add (each a copy of the current mode with its width and height
// changed). Every other caller (DXVK, the game, the Fix's "current settings" reads) gets Windows' answer unchanged.
//
// After a Reset the Fix sizes the game's window to the chosen resolution and centres it; at 2560x1440 that is a
// window larger than the 1920x1080 screen, which would show the middle of the picture instead of shrinking it.
// So the first time the Fix calls us, its import of SetWindowPos is pointed at FitWindowPos, which scales a top-level
// window of this process that is larger than its monitor down to fit (same aspect ratio) and centres it. Sizes that
// fit are passed through untouched. The back buffer keeps the chosen size; the swap chain shrinks it into the window.
//
// The plugin must load before the Widescreen Fix (the ASI loader goes alphabetically: "DisplayModes" < "NFSMost...").
// Log: DisplayModes.log next to the plugin.
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static const char* FIX_NAME = "NFSMostWanted.WidescreenFix.asi";

static HMODULE g_self;
static char g_dir[MAX_PATH];
static FILE* g_log;

struct Mode { DWORD w, h; };
static Mode g_add[8];
static int g_addCount;
static int g_fit = 1;
static int g_area = 1;  // [Shrink] Area

typedef BOOL(WINAPI* EnumW)(LPCWSTR, DWORD, DEVMODEW*);
typedef BOOL(WINAPI* SetPosFn)(HWND, HWND, int, int, int, int, UINT);
static EnumW g_realEnum;   // user32!EnumDisplaySettingsW + 2 (past the two-byte "mov edi, edi")
static SetPosFn g_realSetPos;
static volatile LONG g_fixPatched;

static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list a;
    va_start(a, fmt);
    vfprintf(g_log, fmt, a);
    va_end(a);
    fputc('\n', g_log);
    fflush(g_log);
}

static HMODULE ModuleOf(const void* address)
{
    HMODULE m = NULL;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCSTR)address, &m);
    return m;
}

static const char* BaseName(HMODULE m, char* buf, DWORD size)
{
    buf[0] = 0;
    if (!m || !GetModuleFileNameA(m, buf, size))
        return "?";
    const char* s = strrchr(buf, '\\');
    return s ? s + 1 : buf;
}

static bool IsFix(HMODULE m)
{
    char buf[MAX_PATH];
    return m && _stricmp(BaseName(m, buf, sizeof(buf)), FIX_NAME) == 0;
}

// --- reading the settings -------------------------------------------------------------------------------------------

static void ReadSettings()
{
    char ini[MAX_PATH];
    snprintf(ini, sizeof(ini), "%s\\DisplayModes.ini", g_dir);
    char list[256];
    GetPrivateProfileStringA("Modes", "Add", "2240x1260,2560x1440", list, sizeof(list), ini);
    g_fit = GetPrivateProfileIntA("Window", "FitToScreen", 1, ini);
    g_area = GetPrivateProfileIntA("Shrink", "Area", 1, ini);
    for (char* p = list; *p && g_addCount < (int)(sizeof(g_add) / sizeof(g_add[0]));)
    {
        while (*p == ' ' || *p == ',' || *p == '\t')
            p++;
        if (!*p)
            break;
        unsigned w = 0, h = 0;
        if (sscanf(p, "%ux%u", &w, &h) == 2 && w >= 640 && h >= 480 && w <= 7680 && h <= 4320)
            g_add[g_addCount++] = { w, h };
        else
            Log("settings: ignored \"%.40s\" (want WIDTHxHEIGHT, 640x480 to 7680x4320)", p);
        while (*p && *p != ',')
            p++;
    }
}

// --- keeping the window on the screen ---------------------------------------------------------------------------------

static int g_fitLogs;

static BOOL WINAPI FitWindowPos(HWND wnd, HWND after, int x, int y, int cx, int cy, UINT flags)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(wnd, &pid);
    if (g_fit && !(flags & SWP_NOSIZE) && pid == GetCurrentProcessId() && !GetParent(wnd) && cx > 0 && cy > 0)
    {
        MONITORINFO mi = { sizeof(mi) };
        if (GetMonitorInfoW(MonitorFromWindow(wnd, MONITOR_DEFAULTTONEAREST), &mi))
        {
            int mw = mi.rcMonitor.right - mi.rcMonitor.left, mh = mi.rcMonitor.bottom - mi.rcMonitor.top;
            if (cx > mw || cy > mh)
            {
                double s = (double)mw / cx < (double)mh / cy ? (double)mw / cx : (double)mh / cy;
                int nw = (int)(cx * s + 0.5), nh = (int)(cy * s + 0.5);
                if (nw > mw) nw = mw;
                if (nh > mh) nh = mh;
                int nx = mi.rcMonitor.left + (mw - nw) / 2, ny = mi.rcMonitor.top + (mh - nh) / 2;
                if (g_fitLogs++ < 20)
                    Log("window: the Fix asked for %dx%d at (%d,%d); fitted to the screen: %dx%d at (%d,%d)",
                        cx, cy, x, y, nw, nh, (flags & SWP_NOMOVE) ? x : nx, (flags & SWP_NOMOVE) ? y : ny);
                cx = nw;
                cy = nh;
                if (!(flags & SWP_NOMOVE))
                {
                    x = nx;
                    y = ny;
                }
            }
        }
    }
    return g_realSetPos(wnd, after, x, y, cx, cy, flags);
}

// Points the named import of `module` at `hook`; returns the old value (or NULL if the import is not there).
static void* PatchImport(HMODULE module, const char* dll, const char* name, void* hook)
{
    BYTE* base = (BYTE*)module;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress)
        return NULL;
    for (IMAGE_IMPORT_DESCRIPTOR* d = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); d->Name; d++)
    {
        if (_stricmp((char*)(base + d->Name), dll) != 0 || !d->OriginalFirstThunk)
            continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + d->OriginalFirstThunk);
        IMAGE_THUNK_DATA* slots = (IMAGE_THUNK_DATA*)(base + d->FirstThunk);
        for (; names->u1.AddressOfData; names++, slots++)
        {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            IMAGE_IMPORT_BY_NAME* n = (IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData);
            if (strcmp((char*)n->Name, name) != 0)
                continue;
            void* old = (void*)slots->u1.Function;
            DWORD prot;
            VirtualProtect(&slots->u1.Function, sizeof(void*), PAGE_READWRITE, &prot);
            slots->u1.Function = (DWORD_PTR)hook;
            VirtualProtect(&slots->u1.Function, sizeof(void*), prot, &prot);
            return old;
        }
    }
    return NULL;
}

static void PatchFixWindow(HMODULE fix)
{
    if (InterlockedExchange(&g_fixPatched, 1))
        return;
    if (!g_fit)
    {
        Log("window: FitToScreen = 0, the Fix's window placement is left alone");
        return;
    }
    void* old = PatchImport(fix, "USER32.dll", "SetWindowPos", (void*)FitWindowPos);
    if (old)
    {
        g_realSetPos = (SetPosFn)old;
        Log("window: the Fix's SetWindowPos now keeps the game's window inside the screen");
    }
    else
        Log("window: the Fix imports no SetWindowPos; its window placement is left alone");
}

// --- the extra modes ----------------------------------------------------------------------------------------------

static DWORD g_realCount = (DWORD)-1;  // Windows' mode count (device NULL), counted once
static DWORD g_largestW, g_largestH;
static Mode g_offer[8];               // the Add sizes Windows does not already list
static int g_offerCount;
static int g_listLogs;

static void CountRealModes()
{
    DEVMODEW dm;
    DWORD i = 0;
    for (;; i++)
    {
        memset(&dm, 0, sizeof(dm));
        dm.dmSize = sizeof(dm);
        if (!g_realEnum(NULL, i, &dm))
            break;
        if ((DWORD64)dm.dmPelsWidth * dm.dmPelsHeight > (DWORD64)g_largestW * g_largestH)
        {
            g_largestW = dm.dmPelsWidth;
            g_largestH = dm.dmPelsHeight;
        }
        for (int k = 0; k < g_addCount; k++)
            if (g_add[k].w == dm.dmPelsWidth && g_add[k].h == dm.dmPelsHeight)
                g_add[k].w = 0;  // Windows has it already
    }
    for (int k = 0; k < g_addCount; k++)
        if (g_add[k].w)
            g_offer[g_offerCount++] = g_add[k];
    g_realCount = i;
}

static BOOL WINAPI HookEnum(LPCWSTR device, DWORD mode, DEVMODEW* dm)
{
    BOOL ok = g_realEnum(device, mode, dm);
    if (mode >= 0x80000000u)  // ENUM_CURRENT_SETTINGS, ENUM_REGISTRY_SETTINGS: never changed
        return ok;
    HMODULE caller = ModuleOf(__builtin_return_address(0));
    if (!IsFix(caller))
        return ok;
    PatchFixWindow(caller);
    if (device)
        return ok;
    if (g_realCount == (DWORD)-1)
        CountRealModes();
    if (ok || mode < g_realCount)
        return ok;
    DWORD k = mode - g_realCount;
    if (k == (DWORD)g_offerCount && g_listLogs++ < 4)
    {
        char text[256] = "";
        for (int j = 0; j < g_offerCount; j++)
            snprintf(text + strlen(text), sizeof(text) - strlen(text), " %lux%lu", g_offer[j].w, g_offer[j].h);
        Log("modes: asked by %s: Windows lists %lu (largest %lux%lu); told %lu, added:%s", FIX_NAME,
            g_realCount, g_largestW, g_largestH, g_realCount + g_offerCount, g_offerCount ? text : " none");
    }
    if (k >= (DWORD)g_offerCount || !dm)
        return FALSE;
    DEVMODEW cur;
    memset(&cur, 0, sizeof(cur));
    cur.dmSize = sizeof(cur);
    if (!g_realEnum(NULL, ENUM_CURRENT_SETTINGS, &cur))
        return FALSE;
    // The Fix hands over a zeroed DEVMODEW (dmSize 0); fill the fields it reads and the ones that go with them.
    dm->dmBitsPerPel = cur.dmBitsPerPel;
    dm->dmPelsWidth = g_offer[k].w;
    dm->dmPelsHeight = g_offer[k].h;
    dm->dmDisplayFrequency = cur.dmDisplayFrequency;
    dm->dmDisplayFlags = cur.dmDisplayFlags;
    dm->dmFields = DM_BITSPERPEL | DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY | DM_DISPLAYFLAGS;
    return TRUE;
}

// Hot-patch: user32's exported functions start with "mov edi, edi" (8B FF) and have five spare bytes in front.
// The spare bytes become "jmp HookEnum", the two bytes "jmp short -5"; the original is called at function + 2.
static bool HotPatch(BYTE* fn, void* hook)
{
    BYTE* pad = fn - 5;
    bool spare = true;
    for (int i = 0; i < 5; i++)
        spare = spare && (pad[i] == 0xCC || pad[i] == 0x90);
    if (fn[0] != 0x8B || fn[1] != 0xFF || !spare)
    {
        Log("modes: EnumDisplaySettingsW starts %02X %02X with %02X %02X %02X %02X %02X in front; not the expected "
            "hot-patch shape, nothing changed", fn[0], fn[1], pad[0], pad[1], pad[2], pad[3], pad[4]);
        return false;
    }
    DWORD prot;
    if (!VirtualProtect(pad, 7, PAGE_EXECUTE_READWRITE, &prot))
        return false;
    pad[0] = 0xE9;
    *(INT32*)(pad + 1) = (INT32)((BYTE*)hook - (pad + 5));
    *(volatile WORD*)fn = 0xF9EB;  // jmp short -5, written in one go
    VirtualProtect(pad, 7, prot, &prot);
    FlushInstructionCache(GetCurrentProcess(), pad, 7);
    return true;
}

// --- our own shrink at Present ----------------------------------------------------------------------------------
//
// DXVK (v3.1.1, dxvk_present_frag_blit.frag / _ms_blit.frag) shrinks a larger back buffer into the window with one
// bilinear mix per window pixel, or, for a multisampled back buffer as the game's is, a per-sample pick of one of two
// texels: thin lines pulse as they move (stand-in, modes/tests/shrink.py). Instead, at Present: the back buffer is
// copied to a texture (which also resolves the anti-aliasing), each window pixel is drawn into the back buffer's
// top-left corner as the average of exactly the back-buffer area it covers (up to 3x3 texels, weights by overlap),
// and Present is told to show only that corner, which DXVK copies to the window one to one. DXVK only: Windows' own
// Direct3D refuses a source rectangle unless the swap effect is COPY, and rewrites the call table on state blocks.

typedef IDirect3D9*(WINAPI* Create9Fn)(UINT);
typedef HRESULT(WINAPI* CreateDeviceFn)(IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS*,
                                        IDirect3DDevice9**);
typedef HRESULT(WINAPI* PresentFn)(IDirect3DDevice9*, const RECT*, const RECT*, HWND, const RGNDATA*);
typedef HRESULT(WINAPI* ResetFn)(IDirect3DDevice9*, D3DPRESENT_PARAMETERS*);
static Create9Fn g_realCreate9;
static CreateDeviceFn g_realCreateDevice;
static PresentFn g_realPresent;
static ResetFn g_realReset;
static HWND g_deviceWindow;
static IDirect3DTexture9* g_copy;
static UINT g_copyW, g_copyH;
static D3DFORMAT g_copyFormat;
static IDirect3DPixelShader9* g_shader;
static bool g_shaderTried;
static IDirect3DStateBlock9* g_state;
static int g_shrinkLogs;
static LARGE_INTEGER g_freq;
static double g_cpuMs;
static int g_cpuFrames;
static DWORD g_cpuSince;

enum { kReset = 16, kPresent = 17, kCreateDevice = 16 };

static void* HookEntry(void* object, int slot, void* hook)
{
    void** entry = &(*(void***)object)[slot];
    if (*entry == hook)
        return NULL;
    void* old = *entry;
    DWORD prot;
    VirtualProtect(entry, sizeof(void*), PAGE_EXECUTE_READWRITE, &prot);
    *entry = hook;
    VirtualProtect(entry, sizeof(void*), prot, &prot);
    return old;
}

static void ReleaseShrink()
{
    if (g_copy) g_copy->Release();
    if (g_state) g_state->Release();
    g_copy = NULL;
    g_state = NULL;
}

// One window pixel = the average of the back-buffer area [vpos * scale, (vpos + 1) * scale) on each axis, scale <= 2.
static const char* kShrinkShader =
    "sampler2D s0 : register(s0);\n"
    "float4 c0 : register(c0);\n"  // scale x, scale y, 1/width, 1/height of the back buffer
    "float4 main(float2 vpos : VPOS) : COLOR\n"
    "{\n"
    "    float2 a = vpos * c0.xy;\n"
    "    float2 b = a + c0.xy;\n"
    "    float2 i0 = floor(a);\n"
    "    float4 sum = 0;\n"
    "    for (int j = 0; j < 3; j++)\n"
    "    {\n"
    "        float y = i0.y + j;\n"
    "        float wy = saturate(min(b.y, y + 1) - max(a.y, y));\n"
    "        for (int i = 0; i < 3; i++)\n"
    "        {\n"
    "            float x = i0.x + i;\n"
    "            float wx = saturate(min(b.x, x + 1) - max(a.x, x));\n"
    "            sum += wx * wy * tex2Dlod(s0, float4((float2(x, y) + 0.5) * c0.zw, 0, 0));\n"
    "        }\n"
    "    }\n"
    "    return sum / (c0.x * c0.y);\n"
    "}\n";

struct Blob : IUnknown
{
    virtual LPVOID WINAPI GetBufferPointer() = 0;
    virtual DWORD WINAPI GetBufferSize() = 0;
};
typedef HRESULT(WINAPI* CompileFn)(LPCSTR, UINT, const void*, void*, LPCSTR, LPCSTR, DWORD, Blob**, Blob**, void**);

static void MakeShader(IDirect3DDevice9* dev)
{
    g_shaderTried = true;
    HMODULE d3dx = LoadLibraryA("d3dx9_26.dll");
    CompileFn compile = d3dx ? (CompileFn)GetProcAddress(d3dx, "D3DXCompileShader") : NULL;
    if (!compile)
    {
        Log("shrink: d3dx9_26.dll has no D3DXCompileShader; DXVK's shrink stays");
        return;
    }
    Blob *code = NULL, *errors = NULL;
    HRESULT hr = compile(kShrinkShader, (UINT)strlen(kShrinkShader), NULL, NULL, "main", "ps_3_0", 0, &code, &errors, NULL);
    if (FAILED(hr) || !code)
    {
        Log("shrink: shader did not compile (0x%08lX): %s", (unsigned long)hr,
            errors ? (const char*)errors->GetBufferPointer() : "");
    }
    else if (FAILED(hr = dev->CreatePixelShader((const DWORD*)code->GetBufferPointer(), &g_shader)))
        Log("shrink: CreatePixelShader failed (0x%08lX)", (unsigned long)hr);
    if (code) code->Release();
    if (errors) errors->Release();
}

// Draws the shrunk picture into the back buffer's top-left cw x ch. False: nothing was done.
static bool Shrink(IDirect3DDevice9* dev, IDirect3DSurface9* bb, const D3DSURFACE_DESC& d, int cw, int ch)
{
    if (!g_shaderTried)
        MakeShader(dev);
    if (!g_shader)
        return false;
    if (g_copy && (g_copyW != d.Width || g_copyH != d.Height || g_copyFormat != d.Format))
        ReleaseShrink();
    if (!g_copy)
    {
        HRESULT hr = dev->CreateTexture(d.Width, d.Height, 1, D3DUSAGE_RENDERTARGET, d.Format, D3DPOOL_DEFAULT, &g_copy, NULL);
        if (FAILED(hr))
        {
            if (g_shrinkLogs++ < 5)
                Log("shrink: no %ux%u copy (0x%08lX); DXVK's shrink this frame", d.Width, d.Height, (unsigned long)hr);
            g_copy = NULL;
            return false;
        }
        g_copyW = d.Width;
        g_copyH = d.Height;
        g_copyFormat = d.Format;
    }
    if (!g_state && FAILED(dev->CreateStateBlock(D3DSBT_ALL, &g_state)))
        return false;
    IDirect3DSurface9* copy = NULL;
    g_copy->GetSurfaceLevel(0, &copy);
    HRESULT hr = dev->StretchRect(bb, NULL, copy, NULL, D3DTEXF_NONE);  // a resolve when multisampled
    copy->Release();
    if (FAILED(hr))
        return false;
    g_state->Capture();
    IDirect3DSurface9 *oldTarget = NULL, *oldDepth = NULL;
    dev->GetRenderTarget(0, &oldTarget);
    dev->GetDepthStencilSurface(&oldDepth);
    dev->SetRenderTarget(0, bb);
    dev->SetDepthStencilSurface(NULL);
    D3DVIEWPORT9 vp = { 0, 0, (DWORD)cw, (DWORD)ch, 0.0f, 1.0f };
    dev->SetViewport(&vp);
    dev->SetRenderState(D3DRS_ZENABLE, FALSE);
    dev->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    dev->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    dev->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    dev->SetRenderState(D3DRS_FOGENABLE, FALSE);
    dev->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    dev->SetRenderState(D3DRS_MULTISAMPLEMASK, 0xFFFFFFFF);
    dev->SetVertexShader(NULL);
    dev->SetPixelShader(g_shader);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    dev->SetTexture(0, g_copy);
    dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    dev->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    dev->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    dev->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    dev->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    dev->SetSamplerState(0, D3DSAMP_SRGBTEXTURE, FALSE);
    float c0[4] = { (float)d.Width / cw, (float)d.Height / ch, 1.0f / d.Width, 1.0f / d.Height };
    dev->SetPixelShaderConstantF(0, c0, 1);
    struct V { float x, y, z, w, u, v; };
    const V quad[4] = { { -0.5f, -0.5f, 0, 1, 0, 0 }, { cw - 0.5f, -0.5f, 0, 1, 1, 0 },
                        { -0.5f, ch - 0.5f, 0, 1, 0, 1 }, { cw - 0.5f, ch - 0.5f, 0, 1, 1, 1 } };
    dev->BeginScene();
    hr = dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(V));
    dev->EndScene();
    // Targets are not part of a state block, and setting one resets the viewport: targets first, then the rest.
    if (oldTarget)
        dev->SetRenderTarget(0, oldTarget);
    dev->SetDepthStencilSurface(oldDepth);
    if (oldTarget) oldTarget->Release();
    if (oldDepth) oldDepth->Release();
    g_state->Apply();
    return SUCCEEDED(hr);
}

static HRESULT WINAPI HookPresent(IDirect3DDevice9* dev, const RECT* src, const RECT* dst, HWND wnd, const RGNDATA* dirty)
{
    HWND w = wnd ? wnd : g_deviceWindow;
    IDirect3DSurface9* bb = NULL;
    if (src || dst || !w || FAILED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb)))
        return g_realPresent(dev, src, dst, wnd, dirty);
    D3DSURFACE_DESC d;
    bb->GetDesc(&d);
    RECT cr;
    GetClientRect(w, &cr);
    int cw = cr.right, ch = cr.bottom;
    bool larger = cw > 0 && ch > 0 && (d.Width > (UINT)cw || d.Height > (UINT)ch) && d.Width >= (UINT)cw && d.Height >= (UINT)ch;
    bool fits = larger && d.Width <= 2u * cw && d.Height <= 2u * ch;
    bool done = false;
    if (fits)
    {
        LARGE_INTEGER t0, t1;
        QueryPerformanceCounter(&t0);
        done = Shrink(dev, bb, d, cw, ch);
        QueryPerformanceCounter(&t1);
        g_cpuMs += (t1.QuadPart - t0.QuadPart) * 1000.0 / g_freq.QuadPart;
        g_cpuFrames++;
        if (g_shrinkLogs < 3 && done)
            Log("shrink: %ux%u back buffer (%s) -> %dx%d window, area average (our own), not DXVK's", d.Width, d.Height,
                d.MultiSampleType ? "multisampled" : "single sample", cw, ch), g_shrinkLogs = 3;
        DWORD now = GetTickCount();
        if (now - g_cpuSince >= 10000 && g_cpuFrames)
        {
            Log("shrink: %d frames, processor time in the shrink %.3f ms a frame", g_cpuFrames, g_cpuMs / g_cpuFrames);
            g_cpuMs = 0;
            g_cpuFrames = 0;
            g_cpuSince = now;
        }
    }
    else if (larger && g_shrinkLogs < 3)
        Log("shrink: %ux%u into %dx%d is more than twice; DXVK's shrink", d.Width, d.Height, cw, ch), g_shrinkLogs = 3;
    bb->Release();
    if (!done)
        return g_realPresent(dev, src, dst, wnd, dirty);
    RECT corner = { 0, 0, cw, ch };
    return g_realPresent(dev, &corner, NULL, wnd, dirty);
}

static HRESULT WINAPI HookReset(IDirect3DDevice9* dev, D3DPRESENT_PARAMETERS* pp)
{
    ReleaseShrink();  // default-pool objects must be gone before a Reset
    HRESULT hr = g_realReset(dev, pp);
    if (pp)
        Log("reset: %ux%u -> 0x%08lX", pp->BackBufferWidth, pp->BackBufferHeight, (unsigned long)hr);
    if (pp && pp->hDeviceWindow)
        g_deviceWindow = pp->hDeviceWindow;
    return hr;
}

static bool IsSystemModule(void* address)
{
    char path[MAX_PATH], sys[MAX_PATH];
    if (!GetModuleFileNameA(ModuleOf(address), path, sizeof(path)))
        return true;
    UINT n = GetSystemWow64DirectoryA(sys, sizeof(sys));
    if (n && !_strnicmp(path, sys, n))
        return true;
    n = GetSystemDirectoryA(sys, sizeof(sys));
    return n && !_strnicmp(path, sys, n);
}

static HRESULT WINAPI HookCreateDevice(IDirect3D9* d3d, UINT adapter, D3DDEVTYPE type, HWND focus, DWORD flags,
                                       D3DPRESENT_PARAMETERS* pp, IDirect3DDevice9** out)
{
    HRESULT hr = g_realCreateDevice(d3d, adapter, type, focus, flags, pp, out);
    if (FAILED(hr) || !out || !*out)
        return hr;
    g_deviceWindow = pp && pp->hDeviceWindow ? pp->hDeviceWindow : focus;
    Log("device: %ux%u, multisample type %d quality %lu, swap effect %d, windowed %d", pp ? pp->BackBufferWidth : 0,
        pp ? pp->BackBufferHeight : 0, pp ? (int)pp->MultiSampleType : 0, pp ? (unsigned long)pp->MultiSampleQuality : 0,
        pp ? (int)pp->SwapEffect : 0, pp ? (int)pp->Windowed : 0);
    IDirect3DDevice9* dev = *out;
    if (IsSystemModule((*(void***)dev)[kPresent]))
    {
        Log("shrink: Windows' own Direct3D (not DXVK); DXVK's shrink is not there and ours is off");
        return hr;
    }
    if (void* p = HookEntry(dev, kPresent, (void*)HookPresent)) g_realPresent = (PresentFn)p;
    if (void* p = HookEntry(dev, kReset, (void*)HookReset)) g_realReset = (ResetFn)p;
    Log("shrink: ready (used when the back buffer is larger than the window, up to twice)");
    return hr;
}

static IDirect3D9* WINAPI HookCreate9(UINT sdk)
{
    IDirect3D9* d3d = g_realCreate9(sdk);
    if (d3d)
        if (void* p = HookEntry(d3d, kCreateDevice, (void*)HookCreateDevice))
            g_realCreateDevice = (CreateDeviceFn)p;
    return d3d;
}

static void StartShrink()
{
    QueryPerformanceFrequency(&g_freq);
    g_cpuSince = GetTickCount();
    if (!g_area)
    {
        Log("shrink: [Shrink] Area = 0, DXVK's own shrink is used");
        return;
    }
    void* old = PatchImport(GetModuleHandleA(NULL), "d3d9.dll", "Direct3DCreate9", (void*)HookCreate9);
    if (old)
        g_realCreate9 = (Create9Fn)old;
    Log("shrink: %s", old ? "Direct3DCreate9 import hooked" : "the program imports no Direct3DCreate9; shrink off");
}

static void Start()
{
    GetModuleFileNameA(g_self, g_dir, sizeof(g_dir));
    if (char* s = strrchr(g_dir, '\\'))
        *s = 0;
    char path[MAX_PATH];
    snprintf(path, sizeof(path), "%s\\DisplayModes.log", g_dir);
    g_log = fopen(path, "w");
    Log("DisplayModes started");
    ReadSettings();
    StartShrink();
    if (!g_addCount)
    {
        Log("settings: [Modes] Add lists no size; nothing changed");
        return;
    }
    if (HMODULE fix = GetModuleHandleA(FIX_NAME))
        Log("modes: the Widescreen Fix was loaded before this plugin and has built its list already; the extra sizes "
            "will not appear (this plugin's file name must sort before %s)", FIX_NAME);
    BYTE* fn = (BYTE*)GetProcAddress(GetModuleHandleA("user32.dll"), "EnumDisplaySettingsW");
    if (!fn)
    {
        Log("modes: user32 has no EnumDisplaySettingsW; nothing changed");
        return;
    }
    g_realEnum = (EnumW)(fn + 2);
    if (HotPatch(fn, (void*)HookEnum))
        Log("modes: EnumDisplaySettingsW patched; the Widescreen Fix will be offered the extra sizes");
    if (HMODULE fix = GetModuleHandleA(FIX_NAME))
        PatchFixWindow(fix);
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_self = inst;
        DisableThreadLibraryCalls(inst);
        Start();
    }
    return TRUE;
}
