// Stand-in test for the Player (no game needed). Plays SILENTLY unless --volume is given.
// Build (from music\tests):
//   zig c++ -target x86-windows-gnu -w -municode player-test.cpp ../src/Player.cpp -o player-test.exe
//       -lmfplat -lmfreadwrite -lmfuuid -lole32
// Run:
//   player-test.exe quick <folder>          each song: 3 s play, pause, resume, stop; error cases
//   player-test.exe full <folder-or-file>   each song to the end; checks length and speed
//   add  --volume 0.5  to hear it
// Exit code 0 = all checks passed.
#include "../src/Player.h"
#include "../src/SongName.h"
#include <stdio.h>
#include <math.h>

static int failures;
static float volume = 0.0f;

static void Check(bool ok, const wchar_t* what, const std::wstring& detail)
{
    wprintf(L"  %ls %ls %ls\n", ok ? L"ok  " : L"FAIL", what, detail.c_str());
    if (!ok)
        ++failures;
}

static double Now()
{
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return t.QuadPart / (double)f.QuadPart;
}

static std::wstring Num(double v)
{
    wchar_t b[64];
    swprintf(b, 64, L"%.3f", v);
    return b;
}

static void Quick(const Song& song)
{
    wprintf(L"%ls\n", song.file.c_str());
    Player p;
    if (!p.Open(song.path.c_str()))
    {
        Check(false, L"open", Num((double)(unsigned long)p.Stats().error));
        return;
    }
    p.SetVolume(volume);
    PlayerStats s = p.Stats();
    Check(s.sampleRate >= 8000 && s.channels >= 1, L"format", std::to_wstring(s.sampleRate) + L" Hz x" + std::to_wstring(s.channels));
    p.Play();
    Sleep(3000);
    double a = p.Stats().playedSeconds;
    Check(a > 2.5 && a < 3.2, L"plays in real time: 3 s gives", Num(a));
    p.Pause();
    Sleep(300);
    double b = p.Stats().playedSeconds;
    Sleep(1500);
    double c = p.Stats().playedSeconds;
    Check(fabs(c - b) < 0.01, L"paused: position moved by", Num(c - b));
    p.Play();
    Sleep(2000);
    double d = p.Stats().playedSeconds;
    Check(d - c > 1.6 && d - c < 2.2, L"resumed: 2 s gives", Num(d - c));
    Check(p.Stats().underruns == 0, L"no gaps", std::to_wstring(p.Stats().underruns));
    double t = Now();
    p.Stop();
    Check(Now() - t < 0.5, L"stop returns quickly (s)", Num(Now() - t));
}

// The game's main thread starts and stops songs; neither call may make it wait.
static void NonBlocking(const Song& song)
{
    wprintf(L"start and stop without waiting: %ls\n", song.file.c_str());
    Player p;
    p.SetVolume(volume);
    double t = Now();
    p.Start(song.path.c_str());
    double startTook = Now() - t;
    Check(startTook < 0.005, L"Start returns at once (s)", Num(startTook));
    Check(!p.Finished(), L"not finished right after Start", L"");
    Sleep(1500);
    PlayerStats s = p.Stats();
    Check(s.ready && s.playedSeconds > 0.8, L"the song is playing 1.5 s later", Num(s.playedSeconds));
    Check(s.durationSeconds > 1, L"its length is known", Num(s.durationSeconds));
    t = Now();
    p.Stop();
    double stopTook = Now() - t;
    Check(stopTook < 0.005, L"Stop returns at once (s)", Num(stopTook));
    Check(p.Finished(), L"after Stop the player reports finished", L"");

    Player q;
    q.Start(L"C:\\no-such-folder\\nothing_Here.mp3");
    Sleep(500);
    Check(q.Finished() && FAILED(q.Stats().error), L"Start on a missing file ends by itself with an error", L"");
}

static void Full(const Song& song)
{
    wprintf(L"%ls\n", song.file.c_str());
    Player p;
    if (!p.Open(song.path.c_str()))
    {
        Check(false, L"open", L"");
        return;
    }
    p.SetVolume(volume);
    p.Play();
    // Speed: compare the device clock with the wall clock over the middle of the song.
    Sleep(2000);
    double wall0 = Now(), dev0 = p.Stats().playedSeconds, wall1 = wall0, dev1 = dev0;
    while (!p.Finished())
    {
        Sleep(50);
        PlayerStats s = p.Stats();
        if (s.playedSeconds > dev1)
        {
            wall1 = Now();
            dev1 = s.playedSeconds;
        }
    }
    PlayerStats s = p.Stats();
    Check(SUCCEEDED(s.error), L"no error", L"");
    // Pass = within 0.1%, or within 50 ms where 0.1% is less than that: our readings are taken
    // every 10-50 ms, so on a short clip the measurement itself is no finer than 50 ms.
    double lengthSlack = fmax(0.001 * s.decodedSeconds, 0.05), speedSlack = fmax(0.001 * (wall1 - wall0), 0.05);
    Check(s.decodedSeconds > 1 && fabs(s.playedSeconds - s.decodedSeconds) < lengthSlack,
        L"played length vs decoded length (s)", Num(s.playedSeconds) + L" vs " + Num(s.decodedSeconds));
    Check(fabs((dev1 - dev0) - (wall1 - wall0)) < speedSlack, L"speed: device seconds vs wall seconds",
        Num(dev1 - dev0) + L" vs " + Num(wall1 - wall0) + L" (ratio " + Num((dev1 - dev0) / (wall1 - wall0)) + L")");
    Check(s.underruns == 0, L"no gaps", std::to_wstring(s.underruns));
    if (s.durationSeconds > 0)
        Check(fabs(s.durationSeconds - s.decodedSeconds) < 0.5, L"file's stated length (s)", Num(s.durationSeconds));
}

static void ErrorCases()
{
    wprintf(L"error cases\n");
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    std::wstring empty = std::wstring(tmp) + L"mb-empty_Test.mp3", junk = std::wstring(tmp) + L"mb-junk_Test.mp3";
    CloseHandle(CreateFileW(empty.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr));
    HANDLE h = CreateFileW(junk.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
    BYTE noise[4096];
    for (int i = 0; i < 4096; ++i)
        noise[i] = (BYTE)(i * 31 + 7);
    DWORD wrote;
    WriteFile(h, noise, sizeof(noise), &wrote, nullptr);
    CloseHandle(h);
    Player p;
    Check(!p.Open(L"C:\\no-such-folder\\nothing_Here.mp3"), L"missing file is refused", L"");
    Check(!p.Open(empty.c_str()), L"empty file is refused", L"");
    bool opened = p.Open(junk.c_str());
    if (opened)
    {
        p.Play();
        double t = Now();
        while (!p.Finished() && Now() - t < 5)
            Sleep(20);
        Check(p.Finished(), L"junk file ends by itself", L"");
    }
    else
        Check(true, L"junk file is refused", L"");
    p.Stop();
    DeleteFileW(empty.c_str());
    DeleteFileW(junk.c_str());
}

int wmain(int argc, wchar_t** argv)
{
    if (argc < 3)
    {
        printf("usage: player-test quick|full <folder-or-file> [--volume 0..1]\n");
        return 2;
    }
    for (int i = 3; i + 1 < argc; ++i)
        if (!wcscmp(argv[i], L"--volume"))
            volume = (float)_wtof(argv[i + 1]);
    std::vector<Song> songs;
    DWORD attr = GetFileAttributesW(argv[2]);
    if (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY))
        songs = ScanSongFolder(argv[2]);
    else
    {
        Song s;
        s.path = s.file = argv[2];
        songs.push_back(s);
    }
    bool full = !wcscmp(argv[1], L"full");
    for (const Song& s : songs)
        full ? Full(s) : Quick(s);
    if (!full)
    {
        if (!songs.empty())
            NonBlocking(songs[0]);
        ErrorCases();
    }
    printf("%d songs, %d failures\n", (int)songs.size(), failures);
    return failures ? 1 : 0;
}
