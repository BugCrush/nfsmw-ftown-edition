// FTownConnect.h - the road between Rockport and F-Town in the career's free roam (docs/ftown-connection-research.md
// "The connection: decisions" C1-C7; plan docs/superpowers/plans/2026-11-06-ftown-rockport-connection.md Task 5).
// Included once by FTownLoader.cpp after FTownSmack.h, sharing its helpers (Log, SafeRead, the sets, LoadCity, Unload,
// the minimap, moving traffic's network).
//
// Only while the player exists and GRaceStatus ([0x91E000]) says free roam (play mode +0x1960 = 0, as
// MenuZoneTrigger::ShouldSeeMenuZoneCluster 0x569010 reads it); never in the Bonus Maps' carrier race or a career race.
// - On, when the car comes within the data's on-radius (1,500 m) of Rockport's T: moving traffic's network appended and
//   the grid widened (RoadNetPrepare), the connector's file (one scenery section Z1 = 2601, one collision pack 2601)
//   loaded and its collision registered, the zones swapped in (below), the network joined at the T (RoadNetJoin), the
//   walls opened (below).
// - The zones: Rockport's G26 and G23 records in the DrivableSectionList (VisibleSectionManager 0x9A3B50 + 0x10;
//   bTNode next/prev at +0/+4) are replaced by ours (same number and boundary, 72 slots) listing G3's sections, their
//   own and F-Town's, so the streamer and the drawing keep Rockport's junction in the valley; our zone B26 (a boundary
//   in the DrivableBoundaryList 0x9A3B50 + 0, a record in the section list) from G23's top edge to F-Town's box,
//   listing the same. The streamer reads a zone's record by number (0x72DE81..0x72DED1): a zone with no record there is
//   a null read, so B26 is taken out only while neither streaming position's CurrentZone (TrackStreamer 0x9AA9D0 +
//   0xDE, + 0x142) is ours; at the track's unload it is left linked (static memory) for the game's own unloader.
// - The walls: Rockport's wall across the T's north side (pack 703) and F-Town's edge pieces at Mathura Road (the
//   city's packs): every barrier lying on the data's segment is SUNK: both its points' heights (local y at barrier +
//   0x04 and + 0x14) set to kSunkY, 100 km under the world, the old heights kept. The game's barrier tests all ask
//   for the collider's height inside the barrier's (GetBarrierList 0x7844F0: y + r > YBot and y - r <= YTop;
//   GetClosestIntersectingBarrier 0x773170 and GetBarrierNormal: the crossing point's y between them), so no vehicle
//   collects it any more. (Run L, 2026-11-06: the first opening, 0xC0 in the surface flags byte at barrier + 0x0D as
//   SetExclusionFlags(pack) 0x76C6A0 sets on grouped walls, is an EXCLUSION mask: a collider skips the barrier only
//   when its own mask shares a bit, and PVehicle::LoadBehaviors 0x685240 gives the player 0 (DRIVER_HUMAN), racers
//   and remote cars 0, traffic 0x40, cops 0x80: traffic and cops went through, the player stopped.) Counted against
//   the data first (else none is sunk: another Rockport); sunk again whenever the streamer loads the pack again (a
//   new object in mCollisionPackList); put back while the same object is there. Then every collider's cache cleared
//   with the game's own loop (0x782C81: WCollider::Clear 0x782A30 and +0x80 = 0: the cached barrier lists hold
//   copies), never SetExclusionFlags() 0x782C60, which would turn off every grouped wall the career has switched on.
// - The ramp's faces (FTCN version 2, docs/ftown-race-notes.md "The connector ramp"): Rockport's road faces under
//   our ramp at the T carry no flag 4 and come before ours in a grid node's list (static entries first,
//   WGridNode::iterator), so WWorldPos::FindClosestFace (0x779170) would stop at the road under the ramp. Every face of
//   the region's pack (pack 703) with its centre within the region's heights and a vertex or its centre within `half`
//   of the region's axis gets 4 in its flags byte (the high byte of the strip word of the triangle's last vertex: the
//   WCollisionTri +0x2D the game tests); counted against the data first; the same lifecycle as the walls.
// - F-Town in: when the car is in G26, G23, our zone or F-Town's box (LoadCity: the chunks and their collision; the
//   minimap's pack); out when the car has been 15 s in another zone, outside the box and more than the near-radius
//   (300 m) from the T. No parked cars in the career (FTownTraffic.h asks g_lnCareer).
// - Off when not roaming or 15 s more than the off-radius (2,500 m) from the T, the car not on the connection: walls
//   back, the join undone, the zones back, the connector out. Moving traffic's network stays until the track unloads
//   (as in races: AI may hold its numbers).

static const DWORD kRaceStatusPtr = 0x91E000, kPlayModeAt = 0x1960;
static const DWORD kVsmBoundaries = 0x9A3B50, kVsmSections = 0x9A3B60, kFindDrivable = 0x72CA00;
static const DWORD kStreamerZones[2] = {0x9AA9D0 + 0xDE, 0x9AA9D0 + 0xDE + 0x64};
static const DWORD kColliderArray = 0x9B3C84, kColliderCount = 0x9B3C8C, kColliderClear = 0x782A30;

static const Site kLinkSites[] = {
    {0x569010, {0x8B, 0x0D, 0x00, 0xE0, 0x91, 0x00, 0x8B, 0x91, 0x60, 0x19, 0x00, 0x00}, 12,
     "MenuZoneTrigger::ShouldSeeMenuZoneCluster: GRaceStatus [0x91E000], play mode +0x1960"},
    {0x72CA00, {0x51, 0x53, 0x55, 0x8B, 0x6C, 0x24, 0x10, 0x8D, 0x59, 0x10}, 10,
     "VisibleSectionManager::FindDrivableSection(point): the section list at this + 0x10"},
    {0x72DE25, {0x8D, 0x95, 0xDE, 0x00, 0x00, 0x00}, 6, "DetermineStreamingSections: CurrentZone at TrackStreamer + 0xDE"},
    {0x72DE81, {0x8B, 0x0D, 0x60, 0x3B, 0x9A, 0x00}, 6,
     "DetermineStreamingSections: a zone with no loading section: the drivable list 0x9A3B60"},
    {0x72DE96, {0x66, 0x39, 0x51, 0x0C}, 4, "DetermineStreamingSections: the record's number at +0x0C"},
    {0x72DEA8, {0x0F, 0xBF, 0x51, 0x10}, 4, "DetermineStreamingSections: the record's visible count at +0x10"},
    {0x76C6BC, {0x66, 0x39, 0x51, 0x18}, 4, "SetExclusionFlags(pack): the instance's group at +0x18"},
    {0x76C6C7, {0x8B, 0x41, 0x1C}, 3, "SetExclusionFlags(pack): the instance's article at +0x1C"},
    {0x76C6E0, {0x0F, 0xB7, 0x70, 0x02}, 4, "SetExclusionFlags(pack): the article's strips size at +0x02"},
    {0x7845C4, {0x8A, 0x55, 0x0D, 0x84, 0x10}, 5,
     "GetBarrierList 0x7844F0: the exclusion test, [barrier + 0x0D] & the collider's mask"},
    {0x7845EE, {0xD9, 0x45, 0x04, 0xD8, 0x5D, 0x14}, 6,
     "GetBarrierList: the barrier's heights at +0x04 and +0x14 (the collider's y must be between them)"},
    {0x7731CA, {0xD9, 0x47, 0x04, 0xD8, 0x5F, 0x14}, 6,
     "GetClosestIntersectingBarrier: the crossing's y between the heights at +0x04 and +0x14"},
    {0x782C81,
     {0x8B, 0x35, 0x84, 0x3C, 0x9B, 0x00, 0x8B, 0x15, 0x8C, 0x3C, 0x9B, 0x00, 0x8D, 0x3C, 0x96, 0x3B, 0xF7, 0x74, 0x17,
      0x8B, 0x0E, 0xE8, 0x95, 0xFD, 0xFF, 0xFF, 0x8B, 0x06, 0x83, 0xC6, 0x04, 0x3B, 0xF7, 0xC6, 0x80, 0x80, 0x00, 0x00,
      0x00, 0x00},
     40, "InvalidateAllCachedData (inlined): the colliders [0x9B3C84] x [0x9B3C8C], WCollider::Clear, +0x80 = 0"},
};

// ---------------------------------------------------------------- the data (tools/citymap/connector.py)

#pragma pack(push, 1)
struct LnHead
{
    char magic[4];
    DWORD version;
    float junction[3];
    float onRadius, offRadius, nearRadius;
    float box[4];
    WORD source, ours, adjoin, subCount, subs[2];
    WORD sourceCount, extraCount, pointCount, wallCount;
    DWORD bunSize;
};
struct LnWall
{
    WORD pack, expect;
    float x0, y0, x1, y1, zLow, zHigh;
};
struct LnFaces
{
    WORD pack, expect;
    float x0, y0, x1, y1, half, zLow, zHigh;
};
// the game's records (VisibleSection.hpp): a drivable section 0xA4 bytes, a boundary 0x24 + 8 a point
struct DrvRec
{
    DWORD next, prev, boundary;
    short number;
    signed char most, max;
    short count;
    short vis[72];
    short pad;
};
struct BndRec
{
    DWORD next, prev;
    short number;
    signed char points, panorama;
    float bmin[2], bmax[2], centre[2];
    float pts[16][2];
};
#pragma pack(pop)
static_assert(sizeof(DrvRec) == 0xA4 && sizeof(BndRec) == 0xA4, "the game's record sizes");

static bool g_lnEnabled = true, g_lnReady, g_lnRefused;
static char g_lnDataName[MAX_PATH], g_lnDataPath[MAX_PATH];
static LnHead g_ln;
static short g_lnSrc[72], g_lnExtra[72];
static float g_lnPts[16][2];
static LnWall g_lnWalls[8];
static const int kLnFaceRegions = 4, kLnFacesMax = 1024;
static LnFaces g_lnFaces[kLnFaceRegions];
static DWORD g_lnFaceCount;
static MapSet g_lnSet = {"FTOWNLNK", "connection: "};

// state
static bool g_lnOn, g_lnZones, g_lnOursLinked;
static DrvRec g_lnOurRec, g_lnSubRec[2];
static BndRec g_lnOurBnd;
static DWORD g_lnOrigRec[2];
struct LnFlag
{
    DWORD addr;
    BYTE old;
};
struct LnSunk  // a barrier sunk out of reach: its address and its two points' heights as they were
{
    DWORD bar;
    float y0, y1;
};
static const float kSunkY = -100000.0f;  // local y: 100 km under every collider (the barrier tests, above)
static LnSunk g_lnFlags[8][64];
static int g_lnFlagCount[8];
static DWORD g_lnFlagObj[8];  // the pack object (Rockport's) or city buffer each wall's barriers were sunk in
static bool g_lnMaskLogged;
static LnFlag g_lnFaceFlags[kLnFaceRegions][kLnFacesMax];
static int g_lnFaceFlagCount[kLnFaceRegions];
static DWORD g_lnFaceObj[kLnFaceRegions];  // the pack object each region's flags were set in
static float g_lnFarSince = -1, g_lnCityOutSince = -1;  // simulation seconds (paused: no time passes)
static const float kLinkWait = 15.0f;
static int g_lnLastZone = -1;
static bool g_lnTrackGone;
static bool g_lnCityFailed;  // F-Town's load failed this track  // the track unloaded: nothing until the player is found again (the next track's)

static void LinkSettings(const char* dir)
{
    g_lnEnabled = GetPrivateProfileIntA("Connection", "Enabled", 1, g_iniPath) == 1;
    GetPrivateProfileStringA("Connection", "File", "ftown-connector.bun", g_lnSet.name, sizeof(g_lnSet.name),
                             g_iniPath);
    snprintf(g_lnSet.path, sizeof(g_lnSet.path), "%s%s", dir, g_lnSet.name);
    GetPrivateProfileStringA("Connection", "Data", "ftown-connect.bin", g_lnDataName, sizeof(g_lnDataName),
                             g_iniPath);
    snprintf(g_lnDataPath, sizeof(g_lnDataPath), "%s%s", dir, g_lnDataName);
}

static const char* LinkParse(const BYTE* d, DWORD n)
{
    if (n < sizeof(LnHead))
        return "shorter than its header";
    memcpy(&g_ln, d, sizeof(LnHead));
    const LnHead& h = g_ln;
    if (memcmp(h.magic, "FTCN", 4) || h.version != 2)
        return "not an FTCN version 2 file (tools/citymap/connector.py: the ramp's face regions)";
    if (h.subCount != 2 || h.sourceCount > 68 || h.extraCount > 40 || h.pointCount < 3 || h.pointCount > 16 ||
        h.wallCount > 8)
        return "its counts out of range";
    if (h.subs[1] != h.adjoin)
        return "the second zone swapped is not the one our zone adjoins";
    DWORD o = sizeof(LnHead);
    DWORD need = o + 2u * (h.sourceCount + h.extraCount);
    need += (4 - need % 4) % 4;
    need += 8u * h.pointCount + sizeof(LnWall) * h.wallCount;
    if (need + 4 > n)
        return "its size is not what its counts give";
    memcpy(&g_lnFaceCount, d + need, 4);
    if (g_lnFaceCount > (DWORD)kLnFaceRegions)
        return "more than 4 face regions";
    if (need + 4 + sizeof(LnFaces) * g_lnFaceCount != n)
        return "its size is not what its counts give";
    memcpy(g_lnFaces, d + need + 4, sizeof(LnFaces) * g_lnFaceCount);
    for (DWORD f = 0; f < g_lnFaceCount; f++)
        if (g_lnFaces[f].pack == 0 || g_lnFaces[f].pack >= kPackMax || g_lnFaces[f].expect > kLnFacesMax ||
            !(g_lnFaces[f].half > 0))
            return "a face region out of range (pack 0, more than 1,024 faces or no reach)";
    memcpy(g_lnSrc, d + o, 2u * h.sourceCount);
    o += 2u * h.sourceCount;
    memcpy(g_lnExtra, d + o, 2u * h.extraCount);
    o += 2u * h.extraCount;
    o += (4 - o % 4) % 4;
    memcpy(g_lnPts, d + o, 8u * h.pointCount);
    o += 8u * h.pointCount;
    memcpy(g_lnWalls, d + o, sizeof(LnWall) * h.wallCount);
    for (int w = 0; w < h.wallCount; w++)
        if (g_lnWalls[w].expect > 64)
            return "a wall of more than 64 barriers (the flags kept to put back)";
    if (h.ours < 101 || h.ours >= 2100 || (h.ours % 100) < 1 || (h.ours % 100) > 39)
        return "our zone's number is not a drivable number (A..T, 1..39)";
    for (int k = 0; k < h.sourceCount + h.extraCount; k++)
    {
        int v = k < h.sourceCount ? g_lnSrc[k] : g_lnExtra[k - h.sourceCount];
        if (v <= 0 || v >= kUserInfoMax)
            return "a section number out of range";
    }
    if (!(h.onRadius > 0 && h.offRadius > h.onRadius && h.nearRadius > 0))
        return "its radii out of order";
    return nullptr;
}

static void LinkStart()
{
    if (!g_lnEnabled)
    {
        Log("connection off ([Connection] Enabled = 0)");
        return;
    }
    HANDLE f = CreateFileA(g_lnDataPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("connection off: no data file %s (tools/citymap/connector.py)", g_lnDataName);
        return;
    }
    bool sites = true;
    for (const Site& s : kLinkSites) sites &= BytesAre(s);
    if (!sites)
    {
        CloseHandle(f);
        Log("WRONGBYTES in the connection's sites: connection off (the rest works)");
        return;
    }
    BYTE buf[4096];
    DWORD got = 0, size = GetFileSize(f, nullptr);
    BOOL ok = size <= sizeof(buf) && ReadFile(f, buf, size, &got, nullptr) && got == size;
    CloseHandle(f);
    const char* err = ok ? LinkParse(buf, size) : "cannot be read (or longer than 4 KB)";
    if (err)
    {
        Log("connection off: the data file %s: %s", g_lnDataName, err);
        return;
    }
    if (!ReadMapFile(g_lnSet))
    {
        Log("connection off: the connector's file %s", g_lnSet.name);
        return;
    }
    if (g_lnSet.size != g_ln.bunSize)
    {
        Log("connection off: %s has %lu bytes, the data was built with one of %lu (rebuild both: "
            "tools/citymap/connector.py)", g_lnSet.name, (unsigned long)g_lnSet.size, (unsigned long)g_ln.bunSize);
        return;
    }
    g_lnReady = true;
    Log("connection: %s and %s: the junction at render (%.1f, %.1f, %.1f); on within %.0f m in free roam, off beyond "
        "%.0f m; zones %u/%u swapped, ours %u after %u; %u walls; %lu face regions; F-Town's box %.1f, %.1f .. %.1f, "
        "%.1f",
        g_lnSet.name, g_lnDataName, g_ln.junction[0], g_ln.junction[1], g_ln.junction[2], g_ln.onRadius,
        g_ln.offRadius, g_ln.subs[0], g_ln.subs[1], g_ln.ours, g_ln.adjoin, g_ln.wallCount,
        (unsigned long)g_lnFaceCount, g_ln.box[0], g_ln.box[1], g_ln.box[2], g_ln.box[3]);
}

// ---------------------------------------------------------------- the game's state

static bool Roaming()
{
    DWORD rs = 0, mode = 1;
    return ReadDword(kRaceStatusPtr, &rs) && rs && ReadDword(rs + kPlayModeAt, &mode) && mode == 0;
}

static int ZoneAt(float x, float y)
{
    float v[2] = {x, y};
    DWORD rec = (DWORD)(UINT_PTR)((void*(__thiscall*)(void*, const float*))(UINT_PTR)kFindDrivable)(
        (void*)(UINT_PTR)kVsmBoundaries, v);
    short n = 0;
    return rec && SafeRead(rec + 0x0C, &n, 2) ? n : 0;
}

static bool StreamerZoneIs(int zone)
{
    for (DWORD at : kStreamerZones)
    {
        short z = 0;
        if (SafeRead(at, &z, 2) && z == zone)
            return true;
    }
    return false;
}

// every collider's cached instances cleared, as the inlined InvalidateAllCachedData at 0x782C81 does (WCollider::Clear
// and +0x80 = 0), without SetExclusionFlags()'s walk over every pack
static void CollidersClear()
{
    DWORD arr = 0, n = 0;
    if (!ReadDword(kColliderArray, &arr) || !ReadDword(kColliderCount, &n) || !arr || n > 4096)
        return;
    for (DWORD k = 0; k < n; k++)
    {
        DWORD c = 0;
        if (!ReadDword(arr + 4 * k, &c) || !c)
            continue;
        ((void(__thiscall*)(void*))(UINT_PTR)kColliderClear)((void*)(UINT_PTR)c);
        *(BYTE*)(UINT_PTR)(c + 0x80) = 0;
    }
}

// ---------------------------------------------------------------- the zones

static DWORD FindRec(DWORD list, int number, int at)
{
    DWORD n = 0;
    if (!ReadDword(list, &n))
        return 0;
    for (int guard = 0; n && n != list && guard < 4096; guard++)
    {
        short v = 0;
        if (!SafeRead(n + at, &v, 2))
            return 0;
        if (v == number)
            return n;
        if (!ReadDword(n, &n))
            return 0;
    }
    return 0;
}

static void Swap(DWORD out, DWORD in)
{
    DWORD next = *(DWORD*)(UINT_PTR)out, prev = *(DWORD*)(UINT_PTR)(out + 4);
    *(DWORD*)(UINT_PTR)in = next;
    *(DWORD*)(UINT_PTR)(in + 4) = prev;
    *(DWORD*)(UINT_PTR)prev = in;           // prev->next (the list's own head when out was first)
    *(DWORD*)(UINT_PTR)(next + 4) = in;     // next->prev
}

static void LinkTail(DWORD list, DWORD node)
{
    DWORD last = *(DWORD*)(UINT_PTR)(list + 4);
    *(DWORD*)(UINT_PTR)node = list;
    *(DWORD*)(UINT_PTR)(node + 4) = last;
    *(DWORD*)(UINT_PTR)last = node;
    *(DWORD*)(UINT_PTR)(list + 4) = node;
}

static void Unlink(DWORD node)
{
    DWORD next = *(DWORD*)(UINT_PTR)node, prev = *(DWORD*)(UINT_PTR)(node + 4);
    *(DWORD*)(UINT_PTR)prev = next;
    *(DWORD*)(UINT_PTR)(next + 4) = prev;
}

static void AddUnique(DrvRec& r, int v)
{
    for (int k = 0; k < r.count; k++)
        if (r.vis[k] == v)
            return;
    if (r.count < 72)
        r.vis[r.count++] = (short)v;
}

static bool ZonesIn()
{
    const LnHead& h = g_ln;
    DWORD src = FindRec(kVsmSections, h.source, 0x0C);
    if (!src)
    {
        Log("connection: REFUSED: no drivable section %u in the game's list", h.source);
        return false;
    }
    short cnt = 0, list[72];
    if (!SafeRead(src + 0x10, &cnt, 2) || cnt != (short)h.sourceCount || !SafeRead(src + 0x12, list, 2 * cnt) ||
        memcmp(list, g_lnSrc, 2 * cnt))
    {
        Log("connection: REFUSED: section %u's visible list is not the one the data was built with (%d sections; the "
            "data has %u): another Rockport", h.source, cnt, h.sourceCount);
        return false;
    }
    DWORD takenRec = FindRec(kVsmSections, h.ours, 0x0C), takenBnd = FindRec(kVsmBoundaries, h.ours, 0x08);
    if ((takenRec && takenRec != (DWORD)(UINT_PTR)&g_lnOurRec) ||
        (takenBnd && takenBnd != (DWORD)(UINT_PTR)&g_lnOurBnd))
    {
        Log("connection: REFUSED: zone %u is taken in the game's lists", h.ours);
        return false;
    }
    DWORD adj = FindRec(kVsmSections, h.adjoin, 0x0C), adjB = 0;
    BndRec ab;
    bool shared = adj && ReadDword(adj + 8, &adjB) && adjB && SafeRead(adjB, &ab, 0x24) && ab.points > 0 &&
                  ab.points <= 16 && SafeRead(adjB + 0x24, ab.pts, 8 * ab.points);
    int matched = 0;
    for (int k = 0; shared && k < 2; k++)
        for (int j = 0; j < ab.points; j++)
            if (fabsf(ab.pts[j][0] - g_lnPts[k][0]) < 0.01f && fabsf(ab.pts[j][1] - g_lnPts[k][1]) < 0.01f)
            {
                matched++;
                break;
            }
    if (matched != 2)
    {
        Log("connection: REFUSED: zone %u's boundary does not have our zone's first two points (the switch would be a "
            "far load): another Rockport", h.adjoin);
        return false;
    }
    DWORD orig[2];
    for (int s = 0; s < 2; s++)
    {
        orig[s] = FindRec(kVsmSections, h.subs[s], 0x0C);
        DrvRec& r = g_lnSubRec[s];
        memset(&r, 0, sizeof(r));
        if (!orig[s] || !SafeRead(orig[s], &r, 0x12) || r.count < 0 || r.count > r.max || r.max > 72 ||
            !SafeRead(orig[s] + 0x12, r.vis, 2 * r.count))
        {
            Log("connection: REFUSED: drivable section %u cannot be read", h.subs[s]);
            return false;
        }
        r.max = 72;
        for (int k = 0; k < h.sourceCount; k++) AddUnique(r, g_lnSrc[k]);
        for (int k = 0; k < h.extraCount; k++) AddUnique(r, g_lnExtra[k]);
    }
    DrvRec& o = g_lnOurRec;
    // still linked (the streamer was in it when the connection went off): its next/prev are the game's list now
    DWORD keepNext = o.next, keepPrev = o.prev;
    memset(&o, 0, sizeof(o));
    if (g_lnOursLinked)
        o.next = keepNext, o.prev = keepPrev;
    o.boundary = (DWORD)(UINT_PTR)&g_lnOurBnd;
    o.number = (short)h.ours;
    o.most = 72;
    o.max = 72;
    for (int k = 0; k < h.sourceCount; k++) AddUnique(o, g_lnSrc[k]);
    for (int k = 0; k < g_lnSubRec[1].count; k++) AddUnique(o, g_lnSubRec[1].vis[k]);  // the adjoining zone's own
    BndRec& b = g_lnOurBnd;
    DWORD keepBNext = b.next, keepBPrev = b.prev;
    memset(&b, 0, sizeof(b));
    if (g_lnOursLinked)
        b.next = keepBNext, b.prev = keepBPrev;
    b.number = (short)h.ours;
    b.points = (signed char)h.pointCount;
    b.bmin[0] = b.bmin[1] = 1e30f;
    b.bmax[0] = b.bmax[1] = -1e30f;
    for (int k = 0; k < h.pointCount; k++)
    {
        b.pts[k][0] = g_lnPts[k][0];
        b.pts[k][1] = g_lnPts[k][1];
        for (int a = 0; a < 2; a++)
        {
            b.bmin[a] = g_lnPts[k][a] < b.bmin[a] ? g_lnPts[k][a] : b.bmin[a];
            b.bmax[a] = g_lnPts[k][a] > b.bmax[a] ? g_lnPts[k][a] : b.bmax[a];
            b.centre[a] += g_lnPts[k][a] / h.pointCount;
        }
    }
    for (int s = 0; s < 2; s++)
    {
        Swap(orig[s], (DWORD)(UINT_PTR)&g_lnSubRec[s]);
        g_lnOrigRec[s] = orig[s];
    }
    if (!g_lnOursLinked)
    {
        LinkTail(kVsmBoundaries, (DWORD)(UINT_PTR)&g_lnOurBnd);
        LinkTail(kVsmSections, (DWORD)(UINT_PTR)&g_lnOurRec);
        g_lnOursLinked = true;
    }
    g_lnZones = true;
    Log("connection: zones in: %u and %u replaced (lists %d and %d sections: %u's %u, their own, %u more), our zone %u "
        "(%u points from %u's edge, list %d)", h.subs[0], h.subs[1], g_lnSubRec[0].count, g_lnSubRec[1].count,
        h.source, h.sourceCount, h.extraCount, h.ours, h.pointCount, h.adjoin, o.count);
    return true;
}

// The substitutes back (any time: their numbers stay findable); our zone out unless a streaming position is in it
// (then kept linked: tried again each frame, or left for the track's unloader when `final`).
static void ZonesOut(const char* why, bool final)
{
    if (g_lnZones)
    {
        for (int s = 0; s < 2; s++)
            if (g_lnOrigRec[s])
                Swap((DWORD)(UINT_PTR)&g_lnSubRec[s], g_lnOrigRec[s]);
        g_lnZones = false;
        Log("connection: zones %u and %u back as the game had them (%s)", g_ln.subs[0], g_ln.subs[1], why);
    }
    if (!g_lnOursLinked)
        return;
    if (StreamerZoneIs(g_ln.ours))
    {
        static DWORD logged;
        if (final)
        {
            Log("connection: our zone %u left linked: the streamer is in it; the track's unloader clears the lists "
                "(%s)", g_ln.ours, why);
            g_lnOursLinked = false;  // the game's lists are re-initialised; our records are static
        }
        else if (GetTickCount() - logged > 5000)
        {
            logged = GetTickCount();
            Log("connection: our zone %u kept: the streamer is still in it (%s)", g_ln.ours, why);
        }
        return;
    }
    Unlink((DWORD)(UINT_PTR)&g_lnOurRec);
    Unlink((DWORD)(UINT_PTR)&g_lnOurBnd);
    g_lnOursLinked = false;
    Log("connection: our zone %u out of the game's lists (%s)", g_ln.ours, why);
}

// ---------------------------------------------------------------- the walls

static float SegDist(float px, float py, float x0, float y0, float x1, float y1)
{
    float dx = x1 - x0, dy = y1 - y0, L = dx * dx + dy * dy;
    float t = L > 0 ? ((px - x0) * dx + (py - y0) * dy) / L : 0;
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    float qx = x0 + t * dx - px, qy = y0 + t * dy - py;
    return sqrtf(qx * qx + qy * qy);
}

// Every barrier of a pack object (WCollisionPack: +4 instance count, +8 instances of 0x40) on wall w: with `flag`, sunk
// (both heights kSunkY, the old ones kept in g_lnFlags[w]). Returns how many lie on it.
static int ScanPack(DWORD obj, int w, bool flag)
{
    const LnWall& wl = g_lnWalls[w];
    DWORD count = 0, inst = 0;
    if (!ReadDword(obj + 4, &count) || !ReadDword(obj + 8, &inst) || !inst || count > 0xFFFF)
        return 0;
    int found = 0;
    for (DWORD i = 0; i < count; i++)
    {
        BYTE ci[0x40];
        if (!SafeRead(inst + 0x40 * i, ci, 0x40))
            break;
        DWORD art = *(DWORD*)(ci + 0x1C);
        WORD flags = *(WORD*)(ci + 0x12);
        if (!art || (flags & 3))
            continue;
        WORD hdr[3];
        if (!SafeRead(art, hdr, 6))
            continue;
        const float *r0 = (const float*)ci, *r2 = (const float*)(ci + 0x20), *t = (const float*)(ci + 0x30);
        DWORD bar = art + 0x10 + hdr[1];
        for (WORD e = 0; e < hdr[2]; e++, bar += 0x20)
        {
            float b[8];
            if (!SafeRead(bar, b, 0x20))
                break;
            bool on = true;
            float zs[2];
            for (int p = 0; p < 2; p++)
            {
                const float* l = b + 4 * p;  // p0 at +0, p1 at +0x10
                float d[3] = {l[0] - t[0], l[1] - t[1], l[2] - t[2]};
                float wx = d[0] * r0[0] + d[1] * r0[1] + d[2] * r0[2], wy = d[1];
                float wz = d[0] * r2[0] + d[1] * r2[1] + d[2] * r2[2];
                float rx = wz, ry = -wx;  // render
                zs[p] = wy;
                on &= SegDist(rx, ry, wl.x0, wl.y0, wl.x1, wl.y1) < 0.6f;
            }
            float lo = zs[0] < zs[1] ? zs[0] : zs[1], hi = zs[0] < zs[1] ? zs[1] : zs[0];
            on &= lo >= wl.zLow && hi <= wl.zHigh;
            if (!on)
                continue;
            found++;
            if (flag && g_lnFlagCount[w] < 64)
            {
                LnSunk& s = g_lnFlags[w][g_lnFlagCount[w]++];
                s.bar = bar;
                s.y0 = b[1];
                s.y1 = b[5];
                *(float*)(UINT_PTR)(bar + 0x04) = kSunkY;
                *(float*)(UINT_PTR)(bar + 0x14) = kSunkY;
            }
        }
    }
    return found;
}

static void WallBack(int w)
{
    for (int k = g_lnFlagCount[w] - 1; k >= 0; k--)
    {
        const LnSunk& s = g_lnFlags[w][k];
        *(float*)(UINT_PTR)(s.bar + 0x04) = s.y0;
        *(float*)(UINT_PTR)(s.bar + 0x14) = s.y1;
    }
    g_lnFlagCount[w] = 0;
}

// the first sunk barrier of wall w no longer sunk: its pack was loaded again in the same place
static bool WallReloaded(int w)
{
    float y = 0;
    return g_lnFlagCount[w] && SafeRead(g_lnFlags[w][0].bar + 0x04, &y, 4) && y != kSunkY;
}

// the object each wall lives in now: Rockport's pack object in mCollisionPackList, or the city's buffer (pack 0)
static DWORD WallHome(int w)
{
    if (g_lnWalls[w].pack == 0)
        return (DWORD)(UINT_PTR)g_city.buffer;
    DWORD list = 0, obj = 0;
    if (ReadDword(kPackListPtr, &list) && list && g_lnWalls[w].pack < kPackMax)
        ReadDword(list + 4 * g_lnWalls[w].pack, &obj);
    return obj;
}

static bool Faces(bool open, const char* why);

// Each frame while on: a wall whose home changed has its flags dropped (the old pack is gone) or put back (the same
// object), and set in the new one, counted first.
static void Walls(bool open, const char* why)
{
    bool changed = false;
    for (int w = 0; w < g_ln.wallCount; w++)
    {
        DWORD home = open ? WallHome(w) : 0;
        // the same object with our first barrier back up: the pack was loaded again at the same address
        bool fresh = home && home == g_lnFlagObj[w] && WallReloaded(w);
        if (home == g_lnFlagObj[w] && !fresh)
            continue;
        if (fresh)
        {
            g_lnFlagCount[w] = 0;
            g_lnFlagObj[w] = 0;
            Log("connection: wall %d's pack was loaded again in the same place", w);
        }
        if (g_lnFlagObj[w])
        {
            if (WallHome(w) == g_lnFlagObj[w])
            {
                WallBack(w);
                Log("connection: wall %d closed again (%d barriers; %s)", w, g_lnWalls[w].expect, why);
            }
            else
            {
                g_lnFlagCount[w] = 0;  // its pack went with the streamer: nothing of ours left to put back
                Log("connection: wall %d's pack went (the streamer or the city unloaded it)", w);
            }
            g_lnFlagObj[w] = 0;
            changed = true;
        }
        if (!home)
            continue;
        int n = 0;
        if (g_lnWalls[w].pack == 0)
        {
            DWORD list = 0;
            ReadDword(kPackListPtr, &list);
            for (int k = 0; list && k < g_city.packCount; k++)
            {
                DWORD obj = 0;
                if (ReadDword(list + 4 * g_city.packs[k], &obj) && obj)
                    n += ScanPack(obj, w, false);
            }
        }
        else
            n = ScanPack(home, w, false);
        g_lnFlagObj[w] = home;
        if (n != g_lnWalls[w].expect)
        {
            static DWORD warned[8];
            if (warned[w] != home)
                Log("connection: wall %d NOT OPENED: %d barriers on its line, the data expects %d (pack %u: another "
                    "Rockport or city)", w, n, g_lnWalls[w].expect, g_lnWalls[w].pack);
            warned[w] = home;
            continue;
        }
        if (g_lnWalls[w].pack == 0)
        {
            DWORD list = 0;
            ReadDword(kPackListPtr, &list);
            for (int k = 0; list && k < g_city.packCount; k++)
            {
                DWORD obj = 0;
                if (ReadDword(list + 4 * g_city.packs[k], &obj) && obj)
                    ScanPack(obj, w, true);
            }
        }
        else
            ScanPack(home, w, true);
        changed = true;
        Log("connection: wall %d OPEN (%d barriers of %s %u)", w, n, g_lnWalls[w].pack ? "pack" : "the city's packs",
            g_lnWalls[w].pack);
    }
    changed |= Faces(open, why);
    if (changed)
        CollidersClear();
}

// ---------------------------------------------------------------- the ramp's faces

// Every face of a pack object in region f (LnFaces): counted, and with flag its flags byte | 4 (old bytes kept).
// The article (WCollisionArticle): +0 strip count, +2 strips size; strip spheres at +0x10 (16 each: centre x, y, z,
// u16 radius, u16 offset: the strip at article + 0x10 + offset); a strip's vertices 8 bytes each (s16 x, y, z / 128 +
// the centre, u16 word: vertex 0's = the count, vertex 1's = the strip's flags, vertex k + 2's = triangle k's surface:
// u8 index, u8 flags).
static int ScanFaces(DWORD obj, int f, bool flag)
{
    const LnFaces& r = g_lnFaces[f];
    DWORD count = 0, inst = 0;
    if (!ReadDword(obj + 4, &count) || !ReadDword(obj + 8, &inst) || !inst || count > 0xFFFF)
        return 0;
    int found = 0;
    for (DWORD i = 0; i < count; i++)
    {
        BYTE ci[0x40];
        if (!SafeRead(inst + 0x40 * i, ci, 0x40))
            break;
        DWORD art = *(DWORD*)(ci + 0x1C);
        WORD iflags = *(WORD*)(ci + 0x12);
        if (!art || (iflags & 3))
            continue;
        WORD hdr[2];
        if (!SafeRead(art, hdr, 4))
            continue;
        const float *r0 = (const float*)ci, *r2 = (const float*)(ci + 0x20), *t = (const float*)(ci + 0x30);
        for (WORD s = 0; s < hdr[0]; s++)
        {
            BYTE sph[16];
            if (!SafeRead(art + 0x10 + 0x10 * s, sph, 16))
                break;
            const float* c = (const float*)sph;
            DWORD strip = art + 0x10 + *(WORD*)(sph + 14);
            WORD n = 0;
            if (!SafeRead(strip + 6, &n, 2) || n < 3 || n > 4096)
                continue;
            float rx[3], ry[3], rz[3];
            for (WORD k = 0; k < n; k++)
            {
                short v[4];
                if (!SafeRead(strip + 8 * k, v, 8))
                    break;
                float d[3] = {v[0] / 128.0f + c[0] - t[0], v[1] / 128.0f + c[1] - t[1], v[2] / 128.0f + c[2] - t[2]};
                float wx = d[0] * r0[0] + d[1] * r0[1] + d[2] * r0[2], wy = d[1];
                float wz = d[0] * r2[0] + d[1] * r2[1] + d[2] * r2[2];
                rx[k % 3] = wz, ry[k % 3] = -wx, rz[k % 3] = wy;  // render
                if (k < 2)
                    continue;
                float cx = (rx[0] + rx[1] + rx[2]) / 3, cy = (ry[0] + ry[1] + ry[2]) / 3, cz = (rz[0] + rz[1] + rz[2]) / 3;
                if (cz < r.zLow || cz > r.zHigh)
                    continue;
                bool in = SegDist(cx, cy, r.x0, r.y0, r.x1, r.y1) < r.half;
                for (int q = 0; q < 3 && !in; q++) in = SegDist(rx[q], ry[q], r.x0, r.y0, r.x1, r.y1) < r.half;
                if (!in)
                    continue;
                found++;
                if (flag && g_lnFaceFlagCount[f] < kLnFacesMax)
                {
                    BYTE* fb = (BYTE*)(UINT_PTR)(strip + 8 * k + 7);
                    g_lnFaceFlags[f][g_lnFaceFlagCount[f]].addr = strip + 8 * k + 7;
                    g_lnFaceFlags[f][g_lnFaceFlagCount[f]].old = *fb;
                    g_lnFaceFlagCount[f]++;
                    *fb |= 4;
                }
            }
        }
    }
    return found;
}

static void FacesBack(int f)
{
    for (int k = g_lnFaceFlagCount[f] - 1; k >= 0; k--)
        *(BYTE*)(UINT_PTR)g_lnFaceFlags[f][k].addr = g_lnFaceFlags[f][k].old;
    g_lnFaceFlagCount[f] = 0;
}

static DWORD FacesHome(int f)
{
    DWORD list = 0, obj = 0;
    if (ReadDword(kPackListPtr, &list) && list)
        ReadDword(list + 4 * g_lnFaces[f].pack, &obj);
    return obj;
}

// As Walls: each frame while on, a region whose pack object changed has its flags dropped (the old object is gone) or
// put back (the same object), and set in the new one, counted first.
static bool Faces(bool open, const char* why)
{
    bool changed = false;
    for (int f = 0; f < (int)g_lnFaceCount; f++)
    {
        DWORD home = open ? FacesHome(f) : 0;
        bool fresh = home && home == g_lnFaceObj[f] && g_lnFaceFlagCount[f] &&
                     (*(BYTE*)(UINT_PTR)g_lnFaceFlags[f][0].addr & 4) != 4;
        if (home == g_lnFaceObj[f] && !fresh)
            continue;
        if (fresh)
        {
            g_lnFaceFlagCount[f] = 0;
            g_lnFaceObj[f] = 0;
            Log("connection: faces %d's pack was loaded again in the same place", f);
        }
        if (g_lnFaceObj[f])
        {
            if (FacesHome(f) == g_lnFaceObj[f])
            {
                FacesBack(f);
                Log("connection: faces %d back as they were (%d faces; %s)", f, g_lnFaces[f].expect, why);
            }
            else
            {
                g_lnFaceFlagCount[f] = 0;
                Log("connection: faces %d's pack went (the streamer unloaded it)", f);
            }
            g_lnFaceObj[f] = 0;
            changed = true;
        }
        if (!home)
            continue;
        int n = ScanFaces(home, f, false);
        g_lnFaceObj[f] = home;
        if (n != g_lnFaces[f].expect)
        {
            static DWORD warned[kLnFaceRegions];
            if (warned[f] != home)
                Log("connection: faces %d NOT FLAGGED: %d faces in its region, the data expects %d (pack %u: another "
                    "Rockport); the ramp's part over Rockport's road may not hold a car", f, n, g_lnFaces[f].expect,
                    g_lnFaces[f].pack);
            warned[f] = home;
            continue;
        }
        ScanFaces(home, f, true);
        changed = true;
        Log("connection: faces %d FLAGGED (%d faces of pack %u under the ramp)", f, n, g_lnFaces[f].pack);
    }
    return changed;
}

// ---------------------------------------------------------------- on and off

static void LinkCityOut(const char* why)
{
    if (!g_city.buffer)
        return;
    for (int w = 0; w < g_ln.wallCount; w++)  // the city's wall: closed again before its packs go
        if (g_lnWalls[w].pack == 0 && g_lnFlagObj[w])
        {
            WallBack(w);
            g_lnFlagObj[w] = 0;
        }
    Unload(why);
}

// Run L: the player's collision mask, logged once a track (the game's own exclusion mask for its car's colliders:
// RBComplexParams.fCollisionMask, stored by RigidBody::RigidBody at +0x104; the IRigidBody the plugin holds is the
// object + 0x48, so the mask is at rb + 0xBC). Read only when the constructor's store is the one checked here and the
// body is an RBVehicle.
static const Site kMaskSite = {0x6B5BC6, {0x8B, 0x47, 0x34, 0x89, 0x85, 0x04, 0x01, 0x00, 0x00}, 9,
                               "RigidBody::RigidBody: mov [this + 0x104], params.fCollisionMask (params + 0x34)"};

static void LogPlayerMask(void* player)
{
    if (g_lnMaskLogged)
        return;
    g_lnMaskLogged = true;
    DWORD vtbl = 0, mask = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    if (!rb || vtbl != kRBVehicleVtbl)
        Log("connection: the player's collision mask not read (the body's table 0x%08lX, not an RBVehicle's)",
            (unsigned long)vtbl);
    else if (!BytesAre(kMaskSite))
        Log("connection: the player's collision mask not read (the constructor's store is not the one expected)");
    else if (!ReadDword((DWORD)(UINT_PTR)rb + 0xBC, &mask))
        Log("connection: the player's collision mask cannot be read");
    else
        Log("connection: the player's collision mask 0x%08lX (RigidBody + 0x104; a barrier's flags byte sharing a bit "
            "with it lets the car through: 0 = none does, traffic's 0x40, cops' 0x80; the opened walls are sunk "
            "instead, for every car)", (unsigned long)mask);
}

static void LinkOn(void* player, float dist)
{
    double t0 = NowMs();
    g_collidersOnly = true;  // review: also on the failure paths below (SetExclusionFlags() is never for free roam)
    bool net = RoadNetPrepare() && RoadNetInstalled();
    const char* failed = nullptr;
    if (!SetLoadChunks(g_lnSet, "connection: NOT ON", &failed))
    {
        if (failed)
            SetUnloadChunks(g_lnSet, failed);
        g_lnRefused = true;
        Log("connection: NOT ON: the connector could not be loaded; not tried again until the track unloads");
        return;
    }
    if (!ZonesIn())
    {
        SetUnloadChunks(g_lnSet, "the zones were refused");
        g_lnRefused = true;
        Log("connection: NOT ON: the zones were refused; not tried again until the track unloads");
        return;
    }
    bool joined = net && RoadNetJoin(true, "the connection is on");
    g_lnOn = true;
    g_lnCareer = true;
    g_collidersOnly = true;
    g_lnFarSince = g_lnCityOutSince = -1;
    Walls(true, "the connection is on");
    LogPlayerMask(player);
    Log("connection: ON in %.1f ms (the car %.0f m from the junction): the connector loaded, zones in, %s", NowMs() - t0,
        dist, joined ? "the road network joined at the junction" : "NO road network join (moving traffic is not in)");
}

static void LinkOff(const char* why, bool final)
{
    if (!g_lnOn)
        return;
    LinkCityOut(why);
    Walls(false, why);
    RoadNetJoin(false, why);
    ZonesOut(why, final);
    if (g_lnSet.buffer)
    {
        double ms = SetUnloadChunks(g_lnSet, why);
        Log("connection: the connector UNLOADED: UnloadChunks %.1f ms", ms);
    }
    g_lnOn = false;
    g_lnCareer = false;
    Log("connection: OFF (%s)", why);
}

static bool InTownBox(float x, float y, float m)
{
    return x >= g_ln.box[0] - m && x <= g_ln.box[2] + m && y >= g_ln.box[1] - m && y <= g_ln.box[3] + m;
}

// Once a frame while the player exists (after the game mode, before the traffic).
static void LinkFrame(void* player)
{
    if (!g_lnReady || g_lnTrackGone)
        return;
    if (g_lnOursLinked && !g_lnOn)
        ZonesOut("pending", false);
    float p[3];
    if (!PlayerPosition(player, p))
        return;
    float x = p[2], y = -p[0];
    float dx = x - g_ln.junction[0], dy = y - g_ln.junction[1], dist = sqrtf(dx * dx + dy * dy);
    bool roam = Roaming();
    if (!g_lnOn)
    {
        if (roam && !g_lnRefused && !RaceOurs() && dist < g_ln.onRadius)
            LinkOn(player, dist);
        return;
    }
    int zone = ZoneAt(x, y);
    if (zone != g_lnLastZone)
    {
        Log("connection: the car in zone %d at render (%.0f, %.0f), %.0f m from the junction", zone, x, y, dist);
        g_lnLastZone = zone;
    }
    bool inTown = InTownBox(x, y, 100.0f);
    // (G26 and G23 hold no road of Rockport's: a car in them is on the connector, race or not; in a race F-Town is
    // never loaded, below)
    bool onLink = zone == g_ln.subs[0] || zone == g_ln.subs[1] || zone == g_ln.ours || (zone == 0 && inTown);
    float now = SimNow();
    if (g_lnFarSince > now)
        g_lnFarSince = -1;  // the clock went back (a restart)
    if (g_lnCityOutSince > now)
        g_lnCityOutSince = -1;
    if (!roam && !onLink && dist > g_ln.nearRadius)
    {
        LinkOff("not free roam (a race)", false);
        return;
    }
    if (dist > g_ln.offRadius && !onLink)
    {
        if (g_lnFarSince < 0)
            g_lnFarSince = now;
        else if (now - g_lnFarSince > kLinkWait)
        {
            LinkOff("the car is far from the junction", false);
            return;
        }
    }
    else
        g_lnFarSince = -1;
    if (onLink && !g_city.buffer && roam && !g_lnCityFailed)
    {
        Log("connection: F-Town wanted (the car in zone %d, %.0f m from the junction)", zone, dist);
        if (LoadCity("connection: F-Town NOT IN"))
        {
            MinimapLoad();
            Log("connection: F-Town IN (the car in zone %d)", zone);
        }
        else
        {
            g_lnCityFailed = true;  // review: not again this track; the connector stays (the car may be on it)
            Log("connection: F-Town NOT IN: not tried again until the track unloads (the road stays)");
        }
    }
    if (g_city.buffer && !onLink && dist > g_ln.nearRadius)
    {
        if (g_lnCityOutSince < 0)
            g_lnCityOutSince = now;
        else if (now - g_lnCityOutSince > kLinkWait)
        {
            g_lnCityOutSince = -1;
            LinkCityOut("connection: the car is back in Rockport");
        }
    }
    else
        g_lnCityOutSince = -1;
    Walls(true, "the connection is on");
}

// TrackLoader::Unload: before the city, the grid and the network go
static void LinkTrackUnload()
{
    if (g_lnOn)
        LinkOff("track unloading", true);
    else if (g_lnOursLinked)
        ZonesOut("track unloading", true);
    g_lnRefused = false;
    g_lnCityFailed = false;
    g_lnMaskLogged = false;
    g_lnLastZone = -1;
    g_collidersOnly = false;
    g_lnTrackGone = true;
}
