// Tests MusicBridge.asi without the game. This program builds a tiny imitation of the parts of
// speed.exe the plugin touches, at the game's own addresses (a 26-song track list, a profile with
// the mode array, the two pick records, stand-in functions for the music system), loads the plugin
// and drives it the way the game does.
//
// It needs one real MP3: the first one in the folder given as the first argument of the "main"
// run, by default ..\..\CUSTOM SONGS. It is hard-linked (not copied, not modified) into
// fixtures-songs under six test names. Everything plays at volume 0.
//
// Build (from music\tests):
//   zig c++ -target x86-windows-gnu -w -municode bridge-fakegame.cpp -o bridge-fakegame.exe -Wl,--image-base,0x10000000
// Run next to MusicBridge.asi:  bridge-fakegame.exe       (exit code 0 = all passed)
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <set>
#include <string>
#include <vector>
#include "../src/SongData.h"

static int failures;
static void Check(bool ok, const char* what, long got)
{
    printf("  %s %s (%ld / 0x%lX)\n", ok ? "ok  " : "FAIL", what, got, (unsigned long)got);
    if (!ok)
        ++failures;
}

// ---- the imitation game -----------------------------------------------------------------------

struct SongEntry { const char* title; const char* artist; const char* album; const char* defaultMode; DWORD id; };
struct PickRecord { DWORD enabled, left; int count, last, chosen; DWORD random; };
typedef void*(__cdecl* LookupFn)(DWORD id, DWORD mask);
typedef unsigned(__cdecl* QueueFn)(void* track);
typedef void(__cdecl* BuilderFn)(int reset);
typedef void(__fastcall* PickFn)(void* self, void* edx);
typedef int(__fastcall* Fn0)(void* self, void* edx);
typedef int(__fastcall* Fn1)(void* self, void* edx, int a);
typedef int(__fastcall* Fn5)(void* self, void* edx, DWORD a, DWORD b, DWORD c, DWORD d, DWORD e);

// Reads four bytes from any address (the values inside instructions are not aligned).
static DWORD Read32(UINT_PTR addr)
{
    DWORD value;
    memcpy(&value, (void*)addr, 4);
    return value;
}

static bool Place(UINT_PTR addr, const void* bytes, size_t size)
{
    void* block = VirtualAlloc((void*)(addr & ~0xFFFFu), 0x10000, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!block) // already reserved (by us, or by the system): commit just the pages we need
        block = VirtualAlloc((void*)(addr & ~0xFFFu), 0x2000, MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    if (!block)
        return false;
    memcpy((void*)addr, bytes, size);
    return true;
}

static void __fastcall FakeReserve(void* list, void* edx, unsigned count)
{
    DWORD* v = (DWORD*)list;
    size_t used = (v[2] - v[1]) / 4;
    DWORD* fresh = (DWORD*)malloc(count * 4);
    memcpy(fresh, (void*)v[1], used * 4);
    v[1] = (DWORD)(UINT_PTR)fresh;
    v[2] = (DWORD)(UINT_PTR)(fresh + used);
    v[3] = (DWORD)(UINT_PTR)(fresh + count);
}

static void* __cdecl FakeAlloc(unsigned size)
{
    return malloc(size);
}

static BYTE g_profile[0x1000];
static DWORD g_root[8];
static SongEntry g_original[26];
static char g_titles[26][16];

// A fresh 26-song list, as the game builds it.
static void BuildOriginalList()
{
    DWORD* array = (DWORD*)malloc(26 * 4);
    for (int i = 0; i < 26; ++i)
    {
        snprintf(g_titles[i], sizeof(g_titles[i]), "Original %d", i);
        g_original[i] = { g_titles[i], "Artist", "Album", "AL", 0x01000100u + i };
        SongEntry* e = (SongEntry*)malloc(sizeof(SongEntry));
        *e = g_original[i];
        array[i] = (DWORD)(UINT_PTR)e;
    }
    DWORD* list = (DWORD*)0x9123CC;
    list[1] = (DWORD)(UINT_PTR)array;
    list[2] = list[3] = (DWORD)(UINT_PTR)(array + 26);
    *(int*)0x8F42C4 = 26;
}

static bool PlaceGame(bool wrongPicker)
{
    const BYTE builder[] = { 0xA1, 0x90, 0xCF, 0x91, 0x00, 0xC3 };
    BYTE picker[] = { 0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x50, 0x01, 0x00, 0x00, 0x5E, 0x5B, 0xC3 };
    const BYTE lookup[] = { 0x55, 0x8B, 0xEC, 0xA1, 0x64, 0x29, 0x9C, 0x00, 0x33, 0xC0, 0x5D, 0xC3 }; // returns 0: not found
    const BYTE queueNode[] = { 0xB8, 0x05, 0x00, 0x00, 0x00, 0xC3 };                                  // returns 5
    const BYTE menuRows[] = { 0xA1, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x70, 0x10 };
    const BYTE menuChange[] = { 0xA1, 0x90, 0xCF, 0x91, 0x00, 0x8B, 0x40, 0x10 };
    const BYTE play[] = { 0xB8, 0x77, 0x07, 0x00, 0x00, 0xC2, 0x14, 0x00 };     // returns 0x777
    const BYTE stop[] = { 0xB8, 0x55, 0x00, 0x00, 0x00, 0xC3 };                 // returns 0x55
    const BYTE timeLeft[] = { 0xB8, 0x92, 0x10, 0x00, 0x00, 0xC2, 0x04, 0x00 }; // returns 4242
    const BYTE volume[] = { 0x8B, 0x44, 0x24, 0x04, 0xC2, 0x04, 0x00 };         // returns its argument
    // the next-song button's handler: "cmp [flow state], 3 / jne skip" (only in menus)
    const BYTE nextSong[] = { 0x83, 0x3D, 0x90, 0x5E, 0x92, 0x00, 0x03, 0x75, 0x2C };
    // the handler's entry: mov eax,[0x91CB10] / sub esp,20h; then (here) undo and return 0x66
    const BYTE nextSongEntry[] = { 0xA1, 0x10, 0xCB, 0x91, 0x00, 0x83, 0xEC, 0x20, 0x83, 0xC4, 0x20, 0xB8, 0x66, 0x00, 0x00, 0x00, 0xC3 };
    const DWORD three = 3;
    // In the game's input dispatcher, just before it calls the next-song handler:
    // mov al,[0x91D8C0] / test al,al / je +9 / mov eax,[0x91D8C4] / test eax,eax / jne skip
    const BYTE nextSongGate[] = { 0xA0, 0xC0, 0xD8, 0x91, 0x00, 0x84, 0xC0, 0x74, 0x09, 0xA1, 0xC4, 0xD8, 0x91, 0x00, 0x85, 0xC0, 0x75, 0x28 };
    if (wrongPicker)
        picker[4] = 0x90;

    BYTE queueCall[5] = { 0xE8 };
    LONG rel = (LONG)(0x82FF80 - (0x830557 + 5));
    memcpy(queueCall + 1, &rel, 4);
    // reserve: the game's first ten bytes, then undo them and jump to FakeReserve
    BYTE reserve[19] = { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68, 0x40, 0x3D, 0x87, 0x00, 0x83, 0xC4, 0x08, 0x5D, 0xE9 };
    rel = (LONG)((UINT_PTR)FakeReserve - (0x5AB070 + 19));
    memcpy(reserve + 15, &rel, 4);
    BYTE alloc[5] = { 0xE9 };
    rel = (LONG)((UINT_PTR)FakeAlloc - (0x652AD0 + 5));
    memcpy(alloc + 1, &rel, 4);

    const DWORD zero = 0, aStop = 0x82B5A0, aLeft = 0x82B460, aPlay = 0x82B4A0, aVolume = 0x82B290, pRoot = (DWORD)(UINT_PTR)g_root;
    const BYTE zeros[64] = {};
    bool ok = Place(0x4DF330, builder, sizeof(builder)) && Place(0x4F4CD0, picker, sizeof(picker))
        && Place(0x82BFD0, lookup, sizeof(lookup)) && Place(0x9C2964, &zero, 4) && Place(0x82FF80, queueNode, sizeof(queueNode))
        && Place(0x830557, queueCall, sizeof(queueCall)) && Place(0x5509D3, menuRows, sizeof(menuRows))
        && Place(0x51E000, menuChange, sizeof(menuChange)) && Place(0x5AB070, reserve, sizeof(reserve))
        && Place(0x652AD0, alloc, sizeof(alloc)) && Place(0x82B4A0, play, sizeof(play)) && Place(0x82B5A0, stop, sizeof(stop))
        && Place(0x82B460, timeLeft, sizeof(timeLeft)) && Place(0x82B290, volume, sizeof(volume))
        && Place(0x8C5F3C, &aStop, 4) && Place(0x8C5F50, &aLeft, 4) && Place(0x8C5F58, &aPlay, 4) && Place(0x8C5F60, &aVolume, 4)
        && Place(0x9123CC, zeros, 16) && Place(0x8F42C4, &zero, 4) && Place(0x8F2080, zeros, 48) && Place(0x91CF90, &pRoot, 4)
        && Place(0x91CAE4, &zero, 1) && Place(0x5170C8, nextSong, sizeof(nextSong))
        && Place(0x517070, nextSongEntry, sizeof(nextSongEntry)) && Place(0x91CB10, &zero, 4) && Place(0x925E90, &three, 4)
        && Place(0x5595C8, nextSongGate, sizeof(nextSongGate)) && Place(0x91D8C0, zeros, 8);
    if (!ok)
        return false;

    // The profile: 26 mode records as the game's defaults, then bytes that must never change.
    memset(g_profile, 0xAB, sizeof(g_profile));
    g_root[4] = (DWORD)(UINT_PTR)g_profile; // [root + 0x10]
    *(DWORD*)(g_profile + 0x7C) = 0;
    SavedMode* modes = (SavedMode*)(g_profile + 0x324);
    for (int i = 0; i < 26; ++i)
    {
        modes[i].number = i;
        modes[i].mode = (i == 0 || i == 8) ? kModeAll : i < 10 ? kModeMenus : kModeRaces;
        memset(modes[i].pad, 0xCD, 3);
    }
    BuildOriginalList();
    return true;
}

static std::string ReadLog(HMODULE plugin)
{
    char path[MAX_PATH];
    GetModuleFileNameA(plugin, path, MAX_PATH);
    strcpy(strrchr(path, '.'), ".log");
    std::string text;
    FILE* f = fopen(path, "rb");
    if (f)
    {
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), f)) > 0)
            text.append(buf, n);
        fclose(f);
    }
    return text;
}

static std::wstring Here()
{
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    *wcsrchr(path, L'\\') = 0;
    return path;
}

static void WriteIni(const wchar_t* folder, const wchar_t* skipInRaces = L"1")
{
    std::wstring ini = Here() + L"\\MusicBridge.ini";
    DeleteFileW(ini.c_str());
    WritePrivateProfileStringW(L"Songs", L"Folder", folder, ini.c_str());
    WritePrivateProfileStringW(L"Songs", L"SkipInRaces", skipInRaces, ini.c_str());
    WritePrivateProfileStringW(L"Log", L"Calls", L"1", ini.c_str());
    std::wstring songsIni = Here() + L"\\MusicBridge.songs.ini";
    DeleteFileW(songsIni.c_str());
    // what a user might type to change how one song is shown
    WritePrivateProfileStringW(L"Gamma_Third.mp3", L"Artist", L"Kr$na Crew", songsIni.c_str());
    WritePrivateProfileStringW(L"Epsilon_Fifth.mp3", L"Title", L"Epsilon (Live)", songsIni.c_str());
}

static const wchar_t* kTestNames[6] = { L"Alpha Song_First Artist.mp3", L"Beta_Second.mp3", L"Gamma_Third.mp3", L"Delta_Fourth.mp3",
    L"Epsilon_Fifth.mp3", L"\x0924\x0947\x0930\x093E_\x0915\x0932\x093E.mp3" };

static const wchar_t* kBrokenName = L"Epsilon_Fifth.mp3";

static bool MakeSongFolder(const std::wstring& sourceFolder)
{
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW((sourceFolder + L"\\*.mp3").c_str(), &fd);
    if (find == INVALID_HANDLE_VALUE)
        return false;
    FindClose(find);
    std::wstring source = sourceFolder + L"\\" + fd.cFileName, dir = Here() + L"\\fixtures-songs";
    CreateDirectoryW(dir.c_str(), nullptr);
    for (const wchar_t* name : kTestNames)
    {
        std::wstring target = dir + L"\\" + name;
        if (!wcscmp(name, kBrokenName))
        {
            // One song that can't be played. Delete first and create anew: an older run may have left
            // a hard link here, and writing through a link would write into the user's own file.
            DeleteFileW(target.c_str());
            HANDLE h = CreateFileW(target.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, 0, nullptr);
            if (h == INVALID_HANDLE_VALUE)
                return false;
            BYTE noise[4096];
            for (int i = 0; i < 4096; ++i)
                noise[i] = (BYTE)(i * 31 + 7);
            DWORD wrote;
            WriteFile(h, noise, sizeof(noise), &wrote, nullptr);
            CloseHandle(h);
        }
        else
        {
            // Copies, never links: nothing in this folder may reach the user's music. Earlier versions
            // of this test made hard links; removing a link's name leaves the user's file as it is.
            HANDLE h = CreateFileW(target.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, 0, nullptr);
            BY_HANDLE_FILE_INFORMATION info = {};
            bool linked = h != INVALID_HANDLE_VALUE && GetFileInformationByHandle(h, &info) && info.nNumberOfLinks > 1;
            if (h != INVALID_HANDLE_VALUE)
                CloseHandle(h);
            if (linked)
                DeleteFileW(target.c_str());
            if (GetFileAttributesW(target.c_str()) == INVALID_FILE_ATTRIBUTES && !CopyFileW(source.c_str(), target.c_str(), TRUE))
                return false;
        }
    }
    CreateDirectoryW((Here() + L"\\fixtures-empty").c_str(), nullptr);
    return true;
}

// ---- the three runs ---------------------------------------------------------------------------

static int RunMain()
{
    HMODULE plugin = LoadLibraryW(L"MusicBridge.asi");
    Check(plugin != nullptr, "MusicBridge.asi loaded", plugin != nullptr);
    if (!plugin)
        return 1;
    std::wstring songsIni = Here() + L"\\MusicBridge.songs.ini";
    DWORD* list = (DWORD*)0x9123CC;
    PickRecord* rec = (PickRecord*)0x8F2080;
    SavedMode* profileModes = (SavedMode*)(g_profile + 0x324);

    printf("installed\n");
    Check(*(BYTE*)0x4DF330 == 0xE9 && *(BYTE*)0x4F4CD0 == 0xE9, "builder and picker replaced", *(BYTE*)0x4DF330);
    Check(*(BYTE*)0x5509D3 == 0xBE && *(BYTE*)0x51E000 == 0xB8 && *(BYTE*)0x5509D8 == 0x90 && *(BYTE*)0x51E007 == 0x90,
        "both menu sites load a constant", *(BYTE*)0x5509D3);
    Check(*(BYTE*)0x5170CF == 0x90 && *(BYTE*)0x5170D0 == 0x90 && *(BYTE*)0x5170C8 == 0x83,
        "the next-song button is no longer limited to the menus", *(BYTE*)0x5170CF);
    int handled = ((Fn0)0x517070)(nullptr, nullptr);
    Check(handled == 0x66, "the next-song handler still runs when called (it is only logged)", handled);
    Check(*(BYTE*)0x5595D8 == 0x75 && *(BYTE*)0x5595D9 == 0x28, "the input dispatcher is left alone", *(BYTE*)0x5595D8);

    // The controller plugin calls this when the next-song button goes down.
    typedef int(__cdecl* NextSongFn)();
    NextSongFn nextSong = (NextSongFn)GetProcAddress(plugin, "MusicBridge_NextSong");
    Check(nextSong != nullptr, "MusicBridge_NextSong is exported", nextSong != nullptr);
    if (nextSong)
    {
        Check(nextSong() == 0, "in the menus (flow state 3) the request is left to the game", 0);
        *(int*)0x925E90 = 6;
        Check(nextSong() == 1, "during a race it runs the game's next-song handler", 0);
        *(BYTE*)0x91CAE4 = 1;
        Check(nextSong() == 0, "but not while the game is paused", 0);
        *(BYTE*)0x91CAE4 = 0;
        *(int*)0x925E90 = 3;
    }
    Check(Read32(0x5509D4) == Read32(0x51E001), "the same constant in both", (long)Read32(0x5509D4));
    SavedMode* modes = (SavedMode*)(UINT_PTR)(Read32(0x5509D4) + 0x324);

    printf("list\n");
    ((BuilderFn)0x4DF330)(1);
    SongEntry** entries = (SongEntry**)(UINT_PTR)list[1];
    int size = (int)((list[2] - list[1]) / 4);
    Check(*(int*)0x8F42C4 == 32 && size == 32, "26 originals + 6 custom songs", size);
    Check(size == 32 && !strcmp(entries[26]->title, "Alpha Song") && !strcmp(entries[26]->artist, "First Artist")
        && !strcmp(entries[26]->album, "") && entries[26]->id == 0x01FFA000, "first custom entry: title, artist, empty album, ID", 0);
    Check(size == 32 && !strcmp(entries[27]->title, "Beta") && !strcmp(entries[30]->title, "Gamma"), "sorted by title", 0);
    Check(size == 32 && !strcmp(entries[30]->artist, "Kr$na Crew") && !strcmp(entries[29]->title, "Epsilon (Live)")
        && !strcmp(entries[29]->artist, "Fifth"), "names typed into MusicBridge.songs.ini replace the file's, exactly as typed", 0);
    Check(size == 32 && !strcmp(entries[31]->title, "Custom song 6") && !strcmp(entries[31]->artist, "Unknown"),
        "a Hindi name the game can't draw gets a stand-in title", 0);
    Check(!strcmp(entries[3]->title, "Original 3"), "originals untouched", 0);
    Check(rec[0].count == 16 && rec[1].count == 24 && rec[0].enabled && rec[0].last == -1, "pick records: 10+6 in menus, 18+6 in races",
        rec[0].count * 100 + rec[1].count);
    Check(modes[5].mode == kModeMenus && modes[26].number == 26 && modes[26].mode == kModeAll, "our mode array: originals mirrored, custom All", modes[26].mode);
    bool untouched = true;
    for (int i = 0x324 + 26 * 8; i < 0x324 + 26 * 8 + 256; ++i)
        untouched = untouched && g_profile[i] == 0xAB;
    Check(untouched, "the profile after the 26th record is untouched", 0);

    printf("modes\n");
    modes[27].mode = kModeOff; // the user switches "Beta" off in the menu
    ((BuilderFn)0x4DF330)(0);
    Check(LoadSongMode(songsIni, L"Beta_Second.mp3") == kModeOff, "a custom song's mode is saved in MusicBridge.songs.ini", 0);
    Check(rec[0].count == 15 && rec[1].count == 23, "and it leaves both pick records", rec[0].count);
    modes[3].mode = kModeOff;  // the user switches an original off in the menu
    ((BuilderFn)0x4DF330)(0);
    Check(profileModes[3].mode == kModeOff, "an original's change reaches the profile", profileModes[3].mode);
    profileModes[5].mode = kModeAll; // the game loads a profile
    ((BuilderFn)0x4DF330)(0);
    Check(modes[5].mode == kModeAll, "a profile load reaches our array", modes[5].mode);
    for (int i = 0x324 + 26 * 8; i < 0x324 + 26 * 8 + 256; ++i)
        untouched = untouched && g_profile[i] == 0xAB;
    Check(untouched, "the profile after the 26th record is still untouched", 0);

    printf("picking\n");
    BYTE eaTrax[0x200] = {};
    *(int*)(eaTrax + 0x150) = 0; // menus
    rec[0].last = -1;
    const int expected[] = { 0, 1, 2, 4, 5, 6, 7, 8, 9, 26, 28, 29, 30, 31, 0 };
    bool order = true;
    for (int want : expected)
    {
        ((PickFn)0x4F4CD0)(eaTrax, nullptr);
        order = order && rec[0].chosen == want;
        rec[0].last = rec[0].chosen; // the game does this before the next pick
    }
    Check(order, "menus, list order: enabled songs in order, custom ones included, then round again", rec[0].chosen);
    *(DWORD*)(g_profile + 0x7C) = 1; // random order
    ((BuilderFn)0x4DF330)(1);
    *(int*)(eaTrax + 0x150) = 1; // races
    std::set<int> seen;
    bool above28 = false;
    for (int i = 0; i < 24; ++i)
    {
        ((PickFn)0x4F4CD0)(eaTrax, nullptr);
        seen.insert(rec[1].chosen);
        above28 = above28 || rec[1].chosen >= 28;
        rec[1].last = rec[1].chosen;
    }
    Check(rec[1].count == 24 && seen.size() == 24 && above28, "races, random: 24 enabled songs each once, including numbers above 28", (long)seen.size());
    *(int*)(eaTrax + 0x150) = 7;
    rec[1].chosen = 123;
    ((PickFn)0x4F4CD0)(eaTrax, nullptr);
    Check(rec[1].chosen == 123, "an unknown context is left alone", rec[1].chosen);

    printf("playing\n");
    DWORD channel[64] = {};
    channel[6] = 4; // [channel + 0x18]: four queue slots
    Fn5 play = *(Fn5*)0x8C5F58;
    Fn0 stop = *(Fn0*)0x8C5F3C;
    Fn1 timeLeft = *(Fn1*)0x8C5F50, volume = *(Fn1*)0x8C5F60;
    LookupFn lookup = (LookupFn)0x82BFD0;
    QueueFn queue = (QueueFn)(UINT_PTR)(0x830557 + 5 + Read32(0x830558));
    Check(volume(channel, nullptr, 0) == 0, "volume is passed on (and 0 keeps this test silent)", 0);
    Check(play(channel, nullptr, 1, 2, 0, 0, 4000) == 0x777, "with no song of ours, play goes to the game", 0);
    Check(timeLeft(channel, nullptr, 0) == 4242 && queue(nullptr) == 5, "and so do time-left and queue-node", 0);
    Check(lookup(0x00123456, 0xFFFFFFFF) == nullptr, "an ID that isn't ours gets the game's answer", 0);

    DWORD* record = (DWORD*)lookup(0x00FFA000, 0xFFFFFFFF);
    Check(record && record[3] == 0x02FFA000 && record[5] == 0x11000001, "our ID gets a record carrying the ID", record ? (long)record[3] : 0);
    Check(queue(nullptr) == 0, "queue-node is held back once our song is looked up", 0);
    Check(stop(channel, nullptr) == 0x55, "the game's stop before a song is passed on", 0);
    int handle = play(channel, nullptr, 0x5D1, 0x12EDCD, 0, 0, 30016);
    Check(handle != 0x777 && (handle & 0xFF) == 1, "play starts our song instead of the game's stream", handle);
    int t1 = 0;
    for (int i = 0; i < 60 && (t1 = timeLeft(channel, nullptr, 0)) >= 10000; ++i)
        Sleep(50);
    Check(t1 > 1000 && t1 < 10000 * 60, "time left is our song's remaining time (ms)", t1);
    Check(timeLeft(channel, nullptr, 4) == -8, "a slot past the channel's count is empty (-8)", 0);
    Check(timeLeft(channel, nullptr, -1) == 4242, "the total (slot -1) is left to the game", 0);
    DWORD other[64] = {};
    other[6] = 4;
    Check(timeLeft(other, nullptr, 0) == 4242, "another channel is left to the game", 0);
    Check(play(channel, nullptr, 0x5D2, 0, 0, 0, 4000) != 0x777 && queue(nullptr) == 0, "further pieces are kept from the game while ours plays", 0);
    Check(play(other, nullptr, 9, 9, 0, 0, 100) == 0x777, "but a play on another channel goes to the game", 0);
    Sleep(1000);
    int t2 = timeLeft(channel, nullptr, 0);
    Check(t1 - t2 > 700 && t1 - t2 < 1500, "one second later, about one second less", t1 - t2);

    *(BYTE*)0x91CAE4 = 1; // the game pauses
    Sleep(400);
    int t3 = timeLeft(channel, nullptr, 0);
    Sleep(700);
    int t4 = timeLeft(channel, nullptr, 0);
    Check(t3 - t4 >= 0 && t3 - t4 < 30, "paused: time left stands still", t3 - t4);
    *(BYTE*)0x91CAE4 = 0;
    Sleep(900);
    int t5 = timeLeft(channel, nullptr, 0);
    Check(t4 - t5 > 500, "resumed: it runs again", t4 - t5);

    Check(lookup(0x00641F27, 0xFFFFFFFF) == nullptr && play(channel, nullptr, 1, 2, 0, 0, 100) != 0x777,
        "the game's end-of-song event doesn't reach the stream while ours plays", 0);
    Check(stop(channel, nullptr) == 0x55, "stop is passed on", 0);
    Check(play(channel, nullptr, 1, 2, 0, 0, 4000) == 0x777 && timeLeft(channel, nullptr, 0) == 4242 && queue(nullptr) == 5,
        "after stop everything goes to the game again", 0);

    lookup(0x00FFA002, 0xFFFFFFFF); // the next of ours, straight after
    stop(channel, nullptr);
    Check(play(channel, nullptr, 1, 2, 0, 0, 4000) != 0x777, "a second song of ours starts", 0);
    lookup(0x00FFA003, 0xFFFFFFFF);
    Check(play(channel, nullptr, 1, 2, 0, 0, 4000) != 0x777, "a third replaces it even without a stop in between", 0);
    // That third one ("Epsilon") is the file that can't be played: it must end by itself.
    int broken = 1;
    for (int i = 0; i < 60 && (broken = timeLeft(channel, nullptr, 0)) != 0; ++i)
        Sleep(50);
    Check(broken == 0, "a song whose file can't be played reports no time left, so the game moves on", broken);
    stop(channel, nullptr);

    lookup(0x00FFA000, 0xFFFFFFFF); // looked up, but the game never plays it
    Sleep(5300);
    Check(play(channel, nullptr, 1, 2, 0, 0, 4000) == 0x777 && queue(nullptr) == 5,
        "a looked-up song the game didn't play within 5 s is forgotten, not started by a later play", 0);

    printf("list rebuilt by the game\n");
    BuildOriginalList();
    ((BuilderFn)0x4DF330)(1);
    entries = (SongEntry**)(UINT_PTR)list[1];
    size = (int)((list[2] - list[1]) / 4);
    Check(*(int*)0x8F42C4 == 32 && size == 32 && !strcmp(entries[26]->title, "Alpha Song"), "custom songs are added again", size);
    Check(modes[27].mode == kModeOff && modes[26].mode == kModeAll, "with their modes", modes[27].mode);

    Sleep(100);
    std::string log = ReadLog(plugin);
    const char* expect[] = { "Installed", "list: 26 original songs, 6 custom songs added (numbers 26-31)", "modes: \"Beta\" is now Off",
        "modes: an original song's change written to the profile", "modes: taken from the profile", "lookup 00FFA000 -> ours: \"Alpha Song\"",
        "song: start \"Alpha Song\" - First Artist", "song: paused with the game", "song: resumed", "song: stop \"Alpha Song\"",
        "cut short", "song: start \"Delta\"", "another of ours starts", "next-song handler called: flow state 3, music object 00000000",
        "next song: asked for by the controller plugin", "next-song handler called: flow state 6" };
    for (const char* e : expect)
        Check(log.find(e) != std::string::npos, e, 0);
    return failures ? 1 : 0;
}

static int RunNothingInstalled(const char* expectInLog)
{
    HMODULE plugin = LoadLibraryW(L"MusicBridge.asi");
    Check(plugin != nullptr, "MusicBridge.asi loaded", plugin != nullptr);
    if (!plugin)
        return 1;
    Check(*(BYTE*)0x4DF330 == 0xA1 && *(BYTE*)0x82BFD0 == 0x55 && *(BYTE*)0x5509D3 == 0xA1 && *(BYTE*)0x51E000 == 0xA1,
        "no code was changed", *(BYTE*)0x4DF330);
    Check(*(DWORD*)0x8C5F58 == 0x82B4A0 && *(DWORD*)0x8C5F3C == 0x82B5A0 && Read32(0x830558) == (DWORD)(0x82FF80 - (0x830557 + 5)),
        "no function pointer or call was changed", 0);
    Check(*(DWORD*)0x8C5F50 == 0x82B460 && *(DWORD*)0x8C5F60 == 0x82B290 && *(BYTE*)0x5170CF == 0x75 && *(BYTE*)0x517070 == 0xA1,
        "nor the time-left and volume slots, the next-song check or its handler", *(BYTE*)0x5170CF);
    ((BuilderFn)0x4DF330)(1);
    Check(*(int*)0x8F42C4 == 26, "the list still has 26 songs", *(int*)0x8F42C4);
    Check(ReadLog(plugin).find(expectInLog) != std::string::npos, expectInLog, 0);
    return failures ? 1 : 0;
}

// With SkipInRaces = 0 the plugin is installed as usual but leaves the game's menus-only check alone.
static int RunSkipOff()
{
    HMODULE plugin = LoadLibraryW(L"MusicBridge.asi");
    Check(plugin != nullptr, "MusicBridge.asi loaded", plugin != nullptr);
    if (!plugin)
        return 1;
    Check(*(BYTE*)0x4DF330 == 0xE9, "the plugin is installed", *(BYTE*)0x4DF330);
    Check(*(BYTE*)0x5170CF == 0x75 && *(BYTE*)0x5170D0 == 0x2C, "the next-song check is left as the game has it", *(BYTE*)0x5170CF);
    typedef int(__cdecl* NextSongFn)();
    NextSongFn nextSong = (NextSongFn)GetProcAddress(plugin, "MusicBridge_NextSong");
    *(int*)0x925E90 = 6;
    Check(nextSong && nextSong() == 0, "and a request during a race is ignored", 0);
    return failures ? 1 : 0;
}

static int Spawn(const wchar_t* arguments)
{
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    std::wstring command = std::wstring(L"\"") + self + L"\" " + arguments;
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(nullptr, &command[0], nullptr, nullptr, TRUE, 0, nullptr, nullptr, &si, &pi))
        return 2;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 2;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return (int)code;
}

int wmain(int argc, wchar_t** argv)
{
    setvbuf(stdout, nullptr, _IONBF, 0);
    if (argc < 2) // the parent: three runs, each in a process of its own
    {
        std::wstring source = Here() + L"\\..\\..\\CUSTOM SONGS";
        if (!MakeSongFolder(source))
        {
            wprintf(L"needs at least one .mp3 in %ls\n", source.c_str());
            return 2;
        }
        printf("== six songs\n");
        WriteIni(L"fixtures-songs");
        int a = Spawn(L"main 0");
        printf("== empty folder\n");
        WriteIni(L"fixtures-empty");
        int b = Spawn(L"empty 0");
        printf("== a game that isn't speed.exe v1.3\n");
        WriteIni(L"fixtures-songs");
        int c = Spawn(L"wrong 0");
        printf("== SkipInRaces = 0\n");
        WriteIni(L"fixtures-songs", L"0");
        int d = Spawn(L"noskip 0");
        printf("%s\n", a || b || c || d ? "FAILED" : "all passed");
        return a || b || c || d;
    }

    bool wrong = !wcscmp(argv[1], L"wrong");
    if (!PlaceGame(wrong))
    {
        // Windows puts this process's stack and heaps at random addresses, sometimes on top of the
        // ones we need. Start again (a new process gets a new layout), a limited number of times.
        int attempt = argc > 2 ? _wtoi(argv[2]) : 0;
        if (attempt >= 30)
        {
            printf("could not place the imitation game at the game's addresses in 30 attempts\n");
            return 2;
        }
        return Spawn((std::wstring(argv[1]) + L" " + std::to_wstring(attempt + 1)).c_str());
    }
    int result = !wcscmp(argv[1], L"main") ? RunMain() : !wcscmp(argv[1], L"noskip") ? RunSkipOff()
        : wrong ? RunNothingInstalled("not as expected: picker") : RunNothingInstalled("No songs: nothing installed");
    printf("%d failures\n", failures);
    return result;
}
