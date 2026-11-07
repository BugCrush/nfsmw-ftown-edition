// Starts and stops a damper effect the way MW does at race start and pause, to check that
// InputBridge's "in race" detection (which gates the shift/nitrous vibrations and the telemetry
// panel) follows it. Opens a window like the game's, so the telemetry panel can be seen.
// Usage: race-signal.exe [seconds in race, default 1.5]
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <stdlib.h>

static GUID g_pad;
static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID) { g_pad = dev->guidInstance; return DIENUM_STOP; }

int main(int argc, char** argv)
{
    DWORD raceMs = argc > 1 ? (DWORD)(atof(argv[1]) * 1000) : 1500;
    LoadLibraryA("InputBridge.asi");
    HWND wnd = CreateWindowExA(0, "STATIC", "race-signal", WS_POPUP | WS_VISIBLE, 0, 0,
        GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN), nullptr, nullptr, nullptr, nullptr);
    SetForegroundWindow(wnd);
    IDirectInput8A* di = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di, nullptr);
    di->EnumDevices(DI8DEVCLASS_GAMECTRL, OnDevice, nullptr, DIEDFL_ATTACHEDONLY);
    IDirectInputDevice8A* ff = nullptr;
    di->CreateDevice(g_pad, &ff, nullptr);
    ff->SetDataFormat(&c_dfDIJoystick2);
    ff->SetCooperativeLevel(wnd, DISCL_NONEXCLUSIVE | DISCL_FOREGROUND);
    ff->Acquire();
    DIJOYSTATE2 st;
    ff->GetDeviceState(sizeof(st), &st); // lets InputBridge find the XInput slot

    DWORD axes[2] = { DIJOFS_X, DIJOFS_Y };
    LONG dirs[2] = { 1, 0 };
    DICONDITION cond[2] = { { 0, 3500, 3500, 10000, 10000, 0 }, { 0, 3500, 3500, 10000, 10000, 0 } };
    DIEFFECT eff = { sizeof(DIEFFECT) };
    eff.dwFlags = DIEFF_CARTESIAN | DIEFF_OBJECTOFFSETS;
    eff.dwDuration = INFINITE;
    eff.dwGain = DI_FFNOMINALMAX;
    eff.dwTriggerButton = DIEB_NOTRIGGER;
    eff.cAxes = 2;
    eff.rgdwAxes = axes;
    eff.rglDirection = dirs;
    eff.cbTypeSpecificParams = sizeof(cond);
    eff.lpvTypeSpecificParams = cond;
    IDirectInputEffect* damper = nullptr;
    ff->CreateEffect(GUID_Damper, &eff, &damper, nullptr);
    Sleep(500);
    damper->Start(1, 0);   // race starts
    for (DWORD t0 = GetTickCount(); GetTickCount() - t0 < raceMs;)
    {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        ff->GetDeviceState(sizeof(st), &st);
        Sleep(16);
    }
    damper->Stop();        // pause / back to menus
    Sleep(500);
    return 0;
}
