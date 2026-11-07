// Chooses the next song, replacing the game's own picker (0x4F4CD0), which keeps one bit per song in
// a 28-bit number and so cannot handle more than 28 songs. No game addresses here: pure logic.
#pragma once
#include <vector>

// One record of the per-song mode array, in the game's layout (8 bytes). The array is in menu
// order; `number` is the song's index in the track list.
struct SavedMode
{
    int number;
    unsigned char mode;
    unsigned char pad[3];
};
enum { kModeOff = 0, kModeMenus = 1, kModeRaces = 2, kModeAll = 3 };
enum { kContextMenus = 0, kContextRaces = 1 };

inline bool ModeEnabledIn(unsigned char mode, int context)
{
    return mode == kModeAll || mode == context + 1;
}

inline int CountEnabled(const SavedMode* modes, int count, int context)
{
    int n = 0;
    for (int i = 0; i < count; ++i)
        n += ModeEnabledIn(modes[i].mode, context);
    return n;
}

class Picker
{
public:
    explicit Picker(unsigned seed = 1) : rng_(seed ? seed : 1) {}

    // Returns the song number to play next in this context, or -1 if none is enabled.
    // last: the song number played before (-1 = none).
    // Sequential: the next enabled song after `last` in menu order, wrapping round.
    // Random: every enabled song once before any repeats; a new round doesn't open with `last`.
    int Next(const SavedMode* modes, int count, int context, int last, bool random)
    {
        if (context != kContextMenus && context != kContextRaces || count <= 0)
            return -1;
        std::vector<int> enabled;
        for (int i = 0; i < count; ++i)
            if (ModeEnabledIn(modes[i].mode, context))
                enabled.push_back(modes[i].number);
        if (enabled.empty())
        {
            enabled_[context].clear();
            left_[context].clear();
            return -1;
        }

        if (!random)
        {
            int at = -1;
            for (int i = 0; i < count; ++i)
                if (modes[i].number == last)
                    at = i;
            for (int step = 1; step <= count; ++step)
            {
                const SavedMode& m = modes[(at + step) % count];
                if (ModeEnabledIn(m.mode, context))
                    return m.number;
            }
            return -1;
        }

        std::vector<int>& left = left_[context];
        if (enabled != enabled_[context]) // the set of enabled songs changed: start a new round
        {
            enabled_[context] = enabled;
            left = enabled;
        }
        bool newRound = left.empty();
        if (newRound)
            left = enabled;
        size_t pick = Random((unsigned)left.size());
        if (newRound && left.size() > 1 && left[pick] == last)
            pick = (pick + 1) % left.size(); // every song stays in the round; it just doesn't go first
        int number = left[pick];
        left.erase(left.begin() + pick);
        return number;
    }

private:
    unsigned Random(unsigned below) // xorshift32
    {
        rng_ ^= rng_ << 13;
        rng_ ^= rng_ >> 17;
        rng_ ^= rng_ << 5;
        return rng_ % below;
    }

    std::vector<int> left_[2], enabled_[2];
    unsigned rng_;
};
