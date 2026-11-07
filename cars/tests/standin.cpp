// Stand-in for speed.exe to test CarStable.asi. It puts code shaped like the game's at the game's own addresses
// (docs/cars-notes.md "Addresses for CarStable"):
//  - 0x5AB999: the end of cFrontendDatabase::Default: bCalculateCrc32(copy of the default stable, 0x8CC8, -1) with
//    the call at 0x5AB9A5 (E8 to 0x45CA60), result stored as the current fingerprint (FEDatabase + 8);
//  - 0x5ACB70: a UserProfile::LoadFromBuffer with the same stack frame: saved fingerprint in esi, the compare at
//    0x5ACBF1..0x5ACBFF (jne 0x5ACD51 = refuse), the stable copied at 0x5ACC00, the success path at 0x5ACD5D
//    (mov al,[esp+0x40]; test al,al), returning true at 0x5ACDB9;
//  - 0x57FB50: GetDefaultCar (returns handle 0).
// It loads CarStable.asi, "boots" (makes the fingerprint), then loads a profile and prints what happened.
// Arguments: defaults=<letters> (stock cars of the game now, one per letter, VehicleKey = the letter),
// loaded=<letters> (stock cars in the save), owned=<letter> (a bought car in the save: current car and Quick Race 5),
// fp=<hex>|current (the save's fingerprint), wrongbytes (the compare's bytes differ from the game's).
// Output: LOAD ok|refused; STABLE <slot>:<key>:<bits> ...; CURRENT <handle>; QR5 <handle>; FREECUSTOM <n>.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <initializer_list>

static BYTE g_space[0x600000];

static void Reserve(DWORD address, DWORD size)
{
    if (address < (DWORD)(UINT_PTR)g_space || address + size > (DWORD)(UINT_PTR)g_space + sizeof(g_space))
    {
        printf("0x%08lX is not inside the stand-in's space (%p..+0x%X)\n", (unsigned long)address, (void*)g_space, (unsigned)sizeof(g_space));
        ExitProcess(2);
    }
    DWORD old;
    VirtualProtect((void*)address, size, PAGE_EXECUTE_READWRITE, &old);
    memset((void*)address, 0xCC, size);
}

static BYTE* g_p;
static void At(DWORD a) { g_p = (BYTE*)a; }
static void B(std::initializer_list<int> bytes) { for (int b : bytes) *g_p++ = (BYTE)b; }
static void D(DWORD v) { memcpy(g_p, &v, 4); g_p += 4; }
static void Rel(DWORD target) { D(target - ((DWORD)(UINT_PTR)g_p + 4)); }

static const DWORD kFEDatabase = 0x91E000, kProfile = 0x920000, kSavedFP = 0x91D000;
static const int kStable = 0x8CC8;
static BYTE g_defaults[kStable], g_saved[kStable];
static DWORD g_savedCurrent, g_savedQR5;

static void Blank(BYTE* img)
{
    memset(img, 0, kStable);
    for (int i = 0; i < 200; i++) *(DWORD*)(img + i * 0x14) = 0xFFFFFFFF;
    for (int i = 0; i < 75; i++) img[0xFA0 + i * 0x198 + 0x194] = 0xFF;
    for (int i = 0; i < 25; i++) img[0x8728 + i * 0x38] = 0xFF;
}

static void Put(BYTE* img, int slot, DWORD key, DWORD bits, BYTE custom = 0xFF, BYTE career = 0xFF)
{
    BYTE* r = img + slot * 0x14;
    *(DWORD*)r = slot;
    *(DWORD*)(r + 4) = key + 0x100;
    *(DWORD*)(r + 8) = key;
    *(DWORD*)(r + 0xC) = bits;
    r[0x10] = custom;
    r[0x11] = career;
    if (custom != 0xFF) img[0xFA0 + custom * 0x198 + 0x194] = custom;
    if (career != 0xFF) img[0x8728 + career * 0x38] = career;
}

extern "C" DWORD __cdecl StandinCrc(const BYTE* p, int n, DWORD seed)
{
    DWORD c = seed;
    for (int i = 0; i < n; i++)
    {
        c ^= p[i];
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return c;
}

// Called at 0x5ACC00 (after the compare passed): the game copies the saved stable and, later, the Quick Race cars.
extern "C" void __cdecl LoadStable()
{
    memcpy((void*)(kProfile + 0x414), g_saved, kStable);
    *(DWORD*)(kFEDatabase + 0x1C + 0x18 * 5 + 0x10) = g_savedQR5;
}

int main(int argc, char** argv)
{
    const char *defaults = "AB", *loaded = "AB", *fp = "current";
    char owned = 0;
    bool wrong = false, fill = false, overwrite = false;
    for (int i = 1; i < argc; i++)
    {
        if (!strncmp(argv[i], "defaults=", 9)) defaults = argv[i] + 9;
        else if (!strncmp(argv[i], "loaded=", 7)) loaded = argv[i] + 7;
        else if (!strncmp(argv[i], "owned=", 6)) owned = argv[i][6];
        else if (!strncmp(argv[i], "fp=", 3)) fp = argv[i] + 3;
        else if (!strcmp(argv[i], "wrongbytes")) wrong = true;
        else if (!strcmp(argv[i], "fill")) fill = true;            // the save's stable full (bought copies of car 1)
        else if (!strcmp(argv[i], "overwrite")) overwrite = true;  // a later plugin restores 0x5ACD5D's bytes
    }
    Reserve(0x45C000, 0x1000);
    Reserve(0x57F000, 0x1000);
    Reserve(0x5AB000, 0x2000);
    Reserve(0x91C000, 0x3000);
    Reserve(kProfile, 0xA000);
    memset((void*)0x91C000, 0, 0x3000);
    memset((void*)kProfile, 0, 0xA000);
    *(DWORD*)0x91CF90 = kFEDatabase;
    *(DWORD*)(kFEDatabase + 0x10) = kProfile;

    // bCalculateCrc32 and GetDefaultCar.
    At(0x45CA60); B({0xE9}); Rel((DWORD)(UINT_PTR)&StandinCrc);
    At(0x57FB50); B({0x31, 0xC0, 0xC3});                                   // xor eax, eax; ret
    // Boot: push -1; push 0x8CC8; push g_defaults; call 0x45CA60 (at 0x5AB9A5); mov [FEDatabase+8], eax; add esp,0xC; ret
    At(0x5AB999); B({0x6A, 0xFF, 0x68}); D(kStable); B({0x68}); D((DWORD)(UINT_PTR)g_defaults);
    B({0xE8}); Rel(0x45CA60);
    B({0xA3}); D(kFEDatabase + 8); B({0x83, 0xC4, 0x0C, 0xC3});
    // LoadFromBuffer(buffer, size, commit, player), thiscall on the profile.
    At(0x5ACB70); B({0x83, 0xEC, 0x24, 0x53, 0x55, 0x8B, 0xE9, 0x56, 0x57});  // sub esp,0x24; push ebx; push ebp; mov ebp,ecx; push esi; push edi
    B({0x8B, 0x35}); D(kSavedFP);                                          // mov esi, [saved fingerprint]
    B({0xE9}); Rel(0x5ACBF1);
    At(0x5ACBF1); B({0x8B, 0x0D}); D(0x91CF90);                            // mov ecx, [0x91CF90]
    B({0x3B, 0x71, 0x08});                                                 // cmp esi, [ecx+8]
    B({0x0F, 0x85, 0x51, 0x01, 0x00, 0x00});                               // jne 0x5ACD51
    if (wrong)
    {
        // Same behaviour, other bytes, as another module's detour would leave it: jne 0x5ACC80, where a jmp goes on to
        // the refusal at 0x5ACD51.
        At(0x5ACBFA); B({0x0F, 0x85}); Rel(0x5ACC80);
        At(0x5ACC80); B({0xE9}); Rel(0x5ACD51);
    }
    At(0x5ACC00); B({0xE8}); Rel((DWORD)(UINT_PTR)&LoadStable); B({0xE9}); Rel(0x5ACD5D);
    At(0x5ACD51); B({0x5F, 0x5E, 0x5D, 0x32, 0xC0, 0x5B, 0x83, 0xC4, 0x24, 0xC2, 0x10, 0x00});
    At(0x5ACD5D); B({0x8A, 0x44, 0x24, 0x40, 0x84, 0xC0, 0xC6, 0x45, 0x20, 0x01}); B({0xE9}); Rel(0x5ACDB9);
    At(0x5ACDB9); B({0x5F, 0x5E, 0x5D, 0xB0, 0x01, 0x5B, 0x83, 0xC4, 0x24, 0xC2, 0x10, 0x00});
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);

    // The game's cars now (default stable) and the save's.
    Blank(g_defaults);
    int slot = 0;
    for (const char* c = defaults; *c; c++) Put(g_defaults, slot++, (DWORD)*c, 1 | 0x10000);
    Blank(g_saved);
    slot = 0;
    for (const char* c = loaded; *c; c++) Put(g_saved, slot++, (DWORD)*c, 1 | 0x10000);
    g_savedCurrent = 0;
    g_savedQR5 = 0;
    if (owned)
    {
        Put(g_saved, slot, (DWORD)owned, 2 | 0x10000, 0, 0);
        g_savedCurrent = g_savedQR5 = slot;
    }
    if (fill)
        for (int s = 0; s < 200; s++)
            if (*(DWORD*)(g_saved + s * 0x14) == 0xFFFFFFFF) Put(g_saved, s, (DWORD)loaded[0], 2 | 0x10000);

    HMODULE plugin = LoadLibraryA("CarStable.asi");
    printf("plugin=%s\n", plugin ? "loaded" : "missing");
    if (overwrite)
    {
        At(0x5ACD5D); B({0x8A, 0x44, 0x24, 0x40, 0x84, 0xC0});
        FlushInstructionCache(GetCurrentProcess(), nullptr, 0);
    }
    ((void(__cdecl*)())0x5AB999)();                                        // boot
    DWORD current = *(DWORD*)(kFEDatabase + 8);
    *(DWORD*)kSavedFP = !strcmp(fp, "current") ? current : strtoul(fp, nullptr, 16);
    printf("FINGERPRINT 0x%08lX\n", (unsigned long)current);
    *(DWORD*)(kProfile + 0xA8) = g_savedCurrent;                          // career settings load before the compare

    typedef bool(__thiscall * LoadFn)(void*, void*, int, bool, int);
    bool ok = ((LoadFn)0x5ACB70)((void*)kProfile, nullptr, 0, true, 0);
    printf("LOAD %s\n", ok ? "ok" : "refused");
    printf("STABLE");
    for (int i = 0; i < 200; i++)
    {
        BYTE* r = (BYTE*)(kProfile + 0x414 + i * 0x14);
        if (*(DWORD*)r != 0xFFFFFFFF && *(DWORD*)(r + 8))
            printf(" %d:%c:%lX", i, (char)*(DWORD*)(r + 8), (unsigned long)*(DWORD*)(r + 0xC));
    }
    printf("\nCURRENT %lu\n", (unsigned long)*(DWORD*)(kProfile + 0xA8));
    printf("QR5 %lu\n", (unsigned long)*(DWORD*)(kFEDatabase + 0x1C + 0x18 * 5 + 0x10));
    int freeCustom = 0;
    for (int i = 0; i < 75; i++) freeCustom += *(BYTE*)(kProfile + 0x414 + 0xFA0 + i * 0x198 + 0x194) == 0xFF;
    printf("FREECUSTOM %d\n", freeCustom);
    return 0;
}
