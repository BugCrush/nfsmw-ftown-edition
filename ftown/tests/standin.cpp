// Stand-in for speed.exe to test FTownLoader.asi (and, in the coexistence variants, WorldProbe.asi beside it).
// Linked at image base 0x300000 without relocation (0x400000 until the Run I fixes: the stand-in's own code grew
// past 0x454000), so a large static array covers the game's addresses; code and
// tables shaped like the game's are put there. Every function the plugins call starts with the game's bytes (what
// they check), followed by code of ours that undoes those bytes' stack effects and jumps to a stand-in function.
// None of the game's code is copied here: where the plugins need behaviour, it is written below.
//
// Arguments: frames=<n> (default 80); go=<f1,f2,...> (F8 down on those frames, one frame each); unloadkey=<f> (F7);
// gone=<a>-<b> (no player on frames a..b); trackunload=<f> (the "game" calls TrackLoader::Unload on frame f);
// foreign=<f> (on frame f another element joins one of the plugin's nodes); noface (the height query finds nothing
// at F-Town); nofile (LoadChunks files nothing); taken (scenery section
// 2101 is already in UserInfoTable); wrongbytes (WGridNode::AddDynamic's first byte differs); background (the game
// window is not in front); existingnode (cell row 56, column 0 has a node of Rockport's with a static and a dynamic
// element); worldprobe=before|after (also load WorldProbe.asi, before or after FTownLoader.asi); nohome (a blocking
// SetStream does not bring Rockport back: no face at the saved spot); nosim (Sim::Internal::mSystem is null);
// zoneoff (the streamer's zone switching is disabled, byte 0x9AAC81 = 1); noresetable (the COM lookup finds no
// IResetable); next=<f1,...> (F6, the next spawn, down on those frames); taken=<n> (scenery section n is taken);
// nofile=<n> (LoadChunks files every section and pack but pack n). The map: map.bun if there is one, else
// ftown-slab.bun; every scenery section and collision pack in it is filed (Stage 2: a city of several).
//
// The streamer, as far as the return path needs it: Rockport's faces exist only while "streamed". Putting the car
// outside Rockport drops them (zone 0, notes Q3); a blocking Sim::SetStream at a Rockport point brings them back.
#include <windows.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <initializer_list>

static BYTE g_space[0x800000];

static void Reserve(DWORD address, DWORD size)
{
    if (address < (DWORD)(UINT_PTR)g_space || address + size > (DWORD)(UINT_PTR)g_space + sizeof(g_space))
    {
        printf("0x%08lX is not inside the stand-in's space (%p..+0x%X)\n", (unsigned long)address, (void*)g_space,
               (unsigned)sizeof(g_space));
        ExitProcess(2);
    }
    DWORD old;
    VirtualProtect((void*)(UINT_PTR)address, size, PAGE_EXECUTE_READWRITE, &old);
    memset((void*)(UINT_PTR)address, 0xCC, size);
}

static BYTE* g_p;
static void At(DWORD a) { g_p = (BYTE*)(UINT_PTR)a; }
static void B(std::initializer_list<int> bytes) { for (int b : bytes) *g_p++ = (BYTE)b; }
static void D(DWORD v) { memcpy(g_p, &v, 4); g_p += 4; }
static void Rel(DWORD target) { D(target - ((DWORD)(UINT_PTR)g_p + 4)); }
static void Jmp(DWORD target) { B({0xE9}); Rel(target); }
static void Put(DWORD a, DWORD v) { memcpy((void*)(UINT_PTR)a, &v, 4); }
static DWORD Get(DWORD a) { return *(DWORD*)(UINT_PTR)a; }

static int g_foreignFrame = -1;
static int g_frame, g_background, g_noface, g_nofile, g_existing, g_nohome, g_noresetable;
static int g_rockStreamed = 1;  // Rockport's sections (and faces) around the car are loaded
static int g_goFrames[16], g_goCount, g_unloadFrame = -1, g_goneA = -1, g_goneB = -1, g_trackUnloadFrame = -1;
static int g_nextFrames[16], g_nextCount, g_nofileNumber = -1;
static int g_taFrames[16], g_taCount;  // ta=<f1,...>: F5 (0x74, the Time Attack) down on those frames
static int g_nevFrames[16], g_nevCount;  // nextev=<f1,...>: F4 (0x73, the next event) down on those frames

extern "C" __declspec(dllexport) int __cdecl FTownTestKey(int vk)
{
    if (vk == 0x74)
    {
        for (int i = 0; i < g_taCount; i++)
            if (g_taFrames[i] == g_frame)
                return 1;
        return 0;
    }
    if (vk == 0x73)
    {
        for (int i = 0; i < g_nevCount; i++)
            if (g_nevFrames[i] == g_frame)
                return 1;
        return 0;
    }
    if (vk == 0x77)
        for (int i = 0; i < g_goCount; i++)
            if (g_goFrames[i] == g_frame)
                return 1;
    if (vk == 0x75)
        for (int i = 0; i < g_nextCount; i++)
            if (g_nextFrames[i] == g_frame)
                return 1;
    return vk == 0x76 && g_frame == g_unloadFrame;
}
extern "C" __declspec(dllexport) int __cdecl FTownTestForeground() { return !g_background; }
// WorldProbe's (its teleport is off in its shipped ini: never pressed)
extern "C" __declspec(dllexport) int __cdecl WorldProbeTestKey(int) { return 0; }
extern "C" __declspec(dllexport) int __cdecl WorldProbeTestForeground() { return 1; }

// ---------------------------------------------------------------- the player (as world/tests/standin.cpp)

struct Player
{
    DWORD pad[8];
    DWORD vtbl;
    DWORD more[16];  // +0x28 from vtbl (more[9]): the HUD (LocalPlayer::GetHud 0x6F8F10 reads [this + 0x28])
};
static Player g_player;
static float g_rbData[64] = {0, 0, 0, 0, -2400.0f, 113.0f, 1700.0f};  // physics; position at +0x10
static float* const g_pos = g_rbData + 4;
static float* g_rbDataPtr = g_rbData;
// g_rb is the body's IRigidBody (RigidBody + 0x48, as the game's GetRigidBody hands it); RigidBody + 0x104 =
// g_rb + 0xBC is the collision mask (RBComplexParams.fCollisionMask: the player's 0, DRIVER_HUMAN, PVehicle::
// LoadBehaviors 0x685240), which the stand-in's collision below uses as the player collider's exclusion mask
static DWORD g_simVtbl[32], g_sim[64], g_rb[64];
// facing physics (-0.6, 0, 0.8) = render (0.8, 0.6, 0): heading 36.87 degrees
static float g_orient[16] = {0.8f, 0, 0.6f, 0, 0, 1, 0, 0, -0.6f, 0, 0.8f, 0, 0, 0, 0, 1};

static bool InRockport(const float* p) { return p[0] > -5000.0f && p[2] < 5000.0f; }

static const float* __fastcall GetPosition(Player*, void*) { return g_pos; }
static int g_teleportFrame = -1;  // the last frame the car was teleported (cars placed then are not "in view")
static bool __fastcall SetPosition(Player*, void*, const float* p)
{
    g_teleportFrame = g_frame;
    printf("TELEPORT %.3f %.3f %.3f\n", p[0], p[1], p[2]);
    ((void(__thiscall*)(void*, const float*))0x696FB0)(g_rb, p);  // as LocalPlayer::SetPosition does
    if (!InRockport(p))
        g_rockStreamed = 0;  // the streamer follows the car's body: zone 0 drops Rockport's sections
    return true;
}

// Sim::SetStream (cdecl: the physics point, bool blocking); a blocking call at a Rockport point loads it again
static void __cdecl StSetStream(const float* p, int blocking)
{
    printf("SETSTREAM %.2f %.2f %.2f blocking %d zoneoff %d\n", p[0], p[1], p[2], blocking & 0xFF,
           *(BYTE*)0x9AAC81);
    if (!Get(0x9885E0))
        return;  // as the game: nothing without a simulation
    if ((blocking & 0xFF) && InRockport(p) && !g_nohome && !*(BYTE*)0x9AAC81)
        g_rockStreamed = 1;
}

// the COM lookup (UTL::COM::Object::_IList::Find) and ResetCar's IResetable
static DWORD g_iList[4];
static DWORD g_resetable[4] = {0x8ABA10};
// the HUD (the IHud the player hands out) and its generic message (docs/ftown-race-notes.md R4): the HUD's +4 is its
// COM object's interface list (pointing at itself, as g_iList); Find(IGenericMessage::_IHandle 0x5650B0) gives the
// GenericMessage, whose vtable 0x8A2088 +4 is RequestGenericMessage (0x568030: the game's first bytes, then StRequest)
static DWORD g_hudList[4];
static DWORD g_hud[4];
static DWORD g_gm[8] = {0x8A2088};
static int g_nohud;
// Run K item 5: hudfrom=<f>: the player has no HUD before frame f (LocalPlayer::GetHud gives 0, as at Run K's early
// start); resetablefrom=<f>: the car's ResetCar is not found before frame f
static int g_hudFrom = -1, g_resetableFrom = -1, g_iconWrong;

static DWORD g_radar[16] = {0x8A1F2C};  // the HUD's IRadarDetector (Find with 0x565A30)
static int g_nocd;
static DWORD g_countdown[8] = {0x8A2070};  // the HUD's ICountdown (+0x14 the count; count -1 until it begins)

static void* VehFind(DWORD* list, DWORD handle, bool* isVeh);
static void* __fastcall StFind(DWORD* list, void*, DWORD handle)
{
    if (list == g_hudList)
    {
        if (handle == 0x4B4380)
            return g_nocd ? nullptr : g_countdown;
        if (handle == 0x565A30)
            return g_nohud ? nullptr : g_radar;
        return handle == 0x5650B0 && !g_nohud ? g_gm : nullptr;
    }
    bool isVeh = false;
    void* iv = VehFind(list, handle, &isVeh);  // a vehicle's interface list: its IVehicle (IVehicle::_IHandle)
    if (isVeh)
        return iv;
    if (list != g_iList)
        printf("FIND BAD THIS\n");
    return handle == 0x620250 && !g_noresetable && g_frame >= g_resetableFrom ? g_resetable : nullptr;
}

// the HUD message: printed when it differs from the last one; the frames with a request counted
static char g_msgLast[512];
static int g_msgFrames, g_msgFrameSeen = -1;
static float g_simGo = -1, g_simFinish = -1;
static float g_simTime;  // the simulation's time (Sim::GetTime 0x6E8DE0 reads the float at 0x9885D8)
// The game's GenericMessage (FeGenericMessage.cpp, PC 0x568030 / 0x567F80) as far as showing goes: a request below the
// current priority is refused; a script is set again only when not set (single frame) or always; Update (after the
// plugin's hook, once a frame) hides the message when its script has run out (kScriptFrames) or a single-frame message
// was not asked for again; every script start is a "SHOW" (the text popping in: what the user saw as flashing).
// gamemsg=<f>: the game shows a message of its own at priority 5 on frame f (a race-over line).
static const int kScriptFrames = 45;
static int g_gmPrio, g_gmFrames, g_gmSingle, g_gmSetAt = -1, g_gmStarts, g_gmGameFrame = -1;
static DWORD g_gmScript;  // the line's script: 0 none, 1 hide, else the script's hash
static void GmUpdate()
{
    if (g_gmPrio <= 0)
        return;
    bool running = g_gmScript > 1 && g_frame - g_gmSetAt < kScriptFrames;
    if (!running || (g_gmSingle && g_gmFrames != 0))
    {
        g_gmScript = 1;
        g_gmPrio = 0;
        printf("HUDMSG HIDDEN\n");
    }
    g_gmFrames++;
}
static bool __fastcall StRequest(DWORD* self, void*, const char* text, int single, DWORD script, DWORD icon,
                                 DWORD iconScript, int priority)
{
    char flat[400];
    int k = 0;
    for (const char* c = text; c && *c && k < 398; c++) flat[k++] = *c == '\n' ? '|' : *c;
    flat[k] = 0;
    if (priority < g_gmPrio)
    {
        printf("HUDMSG REFUSED prio %d (showing %d) text %s\n", priority, g_gmPrio, flat);
        return false;
    }
    g_gmPrio = priority;
    g_gmFrames = 0;
    g_gmSingle = single & 0xFF;
    if (text && script && (!g_gmSingle || g_gmScript != script))
    {
        g_gmScript = script;
        g_gmSetAt = g_frame;
        g_gmStarts++;
        printf("HUDMSG SHOW %s\n", flat);
    }
    char line[512];
    snprintf(line, sizeof(line), "HUDMSG prio %d single %d script %08lX icon %lu text %s%s", priority, single & 0xFF,
             (unsigned long)script, (unsigned long)icon, flat, self == g_gm ? "" : " BAD THIS");
    if (strcmp(line, g_msgLast))
    {
        printf("%s\n", line);
        strcpy(g_msgLast, line);
    }
    if (g_msgFrameSeen != g_frame)
        g_msgFrames++;
    g_msgFrameSeen = g_frame;
    if (g_simGo < 0 && text && !strncmp(text, "GO", 2))
        g_simGo = g_simTime;
    if (g_simFinish < 0 && text && (!strncmp(text, "FINISH", 6) || !strncmp(text, "NEW BEST", 8)))
    {
        g_simFinish = g_simTime;
        printf("STANDIN TIMER %.3f\n", g_simFinish - g_simGo);
    }
    return true;
}

// ---------------------------------------------------------------- the race HUD (docs/ftown-race-notes.md R14-R16)
//
// LocalPlayer::UpdateHud's three calls the plugin takes (each a call instruction at its game address, then a ret of
// ours, run once a frame while racing): COMPLETE % (0x6F1DB6 -> GetHudPctRaceComplete: the carrier's racer is never on
// its Rockport route, 0), the timer (0x6F1E00 -> GTimer::GetTime: the carrier's clock, the simulation's time) and the
// radar update (0x6F2170 -> 0x6EDE30: as the game with no cop and no camera near, SetTarget(0, 0, 0)). Printed: RACEINFO
// every 10 frames, RADAR when it changes. The player's settings (GetSettings 0x6E99A0 runs as is over a profile of
// ours); TRANSMISSION when its byte +0x11 changes.
static BYTE g_ri[0x200];
static BYTE g_profile[0x200];
static char g_radarLast[96];
static int g_transLast = -1;
static float __fastcall StPct(void*, void*) { return 0.0f; }
static float __fastcall StGTime(void*, void*) { return g_simTime; }
static void __fastcall StSetTarget(DWORD* self, void*, int type, float range, float dir)
{
    char line[96];
    snprintf(line, sizeof(line), "RADAR type %d range %.2f dir %.2f%s", type, range, dir,
             self == g_radar ? "" : " BAD THIS");
    if (strcmp(line, g_radarLast))
    {
        printf("%s\n", line);
        strcpy(g_radarLast, line);
    }
}
static void __fastcall StRadarGame(void* self, void*, DWORD, DWORD)
{
    ((void(__thiscall*)(void*, int, float, float))Get(0x8A1F2C + 4))(g_radar, 0, 0.0f, 0.0f);
}
extern "C" void __cdecl RunRadarSite(void* self);
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _RunRadarSite\n"
        "_RunRadarSite:\n"
        "  push ebp\n"
        "  mov ebp, [esp + 8]\n"
        "  call _RunRadarInner\n"  // as UpdateHud: the two arguments right above the call's own return
        "  pop ebp\n"
        "  ret\n"
        "_RunRadarInner:\n"
        "  push 0\n"
        "  push 1\n"
        "  mov eax, 0x6F216E\n"
        "  jmp eax\n"
        "  pop ebp\n"
        "  ret\n"
        ".att_syntax prefix\n");
// Run K item 2: FEngHud::Update's call of DetermineHudFeatures (0x58CA4D: push the player; mov esi, ecx; call 0x57CA60,
// then a ret of ours), run once a frame while racing through a runner (esi and ebp kept). The stand-in's
// DetermineHudFeatures gives a racing HUD's mask (FEPkg_Hud.cpp:912-1016 for a race: RaceInformation 0x4000000, the
// leaderboard 0x8, the wrong-way arrow 0x20 among the rest). Printed when it changes: HUDFEATURES raceinfo r leaderboard
// l wrongway w rest 0x...
static const unsigned long long kRacingHud = 0x10000ull | 0x4000 | 0x8000000 | 0x2 | 0x800 | 0x40000 | 0x8 | 0x4000000 |
                                             0x10 | 0x20 | 0x1000000 | 0x10000000 | 0x100000000ull | 0x80000 | 0x400 |
                                             0x20000000 | 0x400000 | 0x200000000ull | 0x800000 | 0x200000;
static char g_hfLast[128];
static unsigned long long __fastcall StHudFeatures(void* hud, void*, void* player)
{
    if (hud != g_hud || player != &g_player.vtbl)
        printf("HUDFEATURES BAD THIS\n");
    return kRacingHud;
}
extern "C" unsigned long long __cdecl RunHudFeatures(void* hud, void* player);
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _RunHudFeatures\n"
        "_RunHudFeatures:\n"
        "  push esi\n"
        "  push ebp\n"
        "  mov ecx, [esp + 12]\n"
        "  mov ebp, [esp + 16]\n"
        "  mov eax, 0x58CA4D\n"
        "  call eax\n"
        "  pop ebp\n"
        "  pop esi\n"
        "  ret\n"
        ".att_syntax prefix\n");
static void HudFeatures()
{
    unsigned long long f = RunHudFeatures(g_hud, &g_player.vtbl);
    char line[128];
    snprintf(line, sizeof(line), "HUDFEATURES raceinfo %d leaderboard %d wrongway %d rest 0x%llX", (f & 0x4000000) ? 1 : 0,
             (f & 0x8) ? 1 : 0, (f & 0x20) ? 1 : 0, f & ~0x4000028ull);
    if (strcmp(line, g_hfLast))
    {
        printf("%s (f=%d)\n", line, g_frame);
        strcpy(g_hfLast, line);
    }
}

static void RaceHud()
{
    HudFeatures();  // Run K item 2
    float pct = ((float(__thiscall*)(void*))0x6F1DB6)(g_ri);
    float t = ((float(__thiscall*)(void*))0x6F1E00)(g_ri + 0x14C);
    if (g_frame % 10 == 0)
        printf("RACEINFO f=%d pct %d time %.2f\n", g_frame, (int)pct, t);
    RunRadarSite(&g_player);
    int tr = g_profile[0x80 + 0x11];
    if (tr != g_transLast)
        printf("TRANSMISSION %d\n", tr);
    g_transLast = tr;
}

// the times file's write-then-rename: the plugin asks between writing the new file and renaming it (a test seam,
// as FTownTestKey); 1 = "the game crashed here": the plugin stops before the rename
static int g_crashWrite;
extern "C" __declspec(dllexport) int __cdecl FTownTestBeforeRename() { return g_crashWrite; }
static void __fastcall StSetReset(void* self, void*, const float* p, const float* d)
{
    printf("RESETPOS %.2f %.2f %.2f dir %.3f %.3f %.3f%s\n", p[0], p[1], p[2], d[0], d[1], d[2],
           self == g_resetable ? "" : " BAD THIS");
}
static void* __fastcall GetSimable(Player*, void*) { return g_sim; }
static void* __fastcall GetRigidBody(void*, void*) { return g_rb; }
static void __fastcall SetLinear(void*, void*, const float* v) { printf("VELOCITY %.1f %.1f %.1f\n", v[0], v[1], v[2]); }
static void __fastcall SetAngular(void*, void*, const float* v) { printf("SPIN %.1f %.1f %.1f\n", v[0], v[1], v[2]); }
// RigidBody::GetSpeed (slot +0x2C, the game's 0x6711B0): the stand-in car's speed, metres a second (the route's step
// times 30 frames a second while it drives the route, else 0)
static float g_speedNow;
static int g_speedReads;
static float __fastcall StGetSpeed(void*, void*)
{
    g_speedReads++;
    printf("GETSPEED %.2f m/s\n", g_speedNow);
    return g_speedNow;
}
static void __fastcall SetOrientMatrix(void*, void*, const float* m)
{
    memcpy(g_orient, m, sizeof(g_orient));
    printf("ORIENT row2 %.3f %.3f %.3f\n", m[8], m[9], m[10]);
}
static void __fastcall GetForward(void*, void*, float* f) { f[0] = g_orient[8], f[1] = g_orient[9], f[2] = g_orient[10]; }
static void __fastcall GetRight(void*, void*, float* r) { r[0] = g_orient[0], r[1] = g_orient[1], r[2] = g_orient[2]; }

// ---------------------------------------------------------------- the grid, the game's lists

struct GridObj
{
    float min[4];
    float edge, invEdge;
    DWORD rows, cols;
    DWORD* nodes;
};
static GridObj g_grid;
struct Node  // WGridNode as stored, 0x14 bytes, then the static element tags
{
    DWORD list;
    WORD index, pad;
    BYTE counts[4];
    WORD offsets[4];
    DWORD tags[4];
};
static Node g_rockNode;    // a stored node of "Rockport" in a far cell
static Node g_existNode;   // existingnode: a node in cell (56, 0)
struct Elem
{
    Elem* next;
    Elem* prev;
    DWORD ind;
    DWORD type;
};
static int g_lists, g_elems;

static Elem* NewElem()
{
    g_elems++;
    return (Elem*)calloc(1, sizeof(Elem));
}

// as the game's AddDynamic: the node's list made on first use (12 bytes: ?, head sentinel, size), push_back
static void __fastcall StAddDynamic(Node* node, void*, DWORD ind, DWORD type)
{
    if (!node->list)
    {
        DWORD* list = (DWORD*)calloc(3, 4);
        Elem* head = NewElem();
        head->next = head->prev = head;
        list[1] = (DWORD)(UINT_PTR)head;
        node->list = (DWORD)(UINT_PTR)list;
        g_lists++;
    }
    DWORD* list = (DWORD*)(UINT_PTR)node->list;
    Elem* head = (Elem*)(UINT_PTR)list[1];
    Elem* e = NewElem();
    e->ind = ind;
    e->type = type;
    e->next = head;
    e->prev = head->prev;
    head->prev->next = e;
    head->prev = e;
    list[2]++;
    printf("ADDDYN cell %u tag %08lX type %lu\n", node->index, (unsigned long)ind, (unsigned long)type);
}

// RemoveDynamic's continuation: called with the node's list (the game's first bytes loaded it into esi)
static void __fastcall StRemoveList(DWORD* list, void*, DWORD ind, DWORD type)
{
    Elem* head = (Elem*)(UINT_PTR)list[1];
    for (Elem* e = head->next; e != head; e = e->next)
        if (e->ind == ind && e->type == type)
        {
            e->prev->next = e->next;
            e->next->prev = e->prev;
            free(e);
            g_elems--;
            list[2]--;
            printf("REMOVEDYN tag %08lX\n", (unsigned long)ind);
            return;
        }
    printf("REMOVEDYN tag %08lX NOT FOUND\n", (unsigned long)ind);
}

static void __fastcall StListDtor(DWORD* list, void*)
{
    Elem* head = (Elem*)(UINT_PTR)list[1];
    int left = 0;
    for (Elem* e = head->next; e != head;)
    {
        Elem* n = e->next;
        free(e);
        g_elems--;
        left++;
        e = n;
    }
    free(head);
    g_elems--;
    printf("LISTDTOR %d elements left\n", left);
}

static void __fastcall StFastFree(void* mem, void*, void* p, unsigned size, const char*)
{
    printf("FASTFREE %u bytes%s\n", size, (DWORD)(UINT_PTR)mem == 0x925B30 ? "" : " BAD THIS");
    free(p);
    if (size == 12)
        g_lists--;
}

static void GridSnapshot(const char* when)
{
    printf("GRID %s", when);
    for (DWORD row = 40; row < 75; row++)
        for (DWORD col = 0; col < 2; col++)
        {
            DWORD cell = row * g_grid.cols + col;
            Node* n = (Node*)(UINT_PTR)g_grid.nodes[cell];
            if (!n)
                continue;
            printf(" %lu:[s%d", (unsigned long)cell, n->counts[0]);
            if (n->list)
            {
                DWORD* list = (DWORD*)(UINT_PTR)n->list;
                Elem* head = (Elem*)(UINT_PTR)list[1];
                for (Elem* e = head->next; e != head; e = e->next)
                    printf(" d%08lX/%lu", (unsigned long)e->ind, (unsigned long)e->type);
            }
            printf("]");
        }
    printf("\n");
}

static bool OursFiled(DWORD pack);
static bool GridHasTagsOf(DWORD pack)
{
    for (DWORD cell = 0; cell < g_grid.rows * g_grid.cols; cell++)
    {
        Node* n = (Node*)(UINT_PTR)g_grid.nodes[cell];
        if (!n || !n->list)
            continue;
        DWORD* list = (DWORD*)(UINT_PTR)n->list;
        Elem* head = (Elem*)(UINT_PTR)list[1];
        for (Elem* e = head->next; e != head; e = e->next)
            if (e->type == 0 && (e->ind >> 16) == pack)
                return true;
    }
    return false;
}

// ---------------------------------------------------------------- the colliders (WCollider instance caches)

// The cars' and the camera's WCollider keep pointers to the collision instances they found (fInstanceCacheList,
// World/WCollider.h:104) until the car leaves the cached region. The stand-in's one collider takes a pointer into the
// loaded buffer after LoadChunks; UnloadChunks reports whether it was cleared first.
static DWORD g_collider[0x40];
static DWORD g_colliderList[1] = {(DWORD)(UINT_PTR)g_collider};
static DWORD g_assets[8];
static void __fastcall StClear(DWORD* c, void*)
{
    c[1] = 0;
    printf("COLLIDER CLEAR\n");
}
static void __fastcall StSetExclusion(void* self, void*)
{
    printf("SETEXCLUSIONFLAGS%s\n", self == (void*)g_assets ? "" : " BAD THIS");
    DWORD* list = (DWORD*)(UINT_PTR)Get(0x9B3C84);
    DWORD n = Get(0x9B3C8C);
    for (DWORD i = 0; i < n; i++)
    {
        ((void(__thiscall*)(void*))0x782A30)((void*)(UINT_PTR)list[i]);
        ((BYTE*)(UINT_PTR)list[i])[0x80] = 0;
    }
}

// ---------------------------------------------------------------- loading

// ---------------------------------------------------------------- the HUD minimap (docs/ftown-race-notes.md R1)
//
// The game's Minimap::SetupMinimap, as far as the plugin changes what it reads: the current track's TrackInfo
// calibration (TrackInfoTable [0x9A3A14], count [0x9A3A18], 0x120 a record, +0x8A the number, +0xAC/+0xB0 upper left,
// +0xB4 width), TheRaceParameters.TrackNumber 0x904FB8, the map header at gChoppedMiniMapManager [0x91CEFC] + 8. Every
// frame after the plugin's hook: the four chop numbers around the car, exactly as the PC code makes them, and the
// textures "<header>_CHOP<n>" the HUD would ask for: ours (a texture of the FTOWNMAP pack), Rockport's (header
// unchanged, 0 <= n < 64) or missing. A chop number of 64 or more is what the game would read past its table: printed
// as OUT OF RANGE (the guard's reason).
static BYTE g_trackInfos[3][0x120];
static DWORD g_mmManager[0x1B4 / 4];
static const char* kRockHeader = "MINI_MAP_QR_SPRINT1";
static DWORD g_mmHashes[256];
static int g_mmHashCount;
static BYTE* g_mmLoaded;
static char g_mmLast[256];

static DWORD BHash(const char* s)
{
    DWORD h = 0xFFFFFFFF;
    while (*s) h = h * 33 + (BYTE)*s++;
    return h;
}

// a texture pack's keys (0x33310002) are its textures' name hashes
static void WalkKeys(BYTE* p, BYTE* end)
{
    while (p + 8 <= end)
    {
        DWORD id = *(DWORD*)p, sz = *(DWORD*)(p + 4);
        if (id == 0x33310002)
            for (DWORD k = 0; k + 8 <= sz && g_mmHashCount < 256; k += 8)
                g_mmHashes[g_mmHashCount++] = *(DWORD*)(p + 8 + k);
        if (id & 0x80000000)
            WalkKeys(p + 8, p + 8 + sz);
        p += 8 + sz;
    }
}

// Run J item 7: our minimap pack's 64 textures as the game would make them (GetTextureInfo 0x503400 by name hash:
// TextureInfo +0 its PlatInfo, whose +0x18 is the IDirect3DTexture9; +0x24 the hash, +0x44 / +0x46 the size, +0x4A
// 0x24 = DXT3): 128 x 128 (the test map's 1,024 picture), every block a flat grey, alive while the pack is loaded.
// LockRect (+0x4C) and UnlockRect (+0x50) on a texture of a gone pack count as LOCKED AFTER UNLOAD; nolock: every
// LockRect fails. Printed every 10 frames when it changes: COURSE yellow N (pixels in the line's colour); at the end
// COURSE ORIGINAL yes/no (every texture as made) and COURSE LOCKS n.
struct FakeTex
{
    DWORD vtbl;
    BYTE* bits;
    int size;
    int alive;
};
static DWORD g_texVtbl[32];
static BYTE g_tis[64][0x80];
static DWORD g_plats[64][16];
static FakeTex g_texs[64];
static BYTE* g_texInit[64];
static int g_texLocks, g_noLock, g_lockAfter, g_texMade;
static long __stdcall StLockRect(FakeTex* t, unsigned, int* lr, const void*, DWORD)
{
    if (!t->alive)
        g_lockAfter++;
    if (g_noLock)
        return (long)0x8876086C;
    g_texLocks++;
    lr[0] = t->size / 4 * 16;
    *(BYTE**)(lr + 1) = t->bits;
    return 0;
}
static long __stdcall StUnlockRect(FakeTex*, unsigned) { return 0; }
static void MakeTextures()
{
    g_texVtbl[0x4C / 4] = (DWORD)(UINT_PTR)&StLockRect;
    g_texVtbl[0x50 / 4] = (DWORD)(UINT_PTR)&StUnlockRect;
    for (int n = 0; n < 64; n++)
    {
        FakeTex& t = g_texs[n];
        t.vtbl = (DWORD)(UINT_PTR)g_texVtbl;
        t.size = 128;
        int bytes = 128 / 4 * 128 / 4 * 16;
        if (!t.bits)
        {
            t.bits = (BYTE*)malloc(bytes);
            g_texInit[n] = (BYTE*)malloc(bytes);
        }
        for (int b = 0; b < bytes; b += 16)
        {
            memset(t.bits + b, 0xFF, 8);
            WORD grey = 0x8410;
            memcpy(t.bits + b + 8, &grey, 2), memcpy(t.bits + b + 10, &grey, 2);
            memset(t.bits + b + 12, 0, 4);
        }
        memcpy(g_texInit[n], t.bits, bytes);
        t.alive = 1;
        char name[64];
        snprintf(name, sizeof(name), "FTOWN_MAP_CHOP%d", n);
        BYTE* ti = g_tis[n];
        memset(ti, 0, sizeof(g_tis[n]));
        *(DWORD*)ti = (DWORD)(UINT_PTR)g_plats[n];
        g_plats[n][0x18 / 4] = (DWORD)(UINT_PTR)&t;
        *(DWORD*)(ti + 0x24) = BHash(name);
        *(short*)(ti + 0x44) = 128, *(short*)(ti + 0x46) = 128;
        ti[0x4A] = 0x24;
    }
    g_texMade = 1;
}
static void* __cdecl StGetTI(DWORD hash, int, int)
{
    for (int n = 0; g_texMade && n < 64; n++)
        if (g_texs[n].alive && *(DWORD*)(g_tis[n] + 0x24) == hash)
            return g_tis[n];
    return nullptr;
}
static DWORD __cdecl StBHash(const char* s) { return BHash(s); }
static int CountYellow()
{
    int n = 0;
    for (int t = 0; g_texMade && t < 64; t++)
        for (int b = 0; b < 128 / 4 * 128 / 4 * 16; b += 16)
        {
            BYTE* p = g_texs[t].bits + b;
            WORD c[2];
            memcpy(c, p + 8, 4);
            int pal[4][3];
            for (int k = 0; k < 2; k++)
                pal[k][0] = (c[k] >> 11 & 31) * 255 / 31, pal[k][1] = (c[k] >> 5 & 63) * 255 / 63,
                pal[k][2] = (c[k] & 31) * 255 / 31;
            for (int i = 0; i < 3; i++)
                pal[2][i] = (2 * pal[0][i] + pal[1][i]) / 3, pal[3][i] = (pal[0][i] + 2 * pal[1][i]) / 3;
            DWORD idx;
            memcpy(&idx, p + 12, 4);
            for (int k = 0; k < 16; k++)
            {
                int* q = pal[idx >> (2 * k) & 3];
                n += abs(q[0] - 255) < 24 && abs(q[1] - 210) < 24 && q[2] < 24;
            }
        }
    return n;
}
static bool TexturesOriginal()
{
    for (int t = 0; t < 64; t++)
        if (g_texMade && memcmp(g_texs[t].bits, g_texInit[t], 128 / 4 * 128 / 4 * 16))
            return false;
    return true;
}

static void MinimapPackLoad(BYTE* buf, int size)
{
    MakeTextures();
    g_mmHashCount = 0;
    WalkKeys(buf, buf + size);
    g_mmLoaded = buf;
    printf("MINIMAPPACK LOAD %d bytes textures %d aligned %d\n", size, g_mmHashCount,
           ((DWORD)(UINT_PTR)buf & 127) == 0 ? 1 : 0);
}

static void MinimapPackUnload(BYTE* buf)
{
    printf("MINIMAPPACK UNLOAD same buffer %d textures original %s\n", buf == g_mmLoaded ? 1 : 0,
           TexturesOriginal() ? "yes" : "no");
    for (FakeTex& t : g_texs) t.alive = 0;
    g_mmHashCount = 0;
    g_mmLoaded = nullptr;
}

static BYTE* TrackInfoOf(int track)
{
    DWORD table = Get(0x9A3A14), n = Get(0x9A3A18);
    for (DWORD i = 0; i < n; i++)
    {
        BYTE* r = (BYTE*)(UINT_PTR)(table + i * 0x120);
        if (*(short*)(r + 0x8A) == track)
            return r;
    }
    return nullptr;
}

// UncompressMaps' test of a chop number runs as the game's code at 0x5673BD (or whatever a plugin put there): the
// stand-in calls it with ebx = the number and ebp = the manager; 0x5673C5 (the number used: [ebp + n*4 + 0x48] read)
// returns 1, 0x5673FB (skipped) returns 0. Review fix: a number >= 64 used is OUT OF RANGE.
extern "C" int __cdecl RunChop(int chop, void* manager);
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _RunChop\n"
        "_RunChop:\n"
        "  push ebx\n"
        "  push ebp\n"
        "  push edi\n"
        "  mov ebx, [esp + 16]\n"
        "  mov ebp, [esp + 20]\n"
        "  mov eax, 0x5673BD\n"
        "  call eax\n"
        "  pop edi\n"
        "  pop ebp\n"
        "  pop ebx\n"
        "  ret\n"
        ".att_syntax prefix\n");

static void EmulateIcons(BYTE* ti, float carX, float carY, float ulx, float uly, float w);  // Run K item 1
static void EmulateMinimap()
{
    BYTE* ti = TrackInfoOf((int)Get(0x904FB8));
    const char* header = (const char*)(UINT_PTR)(Get(0x91CEFC) + 8);
    if (!ti || !Get(0x92D884))
        return;
    float ulx = *(float*)(ti + 0xAC), uly = *(float*)(ti + 0xB0), w = *(float*)(ti + 0xB4);
    float x = g_pos[2], y = -g_pos[0];  // render
    float mx = (x - ulx) / w * 8.0f, my = ((uly - y) / w + 1.0f) * 8.0f;
    int X = (int)mx, Y = (int)my;  // ftol: towards zero
    float dx = mx - X, dy = my - Y;
    int c[4];
    if (dx < 0.5f)
        if (dy < 0.5f) c[0] = (Y - 1) * 8 + X - 1, c[1] = (Y - 1) * 8 + X, c[2] = Y * 8 + X - 1, c[3] = Y * 8 + X;
        else c[0] = Y * 8 + X - 1, c[1] = Y * 8 + X, c[2] = (Y + 1) * 8 + X - 1, c[3] = (Y + 1) * 8 + X;
    else if (dy < 0.5f) c[0] = (Y - 1) * 8 + X, c[1] = (Y - 1) * 8 + X + 1, c[2] = Y * 8 + X, c[3] = Y * 8 + X + 1;
    else c[0] = Y * 8 + X, c[1] = Y * 8 + X + 1, c[2] = (Y + 1) * 8 + X, c[3] = (Y + 1) * 8 + X + 1;
    int ours = 0, rock = 0, missing = 0, out = 0;
    for (int k = 0; k < 4; k++)
    {
        if (c[k] >= 64 && RunChop(c[k], (void*)(UINT_PTR)Get(0x91CEFC)))
            out++;
        char name[128];
        snprintf(name, sizeof(name), "%s_CHOP%d", header, c[k]);
        DWORD h = BHash(name);
        bool found = false;
        for (int i = 0; i < g_mmHashCount; i++) found |= g_mmHashes[i] == h;
        if (found)
            ours++;
        else if (!strcmp(header, kRockHeader) && c[k] >= 0 && c[k] < 64)
            rock++;
        else
            missing++;
    }
    char line[256];
    snprintf(line, sizeof(line), "MINIMAP header %s calibration %.1f %.1f %.1f chops %d %d %d %d ours %d rockport %d "
             "missing %d%s", header, ulx, uly, w, c[0], c[1], c[2], c[3], ours, rock, missing,
             out ? " OUT OF RANGE" : "");
    if (strcmp(line, g_mmLast))
    {
        printf("%s\n", line);
        strcpy(g_mmLast, line);
    }
    EmulateIcons(ti, x, y, ulx, uly, w);  // Run K item 1: Minimap::Update's last call
}

// ---------------------------------------------------------------- Run K item 1: the minimap's gameplay icons
//
// Minimap::Update's last call (0x59DD17: push the player; mov ecx, esi; call UpdateGameplayIcons 0x57A300) runs once a
// frame while racing, through a runner that gives it esi = our Minimap object and ebp = the player. The game's
// UpdateGameplayIcons (stand-in: gameicons=<n> safe houses of the game's own in images 0..n-1, every other image of
// type 8 hidden), Minimap::UpdateElementArt (0x5675D0: the decompiled math, FeMinimap.cpp, on the object's fields:
// +0x98 the track's record, +0xA8 the speed zoom, +0xAC the map's turn, +0xB0/+0xB4 the car in map units, +0xB8/+0xBC
// the map's centre on screen, +0x114 the GPS ring) and the FEng calls (visibility bit 0 of +0x1C, centre at +0x30,
// rotation +0x38, colour +0x40). Printed when it changes: SAFEHOUSE <slot> visible v at dx dy (screen units from the
// map's centre / 1024) alpha a, or SAFEHOUSE none.
static BYTE g_mmObj[0x400];
static DWORD g_icoImg[4][32];
static DWORD g_gpsImg[32];
static int g_gameIcons, g_icoItemOff;
static char g_icoLast[256];
static void __fastcall StGameplayIcons(BYTE* self, void*, void*)
{
    for (int k = 0; k < 8; k++)
    {
        DWORD* img = (DWORD*)(UINT_PTR)*(DWORD*)(self + 0x218 + 4 * k);
        if (!img)
            continue;
        if (k < g_gameIcons)
        {
            img[0x1C / 4] &= ~1u;
            ((float*)img)[0x30 / 4] = 0, ((float*)img)[0x34 / 4] = 0;
            img[0x40 / 4] = 0xFF00FF00;
        }
        else
            img[0x1C / 4] |= 1;
    }
}
static void __fastcall StElementArt(BYTE* self, void*, const float* pos, const float*, DWORD* obj, bool pulse)
{
    BYTE* track = (BYTE*)(UINT_PTR)*(DWORD*)(self + 0x98);
    float ulx = *(float*)(track + 0xAC), uly = *(float*)(track + 0xB0), w = *(float*)(track + 0xB4);
    float mx = (pos[0] - ulx) / w, my = (uly - pos[1]) / w + 1.0f;
    float zoom = *(float*)(self + 0xA8), rot = *(float*)(self + 0xAC) * 3.14159265f / 180.0f;
    float ex = (mx - *(float*)(self + 0xB0)) * zoom, ey = (my - *(float*)(self + 0xB4)) * zoom;
    float rx = ex * cosf(rot) + ey * sinf(rot), ry = ey * cosf(rot) - ex * sinf(rot);
    float d = sqrtf(rx * rx + ry * ry), alpha = 1.0f;
    if (d > 0.06f)
    {
        rx *= 0.06f / d, ry *= 0.06f / d;
        if (d > 0.125f)
            alpha = 1.0f - (d - 0.125f) * 9.523809f;
        if (d > 0.23f)
            alpha = 0.0f;
        if (pulse)
            alpha = 1.0f;
    }
    float* f = (float*)obj;
    f[0x30 / 4] = *(float*)(self + 0xB8) + rx * 1024.0f, f[0x34 / 4] = *(float*)(self + 0xBC) + ry * 1024.0f;
    obj[0x1C / 4] &= ~1u;
    obj[0x40 / 4] = (obj[0x40 / 4] & 0xFFFFFF) | (DWORD)(int)(alpha * 255.0f) << 24;
    if (pulse)
        g_gpsImg[0x1C / 4] &= ~1u, ((float*)g_gpsImg)[0x30 / 4] = f[0x30 / 4];
}
static void __cdecl StSetRotZ(DWORD* obj, float deg) { ((float*)obj)[0x38 / 4] = deg; }
static DWORD* __cdecl StGetColor(DWORD* out, DWORD* obj)
{
    out[0] = obj[0x40 / 4];
    return out;
}
static DWORD __fastcall StColorU32(DWORD* c, void*) { return c[0]; }
static void __cdecl StSetColor(DWORD* obj, DWORD c) { obj[0x40 / 4] = c; }
extern "C" void __cdecl RunIconsSite(void* minimap, void* player);
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _RunIconsSite\n"
        "_RunIconsSite:\n"
        "  push esi\n"
        "  push ebp\n"
        "  mov esi, [esp + 12]\n"
        "  mov ebp, [esp + 16]\n"
        "  mov eax, 0x59DD17\n"
        "  call eax\n"
        "  pop ebp\n"
        "  pop esi\n"
        "  ret\n"
        ".att_syntax prefix\n");
static void EmulateIcons(BYTE* ti, float carX, float carY, float ulx, float uly, float w)
{
    *(DWORD*)(g_mmObj + 0x98) = (DWORD)(UINT_PTR)ti;
    *(float*)(g_mmObj + 0xA8) = 1.0f;
    *(float*)(g_mmObj + 0xAC) = 0.0f;
    *(float*)(g_mmObj + 0xB0) = (carX - ulx) / w, *(float*)(g_mmObj + 0xB4) = (uly - carY) / w + 1.0f;
    *(float*)(g_mmObj + 0xB8) = 100.0f, *(float*)(g_mmObj + 0xBC) = 380.0f;
    *(DWORD*)(g_mmObj + 0x114) = (DWORD)(UINT_PTR)g_gpsImg;
    for (int k = 0; k < 4; k++) *(DWORD*)(g_mmObj + 0x218 + 4 * k) = (DWORD)(UINT_PTR)g_icoImg[k];
    *(DWORD*)(g_profile + 0x40) = g_icoItemOff ? 0xFFDFFFFF : 0xFFFFFFFF;  // [[FEDatabase] + 0x10] + 0x40: map items
    RunIconsSite(g_mmObj, &g_player.vtbl);
    char line[256] = "SAFEHOUSE";
    int any = 0;
    for (int k = 0; k < 4; k++)
    {
        DWORD* img = g_icoImg[k];
        if (img[0x1C / 4] & 1)
            continue;
        any = 1;
        char part[96];
        snprintf(part, sizeof(part), " %d at %.4f %.4f alpha %lu rot %.0f%s", k,
                 (((float*)img)[0x30 / 4] - 100.0f) / 1024.0f, (((float*)img)[0x34 / 4] - 380.0f) / 1024.0f,
                 (unsigned long)(img[0x40 / 4] >> 24), ((float*)img)[0x38 / 4],
                 (g_gpsImg[0x1C / 4] & 1) ? "" : " GPS RING MOVED");
        strncat(line, part, sizeof(line) - strlen(line) - 1);
    }
    if (!any)
        strcat(line, " none");
    if (strcmp(line, g_icoLast))
    {
        printf("%s (f=%d)\n", line, g_frame);
        strcpy(g_icoLast, line);
    }
}

static BYTE* g_file;
static DWORD g_fileSize;
// the race barriers' files (every ftown-barriers*.bun beside the stand-in: each event's set, LoadChunks name FTOWNBAR)
static BYTE* g_barFiles[8];
static DWORD g_barFileSizes[8];
static int g_barFileCount;
static BYTE* g_loaded;  // the city's buffer (the last LoadChunks named FTOWN)
static DWORD g_loadedSize;
static int g_loads, g_unloads, g_barLoads, g_barUnloads;
static DWORD g_userInfo[66][2];  // {refcount, header}: [64] for a taken number
static DWORD g_fakePack[4];
static DWORD g_packList[2700];
static int g_takenNumber = -1;
// every buffer handed to LoadChunks (the city's and the barriers'), with what it filed
struct Loaded
{
    BYTE* buf;
    int size;
    bool bar, unloaded, freed;
    int numbers[64], numberCount, packs[64], packCount;
    DWORD info[64][2];
};
static Loaded g_lds[32];
static int g_ldCount;

static bool OursFiled(DWORD pack)
{
    for (int k = 0; k < g_ldCount; k++)
        if (!g_lds[k].unloaded)
            for (int i = 0; i < g_lds[k].packCount; i++)
                if ((DWORD)g_lds[k].packs[i] == pack)
                    return g_packList[pack] != 0;
    return false;
}

static BYTE* ReadAll(const char* name, DWORD* size)
{
    FILE* f = fopen(name, "rb");
    if (!f)
        return nullptr;
    fseek(f, 0, SEEK_END);
    *size = ftell(f);
    fseek(f, 0, SEEK_SET);
    BYTE* b = (BYTE*)malloc(*size ? *size : 1);
    fread(b, 1, *size, f);
    fclose(f);
    return b;
}

static void ReadMap()
{
    g_file = ReadAll("map.bun", &g_fileSize);  // a variant's other map file (run.py copies it as map.bun too)
    if (!g_file)
        g_file = ReadAll("ftown-slab.bun", &g_fileSize);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA("ftown-barriers*.bun", &fd);
    while (h != INVALID_HANDLE_VALUE && g_barFileCount < 8)
    {
        g_barFiles[g_barFileCount] = ReadAll(fd.cFileName, &g_barFileSizes[g_barFileCount]);
        g_barFileCount++;
        if (!FindNextFileA(h, &fd))
            break;
    }
    if (h != INVALID_HANDLE_VALUE)
        FindClose(h);
}

// ---------------------------------------------------------------- the evening (FTownEvening.h)
//
// The time-of-day object at *(0x9B392C) (rate +0, direction +4, time +8) moved once a frame after the plugin's hook as
// the game's update does (here 0.01 a frame, bounced at 0.05 / 0.95); todset=<f> sets the time to 0.5 on frame f
// before the hook (SetTimeOfDay at a race start); evewrong: SetTimeOfDay's first byte differs. A TOD line every 10
// frames. LoadChunks reports how many of ftown-evening.bin's vertices the buffer holds lit or as by day.
static float g_tod[0x190 / 4];
static int g_todSetFrame = -1;
static int g_todOverride;  // todoverride: the update ends at time 0.6 every frame (a wrapper that keeps its own)

static void TodStep()
{
    float rate = g_tod[0], t = g_tod[2];
    int dir = *(int*)&g_tod[1];
    t += 0.01f * dir * rate;
    if (t > 0.95f) t = 0.95f, dir = -dir;
    if (t < 0.05f) t = 0.05f, dir = -dir;
    g_tod[2] = g_todOverride ? 0.6f : t;
    *(int*)&g_tod[1] = dir;
    if (g_frame % 10 == 0)
        printf("TOD f=%d t=%.3f rate=%.2f dir=%d head=%lu\n", g_frame, t, rate, dir, (unsigned long)Get(0x9B092C));
}

static void LightsReport(const BYTE* buf, int size)
{
    FILE* f = fopen("ftown-evening.bin", "rb");
    if (!f)
        return;
    DWORD h[5];
    int lit = 0, day = 0, n = 0;
    if (fread(h, 4, 5, f) == 5)
        for (DWORD k = 0; k < h[3]; k++)
        {
            DWORD e[6];
            if (fread(e, 4, 6, f) != 6 || e[0] > (DWORD)size - 36)
                break;
            DWORD c;
            memcpy(&c, buf + e[0] + 24, 4);
            float pos[3], orig[3], d[3];
            memcpy(pos, buf + e[0], 12);
            memcpy(orig, g_file + e[0], 12);
            memcpy(d, &e[1], 12);
            bool moved = fabsf(pos[0] - orig[0] - d[0]) < 1e-4f && fabsf(pos[1] - orig[1] - d[1]) < 1e-4f &&
                         fabsf(pos[2] - orig[2] - d[2]) < 1e-4f;
            lit += c == e[5] && moved;
            day += c == e[4] && !memcmp(pos, orig, 12);
            n++;
        }
    fclose(f);
    printf("LIGHTS lit %d day %d of %d\n", lit, day, n);
}

// ---------------------------------------------------------------- the breakable poles (FTownSmack.h)
//
// The game's smackable spawner loader (0x6829D0) and unloader (0x67C040) as read in speed.exe (docs/ftown-notes.md
// "Breakable poles (2026-11-05)"), for chunk 0x34027 in a LoadChunks named FTOWNSMK: nothing without a simulation
// ([0x9885E0]); the pack at (chunk + 0x17) & ~0xF; per record not excluded by the loader's flags (0x40000 here): its
// override entry read from [0x9A3A64] + index * 6 with no bounds check (an index past [0x9A3A68] is printed as PAST THE
// TABLE: what the game would read is not ours), the instance shown (entry flags & ~0x10, AssignOverrides: the
// instance's low 16 exclude bits = the entry's), a scenery model (at most 0x800 live, [0x92617C]; none: the instance
// hidden) at record +0x38, its trigger added to the node of the grid cell at its position (type 1; a cell with no node
// loses it: TRIGGER LOST). A car within 1.5 m of a pole whose trigger is in the car's cell fires it: the pole flies
// (60 frames), the instance hides (0x10). The unloader deletes every model (the instance shown again through the
// entry, the trigger taken out of its node) and must find its entries in the table it was loaded with.
// Arguments: smkcount=<n> (Rockport's table holds n entries, 22340 by default), smkwrong (0x723C90's bytes differ).
static DWORD Clamp(float v, float mn, float inv, DWORD n);
static void PutBytes(DWORD at, std::initializer_list<int> b);
static const DWORD kStRockOverrides = 22340;
static BYTE g_rockTable[22340 * 6], g_rockPristine[22340 * 6];
struct SmkModel
{
    BYTE* rec;
    DWORD index;  // override number
    Node* node;
    BYTE* buf;
    bool fired, gone;
    int flyUntil;
};
static SmkModel g_smkModels[2200];
static int g_smkModelCount, g_smkFlying;

static BYTE* SmkEntry(DWORD index, bool* past)
{
    *past = index >= Get(0x9A3A68);
    return (BYTE*)(UINT_PTR)Get(0x9A3A64) + 6 * index;
}

// AssignOverrides (0x728920 -> 0x728850): the section's header through UserInfoTable; the instance's low 16 bits
static void SmkAssign(const BYTE* entry)
{
    short section = *(const short*)entry, inst = *(const short*)(entry + 2);
    DWORD info = Get(0x9A3BB0 + 4 * section);
    DWORD header = info ? *(DWORD*)(UINT_PTR)(info + 4) : 0;
    if (!header)
        return;
    BYTE* instances = (BYTE*)(UINT_PTR)*(DWORD*)(UINT_PTR)(header + 0x20);
    DWORD* flags = (DWORD*)(instances + 0x40 * inst + 0x18);
    *flags = (*flags & 0xFFFF0000u) | *(const WORD*)(entry + 4);
}

static Node* SmkCellNode(const float* phys)
{
    GridObj* g = (GridObj*)(UINT_PTR)Get(0x9B38A8);
    if (!g)
        return nullptr;
    DWORD c = Clamp(phys[0], g->min[0], g->invEdge, g->cols), r = Clamp(phys[2], g->min[2], g->invEdge, g->rows);
    return (Node*)(UINT_PTR)g->nodes[r * g->cols + c];
}

static bool SmkInList(Node* n, DWORD tag)
{
    if (!n || !n->list)
        return false;
    DWORD* list = (DWORD*)(UINT_PTR)n->list;
    Elem* head = (Elem*)(UINT_PTR)list[1];
    for (Elem* e = head->next; e != head; e = e->next)
        if (e->ind == tag && e->type == 1)
            return true;
    return false;
}

static void SmkLoadChunks(BYTE* buf, int size)
{
    if (!Get(0x9885E0))
    {
        printf("SMKLOAD no simulation: nothing made\n");
        return;
    }
    bool same = !memcmp((void*)(UINT_PTR)Get(0x9A3A64), g_rockTable, sizeof(g_rockTable));
    printf("SMK TABLE %s count %lu, Rockport's part %s\n",
           Get(0x9A3A64) == (DWORD)(UINT_PTR)g_rockTable ? "rockport" : "ours", (unsigned long)Get(0x9A3A68),
           same ? "same" : "CHANGED");
    // review: the game changes Rockport's entries while ours is installed (SceneryGroup 0x72B9E5 / 0x72BA45 flip
    // 0x10): entry 5's flip, made here in the table in use, must be in Rockport's table after the restore
    if (Get(0x9A3A64) != (DWORD)(UINT_PTR)g_rockTable)
    {
        ((BYTE*)(UINT_PTR)Get(0x9A3A64))[6 * 5 + 4] ^= 0x10;
        g_rockPristine[6 * 5 + 4] ^= 0x10;  // what Rockport's table must hold at the end
    }
    int packs = 0, recs = 0, models = 0, triggers = 0, lost = 0, past = 0;
    DWORD off = 0;
    while (off + 8 <= (DWORD)size)
    {
        DWORD id = *(DWORD*)(buf + off), sz = *(DWORD*)(buf + off + 4);
        if (id == 0x34027)
        {
            BYTE* h = (BYTE*)(((DWORD)(UINT_PTR)(buf + off) + 0x17) & ~0xFu);
            h[0xE] = 1;  // swapped
            packs++;
            for (int r = 0; r < *(short*)(h + 0xC); r++)
            {
                BYTE* rec = h + 16 + 0x40 * r;
                recs++;
                if (*(DWORD*)(rec + 0x34) & 0x40000)
                    continue;
                bool out = false;
                BYTE* entry = SmkEntry(*(DWORD*)(rec + 0x2C), &out);
                if (out)
                {
                    past++;
                    continue;
                }
                entry[4] &= 0xEF;  // shown
                SmkAssign(entry);
                if (Get(0x92617C) >= 0x800 || g_smkModelCount >= 2200)
                {
                    entry[4] |= 0x10;  // no model: the static instance hidden
                    SmkAssign(entry);
                    *(DWORD*)(rec + 0x38) = 0;
                    continue;
                }
                SmkModel& m = g_smkModels[g_smkModelCount++];
                memset(&m, 0, sizeof(m));
                m.rec = rec;
                m.buf = buf;
                m.index = *(DWORD*)(rec + 0x2C);
                *(DWORD*)(rec + 0x38) = (DWORD)(UINT_PTR)&m;
                Put(0x92617C, Get(0x92617C) + 1);
                models++;
                m.node = SmkCellNode((const float*)(rec + 0x10));
                if (m.node)
                {
                    StAddDynamic(m.node, nullptr, (DWORD)(UINT_PTR)&m, 1);
                    triggers++;
                }
                else
                {
                    lost++;
                    printf("SMK TRIGGER LOST at physics %.1f %.1f\n", ((float*)(rec + 0x10))[0], ((float*)(rec + 0x10))[2]);
                }
            }
        }
        off += 8 + sz;
    }
    printf("SMKLOAD packs %d records %d models %d triggers %d lost %d past %d live %lu\n", packs, recs, models, triggers,
           lost, past, (unsigned long)Get(0x92617C));
    if (past)
        printf("SMK OVERRIDE PAST THE TABLE (%d records)\n", past);
}

static void SmkUnloadChunks(BYTE* buf)
{
    if (!Get(0x9885E0))
    {
        printf("SMKUNLOAD no simulation: nothing deleted\n");
        return;
    }
    int models = 0, removed = 0, past = 0;
    for (int k = 0; k < g_smkModelCount; k++)
    {
        SmkModel& m = g_smkModels[k];
        if (m.gone || m.buf != buf)
            continue;
        bool out = false;
        BYTE* entry = SmkEntry(m.index, &out);
        if (out)
            past++;
        else
        {
            entry[4] &= 0xEF;  // the model's destructor shows the instance again
            SmkAssign(entry);
        }
        if (!m.fired && m.node)
        {
            DWORD* list = (DWORD*)(UINT_PTR)m.node->list;
            StRemoveList(list, nullptr, (DWORD)(UINT_PTR)&m, 1);
            removed++;
        }
        *(DWORD*)(m.rec + 0x38) = 0;
        m.gone = true;
        Put(0x92617C, Get(0x92617C) - 1);
        models++;
    }
    printf("SMKUNLOAD models %d triggers removed %d table %s count %lu live %lu\n", models, removed,
           Get(0x9A3A64) == (DWORD)(UINT_PTR)g_rockTable ? "rockport" : "ours", (unsigned long)Get(0x9A3A68),
           (unsigned long)Get(0x92617C));
    if (past)
        printf("SMK UNLOAD READS PAST THE TABLE (%d models)\n", past);
}

// once a frame after the plugin's hook: a car in a live pole's trigger fires it; flying poles land after 60 frames
static void SmkFrame()
{
    Node* carNode = SmkCellNode(g_pos);
    for (int k = 0; k < g_smkModelCount; k++)
    {
        SmkModel& m = g_smkModels[k];
        if (m.gone || m.fired)
            continue;
        const float* p = (const float*)(m.rec + 0x10);
        if (fabsf(p[0] - g_pos[0]) > 1.5f || fabsf(p[2] - g_pos[2]) > 1.5f)
            continue;
        if (!SmkInList(carNode, (DWORD)(UINT_PTR)&m))
            continue;  // the trigger is not where the game's query looks
        m.fired = true;
        m.flyUntil = g_frame + 60;
        g_smkFlying++;
        bool out = false;
        BYTE* entry = SmkEntry(m.index, &out);
        if (!out)
        {
            entry[4] |= 0x10;  // the static instance hidden while the pole flies
            SmkAssign(entry);
        }
        StRemoveList((DWORD*)(UINT_PTR)carNode->list, nullptr, (DWORD)(UINT_PTR)&m, 1);
        printf("SMK FIRE uid %lu at render %.1f %.1f: the pole flies%s\n", (unsigned long)*(DWORD*)(m.rec + 0x30), p[2],
               -p[0], out ? " (ITS ENTRY PAST THE TABLE)" : "");
    }
    for (int k = 0; k < g_smkModelCount; k++)
        if (g_smkModels[k].fired && g_smkModels[k].flyUntil == g_frame)
        {
            g_smkFlying--;
            printf("SMK LANDED (the flying pole's own body: Rockport's volume and hierarchy, its model by hash)\n");
        }
}

static void SmkSetup(int count, bool wrong)
{
    for (DWORD i = 0; i < kStRockOverrides; i++)
    {
        short s = (short)(100 + i % 700), n = (short)(i / 700);
        WORD f = (WORD)(0x8000 | (i & 1));
        memcpy(g_rockTable + 6 * i, &s, 2);
        memcpy(g_rockTable + 6 * i + 2, &n, 2);
        memcpy(g_rockTable + 6 * i + 4, &f, 2);
    }
    memcpy(g_rockPristine, g_rockTable, sizeof(g_rockTable));
    memset((void*)0x926000, 0, 0x1000);  // the live scenery models' count [0x92617C]: none
    Put(0x9A3A64, (DWORD)(UINT_PTR)g_rockTable);
    Put(0x9A3A68, (DWORD)count);
    PutBytes(0x887C40, {0x68, 0x40, 0xC0, 0x67, 0x00, 0x68, 0xD0, 0x29, 0x68, 0x00, 0x68, 0x27, 0x40, 0x03, 0x00});
    PutBytes(0x6829D0, {0x8B, 0x44, 0x24, 0x04, 0x81, 0x38, 0x27, 0x40, 0x03, 0x00, 0x0F, 0x85, 0xA2, 0x00, 0x00, 0x00,
                        0x56, 0x8D, 0x70, 0x17, 0xA1, 0x60, 0x58, 0x92, 0x00, 0x83, 0xE6, 0xF0});
    PutBytes(0x6829FE, {0x8A, 0x46, 0x0E, 0x84, 0xC0, 0x75, 0x1B, 0x33, 0xC0, 0x66, 0x39, 0x46, 0x0C});
    PutBytes(0x682A20, {0xE8, 0xEB, 0x62, 0x06, 0x00, 0x84, 0xC0, 0x74, 0x52});
    PutBytes(0x6828D0, {0x83, 0xEC, 0x08, 0x55, 0x8B, 0xE9, 0x0F, 0xBF, 0x45, 0x08, 0x56, 0x57, 0x50, 0xB9, 0xC0, 0x61,
                        0x92, 0x00});
    PutBytes(0x681620, {0x8B, 0x44, 0x24, 0x04, 0x56, 0x8B, 0xF1, 0x85, 0x46, 0x34, 0x75, 0x49, 0x8B, 0x4E, 0x2C, 0x51,
                        0xE8, 0x5B, 0x26, 0x0A, 0x00});
    PutBytes(0x68154E, {0xA1, 0x7C, 0x61, 0x92, 0x00});
    PutBytes(0x68155D, {0x3D, 0x00, 0x08, 0x00, 0x00});
    PutBytes(0x723C90, {0x8B, 0x44, 0x24, 0x04, 0x8B, 0x0D, 0x64, 0x3A, 0x9A, 0x00, 0x8D, 0x04, 0x40, 0x8D, 0x04, 0x41});
    PutBytes(0x7287F0, {0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x7C, 0x50, 0x3B, 0x05, 0x68, 0x3A, 0x9A, 0x00, 0x7D, 0x48,
                        0x8B, 0x0D, 0x64, 0x3A, 0x9A, 0x00});
    PutBytes(0x728920, {0x0F, 0xBF, 0x01, 0x8B, 0x04, 0x85, 0xB0, 0x3B, 0x9A, 0x00, 0x85, 0xC0, 0x74, 0x0D, 0x8B, 0x40,
                        0x04, 0x85, 0xC0});
    PutBytes(0x67BC3B, {0x8B, 0x45, 0x2C, 0x56, 0x57, 0x8B, 0xF1, 0x50, 0x89, 0x74, 0x24, 0x10, 0xE8, 0x44, 0x80, 0x0A,
                        0x00});
    PutBytes(0x67C040, {0x56, 0x8B, 0x74, 0x24, 0x08, 0x81, 0x3E, 0x27, 0x40, 0x03, 0x00, 0x75, 0x24, 0xA1, 0x60, 0x58,
                        0x92, 0x00, 0x85, 0xC0, 0x75, 0x14, 0xE8, 0xB5, 0xCC, 0x06, 0x00, 0x84, 0xC0, 0x74, 0x0B});
    PutBytes(0x6E8D10, {0x8B, 0x0D, 0xE0, 0x85, 0x98, 0x00, 0x33, 0xC0, 0x85, 0xC9, 0x0F, 0x95, 0xC0, 0xC3});
    if (wrong)
        *(BYTE*)0x723C96 = 0x90;
}

static void SmkReport()
{
    printf("SMK ROCKPORT TABLE ptr %s count %lu entries %s live %lu flying %d\n",
           Get(0x9A3A64) == (DWORD)(UINT_PTR)g_rockTable ? "game" : "OURS", (unsigned long)Get(0x9A3A68),
           memcmp(g_rockTable, g_rockPristine, sizeof(g_rockTable)) ? "CHANGED" : "same", (unsigned long)Get(0x92617C),
           g_smkFlying);
}

// the scenery loader's run-time fields of a section header (+0x20 instances, +0x24 their count), as LoaderScenery
// fills them (Scenery.cpp:323): the 0x34103 child's data aligned to 16
static void FillSceneryHeader(BYTE* data, DWORD sz)
{
    BYTE* header = nullptr;
    DWORD off = 0;
    while (off + 8 <= sz)
    {
        DWORD id = *(DWORD*)(data + off), csz = *(DWORD*)(data + off + 4);
        BYTE* d = data + off + 8;
        if (id == 0x34101)
            header = d;
        else if (id == 0x34103 && header)
        {
            BYTE* a = (BYTE*)(((DWORD)(UINT_PTR)d + 15) & ~15u);
            *(DWORD*)(header + 0x20) = (DWORD)(UINT_PTR)a;
            *(DWORD*)(header + 0x24) = (csz - (DWORD)(a - d)) / 0x40;
        }
        off += 8 + csz;
    }
}

static void __cdecl StLoadChunks(BYTE* buf, int size, const char* name)
{
    if (name && !strcmp(name, "FTOWNMAP"))
    {
        MinimapPackLoad(buf, size);
        return;
    }
    if (name && !strcmp(name, "FTOWNSMK"))
    {
        SmkLoadChunks(buf, size);
        return;
    }
    if (name && !strcmp(name, "FTOWNICONS"))  // the menu's icons (Run I item 13): a texture pack, kept loaded
    {
        int before = g_mmHashCount;
        WalkKeys(buf, buf + size);
        printf("ICONPACK LOAD %d bytes textures %d\n", size, g_mmHashCount - before);
        g_mmHashCount = before;
        return;
    }
    bool bar = name && !strcmp(name, "FTOWNBAR");
    if (bar)
        g_barLoads++;
    else
        g_loads++;
    bool pristine = !bar && g_file && (DWORD)size == g_fileSize && !memcmp(buf, g_file, size);
    for (int k = 0; bar && k < g_barFileCount; k++)
        pristine |= g_barFiles[k] && (DWORD)size == g_barFileSizes[k] && !memcmp(buf, g_barFiles[k], size);
    printf("LOADCHUNKS %d bytes name %s pristine %d aligned %d\n", size, name ? name : "(null)", pristine ? 1 : 0,
           ((DWORD)(UINT_PTR)buf & 127) == 0 ? 1 : 0);
    if (!bar && g_file && (DWORD)size == g_fileSize)
        LightsReport(buf, size);
    if (!bar)
    {
        g_loaded = buf;
        g_loadedSize = size;
    }
    if (g_ldCount == 32)
        return;
    Loaded& L = g_lds[g_ldCount++];
    memset(&L, 0, sizeof(L));
    L.buf = buf;
    L.size = size;
    L.bar = bar;
    DWORD off = 0;
    while (off + 8 <= (DWORD)size)
    {
        DWORD id = *(DWORD*)(buf + off), sz = *(DWORD*)(buf + off + 4);
        BYTE* data = buf + off + 8;
        if (id == 0x80034100 && L.numberCount < 64)
        {
            int number = *(int*)(data + 8 + 0x0C), k = L.numberCount++;
            L.numbers[k] = number;
            if (!g_nofile)
            {
                L.info[k][0] = 1;
                L.info[k][1] = (DWORD)(UINT_PTR)(data + 8);
                Put(0x9A3BB0 + 4 * number, (DWORD)(UINT_PTR)L.info[k]);
                FillSceneryHeader(data, sz);
            }
        }
        else if (id == 0x3B801)
        {
            DWORD run = (16 - ((off + 8) & 15)) & 15;
            BYTE* d = data + run;
            int packNo = *(int*)(d + 4);
            if (L.packCount < 64)
                L.packs[L.packCount++] = packNo;
            // the game resolves a pack in place (flags 1, its own address): a second load of the same bytes would
            // see them resolved
            DWORD flags = *(DWORD*)(d + 8);
            if (flags)
                printf("LOADCHUNKS DIRTY: the collision pack is already resolved\n");
            *(DWORD*)(d + 8) = 1;
            *(DWORD*)(d + 12) = (DWORD)(UINT_PTR)d;
            if (!g_nofile && packNo != g_nofileNumber)
                g_packList[packNo] = (DWORD)(UINT_PTR)g_fakePack;
            g_collider[1] = (DWORD)(UINT_PTR)d;  // a collider caches one of our instances
            ((BYTE*)g_collider)[0x80] = 1;
        }
        off += 8 + sz;
    }
}

static bool GridHasTagsOfLoad(const Loaded& L)
{
    for (int i = 0; i < L.packCount; i++)
        if (GridHasTagsOf((DWORD)L.packs[i]))
            return true;
    return false;
}

static void __cdecl StUnloadChunks(BYTE* buf, int size, const char* name)
{
    if (name && !strcmp(name, "FTOWNMAP"))
    {
        MinimapPackUnload(buf);
        return;
    }
    if (name && !strcmp(name, "FTOWNSMK"))
    {
        SmkUnloadChunks(buf);
        return;
    }
    if (!(name && !strcmp(name, "FTOWNBAR")))  // the breakable poles: the game's table back before the city goes
        printf("SMK AT CITY UNLOAD table %s count %lu live %lu\n",
               Get(0x9A3A64) == (DWORD)(UINT_PTR)g_rockTable ? "rockport" : "OURS", (unsigned long)Get(0x9A3A68),
               (unsigned long)Get(0x92617C));
    bool bar = name && !strcmp(name, "FTOWNBAR");
    if (bar)
        g_barUnloads++;
    else
        g_unloads++;
    Loaded* L = nullptr;
    for (int k = g_ldCount - 1; k >= 0 && !L; k--)
        if (g_lds[k].buf == buf && !g_lds[k].unloaded)
            L = &g_lds[k];
    MEMORY_BASIC_INFORMATION mi;
    VirtualQuery(buf, &mi, sizeof(mi));
    bool readable = mi.State == MEM_COMMIT;
    bool stale = g_collider[1] >= (DWORD)(UINT_PTR)buf && g_collider[1] < (DWORD)(UINT_PTR)buf + size;
    printf("UNLOADCHUNKS %d bytes%s same buffer %d readable %d grid %s colliders %s car %s\n", size,
           bar ? " name FTOWNBAR" : "", L ? 1 : 0, readable ? 1 : 0,
           L && GridHasTagsOfLoad(*L) ? "STILL HAS OUR TAGS" : "clean", stale ? "STILL HOLD OUR INSTANCES" : "clean",
           !InRockport(g_pos) ? "ftown" : g_rockStreamed ? "rockport" : "rockport WITHOUT GROUND");
    if (!L)
        return;
    for (int i = 0; i < L->numberCount; i++)
        Put(0x9A3BB0 + 4 * L->numbers[i], 0);
    for (int i = 0; i < L->packCount; i++)
        g_packList[L->packs[i]] = 0;
    L->unloaded = true;
}

// the height query: the point's cell as WGrid::GetRowCol finds it; a face when a tag of one of our filed packs is in it
static DWORD Clamp(float v, float mn, float inv, DWORD n)
{
    DWORD i = (DWORD)(long)((v - mn) * inv);
    if (i >= n)
        i = i > 0x7FFFFFFEu ? 0 : n - 1;
    return i;
}

// moving traffic: a node's stored instance tags (type 0: the widened grid's nodes of FTownLoader hold the city's)
static bool StaticOurs(Node* n)
{
    if (!n)
        return false;
    const DWORD* tags = (const DWORD*)((const BYTE*)n + 0x14 + n->offsets[0]);
    for (int k = 0; k < n->counts[0]; k++)
        if (OursFiled(tags[k] >> 16))
            return true;
    return false;
}

// a face under the point by the stand-in's rule: Rockport while streamed, F-Town where a cell holds our filed tags
static float g_noFaceX = -1;  // nofaceat=<render x>: no face within 1 m of that x (a spot with no ground)
static bool FaceAt(const float* pt)
{
    if (g_noFaceX >= 0 && fabsf(pt[2] - g_noFaceX) < 1.0f)
        return false;
    if (InRockport(pt))
        return g_rockStreamed != 0;
    DWORD col = Clamp(pt[0], g_grid.min[0], g_grid.invEdge, g_grid.cols);
    DWORD row = Clamp(pt[2], g_grid.min[2], g_grid.invEdge, g_grid.rows);
    Node* n = (Node*)(UINT_PTR)g_grid.nodes[row * g_grid.cols + col];
    bool found = StaticOurs(n);
    if (n && n->list)
    {
        DWORD* list = (DWORD*)(UINT_PTR)n->list;
        Elem* head = (Elem*)(UINT_PTR)list[1];
        for (Elem* e = head->next; e != head; e = e->next)
            found |= e->type == 0 && OursFiled(e->ind >> 16);
    }
    return found && !g_noface;
}

static bool __fastcall StHeight(DWORD* mgr, void*, const float* pt, float* h, float* normal)
{
    if (mgr[0] != 0 || mgr[1] != 3)
        printf("HEIGHT bad manager\n");
    if (InRockport(pt))  // Rockport (WorldProbe's POS lines, the return's check): faces only while streamed
    {
        printf("HEIGHT %.2f %.2f %.2f rockport -> %s\n", pt[0], pt[1], pt[2], g_rockStreamed ? "face" : "none");
        if (!g_rockStreamed)
            return false;
        *h = 112.5f;
        normal[0] = 0, normal[1] = 1, normal[2] = 0;
        return true;
    }
    DWORD col = Clamp(pt[0], g_grid.min[0], g_grid.invEdge, g_grid.cols);
    DWORD row = Clamp(pt[2], g_grid.min[2], g_grid.invEdge, g_grid.rows);
    Node* n = (Node*)(UINT_PTR)g_grid.nodes[row * g_grid.cols + col];
    bool found = StaticOurs(n);
    if (n && n->list)
    {
        DWORD* list = (DWORD*)(UINT_PTR)n->list;
        Elem* head = (Elem*)(UINT_PTR)list[1];
        for (Elem* e = head->next; e != head; e = e->next)
            found |= e->type == 0 && OursFiled(e->ind >> 16);
    }
    found = found && !g_noface;
    printf("HEIGHT %.2f %.2f %.2f cell %lu -> %s\n", pt[0], pt[1], pt[2], (unsigned long)(row * g_grid.cols + col),
           found ? "face" : "none");
    if (found)
    {
        *h = 100.0f;
        normal[0] = 0, normal[1] = 1, normal[2] = 0;
    }
    return found;
}

static void __fastcall StTrackUnload(void* self, void*) { printf("TRACKUNLOAD this 0x%08lX\n", (unsigned long)(UINT_PTR)self); }
static unsigned __cdecl StTicker() { return (unsigned)g_frame; }
static void __cdecl StWaitRendering() {}
static int g_link;  // the connection's variants (below): 2 with its sites, 1 without
static void* LkFind(float x, float y);
static void* __fastcall FindDrivable(void*, void*, const float* v2)
{
    if (g_link)
        return LkFind(v2[0], v2[1]);
    static DWORD drivable[8] = {0, 0, 0, 309};
    return v2[1] < 5000.0f ? drivable : nullptr;
}

// drive=<frame>:<x>,<y>: the car is at render (x, y) from that frame on (the height kept), as if driven there
struct Drive
{
    int frame;
    float x, y;
};
static Drive g_drives[16], g_jumps[4];
static int g_driveCount, g_jumpCount;

// route=<frame>:<metres a frame> (up to 2): from that frame the car drives the Time Attack's route as FTownLoader.ini
// [TimeAttack] gives it (Start, Gate1.., Finish, then 50 m on), one step a simulation frame (none while paused);
// routeskip=<k>: around gate k at 300 m to the side (a missed checkpoint); pause=<a>-<b>: the game paused on those
// frames (no simulation time, no movement)
static int g_routeFrames[2], g_routeCount, g_routeSkip = -1, g_pauseA = -1, g_pauseB = -1;
static float g_routeSteps[2];
static float g_path[2048][2];
static int g_pathCount, g_routeOn = -1, g_routeMoving;
static float g_routeAt;  // metres along the path

static void BuildPath()
{
    char buf[128], key[16];
    float v[4];
    g_pathCount = 0;
    // route.txt (run.py writes it from the events file: the event's start, then each gate "x y heading", the finish
    // last): the path through them, then 50 m on
    FILE* rf = fopen("route.txt", "r");
    if (rf)
    {
        float h = 0;
        int k = 0;
        while (g_pathCount < 2040 && fgets(buf, sizeof(buf), rf))
        {
            if (sscanf(buf, "%f %f %f", &v[0], &v[1], &v[2]) != 3)
                continue;
            if (k++ > 0)
                h = v[2] * 3.14159265f / 180.0f;
            if (k - 1 == g_routeSkip)  // 300 m to the left of gate k
            {
                v[0] += -sinf(h) * 300.0f;
                v[1] += cosf(h) * 300.0f;
            }
            g_path[g_pathCount][0] = v[0], g_path[g_pathCount++][1] = v[1];
        }
        fclose(rf);
        if (g_pathCount)
        {
            g_path[g_pathCount][0] = g_path[g_pathCount - 1][0] + cosf(h) * 50.0f;
            g_path[g_pathCount][1] = g_path[g_pathCount - 1][1] + sinf(h) * 50.0f;
            g_pathCount++;
        }
        return;
    }
    GetPrivateProfileStringA("TimeAttack", "Start", "", buf, sizeof(buf), ".\\FTownLoader.ini");
    if (sscanf(buf, "%f , %f , %f , %f", &v[0], &v[1], &v[2], &v[3]) != 4)
        return;
    g_path[g_pathCount][0] = v[0], g_path[g_pathCount++][1] = v[1];
    float h = 0;
    for (int k = 1; k <= 17 && g_pathCount < 30; k++)
    {
        if (k <= 16)
            snprintf(key, sizeof(key), "Gate%d", k);
        else
            strcpy(key, "Finish");
        GetPrivateProfileStringA("TimeAttack", key, "", buf, sizeof(buf), ".\\FTownLoader.ini");
        if (sscanf(buf, "%f , %f , %f", &v[0], &v[1], &v[2]) != 3)
        {
            if (k <= 16)
            {
                k = 16;  // no more gates: the finish next
                continue;
            }
            break;
        }
        h = v[2] * 3.14159265f / 180.0f;
        if (k == g_routeSkip)  // 300 m to the left of the gate
        {
            v[0] += -sinf(h) * 300.0f;
            v[1] += cosf(h) * 300.0f;
        }
        g_path[g_pathCount][0] = v[0], g_path[g_pathCount++][1] = v[1];
    }
    g_path[g_pathCount][0] = g_path[g_pathCount - 1][0] + cosf(h) * 50.0f;
    g_path[g_pathCount][1] = g_path[g_pathCount - 1][1] + sinf(h) * 50.0f;
    g_pathCount++;
}

static void RouteStep()
{
    for (int r = 0; r < g_routeCount; r++)
        if (g_routeFrames[r] == g_frame)
        {
            g_routeOn = r;
            g_routeAt = 0;
            g_routeMoving = 0;
            printf("ROUTE %d starts, %.2f m a frame\n", r + 1, g_routeSteps[r]);
        }
    g_speedNow = 0;
    if (g_routeOn < 0)
        return;
    g_routeAt += g_routeSteps[g_routeOn];
    g_speedNow = g_routeSteps[g_routeOn] * 30.0f;
    g_routeMoving++;
    float left = g_routeAt;
    for (int k = 0; k + 1 < g_pathCount; k++)
    {
        float dx = g_path[k + 1][0] - g_path[k][0], dy = g_path[k + 1][1] - g_path[k][1], len = sqrtf(dx * dx + dy * dy);
        if (left <= len)
        {
            g_pos[2] = g_path[k][0] + dx * left / len;
            g_pos[0] = -(g_path[k][1] + dy * left / len);
            return;
        }
        left -= len;
    }
    printf("ROUTE DONE after %d moving frames\n", g_routeMoving);
    g_routeOn = -1;
}

// ---------------------------------------------------------------- the front end (docs/ftown-race-notes.md R5, R6)
//
// fe=<a1,a2,...>: one action a frame from frame 1, the player absent until "start": qr (the Quick Race main menu is
// built: QuickPlay and CustomRace, CustomRace through the AddOption call at 0x7AA81C as the game's Setup makes it),
// pick:<name> (the option named so on the screen: its React with "pressed", then the screen's NotificationMessage with
// pressed and EXITCOMPLETE), back (Back and EXITCOMPLETE; on the car select the game's Back path through 0x7C26ED),
// start (the car select's start: the race begins). A package switch (cFEng::QueuePackageSwitch) is printed and the
// screen it names built before the next action (MainMenu_Sub.fng: the mode select while FEDatabase +0x12C has 0x400,
// through the ctor's Setup call 0x7BA4D7 and RefreshHeader's title call 0x7A2F6D; else the Quick Race main menu).
// countdown=<f>: the HUD's countdown begins on frame f (4, then 3, 2, 1 a second apart, 0 = GO, -1 six seconds later);
// restart=<f>: the pause menu's Restart Race on frame f (the car back at the Rockport start, the countdown again);
// nocd (the HUD has no countdown); carriertype=<n> (the carrier's race kind); menuwrong (a menu site's byte differs).
static DWORD g_fedb[0x200 / 4];
static DWORD g_feObj[4];
static DWORD g_raceDb[0x40];
static DWORD g_race[8], g_custom[16];
static DWORD g_dragRace[8];  // Run J item 4: the drag carrier 11.7.1 (kind 2; nodragcarrier: not in the database)
static int g_noDragCarrier, g_dragSteer;
static int g_carrierType;
static const char* g_feActs[32];
static int g_feActCount, g_feAt, g_feOn;
static char g_pending[64];
enum Screen
{
    SCR_NONE,
    SCR_QR,
    SCR_MODE,
    SCR_CAR,
    SCR_OTHER,
};
static int g_screen;
static DWORD g_menu[0x200 / 4];  // the screen's menu object (+0x10 the package name, +0x138 the previous button)
static void* g_opts[16];
static int g_optCount;
static int g_cdStart = -1, g_restartFrame = -1, g_cdCount = -1;
static bool g_raceStarted;

static const char* Text(DWORD hash) { return ((const char*(__cdecl*)(DWORD))0x56BC60)(hash); }

static const char* __fastcall StLookup(DWORD, DWORD hash)
{
    static const struct
    {
        DWORD h;
        const char* t;
    } table[] = {{0xB5E8F82F, "QUICK PLAY"}, {0x25BBD4C3, "CUSTOM RACE"}, {0x34FA2C1, "CIRCUIT"}, {0xB94FD70E, "SPRINT"},
                 {0x6F547E4C, "DRAG"},       {0x4930F5FC, "KNOCKOUT"},    {0xEE1EDC76, "SPEEDTRAP"},
                 {0x1F203817, "SELECT MODE"}, {0x9BB9CCC3, "(missing string)"}};
    for (auto& e : table)
        if (e.h == hash)
            return e.t;
    return nullptr;
}

static void* __cdecl StNew(unsigned size) { return calloc(1, size); }
static void* __fastcall StIconCtor(DWORD* o, void*, DWORD tex, DWORD name, DWORD desc)
{
    o[0] = 0x89B8C8;
    o[0xC / 4] = tex;
    o[0x2C / 4] = name;
    o[0x30 / 4] = desc;
    return o;
}
static void __fastcall StAddOption(DWORD* menu, void*, void* opt)
{
    if (menu != g_menu)
        printf("ADDOPTION BAD THIS\n");
    if (g_optCount < 16)
        g_opts[g_optCount++] = opt;
}
static void __fastcall StSetInitial(DWORD* menu, void*, int k) { printf("SETINITIAL %d\n", k); }
static void __fastcall StScrollerNotify(DWORD* menu, void*, DWORD msg, void*, DWORD, DWORD)
{
    if (msg == 0xC407210 || msg == 0x911AB364)
        menu[0x138 / 4] = msg;
}
static void __fastcall StSwitch(void* fe, void*, const char* name, int, unsigned, bool)
{
    printf("SWITCH %s%s\n", name, fe == g_feObj ? "" : " BAD THIS");
    strncpy(g_pending, name, sizeof(g_pending) - 1);
}
static void __fastcall StQueueMessage(void* fe, void*, DWORD msg, const char* pkg, void*)
{
    printf("QUEUEMESSAGE %08lX %s\n", (unsigned long)msg, pkg ? pkg : "(null)");
}
static void __cdecl StSetLangHash(const char*, DWORD obj, DWORD hash)
{
    const char* t = Text(hash);
    printf("TITLE %s\n", t ? t : "(null)");
}
static void* __fastcall StRaceFromName(void* db, void*, const char* name)
{
    printf("RACEFROMNAME %s%s\n", name, db == g_raceDb ? "" : " BAD THIS");
    if (!strcmp(name, "11.7.1"))
        return g_noDragCarrier ? nullptr : g_dragRace;
    return !strcmp(name, "15.2.1") ? g_race : nullptr;
}
static int __fastcall StRaceType(void* race, void*)
{
    return race == g_race ? g_carrierType : race == g_dragRace ? 2 : -1;
}
static void* __fastcall StAlloc(void* db, void*, void* race)
{
    printf("ALLOCCUSTOMRACE%s\n", race == g_race ? "" : race == g_dragRace ? " DRAG" : " BAD RACE");
    return g_custom;
}
static void __fastcall StFill(void* fedb, void*, void* custom, const BYTE* s)
{
    printf("FILLCUSTOMRACE laps %d dir %d opp %d skill %d heat %d traffic %d catchup %d cops %d%s\n", s[4], s[5], s[7],
           s[8], s[9], s[0xA], s[0xB], s[0xC], fedb == g_fedb && custom == g_custom ? "" : " BAD THIS");
}
static void __fastcall StSetStartup(void* db, void*, void* custom, int ctx)
{
    printf("SETSTARTUPRACE ctx %d%s\n", ctx, custom == g_custom ? "" : " BAD RACE");
}
static void __fastcall StFree(void* db, void*, void* custom) { printf("FREECUSTOMRACE\n"); }
static void __fastcall StClearStartup(void* db, void*) { printf("CLEARSTARTUPRACE\n"); }

static void PrintScreen(const char* kind)
{
    printf("SCREEN %s options:", kind);
    for (int k = 0; k < g_optCount; k++)
    {
        const char* t = Text(((DWORD*)g_opts[k])[0x2C / 4]);
        printf("%s %s", k ? " |" : "", t ? t : "(null)");
    }
    printf("\nICONS %s:", kind);
    for (int k = 0; k < g_optCount; k++) printf(" %08lX", (unsigned long)((DWORD*)g_opts[k])[0xC / 4]);
    printf("\n");
}

static void NewMenu()
{
    memset(g_menu, 0, sizeof(g_menu));
    g_menu[0x10 / 4] = (DWORD)(UINT_PTR)"MainMenu_Sub.fng";
    g_optCount = 0;
}

// the game's UIQRModeSelect::Setup (0x7AA900): Rockport's five race kinds (MSOption: +0x4C the kind)
static void __fastcall StModeSetupGame(DWORD* menu, void*)
{
    static const DWORD kinds[5][3] = {{0xE9638D3E, 0x34FA2C1, 1}, {0x2521E5EB, 0xB94FD70E, 0}, {0xAAAB31E9, 0x6F547E4C, 2},
                                      {0x3A015595, 0x4930F5FC, 3}, {0x66C9A7B6, 0xEE1EDC76, 5}};
    for (auto& k : kinds)
    {
        DWORD* o = (DWORD*)calloc(1, 0x50);
        StIconCtor(o, nullptr, k[0], k[1], 0);
        o[0] = 0x8B75B0;
        o[0x4C / 4] = k[2];
        ((void(__thiscall*)(void*, void*))0x573960)(menu, o);
    }
}

// the game's UIQRModeSelect::NotificationMessage (0x7A2F80)
static void __fastcall StModeNotifyGame(DWORD* menu, void*, DWORD msg, void* obj, DWORD p1, DWORD p2)
{
    ((void(__thiscall*)(void*, DWORD, void*, DWORD, DWORD))0x587D30)(menu, msg, obj, p1, p2);
    if (msg != 0xE1FDE1D1)
        return;
    void* fe = (void*)(UINT_PTR)Get(0x91CADC);
    if (menu[0x138 / 4] == 0xC407210)
        ((void(__thiscall*)(void*, const char*, int, unsigned, bool))0x525940)(fe, "Track_Select.fng", 0, 0, false);
    else if (menu[0x138 / 4] == 0x911AB364)
    {
        g_fedb[0x12C / 4] &= ~0x400u;
        ((void(__thiscall*)(void*, const char*, int, unsigned, bool))0x525940)(fe, "MainMenu_Sub.fng", 0, 0, false);
    }
}

// the game's UIQRMainMenu::NotificationMessage (0x7A2E20) at EXITCOMPLETE after a press
static void QrNotifyGame(DWORD msg)
{
    if (msg != 0xE1FDE1D1 || g_menu[0x138 / 4] != 0xC407210)
        return;
    void* fe = (void*)(UINT_PTR)Get(0x91CADC);
    DWORD mode = Get(0x9B9E68);
    if (mode == 0)
        ((void(__thiscall*)(void*, const char*, int, unsigned, bool))0x525940)(fe, "Quick_Race_Brief.fng", 0, 0, false);
    else if (mode == 1)
    {
        g_fedb[0x12C / 4] |= 0x400;
        ((void(__thiscall*)(void*, const char*, int, unsigned, bool))0x525940)(fe, "MainMenu_Sub.fng", 0, 0, false);
    }
}

static void BuildQr()
{
    NewMenu();
    g_screen = SCR_QR;
    DWORD* qp = (DWORD*)calloc(1, 0x4C);
    StIconCtor(qp, nullptr, 0xE6313967, 0xB5E8F82F, 0);
    qp[0] = 0x8B7588;
    ((void(__thiscall*)(void*, void*))0x573960)(g_menu, qp);
    DWORD* cr = (DWORD*)calloc(1, 0x4C);
    StIconCtor(cr, nullptr, 0x2A49B5E2, 0x25BBD4C3, 0);
    cr[0] = 0x8B7590;
    ((void(__stdcall*)(void*, void*))0x7AA810)(g_menu, cr);  // the game's call at 0x7AA81C
    PrintScreen("qr");
}

static void BuildMode()
{
    NewMenu();
    g_screen = SCR_MODE;
    g_menu[0] = 0x8B7E18;
    ((void(__stdcall*)(void*))0x7BA4D0)(g_menu);  // the ctor's Setup call at 0x7BA4D7
    ((void(__cdecl*)())0x7A2F61)();               // RefreshHeader's title call at 0x7A2F6D
    PrintScreen("modeselect");
}

static void Notify(DWORD msg)
{
    if (g_screen == SCR_QR)
    {
        StScrollerNotify(g_menu, nullptr, msg, nullptr, 0, 0);
        QrNotifyGame(msg);
    }
    else if (g_screen == SCR_MODE)
    {
        DWORD vt = g_menu[0];
        ((void(__thiscall*)(void*, DWORD, void*, DWORD, DWORD))Get(vt + 4))(g_menu, msg, nullptr, 0, 0);
    }
}

static void FeAction(const char* a)
{
    if (g_pending[0])
    {
        char p[64];
        strcpy(p, g_pending);
        g_pending[0] = 0;
        if (!strcmp(p, "MainMenu_Sub.fng"))
        {
            if (g_fedb[0x12C / 4] & 0x400)
                BuildMode();
            else
                BuildQr();
        }
        else if (!strcmp(p, "Car_Select.fng"))
        {
            g_screen = SCR_CAR;
            printf("SCREEN carselect\n");
        }
        else
        {
            g_screen = SCR_OTHER;
            printf("SCREEN %s\n", p);
        }
    }
    if (!a)
        return;
    printf("FE %s\n", a);
    if (!strcmp(a, "qr"))
        BuildQr();
    else if (!strncmp(a, "pick:", 5))
    {
        for (int k = 0; k < g_optCount; k++)
        {
            DWORD* o = (DWORD*)g_opts[k];
            const char* t = Text(o[0x2C / 4]);
            if (t && !strcmp(t, a + 5))
            {
                ((void(__thiscall*)(void*, const char*, DWORD, void*, DWORD, DWORD))Get(o[0] + 4))(o, "pkg", 0xC407210,
                                                                                                    nullptr, 0, 0);
                Notify(0xC407210);
                Notify(0xE1FDE1D1);
                return;
            }
        }
        printf("FE NO OPTION %s\n", a + 5);
    }
    else if (!strcmp(a, "back"))
    {
        if (g_screen == SCR_CAR)
            ((void(__cdecl*)())0x7C26DC)();  // the car select's Back (the call at 0x7C26ED)
        else
        {
            Notify(0x911AB364);
            Notify(0xE1FDE1D1);
        }
    }
    else if (!strcmp(a, "start"))
    {
        printf("RACE START racemode %lu modeselect %d\n", (unsigned long)g_fedb[0x18 / 4],
               (g_fedb[0x12C / 4] & 0x400) ? 1 : 0);
        g_raceStarted = true;
        g_screen = SCR_NONE;
    }
}

// the HUD's countdown and the pause menu's restart, once a frame
static bool CallPrepareLater;  // Run J: a restart's PrepareForRace (NisStep calls it)
static int g_nisA = -1, g_nisB = -1, g_noGridUntil = -1;  // nis=<a>-<b>, nogridat=<f> (below)
static void CountdownStep()
{
    if (g_frame == g_restartFrame)
    {
        g_pos[0] = -2400.0f, g_pos[1] = 113.0f, g_pos[2] = 1700.0f;
        g_routeOn = -1;
        g_cdStart = g_frame;  // the race starts over: its countdown with it
        printf("GAME RESTART: the car at the Rockport start\n");
        if (g_nisA >= 0)
            CallPrepareLater = true;  // Run J: the restart puts the racers back with PrepareForRace
    }
    int n = g_cdCount;
    if (g_cdStart >= 0 && g_frame >= g_cdStart)
    {
        int el = g_frame - g_cdStart;
        n = el < 30 ? 4 : el < 60 ? 3 : el < 90 ? 2 : el < 120 ? 1 : el < 300 ? 0 : -1;
    }
    if (n != g_cdCount)
        printf("COUNTDOWN %d\n", n);
    g_cdCount = n;
    g_countdown[5] = (DWORD)n;
}

// ---------------------------------------------------------------- the race start (Run J item 1)
//
// nis=<a>-<b>: as the game's race start (docs/ftown-race-notes.md "Run J"): on frame a EPlayRaceNIS calls
// INIS::StartLocation through the vtable slot 0x8B0D84 with the start marker (the Rockport grid, physics (-2400, 113,
// 1700)) and the NIS exists ([0x9885C8]); frames a..b the NIS sets the car at its origin + 5 m (render x) every frame;
// on frame b+1 the NIS is gone and GRacerInfo::RestoreStartPosition calls IRacer::PrepareForRace through the slot
// 0x892968 with the grid (rpi: position, speed, direction, heat, flags); a restart (restart=) calls it again.
// nogridat=<f>: the world grid (0x9B38A8) unreadable up to frame f. Printed: NIS ORIGIN, NIS MOVES THE CAR, PREPARE.
static float g_nisOrigin[3];
static int g_nisDirect;  // nisdirect: StartLocation called from somewhere else than EPlayRaceNIS
static bool g_nisHave, g_nisMoveSaid;
static DWORD g_nisObj[64], g_racerObj[1024];
static void __fastcall StNisStart(void*, void*, const float* pos, float dir)
{
    memcpy(g_nisOrigin, pos, 12);
    g_nisHave = true;
    printf("NIS ORIGIN render %.1f %.1f %.1f dir %.3f\n", pos[2], -pos[0], pos[1], dir);
}
static float __cdecl StAtan2(float a, float b)
{
    float t = atan2f(a, b) / 6.2831853f;
    return t < 0 ? t + 1.0f : t;
}
static void __fastcall StPrepare(void* self, void*, const float* rpi)
{
    g_pos[0] = rpi[0], g_pos[1] = rpi[1], g_pos[2] = rpi[2];
    printf("PREPARE render %.1f %.1f dir %.3f %.3f speed %.1f%s\n", rpi[2], -rpi[0], rpi[4], rpi[6], rpi[3],
           self == &g_racerObj[0x200] ? "" : " BAD THIS");
}
static void CallPrepare()
{
    float rpi[9] = {-2400.0f, 113.0f, 1700.0f, 0.0f, 0.6f, 0.0f, 0.8f, 1.0f, 0};
    ((void(__thiscall*)(void*, const float*))(UINT_PTR)Get(0x892968))(&g_racerObj[0x200], rpi);
}
static void NisStep()
{
    if (g_frame == g_nisA)
    {
        float grid[3] = {-2400.0f, 113.0f, 1700.0f};
        Put(0x9885C8, (DWORD)(UINT_PTR)g_nisObj);
        g_nisObj[0] = 0x8B0D78;  // NISActivity's INIS vtable: +0x0C the StartLocation slot
        if (g_nisDirect)  // another NIS (an arrest's, AnimChooseArrest.cpp:245): from elsewhere
            ((void(__thiscall*)(void*, const float*, float))(UINT_PTR)Get(0x8B0D84))(g_nisObj, grid, 0.25f);
        else  // EPlayRaceNIS's own call at 0x64148E (the return address 0x641491), through the thunk at 0x641600
            ((void(__cdecl*)(const float*, float))0x641600)(grid, 0.25f);
    }
    if (g_nisHave && g_frame >= g_nisA && g_frame <= g_nisB)
    {
        g_pos[0] = g_nisOrigin[0], g_pos[1] = g_nisOrigin[1], g_pos[2] = g_nisOrigin[2] + 5.0f;
        if (!g_nisMoveSaid)
            printf("NIS MOVES THE CAR render %.1f %.1f\n", g_pos[2], -g_pos[0]);
        g_nisMoveSaid = true;
    }
    if (g_nisA >= 0 && g_frame == g_nisB + 1)
    {
        Put(0x9885C8, 0);
        CallPrepare();
    }
    if (CallPrepareLater)
    {
        CallPrepareLater = false;
        CallPrepare();
    }
    if (g_frame <= g_noGridUntil)
        Put(0x9B38A8, 0);
    else if (g_noGridUntil >= 0 && g_frame == g_noGridUntil + 1)
        Put(0x9B38A8, (DWORD)(UINT_PTR)&g_grid);
}

// ---------------------------------------------------------------- vehicles (docs/ftown-race-notes.md R8, R9)
//
// The ISimable factory list [0x92C66C] (a node of another kind, then PVehicle's), PVehicle::Construct at 0x689820 (the
// game's first 13 bytes, then StConstruct), the vehicle list at 0x92CD18 (20 entries; the player's car is entry 0), the
// IVehicle and ISimable vtables' slots, Kill deferred to the end of the frame (the object then out of the list but its
// bytes kept, as freed memory: a later call through it shows as CALL ON DEAD VEHICLE). A car "loads" for 10 frames. Args: trafficfull (no room in the list),
// racingmem=<n> (at most n racer-class cars fit the car memory), evict=<frame> (the game deletes our second car).
struct FakeVeh
{
    BYTE* obj;  // 0x1AC bytes: +0x2C ISimable (vtable 0x8AA940, +4 its interface list), +0xAC IVehicle (0x8AA828)
    char name[32];
    DWORD key;
    int loading, active, killed, dead;
    float pos[3];
    DWORD input[16];  // its IInput (PInput's vtable 0x8AB5C8; the controls at +8: gas +0x1C, brake +0x20, handbrake +0x24)
    int creepLogged;
};
static FakeVeh g_veh[64];
static DWORD g_vlist[64][2];
static int g_gridA = -1, g_gridB = -1;  // gridhold=<a>-<b>
static int g_creep, g_gasAtFrame = -1;  // creep: a car not braked rolls; gasat=<f>: car 0 given gas
static int g_vehCount, g_trafficFull, g_racingMem = 99, g_evictFrame = -1, g_vehRefused;
static char g_refuseName[32];  // refuse=<name>: the game refuses that model (no car memory for it)
static DWORD g_playerVeh[64];
static const char* const kVehNames[] = {"traftaxi", "traf4dseda", "traf4dsedb", "trafficcoup", "trafstwag",
                                        "trafminivan", "trafpickupa", "trafha", "trafcourt", "trafvanb", "trafnews",
                                        "trafpizza", "trafgarb", "trafcemtr", "thar", "raptor", "challenger71",
                                        "chiron", "flipcar", "longnosecab"};
static bool IsRacer(const char* n)
{
    for (const char* r : {"thar", "raptor", "challenger71", "chiron", "flipcar", "longnosecab"})
        if (!strcmp(n, r))
            return true;
    return false;
}

static void* VehFind(DWORD* list, DWORD handle, bool* isVeh)
{
    *isVeh = list >= g_vlist[0] && list < g_vlist[64];
    if (!*isVeh)
        return nullptr;
    BYTE* obj = g_veh[(list - g_vlist[0]) / 2].obj;
    if (handle == 0x403F90 && obj)  // IInput::_IHandle
        return g_veh[(list - g_vlist[0]) / 2].input;
    return handle == 0x4040E0 && obj ? obj + 0xAC : nullptr;
}

static DWORD StHashOf(const char* s)
{
    DWORD h = 0xABCDEF00u;
    for (; s && *s; s++) h = (h * 33u) ^ (BYTE)*s;
    return h;
}
static DWORD __cdecl StHash(const char* s) { return s && *s ? StHashOf(s) : 0; }

static DWORD* VList() { return (DWORD*)0x92CD18; }  // +4 begin, +8 capacity, +0xC size
static int VSize() { return (int)VList()[3]; }

static FakeVeh* VehOfSim(void* sim)
{
    for (int k = 0; k < g_vehCount; k++)
        if (g_veh[k].obj + 0x2C == (BYTE*)sim)
            return &g_veh[k];
    return nullptr;
}
static FakeVeh* VehOfIVeh(void* iv)
{
    for (int k = 0; k < g_vehCount; k++)
        if (g_veh[k].obj + 0xAC == (BYTE*)iv)
            return &g_veh[k];
    return nullptr;
}
static FakeVeh* Live(FakeVeh* v, const char* what)
{
    if (!v || v->dead)
    {
        printf("CALL ON DEAD VEHICLE (%s)\n", what);
        return nullptr;
    }
    return v;
}

static void ListRemove(BYTE* iv)
{
    DWORD* l = VList();
    DWORD* b = (DWORD*)(UINT_PTR)l[1];
    for (DWORD i = 0; i < l[3]; i++)
        if (b[i] == (DWORD)(UINT_PTR)iv)
        {
            memmove(b + i, b + i + 1, (l[3] - i - 1) * 4);
            l[3]--;
            return;
        }
}

static void Destroy(FakeVeh* v, const char* why)
{
    ListRemove(v->obj + 0xAC);  // the memory left as it was (freed memory keeps its bytes until reused): a call
    // through a deleted car still finds PVehicle's vtables, and the stand-in reports it
    v->dead = 1;
    printf("DESTROYED %d %s (%s)\n", (int)(v - g_veh), v->name, why);
}

static bool __fastcall StOnGround(BYTE* iv, void*, const float* p, const float* d)
{
    FakeVeh* v = Live(VehOfIVeh(iv), "SetVehicleOnGround");
    if (!v)
        return false;
    float q[3] = {p[0], p[1], p[2]};
    bool ok = FaceAt(q);
    if (ok)
        v->pos[0] = p[0], v->pos[1] = 100.6f, v->pos[2] = p[2];
    float dx = p[2] - g_pos[2], dy = -p[0] + g_pos[0], dist = sqrtf(dx * dx + dy * dy);
    float fx = g_orient[10], fy = -g_orient[8], dot = dist > 0 ? (fx * dx + fy * dy) / dist : 0;
    printf("ONGROUND %d %s render %.1f %.1f dir %.2f %.2f -> %s (%.0f m from the car, dot %.2f)%s\n", (int)(v - g_veh),
           v->name, p[2], -p[0], d[2], -d[0], ok ? "yes" : "no", dist, dot,
           (v->loading < 10 && g_teleportFrame != g_frame && dist < 160.0f && dot > 0.25f) ? " INVIEW" : "");
    return ok;
}
static void __fastcall StKill(BYTE* sim, void*)
{
    FakeVeh* v = VehOfSim(sim);
    if (!v || v->dead)
    {
        printf("CALL ON DEAD VEHICLE (Kill)\n");
        return;
    }
    if (v->killed)
        printf("DOUBLE KILL %d\n", (int)(v - g_veh));
    v->killed = 1;
    printf("KILL %d %s active %d\n", (int)(v - g_veh), v->name, v->active);
}
static const float* __fastcall StVehPos(BYTE* sim, void*)
{
    FakeVeh* v = Live(VehOfSim(sim), "GetPosition");
    return v ? v->pos : nullptr;
}
static DWORD __fastcall StVehKey(BYTE* iv, void*) { FakeVeh* v = Live(VehOfIVeh(iv), "key"); return v ? v->key : 0; }
static int __fastcall StVehDriver(BYTE* iv, void*) { return Live(VehOfIVeh(iv), "driver") ? 4 : -1; }
static bool __fastcall StVehLoading(BYTE* iv, void*) { FakeVeh* v = Live(VehOfIVeh(iv), "IsLoading"); return v && v->loading > 0; }
static bool __fastcall StVehIsActive(BYTE* iv, void*) { FakeVeh* v = Live(VehOfIVeh(iv), "IsActive"); return v && v->active; }
static void __fastcall StVehActivate(BYTE* iv, void*)
{
    FakeVeh* v = Live(VehOfIVeh(iv), "Activate");
    if (v && !v->active)
        printf("ACTIVATE %d\n", (int)(v - g_veh));
    if (v)
        v->active = 1;
}
static void __fastcall StVehDeactivate(BYTE* iv, void*)
{
    FakeVeh* v = Live(VehOfIVeh(iv), "Deactivate");
    if (v && v->active)
        printf("DEACTIVATE %d\n", (int)(v - g_veh));
    if (v)
        v->active = 0;
}

// PVehicle::Construct(Sim::Param) by value: {type name, 0xA6B47FAC, VehicleParams*, -}
static void* __cdecl StConstruct(DWORD type, DWORD tag, BYTE* vp, DWORD)
{
    if (type != StHashOf("VehicleParams") || tag != 0xA6B47FACu || !vp)
    {
        printf("CREATE BAD PARAM type %08lX tag %08lX\n", (unsigned long)type, (unsigned long)tag);
        return nullptr;
    }
    DWORD driver = *(DWORD*)(vp + 0x10), key = *(DWORD*)(vp + 0x14), flags = *(DWORD*)(vp + 0x2C);
    const float* dir = *(const float**)(vp + 0x18);
    const float* pos = *(const float**)(vp + 0x1C);
    DWORD custom = *(DWORD*)(vp + 0x20), cache = *(DWORD*)(vp + 0x24), match = *(DWORD*)(vp + 0x28);
    const char* name = nullptr;
    for (const char* n : kVehNames)
        if (StHashOf(n) == key)
            name = n;
    printf("CREATE %s driver %lu flags %lu cache %lu custom %lu match %lu render %.1f %.1f %.1f",
           name ? name : "unknown", (unsigned long)driver, (unsigned long)flags, (unsigned long)cache,
           (unsigned long)custom, (unsigned long)match, pos[2], -pos[0], pos[1]);
    int racers = 0;
    for (int k = 0; k < g_vehCount; k++)
        racers += !g_veh[k].dead && IsRacer(g_veh[k].name);
    if (!name || g_vehCount >= 64)
    {
        printf(" -> null (unknown key)\n");
        return nullptr;
    }
    if (g_trafficFull || VSize() + 1 > 20 || (IsRacer(name) && racers >= g_racingMem) || !strcmp(name, g_refuseName))
    {
        printf(" -> null (no room: list %d, racers %d)\n", VSize(), racers);
        g_vehRefused++;
        return nullptr;
    }
    FakeVeh& v = g_veh[g_vehCount];
    v.obj = (BYTE*)calloc(1, 0x1AC);
    strcpy(v.name, name);
    v.key = key;
    v.loading = 10;
    v.active = 1;
    memcpy(v.pos, pos, 12);
    *(DWORD*)(v.obj + 0x2C) = 0x8AA940;
    *(DWORD*)(v.obj + 0x30) = (DWORD)(UINT_PTR)g_vlist[g_vehCount];
    g_vlist[g_vehCount][1] = (DWORD)(UINT_PTR)g_vlist[g_vehCount];  // Find's ecx: [list + 4] (as the player's)
    *(DWORD*)(v.obj + 0xAC) = 0x8AA828;
    memset(v.input, 0, sizeof(v.input));
    v.input[0] = 0x8AB5C8;
    v.creepLogged = 0;
    DWORD* l = VList();
    ((DWORD*)(UINT_PTR)l[1])[l[3]++] = (DWORD)(UINT_PTR)(v.obj + 0xAC);
    g_vehCount++;
    printf(" -> %d\n", g_vehCount - 1);
    if (flags & 2)
        StOnGround(v.obj + 0xAC, nullptr, pos, dir);
    return v.obj + 0x2C;
}

// end of a frame: the collector deletes killed cars; loading counts down; evict=<frame> deletes our second car
static void VehiclesEndFrame()
{
    for (int k = 0; k < g_vehCount; k++)
    {
        FakeVeh& v = g_veh[k];
        if (v.dead)
            continue;
        if (v.killed)
            Destroy(&v, "killed");
        else if (v.loading > 0)
            v.loading--;
        // creep: a car nothing holds rolls away (0.1 m a frame) while it is active; gasat=<f>: car 0's gas set
        float* ctl = (float*)v.input;
        if (g_frame == g_gasAtFrame && k == 0)
            ctl[0x1C / 4] = 0.5f;
        if (g_creep && v.active && !v.dead && (ctl[0x1C / 4] > 0 || (ctl[0x20 / 4] < 0.5f && ctl[0x24 / 4] < 0.5f)))
        {
            v.pos[0] += 0.1f;
            if (!v.creepLogged)
                printf("PARKED CAR MOVING %d %s\n", k, v.name);
            v.creepLogged = 1;
        }
    }
    if (g_frame == g_evictFrame && g_vehCount > 1 && !g_veh[1].dead)
    {
        printf("EVICT: the game deletes car 1 to make room\n");
        Destroy(&g_veh[1], "the game made room");
    }
}

static void VehiclesSetup()
{
    for (DWORD a : {0x689000u, 0x687000u, 0x688000u, 0x669000u, 0x5CC000u, 0x454000u, 0x887000u, 0x893000u, 0x8F8000u,
                    0x92C000u})
        Reserve(a, 0x1000);
    memset((void*)0x8F8000, 0, 0x1000);
    memset((void*)0x92C000, 0, 0x1000);
    // the factory list: another kind first, then PVehicle's
    static DWORD nodes[2][3];
    nodes[0][0] = StHashOf("Smackable"), nodes[0][1] = 0x12345, nodes[0][2] = (DWORD)(UINT_PTR)nodes[1];
    nodes[1][0] = StHashOf("PVehicle"), nodes[1][1] = 0x689820, nodes[1][2] = 0;
    Put(0x92C66C, (DWORD)(UINT_PTR)nodes[0]);
    // the vehicle list: the player's car first
    Put(0x92CD1C, 0x92CD28), Put(0x92CD20, 20), Put(0x92CD24, 1), Put(0x92CD28, (DWORD)(UINT_PTR)g_playerVeh);
    // PVehicle::Construct: mov eax, fs:[0]; push -1; push 0x87BD7C; then add esp, 8; jmp StConstruct
    At(0x689820); B({0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x6A, 0xFF, 0x68, 0x7C, 0xBD, 0x87, 0x00, 0x83, 0xC4, 0x08});
    Jmp((DWORD)(UINT_PTR)&StConstruct);
    // its parameter check, field reads, the flag 2 ground call and the returned ISimable (only checked)
    At(0x689853); B({0x3D, 0xAC, 0x7F, 0xB4, 0xA6});
    At(0x689877); B({0x8B, 0x40, 0x08, 0x8B, 0x50, 0x18, 0x8B, 0x48, 0x14, 0x8B, 0x78, 0x10, 0x8B, 0x68, 0x28, 0x8B, 0x58,
                     0x2C, 0x8B, 0x70, 0x20});
    At(0x689BFA); B({0xF6, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00, 0x02});
    At(0x689C16); B({0x50, 0x8B, 0x44, 0x24, 0x74, 0x8D, 0x8E, 0xAC, 0x00, 0x00, 0x00, 0x50, 0xFF, 0x52, 0x68, 0x85, 0xF6,
                     0x74, 0x05, 0x83, 0xC6, 0x2C});
    At(0x6893AD); B({0xA1, 0x24, 0xCD, 0x92, 0x00, 0x3B, 0x05, 0x20, 0xCD, 0x92, 0x00});
    At(0x6893D5); B({0xA1, 0x1C, 0xCD, 0x92, 0x00});
    At(0x687817); B({0x83, 0xF8, 0x14, 0x76, 0x07, 0x8D});
    At(0x687838); B({0x3B, 0xEB, 0x0F, 0x84, 0xE2, 0x04, 0x00, 0x00});
    // stringhash32 and Attrib::StringToKey: the game's 8 bytes (je to "xor eax, eax; ret"), then jmp StHash
    At(0x5CC240); B({0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x74, 0x23}); Jmp((DWORD)(UINT_PTR)&StHash);
    At(0x5CC26B); B({0x31, 0xC0, 0xC3});
    At(0x454640); B({0x8B, 0x4C, 0x24, 0x04, 0x85, 0xC9, 0x74, 0x23}); Jmp((DWORD)(UINT_PTR)&StHash);
    At(0x45466B); B({0x31, 0xC0, 0xC3});
    // Kill: push ecx; push esi; mov esi, ecx; push edi; lea eax, [esi-0x2C]; then pop edi; pop esi; pop ecx; jmp
    At(0x6851D0); B({0x51, 0x56, 0x8B, 0xF1, 0x57, 0x8D, 0x46, 0xD4, 0x5F, 0x5E, 0x59}); Jmp((DWORD)(UINT_PTR)&StKill);
    // SetVehicleOnGround after its first 8 bytes (push -1; mov eax, fs:[0]; also WorldProbe's trampoline's way back)
    At(0x685818); B({0x83, 0xC4, 0x04}); Jmp((DWORD)(UINT_PTR)&StOnGround);
    At(0x688010); B({0x8B, 0x41, 0x4C, 0x85, 0xC0}); Jmp((DWORD)(UINT_PTR)&StVehPos);
    At(0x6880A0); Jmp((DWORD)(UINT_PTR)&StVehKey);
    At(0x6880B0); Jmp((DWORD)(UINT_PTR)&StVehDriver);
    At(0x6691D0); Jmp((DWORD)(UINT_PTR)&StVehLoading);
    At(0x6693A0); Jmp((DWORD)(UINT_PTR)&StVehActivate);
    At(0x6693C0); Jmp((DWORD)(UINT_PTR)&StVehDeactivate);
    At(0x688200); Jmp((DWORD)(UINT_PTR)&StVehIsActive);
    // the AI table's start (DRIVER_NONE -> AIVehicleEmpty) and its data
    At(0x887610); B({0xA1, 0xBC, 0xDD, 0x91, 0x00, 0x68, 0x2C, 0x30, 0x89, 0x00, 0xA3, 0x94, 0x88, 0x8F, 0x00});
    strcpy((char*)0x89302C, "AIVehicleEmpty");
    Put(0x8F8890, 4);
    Put(0x8AA828 + 0x50, 0x6880A0), Put(0x8AA828 + 0x58, 0x6880B0), Put(0x8AA828 + 0x5C, 0x6691D0);
    Put(0x8AA828 + 0x68, 0x685810);
    Put(0x8AA828 + 0x80, 0x6693A0), Put(0x8AA828 + 0x84, 0x6693C0), Put(0x8AA828 + 0x88, 0x688200);
    Put(0x8AA940 + 0x08, 0x6851D0), Put(0x8AA940 + 0x60, 0x688010);
    // PInput's IInput (run as is): GetControls, SetControlGas, SetControlBrake, SetControlHandBrake; and the game's
    // own Find of a vehicle's IInput (RBTractor::SetHitch, only checked)
    At(0x69CBB0); B({0x8D, 0x41, 0x08, 0xC3});
    At(0x69CB90); B({0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x1C, 0xC2, 0x04, 0x00});
    At(0x69CBA0); B({0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x20, 0xC2, 0x04, 0x00});
    At(0x69CBC0); B({0x8B, 0x44, 0x24, 0x04, 0x89, 0x41, 0x24, 0xC2, 0x04, 0x00});
    At(0x69B24B); B({0x8B, 0x48, 0x04, 0x68, 0x90, 0x3F, 0x40, 0x00});
    Put(0x8AB5C8 + 0x08, 0x69CBB0), Put(0x8AB5C8 + 0x18, 0x69CB90), Put(0x8AB5C8 + 0x1C, 0x69CBA0);
    Put(0x8AB5C8 + 0x24, 0x69CBC0);
}

static void ParseList(const char* s, int* out, int* n)
{
    *n = 0;
    while (*s && *n < 16)
    {
        out[(*n)++] = atoi(s);
        const char* c = strchr(s, ',');
        if (!c)
            break;
        s = c + 1;
    }
}

// ---------------------------------------------------------------- moving traffic (FTownRoadNet.h)
//
// The game's road network as WRoadNetwork::Init leaves it (3 profiles, 4 nodes, 3 segments, 1 road of "Rockport"),
// AITrafficManager::CheckRace's call site (0x438049) and CheckRace (the game's rule: a segment marked InRace; true with
// no race), ComputeSpeed's posted-speed site (0x41187D) and GetSegmentNumTrafficLanes, bMalloc and bFree.
// spawncheck=<f>:<segment>, speedcheck=<f>:<segment> run the game's call sites with a nav / an action of ours;
// resetrace=<f> clears InRace and RaceRouteForward on every segment as ResetRaceSegments does (a restart).
static BYTE g_rkProf[3][64], g_rkNode[4][32], g_rkSeg[3][22], g_rkRoad[1][8];
static BYTE g_rkSnap[sizeof(g_rkProf) + sizeof(g_rkNode) + sizeof(g_rkSeg) + sizeof(g_rkRoad)];
static int g_spawnF[16], g_spawnSeg[16], g_spawnN, g_speedF[16], g_speedSeg[16], g_speedN, g_resetRaceF = -1;
static int g_bmallocs, g_bfrees;
static BYTE g_action[0x100];
static void* __cdecl StBMalloc(int size, int flags)
{
    g_bmallocs++;
    printf("BMALLOC %d flags %d\n", size, flags);
    return calloc(1, size);
}
static void __cdecl StBFree(void* p)
{
    g_bfrees++;
    printf("BFREE%s\n", p == (void*)g_grid.nodes ? " the grid's live array" : "");
    free(p);
}
static bool __fastcall StCheckRace(void* mgr, void*, const BYTE* nav)
{
    short s = *(const short*)(nav + 0x8E);
    const BYTE* seg = (const BYTE*)(UINT_PTR)Get(0x9B38C0) + 22 * s;
    return (*(const WORD*)(seg + 10) & 0x8000) != 0;
}
static int CountTraffic(const BYTE* prof)
{
    int n = 0;
    for (int z = 0; z < prof[0]; z++) n += (*(const DWORD*)(prof + 4 + 4 * z) & 0xF) == 1;
    return n;
}
static int __fastcall StLanes(const BYTE* segInEcx, void*, const BYTE* seg)
{
    const BYTE* nodes = (const BYTE*)(UINT_PTR)Get(0x9B38BC);
    const BYTE* profs = (const BYTE*)(UINT_PTR)Get(0x9B38B8);
    int best = 0;
    for (int e = 0; e < 2; e++)
    {
        WORD n = *(const WORD*)(seg + 2 * e);
        short p = *(const short*)(nodes + 32 * n + 14);
        int c = CountTraffic(profs + 64 * p);
        best = c > best ? c : best;
    }
    return best;
}
extern "C" int __cdecl StSpawnCheck(void* nav);
extern "C" float __cdecl StSpeedCheck(const void* seg, const void* action);
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _StSpawnCheck\n"
        "_StSpawnCheck:\n"
        "  push ebx\n"
        "  push edi\n"
        "  mov edi, [esp + 12]\n"
        "  mov ebx, 0x00C0FFEE\n"
        "  mov eax, 0x438049\n"
        "  call eax\n"
        "  movzx eax, al\n"
        "  pop edi\n"
        "  pop ebx\n"
        "  ret\n"
        ".globl _StSpeedCheck\n"
        "_StSpeedCheck:\n"
        "  push esi\n"
        "  mov esi, [esp + 12]\n"
        "  mov eax, [esp + 8]\n"
        "  call _StSpeedGo\n"  // our return address below the segment, as the game's frame has its own
        "  pop esi\n"
        "  ret\n"
        "_StSpeedGo:\n"
        "  push eax\n"
        "  mov eax, 0x41187D\n"
        "  jmp eax\n"
        ".att_syntax prefix\n");

static void PutBytes(DWORD at, std::initializer_list<int> b)
{
    At(at);
    B(b);
}

static void Snapshot(BYTE* out)
{
    memcpy(out, g_rkProf, sizeof(g_rkProf));
    out += sizeof(g_rkProf);
    memcpy(out, g_rkNode, sizeof(g_rkNode));
    out += sizeof(g_rkNode);
    memcpy(out, g_rkSeg, sizeof(g_rkSeg));
    out += sizeof(g_rkSeg);
    memcpy(out, g_rkRoad, sizeof(g_rkRoad));
}

static void NetSetup()
{
    // the game's code: the Init stores and two reads (only checked), the call sites, the functions
    PutBytes(0x789A4D, {0xA3, 0x84, 0x38, 0x9B, 0x00});
    PutBytes(0x789A56, {0x89, 0x3D, 0x7C, 0x38, 0x9B, 0x00});
    PutBytes(0x789A60, {0x89, 0x15, 0x74, 0x38, 0x9B, 0x00});
    PutBytes(0x789A7A, {0x89, 0x0D, 0x80, 0x38, 0x9B, 0x00});
    PutBytes(0x789AFD, {0x89, 0x3D, 0xB8, 0x38, 0x9B, 0x00});
    PutBytes(0x789B37, {0x89, 0x3D, 0xBC, 0x38, 0x9B, 0x00});
    PutBytes(0x789B71, {0x89, 0x3D, 0xC0, 0x38, 0x9B, 0x00});
    PutBytes(0x789BAB, {0x89, 0x3D, 0xC8, 0x38, 0x9B, 0x00});
    PutBytes(0x404F45, {0x8B, 0x44, 0x24, 0x04, 0x0F, 0xBF, 0x80, 0x8E, 0x00, 0x00, 0x00, 0x8B, 0x0D, 0xC0, 0x38, 0x9B,
                        0x00, 0x6B, 0xC0, 0x16});
    PutBytes(0x411853, {0x8B, 0x15, 0xC0, 0x38, 0x9B, 0x00});
    // CheckRace: the game's first 9 bytes (GRaceStatus; je 0x404F70 with none), then ours; 0x404F70: mov al, 1; ret 4
    At(0x404F20); B({0xA1, 0x00, 0xE0, 0x91, 0x00, 0x85, 0xC0, 0x74, 0x47}); Jmp((DWORD)(UINT_PTR)&StCheckRace);
    At(0x404F70); B({0xB0, 0x01, 0xC2, 0x04, 0x00});
    At(0x438049); B({0x57, 0x8B, 0xCB, 0xE8}); Rel(0x404F20); B({0xC3});
    // the posted speed: the game's 18 bytes, then ret (the stand-in's helper jumped in with its return address below)
    At(0x41187D); B({0xE8}); Rel(0x76DD30);
    B({0x83, 0xF8, 0x04, 0x7C, 0x05, 0xD9, 0x46, 0x54, 0xEB, 0x03, 0xD9, 0x46, 0x50, 0xC3});
    // GetSegmentNumTrafficLanes: mov ecx, [esp+4]; sub esp, 8; push esi; then pop esi; add esp, 8; jmp StLanes
    At(0x76DD30); B({0x8B, 0x4C, 0x24, 0x04, 0x83, 0xEC, 0x08, 0x56, 0x5E, 0x83, 0xC4, 0x08});
    Jmp((DWORD)(UINT_PTR)&StLanes);
    // bMalloc: mov eax, [esp+8]; mov ecx, [esp+4]; jmp; bFree: mov eax, [esp+4]; sub esp, 0x20; add esp, 0x20; jmp
    At(0x465A70); B({0x8B, 0x44, 0x24, 0x08, 0x8B, 0x4C, 0x24, 0x04}); Jmp((DWORD)(UINT_PTR)&StBMalloc);
    At(0x4655F0); B({0x8B, 0x44, 0x24, 0x04, 0x83, 0xEC, 0x20, 0x83, 0xC4, 0x20}); Jmp((DWORD)(UINT_PTR)&StBFree);
    At(0x76438D); B({0xE8}); Rel(0x465A70);
    At(0x781762); B({0x50, 0xE8}); Rel(0x4655F0);
    // "Rockport": profiles 0, 1 one traffic lane each way, profile 2 four lanes (a highway); nodes in a row at physics
    // x -2000 (far from F-Town); segments 0-1, 1-2, 2-3 of road 0
    for (int p = 0; p < 3; p++)
    {
        int lanes = p == 2 ? 4 : 2;
        g_rkProf[p][0] = (BYTE)lanes;
        g_rkProf[p][1] = (BYTE)(lanes / 2);
        for (int z = 0; z < 15; z++) *(DWORD*)(g_rkProf[p] + 4 + 4 * z) = z < lanes ? 1u : 0xAAAAAAAAu;
    }
    for (int n = 0; n < 4; n++)
    {
        float pos[3] = {-2000.0f, 113.0f, 1000.0f + 30.0f * n};
        memcpy(g_rkNode[n], pos, 12);
        *(short*)(g_rkNode[n] + 12) = (short)n;
        *(short*)(g_rkNode[n] + 14) = (short)(n == 3 ? 2 : 0);
        // each node's segments, as the game's records list them (the connection's join checks them): 0; 0 1; 1 2; 2
        BYTE cnt = 0;
        for (int s = 0; s < 3; s++)
            if (s == n - 1 || s == n)
                *(WORD*)(g_rkNode[n] + 18 + 2 * cnt++) = (WORD)s;
        g_rkNode[n][16] = cnt;
        for (int k = cnt; k < 7; k++) *(WORD*)(g_rkNode[n] + 18 + 2 * k) = 0xAAAA;
    }
    for (int s = 0; s < 3; s++)
    {
        *(WORD*)(g_rkSeg[s] + 0) = (WORD)s;
        *(WORD*)(g_rkSeg[s] + 2) = (WORD)(s + 1);
        *(short*)(g_rkSeg[s] + 8) = (short)s;
    }
    Snapshot(g_rkSnap);
    Put(0x9B38B8, (DWORD)(UINT_PTR)g_rkProf);
    Put(0x9B38BC, (DWORD)(UINT_PTR)g_rkNode);
    Put(0x9B38C0, (DWORD)(UINT_PTR)g_rkSeg);
    Put(0x9B38C8, (DWORD)(UINT_PTR)g_rkRoad);
    Put(0x9B3884, 3);
    Put(0x9B387C, 4);
    Put(0x9B3874, 3);
    Put(0x9B3880, 1);
    Put(0x9B38B4, 0x00BEEF00);  // fgRoadNetwork
    float street = 35.0f * 0.44704f, highway = 55.0f * 0.44704f;
    memcpy(g_action + 0x50, &street, 4);
    memcpy(g_action + 0x54, &highway, 4);
}

static void NetFrame()
{
    for (int k = 0; k < g_spawnN; k++)
        if (g_spawnF[k] == g_frame)
        {
            static BYTE nav[0x2F0];
            *(short*)(nav + 0x8E) = (short)g_spawnSeg[k];
            printf("SPAWNCHECK f=%d seg %d -> %d\n", g_frame, g_spawnSeg[k], StSpawnCheck(nav));
        }
    for (int k = 0; k < g_speedN; k++)
        if (g_speedF[k] == g_frame)
        {
            const BYTE* seg = (const BYTE*)(UINT_PTR)Get(0x9B38C0) + 22 * g_speedSeg[k];
            printf("SPEEDCHECK f=%d seg %d -> %.2f\n", g_frame, g_speedSeg[k], StSpeedCheck(seg, g_action));
        }
    if (g_frame == g_resetRaceF)
    {
        BYTE* segs = (BYTE*)(UINT_PTR)Get(0x9B38C0);
        DWORD n = Get(0x9B3874);
        for (DWORD s = 0; s < n; s++) *(WORD*)(segs + 22 * s + 10) &= (WORD)~0x8004;
        printf("RESETRACESEGMENTS %lu segments\n", (unsigned long)n);
    }
}

static void NetReport()
{
    bool game = Get(0x9B38C0) == (DWORD)(UINT_PTR)g_rkSeg && Get(0x9B38B8) == (DWORD)(UINT_PTR)g_rkProf &&
                Get(0x9B38BC) == (DWORD)(UINT_PTR)g_rkNode && Get(0x9B38C8) == (DWORD)(UINT_PTR)g_rkRoad;
    printf("NET counts %lu %lu %lu %lu pointers %s\n", (unsigned long)Get(0x9B3884), (unsigned long)Get(0x9B387C),
           (unsigned long)Get(0x9B3874), (unsigned long)Get(0x9B3880), game ? "game" : "ours");
    BYTE now[sizeof(g_rkSnap)];
    Snapshot(now);
    printf("ROCKPORT records %s\n", memcmp(now, g_rkSnap, sizeof(now)) ? "CHANGED" : "same");
    printf("GRIDNOW cols %lu min x %.1f\n", (unsigned long)g_grid.cols, g_grid.min[0]);
    printf("BMALLOCS %d BFREES %d\n", g_bmallocs, g_bfrees);
    if (!game && Get(0x9B3884) > 3)  // the first profile after Rockport's: its lanes' offsets (DriveOn)
    {
        const BYTE* p = (const BYTE*)(UINT_PTR)Get(0x9B38B8) + 64 * 3;
        printf("NETPROF zones %d middle %d offsets", p[0], p[1]);
        for (int z = 0; z < p[0]; z++) printf(" %.2f", (float)((int)*(const DWORD*)(p + 4 + 4 * z) >> 18) * 100.0f / 8191.0f);
        printf("\n");
    }
}

// ---------------------------------------------------------------- the connection (FTownConnect.h)
//
// link: the VisibleSectionManager's two lists (0x9A3B50 boundaries, 0x9A3B60 drivable sections) with "Rockport"'s zones
// round the test junction (render 1045, 2000): 309 everything south of y 1900, 703 (the junction's, its list the data's
// source list), 726 and 723 north of it (lists of their own two), as the game's records (0xA4 bytes, bTNode next/prev);
// FindDrivableSection (0x72CA00) walking that list; the streamer after the plugin's hook each frame: the zone at the
// car (CurrentZone at 0x9AA9D0 + 0xDE), and DetermineStreamingSections' read of the zone's record by number (none:
// STREAMER NULL READ, the game's crash); "Rockport"'s pack 703 (WCollisionPack: one instance, five barriers on the wall
// line y 2100 x 995..1095, two elsewhere) in mCollisionPackList; GRaceStatus roaming (racing: play mode 1).
// restream703=<f>: the streamer drops pack 703 and loads it again in a new object (the old one's bytes kept to see
// that nothing writes it); zonehold=<a>-<b>: the streamer's zone does not follow the car; linkbadlist: 703's list one
// section longer than the data's; glide=<a>-<b>:<x0>,<y0>:<x1>,<y1>: the car moves in a straight line those frames;
// nodecheck=<f>: nodes 1 and 2 of the current network; cellcheck=<f>:<x>,<y>: the road tags of the cell there.
static int g_racing, g_restream703 = -1, g_linkBadList, g_zoneHoldA = -1, g_zoneHoldB = -1, g_nodeCheck = -1;
static int g_roamingAt = -1;
static int g_cellCheck[4] = {-1, -1, -1, -1}, g_cellN, g_racingAt = -1, g_segCheckF = -1, g_segCheck[4], g_segN;
static float g_cellX[4], g_cellY[4];
struct Glide
{
    int a, b;
    float x0, y0, x1, y1;
};
static Glide g_glides[8];
static int g_glideCount;
static BYTE g_lnBnd[4][0xA4], g_lnRec[4][0xA4];
static BYTE* g_p703;
static BYTE* g_p703Old;
static const int kP703Size = 0x20 + 0x40 + 0x10 + 2 * 0x10 + 8 * 8 + 7 * 0x20 + 0x20;
static BYTE g_p703OldCopy[kP703Size - 0x20];
static int g_lnZone = -1;

static void LkLinkTail(DWORD list, BYTE* node)
{
    DWORD last = Get(list + 4);
    *(DWORD*)node = list;
    *(DWORD*)(node + 4) = last;
    *(DWORD*)(UINT_PTR)last = (DWORD)(UINT_PTR)node;
    Put(list + 4, (DWORD)(UINT_PTR)node);
}

static void LkZone(int k, short number, float x0, float y0, float x1, float y1, std::initializer_list<short> vis)
{
    BYTE* b = g_lnBnd[k];
    BYTE* r = g_lnRec[k];
    *(short*)(b + 8) = number;
    b[10] = 4;
    float pts[4][2] = {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}};
    float box[6] = {x0, y0, x1, y1, (x0 + x1) / 2, (y0 + y1) / 2};
    memcpy(b + 0x0C, box, sizeof(box));
    memcpy(b + 0x24, pts, sizeof(pts));
    *(DWORD*)(r + 8) = (DWORD)(UINT_PTR)b;
    *(short*)(r + 0x0C) = number;
    r[0x0E] = (BYTE)vis.size();
    r[0x0F] = (BYTE)(vis.size() + 6);
    *(short*)(r + 0x10) = (short)vis.size();
    int i = 0;
    for (short v : vis) *(short*)(r + 0x12 + 2 * i++) = v;
    LkLinkTail(0x9A3B50, b);
    LkLinkTail(0x9A3B60, r);
}

static bool LkInside(const BYTE* b, float x, float y)
{
    int n = (signed char)b[10];
    const float* p = (const float*)(b + 0x24);
    bool in = false;
    for (int i = 0, j = n - 1; i < n; j = i++)
        if ((p[2 * i + 1] > y) != (p[2 * j + 1] > y) &&
            x < (p[2 * j] - p[2 * i]) * (y - p[2 * i + 1]) / (p[2 * j + 1] - p[2 * i + 1]) + p[2 * i])
            in = !in;
    return in;
}

static void* LkFind(float x, float y)
{
    DWORD n = Get(0x9A3B60);
    for (int guard = 0; n != 0x9A3B60 && guard < 100; guard++)
    {
        const BYTE* b = (const BYTE*)(UINT_PTR)*(DWORD*)(UINT_PTR)(n + 8);
        if (LkInside(b, x, y))
        {
            // as the game's FindDrivableSection: the found record to the list's head (Remove, AddHead)
            DWORD next = *(DWORD*)(UINT_PTR)n, prev = *(DWORD*)(UINT_PTR)(n + 4);
            *(DWORD*)(UINT_PTR)prev = next;
            *(DWORD*)(UINT_PTR)(next + 4) = prev;
            DWORD first = Get(0x9A3B60);
            *(DWORD*)(UINT_PTR)n = first;
            *(DWORD*)(UINT_PTR)(n + 4) = 0x9A3B60;
            *(DWORD*)(UINT_PTR)(first + 4) = n;
            Put(0x9A3B60, n);
            return (void*)(UINT_PTR)n;
        }
        n = *(DWORD*)(UINT_PTR)n;
    }
    return nullptr;
}

static BYTE* LkMakePack()
{
    // one instance turned 30 degrees about up and moved (the review: the transform's direction tested; world w_i =
    // (l - t) . r_i, so l = w_0 r0 + w_1 (0, 1, 0) + w_2 r2 + t), its article: 0 strips, 7 barriers; barriers in
    // physics (x = -render y, y up, z = render x): five on the wall line render y 2100 from x 995 to 1095, two at
    // y 1900; and two strips of road faces (the ramp's: FTownConnect.h's face region): strip 0, four triangles at render
    // (1040..1050, 2045..2060), z 113 (in make_test_link.py's region); strip 1, two triangles at the same place, z 90
    // (the road below: out of the region's heights)
    BYTE* p = (BYTE*)calloc(1, kP703Size);
    BYTE* inst = p + 0x20;
    BYTE* art = inst + 0x40;
    *(DWORD*)(p + 4) = 1;
    *(DWORD*)(p + 8) = (DWORD)(UINT_PTR)inst;
    const float c = 0.8660254f, s = 0.5f;
    float r0[3] = {c, 0, -s}, r2[3] = {s, 0, c}, t[3] = {37.0f, -5.0f, 211.0f};
    memcpy(inst, r0, 12);
    memcpy(inst + 0x20, r2, 12);
    memcpy(inst + 0x30, t, 12);
    *(DWORD*)(inst + 0x1C) = (DWORD)(UINT_PTR)art;
    *(WORD*)(art + 0) = 2;
    *(WORD*)(art + 2) = 2 * 0x10 + 8 * 8;
    *(WORD*)(art + 4) = 7;
    {
        // render (x, y, z) -> physics world (-y, z, x) -> local l = w0 r0 + w1 (0, 1, 0) + w2 r2 + t
        auto local = [&](float rx, float ry, float rz, float* l) {
            float w[3] = {-ry, rz, rx};
            for (int a = 0; a < 3; a++) l[a] = w[0] * r0[a] + (a == 1 ? w[1] : 0.0f) + w[2] * r2[a] + t[a];
        };
        const float pts0[6][3] = {{1040, 2045, 113}, {1050, 2045, 113}, {1040, 2052, 113},
                                  {1050, 2052, 113}, {1040, 2060, 113}, {1050, 2060, 113}};
        const float pts1[4][3] = {{1040, 2045, 90}, {1050, 2045, 90}, {1040, 2052, 90}, {1050, 2052, 90}};
        int off = 2 * 0x10;
        for (int st = 0; st < 2; st++)
        {
            int n = st ? 4 : 6;
            const float(*pts)[3] = st ? pts1 : pts0;
            float cc[3];
            local(pts[0][0], pts[0][1], pts[0][2], cc);
            memcpy(art + 0x10 + 0x10 * st, cc, 12);
            *(WORD*)(art + 0x10 + 0x10 * st + 14) = (WORD)off;
            BYTE* sd = art + 0x10 + off;
            for (int k = 0; k < n; k++)
            {
                float l[3];
                local(pts[k][0], pts[k][1], pts[k][2], l);
                for (int a = 0; a < 3; a++) *(short*)(sd + 8 * k + 2 * a) = (short)lrintf((l[a] - cc[a]) * 128.0f);
                *(WORD*)(sd + 8 * k + 6) = (WORD)(k == 0 ? n : k == 1 ? 1 : 0);  // count, strip flags, faces 0
            }
            off += 8 * n;
        }
    }
    for (int e = 0; e < 7; e++)
    {
        float* b = (float*)(art + 0x10 + 2 * 0x10 + 8 * 8 + 0x20 * e);
        float y = e < 5 ? 2100.0f : 1900.0f, xa = 995.0f + 20.0f * (e % 5), xb = xa + 20.0f;
        float w[2][3] = {{-y, 112.0f, xa}, {-y, 176.0f, xb}};
        for (int q = 0; q < 2; q++)
            for (int a = 0; a < 3; a++)
                b[4 * q + a] = w[q][0] * r0[a] + (a == 1 ? w[q][1] : 0.0f) + w[q][2] * r2[a] + t[a];
        float lx = b[4] - b[0], lz = b[6] - b[2];
        b[7] = 1.0f / sqrtf(lx * lx + lz * lz);  // fPts[1].w: 1 / the xz length, as the game's files carry it
        ((BYTE*)b)[0x0D] = 0x02;
    }
    return p;
}

// Does a collider with this exclusion mask, at local point (px, py, pz) with radius r, take barrier b into its list?
// As the game's GetBarrierList (0x7844F0, inlined WCollisionMgr::GetBarrierList): skipped when the mask's low byte
// shares a bit with the surface flags byte (barrier + 0x0D: `mov dl, [ebp+0xd]; test [eax], dl`), else taken when
// DistSq (0x7627B0, xz, with 1 / length at +0x1C) < r^2 and py + r > YBot and py - r <= YTop (the lower and higher
// of +0x04 and +0x14).
static bool LkCollects(const float* b, DWORD mask, float px, float py, float pz, float r)
{
    if ((BYTE)mask & ((const BYTE*)b)[0x0D])
        return false;
    float x1 = b[0], z1 = b[2], x2 = b[4], z2 = b[6], inv = b[7];
    float u = ((px - x1) * (x2 - x1) + (pz - z1) * (z2 - z1)) * inv * inv, d2;
    if (u < 0)
        d2 = (x1 - px) * (x1 - px) + (z1 - pz) * (z1 - pz);
    else if (u > 1)
        d2 = (x2 - px) * (x2 - px) + (z2 - pz) * (z2 - pz);
    else
    {
        float nx = u * (x2 - x1) + x1 - px, nz = u * (z2 - z1) + z1 - pz;
        d2 = nx * nx + nz * nz;
    }
    float bot = b[1] < b[5] ? b[1] : b[5], top = b[5] < b[1] ? b[1] : b[5];
    return d2 < r * r && py + r > bot && py - r <= top;
}

// How many of the five barriers on the wall line let a collider with this mask through: one standing on each, at the
// height of the road under it (the article's local y 113, the stand-in's road; the wall reaches 112..176), radius 3.
// The barriers' own points are read as the pack holds them now; the collider stands where the barrier was built
// (LkMakePack's geometry, so a barrier the plugin moved away is not followed).
static int LkOpenFor(const BYTE* p, DWORD mask)
{
    const BYTE* art = (const BYTE*)(UINT_PTR)*(DWORD*)(p + 0x20 + 0x1C);
    const float* r0 = (const float*)(p + 0x20);
    const float* r2 = (const float*)(p + 0x20 + 0x20);
    const float* t = (const float*)(p + 0x20 + 0x30);
    int n = 0;
    for (int e = 0; e < 5; e++)
    {
        const float* b = (const float*)(art + 0x10 + *(WORD*)(art + 2) + 0x20 * e);
        float xa = 995.0f + 20.0f * e + 10.0f, w[3] = {-2100.0f, 113.0f, xa}, l[3];
        for (int a = 0; a < 3; a++) l[a] = w[0] * r0[a] + (a == 1 ? w[1] : 0.0f) + w[2] * r2[a] + t[a];
        n += !LkCollects(b, mask, l[0], l[1], l[2], 3.0f);
    }
    return n;
}

// the player's car: its body's collision mask (g_rb + 0xBC = RigidBody + 0x104)
static int LkOpen(const BYTE* p) { return LkOpenFor(p, g_rb[0xBC / 4]); }

// the faces of pack 703 whose flags byte (the high byte of vertex k + 2's word) has 4; z90: those of strip 1
static int LkFlagged(const BYTE* p, bool z90 = false)
{
    const BYTE* art = (const BYTE*)(UINT_PTR)*(DWORD*)(p + 0x20 + 0x1C);
    int n = 0;
    for (int st = 0; st < 2; st++)
    {
        if (z90 != (st == 1))
            continue;
        const BYTE* sd = art + 0x10 + *(const WORD*)(art + 0x10 + 0x10 * st + 14);
        int count = *(const WORD*)(sd + 6);
        for (int k = 0; k + 2 < count; k++) n += (sd[8 * (k + 2) + 7] & 4) != 0;
    }
    return n;
}

static void LinkSetup(bool badList)
{
    for (DWORD page : {0x569000u, 0x72D000u, 0x76C000u, 0x784000u, 0x773000u, 0x6B5000u}) Reserve(page, 0x1000);
    // RigidBody::RigidBody's store of the collision mask at +0x104 (FTownConnect.h reads it for its log line)
    PutBytes(0x6B5BC6, {0x8B, 0x47, 0x34, 0x89, 0x85, 0x04, 0x01, 0x00, 0x00});
    for (DWORD l : {0x9A3B50u, 0x9A3B60u})
    {
        Put(l, l);
        Put(l + 4, l);
    }
    if (g_link == 2)  // the sites (only checked) where the game reads what FTownConnect.h relies on
    {
        PutBytes(0x569010, {0x8B, 0x0D, 0x00, 0xE0, 0x91, 0x00, 0x8B, 0x91, 0x60, 0x19, 0x00, 0x00});
        PutBytes(0x72DE25, {0x8D, 0x95, 0xDE, 0x00, 0x00, 0x00});
        PutBytes(0x72DE81, {0x8B, 0x0D, 0x60, 0x3B, 0x9A, 0x00});
        PutBytes(0x72DE96, {0x66, 0x39, 0x51, 0x0C});
        PutBytes(0x72DEA8, {0x0F, 0xBF, 0x51, 0x10});
        PutBytes(0x76C6BC, {0x66, 0x39, 0x51, 0x18});
        PutBytes(0x76C6C7, {0x8B, 0x41, 0x1C});
        PutBytes(0x76C6E0, {0x0F, 0xB7, 0x70, 0x02});
        PutBytes(0x76C6F0, {0x8D, 0x47, 0x0D, 0x08, 0x10});
        PutBytes(0x7845C4, {0x8A, 0x55, 0x0D, 0x84, 0x10});              // GetBarrierList: the exclusion test
        PutBytes(0x7845EE, {0xD9, 0x45, 0x04, 0xD8, 0x5D, 0x14});        // GetBarrierList: the heights
        PutBytes(0x7731CA, {0xD9, 0x47, 0x04, 0xD8, 0x5F, 0x14});        // GetClosestIntersectingBarrier: the heights
    }
    LkZone(0, 309, -3000.0f, -3000.0f, 3000.0f, 1900.0f, {309, 349});
    if (badList)
        LkZone(1, 703, 900.0f, 1900.0f, 2100.0f, 2100.0f, {703, 743, 704, 744, 309, 726, 723});
    else
        LkZone(1, 703, 900.0f, 1900.0f, 2100.0f, 2100.0f, {703, 743, 704, 744, 309, 726});
    LkZone(2, 726, 900.0f, 2100.0f, 2100.0f, 3000.0f, {726, 766});
    LkZone(3, 723, 900.0f, 3000.0f, 2100.0f, 4000.0f, {723, 763});
    g_p703 = LkMakePack();
    g_packList[703] = (DWORD)(UINT_PTR)g_p703;
    Put(0x91E000, 0x00ACE000);
    *(DWORD*)(UINT_PTR)(0x00ACE000 + 0x1960) = g_racing ? 1 : 0;
}

// after the plugin's hook each frame: the glides, the restream, the streamer
static void LinkGlide()
{
    for (int k = 0; k < g_glideCount; k++)
    {
        const Glide& g = g_glides[k];
        if (g_frame < g.a || g_frame > g.b)
            continue;
        float t = g.b > g.a ? (float)(g_frame - g.a) / (g.b - g.a) : 1.0f;
        g_pos[0] = -(g.y0 + (g.y1 - g.y0) * t);
        g_pos[2] = g.x0 + (g.x1 - g.x0) * t;
    }
}

static void LinkFrameStandin()
{
    if (g_frame == g_nodeCheck)
    {
        const BYTE* nodes = (const BYTE*)(UINT_PTR)Get(0x9B38BC);
        for (int k = 1; k <= 2; k++)
        {
            printf("NODE %d segs", k);
            for (int i = 0; i < nodes[32 * k + 16]; i++) printf(" %u", *(const WORD*)(nodes + 32 * k + 18 + 2 * i));
            printf("\n");
        }
    }
    if (g_frame == g_segCheckF)
        for (int k = 0; k < g_segN; k++)
        {
            const BYTE* segs = (const BYTE*)(UINT_PTR)Get(0x9B38C0);
            printf("SEG %d flags 0x%04X\n", g_segCheck[k], *(const WORD*)(segs + 22 * g_segCheck[k] + 10));
        }
    for (int c = 0; c < g_cellN; c++)
    if (g_frame == g_cellCheck[c])
    {
        DWORD col = (DWORD)floorf((-g_cellY[c] - g_grid.min[0]) / 64.0f),
              row = (DWORD)floorf((g_cellX[c] - g_grid.min[2]) / 64.0f);
        Node* n = (Node*)(UINT_PTR)g_grid.nodes[row * g_grid.cols + col];
        printf("CELL %lu,%lu", (unsigned long)row, (unsigned long)col);
        if (!n)
            printf(" no node\n");
        else
        {
            printf(" node %s roads", n == &g_rockNode ? "rockport" : "other");
            const DWORD* tags = (const DWORD*)((const BYTE*)n + 0x14 + n->offsets[3]);
            for (int i = 0; i < n->counts[3]; i++) printf(" %lu", (unsigned long)tags[i]);
            printf(" statics %d\n", n->counts[0]);
        }
    }
    if (!g_link)
        return;
    if (g_frame == g_restream703)
    {
        g_p703Old = g_p703;
        memcpy(g_p703OldCopy, g_p703Old + 0x20, sizeof(g_p703OldCopy));
        g_p703 = LkMakePack();
        g_packList[703] = (DWORD)(UINT_PTR)g_p703;
        printf("PACK703 restreamed (old object kept: open %d)\n", LkOpen(g_p703Old));
    }
    float x = g_pos[2], y = -g_pos[0];
    bool hold = g_frame >= g_zoneHoldA && g_frame <= g_zoneHoldB;
    int zone = g_lnZone < 0 ? 0 : g_lnZone;
    if (!hold && !*(BYTE*)0x9AAC81)
    {
        BYTE* r = (BYTE*)LkFind(x, y);
        zone = r ? *(short*)(r + 0x0C) : 0;
    }
    if (zone != g_lnZone)
    {
        printf("STREAMER f=%d car (%.0f, %.0f) zone %d", g_frame, x, y, zone);
        if (zone > 0)
        {
            BYTE* rec = nullptr;
            for (DWORD n = Get(0x9A3B60); n != 0x9A3B60; n = *(DWORD*)(UINT_PTR)n)
                if (*(short*)(UINT_PTR)(n + 0x0C) == zone)
                {
                    rec = (BYTE*)(UINT_PTR)n;
                    break;
                }
            if (rec)
            {
                printf(" list");
                for (int i = 0; i < *(short*)(rec + 0x10); i++) printf(" %d", *(short*)(rec + 0x12 + 2 * i));
            }
        }
        printf("; wall 703 open %d; faces 703 flagged %d; traffic through %d, cops through %d\n", LkOpen(g_p703),
               LkFlagged(g_p703), LkOpenFor(g_p703, 0x40), LkOpenFor(g_p703, 0x80));
        g_lnZone = zone;
    }
    *(short*)(UINT_PTR)(0x9AA9D0 + 0xDE) = (short)zone;
    if (zone > 0)  // DetermineStreamingSections, every frame a zone is set: its record by number
    {
        bool found = false;
        for (DWORD n = Get(0x9A3B60); n != 0x9A3B60; n = *(DWORD*)(UINT_PTR)n)
            found |= *(short*)(UINT_PTR)(n + 0x0C) == zone;
        if (!found)
            printf("STREAMER NULL READ f=%d zone %d\n", g_frame, zone);
    }
}

static void LinkReport()
{
    if (!g_link)
        return;
    // in number order (the game's lookups reorder the lists: move to head); also every next/prev pair checked
    int nums[32], cnt = 0, broken = 0;
    char star[32];
    for (DWORD n = Get(0x9A3B60); n != 0x9A3B60 && cnt < 32; n = *(DWORD*)(UINT_PTR)n)
    {
        bool orig = false;
        for (int k = 0; k < 4; k++) orig |= (BYTE*)(UINT_PTR)n == g_lnRec[k];
        broken += *(DWORD*)(UINT_PTR)(*(DWORD*)(UINT_PTR)n + 4) != n;
        star[cnt] = orig ? 0 : '*';
        nums[cnt++] = *(short*)(UINT_PTR)(n + 0x0C);
    }
    for (int a = 0; a < cnt; a++)
        for (int b = a + 1; b < cnt; b++)
            if (nums[b] < nums[a] || (nums[b] == nums[a] && star[b] < star[a]))
            {
                int t = nums[a];
                nums[a] = nums[b], nums[b] = t;
                char c = star[a];
                star[a] = star[b], star[b] = c;
            }
    printf("LISTS sections");
    for (int a = 0; a < cnt; a++) printf(" %d%s", nums[a], star[a] ? "*" : "");
    int bn[32], bc = 0;
    for (DWORD n = Get(0x9A3B50); n != 0x9A3B50 && bc < 32; n = *(DWORD*)(UINT_PTR)n)
    {
        broken += *(DWORD*)(UINT_PTR)(*(DWORD*)(UINT_PTR)n + 4) != n;
        bn[bc++] = *(short*)(UINT_PTR)(n + 8);
    }
    for (int a = 0; a < bc; a++)
        for (int b = a + 1; b < bc; b++)
            if (bn[b] < bn[a])
            {
                int t = bn[a];
                bn[a] = bn[b], bn[b] = t;
            }
    printf(" boundaries");
    for (int a = 0; a < bc; a++) printf(" %d", bn[a]);
    if (broken)
        printf(" LINKS BROKEN %d", broken);
    printf("\nWALL703 open %d (traffic %d, cops %d)", LkOpen(g_p703), LkOpenFor(g_p703, 0x40), LkOpenFor(g_p703, 0x80));
    if (g_p703Old)
        printf(" old object %s", memcmp(g_p703OldCopy, g_p703Old + 0x20, sizeof(g_p703OldCopy)) ? "WRITTEN" : "untouched");
    printf("\nFACES703 flagged %d (the road below: %d)\n", LkFlagged(g_p703), LkFlagged(g_p703, true));
}

int main(int argc, char** argv)
{
    setvbuf(stdout, nullptr, _IONBF, 0);  // a crash keeps every line printed before it
    int frames = 80;
    bool wrong = false, taken = false, nosim = false, zoneoff = false, menuWrong = false, menuWrongLong = false;
    int deleteFrame = -1, changeFrame = -1;
    bool trafficWrong = false, eveWrong = false, smkWrong = false;
    int smkCount = 22340, simAt = -1, smkLive = 0, smkLiveUntil = 30;
    const char* wp = nullptr;
    for (int i = 1; i < argc; i++)
    {
        if (!strncmp(argv[i], "frames=", 7)) frames = atoi(argv[i] + 7);
        else if (!strncmp(argv[i], "go=", 3)) ParseList(argv[i] + 3, g_goFrames, &g_goCount);
        else if (!strcmp(argv[i], "evewrong")) eveWrong = true;
        else if (!strcmp(argv[i], "todoverride")) g_todOverride = 1;
        else if (!strncmp(argv[i], "todset=", 7)) g_todSetFrame = atoi(argv[i] + 7);
        else if (!strncmp(argv[i], "unloadkey=", 10)) g_unloadFrame = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "gone=", 5)) { g_goneA = atoi(argv[i] + 5); g_goneB = atoi(strchr(argv[i], '-') + 1); }
        else if (!strncmp(argv[i], "trackunload=", 12)) g_trackUnloadFrame = atoi(argv[i] + 12);
        else if (!strcmp(argv[i], "noface")) g_noface = 1;
        else if (!strcmp(argv[i], "nofile")) g_nofile = 1;
        else if (!strcmp(argv[i], "taken")) taken = true;
        else if (!strncmp(argv[i], "taken=", 6)) { taken = true; g_takenNumber = atoi(argv[i] + 6); }
        else if (!strncmp(argv[i], "next=", 5)) ParseList(argv[i] + 5, g_nextFrames, &g_nextCount);
        else if (!strncmp(argv[i], "ta=", 3)) ParseList(argv[i] + 3, g_taFrames, &g_taCount);
        else if (!strncmp(argv[i], "nextev=", 7)) ParseList(argv[i] + 7, g_nevFrames, &g_nevCount);
        else if (!strncmp(argv[i], "nofile=", 7)) g_nofileNumber = atoi(argv[i] + 7);
        else if (!strcmp(argv[i], "wrongbytes")) wrong = true;
        else if (!strcmp(argv[i], "background")) g_background = 1;
        else if (!strcmp(argv[i], "existingnode")) g_existing = 1;
        else if (!strncmp(argv[i], "worldprobe=", 11)) wp = argv[i] + 11;
        else if (!strncmp(argv[i], "foreign=", 8)) g_foreignFrame = atoi(argv[i] + 8);
        else if (!strcmp(argv[i], "nohome")) g_nohome = 1;
        else if (!strcmp(argv[i], "nosim")) nosim = true;
        else if (!strncmp(argv[i], "smkcount=", 9)) smkCount = atoi(argv[i] + 9);
        else if (!strcmp(argv[i], "smkwrong")) smkWrong = true;
        else if (!strncmp(argv[i], "simat=", 6)) simAt = atoi(argv[i] + 6);  // the simulation appears on that frame
        else if (!strncmp(argv[i], "smklive=", 8)) smkLive = atoi(argv[i] + 8);  // Rockport's live smackables
        else if (!strcmp(argv[i], "zoneoff")) zoneoff = true;
        else if (!strcmp(argv[i], "noresetable")) g_noresetable = 1;
        else if (!strncmp(argv[i], "deletemap=", 10)) deleteFrame = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "changemap=", 10)) changeFrame = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "route=", 6) && g_routeCount < 2)
        {
            sscanf(argv[i] + 6, "%d:%f", &g_routeFrames[g_routeCount], &g_routeSteps[g_routeCount]);
            g_routeCount++;
        }
        else if (!strncmp(argv[i], "routeskip=", 10)) g_routeSkip = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "pause=", 6)) { g_pauseA = atoi(argv[i] + 6); g_pauseB = atoi(strchr(argv[i], '-') + 1); }
        else if (!strcmp(argv[i], "crashwrite")) g_crashWrite = 1;
        else if (!strcmp(argv[i], "nohud")) g_nohud = 1;
        else if (!strncmp(argv[i], "hudfrom=", 8)) g_hudFrom = atoi(argv[i] + 8);
        else if (!strncmp(argv[i], "resetablefrom=", 14)) g_resetableFrom = atoi(argv[i] + 14);
        else if (!strncmp(argv[i], "gameicons=", 10)) g_gameIcons = atoi(argv[i] + 10);
        else if (!strcmp(argv[i], "iconitemoff")) g_icoItemOff = 1;
        else if (!strcmp(argv[i], "iconwrong")) g_iconWrong = 1;
        else if (!strncmp(argv[i], "gamemsg=", 8)) g_gmGameFrame = atoi(argv[i] + 8);
        else if (!strcmp(argv[i], "manual")) g_profile[0x80 + 0x11] = 1;
        else if (!strcmp(argv[i], "creep")) g_creep = 1;
        else if (!strncmp(argv[i], "gridhold=", 9)) { g_gridA = atoi(argv[i] + 9); g_gridB = atoi(strchr(argv[i], '-') + 1); }
        else if (!strncmp(argv[i], "gasat=", 6)) g_gasAtFrame = atoi(argv[i] + 6);
        else if (!strncmp(argv[i], "nis=", 4)) { g_nisA = atoi(argv[i] + 4); g_nisB = atoi(strchr(argv[i], '-') + 1); }
        else if (!strncmp(argv[i], "nogridat=", 9)) g_noGridUntil = atoi(argv[i] + 9);
        else if (!strcmp(argv[i], "nodragcarrier")) g_noDragCarrier = 1;
        else if (!strcmp(argv[i], "dragsteer")) g_dragSteer = 1;
        else if (!strcmp(argv[i], "nolock")) g_noLock = 1;
        else if (!strncmp(argv[i], "spawncheck=", 11) && g_spawnN < 16)
            sscanf(argv[i] + 11, "%d:%d", &g_spawnF[g_spawnN], &g_spawnSeg[g_spawnN]), g_spawnN++;
        else if (!strncmp(argv[i], "speedcheck=", 11) && g_speedN < 16)
            sscanf(argv[i] + 11, "%d:%d", &g_speedF[g_speedN], &g_speedSeg[g_speedN]), g_speedN++;
        else if (!strncmp(argv[i], "resetrace=", 10)) g_resetRaceF = atoi(argv[i] + 10);
        else if (!strcmp(argv[i], "link")) g_link = 2;
        else if (!strcmp(argv[i], "linkwrong")) g_link = 1;
        else if (!strcmp(argv[i], "racing")) g_racing = 1;
        else if (!strcmp(argv[i], "linkbadlist")) g_linkBadList = 1;
        else if (!strncmp(argv[i], "restream703=", 12)) g_restream703 = atoi(argv[i] + 12);
        else if (!strncmp(argv[i], "racingat=", 9)) g_racingAt = atoi(argv[i] + 9);
        else if (!strncmp(argv[i], "roamingat=", 10)) g_roamingAt = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "zonehold=", 9))
        {
            g_zoneHoldA = atoi(argv[i] + 9);
            g_zoneHoldB = atoi(strchr(argv[i], '-') + 1);
        }
        else if (!strncmp(argv[i], "nodecheck=", 10)) g_nodeCheck = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "cellcheck=", 10))
        {
            if (g_cellN < 4)
                sscanf(argv[i] + 10, "%d:%f,%f", &g_cellCheck[g_cellN], &g_cellX[g_cellN], &g_cellY[g_cellN]), g_cellN++;
        }
        else if (!strncmp(argv[i], "segcheck=", 9))  // segcheck=<frame>:<seg>,<seg>..: the segments' flags then
        {
            g_segCheckF = atoi(argv[i] + 9);
            for (char* q = strchr(argv[i], ':'); q && g_segN < 4; q = strchr(q + 1, ','))
                g_segCheck[g_segN++] = atoi(q + 1);
        }
        else if (!strncmp(argv[i], "glide=", 6) && g_glideCount < 8)
        {
            Glide& g = g_glides[g_glideCount++];
            sscanf(argv[i] + 6, "%d-%d:%f,%f:%f,%f", &g.a, &g.b, &g.x0, &g.y0, &g.x1, &g.y1);
        }
        else if (!strcmp(argv[i], "nisdirect")) g_nisDirect = 1;
        else if (!strcmp(argv[i], "trafficfull")) g_trafficFull = 1;
        else if (!strncmp(argv[i], "refuse=", 7)) strncpy(g_refuseName, argv[i] + 7, sizeof(g_refuseName) - 1);
        else if (!strncmp(argv[i], "nofaceat=", 9)) g_noFaceX = (float)atof(argv[i] + 9);
        else if (!strcmp(argv[i], "trafficwrong")) trafficWrong = true;
        else if (!strncmp(argv[i], "racingmem=", 10)) g_racingMem = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "evict=", 6)) g_evictFrame = atoi(argv[i] + 6);
        else if (!strncmp(argv[i], "fe=", 3))
        {
            static char acts[512];
            strncpy(acts, argv[i] + 3, sizeof(acts) - 1);
            for (char* t = strtok(acts, ","); t && g_feActCount < 32; t = strtok(nullptr, ","))
                g_feActs[g_feActCount++] = t;
            g_feOn = 1;
        }
        else if (!strncmp(argv[i], "countdown=", 10)) g_cdStart = atoi(argv[i] + 10);
        else if (!strncmp(argv[i], "restart=", 8)) g_restartFrame = atoi(argv[i] + 8);
        else if (!strcmp(argv[i], "nocd")) g_nocd = 1;
        else if (!strncmp(argv[i], "carriertype=", 12)) g_carrierType = atoi(argv[i] + 12);
        else if (!strcmp(argv[i], "menuwrong")) menuWrong = true;
        else if (!strcmp(argv[i], "menuwronglong")) menuWrongLong = true;
        else if (!strncmp(argv[i], "times=", 6))  // a times file from an earlier session: the best in milliseconds
        {
            FILE* t = fopen("FTownTimes.txt", "wb");
            fprintf(t, "[Route1]\r\nBestMs = %s\r\n", argv[i] + 6);
            for (int k = i + 1; k < argc; k++)  // timesextra=<section>:<key>=<value>;...: more lines (other events)
                if (!strncmp(argv[k], "timesextra=", 11))
                    for (char* q = argv[k] + 11; *q;)
                    {
                        char* e = strchr(q, ';');
                        if (e)
                            *e = 0;
                        char* c = strchr(q, ':');
                        if (c)
                        {
                            *c = 0;
                            fprintf(t, "[%s]\r\n", q);
                            for (char* l = c + 1; *l; l++)  // '|' starts a new line of the section
                                if (*l == '|')
                                    fputs("\r\n", t);
                                else
                                    fputc(*l, t);
                            fputs("\r\n", t);
                        }
                        if (!e)
                            break;
                        q = e + 1;
                    }
            fclose(t);
        }
        else if (!strncmp(argv[i], "jump=", 5) && g_jumpCount < 4)
        {
            Drive& d = g_jumps[g_jumpCount++];
            sscanf(argv[i] + 5, "%d:%f,%f", &d.frame, &d.x, &d.y);
        }
        else if (!strncmp(argv[i], "drive=", 6) && g_driveCount < 16)  // drive=<frame>:<render x>,<render y>
        {
            Drive& d = g_drives[g_driveCount++];
            sscanf(argv[i] + 6, "%d:%f,%f", &d.frame, &d.x, &d.y);
        }
    }
    ReadMap();
    BuildPath();
    DWORD regions[][2] = {{0x45C000, 0x1000}, {0x47E000, 0x1000}, {0x5D0000, 0x1000}, {0x5DD000, 0x1000}, {0x658000, 0x1000},
                          {0x661000, 0x1000}, {0x663000, 0x5000}, {0x671000, 0x1000}, {0x685000, 0x2000},
                          {0x695000, 0x2000}, {0x6A4000, 0x1000}, {0x6B0000, 0x1000}, {0x6CB000, 0x1000},
                          {0x6F8000, 0x2000}, {0x729000, 0x1000}, {0x72C000, 0x1000}, {0x731000, 0x1000},
                          {0x763000, 0x1000}, {0x772000, 0x1000}, {0x77A000, 0x1000}, {0x77D000, 0x1000},
                          {0x781000, 0x2000}, {0x789000, 0x1000}, {0x8A9000, 0x1000}, {0x8AA000, 0x1000},
                          {0x8AB000, 0x1000}, {0x8AC000, 0x1000}, {0x8B0000, 0x1000}, {0x914000, 0x1000},
                          {0x92D000, 0x1000}, {0x938000, 0x1000}, {0x9A3000, 0x4000}, {0x9AA000, 0x1000},
                          {0x9B3000, 0x1000}, {0x510000, 0x1000}, {0x5D5000, 0x1000}, {0x5EB000, 0x1000},
                          {0x611000, 0x1000}, {0x620000, 0x1000}, {0x641000, 0x1000}, {0x6F1000, 0x1000},
                          {0x755000, 0x1000}, {0x988000, 0x1000},
                          // the minimap and the HUD message (docs/ftown-race-notes.md R1, R4)
                          {0x579000, 0x1000}, {0x567000, 0x1000}, {0x722000, 0x1000}, {0x904000, 0x1000},
                          {0x91C000, 0x1000}, {0x6E8000, 0x1000}, {0x568000, 0x1000}, {0x565000, 0x1000},
                          {0x8A2000, 0x1000},
                          // the game mode's front end and race (docs/ftown-race-notes.md R5, R6)
                          {0x7AA000, 0x1000}, {0x7AB000, 0x1000}, {0x7BA000, 0x1000}, {0x7A2000, 0x1000},
                          {0x7C2000, 0x1000}, {0x56B000, 0x1000}, {0x586000, 0x1000}, {0x573000, 0x1000},
                          {0x50E000, 0x1000}, {0x587000, 0x1000}, {0x525000, 0x1000}, {0x516000, 0x1000},
                          {0x652000, 0x1000}, {0x7C6000, 0x1000}, {0x7B4000, 0x1000}, {0x50D000, 0x1000},
                          {0x5DC000, 0x1000}, {0x4B4000, 0x1000}, {0x8B7000, 0x1000}, {0x9B9000, 0x1000},
                          {0x91E000, 0x1000}, {0x603000, 0x1000}, {0x5E9000, 0x1000}, {0x5FA000, 0x1000},
                          {0x56D000, 0x1000}, {0x469000, 0x1000}, {0x600000, 0x1000}, {0x5E3000, 0x1000},
                          {0x89F000, 0x1000}, {0x925000, 0x1000},
                          // the evening (FTownEvening.h)
                          {0x769000, 0x1000}, {0x6DE000, 0x1000}, {0x742000, 0x1000}, {0x9B0000, 0x1000},
                          // the race HUD, the radar, the gears, the parked cars' input (Run I fixes)
                          {0x6F2000, 0x1000}, {0x6ED000, 0x1000}, {0x59C000, 0x1000}, {0x8A1000, 0x1000},
                          {0x6E9000, 0x1000}, {0x68D000, 0x1000}, {0x69B000, 0x1000}, {0x69C000, 0x1000},
                          // Run J: the race start (NIS, PrepareForRace), the drag steering, the minimap's textures
                          {0x6EA000, 0x1000}, {0x5CB000, 0x1000}, {0x416000, 0x1000}, {0x892000, 0x1000},
                          {0x407000, 0x1000}, {0x42F000, 0x1000}, {0x503000, 0x1000}, {0x6BE000, 0x1000},
                          {0x460000, 0x1000},
                          // moving traffic: CheckRace and its call, ComputeSpeed, bMalloc / bFree, WGrid's ctor,
                          // GetSegmentNumTrafficLanes
                          {0x404000, 0x1000}, {0x438000, 0x1000}, {0x411000, 0x1000}, {0x465000, 0x1000},
                          {0x764000, 0x1000}, {0x76D000, 0x1000},
                          // the breakable poles (FTownSmack.h): the spawner loader's and unloader's sites
                          {0x887000, 0x1000}, {0x682000, 0x1000}, {0x681000, 0x1000}, {0x723000, 0x1000},
                          {0x728000, 0x1000}, {0x67B000, 0x1000}, {0x67C000, 0x1000}, {0x926000, 0x1000},
                          // Run K: the HUD's features, the minimap's gameplay icons and the FEng calls they use
                          {0x58C000, 0x1000}, {0x57C000, 0x1000}, {0x59D000, 0x1000}, {0x57A000, 0x1000},
                          {0x514000, 0x1000}, {0x515000, 0x1000}, {0x5B2000, 0x1000}, {0x890000, 0x1000},
                          {0x8F3000, 0x1000}};
    for (auto& r : regions) Reserve(r[0], r[1]);
    for (DWORD a : {0x914000u, 0x92D000u, 0x938000u, 0x988000u, 0x9AA000u, 0x9B3000u, 0x904000u, 0x91C000u, 0x8A2000u,
                    0x9B9000u, 0x91E000u, 0x925000u, 0x8B7000u})
        memset((void*)(UINT_PTR)a, 0, 0x1000);
    memset((void*)0x9A3000, 0, 0x4000);
    memset((void*)0x9B0000, 0, 0x1000);
    // the evening's sites (only checked) and the time-of-day object (Rockport's race: time 0.3, rate 1, direction +1)
    At(0x7696B0); B({0xD9, 0x44, 0x24, 0x04, 0xA1, 0x2C, 0x39, 0x9B, 0x00, 0xD9, 0x58, 0x08, 0xC3});
    if (eveWrong) *(BYTE*)0x7696B0 = 0x90;
    At(0x769390); B({0x8B, 0x4E, 0x04, 0xD9, 0x05, 0xBC, 0x59, 0x92, 0x00, 0xD8, 0x0D, 0xF0, 0x70, 0x89, 0x00, 0x89, 0x4C,
                     0x24, 0x18, 0xDA, 0x4C, 0x24, 0x18, 0xD8, 0x0E});
    At(0x6DE3D6); B({0x8B, 0x0D, 0x2C, 0x39, 0x9B, 0x00, 0xE8}); Rel(0x769360);
    At(0x742AC3); B({0xA1, 0x2C, 0x09, 0x9B, 0x00, 0x85, 0xC0});
    g_tod[0] = 1.0f;
    *(int*)&g_tod[1] = 1;
    g_tod[2] = 0.3f;
    Put(0x9B392C, (DWORD)(UINT_PTR)g_tod);
    VehiclesSetup();
    NetSetup();
    if (g_link)
        LinkSetup(g_linkBadList != 0);
    SmkSetup(smkCount, smkWrong);
    Put(0x92617C, (DWORD)smkLive);  // smklive=: Rockport's own spawners' models, gone at frame 30 (their sections dropped)
    for (int i = 1; i < argc; i++)
        if (!strcmp(argv[i], "netwrong"))  // the posted-speed site differs: moving traffic off
            *(BYTE*)0x411882 = 0x90;
    if (g_spawnN)
        Put(0x91E000, 0x00ACE000);  // GRaceStatus exists (racing): CheckRace's own rule
    if (trafficWrong)  // Construct's parameter check differs
        *(BYTE*)0x689854 = 0xAD;

    // MainLoop: call bGetTicker at 0x663D30 (FTownLoader's hook), call MainLoopBreakpoint at 0x663D35 (WorldProbe's)
    At(0x663D30); B({0xE8}); Rel(0x45CE40); B({0xE8}); Rel(0x667650); B({0xC3});
    At(0x667650); B({0xC3});
    // bGetTicker: the game's 6 bytes (sub esp, 8; lea eax, [esp]), then add esp, 8; jmp StTicker
    At(0x45CE40); B({0x83, 0xEC, 0x08, 0x8D, 0x04, 0x24, 0x83, 0xC4, 0x08}); Jmp((DWORD)(UINT_PTR)&StTicker);
    // TrackLoader::Unload: push ebx; push esi; push 8; xor ebx, ebx; then add esp, 4; pop esi; pop ebx; jmp
    At(0x6617E0); B({0x53, 0x56, 0x6A, 0x08, 0x33, 0xDB, 0x83, 0xC4, 0x04, 0x5E, 0x5B}); Jmp((DWORD)(UINT_PTR)&StTrackUnload);
    At(0x6617F6); B({0x68, 0xF8, 0x8E, 0x8A, 0x00});
    // LoadChunks: the game's 10 bytes (two pushes), pop edi; pop esi; jmp StLoadChunks (cdecl)
    At(0x6589A0); B({0x8B, 0x44, 0x24, 0x08, 0x56, 0x8B, 0x74, 0x24, 0x08, 0x57, 0x5F, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StLoadChunks);
    // UnloadChunks: sub esp, 0x100; push edi; call eWaitUntilRenderingDone (0x6CB2A0: ret); then pop edi;
    // add esp, 0x100; jmp StUnloadChunks
    At(0x658A00); B({0x81, 0xEC, 0x00, 0x01, 0x00, 0x00, 0x57, 0xE8}); Rel(0x6CB2A0);
    B({0x5F, 0x81, 0xC4, 0x00, 0x01, 0x00, 0x00}); Jmp((DWORD)(UINT_PTR)&StUnloadChunks);
    At(0x6CB2A0); B({0xC3});
    // GetWorldHeightAtPoint: the game's 9 bytes, then add esp, 4; pop esi; add esp, 0x48; jmp StHeight
    At(0x7897C0); B({0x83, 0xEC, 0x48, 0x56, 0x68, 0xCD, 0xCC, 0xCC, 0x3C, 0x83, 0xC4, 0x04, 0x5E, 0x83, 0xC4, 0x48});
    Jmp((DWORD)(UINT_PTR)&StHeight);
    // AddDynamic: mov eax, fs:[0]; push -1; push 0x88201F; then add esp, 8; jmp StAddDynamic
    At(0x782B30); B({0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x6A, 0xFF, 0x68, 0x1F, 0x20, 0x88, 0x00, 0x83, 0xC4, 0x08});
    Jmp((DWORD)(UINT_PTR)&StAddDynamic);
    if (wrong) *(BYTE*)0x782B30 = 0x90;
    // RemoveDynamic: push esi; mov esi, [ecx]; test esi, esi; je 0x77A6DC; mov ecx, [esi+4]; then mov ecx, esi;
    // pop esi; jmp StRemoveList (the list in ecx); at 0x77A6DC (no list): pop esi; ret 8
    At(0x77A680); B({0x56, 0x8B, 0x31, 0x85, 0xF6, 0x74, 0x55, 0x8B, 0x4E, 0x04, 0x8B, 0xCE, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StRemoveList);
    At(0x77A6DC); B({0x5E, 0xC2, 0x08, 0x00});
    // WCollisionAssets::SetExclusionFlags: push esi; push edi; mov edi, ecx; xor esi, esi; then pop edi; pop esi;
    // jmp StSetExclusion. Its collider loop's bytes at 0x782C81 (only checked) and the game's call at 0x5DD116.
    At(0x782C60); B({0x56, 0x57, 0x8B, 0xF9, 0x33, 0xF6, 0x5F, 0x5E}); Jmp((DWORD)(UINT_PTR)&StSetExclusion);
    At(0x782C81); B({0x8B, 0x35, 0x84, 0x3C, 0x9B, 0x00, 0x8B, 0x15, 0x8C, 0x3C, 0x9B, 0x00, 0x8D, 0x3C, 0x96, 0x3B, 0xF7,
                     0x74, 0x17, 0x8B, 0x0E, 0xE8}); Rel(0x782A30);
    B({0x8B, 0x06, 0x83, 0xC6, 0x04, 0x3B, 0xF7, 0xC6, 0x80, 0x80, 0x00, 0x00, 0x00, 0x00, 0x75, 0xE9});
    At(0x5DD116); B({0x8B, 0x0D, 0x90, 0x38, 0x9B, 0x00, 0xE8}); Rel(0x782C60);
    // WCollider::Clear: push ebx; push esi; mov esi, ecx; then pop esi; pop ebx; jmp StClear
    At(0x782A30); B({0x53, 0x56, 0x8B, 0xF1, 0x5E, 0x5B}); Jmp((DWORD)(UINT_PTR)&StClear);
    // the list's destructor and gFastMem's Free
    At(0x77D470); Jmp((DWORD)(UINT_PTR)&StListDtor);
    At(0x5D0370); Jmp((DWORD)(UINT_PTR)&StFastFree);
    // WGrid::Shutdown's bytes (only checked, never run: their calls name 0x77D470 and 0x5D0370 above)
    At(0x7816F0); B({0xA1, 0xA8, 0x38, 0x9B, 0x00});
    At(0x7816FD); B({0x8B, 0x48, 0x1C, 0x0F, 0xAF, 0x48, 0x18});
    At(0x781710); B({0x8B, 0x50, 0x20});
    At(0x781720); B({0x8B, 0xCE, 0xE8}); Rel(0x77D470); B({0x6A, 0x00, 0x6A, 0x0C, 0x56, 0xB9, 0x30, 0x5B, 0x92, 0x00, 0xE8});
    Rel(0x5D0370);
    At(0x76369A); B({0xD8, 0x26, 0x57, 0xD8, 0x4E, 0x14});
    At(0x7636AB); B({0xD9, 0x43, 0x08, 0xD8, 0x66, 0x08, 0xD8, 0x4E, 0x14});
    At(0x772CF1); B({0x8B, 0x0D, 0xA0, 0x38, 0x9B, 0x00});
    At(0x731915); B({0x8B, 0x0C, 0x85, 0xB0, 0x3B, 0x9A, 0x00});
    At(0x7299E0); B({0x57, 0x8B, 0x7C, 0x24, 0x08, 0x8B, 0x44, 0xB9, 0x60});
    // the player (WorldProbe's and FTownLoader's sites)
    At(0x47EF0A); B({0x39, 0x1D, 0x84, 0xD8, 0x92, 0x00});
    At(0x47EF12); B({0xA1, 0x7C, 0xD8, 0x92, 0x00});
    At(0x6F8FB0); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F8F30);
    At(0x6F9050); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F9000);
    At(0x6F9060); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F9020);
    At(0x6F8F30); Jmp((DWORD)(UINT_PTR)&GetSimable);
    At(0x6F9000); Jmp((DWORD)(UINT_PTR)&GetPosition);
    At(0x6F9020); B({0x8B, 0x41, 0x18, 0x85, 0xC0}); Jmp((DWORD)(UINT_PTR)&SetPosition);
    // RigidBody::SetPosition: the game's first 5 bytes (mov eax, [ecx+0x30]; mov ecx, [eax]: the body's data
    // block), then our own copy of the position into +0x10 (mov edx, [esp+4]; 3 x mov; ret 4)
    At(0x696FB0); B({0x8B, 0x41, 0x30, 0x8B, 0x08, 0x8B, 0x54, 0x24, 0x04, 0x8B, 0x02, 0x89, 0x41, 0x10, 0x8B, 0x42,
                     0x04, 0x89, 0x41, 0x14, 0x8B, 0x42, 0x08, 0x89, 0x41, 0x18, 0xC2, 0x04, 0x00});
    At(0x696D90); B({0x53, 0x55, 0x56, 0x8B, 0x74, 0x24, 0x10});
    At(0x696DAB); B({0xB9, 0x10, 0x00, 0x00, 0x00, 0xF3, 0xA5});
    At(0x671270); B({0x8B, 0x41, 0x30, 0x8B, 0x00, 0x8B, 0x4C, 0x24, 0x04, 0x05, 0x90, 0x00, 0x00});
    At(0x6711B0); B({0x51, 0x8B, 0x41, 0x30, 0x8B, 0x00, 0xD9, 0x40, 0x28, 0x83, 0xC0, 0x20});  // RigidBody::GetSpeed
    // WorldProbe's other sites (world/tests/standin.cpp): FindDrivableSection, the data ties, the reset path
    At(0x72CA00); B({0x51, 0x53, 0x55, 0x8B, 0x6C, 0x24, 0x10, 0x8D, 0x59, 0x10, 0x5D, 0x5B, 0x59});
    Jmp((DWORD)(UINT_PTR)&FindDrivable);
    At(0x7318B4); B({0xB9, 0x50, 0x3B, 0x9A, 0x00});
    At(0x7318CA); B({0x8B, 0x3D, 0x78, 0xA4, 0x9A, 0x00});
    At(0x6959FD); B({0x81, 0xC1, 0xC8, 0x86, 0x93, 0x00});
    At(0x6B08C0); B({0x83, 0xEC, 0x20, 0x53, 0x8B, 0x5C, 0x24, 0x28});
    At(0x6A45F0); B({0x6A, 0xFF, 0x68, 0xAF, 0xC9, 0x87, 0x00});
    At(0x685810); B({0x6A, 0xFF, 0x64, 0xA1, 0x00, 0x00, 0x00, 0x00});
    At(0x6B0884); B({0xFF, 0x52, 0x08});
    At(0x6B0960); B({0xE8}); Rel(0x6A45F0);
    At(0x6A4631); B({0xFF, 0x52, 0x68});
    Put(0x8ABA18, 0x6B08C0);
    Put(0x8AA890, 0x685810);
    // the return path: Sim::SetStream (push ebp; mov ebp, esp; and esp, -16; sub esp, 16; mov eax, [mSystem]), then
    // mov esp, ebp; pop ebp; jmp StSetStream (cdecl); its blocking branch and the game's callers (only checked)
    At(0x6F1170); B({0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF0, 0x83, 0xEC, 0x10, 0xA1, 0xE0, 0x85, 0x98, 0x00, 0x8B, 0xE5, 0x5D});
    Jmp((DWORD)(UINT_PTR)&StSetStream);
    At(0x6F11B8); B({0x8A, 0x45, 0x0C, 0x84, 0xC0, 0x74, 0x3F});
    At(0x6F11BF); B({0x8B, 0x0D, 0xE0, 0x85, 0x98, 0x00, 0x6A, 0x01, 0xE8}); Rel(0x6F0F80);
    At(0x6F11D6); B({0xB9, 0xD0, 0xA9, 0x9A, 0x00, 0xE8}); Rel(0x7317A0);
    At(0x5108C0); B({0xC6, 0x81, 0xB1, 0x02, 0x00, 0x00, 0x01, 0xC3});
    At(0x5EBD16); B({0xC6, 0x05, 0x81, 0xAC, 0x9A, 0x00, 0x00, 0xE8}); Rel(0x6F1170);
    At(0x6115A1); B({0x56, 0xA2, 0x81, 0xAC, 0x9A, 0x00, 0xE8}); Rel(0x6F1170);
    At(0x755681); B({0x8D, 0x54, 0x24, 0x10, 0x6A, 0x01, 0x52, 0xE8}); Rel(0x6F1170);
    // Find: sub esp, 8; push esi; mov esi, [ecx+8]; mov ecx, [ecx+4] (the stand-in's list points at itself), then
    // pop esi; add esp, 8; jmp StFind
    At(0x5D59F0); B({0x83, 0xEC, 0x08, 0x56, 0x8B, 0x71, 0x08, 0x8B, 0x49, 0x04, 0x5E, 0x83, 0xC4, 0x08});
    Jmp((DWORD)(UINT_PTR)&StFind);
    At(0x620250); B({0xB8, 0x50, 0x02, 0x62, 0x00, 0xC3});
    At(0x611642); B({0x8B, 0x48, 0x04, 0x68, 0xE0, 0x40, 0x40, 0x00, 0xE8}); Rel(0x5D59F0);
    At(0x641E5F); B({0x8B, 0x48, 0x04, 0x68, 0x50, 0x02, 0x62, 0x00, 0xE8}); Rel(0x5D59F0);
    // ResetCar::SetResetPosition: sub esp, 0x20; mov eax, [esp+0x24]; push esi; then pop esi; add esp, 0x20; jmp
    At(0x6A4340); B({0x83, 0xEC, 0x20, 0x8B, 0x44, 0x24, 0x24, 0x56, 0x5E, 0x83, 0xC4, 0x20});
    Jmp((DWORD)(UINT_PTR)&StSetReset);
    Put(0x8ABA1C, 0x6A4340);
    // the HUD minimap's sites (only checked; EmulateMinimap does what they do)
    At(0x579906); B({0xA1, 0xB8, 0x4F, 0x90, 0x00});
    At(0x579942); B({0x8B, 0x86, 0x98, 0x00, 0x00, 0x00, 0xD8, 0xB0, 0xB4, 0x00, 0x00, 0x00, 0x83, 0xC4, 0x0C, 0xD9, 0x44,
                     0x24, 0x14, 0xD8, 0xA0, 0xAC, 0x00, 0x00, 0x00, 0xD8, 0xC9, 0xD9, 0x80, 0xB0, 0x00, 0x00, 0x00});
    At(0x579AA5); B({0x8B, 0x0D, 0xFC, 0xCE, 0x91, 0x00, 0x50, 0x83, 0xC1, 0x08, 0x51});
    At(0x567510); B({0x8B, 0x44, 0x24, 0x0C, 0x8B, 0x4C, 0x24, 0x04, 0xD9, 0x01, 0x8B, 0x54, 0x24, 0x08, 0xD8, 0xA0, 0xAC,
                     0x00, 0x00, 0x00, 0xD8, 0xB0, 0xB4, 0x00, 0x00, 0x00});
    At(0x567280); B({0x8B, 0x44, 0x24, 0x04, 0x50, 0x83, 0xC1, 0x08, 0x6A, 0x40, 0x51});
    At(0x5673BD); B({0x85, 0xDB, 0x7C, 0x3A, 0x8B, 0x7C, 0x9D, 0x48});
    At(0x5673C5); B({0xB8, 0x01, 0x00, 0x00, 0x00, 0xC3});  // the number was used (RunChop returns 1)
    At(0x5673FB); B({0x31, 0xC0, 0xC3});                    // skipped (RunChop returns 0)
    At(0x722840); B({0x8B, 0x15, 0x18, 0x3A, 0x9A, 0x00, 0x56, 0x33, 0xC9, 0x85, 0xD2, 0x57, 0x7E, 0x27, 0xA1, 0x14, 0x3A,
                     0x9A, 0x00});
    At(0x722860); B({0x0F, 0xBF, 0xB8, 0x8A, 0x00, 0x00, 0x00});
    At(0x72286C); B({0x05, 0x20, 0x01, 0x00, 0x00});
    // vtables: the values the plugins check; the setters are pointed at stand-in functions after the plugins load
    for (DWORD v : {0x8B0B10u, 0x8B0BD0u})
    {
        Put(v + 0x04, 0x6F8FB0);
        Put(v + 0x0C, 0x6F9050);
        Put(v + 0x10, 0x6F9060);
        Put(v + 0x20, 0x6F8F10);  // GetHud
    }
    // the HUD message (R4): LocalPlayer::GetHud (mov eax, [ecx + 0x28]; ret: runs as is), IGenericMessage::_IHandle
    // (mov eax, 0x5650B0; ret: runs as is), HUD_ShowMessage's two steps (only checked), RequestGenericMessage's first
    // bytes then pop edi; pop esi; jmp StRequest; Sim::GetTime (fld [0x9885D8]; ret: runs as is)
    At(0x6F8F10); B({0x8B, 0x41, 0x28, 0xC3});
    At(0x5650B0); B({0xB8, 0xB0, 0x50, 0x56, 0x00, 0xC3});
    At(0x611382); B({0x8B, 0x11, 0xFF, 0x52, 0x20});
    At(0x6113A4); B({0x8B, 0x48, 0x04, 0x68, 0xB0, 0x50, 0x56, 0x00, 0xE8}); Rel(0x5D59F0);
    At(0x568030); B({0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x14, 0x57, 0x8B, 0x7C, 0x24, 0x20, 0x5F, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StRequest);
    Put(0x8A208C, 0x568030);
    At(0x6E8DE0); B({0xD9, 0x05, 0xD8, 0x85, 0x98, 0x00, 0xC3});
    // the race HUD's calls (R14-R16): the game's first bytes at each function, then code of ours
    At(0x6004D0); B({0x51, 0xA1, 0x00, 0xE0, 0x91, 0x00, 0x56, 0x8B, 0xF1, 0x5E, 0x59}); Jmp((DWORD)(UINT_PTR)&StPct);
    At(0x5DDEC0); B({0x56, 0x8B, 0xF1, 0x8A, 0x46, 0x08, 0x84, 0xC0, 0x5E}); Jmp((DWORD)(UINT_PTR)&StGTime);
    At(0x6F1DB0); B({0x8B, 0xCD, 0x89, 0x44, 0x24, 0x40, 0xE8}); Rel(0x6004D0); B({0xC3});
    At(0x6F1DF6); B({0x8D, 0x8D, 0x4C, 0x01, 0x00, 0x00, 0x89, 0x44, 0x24, 0x40, 0xE8}); Rel(0x5DDEC0); B({0xC3});
    At(0x6F216E); B({0x8B, 0xCD, 0xE8}); Rel(0x6EDE30); B({0xC3});
    // Run K item 2: FEngHud::Update's call of DetermineHudFeatures, then a ret of ours; the function's first bytes, then
    // mov ecx, ebx (the HUD); pop edi, esi, ebp, ebx; on to StHudFeatures (thiscall(player), ret 4, edx:eax)
    At(0x58CA4D); B({0x55, 0x8B, 0xF1, 0xE8}); Rel(0x57CA60); B({0xC3});
    At(0x57CA60); B({0x53, 0x55, 0x56, 0x8B, 0xD9, 0x8B, 0x4C, 0x24, 0x10, 0x8B, 0x01, 0x57, 0x8B, 0xCB, 0x5F, 0x5E, 0x5D,
                     0x5B});
    Jmp((DWORD)(UINT_PTR)&StHudFeatures);
    // Run K item 1: Minimap::Update's last call, UpdateGameplayIcons, UpdateElementArt and the FEng calls (the game's
    // first bytes, their stack effects undone, then ours); the safe house's row of the icon table (data)
    if (!g_iconWrong)
    {
        At(0x59DD17); B({0x55, 0x8B, 0xCE, 0xE8}); Rel(0x57A300); B({0xC3});
    }
    else
    {
        At(0x59DD17); B({0x55, 0x8B, 0xCE, 0x90, 0xE8}); Rel(0x57A300); B({0xC3});  // iconwrong: not the game's bytes
    }
    At(0x57A300); B({0x81, 0xEC, 0x6C, 0x03, 0x00, 0x00, 0x53, 0x55, 0x8B, 0xE9, 0x5D, 0x5B, 0x81, 0xC4, 0x6C, 0x03, 0x00,
                     0x00});
    Jmp((DWORD)(UINT_PTR)&StGameplayIcons);
    At(0x57A37F); B({0x8B, 0x6D, 0x10, 0x85, 0x75, 0x40});
    At(0x57A38E); B({0x8B, 0x84, 0x85, 0x18, 0x01, 0x00, 0x00});
    At(0x8F3B58); B({0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x00, 0xEC, 0x01, 0x8A, 0x00});
    Put(0x89096C, 0x3F800000);  // the 1.0 UpdateElementArt's first fld reads
    At(0x5675D0); B({0x83, 0xEC, 0x18, 0xD9, 0x05, 0x6C, 0x09, 0x89, 0x00, 0x56, 0x8B, 0xF1, 0x5E, 0xDD, 0xD8, 0x83, 0xC4,
                     0x18});
    Jmp((DWORD)(UINT_PTR)&StElementArt);
    At(0x567811); B({0x83, 0xC4, 0x18, 0xC2, 0x10, 0x00});
    At(0x514E20); B({0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF0, 0x83, 0xEC, 0x6C, 0x56, 0x8B, 0x75, 0x08, 0x5E, 0x8B, 0xE5, 0x5D});
    Jmp((DWORD)(UINT_PTR)&StSetRotZ);
    At(0x515830); B({0x8B, 0x44, 0x24, 0x08, 0x85, 0xC0, 0x56, 0x74, 0x21, 0x8B, 0x48, 0x2C, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StGetColor);
    At(0x5B2D80); B({0x8B, 0x41, 0x08, 0x85, 0xC0, 0x56, 0x57, 0x5F, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StColorU32);
    At(0x5157E0); B({0x83, 0xEC, 0x10, 0x56, 0x8B, 0x74, 0x24, 0x18, 0x85, 0xF6, 0x5E, 0x83, 0xC4, 0x10});
    Jmp((DWORD)(UINT_PTR)&StSetColor);
    g_gpsImg[0x1C / 4] = 1;
    for (auto& img : g_icoImg) img[0x1C / 4] = 1, img[0x40 / 4] = 0xFFFFFFFF;
    At(0x6EDE30); B({0xA1, 0x00, 0xE0, 0x91, 0x00, 0x83, 0xEC, 0x48, 0x85, 0xC0, 0x56, 0x8B, 0xF1, 0x5E, 0x83, 0xC4, 0x48});
    Jmp((DWORD)(UINT_PTR)&StRadarGame);
    At(0x565A30); B({0xB8, 0x30, 0x5A, 0x56, 0x00, 0xC3});
    At(0x59CDB0); B({0x8B, 0x44, 0x24, 0x08, 0x8B, 0x54, 0x24, 0x0C, 0x89, 0x41, 0x24, 0x8B, 0x44, 0x24, 0x04});
    Jmp((DWORD)(UINT_PTR)&StSetTarget);
    Put(0x8A1F2C + 4, 0x59CDB0);
    // LocalPlayer::GetSettings, run as is (index [this + 0x1C] = 0, the profile at [[0x91CF90] + 0x10] + 0x80)
    At(0x6E99A0); B({0x8B, 0x41, 0x1C, 0x85, 0xC0, 0x7C, 0x14, 0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x51, 0x10, 0x8D,
                     0x04, 0x80, 0x8D, 0x84, 0x82, 0x80, 0x00, 0x00, 0x00, 0xC3, 0x33, 0xC0, 0xC3});
    At(0x68D0C3); B({0x8B, 0x16, 0x8B, 0xCE, 0xFF, 0x52, 0x14, 0x80, 0x78, 0x11, 0x01});
    Put(0x8B0B10 + 0x14, 0x6E99A0), Put(0x8B0BD0 + 0x14, 0x6E99A0);
    for (DWORD v : {0x8A9818u, 0x8AC880u})
    {
        Put(v + 0x20, 0x671180);
        Put(v + 0x2C, 0x6711B0);
        Put(v + 0x34, 0x671270);
        Put(v + 0x38, 0x671220);  // GetRightVector
        Put(v + 0x5C, 0x696FB0);
        Put(v + 0x60, 0x696FD0);
        Put(v + 0x64, 0x696FF0);
        Put(v + 0x70, 0x696D90);
    }
    // the game mode's front end (R5): the game's first bytes at every function FTownLoader calls, then code of ours that
    // undoes their stack effects and jumps to a stand-in function; the checked call sites inside small thunks the
    // stand-in calls; the data sites (only checked) as the game has them
    At(0x7AA810); B({0x8B, 0x4C, 0x24, 0x04, 0x8B, 0x44, 0x24, 0x08, 0x50, 0x90, 0x90, 0x90, 0xE8}); Rel(0x573960);
    B({0xC2, 0x08, 0x00});  // stdcall(menu, option): the AddOption call at 0x7AA81C
    At(0x7BA4D0); B({0x90, 0x90, 0x90, 0x8B, 0x4C, 0x24, 0x04, 0xE8}); Rel(0x7AA900); B({0xC2, 0x04, 0x00});
    At(0x7A2F61); B({0x68}); D(0x1F203817); B({0x68}); D(0xB71B576D); B({0x6A, 0x00, 0xE8}); Rel(0x525220);
    B({0x83, 0xC4, 0x0C, 0xC3});  // RefreshHeader's title call at 0x7A2F6D
    At(0x7A2F20); Jmp(0x7A2F61);
    At(0x7C26DC); B({0x6A, 0x00, 0x6A, 0x00, 0x6A, 0x00, 0x8B, 0x0D, 0xDC, 0xCA, 0x91, 0x00, 0x68, 0x24, 0xFC, 0x89, 0x00,
                     0xE8}); Rel(0x525940); B({0xC3});  // the car select's Back: the call at 0x7C26ED
    strcpy((char*)0x89FC24, "Track_Options.fng");
    At(0x56BB80); B({0x53, 0x8B, 0x1D, 0x80, 0xCF, 0x91, 0x00, 0x5B}); Jmp((DWORD)(UINT_PTR)&StLookup);
    At(0x56BC60); B({0x8B, 0x54, 0x24, 0x04, 0xE8}); Rel(0x56BB80); B({0x85, 0xC0, 0x75, 0x0A, 0xBA}); D(0x9BB9CCC3);
    Jmp(0x56BB80); B({0xC3});  // GetTranslatedString, as the game's
    At(0x586FA0); B({0x8B, 0x54, 0x24, 0x04, 0x8B, 0xC1, 0x53, 0x56, 0x5E, 0x5B}); Jmp((DWORD)(UINT_PTR)&StIconCtor);
    At(0x573960); B({0x8B, 0x41, 0x2C, 0x56, 0x8B, 0x74, 0x24, 0x08, 0x83, 0xC1, 0x2C, 0x56, 0x5E, 0x83, 0xE9, 0x2C, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StAddOption);
    At(0x50E7F0); B({0x8A, 0x91, 0x29, 0x01, 0x00, 0x00, 0x33, 0xC0}); Jmp((DWORD)(UINT_PTR)&StSetInitial);
    At(0x587D30); B({0x8B, 0x44, 0x24, 0x04, 0x3D, 0x9E, 0x40, 0x20, 0x91, 0x56, 0x57, 0x5F, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StScrollerNotify);
    At(0x525940); B({0x83, 0x3D, 0x90, 0x5E, 0x92, 0x00, 0x06, 0x56, 0x57, 0x5F, 0x5E}); Jmp((DWORD)(UINT_PTR)&StSwitch);
    At(0x516C90); B({0x8B, 0x44, 0x24, 0x0C, 0x85, 0xC0}); Jmp((DWORD)(UINT_PTR)&StQueueMessage);
    At(0x525220); Jmp((DWORD)(UINT_PTR)&StSetLangHash);
    At(0x652AD0); Jmp(0x7C66D0);
    At(0x7C66D0); Jmp((DWORD)(UINT_PTR)&StNew);
    At(0x7AA6C0); B({0x81, 0x7C, 0x24, 0x08, 0x10, 0x72, 0x40, 0x0C, 0x75, 0x0A, 0xC7, 0x05, 0x68, 0x9E, 0x9B, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0xC2, 0x14, 0x00});  // QuickPlay::React (QRMode 0)
    At(0x7AA710); B({0x81, 0x7C, 0x24, 0x08, 0x10, 0x72, 0x40, 0x0C, 0x75, 0x0A, 0xC7, 0x05, 0x68, 0x9E, 0x9B, 0x00, 0x01, 0x00,
                     0x00, 0x00, 0xC2, 0x14, 0x00});  // CustomRace::React (QRMode 1)
    At(0x7B4980); B({0x56, 0x8B, 0xF1, 0xE8, 0x18, 0x00, 0x00, 0x00});
    At(0x7AA8B0); B({0xC2, 0x14, 0x00});  // MSOption::React (the race kind: not needed here)
    At(0x7AA900); Jmp((DWORD)(UINT_PTR)&StModeSetupGame);
    At(0x7A2F80); Jmp((DWORD)(UINT_PTR)&StModeNotifyGame);
    At(0x7A2E71); B({0xA1, 0x90, 0xCF, 0x91, 0x00});
    At(0x7A2EA7); B({0xA1, 0x90, 0xCF, 0x91, 0x00, 0x81, 0x88, 0x2C, 0x01, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00});
    At(0x7A2EC0); B({0x8B, 0x0D, 0xDC, 0xCA, 0x91, 0x00});
    At(0x7AA8DA); B({0x8B, 0x46, 0x4C, 0x89, 0x42, 0x18});
    At(0x7A2F9F); B({0x81, 0xFE, 0x64, 0xB3, 0x1A, 0x91});
    At(0x7A2FAB); B({0x81, 0xFE, 0xD1, 0xE1, 0xFD, 0xE1});
    At(0x7A2FB7); B({0x8B, 0xBF, 0x38, 0x01, 0x00, 0x00, 0x81, 0xFF, 0x10, 0x72, 0x40, 0x0C});
    At(0x7A2FDA); B({0x81, 0xA0, 0x2C, 0x01, 0x00, 0x00, 0xFF, 0xFB, 0xFF, 0xFF});
    At(0x7AB4AC); B({0x8B, 0x86, 0x28, 0x01, 0x00, 0x00, 0x8B, 0x0D, 0x04, 0xE0, 0x91, 0x00, 0x50, 0xE8}); Rel(0x603440);
    B({0x8B, 0xF8, 0x6A, 0x00, 0x8B, 0xCF, 0xE8}); Rel(0x5E9B80);
    B({0x8B, 0x8E, 0x28, 0x01, 0x00, 0x00, 0xE8}); Rel(0x5FAA20);
    B({0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x50, 0xE8}); Rel(0x56DBE0);
    B({0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x50, 0x57, 0xE8}); Rel(0x56DD20);
    B({0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0xE8}); Rel(0x469120);
    B({0x84, 0xC0, 0x74, 0x09, 0x6A, 0x01, 0x8B, 0xCF, 0xE8}); Rel(0x5DCE60);
    B({0x8B, 0x0D, 0x04, 0xE0, 0x91, 0x00, 0x6A, 0x00, 0x57, 0xE8}); Rel(0x600AB0);
    B({0x8B, 0x0D, 0x04, 0xE0, 0x91, 0x00, 0x57, 0xE8}); Rel(0x5E39E0);
    At(0x50DF70); B({0x8B, 0x44, 0x24, 0x04, 0x56, 0x50, 0x8B, 0xF1, 0x58, 0x5E}); Jmp((DWORD)(UINT_PTR)&StRaceFromName);
    At(0x5DC9D0); B({0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x2C, 0x5E, 0x5B}); Jmp((DWORD)(UINT_PTR)&StClearStartup);
    At(0x5FAA20); Jmp((DWORD)(UINT_PTR)&StRaceType);
    At(0x603440); Jmp((DWORD)(UINT_PTR)&StAlloc);
    At(0x56DD20); Jmp((DWORD)(UINT_PTR)&StFill);
    At(0x600AB0); Jmp((DWORD)(UINT_PTR)&StSetStartup);
    At(0x5E39E0); Jmp((DWORD)(UINT_PTR)&StFree);
    At(0x7AAC43); B({0x8B, 0x47, 0x10, 0x8B, 0x0D, 0xDC, 0xCA, 0x91, 0x00, 0x6A, 0x00, 0x50, 0x68, 0x23, 0x83, 0x82, 0x21,
                     0xE8}); Rel(0x516C90);
    At(0x4B4380); B({0xB8, 0x80, 0x43, 0x4B, 0x00, 0xC3});
    At(0x567F30); B({0x8B, 0x41, 0x14, 0x85, 0xC0, 0x0F, 0x9F, 0xC0, 0xC3});
    Put(0x8B7588, 0x7B4950), Put(0x8B758C, 0x7AA6C0), Put(0x8B7590, 0x7B4980), Put(0x8B7594, 0x7AA710);
    Put(0x8B75B4, 0x7AA8B0);
    Put(0x8B7E18, 0x7BA500), Put(0x8B7E1C, 0x7A2F80), Put(0x8B7E20, 0x573810), Put(0x8B7E24, 0x7A2F20);
    Put(0x8B7E28, 0x7AA900);
    Put(0x8A2070, 0x59DE20), Put(0x8A2074, 0x567F10), Put(0x8A2078, 0x567F30), Put(0x8A207C, 0x567F40);
    // Run J item 1: NISActivity::StartLocation (its first 10 bytes, then pop edi; pop esi; jmp StNisStart), VU0_Atan2
    // (push ecx; fld [esp+0xC]; then fstp st0; pop ecx; jmp), PrepareForRace (its first 9 bytes, then mov ecx, ebx;
    // pop ebx; jmp), the two calls (only checked), the slots
    At(0x6EA330); B({0x8B, 0x44, 0x24, 0x04, 0x56, 0x8B, 0xF0, 0x57, 0x8B, 0x3E, 0x5F, 0x5E});
    Jmp((DWORD)(UINT_PTR)&StNisStart);
    At(0x5CB5D0); B({0x51, 0xD9, 0x44, 0x24, 0x0C, 0xDD, 0xD8, 0x59}); Jmp((DWORD)(UINT_PTR)&StAtan2);
    At(0x4169B0); B({0x53, 0x8B, 0xD9, 0x8B, 0x8B, 0xF4, 0xF8, 0xFF, 0xFF, 0x8B, 0xCB, 0x5B});
    Jmp((DWORD)(UINT_PTR)&StPrepare);
    At(0x5E9793); B({0x8B, 0x10, 0x51, 0x8B, 0xC8, 0xC7, 0x44, 0x24, 0x28, 0x01, 0x00, 0x00, 0x00, 0xFF, 0x52, 0x04});
    At(0x640FBC); B({0x39, 0x2D, 0xC8, 0x85, 0x98, 0x00});
    // Run J item 7: GetTextureInfo (its first 8 bytes, then pop edi; pop esi; pop ebp; pop ebx; jmp StGetTI), its hash
    // compare (only checked), LockImage / UnlockImage (only checked), bStringHash (its first 6 bytes, then jmp)
    At(0x503400); B({0x53, 0x55, 0x56, 0x57, 0x8B, 0x7C, 0x24, 0x14, 0x5F, 0x5E, 0x5D, 0x5B}); Jmp((DWORD)(UINT_PTR)&StGetTI);
    At(0x503422); B({0x39, 0x78, 0x24});
    At(0x6BED80); B({0x8B, 0x09, 0x8B, 0x41, 0x18, 0x8B, 0x08, 0x83, 0xEC, 0x08, 0x6A, 0x00, 0x6A, 0x00, 0x8D, 0x54, 0x24,
                     0x08, 0x52, 0x6A, 0x00, 0x50, 0xFF});
    At(0x6BEDB0); B({0x8B, 0x09, 0x8B, 0x41, 0x18, 0x8B, 0x08, 0x6A, 0x00, 0x50, 0xFF, 0x51, 0x50});
    At(0x460BF0); B({0x8B, 0x54, 0x24, 0x04, 0x8A, 0x0A}); Jmp((DWORD)(UINT_PTR)&StBHash);
    At(0x641480); B({0x8B, 0x44, 0x24, 0x10, 0x8B, 0x16, 0x50, 0x8D, 0x4C, 0x24, 0x20, 0x51, 0x8B, 0xCE, 0xFF, 0x52,
                     0x0C});
    // after the call: ret (to the stand-in); the thunk: push dir; push pos (cdecl args); ecx = the NIS; edx = its
    // vtable; on at the game's call [edx + 0x0C] (0x64148E)
    At(0x641491); B({0xC3});
    At(0x641600); B({0xFF, 0x74, 0x24, 0x08, 0xFF, 0x74, 0x24, 0x08, 0xB9}); D((DWORD)(UINT_PTR)g_nisObj);
    B({0x8B, 0x11}); Jmp(0x64148E);
    Put(0x8B0D84, 0x6EA330), Put(0x8925B8, 0x4169B0), Put(0x892968, 0x4169B0);
    // Run J item 4: AIVehicleHuman::IsDragSteering (its first 7 bytes, then pop edi; pop esi; mov al, 1; ret: the
    // game's AI steering in a drag at speed), the drag block of AIVehicleHuman::Update (its 24 bytes up to the call,
    // only the call run: the thunk at 0x42F600 jumps to 0x42F49F; after the call 0x42F4A4 jumps to code that returns 1
    // "ai" (DoSteering) or 2 "lane" (DetermineDragLane); the join at 0x42F4D4 returns 3 "skipped"); the two jumps to
    // the join as the game has them (only checked); ChangeDragLanes' call (only checked)
    At(0x407FF0); B({0x56, 0x57, 0x8B, 0xF9, 0x8B, 0x47, 0x4C, 0x5F, 0x5E, 0xB0, 0x01, 0xC3});
    At(0x42F48C); B({0x83, 0xF8, 0x01, 0x75, 0x39, 0x8B, 0x4C, 0x24, 0x18, 0xC7, 0x87, 0x80, 0x00, 0x00, 0x00, 0x02, 0x00,
                     0x00, 0x00, 0xE8}); Rel(0x407FF0);
    Jmp(0x42F700);
    At(0x42F4BD); B({0xEB, 0x15});
    At(0x42F4C8); B({0xEB, 0x0A});
    At(0x42F4D4); B({0xB8, 0x03, 0x00, 0x00, 0x00, 0xC3});
    At(0x42F600); B({0xB9}); D((DWORD)(UINT_PTR)g_racerObj); Jmp(0x42F49F);
    At(0x42F700); B({0x84, 0xC0, 0x74, 0x06, 0xB8, 0x01, 0x00, 0x00, 0x00, 0xC3, 0xB8, 0x02, 0x00, 0x00, 0x00, 0xC3});
    At(0x408060); B({0x56, 0x8B, 0xF1, 0x8D, 0x8E, 0x34, 0xF8, 0xFF, 0xFF, 0xE8}); Rel(0x407FF0);
    if (menuWrong)
        *(BYTE*)0x7C26E8 = 0x90;
    if (menuWrongLong)  // the last byte of the 63-byte site (review: the WRONGBYTES line's hex of a long site)
        *(BYTE*)(0x7AB4E0 + 62) = 0x90;
    g_countdown[5] = (DWORD)-1;
    Put(0x91CF90, (DWORD)(UINT_PTR)g_fedb);
    g_fedb[0x10 / 4] = (DWORD)(UINT_PTR)g_profile;  // the player's settings at +0x80 (LocalPlayer::GetSettings)
    Put(0x91CADC, (DWORD)(UINT_PTR)g_feObj);
    Put(0x91E004, (DWORD)(UINT_PTR)g_raceDb);
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);

    // data: the player, the grid, the tables
    g_player.vtbl = 0x8B0B10;
    static DWORD array[1] = {(DWORD)(UINT_PTR)&g_player.vtbl};
    Put(0x92D884, 1);
    Put(0x92D87C, (DWORD)(UINT_PTR)array);
    g_sim[0] = (DWORD)(UINT_PTR)g_simVtbl;
    g_simVtbl[0x54 / 4] = (DWORD)(UINT_PTR)&GetRigidBody;
    g_sim[1] = (DWORD)(UINT_PTR)g_iList;  // ISimable +4: its COM object's interface list
    g_iList[1] = (DWORD)(UINT_PTR)g_iList;
    g_hudList[1] = (DWORD)(UINT_PTR)g_hudList;
    g_hud[1] = (DWORD)(UINT_PTR)g_hudList;
    g_player.more[9] = (DWORD)(UINT_PTR)g_hud;
    if (!nosim)
        Put(0x9885E0, 0x12345678);  // Sim::Internal::mSystem
    if (zoneoff)
        *(BYTE*)0x9AAC81 = 1;
    g_rb[0] = 0x8AC880;  // the player car's body is an RBVehicle, as in the game
    g_rb[0x30 / 4] = (DWORD)(UINT_PTR)&g_rbDataPtr;
    g_rb[0xBC / 4] = 0;  // the player's collision mask (DRIVER_HUMAN: 0)
    g_grid.min[0] = -4800.0f, g_grid.min[2] = -1664.0f, g_grid.min[3] = 1.0f;
    g_grid.edge = 64.0f, g_grid.invEdge = 1.0f / 64.0f;
    g_grid.rows = 103, g_grid.cols = 92;
    g_grid.nodes = (DWORD*)calloc(103 * 92, 4);
    g_rockNode.index = 10 * 92 + 10;
    g_rockNode.counts[0] = 1;
    g_rockNode.tags[0] = (309u << 16) | 3;
    g_grid.nodes[g_rockNode.index] = (DWORD)(UINT_PTR)&g_rockNode;
    if (g_existing)
    {
        g_existNode.index = 56 * 92;
        g_existNode.counts[0] = 1;
        g_existNode.tags[0] = (309u << 16) | 7;
        g_grid.nodes[g_existNode.index] = (DWORD)(UINT_PTR)&g_existNode;
        StAddDynamic(&g_existNode, nullptr, 0xABCD, 1);  // a trigger of "Rockport" already in the cell
    }
    Put(0x9B38A8, (DWORD)(UINT_PTR)&g_grid);
    Put(0x9B38A0, (DWORD)(UINT_PTR)g_packList);
    Put(0x9B3890, (DWORD)(UINT_PTR)g_assets);
    Put(0x9B3C84, (DWORD)(UINT_PTR)g_colliderList);
    Put(0x9B3C8C, 1);
    if (taken)
    {
        static DWORD header[16];
        g_userInfo[64][0] = 1;
        g_userInfo[64][1] = (DWORD)(UINT_PTR)header;
        Put(0x9A3BB0 + 4 * (g_takenNumber > 0 ? g_takenNumber : 2101), (DWORD)(UINT_PTR)g_userInfo[64]);
    }
    float mph = 60.0f;
    memcpy((void*)0x914654, &mph, 4);
    // the minimap's data: three TrackInfo records (the quick race's track 2000 with Rockport's calibration from
    // GLOBALB.BUN), the race's track number, the chopped-map manager with the race's map header
    short numbers[3] = {1001, 2000, 2200};
    float calib[3][3] = {{0, 0, 1000}, {-1224.9f, -1591.1f, 6659.3f}, {-1650.9f, -1294.3f, 6727.2f}};
    for (int k = 0; k < 3; k++)
    {
        memcpy(g_trackInfos[k] + 0x8A, &numbers[k], 2);
        memcpy(g_trackInfos[k] + 0xAC, calib[k], 12);
    }
    Put(0x9A3A14, (DWORD)(UINT_PTR)g_trackInfos);
    Put(0x9A3A18, 3);
    Put(0x904FB8, 2000);
    strcpy((char*)g_mmManager + 8, kRockHeader);
    Put(0x91CEFC, (DWORD)(UINT_PTR)g_mmManager);
    GridSnapshot("BEFORE");

    HMODULE wpBefore = nullptr, ft = nullptr, wpAfter = nullptr;
    if (wp && !strcmp(wp, "before"))
        wpBefore = LoadLibraryA("WorldProbe.asi");
    ft = LoadLibraryA("FTownLoader.asi");
    if (wp && !strcmp(wp, "after"))
        wpAfter = LoadLibraryA("WorldProbe.asi");
    printf("plugin=%s worldprobe=%s\n", ft ? "loaded" : "missing", (wpBefore || wpAfter) ? "loaded" : "no");
    BYTE now[5];
    memcpy(now, (void*)0x663D30, 5);
    printf("HOOK %s\n", (now[0] == 0xE8 && *(DWORD*)(now + 1) == 0x45CE40 - (0x663D30 + 5)) ? "untouched" : "patched");
    memcpy(now, (void*)0x663D35, 5);
    printf("WPHOOK %s\n", (now[0] == 0xE8 && *(DWORD*)(now + 1) == 0x667650 - (0x663D35 + 5)) ? "untouched" : "patched");
    printf("UNLOADHOOK %s\n", *(BYTE*)0x6617E0 == 0x53 ? "untouched" : "patched");
    for (DWORD v : {0x8A9818u, 0x8AC880u})
    {
        Put(v + 0x34, (DWORD)(UINT_PTR)&GetForward);
        Put(v + 0x38, (DWORD)(UINT_PTR)&GetRight);
        Put(v + 0x2C, (DWORD)(UINT_PTR)&StGetSpeed);
        Put(v + 0x60, (DWORD)(UINT_PTR)&SetLinear);
        Put(v + 0x64, (DWORD)(UINT_PTR)&SetAngular);
        Put(v + 0x70, (DWORD)(UINT_PTR)&SetOrientMatrix);
    }
    for (g_frame = 0; g_frame < frames; g_frame++)
    {
        // the front end (fe=...): one action a frame from frame 1, no player until the race starts
        if (g_feOn && !g_raceStarted && g_frame >= 1)
        {
            FeAction(g_feAt < g_feActCount ? g_feActs[g_feAt] : nullptr);
            g_feAt++;
        }
        if (!g_feOn || g_raceStarted)
            CountdownStep();
        NisStep();
        if (g_dragSteer)  // Run J item 4: the player's AI update (its drag block) once a frame
        {
            static int last = -1;
            int r = ((int(__cdecl*)())0x42F600)();
            if (r != last)
                printf("DRAGSTEER f=%d %s\n", g_frame, r == 1 ? "ai" : r == 2 ? "lane" : r == 3 ? "skipped" : "?");
            last = r;
        }
        bool inFrontEnd = g_feOn && !g_raceStarted;
        Put(0x92D884, (inFrontEnd || (g_frame >= g_goneA && g_frame <= g_goneB)) ? 0 : 1);
        if (g_frame == deleteFrame || g_frame == changeFrame)  // the map file on disk gone or grown after startup
        {
            WIN32_FIND_DATAA fd;
            HANDLE h = FindFirstFileA("*.bun", &fd);
            while (h != INVALID_HANDLE_VALUE)
            {
                if (g_frame == deleteFrame)
                    DeleteFileA(fd.cFileName);
                else
                {
                    FILE* f = fopen(fd.cFileName, "ab");
                    fputc(0, f);
                    fclose(f);
                }
                if (!FindNextFileA(h, &fd))
                    break;
            }
            FindClose(h);
            printf("MAP FILES %s\n", g_frame == deleteFrame ? "DELETED" : "CHANGED");
        }
        if (g_frame == g_trackUnloadFrame)
            ((void(__thiscall*)(void*))0x6617E0)((void*)0x8F834C);
        if (g_frame == g_foreignFrame)  // something else (a trigger) joins one of the plugin's nodes in column 0
            for (DWORD row = 50; row < 63; row++)
            {
                Node* n = (Node*)(UINT_PTR)g_grid.nodes[row * g_grid.cols];
                if (n && n != &g_existNode)
                {
                    printf("FOREIGN cell %lu\n", (unsigned long)(row * g_grid.cols));
                    StAddDynamic(n, nullptr, 0xBEEF, 1);
                    break;
                }
            }
        for (int d = 0; d < g_driveCount; d++)
            if (g_drives[d].frame == g_frame)
            {
                g_pos[0] = -g_drives[d].y;
                g_pos[2] = g_drives[d].x;
                printf("DRIVE to render %.1f %.1f\n", g_drives[d].x, g_drives[d].y);
            }
        bool paused = g_frame >= g_pauseA && g_frame <= g_pauseB;
        if (!paused)
        {
            g_simTime += 1.0f / 30.0f;
            RouteStep();
        }
        memcpy((void*)0x9885D8, &g_simTime, 4);
        if (g_frame >= g_gridA && g_frame <= g_gridB)  // gridhold: the game keeps the car on its Rockport grid
        {
            g_pos[0] = -2400.0f, g_pos[1] = 113.0f, g_pos[2] = 1700.0f;
            printf("GAME HOLDS THE CAR ON ITS GRID\n");
        }
        if (g_frame == g_todSetFrame)
        {
            g_tod[2] = 0.5f;
            printf("TODSET 0.500 (a race start)\n");
        }
        if (g_frame == simAt)
        {
            Put(0x9885E0, 0x12345678);
            printf("SIMULATION EXISTS\n");
        }
        if (smkLive && g_frame == smkLiveUntil)
        {
            Put(0x92617C, Get(0x92617C) - (DWORD)smkLive);
            printf("ROCKPORT SPAWNERS GONE\n");
        }
        LinkGlide();
        if (g_link && g_frame == g_racingAt)
        {
            *(DWORD*)(UINT_PTR)(0x00ACE000 + 0x1960) = 1;
            printf("RACE STARTS (play mode racing)\n");
        }
        if (g_link && g_frame == g_roamingAt)
        {
            *(DWORD*)(UINT_PTR)(0x00ACE000 + 0x1960) = 0;
            printf("FREE ROAM AGAIN (play mode roaming)\n");
        }
        if (g_hudFrom >= 0)  // Run K item 5: no HUD before frame hudfrom
            g_player.more[9] = g_frame >= g_hudFrom ? (DWORD)(UINT_PTR)g_hud : 0;
        ((void(__cdecl*)())0x663D30)();
        LinkFrameStandin();
        SmkFrame();
        NetFrame();
        TodStep();
        // review: the game itself can move the car within a loop, after the plugin's hook and before the HUD (a reset,
        // a pause-menu restart): jump=<frame>:<x>,<y> does that
        for (int d = 0; d < g_jumpCount; d++)
            if (g_jumps[d].frame == g_frame)
            {
                g_pos[0] = -g_jumps[d].y;
                g_pos[2] = g_jumps[d].x;
                g_routeOn = -1;  // the drive along the route ends there
                printf("GAME MOVED THE CAR to render %.1f %.1f (after the hook)\n", g_jumps[d].x, g_jumps[d].y);
            }
        if (g_frame == g_gmGameFrame)  // the game's own message (a race-over line, priority 5)
            ((bool(__thiscall*)(void*, const char*, bool, DWORD, DWORD, DWORD, int))0x568030)(
                g_gm, "GAME MESSAGE", false, 0x8AB83EDB, 0, 0, 5);
        EmulateMinimap();  // the HUD runs after MainLoop's first calls
        if (Get(0x92D884))
            RaceHud();
        GmUpdate();
        VehiclesEndFrame();
        if (g_frame % 10 == 0 && g_texMade)  // Run J item 7: the course line in our minimap's textures
        {
            static int last = -1;
            int y = CountYellow();
            if (y != last)
                printf("COURSE f=%d yellow %d\n", g_frame, y);
            last = y;
        }
        for (int k = 0; k < g_ldCount; k++)
            if (g_lds[k].unloaded && !g_lds[k].freed)
            {
                MEMORY_BASIC_INFORMATION mi;
                VirtualQuery(g_lds[k].buf, &mi, sizeof(mi));
                if (mi.State == MEM_FREE || mi.State == MEM_RESERVE)
                {
                    printf("BUFFER FREED%s\n", g_lds[k].bar ? " FTOWNBAR" : "");
                    g_lds[k].freed = true;
                }
            }
        Sleep(2);
    }
    GridSnapshot("AFTER");
    NetReport();
    SmkReport();
    LinkReport();
    printf("HUDMSG FRAMES %d\n", g_msgFrames);
    printf("HUDMSG POPS %d\n", g_gmStarts);
    for (DWORD a = 0; a < g_grid.rows * g_grid.cols; a++)
        for (DWORD b = a + 1; g_grid.nodes[a] && b < g_grid.rows * g_grid.cols; b++)
            if (g_grid.nodes[a] == g_grid.nodes[b])
                printf("DUPLICATE NODE in cells %lu and %lu\n", (unsigned long)a, (unsigned long)b);
    printf("LOADS %d UNLOADS %d LISTS %d ELEMS %d\n", g_loads, g_unloads, g_lists, g_elems);
    printf("BARLOADS %d BARUNLOADS %d\n", g_barLoads, g_barUnloads);
    printf("ZONEBYTE %d\n", *(BYTE*)0x9AAC81);
    printf("COURSE ORIGINAL %s LOCKS %d%s\n", TexturesOriginal() ? "yes" : "no", g_texLocks,
           g_lockAfter ? " LOCKED AFTER UNLOAD" : "");
    int alive = 0;
    for (int k = 0; k < g_vehCount; k++) alive += !g_veh[k].dead;
    printf("VEHICLES made %d alive %d list %d refused %d\n", g_vehCount, alive, VSize(), g_vehRefused);
    return 0;
}
