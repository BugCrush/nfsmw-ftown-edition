// FTownRace.h - F-Town's minimap (and the Time Attack): included once by FTownLoader.cpp, after its helpers (Log,
// SafeRead, Player, the Site/Slot checks, LoadChunks), so the plugin stays one file to build and one .asi to install.
//
// The minimap (docs/ftown-race-notes.md R1 and "Task 2"): the game's own HUD minimap draws a 1024 x 1024 world map cut
// into 8 x 8 textures named "<header>_CHOP<n>", placed by the current track's TrackInfo calibration. While F-Town is
// loaded FTownLoader (1) loads our pack of 64 such textures (FTOWN_MAP_CHOP0..63, tools/citymap/minimap.py) with the
// game's LoadChunks, (2) writes F-Town's calibration into the current track's TrackInfo record and (3) the name
// FTOWN_MAP into the map manager's header; the game then draws F-Town's streets, the arrow and the icons itself.
// The game has no upper bound on the chop number (0x5673BD), so (2) and (3) are in place only while the car is inside
// the safe box (map units [1/16, 15/16) on both axes, where the four chops around the car stay in rows and columns
// 0..7); outside it Rockport's numbers are back and every chop number is negative (as before: an empty map).
// On F7, on leaving the race and on a restart, the calibration and header are put back first; the pack is unloaded 3
// frames later after F7 (the HUD has asked for Rockport's names by then), at once when the race is left.

// ---------------------------------------------------------------- the minimap's addresses (speed.exe v1.3)

static const DWORD kTrackNumber = 0x904FB8;                         // TheRaceParameters.TrackNumber
static const DWORD kTrackInfoTable = 0x9A3A14, kTrackInfoCount = 0x9A3A18;  // TrackInfo::TrackInfoTable, NumTrackInfo
static const DWORD kMapManager = 0x91CEFC;                          // gChoppedMiniMapManager
static const DWORD kTrackInfoSize = 0x120, kTrackInfoNumber = 0x8A, kTrackInfoCalib = 0xAC, kHeaderAt = 8;

static const Site kMinimapSites[] = {
    {0x579906, {0xA1, 0xB8, 0x4F, 0x90, 0x00}, 5,
     "Minimap::SetupMinimap: mov eax, [TheRaceParameters.TrackNumber 0x904FB8]"},
    {0x579942,
     {0x8B, 0x86, 0x98, 0x00, 0x00, 0x00, 0xD8, 0xB0, 0xB4, 0x00, 0x00, 0x00, 0x83, 0xC4, 0x0C, 0xD9, 0x44, 0x24, 0x14,
      0xD8, 0xA0, 0xAC, 0x00, 0x00, 0x00, 0xD8, 0xC9, 0xD9, 0x80, 0xB0, 0x00, 0x00, 0x00},
     33, "SetupMinimap: the calibration read from TrackInfo +0xB4, +0xAC, +0xB0"},
    {0x579AA5, {0x8B, 0x0D, 0xFC, 0xCE, 0x91, 0x00, 0x50, 0x83, 0xC1, 0x08, 0x51}, 11,
     "SetupMinimap: texture names from [gChoppedMiniMapManager 0x91CEFC] + 8 (the header)"},
    {0x567510,
     {0x8B, 0x44, 0x24, 0x0C, 0x8B, 0x4C, 0x24, 0x04, 0xD9, 0x01, 0x8B, 0x54, 0x24, 0x08, 0xD8, 0xA0, 0xAC, 0x00, 0x00,
      0x00, 0xD8, 0xB0, 0xB4, 0x00, 0x00, 0x00},
     26, "Minimap::ConvertPos: (x - TrackInfo +0xAC) / +0xB4"},
    {0x567280, {0x8B, 0x44, 0x24, 0x04, 0x50, 0x83, 0xC1, 0x08, 0x6A, 0x40, 0x51}, 11,
     "ChoppedMiniMapManager::SetMapHeader: 64 bytes at +8"},
    {0x5673BD, {0x85, 0xDB, 0x7C, 0x3A, 0x8B, 0x7C, 0x9D, 0x48}, 8,
     "UncompressMaps: only a negative chop number is skipped (the guard's reason)"},
    {0x722840,
     {0x8B, 0x15, 0x18, 0x3A, 0x9A, 0x00, 0x56, 0x33, 0xC9, 0x85, 0xD2, 0x57, 0x7E, 0x27, 0xA1, 0x14, 0x3A, 0x9A, 0x00},
     19, "TrackInfo::GetTrackInfo: [NumTrackInfo 0x9A3A18], [TrackInfoTable 0x9A3A14]"},
    {0x722860, {0x0F, 0xBF, 0xB8, 0x8A, 0x00, 0x00, 0x00}, 7, "GetTrackInfo: the number at +0x8A"},
    {0x72286C, {0x05, 0x20, 0x01, 0x00, 0x00}, 5, "GetTrackInfo: 0x120 a record"},
};

// ---------------------------------------------------------------- settings and state

static bool g_mmEnabled = true, g_mmChecked;
static char g_mmPath[MAX_PATH], g_mmName[MAX_PATH], g_mmHeader[64];
static float g_mmCalib[3] = {-560.0f, 6508.0f, 5120.0f};  // upper left x, y; width (render metres)
static DWORD g_mmSize;
static FILETIME g_mmTime;
static bool g_mmFileOk;

static BYTE* g_mmBuffer;  // our pack, as handed to LoadChunks (null when not loaded)
static BYTE* g_mmPending;  // unloaded after kFreeAfterFrames frames (the F7 path)
static int g_mmPendingFrames;
static bool g_mmApplied;
static DWORD g_mmRecord, g_mmManager;  // the TrackInfo record and the manager written into
static BYTE g_mmSavedCalib[12], g_mmSavedHeader[64];
static int g_mmTrack;
static bool g_mmNoRecordLogged;

static void MinimapSettings(const char* dir)
{
    g_mmEnabled = GetPrivateProfileIntA("Minimap", "Enabled", 1, g_iniPath) == 1;
    GetPrivateProfileStringA("Minimap", "File", "ftown-minimap.bun", g_mmName, sizeof(g_mmName), g_iniPath);
    snprintf(g_mmPath, sizeof(g_mmPath), "%s%s", dir, g_mmName);
    GetPrivateProfileStringA("Minimap", "Header", "FTOWN_MAP", g_mmHeader, sizeof(g_mmHeader), g_iniPath);
    g_mmCalib[0] = IniFloat("Minimap", "UpperLeftX", -560.0f);
    g_mmCalib[1] = IniFloat("Minimap", "UpperLeftY", 6508.0f);
    g_mmCalib[2] = IniFloat("Minimap", "WidthMetres", 5120.0f);
}

// At start: the minimap's own sites (a mismatch turns only the minimap off) and the file: one texture pack chunk
// (0xB3300000, padding allowed), not kept in memory (read again at each F8, like the city).
static void MinimapStart()
{
    if (!g_mmEnabled)
    {
        Log("minimap off ([Minimap] Enabled = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kMinimapSites) ok &= BytesAre(s);
    if (!ok)
    {
        Log("WRONGBYTES in the minimap's sites: minimap off (the city still works)");
        g_mmEnabled = false;
        return;
    }
    g_mmChecked = true;
    if (!(g_mmCalib[2] > 1.0f))
    {
        Log("minimap off: [Minimap] WidthMetres %.1f is not a width", g_mmCalib[2]);
        g_mmEnabled = false;
        return;
    }
    HANDLE f = CreateFileA(g_mmPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("minimap file %s cannot be opened (error %lu); minimap off", g_mmName, (unsigned long)GetLastError());
        g_mmEnabled = false;
        return;
    }
    g_mmSize = GetFileSize(f, nullptr);
    GetFileTime(f, nullptr, nullptr, &g_mmTime);
    BYTE* b = (BYTE*)VirtualAlloc(nullptr, g_mmSize ? g_mmSize : 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    BOOL read = b && ReadFile(f, b, g_mmSize, &got, nullptr) && got == g_mmSize;
    CloseHandle(f);
    int packs = 0;
    const char* err = read ? nullptr : "cannot be read";
    for (DWORD off = 0; !err && off < g_mmSize;)
    {
        DWORD id = off + 8 <= g_mmSize ? *(DWORD*)(b + off) : 0, size = off + 8 <= g_mmSize ? *(DWORD*)(b + off + 4) : 0;
        if (off + 8 > g_mmSize || size > g_mmSize - off - 8)
            err = "a chunk runs past the file's end";
        else if (id == 0xB3300000)
            packs++;
        else if (id != 0)
            err = "a chunk that is not a texture pack";
        off += 8 + size;
    }
    if (!err && packs != 1)
        err = "not exactly one texture pack";
    if (b)
        VirtualFree(b, 0, MEM_RELEASE);
    if (err)
    {
        Log("minimap file %s: %s; minimap off", g_mmName, err);
        g_mmEnabled = false;
        return;
    }
    g_mmFileOk = true;
    // Review fix: the safe-box guard runs at MainLoop's start, but the game can move the car within the loop before the
    // HUD draws (a reset; the pause menu's Restart Race, which does not unload the track). With F-Town's calibration
    // and a Rockport position the chop numbers are 100+, read past the 64-slot table. So the test at 0x5673BD
    // (test ebx, ebx; jl skip; mov edi, [ebp + ebx*4 + 0x48]) becomes a jump to: cmp ebx, 63; ja skip (unsigned: a
    // negative number is skipped as before); mov edi, [ebp + ebx*4 + 0x48]; jmp 0x5673C5. Numbers 0..63, all Rockport
    // ever makes, run as before. Kept for the process's life.
    BYTE* stub = (BYTE*)VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!stub)
    {
        Log("minimap off: no memory for the chop bound");
        g_mmEnabled = false;
        return;
    }
    BYTE code[] = {0x83, 0xFB, 0x3F, 0x0F, 0x87, 0, 0, 0, 0, 0x8B, 0x7C, 0x9D, 0x48, 0xE9, 0, 0, 0, 0};
    *(DWORD*)(code + 5) = 0x5673FB - ((DWORD)(UINT_PTR)stub + 9);
    *(DWORD*)(code + 14) = 0x5673C5 - ((DWORD)(UINT_PTR)stub + 18);
    memcpy(stub, code, sizeof(code));
    FlushInstructionCache(GetCurrentProcess(), stub, 32);
    BYTE jmp[8] = {0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90};
    *(DWORD*)(jmp + 1) = (DWORD)(UINT_PTR)stub - (0x5673BD + 5);
    if (!WriteCode(0x5673BD, jmp, 8))
    {
        Log("minimap off: the chop bound could not be written");
        g_mmEnabled = false;
        return;
    }
    Log("minimap: chop numbers bounded to 0..63 (0x5673BD -> a stub: 64 or more is skipped as a negative one is)");
    Log("minimap file %s: %lu bytes, one texture pack; header %s, calibration upper left (%.1f, %.1f), width %.1f m",
        g_mmName, (unsigned long)g_mmSize, g_mmHeader, g_mmCalib[0], g_mmCalib[1], g_mmCalib[2]);
}

// ---------------------------------------------------------------- the TrackInfo record and the header

static DWORD TrackRecord(int track)
{
    DWORD table = 0, count = 0;
    if (!ReadDword(kTrackInfoTable, &table) || !ReadDword(kTrackInfoCount, &count) || !table || count > 256)
        return 0;
    for (DWORD i = 0; i < count; i++)
    {
        short n = 0;
        if (!SafeRead(table + i * kTrackInfoSize + kTrackInfoNumber, &n, 2))
            return 0;
        if (n == track)
            return table + i * kTrackInfoSize;
    }
    return 0;
}

static bool HeaderIsOurs(DWORD manager)
{
    char h[64];
    return SafeRead(manager + kHeaderAt, h, sizeof(h)) && !strncmp(h, g_mmHeader, sizeof(h));
}

static void MinimapApply()
{
    DWORD track = 0, manager = 0;
    ReadDword(kTrackNumber, &track);
    DWORD record = TrackRecord((int)track);
    if (!record || !ReadDword(kMapManager, &manager) || !manager)
    {
        if (!g_mmNoRecordLogged)
            Log("minimap: not in: no TrackInfo record for track %ld or no map manager (0x%08lX)", (long)track,
                (unsigned long)manager);
        g_mmNoRecordLogged = true;
        return;
    }
    if (!SafeRead(record + kTrackInfoCalib, g_mmSavedCalib, 12) ||
        !SafeRead(manager + kHeaderAt, g_mmSavedHeader, 64))
        return;
    memcpy((void*)(UINT_PTR)(record + kTrackInfoCalib), g_mmCalib, 12);
    char ours[64] = {0};
    strncpy(ours, g_mmHeader, sizeof(ours) - 1);
    memcpy((void*)(UINT_PTR)(manager + kHeaderAt), ours, 64);
    g_mmRecord = record;
    g_mmManager = manager;
    g_mmTrack = (int)track;
    g_mmApplied = true;
    float was[3];
    memcpy(was, g_mmSavedCalib, 12);
    char header[65];
    memcpy(header, g_mmSavedHeader, 64);
    header[64] = 0;
    Log("minimap: F-Town's map in (track %d: calibration was %.1f, %.1f, %.1f; header was %s)", g_mmTrack, was[0],
        was[1], was[2], header);
}

static void MinimapRestore(const char* why)
{
    if (!g_mmApplied)
        return;
    g_mmApplied = false;
    float now[3];
    bool calibOurs = SafeRead(g_mmRecord + kTrackInfoCalib, now, 12) && !memcmp(now, g_mmCalib, 12);
    if (calibOurs)
        memcpy((void*)(UINT_PTR)(g_mmRecord + kTrackInfoCalib), g_mmSavedCalib, 12);
    DWORD manager = 0;
    bool headerOurs = ReadDword(kMapManager, &manager) && manager == g_mmManager && HeaderIsOurs(manager);
    if (headerOurs)
        memcpy((void*)(UINT_PTR)(manager + kHeaderAt), g_mmSavedHeader, 64);
    Log("minimap: Rockport's map back (%s)%s%s", why, calibOurs ? "" : "; the calibration had changed meanwhile: left",
        headerOurs ? "" : "; the header had changed meanwhile: left");
}

// The pack: loaded after the teleport, unloaded with the city.
static void MinimapUnloadPack(BYTE* buffer)
{
    ((LoadChunksFn)(UINT_PTR)kUnloadChunks)(buffer, (int)g_mmSize, "FTOWNMAP");
    VirtualFree(buffer, 0, MEM_RELEASE);
    Log("minimap: our pack unloaded");
}

static void MinimapFlush()
{
    if (!g_mmPending)
        return;
    BYTE* b = g_mmPending;
    g_mmPending = nullptr;
    MinimapUnloadPack(b);
}

static void MinimapLoad()
{
    if (!g_mmEnabled || !g_mmFileOk)
        return;
    MinimapFlush();
    BYTE* b = (BYTE*)VirtualAlloc(nullptr, g_mmSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!b)
    {
        Log("minimap: no memory for its %lu bytes; not in", (unsigned long)g_mmSize);
        return;
    }
    HANDLE f = CreateFileA(g_mmPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    FILETIME t = {0, 0};
    DWORD got = 0;
    bool ok = f != INVALID_HANDLE_VALUE && GetFileTime(f, nullptr, nullptr, &t) && GetFileSize(f, nullptr) == g_mmSize &&
              !CompareFileTime(&t, &g_mmTime) && ReadFile(f, b, g_mmSize, &got, nullptr) && got == g_mmSize;
    if (f != INVALID_HANDLE_VALUE)
        CloseHandle(f);
    if (!ok)
    {
        VirtualFree(b, 0, MEM_RELEASE);
        Log("minimap: the file %s is gone or changed since the game started; not in", g_mmName);
        return;
    }
    ((LoadChunksFn)(UINT_PTR)kLoadChunks)(b, (int)g_mmSize, "FTOWNMAP");
    g_mmBuffer = b;
    g_mmNoRecordLogged = false;
    Log("minimap: our pack loaded (%lu bytes)", (unsigned long)g_mmSize);
}

// The F-Town map's safe box: map units in [1/16, 15/16) on both axes (a little inside), as Minimap::ConvertPos makes them.
static bool InSafeBox(float x, float y)
{
    float mx = (x - g_mmCalib[0]) / g_mmCalib[2], my = (g_mmCalib[1] - y) / g_mmCalib[2] + 1.0f;
    const float lo = 1.0f / 16 + 0.002f, hi = 15.0f / 16 - 0.002f;
    return mx >= lo && mx < hi && my >= lo && my < hi;
}

// Once a frame while the player exists.
static void MinimapFrame(void* player)
{
    if (g_mmPending && --g_mmPendingFrames <= 0)
        MinimapFlush();
    if (!g_mmBuffer)
        return;
    float p[3];
    if (!PlayerPosition(player, p))
        return;
    float x = p[2], y = -p[0];  // render
    bool inside = InSafeBox(x, y);
    if (inside && !g_mmApplied)
        MinimapApply();
    else if (!inside && g_mmApplied)
    {
        char why[96];
        snprintf(why, sizeof(why), "the car left F-Town's map: render %.0f, %.0f", x, y);
        MinimapRestore(why);
    }
    else if (g_mmApplied && !HeaderIsOurs(g_mmManager))
    {
        // the game set its header again (the HUD reloaded): take that one as the one to put back, ours again
        if (SafeRead(g_mmManager + kHeaderAt, g_mmSavedHeader, 64))
        {
            char ours[64] = {0};
            strncpy(ours, g_mmHeader, sizeof(ours) - 1);
            memcpy((void*)(UINT_PTR)(g_mmManager + kHeaderAt), ours, 64);
            Log("minimap: the game set its map header again; ours again");
        }
    }
}

// ---------------------------------------------------------------- Run K item 1: the safe house's sticky icon
//
// The house was a mark painted into our minimap texture: it scrolled off the round map. Now it is the game's own
// safe-house icon, placed as the game places its icons. Minimap::Update (0x59DB50) ends with UpdateGameplayIcons (the
// call at 0x59DD1A: push the player; mov ecx, esi; call 0x57A300), which puts GManager's icons in the minimap's images
// [minimap + 0x118 + (type * 8 + i) * 4] and hides every image it does not use (FEngSetInvisible 0x514C70: bit 0 of
// [image + 0x1C]). The safe house is type 8, SAFEHOUSEINDICATOR_%d (0x8F3AB8 + 20 x 8: map item 0x200000; images 0..3
// in HUD_SingleRace.fng, none in the drag HUD, which has no minimap). After the game's function, while F-Town's map is
// in, the highest of those images the game left hidden this frame goes to the house: Minimap::UpdateElementArt (0x5675D0,
// thiscall(&pos, &dir, image, pulse), ret 0x10: map units by the track's calibration, the speed zoom and the map's
// turn; farther than 0.06 it is clamped to the map's rim: the stickiness), FEngSetRotationZ(image, 0) (0x514E20) as
// UpdateIconElement does, and its colour's alpha 255 (the game fades a clamped icon out from 0.125 to 0.23 unless it
// is the GPS target, `pulse`, which would also move the GPS ring at +0x114: FEngGetObjectColor 0x515830,
// FEColor::operator unsigned 0x5B2D80, FEngSetColor 0x5157E0). The player's map item toggle ([[FEDatabase 0x91CF90] +
// 0x10] + 0x40 & 0x200000, read so by UpdateGameplayIcons at 0x57A382) is respected.
static const DWORD kIconsCall = 0x59DD1A, kUpdateGameplayIcons = 0x57A300, kUpdateElementArt = 0x5675D0;
static const DWORD kFESetRotationZ = 0x514E20, kFEGetObjectColor = 0x515830, kFEColorToU32 = 0x5B2D80;
static const DWORD kFESetColor = 0x5157E0, kIconFEDatabase = 0x91CF90;  // (FTownGame.h's kFEDatabase)
static const DWORD kSafehouseImages = 0x118 + (8 * 8) * 4, kSafehouseItem = 0x200000;
static const Site kIconSites[] = {
    {0x59DD17, {0x55, 0x8B, 0xCE, 0xE8, 0xE1, 0xC5, 0xFD, 0xFF}, 8,
     "Minimap::Update: push the player; mov ecx, esi; call Minimap::UpdateGameplayIcons (0x57A300)"},
    {0x57A300, {0x81, 0xEC, 0x6C, 0x03, 0x00, 0x00, 0x53, 0x55, 0x8B, 0xE9}, 10,
     "Minimap::UpdateGameplayIcons: sub esp, 0x36C; push ebx; push ebp; mov ebp, ecx"},
    {0x57A37F, {0x8B, 0x6D, 0x10, 0x85, 0x75, 0x40}, 6,
     "UpdateGameplayIcons: the map item toggle, [[FEDatabase] + 0x10] + 0x40 tested with the item"},
    {0x57A38E, {0x8B, 0x84, 0x85, 0x18, 0x01, 0x00, 0x00}, 7, "UpdateGameplayIcons: the images at [minimap + 0x118]"},
    {0x8F3B58, {0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x00, 0xEC, 0x01, 0x8A, 0x00}, 12,
     "kGameplayIconInfo[8]: GIcon type 8, map item 0x200000, \"SAFEHOUSEINDICATOR_%d\""},
    {0x5675D0, {0x83, 0xEC, 0x18, 0xD9, 0x05, 0x6C, 0x09, 0x89, 0x00, 0x56, 0x8B, 0xF1}, 12,
     "Minimap::UpdateElementArt: sub esp, 0x18; fld [1.0]; push esi; mov esi, ecx"},
    {0x567811, {0x83, 0xC4, 0x18, 0xC2, 0x10, 0x00}, 6, "UpdateElementArt: add esp, 0x18; ret 0x10"},
    {0x514E20, {0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF0, 0x83, 0xEC, 0x6C, 0x56, 0x8B, 0x75, 0x08}, 13,
     "FEngSetRotationZ(FEObject*, float)"},
    {0x515830, {0x8B, 0x44, 0x24, 0x08, 0x85, 0xC0, 0x56, 0x74, 0x21, 0x8B, 0x48, 0x2C}, 12,
     "FEngGetObjectColor(out, FEObject*)"},
    {0x5B2D80, {0x8B, 0x41, 0x08, 0x85, 0xC0, 0x56, 0x57}, 7, "FEColor::operator unsigned int"},
    {0x5157E0, {0x83, 0xEC, 0x10, 0x56, 0x8B, 0x74, 0x24, 0x18, 0x85, 0xF6}, 10, "FEngSetColor(FEObject*, unsigned)"},
};
static bool g_iconEnabled = false, g_iconOn;
static float g_safeHouse[2] = {0.0f, 0.0f};  // render metres, from the .ini only (no built-in place: the public build)
static int g_iconSlotLogged = -2;  // the slot the log last named (-1: none free)
static bool g_iconItemOffLogged;

static void IconSettings()
{
    g_iconEnabled = GetPrivateProfileIntA("Minimap", "SafeHouseIcon", 0, g_iniPath) == 1;
    char v[64];
    GetPrivateProfileStringA("Minimap", "SafeHouse", "", v, sizeof(v), g_iniPath);
    if (sscanf(v, "%f , %f", &g_safeHouse[0], &g_safeHouse[1]) != 2)
        g_iconEnabled = false;
}

typedef void(__thiscall* ElementArtFn)(void*, const float*, const float*, void*, bool);
typedef void*(__cdecl* GetColorFn)(void*, void*);
typedef DWORD(__thiscall* ColorU32Fn)(void*);

static void SafeHouseIcon(BYTE* minimap)
{
    if (!g_mmApplied || !g_mmBuffer)
        return;
    // the minimap's own track record must carry F-Town's calibration (the guard put it in this loop)
    DWORD track = 0;
    float cal[3];
    if (!ReadDword((DWORD)(UINT_PTR)minimap + 0x98, &track) || !track || !SafeRead(track + kTrackInfoCalib, cal, 12) ||
        memcmp(cal, g_mmCalib, 12))
        return;
    DWORD db = 0, settings = 0, items = 0;
    if (ReadDword(kIconFEDatabase, &db) && db && ReadDword(db + 0x10, &settings) && settings &&
        ReadDword(settings + 0x40, &items) && !(items & kSafehouseItem))
    {
        if (!g_iconItemOffLogged)
            Log("safe house icon: the map's safe-house icons are off in the player's settings: not shown");
        g_iconItemOffLogged = true;
        return;
    }
    g_iconItemOffLogged = false;
    void* img = nullptr;
    int slot = -1;
    for (int k = 7; k >= 0 && !img; k--)
    {
        DWORD p = 0, flags = 0;
        if (!ReadDword((DWORD)(UINT_PTR)minimap + kSafehouseImages + 4 * k, &p) || !p || !ReadDword(p + 0x1C, &flags))
            continue;
        if (!(flags & 1))
            break;  // the game's own safe house in the highest image there is: none of ours (logged below)
        img = (void*)(UINT_PTR)p, slot = k;
    }
    if (slot != g_iconSlotLogged)
    {
        g_iconSlotLogged = slot;
        if (slot < 0)
            Log("safe house icon: no free SAFEHOUSEINDICATOR image on this HUD: not shown");
        else
            Log("safe house icon: SAFEHOUSEINDICATOR_%d at render (%.1f, %.1f), kept on the map's rim when out of view",
                slot, g_safeHouse[0], g_safeHouse[1]);
    }
    if (!img)
        return;
    static const float dir[2] = {1.0f, 0.0f};
    ((ElementArtFn)(UINT_PTR)kUpdateElementArt)(minimap, g_safeHouse, dir, img, false);
    ((void(__cdecl*)(void*, float))(UINT_PTR)kFESetRotationZ)(img, 0.0f);
    BYTE color[16];
    void* c = ((GetColorFn)(UINT_PTR)kFEGetObjectColor)(color, img);
    DWORD argb = ((ColorU32Fn)(UINT_PTR)kFEColorToU32)(c);
    ((void(__cdecl*)(void*, DWORD))(UINT_PTR)kFESetColor)(img, (argb & 0x00FFFFFF) | 0xFF000000);
}

static void __fastcall HkGameplayIcons(void* minimap, void*, void* player)
{
    ((void(__thiscall*)(void*, void*))(UINT_PTR)kUpdateGameplayIcons)(minimap, player);
    SafeHouseIcon((BYTE*)minimap);
}

static void IconStart()
{
    if (!g_mmEnabled || !g_mmFileOk)
        return;
    if (!g_iconEnabled)
    {
        Log("safe house icon off ([Minimap] SafeHouseIcon = 0, or SafeHouse not x, y)");
        return;
    }
    bool ok = true;
    for (const Site& s : kIconSites) ok &= BytesAre(s);
    if (!ok)
    {
        Log("WRONGBYTES in the safe house icon's sites: no safe house on the minimap");
        return;
    }
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)&HkGameplayIcons - (kIconsCall + 5);
    if (WriteCode(kIconsCall, call, 5))
    {
        g_iconOn = true;
        Log("safe house icon: the game's safe-house icon at render (%.1f, %.1f) on F-Town's minimap, sticky (0x59DD1A)",
            g_safeHouse[0], g_safeHouse[1]);
    }
    else
        Log("safe house icon: the call at 0x59DD1A could not be written: no safe house on the minimap");
}

// With the city: the calibration and header back at once; the pack at once, or after kFreeAfterFrames frames when
// the race goes on (F7, a second F8).
static void CourseStart(int ev);  // FTownCourse.h (Run J item 7): the course line on our minimap
static void CourseStop(const char* why);
static void CourseFrame(const float* car);

static void MinimapUnload(const char* why, bool later)
{
    CourseStop(why);  // the line's blocks back while our textures are there
    MinimapRestore(why);
    if (!g_mmBuffer)
        return;
    MinimapFlush();
    BYTE* b = g_mmBuffer;
    g_mmBuffer = nullptr;
    if (later)
    {
        g_mmPending = b;
        g_mmPendingFrames = kFreeAfterFrames;
    }
    else
        MinimapUnloadPack(b);
}

// ================================================================ the events (docs/ftown-race-notes.md R4, "Task 3",
// "Events"; the list: FTownEvents.h)
//
// An event (the Time Attack, the Drag, the Speed Trap, the Sector Sprint, ... of ftown-events.json) starts with the
// car put at its start (checked for ground like a spawn), its race barriers in (only its own set), held (both
// velocities zeroed every frame) through a 3-2-1 countdown, then the clock runs on the game's simulation time
// (Sim::GetTime 0x6E8DE0: the float at 0x9885D8; the simulation does not step while the game is paused). A gate counts
// when the car's path between two frames crosses its line (GateWidthMetres wide, across the route) in the route's
// direction, so no speed or frame rate can jump one; crossing a gate with an earlier one not crossed ends the run
// ("missed"). A checkpoint shows the split; a speed camera reads the car's speed there (RigidBody::GetSpeed 0x6711B0,
// slot +0x2C of the body, metres a second) and adds it to the score; the finish stops the clock (the Drag also reads
// the trap speed there). The best of every event is kept in FTownTimes.txt beside the ini, one section an event (a new
// file, then renamed over the old one, so a crash mid-write keeps the previous bests). Shown with the game's own HUD
// message (IGenericMessage::RequestGenericMessage, single frame, priority 3, script 0x8AB83EDB: how the Tollbooth
// shows its time, PC 0x57BAB3), asked for again every frame.

static const DWORD kSimTime = 0x9885D8;
static const DWORD kGetHud = 0x6F8F10, kIGenericMessageHandle = 0x5650B0, kGenericMessageVtbl = 0x8A2088;
static const DWORD kMessageScript = 0x8AB83EDB;
static const DWORD kGetSpeed = 0x6711B0;  // RigidBody::GetSpeed: |linear velocity| (metres a second)
static const int kMessagePriority = 3;

static const Site kTimeAttackSites[] = {
    {0x6E8DE0, {0xD9, 0x05, 0xD8, 0x85, 0x98, 0x00, 0xC3}, 7, "Sim::GetTime: fld [0x9885D8]; ret"},
    {0x6F8F10, {0x8B, 0x41, 0x28, 0xC3}, 4, "LocalPlayer::GetHud: mov eax, [ecx + 0x28]"},
    {0x5650B0, {0xB8, 0xB0, 0x50, 0x56, 0x00, 0xC3}, 6, "IGenericMessage::_IHandle"},
    {0x611382, {0x8B, 0x11, 0xFF, 0x52, 0x20}, 5, "HUD_ShowMessage: IPlayer::GetHud (vtable +0x20)"},
    {0x6113A4, {0x8B, 0x48, 0x04, 0x68, 0xB0, 0x50, 0x56, 0x00, 0xE8}, 9,
     "HUD_ShowMessage: Find(IGenericMessage::_IHandle) on the HUD's +4"},
    {0x568030, {0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x14, 0x57, 0x8B, 0x7C}, 9,
     "GenericMessage::RequestGenericMessage: the priority test against [this + 0x14]"},
    {0x6711B0, {0x51, 0x8B, 0x41, 0x30, 0x8B, 0x00, 0xD9, 0x40, 0x28, 0x83, 0xC0, 0x20}, 12,
     "RigidBody::GetSpeed: the linear velocity at [[this + 0x30]] + 0x20"},
};
static const Slot kTimeAttackSlots[] = {
    {kPlayerVtbl1, 0x20, 0x6F8F10, "LocalPlayer vtable 1 +0x20 GetHud"},
    {kPlayerVtbl2, 0x20, 0x6F8F10, "LocalPlayer vtable 2 +0x20 GetHud"},
    {kGenericMessageVtbl, 0x04, 0x568030, "GenericMessage IGenericMessage vtable +0x04 RequestGenericMessage"},
    {kRBVehicleVtbl, 0x2C, kGetSpeed, "RBVehicle IRigidBody vtable +0x2C GetSpeed"},
    {kRigidBodyVtbl, 0x2C, kGetSpeed, "RigidBody IRigidBody vtable +0x2C GetSpeed"},
};

static bool g_taEnabled = true, g_taShowRunning = true, g_taHudMissingLogged;
static int g_taKey = 0x74, g_taNextKey = 0x73;
static float g_taWidth = 40.0f;
static char g_taTimesPath[MAX_PATH];

enum TaState
{
    TA_IDLE,
    TA_COUNTDOWN,
    TA_ARMED,  // at the start, held, waiting for the game's GO (Run I item 12)
    TA_RUNNING,
    TA_SHOWING,  // the result on screen, then idle
};
static TaState g_ta = TA_IDLE;
static int g_ev = -1;  // the event running (or shown, or last run)
static float g_taT0, g_taGo;
static bool g_taPassed[kMaxGates];
static float g_taSplits[kMaxGates], g_taSpeeds[kMaxGates], g_taScore;
static float g_taPrev[2];
static bool g_taHavePrev;
static float g_taBannerUntil = -1;  // TA_SHOWING: the result's time on screen, then idle
static int g_taShownCount = -1;     // the countdown's last number asked for
static char g_msgPending[160];      // the next HUD message (asked once; again only while refused)
static float g_msgPendingUntil = -1;
// every event's best (FTownTimes.txt, read before each run, all written after a new best)
struct Best
{
    int ms;                        // the finish time (-1: none)
    int splitMs[kMaxGates];        // per gate (-1: none)
    float trapKmh;                 // the Drag's speed at the finish
    float scoreKmh;                // the Speed Trap's score (sum of the cameras; <= 0: none)
    float camKmh[kMaxGates];       // per gate (cameras)
};
static Best g_best[kMaxEvents];
// Run I items 6 and 7 (R14): what the race HUD's own timer and COMPLETE % show while an event of ours is on: its time
// (0 before its GO; frozen at its end) and its progress along start -> gates -> finish
static float g_hudPct, g_hudEnd = -1;  // g_hudEnd: the time the run ended (finish or a miss), -1 while it runs
static bool g_hudOn;                    // the two calls in LocalPlayer::UpdateHud are ours

static void HudReset()
{
    g_hudPct = 0;
    g_hudEnd = -1;
}

// percent along the event's course by its gates' chords: the passed gates' lengths, then the projection on the next leg
static float EventProgress(const Event& ev, const float* car)
{
    float total = 0, done = 0, px = ev.start[0], py = ev.start[1];
    bool counting = true;
    for (int k = 0; k < ev.gateCount; k++)
    {
        float dx = ev.gates[k][0] - px, dy = ev.gates[k][1] - py, len = sqrtf(dx * dx + dy * dy);
        if (counting)
        {
            if (g_taPassed[k])
                done += len;
            else
            {
                float t = len > 1e-3f ? ((car[0] - px) * dx + (car[1] - py) * dy) / (len * len) : 0.0f;
                done += len * (t < 0 ? 0 : t > 1 ? 1 : t);
                counting = false;
            }
        }
        total += len;
        px = ev.gates[k][0], py = ev.gates[k][1];
    }
    float pct = total > 0 ? done * 100.0f / total : 0;
    return pct < 0 ? 0 : pct > 100 ? 100 : pct;
}
typedef int(__cdecl* TestBeforeRenameFn)();
static TestBeforeRenameFn g_testBeforeRename;

static void TimeAttackSettings(const char* dir)
{
    g_taEnabled = GetPrivateProfileIntA("TimeAttack", "Enabled", 1, g_iniPath) == 1;
    g_taKey = IniHex("TimeAttack", "Key", "0x74");
    g_taNextKey = IniHex("TimeAttack", "NextEventKey", "0x73");
    g_taWidth = IniFloat("TimeAttack", "GateWidthMetres", 40.0f);
    g_taShowRunning = GetPrivateProfileIntA("TimeAttack", "ShowRunningTime", 1, g_iniPath) == 1;
    snprintf(g_taTimesPath, sizeof(g_taTimesPath), "%sFTownTimes.txt", dir);
    EventsSettings(dir);
}

static void TimeAttackStart()
{
    if (!g_taEnabled)
    {
        Log("events off ([TimeAttack] Enabled = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kTimeAttackSites) ok &= BytesAre(s);
    for (const Slot& s : kTimeAttackSlots) ok &= SlotIs(s);
    if (!ok)
    {
        Log("WRONGBYTES in the Time Attack's sites: the events off (the city still works)");
        g_taEnabled = false;
        return;
    }
    if (!EventsRead())
    {
        g_taEnabled = false;
        return;
    }
    g_testBeforeRename =
        (TestBeforeRenameFn)(void*)GetProcAddress(GetModuleHandleA(nullptr), "FTownTestBeforeRename");
    char gates[64];
    GatesText(g_events[0], gates, sizeof(gates));
    Log("time attack: key 0x%02X starts %s (%s), key 0x%02X the next event; %d events; gates %.0f m wide; speeds in "
        "%s; times in FTownTimes.txt",
        g_taKey, g_events[0].name, gates, g_taNextKey, g_eventCount, g_taWidth, g_mph ? "mph" : "km/h");
}

// "m:ss.cc"
static void TaFormat(char* out, size_t n, float seconds)
{
    int cs = (int)(seconds * 100.0f + 0.5f);
    if (cs < 0)
        cs = 0;
    snprintf(out, n, "%d:%02d.%02d", cs / 6000, cs / 100 % 60, cs % 100);
}

// a speed (km/h) in the shown unit: "241.3 KM/H"
static void SpeedText(char* out, size_t n, float kmh)
{
    snprintf(out, n, "%.1f %s", g_mph ? kmh / 1.609344f : kmh, g_mph ? "MPH" : "KM/H");
}

static float SimNow()
{
    float t = 0;
    SafeRead(kSimTime, &t, 4);
    return t;
}

typedef float(__thiscall* GetSpeedFn)(void*);

// The car's speed (km/h) by the game's own RigidBody::GetSpeed; -1 when the body is not one we know.
static float PlayerSpeedKmh(void* player)
{
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    if (!rb || (vtbl != kRBVehicleVtbl && vtbl != kRigidBodyVtbl))
        return -1.0f;
    return ((GetSpeedFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x2C)))(rb) * 3.6f;
}

typedef bool(__thiscall* RequestMessageFn)(void*, const char*, bool, DWORD, DWORD, DWORD, int);

// Run K item 5: the event is placed before the player's HUD exists (the early start on F-Town); a message waits for it.
// Its time to be shown (TaBanner's seconds) starts when the HUD first takes it or refuses it on priority; while there
// is no HUD it waits up to kMsgWaitHud seconds of simulation time.
static const float kMsgWaitHud = 30.0f;
static float g_msgPendingSecs, g_msgAskedAt;
static int g_msgMissFrames;  // frames the HUD's generic message was not there for the pending message

// The game's generic HUD message, as HUD_ShowMessage (0x611320) finds it: IPlayer::GetHud, then Find on its +4.
// 0: no HUD message yet; 1: refused (the game's own message has a higher priority); 2: shown.
static int TaShow(void* player, const char* text)
{
    void* hud = ((GetPtrFn)(UINT_PTR)kGetHud)(player);
    DWORD list = 0;
    void* gm = nullptr;
    if (hud && ReadDword((DWORD)(UINT_PTR)hud + 4, &list) && list)
        gm = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kIGenericMessageHandle);
    if (!gm || Vtbl(gm) != kGenericMessageVtbl)
    {
        if (!g_taHudMissingLogged)
            Log("%s: the HUD's generic message not found yet (HUD 0x%08lX, found 0x%08lX): the message waits for it",
                g_ev >= 0 ? g_events[g_ev].title : "EVENT", (unsigned long)(UINT_PTR)hud, (unsigned long)(UINT_PTR)gm);
        g_taHudMissingLogged = true;
        g_msgMissFrames++;
        return 0;
    }
    if (g_msgMissFrames)
        Log("%s: the HUD's generic message there after %d frames: \"%s\" asked now",
            g_ev >= 0 ? g_events[g_ev].title : "EVENT", g_msgMissFrames, text);
    g_msgMissFrames = 0;
    // Run I item 6 (R13): asked once, not single frame. The script 0x8AB83EDB pops the text in and runs out by itself;
    // GenericMessage::Update (0x567F80) hides the message when it has run out, and a message asked for every frame
    // was popped in again each time (the flashing). The game asks it this way for all its race lines.
    bool shown = ((RequestMessageFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kGenericMessageVtbl + 4)))(
        gm, text, false, kMessageScript, 0, 0, kMessagePriority);
    if (shown)
        g_msgPending[0] = 0;
    return shown ? 2 : 1;
}

// A message for the HUD: asked for on the next frame, and again while the game refuses it (a message of its own with a
// higher priority is showing), for at most `seconds` from when the HUD first has it (Run K item 5: not from the asking,
// the HUD may not exist yet).
static void TaBanner(const char* text, float seconds)
{
    strncpy(g_msgPending, text, sizeof(g_msgPending) - 1);
    g_msgPending[sizeof(g_msgPending) - 1] = 0;
    g_msgPendingSecs = seconds;
    g_msgPendingUntil = -1;  // the clock starts when the HUD has it
    g_msgAskedAt = SimNow();
}

static void MessageFrame(void* player)
{
    if (!g_msgPending[0])
        return;
    float now = SimNow();
    if (g_msgPendingUntil >= 0 ? now > g_msgPendingUntil : now - g_msgAskedAt > kMsgWaitHud)
    {
        if (g_msgPendingUntil < 0)
            Log("%s: no HUD message in %.0f s: \"%s\" dropped", g_ev >= 0 ? g_events[g_ev].title : "EVENT",
                kMsgWaitHud, g_msgPending);
        g_msgPending[0] = 0;
        return;
    }
    char text[160];
    strcpy(text, g_msgPending);
    if (TaShow(player, text) && g_msgPendingUntil < 0)
        g_msgPendingUntil = now + g_msgPendingSecs;
}

static int TimesInt(const char* section, const char* key)
{
    char buf[32];
    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_taTimesPath);
    return buf[0] ? atoi(buf) : -1;
}

static float TimesFloat(const char* section, const char* key)
{
    char buf[32];
    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_taTimesPath);
    return buf[0] ? (float)atof(buf) : -1.0f;
}

// Every event's best from FTownTimes.txt (so a new best of one event writes the others back unchanged).
static void TaReadBest()
{
    for (int e = 0; e < g_eventCount; e++)
    {
        Best& b = g_best[e];
        const char* sec = g_events[e].best;
        // review fix: the Speed Trap keeps its finish time as TimeMs (read back, or the next write of another
        // event's best would drop it)
        b.ms = TimesInt(sec, g_events[e].kind == EK_SPEEDTRAP ? "TimeMs" : "BestMs");
        b.trapKmh = TimesFloat(sec, "TrapKmh");
        b.scoreKmh = TimesFloat(sec, "BestScoreKmh");
        for (int k = 0; k < kMaxGates; k++)
        {
            char key[24];
            snprintf(key, sizeof(key), "Split%dMs", k + 1);
            b.splitMs[k] = TimesInt(sec, key);
            snprintf(key, sizeof(key), "Camera%dKmh", k + 1);
            b.camKmh[k] = TimesFloat(sec, key);
        }
    }
    const Event& ev = g_events[g_ev];
    const Best& b = g_best[g_ev];
    char t[32], s[32];
    if (ev.kind == EK_SPEEDTRAP && b.scoreKmh > 0)
    {
        SpeedText(s, sizeof(s), b.scoreKmh);
        Log("%s: best so far %s (FTownTimes.txt)", ev.title, s);
    }
    else if (ev.kind != EK_SPEEDTRAP && b.ms > 0)
    {
        TaFormat(t, sizeof(t), b.ms / 1000.0f);
        Log("%s: best so far %s (FTownTimes.txt)", ev.title, t);
    }
    else
        Log("%s: no best %s yet", ev.title, ev.kind == EK_SPEEDTRAP ? "score" : "time");
}

static bool IsEventSection(const char* name)
{
    for (int e = 0; e < g_eventCount; e++)
        if (!_stricmp(name, g_events[e].best))
            return true;
    return false;
}

// A new file, flushed, then renamed over the old one: the old one is never opened for writing. Every event's best,
// and any section of the old file that is no event's (an event taken out of the list keeps its best).
static void TaWriteBest()
{
    static char text[16384];
    const Event& run = g_events[g_ev];
    int n = snprintf(text, sizeof(text), "; F-Town events: the best of each, times in milliseconds, speeds in km/h "
                                         "(FTownLoader.asi; one section an event, ftown-events.json \"best\")\r\n");
    for (int e = 0; e < g_eventCount && n < (int)sizeof(text) - 1024; e++)
    {
        const Event& ev = g_events[e];
        const Best& b = g_best[e];
        bool has = ev.kind == EK_SPEEDTRAP ? b.scoreKmh > 0 : b.ms > 0;
        if (!has)
            continue;
        n += snprintf(text + n, sizeof(text) - n, "[%s]\r\n", ev.best);
        if (ev.kind == EK_SPEEDTRAP)
        {
            n += snprintf(text + n, sizeof(text) - n, "BestScoreKmh = %.1f\r\n", b.scoreKmh);
            if (b.ms > 0)
                n += snprintf(text + n, sizeof(text) - n, "TimeMs = %d\r\n", b.ms);
        }
        else
            n += snprintf(text + n, sizeof(text) - n, "BestMs = %d\r\n", b.ms);
        if (ev.kind == EK_DRAG && b.trapKmh > 0)
            n += snprintf(text + n, sizeof(text) - n, "TrapKmh = %.1f\r\n", b.trapKmh);
        for (int k = 0; k + 1 < ev.gateCount; k++)
        {
            if (ev.gateType[k] == GT_CHECKPOINT && b.splitMs[k] > 0)
                n += snprintf(text + n, sizeof(text) - n, "Split%dMs = %d\r\n", k + 1, b.splitMs[k]);
            if (ev.gateType[k] == GT_CAMERA && b.camKmh[k] >= 0)
                n += snprintf(text + n, sizeof(text) - n, "Camera%dKmh = %.1f\r\n", k + 1, b.camKmh[k]);
        }
    }
    // sections of the old file that are no event's: copied as they are
    // review fix: a line that does not fit ends the copy (snprintf returns the length it wanted, not what it wrote:
    // n is kept inside the buffer, so the write never reads past it)
    static char names[4096], body[4096];
    DWORD got = GetPrivateProfileSectionNamesA(names, sizeof(names), g_taTimesPath);
    bool full = false;
    for (const char* s = names; got && *s && !full; s += strlen(s) + 1)
    {
        if (IsEventSection(s))
            continue;
        DWORD len = GetPrivateProfileSectionA(s, body, sizeof(body), g_taTimesPath);
        int room = (int)sizeof(text) - n, w = snprintf(text + n, room, "[%s]\r\n", s);
        full = w >= room;
        n += full ? 0 : w;
        for (const char* l = body; len && *l && !full; l += strlen(l) + 1)
        {
            room = (int)sizeof(text) - n;
            w = snprintf(text + n, room, "%s\r\n", l);
            full = w >= room;
            n += full ? 0 : w;
        }
    }
    if (full)
        Log("%s: the times file's other sections do not all fit in %d bytes: the rest left out",
            g_events[g_ev].title, (int)sizeof(text));
    char tmp[MAX_PATH + 8];
    snprintf(tmp, sizeof(tmp), "%s.tmp", g_taTimesPath);
    HANDLE f = CreateFileA(tmp, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    DWORD put = 0;
    bool ok = f != INVALID_HANDLE_VALUE && WriteFile(f, text, (DWORD)n, &put, nullptr) && put == (DWORD)n &&
              FlushFileBuffers(f);
    if (f != INVALID_HANDLE_VALUE)
        CloseHandle(f);
    if (!ok)
    {
        Log("%s: times file NOT written (%s, error %lu); the old one kept", run.title, tmp,
            (unsigned long)GetLastError());
        return;
    }
    if (g_testBeforeRename && g_testBeforeRename())
    {
        Log("%s: times file NOT renamed (test: a crash before the rename)", run.title);
        return;
    }
    if (!MoveFileExA(tmp, g_taTimesPath, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
    {
        Log("%s: times file NOT renamed (error %lu); the old one kept", run.title, (unsigned long)GetLastError());
        return;
    }
    Log("%s: times file written (FTownTimes.txt.tmp, then renamed)", run.title);
}

static int g_radarLogged;  // the camera the radar log line last named (reset at each start)
static void ManualOn(void* player);
static void ManualOff(const char* why);

static void TimeAttackStop(const char* why)
{
    CourseStop(why);  // the minimap's course line goes with the run
    ManualOff(why);  // a Drag's manual gears end with it, whatever ended it
    if (g_ta == TA_IDLE)
        return;
    ResetSpotDrop(why);  // (Run K review) a reset spot still pending goes with its run
    if (g_ta == TA_COUNTDOWN || g_ta == TA_RUNNING || g_ta == TA_ARMED)
        Log("%s: stopped (%s)", g_events[g_ev].title, why);
    g_ta = TA_IDLE;
    g_taBannerUntil = -1;
    g_msgPending[0] = 0;  // nothing more on the HUD
    HudReset();
}

static void SetResetSpot(void* player, const float* pos, float headingDeg, const char* what);

// Event k from its start: the car there, its barriers in, the reset spot there; then our own 3-2-1 (armed false: the
// keys, or F-Town loaded at the game's GO), or held until the game's GO (armed: Run I item 12, F-Town loaded before the
// game's countdown, which then counts on F-Town).
static void EventPlace(void* player, int k, bool armed)
{
    if (!g_taEnabled || k < 0 || k >= g_eventCount)
        return;
    if (!g_city.buffer)
    {
        Log("time attack key: F-Town is not loaded (F8 first)");
        return;
    }
    const Event& ev = g_events[k];
    const float* s = ev.start;
    float sp[3] = {-s[1], s[2], s[0]}, h = 0;
    if (!HeightAt(sp, &h))
    {
        Log("%s: no ground at the start (render %.2f, %.2f, %.2f); not started", ev.title, s[0], s[1], s[2]);
        return;
    }
    TimeAttackStop("another start");
    g_ev = k;
    BarriersLoad(k);  // the route's side roads closed (R7): before the car is put down
    char what[48];
    snprintf(what, sizeof(what), "%s START", ev.title);
    Teleport(player, sp, s[3], true, what);
    SetResetSpot(player, sp, s[3], ev.title);  // a reset before the car has driven puts it here, not in Rockport
    g_ta = armed ? TA_ARMED : TA_COUNTDOWN;
    g_taT0 = SimNow();
    g_taHavePrev = false;
    g_taScore = 0;
    memset(g_taPassed, 0, sizeof(g_taPassed));
    g_taBannerUntil = -1;
    g_taShownCount = -1;
    g_radarLogged = -1;
    g_taHudMissingLogged = false;  // (Run K item 5: logged once a run)
    g_msgMissFrames = 0;
    HudReset();
    if (ev.kind == EK_DRAG)
        ManualOn(player);
    if (armed)
    {
        TaBanner(ev.title, 3.0f);
        Log("%s: the car at the start, held for the game's countdown (face at %.2f, the start %.2f above)", ev.title, h,
            sp[1] - h);
    }
    else
        Log("%s: the car at the start; 3-2-1 (face at %.2f, the start %.2f above)", ev.title, h, sp[1] - h);
    TaReadBest();
    CourseStart(k);  // Run J item 7: the whole course on the minimap
}

static void EventStart(void* player, int k) { EventPlace(player, k, false); }

// The game's GO for an armed event: its clock starts now (the game's own GO is on screen).
static void EventGo()
{
    if (g_ta != TA_ARMED)
        return;
    g_ta = TA_RUNNING;
    g_taGo = SimNow();
    g_taHavePrev = false;
    Log("%s: GO (the game's GO)", g_events[g_ev].title);
}

// F5 (keys on): the first event, as the Time Attack always was
static void TimeAttackKey(void* player) { EventStart(player, 0); }

// F4 (keys on): the event after the last one started (the first after the last)
static void NextEventKey(void* player)
{
    if (g_taEnabled && g_eventCount)
        EventStart(player, g_ev < 0 ? (g_eventCount > 1 ? 1 : 0) : (g_ev + 1) % g_eventCount);
}

// Did the path p -> q cross gate g's line in the route's direction?
static bool Crosses(const float* p, const float* q, const float* g)
{
    float hr = g[2] * 3.14159265f / 180.0f, fx = cosf(hr), fy = sinf(hr);
    float dp = (p[0] - g[0]) * fx + (p[1] - g[1]) * fy, dq = (q[0] - g[0]) * fx + (q[1] - g[1]) * fy;
    if (!(dp < 0 && dq >= 0))
        return false;
    float t = dp / (dp - dq);
    float x = p[0] + (q[0] - p[0]) * t - g[0], y = p[1] + (q[1] - p[1]) * t - g[1];
    float across = -x * fy + y * fx;
    return fabsf(across) <= g_taWidth * 0.5f;
}

static void TaDiff(char* out, size_t n, float seconds, int bestMs)
{
    if (bestMs <= 0)
    {
        out[0] = 0;
        return;
    }
    float d = seconds - bestMs / 1000.0f;
    char t[32];
    TaFormat(t, sizeof(t), fabsf(d));
    snprintf(out, n, "  %c%s", d < 0 ? '-' : '+', t);
}

// gate k's number among the gates of its own type (checkpoint 3, camera 2)
static int GateNumber(const Event& ev, int k)
{
    int n = 0;
    for (int j = 0; j <= k; j++) n += ev.gateType[j] == ev.gateType[k];
    return n;
}

static void TaFinish(void* player, float t)
{
    g_hudEnd = t;  // the race HUD's timer stops here, its COMPLETE at 100
    CourseStop("the finish");
    ManualOff("the finish");
    g_hudPct = 100;
    const Event& ev = g_events[g_ev];
    Best& best = g_best[g_ev];
    char ts[32], b[160], sp[32];
    TaFormat(ts, sizeof(ts), t);
    int ms = (int)(t * 1000.0f + 0.5f);
    if (ev.kind == EK_SPEEDTRAP)
    {
        SpeedText(sp, sizeof(sp), g_taScore);
        bool better = best.scoreKmh <= 0 || g_taScore > best.scoreKmh + 1e-3f;
        Log("%s: FINISH %s (%.3f s of simulation time), score %.1f km/h", ev.title, ts, t, g_taScore);
        if (better)
        {
            best.scoreKmh = g_taScore;
            best.ms = ms;
            for (int j = 0; j < kMaxGates; j++) best.camKmh[j] = ev.gateType[j] == GT_CAMERA ? g_taSpeeds[j] : -1.0f;
            Log("%s: NEW BEST score %.1f km/h", ev.title, g_taScore);
            snprintf(b, sizeof(b), "SCORE %s\nNEW BEST", sp);
            TaBanner(b, 8.0f);
            TaWriteBest();
        }
        else
        {
            char bs[32];
            SpeedText(bs, sizeof(bs), best.scoreKmh);
            snprintf(b, sizeof(b), "SCORE %s\nBEST %s", sp, bs);
            TaBanner(b, 8.0f);
        }
        g_ta = TA_SHOWING;
    g_taBannerUntil = SimNow() + 8.0f;
        return;
    }
    float trap = ev.kind == EK_DRAG ? PlayerSpeedKmh(player) : -1.0f;
    char trapText[48] = "";
    if (ev.kind == EK_DRAG)
    {
        SpeedText(sp, sizeof(sp), trap < 0 ? 0 : trap);
        snprintf(trapText, sizeof(trapText), "  TRAP %s", sp);
        Log("%s: FINISH %s (%.3f s of simulation time), trap speed %.1f km/h", ev.title, ts, t, trap);
    }
    else
        Log("%s: FINISH %s (%.3f s of simulation time)", ev.title, ts, t);
    bool better = best.ms <= 0 || ms < best.ms;
    if (better)
    {
        best.ms = ms;
        best.trapKmh = trap;
        for (int j = 0; j < kMaxGates; j++)
            best.splitMs[j] = j + 1 < ev.gateCount && ev.gateType[j] == GT_CHECKPOINT ? (int)(g_taSplits[j] * 1000.0f + 0.5f)
                                                                                      : -1;
        Log("%s: NEW BEST %d ms", ev.title, ms);
        snprintf(b, sizeof(b), "FINISH %s%s\nNEW BEST", ts, trapText);
        TaBanner(b, 8.0f);
        TaWriteBest();
    }
    else
    {
        char bs[32];
        TaFormat(bs, sizeof(bs), best.ms / 1000.0f);
        snprintf(b, sizeof(b), "FINISH %s%s\nBEST %s", ts, trapText, bs);
        TaBanner(b, 8.0f);
    }
    g_ta = TA_SHOWING;
    g_taBannerUntil = SimNow() + 8.0f;
}

static void TaGate(void* player, int k, float t)
{
    const Event& ev = g_events[g_ev];
    for (int j = 0; j < k; j++)
        if (!g_taPassed[j])
        {
            const char* what = ev.gateType[j] == GT_CAMERA ? "SPEED CAMERA" : "CHECKPOINT";
            char b[96];
            snprintf(b, sizeof(b), g_keysEnabled ? "MISSED %s %d\nF5 TO RESTART" : "MISSED %s %d\nPAUSE: RESTART RACE",
                     what, GateNumber(ev, j));
            TaBanner(b, 8.0f);
            g_hudEnd = t;
            CourseStop("a missed gate");
            Log("%s: missed %s %d; no %s (crossed gate %d first)", ev.title,
                ev.gateType[j] == GT_CAMERA ? "camera" : "checkpoint", GateNumber(ev, j),
                ev.kind == EK_SPEEDTRAP ? "score" : "time", k + 1);
            g_ta = TA_SHOWING;
            g_taBannerUntil = SimNow() + 8.0f;
            return;
        }
    g_taPassed[k] = true;
    g_taSplits[k] = t;
    if (ev.gateType[k] == GT_FINISH)
    {
        TaFinish(player, t);
        return;
    }
    char ts[32], diff[48], b[160];
    TaFormat(ts, sizeof(ts), t);
    if (ev.gateType[k] == GT_CAMERA)
    {
        float kmh = PlayerSpeedKmh(player);
        if (kmh < 0)
            kmh = 0;
        g_taSpeeds[k] = kmh;
        g_taScore += kmh;
        char sp[32], tot[32];
        SpeedText(sp, sizeof(sp), kmh);
        SpeedText(tot, sizeof(tot), g_taScore);
        float was = g_best[g_ev].camKmh[k];
        diff[0] = 0;
        if (was >= 0)
            snprintf(diff, sizeof(diff), "  %c%.1f", kmh >= was ? '+' : '-', fabsf((kmh - was) / (g_mph ? 1.609344f : 1.0f)));
        snprintf(b, sizeof(b), "SPEED CAMERA %d/%d\n%s%s  TOTAL %s", GateNumber(ev, k), ev.cameras, sp, diff, tot);
        TaBanner(b, 3.0f);
        Log("%s: camera %d/%d %.1f km/h (total %.1f) at %s", ev.title, GateNumber(ev, k), ev.cameras, kmh, g_taScore,
            ts);
        return;
    }
    TaDiff(diff, sizeof(diff), t, g_best[g_ev].splitMs[k]);
    snprintf(b, sizeof(b), "CHECKPOINT %d/%d\n%s%s", GateNumber(ev, k), ev.checkpoints, ts, diff);
    TaBanner(b, 3.0f);
    Log("%s: checkpoint %d/%d %s%s", ev.title, GateNumber(ev, k), ev.checkpoints, ts, diff);
}

// Run J item 1: an NIS (the race's intro) exists: INIS's singleton (UTL::Collections::Singleton<INIS>::mInstance
// 0x9885C8, read by EPlayRaceNIS at 0x640FBC). While it plays the game moves the car itself (on F-Town now).
static const DWORD kNisInstance = 0x9885C8;
static bool NisOn()
{
    DWORD v = 0;
    return ReadDword(kNisInstance, &v) && v;
}

// Once a frame while the player exists.
static void TimeAttackFrame(void* player)
{
    if (g_ta == TA_IDLE)
        return;
    const Event& ev = g_events[g_ev];
    float now = SimNow();
    if (g_ta == TA_ARMED)
    {
        // held at the start until the game's GO (GameFrame calls EventGo); the game holds the car too (and while the
        // race's intro plays, the intro moves it: not held then)
        DWORD vtbl = 0;
        void* rb = NisOn() ? nullptr : PlayerRigidBody(player, &vtbl);
        if (rb && (vtbl == kRBVehicleVtbl || vtbl == kRigidBodyVtbl))
        {
            static const float zero[3] = {0, 0, 0};
            ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x60)))(rb, zero);
            ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x64)))(rb, zero);
        }
        MessageFrame(player);
        return;
    }
    if (g_ta == TA_COUNTDOWN)
    {
        DWORD vtbl = 0;
        void* rb = PlayerRigidBody(player, &vtbl);
        if (rb && (vtbl == kRBVehicleVtbl || vtbl == kRigidBodyVtbl))
        {
            static const float zero[3] = {0, 0, 0};
            ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x60)))(rb, zero);
            ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x64)))(rb, zero);
        }
        float el = now - g_taT0;
        if (el < 3.0f)
        {
            // each number asked once (the first with the event's title above it)
            int n = 3 - (int)el;
            if (n != g_taShownCount)
            {
                char b[96];
                if (g_taShownCount < 0)
                    snprintf(b, sizeof(b), "%s\n%d", ev.title, n);
                else
                    snprintf(b, sizeof(b), "%d", n);
                TaBanner(b, 1.0f);
                g_taShownCount = n;
            }
            MessageFrame(player);
            return;
        }
        g_ta = TA_RUNNING;
        g_taGo = now;
        Log("%s: GO", ev.title);
        TaBanner("GO!", 1.0f);
    }
    float p[3], cur[2];
    if (g_ta == TA_RUNNING && PlayerPosition(player, p))
    {
        cur[0] = p[2];
        cur[1] = -p[0];
        // review fix: a jump no car drives (a reset; the pause menu's restart, which puts the car back in Rockport
        // without unloading anything) or the simulation's clock going back ends the run
        float moved = g_taHavePrev ? hypotf(cur[0] - g_taPrev[0], cur[1] - g_taPrev[1]) : 0.0f;
        if (moved > 50.0f || now < g_taGo)
        {
            char why[96];
            if (moved > 50.0f)
                snprintf(why, sizeof(why), "the car was moved: %.0f m in one frame", moved);
            else
                snprintf(why, sizeof(why), "the simulation's clock went back");
            TimeAttackStop(why);
            return;
        }
        if (g_taHavePrev)
            for (int k = 0; k < ev.gateCount && g_ta == TA_RUNNING; k++)
                if (!g_taPassed[k] && Crosses(g_taPrev, cur, ev.gates[k]))
                    TaGate(player, k, now - g_taGo);
        g_taPrev[0] = cur[0];
        g_taPrev[1] = cur[1];
        g_taHavePrev = true;
        if (g_ta == TA_RUNNING)
        {
            g_hudPct = EventProgress(ev, cur);
            CourseFrame(cur);
        }
    }
    // Run I item 6: no running line any more (it was asked every frame and popped in again and again); the running
    // time is the race HUD's own timer (HkHudTime), the messages are asked once each
    MessageFrame(player);
    if (g_ta == TA_SHOWING && now >= g_taBannerUntil)
        g_ta = TA_IDLE;
}

// ================================================================ the race HUD's own elements (Run I items 6-9)
//
// LocalPlayer::UpdateHud (0x6F13F0) feeds the race HUD every frame. Three of its calls go to functions of ours, each of
// which runs the game's function and changes nothing unless an event of ours is on F-Town:
// - 0x6F1DB6 GRacerInfo::GetHudPctRaceComplete (0x6004D0) -> RaceInformation's COMPLETE %: our event's progress;
// - 0x6F1E00 GTimer::GetTime (0x5DDEC0, the racer's timer) -> its clock: our event's time, frozen at its end;
// - 0x6F2170 the radar detector's update (0x6EDE30, thiscall, 2 arguments) -> after it, while a camera of ours is ahead
//   within 300 m, IRadarDetector::SetTarget(2 = camera, distance / 300, direction) as the game sets it for its own.
// And while a Drag runs the player's Transmission setting is manual (InputPlayer::IsAutomaticShift 0x68D090 reads it
// every frame: byte +0x11 of IPlayer::GetSettings, 1 = manual); the value found is put back when the run ends.

static const DWORD kHudPctSite = 0x6F1DB6, kHudPct = 0x6004D0, kHudTimeSite = 0x6F1E00, kHudTime = 0x5DDEC0;
static const DWORD kRadarSite = 0x6F2170, kRadarUpdate = 0x6EDE30, kRadarHandle = 0x565A30, kRadarVtbl = 0x8A1F2C;
static const DWORD kGetSettings = 0x6E99A0;
static const float kRadarRange = 300.0f;  // 0x8B058C = 1 / 300: the game's range scale (0x8B01C4 = 300 m)

static const Site kHudSites[] = {
    {0x6F1DB0, {0x8B, 0xCD, 0x89, 0x44, 0x24, 0x40, 0xE8, 0x15, 0xE7, 0xF0, 0xFF}, 11,
     "LocalPlayer::UpdateHud: call GRacerInfo::GetHudPctRaceComplete (0x6004D0) for RaceInformation's COMPLETE %"},
    {0x6F1DF6, {0x8D, 0x8D, 0x4C, 0x01, 0x00, 0x00, 0x89, 0x44, 0x24, 0x40, 0xE8, 0xBB, 0xC0, 0xEE, 0xFF}, 15,
     "LocalPlayer::UpdateHud: call GTimer::GetTime (0x5DDEC0) on the racer's timer (+0x14C) for the lap time"},
    {0x6004D0, {0x51, 0xA1, 0x00, 0xE0, 0x91, 0x00, 0x56, 0x8B, 0xF1}, 9, "GRacerInfo::GetHudPctRaceComplete"},
    {0x5DDEC0, {0x56, 0x8B, 0xF1, 0x8A, 0x46, 0x08, 0x84, 0xC0}, 8, "GTimer::GetTime"},
};
static const Site kRadarSites[] = {
    {0x6F216E, {0x8B, 0xCD, 0xE8, 0xBB, 0xBC, 0xFF, 0xFF}, 7, "LocalPlayer::UpdateHud: call the radar update (0x6EDE30)"},
    {0x6EDE30, {0xA1, 0x00, 0xE0, 0x91, 0x00, 0x83, 0xEC, 0x48, 0x85, 0xC0, 0x56, 0x8B, 0xF1}, 13,
     "the radar update: [GRaceStatus 0x91E000], sub esp, 0x48"},
    {0x565A30, {0xB8, 0x30, 0x5A, 0x56, 0x00, 0xC3}, 6, "IRadarDetector::_IHandle"},
    {0x59CDB0, {0x8B, 0x44, 0x24, 0x08, 0x8B, 0x54, 0x24, 0x0C, 0x89, 0x41, 0x24, 0x8B}, 12,
     "RadarDetector::SetTarget: range +0x24, direction +0x28, type +0x2C"},
};
static const Slot kRadarSlots[] = {
    {kRadarVtbl, 0x04, 0x59CDB0, "RadarDetector IRadarDetector vtable +0x04 SetTarget"},
    {kRBVehicleVtbl, 0x38, 0x671220, "RBVehicle IRigidBody +0x38 GetRightVector"},
    {kRigidBodyVtbl, 0x38, 0x671220, "RigidBody vtable +0x38 GetRightVector"},
};
static const Site kManualSites[] = {
    {0x6E99A0, {0x8B, 0x41, 0x1C, 0x85, 0xC0, 0x7C, 0x14, 0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x51, 0x10}, 16,
     "LocalPlayer::GetSettings: [this + 0x1C] the index, [[FEDatabase 0x91CF90] + 0x10] the profile"},
    {0x68D0C3, {0x8B, 0x16, 0x8B, 0xCE, 0xFF, 0x52, 0x14, 0x80, 0x78, 0x11, 0x01}, 11,
     "InputPlayer::IsAutomaticShift: GetSettings (+0x14), cmp byte [settings + 0x11], 1 (manual)"},
};
static const Slot kManualSlots[] = {
    {kPlayerVtbl1, 0x14, 0x6E99A0, "LocalPlayer vtable 1 +0x14 GetSettings"},
    {kPlayerVtbl2, 0x14, 0x6E99A0, "LocalPlayer vtable 2 +0x14 GetSettings"},
};

static bool g_radarOn, g_manualOn;
static BYTE* g_manualAt;  // the Transmission byte we set (null: none)
static BYTE g_manualWas;

static bool HudCall(DWORD at, const void* to)
{
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)to - (at + 5);
    return WriteCode(at, call, 5);
}

static bool HudOurs()
{
    return g_city.buffer && g_ev >= 0 && g_ev < g_eventCount && (g_ta != TA_IDLE || g_hudEnd >= 0);
}

static float __fastcall HkHudPct(void* racer, void*)
{
    if (HudOurs())
        return g_ta == TA_RUNNING || g_hudEnd >= 0 ? g_hudPct : 0.0f;
    return ((float(__thiscall*)(void*))(UINT_PTR)kHudPct)(racer);
}

static float __fastcall HkHudTime(void* timer, void*)
{
    if (HudOurs())
    {
        if (g_hudEnd >= 0)
            return g_hudEnd;
        return g_ta == TA_RUNNING ? SimNow() - g_taGo : 0.0f;
    }
    return ((float(__thiscall*)(void*))(UINT_PTR)kHudTime)(timer);
}

typedef void(__thiscall* SetTargetFn)(void*, int, float, float);

// The next gate of the running event, when it is a camera within the radar's range: the target as the game makes it
// (range = distance / 300; direction = the angle between the car's forward and the camera, negative on the left).
static void RadarOurs()
{
    if (!g_city.buffer || g_ev < 0 || (g_ta != TA_RUNNING && g_ta != TA_COUNTDOWN && g_ta != TA_ARMED))
        return;
    const Event& ev = g_events[g_ev];
    int k = 0;
    while (k < ev.gateCount && g_taPassed[k]) k++;
    if (k >= ev.gateCount || ev.gateType[k] != GT_CAMERA)
        return;
    void* player = Player();
    float p[3];
    if (!player || !PlayerPosition(player, p))
        return;
    float to[3] = {-ev.gates[k][1] - p[0], 0, ev.gates[k][0] - p[2]};  // physics, horizontal
    float d = sqrtf(to[0] * to[0] + to[2] * to[2]);
    if (d > kRadarRange || d < 1e-3f)
        return;
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    if (!rb || (vtbl != kRBVehicleVtbl && vtbl != kRigidBodyVtbl))
        return;
    float f[3] = {0, 0, 0}, r[3] = {0, 0, 0};
    ((GetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x34)))(rb, f);
    ((GetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x38)))(rb, r);
    float fl = sqrtf(f[0] * f[0] + f[2] * f[2]);
    float c = fl > 1e-3f ? (f[0] * to[0] + f[2] * to[2]) / (fl * d) : 1.0f;
    c = c < -1 ? -1 : c > 1 ? 1 : c;
    float dir = acosf(c);
    if (r[0] * to[0] + r[2] * to[2] < 0)
        dir = -dir;
    void* hud = ((GetPtrFn)(UINT_PTR)kGetHud)(player);
    DWORD list = 0;
    void* radar = nullptr;
    if (hud && ReadDword((DWORD)(UINT_PTR)hud + 4, &list) && list)
        radar = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kRadarHandle);
    if (!radar || Vtbl(radar) != kRadarVtbl)
        return;
    ((SetTargetFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kRadarVtbl + 4)))(radar, 2, d / kRadarRange, dir);
    if (g_radarLogged != k)
    {
        g_radarLogged = k;
        Log("%s: radar on camera %d (%.0f m ahead)", ev.title, GateNumber(ev, k), d);
    }
}

static void __fastcall HkRadar(void* self, void*, DWORD a, DWORD b)
{
    ((void(__thiscall*)(void*, DWORD, DWORD))(UINT_PTR)kRadarUpdate)(self, a, b);
    if (g_radarOn)
        RadarOurs();
}

// the Drag: manual gears while it runs (R16)
static void ManualOn(void* player)
{
    if (!g_manualOn || g_manualAt)
        return;
    BYTE* s = (BYTE*)((GetPtrFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x14)))(player);
    BYTE was = 0;
    if (!s || !SafeRead((DWORD)(UINT_PTR)s + 0x11, &was, 1))
    {
        Log("manual gears: no player settings; the gears stay as set");
        return;
    }
    g_manualAt = s + 0x11;
    g_manualWas = was;
    *g_manualAt = 1;
    Log("manual gears on for the Drag (Transmission was %u)", (unsigned)was);
}

static void ManualOff(const char* why)
{
    if (!g_manualAt)
        return;
    BYTE now = 0;
    if (SafeRead((DWORD)(UINT_PTR)g_manualAt, &now, 1) && now == 1)
    {
        *g_manualAt = g_manualWas;
        Log("manual gears off (%s): Transmission %u put back", why, (unsigned)g_manualWas);
    }
    else
        Log("manual gears off (%s): Transmission changed meanwhile (%u): left", why, (unsigned)now);
    g_manualAt = nullptr;
}

// Run J item 4: the game's own drag race carries our Drag (FTownGame.h SetCarrierRace), so its HUD, heat, perfect
// shifts and gears are the game's. Its steering is not: in a drag the human car is steered by its AI towards the lane of
// the road network (AIVehicleHuman::Update: IsDragSteering 0x407FF0 true -> DoSteering to the WRoadNav; false ->
// DetermineDragLane, which reads the nav's segment; ChangeDragLanes 0x408060 the same), and F-Town has no road network:
// it would steer towards Rockport's roads. While our drag race runs on F-Town, IsDragSteering says false (the player
// steers: IsPlayerSteering 0x435240 true) and the Update's drag block (the call at 0x42F49F) is skipped to its join
// 0x42F4D4 (neither DoSteering nor DetermineDragLane). Any other race: the game's, unchanged.
static bool g_dragRace;  // our carrier race is the drag carrier ([Game] DragCarrierEvent)
static bool g_dragSteerOn;
static BYTE* g_dragSteerTramp;
static const DWORD kIsDragSteering = 0x407FF0, kDragBlockCall = 0x42F49F, kDragBlockJoin = 0x42F4D4;
static const Site kDragSites[] = {
    {0x407FF0, {0x56, 0x57, 0x8B, 0xF9, 0x8B, 0x47, 0x4C}, 7,
     "AIVehicleHuman::IsDragSteering: push esi; push edi; mov edi, ecx; mov eax, [edi + 0x4C]"},
    {0x42F48C, {0x83, 0xF8, 0x01, 0x75, 0x39, 0x8B, 0x4C, 0x24, 0x18, 0xC7, 0x87, 0x80, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00,
                0x00, 0xE8, 0x4C, 0x8B, 0xFD, 0xFF},
     24, "AIVehicleHuman::Update: driver style drag -> the drag lane, call IsDragSteering (0x407FF0)"},
    {0x42F4BD, {0xEB, 0x15}, 2, "AIVehicleHuman::Update: DoSteering's branch joins at 0x42F4D4"},
    {0x42F4C8, {0xEB, 0x0A}, 2, "AIVehicleHuman::Update: DetermineDragLane's branch joins at 0x42F4D4"},
    {0x408060, {0x56, 0x8B, 0xF1, 0x8D, 0x8E, 0x34, 0xF8, 0xFF, 0xFF, 0xE8, 0x82, 0xFF, 0xFF, 0xFF}, 14,
     "AIVehicleHuman::ChangeDragLanes: call IsDragSteering"},
};

static bool RaceOurs();  // FTownGame.h: a bonus race of ours chosen or running
static bool __cdecl DragFreeNow() { return g_dragSteerOn && g_dragRace && g_city.buffer && RaceOurs(); }

static bool __fastcall HkIsDragSteering(void* self, void*)
{
    if (DragFreeNow())
        return false;
    return ((bool(__thiscall*)(void*))(void*)g_dragSteerTramp)(self);
}

static void DragSteerInstall()
{
    bool ok = true;
    for (const Site& s : kDragSites) ok &= BytesAre(s);
    if (!ok)
    {
        Log("WRONGBYTES in the drag steering's sites: our drag race keeps the game's AI lane steering");
        return;
    }
    BYTE* t = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t)
        return;
    // the trampoline: IsDragSteering's first 7 bytes (no position-dependent operand), then on at 0x407FF7
    memcpy(t, (const void*)(UINT_PTR)kIsDragSteering, 7);
    t[7] = 0xE9;
    *(DWORD*)(t + 8) = (kIsDragSteering + 7) - ((DWORD)(UINT_PTR)t + 12);
    // the stub for the call at 0x42F49F: push ecx; call DragFreeNow; pop ecx; test al, al; je game; add esp, 4 (the
    // return address 0x42F4A4); push 0x42F4D4; ret (on at the join); game: jmp IsDragSteering (returns to 0x42F4A4)
    BYTE* s = t + 16;
    BYTE* p = s;
    *p++ = 0x51, *p++ = 0xE8;
    *(DWORD*)p = (DWORD)(UINT_PTR)&DragFreeNow - ((DWORD)(UINT_PTR)p + 4), p += 4;
    *p++ = 0x59, *p++ = 0x84, *p++ = 0xC0, *p++ = 0x74, *p++ = 0x09;
    *p++ = 0x83, *p++ = 0xC4, *p++ = 0x04, *p++ = 0x68;
    *(DWORD*)p = kDragBlockJoin, p += 4;
    *p++ = 0xC3, *p++ = 0xE9;
    *(DWORD*)p = kIsDragSteering - ((DWORD)(UINT_PTR)p + 4), p += 4;
    FlushInstructionCache(GetCurrentProcess(), t, 64);
    g_dragSteerTramp = t;
    BYTE jmp[7] = {0xE9, 0, 0, 0, 0, 0x90, 0x90};
    *(DWORD*)(jmp + 1) = (DWORD)(UINT_PTR)&HkIsDragSteering - (kIsDragSteering + 5);
    if (WriteCode(kIsDragSteering, jmp, 7) && HudCall(kDragBlockCall, s))
    {
        g_dragSteerOn = true;
        Log("drag steering: the player steers our drag race on F-Town (0x407FF0, 0x42F49F; no road network there)");
    }
}

static void HudStart()
{
    if (!g_taEnabled)
        return;
    bool ok = true;
    for (const Site& s : kHudSites) ok &= BytesAre(s);
    if (!ok || !g_taShowRunning)
        Log(ok ? "race HUD: the game's own timer and COMPLETE % ([TimeAttack] ShowRunningTime = 0)"
               : "WRONGBYTES in the race HUD's sites: its timer and COMPLETE % stay the game's");
    else if (HudCall(kHudPctSite, (const void*)&HkHudPct) && HudCall(kHudTimeSite, (const void*)&HkHudTime))
    {
        g_hudOn = true;
        Log("race HUD: its timer and COMPLETE %% show the running event (0x6F1DB6, 0x6F1E00)");
    }
    ok = true;
    for (const Site& s : kRadarSites) ok &= BytesAre(s);
    for (const Slot& s : kRadarSlots) ok &= SlotIs(s);
    if (!ok)
        Log("WRONGBYTES in the radar's sites: no radar for our speed cameras");
    else if (HudCall(kRadarSite, (const void*)&HkRadar))
    {
        g_radarOn = true;
        Log("radar: our speed cameras within %.0f m on the radar detector (0x6F2170)", kRadarRange);
    }
    ok = true;
    for (const Site& s : kManualSites) ok &= BytesAre(s);
    for (const Slot& s : kManualSlots) ok &= SlotIs(s);
    g_manualOn = ok;
    Log(ok ? "manual gears: the Drag switches the player's Transmission to manual while it runs"
           : "WRONGBYTES in the gears' sites: the Drag keeps the player's gears setting");
}
