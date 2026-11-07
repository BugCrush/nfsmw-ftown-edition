// End-to-end test of InputBridge's controls finder. Run next to InputBridge.asi with an .ini that has
// [Debug] FakePad=1 (scripted pad: 2 s full throttle, 2 s released, 2 s hard right, repeating).
// This program keeps a race going (a playing damper) and holds three InputControls-shaped structs:
//   player  - follows the script (steering scaled to 0.8, like game processing)   <- should be locked
//   decoyA  - gas always 1                                   (dropped at throttle release)
//   decoyB  - gas follows the script, steering always 0     (dropped at the steering step)
//   decoyC  - follows the script for the first 6 s, then freezes (passes steps 1-3; only the verify
//             step, which checks the values keep following the inputs, can drop it)
// At 5 s the damper is stopped for 0.15 s, like the game's brief restarts: that must not reset the search.
// It prints their addresses; compare with "candidate" lines in InputBridge.log.
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <stdio.h>
#include <string.h>

struct InputControls
{
    float banking, steering, steeringVertical, strafeVertical, strafeHorizontal, gas, brake, handbrake;
    unsigned char action, nos, pad[2];
};

static GUID g_pad;
static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID) { g_pad = dev->guidInstance; return DIENUM_STOP; }

int main()
{
    // Heap-allocated like the game's objects.
    InputControls* player = new InputControls();
    InputControls* decoyA = new InputControls();
    InputControls* decoyB = new InputControls();
    InputControls* decoyC = new InputControls();
    decoyA->gas = 1.0f;

    DWORD t0 = GetTickCount(); // InputBridge's script clock starts when it loads, right below
    LoadLibraryA("InputBridge.asi");
    printf("player=%p decoyA=%p decoyB=%p decoyC=%p\n", (void*)player, (void*)decoyA, (void*)decoyB, (void*)decoyC);
    fflush(stdout);

    HWND wnd = CreateWindowExA(0, "STATIC", "controls-finder", WS_POPUP | WS_VISIBLE, 0, 0, 200, 200, nullptr, nullptr, nullptr, nullptr);
    IDirectInput8A* di = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di, nullptr);
    di->EnumDevices(DI8DEVCLASS_GAMECTRL, OnDevice, nullptr, DIEDFL_ATTACHEDONLY);
    IDirectInputDevice8A* ff = nullptr;
    di->CreateDevice(g_pad, &ff, nullptr);
    ff->SetDataFormat(&c_dfDIJoystick2);
    ff->SetCooperativeLevel(wnd, DISCL_NONEXCLUSIVE | DISCL_BACKGROUND);
    ff->Acquire();
    DIJOYSTATE2 st;

    DWORD axes[2] = { DIJOFS_X, DIJOFS_Y };
    LONG dirs[2] = { 1, 0 };
    DICONDITION cond[2] = {};
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
    damper->Start(1, 0); // in a race from the start

    bool blipped = false;
    for (DWORD now = GetTickCount(); now - t0 < 25000; now = GetTickCount())
    {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        ff->GetDeviceState(sizeof(st), &st);
        DWORD phase = (now - t0) % 6000;
        float gas = phase < 2000 ? 1.0f : 0.0f, steer = phase >= 4000 ? 0.8f : 0.0f;
        player->gas = gas;
        player->steering = steer;
        decoyB->gas = gas;
        if (now - t0 < 6000)
        {
            decoyC->gas = gas;
            decoyC->steering = steer;
        }
        if (!blipped && now - t0 > 5000)
        {
            blipped = true;
            damper->Stop();
            Sleep(150);
            damper->Start(1, 0);
        }
        Sleep(16);
    }
    damper->Stop();
    Sleep(200);
    return 0;
}
