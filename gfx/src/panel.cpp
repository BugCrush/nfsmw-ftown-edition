// GfxProbe: the live panel. A click-through, never-focused, topmost layered window over the game, drawn
// with GDI 20 times a second (the same kind of window as InputBridge's speed-and-triggers panel). Shown
// while the player is driving and the game is the window in front. It only reads what frame.cpp collects.
//
//   3832 draws  239k tris   7.3 ms          <- this frame: drawing commands, triangles, processor time
//   Shadows   [#######     ]  1256  1.6 ms   <- one row per job: bar = share of processor time,
//   Reflect   ...                              then draws per frame and milliseconds
//   [ graph: draws per frame over the last 10 s for shadows, reflections and the main view ]
#include "probe.h"

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

static const int kPanelW = 340, kPanelH = 196;
static const char* const kJobName[kJobs] = { "Shadows", "Reflect", "Main view", "Logic", "Effects", "HUD" };
static const COLORREF kJobColour[kJobs] = { RGB(155, 125, 215), RGB(201, 162, 39), RGB(63, 157, 107),
                                            RGB(138, 143, 152), RGB(208, 112, 79), RGB(184, 92, 142) };
static HWND g_game;

static void FillBox(HDC dc, int left, int top, int right, int bottom, COLORREF colour)
{
    RECT box = { left, top, right, bottom };
    HBRUSH brush = CreateSolidBrush(colour);
    FillRect(dc, &box, brush);
    DeleteObject(brush);
}

static void DrawPanel(HDC dc, DWORD* pixels, const LiveData& live)
{
    memset(pixels, 0, kPanelW * kPanelH * 4);
    static HFONT font = CreateFontA(-15, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, NONANTIALIASED_QUALITY, 0, "Consolas");
    static HFONT small = CreateFontA(-12, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, NONANTIALIASED_QUALITY, 0, "Consolas");
    SetBkMode(dc, TRANSPARENT);
    char line[128];
    float draws = 0, tris = 0, ms = 0;
    for (int j = 0; j < kJobs; ++j)
    {
        draws += live.draws[j];
        tris += live.tris[j];
        ms += live.ms[j];
    }
    SelectObject(dc, font);
    SetTextColor(dc, RGB(255, 255, 255));
    snprintf(line, sizeof(line), "%.0f draws  %.0fk tris  %.1f ms", draws, tris / 1000, live.frameMs);
    TextOutA(dc, 6, 3, line, (int)strlen(line));

    // One row per job. The bar is the job's share of the frame's processor time; without timing it is
    // the share of draws.
    const int barX = 84, barW = 110, rowY = 25, rowH = 17;
    SelectObject(dc, small);
    for (int j = 0; j < kJobs; ++j)
    {
        int y = rowY + j * rowH;
        float share = ms > 0 ? live.ms[j] / ms : draws > 0 ? live.draws[j] / draws : 0;
        SetTextColor(dc, kJobColour[j]);
        TextOutA(dc, 6, y, kJobName[j], (int)strlen(kJobName[j]));
        FillBox(dc, barX, y + 3, barX + barW, y + 12, RGB(60, 60, 60));
        int filled = (int)(share * barW + 0.5f);
        if (filled > 0)
            FillBox(dc, barX, y + 3, barX + (filled > barW ? barW : filled), y + 12, kJobColour[j]);
        SetTextColor(dc, RGB(220, 220, 220));
        snprintf(line, sizeof(line), "%5.0f %5.2f ms", live.draws[j], live.ms[j]);
        TextOutA(dc, barX + barW + 8, y, line, (int)strlen(line));
    }

    // Graph: draws per frame over the last 10 s for the three big jobs, scaled to the window's peak.
    const int gx = 6, gy = rowY + kJobs * rowH + 6, gw = kPanelW - 12, gh = kPanelH - gy - 6;
    float peak = 100;
    for (int i = 0; i < kLiveHistory; ++i)
        for (int k = 0; k < 3; ++k)
            if (live.history[i][k] > peak)
                peak = live.history[i][k];
    peak = (float)(((int)(peak / 250) + 1) * 250);
    HPEN frame = CreatePen(PS_SOLID, 1, RGB(90, 90, 90));
    SelectObject(dc, frame);
    SelectObject(dc, GetStockObject(NULL_BRUSH));
    Rectangle(dc, gx - 1, gy - 1, gx + gw + 1, gy + gh + 1);
    SetTextColor(dc, RGB(150, 150, 150));
    snprintf(line, sizeof(line), "%.0f draws", peak);
    TextOutA(dc, gx + gw - 76, gy + 1, line, (int)strlen(line));
    POINT points[kLiveHistory];
    for (int k = 0; k < 3; ++k)
    {
        for (int i = 0; i < kLiveHistory; ++i)
        {
            float v = live.history[(live.historyNext + i) % kLiveHistory][k] / peak;
            points[i].x = gx + i * (gw - 1) / (kLiveHistory - 1);
            points[i].y = gy + gh - 1 - (int)((v < 0 ? 0 : v > 1 ? 1 : v) * (gh - 2));
        }
        HPEN pen = CreatePen(PS_SOLID, 1, kJobColour[k]);
        HGDIOBJ old = SelectObject(dc, pen);
        Polyline(dc, points, kLiveHistory);
        SelectObject(dc, old);
        DeleteObject(pen);
    }
    SelectObject(dc, GetStockObject(BLACK_PEN));
    DeleteObject(frame);
}

// GDI does not write alpha: drawn pixels get the content opacity, the rest the background one.
static void ApplyAlpha(DWORD* pixels)
{
    float content = g_cfg.panelOpacity < 0 ? 0 : g_cfg.panelOpacity > 1 ? 1 : g_cfg.panelOpacity;
    float background = g_cfg.panelBackground < 0 ? 0 : g_cfg.panelBackground > 1 ? 1 : g_cfg.panelBackground;
    BYTE contentA = (BYTE)(content * 255), backA = (BYTE)(background * 255);
    for (int i = 0; i < kPanelW * kPanelH; ++i)
    {
        DWORD c = pixels[i] & 0xFFFFFF;
        if (!c)
        {
            pixels[i] = (DWORD)backA << 24;
            continue;
        }
        BYTE r = (BYTE)((c >> 16) * contentA / 255), g = (BYTE)(((c >> 8) & 0xFF) * contentA / 255), b = (BYTE)((c & 0xFF) * contentA / 255);
        pixels[i] = ((DWORD)contentA << 24) | ((DWORD)r << 16) | ((DWORD)g << 8) | b;
    }
}

static void LogData(const LiveData& live)
{
    float draws = 0, tris = 0;
    for (int j = 0; j < kJobs; ++j)
    {
        draws += live.draws[j];
        tris += live.tris[j];
    }
    Log("PANELDATA draws=%.1f tris=%.1f shadows=%.1f reflect=%.1f main=%.1f logic=%.1f effects=%.1f hud=%.1f "
        "shadows_ms=%.4f reflect_ms=%.4f main_ms=%.4f logic_ms=%.4f effects_ms=%.4f hud_ms=%.4f frame_ms=%.4f present_ms=%.4f",
        draws, tris, live.draws[0], live.draws[1], live.draws[2], live.draws[3], live.draws[4], live.draws[5], live.ms[0],
        live.ms[1], live.ms[2], live.ms[3], live.ms[4], live.ms[5], live.frameMs, live.presentMs);
}

// [Panel] Snapshot = 1: the panel's picture (before transparency is applied) as panel.bmp in the run
// folder, two seconds after it first appears. For looking at the panel without the game on screen.
static void SaveSnapshot(const DWORD* pixels)
{
    char path[MAX_PATH + 200];
    snprintf(path, sizeof(path), "%s\\panel.bmp", RunDir());
    FILE* f = fopen(path, "wb");
    if (!f)
        return;
    DWORD rowBytes = (kPanelW * 3 + 3) & ~3u;
    BITMAPFILEHEADER fh = { 0x4D42, (DWORD)(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + rowBytes * kPanelH), 0, 0,
        sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) };
    BITMAPINFOHEADER ih = { sizeof(ih), kPanelW, kPanelH, 1, 24, BI_RGB, rowBytes * kPanelH, 0, 0, 0, 0 };
    fwrite(&fh, sizeof(fh), 1, f);
    fwrite(&ih, sizeof(ih), 1, f);
    BYTE row[1024] = {};
    for (int y = kPanelH - 1; y >= 0; --y) // BMP rows run bottom-up
    {
        for (int x = 0; x < kPanelW; ++x)
            memcpy(row + x * 3, &pixels[y * kPanelW + x], 3);
        fwrite(row, rowBytes, 1, f);
    }
    fclose(f);
}

static DWORD WINAPI PanelThread(LPVOID)
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = (HINSTANCE)&__ImageBase;
    wc.lpszClassName = "GfxProbePanel";
    RegisterClassA(&wc);
    HWND wnd = CreateWindowExA(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        wc.lpszClassName, "", WS_POPUP, 0, 0, kPanelW, kPanelH, nullptr, nullptr, wc.hInstance, nullptr);
    if (!wnd)
    {
        Log("Panel: CreateWindow failed (%lu)", GetLastError());
        return 0;
    }
    HDC screen = GetDC(nullptr);
    HDC mem = CreateCompatibleDC(screen);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof(bi.bmiHeader);
    bi.bmiHeader.biWidth = kPanelW;
    bi.bmiHeader.biHeight = -kPanelH; // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    DWORD* pixels = nullptr;
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, (void**)&pixels, nullptr, 0);
    SelectObject(mem, bmp);
    Log("Panel ready");

    static LiveData live;
    bool shown = false, snapshotDone = false;
    DWORD shownAt = 0;
    for (;;)
    {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE))
            DispatchMessageA(&msg);
        Sleep(50);

        HWND root = GetAncestor(g_game, GA_ROOT);
        bool show = g_driving && root && (!g_cfg.panelOnlyInFront || GetAncestor(GetForegroundWindow(), GA_ROOT) == root);
        if (!show)
        {
            if (shown)
            {
                ShowWindow(wnd, SW_HIDE);
                Log("PANEL state=hidden");
                LogData(live);
            }
            shown = false;
            continue;
        }
        RECT rc;
        GetClientRect(root, &rc);
        POINT origin = { rc.left + g_cfg.panelX, rc.bottom - g_cfg.panelBottom - kPanelH };
        ClientToScreen(root, &origin);

        FrameLiveGet(&live);
        DrawPanel(mem, pixels, live);
        if (g_cfg.panelSnapshot && shown && !snapshotDone && GetTickCount() - shownAt >= 2000)
        {
            snapshotDone = true;
            SaveSnapshot(pixels);
            LogData(live);
        }
        ApplyAlpha(pixels);
        POINT src = { 0, 0 };
        SIZE size = { kPanelW, kPanelH };
        BLENDFUNCTION blend = { AC_SRC_OVER, 0, 255, AC_SRC_ALPHA };
        BOOL drawn = UpdateLayeredWindow(wnd, screen, &origin, &size, mem, &src, 0, &blend, ULW_ALPHA);
        if (!shown)
        {
            Log("PANEL state=shown x=%ld y=%ld client=%ldx%ld draw=%s", origin.x, origin.y, rc.right, rc.bottom, drawn ? "ok" : "FAILED");
            SetWindowPos(wnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
            shown = true;
            shownAt = GetTickCount();
        }
    }
}

void PanelStart(HWND game)
{
    static bool started;
    if (started || !game)
        return;
    started = true;
    g_game = game;
    CloseHandle(CreateThread(nullptr, 0, PanelThread, nullptr, 0, nullptr));
}
