// A stand-in for MusicBridge.asi, for next-song.cpp: it has the one function InputBridge calls and
// counts the calls.
// Build (from input\tests): zig c++ -target x86-windows-gnu -shared -w musicbridge-stub.cpp -o MusicBridge.asi
#include <windows.h>

static volatile LONG g_calls;

extern "C" __declspec(dllexport) int __cdecl MusicBridge_NextSong()
{
    InterlockedIncrement(&g_calls);
    return 1;
}

extern "C" __declspec(dllexport) int __cdecl StubCalls()
{
    return g_calls;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID)
{
    return TRUE;
}
