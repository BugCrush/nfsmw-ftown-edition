// Where the sun is on screen (graphics part 2, light shafts). Plain maths, no Direct3D: tested by
// visual/tests/sun-test.cpp.
//
// The game keeps each camera's world-to-camera matrix for row vectors (camera = world * M; decompilation
// Camera::SetCameraMatrix): rows v0..v2 are the rotation, v3 the translation; in camera space x is to the right,
// y down the screen and z forward (its default camera, looking straight down, has v1 = (0, -1, 0)). The sun is a
// direction (SunInfo's position is a far point relative to the camera; WorldLightDirectionVector is it normalised).
#pragma once
#include <math.h>

// The sun's place on screen, x and y from 0 to 1 (0, 0 = top left; outside 0..1 = off screen but in front), and
// `facing`, the cosine of the angle between the view's direction and the sun (1 = straight ahead). False when the
// sun is behind the camera or within 10 degrees of its side (no rays then), or when the inputs are not a camera and
// a direction (a NaN, a zero vector, a matrix that is not a rotation: memory read at the wrong moment).
inline bool SunScreen(const float m[16], const float toSun[3], float tanX, float tanY, float* x, float* y, float* facing)
{
    float length = sqrtf(toSun[0] * toSun[0] + toSun[1] * toSun[1] + toSun[2] * toSun[2]);
    if (!(length > 1e-6f) || !(tanX > 0) || !(tanY > 0))
        return false;
    float c[3];
    for (int j = 0; j < 3; ++j)
    {
        // Each column of the rotation must be a unit vector (to within 2%), or this is not a camera.
        float column = m[j] * m[j] + m[4 + j] * m[4 + j] + m[8 + j] * m[8 + j];
        if (!(column > 0.96f && column < 1.04f))
            return false;
        c[j] = (toSun[0] * m[j] + toSun[1] * m[4 + j] + toSun[2] * m[8 + j]) / length;
    }
    // cos 80 degrees: nearer the side than that, the projection runs off to infinity and means nothing.
    if (!(c[2] > 0.1736f))
        return false;
    *x = 0.5f + 0.5f * c[0] / (c[2] * tanX);
    *y = 0.5f + 0.5f * c[1] / (c[2] * tanY);
    *facing = c[2];
    return true;
}

// The game's own world-to-clip matrix for a view (speed.exe v1.3: eViewPlatInfo + 0x80, the camera matrix times the
// projection, rebuilt every frame by 0x6CF400 with the field of view the game is using right then; row vectors:
// clip = (p, 1) * M, M[r][c] at m[r * 4 + c]). Its columns 0, 1 and 3 are, for a direction, the clip x (right),
// y (up) and w (distance along the view's forward direction). Column j's direction part is m[j], m[4 + j], m[8 + j].
inline float ClipColumnDot(const float m[16], int j, const float d[3])
{
    return d[0] * m[j] + d[1] * m[4 + j] + d[2] * m[8 + j];
}

// True when the matrix looks like a view's world-to-clip matrix: finite; the w column's direction a unit vector (to
// within 2%: the camera's forward direction); a field of view between 10 and 170 degrees each way; right, up and
// forward at right angles (to within about 3 degrees). Anything else (memory not written yet, or not a view) is not
// used: the caller falls back to the camera and [Depth] FovY.
inline bool ClipMatrixPlausible(const float m[16])
{
    for (int i = 0; i < 16; ++i)
        if (!(m[i] == m[i]) || !(fabsf(m[i]) < 1e30f))
            return false;
    const float* col[3];
    float c0[3] = { m[0], m[4], m[8] }, c1[3] = { m[1], m[5], m[9] }, c3[3] = { m[3], m[7], m[11] };
    col[0] = c0, col[1] = c1, col[2] = c3;
    float n[3];
    for (int k = 0; k < 3; ++k)
        n[k] = sqrtf(col[k][0] * col[k][0] + col[k][1] * col[k][1] + col[k][2] * col[k][2]);
    if (!(n[2] > 0.98f && n[2] < 1.02f))
        return false;
    // Half-angle tangents |forward| / |right| and |forward| / |up| between tan 5 and tan 85 degrees.
    for (int k = 0; k < 2; ++k)
        if (!(n[k] > 0.0875f * n[2] && n[k] < 11.43f * n[2]))
            return false;
    for (int a = 0; a < 3; ++a)
        for (int b = a + 1; b < 3; ++b)
        {
            float dot = col[a][0] * col[b][0] + col[a][1] * col[b][1] + col[a][2] * col[b][2];
            if (!(fabsf(dot) < 0.05f * n[a] * n[b]))
                return false;
        }
    return true;
}

// The view's field of view in degrees across and up/down, from the game's matrix.
inline void ClipFov(const float m[16], float* across, float* upDown)
{
    float n0 = sqrtf(m[0] * m[0] + m[4] * m[4] + m[8] * m[8]), n1 = sqrtf(m[1] * m[1] + m[5] * m[5] + m[9] * m[9]);
    float n3 = sqrtf(m[3] * m[3] + m[7] * m[7] + m[11] * m[11]);
    *across = n0 > 0 ? 2 * atanf(n3 / n0) * 57.2957795f : 0;
    *upDown = n1 > 0 ? 2 * atanf(n3 / n1) * 57.2957795f : 0;
}

// The camera's near and far planes from a world-to-clip matrix (row vectors; Direct3D's depth: clip z = A w + B in
// the camera's terms, 0 at near, w at far, so A = far / (far - near), B = -near A). A comes from the depth column
// against the w column (the camera's forward), B from what is left of the depth column's constant; the camera's
// position cancels. False for anything that is not a finite near/far pair (no matrix yet, an infinite far plane).
inline bool ClipNearFar(const float m[16], float* nearOut, float* farOut)
{
    float ww = m[3] * m[3] + m[7] * m[7] + m[11] * m[11];
    if (!(ww > 1e-12f))
        return false;
    float a = (m[2] * m[3] + m[6] * m[7] + m[10] * m[11]) / ww;
    float b = m[14] - a * m[15];
    if (!(a > 1.0f + 1e-7f) || !(b < 0) || !(a < 1e6f) || !(b > -1e9f))
        return false;
    float n = -b / a, f = a * n / (a - 1);
    if (!(n > 0) || !(f > n) || !(f < 1e9f))
        return false;
    *nearOut = n;
    *farOut = f;
    return true;
}

// The inverse of a 4x4 matrix (row-major, m[r * 4 + c]), by cofactors. False, and `out` not to be used, when an entry
// or the result is not a finite number or the determinant is near zero against the size of the entries (the matrix
// is singular: memory not yet written, or not a view). Used to turn the main view's world-to-clip matrix back from
// screen and depth into world positions (wet reflections).
inline bool Invert4(const float m[16], float out[16])
{
    double a[16], inv[16];
    for (int i = 0; i < 16; ++i)
    {
        if (!(m[i] == m[i]) || !(fabsf(m[i]) < 1e30f))
            return false;
        a[i] = m[i];
    }
    inv[0] = a[5] * a[10] * a[15] - a[5] * a[11] * a[14] - a[9] * a[6] * a[15] + a[9] * a[7] * a[14] + a[13] * a[6] * a[11] - a[13] * a[7] * a[10];
    inv[4] = -a[4] * a[10] * a[15] + a[4] * a[11] * a[14] + a[8] * a[6] * a[15] - a[8] * a[7] * a[14] - a[12] * a[6] * a[11] + a[12] * a[7] * a[10];
    inv[8] = a[4] * a[9] * a[15] - a[4] * a[11] * a[13] - a[8] * a[5] * a[15] + a[8] * a[7] * a[13] + a[12] * a[5] * a[11] - a[12] * a[7] * a[9];
    inv[12] = -a[4] * a[9] * a[14] + a[4] * a[10] * a[13] + a[8] * a[5] * a[14] - a[8] * a[6] * a[13] - a[12] * a[5] * a[10] + a[12] * a[6] * a[9];
    inv[1] = -a[1] * a[10] * a[15] + a[1] * a[11] * a[14] + a[9] * a[2] * a[15] - a[9] * a[3] * a[14] - a[13] * a[2] * a[11] + a[13] * a[3] * a[10];
    inv[5] = a[0] * a[10] * a[15] - a[0] * a[11] * a[14] - a[8] * a[2] * a[15] + a[8] * a[3] * a[14] + a[12] * a[2] * a[11] - a[12] * a[3] * a[10];
    inv[9] = -a[0] * a[9] * a[15] + a[0] * a[11] * a[13] + a[8] * a[1] * a[15] - a[8] * a[3] * a[13] - a[12] * a[1] * a[11] + a[12] * a[3] * a[9];
    inv[13] = a[0] * a[9] * a[14] - a[0] * a[10] * a[13] - a[8] * a[1] * a[14] + a[8] * a[2] * a[13] + a[12] * a[1] * a[10] - a[12] * a[2] * a[9];
    inv[2] = a[1] * a[6] * a[15] - a[1] * a[7] * a[14] - a[5] * a[2] * a[15] + a[5] * a[3] * a[14] + a[13] * a[2] * a[7] - a[13] * a[3] * a[6];
    inv[6] = -a[0] * a[6] * a[15] + a[0] * a[7] * a[14] + a[4] * a[2] * a[15] - a[4] * a[3] * a[14] - a[12] * a[2] * a[7] + a[12] * a[3] * a[6];
    inv[10] = a[0] * a[5] * a[15] - a[0] * a[7] * a[13] - a[4] * a[1] * a[15] + a[4] * a[3] * a[13] + a[12] * a[1] * a[7] - a[12] * a[3] * a[5];
    inv[14] = -a[0] * a[5] * a[14] + a[0] * a[6] * a[13] + a[4] * a[1] * a[14] - a[4] * a[2] * a[13] - a[12] * a[1] * a[6] + a[12] * a[2] * a[5];
    inv[3] = -a[1] * a[6] * a[11] + a[1] * a[7] * a[10] + a[5] * a[2] * a[11] - a[5] * a[3] * a[10] - a[9] * a[2] * a[7] + a[9] * a[3] * a[6];
    inv[7] = a[0] * a[6] * a[11] - a[0] * a[7] * a[10] - a[4] * a[2] * a[11] + a[4] * a[3] * a[10] + a[8] * a[2] * a[7] - a[8] * a[3] * a[6];
    inv[11] = -a[0] * a[5] * a[11] + a[0] * a[7] * a[9] + a[4] * a[1] * a[11] - a[4] * a[3] * a[9] - a[8] * a[1] * a[7] + a[8] * a[3] * a[5];
    inv[15] = a[0] * a[5] * a[10] - a[0] * a[6] * a[9] - a[4] * a[1] * a[10] + a[4] * a[2] * a[9] + a[8] * a[1] * a[6] - a[8] * a[2] * a[5];
    double det = a[0] * inv[0] + a[1] * inv[4] + a[2] * inv[8] + a[3] * inv[12];
    if (!(det != 0) || !(fabs(det) < 1e300))
        return false;
    for (int i = 0; i < 16; ++i)
    {
        inv[i] /= det;
        if (!(inv[i] == inv[i]) || !(fabs(inv[i]) < 1e30))
            return false;
    }
    // Near-singular: the result must really invert the matrix (a scale-free test: the entries of a view matrix range
    // from about 1 to the camera's position on the map, thousands of metres, so no fixed determinant threshold fits).
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c)
        {
            double s = 0;
            for (int k = 0; k < 4; ++k)
                s += inv[r * 4 + k] * a[k * 4 + c];
            if (!(fabs(s - (r == c ? 1.0 : 0.0)) < 1e-6))
                return false;
        }
    for (int i = 0; i < 16; ++i)
        out[i] = (float)inv[i];
    return true;
}

// As SunScreen, from the game's world-to-clip matrix: no field of view assumed, so it follows the game's widening
// of the view at speed. False when the matrix is not plausible, the sun is behind the camera or within 10 degrees
// of its side, or the direction is zero or not a number.
inline bool SunScreenClip(const float m[16], const float toSun[3], float* x, float* y, float* facing)
{
    float length = sqrtf(toSun[0] * toSun[0] + toSun[1] * toSun[1] + toSun[2] * toSun[2]);
    if (!(length > 1e-6f) || !ClipMatrixPlausible(m))
        return false;
    float cx = ClipColumnDot(m, 0, toSun), cy = ClipColumnDot(m, 1, toSun), cw = ClipColumnDot(m, 3, toSun);
    float forward = sqrtf(m[3] * m[3] + m[7] * m[7] + m[11] * m[11]);
    float f = cw / (length * forward);
    if (!(f > 0.1736f))
        return false;
    *x = 0.5f + 0.5f * cx / cw;
    *y = 0.5f - 0.5f * cy / cw;
    *facing = f;
    return true;
}
