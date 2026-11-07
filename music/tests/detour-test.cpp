// Tests music/src/Detour.h: redirecting a function's entry (with a trampoline to the original) and
// swapping a function-table slot for a wrapper, the two mechanisms MusicProbe uses to log calls.
// Build (from music\tests): zig c++ -target x86-windows-gnu -w detour-test.cpp -o detour-test.exe
// Run: detour-test.exe      (exit code 0 = all passed)
#include "../src/Detour.h"
#include <stdio.h>
#include <string.h>

static int failures;
static void Check(bool ok, const char* what, int got)
{
    printf("  %s %s (%d)\n", ok ? "ok  " : "FAIL", what, got);
    if (!ok)
        ++failures;
}

// --- a function entry shaped like the game's event lookup (0x82BFD0) ---------------------------
// push ebp / mov ebp,esp / mov eax,[global] / mov eax,[ebp+8] / add eax,[ebp+0xC] / pop ebp / ret
static DWORD g_global = 7;
typedef int(__cdecl* AddFn)(int, int);
static AddFn g_original;
static int g_hookCalls;

static int __cdecl HookAdd(int a, int b)
{
    ++g_hookCalls;
    return g_original(a, b) + 100;
}

// --- an object with a function table, called the way the game calls its stream channel ---------
struct Channel
{
    int base = 1000;
    virtual int Stop() { return base + 1; }
    virtual int Play(int a, int b, int c, int d, int e) { return base + a + b + c + d + e; }
};
typedef int(__fastcall* PlayFn)(void* self, void* edx, int a, int b, int c, int d, int e);
typedef int(__fastcall* StopFn)(void* self, void* edx);
static PlayFn g_realPlay;
static StopFn g_realStop;
static int g_playSeen, g_stopSeen;

static int __fastcall WrapPlay(void* self, void* edx, int a, int b, int c, int d, int e)
{
    g_playSeen = a * 10000 + b * 1000 + c * 100 + d * 10 + e;
    return g_realPlay(self, edx, a, b, c, d, e);
}
static int __fastcall WrapStop(void* self, void* edx)
{
    ++g_stopSeen;
    return g_realStop(self, edx);
}

int main()
{
    printf("function entry\n");
    BYTE code[] = { 0x55, 0x8B, 0xEC, 0xA1, 0, 0, 0, 0, 0x8B, 0x45, 0x08, 0x03, 0x45, 0x0C, 0x5D, 0xC3 };
    void* globalAddr = &g_global;
    memcpy(code + 4, &globalAddr, 4);
    BYTE* target = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    memcpy(target, code, sizeof(code));
    AddFn add = (AddFn)target;
    Check(add(2, 3) == 5, "before: add(2,3) = 5", add(2, 3));

    BYTE wrong[8] = { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };
    Check(InstallDetour(target, (void*)HookAdd, 8, wrong) == nullptr, "refused when the code doesn't match", 0);
    Check(add(2, 3) == 5, "still untouched after the refusal", add(2, 3));

    g_original = (AddFn)InstallDetour(target, (void*)HookAdd, 8, code);
    Check(g_original != nullptr, "installed", g_original != nullptr);
    if (g_original)
    {
        int hooked = add(2, 3);
        Check(hooked == 105, "after: the hook runs and calls the original", hooked);
        Check(g_original(20, 30) == 50, "the trampoline is the original function", g_original(20, 30));
        Check(g_hookCalls == 1, "hook called once per call", g_hookCalls);
    }

    printf("function-table slot\n");
    // Created through a volatile function pointer so the optimiser can't know the object's type and
    // must call through the table, as the game does.
    Channel* (*volatile make)() = [] { return new Channel; };
    Channel* c = make();
    void** table = *(void***)c;
    Check(c->Play(1, 2, 3, 4, 5) == 1015, "before: Play = 1015", c->Play(1, 2, 3, 4, 5));
    Check(!SwapPointer(&table[1], (void*)HookAdd, (void*)WrapPlay), "refused when the slot isn't what we expect", 0);
    g_realPlay = (PlayFn)table[1];
    g_realStop = (StopFn)table[0];
    Check(SwapPointer(&table[1], (void*)g_realPlay, (void*)WrapPlay), "Play slot swapped", 1);
    Check(SwapPointer(&table[0], (void*)g_realStop, (void*)WrapStop), "Stop slot swapped", 1);
    Channel* viaTable = c;
    int r = viaTable->Play(1, 2, 3, 4, 5);
    Check(r == 1015, "after: same result through the wrapper", r);
    Check(g_playSeen == 12345, "the wrapper saw the five arguments in order", g_playSeen);
    r = viaTable->Stop();
    Check(r == 1001 && g_stopSeen == 1, "a no-argument call passes through too", r);

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
