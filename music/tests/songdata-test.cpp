// Tests music/src/SongData.h: mode syncing with the profile, the custom songs' settings file, and
// text conversion for the game.
// Build (from music\tests): zig c++ -target x86-windows-gnu -w -municode songdata-test.cpp -o songdata-test.exe
// Run: songdata-test.exe      (exit code 0 = all passed)
#include "../src/SongData.h"
#include <stdio.h>
#include <vector>

static int failures;
static void Check(bool ok, const char* what, int got)
{
    printf("  %s %s (%d)\n", ok ? "ok  " : "FAIL", what, got);
    if (!ok)
        ++failures;
}

int wmain()
{
    printf("mode sync\n");
    {
        const int originals = 26;
        std::vector<SavedMode> ours(33), profile(26), shadow(26);
        for (int i = 0; i < 26; ++i)
        {
            profile[i].number = i;
            profile[i].mode = i < 10 ? kModeMenus : kModeRaces;
        }
        for (int i = 26; i < 33; ++i)
        {
            ours[i].number = i;
            ours[i].mode = kModeAll;
        }
        bool valid = false;
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesFromProfile,
            "first sync copies the profile to ours", 0);
        Check(ours[3].mode == kModeMenus && ours[20].mode == kModeRaces && ours[20].number == 20, "ours now mirrors the profile", ours[20].mode);
        Check(ours[30].mode == kModeAll && ours[30].number == 30, "records after the originals are untouched", ours[30].mode);
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesUnchanged, "nothing changed", 0);

        ours[3].mode = kModeOff; // the user changes an original song in the menu
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesToProfile, "a menu change goes to the profile", 0);
        Check(profile[3].mode == kModeOff, "the profile has the new mode", profile[3].mode);

        ours[28].mode = kModeOff; // a custom song's change is none of the profile's business
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesUnchanged, "a custom song's change doesn't touch the profile", 0);

        profile[5].mode = kModeAll; // the game loads another profile
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesFromProfile, "a profile load comes to ours", 0);
        Check(ours[5].mode == kModeAll && ours[3].mode == kModeOff, "ours has the loaded modes", ours[5].mode);

        ours[7].mode = kModeOff;
        profile[8].mode = kModeOff; // both changed since the last sync: the profile wins
        Check(SyncOriginalModes(ours.data(), profile.data(), shadow.data(), &valid, originals) == kModesFromProfile, "if both changed, the profile wins", 0);
        Check(ours[7].mode == kModeMenus && ours[8].mode == kModeOff, "ours follows the profile", ours[7].mode);
    }

    printf("settings file\n");
    {
        wchar_t tmp[MAX_PATH];
        GetTempPathW(MAX_PATH, tmp);
        std::wstring ini = std::wstring(tmp) + L"mb-songdata-test.ini";
        DeleteFileW(ini.c_str());
        const wchar_t* names[] = { L"Joota Japani_Kr$na.mp3", L"Maruti_Dhanda Nyoliwala, Miki Malang & Ron Likhari.mp3",
            L"\x0924\x0947\x0930\x093E_\x0915.mp3", L"Live [2019]_Band.mp3", L"a=b;c_d.mp3" };
        Check(LoadSongMode(ini, names[0]) == kModeAll, "a song never seen before is All", 0);
        bool saved = true;
        for (int i = 0; i < 5; ++i)
            saved = saved && SaveSongMode(ini, names[i], (unsigned char)(i % 4));
        Check(saved, "five songs saved", 0);
        bool back = true;
        for (int i = 0; i < 5; ++i)
            back = back && LoadSongMode(ini, names[i]) == i % 4;
        Check(back, "all five read back (symbols, Hindi, brackets, '=' and ';')", 0);
        SaveSongMode(ini, names[1], kModeRaces);
        Check(LoadSongMode(ini, names[1]) == kModeRaces && LoadSongMode(ini, names[0]) == kModeOff, "changing one leaves the others", 0);
        WritePrivateProfileStringW(L"Odd_Value.mp3", L"Mode", L"sometimes", ini.c_str());
        Check(LoadSongMode(ini, L"Odd_Value.mp3") == kModeAll, "an unreadable value is All", 0);

        // Optional names the user can type into the file to change what the game shows.
        Check(LoadSongText(ini, names[0], L"Artist") == L"", "no override: empty", 0);
        WritePrivateProfileStringW(SettingsSection(names[0]).c_str(), L"Artist", L"KR$NA", ini.c_str());
        WritePrivateProfileStringW(SettingsSection(names[0]).c_str(), L"Title", L"  Joota Japani (Remix)  ", ini.c_str());
        Check(LoadSongText(ini, names[0], L"Artist") == L"KR$NA", "an Artist override is read", 0);
        Check(LoadSongText(ini, names[0], L"Title") == L"Joota Japani (Remix)", "a Title override is read, trimmed", 0);
        Check(LoadSongMode(ini, names[0]) == kModeOff, "the mode beside it is still there", 0);
        Check(LoadSongText(ini, names[1], L"Title") == L"", "other songs have none", 0);
        DeleteFileW(ini.c_str());
    }

    printf("text for the game\n");
    {
        Check(GameText(L"Seedhe Maut", "x") == "Seedhe Maut", "plain text is kept", 0);
        Check(GameText(L"Miki Malang & Ron Likhari, R.D. Burman", "x") == "Miki Malang & Ron Likhari, R.D. Burman", "symbols the game draws are kept", 0);
        // Seen in the game (screenshots 11-15): a line with a single "$" is not drawn; "$$" is drawn as
        // one "$" ("Test A Kr$$" showed "Test A Kr$", "Kr$$na$" showed "Kr$na$").
        Check(GameText(L"Kr$na", "x") == "Kr$$na", "a dollar sign is doubled, which the game draws as one", 0);
        Check(GameText(L"Seedhe Maut ft. Kr$na", "x") == "Seedhe Maut ft. Kr$$na", "anywhere in the text", 0);
        Check(GameText(L"$$$", "x") == "$$$$$$", "each one is doubled", 0);
        Check(GameText(std::wstring(200, L'$'), "x").size() == 254, "doubling never overruns: cut at an even length", 0);
        // A name the user typed as an override is passed on as typed: in the game's text "$NAME$" stands
        // for an embedded picture, and someone who knows that may want to use it or work around it.
        Check(GameText(L"Kr$$x$na", "x", true) == "Kr$$x$na", "an override keeps its dollar signs", 0);
        Check(GameText(L"Dil \x0938\x0947", "x", true) == "Dil ??", "but still only letters the game has", 0);
        Check(GameText(L"Beyonc\x00E9", "x") == "Beyonc\xE9", "accented Latin letters are kept (Windows-1252)", 0);
        Check(GameText(L"\x0924\x0947\x0930\x093E", "Track 27") == "Track 27", "a name with no drawable letters uses the fallback", 0);
        Check(GameText(L"Dil \x0938\x0947", "x") == "Dil ??", "mixed: undrawable letters become ?", 0);
        Check(GameText(std::wstring(400, L'a'), "x").size() == 255, "very long text is cut, not overrun", 0);
    }

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
