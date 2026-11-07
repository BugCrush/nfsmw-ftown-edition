// Tests music/src/Picker.h.
// Build (from music\tests): zig c++ -target x86-windows-gnu -w picker-test.cpp -o picker-test.exe
// Run: picker-test.exe      (exit code 0 = all passed)
#include "../src/Picker.h"
#include <stdio.h>
#include <set>

static int failures;
static void Check(bool ok, const char* what, int got)
{
    printf("  %s %s (%d)\n", ok ? "ok  " : "FAIL", what, got);
    if (!ok)
        ++failures;
}

static std::vector<SavedMode> Modes(int count, unsigned char mode)
{
    std::vector<SavedMode> m(count);
    for (int i = 0; i < count; ++i)
    {
        m[i].number = i;
        m[i].mode = mode;
    }
    return m;
}

int main()
{
    printf("sequential\n");
    {
        std::vector<SavedMode> m = Modes(33, kModeAll); // 26 originals + 7 custom: more than 28
        Picker p;
        int last = -1;
        bool inOrder = true;
        for (int i = 0; i < 33; ++i)
        {
            last = p.Next(m.data(), 33, kContextMenus, last, false);
            inOrder = inOrder && last == i;
        }
        Check(inOrder, "33 songs play in list order, including numbers 28-32", last);
        Check(p.Next(m.data(), 33, kContextMenus, 32, false) == 0, "after the last one it wraps to the first", 0);
    }
    {
        std::vector<SavedMode> m = Modes(6, kModeOff);
        m[1].mode = kModeMenus;
        m[3].mode = kModeRaces;
        m[4].mode = kModeAll;
        Picker p;
        Check(p.Next(m.data(), 6, kContextMenus, -1, false) == 1, "menus: first enabled is 1", 0);
        Check(p.Next(m.data(), 6, kContextMenus, 1, false) == 4, "menus: skips off and races-only songs", 0);
        Check(p.Next(m.data(), 6, kContextMenus, 4, false) == 1, "menus: wraps", 0);
        Check(p.Next(m.data(), 6, kContextRaces, -1, false) == 3, "races: first enabled is 3", 0);
        Check(p.Next(m.data(), 6, kContextRaces, 3, false) == 4, "races: then 4", 0);
        Check(p.Next(m.data(), 6, kContextMenus, 2, false) == 4, "continues after a song that is now off", 0);
    }
    {
        std::vector<SavedMode> m = Modes(4, kModeAll);
        m[0].number = 2; m[1].number = 0; m[2].number = 3; m[3].number = 1; // menu order differs from numbers
        Picker p;
        Check(p.Next(m.data(), 4, kContextMenus, -1, false) == 2, "order follows the array, not the numbers", 0);
        Check(p.Next(m.data(), 4, kContextMenus, 2, false) == 0, "second in array order", 0);
        Check(p.Next(m.data(), 4, kContextMenus, 1, false) == 2, "wraps from the last position", 0);
    }
    {
        std::vector<SavedMode> m = Modes(5, kModeOff);
        Picker p;
        Check(p.Next(m.data(), 5, kContextMenus, -1, false) == -1, "nothing enabled gives -1", 0);
        Check(p.Next(m.data(), 5, kContextRaces, 2, true) == -1, "nothing enabled gives -1 (random)", 0);
        Check(p.Next(m.data(), 5, 2, -1, false) == -1, "an unknown context gives -1", 0);
        Check(p.Next(m.data(), 0, kContextMenus, -1, false) == -1, "an empty list gives -1", 0);
    }

    printf("random\n");
    {
        std::vector<SavedMode> m = Modes(40, kModeAll);
        Picker p(12345);
        std::set<int> round1, round2;
        int last = -1, lastOfRound1 = -1, firstOfRound2 = -1;
        for (int i = 0; i < 40; ++i)
        {
            last = p.Next(m.data(), 40, kContextRaces, last, true);
            round1.insert(last);
        }
        lastOfRound1 = last;
        for (int i = 0; i < 40; ++i)
        {
            last = p.Next(m.data(), 40, kContextRaces, last, true);
            if (i == 0)
                firstOfRound2 = last;
            round2.insert(last);
        }
        Check(round1.size() == 40, "40 songs: each plays once in the first round", (int)round1.size());
        Check(round2.size() == 40, "and once in the second round", (int)round2.size());
        Check(firstOfRound2 != lastOfRound1, "a new round doesn't open with the song just played", firstOfRound2);
        bool shuffled = false;
        Picker q(12345);
        last = -1;
        for (int i = 0; i < 40; ++i)
        {
            last = q.Next(m.data(), 40, kContextRaces, last, true);
            shuffled = shuffled || last != i;
        }
        Check(shuffled, "the order is not simply 0,1,2,...", 0);
    }
    {
        std::vector<SavedMode> m = Modes(10, kModeAll);
        Picker p(7);
        int last = -1;
        std::set<int> menus, races;
        for (int i = 0; i < 5; ++i)
            menus.insert(last = p.Next(m.data(), 10, kContextMenus, last, true));
        last = -1;
        for (int i = 0; i < 10; ++i)
            races.insert(last = p.Next(m.data(), 10, kContextRaces, last, true));
        Check(races.size() == 10, "menu picks don't use up the races round", (int)races.size());
        for (int i = 0; i < 5; ++i)
            menus.insert(last = p.Next(m.data(), 10, kContextMenus, last, true));
        Check(menus.size() == 10, "the menus round carries on where it stopped", (int)menus.size());
    }
    {
        std::vector<SavedMode> m = Modes(10, kModeAll);
        Picker p(99);
        int last = -1;
        for (int i = 0; i < 4; ++i)
            last = p.Next(m.data(), 10, kContextMenus, last, true);
        for (int i = 0; i < 7; ++i)
            m[i].mode = kModeOff; // the user switches songs off: only 7, 8, 9 remain
        std::set<int> seen;
        for (int i = 0; i < 3; ++i)
            seen.insert(last = p.Next(m.data(), 10, kContextMenus, last, true));
        Check(seen.size() == 3 && *seen.begin() == 7, "after a mode change only enabled songs play, each once", (int)seen.size());
    }
    {
        std::vector<SavedMode> m = Modes(5, kModeOff);
        m[2].mode = kModeAll;
        Picker p(3);
        bool same = true;
        for (int i = 0; i < 5; ++i)
            same = same && p.Next(m.data(), 5, kContextMenus, 2, true) == 2;
        Check(same, "a single enabled song repeats", 0);
    }

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
