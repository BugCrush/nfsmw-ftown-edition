// FTownCourse.h - Run J item 7 (docs/ftown-race-notes.md "Run J: the game side"): during an event the course still to
// drive drawn on the HUD minimap as a line, erased behind the car as it goes (a GPS line). Included once by
// FTownLoader.cpp after FTownRace.h (it uses the minimap's calibration and pack, the events and the helpers).
//
// The game's own GPS route needs a road network (F-Town has none), and drawing over the HUD ourselves would mean
// copying the map's rotation, zoom and round mask. Instead the line is painted into our own minimap textures, which
// the game then draws as always: each FTOWN_MAP_CHOP<n> is found with GetTextureInfo (0x503400, by bStringHash
// 0x460BF0 of its name; TextureInfo +0x24 the hash, +0x44 / +0x46 the size, +0x4A compression 0x24 = DXT3), its
// IDirect3DTexture9 at [[TextureInfo] + 0x18] (the PlatInfo, as TextureInfoPlatInterface::LockImage 0x6BED80 reads it),
// locked with its LockRect (vtable +0x4C) and UnlockRect (+0x50) as LockImage / UnlockImage do. Every 4 x 4 DXT3 block
// the line crosses is kept as it was, then encoded again with the line's pixels in the line's colour (the colour pair:
// the line's and the mean of the block's other pixels; each other pixel the nearest of the four colours); a block the
// car has passed gets its own 16 bytes back. Nothing is touched outside an event, or once our pack is gone.

static const DWORD kGetTextureInfo = 0x503400, kBStringHash = 0x460BF0;
static const Site kCourseSites[] = {
    {0x503400, {0x53, 0x55, 0x56, 0x57, 0x8B, 0x7C, 0x24, 0x14}, 8, "GetTextureInfo(name hash, default, unloaded too)"},
    {0x503422, {0x39, 0x78, 0x24}, 3, "GetTextureInfo: cmp [TextureInfo + 0x24], the name hash"},
    {0x6BED80, {0x8B, 0x09, 0x8B, 0x41, 0x18, 0x8B, 0x08, 0x83, 0xEC, 0x08, 0x6A, 0x00, 0x6A, 0x00, 0x8D, 0x54, 0x24, 0x08,
                0x52, 0x6A, 0x00, 0x50, 0xFF},
     23, "TextureInfoPlatInterface::LockImage: [[TextureInfo] + 0x18] the texture, its LockRect (+0x4C)"},
    {0x6BEDB0, {0x8B, 0x09, 0x8B, 0x41, 0x18, 0x8B, 0x08, 0x6A, 0x00, 0x50, 0xFF, 0x51, 0x50}, 13,
     "TextureInfoPlatInterface::UnlockImage: UnlockRect (+0x50)"},
    {0x460BF0, {0x8B, 0x54, 0x24, 0x04, 0x8A, 0x0A}, 6, "bStringHash(const char*)"},
};

struct CBlock
{
    short chop;
    unsigned short bx, by;
    unsigned short shown;  // the pixels drawn in the line's colour now (bit k: pixel k, row-major)
    bool read;             // orig holds the texture's bytes (read at the block's first write)
    BYTE orig[16];         // the block as the texture had it
    float s[16];           // each pixel's place along the course (metres), -1: not on the line
};
struct CChop
{
    void* tex;
    int size;
    bool tried;
};
static const int kCourseBlocks = 8192, kCourseHash = 16384;
static bool g_courseEnabled = true, g_courseOn, g_courseFailed;
static float g_courseWidth = 8.0f;
static DWORD g_courseColor = 0xFFD200;
static CBlock* g_cb;
static int* g_cbHash;
static int g_cbCount;
static CChop g_cc[64];
static bool g_courseLive;  // blocks of the line in the textures (something to put back)
static int g_courseEv = -1, g_courseSeg;
static float g_courseS, g_courseLastT;
static int g_courseLocks;
static int g_courseSize;  // the chops' size (the first usable one's; another size is refused)
static double g_courseUs;

typedef void*(__cdecl* GetTexInfoFn)(DWORD, int, int);
typedef DWORD(__cdecl* StrHashFn)(const char*);
typedef long(__stdcall* LockRectFn)(void*, unsigned, void*, const void*, DWORD);
typedef long(__stdcall* UnlockRectFn)(void*, unsigned);

static void CourseSettings()
{
    g_courseEnabled = GetPrivateProfileIntA("Course", "Enabled", 1, g_iniPath) == 1;
    g_courseWidth = IniFloat("Course", "WidthMetres", 8.0f);
    if (g_courseWidth < 1.0f || g_courseWidth > 60.0f)
        g_courseWidth = 8.0f;
    g_courseColor = (DWORD)IniHex("Course", "Color", "0xFFD200") & 0xFFFFFF;
}

static void CourseStartUp()
{
    if (!g_courseEnabled || !g_mmEnabled)
    {
        Log("course line off ([Course] Enabled = 0, or the minimap off)");
        return;
    }
    bool ok = true;
    for (const Site& s : kCourseSites) ok &= BytesAre(s);
    if (!ok)
    {
        Log("WRONGBYTES in the course line's sites: no course line on the minimap");
        return;
    }
    g_cb = (CBlock*)VirtualAlloc(nullptr, sizeof(CBlock) * kCourseBlocks + sizeof(int) * kCourseHash,
                                 MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_cb)
        return;
    g_cbHash = (int*)(g_cb + kCourseBlocks);
    g_courseOn = true;
    Log("course line: each event's course on the minimap, erased behind the car (%.0f m wide, colour %06lX)",
        g_courseWidth, (unsigned long)g_courseColor);
}

// our chop n's texture (null: not there, not DXT3, or another size than the others)
static void* CourseTexture(int n, int* size)
{
    CChop& c = g_cc[n];
    if (!c.tried)
    {
        c.tried = true;
        char name[96];
        snprintf(name, sizeof(name), "%s_CHOP%d", g_mmHeader, n);
        DWORD h = ((StrHashFn)(UINT_PTR)kBStringHash)(name);
        BYTE* ti = (BYTE*)((GetTexInfoFn)(UINT_PTR)kGetTextureInfo)(h, 0, 0);
        DWORD plat = 0, tex = 0, hash = 0;
        short w = 0, hh = 0;
        BYTE comp = 0;
        if (ti && SafeRead((DWORD)(UINT_PTR)ti + 0x24, &hash, 4) && hash == h && SafeRead((DWORD)(UINT_PTR)ti + 0x44, &w, 2) &&
            SafeRead((DWORD)(UINT_PTR)ti + 0x46, &hh, 2) && SafeRead((DWORD)(UINT_PTR)ti + 0x4A, &comp, 1) &&
            ReadDword((DWORD)(UINT_PTR)ti, &plat) && plat && ReadDword(plat + 0x18, &tex) && tex && comp == 0x24 &&
            w == hh && w >= 16 && w <= 2048 && (w & (w - 1)) == 0 && (!g_courseSize || w == g_courseSize))
        {
            c.tex = (void*)(UINT_PTR)tex;
            c.size = w;
            g_courseSize = w;
        }
        else
            Log("course line: %s not usable (TextureInfo 0x%08lX, texture 0x%08lX, %dx%d, compression 0x%02X)", name,
                (unsigned long)(UINT_PTR)ti, (unsigned long)tex, w, hh, comp);
    }
    *size = c.size;
    return c.tex;
}

static void Rgb565(WORD c, int* rgb)
{
    rgb[0] = ((c >> 11) & 31) * 255 / 31, rgb[1] = ((c >> 5) & 63) * 255 / 63, rgb[2] = (c & 31) * 255 / 31;
}
static WORD To565(const int* rgb)
{
    return (WORD)(((rgb[0] * 31 + 127) / 255) << 11 | ((rgb[1] * 63 + 127) / 255) << 5 | ((rgb[2] * 31 + 127) / 255));
}

// the block's 16 bytes with the pixels of `mask` in the line's colour (mask 0: the block as it was)
static void CourseEncode(const CBlock& b, unsigned short mask, BYTE* out)
{
    memcpy(out, b.orig, 16);
    if (!mask)
        return;
    int pal[4][3], px[16][3];
    WORD c0 = *(const WORD*)(b.orig + 8), c1 = *(const WORD*)(b.orig + 10);
    DWORD idx = *(const DWORD*)(b.orig + 12);
    Rgb565(c0, pal[0]), Rgb565(c1, pal[1]);
    for (int i = 0; i < 3; i++)
        pal[2][i] = (2 * pal[0][i] + pal[1][i]) / 3, pal[3][i] = (pal[0][i] + 2 * pal[1][i]) / 3;
    int sum[3] = {0, 0, 0}, others = 0;
    for (int k = 0; k < 16; k++)
    {
        memcpy(px[k], pal[(idx >> (2 * k)) & 3], sizeof(px[k]));
        if (!(mask >> k & 1))
            for (int i = 0; i < 3; i++) sum[i] += px[k][i];
        others += !(mask >> k & 1);
    }
    int line[3] = {(int)(g_courseColor >> 16 & 255), (int)(g_courseColor >> 8 & 255), (int)(g_courseColor & 255)};
    int bg[3];
    for (int i = 0; i < 3; i++) bg[i] = others ? sum[i] / others : line[i];
    WORD n0 = To565(line), n1 = To565(bg);
    Rgb565(n0, pal[0]), Rgb565(n1, pal[1]);
    for (int i = 0; i < 3; i++)
        pal[2][i] = (2 * pal[0][i] + pal[1][i]) / 3, pal[3][i] = (pal[0][i] + 2 * pal[1][i]) / 3;
    DWORD ni = 0;
    for (int k = 0; k < 16; k++)
    {
        int best = 0;
        if (!(mask >> k & 1))
        {
            int bd = 1 << 30;
            for (int p = 1; p < 4; p++)  // never the line's own colour for a pixel off the line
            {
                int d = 0;
                for (int i = 0; i < 3; i++) d += (px[k][i] - pal[p][i]) * (px[k][i] - pal[p][i]);
                if (d < bd)
                    bd = d, best = p;
            }
        }
        ni |= (DWORD)best << (2 * k);
    }
    *(WORD*)(out + 8) = n0, *(WORD*)(out + 10) = n1, *(DWORD*)(out + 12) = ni;
}

// the block of map pixel (px, py), made (its own bytes read from the texture later) when `make`
static CBlock* CourseBlock(int chop, int bx, int by, bool make)
{
    unsigned key = (unsigned)chop * 0x9E3779B1u ^ (unsigned)bx * 0x85EBCA6Bu ^ (unsigned)by * 0xC2B2AE35u;
    for (unsigned i = 0; i < (unsigned)kCourseHash; i++)
    {
        int& slot = g_cbHash[(key + i) & (kCourseHash - 1)];
        if (slot < 0)
        {
            if (!make || g_cbCount >= kCourseBlocks)
                return nullptr;
            CBlock& b = g_cb[g_cbCount];
            b.chop = (short)chop, b.bx = (unsigned short)bx, b.by = (unsigned short)by, b.shown = 0, b.read = false;
            for (float& s : b.s) s = -1;
            slot = g_cbCount++;
            return &b;
        }
        CBlock& b = g_cb[slot];
        if (b.chop == chop && b.bx == bx && b.by == by)
            return &b;
    }
    return nullptr;
}

// every block whose pixels to show differ from what is shown: written, one lock a chop; `all` puts every block back
static void CourseWrite(bool all)
{
    LARGE_INTEGER a, z;
    QueryPerformanceCounter(&a);
    for (int chop = 0; chop < 64 && !g_courseFailed; chop++)
    {
        BYTE* bits = nullptr;
        int pitch = 0, size = 0;
        void* tex = nullptr;
        for (int k = 0; k < g_cbCount; k++)
        {
            CBlock& b = g_cb[k];
            if (b.chop != chop)
                continue;
            unsigned short want = 0;
            for (int p = 0; p < 16 && !all; p++)
                if (b.s[p] >= 0 && b.s[p] >= g_courseS)
                    want |= (unsigned short)(1 << p);
            if (want == b.shown)
                continue;
            if (!bits)
            {
                tex = CourseTexture(chop, &size);
                if (!tex)
                    break;
                struct
                {
                    int pitch;
                    void* bits;
                } lr = {0, nullptr};
                long hr = ((LockRectFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(tex) + 0x4C)))(tex, 0, &lr, nullptr, 0);
                if (hr < 0 || !lr.bits || lr.pitch < size / 4 * 16)
                {
                    Log("course line: chop %d's texture cannot be locked (0x%08lX): no course line any more", chop,
                        (unsigned long)hr);
                    if (hr >= 0)
                        ((UnlockRectFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(tex) + 0x50)))(tex, 0);
                    g_courseFailed = true;
                    break;
                }
                bits = (BYTE*)lr.bits, pitch = lr.pitch;
                g_courseLocks++;
            }
            BYTE* at = bits + b.by * pitch + b.bx * 16;
            if (!b.read)  // the texture's own bytes, kept to put back
            {
                memcpy(b.orig, at, 16);
                b.read = true;
            }
            BYTE out[16];
            CourseEncode(b, want, out);
            memcpy(at, out, 16);
            b.shown = want;
        }
        if (bits)
            ((UnlockRectFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(tex) + 0x50)))(tex, 0);
    }
    QueryPerformanceCounter(&z);
    g_courseUs += (double)(z.QuadPart - a.QuadPart) * 1e6 / (double)g_qpcFreq.QuadPart;
    g_courseLive = false;
    for (int k = 0; k < g_cbCount && !g_courseLive; k++) g_courseLive = g_cb[k].shown != 0;
}

// the line put back everywhere and forgotten
static void CourseStop(const char* why)
{
    if (!g_courseOn || g_courseEv < 0)
        return;
    if (g_courseLive && g_mmBuffer)
        CourseWrite(true);
    Log("course line: off (%s): %d blocks, %d locks, %.2f ms in all", why, g_cbCount, g_courseLocks, g_courseUs / 1000.0);
    g_courseEv = -1;
    g_cbCount = 0;
    g_courseLive = false;
    for (CChop& c : g_cc) c = CChop();
    g_courseSize = 0;
}

// The event's course from its start to its finish: every map pixel within half the line's width of it, with its place
// along the course (the largest where the course passes twice), then drawn.
static void CourseStart(int ev)
{
    CourseStop("another start");
    const Event& e = g_events[ev];
    if (!g_courseOn || g_courseFailed || !g_mmBuffer || e.routeCount < 2)
        return;
    LARGE_INTEGER a, z;
    QueryPerformanceCounter(&a);
    for (int i = 0; i < kCourseHash; i++) g_cbHash[i] = -1;
    g_cbCount = 0;
    g_courseLocks = 0;
    g_courseUs = 0;
    int size = 0;
    for (int n = 0; n < 64 && !size; n++) CourseTexture(n, &size);
    if (!size)
    {
        Log("course line: none of our chops is usable: no line");
        return;
    }
    const float ulx = g_mmCalib[0], uly = g_mmCalib[1], W = g_mmCalib[2], map = 8.0f * size, mpp = W / map;
    const float half = g_courseWidth * 0.5f;
    float s = 0;
    int pixels = 0;
    bool full = false;
    for (int i = 0; i + 1 < e.routeCount && !full; i++)
    {
        const float *p = e.route[i], *q = e.route[i + 1];
        float dx = q[0] - p[0], dy = q[1] - p[1], len = sqrtf(dx * dx + dy * dy);
        float sa = s, sb = s + len;
        s = sb;
        if (len < 1e-3f || sb < e.startS || sa > e.finishS)
            continue;
        // Run K item 3: over the band (the road the minimap draws, both halves of a divided road), a capsule from
        // band point i to i + 1 with its half width interpolated, at least half the line's width; else on the route
        const float *ba = e.band ? e.band[i] : nullptr, *bb = e.band ? e.band[i + 1] : nullptr;
        const float A[2] = {ba ? ba[0] : p[0], ba ? ba[1] : p[1]}, B[2] = {bb ? bb[0] : q[0], bb ? bb[1] : q[1]};
        const float ha = ba ? fmaxf(ba[2], half) : half, hb = bb ? fmaxf(bb[2], half) : half;
        const float bx = B[0] - A[0], by = B[1] - A[1], bl2 = bx * bx + by * by, hm = fmaxf(ha, hb);
        float x0 = fminf(A[0], B[0]) - hm, x1 = fmaxf(A[0], B[0]) + hm;
        float y0 = fminf(A[1], B[1]) - hm, y1 = fmaxf(A[1], B[1]) + hm;
        int px0 = (int)floorf((x0 - ulx) / mpp), px1 = (int)floorf((x1 - ulx) / mpp);
        int py0 = (int)floorf(((uly - y1) / W + 1.0f) * map), py1 = (int)floorf(((uly - y0) / W + 1.0f) * map);
        for (int py = py0; py <= py1 && !full; py++)
            for (int px = px0; px <= px1; px++)
            {
                if (px < 0 || py < 0 || px >= (int)map || py >= (int)map)
                    continue;
                float x = ulx + (px + 0.5f) * mpp, y = uly - ((py + 0.5f) / map - 1.0f) * W;
                float t = bl2 > 1e-6f ? ((x - A[0]) * bx + (y - A[1]) * by) / bl2 : 0.0f;
                t = t < 0 ? 0 : t > 1 ? 1 : t;
                float ex = A[0] + bx * t - x, ey = A[1] + by * t - y, r = ha + (hb - ha) * t;
                float at = sa + len * t;
                if (ex * ex + ey * ey > r * r || at < e.startS || at > e.finishS)
                    continue;
                int chop = (py / size) * 8 + px / size, lx = px % size, ly = py % size;
                CBlock* b = CourseBlock(chop, lx / 4, ly / 4, true);
                if (!b)
                {
                    full = true;
                    break;
                }
                int k = (ly & 3) * 4 + (lx & 3);
                if (b->s[k] < 0)
                    pixels++;
                if (b->s[k] < at)
                    b->s[k] = at;
            }
    }
    g_courseEv = ev;
    g_courseSeg = 0;
    g_courseS = e.startS;
    g_courseLastT = -1;
    CourseWrite(false);
    QueryPerformanceCounter(&z);
    Log("course line: %s from %.0f to %.0f m: %d pixels in %d blocks (%d x %d chops, %.2f m a pixel; %s)%s, %.2f ms",
        e.title, e.startS, e.finishS, pixels, g_cbCount, size, size, mpp,
        e.band ? "as wide as the road the map draws" : "WidthMetres wide", full ? "; the block table is full" : "",
        (double)(z.QuadPart - a.QuadPart) * 1000.0 / (double)g_qpcFreq.QuadPart);
}

// Once a frame while an event runs: the car's place along the course (its nearest point on the next legs, within 40 m,
// never back), and every 0.1 s of game time the blocks it has passed put back.
static void CourseFrame(const float* car)
{
    if (!g_courseOn || g_courseEv < 0 || !g_courseLive || g_courseFailed || !g_mmBuffer)
        return;
    const Event& e = g_events[g_courseEv];
    float s = 0, best = 40.0f * 40.0f, bestS = -1;
    int bestSeg = -1;
    for (int i = 0; i + 1 < e.routeCount; i++)
    {
        const float *p = e.route[i], *q = e.route[i + 1];
        float dx = q[0] - p[0], dy = q[1] - p[1], len2 = dx * dx + dy * dy, len = sqrtf(len2);
        if (i >= g_courseSeg && i <= g_courseSeg + 30 && len > 1e-3f)
        {
            float t = ((car[0] - p[0]) * dx + (car[1] - p[1]) * dy) / len2;
            t = t < 0 ? 0 : t > 1 ? 1 : t;
            float ex = p[0] + dx * t - car[0], ey = p[1] + dy * t - car[1], d = ex * ex + ey * ey;
            if (d < best)
                best = d, bestS = s + len * t, bestSeg = i;
        }
        s += len;
    }
    if (bestSeg >= 0 && bestS > g_courseS)
        g_courseS = bestS, g_courseSeg = bestSeg;
    float now = SimNow();
    if (g_courseLastT >= 0 && now - g_courseLastT < 0.1f && now >= g_courseLastT)
        return;
    g_courseLastT = now;
    CourseWrite(false);
}
