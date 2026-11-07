// FTownSmack.h - F-Town's breakable poles: Rockport's own smackable street lights and signal masts (X0's, by hash) and
// our lantern lamps break as Rockport's poles do. Included by FTownLoader.cpp after FTownRoadNet.h, sharing its helpers
// (Log, SafeRead, the sites' checks, ReadAgain, the city's set, the grid's reader).
//
// Notes: docs/ftown-notes.md and docs/ftown-race-notes.md "Breakable poles (2026-11-05)"; plan
// docs/superpowers/plans/2026-11-05-ftown-breakable-poles.md. The file ftown-smackables.bun (tools/citymap/build_city.py,
// tools/world/smackables.py) holds, after a chunk of id 0 with our override entries (LoadChunks skips id 0), one
// smackable spawner pack (chunk 0x34027) per district section of the city.
//
// - The game's loader 0x6829D0 (registered with its unloader 0x67C040 at 0x887C40) makes, for each record, a scenery
//   model (0x681540, at most 2,048 live: [0x92617C]) that reaches the pole's static instance through the record's
//   override entry (+0x2C, `table + index * 6` at 0x723C90 with no bounds check) and adds the pole's trigger to the
//   world grid (WTrigger::UpdatePos -> WGridManagedDynamicElem::AddElem: only cells with a node; F-Town's have ours).
//   It does nothing unless Sim::Exists (0x6E8D10: [0x9885E0]).
// - The override table is Rockport's (L2RA.BUN 0x34108: 22,340 entries; pointer 0x9A3A64, count 0x9A3A68). So, once
//   the city's sections are filed and its collision is in the grid, and the simulation exists: a table of our own
//   (Rockport's entries copied, ours after them) is pointed at, then LoadChunks(file copy, "FTOWNSMK"). Leaving
//   F-Town: UnloadChunks first (the unloader deletes every model and its trigger, showing the instance again through
//   the table, so the table must still be ours), then Rockport's 22,340 entries copied back (the flags the game set
//   meanwhile kept), the pointer and count back, ours freed; the file's copy 3 frames later.
// - Refused (the poles stay as static instances: a car passes through them) when the file is missing or malformed,
//   a site's bytes differ, the table's count is not 22,340, or an entry's instance is not the pole of the record
//   (another city than the file was built with).

static const DWORD kSmkTablePtr = 0x9A3A64, kSmkTableCount = 0x9A3A68, kSmkLive = 0x92617C, kSmkMoving = 0x925860;
static const DWORD kSmkRockport = 22340, kSmkMaxRecords = 2048, kSmkLoaderBits = 0x1 | 0x4 | 0x40000 | 0x80000;

static const Site kSmkSites[] = {
    {0x887C40, {0x68, 0x40, 0xC0, 0x67, 0x00, 0x68, 0xD0, 0x29, 0x68, 0x00, 0x68, 0x27, 0x40, 0x03, 0x00}, 15,
     "static init: the 0x34027 loader 0x6829D0 and unloader 0x67C040 registered"},
    {0x6829D0,
     {0x8B, 0x44, 0x24, 0x04, 0x81, 0x38, 0x27, 0x40, 0x03, 0x00, 0x0F, 0x85, 0xA2, 0x00, 0x00, 0x00, 0x56, 0x8D, 0x70,
      0x17, 0xA1, 0x60, 0x58, 0x92, 0x00, 0x83, 0xE6, 0xF0},
     28, "the spawner loader: the pack at (chunk + 0x17) & ~0xF; [0x925860] chunks moved"},
    {0x6829FE, {0x8A, 0x46, 0x0E, 0x84, 0xC0, 0x75, 0x1B, 0x33, 0xC0, 0x66, 0x39, 0x46, 0x0C}, 13,
     "the spawner loader: swapped +0x0E, count +0x0C"},
    {0x682A20, {0xE8, 0xEB, 0x62, 0x06, 0x00, 0x84, 0xC0, 0x74, 0x52}, 9, "the spawner loader: only when Sim::Exists"},
    {0x6828D0, {0x83, 0xEC, 0x08, 0x55, 0x8B, 0xE9, 0x0F, 0xBF, 0x45, 0x08, 0x56, 0x57, 0x50, 0xB9, 0xC0, 0x61, 0x92, 0x00},
     18, "the pack's load: section +0x08, smashed states 0x9261C0"},
    {0x681620,
     {0x8B, 0x44, 0x24, 0x04, 0x56, 0x8B, 0xF1, 0x85, 0x46, 0x34, 0x75, 0x49, 0x8B, 0x4E, 0x2C, 0x51, 0xE8, 0x5B, 0x26,
      0x0A, 0x00},
     21, "SmokeableSpawner::OnLoad: exclude flags +0x34, the override entry +0x2C (0x723C90)"},
    {0x68154E, {0xA1, 0x7C, 0x61, 0x92, 0x00}, 5, "the scenery model's maker: the live count [0x92617C]"},
    {0x68155D, {0x3D, 0x00, 0x08, 0x00, 0x00}, 5, "the scenery model's maker: at most 0x800 live"},
    {0x723C90, {0x8B, 0x44, 0x24, 0x04, 0x8B, 0x0D, 0x64, 0x3A, 0x9A, 0x00, 0x8D, 0x04, 0x40, 0x8D, 0x04, 0x41}, 16,
     "the override entry: [0x9A3A64] + index * 6, no bounds check"},
    {0x7287F0,
     {0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x7C, 0x50, 0x3B, 0x05, 0x68, 0x3A, 0x9A, 0x00, 0x7D, 0x48, 0x8B, 0x0D, 0x64,
      0x3A, 0x9A, 0x00},
     22, "the override table's count [0x9A3A68]"},
    {0x728920,
     {0x0F, 0xBF, 0x01, 0x8B, 0x04, 0x85, 0xB0, 0x3B, 0x9A, 0x00, 0x85, 0xC0, 0x74, 0x0D, 0x8B, 0x40, 0x04, 0x85, 0xC0},
     19, "SceneryOverrideInfo::AssignOverrides: the section's header through UserInfoTable 0x9A3BB0"},
    {0x67BC3B, {0x8B, 0x45, 0x2C, 0x56, 0x57, 0x8B, 0xF1, 0x50, 0x89, 0x74, 0x24, 0x10, 0xE8, 0x44, 0x80, 0x0A, 0x00}, 17,
     "the scenery model's constructor: its instance through the override entry"},
    {0x67C040,
     {0x56, 0x8B, 0x74, 0x24, 0x08, 0x81, 0x3E, 0x27, 0x40, 0x03, 0x00, 0x75, 0x24, 0xA1, 0x60, 0x58, 0x92, 0x00, 0x85,
      0xC0, 0x75, 0x14, 0xE8, 0xB5, 0xCC, 0x06, 0x00, 0x84, 0xC0, 0x74, 0x0B},
     31, "the spawner unloader: only when Sim::Exists"},
    {0x6E8D10, {0x8B, 0x0D, 0xE0, 0x85, 0x98, 0x00, 0x33, 0xC0, 0x85, 0xC9, 0x0F, 0x95, 0xC0, 0xC3}, 14,
     "Sim::Exists: [Sim::Internal::mSystem 0x9885E0] != 0"},
};

#pragma pack(push, 1)
struct SmkEntry
{
    short section, instance;
    WORD flags;
};
#pragma pack(pop)

static bool g_smkEnabled = true, g_smkReady;
static MapSet g_smk = {"FTOWNSMK", "breakable poles: "};
static SmkEntry g_smkEntries[kSmkMaxRecords];
static DWORD g_smkRec[kSmkMaxRecords];  // each record's offset in the file
static DWORD g_smkCount, g_smkBase, g_smkPacks;
static BYTE* g_smkTable;  // our override table while installed
static DWORD g_smkOrigPtr;
static BYTE* g_smkRefusedFor;  // the city buffer a load was refused for (no retry until F-Town loads again)
static int g_smkMade;

static void SmkSettings(const char* dir)
{
    g_smkEnabled = GetPrivateProfileIntA("Breakables", "Enabled", 1, g_iniPath) == 1;
    GetPrivateProfileStringA("Breakables", "File", "ftown-smackables.bun", g_smk.name, sizeof(g_smk.name), g_iniPath);
    snprintf(g_smk.path, sizeof(g_smk.path), "%s%s", dir, g_smk.name);
}

static bool SmkCitySection(int number)
{
    for (int k = 0; k < g_city.sectionCount; k++)
        if (g_city.sections[k] == number)
            return true;
    return false;
}

// The file: the FTSM chunk first, then 0x34027 packs (and id-0 padding) only; each record's override number in order,
// no loader-skipped exclude bit, its pack's section a city section and its entry's. Null or an error text.
static const char* SmkParse(const BYTE* f, DWORD size)
{
    DWORD off = 0;
    int top = 0;
    g_smkCount = g_smkPacks = 0;
    DWORD entries = 0, k = 0;
    while (off < size)
    {
        if (off + 8 > size)
            return "a chunk header runs past the file's end";
        DWORD id = *(const DWORD*)(f + off), sz = *(const DWORD*)(f + off + 4);
        if (sz > size - off - 8)
            return "a chunk runs past the file's end";
        if (++top > 64)
            return "more than 64 top-level chunks";
        const BYTE* d = f + off + 8;
        if (top == 1)
        {
            if (id != 0 || sz < 16 || memcmp(d, "FTSM", 4) || *(const DWORD*)(d + 4) != 1)
                return "not an FTSM version 1 file (its override entries first)";
            g_smkBase = *(const DWORD*)(d + 8);
            entries = *(const DWORD*)(d + 12);
            if (g_smkBase != kSmkRockport)
                return "its entries do not follow Rockport's 22,340";
            if (!entries || entries > kSmkMaxRecords || 16 + 6 * entries > sz)
                return "no entries, more than 2,048, or past the chunk";
            memcpy(g_smkEntries, d + 16, 6 * entries);
        }
        else if (id == 0x34027)
        {
            DWORD start = ((off + 0x17) & ~0xFu);  // the loader's (chunk + 0x17) & ~0xF (our buffer is 64 KB aligned)
            if (start + 16 > off + 8 + sz)
                return "a pack's header runs past its chunk";
            const BYTE* h = f + start;
            short section = *(const short*)(h + 8), count = *(const short*)(h + 12);
            if (*(const DWORD*)h != 0x0B || *(const DWORD*)(h + 4) != 0x0B || h[14] || count < 1 ||
                (DWORD)count > kSmkMaxRecords || start + 16 + 0x40u * count > off + 8 + sz)
                return "a pack's header is not a spawner pack's";
            if (!SmkCitySection(section))
                return "a pack's section is not one of the city's";
            for (int r = 0; r < count; r++, k++)
            {
                DWORD at = start + 16 + 0x40 * r;
                if (k >= entries)
                    return "more records than entries";
                if (*(const DWORD*)(f + at + 0x2C) != g_smkBase + k || (*(const DWORD*)(f + at + 0x34) & kSmkLoaderBits))
                    return "a record's override number or exclude flags";
                if (g_smkEntries[k].section != section)
                    return "a record's entry names another section than its pack";
                g_smkRec[k] = at;
            }
            g_smkPacks++;
        }
        else if (id != 0)
            return "a chunk that is not a spawner pack";
        off += 8 + sz;
    }
    if (k != entries)
        return "fewer records than entries";
    g_smkCount = entries;
    return nullptr;
}

static void SmkStart()
{
    if (!g_smkEnabled)
    {
        Log("breakable poles off ([Breakables] Enabled = 0): the poles stay as they are drawn");
        return;
    }
    HANDLE f = CreateFileA(g_smk.path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("breakable poles off: no file %s (tools/citymap/build_city.py writes it with the city)", g_smk.name);
        return;
    }
    g_smk.size = GetFileSize(f, nullptr);
    GetFileTime(f, nullptr, nullptr, &g_smk.time);
    BYTE* buf = (BYTE*)VirtualAlloc(nullptr, g_smk.size ? g_smk.size : 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    BOOL ok = buf && ReadFile(f, buf, g_smk.size, &got, nullptr) && got == g_smk.size;
    CloseHandle(f);
    const char* err = ok ? SmkParse(buf, g_smk.size) : "cannot be read";
    if (buf)
        VirtualFree(buf, 0, MEM_RELEASE);
    if (err)
    {
        Log("breakable poles off: the file %s: %s", g_smk.name, err);
        return;
    }
    bool sites = true;
    for (const Site& s : kSmkSites) sites &= BytesAre(s);
    if (!sites)
    {
        Log("WRONGBYTES in the breakable poles' sites: breakable poles off (the rest works)");
        return;
    }
    g_smkReady = true;
    Log("breakable poles: %s: %lu poles in %lu packs, override entries %lu.. after Rockport's %lu",
        g_smk.name, (unsigned long)g_smkCount, (unsigned long)g_smkPacks, (unsigned long)g_smkBase,
        (unsigned long)kSmkRockport);
}

// The entries against the loaded city: each names an instance of its section (filed in our buffer) whose low 16
// exclude bits are the entry's flags and whose position is the record's (physics, 1 cm). Null or why not.
static const char* SmkCheckCity(const BYTE* file)
{
    static char why[200];
    for (DWORD k = 0; k < g_smkCount; k++)
    {
        const SmkEntry& e = g_smkEntries[k];
        DWORD info = 0, header = 0, insts = 0, n = 0;
        if (!ReadDword(kUserInfoTable + 4 * e.section, &info) || !info || !ReadDword(info + 4, &header) || !header ||
            header < (DWORD)(UINT_PTR)g_city.buffer || header >= (DWORD)(UINT_PTR)g_city.buffer + g_city.size)
        {
            snprintf(why, sizeof(why), "section %d is not F-Town's filed section", e.section);
            return why;
        }
        if (!ReadDword(header + 0x20, &insts) || !ReadDword(header + 0x24, &n) || e.instance < 0 ||
            (DWORD)e.instance >= n)
        {
            snprintf(why, sizeof(why), "pole %lu: instance %d of section %d is not there (%lu instances)",
                     (unsigned long)k, e.instance, e.section, (unsigned long)n);
            return why;
        }
        BYTE inst[0x40];
        if (!SafeRead(insts + 0x40 * e.instance, inst, sizeof(inst)))
            return "an instance cannot be read";
        DWORD flags = *(DWORD*)(inst + 0x18);
        const float* p = (const float*)(inst + 0x20);  // render
        const float* q = (const float*)(file + g_smkRec[k] + 0x10);  // physics (-y, z, x)
        if ((flags & 0xFFFF) != e.flags || fabsf(q[0] + p[1]) > 0.01f || fabsf(q[1] - p[2]) > 0.01f ||
            fabsf(q[2] - p[0]) > 0.01f)
        {
            snprintf(why, sizeof(why), "pole %lu: instance %d of section %d is not its pole (flags 0x%08lX, at "
                     "%.2f, %.2f, %.2f): the file was built with another city", (unsigned long)k, e.instance,
                     e.section, (unsigned long)flags, p[0], p[1], p[2]);
            return why;
        }
    }
    return nullptr;
}

static void SmkRestoreTable(const char* why)
{
    if (!g_smkTable)
        return;
    DWORD ptr = 0;
    if (ReadDword(kSmkTablePtr, &ptr) && ptr == (DWORD)(UINT_PTR)g_smkTable)
    {
        memcpy((void*)(UINT_PTR)g_smkOrigPtr, g_smkTable, 6 * kSmkRockport);  // Rockport's state as the game left it
        *(DWORD*)(UINT_PTR)kSmkTablePtr = g_smkOrigPtr;
        *(DWORD*)(UINT_PTR)kSmkTableCount = kSmkRockport;
        Log("breakable poles: Rockport's override table back (%lu entries at 0x%08lX) (%s)",
            (unsigned long)kSmkRockport, (unsigned long)g_smkOrigPtr, why);
    }
    else
        Log("breakable poles: the override table is not ours any more (the track was set up again); left as it is (%s)",
            why);
    VirtualFree(g_smkTable, 0, MEM_RELEASE);
    g_smkTable = nullptr;
}

static void SmkLoad()
{
    double t0 = NowMs();
    g_smkRefusedFor = g_city.buffer;  // one try per F-Town load
    DWORD count = 0, ptr = 0;
    if (!ReadDword(kSmkTableCount, &count) || !ReadDword(kSmkTablePtr, &ptr) || !ptr || count != kSmkRockport)
    {
        Log("breakable poles: REFUSED: the override table has %lu entries at 0x%08lX, not Rockport's %lu: the poles "
            "stay static", (unsigned long)count, (unsigned long)ptr, (unsigned long)kSmkRockport);
        return;
    }
    FreePending(g_smk, true);
    BYTE* buffer = (BYTE*)VirtualAlloc(nullptr, g_smk.size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!buffer)
    {
        Log("breakable poles: REFUSED: no memory for the file");
        return;
    }
    if (!ReadAgain(g_smk, buffer))
    {
        VirtualFree(buffer, 0, MEM_RELEASE);
        return;
    }
    const char* bad = SmkCheckCity(buffer);
    if (bad)
    {
        VirtualFree(buffer, 0, MEM_RELEASE);
        Log("breakable poles: REFUSED: %s; the poles stay static", bad);
        return;
    }
    DWORD total = kSmkRockport + g_smkCount;
    g_smkTable = (BYTE*)VirtualAlloc(nullptr, 6 * total, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!g_smkTable || !SafeRead(ptr, g_smkTable, 6 * kSmkRockport))
    {
        if (g_smkTable)
            VirtualFree(g_smkTable, 0, MEM_RELEASE);
        g_smkTable = nullptr;
        VirtualFree(buffer, 0, MEM_RELEASE);
        Log("breakable poles: REFUSED: no memory for the override table (or Rockport's cannot be read)");
        return;
    }
    memcpy(g_smkTable + 6 * kSmkRockport, g_smkEntries, 6 * g_smkCount);
    g_smkOrigPtr = ptr;
    *(DWORD*)(UINT_PTR)kSmkTablePtr = (DWORD)(UINT_PTR)g_smkTable;
    *(DWORD*)(UINT_PTR)kSmkTableCount = total;
    DWORD liveBefore = 0, liveAfter = 0;
    ReadDword(kSmkLive, &liveBefore);
    double t1 = NowMs();
    ((LoadChunksFn)(UINT_PTR)kLoadChunks)(buffer, (int)g_smk.size, g_smk.chunkName);
    g_smk.buffer = buffer;
    double t2 = NowMs();
    ReadDword(kSmkLive, &liveAfter);
    g_smkMade = 0;
    int lost = 0;
    Grid g;
    bool grid = ReadGrid(&g);
    for (DWORD k = 0; k < g_smkCount; k++)
    {
        if (*(DWORD*)(buffer + g_smkRec[k] + 0x38))
            g_smkMade++;
        const float* q = (const float*)(buffer + g_smkRec[k] + 0x10);
        DWORD node = 0;
        if (grid)
        {
            DWORD c = Clamp(q[0], g.minX, g.invEdge, g.cols), r = Clamp(q[2], g.minZ, g.invEdge, g.rows);
            ReadDword(g.nodes + 4 * (r * g.cols + c), &node);
        }
        lost += !node;
    }
    Log("breakable poles: LOADED %s: %lu poles in %lu packs, %d scenery models made (live smackables %lu -> %lu of "
        "2048); override table %lu entries at 0x%08lX (Rockport's %lu first); LoadChunks %.1f ms, all %.1f ms",
        g_smk.name, (unsigned long)g_smkCount, (unsigned long)g_smkPacks, g_smkMade, (unsigned long)liveBefore,
        (unsigned long)liveAfter, (unsigned long)total, (unsigned long)(UINT_PTR)g_smkTable,
        (unsigned long)kSmkRockport, t2 - t1, NowMs() - t0);
    if (lost)
        Log("breakable poles: %d poles stand in a grid cell with no node: their triggers are lost (the poles stay)",
            lost);
    if (g_smkMade < (int)g_smkCount)
        Log("breakable poles: %d poles got no scenery model (the 2,048 cap, a volume or attributes not found): the game "
            "hides those", (int)g_smkCount - g_smkMade);
}

// Leaving F-Town (first, before anything of the city goes): the spawners out while the table is still ours, then
// Rockport's table back.
static void SmkUnload(const char* why)
{
    g_smkRefusedFor = nullptr;  // the next F-Town load tries again
    if (!g_smk.buffer)
    {
        SmkRestoreTable(why);
        return;
    }
    DWORD sim = 0, liveBefore = 0, liveAfter = 0;
    ReadDword(kSimSystem, &sim);
    ReadDword(kSmkLive, &liveBefore);
    double t0 = NowMs();
    ((LoadChunksFn)(UINT_PTR)kUnloadChunks)(g_smk.buffer, (int)g_smk.size, g_smk.chunkName);
    double t1 = NowMs();
    ReadDword(kSmkLive, &liveAfter);
    Log("breakable poles: UNLOADED (%s): UnloadChunks %.1f ms, live smackables %lu -> %lu%s", why, t1 - t0,
        (unsigned long)liveBefore, (unsigned long)liveAfter,
        sim ? "" : " (no simulation: the game's unloader did nothing; its models went with the simulation)");
    FreePending(g_smk, true);
    g_smk.pendingFree = g_smk.buffer;
    g_smk.pendingFrames = kFreeAfterFrames;
    g_smk.buffer = nullptr;
    SmkRestoreTable(why);
}

// Once a frame: the spawners in once F-Town is loaded (its sections filed, its collision in the grid) and the
// simulation exists, the chunks not being moved.
static BYTE* g_smkWaitLogged;  // the city buffer the "waiting for room" line was logged for

static void SmkFrame()
{
    if (!g_smkReady || !g_city.buffer || g_smk.buffer || g_smkRefusedFor == g_city.buffer)
        return;
    DWORD sim = 0, moving = 0, live = 0;
    if (!ReadDword(kSimSystem, &sim) || !sim || (ReadDword(kSmkMoving, &moving) && moving))
        return;
    // review: past the game's 2,048 live models OnLoad hides a pole for good (no model, 0x10 set): wait until there is
    // room for all of ours (Rockport's own spawners near the start go as the streamer drops their sections)
    if (ReadDword(kSmkLive, &live) && live + g_smkCount > kSmkMaxRecords)
    {
        if (g_smkWaitLogged != g_city.buffer)
            Log("breakable poles: waiting: %lu smackables live, no room for our %lu under the game's 2,048",
                (unsigned long)live, (unsigned long)g_smkCount);
        g_smkWaitLogged = g_city.buffer;
        return;
    }
    SmkLoad();
}
