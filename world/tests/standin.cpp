// Stand-in for speed.exe to test WorldProbe.asi. Linked at image base 0x400000 without relocation, so a large static
// array covers the game's addresses; code and tables shaped like the game's are put there:
//  - 0x663D30: a "MainLoop" whose call at 0x663D35 goes to 0x667650 (ret), run once per frame;
//  - 0x47EF0A / 0x47EF12: the player-list instructions of ICEGetPlayerCarTransform (bytes only);
//  - the player list (0x92D884 count, 0x92D87C array) with one LocalPlayer whose vtable 0x8B0B10 has the game's slot
//    values; the slots' thunks (0x6F8FB0, 0x6F9050, 0x6F9060) are the game's bytes and lead to stand-in functions;
//  - a RigidBody vtable at 0x8A9818 with the game's slot values, leading to stand-in velocity setters;
//  - GetWorldHeightAtPoint 0x7897C0 and FindDrivableSection 0x72CA00: the game's first bytes, then code that undoes
//    them and jumps to stand-in functions;
//  - speed (0x914654), the telemetry position (0x9386D8), the scenery list (0x9AA478), the collision pack list
//    (0x9B38A0).
// Arguments: frames=<n> (default 40), key (WorldProbeTestKey reports the key down on frames 10 and 11),
// wrongbytes (GetWorldHeightAtPoint's first byte differs).
// Output: HOOK patched|untouched; TELEPORT x y z (physics, as SetPosition received it); VELOCITY ...; HEIGHTCALLS n.
#include <windows.h>
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

static int g_frame, g_keyFrames, g_background;
static int g_heightCalls, g_findCalls;

static int g_aboveKey;  // "abovekey": F10 (0x79) down on frames 10 and 11 instead of F9

extern "C" __declspec(dllexport) int __cdecl WorldProbeTestKey(int vk)
{
    return ((g_keyFrames && vk == 0x78) || (g_aboveKey && vk == 0x79)) && (g_frame == 10 || g_frame == 11);
}

// 1 = the game window is in front (the plugin teleports only then); "background" makes it 0
extern "C" __declspec(dllexport) int __cdecl WorldProbeTestForeground() { return !g_background; }

// The objects. LocalPlayer: 0x20 bytes, then the IPlayer part (vtable 0x8B0B10), as the game's thunks subtract 0x20.
struct Player
{
    DWORD pad[8];
    DWORD vtbl;
    DWORD more[8];
};
static Player g_player;
// The rigid body's data block, as the game's RigidBody::SetPosition (0x696FB0) reaches it: body +0x30 -> pointer ->
// block, position at +0x10. GetPosition reads it there, so the game's own setter (copied below) moves the car.
static float g_rbData[16] = {0, 0, 0, 0, -2400.0f, 113.0f, 1700.0f};  // physics; render (1700, 2400, 113)
static float* const g_pos = g_rbData + 4;
static float* g_rbDataPtr = g_rbData;
static DWORD g_simVtbl[32], g_sim[64], g_rb[16];
static DWORD g_resetCar[0x60 / 4];  // ResetCar: owner ISimable at +0x34, the IResetable part at +0x4C
static DWORD g_drivable[8];
static DWORD g_scenery[2][4];
static DWORD g_packs[2700];

static const float* __fastcall GetPosition(Player*, void*) { return g_pos; }
static bool __fastcall SetPosition(Player*, void*, const float* p)
{
    printf("TELEPORT %.3f %.3f %.3f\n", p[0], p[1], p[2]);
    // as the game's LocalPlayer::SetPosition 0x6F9020: through the body's IRigidBody +0x5C = RigidBody::SetPosition
    ((void(__thiscall*)(void*, const float*))0x696FB0)(g_rb, p);
    return true;
}

// The reset path, chained as in the game: ResetVehicle -> ResetTo -> SetVehicleOnGround -> RigidBody::SetPosition.
// Each stand-in function prints ORIGINAL so a test sees that the game's function still ran behind a watch.
static const float g_cookie[3] = {-2400.0f, 113.0f, 1650.0f}, g_dir[3] = {0, 0, 1};  // 50 m back along physics z
static float g_otherData[16];  // another car's body (othercalls): its own data block
static float* g_otherDataPtr = g_otherData;
static DWORD g_otherRb[16] = {0x8AC880, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (DWORD)(UINT_PTR)&g_otherDataPtr};
static bool __fastcall StOnGround(void* vehicle, void*, const float* pos, const float* dir)
{
    printf("ORIGINAL SetVehicleOnGround %.1f %.1f %.1f\n", pos[0], pos[1], pos[2]);
    bool mine = vehicle == (BYTE*)g_sim + 0x80;
    ((void(__thiscall*)(void*, const float*))0x696FB0)(mine ? (void*)g_rb : (void*)g_otherRb, pos);
    return vehicle == (BYTE*)g_sim + 0x80;
}
static bool __fastcall StResetTo(DWORD* resetCar, void*, const float* pos, const float* dir, int manual)
{
    printf("ORIGINAL ResetTo manual %d\n", manual & 0xFF);
    return ((bool(__thiscall*)(void*, const float*, const float*))0x685810)((BYTE*)resetCar[0x34 / 4] + 0x80, pos, dir);
}
static bool __fastcall StResetVehicle(BYTE* resetable, void*, int manual)
{
    printf("ORIGINAL ResetVehicle manual %d\n", manual & 0xFF);
    return ((bool(__thiscall*)(void*, const float*, const float*, int))0x6A45F0)(resetable - 0x4C, g_cookie, g_dir,
                                                                               manual & 0xFF);
}
static void* __fastcall GetSimable(Player*, void*) { return g_sim; }
static void* __fastcall GetRigidBody(void*, void*) { return g_rb; }
static void __fastcall SetLinear(void*, void*, const float* v) { printf("VELOCITY %.1f %.1f %.1f\n", v[0], v[1], v[2]); }
static void __fastcall SetAngular(void*, void*, const float* v) { printf("SPIN %.1f %.1f %.1f\n", v[0], v[1], v[2]); }
static bool __fastcall Height(DWORD* mgr, void*, const float* pt, float* h, float* normal)
{
    g_heightCalls++;
    if (mgr[0] != 0 || mgr[1] != 3)
        printf("HEIGHT bad manager %lu %lu\n", (unsigned long)mgr[0], (unsigned long)mgr[1]);
    if (pt[2] > 5000.0f || pt[0] < -5000.0f)
        return false;  // "outside Rockport": no face
    *h = 112.5f;
    normal[0] = 0, normal[1] = 1, normal[2] = 0;
    return true;
}
static void* __fastcall FindDrivable(void* mgr, void*, const float* v2)
{
    g_findCalls++;
    if ((DWORD)(UINT_PTR)mgr != 0x9A3B50)
        printf("FINDDRIVABLE bad this\n");
    return v2[1] < 5000.0f ? g_drivable : nullptr;
}

// gridhold: the start grid holding the car (runs E, F: RigidBody::SetPosition from 0x6912BA and 0x6A7768 in the
// countdown), from two call sites of ours, each a return address of its own
__attribute__((noinline)) static void HoldA(const float* p) { ((void(__thiscall*)(void*, const float*))0x696FB0)(g_rb, p); }
__attribute__((noinline)) static void HoldB(const float* p) { ((void(__thiscall*)(void*, const float*))0x696FB0)(g_rb, p); }

int main(int argc, char** argv)
{
    int frames = 40;
    bool wrong = false, wrongData = false, wrongSlot = false, badPtr = false, rbVehicle = false, wrongRb = false,
         jump = false, drop = false, resetCall = false, wrongReset = false, otherCalls = false, gridHold = false;
    int resetAt = 20;
    for (int i = 1; i < argc; i++)
    {
        if (!strncmp(argv[i], "frames=", 7)) frames = atoi(argv[i] + 7);
        else if (!strcmp(argv[i], "key")) g_keyFrames = 1;
        else if (!strcmp(argv[i], "wrongbytes")) wrong = true;
        else if (!strcmp(argv[i], "wrongdata")) wrongData = true;      // the instruction tying 0x9AA478 differs
        else if (!strcmp(argv[i], "wrongslot")) wrongSlot = true;      // a vtable slot holds another value
        else if (!strcmp(argv[i], "background")) g_background = 1;
        else if (!strcmp(argv[i], "badptr")) badPtr = true;            // the player array points at no memory
        else if (!strcmp(argv[i], "abovekey")) g_aboveKey = 1;
        else if (!strcmp(argv[i], "rbvehicle")) rbVehicle = true;      // the body is an RBVehicle, as in the game
        else if (!strcmp(argv[i], "wrongrb")) wrongRb = true;          // RBVehicle's +0x60 slot holds another value
        else if (!strcmp(argv[i], "jump")) jump = true;                // the car moves 100 m at frame 25 by itself
        else if (!strcmp(argv[i], "drop")) drop = true;                // frames 30-49: the car falls 0.2 m a frame
        else if (!strcmp(argv[i], "resetcall")) resetCall = true;      // the "game" resets the car (frames 2, 20)
        else if (!strcmp(argv[i], "wrongreset")) wrongReset = true;    // ResetTo's second byte differs
        else if (!strcmp(argv[i], "othercalls")) otherCalls = true;    // 300 resets of another car at frame 6
        else if (!strcmp(argv[i], "gridhold")) gridHold = true;        // frames 6-8: 2 x 50 SetPosition calls each
        else if (!strncmp(argv[i], "resetat=", 8)) resetAt = atoi(argv[i] + 8);  // the player's reset frame
    }
    Reserve(0x47E000, 0x1000);
    Reserve(0x663000, 0x5000);
    Reserve(0x6F8000, 0x2000);
    Reserve(0x72C000, 0x1000);
    Reserve(0x731000, 0x1000);
    Reserve(0x772000, 0x1000);
    Reserve(0x695000, 0x1000);
    Reserve(0x789000, 0x1000);
    Reserve(0x8A9000, 0x1000);
    Reserve(0x8B0000, 0x1000);
    Reserve(0x8AC000, 0x1000);
    Reserve(0x6B0000, 0x1000);
    Reserve(0x6A4000, 0x1000);
    Reserve(0x685000, 0x2000);
    Reserve(0x696000, 0x1000);
    Reserve(0x8AA000, 0x1000);
    Reserve(0x8AB000, 0x1000);
    Reserve(0x914000, 0x1000);
    Reserve(0x92D000, 0x1000);
    Reserve(0x938000, 0x1000);
    Reserve(0x9AA000, 0x1000);
    Reserve(0x9B3000, 0x1000);
    memset((void*)0x914000, 0, 0x1000);
    memset((void*)0x92D000, 0, 0x1000);
    memset((void*)0x938000, 0, 0x1000);
    memset((void*)0x9AA000, 0, 0x1000);
    memset((void*)0x9B3000, 0, 0x1000);

    // MainLoop: 5 nops, call 0x667650 at 0x663D35, ret; MainLoopBreakpoint: ret
    At(0x663D30); B({0x90, 0x90, 0x90, 0x90, 0x90, 0xE8}); Rel(0x667650); B({0xC3});
    At(0x667650); B({0xC3});
    At(0x47EF0A); B({0x39, 0x1D, 0x84, 0xD8, 0x92, 0x00});
    At(0x47EF12); B({0xA1, 0x7C, 0xD8, 0x92, 0x00});
    // LocalPlayer thunks (the game's bytes) and their targets
    At(0x6F8FB0); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F8F30);
    At(0x6F9050); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F9000);
    At(0x6F9060); B({0x83, 0xE9, 0x20, 0xE9}); Rel(0x6F9020);
    At(0x6F8F30); Jmp((DWORD)(UINT_PTR)&GetSimable);
    At(0x6F9000); Jmp((DWORD)(UINT_PTR)&GetPosition);
    At(0x6F9020); B({0x8B, 0x41, 0x18, 0x85, 0xC0}); Jmp((DWORD)(UINT_PTR)&SetPosition);
    // vtables
    Put(0x8B0B10 + 0x04, 0x6F8FB0);
    Put(0x8B0B10 + 0x0C, 0x6F9050);
    Put(0x8B0B10 + 0x10, 0x6F9060);
    Put(0x8B0BD0 + 0x04, 0x6F8FB0);
    Put(0x8B0BD0 + 0x0C, 0x6F9050);
    Put(0x8B0BD0 + 0x10, 0x6F9060);
    Put(0x8A9818 + 0x20, 0x671180);
    Put(0x8A9818 + 0x5C, 0x696FB0);
    Put(0x8A9818 + 0x60, 0x696FD0);
    Put(0x8A9818 + 0x64, 0x696FF0);
    if (wrongSlot) Put(0x8B0BD0 + 0x10, 0x6F9070);
    // RBVehicle's IRigidBody vtable (the player car's body in the game): the same setters as RigidBody's
    Put(0x8AC880 + 0x5C, 0x696FB0);
    Put(0x8AC880 + 0x60, wrongRb ? 0x696FD1 : 0x696FD0);
    Put(0x8AC880 + 0x64, 0x696FF0);
    // RigidBody setters: the slot values are the game's (0x696FD0 / 0x696FF0) for the plugin's check; the stand-in
    // has no code there, so after the plugin has loaded the two slots are pointed at stand-in setters (below)
    // GetWorldHeightAtPoint: the game's 9 bytes, then add esp,4; pop esi; add esp,0x48; jmp Height
    At(0x7897C0); B({0x83, 0xEC, 0x48, 0x56, 0x68, 0xCD, 0xCC, 0xCC, 0x3C, 0x83, 0xC4, 0x04, 0x5E, 0x83, 0xC4, 0x48});
    Jmp((DWORD)(UINT_PTR)&Height);
    if (wrong) *(BYTE*)0x7897C0 = 0x55;
    // FindDrivableSection: the game's 10 bytes, then pop ebp; pop ebx; pop ecx; jmp FindDrivable
    At(0x72CA00); B({0x51, 0x53, 0x55, 0x8B, 0x6C, 0x24, 0x10, 0x8D, 0x59, 0x10, 0x5D, 0x5B, 0x59});
    Jmp((DWORD)(UINT_PTR)&FindDrivable);
    // the reset path: each function starts with the game's bytes, then code that undoes them and jumps to the
    // stand-in function (RigidBody::SetPosition is the game's own 31 bytes)
    At(0x6B08C0); B({0x83, 0xEC, 0x20, 0x53, 0x8B, 0x5C, 0x24, 0x28, 0x5B, 0x83, 0xC4, 0x20});  // .. pop ebx; add esp,20
    Jmp((DWORD)(UINT_PTR)&StResetVehicle);
    At(0x6A45F0); B({0x6A, 0xFF, 0x68, 0xAF, 0xC9, 0x87, 0x00, 0x83, 0xC4, 0x08});  // .. add esp, 8
    Jmp((DWORD)(UINT_PTR)&StResetTo);
    if (wrongReset) *(BYTE*)0x6A45F1 = 0xFE;  // push -2: still runs, but not the game's bytes
    At(0x685810); B({0x6A, 0xFF, 0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x83, 0xC4, 0x04});  // .. add esp, 4
    Jmp((DWORD)(UINT_PTR)&StOnGround);
    At(0x696FB0); B({0x8B, 0x41, 0x30, 0x8B, 0x08, 0x8B, 0x54, 0x24, 0x04, 0x8B, 0x02, 0x83, 0xC1, 0x10, 0x89, 0x01,
                     0x8B, 0x42, 0x04, 0x89, 0x41, 0x04, 0x8B, 0x52, 0x08, 0x89, 0x51, 0x08, 0xC2, 0x04, 0x00});
    // the instructions and slots that say what these functions are (bytes only, never run)
    At(0x6B0884); B({0xFF, 0x52, 0x08});            // ResetCar::Check: call [edx+8] = IResetable::ResetVehicle
    At(0x6B0960); B({0xE8}); Rel(0x6A45F0);        // ResetCar::ResetVehicle: call ResetTo
    At(0x6A4631); B({0xFF, 0x52, 0x68});            // ResetTo: call [edx+0x68] = IVehicle::SetVehicleOnGround
    Put(0x8ABA18, 0x6B08C0);                        // ResetCar vtable: ResetVehicle
    Put(0x8AA890, 0x685810);                        // IVehicle vtable +0x68: SetVehicleOnGround
    Put(0x8AC8DC, 0x696FB0);                        // RBVehicle IRigidBody +0x5C (also set below)
    // instructions that tie the data addresses (bytes only, never run)
    At(0x7318B4); B({0xB9, 0x50, 0x3B, 0x9A, 0x00});
    At(0x7318CA); B({0x8B, 0x3D, 0x78, 0xA4, 0x9A, 0x00});
    if (wrongData) *(BYTE*)0x7318CC = 0x79;
    At(0x772CF1); B({0x8B, 0x0D, 0xA0, 0x38, 0x9B, 0x00});
    At(0x6959FD); B({0x81, 0xC1, 0xC8, 0x86, 0x93, 0x00});
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);

    // data
    g_player.vtbl = 0x8B0B10;
    static DWORD array[1] = {(DWORD)(UINT_PTR)&g_player.vtbl};
    Put(0x92D884, 1);
    Put(0x92D87C, (DWORD)(UINT_PTR)array);
    if (badPtr)  // reserved, never committed: reading it faults (WorldProbe must catch that, not crash)
        Put(0x92D87C, (DWORD)(UINT_PTR)VirtualAlloc(nullptr, 0x10000, MEM_RESERVE, PAGE_READWRITE));
    float mph = 60.0f;
    memcpy((void*)0x914654, &mph, 4);
    float tel[3] = {1700.0f, 113.0f, -2400.0f};
    memcpy((void*)0x9386D8, tel, 12);
    g_sim[0] = (DWORD)(UINT_PTR)g_simVtbl;
    g_simVtbl[0x54 / 4] = (DWORD)(UINT_PTR)&GetRigidBody;
    // the RigidBody: vtable 0x8A9818 (checked), whose +0x60/+0x64 slots the plugin calls through; after the plugin
    // has checked the slot values, they are pointed at the stand-in setters
    g_rb[0] = rbVehicle ? 0x8AC880 : 0x8A9818;
    g_rb[0x30 / 4] = (DWORD)(UINT_PTR)&g_rbDataPtr;
    g_resetCar[0x34 / 4] = (DWORD)(UINT_PTR)g_sim;
    g_drivable[3] = 309;  // +0x0C: section C9
    g_scenery[0][0] = (DWORD)(UINT_PTR)g_scenery[1];
    g_scenery[0][3] = 2601;
    g_scenery[1][0] = 0x9AA478;
    g_scenery[1][3] = 101;
    Put(0x9AA478, (DWORD)(UINT_PTR)g_scenery[0]);
    g_packs[101] = 1;
    g_packs[309] = 1;
    Put(0x9B38A0, (DWORD)(UINT_PTR)g_packs);

    HMODULE plugin = LoadLibraryA("WorldProbe.asi");
    printf("plugin=%s\n", plugin ? "loaded" : "missing");
    BYTE now[5];
    memcpy(now, (void*)0x663D35, 5);
    printf("HOOK %s\n", (now[0] == 0xE8 && *(DWORD*)(now + 1) == 0x667650 - (0x663D35 + 5)) ? "untouched" : "patched");
    Put(0x8A9818 + 0x60, (DWORD)(UINT_PTR)&SetLinear);
    Put(0x8A9818 + 0x64, (DWORD)(UINT_PTR)&SetAngular);
    if (!wrongRb)
        Put(0x8AC880 + 0x60, (DWORD)(UINT_PTR)&SetLinear);
    Put(0x8AC880 + 0x64, (DWORD)(UINT_PTR)&SetAngular);
    for (g_frame = 0; g_frame < frames; g_frame++)
    {
        if (drop && g_frame >= 30 && g_frame < 50)
            g_pos[1] -= 0.2f;  // physics y: 4 m in 20 frames (about 60 ms)
        if (jump && g_frame == 25)
            g_pos[2] += 100.0f;  // physics z = render x: render (1700, 2400) -> (1800, 2400)
        if (gridHold && g_frame >= 6 && g_frame <= 8)
        {
            float here[3];
            memcpy(here, g_pos, 12);
            for (int n = 0; n < 50; n++)
            {
                HoldA(here);
                HoldB(here);
            }
        }
        if (otherCalls && g_frame == 6)
        {
            // another car (traffic, a cop): its own ISimable and ResetCar; the stand-in's car is put back after
            static DWORD otherSim[64], otherResetCar[0x60 / 4];
            otherResetCar[0x34 / 4] = (DWORD)(UINT_PTR)otherSim;
            for (int n = 0; n < 300; n++)
                ((void(__thiscall*)(void*, const float*, const float*))0x685810)((BYTE*)otherSim + 0x80, g_cookie, g_dir);
            static const float start[3] = {-2400.0f, 113.0f, 1700.0f};
            memcpy(g_pos, start, 12);
        }
        if (resetCall)
        {
            Put(0x92D884, g_frame < 5 ? 0 : 1);  // no player for the first 5 frames
            if (g_frame == 2 || g_frame == resetAt)
            {
                // as ResetCar::Check does: IResetable::ResetVehicle(false) on the ResetCar's IResetable part
                bool r = ((bool(__thiscall*)(void*, int))0x6B08C0)((BYTE*)g_resetCar + 0x4C, 0);
                printf("RESULT %d\n", r ? 1 : 0);
                if (g_frame == 2)
                {
                    // frame 2 stands for another car's reset (no player yet): put the stand-in's one car back
                    static const float start[3] = {-2400.0f, 113.0f, 1700.0f};
                    memcpy(g_pos, start, 12);
                }
            }
        }
        ((void(__cdecl*)())0x663D30)();
        Sleep(3);
    }
    printf("HEIGHTCALLS %d\n", g_heightCalls);
    printf("FINDDRIVABLECALLS %d\n", g_findCalls);
    return 0;
}
