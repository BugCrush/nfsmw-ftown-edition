// Known-answer test of the sun's screen position (visual/src/sun.h), no Direct3D needed.
//     python visual/tests/run-sun-test.py   (or build this with zig c++ and run it)
// Cameras are built as the game keeps them (decompilation Camera.cpp, SetCameraMatrix; PC layout checked in
// speed.exe: GetSunPos at 0x4FD4F0): a world-to-camera matrix for row vectors (camera = world * M), camera x to the
// right, y down the screen, z forward; rows v0..v2 hold the rotation, row v3 the translation.
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "../src/sun.h"

static int g_failures;

static void Expect(bool ok, const char* what)
{
    if (!ok)
    {
        ++g_failures;
        printf("FAIL %s\n", what);
    }
}

// A camera at `pos` with the given right, down and forward directions (world space, unit length).
static void Camera(float m[16], const float r[3], const float d[3], const float f[3], const float pos[3])
{
    for (int i = 0; i < 3; ++i)
    {
        m[i * 4 + 0] = r[i];
        m[i * 4 + 1] = d[i];
        m[i * 4 + 2] = f[i];
        m[i * 4 + 3] = 0;
    }
    m[12] = -(pos[0] * r[0] + pos[1] * r[1] + pos[2] * r[2]);
    m[13] = -(pos[0] * d[0] + pos[1] * d[1] + pos[2] * d[2]);
    m[14] = -(pos[0] * f[0] + pos[1] * f[1] + pos[2] * f[2]);
    m[15] = 1;
}

// out = a * b (4x4, row-major, row vectors: p * a * b).
static void Multiply(float out[16], const float a[16], const float b[16])
{
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c)
        {
            float s = 0;
            for (int k = 0; k < 4; ++k)
                s += a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = s;
        }
}

static bool Near(float a, float b, float tolerance = 1e-4f)
{
    return fabsf(a - b) <= tolerance;
}

int main()
{
    const float kPi = 3.14159265f;
    const float tanY = tanf(31 * kPi / 180), tanX = tanY * 16 / 9;
    // A camera looking north (world +y) from somewhere on the map, level: right = east (+x), down = -z.
    const float right[3] = { 1, 0, 0 }, down[3] = { 0, 0, -1 }, north[3] = { 0, 1, 0 }, pos[3] = { 1234, -567, 8 };
    float m[16];
    Camera(m, right, down, north, pos);
    float x = -1, y = -1, facing = -1;
    char text[160];

    // The sun straight ahead lands at the centre.
    const float ahead[3] = { 0, 1, 0 };
    Expect(SunScreen(m, ahead, tanX, tanY, &x, &y, &facing) && Near(x, 0.5f) && Near(y, 0.5f) && Near(facing, 1),
           "sun straight ahead is at the centre, facing 1");

    // Behind the camera: false.
    const float behind[3] = { 0, -1, 0 };
    Expect(!SunScreen(m, behind, tanX, tanY, &x, &y, &facing), "sun behind the camera: not on screen");
    // Exactly to the side (90 degrees): false, not a division by zero.
    const float side[3] = { 1, 0, 0 };
    Expect(!SunScreen(m, side, tanX, tanY, &x, &y, &facing), "sun at 90 degrees: not on screen");

    // 10 degrees up: above the centre (y below 0.5) by tan(10)/tanY of the half height.
    const float a = 10 * kPi / 180;
    const float up10[3] = { 0, cosf(a), sinf(a) };
    bool ok = SunScreen(m, up10, tanX, tanY, &x, &y, &facing);
    snprintf(text, sizeof(text), "10 degrees up: x 0.5, y %.4f, facing %.4f; got %d %.4f %.4f %.4f", 0.5f - 0.5f * tanf(a) / tanY, cosf(a), ok, x, y, facing);
    Expect(ok && Near(x, 0.5f) && Near(y, 0.5f - 0.5f * tanf(a) / tanY) && Near(facing, cosf(a)), text);

    // 20 degrees to the right (east of north): right of the centre.
    const float b = 20 * kPi / 180;
    const float right20[3] = { sinf(b), cosf(b), 0 };
    ok = SunScreen(m, right20, tanX, tanY, &x, &y, &facing);
    snprintf(text, sizeof(text), "20 degrees right: x %.4f, y 0.5; got %d %.4f %.4f", 0.5f + 0.5f * tanf(b) / tanX, ok, x, y);
    Expect(ok && Near(x, 0.5f + 0.5f * tanf(b) / tanX) && Near(y, 0.5f), text);

    // Far off to the side but in front (60 degrees right, wider than the view): true, with x beyond 1, so the
    // effect can fade it out by its distance from the screen.
    const float c = 60 * kPi / 180;
    const float right60[3] = { sinf(c), cosf(c), 0 };
    ok = SunScreen(m, right60, tanX, tanY, &x, &y, &facing);
    Expect(ok && x > 1, "60 degrees right: in front of the camera, off the right edge (x > 1)");

    // The sun direction need not be unit length (SunInfo's position is a far point, not a direction).
    const float farAhead[3] = { 0, 5000, 0 };
    Expect(SunScreen(m, farAhead, tanX, tanY, &x, &y, &facing) && Near(x, 0.5f) && Near(y, 0.5f), "a far point straight ahead is at the centre");

    // The camera's position does not move a direction (translation is ignored).
    float moved[16];
    const float elsewhere[3] = { -90000, 4000, 300 };
    Camera(moved, right, down, north, elsewhere);
    Expect(SunScreen(moved, up10, tanX, tanY, &x, &y, &facing) && Near(y, 0.5f - 0.5f * tanf(a) / tanY), "camera position does not matter");

    // The decompilation's default camera (Camera::Camera): looking straight down from 1200 m. A sun overhead is
    // behind it.
    const float defaults[16] = { 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 100, 0, 0, 1200, 1 };
    const float overhead[3] = { 0.2f, 0.1f, 0.97f };
    Expect(!SunScreen(defaults, overhead, tanX, tanY, &x, &y, &facing), "default camera looks down: sun overhead is behind it");

    // Nonsense in, false out: no sun, a broken matrix.
    const float none[3] = { 0, 0, 0 };
    Expect(!SunScreen(m, none, tanX, tanY, &x, &y, &facing), "a zero sun vector: false");
    float broken[16];
    memcpy(broken, m, sizeof(broken));
    broken[5] = NAN;
    Expect(!SunScreen(broken, ahead, tanX, tanY, &x, &y, &facing), "a matrix with NaN: false");
    float zero[16] = {};
    Expect(!SunScreen(zero, ahead, tanX, tanY, &x, &y, &facing), "an all-zero matrix: false");
    float scaled[16];
    memcpy(scaled, m, sizeof(scaled));
    for (int i = 0; i < 12; ++i)
        scaled[i] *= 3; // not a rotation
    Expect(!SunScreen(scaled, ahead, tanX, tanY, &x, &y, &facing), "a matrix that is not a rotation: false");

    // --- The game's own world-to-clip matrix (eViewPlatInfo + 0x80 on the PC: camera matrix times projection,
    // built by 0x6CF400 every frame; docs/visual-notes.md, "The sun's place from the game's own matrix").
    // The projection as speed.exe builds it there: x scaled by sx, y by -sy (camera y is down, clip y up),
    // w = camera z.
    const float sx = 1 / tanX, sy = 1 / tanY;
    float projection[16] = { sx, 0, 0, 0, 0, -sy, 0, 0, 0, 0, 1.0001f, 1, 0, 0, -0.5f, 0 };
    float clip[16];
    Multiply(clip, m, projection);
    Expect(ClipMatrixPlausible(clip), "camera times projection is a plausible view matrix");
    // Every direction lands where SunScreen with the same field of view puts it.
    const float* const dirs[] = { ahead, up10, right20, farAhead, right60 };
    for (const float* dir : dirs)
    {
        float x1 = -1, y1 = -1, f1 = -1, x2 = -2, y2 = -2, f2 = -2;
        bool a1 = SunScreen(m, dir, tanX, tanY, &x1, &y1, &f1), a2 = SunScreenClip(clip, dir, &x2, &y2, &f2);
        snprintf(text, sizeof(text), "game matrix agrees with the camera and tangents for (%g, %g, %g): %d %.4f %.4f %.4f / %d %.4f %.4f %.4f",
                 dir[0], dir[1], dir[2], a1, x1, y1, f1, a2, x2, y2, f2);
        Expect(a1 && a2 && Near(x1, x2) && Near(y1, y2) && Near(f1, f2), text);
    }
    Expect(!SunScreenClip(clip, behind, &x, &y, &facing), "game matrix: sun behind the camera, not on screen");
    Expect(!SunScreenClip(clip, side, &x, &y, &facing), "game matrix: sun at 90 degrees, not on screen");
    Expect(!SunScreenClip(clip, none, &x, &y, &facing), "game matrix: a zero sun vector, false");
    // A wider view (the game widens it as the car speeds up): the same sun lands nearer the centre.
    float wide[16], wideProjection[16];
    memcpy(wideProjection, projection, sizeof(wideProjection));
    wideProjection[0] = sx * 0.7f;
    wideProjection[5] = -sy * 0.7f;
    Multiply(wide, m, wideProjection);
    ok = SunScreenClip(wide, up10, &x, &y, &facing);
    snprintf(text, sizeof(text), "wider view: 10 degrees up at y %.4f; got %d %.4f", 0.5f - 0.5f * 0.7f * tanf(a) / tanY, ok, y);
    Expect(ok && Near(x, 0.5f) && Near(y, 0.5f - 0.5f * 0.7f * tanf(a) / tanY), text);
    float fovX = 0, fovY = 0;
    ClipFov(wide, &fovX, &fovY);
    snprintf(text, sizeof(text), "wider view's field of view %.2f x %.2f degrees, got %.2f x %.2f",
             2 * atanf(tanX / 0.7f) * 180 / kPi, 2 * atanf(tanY / 0.7f) * 180 / kPi, fovX, fovY);
    Expect(Near(fovX, 2 * atanf(tanX / 0.7f) * 180 / kPi, 0.01f) && Near(fovY, 2 * atanf(tanY / 0.7f) * 180 / kPi, 0.01f), text);
    // ClipNearFar: the camera's near and far planes back from a world-to-clip matrix (Direct3D's z: 0 at near, w at
    // far). Known answers: 0.5 / 1000 and 2 / 50 with the camera above (translated: the camera's position must not
    // matter); the test projection's own 1.0001 / -0.5 (near 0.49995, far 5000.5); and refusals.
    {
        const float planes[2][2] = { { 0.5f, 1000 }, { 2, 50 } };
        for (const auto& p : planes)
        {
            float pr[16];
            memcpy(pr, projection, sizeof(pr));
            pr[10] = p[1] / (p[1] - p[0]);
            pr[14] = -p[0] * p[1] / (p[1] - p[0]);
            float c[16], cm[16], n = 0, f = 0;
            Multiply(c, m, pr);
            bool got = ClipNearFar(c, &n, &f);
            snprintf(text, sizeof(text), "near/far %g/%g from the clip matrix, got %d %g/%g", p[0], p[1], got, n, f);
            Expect(got && Near(n, p[0], p[0] * 1e-3f) && Near(f, p[1], p[1] * 1e-3f), text);
            Multiply(cm, moved, pr);
            got = ClipNearFar(cm, &n, &f);
            snprintf(text, sizeof(text), "near/far %g/%g with the camera elsewhere, got %d %g/%g", p[0], p[1], got, n, f);
            Expect(got && Near(n, p[0], p[0] * 1e-3f) && Near(f, p[1], p[1] * 2e-3f), text);
        }
        float n = 0, f = 0;
        bool got = ClipNearFar(clip, &n, &f);
        snprintf(text, sizeof(text), "the test projection (1.0001, -0.5): near 0.49995 far 5000.5, got %d %g/%g", got, n, f);
        Expect(got && Near(n, 0.49995f, 1e-4f) && Near(f, 5000.5f, 5.0f), text);
        float flat[16] = {};
        Expect(!ClipNearFar(flat, &n, &f), "an all-zero matrix gives no near/far");
        float noDepth[16];
        memcpy(noDepth, clip, sizeof(noDepth));
        for (int i = 0; i < 4; ++i)
            noDepth[i * 4 + 2] = noDepth[i * 4 + 3]; // z = w: an infinitely far far plane (or no depth range)
        Expect(!ClipNearFar(noDepth, &n, &f), "z equal to w (no finite far plane) gives no near/far");
        float nanDepth[16];
        memcpy(nanDepth, clip, sizeof(nanDepth));
        nanDepth[14] = NAN;
        Expect(!ClipNearFar(nanDepth, &n, &f), "NaN in the depth row gives no near/far");
    }
    // Not a view matrix (memory not yet written, freed, or another object): rejected, so the caller falls back.
    float clipZero[16] = {};
    Expect(!ClipMatrixPlausible(clipZero), "an all-zero clip matrix is not plausible");
    float clipNan[16];
    memcpy(clipNan, clip, sizeof(clipNan));
    clipNan[4] = NAN;
    Expect(!ClipMatrixPlausible(clipNan), "a clip matrix with NaN is not plausible");
    float clipScaledW[16];
    memcpy(clipScaledW, clip, sizeof(clipScaledW));
    for (int i = 0; i < 3; ++i)
        clipScaledW[i * 4 + 3] *= 2; // w no longer the camera's distance along a unit forward direction
    Expect(!ClipMatrixPlausible(clipScaledW), "a clip matrix whose w column is not a unit direction is not plausible");
    float clipIdentity[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };
    Expect(!ClipMatrixPlausible(clipIdentity), "the identity (no perspective: w does not follow the depth) is not plausible");
    float clipSkew[16];
    memcpy(clipSkew, clip, sizeof(clipSkew));
    clipSkew[0] += 0.5f * clipSkew[3]; // right no longer at right angles to forward
    clipSkew[4] += 0.5f * clipSkew[7];
    clipSkew[8] += 0.5f * clipSkew[11];
    Expect(!ClipMatrixPlausible(clipSkew), "a clip matrix whose right is not at right angles to forward is not plausible");
    float clipFlat[16];
    memcpy(clipFlat, clip, sizeof(clipFlat));
    for (int i = 0; i < 3; ++i)
        clipFlat[i * 4 + 0] *= 0.01f; // 179 degrees across: not a view
    Expect(!ClipMatrixPlausible(clipFlat), "a field of view of nearly 180 degrees is not plausible");

    // Invert4 (wet reflections: depth back to world positions). Identity; a perspective world-to-clip matrix (the
    // camera above, `clip` from the tests above), inverse times matrix within 1e-5 of the identity both ways; a
    // singular matrix and a NaN entry: false.
    {
        float id[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 }, out[16];
        bool ok = Invert4(id, out);
        bool same = ok;
        for (int i = 0; i < 16; ++i)
            same = same && Near(out[i], id[i], 1e-6f);
        Expect(same, "Invert4: the identity's inverse is the identity");
        // A perspective world-to-clip matrix for a camera a few metres from the origin (1e-5), and `clip` above, whose
        // camera stands thousands of metres out on the map: there the float product inverse x matrix carries float
        // rounding of the translation (about 2e-4), so it is held to 1e-3; the inverse is worked out in double.
        float nearCam[16], nearClip[16];
        const float r0[3] = { 0.8f, 0.6f, 0 }, d0[3] = { 0, 0, -1 }, f0[3] = { -0.6f, 0.8f, 0 }, p0[3] = { 3, 4, 1.5f };
        Camera(nearCam, r0, d0, f0, p0);
        Multiply(nearClip, nearCam, projection);
        const float* const mats[2] = { nearClip, clip };
        const float limits[2] = { 1e-5f, 1e-3f };
        for (int k = 0; k < 2; ++k)
        {
            float inv[16], a[16], b[16];
            ok = Invert4(mats[k], inv);
            snprintf(text, sizeof(text), "Invert4: a perspective world-to-clip matrix (%s camera) has an inverse", k ? "far" : "near");
            Expect(ok, text);
            Multiply(a, inv, mats[k]);
            Multiply(b, mats[k], inv);
            float worst = 0;
            for (int i = 0; i < 16; ++i)
            {
                worst = fmaxf(worst, fabsf(a[i] - id[i]));
                worst = fmaxf(worst, fabsf(b[i] - id[i]));
            }
            snprintf(text, sizeof(text), "Invert4: inverse times matrix (%s camera) is the identity within %g, worst %.2g",
                     k ? "far" : "near", limits[k], worst);
            Expect(ok && worst < limits[k], text);
        }
        float singular[16] = { 1, 2, 3, 4, 2, 4, 6, 8, 0, 1, 0, 0, 0, 0, 1, 0 };
        Expect(!Invert4(singular, out), "Invert4: a singular matrix (two rows in proportion) gives false");
        float zero[16] = {};
        Expect(!Invert4(zero, out), "Invert4: the all-zero matrix gives false");
        float withNan[16];
        memcpy(withNan, clip, sizeof(withNan));
        withNan[6] = NAN;
        Expect(!Invert4(withNan, out), "Invert4: a NaN entry gives false");
    }

    printf("sun-test: %s (%d failed)\n", g_failures ? "FAIL" : "PASS", g_failures);
    return g_failures ? 1 : 0;
}
