"""Checks a VisualBridge stand-in run from GfxProbe's screenshots and VisualBridge.log.

    python visual/tests/check-look.py <variant> [--native]

The stand-in's picture: background grey 64 (160 from 6 s), a white patch at (472..488, 232..248), a
grey-128 "HUD" triangle drawn after the pass. Screenshots are taken once a second from 1.5 s.
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import gfxlog

LEFT, RIGHT, HUD, PATCH = (100, 100), (400, 100), (560, 410), (480, 240)
failures = []
# "-native" when the run was on Windows' own Direct3D (run.py --native): reference runs have the same suffix.
SUFFIX = "-native" if "--native" in sys.argv else ""


def expect(ok, what):
    if not ok:
        failures.append(what if len(what) <= 400 else what[:400] + " ...")


def shots(out):
    lines = gfxlog.parse(os.path.join(out, "GfxProbe.log"))
    found = []
    for t, tag, f in lines:
        if tag == "SHOT" and os.path.isfile(f.get("path", "")):
            found.append((float(f["t"]), Image.open(f["path"]).convert("RGB")))
    return found


def grey_at(image, at):
    return image.getpixel(at)[0]


def background(t):
    # Shot time is the probe's driving time. It starts 0.5 s into the run and can fall behind by a few
    # tenths (a stalled frame counts as at most 0.25 s), so the step at 6 s of the run lands between shot
    # times 5 and 6; those two shots are skipped by the checks.
    return 160 if t >= 6 else 64


def check_untouched(out, images, log):
    """The picture is exactly the stand-in's own in every screenshot."""
    for t, image in images:
        if 4.9 < t < 6.1:
            continue  # the step change falls inside this second
        bg = background(t)
        for name, at in (("left", LEFT), ("right", RIGHT)):
            expect(image.getpixel(at) == (bg, bg, bg), "t=%.0f %s background is %d, got %s" % (t, name, bg, image.getpixel(at)))
        expect(image.getpixel(PATCH) == (255, 255, 255), "t=%.0f the patch is white, got %s" % (t, image.getpixel(PATCH)))
        expect(image.getpixel(HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(HUD)))
        expect(image.getpixel((530, 430)) == (bg, bg, bg), "t=%.0f next to the HUD triangle is background (it is where it should be)" % t)


def passes(log):
    total = 0
    for line in log.splitlines():
        if " LOOK " in line:
            fields = dict(kv.split("=") for kv in line.split(" LOOK ")[1].split())
            total += int(fields["passes"])
    return total


def whole_picture_same(images, what, allow_line=False, against="none"):
    """Every screenshot equals the one from the reference run (no plugin, or plugin off), over the whole picture."""
    from PIL import ImageChops
    reference = dict((round(t), image) for t, image in shots(os.path.join(HERE, "out", against + SUFFIX)))
    expect(len(reference) >= 10, "the '%s' run exists to compare with (run it first)" % against)
    for t, image in images:
        if 4.9 < t < 6.1 or round(t) not in reference:
            continue
        box = ImageChops.difference(image, reference[round(t)]).getbbox()
        if allow_line and box and box[0] >= 318 and box[2] <= 322:
            box = None
        expect(box is None, "t=%.0f %s: differs from the plugin-less picture in %s" % (t, what, box))


def stand_in_output(out):
    path = os.path.join(out, "stdout.txt")
    return open(path).read() if os.path.isfile(path) else ""


def state_report(out):
    """Which pieces of state the stand-in found changed after its effect, without the per-frame repeats and
    without addresses (they differ from run to run)."""
    import re
    return sorted({re.sub(r" is 0x.*", "", l) for l in stand_in_output(out).splitlines() if l.startswith("STATE mismatch:")})


def check_hostile_identity(out, images, log):
    """Unusual device state around the pass, a multisampled A8R8G8B8 back buffer: nothing may leak either way."""
    text = stand_in_output(out)
    expect(state_report(out) == state_report(os.path.join(HERE, "out", "hostile-off" + SUFFIX)), "device state after the effect is what it is without the plugin: %s vs %s" % (state_report(out), state_report(os.path.join(HERE, "out", "hostile-off" + SUFFIX))))
    expect("ALPHA left=0x40 right=0x40" in text, "the back buffer's alpha is untouched: %s" % [l for l in text.splitlines() if "ALPHA" in l])
    expect(passes(log) > 300, "the pass ran every frame, got %d" % passes(log))
    # Compared with the same stand-in mode with the plugin off: multisampling softens the triangle's edge,
    # so the plugin-less plain run is not the same picture.
    whole_picture_same(images, "hostile state, neutral pass", against="hostile-off")
    check_untouched(out, images, log)


def check_hostile_split(out, images, log):
    text = stand_in_output(out)
    expect(state_report(out) == state_report(os.path.join(HERE, "out", "hostile-off" + SUFFIX)), "device state after the effect is what it is without the plugin: %s vs %s" % (state_report(out), state_report(os.path.join(HERE, "out", "hostile-off" + SUFFIX))))
    expect("ALPHA left=0x40 right=0x40" in text, "alpha untouched on both halves: %s" % [l for l in text.splitlines() if "ALPHA" in l])
    for t, image in images:
        if 4.9 < t < 6.1:
            continue
        bg = background(t)
        expect(image.getpixel(LEFT) == (bg, bg, bg), "t=%.0f left half is the stand-in's own (%d), got %s" % (t, bg, image.getpixel(LEFT)))
        if 2.5 <= t <= 4.6 or t >= 8.5:
            expect(abs(grey_at(image, RIGHT) - 102) <= 4, "t=%.0f right half steered to 102 despite the hostile state, got %d" % (t, grey_at(image, RIGHT)))
        expect(image.getpixel(HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(HUD)))


def check_hostile_off(out, images, log):
    """The reference for the hostile variants. The stand-in's own effect may leave some state changed (the
    effect library does not put shader constants back); whatever it reports here is not the plugin's doing."""
    check_untouched(out, images, log)
    expect(passes(log) == 0, "no pass when disabled")


def check_gap_exposure(out, images, log):
    """No pass ran from 4.5 s to 7.2 s while the scene went from 64 to 160. The first processed picture after
    the gap must be at the target at once, not flash brighter while old history catches up."""
    after = sorted((t, grey_at(image, RIGHT)) for t, image in images if 6.9 <= t <= 8.1)
    expect(bool(after), "a screenshot just after the gap")
    for t, value in after:
        expect(abs(value - 102) <= 5, "t=%.0f just after the gap the picture is at 102, got %d" % (t, value))


def check_both(out, images, log):
    check_exposure(out, images, log)


def check_none(out, images, log):
    check_untouched(out, images, log)


def check_off(out, images, log):
    check_untouched(out, images, log)
    whole_picture_same(images, "plugin off")
    expect("VisualBridge loaded" in log, "the plugin loaded")
    expect(passes(log) == 0, "no pass runs when disabled, got %d" % passes(log))


def check_identity(out, images, log):
    """The whole chain runs with neutral numbers: copy, measure, bloom of nothing, draw back."""
    check_untouched(out, images, log)
    whole_picture_same(images, "neutral pass", allow_line="split" in out)
    expect("shaders compiled" in log and "resources created 640x480" in log, "shaders and resources ready")
    expect(passes(log) > 300, "the pass ran every frame, got %d" % passes(log))
    expect("reset: resources released" in log, "resources were released for the device reset")
    expect(log.count("resources created 640x480") == 2, "resources were made again after the reset")
    expect(any(t >= 10 for t, image in images), "screenshots continue after the reset")


def check_split_identity(out, images, log):
    check_identity(out, images, log)


def check_broken(out, images, log):
    check_untouched(out, images, log)
    expect("shader NoSuchShader FAILED" in log, "the failed shader is named in the log")
    expect(passes(log) == 0, "no pass runs without its shaders, got %d" % passes(log))


def look_lines(log):
    out = []
    for line in log.splitlines():
        if " LOOK " in line:
            t = float(line.split("]")[0].strip("[ "))
            out.append((t, dict(kv.split("=") for kv in line.split(" LOOK ")[1].split())))
    return out


def check_exposure(out, images, log, side=RIGHT):
    settled = [(t, image) for t, image in images if 2.5 <= t <= 4.6 or t >= 8.5]
    expect(len(settled) >= 5, "screenshots in the settled periods, got %d" % len(settled))
    for t, image in settled:
        got = grey_at(image, side)
        expect(abs(got - 102) <= 4, "t=%.0f background steered to 102 (middle grey), got %d" % (t, got))
        expect(image.getpixel(HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(HUD)))
    # Brightening must not push bright things over white: the light-grey box (230) gets brighter while the
    # dark scene is lifted (t <= 4.6) but stays below white, and white itself stays white.
    for t, image in images:
        if 2.5 <= t <= 4.6:
            light = grey_at(image, (408, 428))
            expect(230 < light < 255, "t=%.0f light grey 230 is lifted but not to white, got %d" % (t, light))
            expect(image.getpixel(PATCH) == (255, 255, 255), "t=%.0f white stays white" % t)
    first = [image for t, image in images if t <= 1.2]
    expect(bool(first) and abs(grey_at(first[0], side) - 102) <= 6, "the first screenshot is already near 102: no flash at the start")
    # Just after the step to a brighter scene the old scale still applies: brighter than the target, then down.
    after_step = sorted((t, grey_at(image, side)) for t, image in images if 6.0 <= t <= 8.2)
    expect(bool(after_step) and after_step[0][1] > 110, "just after the step the picture is brighter than the target, got %s" % after_step[:1])
    expect(all(a[1] >= b[1] for a, b in zip(after_step, after_step[1:])), "then it comes down steadily, got %s" % after_step)
    values = look_lines(log)
    late = [float(f["exposure"]) for t, f in values if float(f["adapted"]) > 0][-2:]
    expect(bool(late) and all(abs(v - 0.518) <= 0.03 for v in late), "the logged exposure ends at 0.52 for the bright scene, got %s" % late)
    expect("reset: resources released" in log, "the device reset happened during the run")


def check_split_exposure(out, images, log):
    check_exposure(out, images, log, side=RIGHT)
    for t, image in images:
        if 4.9 < t < 6.1:
            continue
        bg = background(t)
        expect(image.getpixel(LEFT) == (bg, bg, bg), "t=%.0f the left half is the game's own picture (%d), got %s" % (t, bg, image.getpixel(LEFT)))
    check_tool(out, images, log)


def check_bloom(out, images, log):
    for t, image in images:
        if 4.9 < t < 6.1:
            continue
        bg = background(t)
        far = image.getpixel(RIGHT)
        expect(far == (bg, bg, bg), "t=%.0f far from the patch nothing changes (%d), got %s" % (t, bg, far))
        expect(image.getpixel(LEFT) == (bg, bg, bg), "t=%.0f the far left is unchanged" % t)
        # 12 pixels outside each edge of the patch (472..488, 232..248): brighter than the background.
        near = {"left": grey_at(image, (460, 240)), "right": grey_at(image, (499, 240)),
                "above": grey_at(image, (480, 220)), "below": grey_at(image, (480, 259))}
        expect(all(v >= bg + 2 for v in near.values()), "t=%.0f light spreads around the patch, got %s over %d" % (t, near, bg))
        expect(abs(near["left"] - near["right"]) <= 1 and abs(near["above"] - near["below"]) <= 1, "t=%.0f the glow is even on all sides, got %s" % (t, near))
        farther = grey_at(image, (440, 240))
        expect(bg <= farther <= near["left"], "t=%.0f the glow fades with distance, got %d then %d" % (t, near["left"], farther))
        expect(image.getpixel(HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched" % t)


def check_tool(out, images, log):
    import json
    import subprocess
    import tempfile
    tool = os.path.join(HERE, "..", "..", "tools", "look-compare.py")
    # A made-up split-screen picture with known halves: left mid-grey, right pure red with a white quarter.
    folder = tempfile.mkdtemp()
    picture = Image.new("RGB", (400, 200), (100, 100, 100))
    picture.paste((255, 0, 0), (200, 0, 400, 200))
    picture.paste((255, 255, 255), (300, 100, 400, 200))
    picture.save(os.path.join(folder, "shot-001.bmp"))
    result = subprocess.run([sys.executable, tool, folder, "--json"], capture_output=True, text=True)
    expect(result.returncode == 0, "look-compare runs: " + result.stderr[-300:])
    if result.returncode == 0:
        row = json.loads(result.stdout)[0]
        game, ours = row["game"], row["ours"]
        expect(abs(game["brightness"] - 100) < 0.5 and game["saturation"] < 0.01 and game["white"] == 0, "left half is flat grey 100, got %s" % game)
        expect(abs(ours["white"] - 0.25) < 0.01, "a quarter of the right half is white, got %s" % ours["white"])
        expect(abs(ours["saturation"] - 0.75) < 0.01, "three quarters of the right half is fully saturated, got %s" % ours["saturation"])
        expect(os.path.isfile(os.path.join(folder, "compare-01.png")), "the side-by-side sheet is written")
    # And on a real run: the processed half is brighter, the game's half is the stand-in's own.
    shots_dir = os.path.dirname([f for t, tag, f in gfxlog.parse(os.path.join(out, "GfxProbe.log")) if tag == "SHOT"][0]["path"])
    result = subprocess.run([sys.executable, tool, shots_dir, "--json"], capture_output=True, text=True)
    if result.returncode == 0:
        rows = json.loads(result.stdout)
        expect(abs(rows[3]["game"]["brightness"] - 64) < 2 and rows[3]["ours"]["brightness"] > 95, "on the split-exposure run: game 64, ours about 102, got %s" % rows[3])


# --- The "scene" mode: floor, wall and sky with known depth (see look-standin.cpp) --------------------------
# Camera at the origin looking along +z, 60 degrees vertical field of view, 640x480. The floor is 1 m below the
# camera up to a wall 10 m away that stands 4 m high; above the wall is sky (nothing drawn, depth 1).
import math

TAN = math.tan(math.radians(30))
SKY, WALL, MARKER, SCENE_HUD = (320, 50), (320, 200), (48, 448), (560, 410)
WALL_FOOT, FLOOR_FOOT = (320, 279), (320, 284)  # just above and just below where the wall meets the floor
SKY_ROWS = 114  # rows 0..114 are sky; the wall's top edge is at row 114.8


def floor_z(row):
    """Distance along the view of the floor at a pixel row (centre of the pixel)."""
    return 1 / (-(1 - (row + 0.5) / 240) * TAN)


def depth_grey(z):
    """What the depth view shows for a distance: z / (z + 10), 0..255."""
    return 255 * z / (z + 10)


def reference_shots(against):
    return dict((round(t), image) for t, image in shots(os.path.join(HERE, "out", against + SUFFIX)))


def paired(images, against):
    """(t, image, reference image) for each screenshot that has a reference at the same second."""
    reference = reference_shots(against)
    expect(len(reference) >= 10, "the '%s' run exists to compare with (run it first)" % against)
    return [(t, image, reference[round(t)]) for t, image in images if round(t) in reference]


def check_scene_common(log, images):
    expect("depth: INTZ 640x480" in log, "the scene's depth texture was found: %s" % [l for l in log.splitlines() if "depth" in l][:3])
    expect(passes(log) > 300, "the pass ran every frame, got %d" % passes(log))
    expect("pass point: end of technique visualtreatment on a 640x480 texture" in log, "the pass ran at the end of the treatment, on its texture, by technique name")
    expect("reset: resources released" in log, "resources were released for the device reset")
    expect(any(t >= 10 for t, image in images), "screenshots continue after the reset")


def check_scene_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")
    for t, image in images:
        expect(image.getpixel(SKY) == (200, 200, 200), "t=%.0f sky is the stand-in's grey 200, got %s" % (t, image.getpixel(SKY)))
        expect(image.getpixel(MARKER) == (90, 90, 90), "t=%.0f the treatment's marker is drawn, got %s" % (t, image.getpixel(MARKER)))
        # The smoothing tests' features are there and hard-edged in the plain picture (so their checks can fail).
        expect(intermediate_rows(image) == 0, "t=%.0f the plain diagonal edge has no in-between shades, got %d rows" % (t, intermediate_rows(image)))
        expect(min(grey_at(image, (160, row)) for row in range(62, 69)) == 0, "t=%.0f the one-pixel line is drawn" % t)


def check_scene_identity(out, images, log):
    whole_picture_same(images, "neutral pass in the scene", against="scene-off")
    check_scene_common(log, images)


def check_scene_depth(out, images, log):
    check_scene_common(log, images)
    for t, image in images:
        sky, wall, near = grey_at(image, SKY), grey_at(image, WALL), grey_at(image, (320, 460))
        expect(image.getpixel(SKY) == (255, 255, 255), "t=%.0f sky is white in the depth view, got %s" % (t, image.getpixel(SKY)))
        expect(abs(wall - depth_grey(10)) <= 3, "t=%.0f the wall (10 m) shows %.0f, got %d" % (t, depth_grey(10), wall))
        expect(abs(near - depth_grey(floor_z(460))) <= 3, "t=%.0f the near floor (%.2f m) shows %.0f, got %d" % (t, floor_z(460), depth_grey(floor_z(460)), near))
        expect(near < wall < sky, "t=%.0f near floor < wall < sky, got %d %d %d" % (t, near, wall, sky))
        # The marker the treatment drew must be gone: the pass ran after the treatment, not before it.
        expect(abs(grey_at(image, MARKER) - depth_grey(floor_z(448))) <= 3, "t=%.0f the marker is replaced by the depth view, got %s" % (t, image.getpixel(MARKER)))
        expect(image.getpixel(SCENE_HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(SCENE_HUD)))


def darkening(image, reference, at):
    ref = grey_at(reference, at)
    return (ref - grey_at(image, at)) / float(ref)


def check_ao_picture(images, against, columns=(160, 320, 480), split=False):
    from PIL import ImageChops
    pairs = paired(images, against)
    expect(len(pairs) >= 10, "screenshots paired with the reference, got %d" % len(pairs))
    for t, image, reference in pairs:
        for x in columns:
            for at in ((x, WALL_FOOT[1]), (x, FLOOR_FOOT[1])):
                expect(darkening(image, reference, at) >= 0.15, "t=%.0f the inner corner at %s darkens by 15%% or more, got %.1f%%" % (t, at, 100 * darkening(image, reference, at)))
            for row in range(310, 471, 10):
                change = abs(darkening(image, reference, (x, row)))
                expect(change < 0.02, "t=%.0f open floor at (%d, %d), %.1f m from the wall, changes under 2%%, got %.1f%%" % (t, x, row, 10 - floor_z(row), 100 * change))
        # (In split screen the dividing line at x 319..320 is ours, in the sky as everywhere.)
        for x0, x1 in (((0, 318), (322, 640)) if split else ((0, 640),)):
            sky = ImageChops.difference(image.crop((x0, 0, x1, SKY_ROWS + 1)), reference.crop((x0, 0, x1, SKY_ROWS + 1))).getbbox()
            expect(sky is None, "t=%.0f the sky does not change at all, differs in %s" % (t, sky))
        expect(ImageChops.subtract(image, reference).getbbox() is None, "t=%.0f no pixel gets brighter, got %s" % (t, ImageChops.subtract(image, reference).getbbox()))
        expect(image.getpixel(SCENE_HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(SCENE_HUD)))
        if split:
            box = ImageChops.difference(image.crop((0, 0, 318, 480)), reference.crop((0, 0, 318, 480))).getbbox()
            expect(box is None, "t=%.0f the left half is the game's own picture, differs in %s" % (t, box))


def ao_times(log):
    return [float(f["ao_ms"]) for t, f in look_lines(log) if "ao_ms" in f]


def check_scene_ao(out, images, log):
    check_scene_common(log, images)
    check_ao_picture(images, "scene-off")
    times = ao_times(log)
    expect(bool(times) and max(times) > 0, "the pass's graphics-card time is logged (ao_ms), got %s" % times[:5])


def check_scene_ao_full(out, images, log):
    check_scene_ao(out, images, log)
    expect("ao resolution 640x480" in log, "full-resolution occlusion")


def check_scene_split_ao(out, images, log):
    check_scene_common(log, images)
    check_ao_picture(images, "scene-off", columns=(480,), split=True)


def check_scene_toggle(out, images, log):
    """[Test] ToggleSeconds = 2 (whole once-a-second counts then fall inside one stretch): the effects run two
    seconds and not the next two; each switch is logged with its time,
    so a frame-time recording can be split into on and off stretches of the same race."""
    switches = [l for l in log.splitlines() if "toggle: effects " in l]
    ons = [l for l in switches if "toggle: effects on" in l]
    offs = [l for l in switches if "toggle: effects off" in l]
    expect(len(ons) >= 2 and len(offs) >= 2, "at least two switches each way are logged, got %d on, %d off" % (len(ons), len(offs)))
    expect(all(switches[i].split("effects ")[1][:2] != switches[i - 1].split("effects ")[1][:2] for i in range(1, len(switches))),
           "the switches alternate")
    seconds = [int(f["passes"]) for _, f in look_lines(log)]
    expect(any(p == 0 for p in seconds[1:]) and any(p > 0 for p in seconds[1:]),
           "some seconds have passes and some none, got %s" % seconds)


# --- Edge smoothing (graphics part 2): the scene mode's test features, drawn into the 3D picture before the
# treatment (look-standin.cpp): a black triangle (340,20)-(620,20)-(340,100) on the grey-200 sky, whose long edge
# x = 620 - 3.5 (y - 20) is a hard stair-step, and a black line one pixel thick from (20,60) to (300,70).
EDGE_ROWS = range(25, 96)


def edge_x(row):
    return 620 - 3.5 * (row + 0.5 - 20)


def intermediate_rows(image):
    """Rows of the triangle's long edge that have a shade strictly between the two colours near the edge."""
    found = 0
    for row in EDGE_ROWS:
        x0 = int(edge_x(row))
        values = [grey_at(image, (x, row)) for x in range(x0 - 4, x0 + 6)]
        found += any(20 <= v <= 180 for v in values)
    return found


def line_contrast(image, reference):
    """The one-pixel line's contrast (darkest to brightest across it, per column) against the plain picture's: the
    smallest ratio over the columns."""
    worst = 1.0
    for x in range(30, 291, 10):
        column = [grey_at(image, (x, row)) for row in range(54, 78)]
        plain = [grey_at(reference, (x, row)) for row in range(54, 78)]
        worst = min(worst, (max(column) - min(column)) / float(max(plain) - min(plain)))
    return worst


def flat_changes(image, reference, skip_columns=None):
    """The bounding box of pixels in flat parts of the plain picture (its 5x5 neighbourhood one colour) that changed
    by more than 1/255, or None."""
    from PIL import ImageChops, ImageFilter
    flat = ImageChops.difference(reference.filter(ImageFilter.MaxFilter(5)), reference.filter(ImageFilter.MinFilter(5)))
    flat = flat.convert("L").point(lambda v: 255 if v == 0 else 0)
    if skip_columns:
        flat.paste(0, (skip_columns[0], 0, skip_columns[1], flat.size[1]))
    big = ImageChops.difference(image, reference).convert("L").point(lambda v: 255 if v > 1 else 0)
    return ImageChops.multiply(flat, big).getbbox()


HUD_BOX = (530, 395, 630, 465)


def check_aa_picture(images, against, split=False, line=True, flat=True):
    from PIL import ImageChops
    pairs = paired(images, against)
    expect(len(pairs) >= 10, "screenshots paired with the reference, got %d" % len(pairs))
    for t, image, reference in pairs:
        rows = intermediate_rows(image)
        expect(rows >= 0.9 * len(EDGE_ROWS), "t=%.0f the diagonal edge has an in-between shade in 90%% of its rows, got %d of %d"
               % (t, rows, len(EDGE_ROWS)))
        if line:
            contrast = line_contrast(image, reference)
            expect(contrast >= 0.6, "t=%.0f the one-pixel line keeps 60%% of its contrast, got %.0f%%" % (t, 100 * contrast))
        if flat:
            box = flat_changes(image, reference, (316, 324) if split else None)
            expect(box is None, "t=%.0f flat areas change by at most 1/255, changed in %s" % (t, box))
        hud = ImageChops.difference(image.crop(HUD_BOX), reference.crop(HUD_BOX)).getbbox()
        expect(hud is None, "t=%.0f the HUD triangle and around it are exactly the game's, differ in %s" % (t, hud))
        if split:
            left = ImageChops.difference(image.crop((0, 0, 316, 480)), reference.crop((0, 0, 316, 480))).getbbox()
            expect(left is None, "t=%.0f the left half is the game's own picture, differs in %s" % (t, left))


def aa_counts(log):
    return [int(f["aa"]) for t, f in look_lines(log) if "aa" in f]


def check_aa_common(log, images):
    expect("aa: replacing the pass-through" in log, "the log says the pass-through is replaced: %s"
           % [l for l in log.splitlines() if "aa" in l.lower()][:3])
    counts = aa_counts(log)
    expect(len(counts) >= 8 and all(c > 0 for c in counts[1:]), "smoothing ran every second (aa= in the LOOK line), got %s" % counts)
    times = [float(f["aa_ms"]) for t, f in look_lines(log) if "aa_ms" in f]
    expect(bool(times) and max(times) > 0, "the smoothing's graphics-card time is logged (aa_ms), got %s" % times[:5])
    expect("reset: resources released" in log, "the device reset happened during the run")
    expect(any(t >= 10 for t, image in images), "screenshots continue after the reset")


def check_scene_aa(out, images, log):
    check_aa_common(log, images)
    check_aa_picture(images, "scene-off")


def check_scene_split_aa(out, images, log):
    check_aa_common(log, images)
    check_aa_picture(images, "scene-off", split=True, line=False)


def check_scene_nopass_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_aa_nopass(out, images, log):
    """The stand-in copies the treated picture to the screen without the pack's pass-through technique: the
    smoothing has nothing to replace, and the picture is exactly the one without it."""
    whole_picture_same(images, "no pass-through, no smoothing", against="scene-nopass-off")
    expect("aa: replacing" not in log, "nothing replaced")


def check_scene_hostile_aa(out, images, log):
    text = stand_in_output(out)
    reference = os.path.join(HERE, "out", "scene-hostile-off" + SUFFIX)
    expect(state_report(out) == state_report(reference), "device state after the treatment and after the pass-through is what it is without the plugin: %s vs %s" % (state_report(out), state_report(reference)))
    alpha = [l for l in text.splitlines() if l.startswith("ALPHA2")]
    plain = [l for l in stand_in_output(reference).splitlines() if l.startswith("ALPHA2")]
    expect(bool(alpha) and alpha == plain, "the back buffer's alpha after the pass-through is the game's: %s vs %s" % (alpha, plain))
    check_aa_common(log, images)
    for t, image, ref in paired(images, "scene-hostile-off"):
        rows = intermediate_rows(image)
        expect(rows >= 0.9 * len(EDGE_ROWS), "t=%.0f the edge is smoothed despite the hostile state, got %d rows" % (t, rows))


def check_scene_ao_aa(out, images, log):
    """Occlusion (its direct path onto the treated picture) and then smoothing in the pass-through: both show."""
    check_aa_common(log, images)
    check_aa_picture(images, "scene-off", line=True, flat=False)
    for t, image, reference in paired(images, "scene-off"):
        for x in (160, 320, 480):
            expect(darkening(image, reference, (x, FLOOR_FOOT[1])) >= 0.15, "t=%.0f the corner at x %d still darkens by 15%%" % (t, x))


def check_scene_toggle_only_aa(out, images, log):
    """Occlusion and smoothing on, ToggleOnly = ao: occlusion switches, smoothing runs in every second."""
    switches = toggle_switches(log, "ao")
    expect(len(switches) >= 4, "the ao switches are logged, got %s" % switches[:4])
    counts = aa_counts(log)
    expect(len(counts) >= 8 and all(c > 0 for c in counts[1:]), "smoothing ran in every second, the ao-off ones too: %s" % counts)
    seconds = [int(f["passes"]) for _, f in look_lines(log)]
    expect(any(p == 0 for p in seconds[1:]) and any(p > 0 for p in seconds[1:]), "occlusion's passes come and go, got %s" % seconds)


# --- Distance haze (graphics part 2, Task 7): [Haze] Start 4 m, End 10 m, Amount 0.5, Colour red (255, 0, 0) in the
# stand-in, so the floor nearer than 4 m is untouched, the wall (10 m) is half way to red, and the sky is untouched.
def haze_expected(grey, z, start=4.0, end=10.0, amount=0.5, colour=(255, 0, 0)):
    f = amount * min(max((z - start) / (end - start), 0.0), 1.0)
    return tuple(grey + f * (c - grey) for c in colour)


def check_haze_picture(images, against, split=False):
    from PIL import ImageChops
    pairs = paired(images, against)
    expect(len(pairs) >= 10, "screenshots paired with the reference, got %d" % len(pairs))
    x = 480 if split else 320
    for t, image, reference in pairs:
        near = ImageChops.difference(image.crop((0, 350, 640, 471)), reference.crop((0, 350, 640, 471))).getbbox()
        expect(near is None, "t=%.0f the floor nearer than Start (4 m) is unchanged, differs in %s" % (t, near))
        x0 = 322 if split else 0
        sky = ImageChops.difference(image.crop((x0, 0, 640, SKY_ROWS + 1)), reference.crop((x0, 0, 640, SKY_ROWS + 1))).getbbox()
        expect(sky is None, "t=%.0f the sky (and what stands in it) is unchanged, differs in %s" % (t, sky))
        for at, grey, z in (((x, 200), 160, 10.0), ((x, 299), 128, floor_z(299))):
            want, got = haze_expected(grey, z), image.getpixel(at)
            expect(all(abs(g - w) <= 3 for g, w in zip(got, want)), "t=%.0f at %s (%.1f m) the colour is %s, got %s"
                   % (t, at, z, tuple(round(v) for v in want), got))
        expect(image.getpixel(SCENE_HUD) == (128, 128, 128), "t=%.0f the HUD triangle is untouched, got %s" % (t, image.getpixel(SCENE_HUD)))
        if split:
            left = ImageChops.difference(image.crop((0, 0, 316, 480)), reference.crop((0, 0, 316, 480))).getbbox()
            expect(left is None, "t=%.0f the left half is the game's own picture, differs in %s" % (t, left))


def check_scene_haze(out, images, log):
    check_scene_common(log, images)
    check_haze_picture(images, "scene-off")
    expect("resources created" not in log, "no copy of the picture is made (one blended draw onto the treated picture)")


def check_scene_split_haze(out, images, log):
    check_scene_common(log, images)
    check_haze_picture(images, "scene-off", split=True)


def check_scene_ao_haze(out, images, log):
    """Occlusion and haze together, both straight onto the treated picture (no copy)."""
    check_scene_common(log, images)
    expect("resources created" not in log, "no copy of the picture is made")
    # Occlusion multiplies the picture, then haze mixes in red: against the haze-only run, the green channel at the
    # corner is darker by occlusion's factor (the red channel is pulled up by the red haze, so it cannot show it).
    for t, image, reference in paired(images, "scene-haze"):
        at = (160, FLOOR_FOOT[1])
        dark = (reference.getpixel(at)[1] - image.getpixel(at)[1]) / float(reference.getpixel(at)[1])
        expect(dark >= 0.15, "t=%.0f the corner still darkens by 15%% (green, against haze alone), got %.1f%%" % (t, 100 * dark))
        red, green = image.getpixel((320, 200))[:2]
        expect(red > 190 and green < 100, "t=%.0f the wall is hazed towards red, got %s" % (t, image.getpixel((320, 200))))


def check_scene_nointz_haze(out, images, log):
    whole_picture_same(images, "no depth, haze skipped", against="scene-nointz-off")


def check_scene_hostile_haze(out, images, log):
    reference = os.path.join(HERE, "out", "scene-hostile-off" + SUFFIX)
    expect(state_report(out) == state_report(reference), "device state is what it is without the plugin: %s vs %s" % (state_report(out), state_report(reference)))
    expect("ALPHA left=0x40 right=0x40" in stand_in_output(out), "the back buffer's alpha is untouched")
    check_scene_common(log, images)
    for t, image, ref in paired(images, "scene-hostile-off"):
        expect(image.getpixel((320, 200))[0] > 190, "t=%.0f the wall is hazed despite the hostile state, got %s" % (t, image.getpixel((320, 200))))


def check_scene_toggle_only_haze(out, images, log):
    switches = toggle_switches(log, "haze")
    expect(len(switches) >= 4, "the haze switches are logged, got %s" % switches[:4])
    seconds = [int(f["passes"]) for _, f in look_lines(log)]
    expect(all(p > 0 for p in seconds[1:]), "occlusion keeps the pass running in every second, got %s" % seconds)


# --- Light shafts (graphics part 2, Task 6). Stand-in mode "sun": the stand-in's camera and a sun direction in its own
# memory, their addresses written to VisualBridge.ini ([Sun]); the sun lands at about (404, 53), in the sky above the
# wall. "sunbehind": behind the camera. "sunside": in front but far off the right edge (x about 1.47).
SUN_AT = (404, 53)


def sun_lines(log):
    out = []
    for line in log.splitlines():
        if " SUN " in line:
            out.append(dict(kv.split("=") for kv in line.split(" SUN ")[1].split() if "=" in kv))
    return out


def check_shafts_picture(images, against, split=False):
    from PIL import ImageChops
    pairs = paired(images, against)
    expect(len(pairs) >= 10, "screenshots paired with the reference, got %d" % len(pairs))
    for t, image, reference in pairs:
        gain = grey_at(image, (404, 105)) - grey_at(reference, (404, 105))
        expect(gain >= 6, "t=%.0f the sky between the sun and the wall top brightens, got +%d" % (t, gain))
        for at in ((100, 260), (320, 420), (550, 300), (60, 200)):
            expect(image.getpixel(at) == reference.getpixel(at), "t=%.0f far from the sky's edge %s is unchanged, got %s for %s"
                   % (t, at, image.getpixel(at), reference.getpixel(at)))
        darker = ImageChops.subtract(reference, image).getbbox()
        if split and darker and darker[0] >= 318 and darker[2] <= 322:
            darker = None
        expect(darker is None, "t=%.0f no pixel gets darker, got %s" % (t, darker))
        hud = ImageChops.difference(image.crop(HUD_BOX), reference.crop(HUD_BOX)).getbbox()
        expect(hud is None, "t=%.0f the HUD and around it are the game's, differ in %s" % (t, hud))
        if split:
            left = ImageChops.difference(image.crop((0, 0, 316, 480)), reference.crop((0, 0, 316, 480))).getbbox()
            expect(left is None, "t=%.0f the left half is the game's own picture, differs in %s" % (t, left))


def check_sun_logged(log, x=0.632, y=0.110, proj="game"):
    suns = sun_lines(log)
    expect(bool(suns) and all(s.get("on") == "1" for s in suns[1:]), "SUN lines say the sun is on screen: %s" % suns[:2])
    if suns:
        s = suns[-1]
        expect(abs(float(s["x"]) - x) < 0.01 and abs(float(s["y"]) - y) < 0.01, "the sun at (%.3f, %.3f), got %s" % (x, y, s))
        expect(s.get("proj") == proj, "the SUN line says which projection was used (proj=%s), got %s" % (proj, s.get("proj")))


def check_scene_sun_shafts(out, images, log):
    check_scene_common(log, images)
    check_sun_logged(log)
    check_shafts_picture(images, "scene-sun-off")
    expect("resources created" not in log, "no copy of the picture is made")
    # The game's depth planes are logged in the SUN line even when [Depth] FromGame is 0 (the stand-in's view: 0.5 / 1000).
    planes = [s.get("planes") for s in sun_lines(log)]
    expect("0.500/1000" in planes, "the SUN line carries the view's planes=0.500/1000, got %s" % sorted(set(p for p in planes if p))[:3])
    times = [float(f["shafts_ms"]) for t, f in look_lines(log) if "shafts_ms" in f]
    expect(bool(times) and max(times) > 0, "the shafts' graphics-card time is logged (shafts_ms), got %s" % times[:5])


def check_scene_sun_split_shafts(out, images, log):
    check_scene_common(log, images)
    check_shafts_picture(images, "scene-sun-off", split=True)


def check_scene_sun_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_sunbehind_shafts(out, images, log):
    whole_picture_same(images, "sun behind the camera: no rays", against="scene-off")
    suns = sun_lines(log)
    expect(bool(suns) and all(s.get("on") == "0" for s in suns), "SUN lines say not on screen: %s" % suns[:2])


def check_scene_sun_noinfo_shafts(out, images, log):
    """SunInfo is 0 while the stand-in's camera and direction say the sun is ahead: the direction in memory is a
    leftover, so VisualBridge treats it as no sun (as the game's own GetSunPos does)."""
    whole_picture_same(images, "no sun entry: no rays", against="scene-off")
    suns = sun_lines(log)
    expect(bool(suns) and all(s.get("on") == "0" and s.get("info") == "0x00000000" for s in suns),
           "SUN lines say no sun entry (info=0x00000000, on=0): %s" % suns[:2])
    # Neither projection ran (no sun entry): the line must not claim the fallback did.
    expect(bool(suns) and all(s.get("proj") == "none" for s in suns), "SUN lines say proj=none: %s" % [s.get("proj") for s in suns][:4])


def check_scene_sunside_shafts(out, images, log):
    whole_picture_same(images, "sun far off the screen's edge: no streaks", against="scene-off")


def check_marker(images, at=SUN_AT):
    """The ShowSun marker: a magenta cross centred on the sun, arms 1/36 of the picture's height (13 px here) each way,
    big enough to find at a glance in the game; not a filled block, and nothing magenta far from it."""
    x, y = at
    for t, image in images:
        expect(image.getpixel(at) == (255, 0, 255), "t=%.0f the marker sits where the sun is %s, got %s" % (t, at, image.getpixel(at)))
        for arm in ((x + 10, y), (x - 10, y), (x, y + 10), (x, y - 10)):
            expect(image.getpixel(arm) == (255, 0, 255), "t=%.0f the marker's arm reaches %s, got %s" % (t, arm, image.getpixel(arm)))
        expect(image.getpixel((x + 10, y + 10)) != (255, 0, 255), "t=%.0f the marker is a cross, not a block" % t)
        expect(image.getpixel((x, y + 27)) != (255, 0, 255), "t=%.0f the marker ends within 13 px" % t)


def check_scene_sun_showsun(out, images, log):
    check_marker(images)
    check_sun_logged(log)


def check_scene_sun_wrongfov_showsun(out, images, log):
    """[Depth] FovY says 40 degrees while the stand-in's view is 60 (as the game widens its view at speed): the sun's
    place comes from the view's own matrix (the stand-in's eViewPlatInfo + 0x80), so the marker is still on the sun."""
    check_marker(images)
    check_sun_logged(log, proj="game")


def check_scene_sun_noplat_showsun(out, images, log):
    """No platform info (the view's pointer at +0 is 0): VisualBridge falls back to the camera and [Depth] FovY (60,
    right for the stand-in) and says so."""
    check_marker(images)
    check_sun_logged(log, proj="fovy")


def shadow_max(out):
    import re
    m = re.search(r"SHADOWMAX (-?\d+) calls (\d+)", stand_in_output(out))
    expect(m is not None, "the stand-in reports SHADOWMAX")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def check_scene_shadows_unlock(out, images, log):
    """[Shadows] Unlock = 1: both call sites of the (stand-in) shadow-maximum function go through VisualBridge's wrapper,
    the function still runs at each (2 calls), and the maximum it set to 0 is lifted back to Level (2); logged."""
    value, calls = shadow_max(out)
    expect(value == 2, "the shadow maximum is lifted to 2, got %s" % value)
    expect(calls == 2, "the game's function still runs at both sites, got %s calls" % calls)
    expect(log.count("rerouted through VisualBridge") == 2, "both call sites are logged as rerouted")
    expect("shadows: the game set the highest shadow level to 0; lifted to 2" in log, "the lift is logged")


def check_scene_shadowsro_unlock(out, images, log):
    """[Shadows] MaxAddress points at read-only memory: the calls are rerouted and the game's function runs, but nothing
    is written there (the stand-in would crash) and the log says why (the review of 2026-10-30, item 4)."""
    value, calls = shadow_max(out)
    expect(calls == 2, "the game's function still runs at both sites, got %s calls" % calls)
    expect("cannot be written" in log, "the log says the maximum cannot be written")
    expect("lifted to" not in log, "nothing is lifted")


def check_scene_shadows_off(out, images, log):
    """[Shadows] Unlock = 0: nothing patched, the maximum stays as the function set it (0)."""
    value, calls = shadow_max(out)
    expect(value == 0 and calls == 2, "the maximum stays 0 after 2 calls, got %s after %s" % (value, calls))
    expect("shadows: call site" not in log, "no call site touched")


def check_scene_shadowswrong_unlock(out, images, log):
    """The .ini names a different function than the sites call: neither site is patched (logged), the maximum stays 0."""
    value, calls = shadow_max(out)
    expect(value == 0 and calls == 2, "the maximum stays 0 after 2 calls, got %s after %s" % (value, calls))
    expect(log.count("is not a call to") == 2, "both sites logged as not matching")
    expect("rerouted" not in log, "nothing rerouted")


def check_scene_sun_ao_fov60(out, images, log):
    """Occlusion with [Depth] FovY right for the stand-in's view (60): the reference for the two below. The
    occlusion's field of view comes from the view's matrix, and the log says so."""
    expect("view field of view: from the game's view" in log, "the log says the field of view is the view's own")
    reference = dict((round(t), image) for t, image in shots(os.path.join(HERE, "out", "scene-sun-off" + SUFFIX)))
    from PIL import ImageChops
    expect(any(ImageChops.difference(image, reference[round(t)]).getbbox() for t, image in images
               if round(t) in reference and t > 6.1), "the occlusion changes the picture (against scene-sun-off)")


def check_scene_sun_ao_wrongfov(out, images, log):
    """[Depth] FovY says 40 while the view is 60 (as when the game widens its view at speed): the occlusion uses the
    view's own field of view, so the picture is exactly the one with FovY right."""
    whole_picture_same(images, "occlusion with a wrong FovY", against="scene-sun-ao-fov60")
    expect("view field of view: from the game's view" in log, "the log says the field of view is the view's own")


def check_scene_sun_ao_wrongnear(out, images, log):
    """[Depth] says 2 / 50 m but FromGame = 1: the planes come from the view's matrix (0.5 / 1000), logged, and the
    occlusion is exactly fov60's."""
    # Within 1/255: the planes worked out from the matrix differ from 0.5 / 1000 in the last float digits, which moves a
    # few far pixels by one step (79 pixels at the horizon, measured).
    from PIL import ImageChops
    reference = reference_shots("scene-sun-ao-fov60")
    for t, image in images:
        if 4.9 < t < 6.1 or round(t) not in reference:
            continue
        top = max(hi for lo, hi in ImageChops.difference(image, reference[round(t)]).getextrema())
        expect(top <= 1, "t=%.0f occlusion with the game's planes within 1/255 of fov60's, differs by %d" % (t, top))
    expect("depth planes: from the game's view (near 0.500 far 1000)" in log, "the log names the game's planes")


def check_scene_sun_ao_wrongnear_off(out, images, log):
    """The same wrong planes used (FromGame = 0): the occlusion differs from fov60's (so the test above can tell), and
    the log says where the planes came from; the game's are still logged."""
    from PIL import ImageChops
    reference = reference_shots("scene-sun-ao-fov60")
    tops = [max(hi for lo, hi in ImageChops.difference(image, reference[round(t)]).getextrema()) for t, image in images
            if round(t) in reference and not 4.9 < t < 6.1]
    expect(bool(tops) and max(tops) > 1, "wrong planes change the picture by more than 1/255, got %s" % tops[:4])
    expect("depth planes: from [Depth] Near/Far (2.000, 50)" in log, "the log says the [Depth] values are used")


def check_scene_sun_badplat_ao_fromgame(out, images, log):
    """No usable matrix with FromGame = 1: [Depth] Near/Far (right here), said in the log, the picture is fov60's."""
    whole_picture_same(images, "occlusion on the [Depth] fallback", against="scene-sun-ao-fov60")
    expect("depth planes: from [Depth] Near/Far (0.500, 1000): the view's matrix cannot be read" in log, "the log says why")


def check_scene_sun_badplat_ao(out, images, log):
    """No usable matrix (all zero): the occlusion falls back to [Depth] FovY (60, right here), says so, and matches
    the reference."""
    whole_picture_same(images, "occlusion on the FovY fallback", against="scene-sun-ao-fov60")
    expect("view field of view: from [Depth] FovY" in log, "the log says the fallback is used")


def check_scene_sun_badplat_showsun(out, images, log):
    """The view's matrix is not a view (all zero, as before the game first fills it): the fallback, logged."""
    check_marker(images)
    check_sun_logged(log, proj="fovy")


def check_scene_sunleft_split_showsun(out, images, log):
    """Split screen: the marker shows on the left (game's) half too, so it can be checked while comparing."""
    check_marker(images, at=(236, 53))


def check_scene_sun_hostile_shafts(out, images, log):
    reference = os.path.join(HERE, "out", "scene-sun-hostile-off" + SUFFIX)
    expect(state_report(out) == state_report(reference), "device state is what it is without the plugin: %s vs %s" % (state_report(out), state_report(reference)))
    expect("ALPHA left=0x40 right=0x40" in stand_in_output(out), "the back buffer's alpha is untouched")
    for t, image, ref in paired(images, "scene-sun-hostile-off"):
        expect(grey_at(image, (404, 105)) - grey_at(ref, (404, 105)) >= 6, "t=%.0f rays despite the hostile state" % t)


def check_scene_sun_hostile_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def toggle_switches(log, name):
    """The toggle lines for one name ("effects" when everything switches), in order: [(time, on?)]."""
    out = []
    for line in log.splitlines():
        if "toggle: %s " % name in line:
            out.append((float(line.split("]")[0].strip("[ ")), line.rstrip().endswith(" on")))
    return out


def check_scene_toggle_only(out, images, log):
    """[Test] ToggleOnly = ao: only ambient occlusion switches; the log names it ("toggle: ao on/off"), so a cost
    measured from the switches is that effect's alone. (With a second effect on, passes go on in the "off" seconds:
    checked by scene-toggle-only-aa.)"""
    switches = toggle_switches(log, "ao")
    expect(sum(1 for t, on in switches if on) >= 2 and sum(1 for t, on in switches if not on) >= 2,
           "at least two 'toggle: ao' switches each way, got %s" % switches[:6])
    expect(all(a[1] != b[1] for a, b in zip(switches, switches[1:])), "the switches alternate: %s" % switches[:8])
    expect(not toggle_switches(log, "effects"), "no 'toggle: effects' lines when one effect is named")
    seconds = [int(f["passes"]) for _, f in look_lines(log)]
    expect(any(p == 0 for p in seconds[1:]) and any(p > 0 for p in seconds[1:]),
           "with occlusion the only effect, some seconds have passes and some none, got %s" % seconds)


def check_scene_intz2_ao(out, images, log):
    """A second, smaller INTZ depth texture bound first each frame: VisualBridge keeps to the one the size of the
    picture, so occlusion is right and the depth is found once, not every frame."""
    check_scene_ao(out, images, log)
    found = [l for l in log.splitlines() if "depth: INTZ" in l and "found" in l]
    expect(len(found) <= 2 and all("640x480" in l for l in found), "the picture-sized INTZ found once (and once after the Reset), got %s" % found[:4])


def showcase_squares(image):
    """How many of the showcase's level squares (top left, 20 px apart) are drawn in a screenshot."""
    return sum(1 for i in range(3) if image.getpixel((26 + i * 20, 56)) == (255, 255, 255))


def check_scene_ao_showcase(out, images, log):
    """[Test] AOShowcase with 1-second blinks and one blink per level (2 s a level, occlusion on for the first second,
    so screenshots a second apart see the levels in turn: each level has two "on" seconds in the run, 0-1 and 6-7 s for
    level 1; with longer blinks level 1's only one ends before the first screenshot): the levels follow 1, 2, 3, each
    logged with its settings; occlusion is worked out at half size in level 1 and full
    size in levels 2 and 3; the level squares (1 to 3) are drawn top left while occlusion is on, and all three counts
    are seen; levels 2 and 3 (same size, radius 0.6 against 0.35) give different pictures, so the radius reaches the
    shader."""
    from PIL import ImageChops
    levels = [int(l.split("level ")[1][0]) for l in log.splitlines() if "showcase: level " in l]
    expect(len(levels) >= 3 and levels[:3] == [1, 2, 3], "levels 1, 2, 3 in order, got %s" % levels)
    expect("ao resolution 320x240" in log and "ao resolution 640x480" in log, "half and full size both used")
    expect("showcase: level 3 (half=0 radius=0.35)" in log, "level 3 logged with its settings")
    by_count = {}
    for _t, im in images:
        by_count.setdefault(showcase_squares(im), []).append(im)
    expect({1, 2, 3} <= set(by_count), "1, 2 and 3 level squares are all seen, got counts %s" % sorted(by_count))
    if 2 in by_count and 3 in by_count:
        # Below the squares: the scene with occlusion at radius 0.6 (level 2) against 0.35 (level 3).
        two, three = by_count[2][0].crop((0, 100, 640, 480)), by_count[3][0].crop((0, 100, 640, 480))
        biggest = max(v for band in ImageChops.difference(two, three).getextrema() for v in band)
        expect(biggest >= 3, "levels 2 and 3 give different pictures (the radius reaches the shader), largest difference %d" % biggest)


def check_scene_ao_showcase_notoggle(out, images, log):
    """[Test] AOShowcase = 1 without ToggleSeconds does nothing: the log says so (once), no level is shown."""
    said = [l for l in log.splitlines() if "AOShowcase = 1" in l and "ToggleSeconds = 0" in l]
    expect(len(said) == 1, "the log says once that the showcase needs ToggleSeconds, got %s" % said)
    expect("showcase: level" not in log, "no showcase level is run")
    expect(all(showcase_squares(im) == 0 for _t, im in images), "no level squares are drawn")


def check_scene_ao_showcase_fullfail(out, images, log):
    """The full-size occlusion cannot be made ([Test] FailFullSizeAO, as if the card were out of memory): in levels 2
    and 3 occlusion does not run, so their squares are not drawn (they would claim a level that is not shown); back in
    level 1 (half size) the failure is forgotten and occlusion runs again, before the device Reset at 9 s would clear it."""
    counts = sorted({showcase_squares(im) for _t, im in images})
    expect(2 not in counts and 3 not in counts, "no level 2 or 3 squares while occlusion failed, got counts %s" % counts)
    lines = log.splitlines()
    failed = [i for i, l in enumerate(lines) if "depth resources FAILED" in l]
    reset = [i for i, l in enumerate(lines) if "reset: resources released" in l]
    expect(bool(failed), "the full-size failure is logged")
    if failed:
        again = [i for i, l in enumerate(lines) if "ao resolution 320x240" in l and i > failed[0] and (not reset or i < reset[0])]
        expect(bool(again), "half-size occlusion is made again after the failure, before the Reset: %s" % lines[failed[0]:failed[0] + 6])


def check_scene_reload_ao_showcase(out, images, log):
    """The stand-in switches the showcase off at 4.5 s and on again at 10.2 s (rewriting VisualBridge.ini): the
    'settings reloaded' line shows the test settings, and the level after switching back on is logged although it is
    the same level as the last one before (level 3)."""
    lines = log.splitlines()
    reloads = [i for i, l in enumerate(lines) if "settings reloaded" in l]
    expect(len(reloads) >= 2, "two reloads logged, got %d" % len(reloads))
    for i in reloads:
        expect("toggleSeconds=1" in lines[i] and "toggleOnly=ao" in lines[i] and "aoShowcase=" in lines[i],
               "the reload line prints toggleSeconds, toggleOnly and aoShowcase: %s" % lines[i])
    if len(reloads) >= 2:
        expect("aoShowcase=0" in lines[reloads[0]] and "aoShowcase=1" in lines[reloads[1]], "off, then on again")
        after = [l for l in lines[reloads[1]:] if "showcase: level" in l]
        expect(bool(after), "a showcase level is logged after switching the showcase back on")


def check_scene_toggle_huge(out, images, log):
    """[Test] ToggleSeconds = 999999999 (a typo): clamped to 3600 and logged; the effects run (the first hour is on)."""
    expect(any("ToggleSeconds = 999999999" in l and "3600" in l for l in log.splitlines()), "the clamp is logged")
    expect(passes(log) > 300, "the pass ran every frame, got %d" % passes(log))


def check_scene_toggle_wrap(out, images, log):
    """[Test] ToggleSeconds = 536870912 with the showcase: times 1000 (and 2000) wraps to 0 in 32 bits, a division by
    zero that would crash the game. Clamped to 3600 and logged; the stand-in runs to the end."""
    expect(any("ToggleSeconds = 536870912" in l and "3600" in l for l in log.splitlines()), "the clamp is logged")
    expect(passes(log) > 300, "the pass ran every frame, got %d" % passes(log))
    expect("presented" in stand_in_output(out), "the stand-in ran to the end")


# --- Wet reflections (graphics part 3, Task 6). Mode "wet": the scene plus a white box standing on the floor 5 m ahead
# (x -1..1, from the floor up to 0.5 m above the camera: screen columns about 237..403, rows 198..323) and a low box
# to the right (x 1.2..2.0, its flat top 0.4 m above the floor at z 3..3.6: columns about 458..597, the top rows about
# 309..323). The floor below the white box (rows 324 to about 450, the same columns: a reflection in a level floor
# stays in the same screen column) must brighten; walls and sky must not change. [Wet] UpAxis = y in the stand-in.
WET_COLUMNS = (237, 403)


def changed_box(image, reference, threshold=1, box=(0, 0, 640, 480)):
    """The bounding box of pixels inside `box` that differ by more than `threshold` (any channel), or None."""
    from PIL import ImageChops
    diff = ImageChops.difference(image.crop(box), reference.crop(box)).convert("L").point(lambda v: 255 if v > threshold else 0)
    found = diff.getbbox()
    return None if found is None else (found[0] + box[0], found[1] + box[1], found[2] + box[0], found[3] + box[1])


def wet_ready(log, images):
    """The screenshots taken once the wet shaders were ready: they are compiled on a worker thread (seconds with the
    game's compiler), started when the plugin loads. A screenshot's time (GfxProbe's driving time) is at least half a
    second behind the plugin's clock, so shots at or after the logged time are safe."""
    import re
    ready = [float(re.match(r"\[\s*([\d.]+)\]", l).group(1)) for l in log.splitlines() if "wet shaders compiled" in l]
    expect(bool(ready), "the wet shaders were compiled (logged)")
    return [(t, image) for t, image in images if ready and t >= ready[0]]


def check_wet_picture(images, against, split=False):
    from PIL import ImageChops
    pairs = paired(images, against)
    expect(len(pairs) >= 3, "screenshots with reflections paired with the reference, got %d" % len(pairs))
    x0 = 322 if split else 0
    for t, image, reference in pairs:
        for at in (((360, 340), (380, 380), (350, 360)) if split else ((320, 340), (320, 380), (280, 360))):
            gain = grey_at(image, at) - grey_at(reference, at)
            expect(gain >= 10, "t=%.0f the floor below the white box at %s brightens by 10 or more, got %+d" % (t, at, gain))
        # (In split screen only the right half is ours: the left is the game's unsmoothed picture.)
        darker = ImageChops.subtract(reference.crop((x0, 0, 640, 480)), image.crop((x0, 0, 640, 480))).getbbox()
        expect(darker is None, "t=%.0f no pixel gets darker, got %s" % (t, darker))
        for name, box in (("sky", (x0, 0, 640, SKY_ROWS + 1)), ("wall left of the box", (max(x0, 0), 130, 230, 190)),
                          ("wall right of the box", (max(x0, 410), 130, 450, 190)), ("white box", (max(x0, 245), 205, 395, 315))):
            if box[0] >= box[2]:
                continue  # wholly on the game's half in split screen
            found = changed_box(image, reference, 1, box)
            expect(found is None, "t=%.0f the %s is unchanged within 1/255, differs in %s" % (t, name, found))
        if not split:
            # Left of the box the floor mirrors the wall (grey 160, 10 m ahead, 4 m high): a floor point z metres ahead
            # sees it while z > 2 m (rows above about 448); nearer, the mirrored ray clears the wall top into the sky.
            gain = grey_at(image, (100, 380)) - grey_at(reference, (100, 380))
            expect(gain >= 3, "t=%.0f the floor left of the box mirrors the wall (brighter), got %+d" % (t, gain))
            near = changed_box(image, reference, 1, (0, 455, 200, 471))
            expect(near is None, "t=%.0f the floor nearer than 2 m (its mirrored ray goes over the wall) is unchanged, differs in %s" % (t, near))
        # The HUD triangle itself (drawn after the pass; the floor around it may carry the wall's reflection).
        expect(image.getpixel((560, 420)) == reference.getpixel((560, 420)), "t=%.0f the HUD triangle is the game's" % t)


def wet_report(images, against):
    """Reported, not failed: how much the low box's flat top (it faces up too) changes."""
    gains = [grey_at(image, (530, 318)) - grey_at(reference, (530, 318)) for t, image, reference in paired(images, against)]
    return "the low box's top changes by %s" % (sorted(set(gains)) if gains else "?")


def wet_common(log):
    expect("aa: replacing the pass-through" in log, "the pass-through is ours (logged)")
    times = [float(f["wet_ms"]) for t, f in look_lines(log) if "wet_ms" in f]
    expect(bool(times) and max(times) > 0, "the reflections' graphics-card time is logged (wet_ms), got %s" % times[:5])
    expect("reset: resources released" in log, "the device reset happened during the run")


def check_scene_wet_disabled(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_wet_aaonly(out, images, log):
    check_aa_common(log, images)


def check_scene_wet(out, images, log):
    """Edge smoothing and wet reflections (as they would be installed), against smoothing alone."""
    wet_common(log)
    check_wet_picture(wet_ready(log, images), "scene-wet-aaonly")
    print("  report: " + wet_report(wet_ready(log, images), "scene-wet-aaonly"))


def reflection_detail(image, reference):
    """How sharp the reflection below the white box is: the summed squared differences between neighbouring pixels of
    (picture minus reference) over the floor below the box (squared, because a plain sum of differences across an
    edge stays the same however far the edge is spread)."""
    from PIL import ImageChops
    diff = ImageChops.subtract(image, reference).crop((230, 322, 410, 420)).convert("L")
    w, h = diff.size
    px = diff.load()
    return sum((px[x + 1, y] - px[x, y]) ** 2 + (px[x, y + 1] - px[x, y]) ** 2 for y in range(h - 1) for x in range(w - 1))


def check_scene_wet_blur(out, images, log):
    """[Wet] Blur = 4 (pixels): the reflection is still there (the floor below the box brightens) but softer than
    scene-wet's sharp one at the same moments (its edge detail at most 80% of it), and nothing gets darker."""
    wet_common(log)
    ready = wet_ready(log, images)
    sharp = reference_shots("scene-wet")
    compared = 0
    for t, image, reference in paired(ready, "scene-wet-aaonly"):
        gain = grey_at(image, (320, 360)) - grey_at(reference, (320, 360))
        expect(gain >= 5, "t=%.0f the floor below the box still brightens, got %+d" % (t, gain))
        if round(t) in sharp:
            soft, crisp = reflection_detail(image, reference), reflection_detail(sharp[round(t)], reference)
            expect(soft <= 0.8 * crisp, "t=%.0f the blurred reflection's detail %d is at most 80%% of the sharp one's %d" % (t, soft, crisp))
            compared += 1
    expect(compared >= 3, "compared with scene-wet at 3 or more moments, got %d" % compared)
    expect("wet settings: strength=0.25 blur=4.0 blur_steps=8" in log, "the blur and its neighbour rays' steps (8, the default) are logged at start")


def check_scene_wet_toggle(out, images, log):
    """ToggleOnly = wet: the SUN line's wet= follows the switch (off(toggle) while off, on while on, once compiled),
    instead of keeping the last value (the review of 2026-10-30, item 3)."""
    states = set(s.get("wet") for s in sun_lines(log))
    expect("off(toggle)" in states and "on" in states, "the SUN line shows wet=on and wet=off(toggle), got %s" % sorted(x for x in states if x))
    expect("toggle: wet off" in log and "toggle: wet on" in log, "the switches are logged")


def check_scene_wet_c333b1a(out, images, log):
    """The reference run of the first wet reflections' build (c333b1a): its reflections are there."""
    wet_common(log)


def check_scene_wet_frozen(out, images, log):
    """Sharp reflections (Blur 0) of the current source give the same pictures as the first build's (c333b1a), from
    the moment both have their shaders (the blur's restructuring must not have changed the sharp path)."""
    wet_common(log)
    ready = wet_ready(log, images)
    reference = reference_shots("scene-wet-c333b1a")
    from PIL import ImageChops
    compared = 0
    for t, image in ready:
        if round(t) in reference and round(t) - 1 in reference and t > 30:
            top = max(hi for lo, hi in ImageChops.difference(image, reference[round(t)]).getextrema())
            expect(top <= 1, "t=%.0f sharp reflections within 1/255 of the first build's, differ by %d" % (t, top))
            compared += 1
    expect(compared >= 3, "compared at 3 or more moments, got %d" % compared)


def check_scene_wet_noaa(out, images, log):
    """Wet on, edge smoothing off: the pass-through is still ours (reflections), with no smoothing: the plain
    picture's diagonal edge keeps its stair-steps, and the reflections show against the plugin disabled."""
    wet_common(log)
    check_wet_picture(wet_ready(log, images), "scene-wet-disabled")
    for t, image in images:
        expect(intermediate_rows(image) == 0, "t=%.0f no smoothing: the diagonal edge has no in-between shades, got %d rows" % (t, intermediate_rows(image)))


def check_scene_wet_off(out, images, log):
    """Both off: exactly the pack's picture (the pass-through is the pack's own draw)."""
    whole_picture_same(images, "wet and smoothing off", against="scene-wet-disabled")
    expect("aa: replacing" not in log, "the pass-through is not replaced")


def check_scene_wet_badmatrix(out, images, log):
    """The view's matrix is all zero (not a view): no reflections, the picture is smoothing alone, and the SUN line
    says wet=off(matrix)."""
    whole_picture_same(images, "no valid matrix: no reflections", against="scene-wet-aaonly")
    suns = sun_lines(log)
    expect(bool(suns) and all(s.get("wet") == "off(matrix)" for s in suns[1:]), "SUN lines say wet=off(matrix): %s" % [s.get("wet") for s in suns][:4])


def check_scene_wet_edge_ref(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_wet_edge(out, images, log):
    """The white box at the screen's left edge (columns 0..70): its reflection fades towards the edge, and no streak
    runs across the floor: where only the wall is above the floor (columns 100..230) the picture is the same as with
    the box in the middle (scene-wet-noaa), within 1/255."""
    ready = wet_ready(log, images)
    expect(len(ready) >= 3, "screenshots with reflections, got %d" % len(ready))
    middle = reference_shots("scene-wet-noaa")
    for t, image, reference in paired(ready, "scene-wet-edge-ref"):
        if round(t) in middle:
            found = changed_box(image, middle[round(t)], 1, (100, 330, 230, 440))
            expect(found is None, "t=%.0f no streak: the floor where only the wall is mirrored is as with the box in the middle, differs in %s" % (t, found))
        edge = max(abs(grey_at(image, (x, 380)) - grey_at(reference, (x, 380))) for x in range(0, 3))
        inner = max(grey_at(image, (x, 380)) - grey_at(reference, (x, 380)) for x in range(40, 66))
        expect(edge <= 2, "t=%.0f at the screen's edge the reflection has faded (change 2/255 or less), got %d" % (t, edge))
        expect(inner >= 3, "t=%.0f inside the edge band the reflection still shows, got %+d" % (t, inner))
        darker = ImageChops_subtract_box(reference, image)
        expect(darker is None, "t=%.0f no pixel gets darker, got %s" % (t, darker))


def ImageChops_subtract_box(a, b):
    from PIL import ImageChops
    return ImageChops.subtract(a, b).getbbox()


def check_scene_split_wet(out, images, log):
    from PIL import ImageChops
    wet_common(log)
    check_wet_picture(wet_ready(log, images), "scene-wet-aaonly", split=True)
    for t, image, reference in paired(images, "scene-wet-disabled"):
        left = ImageChops.difference(image.crop((0, 0, 316, 480)), reference.crop((0, 0, 316, 480))).getbbox()
        expect(left is None, "t=%.0f the left half is the game's own picture, differs in %s" % (t, left))


def check_scene_hostile_wet(out, images, log):
    text = stand_in_output(out)
    reference = os.path.join(HERE, "out", "scene-hostile-off" + SUFFIX)
    expect(state_report(out) == state_report(reference), "device state after the treatment and after the pass-through is what it is without the plugin: %s vs %s" % (state_report(out), state_report(reference)))
    alpha = [l for l in text.splitlines() if l.startswith("ALPHA2")]
    plain = [l for l in stand_in_output(reference).splitlines() if l.startswith("ALPHA2")]
    expect(bool(alpha) and alpha == plain, "the back buffer's alpha after the pass-through is the game's: %s vs %s" % (alpha, plain))
    wet_common(log)
    ready = wet_ready(log, images)
    expect(len(ready) >= 3, "screenshots with reflections, got %d" % len(ready))
    for t, image in ready:
        expect(grey_at(image, (320, 360)) > 150, "t=%.0f the reflection shows despite the hostile state, got %d" % (t, grey_at(image, (320, 360))))


def check_scene_nointz_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_nointz_ao(out, images, log):
    """No depth texture in the frame: occlusion and the depth view skip themselves, the picture is the game's."""
    whole_picture_same(images, "no depth, effects skipped", against="scene-nointz-off")
    expect("no scene depth" in log, "the log says the depth is missing")


def check_scene_hostile_off(out, images, log):
    expect(passes(log) == 0, "no pass when disabled")


def check_scene_hostile_ao(out, images, log):
    expect(state_report(out) == state_report(os.path.join(HERE, "out", "scene-hostile-off" + SUFFIX)), "device state after the treatment is what it is without the plugin: %s vs %s" % (state_report(out), state_report(os.path.join(HERE, "out", "scene-hostile-off" + SUFFIX))))
    expect("ALPHA left=0x40 right=0x40" in stand_in_output(out), "the back buffer's alpha is untouched: %s" % [l for l in stand_in_output(out).splitlines() if "ALPHA" in l])
    check_scene_common(log, images)
    for t, image, reference in paired(images, "scene-hostile-off"):
        expect(darkening(image, reference, FLOOR_FOOT) >= 0.15, "t=%.0f the corner darkens despite the hostile state, got %.1f%%" % (t, 100 * darkening(image, reference, FLOOR_FOOT)))


CHECKS = {"scene-off": check_scene_off, "scene-identity": check_scene_identity, "scene-depth": check_scene_depth,
          "scene-ao": check_scene_ao, "scene-ao-full": check_scene_ao_full, "scene-split-ao": check_scene_split_ao,
          "scene-toggle": check_scene_toggle, "scene-ao-showcase": check_scene_ao_showcase,
          "scene-ao-showcase-notoggle": check_scene_ao_showcase_notoggle, "scene-ao-showcase-fullfail": check_scene_ao_showcase_fullfail,
          "scene-reload-ao-showcase": check_scene_reload_ao_showcase, "scene-toggle-huge": check_scene_toggle_huge,
          "scene-toggle-wrap": check_scene_toggle_wrap,
          "scene-wet-disabled": check_scene_wet_disabled, "scene-wet-aaonly": check_scene_wet_aaonly, "scene-wet": check_scene_wet,
          "scene-wet-noaa": check_scene_wet_noaa, "scene-wet-c333b1a": check_scene_wet_c333b1a, "scene-wet-frozen": check_scene_wet_frozen, "scene-wet-toggle": check_scene_wet_toggle, "scene-wet-blur": check_scene_wet_blur, "scene-wet-off": check_scene_wet_off, "scene-wet-badmatrix": check_scene_wet_badmatrix,
          "scene-wet-edge-ref": check_scene_wet_edge_ref, "scene-wet-edge": check_scene_wet_edge, "scene-split-wet": check_scene_split_wet,
          "scene-hostile-wet": check_scene_hostile_wet, "scene-toggle-only": check_scene_toggle_only, "scene-intz2-ao": check_scene_intz2_ao, "scene-aa": check_scene_aa, "scene-split-aa": check_scene_split_aa,
          "scene-nopass-off": check_scene_nopass_off, "scene-aa-nopass": check_scene_aa_nopass,
          "scene-hostile-aa": check_scene_hostile_aa, "scene-ao-aa": check_scene_ao_aa,
          "scene-toggle-only-aa": check_scene_toggle_only_aa,
          "scene-haze": check_scene_haze, "scene-split-haze": check_scene_split_haze, "scene-ao-haze": check_scene_ao_haze,
          "scene-nointz-haze": check_scene_nointz_haze, "scene-hostile-haze": check_scene_hostile_haze,
          "scene-toggle-only-haze": check_scene_toggle_only_haze,
          "scene-sun-off": check_scene_sun_off, "scene-sun-shafts": check_scene_sun_shafts,
          "scene-sun-split-shafts": check_scene_sun_split_shafts, "scene-sunbehind-shafts": check_scene_sunbehind_shafts, "scene-sun-noinfo-shafts": check_scene_sun_noinfo_shafts,
          "scene-sunside-shafts": check_scene_sunside_shafts, "scene-sun-showsun": check_scene_sun_showsun,
          "scene-sun-wrongfov-showsun": check_scene_sun_wrongfov_showsun, "scene-sun-noplat-showsun": check_scene_sun_noplat_showsun,
          "scene-sun-badplat-showsun": check_scene_sun_badplat_showsun, "scene-sun-ao-fov60": check_scene_sun_ao_fov60, "scene-shadows-unlock": check_scene_shadows_unlock, "scene-shadows-off": check_scene_shadows_off, "scene-shadowswrong-unlock": check_scene_shadowswrong_unlock, "scene-shadowsro-unlock": check_scene_shadowsro_unlock, "scene-sun-ao-wrongfov": check_scene_sun_ao_wrongfov, "scene-sun-badplat-ao": check_scene_sun_badplat_ao, "scene-sun-ao-wrongnear": check_scene_sun_ao_wrongnear, "scene-sun-ao-wrongnear-off": check_scene_sun_ao_wrongnear_off, "scene-sun-badplat-ao-fromgame": check_scene_sun_badplat_ao_fromgame, "scene-sunleft-split-showsun": check_scene_sunleft_split_showsun,
          "scene-sun-hostile-off": check_scene_sun_hostile_off, "scene-sun-hostile-shafts": check_scene_sun_hostile_shafts,
          "scene-nointz-off": check_scene_nointz_off, "scene-nointz-ao": check_scene_nointz_ao,
          "scene-hostile-off": check_scene_hostile_off, "scene-hostile-ao": check_scene_hostile_ao,
          "hostile-off": check_hostile_off, "hostile-identity": check_hostile_identity, "hostile-split": check_hostile_split,
          "gap-exposure": check_gap_exposure, "both": check_both, "exposure": check_exposure, "split-exposure": check_split_exposure, "bloom": check_bloom, "none": check_none, "off": check_off, "identity": check_identity, "split-identity": check_split_identity,
          "broken": check_broken}


def main():
    variant = sys.argv[1]
    out = os.path.join(HERE, "out", variant + SUFFIX)
    images = shots(out)
    expect(len(images) >= 10, "at least ten screenshots, got %d" % len(images))
    path = os.path.join(out, "VisualBridge.log")
    log = open(path, encoding="utf-8", errors="replace").read() if os.path.isfile(path) else ""
    CHECKS[variant](out, images, log)
    print("%s: %s" % (variant, "FAIL\n  " + "\n  ".join(failures) if failures else "PASS"))
    sys.exit(1 if failures else 0)


main()
