// GfxProbe: one frame taken apart. From the Present that starts it to the Present that ends it, every
// intercepted call becomes a line in dissect-N\calls.txt, and each target is saved as an image at the
// moment the game switches away from it. This is slow (a short freeze) and happens a few times a run.
#include "probe.h"

bool g_dissecting;
static FILE* g_file;
static int g_number, g_next, g_lines, g_draws, g_images, g_saves;
static char g_dir[MAX_PATH + 220];
static LONGLONG g_started;
static DWORD g_startedAt;

void DissectLine(const char* fmt, ...)
{
    if (!g_file)
        return;
    va_list args;
    va_start(args, fmt);
    vfprintf(g_file, fmt, args);
    va_end(args);
    fputc('\n', g_file);
    ++g_lines;
}

bool DissectWanted()
{
    return g_cfg.dissect && !g_dissecting && g_driving && g_next < g_cfg.dissectCount
        && g_drivingMs >= (DWORD)g_cfg.dissectAt[g_next] * 1000;
}

void DissectStart()
{
    ++g_next;
    char path[MAX_PATH + 240];
    snprintf(g_dir, sizeof(g_dir), "%s\\dissect-%d", RunDir(), ++g_number);
    CreateDirectoryA(g_dir, nullptr);
    snprintf(path, sizeof(path), "%s\\calls.txt", g_dir);
    g_file = fopen(path, "w");
    if (!g_file)
    {
        Log("DISSECT n=%d FAILED: cannot write %s", g_number, path);
        return;
    }
    g_lines = g_draws = g_images = g_saves = 0;
    g_started = Ticks();
    g_startedAt = g_drivingMs;
    g_dissecting = true;
    DissectLine("frame dissect=%d driving_t=%.1f", g_number, g_drivingMs / 1000.0);
}

// Saves the target the game is about to leave (or, at the end of the frame, the last one).
void DissectSaveTarget(IDirect3DDevice9* dev)
{
    if (!g_dissecting || !FrameStageActive())
        return;
    g_own = true;
    IDirect3DSurface9* current = nullptr;
    HRESULT hr = dev->GetRenderTarget(0, &current);
    g_own = false;
    if (FAILED(hr) || !current)
        return;
    D3DSURFACE_DESC desc = {};
    current->GetDesc(&desc);
    int id = TargetId(dev, current);
    char file[64], path[MAX_PATH + 300], note[64], range[96] = "";
    snprintf(file, sizeof(file), "%03d-stage%02d-T%d-%ux%u.bmp", ++g_saves, FrameStageNumber(), id, desc.Width, desc.Height);
    snprintf(path, sizeof(path), "%s\\%s", g_dir, file);
    bool ok = SaveSurface(dev, current, path, note, sizeof(note));
    float lowest, highest, mean;
    if (SurfaceRange(dev, current, &lowest, &highest, &mean))
        snprintf(range, sizeof(range), " min=%g max=%g mean=%g", lowest, highest, mean);
    DissectLine("image stage=%d target=T%d size=%ux%u fmt=%s ok=%d%s file=%s note=%s", FrameStageNumber(), id, desc.Width,
        desc.Height, FormatName(desc.Format), ok ? 1 : 0, range, file, note[0] ? note : "-");
    if (ok)
        ++g_images;
    current->Release();
}

void DissectFinish(IDirect3DDevice9* dev)
{
    DissectSaveTarget(dev);
    g_dissecting = false;
    int lines = g_lines;
    fclose(g_file);
    g_file = nullptr;
    Log("DISSECT n=%d t=%.1f lines=%d draws=%d images=%d ms=%.0f dir=%s", g_number, g_startedAt / 1000.0, lines, g_draws,
        g_images, TicksToMs(Ticks() - g_started), g_dir);
}

void DissectDraw(IDirect3DDevice9* dev, const char* call, D3DPRIMITIVETYPE type, UINT primitives)
{
    ++g_draws;
    g_own = true;
    IDirect3DVertexShader9* vs = nullptr;
    IDirect3DPixelShader9* ps = nullptr;
    dev->GetVertexShader(&vs);
    dev->GetPixelShader(&ps);
    char textures[480];
    size_t len = 0;
    textures[0] = 0;
    for (DWORD stage = 0; stage < 8; ++stage)
    {
        IDirect3DBaseTexture9* texture = nullptr;
        if (FAILED(dev->GetTexture(stage, &texture)) || !texture)
            continue;
        char one[48];
        DescribeTexture(texture, one, sizeof(one));
        len += snprintf(textures + len, sizeof(textures) - len, "%s%lu:%s", len ? ";" : "", (unsigned long)stage, one);
        texture->Release();
    }
    DWORD minF = 0, magF = 0, mipF = 0, aniso = 0;
    dev->GetSamplerState(0, D3DSAMP_MINFILTER, &minF);
    dev->GetSamplerState(0, D3DSAMP_MAGFILTER, &magF);
    dev->GetSamplerState(0, D3DSAMP_MIPFILTER, &mipF);
    dev->GetSamplerState(0, D3DSAMP_MAXANISOTROPY, &aniso);
    DissectLine("draw call=%s prims=%u tris=%u fx=%s tech=%s pass=%d vs=%08lx ps=%08lx filt0=%s/%s/%s/%lu tex=%s", call, primitives,
        type >= D3DPT_TRIANGLELIST ? primitives : 0, LabelFx(g_curLabel), LabelTech(g_curLabel), g_curPass,
        (unsigned long)ShaderHash(vs), (unsigned long)ShaderHash(ps), FilterName(minF), FilterName(magF), FilterName(mipF),
        (unsigned long)aniso, textures[0] ? textures : "-");
    if (vs) vs->Release();
    if (ps) ps->Release();
    g_own = false;
}

// Only the render states that decide how a draw lands in the picture.
void DissectState(D3DRENDERSTATETYPE state, DWORD value)
{
    static const struct { D3DRENDERSTATETYPE state; const char* name; } kStates[] = {
        { D3DRS_ZENABLE, "ZENABLE" }, { D3DRS_ZWRITEENABLE, "ZWRITEENABLE" }, { D3DRS_ZFUNC, "ZFUNC" },
        { D3DRS_ALPHATESTENABLE, "ALPHATESTENABLE" }, { D3DRS_ALPHAREF, "ALPHAREF" },
        { D3DRS_ALPHABLENDENABLE, "ALPHABLENDENABLE" }, { D3DRS_SRCBLEND, "SRCBLEND" }, { D3DRS_DESTBLEND, "DESTBLEND" },
        { D3DRS_BLENDOP, "BLENDOP" }, { D3DRS_CULLMODE, "CULLMODE" }, { D3DRS_FOGENABLE, "FOGENABLE" },
        { D3DRS_FOGCOLOR, "FOGCOLOR" }, { D3DRS_STENCILENABLE, "STENCILENABLE" },
        { D3DRS_COLORWRITEENABLE, "COLORWRITEENABLE" }, { D3DRS_MULTISAMPLEANTIALIAS, "MULTISAMPLEANTIALIAS" },
        { D3DRS_SRGBWRITEENABLE, "SRGBWRITEENABLE" }, { D3DRS_DEPTHBIAS, "DEPTHBIAS" },
        { D3DRS_SLOPESCALEDEPTHBIAS, "SLOPESCALEDEPTHBIAS" } };
    for (const auto& known : kStates)
        if (known.state == state)
        {
            DissectLine("state name=%s value=0x%lX", known.name, (unsigned long)value);
            return;
        }
}

// Shader constants are four numbers each; at most eight are printed per write.
void DissectConstants(bool vertex, UINT reg, const float* data, UINT count)
{
    char values[640];
    size_t len = 0;
    values[0] = 0;
    UINT shown = count > 8 ? 8 : count;
    for (UINT i = 0; i < shown * 4 && data; ++i)
        len += snprintf(values + len, sizeof(values) - len, "%s%g", i ? "," : "", data[i]);
    DissectLine("constants kind=%s reg=%u count=%u values=%s", vertex ? "vs" : "ps", reg, count, values[0] ? values : "-");
}
