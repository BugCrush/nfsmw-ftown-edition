// fxdump: prints a compiled effect as text (techniques, passes, shader assembly) with the game's own
// version of the effect library, d3dx9_26.dll. Read-only analysis tool.
//   zig c++ -target x86-windows-gnu -O2 fxdump.cpp -ld3d9 -ld3dx9_26 -luser32 -o fxdump.exe
//   fxdump.exe <effect file>...     (effect files: python tools/fx-inspect.py effects speed.exe --out <dir>)
#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <stdio.h>

int main(int argc, char** argv)
{
    HWND wnd = CreateWindowExA(0, "STATIC", "fxdump", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, nullptr, nullptr, nullptr, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.BackBufferWidth = 64;
    pp.BackBufferHeight = 64;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    IDirect3DDevice9* dev = nullptr;
    if (FAILED(d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev)))
        return 1;
    static char data[1 << 20];
    for (int i = 1; i < argc; ++i)
    {
        FILE* f = fopen(argv[i], "rb");
        if (!f)
        {
            printf("==== %s: cannot open\n", argv[i]);
            continue;
        }
        size_t size = fread(data, 1, sizeof(data), f);
        fclose(f);
        ID3DXEffect* fx = nullptr;
        ID3DXBuffer* errors = nullptr, * text = nullptr;
        HRESULT hr = D3DXCreateEffect(dev, data, (UINT)size, nullptr, nullptr, 0, nullptr, &fx, &errors);
        printf("==== %s (%u bytes) hr=0x%08lx %s\n", argv[i], (unsigned)size, hr, errors ? (const char*)errors->GetBufferPointer() : "");
        if (fx && SUCCEEDED(D3DXDisassembleEffect(fx, FALSE, &text)))
            fwrite(text->GetBufferPointer(), 1, text->GetBufferSize() - 1, stdout);
        printf("\n");
    }
    return 0;
}
