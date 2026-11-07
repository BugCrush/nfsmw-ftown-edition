// GfxProbe: the pictures the game draws into, numbered T0, T1, ... in the order they are first seen.
#include "probe.h"

enum { kMaxTargets = 128 };
struct TargetInfo
{
    IDirect3DSurface9* surface;
    UINT width, height;
    D3DFORMAT format;
    int multisample;
    char kind[12];
};
static TargetInfo g_targets[kMaxTargets];
static int g_targetCount;

// A surface is recognised by its address together with its size and format, so an address the game
// reuses for a different picture gets a new number.
int TargetId(IDirect3DDevice9* dev, IDirect3DSurface9* surface)
{
    D3DSURFACE_DESC desc;
    if (!surface || FAILED(surface->GetDesc(&desc)))
        return -1;
    for (int i = 0; i < g_targetCount; ++i)
    {
        const TargetInfo& t = g_targets[i];
        if (t.surface == surface && t.width == desc.Width && t.height == desc.Height && t.format == desc.Format
            && t.multisample == (int)desc.MultiSampleType)
            return i;
    }
    if (g_targetCount == kMaxTargets)
    {
        static bool said;
        if (!said)
            Log("OVERFLOW targets=%d note=more distinct targets than the probe numbers; the rest share T%d", kMaxTargets,
                kMaxTargets - 1);
        said = true;
        return kMaxTargets - 1;
    }
    TargetInfo& t = g_targets[g_targetCount];
    t.surface = surface;
    t.width = desc.Width;
    t.height = desc.Height;
    t.format = desc.Format;
    t.multisample = (int)desc.MultiSampleType;
    strcpy(t.kind, "surface");
    bool wasOwn = g_own;
    g_own = true;
    IDirect3DSurface9* back = nullptr;
    void* container = nullptr;
    if (SUCCEEDED(dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) && back == surface)
        strcpy(t.kind, "backbuffer");
    else if (desc.Usage & D3DUSAGE_DEPTHSTENCIL)
        strcpy(t.kind, "depth");
    else if (SUCCEEDED(surface->GetContainer(IID_IDirect3DCubeTexture9, &container)))
        strcpy(t.kind, "cube");
    else if (SUCCEEDED(surface->GetContainer(IID_IDirect3DTexture9, &container)))
        strcpy(t.kind, "texture");
    if (container)
        ((IUnknown*)container)->Release();
    if (back)
        back->Release();
    g_own = wasOwn;
    Log("TARGET id=T%d kind=%s size=%ux%u fmt=%s ms=%d", g_targetCount, t.kind, t.width, t.height, FormatName(t.format),
        t.multisample);
    return g_targetCount++;
}

char TargetKindCode(int id)
{
    return id >= 0 && id < g_targetCount ? g_targets[id].kind[0] : 0;
}

void TargetDescribe(int id, char* out, size_t size)
{
    if (id < 0 || id >= g_targetCount)
    {
        snprintf(out, size, "kind=none size=0x0 fmt=- ms=0");
        return;
    }
    const TargetInfo& t = g_targets[id];
    snprintf(out, size, "kind=%s size=%ux%u fmt=%s ms=%d", t.kind, t.width, t.height, FormatName(t.format), t.multisample);
}

// ---------------------------------------------------------------------------------------------
// What the game creates. Pictures it can draw into are logged one by one; ordinary textures are only
// counted by size and format (there are thousands).

enum { kMaxTextureKinds = 256, kMaxShaders = 2048 };
struct TextureKind { UINT width, height; D3DFORMAT format; LONG count; };
static TextureKind g_textureKinds[kMaxTextureKinds];
static int g_textureKindCount;
static LONG g_textureTotal, g_textureReported;

void ResourcesOnCreateTexture(UINT width, UINT height, UINT levels, DWORD usage, D3DFORMAT format, bool cube)
{
    if (usage & (D3DUSAGE_RENDERTARGET | D3DUSAGE_DEPTHSTENCIL))
    {
        Log("CREATE kind=%s size=%ux%u fmt=%s levels=%u ms=0",
            (usage & D3DUSAGE_DEPTHSTENCIL) ? "depth-texture" : cube ? "cube-target" : "texture-target", width, height,
            FormatName(format), levels);
        return;
    }
    ++g_textureTotal;
    for (int i = 0; i < g_textureKindCount; ++i)
        if (g_textureKinds[i].width == width && g_textureKinds[i].height == height && g_textureKinds[i].format == format)
        {
            ++g_textureKinds[i].count;
            return;
        }
    if (g_textureKindCount < kMaxTextureKinds)
        g_textureKinds[g_textureKindCount++] = { width, height, format, 1 };
}

void ResourcesOnCreateSurface(const char* kind, UINT width, UINT height, D3DFORMAT format, int multisample)
{
    Log("CREATE kind=%s size=%ux%u fmt=%s levels=1 ms=%d", kind, width, height, FormatName(format), multisample);
}

// Written with each report in which the number of ordinary textures has changed: the 12 commonest kinds.
void ResourcesReport()
{
    if (g_textureTotal == g_textureReported)
        return;
    g_textureReported = g_textureTotal;
    char top[512];
    size_t len = 0;
    top[0] = 0;
    bool used[kMaxTextureKinds] = {};
    for (int shown = 0; shown < 12; ++shown)
    {
        int best = -1;
        for (int i = 0; i < g_textureKindCount; ++i)
            if (!used[i] && (best < 0 || g_textureKinds[i].count > g_textureKinds[best].count))
                best = i;
        if (best < 0)
            break;
        used[best] = true;
        const TextureKind& k = g_textureKinds[best];
        len += snprintf(top + len, sizeof(top) - len, "%s%ux%u:%sx%ld", shown ? "," : "", k.width, k.height,
            FormatName(k.format), k.count);
    }
    Log("TEXTURES total=%ld kinds=%d top=%s", g_textureTotal, g_textureKindCount, top);
}

// ---------------------------------------------------------------------------------------------
// Shaders: each distinct one is saved once, named by a hash of its contents.

struct ShaderInfo { void* shader; DWORD hash; };
static ShaderInfo g_shaders[kMaxShaders];
static int g_shaderCount;
static DWORD g_savedHash[kMaxShaders];
static int g_savedCount;

// The length of a shader is only known to the library that understands it. The game has d3dx9_26.dll
// loaded; any other version present is as good.
static UINT ShaderSize(const DWORD* code)
{
    typedef UINT(WINAPI* GetShaderSizeFn)(const DWORD*);
    static GetShaderSizeFn getSize;
    static bool looked;
    if (!looked)
    {
        looked = true;
        for (int version = 24; version <= 43 && !getSize; ++version)
        {
            char name[32];
            snprintf(name, sizeof(name), "d3dx9_%d.dll", version);
            HMODULE module = GetModuleHandleA(name);
            if (module)
                getSize = (GetShaderSizeFn)GetProcAddress(module, "D3DXGetShaderSize");
        }
        if (!getSize)
            Log("SHADERS off: no d3dx9 library is loaded to measure shaders with");
    }
    return getSize && code ? getSize(code) : 0;
}

void ResourcesOnCreateShader(const DWORD* code, void* shader, bool vertex)
{
    UINT bytes = ShaderSize(code);
    if (!bytes)
        return;
    DWORD hash = 2166136261u; // FNV-1a
    for (UINT i = 0; i < bytes; ++i)
        hash = (hash ^ ((const BYTE*)code)[i]) * 16777619u;
    int slot = 0;
    while (slot < g_shaderCount && g_shaders[slot].shader != shader)
        ++slot;
    if (slot < kMaxShaders)
    {
        g_shaders[slot] = { shader, hash }; // an address reused for a new shader gets the new hash
        if (slot == g_shaderCount)
            ++g_shaderCount;
    }
    for (int i = 0; i < g_savedCount; ++i)
        if (g_savedHash[i] == hash)
            return;
    if (g_savedCount < kMaxShaders)
        g_savedHash[g_savedCount++] = hash;
    DWORD version = code[0];
    const char* kind = vertex ? "vs" : "ps";
    Log("SHADER kind=%s hash=%08lx bytes=%u version=%s_%lu_%lu", kind, (unsigned long)hash, bytes, kind,
        (unsigned long)((version >> 8) & 0xFF), (unsigned long)(version & 0xFF));
    char dir[MAX_PATH + 200], path[MAX_PATH + 240];
    snprintf(dir, sizeof(dir), "%s\\shaders", RunDir());
    CreateDirectoryA(dir, nullptr);
    snprintf(path, sizeof(path), "%s\\%s_%08lx.bin", dir, kind, (unsigned long)hash);
    FILE* f = fopen(path, "wb");
    if (f)
    {
        fwrite(code, 1, bytes, f);
        fclose(f);
    }
    else
        Log("SHADER file not written: %s", path);
}

DWORD ShaderHash(void* shader)
{
    for (int i = 0; i < g_shaderCount; ++i)
        if (g_shaders[i].shader == shader)
            return g_shaders[i].hash;
    return 0;
}
