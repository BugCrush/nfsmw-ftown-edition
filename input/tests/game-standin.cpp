// Stand-in for speed.exe, stage 2: mirrors the calls the game made in the stage 1 log.
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include <stdio.h>

static GUID g_pad;
static bool g_found;
static int g_axes, g_actuators;
static bool g_hasRz;

static BOOL CALLBACK OnDevice(LPCDIDEVICEINSTANCEA dev, LPVOID)
{
    g_pad = dev->guidInstance;
    g_found = true;
    return DIENUM_STOP;
}

static BOOL CALLBACK OnObject(LPCDIDEVICEOBJECTINSTANCEA obj, LPVOID)
{
    if (DIDFT_GETTYPE(obj->dwType) & DIDFT_AXIS)
    {
        ++g_axes;
        if (IsEqualGUID(obj->guidType, GUID_RzAxis)) g_hasRz = true;
        if (obj->dwType & DIDFT_FFACTUATOR) ++g_actuators;
    }
    return DIENUM_CONTINUE;
}

int main()
{
    LoadLibraryA("InputBridge.asi");
    HWND wnd = GetConsoleWindow();

    // Instance 1: input, like the game's main device.
    IDirectInput8A* di = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di, nullptr);
    di->EnumDevices(DI8DEVCLASS_GAMECTRL, OnDevice, nullptr, DIEDFL_ATTACHEDONLY);
    if (!g_found) { printf("no controller\n"); return 1; }
    IDirectInputDevice8A* pad = nullptr;
    di->CreateDevice(g_pad, &pad, nullptr);
    pad->SetDataFormat(&c_dfDIJoystick2);
    pad->Acquire();
    pad->EnumObjects(OnObject, nullptr, DIDFT_ALL);
    DIDEVCAPS caps = { sizeof(caps) };
    pad->GetCapabilities(&caps);
    DIJOYSTATE2 st;
    pad->GetDeviceState(sizeof(st), &st);
    printf("input: axes enumerated=%d hasRz=%d actuators=%d caps.axes=%lu ff=%d\n", g_axes, g_hasRz, g_actuators,
        caps.dwAxes, (caps.dwFlags & DIDC_FORCEFEEDBACK) != 0);
    printf("resting state: X=%ld Y=%ld Z=%ld Rx=%ld Ry=%ld Rz=%ld POV=%ld\n", st.lX, st.lY, st.lZ, st.lRx, st.lRy, st.lRz,
        (long)st.rgdwPOV[0]);

    // Instance 2: force feedback, like the game's second device.
    IDirectInput8A* di2 = nullptr;
    DirectInput8Create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, (void**)&di2, nullptr);
    IDirectInputDevice8A* ff = nullptr;
    di2->CreateDevice(g_pad, &ff, nullptr);
    ff->SetDataFormat(&c_dfDIJoystick2);
    ff->SetCooperativeLevel(wnd, DISCL_EXCLUSIVE | DISCL_BACKGROUND);
    DIPROPRANGE range = { { sizeof(DIPROPRANGE), sizeof(DIPROPHEADER), DIDFT_ABSAXIS | DIDFT_MAKEINSTANCE(0), DIPH_BYID }, -10000, 10000 };
    printf("SetProperty RANGE X hr=0x%08lx\n", ff->SetProperty(DIPROP_RANGE, &range.diph));
    range.diph.dwObj = DIDFT_ABSAXIS | DIDFT_MAKEINSTANCE(5);
    printf("SetProperty RANGE Rz hr=0x%08lx\n", ff->SetProperty(DIPROP_RANGE, &range.diph));
    ff->Acquire();
    printf("SendForceFeedbackCommand ON hr=0x%08lx\n", ff->SendForceFeedbackCommand(DISFFC_SETACTUATORSON));

    DWORD axes[1] = { DIJOFS_X };
    LONG dirs[1] = { 0 };
    DICONSTANTFORCE cf = { 6000 };
    DIEFFECT eff = { sizeof(DIEFFECT) };
    eff.dwFlags = DIEFF_CARTESIAN | DIEFF_OBJECTOFFSETS;
    eff.dwDuration = 400000; // 0.4 s
    eff.dwGain = DI_FFNOMINALMAX;
    eff.dwTriggerButton = DIEB_NOTRIGGER;
    eff.cAxes = 1;
    eff.rgdwAxes = axes;
    eff.rglDirection = dirs;
    eff.cbTypeSpecificParams = sizeof(cf);
    eff.lpvTypeSpecificParams = &cf;
    IDirectInputEffect* effect = nullptr;
    printf("CreateEffect hr=0x%08lx\n", ff->CreateEffect(GUID_ConstantForce, &eff, &effect, nullptr));
    printf("Start hr=0x%08lx\n", effect->Start(1, 0));
    Sleep(250);
    DWORD status = 0;
    effect->GetEffectStatus(&status);
    printf("status while playing=%lu\n", status);
    Sleep(400);
    effect->GetEffectStatus(&status);
    printf("status after duration=%lu\n", status);
    Sleep(100);
    effect->Release();
    ff->Unacquire();
    ff->Release();
    pad->Release();
    di2->Release();
    di->Release();
    return 0;
}
