// FpsRecorder.asi - records the game's frames with PresentMon, only while the game runs.
//
// In the game: DllMain starts a hidden watcher, `rundll32 FpsRecorder.asi,Watch <game pid>`.
// In the watcher: starts PresentMon for that pid, waits for the game to exit (or crash),
// then stops PresentMon gracefully so the CSV is complete, and exits.
// A separate watcher is needed because PresentMon can't detect the game exiting without admin rights.
//
// Settings: scripts\FpsRecorder.ini (optional). Log: <OutputDir>\fps-recorder.log
#include <windows.h>
#include <shlwapi.h>
#include <string>
#include <vector>
#include <algorithm>

#pragma comment(lib, "shlwapi.lib")

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

static const wchar_t* kSessionName = L"NFSMWFpsRecorder";

static std::wstring DirOf(const std::wstring& path)
{
    size_t slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? L"." : path.substr(0, slash);
}

static std::wstring ModulePath(HMODULE module)
{
    wchar_t buf[MAX_PATH];
    GetModuleFileNameW(module, buf, MAX_PATH);
    return buf;
}

static std::wstring FullPath(const std::wstring& path)
{
    wchar_t buf[MAX_PATH];
    return GetFullPathNameW(path.c_str(), MAX_PATH, buf, nullptr) ? buf : path;
}

// Keep only the newest (keep - 1) recordings so the new one makes `keep`.
static void PruneOldRecordings(const std::wstring& dir, int keep)
{
    std::vector<std::wstring> files;
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW((dir + L"\\nfsmw-fps-*.csv").c_str(), &fd);
    if (find == INVALID_HANDLE_VALUE)
        return;
    do { files.push_back(fd.cFileName); } while (FindNextFileW(find, &fd));
    FindClose(find);

    // Names embed a yyyyMMdd-HHmmss timestamp, so name order is age order.
    std::sort(files.begin(), files.end());
    for (int i = 0; i + (keep - 1) < (int)files.size(); ++i)
        DeleteFileW((dir + L"\\" + files[i]).c_str());
}

static void LogLine(HANDLE log, const std::wstring& text)
{
    if (log == INVALID_HANDLE_VALUE)
        return;
    std::string line;
    for (wchar_t c : text) line += (char)c;
    line += "\r\n";
    DWORD written;
    WriteFile(log, line.data(), (DWORD)line.size(), &written, nullptr);
}

// Starts a hidden process with its output going to `log`. Returns the process handle, or null.
static HANDLE Run(std::wstring cmd, const std::wstring& workDir, HANDLE log)
{
    LogLine(log, L"Run: " + cmd);
    STARTUPINFOW si = { sizeof(si) };
    if (log != INVALID_HANDLE_VALUE)
    {
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdOutput = log;
        si.hStdError = log;
    }
    PROCESS_INFORMATION pi = {};
    if (!CreateProcessW(nullptr, &cmd[0], nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr,
            workDir.empty() ? nullptr : workDir.c_str(), &si, &pi))
    {
        LogLine(log, L"  failed, error " + std::to_wstring(GetLastError()));
        return nullptr;
    }
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

// rundll32 entry point: FpsRecorder.asi,Watch <game pid>
extern "C" __declspec(dllexport) void CALLBACK Watch(HWND, HINSTANCE, LPSTR args, int)
{
    DWORD gamePid = strtoul(args, nullptr, 10);
    HANDLE game = OpenProcess(SYNCHRONIZE, FALSE, gamePid);
    if (!game)
        return;

    std::wstring asiDir = DirOf(ModulePath((HMODULE)&__ImageBase));
    std::wstring iniPath = asiDir + L"\\FpsRecorder.ini";

    wchar_t buf[MAX_PATH];
    GetPrivateProfileStringW(L"MAIN", L"PresentMonPath", L"..\\..\\fps-capture\\PresentMon.exe", buf, MAX_PATH, iniPath.c_str());
    std::wstring presentMon = buf;
    GetPrivateProfileStringW(L"MAIN", L"OutputDir", L"..\\..\\fps-capture", buf, MAX_PATH, iniPath.c_str());
    std::wstring outDir = buf;
    int keep = GetPrivateProfileIntW(L"MAIN", L"KeepLast", 10, iniPath.c_str());

    // Relative paths are relative to the scripts folder.
    if (PathIsRelativeW(presentMon.c_str())) presentMon = asiDir + L"\\" + presentMon;
    if (PathIsRelativeW(outDir.c_str())) outDir = asiDir + L"\\" + outDir;
    presentMon = FullPath(presentMon);
    outDir = FullPath(outDir);

    CreateDirectoryW(outDir.c_str(), nullptr);
    if (keep > 0)
        PruneOldRecordings(outDir, keep);

    SECURITY_ATTRIBUTES sa = { sizeof(sa), nullptr, TRUE };
    HANDLE log = CreateFileW((outDir + L"\\fps-recorder.log").c_str(), GENERIC_WRITE, FILE_SHARE_READ, &sa,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);

    SYSTEMTIME t;
    GetLocalTime(&t);
    wchar_t stamp[32];
    wsprintfW(stamp, L"%04d%02d%02d-%02d%02d%02d", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    std::wstring csv = outDir + L"\\nfsmw-fps-" + stamp + L".csv";

    HANDLE recorder = Run(L"\"" + presentMon + L"\" --process_id " + std::to_wstring(gamePid) +
        L" --output_file \"" + csv + L"\" --no_console_stats --session_name " + kSessionName +
        L" --stop_existing_session", outDir, log);

    if (recorder)
    {
        WaitForSingleObject(game, INFINITE);
        LogLine(log, L"Game exited; stopping PresentMon.");

        HANDLE stopper = Run(L"\"" + presentMon + L"\" --session_name " + kSessionName +
            L" --terminate_existing_session", outDir, log);
        if (stopper)
        {
            WaitForSingleObject(stopper, 15000);
            CloseHandle(stopper);
        }
        if (WaitForSingleObject(recorder, 15000) == WAIT_TIMEOUT)
        {
            LogLine(log, L"PresentMon did not stop; terminating it.");
            TerminateProcess(recorder, 1);
        }
        LogLine(log, L"Done.");
        CloseHandle(recorder);
    }

    if (log != INVALID_HANDLE_VALUE)
        CloseHandle(log);
    CloseHandle(game);
}

static DWORD WINAPI StartWatcher(LPVOID module)
{
    // speed.exe is 32-bit, so System32 redirects to SysWOW64 and this is the 32-bit rundll32.
    wchar_t sysDir[MAX_PATH];
    GetSystemDirectoryW(sysDir, MAX_PATH);
    std::wstring cmd = L"\"" + std::wstring(sysDir) + L"\\rundll32.exe\" \"" + ModulePath((HMODULE)module) +
        L"\",Watch " + std::to_wstring(GetCurrentProcessId());
    HANDLE watcher = Run(cmd, L"", INVALID_HANDLE_VALUE);
    if (watcher)
        CloseHandle(watcher);
    return 0;
}

static bool IsRunningInRundll32()
{
    std::wstring exe = ModulePath(nullptr);
    return lstrcmpiW(PathFindFileNameW(exe.c_str()), L"rundll32.exe") == 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH && !IsRunningInRundll32())
    {
        DisableThreadLibraryCalls(instance);
        // Process creation isn't safe inside DllMain; do it on a separate thread.
        HANDLE thread = CreateThread(nullptr, 0, StartWatcher, instance, 0, nullptr);
        if (thread)
            CloseHandle(thread);
    }
    return TRUE;
}
