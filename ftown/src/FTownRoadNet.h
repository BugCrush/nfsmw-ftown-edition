// FTownRoadNet.h - moving traffic on F-Town: F-Town's road network for the game's AI (tools/citymap/roadnet_build.py,
// ftown-roadnet.bin) appended to Rockport's while F-Town is in the race, the world grid widened so the game finds it,
// the game's own traffic spawning on F-Town's roads and driving at their speeds. Included by FTownLoader.cpp after
// FTownTraffic.h, sharing its helpers (Log, SafeRead, the sites' checks, the city's set, the events' state).
//
// Research: docs/ftown-traffic-ai-research.md; plan docs/superpowers/plans/2026-11-05-ftown-moving-traffic.md; notes
// docs/ftown-race-notes.md "Moving traffic (2026-11-05)".
// - The network: WRoadNetwork::Init (0x789980) points fProfiles 0x9B38B8, fNodes 0x9B38BC, fSegments 0x9B38C0, fRoads
//   0x9B38C8 at the track file and stores the counts (profiles 0x9B3884, nodes 0x9B387C, segments 0x9B3874, roads
//   0x9B3880). Every AI nav holds segment numbers, so ours go after Rockport's in one list of our own (Rockport's part
//   copied as it is): old numbers stay valid. Put back (Rockport's part copied back, the pointers and counts restored)
//   before the track unloads; kept through an F-Town unload in the race (traffic may still hold our numbers).
// - The grid: lookups read a cell's stored node's road-segment tags (type 3); F-Town lies on the low-x side of
//   Rockport's grid. FTownLoader prepends the file's columns: a new cell array from the game's bMalloc (0x465A70, so
//   WGrid::Shutdown's bFree 0x4655F0 is right even if ours never runs), Rockport's node pointers moved, nodes of ours
//   (0x14-byte header, then the city's collision-instance tags (type 0, counted only while the city is loaded) and the
//   road-segment tags) in F-Town's cells. The city's collision then needs no dynamic entries.
// - Spawning: AITrafficManager::CheckRace's one call (0x43804C, in FindSpawnPoint) goes to ours: an F-Town segment in
//   Free Roam may spawn traffic (no InRace marks, so the game's wrong-way check stays quiet); otherwise the game's own
//   rule (in an event only its route, marked InRace + RaceRouteForward; its exits NoTraffic).
// - Speeds: AIActionTraffic::ComputeSpeed's posted speed (0x41187D..0x41188E: >= 4 traffic lanes ? highway : street)
//   goes to ours: on an F-Town segment its road kind's km/h times a factor 0.85..1.15 a car; elsewhere the game's.
// - The connection to Rockport (file version 2, docs/ftown-connection-research.md C4/C5): the connector is a road of
//   ours; its far end joins Mathura Road, its Rockport end one decision segment per mouth of Rockport's T. Joined
//   (RoadNetJoin) only while FTownConnect.h has the connection on: our copy of each mouth's record gets the segment in
//   its next slot (Rockport's own bytes never change; the copy-back first takes it out again); off, every link segment
//   is NoTraffic. The connector's cells in Rockport's own columns: the widened array points at a copy of Rockport's
//   node with our road tags added (its dynamic list shared, handed back at narrowing).

static const DWORD kRnProfilesPtr = 0x9B38B8, kRnNodesPtr = 0x9B38BC, kRnSegmentsPtr = 0x9B38C0,
                   kRnRoadsPtr = 0x9B38C8;
static const DWORD kRnProfiles = 0x9B3884, kRnNodes = 0x9B387C, kRnSegments = 0x9B3874, kRnRoads = 0x9B3880;
static const DWORD kRnNetwork = 0x9B38B4, kRnCheckRace = 0x404F20, kRnCheckSite = 0x43804C;
static const DWORD kRnSpeedSite = 0x41187D, kRnLanes = 0x76DD30, kBMalloc = 0x465A70, kBFree = 0x4655F0;

static const Site kRnSites[] = {
    {0x789A4D, {0xA3, 0x84, 0x38, 0x9B, 0x00}, 5, "WRoadNetwork::Init: mov [fNumProfiles 0x9B3884], eax"},
    {0x789A56, {0x89, 0x3D, 0x7C, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fNumNodes 0x9B387C], edi"},
    {0x789A60, {0x89, 0x15, 0x74, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fNumSegments 0x9B3874], edx"},
    {0x789A7A, {0x89, 0x0D, 0x80, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fNumRoads 0x9B3880], ecx"},
    {0x789AFD, {0x89, 0x3D, 0xB8, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fProfiles 0x9B38B8], edi"},
    {0x789B37, {0x89, 0x3D, 0xBC, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fNodes 0x9B38BC], edi"},
    {0x789B71, {0x89, 0x3D, 0xC0, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fSegments 0x9B38C0], edi"},
    {0x789BAB, {0x89, 0x3D, 0xC8, 0x38, 0x9B, 0x00}, 6, "WRoadNetwork::Init: mov [fRoads 0x9B38C8], edi"},
    {0x438049, {0x57, 0x8B, 0xCB, 0xE8, 0xCF, 0xCE, 0xFC, 0xFF}, 8,
     "AITrafficManager::FindSpawnPoint: push nav; mov ecx, this; call CheckRace (0x404F20)"},
    {0x404F20, {0xA1, 0x00, 0xE0, 0x91, 0x00, 0x85, 0xC0, 0x74, 0x47}, 9, "AITrafficManager::CheckRace: GRaceStatus"},
    {0x404F45,
     {0x8B, 0x44, 0x24, 0x04, 0x0F, 0xBF, 0x80, 0x8E, 0x00, 0x00, 0x00, 0x8B, 0x0D, 0xC0, 0x38, 0x9B, 0x00, 0x6B, 0xC0,
      0x16},
     20, "CheckRace: the nav's segment (+0x8E) in fSegments (22 bytes each)"},
    {0x411853, {0x8B, 0x15, 0xC0, 0x38, 0x9B, 0x00}, 6, "AIActionTraffic::ComputeSpeed: mov edx, [fSegments]"},
    {0x41187D,
     {0xE8, 0xAE, 0xC4, 0x35, 0x00, 0x83, 0xF8, 0x04, 0x7C, 0x05, 0xD9, 0x46, 0x54, 0xEB, 0x03, 0xD9, 0x46, 0x50}, 18,
     "ComputeSpeed: GetSegmentNumTrafficLanes >= 4 ? highway (+0x54) : street (+0x50)"},
    {0x76DD30, {0x8B, 0x4C, 0x24, 0x04, 0x83, 0xEC, 0x08, 0x56}, 8, "WRoadNetwork::GetSegmentNumTrafficLanes"},
    {0x465A70, {0x8B, 0x44, 0x24, 0x08, 0x8B, 0x4C, 0x24, 0x04}, 8, "bMalloc(size, flags)"},
    {0x4655F0, {0x8B, 0x44, 0x24, 0x04, 0x83, 0xEC, 0x20}, 7, "bFree"},
    {0x76438D, {0xE8, 0xDE, 0x16, 0xD0, 0xFF}, 5, "WGrid::WGrid: the cell array from bMalloc"},
    {0x781762, {0x50, 0xE8, 0x88, 0x3E, 0xCE, 0xFF}, 6, "WGrid::Shutdown: bFree(fNodes)"},
};

static bool __fastcall HkCheckRace(void* mgr, void*, const BYTE* nav);
extern "C" char FtSpeedStub[];

// ---------------------------------------------------------------- settings and the file

static bool g_rnEnabled = true, g_rnEventTraffic = true, g_rnLeft, g_rnReady;
static int g_rnLevel = 3;
static float g_rnSpread = 0.15f;
static char g_rnName[MAX_PATH], g_rnPath[MAX_PATH];

#pragma pack(push, 1)
struct RnHead
{
    char magic[4];
    DWORD version;
    DWORD rock[4];  // profiles, nodes, segments, roads (expected in the game)
    DWORD ours[4];
    float gridMinX, gridMinZ, gridEdge;
    DWORD gridRows, gridCols, padCols;
    DWORD cells, tags, events, parking;
    DWORD spots, joins, rockCells, links;  // version 2: the connection (version 1: zeros)
};
struct RnCell
{
    DWORD cell, first, count;
};
struct RnEvent
{
    char id[16];
    DWORD first, count;
};
struct RnJoin
{
    WORD node, count, before[7], added;
};
#pragma pack(pop)

static BYTE* g_rnFile;
static DWORD g_rnSize;
static const RnHead* g_rnHead;
static const BYTE *g_rnProf, *g_rnNode, *g_rnSeg, *g_rnRoad, *g_rnKmh, *g_rnPark;
static const RnCell* g_rnCells;
static const DWORD *g_rnTags, *g_rnMarks;
static const RnEvent* g_rnEvents;
static const RnJoin* g_rnJoins;
static const RnCell* g_rnRockCells;
static const DWORD *g_rnRockTags, *g_rnLinks;
static bool g_rnJoined;

static void RoadNetSettings(const char* dir)
{
    g_rnEnabled = GetPrivateProfileIntA("MovingTraffic", "Enabled", 1, g_iniPath) == 1;
    GetPrivateProfileStringA("MovingTraffic", "File", "ftown-roadnet.bin", g_rnName, sizeof(g_rnName), g_iniPath);
    snprintf(g_rnPath, sizeof(g_rnPath), "%s%s", dir, g_rnName);
    g_rnLevel = GetPrivateProfileIntA("MovingTraffic", "Level", 3, g_iniPath);
    g_rnLevel = g_rnLevel < 0 ? 0 : g_rnLevel > 3 ? 3 : g_rnLevel;
    g_rnEventTraffic = GetPrivateProfileIntA("MovingTraffic", "EventTraffic", 1, g_iniPath) == 1;
    char buf[16];
    GetPrivateProfileStringA("MovingTraffic", "DriveOn", "right", buf, sizeof(buf), g_iniPath);
    g_rnLeft = !_stricmp(buf, "left");
    int spread = GetPrivateProfileIntA("MovingTraffic", "SpeedSpreadPercent", 15, g_iniPath);
    g_rnSpread = (spread < 0 ? 0 : spread > 50 ? 50 : spread) / 100.0f;
}

// Reads and checks the file: its arrays inside it, its numbers within the game's limits. Null or an error text.
static const char* RoadNetParse()
{
    if (g_rnSize < sizeof(RnHead))
        return "shorter than its header";
    const RnHead* h = (const RnHead*)g_rnFile;
    if (memcmp(h->magic, "FTRN", 4) || (h->version != 1 && h->version != 2))
        return "not an FTRN version 1 or 2 file";
    if (h->version == 1 && (h->joins || h->rockCells || h->links))
        return "a version 1 file with the connection's counts";
    if (!h->ours[0] || !h->ours[1] || !h->ours[2] || !h->ours[3])
        return "an empty network";
    if (h->rock[1] + h->ours[1] > 32767 || h->rock[2] + h->ours[2] > 32767 || h->rock[0] + h->ours[0] > 32767 ||
        h->rock[3] + h->ours[3] > 32767)
        return "more than 32,767 nodes, segments, profiles or roads in all (the game keeps them in 15/16 bits)";
    if (h->padCols < 1 || h->padCols > 1024 || h->gridRows > 4096 || h->gridCols > 4096 || !(h->gridEdge > 0))
        return "grid numbers out of range";
    unsigned long long o = sizeof(RnHead);
    auto take = [&](unsigned long long n) -> const BYTE* {
        if (o + n > g_rnSize)
            return nullptr;
        const BYTE* p = g_rnFile + o;
        o += (n + 3) & ~3ull;
        return p;
    };
    unsigned long long segBytes = 22ull * h->ours[2];
    g_rnProf = take(64ull * h->ours[0]);
    g_rnNode = take(32ull * h->ours[1]);
    g_rnSeg = take(segBytes);
    g_rnRoad = take(8ull * h->ours[3]);
    g_rnKmh = take(h->ours[2]);
    g_rnCells = (const RnCell*)take(12ull * h->cells);
    g_rnTags = (const DWORD*)take(4ull * h->tags);
    g_rnEvents = (const RnEvent*)take(24ull * h->events);
    if (!g_rnProf || !g_rnNode || !g_rnSeg || !g_rnRoad || !g_rnKmh || !g_rnCells || !g_rnTags || !g_rnEvents)
        return "its arrays run past the file's end";
    DWORD marks = 0;
    for (DWORD k = 0; k < h->events; k++)
    {
        if (g_rnEvents[k].first != marks || g_rnEvents[k].count > 65536)
            return "an event's marks out of order";
        marks += g_rnEvents[k].count;
    }
    g_rnMarks = (const DWORD*)take(4ull * marks);
    g_rnPark = take(h->parking);
    if (!g_rnMarks || (!g_rnPark && h->parking))
        return "its marks or parking list run past the file's end";
    if (h->joins > 16 || h->rockCells > 4096 || h->links > 65536)
        return "the connection's counts out of range";
    g_rnJoins = (const RnJoin*)take(20ull * h->joins);
    g_rnRockCells = (const RnCell*)take(12ull * h->rockCells);
    DWORD rockTags = 0;
    if (g_rnRockCells)
        for (DWORD k = 0; k < h->rockCells; k++)
        {
            const RnCell& c = g_rnRockCells[k];
            if (c.first != rockTags || c.count > 200 || c.cell >= h->gridRows * h->gridCols ||
                (k && c.cell <= g_rnRockCells[k - 1].cell))
                return "a cell of Rockport's columns out of range or order";
            rockTags += c.count;
        }
    g_rnRockTags = (const DWORD*)take(4ull * rockTags);
    g_rnLinks = (const DWORD*)take(4ull * h->links);
    if ((h->joins && !g_rnJoins) || (h->rockCells && (!g_rnRockCells || (rockTags && !g_rnRockTags))) ||
        (h->links && !g_rnLinks))
        return "the connection's lists run past the file's end";
    for (DWORD k = 0; k < h->joins; k++)
    {
        const RnJoin& j = g_rnJoins[k];
        if (j.node >= h->rock[1] || j.count > 6 || j.added < h->rock[2] || j.added >= h->rock[2] + h->ours[2])
            return "a join out of range";
    }
    for (DWORD k = 0; k < rockTags; k++)
        if (g_rnRockTags[k] < h->rock[2] || g_rnRockTags[k] >= h->rock[2] + h->ours[2])
            return "a Rockport cell names a segment that is not ours";
    for (DWORD k = 0; k < h->links; k++)
        if (g_rnLinks[k] < h->rock[2] || g_rnLinks[k] >= h->rock[2] + h->ours[2])
            return "a link segment that is not ours";
    DWORD cols = h->gridCols + h->padCols, tags = 0;
    for (DWORD k = 0; k < h->cells; k++)
    {
        const RnCell& c = g_rnCells[k];
        if (c.first != tags || c.count > 255 || c.cell >= h->gridRows * cols || c.cell % cols >= h->padCols ||
            (k && c.cell <= g_rnCells[k - 1].cell))
            return "a grid cell out of range or order (or one of Rockport's columns)";
        tags += c.count;
    }
    if (tags != h->tags)
        return "the cells' tags do not add up";
    DWORD nseg = h->rock[2] + h->ours[2], nnode = h->rock[1] + h->ours[1];
    for (DWORD k = 0; k < h->tags; k++)
        if (g_rnTags[k] < h->rock[2] || g_rnTags[k] >= nseg)
            return "a cell names a segment that is not ours";
    for (DWORD k = 0; k < marks; k++)
        if ((g_rnMarks[k] & 0xFFFF) < h->rock[2] || (g_rnMarks[k] & 0xFFFF) >= nseg)
            return "an event marks a segment that is not ours";
    for (DWORD k = 0; k < h->ours[2]; k++)
    {
        const BYTE* s = g_rnSeg + 22 * k;
        WORD a = *(const WORD*)s, b = *(const WORD*)(s + 2);
        short idx = *(const short*)(s + 8);
        bool joinEnd = false;  // a join's segment ends at its Rockport mouth (version 2)
        for (DWORD j = 0; j < h->joins && b < h->rock[1]; j++)
            joinEnd |= g_rnJoins[j].added == h->rock[2] + k && g_rnJoins[j].node == b;
        if (a < h->rock[1] || a >= nnode || (b < h->rock[1] && !joinEnd) || b >= nnode || (DWORD)idx != h->rock[2] + k)
            return "a segment's nodes or number out of range";
    }
    for (DWORD k = 0; k < h->ours[1]; k++)
    {
        const BYTE* n = g_rnNode + 32 * k;
        short idx = *(const short*)(n + 12), prof = *(const short*)(n + 14);
        BYTE cnt = n[16];
        if ((DWORD)idx != h->rock[1] + k || prof < (short)h->rock[0] || (DWORD)prof >= h->rock[0] + h->ours[0] ||
            cnt > 7)
            return "a node's number, profile or segment count out of range";
        for (int j = 0; j < cnt; j++)
        {
            WORD sg = *(const WORD*)(n + 18 + 2 * j);
            if (sg < h->rock[2] || sg >= nseg)
                return "a node names a segment that is not ours";
        }
    }
    g_rnHead = h;
    return nullptr;
}

static void RoadNetStart()
{
    if (!g_rnEnabled)
    {
        Log("moving traffic off ([MovingTraffic] Enabled = 0)");
        return;
    }
    HANDLE f = CreateFileA(g_rnPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("moving traffic off: no road network file %s (tools/citymap/roadnet_build.py)", g_rnName);
        return;
    }
    g_rnSize = GetFileSize(f, nullptr);
    g_rnFile = (BYTE*)VirtualAlloc(nullptr, g_rnSize ? g_rnSize : 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    BOOL ok = g_rnFile && ReadFile(f, g_rnFile, g_rnSize, &got, nullptr) && got == g_rnSize;
    CloseHandle(f);
    const char* err = ok ? RoadNetParse() : "cannot be read";
    if (err)
    {
        Log("moving traffic off: the road network file %s: %s", g_rnName, err);
        return;
    }
    bool sites = true;
    for (const Site& s : kRnSites) sites &= BytesAre(s);
    if (!sites)
    {
        Log("WRONGBYTES in the moving traffic's sites: moving traffic off (the rest works)");
        return;
    }
    // the hooks: CheckRace's call and the posted speed (both only change anything for F-Town's segments)
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)&HkCheckRace - (kRnCheckSite + 5);
    BYTE speed[7] = {0xE8, 0, 0, 0, 0, 0xEB, 0x0B};  // call ours; jmp 0x41188F (the posted speed is in st0)
    *(DWORD*)(speed + 1) = (DWORD)(UINT_PTR)FtSpeedStub - (kRnSpeedSite + 5);
    if (!WriteCode(kRnCheckSite, call, 5) || !WriteCode(kRnSpeedSite, speed, 7))
    {
        Log("moving traffic off: the hook sites could not be written");
        return;
    }
    g_rnReady = true;
    const RnHead* h = g_rnHead;
    Log("moving traffic: road network %s: %lu profiles, %lu nodes, %lu segments, %lu roads after Rockport's %lu / %lu "
        "/ %lu / %lu; %lu grid cells (%lu segment tags) in %lu columns before Rockport's; %lu events marked; traffic "
        "level %d (events %s), driving on the %s, speeds x %.2f..%.2f a car",
        g_rnName, (unsigned long)h->ours[0], (unsigned long)h->ours[1], (unsigned long)h->ours[2],
        (unsigned long)h->ours[3], (unsigned long)h->rock[0], (unsigned long)h->rock[1], (unsigned long)h->rock[2],
        (unsigned long)h->rock[3], (unsigned long)h->cells, (unsigned long)h->tags, (unsigned long)h->padCols,
        (unsigned long)h->events, g_rnLevel, g_rnEventTraffic ? "too" : "none", g_rnLeft ? "LEFT (experiment)" : "right",
        1.0f - g_rnSpread, 1.0f + g_rnSpread);
}

// ---------------------------------------------------------------- installed state

static bool g_rnInstalled;
static void RnLinkFlags();
static const char* g_rnRejected;  // an install refused this session: the carriers get no traffic after it
static DWORD g_rnOrigPtr[4], g_rnOrigCount[4];  // profiles, nodes, segments, roads
static BYTE* g_rnMine[4];
static BYTE* g_rnMineOld[4];  // freed at the next install (nothing should read them; belt and braces)
static DWORD g_rnGrid, g_rnOldNodes, g_rnNewNodes, g_rnOldCols;
static float g_rnOldMinX;
static BYTE* g_rnNodeMem;  // our grid nodes
static DWORD g_rnNodeCount;
static OurNode** g_rnCellNode;  // per file cell (and per city-only cell after them): our node
struct RnRockCopy
{
    DWORD orig;  // Rockport's node (0: the cell had none)
    OurNode* copy;
};
static RnRockCopy g_rnRockCopy[4096];
static DWORD g_rnRockCopyCount;
static BYTE* g_rnRockMem;
static int g_rnEvent = -1;  // the event (g_events index) whose route is marked, or -1
static int g_rnRemarks;
static const DWORD kRecSize[4] = {64, 32, 22, 8};
static const DWORD kPtrs[4] = {kRnProfilesPtr, kRnNodesPtr, kRnSegmentsPtr, kRnRoadsPtr};
static const DWORD kCounts[4] = {kRnProfiles, kRnNodes, kRnSegments, kRnRoads};

static bool RoadNetInstalled()
{
    DWORD p = 0;
    return g_rnInstalled && ReadDword(kRnSegmentsPtr, &p) && p == (DWORD)(UINT_PTR)g_rnMine[2];
}

static DWORD SegIndexOf(const BYTE* seg)
{
    return (DWORD)((seg - g_rnMine[2]) / 22);
}

static bool OurSegment(int idx)
{
    return RoadNetInstalled() && idx >= (int)g_rnHead->rock[2] && idx < (int)(g_rnHead->rock[2] + g_rnHead->ours[2]);
}

// the cells our nodes stand in: the file's (road segments) and, merged in, the city's collision instances' cells
struct RnCellPlan
{
    DWORD cell, roads, roadFirst, inst, instFirst;
};
static RnCellPlan* g_rnPlan;
static DWORD g_rnPlanCount;
static DWORD* g_rnInstTags;  // the city's instance tags, cell by cell

static int CmpDword(const void* a, const void* b)
{
    DWORD x = *(const DWORD*)a, y = *(const DWORD*)b;
    return x < y ? -1 : x > y ? 1 : 0;
}

// The city's instances (g_city.inst) by widened cell: (cell << 0, tag) pairs, sorted by cell. False when a cell
// would hold more than 255 or an instance lies outside our columns.
static bool PlanCells(const char** why)
{
    const RnHead* h = g_rnHead;
    DWORD cols = h->gridCols + h->padCols;
    float minX = h->gridMinX - h->padCols * h->gridEdge, inv = 1.0f / h->gridEdge;
    DWORD pairsMax = 0;
    for (int i = 0; i < g_city.instCount; i++)
    {
        float r = g_city.inst[i].radius + (float)g_cellMargin;
        DWORD n = (DWORD)((2 * r) * inv + 2);
        pairsMax += n * n;
    }
    DWORD(*pairs)[2] = (DWORD(*)[2])calloc(pairsMax ? pairsMax : 1, 8);
    DWORD np = 0;
    for (int i = 0; i < g_city.instCount; i++)
    {
        const CollInst& ci = g_city.inst[i];
        float r = ci.radius + (float)g_cellMargin;
        long c0 = (long)floorf((ci.pos[0] - r - minX) * inv), c1 = (long)floorf((ci.pos[0] + r - minX) * inv);
        long r0 = (long)floorf((ci.pos[2] - r - h->gridMinZ) * inv), r1 = (long)floorf((ci.pos[2] + r - h->gridMinZ) * inv);
        if (c0 < 0 || c1 >= (long)h->padCols || r0 < 0 || r1 >= (long)h->gridRows)
        {
            free(pairs);
            *why = "a collision instance of the city outside the widened grid's new columns";
            return false;
        }
        for (long rr = r0; rr <= r1; rr++)
            for (long cc = c0; cc <= c1; cc++)
            {
                pairs[np][0] = (DWORD)rr * cols + (DWORD)cc;
                pairs[np][1] = ci.tag;
                np++;
            }
    }
    qsort(pairs, np, 8, CmpDword);  // by cell (the first word)
    // merge with the file's cells (sorted by cell)
    g_rnPlan = (RnCellPlan*)calloc(h->cells + np + 1, sizeof(RnCellPlan));
    g_rnInstTags = (DWORD*)calloc(np ? np : 1, 4);
    DWORD a = 0, b = 0, n = 0;
    while (a < h->cells || b < np)
    {
        DWORD cell = a < h->cells && (b >= np || g_rnCells[a].cell <= pairs[b][0]) ? g_rnCells[a].cell : pairs[b][0];
        RnCellPlan& p = g_rnPlan[n++];
        p.cell = cell;
        if (a < h->cells && g_rnCells[a].cell == cell)
        {
            p.roads = g_rnCells[a].count;
            p.roadFirst = g_rnCells[a].first;
            a++;
        }
        p.instFirst = b;
        while (b < np && pairs[b][0] == cell)
        {
            g_rnInstTags[b] = pairs[b][1];
            b++;
        }
        p.inst = b - p.instFirst;
        if (p.inst > 255)
        {
            free(pairs);
            *why = "a grid cell would hold more than 255 of the city's collision instances";
            return false;
        }
    }
    g_rnPlanCount = n;
    free(pairs);
    return true;
}

typedef void*(__cdecl* BMallocFn)(int, int);
typedef void(__cdecl* BFreeFn)(void*);

static bool Widen(const char** why)
{
    const RnHead* h = g_rnHead;
    DWORD grid = 0;
    BYTE g[0x24];
    if (!ReadDword(kGridPtr, &grid) || !grid || !SafeRead(grid, g, sizeof(g)))
    {
        *why = "the world grid cannot be read";
        return false;
    }
    float minX = *(float*)g, minZ = *(float*)(g + 8), edge = *(float*)(g + 0x10);
    DWORD rows = *(DWORD*)(g + 0x18), cols = *(DWORD*)(g + 0x1C), nodes = *(DWORD*)(g + 0x20);
    if (minX != h->gridMinX || minZ != h->gridMinZ || edge != h->gridEdge || rows != h->gridRows ||
        cols != h->gridCols || !nodes)
    {
        static char text[200];
        snprintf(text, sizeof(text), "the world grid (min %.1f, %.1f, edge %.1f, %lu x %lu) is not the one the file was "
                 "built for (%.1f, %.1f, %.1f, %lu x %lu)", minX, minZ, edge, (unsigned long)rows, (unsigned long)cols,
                 h->gridMinX, h->gridMinZ, h->gridEdge, (unsigned long)h->gridRows, (unsigned long)h->gridCols);
        *why = text;
        return false;
    }
    if (!g_rnPlan && !PlanCells(why))
        return false;
    DWORD ncols = cols + h->padCols;
    DWORD* fresh = (DWORD*)((BMallocFn)(UINT_PTR)kBMalloc)((int)(rows * ncols * 4), 0);
    if (!fresh)
    {
        *why = "bMalloc gave no memory for the widened cell array";
        return false;
    }
    memset(fresh, 0, rows * ncols * 4);
    for (DWORD r = 0; r < rows; r++)
        memcpy(fresh + r * ncols + h->padCols, (const DWORD*)(UINT_PTR)nodes + r * cols, cols * 4);
    DWORD bytes = 0;
    for (DWORD k = 0; k < g_rnPlanCount; k++) bytes += 0x14 + 4 * (g_rnPlan[k].inst + g_rnPlan[k].roads);
    g_rnNodeMem = (BYTE*)VirtualAlloc(nullptr, bytes ? bytes : 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_rnCellNode = (OurNode**)calloc(g_rnPlanCount ? g_rnPlanCount : 1, sizeof(OurNode*));
    if (!g_rnNodeMem || !g_rnCellNode)
    {
        ((BFreeFn)(UINT_PTR)kBFree)(fresh);
        *why = "no memory for our grid nodes";
        return false;
    }
    BYTE* at = g_rnNodeMem;
    for (DWORD k = 0; k < g_rnPlanCount; k++)
    {
        const RnCellPlan& p = g_rnPlan[k];
        OurNode* n = (OurNode*)at;
        memset(n, 0, sizeof(*n));
        n->index = (WORD)p.cell;
        n->counts[0] = 0;  // the city's instances count only while its packs are filed (RoadNetCityStatic)
        n->counts[3] = (BYTE)p.roads;
        n->offsets[0] = 0;
        n->offsets[3] = (WORD)(4 * p.inst);
        DWORD* tags = (DWORD*)(at + 0x14);
        memcpy(tags, g_rnInstTags + p.instFirst, 4 * p.inst);
        memcpy(tags + p.inst, g_rnTags + p.roadFirst, 4 * p.roads);
        fresh[p.cell] = (DWORD)(UINT_PTR)n;
        g_rnCellNode[k] = n;
        at += 0x14 + 4 * (p.inst + p.roads);
    }
    g_rnNodeCount = g_rnPlanCount;
    // the connector's cells in Rockport's own columns: a copy of Rockport's node (or a node of ours) with our road tags
    g_rnRockCopyCount = 0;
    if (h->rockCells)
    {
        DWORD rbytes = 0;
        for (DWORD k = 0; k < h->rockCells; k++) rbytes += 0x14 + 4 * (g_rnRockCells[k].count + 4 * 255);
        g_rnRockMem = (BYTE*)VirtualAlloc(nullptr, rbytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        BYTE* rat = g_rnRockMem;
        for (DWORD k = 0; rat && k < h->rockCells; k++)
        {
            const RnCell& c = g_rnRockCells[k];
            DWORD row = c.cell / cols, col = c.cell % cols, at = row * ncols + h->padCols + col;
            DWORD orig = fresh[at];
            BYTE head[0x14] = {0};
            if (orig && !SafeRead(orig, head, 0x14))
                continue;
            BYTE* counts = head + 8;
            WORD* offs = (WORD*)(head + 12);
            if (counts[3] + c.count > 255)
            {
                Log("moving traffic: the connection's cell %lu keeps Rockport's node: %u road tags + %lu > 255",
                    (unsigned long)c.cell, counts[3], (unsigned long)c.count);
                continue;
            }
            OurNode* n = (OurNode*)rat;
            memcpy(n, head, 0x14);  // review: the whole head (its +6 too), then counts and offsets ours
            if (!orig)
                n->index = (WORD)at;
            DWORD* tags = (DWORD*)(rat + 0x14);
            DWORD used = 0;
            bool read = true;
            for (int t = 0; t < 4; t++)
            {
                n->offsets[t] = (WORD)(4 * used);
                if (orig && counts[t] && !SafeRead(orig + 0x14 + offs[t], tags + used, 4 * counts[t]))
                    read = false;
                used += orig ? counts[t] : 0;
                n->counts[t] = orig ? counts[t] : 0;
            }
            if (!read)
            {
                Log("moving traffic: the connection's cell %lu keeps Rockport's node: its tags cannot be read",
                    (unsigned long)c.cell);
                continue;
            }
            memcpy(tags + used, g_rnRockTags + c.first, 4 * c.count);
            n->counts[3] = (BYTE)(n->counts[3] + c.count);
            used += c.count;
            fresh[at] = (DWORD)(UINT_PTR)n;
            g_rnRockCopy[g_rnRockCopyCount].orig = orig;
            g_rnRockCopy[g_rnRockCopyCount].copy = n;
            g_rnRockCopyCount++;
            rat += 0x14 + 4 * used;
        }
    }
    g_rnGrid = grid;
    g_rnOldNodes = nodes;
    g_rnOldCols = cols;
    g_rnOldMinX = minX;
    g_rnNewNodes = (DWORD)(UINT_PTR)fresh;
    float newMin = minX - h->padCols * edge;
    memcpy((void*)(UINT_PTR)(grid + 0x00), &newMin, 4);
    *(DWORD*)(UINT_PTR)(grid + 0x1C) = ncols;
    *(DWORD*)(UINT_PTR)(grid + 0x20) = g_rnNewNodes;
    return true;
}

static bool GridIsOurs()
{
    DWORD grid = 0, nodes = 0, cols = 0;
    return g_rnNewNodes && ReadDword(kGridPtr, &grid) && grid == g_rnGrid && ReadDword(grid + 0x20, &nodes) &&
           nodes == g_rnNewNodes && ReadDword(grid + 0x1C, &cols) && cols == g_rnOldCols + g_rnHead->padCols;
}

// Narrows the grid back: our nodes' lists (the barriers' dynamic entries made them) freed as WGrid::Shutdown frees
// a node's list when empty; Rockport's array, columns and min x back; our array to bFree.
static void Narrow(const char* why)
{
    if (!g_rnNewNodes)
        return;
    if (!GridIsOurs())
    {
        Log("moving traffic: the world grid is not the widened one any more (shut down or rebuilt: it took our array "
            "with it); nothing to narrow (%s)", why);
        g_rnNewNodes = 0;
        g_rnNodeMem = nullptr;  // the game may have run its Shutdown over our nodes: left as they are
        return;
    }
    int kept = 0, lists = 0, handed = 0, rockKept = 0;
    // the connection's copies of Rockport's nodes: their dynamic list (shared, or made while the copy stood there)
    // handed back to Rockport's node; a copy of an empty cell is one of ours
    for (DWORD k = 0; k < g_rnRockCopyCount; k++)
    {
        OurNode* n = g_rnRockCopy[k].copy;
        DWORD orig = g_rnRockCopy[k].orig;
        if (orig)
        {
            DWORD ol = 0;
            if (ReadDword(orig, &ol) && ol != n->list)
            {
                *(DWORD*)(UINT_PTR)orig = n->list;
                handed++;
            }
            continue;
        }
        if (!n->list)
            continue;
        DWORD size = 0;
        if (!ReadDword(n->list + 8, &size) || size)
        {
            rockKept++;
            continue;
        }
        ((ListDtorFn)(UINT_PTR)kListDtor)((void*)(UINT_PTR)n->list);
        ((FastFreeFn)(UINT_PTR)kFastMemFree)((void*)(UINT_PTR)kFastMem, (void*)(UINT_PTR)n->list, 0xC, nullptr);
        n->list = 0;
    }
    if (g_rnRockCopyCount)
        Log("moving traffic: the connection's %lu cells in Rockport's columns back (%d dynamic lists handed back to "
            "Rockport's nodes%s)", (unsigned long)g_rnRockCopyCount, handed,
            rockKept ? "; some of ours kept: the game's elements in them" : "");
    g_rnRockCopyCount = 0;
    if (!rockKept && g_rnRockMem)
        VirtualFree(g_rnRockMem, 0, MEM_RELEASE);
    g_rnRockMem = nullptr;
    for (DWORD k = 0; k < g_rnNodeCount; k++)
    {
        OurNode* n = g_rnCellNode[k];
        if (!n->list)
            continue;
        DWORD size = 0;
        if (!ReadDword(n->list + 8, &size) || size)
        {
            kept++;
            continue;
        }
        ((ListDtorFn)(UINT_PTR)kListDtor)((void*)(UINT_PTR)n->list);
        ((FastFreeFn)(UINT_PTR)kFastMemFree)((void*)(UINT_PTR)kFastMem, (void*)(UINT_PTR)n->list, 0xC, nullptr);
        n->list = 0;
        lists++;
    }
    memcpy((void*)(UINT_PTR)(g_rnGrid + 0x00), &g_rnOldMinX, 4);
    *(DWORD*)(UINT_PTR)(g_rnGrid + 0x1C) = g_rnOldCols;
    *(DWORD*)(UINT_PTR)(g_rnGrid + 0x20) = g_rnOldNodes;
    ((BFreeFn)(UINT_PTR)kBFree)((void*)(UINT_PTR)g_rnNewNodes);
    Log("moving traffic: grid narrowed back (%lu columns, min x %.1f): %d lists of our nodes freed%s (%s)",
        (unsigned long)g_rnOldCols, g_rnOldMinX, lists,
        kept ? "; some nodes kept (the game's elements in them: their memory stays)" : "", why);
    if (!kept)
        VirtualFree(g_rnNodeMem, 0, MEM_RELEASE);
    g_rnNodeMem = nullptr;
    g_rnNewNodes = 0;
}

// The city's collision instances counted in our nodes (their packs are filed now); false when the grid is not
// widened (the old dynamic registration then).
static bool RoadNetCityStatic(MapSet& m)
{
    if (!GridIsOurs())
        return false;
    int entries = 0, cells = 0, mx = 0;
    for (DWORD k = 0; k < g_rnNodeCount; k++)
        if (g_rnPlan[k].inst)
        {
            g_rnCellNode[k]->counts[0] = (BYTE)g_rnPlan[k].inst;
            entries += g_rnPlan[k].inst;
            cells++;
            if ((int)g_rnPlan[k].inst > mx)
                mx = g_rnPlan[k].inst;
        }
    m.regCount = entries;
    m.cellsTouched = cells;
    m.madeCount = 0;
    m.tagsMax = mx;
    m.tagsMedian = 0;
    m.staticReg = true;
    return true;
}

static void RoadNetCityUnstatic(MapSet& m, const char* why)
{
    m.staticReg = false;
    if (!GridIsOurs())
    {
        Log("grid: the world grid is not the widened one any more; nothing to remove (%s)", why);
        return;
    }
    for (DWORD k = 0; k < g_rnNodeCount; k++) g_rnCellNode[k]->counts[0] = 0;
    Log("grid: the city's %d static entries taken out of our nodes (%s)", m.regCount, why);
    m.regCount = 0;
}

static void UnmarkEvent();
static const WORD kNoTrafficFlag = 2;

// The connection's segments: NoTraffic while not joined (no AI towards a connector whose collision is not there), the
// file's own flag while joined.
static void RnLinkFlags()
{
    if (!g_rnInstalled || !g_rnLinks)
        return;
    const RnHead* h = g_rnHead;
    for (DWORD k = 0; k < h->links; k++)
    {
        DWORD seg = g_rnLinks[k];
        WORD* f = (WORD*)(g_rnMine[2] + 22 * seg + 10);
        WORD file = *(const WORD*)(g_rnSeg + 22 * (seg - h->rock[2]) + 10);
        *f = g_rnJoined ? (WORD)((*f & ~kNoTrafficFlag) | (file & kNoTrafficFlag)) : (WORD)(*f | kNoTrafficFlag);
    }
}

// The join at Rockport's T (FTownConnect.h): our copy of each mouth's record gets the join's segment in its next slot
// (only when every record is as the file says), or Rockport's own record back. True when the state is the one asked.
static bool RoadNetJoin(bool on, const char* why)
{
    if (!RoadNetInstalled() || !g_rnHead->joins)
        return false;
    if (on == g_rnJoined)
        return true;
    const RnHead* h = g_rnHead;
    if (on)
    {
        for (DWORD k = 0; k < h->joins; k++)
        {
            const RnJoin& j = g_rnJoins[k];
            const BYTE* n = g_rnMine[1] + 32 * j.node;
            bool same = n[16] == j.count && !memcmp(n + 18, j.before, 2 * j.count);
            if (!same)
            {
                Log("connection: JOIN REFUSED: Rockport's node %u has %u segments (%u %u %u ...), the file was built "
                    "with %u (%u %u %u ...): another Rockport; the connector stays NoTraffic", j.node, n[16],
                    *(const WORD*)(n + 18), *(const WORD*)(n + 20), *(const WORD*)(n + 22), j.count, j.before[0],
                    j.before[1], j.before[2]);
                return false;
            }
        }
        for (DWORD k = 0; k < h->joins; k++)
        {
            const RnJoin& j = g_rnJoins[k];
            BYTE* n = g_rnMine[1] + 32 * j.node;
            *(WORD*)(n + 18 + 2 * n[16]) = j.added;
            n[16]++;
        }
    }
    else
        for (DWORD k = 0; k < h->joins; k++)  // Rockport's own record (the game never writes a node record)
            memcpy(g_rnMine[1] + 32 * g_rnJoins[k].node, (const void*)(UINT_PTR)(g_rnOrigPtr[1] + 32 * g_rnJoins[k].node),
                   32);
    g_rnJoined = on;
    RnLinkFlags();
    Log("connection: road network %s at Rockport's junction (%lu mouths, %lu link segments %s) (%s)",
        on ? "JOINED" : "unjoined", (unsigned long)h->joins, (unsigned long)h->links,
        on ? "open to traffic" : "NoTraffic", why);
    return true;
}

// Rockport's arrays copied, ours after them, the game's pointers and counts ours; the grid widened. Before the
// city's chunks are loaded (their collision goes into our nodes). False: nothing changed.
static bool RoadNetPrepare()
{
    if (!g_rnReady || RoadNetInstalled())
        return g_rnReady;
    const RnHead* h = g_rnHead;
    DWORD ptr[4], cnt[4];
    for (int k = 0; k < 4; k++)
        if (!ReadDword(kPtrs[k], &ptr[k]) || !ReadDword(kCounts[k], &cnt[k]) || !ptr[k])
        {
            g_rnRejected = "not installed: see the NOT INSTALLED line";
            Log("moving traffic: NOT INSTALLED: the game's road network is not there (no pointer at 0x%08lX)",
                (unsigned long)kPtrs[k]);
            return false;
        }
    if (cnt[0] != h->rock[0] || cnt[1] != h->rock[1] || cnt[2] != h->rock[2] || cnt[3] != h->rock[3])
    {
        g_rnRejected = "not installed: see the NOT INSTALLED line";
        Log("moving traffic: NOT INSTALLED: the game's network has %lu profiles, %lu nodes, %lu segments, %lu roads; the "
            "file was built after %lu / %lu / %lu / %lu", (unsigned long)cnt[0], (unsigned long)cnt[1],
            (unsigned long)cnt[2], (unsigned long)cnt[3], (unsigned long)h->rock[0], (unsigned long)h->rock[1],
            (unsigned long)h->rock[2], (unsigned long)h->rock[3]);
        return false;
    }
    const char* why = nullptr;
    double t0 = NowMs();
    if (!Widen(&why))
    {
        g_rnRejected = "not installed: see the NOT INSTALLED line";
        Log("moving traffic: NOT INSTALLED: %s", why);
        return false;
    }
    for (int k = 0; k < 4; k++)
        if (g_rnMineOld[k])
        {
            VirtualFree(g_rnMineOld[k], 0, MEM_RELEASE);
            g_rnMineOld[k] = nullptr;
        }
    const BYTE* ours[4] = {g_rnProf, g_rnNode, g_rnSeg, g_rnRoad};
    for (int k = 0; k < 4; k++)
    {
        DWORD rock = cnt[k] * kRecSize[k], add = h->ours[k] * kRecSize[k];
        g_rnMine[k] = (BYTE*)VirtualAlloc(nullptr, rock + add, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!g_rnMine[k] || !SafeRead(ptr[k], g_rnMine[k], rock))
        {
            for (int j = 0; j <= k; j++)
                if (g_rnMine[j])
                    VirtualFree(g_rnMine[j], 0, MEM_RELEASE), g_rnMine[j] = nullptr;
            Narrow("no memory for the network");
            g_rnRejected = "not installed: see the NOT INSTALLED line";
            Log("moving traffic: NOT INSTALLED: no memory for the network (or Rockport's cannot be read)");
            return false;
        }
        memcpy(g_rnMine[k] + rock, ours[k], add);
    }
    if (g_rnLeft)  // the experiment: every lane offset of ours negated (forward lanes left of the centre line)
        for (DWORD p = 0; p < h->ours[0]; p++)
        {
            BYTE* prof = g_rnMine[0] + (cnt[0] + p) * 64;
            for (int z = 0; z < prof[0] && z < 15; z++)
            {
                DWORD* w = (DWORD*)(prof + 4 + 4 * z);
                int off = (int)(*w << 0) >> 18;  // the 14-bit signed offset (bits 18..31)
                *w = (*w & 0x3FFFF) | ((DWORD)(-off & 0x3FFF) << 18);
            }
        }
    for (int k = 0; k < 4; k++)
    {
        g_rnOrigPtr[k] = ptr[k];
        g_rnOrigCount[k] = cnt[k];
        *(DWORD*)(UINT_PTR)kPtrs[k] = (DWORD)(UINT_PTR)g_rnMine[k];
        *(DWORD*)(UINT_PTR)kCounts[k] = cnt[k] + h->ours[k];
    }
    g_rnInstalled = true;
    g_rnJoined = false;
    RnLinkFlags();
    g_rnEvent = -1;
    g_rnRemarks = 0;
    Log("moving traffic: INSTALLED in %.2f ms: the network %lu profiles, %lu nodes, %lu segments, %lu roads (Rockport's "
        "first, as they were); the grid %lu columns from min x %.1f (%lu cells of ours, %lu with the city's collision)",
        NowMs() - t0, (unsigned long)(cnt[0] + h->ours[0]), (unsigned long)(cnt[1] + h->ours[1]),
        (unsigned long)(cnt[2] + h->ours[2]), (unsigned long)(cnt[3] + h->ours[3]),
        (unsigned long)(g_rnOldCols + h->padCols), g_rnOldMinX - h->padCols * h->gridEdge,
        (unsigned long)g_rnNodeCount, (unsigned long)[] {
            DWORD n = 0;
            for (DWORD k = 0; k < g_rnPlanCount; k++) n += g_rnPlan[k].inst != 0;
            return n;
        }());
    return true;
}

// Rockport's network back (its records copied back from our list: the flags the game set meanwhile kept), the
// pointers and counts the game's again; the grid narrowed. Before the track unloads (or when a load failed).
static void RoadNetRestore(const char* why)
{
    if (!g_rnInstalled)
        return;
    UnmarkEvent();
    if (RoadNetInstalled())
    {
        RoadNetJoin(false, why);  // Rockport's mouths as the game had them before they are copied back
        for (int k = 0; k < 4; k++)
        {
            memcpy((void*)(UINT_PTR)g_rnOrigPtr[k], g_rnMine[k], g_rnOrigCount[k] * kRecSize[k]);
            *(DWORD*)(UINT_PTR)kPtrs[k] = g_rnOrigPtr[k];
            *(DWORD*)(UINT_PTR)kCounts[k] = g_rnOrigCount[k];
        }
        Log("moving traffic: Rockport's road network back (%lu segments; %d re-marks of an event's route) (%s)",
            (unsigned long)g_rnOrigCount[2], g_rnRemarks, why);
    }
    else
        Log("moving traffic: the game's road network is not ours any more (the track was set up again); left as it is "
            "(%s)", why);
    for (int k = 0; k < 4; k++)
    {
        g_rnMineOld[k] = g_rnMine[k];  // freed at the next install
        g_rnMine[k] = nullptr;
    }
    g_rnInstalled = false;
    Narrow(why);
}

// ---------------------------------------------------------------- the events' routes

static void SetFlags(DWORD seg, WORD set, WORD clear)
{
    WORD* f = (WORD*)(g_rnMine[2] + 22 * seg + 10);
    *f = (WORD)((*f & ~clear) | set);
}

static int FileEvent(int k)
{
    if (k < 0 || k >= g_eventCount)
        return -1;
    for (DWORD e = 0; e < g_rnHead->events; e++)
        if (!strncmp(g_rnEvents[e].id, g_events[k].id, 15))
            return (int)e;
    return -1;
}

static const WORD kInRace = 0x8000, kRaceForward = 4, kNoTraffic = 2;

static void MarkEvent(int k, bool again)
{
    int e = FileEvent(k);
    if (e < 0)
    {
        if (!again)
            Log("moving traffic: %s has no route in %s: no traffic on it", g_events[k].title, g_rnName);
        g_rnEvent = k;
        return;
    }
    const RnEvent& ev = g_rnEvents[e];
    int route = 0, exits = 0;
    for (DWORD m = 0; m < ev.count; m++)
    {
        DWORD v = g_rnMarks[ev.first + m], seg = v & 0xFFFF;
        if (v & 0x20000)
            SetFlags(seg, kNoTraffic, 0), exits++;
        else
            SetFlags(seg, (WORD)(kInRace | ((v & 0x10000) ? kRaceForward : 0)), (v & 0x10000) ? 0 : kRaceForward),
                route++;
    }
    g_rnEvent = k;
    if (again)
        g_rnRemarks++;
    Log("moving traffic: %s's route %s: %d segments InRace, %d exits NoTraffic%s", g_events[k].title,
        again ? "marked again (the game cleared the race marks)" : "marked", route, exits,
        g_rnEventTraffic ? "" : " (EventTraffic = 0: the carrier has no traffic)");
}

static void UnmarkEvent()
{
    if (g_rnEvent < 0 || !RoadNetInstalled())
    {
        g_rnEvent = -1;
        return;
    }
    // every segment of ours gets the file's own flags back (the game sets none on ours but the race marks)
    const RnHead* h = g_rnHead;
    for (DWORD s = 0; s < h->ours[2]; s++)
        *(WORD*)(g_rnMine[2] + 22 * (h->rock[2] + s) + 10) = *(const WORD*)(g_rnSeg + 22 * s + 10);
    RnLinkFlags();
    Log("moving traffic: %s's route marks cleared", g_events[g_rnEvent].title);
    g_rnEvent = -1;
}

// the first route segment of the marked event (to see whether the game cleared the marks)
static int MarkedSentinel()
{
    int e = FileEvent(g_rnEvent);
    if (e < 0)
        return -1;
    const RnEvent& ev = g_rnEvents[e];
    for (DWORD m = 0; m < ev.count; m++)
        if (!(g_rnMarks[ev.first + m] & 0x20000))
            return (int)(g_rnMarks[ev.first + m] & 0xFFFF);
    return -1;
}

static void RoadNetFrame()
{
    if (!RoadNetInstalled())
        return;
    int want = (g_ta == TA_ARMED || g_ta == TA_COUNTDOWN || g_ta == TA_RUNNING) ? g_ev : -1;
    if (want != g_rnEvent)
    {
        UnmarkEvent();
        if (want >= 0)
            MarkEvent(want, false);
        return;
    }
    int s = g_rnEvent >= 0 ? MarkedSentinel() : -1;
    if (s >= 0 && !(*(WORD*)(g_rnMine[2] + 22 * s + 10) & kInRace))
        MarkEvent(g_rnEvent, true);  // ResetRaceSegments (a restart) cleared every segment's InRace
}

// ---------------------------------------------------------------- the game's calls

// AITrafficManager::CheckRace's call in FindSpawnPoint (thiscall, the nav pushed, ret 4)
static bool __fastcall HkCheckRace(void* mgr, void*, const BYTE* nav)
{
    short seg = *(const short*)(nav + 0x8E);
    if (OurSegment(seg) && g_rnEvent < 0)
        return true;  // Free Roam (no event running): every road of F-Town
    return ((bool(__thiscall*)(void*, const BYTE*))(UINT_PTR)kRnCheckRace)(mgr, nav);
}

// ComputeSpeed's posted speed (metres a second): ours on F-Town's segments, the game's rule elsewhere
extern "C" float __cdecl FtPostedSpeed(const BYTE* seg, const BYTE* action)
{
    DWORD idx = RoadNetInstalled() ? SegIndexOf(seg) : 0;
    if (RoadNetInstalled() && seg >= g_rnMine[2] && OurSegment((int)idx))
    {
        float kmh = g_rnKmh[idx - g_rnHead->rock[2]];
        if (kmh < 5.0f)
            kmh = 35.0f;
        DWORD x = (DWORD)(UINT_PTR)action;
        x ^= x >> 15;
        x *= 0x2C1B3C6Du;
        x ^= x >> 12;
        float f = 1.0f + g_rnSpread * (2.0f * (float)(x & 0xFFFF) / 65535.0f - 1.0f);
        return kmh / 3.6f * f;
    }
    DWORD net = 0;
    ReadDword(kRnNetwork, &net);
    int lanes = ((int(__thiscall*)(void*, const BYTE*))(UINT_PTR)kRnLanes)((void*)(UINT_PTR)net, seg);
    return lanes >= 4 ? *(const float*)(action + 0x54) : *(const float*)(action + 0x50);
}

// called at 0x41187D with the segment pushed (the game's push edi) and the action in esi: the posted speed in st0
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _FtSpeedStub\n"
        "_FtSpeedStub:\n"
        "  push esi\n"
        "  push dword ptr [esp + 8]\n"
        "  call _FtPostedSpeed\n"
        "  add esp, 8\n"
        "  ret 4\n"
        ".att_syntax prefix\n");

// the carrier race's traffic setting (RaceSettings +0xA: 1, 2, 3 = 10, 30, 50 % density, FillCustomRace 0x56DD82)
static int RoadNetTrafficLevel(int mode)
{
    if (!g_rnReady)
        return 0;
    // the review: no traffic when the network will not (or did not) go in: an install refused this session, or the
    // game's network still in place from the last track not the one the file was built after
    if (g_rnRejected)
    {
        Log("moving traffic: no traffic for the carrier: the network was refused earlier (%s)", g_rnRejected);
        return 0;
    }
    DWORD cnt[4] = {0, 0, 0, 0};
    bool read = true;
    for (int k = 0; k < 4; k++) read &= ReadDword(kCounts[k], &cnt[k]);
    if (read && !RoadNetInstalled() && (cnt[0] || cnt[1] || cnt[2] || cnt[3]) &&
        (cnt[0] != g_rnHead->rock[0] || cnt[1] != g_rnHead->rock[1] || cnt[2] != g_rnHead->rock[2] ||
         cnt[3] != g_rnHead->rock[3]))
    {
        Log("moving traffic: no traffic for the carrier: the game's network has %lu profiles, %lu nodes, %lu segments, "
            "%lu roads; the file was built after %lu / %lu / %lu / %lu", (unsigned long)cnt[0], (unsigned long)cnt[1],
            (unsigned long)cnt[2], (unsigned long)cnt[3], (unsigned long)g_rnHead->rock[0],
            (unsigned long)g_rnHead->rock[1], (unsigned long)g_rnHead->rock[2], (unsigned long)g_rnHead->rock[3]);
        return 0;
    }
    if (IsEventMode(mode) && !g_rnEventTraffic)
        return 0;
    return g_rnLevel;
}

// a parked car's spot with moving traffic installed: only kerb spots the file keeps (a side with two lanes)
static bool RoadNetSpotOk(int spot)
{
    if (!RoadNetInstalled())
        return true;
    if (!g_rnPark || g_rnHead->spots != (DWORD)g_tspCount)
        return g_tsp[spot].kind == 0;  // the file's list is for another spots file: kerb spots, no lane spots
    return spot >= 0 && spot < (int)g_rnHead->parking && g_rnPark[spot] != 0;
}
