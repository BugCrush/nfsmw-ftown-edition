// visual/src/sun.h from the command line, for visual/tests/sun-frames-test.py (the game's own frames).
//     sun-cli clip   <16 floats: world-to-clip matrix, row-major> <dx dy dz>
//     sun-cli camera <16 floats: world-to-camera matrix, row-major> <dx dy dz> <tanX> <tanY>
// Prints "on x y facing plausible" or "off - - - plausible" (plausible: ClipMatrixPlausible for "clip", 1 for "camera").
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/sun.h"

int main(int argc, char** argv)
{
    bool clip = argc >= 21 && !strcmp(argv[1], "clip");
    bool camera = argc >= 23 && !strcmp(argv[1], "camera");
    if (!clip && !camera)
    {
        fprintf(stderr, "usage: sun-cli clip <16> <3> | sun-cli camera <16> <3> <tanX> <tanY>\n");
        return 2;
    }
    float m[16], d[3];
    for (int i = 0; i < 16; ++i)
        m[i] = (float)atof(argv[2 + i]);
    for (int i = 0; i < 3; ++i)
        d[i] = (float)atof(argv[18 + i]);
    float x = 0, y = 0, facing = 0;
    bool on, plausible = true;
    if (clip)
    {
        plausible = ClipMatrixPlausible(m);
        on = SunScreenClip(m, d, &x, &y, &facing);
    }
    else
        on = SunScreen(m, d, (float)atof(argv[21]), (float)atof(argv[22]), &x, &y, &facing);
    if (on)
        printf("on %.6f %.6f %.6f %d\n", x, y, facing, plausible ? 1 : 0);
    else
        printf("off - - - %d\n", plausible ? 1 : 0);
    return 0;
}
