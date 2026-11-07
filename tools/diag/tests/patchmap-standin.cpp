// Stand-in for PatchMap's test: a program that patches itself the ways game mods do, then loads PatchMap.asi.
//   1. a 5-byte jump (E9) at the start of Victim() into Replacement() in patchmap-standin-mod.dll
//   2. 8 plain bytes (CC) written over the start of Plain()            -> a range with no owner
//   3. a pointer in a read-only table (.rdata) replaced by one into the mod DLL
//   4. its import slot for GetTickCount pointed at the mod DLL          -> an import hook, like InputBridge's
// Built twice from this file: with -DMOD as the DLL, without as the program. PATCHMAP_NOW=1 makes PatchMap
// compare at once instead of waiting for the game's menus.
#include <windows.h>
#include <stdio.h>

#ifdef MOD
extern "C" __declspec(dllexport) int Replacement() { return 42; }
// No WINAPI: on x86 it would be exported as FakeTickCount@0. With no arguments the two conventions are the same.
extern "C" __declspec(dllexport) DWORD FakeTickCount() { return 7; }
BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
#else

static volatile int g_sink;

extern "C" __attribute__((noinline)) int Victim()
{
    for (int i = 0; i < 40; ++i) g_sink += i * 3;  // a long body keeps Plain() well apart
    return g_sink;
}

extern "C" __attribute__((noinline)) int Plain()
{
    for (int i = 0; i < 40; ++i) g_sink -= i;
    return g_sink;
}

static void A() {}
static void B() {}
extern "C" void (* const g_table[2])() = {A, B};

static void Write(void* at, const void* bytes, size_t n)
{
    DWORD old;
    VirtualProtect(at, n, PAGE_EXECUTE_READWRITE, &old);
    // Byte by byte through volatile: g_table is const, and the compiler may drop a memcpy into a const object.
    for (size_t i = 0; i < n; ++i) ((volatile BYTE*)at)[i] = ((const BYTE*)bytes)[i];
    VirtualProtect(at, n, old, &old);
}

// The import slot that holds GetTickCount in this program's import table.
static void** ImportSlot(const char* dll, const char* name)
{
    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    auto* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (auto* d = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); d->Name; ++d)
    {
        if (lstrcmpiA((char*)(base + d->Name), dll) != 0) continue;
        auto* names = (IMAGE_THUNK_DATA*)(base + (d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk));
        auto* slots = (void**)(base + d->FirstThunk);
        for (int i = 0; names[i].u1.AddressOfData; ++i)
            if (!(names[i].u1.Ordinal & IMAGE_ORDINAL_FLAG) &&
                strcmp((char*)((IMAGE_IMPORT_BY_NAME*)(base + names[i].u1.AddressOfData))->Name, name) == 0)
                return &slots[i];
    }
    return nullptr;
}

int main()
{
    freopen("standin.log", "w", stdout);
    setvbuf(stdout, nullptr, _IONBF, 0);
    HMODULE mod = LoadLibraryA("patchmap-standin-mod.dll");
    if (!mod) { printf("patchmap-standin-mod.dll not found\n"); return 2; }
    BYTE* target = (BYTE*)GetProcAddress(mod, "Replacement");
    BYTE jmp[5] = {0xE9};
    *(INT32*)(jmp + 1) = (INT32)(target - ((BYTE*)&Victim + 5));
    Write((void*)&Victim, jmp, 5);

    BYTE cc[8] = {0xCC, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC};
    Write((void*)&Plain, cc, 8);

    void* fake = (void*)GetProcAddress(mod, "Replacement");
    Write((void*)&g_table[1], &fake, sizeof(fake));

    void** slot = ImportSlot("KERNEL32.dll", "GetTickCount");
    if (!slot) { printf("no GetTickCount import slot\n"); return 3; }
    void* tick = (void*)GetProcAddress(mod, "FakeTickCount");
    Write(slot, &tick, sizeof(tick));
    printf("patched: Victim %p, Plain %p, table %p (now %p, mod fn %p), import slot %p\n", (void*)&Victim,
           (void*)&Plain, (void*)&g_table[1], *(void* volatile*)&g_table[1], fake, (void*)slot);

    SetEnvironmentVariableA("PATCHMAP_NOW", "1");
    if (!LoadLibraryA("PatchMap.asi")) { printf("PatchMap.asi not found\n"); return 4; }
    Sleep(2000);
    printf("tick %lu\n", GetTickCount());  // keeps the import used
    return 0;
}
#endif
