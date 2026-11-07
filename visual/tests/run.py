"""Builds VisualBridge and its stand-in and runs one variant under DXVK with GfxProbe as the camera.

    python visual/tests/run.py <variant>

Variants: none (no VisualBridge.asi at all), off, identity, split-identity, broken, exposure,
split-exposure, bloom. The folder is visual/tests/out/<variant>/ (git-ignored); its path is printed last.
--native: Windows' own Direct3D instead of DXVK (no d3d9.dll copied); the folder is <variant>-native/.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
GAME = os.path.join(ROOT, "Need For Speed Most Wanted Black Edition")

PROBE_INI = """[Capture]
Dir = .
Label = test
[Log]
ReportSeconds = 4
[Parts]
Filtering = 0
FrameMap = 1
Effects = 0
EffectValues = 0
Resources = 0
Shaders = 0
Timing = 0
Shots = 1
Dissect = 0
Watch = 0
Panel = 0
[Shots]
Interval = 1
Max = 40
"""

BASE = {"Enabled": 1, "Exposure": 0, "Bloom": 0, "SplitScreen": 0, "Identity": 0, "FinalShader": "Final", "AO": 0,
        "ShowDepth": 0, "Strength": 0.6, "Radius": 1.0, "HalfResolution": 1, "ToggleSeconds": 0,
        "ToggleOnly": "all", "AA": 0, "AAStrength": 0.75, "Haze": 0, "Shafts": 0, "ShowSun": 0, "FovY": 60, "DepthNear": 0.5, "DepthFar": 1000, "FromGame": 0,
        "AOShowcase": 0, "Blinks": 5, "FailFullSizeAO": 0,
        "ShadowUnlock": 0, "Wet": 0, "WetStrength": 0.25, "WetSteps": 16, "WetMaxDistance": 40, "WetMinUp": 0.9, "WetEdgeFade": 0.1, "UpAxis": "y", "WetBlur": 0, "WetBlurSteps": 8}
VARIANTS = {
    "off": {"Enabled": 0},
    "identity": {"Identity": 1},
    "split-identity": {"Identity": 1, "SplitScreen": 1},
    "broken": {"Identity": 1, "FinalShader": "NoSuchShader"},
    "exposure": {"Exposure": 1},
    "split-exposure": {"Exposure": 1, "SplitScreen": 1},
    "bloom": {"Bloom": 1},
    "both": {"Exposure": 1, "Bloom": 1},
    # The stand-in's "hostile" mode: A8R8G8B8, 4x multisampling, unusual device state around the pass.
    "hostile-off": {"Enabled": 0},
    "hostile-identity": {"Identity": 1},
    "hostile-split": {"Exposure": 1, "Bloom": 1, "SplitScreen": 1},
    # The stand-in's "gap" mode: no pass from 4.5 s to 7.2 s, across the brightness step.
    "gap-exposure": {"Exposure": 1},
    # The stand-in's "scene" mode, shaped like the game with the Xbox 360 pack: a depth pre-pass into an INTZ
    # depth texture, the scene (floor, wall, sky) on the back buffer, then an effect created from memory (so
    # its name is unknown) whose "visualtreatment" technique draws a marker on the back buffer, then the HUD.
    "scene-off": {"Enabled": 0},
    "scene-identity": {"Identity": 1},
    "scene-depth": {"ShowDepth": 1},
    "scene-ao": {"AO": 1},
    "scene-ao-full": {"AO": 1, "HalfResolution": 0},
    "scene-split-ao": {"AO": 1, "SplitScreen": 1},
    # [Test] ToggleSeconds: the effects switch off and on every N seconds, to measure their cost inside one race.
    "scene-toggle": {"AO": 1, "ToggleSeconds": 2},
    # [Test] AOShowcase: occlusion blinks (ToggleSeconds) and steps through three sharpness levels, Blinks blinks each.
    "scene-ao-showcase": {"AO": 1, "ToggleSeconds": 1, "ToggleOnly": "ao", "AOShowcase": 1, "Blinks": 1},
    # The showcase switched on without ToggleSeconds: it does nothing, and the log says so.
    "scene-ao-showcase-notoggle": {"AO": 1, "AOShowcase": 1},
    # [Test] FailFullSizeAO: the full-size occlusion targets are not made (as if out of memory), levels 2 and 3 fail.
    "scene-ao-showcase-fullfail": {"AO": 1, "ToggleSeconds": 1, "ToggleOnly": "ao", "AOShowcase": 1, "Blinks": 1, "FailFullSizeAO": 1},
    # "reload": the stand-in switches [Test] AOShowcase off at 4.5 s and on again at 10.2 s.
    "scene-reload-ao-showcase": {"AO": 1, "ToggleSeconds": 1, "ToggleOnly": "ao", "AOShowcase": 1, "Blinks": 1},
    # A ToggleSeconds typo: clamped to 3600. 536870912 * 1000 wraps to 0 in 32 bits (a division by zero unclamped).
    "scene-toggle-huge": {"AO": 1, "ToggleSeconds": 999999999},
    "scene-toggle-wrap": {"AO": 1, "ToggleSeconds": 536870912, "ToggleOnly": "ao", "AOShowcase": 1},
    # [Test] ToggleOnly: only the named effect switches; the others stay as set.
    "scene-toggle-only": {"AO": 1, "ToggleSeconds": 2, "ToggleOnly": "ao"},
    # "bench": 1920x1080, ~2,800 draws a frame, no frame cap; not in suite.py (a measurement, not a check):
    # python visual/tests/run.py scene-bench-toggle, then compare BENCH frames in the on and off seconds.
    "scene-bench-toggle": {"AO": 1, "ToggleSeconds": 3},
    "scene-bench-identity-toggle": {"Identity": 1, "ToggleSeconds": 3},
    # "nointz": the stand-in makes no depth texture; the effects that need depth must skip themselves.
    "scene-nointz-off": {"Enabled": 0},
    "scene-nointz-ao": {"AO": 1, "ShowDepth": 1},
    # "hostile" on top: unusual device state around the treatment effect, read back after it.
    "scene-hostile-off": {"Enabled": 0},
    "scene-hostile-ao": {"AO": 1},
    # "intz2": a second, smaller INTZ depth texture bound before the real one each frame.
    "scene-intz2-ao": {"AO": 1},
    # Edge smoothing in place of the pack's pass-through ([Parts] AA). "nopass": the stand-in copies the treated
    # picture to the screen without the pass-through technique (nothing to replace).
    "scene-aa": {"AA": 1},
    "scene-split-aa": {"AA": 1, "SplitScreen": 1},
    "scene-nopass-off": {"Enabled": 0},
    "scene-aa-nopass": {"AA": 1},
    "scene-hostile-aa": {"AA": 1},
    "scene-ao-aa": {"AO": 1, "AA": 1},
    "scene-toggle-only-aa": {"AO": 1, "AA": 1, "ToggleSeconds": 2, "ToggleOnly": "ao"},
    # Bench (not in the suite): smoothing switched every 3 s, with occlusion on (as it would be installed), and alone.
    "scene-bench-ao-aa-toggle": {"AO": 1, "AA": 1, "ToggleSeconds": 3, "ToggleOnly": "aa"},
    "scene-bench-aa-toggle": {"AA": 1, "ToggleSeconds": 3, "ToggleOnly": "aa"},
    # Distance haze ([Parts] Haze; in the stand-in Start 4 m, End 10 m, Amount 0.5, Colour red).
    "scene-haze": {"Haze": 1},
    "scene-split-haze": {"Haze": 1, "SplitScreen": 1},
    "scene-ao-haze": {"AO": 1, "Haze": 1},
    "scene-nointz-haze": {"Haze": 1},
    "scene-hostile-haze": {"Haze": 1},
    "scene-toggle-only-haze": {"AO": 1, "Haze": 1, "ToggleSeconds": 2, "ToggleOnly": "haze"},
    # Light shafts ([Parts] Shafts). "sun": the stand-in gives its camera and a sun direction ([Sun] addresses);
    # "sunbehind": the sun behind the camera; "sunside": in front, far off the right edge.
    "scene-sun-off": {"Enabled": 0},
    "scene-sun-shafts": {"Shafts": 1},
    "scene-sun-split-shafts": {"Shafts": 1, "SplitScreen": 1},
    "scene-sunbehind-shafts": {"Shafts": 1},
    # "noinfo": the sun ahead, but the game's SunInfo pointer is 0 (no sun entry for this track or time of day):
    # the direction left in memory is stale, so no rays.
    "scene-sun-noinfo-shafts": {"Shafts": 1},
    "scene-sunside-shafts": {"Shafts": 1},
    "scene-sun-showsun": {"ShowSun": 1},
    # "sunleft": the sun left of the centre; in split screen its marker must still show (on the game's half).
    "scene-sunleft-split-showsun": {"ShowSun": 1, "SplitScreen": 1},
    # The sun's place from the view's own matrix (the stand-in's eViewPlatInfo + 0x80), as the game widens its view:
    # "wrongfov": [Depth] FovY says 40 while the stand-in's view is 60; the marker must still sit on the sun.
    # "noplat": no platform info (pointer 0); "badplat": an all-zero matrix: both fall back to FovY (60, right here).
    "scene-sun-wrongfov-showsun": {"ShowSun": 1, "FovY": 40},
    "scene-sun-noplat-showsun": {"ShowSun": 1},
    "scene-sun-badplat-showsun": {"ShowSun": 1},
    # Ambient occlusion from the view's own field of view: "fov60" with [Depth] FovY right (60) is the reference;
    # "wrongfov" says 40, so the occlusion must still come out the same (it reads the view's matrix); "badplat"
    # (all-zero matrix) with FovY 60 falls back to FovY and matches the reference too.
    "scene-sun-ao-fov60": {"AO": 1, "HalfResolution": 0, "Radius": 0.35},
    "scene-sun-ao-wrongfov": {"AO": 1, "HalfResolution": 0, "Radius": 0.35, "FovY": 40},
    # The shadow-level unlock ([Shadows] Unlock): "shadows" gives a stand-in game function that sets the menu's highest
    # shadow level to 0 and two call sites; "shadowswrong" names the wrong function, so nothing may be patched.
    "scene-shadows-unlock": {"ShadowUnlock": 1},
    "scene-shadows-off": {"ShadowUnlock": 0},
    "scene-shadowswrong-unlock": {"ShadowUnlock": 1},
    # "shadowsro": the maximum's address is read-only: nothing written there, no crash, logged.
    "scene-shadowsro-unlock": {"ShadowUnlock": 1},
    # Depth planes from the view's own matrix ([Depth] FromGame; the review of 2026-10-30): the stand-in's view is
    # 0.5 / 1000 m. "wrongnear": [Depth] says 2 / 50, FromGame = 1, so the picture must be fov60's; "-off": the same
    # wrong values used (FromGame = 0), so it must differ (the test can tell); "badplat": no matrix, FromGame = 1 and
    # the right values: falls back to [Depth] and says so.
    "scene-sun-ao-wrongnear": {"AO": 1, "HalfResolution": 0, "Radius": 0.35, "DepthNear": 2, "DepthFar": 50, "FromGame": 1},
    "scene-sun-ao-wrongnear-off": {"AO": 1, "HalfResolution": 0, "Radius": 0.35, "DepthNear": 2, "DepthFar": 50},
    "scene-sun-badplat-ao-fromgame": {"AO": 1, "HalfResolution": 0, "Radius": 0.35, "FromGame": 1},
    "scene-sun-badplat-ao": {"AO": 1, "HalfResolution": 0, "Radius": 0.35},
    "scene-sun-hostile-off": {"Enabled": 0},
    "scene-sun-hostile-shafts": {"Shafts": 1},
    # Wet reflections ([Parts] Wet), mode "wet": a bright box on the floor 5 m ahead and a low flat-topped box (the
    # stand-in's world has y up, so [Wet] UpAxis = y here); the view's matrix as in "sun". References: the plugin
    # disabled, and edge smoothing alone.
    "scene-wet-disabled": {"Enabled": 0},
    "scene-wet-aaonly": {"AA": 1},
    "scene-wet": {"AA": 1, "Wet": 1},
    "scene-wet-noaa": {"Wet": 1},
    # Frozen reference for sharp reflections (Blur 0; the review of 2026-10-30, item 8), not in the suite: run
    # "scene-wet-c333b1a" with --asi <VisualBridge.asi built from commit c333b1a, the first wet reflections>, then
    # "scene-wet-frozen" (the current source, scene-wet's settings) must give the same pictures.
    "scene-wet-c333b1a": {"AA": 1, "Wet": 1},
    "scene-wet-frozen": {"AA": 1, "Wet": 1},
    # Wet switched off and on every 3 s (ToggleOnly = wet): the SUN line must follow (wet=off(toggle) in the off stretches).
    "scene-wet-toggle": {"AA": 1, "Wet": 1, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    # [Wet] Blur: the reflection softened (the user, 2026-10-29: "slightly blurry"), against scene-wet's sharp one.
    "scene-wet-blur": {"AA": 1, "Wet": 1, "WetBlur": 4},
    "scene-wet-off": {},
    "scene-wet-badmatrix": {"AA": 1, "Wet": 1},
    "scene-wet-edge-ref": {"Enabled": 0},
    "scene-wet-edge": {"Wet": 1},
    "scene-split-wet": {"AA": 1, "Wet": 1, "SplitScreen": 1},
    "scene-hostile-wet": {"AA": 1, "Wet": 1},
    # Bench (not in the suite): wet switched every 3 s with edge smoothing on, at 8, 16 and 24 steps.
    "scene-bench-wet-toggle-s8": {"AA": 1, "Wet": 1, "WetSteps": 8, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    "scene-bench-wet-toggle-s16": {"AA": 1, "Wet": 1, "WetSteps": 16, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    # The blur's cost (the game's settings: Blur 5), neighbour rays at 16 steps (as first installed) against 8.
    "scene-bench-wet-toggle-blur-bs16": {"AA": 1, "Wet": 1, "WetBlur": 5, "WetBlurSteps": 16, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    "scene-bench-wet-toggle-blur-bs8": {"AA": 1, "Wet": 1, "WetBlur": 5, "WetBlurSteps": 8, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    "scene-bench-wet-toggle-s24": {"AA": 1, "Wet": 1, "WetSteps": 24, "ToggleSeconds": 3, "ToggleOnly": "wet"},
    "scene-bench-haze-toggle": {"AO": 1, "Haze": 1, "ToggleSeconds": 3, "ToggleOnly": "haze"},
    "scene-bench-sun-shafts-toggle": {"AO": 1, "Shafts": 1, "ToggleSeconds": 3, "ToggleOnly": "shafts"},
}
# Words in a variant's name that are passed to the stand-in as its mode.
MODES = ("hostile", "gap", "scene", "nointz", "bench", "intz2", "nopass", "sun", "sunbehind", "sunside", "sunleft", "noinfo",
         "noplat", "badplat", "reload", "wet", "edge", "badmatrix", "shadows", "shadowswrong", "shadowsro")


def look_ini(v):
    s = dict(BASE, **v)
    return ("[Look]\nEnabled = %(Enabled)d\n[Parts]\nExposure = %(Exposure)d\nBloom = %(Bloom)d\nAO = %(AO)d\nAA = %(AA)d\nHaze = %(Haze)d\nShafts = %(Shafts)d\nWet = %(Wet)d\n"
            "[Exposure]\nMiddleGrey = 0.40\nSpeedUp = 3.0\nSpeedDown = 1.0\nMin = 0.5\nMax = 2.0\n"
            "[Bloom]\nThreshold = 0.8\nScale = 0.6\nWidth = 1.5\n"
            "[Test]\nSplitScreen = %(SplitScreen)d\nIdentity = %(Identity)d\nFinalShader = %(FinalShader)s\n"
            "ToggleSeconds = %(ToggleSeconds)d\nToggleOnly = %(ToggleOnly)s\nAOShowcase = %(AOShowcase)d\nFailFullSizeAO = %(FailFullSizeAO)d\n"
            "[AOShowcase]\nBlinks = %(Blinks)d\nHalf1 = 1\nRadius1 = 1.0\nHalf2 = 0\nRadius2 = 0.6\nHalf3 = 0\nRadius3 = 0.35\n"
            "[Game]\nAfter = IDI_TESTA_FX\nBefore = IDI_TESTB_FX\nFinal = visualtreatment\n"
            "[AO]\nStrength = %(Strength)s\nRadius = %(Radius)s\nHalfResolution = %(HalfResolution)d\n"
            "[Depth]\nNear = %(DepthNear)s\nFar = %(DepthFar)s\nFovY = %(FovY)s\nFromGame = %(FromGame)d\n"
            "[AA]\nStrength = %(AAStrength)s\n"
            "[Haze]\nStart = 4\nEnd = 10\nAmount = 0.5\nColour = 255,0,0\n"
            "[Shafts]\nStrength = 0.35\nLength = 0.6\nColour = 255,240,210\n"
            "[Wet]\nStrength = %(WetStrength)s\nSteps = %(WetSteps)d\nMaxDistance = %(WetMaxDistance)s\nMinUp = %(WetMinUp)s\n"
            "EdgeFade = %(WetEdgeFade)s\nUpAxis = %(UpAxis)s\nBlur = %(WetBlur)s\nBlurSteps = %(WetBlurSteps)s\n"
            "[Shadows]\nUnlock = %(ShadowUnlock)d\nLevel = 2\n"
            "[Debug]\nShowDepth = %(ShowDepth)d\nShowSun = %(ShowSun)d\n") % s


def main():
    variant = sys.argv[1]
    native = "--native" in sys.argv
    out = os.path.join(HERE, "out", variant + ("-native" if native else ""))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    res = os.path.join(out, "look.res")
    subprocess.check_call([ZIG, "rc", "look.rc", res], cwd=HERE)
    exe = os.path.join(out, "look-standin.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O2", "look-standin.cpp", res, "-ld3d9", "-ld3dx9_26",
                           "-luser32", "-o", exe, "-w"], cwd=HERE)
    shutil.copy(os.path.join(ROOT, "gfx", "src", "GfxProbe.asi"), out)
    if not native:
        shutil.copy(os.path.join(GAME, "d3d9.dll"), out)
    with open(os.path.join(out, "GfxProbe.ini"), "wb") as f:
        # --fullprobe: every part of GfxProbe on (frame map, effects, timing, dissection, panel), to check the
        # two plugins side by side as they run in the game.
        probe = PROBE_INI.replace("= 0", "= 1") if "--fullprobe" in sys.argv else PROBE_INI
        f.write(probe.replace("\n", "\r\n").encode("ascii"))
    if variant != "none":
        if "--asi" in sys.argv:
            # Another build (e.g. an older commit's, for a frozen reference) instead of building the current source.
            shutil.copy(sys.argv[sys.argv.index("--asi") + 1], os.path.join(out, "VisualBridge.asi"))
        else:
            subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "visual", "src", "build.bat"), ZIG])
            shutil.copy(os.path.join(ROOT, "visual", "src", "VisualBridge.asi"), out)
        with open(os.path.join(out, "VisualBridge.ini"), "wb") as f:
            f.write(look_ini(VARIANTS[variant]).replace("\n", "\r\n").encode("ascii"))
    mode = [word for word in variant.split("-") if word in MODES]
    result = subprocess.run([exe] + mode, cwd=out, timeout=120, capture_output=True, text=True)
    with open(os.path.join(out, "stdout.txt"), "w") as f:
        f.write(result.stdout)
    print(result.stdout)
    print(out)
    sys.exit(result.returncode)


main()
