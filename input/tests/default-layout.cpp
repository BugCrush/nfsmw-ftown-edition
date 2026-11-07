// Stand-in for speed.exe to test InputBridge's [Controls] DefaultLayout. It puts, at the game's own addresses, the
// bytes InputBridge checks and a small function at 0x63CD80 shaped like the game's "controller defaults for this
// pad": the game's first two instructions, then a call to FillGameDefaults below, which writes the generic defaults
// speed.exe v1.3 gives an unknown pad (decoded from 0x63EAC0: A accelerate, X brake, no shifting...) into the
// controller slots of the 24 records of the bindings table at 0x91F418 (0x34 bytes each). The first joystick object
// is at *0x91F150 with its product name at +0x114.
// Then it loads InputBridge.asi, calls 0x63CD80 twice (as the game does at start and on "restore defaults") and
// prints every record. Arguments: the pad ("xbox", "wheel", "nopad"); "wrongbytes" = the function's first bytes
// differ from the game's (InputBridge must refuse); "wrongtable" = the table's address in the copy loop differs.
// Output: CALLS <n> (times the game's function ran), then REC <i> <13 dwords> per record.
#include <windows.h>
#include <stdio.h>
#include <string.h>

// The game's addresses must be ours: the stand-in is linked at 0x400000 without relocation, and this array
// (in the image, so at a fixed address) spans them.
static BYTE g_space[0x600000];
static int g_gameCalls;
static BYTE g_pad[0x200];

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

static DWORD* Rec(int i)
{
    return (DWORD*)(UINT_PTR)(0x91F418 + i * 0x34);
}

// The generic defaults (the branch the user's pad took; slot (type, device, index), 0 = none).
static const DWORD kGeneric[24][6] = {
    { 2, 0, 0 }, { 2, 0, 2 }, { 4, 0, 0 }, { 5, 0, 0 }, { 2, 0, 1 }, { 2, 0, 3 }, { 2, 0, 6 }, { 0 }, { 0 }, { 2, 0, 5 },
    { 3, 0, 0 }, { 3, 0, 2 }, { 3, 0, 3 }, { 3, 0, 1 }, { 0 }, { 0 }, { 2, 0, 4 }, { 0 }, { 2, 0, 7 },
    { 3, 0, 3, 4, 0, 0 }, { 3, 0, 1, 5, 0, 0 }, { 3, 0, 0, 4, 0, 1 }, { 3, 0, 2, 5, 0, 1 }, { 0 },
};

extern "C" void __cdecl FillGameDefaults()
{
    ++g_gameCalls;
    for (int i = 0; i < 24; ++i)
        memcpy(Rec(i) + 7, kGeneric[i], sizeof(kGeneric[i]));
    // A second-controller binding on Steer Left, as some known pads get: InputBridge must clear it.
    Rec(2)[10] = 3;
    Rec(2)[12] = 3;
}

int main(int argc, char** argv)
{
    const char* pad = "xbox";
    bool wrongBytes = false, wrongTable = false;
    for (int i = 1; i < argc; ++i)
    {
        if (!strcmp(argv[i], "wrongbytes"))
            wrongBytes = true;
        else if (!strcmp(argv[i], "wrongtable"))
            wrongTable = true;
        else
            pad = argv[i];
    }
    Reserve(0x628000, 0x1000);
    Reserve(0x63C000, 0x4000);
    Reserve(0x91F000, 0x2000);
    memset((void*)0x628000, 0xCC, 0x1000);
    memset((void*)0x63C000, 0xCC, 0x4000);

    // 0x63CD80: mov eax, [0x91F150]; sub esp, 0x240 | add esp, 0x240; mov eax, FillGameDefaults; call eax; ret
    const BYTE entry[] = { 0xA1, 0x50, 0xF1, 0x91, 0x00, 0x81, 0xEC, 0x40, 0x02, 0x00, 0x00,
                           0x81, 0xC4, 0x40, 0x02, 0x00, 0x00, 0xB8, 0, 0, 0, 0, 0xFF, 0xD0, 0xC3 };
    Put(0x63CD80, entry, sizeof(entry));
    *(DWORD*)0x63CD92 = (DWORD)(UINT_PTR)&FillGameDefaults;
    if (wrongBytes)
        *(BYTE*)0x63CD81 = 0x54; // mov eax, [0x91F154]: still runs, other bytes (as if another module changed them)
    const BYTE loopStart[] = { 0xB8, 0x40, 0xF4, 0x91, 0x00 };
    Put(0x63EE8E, loopStart, sizeof(loopStart));
    const BYTE loopEnd[] = { 0x3D, 0x20, 0xF9, 0x91, 0x00 };
    Put(0x63EEC4, loopEnd, sizeof(loopEnd));
    if (wrongTable)
        *(BYTE*)0x63EE8F = 0x44;
    const BYTE accessor[] = { 0x8B, 0x44, 0x24, 0x04, 0x6B, 0xC0, 0x34, 0x05, 0x1C, 0xF4, 0x91, 0x00, 0xC2, 0x04, 0x00 };
    Put(0x628CB0, accessor, sizeof(accessor));

    // The table before: keyboard slots as the game's defaults have them (type 1, a key), controllers empty.
    for (int i = 0; i < 24; ++i)
    {
        Rec(i)[1] = 1;
        Rec(i)[2] = 0x10 + i;
    }
    if (!strcmp(pad, "xbox"))
        strcpy((char*)g_pad + 0x114, "Controller (Controller(XBOX 360 For Windows))");
    else if (!strcmp(pad, "wheel"))
        strcpy((char*)g_pad + 0x114, "Logitech G29 Driving Force Racing Wheel");
    *(DWORD*)0x91F150 = strcmp(pad, "nopad") ? (DWORD)(UINT_PTR)g_pad : 0;

    if (!LoadLibraryA("InputBridge.asi"))
    {
        printf("LoadLibrary failed: %lu\n", GetLastError());
        return 3;
    }
    ((void (*)())0x63CD80)(); // the game's input start
    ((void (*)())0x63CD80)(); // "restore defaults" in the Controls menu
    printf("CALLS %d\n", g_gameCalls);
    for (int i = 0; i < 24; ++i)
    {
        printf("REC %d", i);
        for (int k = 0; k < 13; ++k)
            printf(" %lu", (unsigned long)Rec(i)[k]);
        printf("\n");
    }
    return 0;
}
