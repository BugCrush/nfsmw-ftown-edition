// Plays one light "Surface" effect (the game's usual 1411 magnitude, 20 ms sine) for 1.5 s, then a
// second identical one alongside it for 1.5 s, to check how InputBridge blends simultaneous effects.
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>

static GUID g_pad;
static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID) { g_pad = dev->guidInstance; return DIENUM_STOP; }

static IDirectInputEffect* StartSurface(IDirectInputDevice8A* ff)
{
    static DWORD axes[1] = { DIJOFS_X };
    static LONG dirs[1] = { 0 };
    static DIPERIODIC per = { 1411, 0, 0, 20000 };
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
    return effect;
}

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
    ff->GetDeviceState(sizeof(st), &st); // lets InputBridge find the XInput slot
    IDirectInputEffect* a = StartSurface(ff);
    Sleep(1500);
    IDirectInputEffect* b = StartSurface(ff);
    Sleep(1500);
    a->Stop();
    b->Stop();
    Sleep(300);
    return 0;
}
