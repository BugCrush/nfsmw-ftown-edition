// FTownTraffic.h - F-Town's traffic cars: real game vehicles (Rockport's traffic models and the add-on cars) standing
// on F-Town's roads, made by the game's own factory with no driver (they never drive; pushed or hit they move as any
// car). Included by FTownLoader.cpp after FTownGame.h, sharing its helpers (Log, SafeRead, the sites' checks, the
// player, the game mode's state).
//
// Research: docs/ftown-race-notes.md R8-R11. Plan: docs/superpowers/plans/2026-11-04-ftown-traffic-cars.md.
// - Making a car: the ISimable factory list [0x92C66C] holds PVehicle's node (name stringhash32("PVehicle"), function
//   PVehicle::Construct 0x689820), called cdecl with a Sim::Param by value {stringhash32("VehicleParams"), 0xA6B47FAC,
//   &params, 0}; params +0x10 driver class 4 (DRIVER_NONE: the game gives it AIVehicleEmpty, no AI), +0x14 the
//   pvehicle key (Attrib::StringToKey 0x454640), +0x18 &direction, +0x1C &position (physics), +0x24 cache 0 (so the
//   game's MakeRoom refuses rather than deleting its own cars), +0x2C flags 2 (put on the ground).
// - The game holds 20 vehicles at once (its list 0x92CD18); it may delete ours when it needs room. So a car is used
//   only while its IVehicle is in that list with PVehicle's vtables, our key and driver class 4 (Alive).
// - Removal: IVehicle::Deactivate, then ISimable::Kill (deferred deletion), before F-Town's chunks or the track go.
// - A pool of at most [Traffic] Count follows the player: a car farther than ReleaseMetres moves to a free spot nearer.

static const DWORD kFactoryList = 0x92C66C, kConstruct = 0x689820, kVehList = 0x92CD18;
static const DWORD kStringHash = 0x5CC240, kStringToKey = 0x454640;
static const DWORD kIVehicleVtbl = 0x8AA828, kISimableVtbl = 0x8AA940, kIVehicleHandle = 0x4040E0;
static const DWORD kParamTag = 0xA6B47FAC;

static const Site kTrafficSites[] = {
    {0x689820, {0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x6A, 0xFF, 0x68, 0x7C, 0xBD, 0x87, 0x00}, 13,
     "PVehicle::Construct(Sim::Param)"},
    {0x689853, {0x3D, 0xAC, 0x7F, 0xB4, 0xA6}, 5, "PVehicle::Construct: cmp eax, 0xA6B47FAC (the param's tag)"},
    {0x689877,
     {0x8B, 0x40, 0x08, 0x8B, 0x50, 0x18, 0x8B, 0x48, 0x14, 0x8B, 0x78, 0x10, 0x8B, 0x68, 0x28, 0x8B, 0x58, 0x2C, 0x8B,
      0x70, 0x20},
     21, "PVehicle::Construct: VehicleParams +0x10 driver, +0x14 key, +0x18 dir, +0x20, +0x28, +0x2C flags"},
    {0x689BFA, {0xF6, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00, 0x02}, 8, "PVehicle::Construct: test flags, 2 (on ground)"},
    {0x689C16,
     {0x50, 0x8B, 0x44, 0x24, 0x74, 0x8D, 0x8E, 0xAC, 0x00, 0x00, 0x00, 0x50, 0xFF, 0x52, 0x68, 0x85, 0xF6, 0x74, 0x05,
      0x83, 0xC6, 0x2C},
     22, "PVehicle::Construct: IVehicle (+0xAC) SetVehicleOnGround (+0x68); returns the ISimable (+0x2C)"},
    {0x6893AD, {0xA1, 0x24, 0xCD, 0x92, 0x00, 0x3B, 0x05, 0x20, 0xCD, 0x92, 0x00}, 11,
     "PVehicle: the vehicle list 0x92CD18 (size +0xC, capacity +8)"},
    {0x6893D5, {0xA1, 0x1C, 0xCD, 0x92, 0x00}, 5, "PVehicle: the vehicle list's entries (+4)"},
    {0x687817, {0x83, 0xF8, 0x14, 0x76, 0x07, 0x8D}, 6, "PVehicle::MakeRoom: cmp eax, 20 (the vehicles at most)"},
    {0x687838, {0x3B, 0xEB, 0x0F, 0x84, 0xE2, 0x04, 0x00, 0x00}, 8, "PVehicle::MakeRoom: no cache -> refused"},
    {0x5CC240, {0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x74, 0x23}, 8, "stringhash32"},
    {0x454640, {0x8B, 0x4C, 0x24, 0x04, 0x85, 0xC9, 0x74, 0x23}, 8, "Attrib::StringToKey"},
    {0x6851D0, {0x51, 0x56, 0x8B, 0xF1, 0x57, 0x8D, 0x46, 0xD4}, 8, "PVehicle::Kill"},
    {0x688010, {0x8B, 0x41, 0x4C, 0x85, 0xC0}, 5, "PVehicle::GetPosition"},
    {0x887610, {0xA1, 0xBC, 0xDD, 0x91, 0x00, 0x68, 0x2C, 0x30, 0x89, 0x00, 0xA3, 0x94, 0x88, 0x8F, 0x00}, 15,
     "the AI table's start: driver class 4 -> \"AIVehicleEmpty\""},
    {0x89302C, {'A', 'I', 'V', 'e', 'h', 'i', 'c', 'l', 'e', 'E', 'm', 'p', 't', 'y', 0}, 15, "\"AIVehicleEmpty\""},
    {0x8F8890, {0x04, 0x00, 0x00, 0x00}, 4, "the AI table's first driver class: 4 (DRIVER_NONE)"},
    // Run I item 14 (R19): a parked car's input (PInput: nobody writes its controls, so nothing held it)
    {0x69B24B, {0x8B, 0x48, 0x04, 0x68, 0x90, 0x3F, 0x40, 0x00}, 8,
     "RBTractor::SetHitch: Find(IInput::_IHandle 0x403F90) on a vehicle's interface list"},
    {0x69CBB0, {0x8D, 0x41, 0x08, 0xC3}, 4, "PInput::GetControls: the controls at +8"},
    {0x69CB90, {0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x1C, 0xC2}, 8, "PInput::SetControlGas: +0x1C"},
    {0x69CBA0, {0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x20, 0xC2}, 8, "PInput::SetControlBrake: +0x20"},
    {0x69CBC0, {0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x24, 0xC2}, 8, "PInput::SetControlHandBrake: +0x24"},
};

static const Slot kTrafficSlots[] = {
    {kIVehicleVtbl, 0x50, 0x6880A0, "PVehicle IVehicle +0x50 GetVehicleKey"},
    {kIVehicleVtbl, 0x58, 0x6880B0, "PVehicle IVehicle +0x58 GetDriverClass"},
    {kIVehicleVtbl, 0x5C, 0x6691D0, "PVehicle IVehicle +0x5C IsLoading"},
    {kIVehicleVtbl, 0x68, 0x685810, "PVehicle IVehicle +0x68 SetVehicleOnGround"},
    {kIVehicleVtbl, 0x80, 0x6693A0, "PVehicle IVehicle +0x80 Activate"},
    {kIVehicleVtbl, 0x84, 0x6693C0, "PVehicle IVehicle +0x84 Deactivate"},
    {kIVehicleVtbl, 0x88, 0x688200, "PVehicle IVehicle +0x88 IsActive"},
    {kISimableVtbl, 0x08, 0x6851D0, "PVehicle ISimable +0x08 Kill"},
    {kISimableVtbl, 0x60, 0x688010, "PVehicle ISimable +0x60 GetPosition"},
    {0x8AB5C8, 0x08, 0x69CBB0, "PInput IInput +0x08 GetControls"},
    {0x8AB5C8, 0x18, 0x69CB90, "PInput IInput +0x18 SetControlGas"},
    {0x8AB5C8, 0x1C, 0x69CBA0, "PInput IInput +0x1C SetControlBrake"},
    {0x8AB5C8, 0x24, 0x69CBC0, "PInput IInput +0x24 SetControlHandBrake"},
};
static const DWORD kIInputHandle = 0x403F90, kPInputVtbl = 0x8AB5C8;

// ---------------------------------------------------------------- settings and state

struct TSpot
{
    float x, y, z, h;  // render; heading degrees counter-clockwise from +x
    int route, kind;
    bool bad;  // no ground there (SetVehicleOnGround said so)
    int car;   // the car standing there, or -1
};
struct TCar
{
    void* sim;  // ISimable*
    void* veh;  // IVehicle* (sim + 0x80)
    DWORD key;
    int spot;
    bool hidden, addon;
    char name[32];
    void* input;  // its IInput (PInput), held braked (Run I item 14); null until found
    bool noInputLogged, gasLogged, driftLogged;
};
static const int kMaxModels = 32, kMaxCars = 20, kMaxSpots = 4096;
static bool g_trEnabled = true, g_trOn, g_trHold = true;  // g_trHold: [Traffic] Hold (Run I item 14)
static char g_trFile[MAX_PATH] = "ftown-traffic.json", g_trDir[MAX_PATH];
static int g_trCount = 16, g_trReserve = 2, g_trAddOnCount = 6;
static float g_trNear = 40, g_trFar = 300, g_trRelease = 380, g_trView = 160, g_trSpacing = 12, g_trUpdate = 0.5f,
             g_trToggle = 0;
static char g_trModels[kMaxModels][32], g_trAddOns[kMaxModels][32];
static int g_trModelCount, g_trAddOnNames;
static TSpot* g_tsp;
static int g_tspCount, g_tspRoute;
static TCar g_tc[kMaxCars];
static int g_tcCount;
static int g_trPlan[kMaxCars];  // car n's model: >= 0 a traffic model, < 0 add-on -1 - k
static int g_trNextModel;  // the next traffic model for a refused car's place
static bool g_trModelLogged[kMaxModels], g_trAddOnLogged[kMaxModels];  // a refusal of that name logged
static int g_trRefusedUnlogged;
static float g_trNextCreate = -1, g_trNextUpdate = -1, g_trNextToggle = -1, g_trLastNow = -1;
static bool g_trHidden, g_trToggledOff, g_trFullLogged;
static int g_trMoveLines, g_trMovesUnlogged, g_trMade;
static DWORD g_trRng = 12345;
static int g_trFrames;
static double g_trCostSum, g_trCostMax;

static int SplitList(const char* s, char out[][32], int max)
{
    int n = 0;
    while (*s && n < max)
    {
        while (*s == ' ' || *s == ',') s++;
        int k = 0;
        while (*s && *s != ',' && k < 31)
            if (*s != ' ')
                out[n][k++] = *s++;
            else
                s++;
        out[n][k] = 0;
        if (k)
            n++;
        while (*s && *s != ',') s++;
    }
    return n;
}

static void TrafficSettings(const char* dir)
{
    strcpy(g_trDir, dir);
    g_trEnabled = GetPrivateProfileIntA("Traffic", "Enabled", 1, g_iniPath) == 1;
    g_trHold = GetPrivateProfileIntA("Traffic", "Hold", 1, g_iniPath) == 1;
    GetPrivateProfileStringA("Traffic", "File", "ftown-traffic.json", g_trFile, sizeof(g_trFile), g_iniPath);
    g_trCount = GetPrivateProfileIntA("Traffic", "Count", 16, g_iniPath);
    g_trCount = g_trCount < 0 ? 0 : g_trCount > kMaxCars ? kMaxCars : g_trCount;
    g_trReserve = GetPrivateProfileIntA("Traffic", "Reserve", 2, g_iniPath);
    g_trAddOnCount = GetPrivateProfileIntA("Traffic", "AddOnCount", 6, g_iniPath);
    char buf[1024];
    GetPrivateProfileStringA("Traffic", "Models",
                             "traftaxi, traf4dseda, traf4dsedb, trafficcoup, trafstwag, trafminivan, trafpickupa, trafha, "
                             "trafcourt, trafvanb, trafnews, trafpizza, trafgarb, trafcemtr",
                             buf, sizeof(buf), g_iniPath);
    g_trModelCount = SplitList(buf, g_trModels, kMaxModels);
    GetPrivateProfileStringA("Traffic", "AddOns", "thar, raptor, challenger71, chiron, flipcar, longnosecab", buf,
                             sizeof(buf), g_iniPath);
    g_trAddOnNames = SplitList(buf, g_trAddOns, kMaxModels);
    g_trNear = IniFloat("Traffic", "NearMetres", 40);
    g_trFar = IniFloat("Traffic", "FarMetres", 300);
    g_trRelease = IniFloat("Traffic", "ReleaseMetres", 380);
    g_trView = IniFloat("Traffic", "ViewMetres", 160);
    g_trSpacing = IniFloat("Traffic", "SpacingMetres", 12);
    g_trUpdate = IniFloat("Traffic", "UpdateMs", 500) / 1000.0f;
    g_trToggle = IniFloat("Traffic", "ToggleSeconds", 0);
    if (g_trAddOnCount > g_trAddOnNames)
        g_trAddOnCount = g_trAddOnNames;
    if (g_trAddOnCount > g_trCount)
        g_trAddOnCount = g_trCount;
    if (g_trAddOnCount < 0)
        g_trAddOnCount = 0;
}

// The spots file (tools/citymap/traffic_spots.py): every line starting with '[' that holds six numbers.
static bool ReadSpots()
{
    char path[MAX_PATH];
    snprintf(path, sizeof(path), "%s%s", g_trDir, g_trFile);
    FILE* f = fopen(path, "rb");
    if (!f)
    {
        Log("traffic: no spots (%s cannot be read): traffic off", g_trFile);
        return false;
    }
    g_tsp = (TSpot*)calloc(kMaxSpots, sizeof(TSpot));
    char line[256];
    while (g_tsp && g_tspCount < kMaxSpots && fgets(line, sizeof(line), f))
    {
        const char* s = line;
        while (*s == ' ' || *s == '\t') s++;
        TSpot t = {};
        if (*s == '[' && sscanf(s + 1, " %f , %f , %f , %f , %d , %d", &t.x, &t.y, &t.z, &t.h, &t.route, &t.kind) == 6)
        {
            t.car = -1;
            g_tspRoute += t.route != 0;
            g_tsp[g_tspCount++] = t;
        }
    }
    fclose(f);
    if (!g_tspCount)
    {
        Log("traffic: no spots (%s has none): traffic off", g_trFile);
        return false;
    }
    Log("traffic: %d spots in %s (%d by the events' routes)", g_tspCount, g_trFile, g_tspRoute);
    return true;
}

// which model car n gets: the add-ons at n = round(k * Count / AddOnCount), the traffic models in turn elsewhere
static void PlanModels()
{
    int t = 0;
    for (int n = 0; n < g_trCount; n++) g_trPlan[n] = 0;
    bool addon[kMaxCars] = {};
    for (int k = 0; k < g_trAddOnCount; k++)
    {
        int n = (int)floorf((float)k * g_trCount / g_trAddOnCount + 0.5f);
        if (n >= g_trCount)
            n = g_trCount - 1;
        addon[n] = true;
        g_trPlan[n] = -1 - k;
    }
    for (int n = 0; n < g_trCount; n++)
        if (!addon[n])
            g_trPlan[n] = g_trModelCount ? (t++ % g_trModelCount) : 0;
    g_trNextModel = t;
}

static void TrafficStart()
{
    if (!g_trEnabled)
    {
        Log("traffic off ([Traffic] Enabled = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kTrafficSites) ok &= BytesAre(s);
    for (const Slot& s : kTrafficSlots) ok &= SlotIs(s);
    if (!ok)
    {
        Log("WRONGBYTES in the traffic's sites: traffic off (the rest works)");
        return;
    }
    if (!g_trModelCount && !g_trAddOnCount)
    {
        Log("traffic: no models ([Traffic] Models and AddOns empty): traffic off");
        return;
    }
    if (!ReadSpots())
        return;
    PlanModels();
    g_trOn = true;
    Log("traffic: up to %d cars (%d add-ons: %d named), %d traffic models; %d vehicle slots left to the game; spots "
        "%.0f..%.0f m from the car, moved past %.0f m, none within %.0f m in front, %.0f m apart",
        g_trCount, g_trAddOnCount, g_trAddOnNames, g_trModelCount, g_trReserve, g_trNear, g_trFar, g_trRelease,
        g_trView, g_trSpacing);
    Log(g_trHold ? "traffic: standing cars held (gas 0, brake 1, handbrake 1 every frame; their input PInput)"
                 : "traffic: standing cars not held ([Traffic] Hold = 0)");
}

// ---------------------------------------------------------------- the game's vehicles

typedef void*(__cdecl* ConstructFn)(DWORD, DWORD, DWORD, DWORD);
typedef DWORD(__cdecl* HashFn)(const char*);
typedef bool(__thiscall* OnGroundFn)(void*, const float*, const float*);
typedef DWORD(__thiscall* DwordThisFn)(void*);

// the vehicle list's entries; false when it cannot be read or is not as the game keeps it
static bool VehList(DWORD* entries, int* count)
{
    DWORD l[4];
    if (!SafeRead(kVehList, l, 16) || l[3] > 20 || l[2] > 64)
        return false;
    *count = (int)l[3];
    return *count == 0 || SafeRead(l[1], entries, 4 * l[3]);
}

static bool InList(void* veh)
{
    DWORD e[20];
    int n = 0;
    if (!VehList(e, &n))
        return false;
    for (int k = 0; k < n; k++)
        if (e[k] == (DWORD)(UINT_PTR)veh)
            return true;
    return false;
}

// car k is ours and alive: in the game's list, PVehicle's vtables, our key, driver class 4
static bool Alive(const TCar& c)
{
    if (!c.veh || !InList(c.veh) || Vtbl(c.veh) != kIVehicleVtbl || Vtbl(c.sim) != kISimableVtbl)
        return false;
    DWORD key = ((DwordThisFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kIVehicleVtbl + 0x50)))(c.veh);
    DWORD driver = ((DwordThisFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kIVehicleVtbl + 0x58)))(c.veh);
    return key == c.key && driver == 4;
}

static void VehCall(void* veh, DWORD slot) { ((VoidThisFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kIVehicleVtbl + slot)))(veh); }

static bool CarPosition(const TCar& c, float* render)
{
    const float* p = ((const float*(__thiscall*)(void*))(UINT_PTR)(*(DWORD*)(UINT_PTR)(kISimableVtbl + 0x60)))(c.sim);
    float q[3];
    if (!p || !SafeRead((DWORD)(UINT_PTR)p, q, 12))
        return false;
    render[0] = q[2], render[1] = -q[0];
    return true;
}

static void SpotPhysics(const TSpot& s, float* pos, float* dir)
{
    float h = s.h * 3.14159265f / 180.0f;
    pos[0] = -s.y, pos[1] = s.z + 1.0f, pos[2] = s.x;
    dir[0] = -sinf(h), dir[1] = 0, dir[2] = cosf(h);
}

static bool PutOnSpot(TCar& c, int spot)
{
    float pos[3], dir[3];
    SpotPhysics(g_tsp[spot], pos, dir);
    return ((OnGroundFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kIVehicleVtbl + 0x68)))(c.veh, pos, dir);
}

// the forgotten car's spot is free again; the array stays packed (the spots' car numbers follow)
static void ForgetCar(int k)
{
    if (g_tc[k].spot >= 0)
        g_tsp[g_tc[k].spot].car = -1;
    for (int j = k; j + 1 < g_tcCount; j++)
    {
        g_tc[j] = g_tc[j + 1];
        if (g_tc[j].spot >= 0)
            g_tsp[g_tc[j].spot].car = j;
    }
    g_tcCount--;
}

static void KillCar(TCar& c)
{
    VehCall(c.veh, 0x84);  // Deactivate: out of the simulation first
    ((VoidThisFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kISimableVtbl + 0x08)))(c.sim);
}

static void TrafficRemove(const char* why)
{
    if (!g_tcCount)
        return;
    int killed = 0, gone = 0;
    while (g_tcCount)
    {
        if (Alive(g_tc[0]))
        {
            KillCar(g_tc[0]);
            killed++;
        }
        else
            gone++;
        ForgetCar(0);
    }
    for (int k = 0; k < g_tspCount; k++) g_tsp[k].car = -1;
    Log("traffic: removed %d cars (%s)%s", killed, why, gone ? "; some were already gone" : "");
    if (g_trFrames)
        Log("traffic: our work per frame while F-Town was loaded: %d frames, mean %.1f us, max %.1f us (the cars' own "
            "cost is the game's: measure it with [Traffic] ToggleSeconds)",
            g_trFrames, g_trCostSum / g_trFrames, g_trCostMax);
    g_trFrames = 0;
    g_trCostSum = g_trCostMax = 0;
    g_trHidden = g_trToggledOff = g_trFullLogged = false;
    g_trNextCreate = g_trNextUpdate = g_trNextToggle = -1;
    g_trMoveLines = 0;
    if (g_trMovesUnlogged)
        Log("traffic: %d more moves not logged", g_trMovesUnlogged);
    g_trMovesUnlogged = 0;
    if (g_trRefusedUnlogged)
        Log("traffic: %d more refusals of names already logged", g_trRefusedUnlogged);
    g_trRefusedUnlogged = 0;
}

// The running event's bit in a spot's route field (tools/citymap/traffic_spots.py: bit k for event k), 0 when none
// runs: an event running or shown, else the one whose barriers are in, else the mode the game is playing.
static int EventRouteMask()
{
    int k = -1;
    if (g_ta != TA_IDLE)
        k = g_ev;
    else if (!BarriersLoaded(&k) && g_gs == GS_PLAYING && IsEventMode(g_gsMode))
        k = g_gsMode - OPT_EVENT0;
    return k >= 0 && k < 31 ? 1 << k : 0;
}

// A free spot Near..Far from the car (render p), Spacing from our cars, not the route's in a Time Attack; with `view`
// none within View metres in front (f: the car's render forward). One of the six nearest, at random.
static int PickSpot(const float* p, const float* f, bool view)
{
    int mask = EventRouteMask();
    float carPos[kMaxCars][2];
    int cars = 0;
    for (int k = 0; k < g_tcCount; k++)
        if (CarPosition(g_tc[k], carPos[cars]))
            cars++;
    int best[6];
    float bestD[6];
    int nb = 0;
    for (int s = 0; s < g_tspCount; s++)
    {
        const TSpot& t = g_tsp[s];
        if (t.bad || t.car >= 0 || (t.route & mask) || !RoadNetSpotOk(s))
            continue;
        float dx = t.x - p[0], dy = t.y - p[1], d = sqrtf(dx * dx + dy * dy);
        if (d < g_trNear || d > g_trFar)
            continue;
        if (view && d < g_trView && (dx * f[0] + dy * f[1]) > 0.25f * d)
            continue;
        bool clear = true;
        for (int k = 0; k < cars && clear; k++)
        {
            float ex = t.x - carPos[k][0], ey = t.y - carPos[k][1];
            clear = ex * ex + ey * ey >= g_trSpacing * g_trSpacing;
        }
        if (!clear)
            continue;
        int at;
        if (nb == 6)
        {
            if (d >= bestD[5])
                continue;
            at = 5;
        }
        else
            at = nb++;
        while (at > 0 && bestD[at - 1] > d)
        {
            best[at] = best[at - 1];
            bestD[at] = bestD[at - 1];
            at--;
        }
        best[at] = s;
        bestD[at] = d;
    }
    if (!nb)
        return -1;
    g_trRng = g_trRng * 1103515245u + 12345u;
    return best[(g_trRng >> 16) % nb];
}

static const char* PlanName(int n, bool* addon)
{
    *addon = g_trPlan[n] < 0;
    return *addon ? g_trAddOns[-1 - g_trPlan[n]] : g_trModels[g_trPlan[n]];
}

static void HoldCar(int k);

static void* FactoryConstruct()
{
    DWORD name = ((HashFn)(UINT_PTR)kStringHash)("PVehicle"), node = 0;
    if (!ReadDword(kFactoryList, &node))
        return nullptr;
    for (int k = 0; k < 64 && node; k++)
    {
        DWORD n[3];
        if (!SafeRead(node, n, 12))
            return nullptr;
        if (n[0] == name)
            return (void*)(UINT_PTR)n[1];
        node = n[2];
    }
    return nullptr;
}

// Makes car number g_tcCount on a spot near the player (p, f render). False when the game refused (tried later).
static bool MakeCar(const float* p, const float* f)
{
    int n = g_tcCount;
    bool addon = false;
    const char* name = PlanName(n, &addon);
    int spot = PickSpot(p, f, false);
    if (spot < 0)
        return false;
    void* fn = FactoryConstruct();
    if ((DWORD)(UINT_PTR)fn != kConstruct)
    {
        Log("traffic: the factory's PVehicle function is 0x%08lX, not PVehicle::Construct 0x%08lX: traffic off",
            (unsigned long)(UINT_PTR)fn, (unsigned long)kConstruct);
        g_trOn = false;
        return false;
    }
    float pos[3], dir[3];
    SpotPhysics(g_tsp[spot], pos, dir);
    DWORD vp[12] = {};
    DWORD key = ((HashFn)(UINT_PTR)kStringToKey)(name);
    vp[0] = ((HashFn)(UINT_PTR)kStringHash)("VehicleParams");
    vp[1] = kParamTag;
    vp[2] = (DWORD)(UINT_PTR)vp;
    vp[4] = 4;  // DRIVER_NONE
    vp[5] = key;
    vp[6] = (DWORD)(UINT_PTR)dir;
    vp[7] = (DWORD)(UINT_PTR)pos;
    vp[11] = 2;  // put on the ground
    void* sim = ((ConstructFn)fn)(vp[0], vp[1], vp[2], 0);
    const TSpot& t = g_tsp[spot];
    if (!sim)
    {
        // review: every refused car takes the next traffic model (a refused traffic model held the pool for good and
        // logged every update); each name is logged once
        bool& logged = addon ? g_trAddOnLogged[-1 - g_trPlan[n]] : g_trModelLogged[g_trPlan[n]];
        if (!logged)
            Log("traffic: car %d (%s) NOT made (the game refused it: no room in its vehicle list or its car memory, or "
                "an unknown name); the next traffic model takes its place (logged once a name)", n, name);
        else
            g_trRefusedUnlogged++;
        logged = true;
        int next = g_trModelCount ? g_trNextModel % g_trModelCount : 0;
        for (int k = 0; k < g_trModelCount && g_trModelLogged[next]; k++)  // a refused name is not taken again
            next = ++g_trNextModel % g_trModelCount;
        g_trNextModel++;
        g_trPlan[n] = next;
        return false;
    }
    DWORD list = 0;
    void* veh = nullptr;
    if (ReadDword((DWORD)(UINT_PTR)sim + 4, &list) && list)
        veh = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kIVehicleHandle);
    TCar& c = g_tc[n];
    c = TCar{sim, veh, key, spot, false, addon, {0}, nullptr, false, false, false};
    strncpy(c.name, name, sizeof(c.name) - 1);
    if (veh != (BYTE*)sim + 0x80 || !Alive(c))
    {
        Log("traffic: car %d (%s): not a vehicle as expected (IVehicle 0x%08lX of ISimable 0x%08lX): traffic off", n,
            name, (unsigned long)(UINT_PTR)veh, (unsigned long)(UINT_PTR)sim);
        if (Vtbl(sim) == kISimableVtbl)
            ((VoidThisFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kISimableVtbl + 0x08)))(sim);
        g_trOn = false;
        return false;
    }
    g_tcCount++;
    g_trMade++;
    g_tsp[spot].car = n;
    if (!PutOnSpot(c, spot))
    {
        Log("traffic: car %d (%s) has no ground at spot %d: removed (the spot is not used again)", n, name, spot);
        g_tsp[spot].bad = true;
        KillCar(c);
        ForgetCar(n);
        return true;
    }
    VehCall(c.veh, 0x80);  // Activate
    HoldCar(n);  // held from its first frame
    Log("traffic: car %d made: %s%s at spot %d, render (%.1f, %.1f, %.1f) heading %.1f, %.0f m from the car", n, name,
        addon ? " (add-on)" : "", spot, t.x, t.y, t.z, t.h, sqrtf((t.x - p[0]) * (t.x - p[0]) + (t.y - p[1]) * (t.y - p[1])));
    return true;
}

static void MoveCar(int k, const float* p, const float* f, bool view, const char* why)
{
    TCar& c = g_tc[k];
    int spot = PickSpot(p, f, view);
    if (spot < 0)
    {
        if (!c.hidden)
        {
            VehCall(c.veh, 0x84);
            c.hidden = true;
        }
        return;
    }
    int from = c.spot;
    if (from >= 0)
        g_tsp[from].car = -1;
    c.spot = spot;
    g_tsp[spot].car = k;
    if (!PutOnSpot(c, spot))
    {
        g_tsp[spot].bad = true;
        g_tsp[spot].car = -1;
        c.spot = -1;
        VehCall(c.veh, 0x84);
        c.hidden = true;
        Log("traffic: car %d (%s): no ground at spot %d (not used again); hidden until another spot", k, c.name, spot);
        return;
    }
    if (c.hidden)
        VehCall(c.veh, 0x80);
    c.hidden = false;
    c.driftLogged = false;
    HoldCar(k);
    const TSpot& t = g_tsp[spot];
    if (g_trMoveLines++ < 200)
        Log("traffic: car %d (%s) moved to spot %d, render (%.1f, %.1f), %.0f m from the car (%s)", k, c.name, spot, t.x,
            t.y, sqrtf((t.x - p[0]) * (t.x - p[0]) + (t.y - p[1]) * (t.y - p[1])), why);
    else
        g_trMovesUnlogged++;
}

static void HideAll(const char* why)
{
    int n = 0;
    for (int k = 0; k < g_tcCount; k++)
        if (Alive(g_tc[k]))
        {
            if (!g_tc[k].hidden)
                VehCall(g_tc[k].veh, 0x84);
            g_tc[k].hidden = true;
            n++;
        }
    Log("traffic: %d cars hidden (%s)", n, why);
}

static void ForgetGone()
{
    for (int k = 0; k < g_tcCount;)
        if (!Alive(g_tc[k]))
        {
            Log("traffic: car %d (%s) is gone (the game removed it); another is made in its place", k, g_tc[k].name);
            ForgetCar(k);
        }
        else
            k++;
}

static bool PlayerRenderPose(void* player, float* p, float* f)
{
    float q[3];
    if (!PlayerPosition(player, q))
        return false;
    p[0] = q[2], p[1] = -q[0];
    f[0] = 0, f[1] = 1;
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    if (rb && (vtbl == kRBVehicleVtbl || vtbl == kRigidBodyVtbl))
    {
        float v[3] = {0, 0, 0};
        ((GetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x34)))(rb, v);
        float L = sqrtf(v[0] * v[0] + v[2] * v[2]);
        if (L > 1e-3f)
            f[0] = v[2] / L, f[1] = -v[0] / L;
    }
    return true;
}

static int Target()
{
    DWORD e[20];
    int n = 0;
    if (!VehList(e, &n))
        return 0;
    int others = n - g_tcCount, room = 20 - g_trReserve - others;
    return room < g_trCount ? (room < 0 ? 0 : room) : g_trCount;
}

typedef void(__thiscall* SetControlFn)(void*, float);

// Run I item 14 (R19): our cars are DRIVER_NONE (AIVehicleEmpty writes no controls) with PInput, whose controls start
// cleared: no brake, no handbrake, nothing held them. Each frame every standing car gets gas 0, brake 1, handbrake 1
// (pushed or hit it still slides, as a braked car does); a gas found set (something else drove it) is logged once.
static void HoldCar(int k)
{
    TCar& c = g_tc[k];
    if (!g_trHold || c.hidden || !Alive(c))
        return;
    if (!c.input)
    {
        DWORD list = 0;
        if (ReadDword((DWORD)(UINT_PTR)c.sim + 4, &list) && list)
            c.input = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kIInputHandle);
    }
    if (!c.input || Vtbl(c.input) != kPInputVtbl)
    {
        if (!c.noInputLogged)
            Log("traffic: car %d (%s): its input is not PInput (0x%08lX, vtable 0x%08lX): not held", k, c.name,
                (unsigned long)(UINT_PTR)c.input, (unsigned long)(c.input ? Vtbl(c.input) : 0));
        c.noInputLogged = true;
        c.input = nullptr;
        return;
    }
    const float* ctl = ((const float*(__thiscall*)(void*))(UINT_PTR)(*(DWORD*)(UINT_PTR)(kPInputVtbl + 0x08)))(c.input);
    float gas = 0;
    if (ctl && SafeRead((DWORD)(UINT_PTR)ctl + 0x14, &gas, 4) && gas != 0 && !c.gasLogged)
    {
        c.gasLogged = true;
        Log("traffic: car %d (%s) had gas %.2f (something else drives it); held again", k, c.name, gas);
    }
    ((SetControlFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kPInputVtbl + 0x18)))(c.input, 0.0f);
    ((SetControlFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kPInputVtbl + 0x1C)))(c.input, 1.0f);
    ((SetControlFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(kPInputVtbl + 0x24)))(c.input, 1.0f);
}

static void HoldAll()
{
    if (!g_trHold)
        return;
    for (int k = 0; k < g_tcCount; k++) HoldCar(k);
}

static void TrafficWork(void* player)
{
    float now = SimNow();
    if (now < g_trLastNow)  // the simulation's clock went back (a restart): the timers start again
        g_trNextCreate = g_trNextUpdate = g_trNextToggle = -1;
    g_trLastNow = now;
    // the cars stand while the car is on F-Town (since Run I item 12 also while the game counts down there)
    bool active = g_city.buffer && !OffFTown(player) && !g_lnCareer;  // none in the career (FTownConnect.h)
    if (!active)
    {
        if (g_tcCount && !g_trHidden)
        {
            ForgetGone();
            HideAll("the car is off F-Town");
            g_trHidden = true;
        }
        return;
    }
    float p[2], f[2];
    if (!PlayerRenderPose(player, p, f))
        return;
    HoldAll();
    if (g_trHidden)
    {
        ForgetGone();
        for (int k = 0; k < g_tcCount; k++) MoveCar(k, p, f, false, "placed again");
        Log("traffic: placed again (%d cars)", g_tcCount);
        g_trHidden = false;
    }
    if (g_trToggle > 0)
    {
        if (g_trNextToggle < 0)
            g_trNextToggle = now + g_trToggle;
        else if (now >= g_trNextToggle)
        {
            g_trNextToggle = now + g_trToggle;
            g_trToggledOff = !g_trToggledOff;
            ForgetGone();
            for (int k = 0; k < g_tcCount; k++)
                if (!g_tc[k].hidden)
                    VehCall(g_tc[k].veh, g_trToggledOff ? 0x84 : 0x80);
            Log("toggle: traffic %s (%d cars)", g_trToggledOff ? "off" : "on", g_tcCount);
        }
        if (g_trToggledOff)
            return;
    }
    if (g_tcCount < Target() && now >= g_trNextCreate)
    {
        ForgetGone();
        if (!MakeCar(p, f))
            g_trNextCreate = now + g_trUpdate;
        else if (g_tcCount == Target() && !g_trFullLogged)
        {
            int addons = 0;
            for (int k = 0; k < g_tcCount; k++) addons += g_tc[k].addon;
            Log("traffic: %d cars standing (%d add-ons)", g_tcCount, addons);
            g_trFullLogged = true;
        }
        return;
    }
    if (g_trNextUpdate >= 0 && now < g_trNextUpdate)
        return;
    g_trNextUpdate = now + g_trUpdate;
    int before = g_tcCount;
    ForgetGone();
    if (g_tcCount < before)
        g_trFullLogged = false;
    int mask = EventRouteMask();
    for (int k = 0; k < g_tcCount; k++)
    {
        TCar& c = g_tc[k];
        float q[2];
        if (!CarPosition(c, q))
            continue;
        float d = sqrtf((q[0] - p[0]) * (q[0] - p[0]) + (q[1] - p[1]) * (q[1] - p[1]));
        if (c.spot >= 0 && !c.hidden && !c.driftLogged && d > 25.0f)
        {
            const TSpot& t = g_tsp[c.spot];
            float off = sqrtf((q[0] - t.x) * (q[0] - t.x) + (q[1] - t.y) * (q[1] - t.y));
            if (off > 5.0f)
            {
                c.driftLogged = true;
                Log("traffic: car %d (%s) is %.1f m from its spot with the player %.0f m away (it moved without being "
                    "pushed)", k, c.name, off, d);
            }
        }
        if (c.spot >= 0 && (g_tsp[c.spot].route & mask))
            MoveCar(k, p, f, true, "off the event's route");
        else if (c.hidden || d > g_trRelease)
        {
            char why[64];
            snprintf(why, sizeof(why), c.hidden ? "was hidden" : "it was %.0f m away", d);
            MoveCar(k, p, f, true, why);
        }
    }
}

static void TrafficFrame(void* player)
{
    if (!g_trOn)
        return;
    LARGE_INTEGER a, b;
    QueryPerformanceCounter(&a);
    TrafficWork(player);
    QueryPerformanceCounter(&b);
    if (g_city.buffer)
    {
        double us = (double)(b.QuadPart - a.QuadPart) * 1e6 / (double)g_qpcFreq.QuadPart;
        g_trFrames++;
        g_trCostSum += us;
        if (us > g_trCostMax)
            g_trCostMax = us;
    }
}
