// FTownEvening.h - F-Town (Evening): the game's own sunset held while F-Town is loaded, and the city's lights
// (docs/ftown-notes.md "Evening (2026-11-05)").
//
// The PC game keeps its time of day in one object, eTimeOfDayLighting, at *(0x9B392C): +0x00 the rate (1.0), +0x04
// the direction (+1 / -1), +0x08 the time (0.05..0.95 in a race; 0.95 is the west end, the sun 7.7 degrees up, the
// lighting wholly the database's dusk_sunny). Its update (0x769360, once a frame from eDisplayFrame 0x6DE3DC) moves the
// time by rate x direction, and SetTimeOfDay (0x7696B0) writes +0x08 at a race's start. While F-Town (Evening) is
// loaded we write the time and rate 0 every frame (and ForceHeadlightsOn, 0x9B092C, read by
// CarRenderInfo::RenderFlaresOnCar at 0x742AC3), and put back what we found when F-Town goes. Data only: no code of
// the game is patched for the evening.
//
// The lights: ftown-evening.bin ([Evening] Lights; tools/citymap/evening.py): the city's glowing vertices (file
// offsets of 36-byte vertex records), each with its day colour, its evening colour and a move (a window pane: from
// behind its wall to in front of it). Applied to the fresh copy of the city file before LoadChunks, only for the
// evening, and only when every entry's day colour is found where it should be (else none: a stale list).

static const DWORD kTodPtr = 0x9B392C, kForceHeadlights = 0x9B092C;

static const Site kEveSites[] = {
    {0x7696B0, {0xD9, 0x44, 0x24, 0x04, 0xA1, 0x2C, 0x39, 0x9B, 0x00, 0xD9, 0x58, 0x08, 0xC3}, 13,
     "SetTimeOfDay: the time at [TimeOfDayPointer 0x9B392C] + 8"},
    {0x769390,
     {0x8B, 0x4E, 0x04, 0xD9, 0x05, 0xBC, 0x59, 0x92, 0x00, 0xD8, 0x0D, 0xF0, 0x70, 0x89, 0x00, 0x89, 0x4C, 0x24, 0x18,
      0xDA, 0x4C, 0x24, 0x18, 0xD8, 0x0E},
     25, "eTimeOfDayLighting update: time step x direction (+4) x rate (+0)"},
    {0x6DE3D6, {0x8B, 0x0D, 0x2C, 0x39, 0x9B, 0x00, 0xE8, 0x7F, 0xAF, 0x08, 0x00}, 11,
     "eDisplayFrame: the time-of-day update once a frame"},
    {0x742AC3, {0xA1, 0x2C, 0x09, 0x9B, 0x00, 0x85, 0xC0}, 7, "RenderFlaresOnCar: ForceHeadlightsOn (0x9B092C)"},
};

struct EveEntry
{
    DWORD off;
    float d[3];
    DWORD day, eve;
};

static bool g_eveEnabled = true, g_eveKeys, g_eveHeadlights = true;
static bool g_eveOk;      // the sites checked
static bool g_eveWanted;  // the evening chosen for the next load (the menu's F-Town (Evening), or [Evening] Keys)
static bool g_eveOn;      // the time held now
static float g_eveTime = 0.95f;
static char g_eveLightsPath[MAX_PATH], g_eveLightsName[64];
static EveEntry* g_eveEntries;
static int g_eveCount;
static DWORD g_eveTod, g_eveSavedHead;
static float g_eveSavedRate, g_eveSavedTime;
static int g_eveSavedDir;
// what the game's update (and any wrapper of it, X360Stuff's) left in the object since our last write: read just
// before each write, so the AFTER lines show whether the time stays (the review: reading after our write said nothing)
static float g_eveSeenTime = -1, g_eveSeenRate = -1, g_eveSeenDusk = -1, g_eveSeenSunZ = -2;

static bool SafeWrite(DWORD address, const void* in, DWORD size)
{
    if (address < 0x10000 || address + size < address)
        return false;
    return FtSafeCopy((void*)(UINT_PTR)address, in, size) != 0;
}

static void EveningSettings(const char* dir)
{
    g_eveEnabled = GetPrivateProfileIntA("Evening", "Enabled", 1, g_iniPath) == 1;
    g_eveKeys = GetPrivateProfileIntA("Evening", "Keys", 0, g_iniPath) == 1;
    g_eveHeadlights = GetPrivateProfileIntA("Evening", "Headlights", 1, g_iniPath) == 1;
    g_eveTime = IniFloat("Evening", "Time", 0.95f);
    if (!(g_eveTime >= 0.05f && g_eveTime <= 0.95f))  // the range the game's own update keeps in a race
        g_eveTime = 0.95f;
    GetPrivateProfileStringA("Evening", "Lights", "ftown-evening.bin", g_eveLightsName, sizeof(g_eveLightsName),
                             g_iniPath);
    snprintf(g_eveLightsPath, sizeof(g_eveLightsPath), "%s%s", dir, g_eveLightsName);
}

// At start, after the city file is parsed (its size known): the sites, then the lights list.
static void EveningStart()
{
    if (!g_eveEnabled)
    {
        Log("evening off ([Evening] Enabled = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kEveSites) ok &= BytesAre(s);
    if (!ok)
    {
        Log("WRONGBYTES in the evening's sites: F-Town (Evening) off (the rest works)");
        return;
    }
    g_eveOk = true;
    FILE* f = fopen(g_eveLightsPath, "rb");
    if (!f)
    {
        Log("evening: time %.2f; lights file %s cannot be opened: the evening without lights", g_eveTime,
            g_eveLightsName);
        return;
    }
    struct
    {
        char magic[4];
        DWORD version, citySize, count, zero;
    } h;
    const char* bad = nullptr;
    if (fread(&h, sizeof(h), 1, f) != 1 || memcmp(h.magic, "FTEV", 4) || h.version != 1)
        bad = "not an F-Town lights file";
    else if (h.citySize != g_city.size)
        bad = "made for another city file (its size differs): build_city.py writes both";
    else if (h.count > 4000000)
        bad = "too many entries";
    if (!bad)
    {
        g_eveEntries = (EveEntry*)malloc(sizeof(EveEntry) * (h.count ? h.count : 1));
        if (!g_eveEntries || fread(g_eveEntries, sizeof(EveEntry), h.count, f) != h.count || fgetc(f) != EOF)
            bad = "its length does not match its count";
        else
        {
            g_eveCount = (int)h.count;
            for (int k = 0; k < g_eveCount && !bad; k++)
                if (g_eveEntries[k].off % 4 || g_city.size < 36 || g_eveEntries[k].off > g_city.size - 36)  // no wrap
                    bad = "an entry lies outside the city file";
        }
    }
    fclose(f);
    if (bad)
    {
        free(g_eveEntries);
        g_eveEntries = nullptr;
        g_eveCount = 0;
        Log("evening: time %.2f; lights file %s REFUSED: %s: the evening without lights", g_eveTime, g_eveLightsName,
            bad);
        return;
    }
    Log("evening: time %.2f, headlights %s; lights file %s: %d vertices", g_eveTime, g_eveHeadlights ? "on" : "as they are",
        g_eveLightsName, g_eveCount);
}

// The fresh copy of the city file, before LoadChunks: the lights, all or none.
static void EveningApply(BYTE* buffer)
{
    if (!g_eveWanted || !g_eveOk || !g_eveCount)
        return;
    double t0 = NowMs();
    for (int k = 0; k < g_eveCount; k++)
    {
        const EveEntry& e = g_eveEntries[k];
        DWORD c;
        memcpy(&c, buffer + e.off + 24, 4);
        if (c != e.day)
        {
            Log("EVENING LIGHTS REFUSED: vertex %d at 0x%08lX holds 0x%08lX, the list says 0x%08lX (a stale list): none "
                "applied", k, (unsigned long)e.off, (unsigned long)c, (unsigned long)e.day);
            return;
        }
    }
    for (int k = 0; k < g_eveCount; k++)
    {
        const EveEntry& e = g_eveEntries[k];
        float* p = (float*)(buffer + e.off);
        p[0] += e.d[0];
        p[1] += e.d[1];
        p[2] += e.d[2];
        memcpy(buffer + e.off + 24, &e.eve, 4);
    }
    Log("EVENING LIGHTS: %d vertices lit, %.1f ms", g_eveCount, NowMs() - t0);
}

// After a load that put the car on F-Town: the time held.
static void EveningOn()
{
    if (!g_eveWanted || !g_eveOk || g_eveOn)
        return;
    DWORD tod = 0, dir = 0, head = 0;
    float rate = 0, t = 0;
    if (!ReadDword(kTodPtr, &tod) || !tod || !SafeRead(tod, &rate, 4) || !ReadDword(tod + 4, &dir) ||
        !SafeRead(tod + 8, &t, 4) || !ReadDword(kForceHeadlights, &head) || !(t >= 0.0f && t <= 1.0f) ||
        !(rate >= 0.0f && rate < 100.0f))
    {
        Log("EVENING NOT SET: the time-of-day object (0x9B392C) is not there or not as expected");
        return;
    }
    g_eveTod = tod;
    g_eveSavedRate = rate;
    g_eveSavedDir = (int)dir;
    g_eveSavedTime = t;
    g_eveSavedHead = head;
    g_eveOn = true;
    Log("EVENING ON: time %.3f -> %.3f, rate %.2f -> 0 (held), direction %d; headlights %s (ForceHeadlightsOn was %lu)",
        t, g_eveTime, rate, (int)dir, g_eveHeadlights ? "forced on" : "as they are", (unsigned long)head);
}

// Once a frame while loaded: the time and rate again (a race's start or anything else may set them).
static void EveningFrame()
{
    if (!g_eveOn)
        return;
    DWORD tod = 0;
    if (!ReadDword(kTodPtr, &tod) || tod != g_eveTod)
    {
        Log("EVENING: the time-of-day object changed (0x%08lX, was 0x%08lX): no longer held", (unsigned long)tod,
            (unsigned long)g_eveTod);
        g_eveOn = false;
        return;
    }
    SafeRead(tod + 8, &g_eveSeenTime, 4);
    SafeRead(tod, &g_eveSeenRate, 4);
    SafeRead(tod + 0x164, &g_eveSeenDusk, 4);  // the blend's dusk weight (0x769580)
    SafeRead(tod + 0x188, &g_eveSeenSunZ, 4);  // the sun's height (normalised, +0x180)
    const float zero = 0.0f;
    SafeWrite(tod, &zero, 4);
    SafeWrite(tod + 8, &g_eveTime, 4);
    if (g_eveHeadlights)
    {
        const DWORD one = 1;
        SafeWrite(kForceHeadlights, &one, 4);
    }
}

// 1 s and 3 s after the load: what the game's last update (X360Stuff wraps it) left before this frame's write, so
// these lines say whether the time stays: the time and rate it left, the dusk weight it blended and the sun's height.
static void EveningAfter(int k)
{
    if (!g_eveOn)
        return;
    Log("EVENING AFTER %d s: the update left time %.3f, rate %.2f; dusk weight %.2f, sun height %.3f", k ? 3 : 1,
        g_eveSeenTime, g_eveSeenRate, g_eveSeenDusk, g_eveSeenSunZ);
}

// F-Town going (every way): what we found put back.
static void EveningOff(const char* why)
{
    if (!g_eveOn)
        return;
    g_eveOn = false;
    DWORD tod = 0;
    if (!ReadDword(kTodPtr, &tod) || tod != g_eveTod)
    {
        Log("EVENING OFF (%s): the time-of-day object changed meanwhile: nothing written back", why);
        return;
    }
    DWORD dir = (DWORD)g_eveSavedDir;
    SafeWrite(tod, &g_eveSavedRate, 4);
    SafeWrite(tod + 4, &dir, 4);
    SafeWrite(tod + 8, &g_eveSavedTime, 4);
    if (g_eveHeadlights)
        SafeWrite(kForceHeadlights, &g_eveSavedHead, 4);
    Log("EVENING OFF (%s): time %.3f, rate %.2f, direction %d and ForceHeadlightsOn %lu put back", why, g_eveSavedTime,
        g_eveSavedRate, g_eveSavedDir, (unsigned long)g_eveSavedHead);
}
