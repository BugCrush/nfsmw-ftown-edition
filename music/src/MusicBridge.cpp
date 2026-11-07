// MusicBridge.asi - the user's own MP3s in the game's EA Trax list, next to the original songs.
//
// What it does (design: docs/superpowers/specs/2026-10-04-custom-songs-design.md, facts and
// addresses: docs/music-notes.md):
//  - List: after the game builds its track list, one entry per file in CUSTOM SONGS is appended.
//  - Modes: the game's menu is pointed at a mode array of ours. The originals' modes are mirrored
//    to and from the profile save (which never grows); custom songs' modes go to
//    MusicBridge.songs.ini.
//  - Picking: the game's two functions that use a 28-bit number per song are replaced (Picker.h).
//  - Playing: when the game looks up one of our song IDs, we answer with a record of our own, keep
//    the game's stream channel from playing, and play the file ourselves (Player), reporting the
//    time remaining so the game moves on when the song ends. Every other ID is passed through.
// If CUSTOM SONGS is empty or missing, or the game's code isn't exactly speed.exe v1.3, nothing at
// all is installed.
//
// Hook locations and record layouts: XNFSMusicPlayer by xan1242 (MIT), confirmed by our own
// disassembly and by MusicProbe's logs.
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <string>
#include <vector>
#include "Detour.h"
#include "Picker.h"
#include "Player.h"
#include "SongData.h"
#include "SongName.h"

// ---------------------------------------------------------------------------------------------
// The game (speed.exe v1.3)

static const UINT_PTR kBuilder = 0x4DF330;      // fills the two pick records from the modes
static const UINT_PTR kPickerFn = 0x4F4CD0;     // picks the next song for a context
static const UINT_PTR kLookup = 0x82BFD0;       // event lookup: (id, mask) -> record, or 0
static const UINT_PTR kQueueCall = 0x830557;    // "call queue-node" inside the music system
static const UINT_PTR kQueueNode = 0x82FF80;
static const UINT_PTR kMenuRows = 0x5509D3;     // EA Trax menu: loads the mode array's address
static const UINT_PTR kMenuChange = 0x51E000;   // EA Trax menu, mode change: the same
static const UINT_PTR kReserve = 0x5AB070;      // the track list's reserve(n)
static const UINT_PTR kAlloc = 0x652AD0;        // the game's allocator (a jump to its malloc)
static const UINT_PTR kSlotStop = 0x8C5F3C, kSlotTimeLeft = 0x8C5F50, kSlotPlay = 0x8C5F58, kSlotVolume = 0x8C5F60;
static const UINT_PTR kStop = 0x82B5A0, kTimeLeft = 0x82B460, kPlay = 0x82B4A0, kVolume = 0x82B290;

static const UINT_PTR kList = 0x9123CC;         // the track list: +4 begin, +8 end, +0xC capacity end
static const UINT_PTR kTrackCount = 0x8F42C4;
static const UINT_PTR kRecords = 0x8F2080;      // two pick records: menus, races
static const UINT_PTR kSettingsRoot = 0x91CF90; // [[root]+0x10] = profile; +0x324 modes, +0x7C random
static const UINT_PTR kPaused = 0x91CAE4;

static const BYTE kBuilderCode[5] = { 0xA1, 0x90, 0xCF, 0x91, 0x00 };
static const BYTE kPickerCode[10] = { 0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x50, 0x01, 0x00, 0x00 };
static const BYTE kLookupCode[8] = { 0x55, 0x8B, 0xEC, 0xA1, 0x64, 0x29, 0x9C, 0x00 };
static const BYTE kMenuRowsCode[8] = { 0xA1, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x70, 0x10 };   // mov eax,[root]; mov esi,[eax+10h]
static const BYTE kMenuChangeCode[8] = { 0xA1, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x40, 0x10 }; // mov eax,[root]; mov eax,[eax+10h]
static const BYTE kReserveCode[10] = { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68, 0x40, 0x3D, 0x87, 0x00 };
// The next-song button's handler: "cmp [flow state], 3 / jne skip" lets it work in the menus only.
static const UINT_PTR kNextSongCheck = 0x5170C8;
static const BYTE kNextSongCode[9] = { 0x83, 0x3D, 0x90, 0x5E, 0x92, 0x00, 0x03, 0x75, 0x2C };
// That alone is not enough: the handler is called by the game's input dispatcher (0x559602), which
// never sees the button during a race (seen in the game: presses arrive, the handler isn't called,
// and the dispatcher's own skip on [0x91D8C0]/[0x91D8C4] is not the reason: both stay 0). So the
// controller plugin, which sees every press, calls MusicBridge_NextSong and we call the handler.
static const UINT_PTR kNextSongOwner = 0x91CAE0; // what the dispatcher passes as `this`

struct SongEntry { const char* title; const char* artist; const char* album; const char* defaultMode; DWORD id; }; // 20 bytes
struct PickRecord { DWORD enabled, left; int count, last, chosen; DWORD random; };                                  // 24 bytes

typedef void*(__cdecl* LookupFn)(DWORD id, DWORD mask);
typedef unsigned(__cdecl* QueueNodeFn)(void* track);
typedef void*(__cdecl* AllocFn)(unsigned size);
typedef void(__fastcall* ReserveFn)(void* list, void* edx, unsigned count);
typedef int(__fastcall* ChannelFn0)(void* self, void* edx);
typedef int(__fastcall* ChannelFn1)(void* self, void* edx, int a);
typedef int(__fastcall* ChannelFn5)(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e);

// ---------------------------------------------------------------------------------------------
// Log

static FILE* g_log;
static DWORD g_startTick;
static CRITICAL_SECTION g_logLock;
static int g_logCalls = 1;
static int g_skipInRaces = 1;

static void Log(const char* fmt, ...)
{
    if (!g_log)
        return;
    EnterCriticalSection(&g_logLock);
    fprintf(g_log, "[%8.3f] ", (GetTickCount() - g_startTick) / 1000.0);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log, fmt, args);
    va_end(args);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_logLock);
}

// A repeated message is logged at most once a second.
static bool OncePerSecond(DWORD* lastTick)
{
    DWORD now = GetTickCount();
    if (now - *lastTick < 1000)
        return false;
    *lastTick = now;
    return true;
}

// ---------------------------------------------------------------------------------------------
// Our songs

static const int kMaxSongs = 512;               // originals + custom; the size of our mode array
static const DWORD kFirstSongId = 0x00FFA000;   // custom song k gets ID 0x01FFA000 + k

struct CustomSong
{
    Song song;                 // file, path, title, artist
    std::string title, artist; // as the game can draw them
    unsigned char savedMode;   // what MusicBridge.songs.ini holds
};
static std::vector<CustomSong> g_songs;
static std::wstring g_songsIni;
static float g_gain = 1.0f;

static SavedMode g_modes[kMaxSongs];            // what the game's menu and our picker read
static SavedMode g_shadow[kMaxSongs];
static bool g_shadowValid;
static int g_originals = -1;                    // songs the game listed itself; -1 until first seen
static SongEntry* g_firstEntry;                 // our first entry in the game's list, to recognise it
static Picker g_picker(GetTickCount());

static BYTE* Profile()
{
    BYTE* root = *(BYTE**)kSettingsRoot;
    return root ? *(BYTE**)(root + 0x10) : nullptr;
}

// Appends our songs to the game's list if they aren't there (the game may rebuild its list).
static void EnsureSongsListed()
{
    int count = *(int*)kTrackCount;
    SongEntry** begin = *(SongEntry***)(kList + 4);
    SongEntry** end = *(SongEntry***)(kList + 8);
    if (!begin || count <= 0 || end - begin != count)
        return;
    int n = (int)g_songs.size();
    if (g_originals >= 0 && count == g_originals + n && begin[g_originals] == g_firstEntry)
        return; // already there
    if (count + n > kMaxSongs)
        n = kMaxSongs - count;
    if (n <= 0)
        return;

    ((ReserveFn)kReserve)((void*)kList, nullptr, (unsigned)(count + n));
    begin = *(SongEntry***)(kList + 4);
    end = *(SongEntry***)(kList + 8);
    SongEntry** capacity = *(SongEntry***)(kList + 0xC);
    if (!begin || end - begin != count || capacity - begin < count + n)
    {
        Log("list: could not make room for %d songs (the game's list did not grow); none added", n);
        return;
    }
    g_originals = count;
    for (int k = 0; k < n; ++k)
    {
        // The game frees every entry with its own allocator when it rebuilds the list, so ours
        // must come from that allocator too. The texts stay ours; the game doesn't free those.
        SongEntry* e = (SongEntry*)((AllocFn)kAlloc)(sizeof(SongEntry));
        e->title = g_songs[k].title.c_str();
        e->artist = g_songs[k].artist.c_str();
        e->album = "";
        e->defaultMode = "AL";
        e->id = 0x01000000 | (kFirstSongId + k);
        *end++ = e;
        if (k == 0)
            g_firstEntry = e;
        g_modes[count + k].number = count + k;
        g_modes[count + k].mode = g_songs[k].savedMode;
    }
    *(SongEntry***)(kList + 8) = end;
    *(int*)kTrackCount = count + n;
    g_shadowValid = false; // take the originals' modes from the profile afresh
    Log("list: %d original songs, %d custom songs added (numbers %d-%d)", count, n, count, count + n - 1);
}

// Keeps our mode array and the profile's in step, and saves custom songs' changes.
static void SyncModes()
{
    BYTE* profile = Profile();
    if (g_originals < 0 || !profile)
        return;
    ModeSyncResult r = SyncOriginalModes(g_modes, (SavedMode*)(profile + 0x324), g_shadow, &g_shadowValid, g_originals);
    if (r == kModesFromProfile)
        Log("modes: taken from the profile");
    else if (r == kModesToProfile)
        Log("modes: an original song's change written to the profile");
    int total = *(int*)kTrackCount;
    for (int k = 0; k < (int)g_songs.size() && g_originals + k < total; ++k)
    {
        SavedMode& m = g_modes[g_originals + k];
        m.number = g_originals + k;
        m.mode &= 3;
        if (m.mode != g_songs[k].savedMode)
        {
            g_songs[k].savedMode = m.mode;
            bool ok = SaveSongMode(g_songsIni, g_songs[k].song.file, m.mode);
            Log("modes: \"%s\" is now %ls%s", g_songs[k].title.c_str(), ModeName(m.mode), ok ? "" : " (could NOT be saved)");
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Replacements for the game's mask builder and picker

static void __cdecl BuildPicks(int resetLast)
{
    EnsureSongsListed();
    SyncModes();
    PickRecord* rec = (PickRecord*)kRecords;
    BYTE* profile = Profile();
    int count = *(int*)kTrackCount;
    DWORD random = profile ? *(DWORD*)(profile + 0x7C) : 0;
    for (int context = 0; context < 2; ++context)
    {
        int n = g_originals >= 0 ? CountEnabled(g_modes, count, context) : 0;
        rec[context].enabled = rec[context].left = n ? 1 : 0; // the rest of the game only asks "any?"
        rec[context].count = n;
        rec[context].random = random;
        if (resetLast)
            rec[context].last = -1;
    }
    if (g_logCalls)
        Log("picks: %d songs enabled in menus, %d in races, %s order", rec[0].count, rec[1].count, random ? "random" : "list");
}

static void __fastcall PickNext(void* eaTrax, void* edx)
{
    int context = *(int*)((BYTE*)eaTrax + 0x150);
    if (context != kContextMenus && context != kContextRaces)
        return;
    SyncModes();
    PickRecord* rec = (PickRecord*)kRecords + context;
    rec->chosen = g_originals >= 0 ? g_picker.Next(g_modes, *(int*)kTrackCount, context, rec->last, rec->random != 0) : -1;
    if (g_logCalls)
        Log("pick: %s -> song %d (after %d, %s)", context ? "races" : "menus", rec->chosen, rec->last, rec->random ? "random" : "list order");
}

// ---------------------------------------------------------------------------------------------
// Playing our songs

static LookupFn g_lookup;                       // the game's lookup (trampoline)
static QueueNodeFn g_queueNode;
static Player g_player;
static CRITICAL_SECTION g_playerLock;           // the pause watcher runs on its own thread
static int g_pending = -1;                      // our song the game has just looked up, not yet started
static DWORD g_pendingTick;                     // when it was looked up
static int g_playing = -1;                      // our song now playing
static void* g_channel;                         // the game's stream channel that "plays" it
static int g_volume = 127;                      // last level the game set (0..127)
static bool g_pausedNow;
static int g_handle = 1;                        // what play returns: 0x101, 0x201, ... like the game's
static DWORD g_songStartTick;
// What the game gets for one of our IDs: the shape of its own records for a song, as used by
// XNFSMusicPlayer. The fourth field carries the ID.
static DWORD g_record[11] = { 0, 0, 0, 0, 0, 0x11000001, 0x000F0400, 0x01FFFFFF, 0x11000001, 0x00030400, 0x00FF0619 };

static int FindSong(DWORD id24)
{
    int k = (int)(id24 - kFirstSongId);
    return id24 >= kFirstSongId && k < (int)g_songs.size() ? k : -1;
}

static void ApplyVolume()
{
    g_player.SetVolume(g_volume / 127.0f * g_gain);
}

static void StartSong(int k, void* channel)
{
    EnterCriticalSection(&g_playerLock);
    ApplyVolume();
    g_player.Start(g_songs[k].song.path.c_str());
    g_pausedNow = *(BYTE*)kPaused != 0;
    if (g_pausedNow)
        g_player.Pause();
    g_playing = k;
    g_channel = channel;
    g_songStartTick = GetTickCount();
    LeaveCriticalSection(&g_playerLock);
    Log("song: start \"%s\" - %s (volume %d of 127)", g_songs[k].title.c_str(), g_songs[k].artist.c_str(), g_volume);
}

static void StopSong(const char* why)
{
    EnterCriticalSection(&g_playerLock);
    PlayerStats s = g_player.Stats();
    bool ended = g_player.Finished();
    g_player.Stop();
    int k = g_playing;
    g_playing = -1;
    LeaveCriticalSection(&g_playerLock);
    Log("song: stop \"%s\" (%s): played %.3f s of %.3f s, %s, %u gaps, error 0x%08lX, %.1f s since start", g_songs[k].title.c_str(), why,
        s.playedSeconds, s.durationSeconds, ended ? "reached the end" : "cut short", s.underruns, (unsigned long)s.error,
        (GetTickCount() - g_songStartTick) / 1000.0);
}

// Milliseconds of our song still to play; 0 when it has ended or failed.
static int RemainingMs()
{
    EnterCriticalSection(&g_playerLock);
    PlayerStats s = g_player.Stats();
    bool finished = g_player.Finished();
    LeaveCriticalSection(&g_playerLock);
    if (finished)
        return 0;
    if (!s.ready || s.durationSeconds <= 0)
        return 10000; // still opening
    int ms = (int)((s.durationSeconds - s.playedSeconds) * 1000.0);
    return ms > 1 ? ms : 1;
}

static void* __cdecl WrapLookup(DWORD id, DWORD mask)
{
    int k = FindSong(id & mask & 0x00FFFFFF);
    if (k < 0)
    {
        g_pending = -1;
        void* record = g_lookup(id, mask);
        if (g_logCalls)
            Log("lookup %08lX -> %s", (unsigned long)id, record ? "the game's" : "not found");
        return record;
    }
    g_pending = k;
    g_pendingTick = GetTickCount();
    g_record[3] = 0x02000000 | (id & 0x00FFFFFF);
    Log("lookup %08lX -> ours: \"%s\"", (unsigned long)id, g_songs[k].title.c_str());
    return g_record;
}

// Our song the game has looked up and is about to play, or -1. The game plays within a second of
// the lookup (16-46 ms normally, about 0.9 s across a loading screen); if it hasn't after 5 s it
// isn't going to, and a later, unrelated play must not start the song.
static int Pending()
{
    if (g_pending >= 0 && GetTickCount() - g_pendingTick > 5000)
    {
        Log("lookup of \"%s\" was not followed by a play: forgotten", g_songs[g_pending].title.c_str());
        g_pending = -1;
    }
    return g_pending;
}

static unsigned __cdecl WrapQueueNode(void* track)
{
    if (Pending() >= 0 || g_playing >= 0)
        return 0; // our song isn't made of the game's pieces
    return g_queueNode(track);
}

static int __fastcall WrapPlay(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e)
{
    if (Pending() >= 0)
    {
        if (g_playing >= 0)
            StopSong("another of ours starts");
        StartSong(g_pending, self);
        g_pending = -1;
        return g_handle += 0x100;
    }
    if (g_playing >= 0 && self == g_channel) // only the channel our song stands in for is held back
    {
        static DWORD lastLog;
        if (g_logCalls && OncePerSecond(&lastLog))
            Log("play %08lX %08lX %08lX kept from the game's channel while ours plays", (unsigned long)a, (unsigned long)b, (unsigned long)e);
        return g_handle += 0x100;
    }
    return ((ChannelFn5)kPlay)(self, edx, a, b, c, d, e);
}

static int __fastcall WrapStop(void* self, void* edx)
{
    if (g_playing >= 0)
        StopSong("the game stopped the music");
    return ((ChannelFn0)kStop)(self, edx);
}

static int __fastcall WrapTimeLeft(void* self, void* edx, int slot)
{
    if (g_playing >= 0 && self == g_channel && slot >= 0)
    {
        int result = slot < *(int*)((BYTE*)self + 0x18) ? RemainingMs() : -8;
        static DWORD lastLog;
        if (g_logCalls && slot == 0 && OncePerSecond(&lastLog))
            Log("time left: %d ms", result);
        return result;
    }
    return ((ChannelFn1)kTimeLeft)(self, edx, slot);
}

static int __fastcall WrapVolume(void* self, void* edx, int volume)
{
    if (volume >= 0 && volume <= 127)
    {
        g_volume = volume;
        if (g_playing >= 0)
        {
            EnterCriticalSection(&g_playerLock);
            ApplyVolume();
            LeaveCriticalSection(&g_playerLock);
        }
    }
    return ((ChannelFn1)kVolume)(self, edx, volume);
}

// ---------------------------------------------------------------------------------------------
// Diagnostics for the next-song button (only with [Log] Calls = 1). The handler at 0x517070 does
// nothing when the music object's state ([0x91CB10] + 0x11C) is 3, 4 or 5, when the EA Trax menu is
// open, or (unless SkipInRaces removed it) when the flow state isn't 3.

static const UINT_PTR kNextSongFn = 0x517070, kMusicObject = 0x91CB10, kFlowState = 0x925E90;
static const BYTE kNextSongFnCode[8] = { 0xA1, 0x10, 0xCB, 0x91, 0x00, 0x83, 0xEC, 0x20 };
static ChannelFn0 g_nextSong; // the game's handler (trampoline)

// The music object's state, or -1 if there is no object. Read safely: the pointer is the game's.
static int MusicState(UINT_PTR* object)
{
    int state = -1;
    SIZE_T read = 0;
    *object = *(UINT_PTR*)kMusicObject;
    if (*object)
        ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(*object + 0x11C), &state, 4, &read);
    return state;
}

static int __fastcall WrapNextSong(void* self, void* edx)
{
    UINT_PTR object;
    int state = MusicState(&object);
    Log("next-song handler called: flow state %d, music object %08lX, music state %d, called from %p", *(int*)kFlowState,
        (unsigned long)object, state, __builtin_return_address(0));
    return g_nextSong(self, edx);
}

// Called by the controller plugin (InputBridge), on the game's own thread, each time the next-song
// button goes down. Returns 1 if the game's handler was run, 0 if the request was left alone: in
// the menus the game handles the button itself, and a paused game or a loading screen is no time
// to change the song. Flow state 6 is driving (race or free roam).
static bool g_installed;
extern "C" __declspec(dllexport) int __cdecl MusicBridge_NextSong()
{
    if (!g_installed || !g_skipInRaces || *(int*)kFlowState != 6 || *(BYTE*)kPaused)
        return 0;
    Log("next song: asked for by the controller plugin");
    ((ChannelFn0)kNextSongFn)(*(void**)kNextSongOwner, nullptr);
    return 1;
}

// The game doesn't call the channel to pause; its paused flag is the signal.
static DWORD WINAPI PauseWatcher(void*)
{
    int lastState = -2, lastFlow = -2;
    for (;;)
    {
        Sleep(20);
        if (g_logCalls)
        {
            UINT_PTR object;
            int state = MusicState(&object), flow = *(int*)kFlowState;
            if (state != lastState || flow != lastFlow)
            {
                Log("state: flow %d, music state %d", flow, state);
                lastState = state;
                lastFlow = flow;
            }
        }
        bool paused = *(BYTE*)kPaused != 0;
        EnterCriticalSection(&g_playerLock);
        if (g_playing >= 0 && paused != g_pausedNow)
        {
            g_pausedNow = paused;
            paused ? g_player.Pause() : g_player.Play();
            Log("song: %s", paused ? "paused with the game" : "resumed");
        }
        LeaveCriticalSection(&g_playerLock);
    }
}

// ---------------------------------------------------------------------------------------------
// Installing

static bool BytesAre(UINT_PTR addr, const BYTE* expected, size_t size)
{
    BYTE got[32];
    SIZE_T read = 0;
    return ReadProcessMemory(GetCurrentProcess(), (LPCVOID)addr, got, size, &read) && read == size && memcmp(got, expected, size) == 0;
}

static bool PointerIs(UINT_PTR addr, UINT_PTR expected)
{
    return BytesAre(addr, (const BYTE*)&expected, 4);
}

static void WriteBytes(UINT_PTR addr, const BYTE* bytes, size_t size)
{
    DWORD old;
    VirtualProtect((void*)addr, size, PAGE_EXECUTE_READWRITE, &old);
    memcpy((void*)addr, bytes, size);
    VirtualProtect((void*)addr, size, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void*)addr, size);
}

// Every place we change is checked first; if any one differs, nothing is changed at all.
static bool GameIsAsExpected()
{
    BYTE call[5] = { 0xE8 };
    LONG rel = (LONG)(kQueueNode - (kQueueCall + 5));
    memcpy(call + 1, &rel, 4);
    BYTE jump = 0xE9;
    struct { const char* what; bool ok; } checks[] = {
        { "mask builder", BytesAre(kBuilder, kBuilderCode, sizeof(kBuilderCode)) },
        { "picker", BytesAre(kPickerFn, kPickerCode, sizeof(kPickerCode)) },
        { "event lookup", BytesAre(kLookup, kLookupCode, sizeof(kLookupCode)) },
        { "queue-node call", BytesAre(kQueueCall, call, sizeof(call)) },
        { "menu rows", BytesAre(kMenuRows, kMenuRowsCode, sizeof(kMenuRowsCode)) },
        { "menu mode change", BytesAre(kMenuChange, kMenuChangeCode, sizeof(kMenuChangeCode)) },
        { "list reserve", BytesAre(kReserve, kReserveCode, sizeof(kReserveCode)) },
        { "allocator", BytesAre(kAlloc, &jump, 1) },
        { "play slot", PointerIs(kSlotPlay, kPlay) },
        { "stop slot", PointerIs(kSlotStop, kStop) },
        { "time-left slot", PointerIs(kSlotTimeLeft, kTimeLeft) },
        { "volume slot", PointerIs(kSlotVolume, kVolume) },
        { "next-song check", !g_skipInRaces || BytesAre(kNextSongCheck, kNextSongCode, sizeof(kNextSongCode)) },
        { "next-song handler", !g_skipInRaces || BytesAre(kNextSongFn, kNextSongFnCode, sizeof(kNextSongFnCode)) },
    };
    bool all = true;
    for (auto& c : checks)
        if (!c.ok)
        {
            Log("not as expected: %s", c.what);
            all = false;
        }
    return all;
}

static void Install()
{
    InstallDetour((void*)kBuilder, (void*)BuildPicks, sizeof(kBuilderCode), kBuilderCode);
    InstallDetour((void*)kPickerFn, (void*)PickNext, sizeof(kPickerCode), kPickerCode);
    g_lookup = (LookupFn)InstallDetour((void*)kLookup, (void*)WrapLookup, sizeof(kLookupCode), kLookupCode);

    g_queueNode = (QueueNodeFn)kQueueNode;
    BYTE call[5] = { 0xE8 };
    LONG rel = (LONG)((UINT_PTR)WrapQueueNode - (kQueueCall + 5));
    memcpy(call + 1, &rel, 4);
    WriteBytes(kQueueCall, call, sizeof(call));

    // Both menu sites load the profile's address into a register and later add 0x324 to reach
    // the modes. Load a constant instead, chosen so that +0x324 lands on our array.
    DWORD base = (DWORD)(UINT_PTR)g_modes - 0x324;
    BYTE rows[8] = { 0xBE, 0, 0, 0, 0, 0x90, 0x90, 0x90 };   // mov esi, base
    BYTE change[8] = { 0xB8, 0, 0, 0, 0, 0x90, 0x90, 0x90 }; // mov eax, base
    memcpy(rows + 1, &base, 4);
    memcpy(change + 1, &base, 4);
    WriteBytes(kMenuRows, rows, sizeof(rows));
    WriteBytes(kMenuChange, change, sizeof(change));

    SwapPointer((void**)kSlotPlay, (void*)kPlay, (void*)WrapPlay);
    SwapPointer((void**)kSlotStop, (void*)kStop, (void*)WrapStop);
    SwapPointer((void**)kSlotTimeLeft, (void*)kTimeLeft, (void*)WrapTimeLeft);
    SwapPointer((void**)kSlotVolume, (void*)kVolume, (void*)WrapVolume);
    if (g_skipInRaces)
    {
        // Remove the "jne skip" so the button also changes the song during a race. The handler then
        // asks for the next song exactly as it does in the menus; the pick uses the races record.
        const BYTE nops[2] = { 0x90, 0x90 };
        WriteBytes(kNextSongCheck + 7, nops, sizeof(nops));
    }
    if (g_logCalls && BytesAre(kNextSongFn, kNextSongFnCode, sizeof(kNextSongFnCode)))
        g_nextSong = (ChannelFn0)InstallDetour((void*)kNextSongFn, (void*)WrapNextSong, sizeof(kNextSongFnCode), kNextSongFnCode);
    CloseHandle(CreateThread(nullptr, 0, PauseWatcher, nullptr, 0, nullptr));
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    wchar_t path[MAX_PATH], prev[MAX_PATH], dir[MAX_PATH], folder[MAX_PATH], full[MAX_PATH], gain[32];
    GetModuleFileNameW(instance, path, MAX_PATH);
    wcscpy(dir, path);
    *wcsrchr(dir, L'\\') = 0;
    wchar_t* dot = wcsrchr(path, L'.');
    wcscpy(dot, L".prev.log");
    wcscpy(prev, path);
    wcscpy(dot, L".log");
    MoveFileExW(path, prev, MOVEFILE_REPLACE_EXISTING);
    InitializeCriticalSection(&g_logLock);
    InitializeCriticalSection(&g_playerLock);
    g_startTick = GetTickCount();
    g_log = _wfopen(path, L"w");

    wcscpy(dot, L".songs.ini");
    g_songsIni = path;
    wcscpy(dot, L".ini");
    GetPrivateProfileStringW(L"Songs", L"Folder", L"..\\..\\CUSTOM SONGS", folder, MAX_PATH, path);
    GetPrivateProfileStringW(L"Player", L"Gain", L"1.0", gain, 32, path);
    g_gain = (float)_wtof(gain);
    g_logCalls = GetPrivateProfileIntW(L"Log", L"Calls", 1, path);
    g_skipInRaces = GetPrivateProfileIntW(L"Songs", L"SkipInRaces", 1, path);
    std::wstring joined = (folder[0] && folder[1] == L':') || folder[0] == L'\\' ? std::wstring(folder) : std::wstring(dir) + L"\\" + folder;
    GetFullPathNameW(joined.c_str(), MAX_PATH, full, nullptr);

    std::vector<Song> found = ScanSongFolder(full);
    Log("MusicBridge loaded; %d songs in %ls", (int)found.size(), full);
    for (size_t k = 0; k < found.size(); ++k)
    {
        char fallback[32];
        snprintf(fallback, sizeof(fallback), "Custom song %d", (int)k + 1);
        CustomSong c;
        c.song = found[k];
        // A Title or Artist typed into MusicBridge.songs.ini replaces the one from the file's name,
        // and is passed to the game exactly as typed.
        std::wstring title = LoadSongText(g_songsIni, found[k].file, L"Title"), artist = LoadSongText(g_songsIni, found[k].file, L"Artist");
        c.title = title.empty() ? GameText(found[k].title, fallback) : GameText(title, fallback, true);
        c.artist = artist.empty() ? GameText(found[k].artist, "Unknown") : GameText(artist, "Unknown", true);
        c.savedMode = LoadSongMode(g_songsIni, found[k].file);
        Log("  \"%s\" - %s [%ls] file: %ls", c.title.c_str(), c.artist.c_str(), ModeName(c.savedMode), found[k].file.c_str());
        g_songs.push_back(c);
    }
    if (g_songs.empty())
    {
        Log("No songs: nothing installed; the game runs as it does without this plugin.");
        return TRUE;
    }
    if (!GameIsAsExpected())
    {
        Log("This is not speed.exe v1.3 as we know it, or another plugin changed the same places: nothing installed.");
        return TRUE;
    }
    Install();
    g_installed = true;
    Log("Installed (gain %.2f, call logging %s, next-song button in races %s).", g_gain, g_logCalls ? "on" : "off",
        g_skipInRaces ? "on" : "off");
    return TRUE;
}
