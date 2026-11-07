// Checks that InputBridge asks the music plugin for the next song when the next-song button goes
// down: once per press, not while it is held, and not at all when the setting is off.
// Needs the controller connected, InputBridge.asi and the stub MusicBridge.asi (musicbridge-stub.cpp)
// next to this program. It sets [Debug] FakePad = 1 in the InputBridge.ini beside it for the run:
// the scripted pad presses the right stick for 0.2 s once in every 6 s.
// Build (from input\tests): zig c++ -target x86-windows-gnu -w next-song.cpp -ldinput8 -ldxguid -luser32 -o next-song.exe
// Run: next-song.exe        (about 16 s; exit code 0 = all passed)
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <stdio.h>
#include <string.h>

static GUID g_pad;
static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID) { g_pad = dev->guidInstance; return DIENUM_STOP; }

static void IniPath(char* path)
{
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    strcpy(strrchr(path, '\\') + 1, "InputBridge.ini");
}

// One run in a process of its own: InputBridge reads its settings when it loads.
static int Run(const char* button)
{
    char ini[MAX_PATH];
    IniPath(ini);
    WritePrivateProfileStringA("Debug", "FakePad", "1", ini);
    WritePrivateProfileStringA("Music", "NextSongButton", button, ini);
    HMODULE stub = LoadLibraryA("MusicBridge.asi");
    typedef int(__cdecl* CallsFn)();
    CallsFn calls = stub ? (CallsFn)GetProcAddress(stub, "StubCalls") : nullptr;
    if (!LoadLibraryA("InputBridge.asi") || !calls)
        return -1;
    IDirectInput8A* di = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di, nullptr);
    di->EnumDevices(DI8DEVCLASS_GAMECTRL, OnDevice, nullptr, DIEDFL_ATTACHEDONLY);
    IDirectInputDevice8A* pad = nullptr;
    if (FAILED(di->CreateDevice(g_pad, &pad, nullptr)))
        return -2;
    pad->SetDataFormat(&c_dfDIJoystick2);
    pad->SetCooperativeLevel(GetDesktopWindow(), DISCL_NONEXCLUSIVE | DISCL_BACKGROUND);
    pad->Acquire();
    DIJOYSTATE2 st;
    for (DWORD t0 = GetTickCount(); GetTickCount() - t0 < 7500;) // one 6 s loop of the scripted pad, and a bit
    {
        pad->GetDeviceState(sizeof(st), &st); // the game reads the pad about this often
        Sleep(8);
    }
    WritePrivateProfileStringA("Debug", "FakePad", "0", ini);
    WritePrivateProfileStringA("Music", "NextSongButton", "9", ini);
    return calls();
}

int main(int argc, char** argv)
{
    if (argc > 1)
        return Run(argv[1]);
    int failures = 0;
    const char* cases[][2] = { { "9", "the right stick click asks for the next song exactly once per press" },
        { "-1", "with NextSongButton = -1 nothing is asked" }, { "3", "another button (Y, not pressed) asks nothing" },
        { "10", "a number just past the last button (10) is treated as off" },
        { "99", "a nonsense number (99) is treated as off and nothing crashes" } };
    const int expected[] = { 1, 0, 0, 0, 0 };
    for (int i = 0; i < 5; ++i)
    {
        char self[MAX_PATH], command[MAX_PATH + 16];
        GetModuleFileNameA(nullptr, self, MAX_PATH);
        snprintf(command, sizeof(command), "\"%s\" %s", self, cases[i][0]);
        STARTUPINFOA si = { sizeof(si) };
        PROCESS_INFORMATION pi;
        DWORD got = (DWORD)-9;
        if (CreateProcessA(nullptr, command, nullptr, nullptr, FALSE, 0, nullptr, nullptr, &si, &pi))
        {
            WaitForSingleObject(pi.hProcess, INFINITE);
            GetExitCodeProcess(pi.hProcess, &got);
        }
        bool ok = (int)got == expected[i];
        failures += !ok;
        printf("  %s %s (%d calls)\n", ok ? "ok  " : "FAIL", cases[i][1], (int)got);
    }
    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
