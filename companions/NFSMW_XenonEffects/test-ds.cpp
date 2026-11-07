// Checks that dropping a `ds:` segment prefix from a memory operand (prep.py, change 2) leaves the same
// instruction. Two naked functions do the same three operations on a global, one written with ds:[x] (the form
// Clang accepts with a prefix) and one plainly; their machine code is compared, ignoring a 0x3E (ds) prefix byte.
// Build: zig c++ -target x86-windows-gnu -O2 -fms-extensions -fasm-blocks -fdeclspec test-ds.cpp -o test-ds.exe
#include <stdio.h>
#include <string.h>

extern "C" float flt_9C2A3C = 2.0f;
extern "C" int dword_test = 5;

__declspec(naked) void WithPrefix()
{
    _asm
    {
        fmul dword ptr ds:[flt_9C2A3C]
        fcomp dword ptr ds:[flt_9C2A3C]
        mov eax, dword ptr ds:[dword_test]
        ret
    }
}

__declspec(naked) void Plain()
{
    _asm
    {
        fmul flt_9C2A3C
        fcomp flt_9C2A3C
        mov eax, dword_test
        ret
    }
}

static int Strip(const unsigned char* p, unsigned char* out)
{
    int n = 0;
    for (int i = 0; i < 64; ++i)
    {
        if (p[i] == 0x3E) continue;  // ds prefix: the default for these operands, no effect
        out[n++] = p[i];
        if (p[i] == 0xC3) break;     // ret
    }
    return n;
}

int main()
{
    unsigned char a[64], b[64];
    int na = Strip((const unsigned char*)&WithPrefix, a), nb = Strip((const unsigned char*)&Plain, b);
    for (int i = 0; i < na; ++i) printf("%02X ", a[i]);
    printf("\n");
    for (int i = 0; i < nb; ++i) printf("%02X ", b[i]);
    printf("\n");
    bool same = na == nb && memcmp(a, b, na) == 0;
    printf(same ? "SAME\n" : "DIFFERENT\n");
    return same ? 0 : 1;
}
