// GfxProbe: patching call tables and imports, and every intercepted device call.
// Each hook forwards the call unchanged and tells the parts that are switched on.
#include "probe.h"

// IDirect3DDevice9 call-table positions.
enum { kPresent = 17, kCreateTexture = 23, kCreateCubeTexture = 25, kCreateRenderTarget = 28, kCreateDepthStencilSurface = 29,
       kCreateVertexShader = 91, kSetVertexShaderConstantF = 94, kCreatePixelShader = 106, kSetPixelShaderConstantF = 109, kStretchRect = 34, kSetRenderTarget = 37, kSetDepthStencilSurface = 39, kClear = 43, kSetRenderState = 57, kBeginStateBlock = 60, kEndStateBlock = 61, kGetSamplerState = 68, kSetSamplerState = 69, kDrawPrimitive = 81, kDrawIndexedPrimitive = 82,
       kDrawPrimitiveUP = 83, kDrawIndexedPrimitiveUP = 84 };

// Every entry this plugin has hooked, with what was there before.
enum { kMaxHooked = 96 };
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

// Puts hook into a call-table entry and returns what was there, or nullptr if the caller's saved original
// is still the right one. It is called again and again for the same entries (the tables are shared by
// every instance, and Windows' own Direct3D wipes them), so three cases must be told apart:
//  - our hook is in place: nothing to do;
//  - the entry is back to what we first found there (the table was rewritten): put our hook back;
//  - something else is there: another plugin hooked on top of us and calls us in turn. Leave it. Hooking
//    again here would make the two plugins call each other for ever.
void* HookSlot(void* object, int slot, void* hook)
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

bool PatchImport(const char* dll, const char* func, void* hook, void** original)
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

typedef HRESULT(WINAPI* SetSamplerStateFn)(IDirect3DDevice9*, DWORD, D3DSAMPLERSTATETYPE, DWORD);
typedef HRESULT(WINAPI* DrawPrimitiveFn)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, UINT);
typedef HRESULT(WINAPI* DrawIndexedPrimitiveFn)(IDirect3DDevice9*, D3DPRIMITIVETYPE, INT, UINT, UINT, UINT, UINT);
typedef HRESULT(WINAPI* DrawPrimitiveUPFn)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, const void*, UINT);
typedef HRESULT(WINAPI* DrawIndexedPrimitiveUPFn)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, UINT, UINT, const void*,
    D3DFORMAT, const void*, UINT);
typedef HRESULT(WINAPI* PresentFn)(IDirect3DDevice9*, const RECT*, const RECT*, HWND, const RGNDATA*);
static SetSamplerStateFn g_setSamplerState;
static DrawPrimitiveFn g_drawPrimitive;
static DrawIndexedPrimitiveFn g_drawIndexedPrimitive;
static DrawPrimitiveUPFn g_drawPrimitiveUP;
static DrawIndexedPrimitiveUPFn g_drawIndexedPrimitiveUP;
static PresentFn g_present;

static HRESULT WINAPI HookSetSamplerState(IDirect3DDevice9* dev, DWORD stage, D3DSAMPLERSTATETYPE type, DWORD value)
{
    if (g_cfg.filtering && !g_own)
        FilteringOnSetSamplerState(stage, type, value);
    return g_setSamplerState(dev, stage, type, value);
}

// What every draw tells the parts. call is the name used in a dissection.
static void OnDraw(IDirect3DDevice9* dev, const char* call, D3DPRIMITIVETYPE type, UINT primitives)
{
    if (g_own)
        return;
    if (g_cfg.filtering)
        FilteringOnDraw(dev);
    if (g_cfg.frameMap)
        FrameDraw(type, primitives);
    if (g_dissecting)
        DissectDraw(dev, call, type, primitives);
}

static HRESULT WINAPI HookDrawPrimitive(IDirect3DDevice9* dev, D3DPRIMITIVETYPE t, UINT start, UINT count)
{
    TimeEnter();
    OnDraw(dev, "DrawPrimitive", t, count);
    HRESULT hr = g_drawPrimitive(dev, t, start, count);
    TimeLeave();
    return hr;
}
static HRESULT WINAPI HookDrawIndexedPrimitive(IDirect3DDevice9* dev, D3DPRIMITIVETYPE t, INT base, UINT minIdx, UINT verts,
    UINT start, UINT count)
{
    TimeEnter();
    OnDraw(dev, "DrawIndexedPrimitive", t, count);
    HRESULT hr = g_drawIndexedPrimitive(dev, t, base, minIdx, verts, start, count);
    TimeLeave();
    return hr;
}
static HRESULT WINAPI HookDrawPrimitiveUP(IDirect3DDevice9* dev, D3DPRIMITIVETYPE t, UINT count, const void* data, UINT stride)
{
    TimeEnter();
    OnDraw(dev, "DrawPrimitiveUP", t, count);
    HRESULT hr = g_drawPrimitiveUP(dev, t, count, data, stride);
    TimeLeave();
    return hr;
}
static HRESULT WINAPI HookDrawIndexedPrimitiveUP(IDirect3DDevice9* dev, D3DPRIMITIVETYPE t, UINT minIdx, UINT verts, UINT count,
    const void* idx, D3DFORMAT fmt, const void* data, UINT stride)
{
    TimeEnter();
    OnDraw(dev, "DrawIndexedPrimitiveUP", t, count);
    HRESULT hr = g_drawIndexedPrimitiveUP(dev, t, minIdx, verts, count, idx, fmt, data, stride);
    TimeLeave();
    return hr;
}

typedef HRESULT(WINAPI* SetRenderTargetFn)(IDirect3DDevice9*, DWORD, IDirect3DSurface9*);
typedef HRESULT(WINAPI* ClearFn)(IDirect3DDevice9*, DWORD, const D3DRECT*, DWORD, D3DCOLOR, float, DWORD);
typedef HRESULT(WINAPI* StretchRectFn)(IDirect3DDevice9*, IDirect3DSurface9*, const RECT*, IDirect3DSurface9*, const RECT*,
    D3DTEXTUREFILTERTYPE);
typedef HRESULT(WINAPI* SetRenderStateFn)(IDirect3DDevice9*, D3DRENDERSTATETYPE, DWORD);
static SetRenderTargetFn g_setRenderTarget;
static ClearFn g_clear;
static StretchRectFn g_stretchRect;
static SetRenderStateFn g_setRenderState;

// "module+0xoffset" for a code address (or the bare address).
static void Where(DWORD address, char* out, size_t size)
{
    HMODULE module = nullptr;
    char path[MAX_PATH];
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCSTR)(UINT_PTR)address, &module) && GetModuleFileNameA(module, path, sizeof(path)))
    {
        const char* name = strrchr(path, '\\');
        snprintf(out, size, "%s+0x%lX", name ? name + 1 : path, (unsigned long)(address - (DWORD)(UINT_PTR)module));
    }
    else
        snprintf(out, size, "0x%08lX", (unsigned long)address);
}

// [Trace]: where a switch to a target of the traced width comes from: the caller of SetRenderTarget and the return
// addresses into the program itself (its own module) found on the stack above it, one line per distinct caller.
static __attribute__((noinline)) void TraceTarget(IDirect3DSurface9* target, DWORD caller, const DWORD* stack)
{
    static DWORD seen[64];
    static int count;
    D3DSURFACE_DESC desc;
    if (!target || count >= g_cfg.traceMax || count >= 64 || FAILED(target->GetDesc(&desc)) || (int)desc.Width != g_cfg.traceWidth)
        return;
    for (int i = 0; i < count; ++i)
        if (seen[i] == caller)
            return;
    seen[count++] = caller;
    HMODULE exe = GetModuleHandleA(nullptr);
    DWORD lo = (DWORD)(UINT_PTR)exe, hi = lo;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)exe;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)((BYTE*)exe + dos->e_lfanew);
    hi = lo + nt->OptionalHeader.SizeOfImage;
    char where[96], chain[1024] = "";
    size_t used = 0;
    int found = 0;
    for (int i = 0; i < 2048 && found < 16 && Readable((DWORD)(UINT_PTR)(stack + i), 4); ++i)
    {
        DWORD v = stack[i];
        if (v > lo + 0x1000 && v < hi)
        {
            Where(v, where, sizeof(where));
            used += snprintf(chain + used, sizeof(chain) - used, "%s%s", found ? "," : "", where);
            if (used >= sizeof(chain))
                break;
            ++found;
        }
    }
    Where(caller, where, sizeof(where));
    Log("TRACE target=%lux%lu caller=%s stack=%s", (unsigned long)desc.Width, (unsigned long)desc.Height, where, chain);
}

static HRESULT WINAPI HookSetRenderTarget(IDirect3DDevice9* dev, DWORD index, IDirect3DSurface9* target)
{
    if (g_cfg.traceWidth > 0 && index == 0)
    {
        // The scan starts at this hook's own frame (saved frame pointer, then the return address into the caller).
        TraceTarget(target, (DWORD)(UINT_PTR)__builtin_return_address(0), (const DWORD*)__builtin_frame_address(0));
    }
    if (g_own || !g_cfg.frameMap)
        return g_setRenderTarget(dev, index, target);
    TimeEnter();
    int id = index == 0 ? TargetId(dev, target) : -1;
    if (g_dissecting && index == 0 && id != FrameTarget())
        DissectSaveTarget(dev); // the picture as the game leaves it
    HRESULT hr = g_setRenderTarget(dev, index, target);
    if (index == 0 && SUCCEEDED(hr))
        FrameSetTarget(id);
    if (g_dissecting)
    {
        char what[96];
        TargetDescribe(index == 0 ? id : TargetId(dev, target), what, sizeof(what));
        DissectLine("target index=%lu target=T%d %s", (unsigned long)index, index == 0 ? id : TargetId(dev, target), what);
    }
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookClear(IDirect3DDevice9* dev, DWORD count, const D3DRECT* rects, DWORD flags, D3DCOLOR color, float z,
    DWORD stencil)
{
    if (g_own)
        return g_clear(dev, count, rects, flags, color, z, stencil);
    TimeEnter();
    FrameClear();
    if (g_dissecting)
        DissectLine("clear flags=0x%lX color=0x%08lX z=%g rects=%lu", (unsigned long)flags, (unsigned long)color, z, (unsigned long)count);
    HRESULT hr = g_clear(dev, count, rects, flags, color, z, stencil);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookStretchRect(IDirect3DDevice9* dev, IDirect3DSurface9* src, const RECT* srcRect, IDirect3DSurface9* dst,
    const RECT* dstRect, D3DTEXTUREFILTERTYPE filter)
{
    if (g_own)
        return g_stretchRect(dev, src, srcRect, dst, dstRect, filter);
    TimeEnter();
    int from = TargetId(dev, src), to = TargetId(dev, dst);
    FrameCopy(from, to);
    if (g_dissecting)
        DissectLine("copy src=T%d dst=T%d filter=%s", from, to, FilterName(filter));
    HRESULT hr = g_stretchRect(dev, src, srcRect, dst, dstRect, filter);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookSetRenderState(IDirect3DDevice9* dev, D3DRENDERSTATETYPE state, DWORD value)
{
    if (!g_own)
    {
        if (state == D3DRS_MULTISAMPLEANTIALIAS)
            FrameMsaa(value);
        if (g_dissecting)
            DissectState(state, value);
    }
    return g_setRenderState(dev, state, value);
}

typedef HRESULT(WINAPI* CreateTextureFn)(IDirect3DDevice9*, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL, IDirect3DTexture9**, HANDLE*);
typedef HRESULT(WINAPI* CreateCubeTextureFn)(IDirect3DDevice9*, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL, IDirect3DCubeTexture9**, HANDLE*);
typedef HRESULT(WINAPI* CreateSurfaceFn)(IDirect3DDevice9*, UINT, UINT, D3DFORMAT, D3DMULTISAMPLE_TYPE, DWORD, BOOL,
    IDirect3DSurface9**, HANDLE*);
typedef HRESULT(WINAPI* CreateVertexShaderFn)(IDirect3DDevice9*, const DWORD*, IDirect3DVertexShader9**);
typedef HRESULT(WINAPI* CreatePixelShaderFn)(IDirect3DDevice9*, const DWORD*, IDirect3DPixelShader9**);
static CreateTextureFn g_createTexture;
static CreateCubeTextureFn g_createCubeTexture;
static CreateSurfaceFn g_createRenderTarget, g_createDepthStencil;
static CreateVertexShaderFn g_createVertexShader;
static CreatePixelShaderFn g_createPixelShader;

static HRESULT WINAPI HookCreateTexture(IDirect3DDevice9* dev, UINT w, UINT h, UINT levels, DWORD usage, D3DFORMAT format,
    D3DPOOL pool, IDirect3DTexture9** out, HANDLE* shared)
{
    TimeEnter();
    HRESULT hr = g_createTexture(dev, w, h, levels, usage, format, pool, out, shared);
    if (SUCCEEDED(hr) && !g_own)
        ResourcesOnCreateTexture(w, h, levels, usage, format, false);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookCreateCubeTexture(IDirect3DDevice9* dev, UINT edge, UINT levels, DWORD usage, D3DFORMAT format,
    D3DPOOL pool, IDirect3DCubeTexture9** out, HANDLE* shared)
{
    TimeEnter();
    HRESULT hr = g_createCubeTexture(dev, edge, levels, usage, format, pool, out, shared);
    if (SUCCEEDED(hr) && !g_own)
        ResourcesOnCreateTexture(edge, edge, levels, usage, format, true);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookCreateRenderTarget(IDirect3DDevice9* dev, UINT w, UINT h, D3DFORMAT format, D3DMULTISAMPLE_TYPE ms,
    DWORD quality, BOOL lockable, IDirect3DSurface9** out, HANDLE* shared)
{
    TimeEnter();
    HRESULT hr = g_createRenderTarget(dev, w, h, format, ms, quality, lockable, out, shared);
    if (SUCCEEDED(hr) && !g_own)
        ResourcesOnCreateSurface("target", w, h, format, (int)ms);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookCreateDepthStencil(IDirect3DDevice9* dev, UINT w, UINT h, D3DFORMAT format, D3DMULTISAMPLE_TYPE ms,
    DWORD quality, BOOL discard, IDirect3DSurface9** out, HANDLE* shared)
{
    TimeEnter();
    HRESULT hr = g_createDepthStencil(dev, w, h, format, ms, quality, discard, out, shared);
    if (SUCCEEDED(hr) && !g_own)
        ResourcesOnCreateSurface("depth", w, h, format, (int)ms);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookCreateVertexShader(IDirect3DDevice9* dev, const DWORD* code, IDirect3DVertexShader9** out)
{
    TimeEnter();
    HRESULT hr = g_createVertexShader(dev, code, out);
    if (SUCCEEDED(hr) && out && *out)
        ResourcesOnCreateShader(code, *out, true);
    TimeLeave();
    return hr;
}

static HRESULT WINAPI HookCreatePixelShader(IDirect3DDevice9* dev, const DWORD* code, IDirect3DPixelShader9** out)
{
    TimeEnter();
    HRESULT hr = g_createPixelShader(dev, code, out);
    if (SUCCEEDED(hr) && out && *out)
        ResourcesOnCreateShader(code, *out, false);
    TimeLeave();
    return hr;
}

typedef HRESULT(WINAPI* SetDepthStencilFn)(IDirect3DDevice9*, IDirect3DSurface9*);
typedef HRESULT(WINAPI* SetShaderConstantFFn)(IDirect3DDevice9*, UINT, const float*, UINT);
static SetDepthStencilFn g_setDepthStencil;
static SetShaderConstantFFn g_setVertexConstantF, g_setPixelConstantF;

static HRESULT WINAPI HookSetDepthStencil(IDirect3DDevice9* dev, IDirect3DSurface9* depth)
{
    if (g_dissecting && !g_own)
    {
        D3DSURFACE_DESC desc = {};
        if (depth)
            depth->GetDesc(&desc);
        DissectLine("depth size=%ux%u fmt=%s ms=%d", desc.Width, desc.Height, depth ? FormatName(desc.Format) : "none",
            (int)desc.MultiSampleType);
    }
    return g_setDepthStencil(dev, depth);
}

static HRESULT WINAPI HookSetVertexConstantF(IDirect3DDevice9* dev, UINT reg, const float* data, UINT count)
{
    if (g_dissecting && !g_own)
        DissectConstants(true, reg, data, count);
    return g_setVertexConstantF(dev, reg, data, count);
}

static HRESULT WINAPI HookSetPixelConstantF(IDirect3DDevice9* dev, UINT reg, const float* data, UINT count)
{
    if (g_dissecting && !g_own)
        DissectConstants(false, reg, data, count);
    return g_setPixelConstantF(dev, reg, data, count);
}

static HRESULT WINAPI HookPresent(IDirect3DDevice9* dev, const RECT* src, const RECT* dst, HWND wnd, const RGNDATA* dirty)
{
    TimeEnter(); // closes the game's own time for the frame
    if (g_dissecting)
        DissectFinish(dev);
    if (g_cfg.frameMap)
        FrameEnd(g_driving);
    if (g_cfg.filtering)
        FilteringOnPresent();
    if (g_cfg.shots || g_cfg.dissect || g_cfg.frameMap)
        DrivingTick();
    if (g_cfg.watch)
        WatchTick();
    static DWORD lastReport;
    DWORD now = GetTickCount();
    if (!lastReport)
        lastReport = now;
    if (now - lastReport >= (DWORD)g_cfg.reportSeconds * 1000)
    {
        if (g_cfg.filtering)
            FilteringReport();
        if (g_cfg.frameMap)
            FrameReport();
        if (g_cfg.resources)
            ResourcesReport();
        if (g_cfg.effects && g_cfg.effectValues)
            EffectsReport();
        lastReport = now;
    }
    CaptureGridIfRequested(dev);
    if (g_cfg.effects && g_cfg.effectValues)
        EffectsTick();
    if (g_cfg.shots)
        ShotsTick(dev);
    LONGLONG before = Ticks();
    HRESULT hr = g_present(dev, src, dst, wnd, dirty);
    LONGLONG presentTicks = Ticks() - before;
    if (DissectWanted())
        DissectStart();
    if (g_cfg.frameMap)
    {
        FramePresentDone(presentTicks);
        FrameBegin(dev, !g_dissecting); // a dissected frame is far too slow to be a timing sample
    }
    if (g_dissecting)
    {
        char what[96];
        TargetDescribe(FrameTarget(), what, sizeof(what));
        DissectLine("target index=0 target=T%d %s start=1", FrameTarget(), what);
    }
    return hr;
}

// Windows' own Direct3D keeps one call table per device and rewrites all of it when the recording of a
// state block begins (BeginStateBlock) and again when it ends, which removes every hook. D3DX effects
// record state blocks. So after Begin only the End hook is put back (the table then holds the recording
// versions of the calls, which must not be mixed with the originals we saved), and after End all hooks
// are. DXVK does not rewrite its table; there HookSlot finds the hooks still in place and does nothing.
typedef HRESULT(WINAPI* BeginStateBlockFn)(IDirect3DDevice9*);
typedef HRESULT(WINAPI* EndStateBlockFn)(IDirect3DDevice9*, IDirect3DStateBlock9**);
static BeginStateBlockFn g_beginStateBlock;
static EndStateBlockFn g_endStateBlock;
static void InstallHooks(IDirect3DDevice9* dev);

static HRESULT WINAPI HookEndStateBlock(IDirect3DDevice9* dev, IDirect3DStateBlock9** out)
{
    HRESULT hr = g_endStateBlock(dev, out);
    InstallHooks(dev);
    return hr;
}

static HRESULT WINAPI HookBeginStateBlock(IDirect3DDevice9* dev)
{
    HRESULT hr = g_beginStateBlock(dev);
    void* p = HookSlot(dev, kEndStateBlock, (void*)HookEndStateBlock);
    if (p)
        g_endStateBlock = (EndStateBlockFn)p;
    return hr;
}

static void InstallHooks(IDirect3DDevice9* dev)
{
    void* p;
    if ((p = HookSlot(dev, kSetSamplerState, (void*)HookSetSamplerState))) g_setSamplerState = (SetSamplerStateFn)p;
    if ((p = HookSlot(dev, kDrawPrimitive, (void*)HookDrawPrimitive))) g_drawPrimitive = (DrawPrimitiveFn)p;
    if ((p = HookSlot(dev, kDrawIndexedPrimitive, (void*)HookDrawIndexedPrimitive))) g_drawIndexedPrimitive = (DrawIndexedPrimitiveFn)p;
    if ((p = HookSlot(dev, kDrawPrimitiveUP, (void*)HookDrawPrimitiveUP))) g_drawPrimitiveUP = (DrawPrimitiveUPFn)p;
    if ((p = HookSlot(dev, kDrawIndexedPrimitiveUP, (void*)HookDrawIndexedPrimitiveUP))) g_drawIndexedPrimitiveUP = (DrawIndexedPrimitiveUPFn)p;
    if ((p = HookSlot(dev, kPresent, (void*)HookPresent))) g_present = (PresentFn)p;
    // The trace ([Trace] TargetWidth) needs this one even with the frame map off.
    if (g_cfg.frameMap || g_cfg.traceWidth > 0)
        if ((p = HookSlot(dev, kSetRenderTarget, (void*)HookSetRenderTarget))) g_setRenderTarget = (SetRenderTargetFn)p;
    if (g_cfg.frameMap)
    {
        if ((p = HookSlot(dev, kClear, (void*)HookClear))) g_clear = (ClearFn)p;
        if ((p = HookSlot(dev, kStretchRect, (void*)HookStretchRect))) g_stretchRect = (StretchRectFn)p;
        if ((p = HookSlot(dev, kSetRenderState, (void*)HookSetRenderState))) g_setRenderState = (SetRenderStateFn)p;
    }
    if (g_cfg.resources)
    {
        if ((p = HookSlot(dev, kCreateTexture, (void*)HookCreateTexture))) g_createTexture = (CreateTextureFn)p;
        if ((p = HookSlot(dev, kCreateCubeTexture, (void*)HookCreateCubeTexture))) g_createCubeTexture = (CreateCubeTextureFn)p;
        if ((p = HookSlot(dev, kCreateRenderTarget, (void*)HookCreateRenderTarget))) g_createRenderTarget = (CreateSurfaceFn)p;
        if ((p = HookSlot(dev, kCreateDepthStencilSurface, (void*)HookCreateDepthStencil))) g_createDepthStencil = (CreateSurfaceFn)p;
    }
    if (g_cfg.shaders)
    {
        if ((p = HookSlot(dev, kCreateVertexShader, (void*)HookCreateVertexShader))) g_createVertexShader = (CreateVertexShaderFn)p;
        if ((p = HookSlot(dev, kCreatePixelShader, (void*)HookCreatePixelShader))) g_createPixelShader = (CreatePixelShaderFn)p;
    }
    if (g_cfg.dissect)
    {
        if ((p = HookSlot(dev, kSetDepthStencilSurface, (void*)HookSetDepthStencil))) g_setDepthStencil = (SetDepthStencilFn)p;
        if ((p = HookSlot(dev, kSetVertexShaderConstantF, (void*)HookSetVertexConstantF))) g_setVertexConstantF = (SetShaderConstantFFn)p;
        if ((p = HookSlot(dev, kSetPixelShaderConstantF, (void*)HookSetPixelConstantF))) g_setPixelConstantF = (SetShaderConstantFFn)p;
    }
    if ((p = HookSlot(dev, kBeginStateBlock, (void*)HookBeginStateBlock))) g_beginStateBlock = (BeginStateBlockFn)p;
    if ((p = HookSlot(dev, kEndStateBlock, (void*)HookEndStateBlock))) g_endStateBlock = (EndStateBlockFn)p;
}

void InstallDeviceHooks(IDirect3DDevice9* dev)
{
    InstallHooks(dev);
    Log("  device hooks installed");
}
