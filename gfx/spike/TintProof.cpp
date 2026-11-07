// TintProof.asi - THROWAWAY proof for the exposure-and-bloom work (2026-10-13). Not a feature.
//
// Question it answers: can a plugin of ours find the moment between the game's last full-screen effect
// and its HUD, draw there, and leave everything else as it was, next to GfxProbe and under DXVK?
//
// What it does: once per frame, at the first Begin of a "before" effect (the HUD's: IDI_FE_FX,
// IDI_FE_MASK_FX) while the back buffer is the target and after an "after" effect (the colour
// treatment: IDI_VISUALTREATMENT_FX) has run in that frame, it lays a translucent colour over the whole
// picture. The HUD is drawn afterwards and stays untinted. All device state is saved and put back.
// Settings in TintProof.ini; delete the .asi to remove it. Written for DXVK only: it does not put its
// hooks back after Windows' own Direct3D rewrites the device's call table.
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>

static FILE* g_log;
static DWORD g_startTick;
static char g_after[8][48], g_before[8][48];
static int g_afterCount, g_beforeCount;
static D3DCOLOR g_colour = 0x40FF00FF; // a quarter-strength magenta
static bool g_enabled = true;

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

// Hooks a call-table entry once and never again: if another plugin hooks on top later, it chains to us.
static void* HookOnce(void* object, int slot, void* hook)
{
    void** entry = &(*(void***)object)[slot];
    DWORD old;
    VirtualProtect(entry, sizeof(void*), PAGE_EXECUTE_READWRITE, &old);
    void* original = *entry;
    *entry = hook;
    VirtualProtect(entry, sizeof(void*), old, &old);
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

enum { kMaxFx = 64 };
static ID3DXEffect* g_afterFx[kMaxFx];
static ID3DXEffect* g_beforeFx[kMaxFx];
static int g_afterFxCount, g_beforeFxCount;
static IDirect3DDevice9* g_device;
static bool g_afterSeen, g_doneThisFrame, g_busy;
static LONG g_frames, g_tinted, g_failed;

struct TintVertex { float x, y, z, rhw; D3DCOLOR colour; };

// Lays the colour over the current target. Every piece of device state is captured first and applied
// back afterwards, so the game continues as if nothing had been drawn.
static void DrawTint(IDirect3DDevice9* dev)
{
    IDirect3DSurface9* target = nullptr;
    IDirect3DStateBlock9* saved = nullptr;
    D3DSURFACE_DESC desc;
    if (FAILED(dev->GetRenderTarget(0, &target)) || FAILED(target->GetDesc(&desc))
        || FAILED(dev->CreateStateBlock(D3DSBT_ALL, &saved)))
    {
        ++g_failed;
        if (target) target->Release();
        return;
    }
    D3DVIEWPORT9 viewport = { 0, 0, desc.Width, desc.Height, 0.0f, 1.0f };
    dev->SetViewport(&viewport);
    dev->SetVertexShader(nullptr);
    dev->SetPixelShader(nullptr);
    dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
    dev->SetTexture(0, nullptr);
    dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    dev->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    dev->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    dev->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    dev->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    dev->SetRenderState(D3DRS_ZENABLE, FALSE);
    dev->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    dev->SetRenderState(D3DRS_LIGHTING, FALSE);
    dev->SetRenderState(D3DRS_FOGENABLE, FALSE);
    dev->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    dev->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    dev->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    dev->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
    dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    float w = (float)desc.Width, h = (float)desc.Height;
    const TintVertex quad[4] = { { -0.5f, -0.5f, 0.5f, 1, g_colour }, { w - 0.5f, -0.5f, 0.5f, 1, g_colour },
                                 { -0.5f, h - 0.5f, 0.5f, 1, g_colour }, { w - 0.5f, h - 0.5f, 0.5f, 1, g_colour } };
    if (SUCCEEDED(dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(TintVertex))))
        ++g_tinted;
    else
        ++g_failed;
    saved->Apply();
    saved->Release();
    target->Release();
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

typedef HRESULT(WINAPI* FxBeginFn)(ID3DXEffect*, UINT*, DWORD);
static FxBeginFn g_fxBegin;

static HRESULT WINAPI HookFxBegin(ID3DXEffect* fx, UINT* passes, DWORD flags)
{
    if (g_enabled && g_device && !g_busy)
    {
        for (int i = 0; i < g_afterFxCount; ++i)
            if (g_afterFx[i] == fx)
                g_afterSeen = true;
        if (g_afterSeen && !g_doneThisFrame)
            for (int i = 0; i < g_beforeFxCount; ++i)
                if (g_beforeFx[i] == fx && TargetIsBackBuffer(g_device))
                {
                    g_doneThisFrame = true;
                    g_busy = true; // the state block and the draw may call back into hooked code
                    DrawTint(g_device);
                    g_busy = false;
                    break;
                }
    }
    return g_fxBegin(fx, passes, flags);
}

typedef HRESULT(WINAPI* PresentFn)(IDirect3DDevice9*, const RECT*, const RECT*, HWND, const RGNDATA*);
static PresentFn g_present;

static HRESULT WINAPI HookPresent(IDirect3DDevice9* dev, const RECT* src, const RECT* dst, HWND wnd, const RGNDATA* dirty)
{
    g_afterSeen = g_doneThisFrame = false;
    ++g_frames;
    static DWORD last;
    DWORD now = GetTickCount();
    if (now - last >= 5000)
    {
        Log("TINT frames=%ld tinted=%ld failed=%ld", g_frames, g_tinted, g_failed);
        g_frames = g_tinted = g_failed = 0;
        last = now;
    }
    return g_present(dev, src, dst, wnd, dirty);
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
        g_present = (PresentFn)HookOnce(dev, 17, (void*)HookPresent);
        g_fxBegin = (FxBeginFn)HookOnce(*out, 63, (void*)HookFxBegin);
        Log("hooked Present and the effects' Begin (first effect: %s)", resource);
    }
    for (int i = 0; i < g_afterCount; ++i)
        if (!lstrcmpiA(resource, g_after[i]) && g_afterFxCount < kMaxFx)
        {
            g_afterFx[g_afterFxCount++] = *out;
            Log("'after' effect %s = %p", resource, (void*)*out);
        }
    for (int i = 0; i < g_beforeCount; ++i)
        if (!lstrcmpiA(resource, g_before[i]) && g_beforeFxCount < kMaxFx)
        {
            g_beforeFx[g_beforeFxCount++] = *out;
            Log("'before' effect %s = %p", resource, (void*)*out);
        }
    return hr;
}

static int SplitNames(char* text, char names[][48])
{
    int count = 0;
    for (char* token = strtok(text, ", "); token && count < 8; token = strtok(nullptr, ", "))
        snprintf(names[count++], 48, "%s", token);
    return count;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    char path[MAX_PATH], text[256];
    GetModuleFileNameA(instance, path, MAX_PATH);
    char* dot = strrchr(path, '.');
    strcpy(dot, ".log");
    g_startTick = GetTickCount();
    g_log = fopen(path, "w");
    strcpy(dot, ".ini");
    g_enabled = GetPrivateProfileIntA("Tint", "Enabled", 1, path) != 0;
    GetPrivateProfileStringA("Tint", "Colour", "0x40FF00FF", text, sizeof(text), path);
    g_colour = strtoul(text, nullptr, 0);
    GetPrivateProfileStringA("Tint", "After", "IDI_VISUALTREATMENT_FX", text, sizeof(text), path);
    g_afterCount = SplitNames(text, g_after);
    GetPrivateProfileStringA("Tint", "Before", "IDI_FE_FX,IDI_FE_MASK_FX", text, sizeof(text), path);
    g_beforeCount = SplitNames(text, g_before);
    Log("TintProof loaded (throwaway proof): enabled=%d colour=0x%08lX", g_enabled ? 1 : 0, (unsigned long)g_colour);
    bool ok = PatchImport("d3dx9_26.dll", "D3DXCreateEffectFromResourceA", (void*)HookCreateEffect, (void**)&g_createEffect);
    Log("effect import hook %s", ok ? "installed" : "NOT FOUND");
    return TRUE;
}
