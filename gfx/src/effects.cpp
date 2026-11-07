// GfxProbe: the game's effects. An effect bundles the shaders for one kind of surface with their named
// settings. The game loads every effect through d3dx9_26.dll!D3DXCreateEffectFromResourceA (one call site,
// 0x6C60D2); patching that import shows each effect by name. The effect's own Begin/BeginPass/End calls
// (positions 63, 64, 67 in its call table, checked against d3dx9_26.dll) say which one is drawing.
#include "probe.h"
#include <d3dx9.h>

enum { kFxRelease = 2, kFxBegin = 63, kFxBeginPass = 64, kFxEnd = 67 };
enum { kWriteInFull = 3 };
enum { kMaxFx = 64, kMaxTech = 16, kCompare = 64, kMaxValue = 4096 };

struct Param
{
    D3DXHANDLE handle;
    char name[48];
    char kind;            // 'n' numeric, 't' texture, 0 neither (not polled)
    bool isFloat;
    UINT bytes;
    BYTE last[kCompare];  // the first bytes of the last value seen
    void* lastTexture;
    int written;          // changes written in full so far (at most kWriteInFull)
    int changes;          // polls that found a change since the last report
    char lastText[96];    // the latest value as printed
};
struct Fx
{
    ID3DXEffect* fx;
    char name[48];
    D3DXHANDLE tech[kMaxTech];
    int label[kMaxTech];
    int techCount;
    Param* params;
    int paramCount;
};
static Fx g_fx[kMaxFx];
static int g_fxCount;
static BYTE g_value[kMaxValue];

typedef HRESULT(WINAPI* CreateEffectFn)(IDirect3DDevice9*, HMODULE, LPCSTR, const D3DXMACRO*, ID3DXInclude*, DWORD,
    ID3DXEffectPool*, ID3DXEffect**, ID3DXBuffer**);
typedef HRESULT(WINAPI* FxBeginFn)(ID3DXEffect*, UINT*, DWORD);
typedef HRESULT(WINAPI* FxBeginPassFn)(ID3DXEffect*, UINT);
typedef HRESULT(WINAPI* FxEndFn)(ID3DXEffect*);
static CreateEffectFn g_createEffect;
static FxBeginFn g_fxBegin;
static FxBeginPassFn g_fxBeginPass;
static FxEndFn g_fxEnd;

static const char* ClassName(D3DXPARAMETER_CLASS c)
{
    switch (c)
    {
    case D3DXPC_SCALAR: return "scalar";
    case D3DXPC_VECTOR: return "vector";
    case D3DXPC_MATRIX_ROWS:
    case D3DXPC_MATRIX_COLUMNS: return "matrix";
    case D3DXPC_OBJECT: return "object";
    case D3DXPC_STRUCT: return "struct";
    }
    return "other";
}

static const char* TypeName(D3DXPARAMETER_TYPE t)
{
    switch (t)
    {
    case D3DXPT_BOOL: return "bool";
    case D3DXPT_INT: return "int";
    case D3DXPT_FLOAT: return "float";
    case D3DXPT_STRING: return "string";
    case D3DXPT_TEXTURE:
    case D3DXPT_TEXTURE1D:
    case D3DXPT_TEXTURE2D:
    case D3DXPT_TEXTURE3D:
    case D3DXPT_TEXTURECUBE: return "texture";
    case D3DXPT_SAMPLER:
    case D3DXPT_SAMPLER1D:
    case D3DXPT_SAMPLER2D:
    case D3DXPT_SAMPLER3D:
    case D3DXPT_SAMPLERCUBE: return "sampler";
    default: return "other";
    }
}

// Up to 16 numbers of a value, comma-separated.
static void FormatNumbers(const Param& p, const BYTE* value, char* out, size_t size)
{
    UINT count = p.bytes / 4 > 16 ? 16 : p.bytes / 4;
    size_t len = 0;
    out[0] = 0;
    for (UINT i = 0; i < count && len < size - 16; ++i)
    {
        if (p.isFloat)
            len += snprintf(out + len, size - len, "%s%g", i ? "," : "", ((const float*)value)[i]);
        else
            len += snprintf(out + len, size - len, "%s%d", i ? "," : "", ((const int*)value)[i]);
    }
}

void DescribeTexture(IDirect3DBaseTexture9* texture, char* out, size_t size)
{
    D3DSURFACE_DESC desc;
    if (!texture)
        snprintf(out, size, "tex:none");
    else if (texture->GetType() == D3DRTYPE_TEXTURE && SUCCEEDED(((IDirect3DTexture9*)texture)->GetLevelDesc(0, &desc)))
        snprintf(out, size, "tex:%ux%u:%s", desc.Width, desc.Height, FormatName(desc.Format));
    else if (texture->GetType() == D3DRTYPE_CUBETEXTURE && SUCCEEDED(((IDirect3DCubeTexture9*)texture)->GetLevelDesc(0, &desc)))
        snprintf(out, size, "cube:%ux%u:%s", desc.Width, desc.Height, FormatName(desc.Format));
    else
        snprintf(out, size, "tex:other");
}

static Fx* g_lastFound;

static Fx* Find(ID3DXEffect* fx)
{
    if (g_lastFound && g_lastFound->fx == fx)
        return g_lastFound;
    for (int i = 0; i < g_fxCount; ++i)
        if (g_fx[i].fx == fx)
            return g_lastFound = &g_fx[i];
    return nullptr;
}

// An effect the game has released must not be polled again: its record goes with it.
typedef ULONG(WINAPI* FxReleaseFn)(ID3DXEffect*);
static FxReleaseFn g_fxRelease;

static ULONG WINAPI HookFxRelease(ID3DXEffect* fx)
{
    ULONG left = g_fxRelease(fx);
    Fx* f = left == 0 ? Find(fx) : nullptr;
    if (f)
    {
        Log("EFFECTGONE name=%s", f->name);
        delete[] f->params;
        *f = g_fx[--g_fxCount];
        g_lastFound = nullptr;
    }
    return left;
}

static HRESULT WINAPI HookFxBegin(ID3DXEffect* fx, UINT* passes, DWORD flags)
{
    Fx* f = Find(fx);
    if (f)
    {
        D3DXHANDLE current = fx->GetCurrentTechnique();
        int label = -1;
        for (int i = 0; i < f->techCount; ++i)
            if (f->tech[i] == current)
                label = f->label[i];
        g_curLabel = label >= 0 ? label : LabelRegister(f->name, "?");
    }
    else
        g_curLabel = LabelRegister("(unknown effect)", "?");
    g_curPass = 0;
    if (g_dissecting)
        DissectLine("fx-begin fx=%s tech=%s", LabelFx(g_curLabel), LabelTech(g_curLabel));
    return g_fxBegin(fx, passes, flags);
}

static HRESULT WINAPI HookFxBeginPass(ID3DXEffect* fx, UINT pass)
{
    g_curPass = (int)pass;
    if (g_dissecting)
        DissectLine("fx-pass pass=%u", pass);
    return g_fxBeginPass(fx, pass);
}

static HRESULT WINAPI HookFxEnd(ID3DXEffect* fx)
{
    HRESULT hr = g_fxEnd(fx);
    if (g_dissecting)
        DissectLine("fx-end");
    g_curLabel = 0;
    g_curPass = 0;
    return hr;
}

// Writes the effect's techniques and settings to the log and remembers what EffectsTick polls.
static void Register(ID3DXEffect* fx, const char* name)
{
    Fx* f = Find(fx);
    if (f)
        delete[] f->params; // the library reused the address of an effect the game released
    else if (g_fxCount < kMaxFx)
        f = &g_fx[g_fxCount++];
    else
    {
        Log("EFFECT name=%s NOT RECORDED (more than %d effects)", name, kMaxFx);
        return;
    }
    memset(f, 0, sizeof(*f));
    f->fx = fx;
    snprintf(f->name, sizeof(f->name), "%s", name);
    D3DXEFFECT_DESC desc = {};
    fx->GetDesc(&desc);
    Log("EFFECT name=%s params=%u techniques=%u", f->name, desc.Parameters, desc.Techniques);
    for (UINT i = 0; i < desc.Techniques; ++i)
    {
        D3DXHANDLE h = fx->GetTechnique(i);
        D3DXTECHNIQUE_DESC td = {};
        if (!h || FAILED(fx->GetTechniqueDesc(h, &td)))
            continue;
        Log("TECH fx=%s name=%s passes=%u", f->name, td.Name ? td.Name : "?", td.Passes);
        if (f->techCount < kMaxTech)
        {
            f->tech[f->techCount] = h;
            f->label[f->techCount++] = LabelRegister(f->name, td.Name ? td.Name : "?");
        }
    }
    f->params = new Param[desc.Parameters ? desc.Parameters : 1]();
    for (UINT i = 0; i < desc.Parameters; ++i)
    {
        D3DXHANDLE h = fx->GetParameter(nullptr, i);
        D3DXPARAMETER_DESC pd = {};
        if (!h || FAILED(fx->GetParameterDesc(h, &pd)))
            continue;
        Param& p = f->params[f->paramCount++];
        p.handle = h;
        snprintf(p.name, sizeof(p.name), "%s", pd.Name ? pd.Name : "?");
        p.bytes = pd.Bytes;
        p.isFloat = pd.Type == D3DXPT_FLOAT;
        char value[320] = "-";
        bool numeric = (pd.Type == D3DXPT_FLOAT || pd.Type == D3DXPT_INT || pd.Type == D3DXPT_BOOL)
            && pd.Class != D3DXPC_STRUCT && pd.Bytes >= 4 && pd.Bytes <= kMaxValue;
        if (numeric && SUCCEEDED(fx->GetValue(h, g_value, pd.Bytes)))
        {
            p.kind = 'n';
            memcpy(p.last, g_value, pd.Bytes < kCompare ? pd.Bytes : kCompare);
            FormatNumbers(p, g_value, value, sizeof(value));
        }
        else if (!strcmp(TypeName(pd.Type), "texture"))
            p.kind = 't';
        Log("PARAM fx=%s name=%s class=%s type=%s rows=%u cols=%u elems=%u bytes=%u value=%s", f->name, p.name,
            ClassName(pd.Class), TypeName(pd.Type), pd.Rows, pd.Columns, pd.Elements, pd.Bytes, value);
    }
    void* p;
    if ((p = HookSlot(fx, kFxBegin, (void*)HookFxBegin))) g_fxBegin = (FxBeginFn)p;
    if ((p = HookSlot(fx, kFxBeginPass, (void*)HookFxBeginPass))) g_fxBeginPass = (FxBeginPassFn)p;
    if ((p = HookSlot(fx, kFxEnd, (void*)HookFxEnd))) g_fxEnd = (FxEndFn)p;
    if ((p = HookSlot(fx, kFxRelease, (void*)HookFxRelease))) g_fxRelease = (FxReleaseFn)p;
}

static HRESULT WINAPI HookCreateEffect(IDirect3DDevice9* dev, HMODULE module, LPCSTR resource, const D3DXMACRO* defines,
    ID3DXInclude* include, DWORD flags, ID3DXEffectPool* pool, ID3DXEffect** out, ID3DXBuffer** errors)
{
    HRESULT hr = g_createEffect(dev, module, resource, defines, include, flags, pool, out, errors);
    char name[48];
    if (IS_INTRESOURCE(resource)) // a number, not a pointer to text
        snprintf(name, sizeof(name), "#%u", (unsigned)(UINT_PTR)resource);
    else
        snprintf(name, sizeof(name), "%s", resource);
    if (SUCCEEDED(hr) && out && *out)
        Register(*out, name);
    else
        Log("EFFECT name=%s FAILED hr=0x%08lX", name, (unsigned long)hr);
    return hr;
}

void EffectsInit()
{
    bool ok = PatchImport("d3dx9_26.dll", "D3DXCreateEffectFromResourceA", (void*)HookCreateEffect, (void**)&g_createEffect);
    Log("Effect import hook %s", ok ? "installed" : "NOT FOUND (effects part is off)");
}

static DWORD HashText(DWORD hash, const char* text)
{
    for (const char* c = text; *c; ++c)
        hash = (hash ^ (BYTE)*c) * 16777619u; // FNV-1a
    return hash;
}

// Once a second: note the settings whose value changed. A change is written in full (FXVALUE) only the
// first three times for a setting; after that it is only counted, and EffectsReport sums the counts up.
// Without that limit the settings the game changes for every draw (matrices, the diffuse texture) would
// fill the log. Settings of the same name with the same new value are written once per poll (effects in
// one pool share them).
void EffectsTick()
{
    static DWORD last;
    DWORD now = GetTickCount();
    if (now - last < 1000)
        return;
    last = now;
    enum { kSeen = 256 };
    DWORD seen[kSeen];
    int seenCount = 0;
    for (int i = 0; i < g_fxCount; ++i)
    {
        Fx& f = g_fx[i];
        for (int j = 0; j < f.paramCount; ++j)
        {
            Param& p = f.params[j];
            char text[320];
            if (p.kind == 'n')
            {
                UINT compare = p.bytes < kCompare ? p.bytes : kCompare;
                if (FAILED(f.fx->GetValue(p.handle, g_value, p.bytes)) || !memcmp(p.last, g_value, compare))
                    continue;
                memcpy(p.last, g_value, compare);
                FormatNumbers(p, g_value, text, sizeof(text));
            }
            else if (p.kind == 't')
            {
                IDirect3DBaseTexture9* texture = nullptr;
                if (FAILED(f.fx->GetTexture(p.handle, &texture)) || texture == p.lastTexture)
                {
                    if (texture)
                        texture->Release();
                    continue;
                }
                p.lastTexture = texture;
                DescribeTexture(texture, text, sizeof(text));
                if (texture)
                    texture->Release();
            }
            else
                continue;
            ++p.changes;
            snprintf(p.lastText, sizeof(p.lastText), "%s", text);
            if (p.written >= kWriteInFull)
                continue;
            DWORD hash = HashText(HashText(2166136261u, p.name), text);
            bool duplicate = false;
            for (int s = 0; s < seenCount; ++s)
                if (seen[s] == hash)
                    duplicate = true;
            if (duplicate)
                continue;
            if (seenCount < kSeen)
                seen[seenCount++] = hash;
            ++p.written;
            Log("FXVALUE fx=%s name=%s value=%s", f.name, p.name, text);
        }
    }
}

// With every report: one line per setting that changed since the last report, with how many of the
// once-a-second polls found it changed and its latest value (cut to 95 characters).
void EffectsReport()
{
    enum { kSeen = 1024 };
    static DWORD seen[kSeen];
    int seenCount = 0;
    for (int i = 0; i < g_fxCount; ++i)
    {
        Fx& f = g_fx[i];
        for (int j = 0; j < f.paramCount; ++j)
        {
            Param& p = f.params[j];
            if (!p.changes)
                continue;
            int changes = p.changes;
            p.changes = 0;
            DWORD hash = HashText(HashText(2166136261u, p.name), p.lastText) + (DWORD)changes;
            bool duplicate = false;
            for (int s = 0; s < seenCount; ++s)
                if (seen[s] == hash)
                    duplicate = true;
            if (duplicate)
                continue;
            if (seenCount < kSeen)
                seen[seenCount++] = hash;
            Log("FXCHANGE fx=%s name=%s changes=%d last=%s", f.name, p.name, changes, p.lastText);
        }
    }
}
