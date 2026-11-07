// VisualBridge's pixel shaders (ps_2_0), compiled at start-up. One source, several entry points.
// s0, s1, s2 and c0, c1 mean different things per shader; each says what it expects.
#pragma once

static const char kShaderSource[] = R"hlsl(
sampler s0 : register(s0);
sampler s1 : register(s1);
sampler s2 : register(s2);
float4 c0 : register(c0);
float4 c1 : register(c1);
static const float3 kLuminance = float3(0.2125, 0.7154, 0.0721);

// Average of four taps placed diagonally around the pixel; with linear filtering each tap averages
// 2x2 texels, so one draw shrinks a picture to a quarter of its size. c0.xy = one source texel.
float4 Down4(float2 uv : TEXCOORD0) : COLOR
{
    return 0.25 * (tex2D(s0, uv + c0.xy * float2(-1, -1)) + tex2D(s0, uv + c0.xy * float2(1, -1))
                 + tex2D(s0, uv + c0.xy * float2(-1, 1)) + tex2D(s0, uv + c0.xy * float2(1, 1)));
}

// Logarithm of the luminance, averaged over a 3x3 grid of taps. The logarithm keeps a few very bright
// pixels from dominating the average. c0.xy = spacing of the taps.
float4 LogLum(float2 uv : TEXCOORD0) : COLOR
{
    float sum = 0;
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x)
            sum += log(dot(tex2D(s0, uv + c0.xy * float2(x, y)).rgb, kLuminance) + 0.0001);
    return float4(sum / 9, 0, 0, 1);
}

// The eye adapting. s0 = 1x1 average log luminance, s1 = last frame's adapted luminance.
// c0.x = seconds since the last frame, c0.y = speed when the scene gets brighter, c0.z = when it gets
// darker, c0.w = 1 on the first frame (no history: take the measured value).
float4 Adapt(float2 uv : TEXCOORD0) : COLOR
{
    float measured = exp(tex2D(s0, float2(0.5, 0.5)).r);
    float previous = tex2D(s1, float2(0.5, 0.5)).r;
    float speed = measured > previous ? c0.y : c0.z;
    float next = lerp(previous + (measured - previous) * (1 - exp(-c0.x * speed)), measured, c0.w);
    return float4(next, measured, 0, 1);
}

// Exposure on a picture that is already 8-bit and already has its whites at white cannot be a plain
// multiplication: that pushes everything bright over white (tried in the game on 2026-10-13: up to 27% of
// the picture clipped). Instead each colour goes through  out = 1 - (1 - colour)^e : black stays black,
// white stays white, e above 1 lifts the shadows and middle and squeezes the highlights together, e
// below 1 darkens. e is chosen so that the adapted luminance lands on middle grey.
// s1 = adapted luminance. c1.x = middle grey, c1.y = lowest and c1.z = highest e allowed, c1.w = 1 if on.
float Exposure()
{
    float adapted = clamp(tex2D(s1, float2(0.5, 0.5)).r, 0.001, 0.98);
    float e = clamp(log(1 - c1.x) / log(1 - adapted), c1.y, c1.z);
    return lerp(1, e, c1.w);
}

float3 Expose(float3 colour)
{
    return 1 - pow(saturate(1 - colour), Exposure());
}

// What is brighter than the threshold after exposure. s0 = quarter-size picture. c0.x = threshold.
float4 Bright(float2 uv : TEXCOORD0) : COLOR
{
    return float4(max(Expose(tex2D(s0, uv).rgb) - c0.x, 0), 1);
}

// One direction of a Gaussian blur, nine taps (the weights add up to 1). c0.xy = step between taps in that direction.
float4 Blur(float2 uv : TEXCOORD0) : COLOR
{
    static const float weight[5] = { 0.227027, 0.194595, 0.121622, 0.054054, 0.016216 };
    float4 sum = tex2D(s0, uv) * weight[0];
    for (int i = 1; i < 5; ++i)
        sum += (tex2D(s0, uv + c0.xy * i) + tex2D(s0, uv - c0.xy * i)) * weight[i];
    return sum;
}

// The result. s0 = the picture, s1 = adapted luminance, s2 = bloom. c0.x = bloom scale.
float4 Final(float2 uv : TEXCOORD0) : COLOR
{
    return float4(Expose(tex2D(s0, uv).rgb) + tex2D(s2, uv).rgb * c0.x, 1);
}
)hlsl";

// The passes that read the scene's depth: shader model 3 (vs_3_0 with ps_3_0, as Direct3D 9 requires), one source.
// Shared by all of them: s3 = the depth texture (INTZ, point-sampled; its red channel is the stored depth 0..1),
// c4 = (near, far, sky: stored depth at or above this is sky, relative bias), c5 = (tan of half the horizontal
// field of view, tan of half the vertical, one picture pixel across, one down). c0 to c3 are each pass's own.
static const char kShader3Source[] = R"hlsl(
sampler s0 : register(s0);
sampler s1 : register(s1);
sampler s3 : register(s3);
float4 c0 : register(c0);
float4 c1 : register(c1);
float4 c2 : register(c2);
float4 c4 : register(c4);
float4 c5 : register(c5);
// Wet reflections only: c6-c9 the main view's world-to-clip matrix (its rows: clip = p.x c6 + p.y c7 + p.z c8 + c9),
// c10-c13 its inverse (rows), c14 = (Strength, Steps, MaxDistance in metres, MinUp), c15 = (EdgeFade, relative
// thickness, thickness in metres, Blur in pixels), c16 = (the world's up direction, BlurSteps: the neighbour rays' steps), c17 = the camera's position in the world.
float4 c6 : register(c6);
float4 c7 : register(c7);
float4 c8 : register(c8);
float4 c9 : register(c9);
float4 c10 : register(c10);
float4 c11 : register(c11);
float4 c12 : register(c12);
float4 c13 : register(c13);
float4 c14 : register(c14);
float4 c15 : register(c15);
float4 c16 : register(c16);
float4 c17 : register(c17);
// i0.x = Steps: an integer constant, so that the compiler makes a real loop (unrolled, 64 steps took 6 s to compile).
int4 i0 : register(i0);
int4 i1 : register(i1);

// Our quads come in already in clip space; the vertex shader passes them on.
void Pass3VS(float4 position : POSITION, float2 uv : TEXCOORD0, out float4 outPosition : POSITION, out float2 outUv : TEXCOORD0)
{
    outPosition = position;
    outUv = uv;
}

float RawDepth(float2 uv)
{
    return tex2Dlod(s3, float4(uv, 0, 0)).r;
}

// The stored depth is not distance: with the usual projection it is f/(f-n) * (1 - n/z). This undoes it and
// gives the distance along the view, z, in metres.
float LinearFromRaw(float d)
{
    return c4.x * c4.y / (c4.y - d * (c4.y - c4.x));
}

float LinearDepth(float2 uv)
{
    return LinearFromRaw(RawDepth(uv));
}

// Where a pixel is in view space (x right, y up, z forward), from its place on screen and its distance.
float3 ViewPos(float2 uv, float z)
{
    return float3((uv.x * 2 - 1) * c5.x * z, (1 - uv.y * 2) * c5.y * z, z);
}

// The view-space position of the depth texel that covers uv: the place is taken from the texel's centre, the
// same texel the depth comes from. (Taking it from uv itself puts the point off its surface by up to half a
// texel's change in depth, and a flat floor then occludes itself: 6% darker in the stand-in at half size.)
float2 TexelCentre(float2 uv)
{
    return (floor(uv / c5.zw) + 0.5) * c5.zw;
}

float3 ViewPosAt(float2 uv)
{
    float2 centre = TexelCentre(uv);
    return ViewPos(centre, LinearDepth(centre));
}

// The depth view (the [Debug] ShowDepth switch): distance as grey, z / (z + 10), so 10 m is middle grey;
// sky is white.
float4 DepthView(float2 uv : TEXCOORD0) : COLOR
{
    // (This shader compiler takes no early return from inside an if: hence the one return at the end, here
    // and below.)
    float d = RawDepth(uv);
    float z = LinearFromRaw(d);
    return float4((d >= c4.z ? 1 : z / (z + 10)).xxx, 1);
}

// Ambient occlusion, after "Scalable Ambient Obscurance" (McGuire, Mara and Luebke, 2012): samples on a spiral
// around the pixel, at most Radius metres away in the scene; each one that lies above the surface (along its
// normal) and closer than Radius darkens it, weighted to fade out smoothly towards Radius. Samples farther than
// Radius count for nothing, so a near object never darkens the distance behind it (no halo), and the sky (no
// depth) is never darkened. Output: (visibility 1 = open .. 0 = closed in, distance z, 0, 1).
// c0 = (Radius, Radius squared, bias in metres, intensity / Radius^6 * 5 / samples), c1 = (scale from metres at
// 1 m to pixels of this target, largest radius in pixels, one pixel across of this target, one down),
// c2 = (distance where occlusion starts to fade out, where it is gone, 0, 0).
static const int kSamples = 12;
static const float kTurns = 7;
float4 AO(float2 uvIn : TEXCOORD0, float2 pixel : VPOS) : COLOR
{
    float2 uv = TexelCentre(uvIn);
    float d = RawDepth(uv);
    float z = LinearFromRaw(d);
    float3 P = ViewPos(uv, z);
    // The surface's direction from the neighbours one picture pixel away; of each pair the one nearer in
    // depth, so that a pixel on an object's edge takes its own surface, not the background's.
    float3 xa = ViewPosAt(uv + float2(c5.z, 0)), xb = ViewPosAt(uv - float2(c5.z, 0));
    float3 ya = ViewPosAt(uv + float2(0, c5.w)), yb = ViewPosAt(uv - float2(0, c5.w));
    float3 dx = abs(xa.z - z) < abs(xb.z - z) ? xa - P : P - xb;
    float3 dy = abs(ya.z - z) < abs(yb.z - z) ? ya - P : P - yb;
    float3 N = normalize(cross(dy, dx));
    if (dot(N, P) > 0)
        N = -N; // facing the camera
    float radius = min(c0.x * c1.x / z, c1.y);
    float turn = frac(sin(dot(pixel, float2(12.9898, 78.233))) * 43758.5453) * 6.2831853;
    float bias = c0.z + c4.w * z;
    float sum = 0;
    for (int i = 0; i < kSamples; ++i)
    {
        float along = (i + 0.5) / kSamples;
        float angle = along * kTurns * 6.2831853 + turn;
        float2 at = uv + float2(cos(angle), sin(angle)) * (along * radius) * c1.zw;
        float3 v = ViewPosAt(at) - P;
        float vv = dot(v, v);
        float f = max(c0.y - vv, 0);
        sum += f * f * f * max((dot(v, N) - bias) / (0.01 + vv), 0);
    }
    float visible = max(1 - sum * c0.w, 0);
    visible = lerp(visible, 1, saturate((z - c2.x) / (c2.y - c2.x)));
    // Sky: open, and a distance far from anything, so the blur never mixes it with the scene.
    return d >= c4.z ? float4(1, 60000, 0, 1) : float4(visible, z, 0, 1);
}

// One direction of a blur of the occlusion that does not cross edges: a tap counts less the more its distance
// differs from the centre's (relative), and not at all from 1/8 apart. s0 = occlusion (visibility, z).
// c0.xy = one occlusion pixel in the blur's direction.
float4 AOBlur(float2 uv : TEXCOORD0) : COLOR
{
    static const float weight[5] = { 0.2270270, 0.1945946, 0.1216216, 0.0540541, 0.0162162 };
    float4 centre = tex2Dlod(s0, float4(uv, 0, 0));
    float sum = centre.r * weight[0], total = weight[0];
    for (int i = 1; i < 5; ++i)
        for (int side = -1; side <= 1; side += 2)
        {
            float4 tap = tex2Dlod(s0, float4(uv + c0.xy * (i * side), 0, 0));
            float w = weight[i] * saturate(1 - 8 * abs(tap.g - centre.g) / centre.g);
            sum += tap.r * w;
            total += w;
        }
    return float4(sum / total, centre.g, 0, 1);
}

// The occlusion applied to the picture: colour times (1 - Strength * (1 - visibility)), never brighter, the sky
// exactly as it was. The occlusion is at a lower resolution; of its four nearest pixels each counts by how close
// it is on screen and how close its distance is to this pixel's, so dark does not bleed across edges.
// s0 = the picture, s1 = occlusion (visibility, z). c0 = (Strength, 0, one occlusion pixel across, one down).
float4 AOApply(float2 uv : TEXCOORD0) : COLOR
{
    float4 colour = tex2Dlod(s0, float4(uv, 0, 0));
    float d = RawDepth(uv);
    float z = LinearFromRaw(d);
    float2 first = (floor(uv / c0.zw - 0.5) + 0.5) * c0.zw;
    float sum = 0, total = 0;
    for (int j = 0; j < 2; ++j)
        for (int i = 0; i < 2; ++i)
        {
            float2 at = first + float2(i, j) * c0.zw;
            float4 tap = tex2Dlod(s1, float4(at, 0, 0));
            float2 near = saturate(1 - abs(uv - at) / c0.zw);
            float w = near.x * near.y / (0.001 + abs(tap.g - z) / z);
            sum += tap.r * w;
            total += w;
        }
    float visible = total > 0 && d < c4.z ? saturate(sum / total) : 1;
    return float4(colour.rgb * (1 - c0.x * (1 - visible)), colour.a);
}

// The same upsampling as AOApply, but only the darkening factor: drawn straight onto the game's picture with a
// multiplying blend (the picture times this), so that no copy of the picture is needed (the direct path).
float4 AOFactor(float2 uv : TEXCOORD0) : COLOR
{
    float d = RawDepth(uv);
    float z = LinearFromRaw(d);
    float2 first = (floor(uv / c0.zw - 0.5) + 0.5) * c0.zw;
    float sum = 0, total = 0;
    for (int j = 0; j < 2; ++j)
        for (int i = 0; i < 2; ++i)
        {
            float2 at = first + float2(i, j) * c0.zw;
            float4 tap = tex2Dlod(s1, float4(at, 0, 0));
            float2 near = saturate(1 - abs(uv - at) / c0.zw);
            float w = near.x * near.y / (0.001 + abs(tap.g - z) / z);
            sum += tap.r * w;
            total += w;
        }
    float visible = total > 0 && d < c4.z ? saturate(sum / total) : 1;
    float f = 1 - c0.x * (1 - visible);
    return float4(f, f, f, 1);
}

// Edge smoothing ([Parts] AA), drawn in place of the pack's pass-through: the treated picture (s0, linear filtering)
// onto the back buffer, colour and alpha. A luminance-edge filter after FXAA 3.11's "quality" path (Timothy Lottes,
// NVIDIA, 2011): where the brightness around a pixel varies by more than a threshold, find the edge's direction, walk
// along it both ways to its ends, and sample the picture shifted across the edge by how far the pixel is from the
// nearer end (long, shallow stair-steps become gradients); thin details get a smaller, sub-pixel blend. Flat areas
// are returned exactly as they are. c0 = (Strength: how much of the smoothed colour is used, sub-pixel amount,
// relative edge threshold, smallest edge threshold); c5.zw = one picture pixel.
float SmoothLuma(float2 uv)
{
    return dot(tex2Dlod(s0, float4(uv, 0, 0)).rgb, float3(0.299, 0.587, 0.114));
}

float4 SmoothColour(float2 uv)
{
    float2 px = c5.zw;
    float4 centre = tex2Dlod(s0, float4(uv, 0, 0));
    float lumaM = dot(centre.rgb, float3(0.299, 0.587, 0.114));
    float lumaS = SmoothLuma(uv + float2(0, px.y));
    float lumaE = SmoothLuma(uv + float2(px.x, 0));
    float lumaN = SmoothLuma(uv - float2(0, px.y));
    float lumaW = SmoothLuma(uv - float2(px.x, 0));
    float maxL = max(max(lumaN, lumaW), max(lumaE, max(lumaS, lumaM)));
    float minL = min(min(lumaN, lumaW), min(lumaE, min(lumaS, lumaM)));
    float range = maxL - minL;
    float4 result = centre;
    if (range >= max(c0.w, maxL * c0.z))
    {
        float lumaNW = SmoothLuma(uv + float2(-px.x, -px.y));
        float lumaSE = SmoothLuma(uv + float2(px.x, px.y));
        float lumaNE = SmoothLuma(uv + float2(px.x, -px.y));
        float lumaSW = SmoothLuma(uv + float2(-px.x, px.y));
        float lumaNS = lumaN + lumaS;
        float lumaWE = lumaW + lumaE;
        float edgeHorz = abs(-2 * lumaW + lumaNW + lumaSW) + 2 * abs(-2 * lumaM + lumaNS) + abs(-2 * lumaE + lumaNE + lumaSE);
        float edgeVert = abs(-2 * lumaS + lumaSW + lumaSE) + 2 * abs(-2 * lumaM + lumaWE) + abs(-2 * lumaN + lumaNW + lumaNE);
        bool horzSpan = edgeHorz >= edgeVert;
        // Sub-pixel: how much the centre stands out from the average of its 3x3 neighbourhood.
        float average = (2 * (lumaNS + lumaWE) + lumaNW + lumaSE + lumaNE + lumaSW) / 12;
        float subpix = saturate(abs(average - lumaM) / range);
        subpix = (-2 * subpix + 3) * subpix * subpix;
        subpix = subpix * subpix * c0.y;
        // Which side of the pixel the edge is on.
        float luma1 = horzSpan ? lumaN : lumaW;
        float luma2 = horzSpan ? lumaS : lumaE;
        float gradient1 = luma1 - lumaM, gradient2 = luma2 - lumaM;
        bool side1 = abs(gradient1) >= abs(gradient2);
        float gradientScaled = 0.25 * max(abs(gradient1), abs(gradient2));
        float stepLength = horzSpan ? px.y : px.x;
        float lumaLocal = 0.5 * ((side1 ? luma1 : luma2) + lumaM);
        if (side1)
            stepLength = -stepLength;
        float2 onEdge = uv;
        if (horzSpan)
            onEdge.y += stepLength * 0.5;
        else
            onEdge.x += stepLength * 0.5;
        // Walk along the edge both ways until the brightness on it changes: the edge's ends.
        float2 along = horzSpan ? float2(px.x, 0) : float2(0, px.y);
        float2 posN = onEdge - along, posP = onEdge + along;
        float endN = SmoothLuma(posN) - lumaLocal, endP = SmoothLuma(posP) - lumaLocal;
        bool doneN = abs(endN) >= gradientScaled, doneP = abs(endP) >= gradientScaled;
        static const float kSteps[10] = { 1.5, 2, 2, 2, 2, 4, 4, 8, 8, 12 };
        for (int i = 0; i < 10; ++i)
        {
            if (!doneN)
            {
                posN -= along * kSteps[i];
                endN = SmoothLuma(posN) - lumaLocal;
                doneN = abs(endN) >= gradientScaled;
            }
            if (!doneP)
            {
                posP += along * kSteps[i];
                endP = SmoothLuma(posP) - lumaLocal;
                doneP = abs(endP) >= gradientScaled;
            }
        }
        float distN = horzSpan ? uv.x - posN.x : uv.y - posN.y;
        float distP = horzSpan ? posP.x - uv.x : posP.y - uv.y;
        bool nearerN = distN < distP;
        float dist = min(distN, distP);
        // Only the end on the side where the stair-step turns towards this pixel shifts it.
        bool centreBelow = lumaM - lumaLocal < 0;
        bool goodSpan = ((nearerN ? endN : endP) < 0) != centreBelow;
        float offset = goodSpan ? 0.5 - dist / (distN + distP) : 0;
        offset = max(offset, subpix);
        float2 at = uv;
        if (horzSpan)
            at.y += offset * stepLength;
        else
            at.x += offset * stepLength;
        result.rgb = lerp(centre.rgb, tex2Dlod(s0, float4(at, 0, 0)).rgb, c0.x);
    }
    return result;
}

float4 Smooth(float2 uv : TEXCOORD0) : COLOR
{
    return SmoothColour(uv);
}

// Wet reflections ([Parts] Wet), in the same draw as the pass-through (after "Efficient GPU Screen-Space Ray Tracing",
// McGuire and Mara, 2014): each pixel's place in the world from its depth, its surface's direction from the
// neighbouring depths; on surfaces facing up (MinUp) the view ray is mirrored and followed in the world, in Steps
// steps up to MaxDistance metres, each step projected with the view's own matrix, until it passes behind what the
// depth says is there (then four halvings find the crossing; a crossing deeper than the thickness is a ray passing
// behind something, not a hit). The picture at the hit is mixed in at Strength, less towards the screen's edges
// (EdgeFade), with the distance travelled and as the surface leans away from flat. Rays that leave the screen, go
// behind the camera, reach only sky or hit nothing add nothing. Reflections only ever add light: a dark reflected
// thing never darkens the road.
float4 WorldToClip(float3 p)
{
    return p.x * c6 + p.y * c7 + p.z * c8 + c9;
}

// The world position on a pixel's view ray at view distance z (w is the distance along the view, zero at the camera,
// and changes evenly along a ray from the camera).
float3 WorldAt(float2 uv, float z)
{
    float4 h = (uv.x * 2 - 1) * c10 + (1 - uv.y * 2) * c11 + 0.5 * c12 + c13;
    float3 q = h.xyz / h.w;
    return c17.xyz + (q - c17.xyz) * (z / WorldToClip(q).w);
}

float3 WorldAtTexel(float2 uv)
{
    float2 centre = TexelCentre(uv);
    return WorldAt(centre, LinearDepth(centre));
}

float2 ClipToUv(float4 clip)
{
    return float2(0.5 + 0.5 * clip.x / clip.w, 0.5 - 0.5 * clip.y / clip.w);
}

// True when the point lies behind the scene's depth at its place on screen (sky counts as nothing to hit).
bool Behind(float3 q)
{
    float4 cq = WorldToClip(q);
    float raw = RawDepth(ClipToUv(cq));
    return raw < c4.z && cq.w > LinearFromRaw(raw);
}

// The surface's direction at a pixel, from the neighbouring depths (facing the camera).
float3 SurfaceNormal(float2 uv, float3 P)
{
    float3 xa = WorldAtTexel(uv + float2(c5.z, 0)), xb = WorldAtTexel(uv - float2(c5.z, 0));
    float3 ya = WorldAtTexel(uv + float2(0, c5.w)), yb = WorldAtTexel(uv - float2(0, c5.w));
    float3 dx = abs(dot(xa - P, xa - P)) < abs(dot(xb - P, xb - P)) ? xa - P : P - xb;
    float3 dy = abs(dot(ya - P, ya - P)) < abs(dot(yb - P, yb - P)) ? ya - P : P - yb;
    float3 N = normalize(cross(dy, dx));
    return dot(N, c17.xyz - P) < 0 ? -N : N;
}

// The light one pixel's mirrored ray adds (zero when it hits nothing). N: the surface's direction (worked out once at
// the centre pixel and shared by the blur's neighbour rays: on a flat road they are the same).
float3 WetLight(float2 uvIn, float3 base, float steps, float3 N)
{
    float3 result = 0;
    float2 uv = TexelCentre(uvIn);
    float d = RawDepth(uv);
    if (d < c4.z)
    {
        float z = LinearFromRaw(d);
        float3 P = WorldAt(uv, z);
        float up = dot(N, c16.xyz);
        if (up >= c14.w)
        {
            float3 R = reflect(normalize(P - c17.xyz), N);
            float stepLength = c14.z / steps;
            float before = 0, t = 0;
            bool crossed = false, done = false;
            for (int i = 0; i < i0.x; ++i)
            {
                if (!done && i < steps)
                {
                    t = stepLength * (i + 1);
                    float4 cq = WorldToClip(P + R * t);
                    float2 at = ClipToUv(cq);
                    if (cq.w <= c4.x || at.x < 0 || at.x > 1 || at.y < 0 || at.y > 1)
                        done = true; // behind the camera or off the screen: nothing
                    else if (Behind(P + R * t))
                    {
                        crossed = true;
                        done = true;
                    }
                    else
                        before = t;
                }
            }
            if (crossed)
            {
                float lo = before, hi = t;
                for (int k = 0; k < 4; ++k)
                {
                    float mid = 0.5 * (lo + hi);
                    if (Behind(P + R * mid))
                        hi = mid;
                    else
                        lo = mid;
                }
                float4 ch = WorldToClip(P + R * hi);
                float2 at = ClipToUv(ch);
                float zs = LinearFromRaw(RawDepth(at));
                if (ch.w - zs < c15.z + c15.y * zs)
                {
                    float edge = saturate(min(min(at.x, 1 - at.x), min(at.y, 1 - at.y)) / c15.x);
                    float w = c14.x * edge * saturate(1 - hi / c14.z) * saturate((up - c14.w) / max(1 - c14.w, 0.0001));
                    float3 seen = tex2Dlod(s0, float4(at, 0, 0)).rgb;
                    result = w * max(seen - base, 0);
                }
            }
        }
    }
    return result;
}

// Blur (c15.w, pixels; the user, 2026-10-29: the reflections "slightly blurry"): the light averaged with that of four
// neighbours Blur pixels away diagonally, each tracing its own ray, so both the reflected picture and its outline soften.
float3 WetMix(float2 uvIn, float3 base)
{
    // One loop over the rays (i1.x: 1 when sharp, 5 with Blur), so the ray march appears once in the compiled shader.
    // (The game's compiler allows no return inside an if.)
    float3 light = 0;
    float j = 0;
    float2 centre = TexelCentre(uvIn);
    float dc = RawDepth(centre);
    if (dc < c4.z) // the sky reflects nothing
    {
        float3 N = SurfaceNormal(centre, WorldAt(centre, LinearFromRaw(dc)));
        if (dot(N, c16.xyz) >= c14.w) // only surfaces facing up
        {
            float2 o = c15.w * c5.zw;
            for (int k = 0; k < i1.x; ++k)
            {
                float2 s = j < 0.5 ? float2(0, 0) : float2(fmod(j - 1, 2) * 2 - 1, floor((j - 1) / 2) * 2 - 1);
                // The four neighbour rays take c16.w steps (BlurSteps) over the same distance: coarser, cheaper.
                light += WetLight(uvIn + s * o, base, j < 0.5 ? c14.y : c16.w, N);
                j += 1;
            }
        }
    }
    return base + light / max(j, 1);
}

// The pass-through with reflections and no smoothing ([Parts] AA = 0): the treated picture as it is, colour and alpha.
float4 Wet(float2 uv : TEXCOORD0) : COLOR
{
    float4 colour = tex2Dlod(s0, float4(uv, 0, 0));
    colour.rgb = WetMix(uv, colour.rgb);
    return colour;
}

// Smoothing and reflections in the one draw.
float4 SmoothWet(float2 uv : TEXCOORD0) : COLOR
{
    float4 colour = SmoothColour(uv);
    colour.rgb = WetMix(uv, colour.rgb);
    return colour;
}

// Distance haze ([Parts] Haze), drawn straight onto the treated picture with alpha blending (the picture moves
// towards the colour by the alpha): nothing nearer than Start, Amount of the way at End and beyond, the sky (no
// depth) never. c0 = (Start, End, Amount, 0) in metres, c1 = the haze colour (0..1).
float4 Haze(float2 uv : TEXCOORD0) : COLOR
{
    float d = RawDepth(uv);
    float z = LinearFromRaw(d);
    float f = d >= c4.z ? 0 : c0.z * saturate((z - c0.x) / (c0.y - c0.x));
    return float4(c1.rgb, f);
}

// Light shafts ([Parts] Shafts), first pass, at a quarter of the picture's size: from each pixel, 32 steps along
// the line towards the sun's place on screen (Length of the way); a step counts when the depth there is sky and by
// how near it is to the sun (a glow that fades out at the glow radius), nearer steps more. Where walls, trees or
// bridges stand between the pixel and the sun's glow, steps hit them: those are the gaps between the rays. Depth
// only: no copy of the picture. c0 = (sun x, sun y, Length, picture width / height), c1 = (glow radius in picture
// heights, 0, 0, 0). Output: the ray brightness 0..1.
float4 ShaftsMask(float2 uv : TEXCOORD0) : COLOR
{
    float sum = 0, total = 0;
    for (int i = 0; i < 32; ++i)
    {
        float t = (i + 0.5) / 32 * c0.z;
        float2 p = lerp(uv, c0.xy, t);
        float w = 1 - 0.5 * t;
        float inside = (p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1) ? 1 : 0;
        float sky = RawDepth(p) >= c4.z ? 1 : 0;
        float glow = saturate(1 - length((p - c0.xy) * float2(c0.w, 1)) / c1.x);
        sum += inside * sky * glow * glow * w;
        total += w;
    }
    return float4((sum / total).xxx, 1);
}

// Second pass: the ray brightness (s1, quarter size, linear filtering) times the colour, added to the picture
// (blend one, one: never darker). c0 = colour times Strength times how far the sun is inside the screen.
float4 ShaftsApply(float2 uv : TEXCOORD0) : COLOR
{
    return float4(tex2Dlod(s1, float4(uv, 0, 0)).r * c0.rgb, 1);
}
)hlsl";
