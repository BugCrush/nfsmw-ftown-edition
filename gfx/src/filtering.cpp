// GfxProbe: which texture filtering the game's draws use (unchanged from the first GfxProbe).
// Every 8th draw the stage-0 sampler state is read back (GetSamplerState, so state blocks are covered).
#include "probe.h"

const char* FilterName(DWORD f)
{
    switch (f)
    {
    case D3DTEXF_NONE: return "none";
    case D3DTEXF_POINT: return "point";
    case D3DTEXF_LINEAR: return "linear";
    case D3DTEXF_ANISOTROPIC: return "anisotropic";
    case D3DTEXF_PYRAMIDALQUAD: return "pyramidal";
    case D3DTEXF_GAUSSIANQUAD: return "gaussian";
    }
    return "?";
}

// What the game set (SetSamplerState), per sampler stage 0-7.
static volatile LONG g_setMinFilter[8][8], g_setMaxAniso[8][17];
// What draws used: stage-0 min/mag/mip filter and MaxAnisotropy, sampled every 8th draw.
static volatile LONG g_drawCombo[8][8][8][17];
static volatile LONG g_draws, g_sampled, g_frames;

void FilteringOnSetSamplerState(DWORD stage, D3DSAMPLERSTATETYPE type, DWORD value)
{
    if (stage >= 8)
        return;
    if (type == D3DSAMP_MINFILTER && value < 8)
        InterlockedIncrement(&g_setMinFilter[stage][value]);
    else if (type == D3DSAMP_MAXANISOTROPY)
        InterlockedIncrement(&g_setMaxAniso[stage][value > 16 ? 16 : value]);
}

void FilteringOnDraw(IDirect3DDevice9* dev)
{
    if (InterlockedIncrement(&g_draws) & 7)
        return;
    DWORD minF = 0, magF = 0, mipF = 0, aniso = 0;
    dev->GetSamplerState(0, D3DSAMP_MINFILTER, &minF);
    dev->GetSamplerState(0, D3DSAMP_MAGFILTER, &magF);
    dev->GetSamplerState(0, D3DSAMP_MIPFILTER, &mipF);
    dev->GetSamplerState(0, D3DSAMP_MAXANISOTROPY, &aniso);
    InterlockedIncrement(&g_drawCombo[minF & 7][magF & 7][mipF & 7][aniso > 16 ? 16 : aniso]);
    InterlockedIncrement(&g_sampled);
}

void FilteringOnPresent()
{
    InterlockedIncrement(&g_frames);
}

// Writes the counts since the last report and clears them.
void FilteringReport()
{
    LONG sampled = InterlockedExchange(&g_sampled, 0), draws = InterlockedExchange(&g_draws, 0);
    LONG frames = InterlockedExchange(&g_frames, 0);
    if (!sampled)
        return;
    Log("--- last 15 s: %ld frames, %ld draw calls (%ld per frame), %ld sampled", frames, draws,
        frames ? draws / frames : 0, sampled);
    LONG effective[17] = {};
    for (int a = 0; a < 8; ++a)
        for (int b = 0; b < 8; ++b)
            for (int c = 0; c < 8; ++c)
                for (int d = 0; d < 17; ++d)
                {
                    LONG n = InterlockedExchange(&g_drawCombo[a][b][c][d], 0);
                    if (!n)
                        continue;
                    effective[a == D3DTEXF_ANISOTROPIC ? (d ? d : 1) : 1] += n;
                    if (n * 200 >= sampled) // only combinations with 0.5%+ of draws
                        Log("  %5.1f%% of draws: min=%s mag=%s mip=%s maxAnisotropy=%d", n * 100.0 / sampled,
                            FilterName(a), FilterName(b), FilterName(c), d);
                }
    char line[256] = "  effective anisotropy:";
    size_t len = strlen(line);
    for (int d = 1; d < 17; ++d)
        if (effective[d])
            len += snprintf(line + len, sizeof(line) - len, " %dx=%.1f%%", d, effective[d] * 100.0 / sampled);
    Log("%s", line);

    char set[256] = "  game set (stage 0) maxAnisotropy:";
    len = strlen(set);
    bool any = false;
    for (int d = 0; d < 17; ++d)
    {
        LONG n = InterlockedExchange(&g_setMaxAniso[0][d], 0);
        if (n)
        {
            len += snprintf(set + len, sizeof(set) - len, " %d(x%ld)", d, n);
            any = true;
        }
    }
    for (int s = 1; s < 8; ++s)
        for (int d = 0; d < 17; ++d)
            InterlockedExchange(&g_setMaxAniso[s][d], 0);
    if (any)
        Log("%s", set);
    for (int s = 0; s < 8; ++s)
        for (int f = 0; f < 8; ++f)
            InterlockedExchange(&g_setMinFilter[s][f], 0);
}
