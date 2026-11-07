// How long VisualBridge's depth-pass shaders take to compile with the game's compiler (d3dx9_26) and how big they come
// out: one line per entry point (milliseconds, instruction slots). A shader that takes seconds stalls the game's first
// frame that uses it.
//     shader-compile-time.exe [entry ...]     (no arguments: every entry point)
#include <windows.h>
#include <d3dx9.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "../src/shaders.h"

int main(int argc, char** argv)
{
    static const char* const kAll[] = { "Pass3VS", "DepthView", "AO", "AOBlur", "AOApply", "AOFactor", "Smooth", "Haze", "ShaftsMask",
                                        "ShaftsApply", "Wet", "SmoothWet" };
    // --flags N: D3DXSHADER_* flags for the compile (e.g. 1024 = PREFER_FLOW_CONTROL, 4 = SKIPOPTIMIZATION).
    DWORD flags = 0;
    if (argc > 2 && !strcmp(argv[1], "--flags"))
    {
        flags = strtoul(argv[2], nullptr, 0);
        argv += 2;
        argc -= 2;
    }
    int count = argc > 1 ? argc - 1 : (int)(sizeof(kAll) / sizeof(kAll[0]));
    int failures = 0;
    for (int i = 0; i < count; ++i)
    {
        const char* name = argc > 1 ? argv[i + 1] : kAll[i];
        ID3DXBuffer* code = nullptr, * errors = nullptr, * text = nullptr;
        LARGE_INTEGER f, a, b;
        QueryPerformanceFrequency(&f);
        QueryPerformanceCounter(&a);
        HRESULT hr = D3DXCompileShader(kShader3Source, (UINT)strlen(kShader3Source), nullptr, nullptr, name,
            !strcmp(name, "Pass3VS") ? "vs_3_0" : "ps_3_0", flags, &code, &errors, nullptr);
        QueryPerformanceCounter(&b);
        double ms = (double)(b.QuadPart - a.QuadPart) * 1000.0 / (double)f.QuadPart;
        if (FAILED(hr))
        {
            ++failures;
            printf("%-12s FAILED %s\n", name, errors ? (const char*)errors->GetBufferPointer() : "");
            continue;
        }
        int slots = -1;
        if (SUCCEEDED(D3DXDisassembleShader((const DWORD*)code->GetBufferPointer(), FALSE, nullptr, &text)))
        {
            const char* t = (const char*)text->GetBufferPointer();
            const char* at = strstr(t, "approximately ");
            if (at)
                slots = atoi(at + 14);
            if (argc > 2 && !strcmp(argv[argc - 1], "--dump"))
                printf("%s\n", t);
        }
        printf("%-12s %8.0f ms  %5d instruction slots  %u bytes\n", name, ms, slots, (unsigned)code->GetBufferSize());
    }
    return failures ? 1 : 0;
}
