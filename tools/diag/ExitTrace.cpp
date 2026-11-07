// ExitTrace.asi - diagnostic only. Logs why the game exits: every exception the process raises
// (first chance), and the call path into ExitProcess / PostQuitMessage / DestroyWindow.
// Stack traces are raw return-address candidates inside speed.exe, found by scanning the stack.
// Log: ExitTrace.log next to this .asi.
#include <windows.h>
#include <stdio.h>
#include <string.h>

static FILE* g_log;
static DWORD g_start;
static BYTE* g_exeBase;
static DWORD g_exeSize;

static void Log(const char* fmt, ...)
{
    if (!g_log) return;
    va_list a;
    va_start(a, fmt);
    fprintf(g_log, "[%8.3f] ", (GetTickCount() - g_start) / 1000.0);
    vfprintf(g_log, fmt, a);
    fputc('\n', g_log);
    fflush(g_log);
    va_end(a);
}

static void ModuleOf(void* addr, char* out, size_t n)
{
    HMODULE m = nullptr;
    out[0] = 0;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCSTR)addr, &m) && m)
    {
        char path[MAX_PATH];
        GetModuleFileNameA(m, path, MAX_PATH);
        const char* name = strrchr(path, '\\') ? strrchr(path, '\\') + 1 : path;
        snprintf(out, n, "%s+0x%lX", name, (unsigned long)((BYTE*)addr - (BYTE*)m));
    }
}

// Logs stack values that point into any loaded module's code, starting at `sp`.
static void LogStack(const char* what, void* sp)
{
    Log("%s: stack scan", what);
    DWORD* p = (DWORD*)sp;
    int found = 0;
    for (int i = 0; i < 2048 && found < 40; ++i)
    {
        MEMORY_BASIC_INFORMATION mbi;
        if (!VirtualQuery(p + i, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT)
            break;
        BYTE* v = (BYTE*)p[i];
        if (!VirtualQuery(v, &mbi, sizeof(mbi)) || !(mbi.Protect & (PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE)))
            continue;
        char mod[MAX_PATH];
        ModuleOf(v, mod, sizeof(mod));
        if (!mod[0])
            continue;
        Log("  [esp+0x%03X] %p %s", i * 4, v, mod);
        ++found;
    }
}

static LONG CALLBACK OnException(EXCEPTION_POINTERS* e)
{
    static int count;
    DWORD code = e->ExceptionRecord->ExceptionCode;
    if (code == 0x406D1388 || code == DBG_PRINTEXCEPTION_C || code == 0x4001000A) // thread naming, debug prints
        return EXCEPTION_CONTINUE_SEARCH;
    if (++count > 30)
        return EXCEPTION_CONTINUE_SEARCH;
    char mod[MAX_PATH];
    ModuleOf(e->ExceptionRecord->ExceptionAddress, mod, sizeof(mod));
    Log("EXCEPTION 0x%08lX at %p %s thread=%lu", (unsigned long)code, e->ExceptionRecord->ExceptionAddress, mod,
        (unsigned long)GetCurrentThreadId());
    if (code == EXCEPTION_ACCESS_VIOLATION)
        Log("  access %s address %p", e->ExceptionRecord->ExceptionInformation[0] ? "write" : "read",
            (void*)e->ExceptionRecord->ExceptionInformation[1]);
    LogStack("  exception", (void*)e->ContextRecord->Esp);
    return EXCEPTION_CONTINUE_SEARCH;
}

typedef void(WINAPI* ExitProcessFn)(UINT);
typedef void(WINAPI* PostQuitMessageFn)(int);
typedef BOOL(WINAPI* DestroyWindowFn)(HWND);
static ExitProcessFn g_exitProcess;
static PostQuitMessageFn g_postQuit;
static DestroyWindowFn g_destroyWindow;

static void WINAPI HookExitProcess(UINT code)
{
    int marker;
    Log("ExitProcess(%u) called, thread=%lu", code, (unsigned long)GetCurrentThreadId());
    LogStack("ExitProcess", &marker);
    g_exitProcess(code);
}

static void WINAPI HookPostQuitMessage(int code)
{
    int marker;
    Log("PostQuitMessage(%d) called", code);
    LogStack("PostQuitMessage", &marker);
    g_postQuit(code);
}

static BOOL WINAPI HookDestroyWindow(HWND wnd)
{
    int marker;
    Log("DestroyWindow(%p) called", wnd);
    LogStack("DestroyWindow", &marker);
    return g_destroyWindow(wnd);
}

static bool PatchImport(const char* dll, const char* func, void* hook, void** original)
{
    BYTE* base = g_exeBase;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); imp->Name; ++imp)
    {
        if (lstrcmpiA((const char*)(base + imp->Name), dll) != 0)
            continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA* funcs = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++funcs)
        {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            if (strcmp((const char*)((IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData))->Name, func) != 0)
                continue;
            DWORD old;
            VirtualProtect(&funcs->u1.Function, 4, PAGE_READWRITE, &old);
            *original = (void*)funcs->u1.Function;
            funcs->u1.Function = (UINT_PTR)hook;
            VirtualProtect(&funcs->u1.Function, 4, old, &old);
            return true;
        }
    }
    return false;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_DETACH)
    {
        Log("DLL_PROCESS_DETACH (%s)", reserved ? "process terminating" : "FreeLibrary");
        return TRUE;
    }
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(inst);
    char path[MAX_PATH];
    GetModuleFileNameA(inst, path, MAX_PATH);
    strcpy(strrchr(path, '.'), ".log");
    g_log = fopen(path, "w");
    g_start = GetTickCount();
    g_exeBase = (BYTE*)GetModuleHandleA(nullptr);
    AddVectoredExceptionHandler(1, OnException);
    Log("ExitTrace loaded; exe base %p", g_exeBase);
    Log("hook ExitProcess: %d", PatchImport("kernel32.dll", "ExitProcess", (void*)HookExitProcess, (void**)&g_exitProcess));
    Log("hook PostQuitMessage: %d", PatchImport("user32.dll", "PostQuitMessage", (void*)HookPostQuitMessage, (void**)&g_postQuit));
    Log("hook DestroyWindow: %d", PatchImport("user32.dll", "DestroyWindow", (void*)HookDestroyWindow, (void**)&g_destroyWindow));
    return TRUE;
}
