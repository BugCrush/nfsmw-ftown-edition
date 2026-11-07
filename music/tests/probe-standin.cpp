// Stand-in for speed.exe to test MusicProbe.asi: loads it, waits, exits. It is not the game, so the
// probe must log "Not speed.exe v1.3 ... idle" and do nothing else.
// Build (from music\tests): zig c++ -target x86-windows-gnu -w probe-standin.cpp -o probe-standin.exe
// Run next to MusicProbe.asi, then read MusicProbe.log.
#include <windows.h>
#include <stdio.h>

int main()
{
    HMODULE probe = LoadLibraryA("MusicProbe.asi");
    printf("MusicProbe.asi %s\n", probe ? "loaded" : "NOT loaded");
    Sleep(1000);
    return probe ? 0 : 1;
}
