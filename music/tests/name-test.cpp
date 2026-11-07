// Checks ParseSongName against name-cases.tsv and ScanSongFolder against a folder made here.
// Build: zig c++ -target x86-windows-gnu -w -municode name-test.cpp -o name-test.exe
// Run from music\tests: name-test.exe      (exit code 0 = all passed)
#include "../src/SongName.h"
#include <stdio.h>

static std::wstring Wide(const std::string& utf8)
{
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), &w[0], n);
    return w;
}

static int failures;
static void Check(bool ok, const char* what, const std::wstring& detail)
{
    if (!ok)
    {
        ++failures;
        wprintf(L"FAIL %hs: %ls\n", what, detail.c_str());
    }
}

int wmain()
{
    FILE* f = fopen("name-cases.tsv", "rb");
    if (!f)
    {
        printf("FAIL: name-cases.tsv not found (run from music\\tests)\n");
        return 1;
    }
    char line[1024];
    int cases = 0;
    while (fgets(line, sizeof(line), f))
    {
        std::string s(line);
        while (!s.empty() && (s.back() == '\n' || s.back() == '\r'))
            s.pop_back();
        if (s.empty() || s[0] == '#')
            continue;
        size_t t1 = s.find('\t'), t2 = s.find('\t', t1 + 1);
        std::wstring file = Wide(s.substr(0, t1)), wantTitle = Wide(s.substr(t1 + 1, t2 - t1 - 1)),
                     wantArtist = Wide(s.substr(t2 + 1)), title, artist;
        ParseSongName(file, &title, &artist);
        Check(title == wantTitle, "title", file + L" -> [" + title + L"] want [" + wantTitle + L"]");
        Check(artist == wantArtist, "artist", file + L" -> [" + artist + L"] want [" + wantArtist + L"]");
        ++cases;
    }
    fclose(f);

    // Folder scan: only .mp3 files, subfolders ignored, sorted by title ignoring case.
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    std::wstring dir = std::wstring(tmp) + L"mb-name-test";
    CreateDirectoryW(dir.c_str(), nullptr);
    CreateDirectoryW((dir + L"\\sub.mp3").c_str(), nullptr);
    const wchar_t* names[] = { L"zebra_Z.mp3", L"Apple_A.mp3", L"mango_M.MP3", L"notes.txt", L"\x0924\x0947_\x0915.mp3" };
    for (const wchar_t* n : names)
        CloseHandle(CreateFileW((dir + L"\\" + n).c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr));
    std::vector<Song> songs = ScanSongFolder(dir);
    Check(songs.size() == 4, "scan count", std::to_wstring(songs.size()));
    if (songs.size() == 4)
    {
        Check(songs[0].title == L"Apple" && songs[1].title == L"mango" && songs[2].title == L"zebra", "scan order", songs[0].title);
        Check(songs[3].artist == L"\x0915", "scan unicode", songs[3].artist);
        Check(GetFileAttributesW(songs[3].path.c_str()) != INVALID_FILE_ATTRIBUTES, "scan path opens", songs[3].path);
    }
    Check(ScanSongFolder(dir + L"\\does-not-exist").empty(), "missing folder", L"");
    for (const wchar_t* n : names)
        DeleteFileW((dir + L"\\" + n).c_str());
    RemoveDirectoryW((dir + L"\\sub.mp3").c_str());
    RemoveDirectoryW(dir.c_str());

    printf("%d name cases, %d failures\n", cases, failures);
    return failures ? 1 : 0;
}
