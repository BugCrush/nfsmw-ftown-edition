// Stand-in for speed.exe to test ReflectRate.asi. It puts, at the game's own addresses, the bytes ReflectRate
// patches and a small loop shaped like the game's face loop (0x6DE675 .. 0x6DE85B): for each of the six views
// 16..21 (0x919DC0 .. 0x919FF0, 0x70 bytes each) it tests the view's "switched on" byte (+8) and, if on, "draws"
// the face by adding 1 to a counter in the view (+0x6C). Then it loads ReflectRate.asi and runs the loop as a
// frame, many times, and prints how often each face was drawn.
// Arguments: "wrongbytes" = the bytes at 0x6DE680 differ from the game's (the plugin must refuse);
// "leftoff" = view 19 (left) is switched off. Output: FACES lines, one per batch.
#include <windows.h>
#include <stdio.h>
#include <string.h>

// The game's addresses must be ours: the stand-in is linked at 0x400000 without relocation, and this array
// (in the image, so at a fixed address) spans them. Made executable where the loop goes.
static BYTE g_space[0x600000];

static BYTE* Reserve(DWORD address, DWORD size)
{
    if (address < (DWORD)(UINT_PTR)g_space || address + size > (DWORD)(UINT_PTR)g_space + sizeof(g_space))
    {
        printf("0x%08lX is not inside the stand-in's space (%p..+0x%X)\n", (unsigned long)address, (void*)g_space, (unsigned)sizeof(g_space));
        ExitProcess(2);
    }
    DWORD old;
    VirtualProtect((void*)address, size, PAGE_EXECUTE_READWRITE, &old);
    return (BYTE*)address;
}

static void Put(DWORD address, const BYTE* bytes, size_t n)
{
    memcpy((void*)address, bytes, n);
}

static void Rel32(DWORD at, DWORD target) // a jump/call whose rel32 field is at 'at'
{
    *(DWORD*)at = target - (at + 4);
}

int main(int argc, char** argv)
{
    bool wrong = false, leftOff = false, shadowWrong = false, shadowNoAccess = false;
    for (int i = 1; i < argc; ++i)
    {
        wrong |= !strcmp(argv[i], "wrongbytes");
        leftOff |= !strcmp(argv[i], "leftoff");
        shadowWrong |= !strcmp(argv[i], "shadowwrong");
        shadowNoAccess |= !strcmp(argv[i], "shadownoaccess");
    }
    Reserve(0x6DE000, 0x1000);
    Reserve(0x919000, 0x2000);
    memset((void*)0x6DE000, 0xCC, 0x1000);
    // The frame: a function at 0x6DE670.
    const BYTE prologue[] = { 0x53, 0x56, 0x31, 0xDB, 0x90 };              // push ebx; push esi; xor ebx, ebx; nop
    Put(0x6DE670, prologue, sizeof(prologue));
    const BYTE first[] = { 0xBE, 0xC0, 0x9D, 0x91, 0x00 };                  // 0x6DE675 mov esi, 0x919DC0
    Put(0x6DE675, first, sizeof(first));
    const BYTE pad[] = { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };               // 0x6DE67A .. 0x6DE67F
    Put(0x6DE67A, pad, sizeof(pad));
    const BYTE test[] = { 0x38, 0x5E, 0x08, 0x0F, 0x84, 0xC3, 0x01, 0x00, 0x00 }; // 0x6DE680 cmp byte [esi+8], bl; je 0x6DE84C
    Put(0x6DE680, test, sizeof(test));
    if (wrong)
        *(BYTE*)0x6DE680 = 0x3A; // cmp bl, byte [esi+8]: the same test, other bytes (as if another module had changed them)
    const BYTE draw[] = { 0xFF, 0x46, 0x6C, 0xE9, 0, 0, 0, 0 };             // 0x6DE689 inc dword [esi+0x6C]; jmp 0x6DE84C
    Put(0x6DE689, draw, sizeof(draw));
    Rel32(0x6DE68D, 0x6DE84C);
    const BYTE next[] = { 0x83, 0xC6, 0x70, 0x81, 0xFE, 0xF0, 0x9F, 0x91, 0x00, 0x0F, 0x8E, 0, 0, 0, 0 }; // add esi, 0x70; cmp esi, 0x919FF0; jle 0x6DE680
    Put(0x6DE84C, next, sizeof(next));
    Rel32(0x6DE857, 0x6DE680);
    const BYTE epilogue[] = { 0x5E, 0x5B, 0xC3 };                           // 0x6DE85B pop esi; pop ebx; ret
    Put(0x6DE85B, epilogue, sizeof(epilogue));
    // The shadow map: the game draws it with one call per frame at 0x6DEC72 (call 0x6E54E0 with the main view and a
    // matrix, cdecl, two arguments). Here 0x6DEC6B: push 0; push 0x919650; call; add esp, 8; ret; and the stand-in
    // for 0x6E54E0 adds 1 to a counter at 0x919010. "shadowwrong": the call goes to 0x6E54F0 instead (another
    // function: the plugin must leave it alone); that one counts too.
    Reserve(0x6E5000, 0x1000);
    memset((void*)0x6E5000, 0xCC, 0x1000);
    const BYTE shadowCall[] = { 0x6A, 0x00, 0x68, 0x50, 0x96, 0x91, 0x00, 0xE8, 0, 0, 0, 0, 0x83, 0xC4, 0x08, 0xC3 };
    Put(0x6DEC6B, shadowCall, sizeof(shadowCall));
    Rel32(0x6DEC73, shadowWrong ? 0x6E54F0 : 0x6E54E0);
    const BYTE shadowDraw[] = { 0xFF, 0x05, 0x10, 0x90, 0x91, 0x00, 0xC3 }; // inc dword [0x919010]; ret
    Put(0x6E54E0, shadowDraw, sizeof(shadowDraw));
    Put(0x6E54F0, shadowDraw, sizeof(shadowDraw));
    FlushInstructionCache(GetCurrentProcess(), (void*)0x6E5000, 0x1000);
    FlushInstructionCache(GetCurrentProcess(), (void*)0x6DE000, 0x1000);
    // "shadownoaccess": the page holding the shadow call cannot be read while the plugin loads (as if unmapped or
    // guarded): the plugin must not touch it (no crash) and must say so. Made readable again after loading.
    if (shadowNoAccess)
    {
        DWORD old;
        VirtualProtect((void*)0x6DEC00, 0x100, PAGE_NOACCESS, &old);
    }
    for (int view = 16; view <= 21; ++view)
        *(BYTE*)(0x9196C0 + view * 0x70 + 8) = (leftOff && view == 19) ? 0 : 1;

    HMODULE plugin = LoadLibraryA("ReflectRate.asi");
    if (shadowNoAccess)
    {
        // The whole 4 KB page (0x6DE000, the face loop too) was unreadable while the plugin loaded: readable again.
        DWORD old;
        VirtualProtect((void*)0x6DEC00, 0x100, PAGE_EXECUTE_READWRITE, &old);
    }
    printf("plugin=%p patched=%s\n", (void*)plugin, *(BYTE*)0x6DE680 == 0xE9 ? "yes" : "no");
    if (*(BYTE*)0x6DE680 == 0xE9)
    {
        // PatchMap names a patch's owner by the module its jump lands in: it must be the plugin's own image.
        DWORD dest = 0x6DE680 + 5 + *(DWORD*)0x6DE681;
        HMODULE owner = nullptr;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)dest, &owner);
        printf("jump lands in %s\n", owner && owner == plugin ? "the plugin" : "no module of its own");
    }
    printf("shadow call patched=%s\n", (0x6DEC77 + *(DWORD*)0x6DEC73) == (shadowWrong ? 0x6E54F0u : 0x6E54E0u) ? "no" : "yes");
    typedef void(__cdecl * FrameFn)();
    FrameFn faces = (FrameFn)0x6DE670, shadow = (FrameFn)0x6DEC6B;
    char shadows[256];
    // Batch 1: 100 frames in a row. Batch 2: after a gap of 1.2 s (as after the menus), 10 frames.
    const int batches[2] = { 100, 10 };
    for (int b = 0; b < 2; ++b)
    {
        if (b)
            Sleep(1200);
        for (int view = 16; view <= 21; ++view)
            *(DWORD*)(0x9196C0 + view * 0x70 + 0x6C) = 0;
        printf("MASKS batch=%d", b + 1);
        for (int i = 0; i < batches[b]; ++i)
        {
            DWORD before[6];
            for (int view = 16; view <= 21; ++view)
                before[view - 16] = *(DWORD*)(0x9196C0 + view * 0x70 + 0x6C);
            DWORD shadowBefore = *(DWORD*)0x919010;
            faces();
            shadow();
            shadows[i] = *(DWORD*)0x919010 != shadowBefore ? '1' : '0';
            int mask = 0; // bit 0 = view 16 (front) .. bit 5 = view 21 (down): which faces were drawn this frame
            for (int view = 16; view <= 21; ++view)
                if (*(DWORD*)(0x9196C0 + view * 0x70 + 0x6C) != before[view - 16])
                    mask |= 1 << (view - 16);
            printf(" %02x", mask);
        }
        printf("\n");
        shadows[batches[b]] = 0;
        printf("SHADOWS batch=%d %s\n", b + 1, shadows);
        printf("FACES batch=%d frames=%d", b + 1, batches[b]);
        for (int view = 16; view <= 21; ++view)
            printf(" %d", (int)*(DWORD*)(0x9196C0 + view * 0x70 + 0x6C));
        printf("\n");
    }
    // One more frame a second later so the plugin writes its once-a-second line for batch 2.
    Sleep(1100);
    faces();
    shadow();
    return 0;
}
