// PatchMap.asi - diagnostic only, changes nothing. Once the game has started (menus reached, or 20 s), compares
// the exe's read-only sections (.text, .rdata) in memory with the file on disk and logs every changed range and
// which module its jumps, calls or pointers lead into; and checks every import slot against the function it
// should hold, logging the slots another module has redirected (how InputBridge and GfxProbe hook).
// Log: PatchMap.log next to this .asi. Lines:
//   RANGE start=0x... len=N section=.text|.rdata     a run of changed bytes (gaps under 8 bytes joined)
//   TARGET at=0x... kind=jmp|call|ptr dest=0x... module=<name>+0x...   where that range leads
//   OWNER start=0x... owner=<module of the first target>|-
//   IMPORT slot=0x... import=<dll>!<function> module=<name>+0x...      a redirected import slot
//   DONE ranges=N bytes=M imports=K
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <vector>

static FILE* g_log;

static void Log(const char* fmt, ...)
{
    if (!g_log) return;
    va_list a;
    va_start(a, fmt);
    vfprintf(g_log, fmt, a);
    fputc('\n', g_log);
    fflush(g_log);
    va_end(a);
}

static HMODULE ModuleAt(const void* addr)
{
    HMODULE m = nullptr;
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCSTR)addr, &m))
        return nullptr;
    return m;
}

static void ModuleOf(const void* addr, char* out, size_t n)
{
    out[0] = '-';
    out[1] = 0;
    HMODULE m = ModuleAt(addr);
    if (!m) return;
    char path[MAX_PATH];
    GetModuleFileNameA(m, path, MAX_PATH);
    const char* name = strrchr(path, '\\') ? strrchr(path, '\\') + 1 : path;
    snprintf(out, n, "%s+0x%lX", name, (unsigned long)((const BYTE*)addr - (const BYTE*)m));
}

static bool IsMapped(const void* p)
{
    MEMORY_BASIC_INFORMATION mbi;
    return VirtualQuery(p, &mbi, sizeof(mbi)) && mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
}

static bool Outside(BYTE* exeBase, DWORD exeSize, const BYTE* p)
{
    return (p < exeBase || p >= exeBase + exeSize) && IsMapped(p) && ModuleAt(p) != nullptr;
}

// Reports jumps/calls starting just before or inside [start, start+len) and pointers inside it that lead out of
// the exe into another module. The owner is the module of the first one found.
static void Targets(BYTE* exeBase, DWORD exeSize, BYTE* start, size_t len, char* owner, size_t ownerSize)
{
    owner[0] = '-';
    owner[1] = 0;
    for (BYTE* p = start - 1; p < start + len; ++p)
    {
        if (*p != 0xE8 && *p != 0xE9) continue;
        BYTE* dest = p + 5 + *(INT32*)(p + 1);
        if (!Outside(exeBase, exeSize, dest)) continue;
        char mod[MAX_PATH];
        ModuleOf(dest, mod, sizeof(mod));
        Log("TARGET at=0x%08X kind=%s dest=0x%08X module=%s", (unsigned)(UINT_PTR)p, *p == 0xE8 ? "call" : "jmp",
            (unsigned)(UINT_PTR)dest, mod);
        if (owner[0] == '-') { strncpy(owner, mod, ownerSize - 1); owner[ownerSize - 1] = 0; }
    }
    for (BYTE* p = (BYTE*)((UINT_PTR)start & ~(UINT_PTR)3); p + 4 <= start + len; p += 4)
    {
        BYTE* v = *(BYTE**)p;
        if (!Outside(exeBase, exeSize, v)) continue;
        char mod[MAX_PATH];
        ModuleOf(v, mod, sizeof(mod));
        Log("TARGET at=0x%08X kind=ptr dest=0x%08X module=%s", (unsigned)(UINT_PTR)p, (unsigned)(UINT_PTR)v, mod);
        if (owner[0] == '-') { strncpy(owner, mod, ownerSize - 1); owner[ownerSize - 1] = 0; }
    }
}

// Marks every import slot in `skip` (they are filled in by Windows at load, so their bytes always differ from the
// file) and logs the slots that do not hold the function they import. Reads the import descriptors from the file.
static int Imports(BYTE* exeBase, const std::vector<BYTE>& file, IMAGE_NT_HEADERS32* nt, std::vector<bool>& skip)
{
    auto rvaToFile = [&](DWORD rva) -> const BYTE* {
        auto* sec = IMAGE_FIRST_SECTION(nt);
        for (int s = 0; s < nt->FileHeader.NumberOfSections; ++s, ++sec)
            if (rva >= sec->VirtualAddress && rva < sec->VirtualAddress + sec->SizeOfRawData)
                return file.data() + sec->PointerToRawData + (rva - sec->VirtualAddress);
        return nullptr;
    };
    auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    auto* d = (const IMAGE_IMPORT_DESCRIPTOR*)rvaToFile(dir.VirtualAddress);
    int hooked = 0;
    for (; d && d->Name; ++d)
    {
        const char* dll = (const char*)rvaToFile(d->Name);
        HMODULE lib = dll ? GetModuleHandleA(dll) : nullptr;
        auto* names = (const IMAGE_THUNK_DATA32*)rvaToFile(d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk);
        for (int i = 0; names && names[i].u1.AddressOfData; ++i)
        {
            DWORD slotRva = d->FirstThunk + i * 4;
            for (int b = 0; b < 4; ++b)
                if (slotRva + b < skip.size()) skip[slotRva + b] = true;
            if (!lib) continue;
            char name[160];
            FARPROC expected;
            if (names[i].u1.Ordinal & IMAGE_ORDINAL_FLAG32)
            {
                expected = GetProcAddress(lib, (LPCSTR)(UINT_PTR)IMAGE_ORDINAL32(names[i].u1.Ordinal));
                snprintf(name, sizeof(name), "#%u", (unsigned)IMAGE_ORDINAL32(names[i].u1.Ordinal));
            }
            else
            {
                auto* byName = (const IMAGE_IMPORT_BY_NAME*)rvaToFile(names[i].u1.AddressOfData);
                if (!byName) continue;
                expected = GetProcAddress(lib, (LPCSTR)byName->Name);
                snprintf(name, sizeof(name), "%s", (const char*)byName->Name);
            }
            void* actual = *(void**)(exeBase + slotRva);
            if (!expected || actual == (void*)expected) continue;
            char mod[MAX_PATH];
            ModuleOf(actual, mod, sizeof(mod));
            Log("IMPORT slot=0x%08X import=%s!%s module=%s", (unsigned)(UINT_PTR)(exeBase + slotRva), dll, name, mod);
            ++hooked;
        }
    }
    return hooked;
}

static DWORD WINAPI Run(LPVOID)
{
    char envNow[4] = {};
    bool now = GetEnvironmentVariableA("PATCHMAP_NOW", envNow, sizeof(envNow)) > 0;
    if (!now)
    {
        // 20 s, or the game's menus reached (flow state 3 at 0x925E90 in speed.exe v1.3) after at least 3 s
        for (int i = 0; i < 200; ++i)
        {
            if (i >= 30 && IsMapped((void*)0x925E90) && *(volatile int*)0x925E90 == 3) break;
            Sleep(100);
        }
    }
    BYTE* exeBase = (BYTE*)GetModuleHandleA(nullptr);
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    FILE* f = fopen(path, "rb");
    if (!f) { Log("ERROR cannot read %s", path); return 0; }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::vector<BYTE> file(size);
    size_t got = fread(file.data(), 1, size, f);
    fclose(f);
    if ((long)got != size) { Log("ERROR short read of %s", path); return 0; }

    auto* dos = (IMAGE_DOS_HEADER*)file.data();
    auto* nt = (IMAGE_NT_HEADERS32*)(file.data() + dos->e_lfanew);
    if ((UINT_PTR)exeBase != nt->OptionalHeader.ImageBase)
    {
        Log("ERROR loaded at %p, file prefers 0x%08X: relocated, not compared", exeBase, (unsigned)nt->OptionalHeader.ImageBase);
        return 0;
    }
    DWORD exeSize = nt->OptionalHeader.SizeOfImage;
    Log("EXE %s base=%p size=0x%X", path, exeBase, (unsigned)exeSize);
    std::vector<bool> skip(exeSize, false);
    int imports = Imports(exeBase, file, nt, skip);

    auto* sec = IMAGE_FIRST_SECTION(nt);
    int ranges = 0;
    size_t bytes = 0;
    for (int s = 0; s < nt->FileHeader.NumberOfSections; ++s, ++sec)
    {
        char name[9] = {};
        memcpy(name, sec->Name, 8);
        if (strcmp(name, ".text") != 0 && strcmp(name, ".rdata") != 0) continue;
        DWORD n = sec->SizeOfRawData < sec->Misc.VirtualSize ? sec->SizeOfRawData : sec->Misc.VirtualSize;
        BYTE* mem = exeBase + sec->VirtualAddress;
        const BYTE* disk = file.data() + sec->PointerToRawData;
        auto differs = [&](DWORD i) { return mem[i] != disk[i] && !skip[sec->VirtualAddress + i]; };
        DWORD raw = 0, skipped = 0;
        for (DWORD i = 0; i < n; ++i)
            if (mem[i] != disk[i]) { ++raw; if (skip[sec->VirtualAddress + i]) ++skipped; }
        Log("SECTION name=%s start=0x%08X size=0x%X changed=%u import-slot-bytes=%u", name,
            (unsigned)(UINT_PTR)mem, (unsigned)n, (unsigned)raw, (unsigned)skipped);
        for (DWORD i = 0; i < n; )
        {
            if (!differs(i)) { ++i; continue; }
            DWORD start = i, last = i;
            for (DWORD j = i + 1; j < n && j <= last + 8; ++j)
                if (differs(j)) last = j;
            size_t len = last - start + 1;
            Log("RANGE start=0x%08X len=%u section=%s", (unsigned)(UINT_PTR)(mem + start), (unsigned)len, name);
            char owner[MAX_PATH];
            Targets(exeBase, exeSize, mem + start, len, owner, sizeof(owner));
            Log("OWNER start=0x%08X owner=%s", (unsigned)(UINT_PTR)(mem + start), owner);
            ++ranges;
            bytes += len;
            i = last + 1;
        }
    }
    Log("DONE ranges=%d bytes=%u imports=%d", ranges, (unsigned)bytes, imports);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        char path[MAX_PATH];
        GetModuleFileNameA(inst, path, MAX_PATH);
        char* dot = strrchr(path, '.');
        if (dot) strcpy(dot, ".log");
        g_log = fopen(path, "w");
        DisableThreadLibraryCalls(inst);
        HANDLE t = CreateThread(nullptr, 0, Run, nullptr, 0, nullptr);
        if (t) CloseHandle(t);
    }
    return TRUE;
}
