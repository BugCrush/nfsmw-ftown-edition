// FTownGame.h - F-Town's game mode: the way in from the game's own menus (docs/ftown-race-notes.md R5, R6) and the
// race that carries it. Included once by FTownLoader.cpp after FTownRace.h (it uses Load, the Time Attack and the
// barriers), so the plugin stays one file to build and one .asi to install.
//
// The menu (R5): Quick Race's main menu gets a third option, "Bonus Maps" (the call at 0x7AA81C adds it after the
// game's own). Choosing it does what Custom Race does (its React 0x7AA710: QRMode 1, the game then opens its mode
// select, MainMenu_Sub.fng) and arms our flow. While armed, the mode select (UIQRModeSelect: Setup 0x7AA900 through the
// call 0x7BA4D7 and vtable slot 0x8B7E28, NotificationMessage through slot 0x8B7E1C, the title through the call
// 0x7A2F6D) is ours twice: the map list (F-Town), then the mode list (Free Roam, then every event of ftown-events.json:
// Time Attack, Drag (DND-KMP Expressway), Speed Trap (Mathura Road), Sector Sprint). A mode builds the
// carrier race (R6: a Rockport Sprint with no opponents, cops or traffic) as the game's startup race and opens the
// game's own Car_Select.fng; its Back comes to our mode list (the call 0x7C26ED). Back from the map list is the game's
// own (the Quick Race main menu, the flow disarmed); building the Quick Race main menu always disarms it, so Custom
// Race afterwards is Rockport's. Our texts (three and one an event) come from the string lookup 0x56BB80.
//
// The race (R6): FTownLoader waits for the game's 3-2-1-GO (the HUD's ICountdown: its count seen at 1 or more, then
// at 0 or less), then loads F-Town (Load, as F8) and starts the mode: Free Roam at Spawn1, an event at its start
// (its barriers in). The count running again later is the pause menu's Restart Race: the mode starts again at the next
// GO. The car found off F-Town (a reset to a Rockport spot) goes back to the mode's start. Leaving the race (the track
// unloading) ends it all.

// ---------------------------------------------------------------- addresses (speed.exe v1.3, R5 and R6)

static const DWORD kQrMainAddSite = 0x7AA81C;    // UIQRMainMenu::Setup: the last call IconScrollerMenu::AddOption
static const DWORD kModeSetupSite = 0x7BA4D7;    // UIQRModeSelect ctor: call Setup
static const DWORD kModeTitleSite = 0x7A2F6D;    // UIQRModeSelect::RefreshHeader: call FEngSetLanguageHash
static const DWORD kCarBackSite = 0x7C26ED;      // UIQRCarSelect Back: call QueuePackageSwitch("Track_Options.fng")
static const DWORD kModeVtbl = 0x8B7E18;         // UIQRModeSelect's vtable: +0x04 NotificationMessage, +0x10 Setup
static const DWORD kLookup = 0x56BB80;           // the language string lookup (fastcall: hash in edx)
static const DWORD kAddOption = 0x573960, kIconCtor = 0x586FA0, kNew = 0x652AD0, kSetInitial = 0x50E7F0;
static const DWORD kScrollerNotify = 0x587D30, kSwitch = 0x525940, kQueueMessage = 0x516C90, kSetLangHash = 0x525220;
static const DWORD kCustomRaceReact = 0x7AA710, kCustomRaceDtor = 0x7B4980, kModeSetup = 0x7AA900;
static const DWORD kModeNotify = 0x7A2F80;
static const DWORD kFE = 0x91CADC, kFEDatabase = 0x91CF90, kRaceDb = 0x91E004;
static const DWORD kGetRaceFromName = 0x50DF70, kGetRaceType = 0x5FAA20, kAllocCustom = 0x603440;
static const DWORD kFillCustom = 0x56DD20, kSetStartup = 0x600AB0, kFreeCustom = 0x5E39E0, kClearStartup = 0x5DC9D0;
static const DWORD kCountdownHandle = 0x4B4380, kCountdownVtbl = 0x8A2070;
static const DWORD kMsgPressed = 0xC407210, kMsgBack = 0x911AB364, kMsgExitComplete = 0xE1FDE1D1;
static const DWORD kModeSelectBit = 0x400;  // FEDatabase +0x12C: the mode select's game mode bit

static const Site kGameSites[] = {
    {0x7AA81C, {0xE8, 0x3F, 0x91, 0xDC, 0xFF}, 5, "UIQRMainMenu::Setup: the last call AddOption (0x573960)"},
    {0x7BA4D7, {0xE8, 0x24, 0x04, 0xFF, 0xFF}, 5, "UIQRModeSelect ctor: call Setup (0x7AA900)"},
    {0x7A2F6D, {0xE8, 0xAE, 0x22, 0xD8, 0xFF}, 5, "UIQRModeSelect::RefreshHeader: call FEngSetLanguageHash (0x525220)"},
    {0x7C26E8, {0x68, 0x24, 0xFC, 0x89, 0x00, 0xE8, 0x4E, 0x32, 0xD6, 0xFF}, 10,
     "UIQRCarSelect Back: push \"Track_Options.fng\"; call QueuePackageSwitch (0x525940)"},
    {0x56BB80, {0x53, 0x8B, 0x1D, 0x80, 0xCF, 0x91, 0x00}, 7, "the string lookup: push ebx; mov ebx, [0x91CF80]"},
    {0x586FA0, {0x8B, 0x54, 0x24, 0x04, 0x8B, 0xC1, 0x53, 0x56}, 8, "IconOption::IconOption(tex, name, desc)"},
    {0x573960, {0x8B, 0x41, 0x2C, 0x56, 0x8B, 0x74, 0x24, 0x08, 0x83, 0xC1, 0x2C, 0x56}, 12,
     "IconScrollerMenu::AddOption"},
    {0x50E7F0, {0x8A, 0x91, 0x29, 0x01, 0x00, 0x00, 0x33, 0xC0}, 8, "IconScrollerMenu::SetInitialOption"},
    {0x587D30, {0x8B, 0x44, 0x24, 0x04, 0x3D, 0x9E, 0x40, 0x20, 0x91, 0x56, 0x57}, 11,
     "IconScrollerMenu::NotificationMessage"},
    {0x525940, {0x83, 0x3D, 0x90, 0x5E, 0x92, 0x00, 0x06, 0x56, 0x57}, 9, "cFEng::QueuePackageSwitch"},
    {0x516C90, {0x8B, 0x44, 0x24, 0x0C, 0x85, 0xC0}, 6, "cFEng::QueuePackageMessage"},
    {0x652AD0, {0xE9, 0xFB, 0x3B, 0x17, 0x00}, 5, "operator new"},
    {0x7AA710, {0x81, 0x7C, 0x24, 0x08, 0x10, 0x72, 0x40, 0x0C, 0x75, 0x0A, 0xC7, 0x05, 0x68, 0x9E, 0x9B, 0x00, 0x01, 0x00,
                0x00, 0x00, 0xC2, 0x14, 0x00},
     23, "CustomRace::React: pressed (0xC407210) -> QRMode [0x9B9E68] = 1"},
    {0x7B4980, {0x56, 0x8B, 0xF1, 0xE8, 0x18, 0x00, 0x00, 0x00}, 8, "CustomRace's deleting destructor"},
    {0x7A2E71, {0xA1, 0x90, 0xCF, 0x91, 0x00}, 5, "UIQRMainMenu: mov eax, [FEDatabase 0x91CF90]"},
    {0x7A2EA7, {0xA1, 0x90, 0xCF, 0x91, 0x00, 0x81, 0x88, 0x2C, 0x01, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00}, 15,
     "UIQRMainMenu: FEDatabase +0x12C |= 0x400 (mode select)"},
    {0x7A2EC0, {0x8B, 0x0D, 0xDC, 0xCA, 0x91, 0x00}, 6, "UIQRMainMenu: mov ecx, [cFEng 0x91CADC]"},
    {0x7AA8DA, {0x8B, 0x46, 0x4C, 0x89, 0x42, 0x18}, 6, "MSOption::React: FEDatabase +0x18 (RaceMode) = the kind"},
    {0x7A2F9F, {0x81, 0xFE, 0x64, 0xB3, 0x1A, 0x91}, 6, "UIQRModeSelect: cmp msg, Back (0x911AB364)"},
    {0x7A2FAB, {0x81, 0xFE, 0xD1, 0xE1, 0xFD, 0xE1}, 6, "UIQRModeSelect: cmp msg, EXITCOMPLETE (0xE1FDE1D1)"},
    {0x7A2FB7, {0x8B, 0xBF, 0x38, 0x01, 0x00, 0x00, 0x81, 0xFF, 0x10, 0x72, 0x40, 0x0C}, 12,
     "UIQRModeSelect: the previous button at +0x138, pressed"},
    {0x7A2FDA, {0x81, 0xA0, 0x2C, 0x01, 0x00, 0x00, 0xFF, 0xFB, 0xFF, 0xFF}, 10,
     "UIQRModeSelect Back: FEDatabase +0x12C &= ~0x400"},
    {0x7AB4AC,
     {0x8B, 0x86, 0x28, 0x01, 0x00, 0x00, 0x8B, 0x0D, 0x04, 0xE0, 0x91, 0x00, 0x50, 0xE8, 0x82, 0x7F, 0xE5, 0xFF, 0x8B,
      0xF8, 0x6A, 0x00, 0x8B, 0xCF, 0xE8, 0xB7, 0xE6, 0xE3, 0xFF, 0x8B, 0x8E, 0x28, 0x01, 0x00, 0x00, 0xE8, 0x4C, 0xF5,
      0xE4, 0xFF, 0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x50, 0xE8, 0x00, 0x27, 0xDC, 0xFF},
     52,
     "UIQRTrackOptions accept: GRaceDatabase [0x91E004], AllocCustomRace 0x603440, GetRaceType 0x5FAA20, "
     "GetQuickRaceSettings 0x56DBE0"},
    {0x7AB4E0,
     {0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00, 0x50, 0x57, 0xE8, 0x33, 0x28, 0xDC, 0xFF, 0x8B, 0x0D, 0x90, 0xCF, 0x91, 0x00,
      0xE8, 0x28, 0xDC, 0xCB, 0xFF, 0x84, 0xC0, 0x74, 0x09, 0x6A, 0x01, 0x8B, 0xCF, 0xE8, 0x5B, 0x19, 0xE3, 0xFF, 0x8B,
      0x0D, 0x04, 0xE0, 0x91, 0x00, 0x6A, 0x00, 0x57, 0xE8, 0x9D, 0x55, 0xE5, 0xFF, 0x8B, 0x0D, 0x04, 0xE0, 0x91, 0x00,
      0x57, 0xE8, 0xC1, 0x84, 0xE3, 0xFF},
     63, "UIQRTrackOptions accept: FillCustomRace 0x56DD20, SetStartupRace 0x600AB0 (context 0), FreeCustomRace 0x5E39E0"},
    {0x50DF70, {0x8B, 0x44, 0x24, 0x04, 0x56, 0x50, 0x8B, 0xF1}, 8, "GRaceDatabase::GetRaceFromName"},
    {0x5DC9D0, {0x53, 0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x2C}, 7, "GRaceDatabase::ClearStartupRace"},
    {0x7AAC43, {0x8B, 0x47, 0x10, 0x8B, 0x0D, 0xDC, 0xCA, 0x91, 0x00, 0x6A, 0x00, 0x50, 0x68, 0x23, 0x83, 0x82, 0x21, 0xE8,
                0x37, 0xC0, 0xD6, 0xFF},
     22, "UIQRModeSelect::Setup: QueuePackageMessage(0x21828323, its package, 0)"},
    {0x4B4380, {0xB8, 0x80, 0x43, 0x4B, 0x00, 0xC3}, 6, "ICountdown::_IHandle"},
    {0x567F30, {0x8B, 0x41, 0x14, 0x85, 0xC0, 0x0F, 0x9F, 0xC0, 0xC3}, 9, "Countdown::IsActive: the count at +0x14"},
};
static const Slot kGameSlots[] = {
    {0x8B7590, 0x00, 0x7B4980, "CustomRace vtable +0x00 destructor"},
    {0x8B7590, 0x04, 0x7AA710, "CustomRace vtable +0x04 React"},
    {kModeVtbl, 0x04, 0x7A2F80, "UIQRModeSelect vtable +0x04 NotificationMessage"},
    {kModeVtbl, 0x0C, 0x7A2F20, "UIQRModeSelect vtable +0x0C RefreshHeader"},
    {kModeVtbl, 0x10, 0x7AA900, "UIQRModeSelect vtable +0x10 Setup"},
    {kCountdownVtbl, 0x08, 0x567F30, "Countdown ICountdown vtable +0x08 IsActive"},
};

// ---------------------------------------------------------------- settings and state

enum GameState
{
    GS_IDLE,
    GS_MAPS,     // our map list is (or is about to be) on screen
    GS_MODES,    // our mode list
    GS_CAR,      // the carrier race set, the game's car select on screen
    GS_WAIT_GO,  // in the race, waiting for the game's GO
    GS_PLAYING,  // F-Town loaded, the mode running
    GS_FAILED,   // F-Town could not be loaded: the race goes on in Rockport
};
static const char* const kStateNames[] = {"idle", "maps", "modes", "car select", "waiting for GO", "playing",
                                          "failed"};
enum OptionId
{
    OPT_BONUS = 1,
    OPT_MAP_FTOWN = 10,
    OPT_MAP_FTOWN_EVENING = 11,  // F-Town (Evening) (FTownEvening.h)
    OPT_FREE_ROAM = 20,
    OPT_EVENT0 = 21,  // + k: event k of ftown-events.json
};
static bool g_menuEnabled = true, g_menuOn;
static GameState g_gs = GS_IDLE;
static int g_gsMode = OPT_FREE_ROAM, g_gsPick;
static char g_carrier[32] = "15.2.1";
static char g_dragCarrier[32] = "11.7.1";  // [Game] DragCarrierEvent (Run J item 4); empty: the Sprint carrier
static float g_noCountdownSeconds = 20.0f, g_waitSince;
static bool g_startAtGo = true, g_seenHigh;
static bool g_startEarly = true;  // [Game] StartEarly (Run I item 12): F-Town before the game's countdown
static bool g_startOnFTown = true, g_startHooks;  // [Game] StartOnFTown (Run J item 1): the intro and grid moved
static bool g_earlyDone, g_earlyGaveUp;  // the early start done for this wait / given up (the game keeps the car)
static int g_lastCount = -1;  // the countdown's last number seen while waiting
static int g_earlyBack;                 // times the car was put back at the start while waiting
static float g_box[4] = {629.6f, 7072.1f, 3370.4f, 11063.9f};  // F-Town's closed edge box (ftown/ftown-city.json)
static DWORD g_icons[3] = {0x2A49B5E2, 0x2521E5EB, 0xE6313967};  // bonus, F-Town, Free Roam (events: their json icon)
// Run I item 13 (docs/ftown-race-notes.md R18): our own icons (ftown-icons.bun, tools/ftownicons/make_icons.py from the
// user's logos): one texture pack, handed to the game's LoadChunks when the Quick Race menu is first built and kept for
// the process's life; the front end finds an IconOption's texture by its name hash in any loaded pack (as the HUD finds
// the minimap's). Missing or not as expected: the game's icons above.
static const DWORD kIconMorning = 0x87FC212E, kIconEvening = 0x2F931900, kIconFreeRoam = 0xD9B13185;  // bStringHash
static char g_iconFile[MAX_PATH], g_iconPath[MAX_PATH];
static BYTE* g_iconBuf;  // read and checked at start; handed to the game once
static DWORD g_iconSize;
static bool g_iconsLoaded;
static DWORD g_iconEvening;  // the evening map's icon (the game's F-Town icon until ours load)

// our texts: name hashes of our own choosing (none is in the game's string table, which the lookup searches only
// after ours: a clash would show our text for one of the game's) and the texts shown
struct Text
{
    DWORD hash;
    const char* text;
};
static Text g_texts[4 + kMaxEvents] = {
    {0x7A6F1A3Bu, "Bonus Maps"},        // the Quick Race option and the map list's title
    {0x0F70C5A1u, "F-Town"},            // the map, and the mode list's title
    {0x3DE1B6F4u, "Free Roam"},
    {0x5E4C1A93u, "F-Town (Evening)"},  // the evening's map, and its mode list's title
};
static int g_textCount = 4;
static const DWORD kTextBonus = 0x7A6F1A3Bu, kTextFTown = 0x0F70C5A1u, kTextFreeRoam = 0x3DE1B6F4u;
static const DWORD kTextFTownEvening = 0x5E4C1A93u;
// the events' names (in the list's order; the first is the Time Attack's hash as before); none of these is in the
// game's English string table (tools/citymap/tests/test_events.py checks LANGUAGES/English.bin)
static const DWORD kEventText[kMaxEvents] = {0x5B2C9E07u, 0x6D41A3C9u, 0x2E8F57B2u, 0x41C6D08Eu,
                                             0x13A7E4F5u, 0x7C59B26Au, 0x0AD38F14u, 0x36E1C7D3u};
static char g_modeWhy[96];

static bool IsEventMode(int mode) { return mode >= OPT_EVENT0 && mode < OPT_EVENT0 + g_eventCount; }

static const char* ModeName(int mode)
{
    return IsEventMode(mode) ? g_events[mode - OPT_EVENT0].name : "Free Roam";
}

static void GameSettings()
{
    g_menuEnabled = GetPrivateProfileIntA("Menu", "Enabled", 1, g_iniPath) == 1;
    const char* keys[3] = {"IconBonus", "IconMap", "IconFreeRoam"};
    char def[16];
    for (int k = 0; k < 3; k++)
    {
        snprintf(def, sizeof(def), "0x%08lX", (unsigned long)g_icons[k]);
        g_icons[k] = (DWORD)IniHex("Menu", keys[k], def);
    }
    g_iconEvening = g_icons[1];
    GetPrivateProfileStringA("Menu", "IconFile", "ftown-icons.bun", g_iconFile, sizeof(g_iconFile), g_iniPath);
    GetPrivateProfileStringA("Game", "CarrierEvent", "15.2.1", g_carrier, sizeof(g_carrier), g_iniPath);
    GetPrivateProfileStringA("Game", "DragCarrierEvent", "11.7.1", g_dragCarrier, sizeof(g_dragCarrier), g_iniPath);
    g_noCountdownSeconds = IniFloat("Game", "NoCountdownSeconds", 20.0f);
    g_startAtGo = GetPrivateProfileIntA("Game", "StartAtGo", 1, g_iniPath) == 1;
    g_startEarly = GetPrivateProfileIntA("Game", "StartEarly", 1, g_iniPath) == 1;
    g_startOnFTown = GetPrivateProfileIntA("Game", "StartOnFTown", 1, g_iniPath) == 1;
    char buf[128];
    GetPrivateProfileStringA("Game", "Box", "", buf, sizeof(buf), g_iniPath);
    float b[4];
    if (buf[0] && sscanf(buf, " %f , %f , %f , %f", &b[0], &b[1], &b[2], &b[3]) == 4)
        memcpy(g_box, b, sizeof(b));
}

static void SetState(GameState s, const char* why)
{
    if (s == g_gs)
        return;
    Log("game: %s -> %s (%s)", kStateNames[g_gs], kStateNames[s], why);
    g_gs = s;
    if (s == GS_IDLE)
        g_dragRace = false;  // our drag carrier ends with the flow
}

// ---------------------------------------------------------------- the game's front-end functions

typedef void(__thiscall* AddOptionFn)(void*, void*);
typedef void*(__thiscall* IconCtorFn)(void*, DWORD, DWORD, DWORD);
typedef void(__thiscall* SetInitialFn)(void*, int);
typedef void(__thiscall* NotifyFn)(void*, DWORD, void*, DWORD, DWORD);
typedef void(__thiscall* ReactFn)(void*, const char*, DWORD, void*, DWORD, DWORD);
typedef void(__thiscall* SwitchFn)(void*, const char*, int, unsigned, bool);
typedef void(__thiscall* QueueMessageFn)(void*, DWORD, const char*, void*);
typedef void(__cdecl* SetLangHashFn)(const char*, DWORD, DWORD);
typedef void*(__thiscall* RaceFromNameFn)(void*, const char*);
typedef int(__thiscall* RaceTypeFn)(void*);
typedef void*(__thiscall* AllocCustomFn)(void*, void*);
typedef void(__thiscall* FillCustomFn)(void*, void*, void*);
typedef void(__thiscall* SetStartupFn)(void*, void*, int);
typedef void(__thiscall* FreeCustomFn)(void*, void*);
typedef void(__thiscall* VoidFn)(void*);

static void* FrontEnd()
{
    DWORD fe = 0;
    return ReadDword(kFE, &fe) && fe ? (void*)(UINT_PTR)fe : nullptr;
}

static void Switch(const char* package)
{
    void* fe = FrontEnd();
    if (!fe)
    {
        Log("menu: no front end (0x91CADC) to switch to %s", package);
        return;
    }
    Log("menu: to %s", package);
    ((SwitchFn)(UINT_PTR)kSwitch)(fe, package, 0, 0, false);
}

static DWORD* FEDatabase()
{
    DWORD db = 0;
    return ReadDword(kFEDatabase, &db) && db ? (DWORD*)(UINT_PTR)db : nullptr;
}

// ---------------------------------------------------------------- our options

static DWORD g_optionVtbl[2];  // CustomRace's destructor, our React

static void __fastcall OptionReact(void* self, void*, const char* pkg, DWORD data, void* obj, DWORD p1, DWORD p2)
{
    if (data != kMsgPressed)
        return;
    int id = (int)*(DWORD*)((BYTE*)self + 0x4C);
    if (id == OPT_BONUS)
    {
        // what Custom Race does (QRMode 1: the game opens its mode select), then our flow on that screen
        ((ReactFn)(UINT_PTR)kCustomRaceReact)(self, pkg, data, obj, p1, p2);
        SetState(GS_MAPS, "Bonus Maps chosen");
        return;
    }
    g_gsPick = id;
    Log("menu: option %d chosen", id);
}

static void* NewOption(DWORD icon, DWORD name, int id)
{
    void* o = ((void*(__cdecl*)(unsigned))(UINT_PTR)kNew)(0x50);
    if (!o)
        return nullptr;
    ((IconCtorFn)(UINT_PTR)kIconCtor)(o, icon, name, 0);
    *(DWORD*)o = (DWORD)(UINT_PTR)g_optionVtbl;
    *(DWORD*)((BYTE*)o + 0x4C) = (DWORD)id;
    return o;
}

static void AddOurs(void* menu, DWORD icon, DWORD name, int id)
{
    void* o = NewOption(icon, name, id);
    if (o)
        ((AddOptionFn)(UINT_PTR)kAddOption)(menu, o);
}

// ---------------------------------------------------------------- the hooks

// 0x7AA81C: the Quick Race main menu's last AddOption: the game's option, then Bonus Maps. Building this menu ends any
// flow of ours that has not reached the race.
static void IconsLoad();

static void __fastcall HkQrMainAdd(void* menu, void*, void* option)
{
    IconsLoad();  // before any option of ours is made
    ((AddOptionFn)(UINT_PTR)kAddOption)(menu, option);
    if (g_gs != GS_IDLE && g_gs < GS_WAIT_GO)
        SetState(GS_IDLE, "the Quick Race menu again");
    AddOurs(menu, g_icons[0], kTextBonus, OPT_BONUS);
    Log("menu: Bonus Maps added to the Quick Race menu");
}

// UIQRModeSelect::Setup (the ctor's call 0x7BA4D7, vtable +0x10): our lists while armed
static void __fastcall HkModeSetup(void* menu, void*)
{
    if (g_gs != GS_MAPS && g_gs != GS_MODES)
    {
        ((VoidFn)(UINT_PTR)kModeSetup)(menu);
        return;
    }
    if (g_gs == GS_MAPS)
    {
        AddOurs(menu, g_icons[1], kTextFTown, OPT_MAP_FTOWN);
        if (g_eveOk)
            AddOurs(menu, g_iconEvening, kTextFTownEvening, OPT_MAP_FTOWN_EVENING);
    }
    else
    {
        AddOurs(menu, g_icons[2], kTextFreeRoam, OPT_FREE_ROAM);
        if (g_taEnabled)
            for (int k = 0; k < g_eventCount; k++) AddOurs(menu, g_events[k].icon, kEventText[k], OPT_EVENT0 + k);
    }
    g_gsPick = 0;
    ((SetInitialFn)(UINT_PTR)kSetInitial)(menu, 0);
    void* fe = FrontEnd();
    if (fe)
        ((QueueMessageFn)(UINT_PTR)kQueueMessage)(fe, 0x21828323, *(const char**)((BYTE*)menu + 0x10), nullptr);
    Log("menu: %s list set up", g_gs == GS_MAPS ? "the map" : "F-Town's mode");
}

// UIQRModeSelect::RefreshHeader's title (the call 0x7A2F6D): ours while armed
static void __cdecl HkModeTitle(const char* pkg, DWORD obj, DWORD hash)
{
    if (g_gs == GS_MAPS)
        hash = kTextBonus;
    else if (g_gs == GS_MODES)
        hash = g_eveWanted ? kTextFTownEvening : kTextFTown;
    ((SetLangHashFn)(UINT_PTR)kSetLangHash)(pkg, obj, hash);
}

// R6: the carrier race as the game's Track Options sets one, with our settings: 1 lap, forward, no opponents, skill
// 0, no heat, no traffic, no catch-up, no cops (the PC's RaceSettings record, 0x18 bytes, FillCustomRace 0x56DD20)
static bool SetCarrierRace()
{
    DWORD db = 0;
    DWORD* fedb = FEDatabase();
    if (!ReadDword(kRaceDb, &db) || !db || !fedb)
    {
        Log("game: NO RACE: the race database (0x91E004) or FEDatabase (0x91CF90) is not there");
        return false;
    }
    // Run J item 4: a drag event of ours runs as the game's own drag race (its HUD, heat, shifts) when
    // [Game] DragCarrierEvent names a drag race (kind 2); otherwise the Sprint carrier as before
    g_dragRace = false;
    const char* name = g_carrier;
    int kind = 0;
    void* race = nullptr;
    if (IsEventMode(g_gsMode) && g_events[g_gsMode - OPT_EVENT0].kind == EK_DRAG && g_dragCarrier[0])
    {
        race = ((RaceFromNameFn)(UINT_PTR)kGetRaceFromName)((void*)(UINT_PTR)db, g_dragCarrier);
        int t = race ? ((RaceTypeFn)(UINT_PTR)kGetRaceType)(race) : -1;
        if (race && t == 2)
            name = g_dragCarrier, kind = 2, g_dragRace = true;
        else
        {
            Log("game: the drag carrier %s is %s: the Sprint carrier %s instead ([Game] DragCarrierEvent)",
                g_dragCarrier, race ? "not a drag race" : "not in the race database", g_carrier);
            race = nullptr;
        }
    }
    if (!race)
        race = ((RaceFromNameFn)(UINT_PTR)kGetRaceFromName)((void*)(UINT_PTR)db, g_carrier);
    if (!race)
    {
        Log("game: NO RACE: the carrier event %s is not in the race database ([Game] CarrierEvent)", g_carrier);
        return false;
    }
    int type = ((RaceTypeFn)(UINT_PTR)kGetRaceType)(race);
    if (type != kind)
    {
        Log("game: NO RACE: the carrier event %s is of kind %d, not %s", name, type, kind ? "a drag (2)" : "a Sprint (0)");
        return false;
    }
    void* custom = ((AllocCustomFn)(UINT_PTR)kAllocCustom)((void*)(UINT_PTR)db, race);
    if (!custom)
    {
        Log("game: NO RACE: AllocCustomRace gave nothing");
        return false;
    }
    BYTE settings[0x18] = {0};
    settings[4] = 1;  // laps
    int traffic = RoadNetTrafficLevel(g_gsMode);  // moving traffic: the game's level 1..3 (10/30/50 %), 0 = none
    settings[0xA] = (BYTE)traffic;
    ((FillCustomFn)(UINT_PTR)kFillCustom)(fedb, custom, settings);
    ((SetStartupFn)(UINT_PTR)kSetStartup)((void*)(UINT_PTR)db, custom, 0);
    ((FreeCustomFn)(UINT_PTR)kFreeCustom)((void*)(UINT_PTR)db, custom);
    fedb[0x18 / 4] = (DWORD)kind;  // RaceMode: a Sprint (0) or a drag (2)
    char tr[48] = "no traffic";
    if (traffic)
        snprintf(tr, sizeof(tr), "traffic level %d (%d %%)", traffic, traffic == 1 ? 10 : traffic == 2 ? 30 : 50);
    Log("game: carrier race %s set (%s: 1 lap, 0 opponents, %s, no cops) for %s", name,
        kind == 2 ? "a drag race" : "a Sprint", tr, ModeName(g_gsMode));
    return true;
}

// UIQRModeSelect::NotificationMessage (vtable +0x04): our steps while armed
static void __fastcall HkModeNotify(void* menu, void*, DWORD msg, void* obj, DWORD p1, DWORD p2)
{
    DWORD prev = *(DWORD*)((BYTE*)menu + 0x138);
    bool exitDone = msg == kMsgExitComplete;
    if (g_gs != GS_MAPS && g_gs != GS_MODES)
    {
        ((NotifyFn)(UINT_PTR)kModeNotify)(menu, msg, obj, p1, p2);
        return;
    }
    if (g_gs == GS_MAPS && exitDone && prev == kMsgBack)
    {
        // Back from the map list: the game's own (the mode select bit cleared, the Quick Race main menu)
        SetState(GS_IDLE, "Back from the map list");
        ((NotifyFn)(UINT_PTR)kModeNotify)(menu, msg, obj, p1, p2);
        return;
    }
    ((NotifyFn)(UINT_PTR)kScrollerNotify)(menu, msg, obj, p1, p2);
    if (!exitDone)
        return;
    prev = *(DWORD*)((BYTE*)menu + 0x138);
    if (prev == kMsgBack)
    {
        SetState(GS_MAPS, "Back from the mode list");
        Switch("MainMenu_Sub.fng");
        return;
    }
    if (prev != kMsgPressed)
        return;
    if (g_gs == GS_MAPS && (g_gsPick == OPT_MAP_FTOWN || g_gsPick == OPT_MAP_FTOWN_EVENING))
    {
        g_eveWanted = g_gsPick == OPT_MAP_FTOWN_EVENING;
        SetState(GS_MODES, g_eveWanted ? "F-Town (Evening) chosen" : "F-Town chosen");
        Switch("MainMenu_Sub.fng");
    }
    else if (g_gs == GS_MODES && (g_gsPick == OPT_FREE_ROAM || IsEventMode(g_gsPick)))
    {
        g_gsMode = g_gsPick;
        if (SetCarrierRace())
        {
            snprintf(g_modeWhy, sizeof(g_modeWhy), "%s chosen", ModeName(g_gsMode));
            SetState(GS_CAR, g_modeWhy);
            Switch("Car_Select.fng");
        }
        else
            Switch("MainMenu_Sub.fng");  // the mode list again
    }
    else
        Switch("MainMenu_Sub.fng");
}

// UIQRCarSelect's Back (the call 0x7C26ED, normally to Track_Options.fng): our mode list while a bonus race is pending
static void __fastcall HkCarBack(void* fe, void*, const char* package, int a, unsigned b, bool c)
{
    if (g_gs != GS_CAR)
    {
        ((SwitchFn)(UINT_PTR)kSwitch)(fe, package, a, b, c);
        return;
    }
    DWORD db = 0;
    if (ReadDword(kRaceDb, &db) && db)
        ((VoidFn)(UINT_PTR)kClearStartup)((void*)(UINT_PTR)db);
    DWORD* fedb = FEDatabase();
    if (fedb)
        fedb[0x12C / 4] |= kModeSelectBit;
    SetState(GS_MODES, "Back from the car select");
    Log("menu: to MainMenu_Sub.fng (instead of %s)", package);
    ((SwitchFn)(UINT_PTR)kSwitch)(fe, "MainMenu_Sub.fng", 0, 0, false);
}

// ---------------------------------------------------------------- the string lookup (0x56BB80)

static BYTE* g_lookupStub;

static bool InstallLookup()
{
    g_textCount = 4;
    if (g_taEnabled)
        for (int k = 0; k < g_eventCount; k++) g_texts[g_textCount++] = {kEventText[k], g_events[k].name};
    const int n = g_textCount;
    const Text* kTexts = g_texts;
    g_lookupStub = (BYTE*)VirtualAlloc(nullptr, 256, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!g_lookupStub)
        return false;
    BYTE* p = g_lookupStub;
    for (int k = 0; k < n; k++)
    {
        // cmp edx, hash; jne +6; mov eax, text; ret
        *p++ = 0x81, *p++ = 0xFA;
        memcpy(p, &kTexts[k].hash, 4), p += 4;
        *p++ = 0x75, *p++ = 0x06;
        *p++ = 0xB8;
        DWORD t = (DWORD)(UINT_PTR)kTexts[k].text;
        memcpy(p, &t, 4), p += 4;
        *p++ = 0xC3;
    }
    // the game's own first instructions, then on at 0x56BB87
    static const BYTE first[7] = {0x53, 0x8B, 0x1D, 0x80, 0xCF, 0x91, 0x00};
    memcpy(p, first, 7), p += 7;
    *p++ = 0xE9;
    DWORD rel = (kLookup + 7) - ((DWORD)(UINT_PTR)p + 4);
    memcpy(p, &rel, 4), p += 4;
    FlushInstructionCache(GetCurrentProcess(), g_lookupStub, 256);
    BYTE jmp[7] = {0xE9, 0, 0, 0, 0, 0x90, 0x90};
    *(DWORD*)(jmp + 1) = (DWORD)(UINT_PTR)g_lookupStub - (kLookup + 5);
    return WriteCode(kLookup, jmp, 7);
}

static bool PatchCall(DWORD at, const void* to)
{
    BYTE call[5] = {0xE8};
    *(DWORD*)(call + 1) = (DWORD)(UINT_PTR)to - (at + 5);
    return WriteCode(at, call, 5);
}

static bool PatchSlot(DWORD at, const void* to)
{
    DWORD v = (DWORD)(UINT_PTR)to;
    return WriteCode(at, (const BYTE*)&v, 4);
}

// The icons' file at start: one texture pack chunk (padding allowed) whose keys hold our three names.
static void IconsStart()
{
    strcpy(g_iconPath, g_iniPath);
    char* slash = strrchr(g_iconPath, '\\');
    snprintf(slash ? slash + 1 : g_iconPath, MAX_PATH - (slash ? (int)(slash + 1 - g_iconPath) : 0), "%s", g_iconFile);
    HANDLE f = CreateFileA(g_iconPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("icons: %s cannot be opened (error %lu): the game's icons", g_iconFile, (unsigned long)GetLastError());
        return;
    }
    DWORD size = GetFileSize(f, nullptr), got = 0;
    BYTE* b = size && size < (16u << 20) ? (BYTE*)VirtualAlloc(nullptr, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
                                         : nullptr;
    bool read = b && ReadFile(f, b, size, &got, nullptr) && got == size;
    CloseHandle(f);
    const char* err = read ? nullptr : "cannot be read";
    int packs = 0, found = 0;
    for (DWORD off = 0; !err && off < size;)
    {
        if (off + 8 > size || *(DWORD*)(b + off + 4) > size - off - 8)
        {
            err = "a chunk runs past the file's end";
            break;
        }
        DWORD id = *(DWORD*)(b + off), n = *(DWORD*)(b + off + 4);
        if (id == 0xB3300000)
        {
            packs++;
            // the keys (0x33310002, (hash, 0) pairs) inside its info (0xB3310000)
            for (DWORD i = off + 8; i + 8 <= off + 8 + n;)
            {
                DWORD cid = *(DWORD*)(b + i), cn = *(DWORD*)(b + i + 4);
                if (cn > off + 8 + n - i - 8)
                    break;
                if (cid == 0xB3310000)
                    for (DWORD j = i + 8; j + 8 <= i + 8 + cn;)
                    {
                        DWORD kid = *(DWORD*)(b + j), kn = *(DWORD*)(b + j + 4);
                        if (kn > i + 8 + cn - j - 8)
                            break;
                        for (DWORD k = 0; kid == 0x33310002 && k + 8 <= kn; k += 8)
                        {
                            DWORD h = *(DWORD*)(b + j + 8 + k);
                            found |= (h == kIconMorning ? 1 : 0) | (h == kIconEvening ? 2 : 0) |
                                     (h == kIconFreeRoam ? 4 : 0);  // each name once at least (review)
                        }
                        j += 8 + kn;
                    }
                i += 8 + cn;
            }
        }
        else if (id != 0)
            err = "a chunk that is not a texture pack";
        off += 8 + n;
    }
    if (!err && packs != 1)
        err = "not exactly one texture pack";
    if (!err && found != 7)
        err = "not FTOWN_ICON_MORNING, _EVENING and _FREEROAM";
    if (err)
    {
        Log("icons: %s: %s: the game's icons", g_iconFile, err);
        if (b)
            VirtualFree(b, 0, MEM_RELEASE);
        return;
    }
    g_iconBuf = b;
    g_iconSize = size;
    Log("icons: %s: %lu bytes, one texture pack with FTOWN_ICON_MORNING, _EVENING, _FREEROAM (loaded with the Quick "
        "Race menu)", g_iconFile, (unsigned long)size);
}

// Once, when the Quick Race menu is first built: the pack to the game (kept loaded); the three icons ours from then on.
static void IconsLoad()
{
    if (g_iconsLoaded || !g_iconBuf)
        return;
    ((LoadChunksFn)(UINT_PTR)kLoadChunks)(g_iconBuf, (int)g_iconSize, "FTOWNICONS");
    g_iconsLoaded = true;
    g_icons[1] = kIconMorning;
    g_iconEvening = kIconEvening;
    g_icons[2] = kIconFreeRoam;
    Log("icons: our pack loaded: F-Town 0x%08lX, F-Town (Evening) 0x%08lX, Free Roam 0x%08lX",
        (unsigned long)kIconMorning, (unsigned long)kIconEvening, (unsigned long)kIconFreeRoam);
}

static void StartHooksInstall();  // Run J item 1 (below)

// At start: every site checked (a mismatch turns only the menu off), then the hooks.
static void GameStart()
{
    Log("keys %s ([Keys] Enabled = %d)", g_keysEnabled ? "on: F8 / F7 / F6 / F5 work as before" : "off", g_keysEnabled);
    if (!g_menuEnabled)
    {
        Log("menu off ([Menu] Enabled = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kGameSites) ok &= BytesAre(s);
    for (const Slot& s : kGameSlots) ok &= SlotIs(s);
    if (!ok)
    {
        Log("WRONGBYTES in the menu's sites: the Bonus Maps menu off (the rest works)");
        return;
    }
    g_optionVtbl[0] = kCustomRaceDtor;
    g_optionVtbl[1] = (DWORD)(UINT_PTR)&OptionReact;
    if (!InstallLookup() || !PatchCall(kQrMainAddSite, (const void*)&HkQrMainAdd) ||
        !PatchCall(kModeSetupSite, (const void*)&HkModeSetup) || !PatchSlot(kModeVtbl + 0x10, (const void*)&HkModeSetup) ||
        !PatchSlot(kModeVtbl + 0x04, (const void*)&HkModeNotify) ||
        !PatchCall(kModeTitleSite, (const void*)&HkModeTitle) || !PatchCall(kCarBackSite, (const void*)&HkCarBack))
    {
        Log("menu: a hook could not be written; the menu is incomplete");
        return;
    }
    g_menuOn = true;
    StartHooksInstall();
    IconsStart();
    char modes[512] = "Free Roam";
    for (int k = 0; g_taEnabled && k < g_eventCount; k++)
        snprintf(modes + strlen(modes), sizeof(modes) - strlen(modes), ", %s", g_events[k].name);
    Log("menu: Bonus Maps on the Quick Race menu (F-Town: %s); carrier race %s; F-Town starts %s", modes, g_carrier,
        g_startAtGo ? "at the game's GO" : "as soon as the car is there");
}

// ---------------------------------------------------------------- Run J item 1: the race starts on F-Town
//
// The game puts the car on its start grid twice before GO (docs/ftown-race-notes.md "Run J", WorldProbe's callers in
// Run J): the race's intro NIS animates it every frame around the scene origin (SuspensionSpline::SetNISPosition,
// 0x691152 / 0x6912BA), which EPlayRaceNIS sets from the start marker through INIS::StartLocation (the call at
// 0x64148E, vtable slot 0x8B0D84 = NISActivity::StartLocation 0x6EA330: physics position, direction = 1 -
// VU0_Atan2(dir.x, dir.z) turns); after the intro GRacerInfo::RestoreStartPosition (the call at 0x5E97A0) puts it on
// the grid with IRacer::PrepareForRace (slots 0x8925B8 and 0x892968 = AIVehicleRacecar::PrepareForRace 0x4169B0:
// SetVehicleOnGround(rpi.Position, rpi.Direction)); the Restart Race does that again. Then staging keeps the car where
// it is until GO. So both are pointed at the mode's start while a bonus race of ours is on: the intro plays on F-Town
// and the game itself puts the car on our start; F-Town's chunks are loaded in the intro's hook, before the game puts
// any car down there. Every other race goes straight to the game's functions.

static const DWORD kNisStartSlot = 0x8B0D84, kNisStartLocation = 0x6EA330, kVu0Atan2 = 0x5CB5D0;
static const DWORD kRacerSlotA = 0x8925B8, kRacerSlotB = 0x892968, kPrepareForRace = 0x4169B0;
static const DWORD kNisCallReturn = 0x641491;  // after EPlayRaceNIS's call [edx + 0x0C] at 0x64148E (checked below)
static const Site kStartSites[] = {
    {0x6EA330, {0x8B, 0x44, 0x24, 0x04, 0x56, 0x8B, 0xF0, 0x57, 0x8B, 0x3E}, 10,
     "NISActivity::StartLocation(const Vector3&, float)"},
    {0x5CB5D0, {0x51, 0xD9, 0x44, 0x24, 0x0C}, 5, "VU0_Atan2(float, float)"},
    {0x641480, {0x8B, 0x44, 0x24, 0x10, 0x8B, 0x16, 0x50, 0x8D, 0x4C, 0x24, 0x20, 0x51, 0x8B, 0xCE, 0xFF, 0x52, 0x0C}, 17,
     "EPlayRaceNIS: INIS::StartLocation(marker position, 1 - VU0_Atan2) through the vtable (+0x0C)"},
    {0x640FBC, {0x39, 0x2D, 0xC8, 0x85, 0x98, 0x00}, 6, "EPlayRaceNIS: cmp [INIS::mInstance 0x9885C8], 0"},
    {0x4169B0, {0x53, 0x8B, 0xD9, 0x8B, 0x8B, 0xF4, 0xF8, 0xFF, 0xFF}, 9, "AIVehicleRacecar::PrepareForRace"},
    {0x5E9793, {0x8B, 0x10, 0x51, 0x8B, 0xC8, 0xC7, 0x44, 0x24, 0x28, 0x01, 0x00, 0x00, 0x00, 0xFF, 0x52, 0x04}, 16,
     "GRacerInfo::RestoreStartPosition: IRacer::PrepareForRace(rpi) through the vtable (+0x04)"},
};
static const Slot kStartSlots[] = {
    {0x8B0D78, 0x0C, 0x6EA330, "NISActivity INIS vtable +0x0C StartLocation"},
    {0x8925B4, 0x04, 0x4169B0, "AIVehicleRacecar IRacer vtable +0x04 PrepareForRace"},
    {0x892964, 0x04, 0x4169B0, "AIVehicleHuman IRacer vtable +0x04 PrepareForRace"},
};

// a bonus race of ours is chosen (the carrier set) or running
static bool RaceOurs() { return g_menuOn && (g_gs == GS_CAR || g_gs == GS_WAIT_GO || g_gs == GS_PLAYING); }

// the mode's start: render x, y, z, heading (degrees counter-clockwise from render +x)
static void ModeStartPose(float* r)
{
    const float* s = IsEventMode(g_gsMode) ? g_events[g_gsMode - OPT_EVENT0].start : g_spawns[0];
    memcpy(r, s, 16);
}

typedef void(__thiscall* NisStartFn)(void*, const float*, float);
typedef void(__thiscall* PrepareFn)(void*, const BYTE*);

static void __fastcall HkNisStart(void* self, void*, const float* pos, float dir)
{
    // review: only the race's intro (EPlayRaceNIS's call at 0x64148E returns to 0x641491), not any other NIS
    if (!g_startHooks || !RaceOurs() || __builtin_return_address(0) != (void*)(UINT_PTR)kNisCallReturn)
    {
        ((NisStartFn)(UINT_PTR)kNisStartLocation)(self, pos, dir);
        return;
    }
    if (!g_city.buffer)
    {
        // collision before the game puts the car down on F-Town (the intro places it from its first frame)
        if (LoadCity("NOT LOADED for the intro"))
        {
            g_cityForIntro = true;
            Log("race start: F-Town loaded for the intro (the car is placed when the race runs)");
        }
        else
        {
            // review: an intro on F-Town with nothing there would be a void: the game's (F-Town loads when the race
            // runs, and PrepareForRace then puts the car on our start)
            Log("race start: F-Town could not be loaded for the intro: the intro stays the game's");
            ((NisStartFn)(UINT_PTR)kNisStartLocation)(self, pos, dir);
            return;
        }
    }
    float r[4];
    ModeStartPose(r);
    float h = r[3] * 3.14159265f / 180.0f, fx = -sinf(h), fz = cosf(h);
    float p[3] = {-r[1], r[2], r[0]};
    float d = 1.0f - ((float(__cdecl*)(float, float))(UINT_PTR)kVu0Atan2)(fx, fz);
    Log("race start: the race's intro on F-Town (its origin from physics (%.2f, %.2f, %.2f) direction %.3f to render "
        "(%.2f, %.2f, %.2f) direction %.3f: %s's start)", pos[0], pos[1], pos[2], dir, r[0], r[1], r[2], d,
        ModeName(g_gsMode));
    ((NisStartFn)(UINT_PTR)kNisStartLocation)(self, p, d);
}

static void __fastcall HkPrepare(void* self, void*, const BYTE* rpi)
{
    if (!g_startHooks || !RaceOurs() || !g_city.buffer)
    {
        ((PrepareFn)(UINT_PTR)kPrepareForRace)(self, rpi);
        return;
    }
    // RacePreparationInfo: +0 position, +0x0C speed, +0x10 direction, +0x1C heat, +0x20 flags (physics coordinates)
    BYTE copy[0x24];
    memcpy(copy, rpi, sizeof(copy));
    float r[4];
    ModeStartPose(r);
    float h = r[3] * 3.14159265f / 180.0f;
    float* f = (float*)copy;
    const float* was = (const float*)rpi;
    f[0] = -r[1], f[1] = r[2], f[2] = r[0];
    f[3] = 0;
    f[4] = -sinf(h), f[5] = 0, f[6] = cosf(h);
    Log("race start: the start grid on F-Town (PrepareForRace: physics (%.2f, %.2f, %.2f) -> render (%.2f, %.2f, %.2f) "
        "heading %.1f)", was[0], was[1], was[2], r[0], r[1], r[2], r[3]);
    ((PrepareFn)(UINT_PTR)kPrepareForRace)(self, copy);
}

static void StartHooksInstall()
{
    if (!g_startOnFTown)
    {
        Log("race start: the game's own (the intro and the grid in Rockport: [Game] StartOnFTown = 0)");
        return;
    }
    bool ok = true;
    for (const Site& s : kStartSites) ok &= BytesAre(s);
    for (const Slot& s : kStartSlots) ok &= SlotIs(s);
    if (!ok)
    {
        Log("WRONGBYTES in the race start's sites: the intro and the grid stay in Rockport");
        return;
    }
    if (PatchSlot(kNisStartSlot, (const void*)&HkNisStart) && PatchSlot(kRacerSlotA, (const void*)&HkPrepare) &&
        PatchSlot(kRacerSlotB, (const void*)&HkPrepare))
    {
        g_startHooks = true;
        Log("race start: our races' intro and start grid on F-Town (slots 0x8B0D84, 0x8925B8, 0x892968)");
    }
    else
        Log("race start: a slot could not be written");
}

// ---------------------------------------------------------------- the race

// The HUD's countdown (R6): its count (4, 3, 2, 1, 0 = GO, -1 after), or -99 when the HUD has none.
static int Countdown(void* player)
{
    void* hud = ((GetPtrFn)(UINT_PTR)kGetHud)(player);
    DWORD list = 0;
    void* cd = nullptr;
    if (hud && ReadDword((DWORD)(UINT_PTR)hud + 4, &list) && list)
        cd = ((FindFn)(UINT_PTR)kFind)((void*)(UINT_PTR)list, kCountdownHandle);
    int n = 0;
    if (!cd || Vtbl(cd) != kCountdownVtbl || !SafeRead((DWORD)(UINT_PTR)cd + 0x14, &n, 4))
        return -99;
    return n;
}

static bool OffFTown(void* player)
{
    float p[3];
    if (!PlayerPosition(player, p))
        return false;
    float x = p[2], y = -p[0];
    const float m = 100.0f;
    return x < g_box[0] - m || x > g_box[2] + m || y < g_box[1] - m || y > g_box[3] + m;
}

// The mode's start: an event from its start (its barriers in), Free Roam at Spawn1. armed: held at the start for the
// game's GO (Run I item 12: the game's countdown counts on F-Town); else an event runs its own 3-2-1.
static void ModeStart(void* player, const char* why, bool armed = false)
{
    if (IsEventMode(g_gsMode))
    {
        Log("game: the %s begins (%s)", ModeName(g_gsMode), why);
        EventPlace(player, g_gsMode - OPT_EVENT0, armed);
        return;
    }
    const float* s0 = g_spawns[0];
    float sp[3] = {-s0[1], s0[2], s0[0]}, h = 0;
    if (!HeightAt(sp, &h))
    {
        Log("game: NOT MOVED: no face at spawn 1 (%s)", why);
        return;
    }
    Log("game: Free Roam at spawn 1 (%s)", why);
    Teleport(player, sp, s0[3], g_setHeading, "FREE ROAM START");
    SetResetSpot(player, sp, s0[3], "spawn 1");
    g_spawnAt = 0;
}

static void Go(void* player, const char* why)
{
    if (!g_city.buffer || g_cityForIntro)
    {
        Log("game: GO (%s): loading F-Town", why);
        Load(player);
        if (!g_city.buffer)
        {
            SetState(GS_FAILED, "F-Town could not be loaded: the race goes on in Rockport");
            return;
        }
        if (IsEventMode(g_gsMode))
            ModeStart(player, why);
        else
        {
            const float* s0 = g_spawns[0];
            float sp[3] = {-s0[1], s0[2], s0[0]};
            Log("game: Free Roam at spawn 1 (%s)", why);
            SetResetSpot(player, sp, s0[3], "spawn 1");
        }
    }
    else if (g_ta == TA_ARMED && !OffFTown(player))
        EventGo();  // the car waited at the start: its clock starts with the game's
    else if (g_earlyDone && !IsEventMode(g_gsMode) && !OffFTown(player))
        Log("game: Free Roam goes on (%s)", why);
    else
        ModeStart(player, why);
    SetState(GS_PLAYING, why);
}

// Run I item 12 (R17): F-Town and the mode's start before the game's countdown. The first frame the simulation runs
// with the player there (the track and the car loaded): Load (collision before the car, as F8), then the mode's start,
// armed. The car found off F-Town while waiting (the game put it back on its grid) goes back, at most
// kEarlyBacks times a wait; after that the old way (the mode starts at the game's GO).
static const int kEarlyBacks = 3;

static void EarlyStart(void* player, const char* why)
{
    if (!g_city.buffer || g_cityForIntro)
    {
        Log("game: %s: loading F-Town before the game's countdown (zone switching byte %u)", why,
            (unsigned)*(volatile BYTE*)(UINT_PTR)kZoneSwitchingDisabled);
        Load(player);
        if (!g_city.buffer)
        {
            SetState(GS_FAILED, "F-Town could not be loaded: the race goes on in Rockport");
            return;
        }
    }
    ModeStart(player, why, true);
    g_earlyDone = true;
}

// Once a frame while the player exists.
static void GameFrame(void* player)
{
    if (g_gs == GS_CAR)
    {
        g_waitSince = SimNow();
        g_seenHigh = false;
        g_earlyDone = g_earlyGaveUp = false;
        g_earlyBack = 0;
        g_lastCount = -1;
        snprintf(g_modeWhy, sizeof(g_modeWhy), "the race is there: %s", ModeName(g_gsMode));
        SetState(GS_WAIT_GO, g_modeWhy);
    }
    if (g_gs != GS_WAIT_GO && g_gs != GS_PLAYING)
        return;
    int n = Countdown(player);
    if (g_gs == GS_WAIT_GO)
    {
        if (n >= 1)
            g_seenHigh = true;
        // review: a Restart Race during the countdown (the count up again) gives the early start its tries again
        if (n > g_lastCount && g_lastCount >= 0)
            g_earlyBack = 0;
        g_lastCount = n;
        if (!g_startAtGo)
        {
            Go(player, "[Game] StartAtGo = 0");
            return;
        }
        if (g_startEarly && !g_earlyGaveUp)
        {
            if (!g_earlyDone && SimNow() > g_waitSince)
                EarlyStart(player, "the race is running");
            else if (g_earlyDone && g_city.buffer && !NisOn() && OffFTown(player))
            {
                if (g_earlyBack < kEarlyBacks)
                {
                    g_earlyBack++;
                    ModeStart(player, "the game put the car back on its grid", true);
                }
                else
                {
                    g_earlyGaveUp = true;
                    TimeAttackStop("the game keeps the car on its grid");
                    Log("game: the game keeps the car on its grid before GO: the mode starts at the game's GO");
                }
            }
            if (g_gs != GS_WAIT_GO)
                return;
        }
        if (g_seenHigh && n <= 0 && n != -99)
            Go(player, "the game's GO");
        else if (!g_seenHigh && SimNow() - g_waitSince > g_noCountdownSeconds)
            Go(player, "no countdown seen");
        return;
    }
    if (n >= 1)
    {
        TimeAttackStop("the race restarted");
        g_seenHigh = true;
        g_waitSince = SimNow();
        g_earlyBack = 0;
        g_earlyGaveUp = false;
        SetState(GS_WAIT_GO, "the countdown runs again: the race restarted");
        if (g_startEarly && g_city.buffer)
            ModeStart(player, "the race restarted", true);  // on F-Town again before the countdown ends
        return;
    }
    if (g_city.buffer && !NisOn() && OffFTown(player))
        ModeStart(player, "the car was off F-Town");
}

// ---------------------------------------------------------------- Run K item 2: Free Roam without the race HUD's lines
//
// Bonus Maps' Free Roam rides a Sprint carrier, so the HUD shows a race's elements: FEngHud::DetermineHudFeatures
// (0x57CA60, thiscall(IPlayer*), ret 4, a 64-bit mask in edx:eax; called once, from FEngHud::Update at 0x58CA50) sets
// 0x4000000 (RaceInformation: the timer, COMPLETE % and the position 1/1), 0x8 (the leaderboard) and 0x20 (the wrong-way
// arrow) only when GRaceStatus' play mode is Racing (FEPkg_Hud.cpp:960-991); in the game's own free roam (Roaming) they
// are off. While our Free Roam is on (a bonus race of ours, mode Free Roam) those three bits are cleared after the game's
// function; every other race (our events, Rockport's) and the career are the game's.
static const DWORD kHudFeaturesSite = 0x58CA50, kDetermineHudFeatures = 0x57CA60;
static const unsigned __int64 kRacingOnlyFeatures = 0x4000000ull | 0x8ull | 0x20ull;
static const Site kHudFeaturesSites[] = {
    {0x58CA4D, {0x55, 0x8B, 0xF1, 0xE8, 0x0B, 0x00, 0xFF, 0xFF}, 8,
     "FEngHud::Update: push the player; call FEngHud::DetermineHudFeatures (0x57CA60)"},
    {0x57CA60, {0x53, 0x55, 0x56, 0x8B, 0xD9, 0x8B, 0x4C, 0x24, 0x10, 0x8B, 0x01, 0x57}, 12,
     "FEngHud::DetermineHudFeatures: push ebx, ebp, esi; mov ebx, ecx; the player at [esp + 0x10]"},
};
static bool g_hudFeaturesOn, g_freeRoamHudLogged;

static bool RaceBeforeGo() { return RaceOurs() && g_gs != GS_PLAYING; }  // (Run K review: FTownLoader.cpp)

static bool FreeRoamOurs() { return RaceOurs() && !IsEventMode(g_gsMode); }  // (from the race's start: no flash)

static unsigned __int64 __fastcall HkHudFeatures(void* hud, void*, void* player)
{
    unsigned __int64 f = ((unsigned __int64(__thiscall*)(void*, void*))(UINT_PTR)kDetermineHudFeatures)(hud, player);
    if (!FreeRoamOurs())
    {
        g_freeRoamHudLogged = false;
        return f;
    }
    if (!g_freeRoamHudLogged && (f & kRacingOnlyFeatures))
    {
        g_freeRoamHudLogged = true;
        Log("race HUD: Free Roam: the timer, COMPLETE %%, position and leaderboard hidden (features 0x%08lX%08lX)",
            (unsigned long)(f >> 32), (unsigned long)f);
    }
    return f & ~kRacingOnlyFeatures;
}

static void HudFeaturesStart()
{
    bool ok = true;
    for (const Site& s : kHudFeaturesSites) ok &= BytesAre(s);
    if (!ok)
        Log("WRONGBYTES in the HUD features' sites: Free Roam keeps the race HUD's timer and COMPLETE %%");
    else if (HudCall(kHudFeaturesSite, (const void*)&HkHudFeatures))
    {
        g_hudFeaturesOn = true;
        Log("race HUD: Free Roam hides the race HUD's timer, COMPLETE %% and position (0x58CA50)");
    }
    else
        Log("race HUD: the call at 0x58CA50 could not be written: Free Roam keeps the race HUD's timer");
}

// TrackLoader::Unload: the race is left; everything of ours ends (F-Town itself is unloaded by the caller).
static void GameTrackUnload()
{
    if (g_gs >= GS_WAIT_GO)
        SetState(GS_IDLE, "the race was left");
}
