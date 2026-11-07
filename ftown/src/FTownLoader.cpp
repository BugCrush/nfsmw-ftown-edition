// FTownLoader.asi - F-Town: loads our own world chunks (a texture pack, solid lists, scenery sections, collision packs:
// the stage 1 slab has one of each, the stage 2 city 12 of each) from a file through the game's own loaders, puts the
// collision into the world grid, and moves the player's car onto it; undoes all of it before the race is left.
//
// Findings and addresses: docs/ftown-notes.md (Task 5 Q1-Q6, "WorldProbe 2", "Part 2: the slab and FTownLoader").
// speed.exe v1.3 only: every code site, data-address instruction and vtable slot used is checked against its expected
// bytes at load; on any mismatch the log says WRONGBYTES and the plugin patches nothing and does nothing.
//
// Once a frame on the game thread: MainLoop (0x663D30) starts with `call bGetTicker` (0x45CE40, its result unused);
// that call is pointed at FtFrame(), which calls bGetTicker and then does its work. (WorldProbe hooks the next call,
// 0x663D35; the two sites do not overlap, so both plugins work in either load order.)
// Before the track is unloaded: TrackLoader::Unload (0x6617E0, the one function every way out of a race goes through:
// quit, restart by reload, career travel) gets a 6-byte jmp to a hook that unloads our chunks first, then runs the
// game's function through a trampoline.
//
// F8 (in a race, the game window in front): refuse if any of the file's numbers is taken; copy the file into a fresh
// buffer; LoadChunks(buffer, size, "FTOWN") (0x6589A0); confirm every scenery section (UserInfoTable[number]) and every
// collision pack (mCollisionPackList[number]) was filed (else all of it is unloaded); put every pack's collision
// instances' tags (pack number << 16 | index) into the grid cells around them
// (WGridNode::AddDynamic 0x782B30; cells without a node get a node of ours, as the stored nodes are 0x14 bytes);
// ask GetWorldHeightAtPoint (0x7897C0) for a face under the spawn point; only then LocalPlayer::SetPosition, the
// heading (RigidBody::SetOrientation(Matrix4), slot +0x70) and zero velocities. No face: everything undone, the car
// stays. F6 (stage 2): while loaded, the car to the next spawn of [Spawn] (each checked for a face the same way).
// F7 or a second F8 first return the car (small fixes 2026-11-03, Run E: after F7 it fell for ever): while
// F-Town is still loaded, Rockport is streamed in at the spot the car left at F8 (the game's own jump:
// Sim::SetStream 0x6F1170 blocking; refused while the game has zone switching off), a face there is checked, the car
// is put back (heading, no speed) and the reset's saved spots are replaced by that spot
// (ResetCar::SetResetPosition through IResetable); no face: nothing is
// unloaded. Then, as for the player gone or the track unloading: the grid entries out (WGridNode::RemoveDynamic
// 0x77A680; our nodes' lists freed as WGrid::Shutdown frees them, the cells set back to empty), every collider's
// instance cache cleared (WCollisionAssets::SetExclusionFlags 0x782C60), UnloadChunks (0x658A00), and the buffer
// freed 3 frames later.
//
// Settings: FTownLoader.ini. Log: FTownLoader.log (rewritten at every start).
#include <windows.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ---------------------------------------------------------------- reads that cannot crash (WorldProbe 2's method)

extern "C" int __cdecl FtSafeCopy(void* dst, const void* src, unsigned n);
extern "C" char FtSafeCopyRead[], FtSafeCopyDone[], FtSafeCopyFault[];
__asm__(".intel_syntax noprefix\n"
        ".text\n"
        ".globl _FtSafeCopy\n"
        ".globl _FtSafeCopyRead\n"
        ".globl _FtSafeCopyDone\n"
        ".globl _FtSafeCopyFault\n"
        "_FtSafeCopy:\n"
        "  push esi\n"
        "  push edi\n"
        "  mov edi, [esp + 12]\n"
        "  mov esi, [esp + 16]\n"
        "  mov ecx, [esp + 20]\n"
        "_FtSafeCopyRead:\n"
        "  rep movsb\n"
        "_FtSafeCopyDone:\n"
        "  mov eax, 1\n"
        "  pop edi\n"
        "  pop esi\n"
        "  ret\n"
        "_FtSafeCopyFault:\n"
        "  xor eax, eax\n"
        "  pop edi\n"
        "  pop esi\n"
        "  ret\n"
        ".att_syntax prefix\n");

static LONG CALLBACK OnFault(EXCEPTION_POINTERS* e)
{
    DWORD code = e->ExceptionRecord->ExceptionCode;
    DWORD eip = e->ContextRecord->Eip;
    if ((code == EXCEPTION_ACCESS_VIOLATION || code == STATUS_GUARD_PAGE_VIOLATION) &&
        eip >= (DWORD)(UINT_PTR)FtSafeCopyRead && eip < (DWORD)(UINT_PTR)FtSafeCopyDone)
    {
        e->ContextRecord->Eip = (DWORD)(UINT_PTR)FtSafeCopyFault;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

// ---------------------------------------------------------------- the log

static FILE* g_log;
static LARGE_INTEGER g_qpcFreq, g_qpcStart;

static double NowMs()
{
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return (double)(t.QuadPart - g_qpcStart.QuadPart) * 1e3 / (double)g_qpcFreq.QuadPart;
}

// Events only (no per-frame lines), so every line is flushed: a crash right after a step keeps the step's line.
static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    char line[1200];
    int k = snprintf(line, sizeof(line), "[%9.3f] ", NowMs() / 1e3);
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(line + k, sizeof(line) - k - 1, fmt, args);
    va_end(args);
    k = (n < 0 || k + n > (int)sizeof(line) - 2) ? (int)sizeof(line) - 2 : k + n;
    line[k++] = '\n';
    fwrite(line, 1, k, g_log);
    fflush(g_log);
}

static bool SafeRead(DWORD address, void* out, DWORD size)
{
    if (address < 0x10000 || address + size < address)
        return false;
    return FtSafeCopy(out, (const void*)(UINT_PTR)address, size) != 0;
}

static bool ReadDword(DWORD address, DWORD* out) { return SafeRead(address, out, 4); }

// ---------------------------------------------------------------- the game's addresses (speed.exe v1.3)

static const DWORD kFrameSite = 0x663D30, kGetTicker = 0x45CE40;
static const DWORD kTrackUnload = 0x6617E0;
static const DWORD kLoadChunks = 0x6589A0, kUnloadChunks = 0x658A00;
static const DWORD kHeightAtPoint = 0x7897C0;
static const DWORD kAddDynamic = 0x782B30, kRemoveDynamic = 0x77A680;
static const DWORD kListDtor = 0x77D470, kFastMemFree = 0x5D0370, kFastMem = 0x925B30;
static const DWORD kGridPtr = 0x9B38A8;
static const DWORD kAssetsPtr = 0x9B3890, kSetExclusionFlags = 0x782C60;
static const DWORD kPackListPtr = 0x9B38A0;
static const DWORD kUserInfoTable = 0x9A3BB0;  // TheVisibleSectionManager 0x9A3B50 + 0x60
static const DWORD kPlayerCount = 0x92D884, kPlayerArray = 0x92D87C;
static const DWORD kPlayerVtbl1 = 0x8B0B10, kPlayerVtbl2 = 0x8B0BD0;
static const DWORD kRigidBodyVtbl = 0x8A9818, kRBVehicleVtbl = 0x8AC880;
static const int kUserInfoMax = 2800, kPackMax = 2700;
// the return path (docs/ftown-notes.md "Small fixes (2026-11-03)")
static const DWORD kSetStream = 0x6F1170, kSimSystem = 0x9885E0;  // Sim::SetStream; Sim::Internal::mSystem
static const DWORD kZoneSwitchingDisabled = 0x9AAC81;             // TheTrackStreamer 0x9AA9D0 + 0x2B1
static const DWORD kFind = 0x5D59F0, kIResetableHandle = 0x620250;  // UTL::COM::Object::_IList::Find; _IHandle
static const DWORD kResetableVtbl = 0x8ABA10;                     // ResetCar's IResetable vtable

struct Site
{
    DWORD at;
    BYTE bytes[64];
    int n;
    const char* what;
};

static const Site kSites[] = {
    {0x663D30, {0xE8, 0x0B, 0x91, 0xDF, 0xFF}, 5, "MainLoop: call bGetTicker (the per-frame hook)"},
    {0x45CE40, {0x83, 0xEC, 0x08, 0x8D, 0x04, 0x24}, 6, "bGetTicker"},
    {0x6617E0, {0x53, 0x56, 0x6A, 0x08, 0x33, 0xDB}, 6, "TrackLoader::Unload (the unload hook)"},
    {0x6617F6, {0x68, 0xF8, 0x8E, 0x8A, 0x00}, 5, "TrackLoader::Unload: push \"TrackLoader::Unload\""},
    {0x6589A0, {0x8B, 0x44, 0x24, 0x08, 0x56, 0x8B, 0x74, 0x24, 0x08, 0x57}, 10, "LoadChunks(bChunk*, int, const char*)"},
    {0x658A00, {0x81, 0xEC, 0x00, 0x01, 0x00, 0x00, 0x57, 0xE8, 0x94, 0x28, 0x07, 0x00}, 12,
     "UnloadChunks: sub esp, 0x100; push edi; call eWaitUntilRenderingDone"},
    {0x7897C0, {0x83, 0xEC, 0x48, 0x56, 0x68, 0xCD, 0xCC, 0xCC, 0x3C}, 9, "WCollisionMgr::GetWorldHeightAtPoint"},
    {0x782B30, {0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x6A, 0xFF, 0x68, 0x1F, 0x20, 0x88, 0x00}, 13,
     "WGridNode::AddDynamic(unsigned, WGridNode_ElemType)"},
    {0x77A680, {0x56, 0x8B, 0x31, 0x85, 0xF6, 0x74, 0x55, 0x8B, 0x4E, 0x04}, 10, "WGridNode::RemoveDynamic"},
    {0x781720,
     {0x8B, 0xCE, 0xE8, 0x49, 0xBD, 0xFF, 0xFF, 0x6A, 0x00, 0x6A, 0x0C, 0x56, 0xB9, 0x30, 0x5B, 0x92, 0x00, 0xE8, 0x3A,
      0xEC, 0xE4, 0xFF},
     22, "WGrid::Shutdown: a node's list freed (list dtor 0x77D470, gFastMem 0x925B30 Free 0x5D0370, 12 bytes)"},
    {0x7816F0, {0xA1, 0xA8, 0x38, 0x9B, 0x00}, 5, "WGrid::Shutdown: mov eax, [fgGrid 0x9B38A8]"},
    // review: the colliders' instance caches (WCollider::fInstanceCacheList) hold pointers into our buffer; the
    // game's own WCollisionAssets::SetExclusionFlags() clears every collider (after a walk of packs 0..0x3FF)
    {0x782C60, {0x56, 0x57, 0x8B, 0xF9, 0x33, 0xF6}, 6, "WCollisionAssets::SetExclusionFlags()"},
    {0x782C81,
     {0x8B, 0x35, 0x84, 0x3C, 0x9B, 0x00, 0x8B, 0x15, 0x8C, 0x3C, 0x9B, 0x00, 0x8D, 0x3C, 0x96, 0x3B, 0xF7, 0x74, 0x17,
      0x8B, 0x0E, 0xE8, 0x95, 0xFD, 0xFF, 0xFF, 0x8B, 0x06, 0x83, 0xC6, 0x04, 0x3B, 0xF7, 0xC6, 0x80, 0x80, 0x00, 0x00,
      0x00, 0x00, 0x75, 0xE9},
     42, "SetExclusionFlags: WCollider::Clear (0x782A30) on every collider of the list at 0x9B3C84"},
    {0x782A30, {0x53, 0x56, 0x8B, 0xF1}, 4, "WCollider::Clear"},
    {0x5DD116, {0x8B, 0x0D, 0x90, 0x38, 0x9B, 0x00, 0xE8, 0x3F, 0x5B, 0x1A, 0x00}, 11,
     "GRaceBin::EnableBarriers: mov ecx, [WCollisionAssets 0x9B3890]; call SetExclusionFlags"},
    {0x7816FD, {0x8B, 0x48, 0x1C, 0x0F, 0xAF, 0x48, 0x18}, 7, "WGrid::Shutdown: cols +0x1C x rows +0x18"},
    {0x781710, {0x8B, 0x50, 0x20}, 3, "WGrid::Shutdown: fNodes +0x20"},
    {0x76369A, {0xD8, 0x26, 0x57, 0xD8, 0x4E, 0x14}, 6, "WGrid::GetRowCol: (x - fMin.x) * fInvEdgeSize (+0x14)"},
    {0x7636AB, {0xD9, 0x43, 0x08, 0xD8, 0x66, 0x08, 0xD8, 0x4E, 0x14}, 9, "WGrid::GetRowCol: (z - fMin.z +0x08) * inv"},
    {0x772CF1, {0x8B, 0x0D, 0xA0, 0x38, 0x9B, 0x00}, 6, "UnLoadCollisionPack: mov ecx, [mCollisionPackList 0x9B38A0]"},
    {0x731915, {0x8B, 0x0C, 0x85, 0xB0, 0x3B, 0x9A, 0x00}, 7,
     "WhatSectionsShouldWeDraw: mov ecx, [UserInfoTable 0x9A3BB0 + n*4]"},
    {0x7299E0, {0x57, 0x8B, 0x7C, 0x24, 0x08, 0x8B, 0x44, 0xB9, 0x60}, 9,
     "VisibleSectionManager::AllocateUserInfo: [this + n*4 + 0x60]"},
    {0x47EF0A, {0x39, 0x1D, 0x84, 0xD8, 0x92, 0x00}, 6, "ICEGetPlayerCarTransform: cmp [player count 0x92D884]"},
    {0x47EF12, {0xA1, 0x7C, 0xD8, 0x92, 0x00}, 5, "ICEGetPlayerCarTransform: mov eax, [player array 0x92D87C]"},
    {0x6F8FB0, {0x83, 0xE9, 0x20, 0xE9, 0x78, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer GetSimable thunk"},
    {0x6F9050, {0x83, 0xE9, 0x20, 0xE9, 0xA8, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer GetPosition thunk"},
    {0x6F9060, {0x83, 0xE9, 0x20, 0xE9, 0xB8, 0xFF, 0xFF, 0xFF}, 8, "LocalPlayer SetPosition thunk"},
    {0x6F9020, {0x8B, 0x41, 0x18, 0x85, 0xC0}, 5, "LocalPlayer::SetPosition"},
    {0x696D90, {0x53, 0x55, 0x56, 0x8B, 0x74, 0x24, 0x10}, 7, "RigidBody::SetOrientation (the Matrix4 one)"},
    {0x696DAB, {0xB9, 0x10, 0x00, 0x00, 0x00, 0xF3, 0xA5}, 7, "RigidBody::SetOrientation: copies 16 floats"},
    {0x671270, {0x8B, 0x41, 0x30, 0x8B, 0x00, 0x8B, 0x4C, 0x24, 0x04, 0x05, 0x90, 0x00, 0x00}, 13,
     "RigidBody::GetForwardVector: the orientation's row 2 (+0x90)"},
    // the return path (small fixes 2026-11-03)
    {0x6F1170, {0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF0, 0x83, 0xEC, 0x10, 0xA1, 0xE0, 0x85, 0x98, 0x00}, 14,
     "Sim::SetStream(const Vector3&, bool): mov eax, [Sim::Internal::mSystem 0x9885E0]"},
    {0x6F11B8, {0x8A, 0x45, 0x0C, 0x84, 0xC0, 0x74, 0x3F}, 7, "Sim::SetStream: the blocking flag (second argument)"},
    {0x6F11BF, {0x8B, 0x0D, 0xE0, 0x85, 0x98, 0x00, 0x6A, 0x01, 0xE8, 0xB4, 0xFD, 0xFF, 0xFF}, 13,
     "Sim::SetStream: SimSystem::PauseInput(true) when blocking"},
    {0x6F11D6, {0xB9, 0xD0, 0xA9, 0x9A, 0x00, 0xE8, 0xC0, 0x05, 0x04, 0x00}, 10,
     "Sim::SetStream: TheTrackStreamer.BlockUntilLoadingComplete (0x7317A0)"},
    {0x5108C0, {0xC6, 0x81, 0xB1, 0x02, 0x00, 0x00, 0x01, 0xC3}, 8,
     "TrackStreamer::DisableZoneSwitching: the flag at +0x2B1"},
    {0x5EBD16, {0xC6, 0x05, 0x81, 0xAC, 0x9A, 0x00, 0x00, 0xE8, 0x4E, 0x54, 0x10, 0x00}, 12,
     "GManager::WarpToMarker: zone switching on (0x9AAC81 = 0), call Sim::SetStream"},
    {0x6115A1, {0x56, 0xA2, 0x81, 0xAC, 0x9A, 0x00, 0xE8, 0xC4, 0xFB, 0x0D, 0x00}, 11,
     "Game_WarpPlayerToTrigger: zone switching on, call Sim::SetStream"},
    {0x755681, {0x8D, 0x54, 0x24, 0x10, 0x6A, 0x01, 0x52, 0xE8, 0xE3, 0xBA, 0xF9, 0xFF}, 12,
     "DebugWorld::HandleJumpToHotPosition: Sim::SetStream(position, true)"},
    {0x5D59F0, {0x83, 0xEC, 0x08, 0x56, 0x8B, 0x71, 0x08, 0x8B, 0x49, 0x04}, 10, "UTL::COM::Object::_IList::Find"},
    {0x620250, {0xB8, 0x50, 0x02, 0x62, 0x00, 0xC3}, 6, "IResetable::_IHandle"},
    {0x611642, {0x8B, 0x48, 0x04, 0x68, 0xE0, 0x40, 0x40, 0x00, 0xE8, 0xA1, 0x43, 0xFC, 0xFF}, 13,
     "Game_WarpPlayerToTrigger: Find on the player's ISimable +4 (IVehicle)"},
    {0x641E5F, {0x8B, 0x48, 0x04, 0x68, 0x50, 0x02, 0x62, 0x00, 0xE8, 0x84, 0x3B, 0xF9, 0xFF}, 13,
     "EResetPlayerCar: Find(IResetable) on +4"},
    {0x6A4340, {0x83, 0xEC, 0x20, 0x8B, 0x44, 0x24, 0x24, 0x56}, 8, "ResetCar::SetResetPosition"},
};

struct Slot
{
    DWORD table, offset, value;
    const char* what;
};

static const Slot kSlots[] = {
    {kPlayerVtbl1, 0x04, 0x6F8FB0, "LocalPlayer vtable 1 +0x04 GetSimable"},
    {kPlayerVtbl1, 0x0C, 0x6F9050, "LocalPlayer vtable 1 +0x0C GetPosition"},
    {kPlayerVtbl1, 0x10, 0x6F9060, "LocalPlayer vtable 1 +0x10 SetPosition"},
    {kPlayerVtbl2, 0x04, 0x6F8FB0, "LocalPlayer vtable 2 +0x04 GetSimable"},
    {kPlayerVtbl2, 0x0C, 0x6F9050, "LocalPlayer vtable 2 +0x0C GetPosition"},
    {kPlayerVtbl2, 0x10, 0x6F9060, "LocalPlayer vtable 2 +0x10 SetPosition"},
    {kRBVehicleVtbl, 0x34, 0x671270, "RBVehicle IRigidBody +0x34 GetForwardVector"},
    {kRBVehicleVtbl, 0x5C, 0x696FB0, "RBVehicle IRigidBody +0x5C SetPosition"},
    {kRBVehicleVtbl, 0x60, 0x696FD0, "RBVehicle IRigidBody +0x60 SetLinearVelocity"},
    {kRBVehicleVtbl, 0x64, 0x696FF0, "RBVehicle IRigidBody +0x64 SetAngularVelocity"},
    {kRBVehicleVtbl, 0x70, 0x696D90, "RBVehicle IRigidBody +0x70 SetOrientation(Matrix4)"},
    {kRigidBodyVtbl, 0x34, 0x671270, "RigidBody vtable +0x34 GetForwardVector"},
    {kRigidBodyVtbl, 0x60, 0x696FD0, "RigidBody vtable +0x60 SetLinearVelocity"},
    {kRigidBodyVtbl, 0x64, 0x696FF0, "RigidBody vtable +0x64 SetAngularVelocity"},
    {kRigidBodyVtbl, 0x70, 0x696D90, "RigidBody vtable +0x70 SetOrientation(Matrix4)"},
    {kResetableVtbl, 0x08, 0x6B08C0, "ResetCar IResetable +0x08 ResetVehicle"},
    {kResetableVtbl, 0x0C, 0x6A4340, "ResetCar IResetable +0x0C SetResetPosition"},
};

static bool BytesAre(const Site& s)
{
    BYTE b[sizeof(s.bytes)];  // small fixes: was 32 bytes, and the collider loop's site is 42
    if (SafeRead(s.at, b, s.n) && !memcmp(b, s.bytes, s.n))
    {
        Log("check ok 0x%08lX %s", (unsigned long)s.at, s.what);
        return true;
    }
    if (SafeRead(s.at, b, s.n))
    {
        char hex[3 * sizeof(s.bytes) + 1];  // review: 3 characters a byte (was 100: 33 bytes)
        int k = 0;
        for (int i = 0; i < s.n; i++) k += sprintf(hex + k, " %02X", b[i]);
        Log("WRONGBYTES 0x%08lX %s:%s", (unsigned long)s.at, s.what, hex);
    }
    else
        Log("WRONGBYTES 0x%08lX %s: cannot be read", (unsigned long)s.at, s.what);
    return false;
}

static bool SlotIs(const Slot& s)
{
    DWORD v = 0;
    if (ReadDword(s.table + s.offset, &v) && v == s.value)
    {
        Log("check ok 0x%08lX %s = 0x%08lX", (unsigned long)(s.table + s.offset), s.what, (unsigned long)v);
        return true;
    }
    Log("WRONGBYTES 0x%08lX %s: 0x%08lX, expected 0x%08lX", (unsigned long)(s.table + s.offset), s.what,
        (unsigned long)v, (unsigned long)s.value);
    return false;
}

static bool CheckAll()
{
    bool ok = true;
    for (const Site& s : kSites) ok &= BytesAre(s);
    for (const Slot& s : kSlots) ok &= SlotIs(s);
    return ok;
}

// ---------------------------------------------------------------- settings

static char g_iniPath[MAX_PATH];

// ---------------------------------------------------------------- a set of our chunks (one file)
//
// The city (ftown-city.bun, [Map] File) and, since the game mode (docs/ftown-race-notes.md R7), the Time Attack's race
// barriers (ftown-barriers.bun, [Barriers] File): each file is parsed at start, read again into a fresh buffer at each
// load, handed to LoadChunks, its collision put into the grid, and taken out again the same way.
struct OurNode;
struct CollInst
{
    float pos[3];  // physics
    float radius;
    DWORD tag;  // pack number << 16 | the instance's index in its pack
};
struct Reg
{
    DWORD cell;
    DWORD tag;
    DWORD node;
};
struct Made
{
    DWORD cell;
    OurNode* node;
};
struct MapSet
{
    const char* chunkName;  // the name LoadChunks / UnloadChunks get ("FTOWN", "FTOWNBAR")
    const char* prefix;     // log lines start with it ("" for the city, as before)
    char path[MAX_PATH], name[MAX_PATH];
    bool parsed;
    BYTE* file;  // the file as read at start (released after parsing)
    DWORD size;
    FILETIME time;
    // every scenery section and collision pack of the file (at most 64 top-level chunks in all)
    int sections[64], sectionCount, packs[64], packCount;
    CollInst* inst;
    int instCount;
    BYTE* buffer;  // what the game was handed (null when nothing is loaded)
    BYTE* pendingFree;  // unloaded, freed a few frames later (belt and braces: nothing should read it)
    int pendingFrames;
    Reg* regs;
    int regCount, regMax;
    DWORD regGrid, regNodes;  // the WGrid and fNodes the entries went into
    Made made[1024];
    int madeCount;
    int cellsTouched, tagsMax, tagsMedian;
    bool staticReg;  // moving traffic: the city's collision in the widened grid's own nodes (FTownRoadNet.h)
};
static MapSet g_city = {"FTOWN", ""};
static const int kMaxSpawns = 8;
// render x, y, z (z up), heading (degrees counter-clockwise from +x); [Spawn] Spawn1..Spawn8, or the old X/Y/Z/Heading
static float g_spawns[kMaxSpawns][4] = {{2000.0f, 11430.0f, 101.0f, 90.0f}};
static int g_spawnCount = 1, g_spawnAt;
static bool g_setHeading = true, g_returnEnabled = true, g_barEnabled = true;
static int g_keyGo = 0x77, g_keyUnload = 0x76, g_keyNext = 0x75;
static bool g_keysEnabled;  // [Keys] Enabled: F8 / F7 / F6 / F5 (off by default since the game mode)
static int g_cellMargin = 64;

static float IniFloat(const char* section, const char* key, float def)
{
    char buf[64];
    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_iniPath);
    return buf[0] ? (float)atof(buf) : def;
}

static int IniHex(const char* section, const char* key, const char* def)
{
    char buf[32];
    GetPrivateProfileStringA(section, key, def, buf, sizeof(buf), g_iniPath);
    return (int)strtoul(buf, nullptr, 0);
}

static void LoadSettings(const char* dir)
{
    GetPrivateProfileStringA("Map", "File", "ftown-slab.bun", g_city.name, sizeof(g_city.name), g_iniPath);
    snprintf(g_city.path, sizeof(g_city.path), "%s%s", dir, g_city.name);
    // stage 2: Spawn1 = x, y, z, heading ... Spawn8 (the first empty or malformed one ends the list); without Spawn1
    // the stage 1 keys X, Y, Z, Heading
    g_spawnCount = 0;
    for (int k = 0; k < kMaxSpawns; k++)
    {
        char key[16], buf[128];
        snprintf(key, sizeof(key), "Spawn%d", k + 1);
        GetPrivateProfileStringA("Spawn", key, "", buf, sizeof(buf), g_iniPath);
        float v[4];
        if (!buf[0] || sscanf(buf, " %f , %f , %f , %f", &v[0], &v[1], &v[2], &v[3]) != 4)
            break;
        memcpy(g_spawns[k], v, sizeof(v));
        g_spawnCount++;
    }
    if (!g_spawnCount)
    {
        g_spawns[0][0] = IniFloat("Spawn", "X", 2000.0f);
        g_spawns[0][1] = IniFloat("Spawn", "Y", 11430.0f);
        g_spawns[0][2] = IniFloat("Spawn", "Z", 101.0f);
        g_spawns[0][3] = IniFloat("Spawn", "Heading", 90.0f);
        g_spawnCount = 1;
    }
    g_setHeading = GetPrivateProfileIntA("Spawn", "SetHeading", 1, g_iniPath) == 1;
    g_keysEnabled = GetPrivateProfileIntA("Keys", "Enabled", 0, g_iniPath) == 1;
    g_keyGo = IniHex("Keys", "Go", "0x77");
    g_keyUnload = IniHex("Keys", "Unload", "0x76");
    g_keyNext = IniHex("Keys", "NextSpawn", "0x75");
    g_cellMargin = GetPrivateProfileIntA("Grid", "MarginMetres", 64, g_iniPath);
    g_returnEnabled = GetPrivateProfileIntA("Return", "Enabled", 1, g_iniPath) == 1;
    g_barEnabled = GetPrivateProfileIntA("Barriers", "Enabled", 1, g_iniPath) == 1;
}

// The key test and the window test. In the game GetAsyncKeyState and the foreground window; the stand-in test
// (ftown/tests/standin.cpp) exports FTownTestKey / FTownTestForeground (speed.exe exports neither).
typedef int(__cdecl* TestKeyFn)(int);
typedef int(__cdecl* TestForegroundFn)();
static TestKeyFn g_testKey;
static TestForegroundFn g_testForeground;

static bool KeyDown(int vk)
{
    if (g_testKey)
        return g_testKey(vk) != 0;
    return (GetAsyncKeyState(vk) & 0x8000) != 0;
}

static bool GameInFront()
{
    if (g_testForeground)
        return g_testForeground() != 0;
    HWND w = GetForegroundWindow();
    DWORD pid = 0;
    if (w)
        GetWindowThreadProcessId(w, &pid);
    return pid == GetCurrentProcessId();
}

// ---------------------------------------------------------------- the map file (our own format: tools/world/slab.py)


static const DWORD kChunkTexturePack = 0xB3300000, kChunkSolids = 0x80134000, kChunkScenery = 0x80034100,
                   kChunkCollision = 0x3B801;

// Checks the file is a chunk list of the kinds we write, finds every scenery section's and collision pack's number
// and every collision instance's position, radius and tag. Returns an error text or null.
static const char* ParseFile(MapSet& m)
{
    DWORD off = 0;
    int top = 0;
    while (off < m.size)
    {
        if (off + 8 > m.size)
            return "a chunk header runs past the file's end";
        DWORD id = *(DWORD*)(m.file + off), size = *(DWORD*)(m.file + off + 4);
        if (size > m.size - off - 8)
            return "a chunk runs past the file's end";
        if (id != 0 && id != kChunkTexturePack && id != kChunkSolids && id != kChunkScenery && id != kChunkCollision)
            return "a chunk kind FTownLoader does not hand to the game";
        if (++top > 64)
            return "more than 64 top-level chunks (UnloadChunks handles 64)";
        BYTE* data = m.file + off + 8;
        if (id == kChunkScenery)
        {
            // the header 0x34101 is the first child; its data 16-aligned (+0x0C the section number)
            if (size < 8 + 0x3C || *(DWORD*)data != 0x34101 || ((off + 16) & 15))
                return "the scenery section does not start with a 16-aligned header";
            int number = *(int*)(data + 8 + 0x0C);
            if (number <= 0 || number >= kUserInfoMax)
                return "a scenery section's number is out of range";
            for (int k = 0; k < m.sectionCount; k++)
                if (m.sections[k] == number)
                    return "two scenery sections with one number";
            m.sections[m.sectionCount++] = number;
        }
        else if (id == kChunkCollision)
        {
            DWORD run = (16 - ((off + 8) & 15)) & 15;
            BYTE* d = data + run;
            DWORD left = size - run;
            if (left < 48)
                return "the collision pack is too short";
            int number = *(int*)(d + 4);
            if (number <= 0 || number >= kPackMax)
                return "a collision pack's number is out of range";
            for (int k = 0; k < m.packCount; k++)
                if (m.packs[k] == number)
                    return "two collision packs with one number";
            m.packs[m.packCount++] = number;
            DWORD count = *(DWORD*)(d + 40), base = 32 + 16 * *(DWORD*)(d + 44);
            for (DWORD i = 0; i < count; i++)
            {
                DWORD u = base + 16 * i;
                if (u + 16 > left)
                    return "a collision UData runs past the pack";
                DWORD tag = *(DWORD*)(d + u), bits = *(DWORD*)(d + u + 4), n = *(DWORD*)(d + u + 8),
                      o = *(DWORD*)(d + u + 12);
                if (tag != 0x63690000)
                    continue;
                if ((bits >> 8) != n * 0x40 || u + o + n * 0x40 > left || n > 0xFFFF)
                    return "the collision instances do not fit the pack";
                CollInst* more = (CollInst*)realloc(m.inst, (m.instCount + n + 1) * sizeof(CollInst));
                if (!more)
                    return "no memory for the collision instances";
                m.inst = more;
                for (DWORD k = 0; k < n; k++)
                {
                    const float* r = (const float*)(d + u + o + 0x40 * k);
                    const float *r0 = r, *r2 = r + 8, *t = r + 12;
                    CollInst& ci = m.inst[m.instCount++];
                    // CalcPosition (WCollision.cpp:34): -(t . r0), -(t . r1), -(t . r2), r1 = (0, 1, 0)
                    ci.pos[0] = -(t[0] * r0[0] + t[1] * r0[1] + t[2] * r0[2]);
                    ci.pos[1] = -t[1];
                    ci.pos[2] = -(t[0] * r2[0] + t[1] * r2[1] + t[2] * r2[2]);
                    ci.radius = r[15];
                    ci.tag = ((DWORD)number << 16) | k;
                }
            }
        }
        off += 8 + size;
    }
    if (!m.sectionCount)
        return "no scenery section";
    if (!m.packCount)
        return "no collision pack";
    if (!m.instCount)
        return "the collision packs have no instances";
    return nullptr;
}

static const char* Off(const MapSet& m)
{
    return &m == &g_city ? "FTownLoader does nothing" : "the race barriers are off";
}

static bool ReadMapFile(MapSet& m)
{
    HANDLE f = CreateFileA(m.path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("%srefused: the map file %s cannot be opened (error %lu); %s", m.prefix, m.path,
            (unsigned long)GetLastError(), Off(m));
        return false;
    }
    m.size = GetFileSize(f, nullptr);
    GetFileTime(f, nullptr, nullptr, &m.time);
    m.file = (BYTE*)VirtualAlloc(nullptr, m.size ? m.size : 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    BOOL ok = m.file && ReadFile(f, m.file, m.size, &got, nullptr) && got == m.size;
    CloseHandle(f);
    if (!ok)
    {
        Log("%srefused: the map file %s could not be read; %s", m.prefix, m.path, Off(m));
        return false;
    }
    const char* err = ParseFile(m);
    if (err)
    {
        Log("%srefused: the map file %s: %s; %s", m.prefix, m.name, err, Off(m));
        return false;
    }
    char secs[64 * 6 + 1] = "", packs[64 * 6 + 1] = "";
    for (int k = 0, n = 0; k < m.sectionCount; k++) n += sprintf(secs + n, "%s%d", k ? " " : "", m.sections[k]);
    for (int k = 0, n = 0; k < m.packCount; k++) n += sprintf(packs + n, "%s%d", k ? " " : "", m.packs[k]);
    // review: the city is 40 MB; the parsed numbers and instances are all FTownLoader keeps, so the copy goes now and
    // each load reads the file again (ReadAgain), checked to be the file parsed here
    VirtualFree(m.file, 0, MEM_RELEASE);
    m.file = nullptr;
    char spawns[32] = "";
    if (&m == &g_city)
        snprintf(spawns, sizeof(spawns), " %d spawns;", g_spawnCount);
    Log("%smap file %s: %lu bytes, %d scenery sections (%s), %d collision packs (%s) with %d instances;%s the "
        "parsed copy released (read again from disk at each load)",
        m.prefix, m.name, (unsigned long)m.size, m.sectionCount, secs, m.packCount, packs, m.instCount, spawns);
    m.parsed = true;
    return true;
}

// Reads the map file into `buffer` (g_city.size bytes): refused when it is gone, or its size or write time differ from
// the file parsed at the start (its numbers and instances would no longer be the file's).
static bool ReadAgain(MapSet& m, BYTE* buffer)
{
    HANDLE f = CreateFileA(m.path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN,
                           nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("REFUSED: the map file %s cannot be read again (error %lu)", m.name, (unsigned long)GetLastError());
        return false;
    }
    FILETIME t = {0, 0};
    GetFileTime(f, nullptr, nullptr, &t);
    if (GetFileSize(f, nullptr) != m.size || CompareFileTime(&t, &m.time) != 0)
    {
        CloseHandle(f);
        Log("REFUSED: the map file %s changed since the game started (restart the game to use it)", m.name);
        return false;
    }
    DWORD got = 0;
    BOOL ok = ReadFile(f, buffer, m.size, &got, nullptr) && got == m.size;
    CloseHandle(f);
    if (!ok)
        Log("REFUSED: the map file %s cannot be read again (%lu of %lu bytes)", m.name, (unsigned long)got,
            (unsigned long)m.size);
    return ok != 0;
}

// ---------------------------------------------------------------- the game's functions

typedef void(__cdecl* LoadChunksFn)(void*, int, const char*);
typedef bool(__thiscall* HeightFn)(void*, const float*, float*, float*);
typedef void(__thiscall* DynFn)(void*, unsigned, int);
typedef void(__thiscall* ListDtorFn)(void*);
typedef void(__thiscall* FastFreeFn)(void*, void*, unsigned, const char*);
typedef const float*(__thiscall* GetPositionFn)(void*);
typedef bool(__thiscall* SetPositionFn)(void*, const float*);
typedef void*(__thiscall* GetPtrFn)(void*);
typedef void(__thiscall* SetVecFn)(void*, const float*);
typedef void(__thiscall* GetVecFn)(void*, float*);

static DWORD Vtbl(void* obj)
{
    DWORD v = 0;
    ReadDword((DWORD)(UINT_PTR)obj, &v);
    return v;
}

static void* Player()
{
    DWORD count = 0, array = 0, player = 0;
    if (!ReadDword(kPlayerCount, &count) || count == 0 || count > 8)
        return nullptr;
    if (!ReadDword(kPlayerArray, &array) || !ReadDword(array, &player) || !player)
        return nullptr;
    DWORD v = Vtbl((void*)(UINT_PTR)player);
    return (v == kPlayerVtbl1 || v == kPlayerVtbl2) ? (void*)(UINT_PTR)player : nullptr;
}

static bool PlayerPosition(void* player, float* p)
{
    const float* pos = ((GetPositionFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x0C)))(player);
    return pos && SafeRead((DWORD)(UINT_PTR)pos, p, 12);
}

static void* PlayerRigidBody(void* player, DWORD* vtbl)
{
    *vtbl = 0;
    void* simable = ((GetPtrFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x04)))(player);
    DWORD sv = simable ? Vtbl(simable) : 0, fn = 0;
    if (!sv || !ReadDword(sv + 0x54, &fn) || !fn)
        return nullptr;
    void* rb = ((GetPtrFn)(UINT_PTR)fn)(simable);
    return rb && (*vtbl = Vtbl(rb)) != 0 ? rb : nullptr;
}

static bool HeightAt(const float* physics, float* h)
{
    DWORD mgr[2] = {0, 3};  // the surface exclusion mask and primitive mask the game passes (notes Q4)
    float normal[3] = {0, 0, 0};
    return ((HeightFn)(UINT_PTR)kHeightAtPoint)(mgr, physics, h, normal);
}

// ---------------------------------------------------------------- the grid

// A WGridNode as the PC stores it: 0x14 bytes (list pointer, u16 node index, u16, u8 counts[4], u16 offsets[4]),
// docs/ftown-notes.md Task 4. Ours have no static elements; the game's AddDynamic gives them a list.
struct OurNode
{
    DWORD list;
    WORD index, pad;
    BYTE counts[4];
    WORD offsets[4];
};
static OurNode g_nodes[1024];  // never freed: the grid may point at one until it is shut down
// review: a node stays busy while it is in a cell; one "kept" at unload (something else joined its list) stays busy
// for good and is never handed out again
static bool g_nodeBusy[1024];


struct Grid
{
    float minX, minZ, invEdge;
    DWORD rows, cols, nodes;
    DWORD self;
};

static bool ReadGrid(Grid* g)
{
    DWORD grid = 0;
    BYTE b[0x24];
    if (!ReadDword(kGridPtr, &grid) || !grid || !SafeRead(grid, b, sizeof(b)))
        return false;
    g->self = grid;
    g->minX = *(float*)(b + 0x00);
    g->minZ = *(float*)(b + 0x08);
    g->invEdge = *(float*)(b + 0x14);
    g->rows = *(DWORD*)(b + 0x18);
    g->cols = *(DWORD*)(b + 0x1C);
    g->nodes = *(DWORD*)(b + 0x20);
    return g->rows && g->cols && g->rows <= 4096 && g->cols <= 4096 && g->nodes && isfinite(g->invEdge) &&
           g->invEdge > 0;
}

// WGrid::GetRowCol (0x763690): truncation, then RangeCheckROWCOL: a negative index (as unsigned, > 0x7FFFFFFE) -> 0,
// one past the end -> the last.
static DWORD Clamp(float v, float mn, float inv, DWORD n)
{
    DWORD i = (DWORD)(long)((v - mn) * inv);
    if (i >= n)
        i = i > 0x7FFFFFFEu ? 0 : n - 1;
    return i;
}


static bool RoadNetCityStatic(MapSet& m);  // FTownRoadNet.h
static void RoadNetCityUnstatic(MapSet& m, const char* why);

static bool Register(MapSet& m, const Grid& g)
{
    if (&m == &g_city && RoadNetCityStatic(m))
        return true;  // the widened grid: our nodes hold the city's instance tags (no dynamic entries)
    m.regCount = 0;
    m.madeCount = 0;
    m.cellsTouched = 0;
    m.regGrid = g.self;
    m.regNodes = g.nodes;
    m.regMax = 0;
    for (int i = 0; i < m.instCount; i++)
    {
        float r = m.inst[i].radius + (float)g_cellMargin;
        DWORD c0 = Clamp(m.inst[i].pos[0] - r, g.minX, g.invEdge, g.cols), c1 = Clamp(m.inst[i].pos[0] + r, g.minX,
                                                                                   g.invEdge, g.cols);
        DWORD r0 = Clamp(m.inst[i].pos[2] - r, g.minZ, g.invEdge, g.rows), r1 = Clamp(m.inst[i].pos[2] + r, g.minZ,
                                                                                   g.invEdge, g.rows);
        m.regMax += (int)((c1 - c0 + 1) * (r1 - r0 + 1));
    }
    m.regs = (Reg*)calloc(m.regMax ? m.regMax : 1, sizeof(Reg));
    for (int i = 0; i < m.instCount; i++)
    {
        float r = m.inst[i].radius + (float)g_cellMargin;
        DWORD c0 = Clamp(m.inst[i].pos[0] - r, g.minX, g.invEdge, g.cols), c1 = Clamp(m.inst[i].pos[0] + r, g.minX,
                                                                                   g.invEdge, g.cols);
        DWORD r0 = Clamp(m.inst[i].pos[2] - r, g.minZ, g.invEdge, g.rows), r1 = Clamp(m.inst[i].pos[2] + r, g.minZ,
                                                                                   g.invEdge, g.rows);
        DWORD tag = m.inst[i].tag;
        for (DWORD row = r0; row <= r1; row++)
            for (DWORD col = c0; col <= c1; col++)
            {
                DWORD cell = row * g.cols + col, slot = g.nodes + 4 * cell, node = 0;
                if (!ReadDword(slot, &node))
                    return false;
                if (!node)
                {
                    int free = 0, pool = (int)(sizeof(g_nodes) / sizeof(g_nodes[0]));
                    while (free < pool && g_nodeBusy[free]) free++;
                    if (free == pool || m.madeCount >= (int)(sizeof(m.made) / sizeof(m.made[0])))
                    {
                        Log("REFUSED: more empty grid cells than FTownLoader has nodes for (%d)", pool);
                        return false;
                    }
                    g_nodeBusy[free] = true;
                    OurNode* n = &g_nodes[free];
                    memset(n, 0, sizeof(*n));
                    n->index = (WORD)cell;
                    *(DWORD*)(UINT_PTR)slot = (DWORD)(UINT_PTR)n;
                    m.made[m.madeCount].cell = cell;
                    m.made[m.madeCount].node = n;
                    m.madeCount++;
                    node = (DWORD)(UINT_PTR)n;
                }
                ((DynFn)(UINT_PTR)kAddDynamic)((void*)(UINT_PTR)node, tag, 0);
                m.regs[m.regCount].cell = cell;
                m.regs[m.regCount].tag = tag;
                m.regs[m.regCount].node = node;
                m.regCount++;
            }
    }
    // tags per cell (the cost of a query at the place: every tag of a cell is walked, notes Q4)
    DWORD* cells = (DWORD*)calloc(m.regCount ? m.regCount : 1, sizeof(DWORD));
    for (int k = 0; k < m.regCount; k++) cells[k] = m.regs[k].cell;
    qsort(cells, m.regCount, sizeof(DWORD), [](const void* a, const void* b) {
        DWORD x = *(const DWORD*)a, y = *(const DWORD*)b;
        return x < y ? -1 : x > y ? 1 : 0;
    });
    int* runs = (int*)calloc(m.regCount ? m.regCount : 1, sizeof(int));
    for (int k = 0; k < m.regCount; k++)
    {
        if (k == 0 || cells[k] != cells[k - 1])
            runs[m.cellsTouched++] = 0;
        runs[m.cellsTouched - 1]++;
    }
    qsort(runs, m.cellsTouched, sizeof(int), [](const void* a, const void* b) {
        return *(const int*)a - *(const int*)b;
    });
    m.tagsMax = m.cellsTouched ? runs[m.cellsTouched - 1] : 0;
    m.tagsMedian = m.cellsTouched ? runs[m.cellsTouched / 2] : 0;
    free(cells);
    free(runs);
    return true;
}

// Takes our tags out of the cells, frees our nodes' lists as WGrid::Shutdown does and sets those cells back to empty.
static void Unregister(MapSet& m, const char* why)
{
    if (m.staticReg)
    {
        RoadNetCityUnstatic(m, why);
        return;
    }
    if (!m.regs && !m.madeCount)
        return;
    Grid g;
    bool same = ReadGrid(&g) && g.self == m.regGrid && g.nodes == m.regNodes;
    int removed = 0, freed = 0, kept = 0;
    if (!same)
    {
        Log("grid: the world grid is not the one the entries went into (rebuilt or shut down: it took them with it);"
            " nothing to remove");
        memset(g_nodeBusy, 0, sizeof(g_nodeBusy));  // no grid points at our nodes any more
    }
    else
    {
        for (int k = 0; k < m.regCount; k++)
        {
            DWORD now = 0;
            if (!ReadDword(g.nodes + 4 * m.regs[k].cell, &now) || now != m.regs[k].node)
                continue;
            ((DynFn)(UINT_PTR)kRemoveDynamic)((void*)(UINT_PTR)now, m.regs[k].tag, 0);
            removed++;
        }
        for (int k = 0; k < m.madeCount; k++)
        {
            DWORD slot = g.nodes + 4 * m.made[k].cell, now = 0;
            OurNode* n = m.made[k].node;
            if (!ReadDword(slot, &now) || now != (DWORD)(UINT_PTR)n)
                continue;
            DWORD size = 0;
            if (n->list && (!ReadDword(n->list + 8, &size) || size))
            {
                kept++;  // something else put elements into our node: leave it in its cell
                continue;
            }
            if (n->list)
            {
                ((ListDtorFn)(UINT_PTR)kListDtor)((void*)(UINT_PTR)n->list);
                ((FastFreeFn)(UINT_PTR)kFastMemFree)((void*)(UINT_PTR)kFastMem, (void*)(UINT_PTR)n->list, 0xC,
                                                      nullptr);
                n->list = 0;
            }
            *(DWORD*)(UINT_PTR)slot = 0;
            g_nodeBusy[n - g_nodes] = false;
            freed++;
        }
    }
    Log("grid: %d entries removed, %d cells of ours emptied and set back to no node%s (%s)", removed, freed,
        kept ? ", some kept (other elements in them)" : "", why);
    free(m.regs);
    m.regs = nullptr;
    m.regCount = 0;
    m.madeCount = 0;
}

// ---------------------------------------------------------------- load, unload, teleport

static int g_costFrames;  // the minimap's and the Time Attack's work, every frame while loaded (microseconds)
static double g_costSum, g_costMax;
static float g_home[3], g_homeHeading;  // where the car was at F8: physics; degrees counter-clockwise from render +x
static bool g_haveHome;
static bool g_cityForIntro;  // Run J: the chunks loaded for the race's intro, the car not placed yet (Load's tail due)
static const int kFreeAfterFrames = 3;
// FTownRace.h (included below, after the teleport and the way back it uses)
static void MinimapUnload(const char* why, bool later);
static void BarriersLoad(int k);
static void TimeAttackStop(const char* why);
static void TrafficRemove(const char* why);  // FTownTraffic.h
static void EveningOff(const char* why);  // FTownEvening.h
static void HudReset();                   // FTownRace.h: the race HUD's timer and COMPLETE % the game's again
static void ManualOff(const char* why);   // FTownRace.h: the Drag's manual gears put back
static bool WriteCode(DWORD at, const BYTE* bytes, int n);
// FTownRoadNet.h (moving traffic): the network and the widened grid
static bool RoadNetPrepare();
static void RoadNetRestore(const char* why);
static bool RoadNetInstalled();
static void RoadNetFrame();
static int RoadNetTrafficLevel(int mode);
static bool RoadNetSpotOk(int spot);

static void FreePending(MapSet& m, bool now)
{
    if (!m.pendingFree || (!now && --m.pendingFrames > 0))
        return;
    VirtualFree(m.pendingFree, 0, MEM_RELEASE);
    m.pendingFree = nullptr;
    Log("%sbuffer freed%s", m.prefix, now ? " (before a new load)" : "");
}

typedef void(__thiscall* VoidThisFn)(void*);
// FTownConnect.h (the career's connection to Rockport): F-Town loaded by it (no parked cars), and the colliders cleared
// without SetExclusionFlags() (which would turn off every grouped wall the career has switched on)
static bool g_lnCareer, g_collidersOnly;
static void CollidersClear();

// Takes a set's chunks out of the game: its grid entries, then every collider's cached instances, then UnloadChunks;
// the buffer is freed kFreeAfterFrames frames later. Returns the UnloadChunks time.
static double SetUnloadChunks(MapSet& m, const char* why)
{
    double t0 = NowMs();
    Unregister(m, why);
    // review: every car's and the camera's WCollider caches the collision instances it found (fInstanceCacheList,
    // World/WCollider.h:104) until it leaves its cached region, and reads them every physics frame; UnloadChunks
    // does not tell them (the streamer only drops sections far from the car). The game's SetExclusionFlags()
    // ends by clearing every collider (WCollider::Clear 0x782A30 on the list at 0x9B3C84, the inlined
    // InvalidateAllCachedData; 0x782C81..0x782CA9), as GRaceBin::EnableBarriers uses it (0x5DD116).
    DWORD assets = 0;
    if (g_collidersOnly)
    {
        CollidersClear();
        Log("%scolliders cleared (their caches only: free roam)", m.prefix);
    }
    else if (ReadDword(kAssetsPtr, &assets) && assets)
    {
        ((VoidThisFn)(UINT_PTR)kSetExclusionFlags)((void*)(UINT_PTR)assets);
        Log("%scolliders cleared (WCollisionAssets::SetExclusionFlags)", m.prefix);
    }
    else
        Log("%scolliders NOT cleared: WCollisionAssets (0x9B3890) is gone", m.prefix);
    ((LoadChunksFn)(UINT_PTR)kUnloadChunks)(m.buffer, (int)m.size, m.chunkName);
    double t1 = NowMs();
    FreePending(m, true);
    m.pendingFree = m.buffer;
    m.pendingFrames = kFreeAfterFrames;
    m.buffer = nullptr;
    return t1 - t0;
}

static void BarriersUnload(const char* why);
static void SmkUnload(const char* why);  // FTownSmack.h (the breakable poles)

static void Unload(const char* why)
{
    if (!g_city.buffer)
        return;
    SmkUnload(why);   // the breakable poles' spawners first, while the override table and the city are still there
    EveningOff(why);  // Rockport's time of day back first
    TrafficRemove(why);  // the cars stand on F-Town: they go before anything of it
    double t0 = NowMs();
    TimeAttackStop(why);
    HudReset();  // the race HUD's timer and COMPLETE % are the game's again
    BarriersUnload(why);  // the barriers stand on F-Town: they go first
    // the minimap's numbers back first; its pack now, or a few frames later when the race goes on (F7, second F8)
    MinimapUnload(why, !strcmp(why, "unload key") || !strcmp(why, "second go key while loaded"));
    if (g_costFrames)
        Log("cost per frame while F-Town was loaded: %d frames, mean %.1f us, max %.1f us (the minimap and the Time "
            "Attack)", g_costFrames, g_costSum / g_costFrames, g_costMax);
    g_costFrames = 0;
    g_costSum = g_costMax = 0;
    SetUnloadChunks(g_city, why);
    double t1 = NowMs();
    g_haveHome = false;
    g_cityForIntro = false;
    Log("UNLOADED (%s): UnloadChunks %.1f ms; the buffer is freed %d frames later", why, t1 - t0, kFreeAfterFrames);
}

static bool NumbersFree(MapSet& m)
{
    for (int k = 0; k < m.sectionCount; k++)
    {
        DWORD info = 0, header = 0;
        if (!ReadDword(kUserInfoTable + 4 * m.sections[k], &info))
            return false;
        if (info && ReadDword(info + 4, &header) && header)
        {
            Log("REFUSED: scenery section %d is taken (UserInfoTable holds header 0x%08lX)", m.sections[k],
                (unsigned long)header);
            return false;
        }
    }
    DWORD list = 0;
    if (!ReadDword(kPackListPtr, &list) || !list)
    {
        Log("REFUSED: the collision pack list cannot be read");
        return false;
    }
    for (int k = 0; k < m.packCount; k++)
    {
        DWORD pack = 0;
        if (!ReadDword(list + 4 * m.packs[k], &pack))
        {
            Log("REFUSED: the collision pack list cannot be read");
            return false;
        }
        if (pack)
        {
            Log("REFUSED: collision pack %d is taken (0x%08lX)", m.packs[k], (unsigned long)pack);
            return false;
        }
    }
    return true;
}

// Moves the car to t (physics), sets the heading (degrees counter-clockwise from render +x) when setHeading, zeroes
// both velocities. `what` starts the log line: "TELEPORT" (F8) or "RETURNED" (the way back).
static void Teleport(void* player, const float* t, float headingDeg, bool setHeading, const char* what)
{
    float before[3] = {0, 0, 0};
    PlayerPosition(player, before);
    bool ok = ((SetPositionFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x10)))(player, t);
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    char heading[160] = "heading not set ([Spawn] SetHeading = 0)", velocity[96];
    if (rb && (vtbl == kRBVehicleVtbl || vtbl == kRigidBodyVtbl))
    {
        if (setHeading)
        {
            // rows = the body's axes in the world (row-major, row 2 = forward, RigidBody::GetForwardVector reads
            // +0x90 = row 2 of the matrix at +0x70); facing render (cos h, sin h, 0) = physics (-sin h, 0, cos h)
            float h = headingDeg * 3.14159265f / 180.0f, c = cosf(h), s = sinf(h);
            float m[16] = {c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1};
            ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x70)))(rb, m);
            float f[3] = {0, 0, 0};
            ((GetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x34)))(rb, f);
            sprintf(heading, "heading %.1f deg set: forward physics (%.3f, %.3f, %.3f) = render (%.3f, %.3f, %.3f)",
                    headingDeg, f[0], f[1], f[2], f[2], -f[0], f[1]);
        }
        static const float zero[3] = {0, 0, 0};
        ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x60)))(rb, zero);
        ((SetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x64)))(rb, zero);
        sprintf(velocity, "velocity zeroed (rigid body vtable 0x%08lX)", (unsigned long)vtbl);
    }
    else
        sprintf(velocity, "velocity not zeroed and heading not set (rigid body vtable 0x%08lX not known)",
                (unsigned long)vtbl);
    Log("%s from physics (%.2f, %.2f, %.2f) to render (%.2f, %.2f, %.2f) = physics (%.2f, %.2f, %.2f): %s; %s; %s",
        what, before[0], before[1], before[2], t[2], -t[0], t[1], t[0], t[1], t[2],
        ok ? "set" : "SetPosition returned false", velocity, heading);
}

// ---------------------------------------------------------------- the way back (small fixes 2026-11-03)
//
// Run E: after F7 the car fell for ever. ResetCar::ResetVehicle takes the oldest saved spot ("cookie"); those were
// recorded on F-Town's ground, which F7 had removed, so ResetTo -> SetVehicleOnGround failed and, the cookies not
// being cleared on failure (ResetCar.cpp:337-348), failed again every frame. So before the unload the car is put back
// where it was at F8, in the order the game's own jumps use (GManager::WarpToMarker 0x5EBC80,
// Game_WarpPlayerToTrigger 0x611570): Sim::SetStream (they clear the zone-switching byte, which in gameplay is 0
// anyway; we refuse when it is set, see ReturnHome); here blocking (as
// DebugWorld::HandleJumpToHotPosition), so Rockport is loaded before anything else runs. F-Town stays loaded
// meanwhile, so the car is never without ground. The streamer then follows the car's body (Camera/CameraMover.cpp:
// 270-279 takes the player's rigid body position), which is at the saved spot from the next frame on.

static void SaveHome(void* player)
{
    g_haveHome = PlayerPosition(player, g_home);
    g_homeHeading = 0;
    DWORD vtbl = 0;
    void* rb = PlayerRigidBody(player, &vtbl);
    float f[3] = {0, 0, 0};
    if (rb && (vtbl == kRBVehicleVtbl || vtbl == kRigidBodyVtbl))
        ((GetVecFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(vtbl + 0x34)))(rb, f);
    // physics forward (-sin h, y, cos h) = render (cos h, sin h): h = atan2(-f.x, f.z)
    if (f[0] * f[0] + f[2] * f[2] > 1e-6f)
        g_homeHeading = atan2f(-f[0], f[2]) * 180.0f / 3.14159265f;
}

typedef void*(__thiscall* FindFn)(void*, DWORD);
typedef void(__thiscall* SetResetFn)(void*, const float*, const float*);

// IResetable::SetResetPosition (ResetCar 0x6A4340): clears the cookie trail and adds one cookie at (position,
// direction) with flags 0 (no snap to the road network). Found as EResetPlayerCar (0x641E5F) and
// Game_WarpPlayerToTrigger (0x611642) find interfaces: Find(handle) on the ISimable's +4.
// The reset's spot: IResetable::SetResetPosition (clears the cookie trail, one cookie at pos, physics, facing heading).
// Run K item 5: since the race's start moved to F-Town before the game's countdown (Run J), the event is placed before
// the car's ResetCar exists (Run K log: "found 0x00000000" at every start). A refused spot is kept and tried again every
// frame (ResetSpotFrame) until the IResetable is there, as long as the car has not driven 8 m from it (after that the
// game's own cookie trail is on F-Town's road, the better spot); a newer spot replaces it, the track's unload drops it.
static const float kResetLateMetres = 8.0f;
static struct
{
    bool on;
    float pos[3], heading;
    char what[48];
    int frames;
    bool anchored;  // the review: the 8 m are counted from where the car was at the game's GO (Free Roam drifts before)
    float anchor[3];
} g_resetLate;
static bool RaceBeforeGo();  // FTownGame.h: a bonus race of ours not yet at the game's GO

static void ResetSpotDrop(const char* why)
{
    if (!g_resetLate.on)
        return;
    g_resetLate.on = false;
    Log("reset cookies for %s dropped (%s)", g_resetLate.what, why);
}

static bool TrySetResetSpot(void* player, const float* pos, float headingDeg, DWORD* found, DWORD* vtbl)
{
    void* simable = ((GetPtrFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(Vtbl(player) + 0x04)))(player);
    DWORD list = 0;
    void* resetable = nullptr;
    if (simable && ReadDword((DWORD)(UINT_PTR)simable + 4, &list) && list)
        resetable = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kIResetableHandle);
    DWORD v = resetable ? Vtbl(resetable) : 0;
    *found = (DWORD)(UINT_PTR)resetable, *vtbl = v;
    if (v != kResetableVtbl)
        return false;
    float h = headingDeg * 3.14159265f / 180.0f;
    float dir[3] = {-sinf(h), 0, cosf(h)};
    ((SetResetFn)(UINT_PTR)(*(DWORD*)(UINT_PTR)(v + 0x0C)))(resetable, pos, dir);
    return true;
}

static void SetResetSpot(void* player, const float* pos, float headingDeg, const char* what)
{
    DWORD found = 0, v = 0;
    g_resetLate.on = false;
    if (TrySetResetSpot(player, pos, headingDeg, &found, &v))
    {
        Log("reset cookies replaced by %s (ResetCar::SetResetPosition)", what);
        return;
    }
    g_resetLate.on = true;
    memcpy(g_resetLate.pos, pos, sizeof(g_resetLate.pos));
    g_resetLate.heading = headingDeg;
    strncpy(g_resetLate.what, what, sizeof(g_resetLate.what) - 1);
    g_resetLate.what[sizeof(g_resetLate.what) - 1] = 0;
    g_resetLate.frames = 0;
    g_resetLate.anchored = false;
    Log("reset cookies NOT replaced yet (%s): no ResetCar IResetable (found 0x%08lX, vtable 0x%08lX); tried again every "
        "frame until the car has driven %.0f m",
        what, (unsigned long)found, (unsigned long)v, kResetLateMetres);
}

// Once a frame while the player exists: a refused reset spot tried again (Run K item 5).
static void ResetSpotFrame(void* player)
{
    if (!g_resetLate.on)
        return;
    g_resetLate.frames++;
    float p[3];
    // before the game's GO the car waits (or drifts: Free Roam is not held), the spot stays; from the GO on (or at
    // once outside our races) it counts from where the car was then
    if (!RaceBeforeGo() && PlayerPosition(player, p) && !g_resetLate.anchored)
    {
        memcpy(g_resetLate.anchor, p, sizeof(p));
        g_resetLate.anchored = true;
    }
    else if (g_resetLate.anchored && PlayerPosition(player, p) &&
             hypotf(p[0] - g_resetLate.anchor[0], p[2] - g_resetLate.anchor[2]) > kResetLateMetres)
    {
        g_resetLate.on = false;
        Log("reset cookies for %s given up after %d frames: the car is more than %.0f m from the spot (the game's own "
            "trail now)",
            g_resetLate.what, g_resetLate.frames, kResetLateMetres);
        return;
    }
    DWORD found = 0, v = 0;
    if (TrySetResetSpot(player, g_resetLate.pos, g_resetLate.heading, &found, &v))
    {
        g_resetLate.on = false;
        Log("reset cookies replaced by %s (ResetCar::SetResetPosition; late: %d frames)", g_resetLate.what,
            g_resetLate.frames);
    }
}

static void ReplaceCookies(void* player) { SetResetSpot(player, g_home, g_homeHeading, "the saved spot"); }

// true: the car is back in Rockport (or the way back is off), so the unload may go on; false: F-Town stays loaded.
static bool ReturnHome(void* player, const char* why)
{
    if (!g_returnEnabled)
    {
        Log("RETURN off ([Return] Enabled = 0): unloading with the car where it is (%s)", why);
        return true;
    }
    if (!g_haveHome)
    {
        Log("NOT RETURNED: no saved spot; F-Town stays loaded (%s)", why);
        return false;
    }
    DWORD sim = 0;
    if (!ReadDword(kSimSystem, &sim) || !sim)
    {
        Log("NOT RETURNED: the simulation is not running (Sim::Internal::mSystem is null); F-Town stays loaded (%s)",
            why);
        return false;
    }
    // review: the byte is set only by code that borrows the streamer's memory pool (the results screen's
    // SillyTextureStreamerManager 0x58E61F, the world map's UITrackMapStreamer 0x55A337, both then MakeSpaceInPool
    // 0x731040; an NIS; QuickGame with an intro NIS) and cleared by that code when it is done. The game's warps
    // (0x5EBD16, 0x6115A2) clear it only in gameplay, when nothing is borrowed. So streaming now could load sections
    // into lent-out memory: refuse.
    BYTE zoneOff = *(volatile BYTE*)(UINT_PTR)kZoneSwitchingDisabled;
    if (zoneOff)
    {
        Log("NOT RETURNED: the game has zone switching disabled (0x9AAC81 = %u: a menu, the results screen or a "
            "cut-scene is using the streamer's memory); F-Town stays loaded: press F7 again while driving (%s)",
            (unsigned)zoneOff, why);
        return false;
    }
    double t0 = NowMs();
    ((void(__cdecl*)(const float*, bool))(UINT_PTR)kSetStream)(g_home, true);
    double t1 = NowMs();
    Log("RETURN: Rockport streamed in at the saved spot (Sim::SetStream, blocking) in %.1f ms (%s)", t1 - t0, why);
    float probe[3] = {g_home[0], g_home[1] + 1.0f, g_home[2]}, h = 0;
    if (!HeightAt(probe, &h))
    {
        Log("NOT RETURNED: no face at the saved spot after streaming (render %.2f, %.2f, %.2f); F-Town stays loaded "
            "and the car stays on it (F7 again to retry, or quit the race)",
            g_home[2], -g_home[0], g_home[1]);
        return false;
    }
    Log("face at the saved spot: %.2f (car %.2f above)", h, g_home[1] - h);
    Teleport(player, g_home, g_homeHeading, true, "RETURNED");
    ReplaceCookies(player);
    g_haveHome = false;
    return true;
}

// the events' list (ftown-events.json), then the minimap and the events' runs: F-Town's own files, sharing this
// file's helpers
#include "FTownEvents.h"
#include "FTownRace.h"
// the course line on the minimap (Run J item 7: FTown's own file, sharing the minimap's and the events' state)
#include "FTownCourse.h"
// F-Town (Evening): the time held and the lights (FTown's own file, sharing this file's helpers)
#include "FTownEvening.h"

static DWORD g_checkAt[2];  // tick counts for the two position checks after a teleport

// Hands a set's file to the game: refuses (nothing loaded, false, *failed null) when a number is taken, the grid
// cannot be read, there is no memory or the file is gone or changed; otherwise LoadChunks, checks every section and
// pack was filed and registers the collision in the grid. When that fails, *failed names why (false, the chunks still
// loaded: the caller unloads them). `failWord` starts the failure lines ("NOT TELEPORTED" for the city).
static bool SetLoadChunks(MapSet& m, const char* failWord, const char** failed)
{
    *failed = nullptr;
    if (!NumbersFree(m))
        return false;
    Grid g;
    if (!ReadGrid(&g))
    {
        Log("%sREFUSED: the world grid (0x9B38A8) cannot be read", m.prefix);
        return false;
    }
    FreePending(m, true);
    if (&m == &g_city)
        MinimapFlush();
    double t0 = NowMs();
    BYTE* buffer = (BYTE*)VirtualAlloc(nullptr, m.size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!buffer)
    {
        Log("%sREFUSED: no memory for a %lu-byte buffer", m.prefix, (unsigned long)m.size);
        return false;
    }
    // a fresh copy every time (the loaders resolve chunks in place), read from disk: nothing is kept between loads
    if (!ReadAgain(m, buffer))
    {
        VirtualFree(buffer, 0, MEM_RELEASE);
        return false;
    }
    if (&m == &g_city)
        EveningApply(buffer);  // F-Town (Evening): the lights in this copy only
    double t1 = NowMs();
    ((LoadChunksFn)(UINT_PTR)kLoadChunks)(buffer, (int)m.size, m.chunkName);
    m.buffer = buffer;
    double t2 = NowMs();
    Log("%sLOADED %s: %lu bytes read in %.1f ms, LoadChunks %.1f ms; %d scenery sections, %d collision packs", m.prefix,
        m.name, (unsigned long)m.size, t1 - t0, t2 - t1, m.sectionCount, m.packCount);
    bool allFiled = true;
    for (int k = 0; k < m.sectionCount; k++)
    {
        DWORD info = 0, header = 0;
        ReadDword(kUserInfoTable + 4 * m.sections[k], &info);
        if (info)
            ReadDword(info + 4, &header);
        bool ours = header >= (DWORD)(UINT_PTR)buffer && header < (DWORD)(UINT_PTR)buffer + m.size;
        allFiled &= ours;
        Log("%sscenery section %d filed: %s (header 0x%08lX)", m.prefix, m.sections[k], ours ? "yes" : "NO",
            (unsigned long)header);
    }
    DWORD list = 0;
    ReadDword(kPackListPtr, &list);
    for (int k = 0; k < m.packCount; k++)
    {
        DWORD pack = 0;
        if (list)
            ReadDword(list + 4 * m.packs[k], &pack);
        allFiled &= pack != 0;
        Log("%scollision pack %d filed: %s (0x%08lX)", m.prefix, m.packs[k], pack ? "yes" : "NO", (unsigned long)pack);
    }
    if (!allFiled)
    {
        Log("%s%s: the game did not file our chunks", m.prefix, failWord);
        *failed = "not filed";
        return false;
    }
    double t3 = NowMs();
    if (!Register(m, g))
    {
        Log("%s%s: grid registration failed", m.prefix, failWord);
        *failed = "grid registration failed";
        return false;
    }
    Log("%sgrid: %d instances in %d packs, %d entries in %d cells (%d nodes of ours for empty cells), %.2f ms; tags "
        "per cell: max %d, median %d",
        m.prefix, m.instCount, m.packCount, m.regCount, m.cellsTouched, m.madeCount, NowMs() - t3, m.tagsMax,
        m.tagsMedian);
    return true;
}

// F-Town's chunks and collision only (no car yet): Run J item 1 loads them when the race's intro is placed on F-Town,
// before the game puts any car down there. False (nothing loaded) when refused or failed.
static bool LoadCity(const char* failWord)
{
    if (g_city.buffer)
        return true;
    // moving traffic: F-Town's network appended and the grid widened first (the city's collision goes into our
    // nodes); kept until the track unloads, or put back now when the city does not load
    bool fresh = !RoadNetInstalled() && RoadNetPrepare();
    const char* failed = nullptr;
    if (!SetLoadChunks(g_city, failWord, &failed))
    {
        if (failed)
            Unload(failed);
        if (fresh)
            RoadNetRestore("the city did not load");
        return false;
    }
    return true;
}

static void Load(void* player)
{
    double t0 = NowMs();
    // review: loaded for the race's intro, the car may already be on F-Town (the intro): no home spot saved then
    bool forIntro = g_city.buffer && g_cityForIntro;
    if (g_city.buffer)
        Log("F-Town already loaded (for the race's intro): the car to spawn 1");
    else if (!LoadCity("NOT TELEPORTED"))
        return;
    g_cityForIntro = false;
    const float* s0 = g_spawns[0];
    float sp[3] = {-s0[1], s0[2], s0[0]}, h = 0;
    double t4 = NowMs();
    bool face = HeightAt(sp, &h);
    double t5 = NowMs();
    if (!face)
    {
        Log("NOT TELEPORTED: no face at spawn (height query %.3f ms)", t5 - t4);
        Unload("no face at spawn");
        return;
    }
    Log("height at spawn 1: face at %.2f (spawn %.2f above), query %.3f ms; F8 to here %.1f ms", h, sp[1] - h,
        t5 - t4, t5 - t0);
    if (!forIntro)
        SaveHome(player);
    Teleport(player, sp, s0[3], g_setHeading, "TELEPORT");
    g_spawnAt = 0;
    MinimapLoad();
    EveningOn();
    DWORD now = GetTickCount();
    g_checkAt[0] = now + 1000;
    g_checkAt[1] = now + 3000;
}

// ---------------------------------------------------------------- the Time Attack's race barriers (R7)
//
// Each event's own file (ftown-events.json "barriers": tools/citymap/race_barriers.py): Rockport's race-barrier panels
// (X0's, by hash) and walls sealing its route. Every file uses section and pack 1409, so only one is loaded at a time:
// the running event's, loaded when it begins (F-Town loaded), kept while it is restarted, taken out when another
// event begins and with F-Town (and on F6 with the keys on). Free Roam never loads any.

static void BarriersStart()
{
    if (!g_barEnabled)
    {
        Log("barriers off ([Barriers] Enabled = 0)");
        return;
    }
    char dir[MAX_PATH];
    strcpy(dir, g_iniPath);
    char* slash = strrchr(dir, '\\');
    if (slash)
        slash[1] = 0;
    else
        dir[0] = 0;
    for (int k = 0; k < g_eventCount; k++)
    {
        MapSet& m = g_bars[k];
        if (!g_events[k].barriers[0])
            continue;
        strncpy(m.name, g_events[k].barriers, sizeof(m.name) - 1);
        snprintf(m.path, sizeof(m.path), "%s%s", dir, m.name);
        if (!ReadMapFile(m))
            Log("barriers: %s runs without barriers", g_events[k].name);
    }
}

static void BarriersUnloadSet(MapSet& m, const char* why)
{
    if (!m.buffer)
        return;
    double ms = SetUnloadChunks(m, why);
    Log("barriers: UNLOADED %s (%s): UnloadChunks %.1f ms; the buffer is freed %d frames later", m.name, why, ms,
        kFreeAfterFrames);
}

static void BarriersLoad(int k)
{
    if (!g_barEnabled || k < 0 || k >= g_eventCount || !g_city.buffer)
        return;
    for (int j = 0; j < g_eventCount; j++)
        if (j != k)
            BarriersUnloadSet(g_bars[j], "another event");  // the same numbers: out before the next set goes in
    MapSet& m = g_bars[k];
    if (!m.parsed || m.buffer)
        return;
    const char* failed = nullptr;
    if (!SetLoadChunks(m, "NOT LOADED", &failed) && failed)
    {
        double ms = SetUnloadChunks(m, failed);
        Log("barriers: UNLOADED (%s): UnloadChunks %.1f ms", failed, ms);
    }
}

static void BarriersUnload(const char* why)
{
    for (int k = 0; k < g_eventCount; k++) BarriersUnloadSet(g_bars[k], why);
}

static bool BarriersLoaded(int* which)
{
    for (int k = 0; k < g_eventCount; k++)
        if (g_bars[k].buffer)
        {
            if (which)
                *which = k;
            return true;
        }
    return false;
}

// F6 while loaded: the next spawn (round to the first), checked for a face as Load checks the first.
static void NextSpawn(void* player)
{
    TimeAttackStop("next spawn key");
    BarriersUnload("next spawn key");
    int k = (g_spawnAt + 1) % g_spawnCount;
    const float* s = g_spawns[k];
    float sp[3] = {-s[1], s[2], s[0]}, h = 0;
    if (!HeightAt(sp, &h))
    {
        Log("NOT MOVED: no face at spawn %d (render %.2f, %.2f, %.2f); the car stays", k + 1, s[0], s[1], s[2]);
        return;
    }
    Log("height at spawn %d: face at %.2f (spawn %.2f above)", k + 1, h, sp[1] - h);
    char what[32];
    snprintf(what, sizeof(what), "NEXT SPAWN %d", k + 1);
    Teleport(player, sp, s[3], g_setHeading, what);
    g_spawnAt = k;
    DWORD now = GetTickCount();
    g_checkAt[0] = now + 1000;
    g_checkAt[1] = now + 3000;
}

static void AfterCheck(void* player, int k)
{
    float p[3], h = 0;
    if (!PlayerPosition(player, p))
        return;
    float q[3] = {p[0], p[1] + 1.0f, p[2]};
    bool face = HeightAt(q, &h);
    char ht[64];
    if (face)
        sprintf(ht, "face at %.2f (car %.2f above)", h, p[1] - h);
    else
        strcpy(ht, "no face");
    Log("AFTER %d s: render (%.2f, %.2f, %.2f), %s", k ? 3 : 1, p[2], -p[0], p[1], ht);
}

// the game mode: the menu and the race that carries F-Town (FTown's own file, sharing this file's helpers)
#include "FTownGame.h"
// the traffic cars (FTown's own file, sharing this file's helpers and the game mode's state)
#include "FTownTraffic.h"
// moving traffic (FTown's own file: F-Town's road network for the game's AI, the widened grid, the spawn and speed hooks)
#include "FTownRoadNet.h"
// the breakable poles (FTown's own file: Rockport's smackable spawners for F-Town's poles, the override table extended)
#include "FTownSmack.h"
// the career's connection to Rockport (FTown's own file: the road, the zones, the walls, F-Town by the car's place)
#include "FTownConnect.h"

// ---------------------------------------------------------------- once a frame, and the track unload hook

static bool g_goWasDown, g_unloadWasDown, g_nextWasDown, g_taWasDown, g_nevWasDown, g_hadPlayer;

static void FrameWork()
{
    FreePending(g_city, false);
    for (int k = 0; k < kMaxEvents; k++) FreePending(g_bars[k], false);
    FreePending(g_smk, false);  // the breakable poles' copy (review: also when there is no player)
    FreePending(g_lnSet, false);  // the connector's copy
    void* player = Player();
    if (!player)
    {
        if (g_hadPlayer)
        {
            Log("player gone");
            ResetSpotDrop("player gone");
            Unload("player gone");
        }
        g_hadPlayer = false;
        g_checkAt[0] = g_checkAt[1] = 0;
        return;
    }
    if (!g_hadPlayer)
    {
        Log("player found");
        g_lnTrackGone = false;  // FTownConnect.h: a track (the next one) is there again
    }
    g_hadPlayer = true;
    GameFrame(player);
    LinkFrame(player);  // the career's connection: on and off by the car's place, F-Town in and out
    SmkFrame();  // the breakable poles once F-Town is loaded and the simulation exists
    bool keys = g_keysEnabled;
    bool go = keys && KeyDown(g_keyGo), un = keys && KeyDown(g_keyUnload), nx = keys && KeyDown(g_keyNext),
         ta = keys && g_taEnabled && KeyDown(g_taKey), nev = keys && g_taEnabled && KeyDown(g_taNextKey);
    bool goEdge = go && !g_goWasDown, unEdge = un && !g_unloadWasDown, nextEdge = nx && !g_nextWasDown;
    bool taEdge = ta && !g_taWasDown, nevEdge = nev && !g_nevWasDown;
    g_nevWasDown = nev;
    g_goWasDown = go;
    g_unloadWasDown = un;
    g_nextWasDown = nx;
    g_taWasDown = ta;
    if (goEdge || unEdge || nextEdge || taEdge || nevEdge)
    {
        if (!GameInFront())
            Log("key ignored: the game window is not in front");
        else if (taEdge && !goEdge && !unEdge && !nextEdge)
            TimeAttackKey(player);
        else if (nevEdge && !goEdge && !unEdge && !nextEdge)
            NextEventKey(player);
        else if (nextEdge && !goEdge && !unEdge)
        {
            if (!g_city.buffer)
                Log("next spawn key: nothing loaded");
            else
                NextSpawn(player);
        }
        else if (unEdge)
        {
            if (!g_city.buffer)
                Log("unload key: nothing loaded");
            else if (ReturnHome(player, "unload key"))
                Unload("unload key");
        }
        else if (g_city.buffer)
        {
            if (ReturnHome(player, "second go key while loaded"))
                Unload("second go key while loaded");
        }
        else
        {
            g_eveWanted = g_eveKeys;  // F8: the day, or the evening with [Evening] Keys = 1
            Load(player);
        }
    }
    if (g_city.buffer)
        EveningFrame();
    if (g_city.buffer || g_mmPending)
    {
        LARGE_INTEGER a, b;
        QueryPerformanceCounter(&a);
        MinimapFrame(player);
        TimeAttackFrame(player);
        QueryPerformanceCounter(&b);
        if (g_city.buffer)
        {
            double us = (double)(b.QuadPart - a.QuadPart) * 1e6 / (double)g_qpcFreq.QuadPart;
            g_costFrames++;
            g_costSum += us;
            if (us > g_costMax)
                g_costMax = us;
        }
    }
    ResetSpotFrame(player);  // Run K item 5: a reset spot the car's ResetCar was not there for yet
    TrafficFrame(player);  // after the keys and the game mode: F-Town loaded and the car moved this frame
    RoadNetFrame();        // the running event's route marked for the game's traffic (moving traffic)
    for (int k = 0; k < 2; k++)
        if (g_checkAt[k] && (int)(GetTickCount() - g_checkAt[k]) >= 0)
        {
            g_checkAt[k] = 0;
            if (g_city.buffer)
            {
                AfterCheck(player, k);
                EveningAfter(k);
            }
        }
}

extern "C" unsigned __cdecl FtFrame()
{
    unsigned ticks = ((unsigned(__cdecl*)())(UINT_PTR)kGetTicker)();
    FrameWork();
    return ticks;
}

static void* g_trTrackUnload;

static void __fastcall HkTrackUnload(void* self, void* edx)
{
    LinkTrackUnload();  // walls, zones and the join back, the connector out, while the track is all there
    TrafficRemove("track unloading");
    ManualOff("track unloading");
    ResetSpotDrop("track unloading");  // (Run K item 5) the car goes with the track
    if (g_city.buffer)
    {
        Log("TrackLoader::Unload: the track is being unloaded");
        Unload("track unloading");
    }
    MinimapFlush();  // a pack still waiting its few frames goes now, with the HUD
    GameTrackUnload();
    RoadNetRestore("track unloading");  // Rockport's network and grid back before the game's own unload
    ((void(__fastcall*)(void*, void*))g_trTrackUnload)(self, edx);
}

static bool WriteCode(DWORD at, const BYTE* bytes, int n)
{
    DWORD old;
    if (!VirtualProtect((void*)(UINT_PTR)at, n, PAGE_EXECUTE_READWRITE, &old))
        return false;
    memcpy((void*)(UINT_PTR)at, bytes, n);
    VirtualProtect((void*)(UINT_PTR)at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)(UINT_PTR)at, n);
    return true;
}

static bool Install()
{
    // the unload hook first (a trampoline of the 6 whole instructions it overwrites, none position-dependent)
    BYTE* t = (BYTE*)VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t)
        return false;
    memcpy(t, (const void*)(UINT_PTR)kTrackUnload, 6);
    t[6] = 0xE9;
    *(DWORD*)(t + 7) = (kTrackUnload + 6) - ((DWORD)(UINT_PTR)t + 11);
    FlushInstructionCache(GetCurrentProcess(), t, 32);
    g_trTrackUnload = t;
    BYTE jmp[6] = {0xE9, 0, 0, 0, 0, 0x90};
    *(DWORD*)(jmp + 1) = (DWORD)(UINT_PTR)&HkTrackUnload - (kTrackUnload + 5);
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)&FtFrame - (kFrameSite + 5);
    return WriteCode(kTrackUnload, jmp, 6) && WriteCode(kFrameSite, call, 5);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_DETACH)
    {
        ManualOff("the game is closing");
        if (g_log)
        {
            Log("FTownLoader unloading%s", g_city.buffer ? " (the map was still loaded)" : "");
            fclose(g_log);
            g_log = nullptr;
        }
        return TRUE;
    }
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    QueryPerformanceFrequency(&g_qpcFreq);
    QueryPerformanceCounter(&g_qpcStart);
    AddVectoredExceptionHandler(1, OnFault);
    char path[MAX_PATH], dir[MAX_PATH];
    GetModuleFileNameA(instance, path, MAX_PATH);
    strcpy(dir, path);
    char* slash = strrchr(dir, '\\');
    if (slash)
        slash[1] = 0;
    else
        dir[0] = 0;
    char* dot = strrchr(path, '.');
    strcpy(dot, ".ini");
    strcpy(g_iniPath, path);
    if (GetPrivateProfileIntA("Log", "Enabled", 1, g_iniPath) == 1)
    {
        strcpy(dot, ".log");
        g_log = fopen(path, "w");
    }
    Log("FTownLoader loaded (F-Town stage 2: a city of several sections and packs)");
    LoadSettings(dir);
    MinimapSettings(dir);
    IconSettings();  // Run K item 1: the safe house's sticky icon
    CourseSettings();
    TimeAttackSettings(dir);
    GameSettings();
    TrafficSettings(dir);
    RoadNetSettings(dir);
    EveningSettings(dir);
    SmkSettings(dir);
    LinkSettings(dir);
    g_testKey = (TestKeyFn)(void*)GetProcAddress(GetModuleHandleA(nullptr), "FTownTestKey");
    g_testForeground = (TestForegroundFn)(void*)GetProcAddress(GetModuleHandleA(nullptr), "FTownTestForeground");
    if (!CheckAll())
    {
        Log("WRONGBYTES: not the expected speed.exe v1.3 (or another module changed it); FTownLoader does nothing");
        return TRUE;
    }
    if (!ReadMapFile(g_city))
        return TRUE;
    MinimapStart();
    IconStart();
    CourseStartUp();
    TimeAttackStart();  // the events' list first: each event names its barrier file
    HudStart();         // the race HUD's timer, COMPLETE %, radar and the Drag's gears (Run I fixes)
    DragSteerInstall();  // our drag race steered by the player (Run J item 4)
    BarriersStart();
    EveningStart();
    SmkStart();  // the breakable poles (after the city's numbers: the packs' sections are checked against them)
    LinkStart();  // the career's connection to Rockport (its data and the connector's file)
    if (!Install())
    {
        Log("refused: the hook sites could not be made writable; FTownLoader does nothing");
        return TRUE;
    }
    Log("hooked 0x%08lX (per frame) and 0x%08lX (TrackLoader::Unload); key 0x%02X loads %s and moves the car to "
        "render (%.2f, %.2f, %.2f) heading %.1f, key 0x%02X unloads, key 0x%02X moves to the next of %d spawns",
        (unsigned long)kFrameSite, (unsigned long)kTrackUnload, g_keyGo, g_city.name, g_spawns[0][0], g_spawns[0][1],
        g_spawns[0][2], g_spawns[0][3], g_keyUnload, g_keyNext, g_spawnCount);
    GameStart();
    HudFeaturesStart();  // Run K item 2: Free Roam without the race HUD's timer, COMPLETE % and position
    TrafficStart();
    RoadNetStart();
    return TRUE;
}
