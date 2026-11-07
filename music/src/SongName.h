// The naming rule for CUSTOM SONGS: "<title>_<artist>.mp3", split at the LAST underscore.
// tools/songs.py implements the same rule; both are checked against music/tests/name-cases.tsv.
#pragma once
#include <windows.h>
#include <algorithm>
#include <string>
#include <vector>

struct Song
{
    std::wstring file;   // file name as found, e.g. L"Joota Japani_Kr$na.mp3" (the song's identity)
    std::wstring path;   // full path used to open it
    std::wstring title;
    std::wstring artist;
};

inline std::wstring TrimSpaces(const std::wstring& s)
{
    size_t a = s.find_first_not_of(L" \t"), b = s.find_last_not_of(L" \t");
    return a == std::wstring::npos ? std::wstring() : s.substr(a, b - a + 1);
}

inline bool HasMp3Extension(const std::wstring& file)
{
    return file.size() > 4 && _wcsicmp(file.c_str() + file.size() - 4, L".mp3") == 0;
}

// file: a file name with its extension. Never fails: a name that doesn't fit the pattern
// becomes the title, with artist "Unknown".
inline void ParseSongName(const std::wstring& file, std::wstring* title, std::wstring* artist)
{
    std::wstring stem = HasMp3Extension(file) ? file.substr(0, file.size() - 4) : file;
    size_t cut = stem.rfind(L'_');
    std::wstring t = cut == std::wstring::npos ? L"" : TrimSpaces(stem.substr(0, cut));
    std::wstring a = cut == std::wstring::npos ? L"" : TrimSpaces(stem.substr(cut + 1));
    if (t.empty() || a.empty())
    {
        *title = TrimSpaces(stem);
        *artist = L"Unknown";
        return;
    }
    *title = t;
    *artist = a;
}

// Every *.mp3 directly inside dir (no subfolders), sorted by title, then file name, ignoring case.
// A missing or empty folder gives an empty list.
inline std::vector<Song> ScanSongFolder(const std::wstring& dir)
{
    std::vector<Song> songs;
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (find == INVALID_HANDLE_VALUE)
        return songs;
    do
    {
        if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || !HasMp3Extension(fd.cFileName))
            continue;
        Song s;
        s.file = fd.cFileName;
        s.path = dir + L"\\" + s.file;
        ParseSongName(s.file, &s.title, &s.artist);
        songs.push_back(s);
    } while (FindNextFileW(find, &fd));
    FindClose(find);
    std::sort(songs.begin(), songs.end(), [](const Song& x, const Song& y) {
        int c = _wcsicmp(x.title.c_str(), y.title.c_str());
        return c ? c < 0 : _wcsicmp(x.file.c_str(), y.file.c_str()) < 0;
    });
    return songs;
}
