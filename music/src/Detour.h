// Two ways to get our code called in place of the game's, both refusing to act unless the game's
// bytes are exactly what we expect (so a different executable is left alone).
#pragma once
#include <windows.h>
#include <string.h>

// Replaces one function pointer (e.g. a function-table slot). Fails if it doesn't hold `expected`.
inline bool SwapPointer(void** slot, void* expected, void* replacement)
{
    if (*slot != expected)
        return false;
    DWORD old;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old))
        return false;
    *slot = replacement;
    VirtualProtect(slot, sizeof(void*), old, &old);
    return true;
}

// Makes `target` jump to `hook`. `stolen` is how many bytes at the start of target are overwritten
// (at least 5, ending on an instruction boundary, and position-independent); they must equal
// `expected`. Returns a trampoline that behaves as the original function, or nullptr if refused.
inline void* InstallDetour(void* target, void* hook, size_t stolen, const BYTE* expected)
{
    BYTE* at = (BYTE*)target;
    if (stolen < 5 || memcmp(at, expected, stolen) != 0)
        return nullptr;
    BYTE* trampoline = (BYTE*)VirtualAlloc(nullptr, stolen + 5, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline)
        return nullptr;
    memcpy(trampoline, at, stolen);
    trampoline[stolen] = 0xE9; // jmp back to the rest of the original
    LONG back = (LONG)((at + stolen) - (trampoline + stolen + 5));
    memcpy(trampoline + stolen + 1, &back, 4);

    DWORD old;
    if (!VirtualProtect(at, stolen, PAGE_EXECUTE_READWRITE, &old))
        return nullptr;
    LONG to = (LONG)((BYTE*)hook - (at + 5));
    at[0] = 0xE9; // jmp hook
    memcpy(at + 1, &to, 4);
    memset(at + 5, 0x90, stolen - 5);
    VirtualProtect(at, stolen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, stolen);
    return trampoline;
}
