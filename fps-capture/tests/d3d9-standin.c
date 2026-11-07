// Stand-in for speed.exe: loads the installed plugin, presents D3D9 frames for ~4 s, exits.
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>

int main(void) {
    HMODULE m = LoadLibraryW(L"D:\\projects\\nfsmwbe\\Need For Speed Most Wanted Black Edition\\scripts\\FpsRecorder.asi");
    printf("plugin=%p pid=%lu\n", (void*)m, GetCurrentProcessId());
    fflush(stdout);

    HWND wnd = CreateWindowW(L"STATIC", L"d3dhost", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 320, 240, 0, 0, 0, 0);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {0};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_ONE;
    IDirect3DDevice9* dev = NULL;
    HRESULT hr = IDirect3D9_CreateDevice(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd,
        D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev);
    printf("device hr=0x%08lx\n", hr);

    DWORD end = GetTickCount() + 4000;
    int frames = 0;
    while (dev && GetTickCount() < end) {
        MSG msg;
        while (PeekMessageW(&msg, 0, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, D3DCOLOR_XRGB(frames & 255, 0, 0), 1.0f, 0);
        IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
        frames++;
    }
    printf("presented %d frames\n", frames);
    return 0;
}
