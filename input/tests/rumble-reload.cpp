// Plays a continuous 20 ms sine (a "Surface" effect) for 4 seconds, to test live .ini reload.
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>

static GUID g_pad;
static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID) { g_pad = dev->guidInstance; return DIENUM_STOP; }

int main()
{
    LoadLibraryA("InputBridge.asi");
    IDirectInput8A* di = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di, nullptr);
    di->EnumDevices(DI8DEVCLASS_GAMECTRL, OnDevice, nullptr, DIEDFL_ATTACHEDONLY);
    IDirectInputDevice8A* ff = nullptr;
    di->CreateDevice(g_pad, &ff, nullptr);
    ff->SetDataFormat(&c_dfDIJoystick2);
    ff->Acquire();
    DIJOYSTATE2 st;
    ff->GetDeviceState(sizeof(st), &st);
    DWORD axes[1] = { DIJOFS_X };
    LONG dirs[1] = { 0 };
    DIPERIODIC per = { 3000, 0, 0, 20000 };
    DIEFFECT eff = { sizeof(DIEFFECT) };
    eff.dwFlags = DIEFF_CARTESIAN | DIEFF_OBJECTOFFSETS;
    eff.dwDuration = INFINITE;
    eff.dwGain = DI_FFNOMINALMAX;
    eff.dwTriggerButton = DIEB_NOTRIGGER;
    eff.cAxes = 1;
    eff.rgdwAxes = axes;
    eff.rglDirection = dirs;
    eff.cbTypeSpecificParams = sizeof(per);
    eff.lpvTypeSpecificParams = &per;
    IDirectInputEffect* effect = nullptr;
    ff->CreateEffect(GUID_Sine, &eff, &effect, nullptr);
    effect->Start(1, 0);
    Sleep(4000);
    effect->Stop();
    Sleep(200);
    return 0;
}
