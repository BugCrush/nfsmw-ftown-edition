// Where per-song play modes live, and how song names become text the game can draw.
//  - The originals' modes stay in the profile save, exactly as today. The game's menu is pointed at
//    an array of ours that mirrors them; SyncOriginalModes carries changes both ways.
//  - Custom songs' modes are kept in our own settings file, keyed by file name.
#pragma once
#include <windows.h>
#include <string.h>
#include <string>
#include "Picker.h"

enum ModeSyncResult { kModesUnchanged, kModesFromProfile, kModesToProfile };

// ours / profile / shadow each hold `originals` records. shadow is what both sides held after the
// last sync. If the profile differs from it, the game loaded or reset the profile: it wins. Otherwise
// if ours differs, the user changed a mode in the menu: it is written back to the profile.
inline ModeSyncResult SyncOriginalModes(SavedMode* ours, SavedMode* profile, SavedMode* shadow, bool* shadowValid, int originals)
{
    size_t bytes = originals * sizeof(SavedMode);
    if (!*shadowValid || memcmp(profile, shadow, bytes) != 0)
    {
        memcpy(ours, profile, bytes);
        memcpy(shadow, profile, bytes);
        *shadowValid = true;
        return kModesFromProfile;
    }
    if (memcmp(ours, shadow, bytes) != 0)
    {
        memcpy(profile, ours, bytes);
        memcpy(shadow, ours, bytes);
        return kModesToProfile;
    }
    return kModesUnchanged;
}

// ---- custom songs' modes: an .ini with one section per file name ---------------------------

inline const wchar_t* ModeName(unsigned char mode)
{
    static const wchar_t* names[] = { L"Off", L"Menus", L"Races", L"All" };
    return names[mode & 3];
}

// "[" and "]" would end the section name early.
inline std::wstring SettingsSection(const std::wstring& file)
{
    std::wstring s = file;
    for (wchar_t& c : s)
        if (c == L'[')
            c = L'(';
        else if (c == L']')
            c = L')';
    return s;
}

// A song we have never seen plays everywhere ("All"), like the game's own default for its main songs.
inline unsigned char LoadSongMode(const std::wstring& ini, const std::wstring& file)
{
    wchar_t value[16] = L"";
    GetPrivateProfileStringW(SettingsSection(file).c_str(), L"Mode", L"All", value, 16, ini.c_str());
    for (unsigned char m = 0; m < 4; ++m)
        if (_wcsicmp(value, ModeName(m)) == 0)
            return m;
    return kModeAll;
}

inline bool SaveSongMode(const std::wstring& ini, const std::wstring& file, unsigned char mode)
{
    // Windows writes an .ini as Unicode only if the file already starts with a UTF-16 mark;
    // without it, names outside the system's code page would be lost.
    if (GetFileAttributesW(ini.c_str()) == INVALID_FILE_ATTRIBUTES)
    {
        HANDLE h = CreateFileW(ini.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, 0, nullptr);
        if (h != INVALID_HANDLE_VALUE)
        {
            const wchar_t head[] = L"\xFEFF; Play modes of the songs in CUSTOM SONGS (Off, Menus, Races, All). Written by MusicBridge.\r\n";
            DWORD wrote;
            WriteFile(h, head, (DWORD)(wcslen(head) * sizeof(wchar_t)), &wrote, nullptr);
            CloseHandle(h);
        }
    }
    return WritePrivateProfileStringW(SettingsSection(file).c_str(), L"Mode", ModeName(mode), ini.c_str()) != 0;
}

// The user may add "Title = ..." or "Artist = ..." under a song's section to change what the game
// shows for it (the file's name is not touched). key is L"Title" or L"Artist"; empty = no override.
inline std::wstring LoadSongText(const std::wstring& ini, const std::wstring& file, const wchar_t* key)
{
    wchar_t value[256] = L"";
    GetPrivateProfileStringW(SettingsSection(file).c_str(), key, L"", value, 256, ini.c_str());
    std::wstring s = value;
    size_t a = s.find_first_not_of(L" \t"), b = s.find_last_not_of(L" \t");
    return a == std::wstring::npos ? std::wstring() : s.substr(a, b - a + 1);
}

// ---- text for the game ------------------------------------------------------------------------

// The game's text is one byte per character (Windows-1252). Characters it has no code for become
// "?". In the game's menu text "$NAME$" stands for an embedded picture (a button icon): a line with a
// single "$" in it is not drawn at all, and "$$" is drawn as one "$" (seen in the game; the game's own
// data writes the group P$C as "P$$C"). So each "$" is doubled, unless asTyped is set (a name the user
// typed as an override is passed on unchanged). The result is at most 255 characters.
// If nothing readable is left, `fallback` is used instead.
inline std::string GameText(const std::wstring& text, const char* fallback, bool asTyped = false)
{
    char buf[256] = "";
    WideCharToMultiByte(1252, WC_NO_BEST_FIT_CHARS, text.c_str(), -1, buf, sizeof(buf) - 1, "?", nullptr);
    bool readable = false;
    std::string out;
    for (const char* p = buf; *p; ++p)
    {
        size_t add = *p == '$' && !asTyped ? 2 : 1;
        if (out.size() + add > 255)
            break; // never leave half of a "$$" pair
        out.append(add, *p);
        readable = readable || (*p != '?' && *p != ' ');
    }
    return readable ? out : fallback;
}
