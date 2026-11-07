// Loads a plugin with LoadLibraryA outside the game and reports OK or the Windows error, then unloads it.
// Usage: test-load.exe <plugin.asi>. A plugin that patches game addresses at load may crash here: that says
// nothing about the game, and is reported as such.
// Build: zig c++ -target x86-windows-gnu -O2 test-load.cpp -o test-load.exe
#include <windows.h>
#include <stdio.h>

static LONG WINAPI Crash(EXCEPTION_POINTERS* e)
{
    printf("CRASH during load: exception 0x%08lX at %p (expected for plugins that patch game code at load)\n",
           e->ExceptionRecord->ExceptionCode, e->ExceptionRecord->ExceptionAddress);
    fflush(stdout);
    ExitProcess(2);
}

int main(int argc, char** argv)
{
    if (argc < 2) { printf("usage: test-load <plugin>\n"); return 3; }
    SetUnhandledExceptionFilter(Crash);
    HMODULE m = LoadLibraryA(argv[1]);
    if (!m) { printf("FAILED: LoadLibrary error %lu\n", GetLastError()); return 1; }
    printf("OK: loaded at %p\n", (void*)m);
    FreeLibrary(m);
    return 0;
}
