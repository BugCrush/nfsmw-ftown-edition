"""Checks what GfxProbe recorded from the d3d9-frame stand-in against the frame it is known to draw.

    python gfx/tests/check-frame.py <out folder> <check> [<check> ...] [--dxvk]

Checks: framemap (more are added per task; "all" runs every one).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import gfxlog

failures = []


def expect(ok, what):
    if not ok:
        failures.append(what if len(what) <= 400 else what[:400] + " ...")


def near(actual, wanted, what, tolerance=0.005):
    expect(abs(float(actual) - wanted) <= tolerance, "%s: wanted %s, got %s" % (what, wanted, actual))


def start(lines):
    """Log time at which the stand-in's own clock read 0: it reports "driving" at its 1 s mark. The probe's
    clock starts when it is loaded, which is before the device exists (much earlier under DXVK)."""
    on = [t for t, tag, f in lines if tag == "DRIVING" and f.get("state") == "1"]
    return on[0] - 1.0 if on else 0.0


def stages_by_size(report):
    return {(s["kind"], s["size"]): s for s in report["STAGE"]}


def check_framemap(out, lines, dxvk):
    reps = gfxlog.reports(lines)
    expect(len(reps) >= 2, "at least two reports, got %d" % len(reps))
    targets = {f["id"]: f for t, tag, f in lines if tag == "TARGET"}
    # The 8-pixel-high surfaces are the extra targets the stand-in makes after its last frame (overflow check).
    kinds = sorted((f["kind"], f["size"], f["fmt"]) for f in targets.values() if not f["size"].endswith("x8"))
    expect(kinds == [("backbuffer", "640x480", "X8R8G8B8"), ("texture", "256x256", "A8R8G8B8"),
                     ("texture", "64x64", "A16B16G16R16F")], "three targets, got %s" % kinds)
    for rep in reps:
        at = "report at %.0f s: " % rep["t"]
        expect(rep["FRAMEMAP"]["overflow"] == "0", at + "no overflow")
        by = stages_by_size(rep)
        expect(sorted(by) == [("backbuffer", "640x480"), ("texture", "256x256"), ("texture", "64x64")],
               at + "three stages, got %s" % sorted(by))
        if len(by) != 3:
            continue
        wide, tex, back = by[("texture", "64x64")], by[("texture", "256x256")], by[("backbuffer", "640x480")]
        for s, order, draws, tris, clears, copies in ((wide, 1, 0, 0, 1, 0), (tex, 2, 3, 3, 1, 0), (back, 3, 6, 11, 1, 1)):
            name = at + s["size"] + " "
            near(s["order"], order, name + "order")
            near(s["draws"], draws, name + "draws")
            near(s["tris"], tris, name + "triangles")
            near(s["clears"], clears, name + "clears")
            near(s["copies"], copies, name + "copies")
            near(s["seen"], 100.0, name + "seen in every frame", 0.05)
            expect(s["visit"] == "1", name + "first visit")
            expect(s["ms"] == "0", name + "not multisampled")
        expect(len(rep["SHAPE"]) == 1, at + "one frame shape, got %d" % len(rep["SHAPE"]))
        if rep["SHAPE"]:
            near(rep["SHAPE"][0]["share"], 100.0, at + "shape share", 0.05)
            expect(rep["SHAPE"][0]["seq"] == ",".join((wide["target"], tex["target"], back["target"])), at + "shape order")
        expect(len(rep["COPY"]) == 1, at + "one copy pair, got %d" % len(rep["COPY"]))
        if rep["COPY"]:
            c = rep["COPY"][0]
            expect((c["src"], c["dst"]) == (tex["target"], back["target"]), at + "copy from texture target to back buffer")
            near(c["per_frame"], 1.0, at + "copies per frame")
    # Time split: the stage times of a timed frame must add up to the frame, and frame + present must
    # match the frame rate the report itself implies.
    timed = [rep for rep in reps if rep["TIME"]]
    expect(bool(timed), "at least one report with a TIME line")
    for rep in timed:
        at = "report at %.0f s: " % rep["t"]
        time = rep["TIME"][0]
        frame_ms, present_ms = float(time["frame_ms"]), float(time["present_ms"])
        parts = sum(float(s["in_ms"]) + float(s["out_ms"]) for s in rep["STAGE"])
        parts += float(time["loose_in_ms"]) + float(time["loose_out_ms"])
        expect(abs(parts - frame_ms) <= 0.05 * frame_ms + 0.01, at + "stage times add up to the frame: %.4f vs %.4f" % (parts, frame_ms))
        period = 4000.0 / float(rep["FRAMEMAP"]["frames"])
        expect(abs(frame_ms + present_ms - period) <= 0.25 * period, at + "frame+present %.2f ms vs %.2f ms per frame" % (frame_ms + present_ms, period))
        expect(float(time["clock_ns"]) > 0, at + "clock cost measured")
    expect(bool(glob.glob(os.path.join(out, "*_d3d9.log"))) == dxvk, "DXVK log present only with --dxvk")


def check_targets_overflow(out, lines, dxvk):
    text = open(os.path.join(out, "GfxProbe.log"), encoding="utf-8", errors="replace").read()
    expect(text.count("OVERFLOW targets=") == 1, "the overflow is reported exactly once")
    ids = [f["id"] for t, tag, f in lines if tag == "TARGET"]
    expect(len(ids) == 128 and len(set(ids)) == 128, "128 distinct target numbers, got %d" % len(set(ids)))


def check_effects(out, lines, dxvk):
    effects = [f for t, tag, f in lines if tag == "EFFECT"]
    names = [f["name"] for f in effects]
    # A is loaded twice (released in between), B once, and one effect by number.
    expect(names == ["IDI_TESTA_FX", "IDI_TESTA_FX", "IDI_TESTB_FX", "#77"], "effects in load order, got %s" % names)
    # The first A is released before the second is loaded: its record must go, or the probe would later
    # read a freed effect (it crashed that way under DXVK, where the address is not reused).
    order = [(tag, f.get("name")) for t, tag, f in lines if tag in ("EFFECT", "EFFECTGONE")]
    expect(order[:3] == [("EFFECT", "IDI_TESTA_FX"), ("EFFECTGONE", "IDI_TESTA_FX"), ("EFFECT", "IDI_TESTA_FX")],
           "the released effect is forgotten before the next is loaded, got %s" % order[:3])
    expect(len([1 for tag, name in order if tag == "EFFECTGONE"]) == 1, "only the one released effect is forgotten")
    techs = sorted((f["fx"], f["name"], f["passes"]) for t, tag, f in lines if tag == "TECH" and f["fx"] != "#77")
    expect(techs == [("IDI_TESTA_FX", "Main", "1"), ("IDI_TESTA_FX", "Main", "1"), ("IDI_TESTB_FX", "Bright", "1"),
                     ("IDI_TESTB_FX", "Plain", "1")], "techniques, got %s" % techs)
    params = {(f["fx"], f["name"]): f for t, tag, f in lines if tag == "PARAM"}
    tint = params.get(("IDI_TESTA_FX", "g_vTint"), {})
    expect((tint.get("class"), tint.get("type"), tint.get("cols"), tint.get("value")) == ("vector", "float", "4", "1,0,0,1"),
           "A g_vTint is a float4 of 1,0,0,1, got %s" % tint)
    exposure = params.get(("IDI_TESTB_FX", "g_fExposure"), {})
    expect((exposure.get("class"), exposure.get("value")) == ("scalar", "0.5"), "B g_fExposure starts at 0.5, got %s" % exposure)
    big = params.get(("IDI_TESTB_FX", "g_avBig"), {})
    expect((big.get("elems"), big.get("bytes")) == ("32", "512"), "B g_avBig is 32 vectors, 512 bytes, got %s" % big)
    expect(big.get("value") == ",".join(["0"] * 16), "B g_avBig shows its first 16 numbers, got %s" % big.get("value"))
    expect(params.get(("IDI_TESTB_FX", "g_tDiffuse"), {}).get("type") == "texture", "B g_tDiffuse is a texture")
    # A setting that changes at every poll is logged in full only three times; after that it is counted
    # and summed up once per report (FXCHANGE), so per-draw settings cannot flood the log.
    spin = [f for t, tag, f in lines if tag == "FXVALUE" and f["name"] == "g_vSpin"]
    expect(len(spin) == 3, "the ever-changing setting is logged in full three times, got %d" % len(spin))
    counted = {}
    for t, tag, f in lines:
        if tag == "FXCHANGE":
            counted[f["name"]] = counted.get(f["name"], 0) + int(f["changes"])
    expect(counted.get("g_vSpin", 0) >= 8, "its changes are counted per report, got %s" % counted)
    expect(counted.get("g_fExposure") == 1 and counted.get("g_tDiffuse") == 1, "one counted change each for the two settings set once, got %s" % counted)
    changes = [(t, f) for t, tag, f in lines if tag == "FXVALUE" and f["name"] != "g_vSpin"]
    got = sorted((f["fx"], f["name"], f["value"]) for t, f in changes)
    expect(got == [("IDI_TESTB_FX", "g_fExposure", "0.75"), ("IDI_TESTB_FX", "g_tDiffuse", "tex:256x256:A8R8G8B8")],
           "exactly two value changes, got %s" % got)
    for t, f in changes:
        expect(4.8 <= t - start(lines) <= 6.3, "%s changed at 5 s (polled once a second), logged at %.1f s" % (f["name"], t - start(lines)))
    for rep in gfxlog.reports(lines):
        at = "report at %.0f s: " % rep["t"]
        by = stages_by_size(rep)
        if len(by) != 3:
            continue
        tex, back = by[("texture", "256x256")], by[("backbuffer", "640x480")]
        labels = sorted((l["target"], l["fx"], l["tech"], float(l["draws"])) for l in rep["LABEL"])
        wanted = sorted([(tex["target"], "IDI_TESTA_FX", "Main", 3.0), (back["target"], "IDI_TESTB_FX", "Bright", 5.0),
                         (back["target"], "(none)", "-", 1.0)])
        expect(labels == wanted, at + "draws labelled by effect and technique, got %s" % labels)


def check_resources(out, lines, dxvk):
    created = sorted((f["kind"], f["size"], f["fmt"]) for t, tag, f in lines if tag == "CREATE" and f["size"] in ("256x256", "64x64"))
    expect(created == [("texture-target", "256x256", "A8R8G8B8"), ("texture-target", "64x64", "A16B16G16R16F")],
           "two texture targets created, got %s" % created)
    textures = [f for t, tag, f in lines if tag == "TEXTURES"]
    expect(bool(textures) and textures[0]["total"] == "2" and textures[0]["top"] == "32x32:DXT1x2",
           "two ordinary 32x32 DXT1 textures counted, got %s" % textures[:1])
    shaders = [f for t, tag, f in lines if tag == "SHADER"]
    expect({f["kind"] for f in shaders} == {"vs", "ps"}, "vertex and pixel shaders logged")
    expect(all(f["version"] in ("vs_2_0", "ps_2_0") for f in shaders), "all shaders are version 2.0")
    expect(len({(f["kind"], f["hash"]) for f in shaders}) == len(shaders), "each distinct shader logged once")
    runs = glob.glob(os.path.join(out, "test", "run-*"))
    expect(len(runs) == 1, "one run folder, got %d" % len(runs))
    for f in shaders:
        path = os.path.join(runs[0], "shaders", "%s_%s.bin" % (f["kind"], f["hash"])) if runs else ""
        expect(os.path.isfile(path) and os.path.getsize(path) == int(f["bytes"]), "shader file with %s bytes: %s" % (f["bytes"], path))
        if os.path.isfile(path):
            head = open(path, "rb").read(4)
            expect(head == (b"\x00\x02\xfe\xff" if f["kind"] == "vs" else b"\x00\x02\xff\xff"), "version token in " + path)


def check_watch(out, lines, dxvk):
    watch = [(t, f) for t, tag, f in lines if tag == "WATCH"]
    # The line is "WATCH name=nowhere OFF address=0x00000010 not readable"; the parser joins "OFF" to the name.
    expect(any(f.get("name") == "nowhere OFF" for t, f in watch), "the unreadable entry is switched off")
    values = [(t, f["value"], f["was"]) for t, f in watch if f.get("name") == "testvalue" and "value" in f]
    expect([(v, w) for t, v, w in values] == [("7", "-"), ("9", "7")], "testvalue read as 7, then 9, got %s" % values)
    if len(values) == 2:
        expect(4.8 <= values[1][0] - start(lines) <= 5.3, "testvalue changed at 5 s, logged at %.1f s" % (values[1][0] - start(lines)))
    spinner = [t for t, f in watch if f.get("name") == "spinner" and "value" in f]
    expect(len(spinner) >= 20, "the spinner is logged, got %d lines" % len(spinner))
    per_second = {}
    for t in spinner:
        per_second[int(t)] = per_second.get(int(t), 0) + 1
    # The limit is per second of the probe's clock; a log second can straddle two of them.
    expect(max(per_second.values() or [0]) <= 20, "at most ten spinner lines a second, got %s" % per_second)
    driving = [(t, f["state"]) for t, tag, f in lines if tag == "DRIVING"]
    expect([s for t, s in driving] == ["1", "0", "1"], "driving on at 1 s, off at 8 s, on at 10 s, got %s" % driving)


def check_shots(out, lines, dxvk):
    from PIL import Image
    shots = [(t, f) for t, tag, f in lines if tag == "SHOT"]
    expect([f["n"] for t, f in shots] == ["1", "2", "3", "4"], "four screenshots, got %s" % [f["n"] for t, f in shots])
    for (t, f), wanted in zip(shots, (2.0, 4.0, 6.0, 8.0)):
        near(f["t"], wanted, "shot %s driving time" % f["n"], 0.1)
        expect(f["ok"] == "1", "shot %s saved" % f["n"])
        expect(not 8.05 < t - start(lines) < 9.95, "no shot while paused (shot %s at %.1f s)" % (f["n"], t - start(lines)))
        if os.path.isfile(f["path"]):
            image = Image.open(f["path"])
            expect(image.size == (640, 480), "shot %s is 640x480" % f["n"])
            expect(image.getpixel((320, 240)) == (200, 20, 40), "shot %s centre colour, got %s" % (f["n"], image.getpixel((320, 240))))
            expect(image.getpixel((40, 40)) == (10, 200, 30), "shot %s shows the copied target top-left" % f["n"])
        else:
            expect(False, "shot file exists: " + f["path"])


def check_dissect(out, lines, dxvk):
    from PIL import Image
    done = [f for t, tag, f in lines if tag == "DISSECT"]
    expect(len(done) == 1, "one dissection, got %d" % len(done))
    if len(done) != 1:
        return
    d = done[0]
    near(d["t"], 3.0, "dissected at 3 s of driving", 0.1)
    expect((d["draws"], d["images"]) == ("9", "3"), "9 draws and 3 images, got %s draws, %s images" % (d["draws"], d["images"]))
    calls = gfxlog.parse_calls(os.path.join(d["dir"], "calls.txt"))
    expect(len(calls) == int(d["lines"]), "calls.txt has the %s lines the log reports, got %d" % (d["lines"], len(calls)))
    count = {}
    for call, f in calls:
        count[call] = count.get(call, 0) + 1
    for call, wanted in (("frame", 1), ("target", 4), ("clear", 3), ("copy", 1), ("fx-begin", 2), ("fx-end", 2), ("draw", 9), ("image", 3)):
        expect(count.get(call, 0) == wanted, "%d '%s' lines, got %d" % (wanted, call, count.get(call, 0)))
    targets = {f["id"]: (f["kind"], f["size"]) for t, tag, f in lines if tag == "TARGET"}
    seq = [targets.get(f["target"]) for call, f in calls if call == "target"]
    expect(seq == [("backbuffer", "640x480"), ("texture", "64x64"), ("texture", "256x256"), ("backbuffer", "640x480")],
           "targets in order (the first is the one current at frame start), got %s" % seq)
    known = {f["hash"] for t, tag, f in lines if tag == "SHADER"}
    draws = [f for call, f in calls if call == "draw"]
    for i, f in enumerate(draws):
        fx, tech, prims = (("IDI_TESTA_FX", "Main", "1") if i < 3 else ("IDI_TESTB_FX", "Bright", "2") if i < 8 else ("(none)", "-", "1"))
        expect((f["fx"], f["tech"], f["prims"], f["tris"], f["call"]) == (fx, tech, prims, prims, "DrawPrimitiveUP"),
               "draw %d is %s/%s with %s triangles, got %s" % (i + 1, fx, tech, prims, f))
        expect(f["filt0"] == "linear/point/none/1", "draw %d filtering, got %s" % (i + 1, f["filt0"]))
        expect(f["tex"] == "-", "draw %d has no texture bound" % (i + 1))
        if i < 8:
            expect(f["vs"] in known and f["ps"] in known, "draw %d names shaders the probe saved" % (i + 1))
        else:
            expect((f["vs"], f["ps"]) == ("00000000", "00000000"), "draw 9 uses no shaders")
    expect(any(f.get("kind") == "vs" and f.get("reg") == "40" and f.get("values") == "0.25,0.5,0.75,1"
               for call, f in calls if call == "constants"), "the vertex constant written at register 40 is listed")
    expect(any(f.get("name") == "ALPHABLENDENABLE" and f.get("value") == "0x0" for call, f in calls if call == "state"),
           "the blend state write is listed")
    images = [f for call, f in calls if call == "image"]
    wanted = (("64x64", (255, 128, 0)), ("256x256", (10, 200, 30)), ("640x480", (200, 20, 40)))
    for f, (size, colour) in zip(images, wanted):
        expect(f["ok"] == "1" and f["size"] == size, "image of the %s target saved, got %s" % (size, f))
        path = os.path.join(d["dir"], f["file"])
        if os.path.isfile(path):
            image = Image.open(path)
            w, h = image.size
            got = image.getpixel((w // 2, h // 2))
            expect(all(abs(a - b) <= 1 for a, b in zip(got, colour)), "%s image centre colour %s, got %s" % (size, colour, got))
            if size == "640x480":
                expect(image.getpixel((40, 40)) == (10, 200, 30), "back buffer image is taken after the copy")
        else:
            expect(False, "image file exists: " + path)
    if images:
        wide = images[0]
        near(wide.get("min", -1), 0.0, "wide target minimum", 0.01)
        near(wide.get("max", -1), 1.0, "wide target maximum", 0.01)
        near(wide.get("mean", -1), (1.0 + 128 / 255.0) / 3, "wide target mean", 0.01)
    # The frame map of every report, including the one that contains the dissected frame, stays exact.
    check_framemap(out, lines, dxvk)


def check_tools(out, lines, dxvk):
    import json
    import subprocess
    import tempfile
    from PIL import Image
    tools = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools")
    log = os.path.join(out, "GfxProbe.log")

    # Review focus: a path with spaces and "=" survives the parser.
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("[   1.000] SHOT n=1 t=2.0 ok=1 path=C:\\Need For Speed\\a=b\\shot 1.bmp\n")
    parsed = gfxlog.parse(f.name)
    os.unlink(f.name)
    expect(parsed == [(1.0, "SHOT", {"n": "1", "t": "2.0", "ok": "1", "path": "C:\\Need For Speed\\a=b\\shot 1.bmp"})],
           "parser keeps a path with spaces and '=' whole, got %s" % parsed)

    result = subprocess.run([sys.executable, os.path.join(tools, "gfx-report.py"), log, "--all", "--json"], capture_output=True, text=True)
    expect(result.returncode == 0, "gfx-report runs: " + result.stderr[-300:])
    if result.returncode == 0:
        report = json.loads(result.stdout)
        stages = {(s["kind"], s["size"]): s for s in report["stages"]}
        tex, back = stages.get(("texture", "256x256"), {}), stages.get(("backbuffer", "640x480"), {})
        near(tex.get("draws", -1), 3, "report: texture stage draws")
        near(back.get("draws", -1), 6, "report: back buffer draws")
        near(back.get("tris", -1), 11, "report: back buffer triangles")
        expect(tex.get("labels") == {"IDI_TESTA_FX/Main": 3.0}, "report: texture stage labels, got %s" % tex.get("labels"))
        expect(back.get("labels") == {"IDI_TESTB_FX/Bright": 5.0, "(none)/-": 1.0}, "report: back buffer labels, got %s" % back.get("labels"))
        near(report["draws_per_frame"], 9, "report: draws per frame")
        expect(sorted(report["effects"]) == ["#77", "IDI_TESTA_FX", "IDI_TESTB_FX"], "report: effects, got %s" % sorted(report["effects"]))
        by_name = {c["name"]: c for c in report["fxchanges"]} if "fxchanges" in report else {}
        expect(by_name.get("g_vSpin", {}).get("changes", 0) >= 8, "report: the ever-changing setting with its count, got %s" % by_name.get("g_vSpin"))
        expect((by_name.get("g_fExposure", {}).get("changes"), by_name.get("g_fExposure", {}).get("last")) == (1, "0.75"),
               "report: g_fExposure changed once, to 0.75, got %s" % by_name.get("g_fExposure"))
        expect(any("targets" in w for w in report.get("warnings", [])), "report: warns that the target table overflowed, got %s" % report.get("warnings"))
        report["fxvalues"] = [c for c in report["fxvalues"] if c["name"] != "g_vSpin"]
        expect([(c["name"], c["value"]) for c in report["fxvalues"]] == [("g_fExposure", "0.75"), ("g_tDiffuse", "tex:256x256:A8R8G8B8")]
               or [(c["name"], c["value"]) for c in report["fxvalues"]] == [("g_tDiffuse", "tex:256x256:A8R8G8B8"), ("g_fExposure", "0.75")],
               "report: value changes, got %s" % report["fxvalues"])
        expect(report["shots"] == 4, "report: four shots, got %s" % report["shots"])
        expect(len(report["dissections"]) == 1, "report: one dissection")
        if report["dissections"]:
            d = report["dissections"][0]
            expect(d["draws"] == 9 and d["not_16x"] == 9, "report: 9 dissected draws, none 16x-filtered, got %s" % d)
            rows = sorted((r["size"], r["label"], r["draws"]) for r in d["not_16x_by_stage"])
            expect(rows == [("256x256", "IDI_TESTA_FX/Main", 3), ("640x480", "(none)/-", 1), ("640x480", "IDI_TESTB_FX/Bright", 5)],
                   "report: non-16x draws by stage and effect, got %s" % rows)
        expect(report["time"]["timed_frames"] >= 1 and report["time"]["frame_ms"] > 0, "report: time split present")
    text = subprocess.run([sys.executable, os.path.join(tools, "gfx-report.py"), log, "--all"], capture_output=True, text=True)
    expect(text.returncode == 0 and "IDI_TESTB_FX/Bright" in text.stdout and "640x480" in text.stdout, "gfx-report text output")

    # A stage that was never in a timed frame must read as "not measured", not as 0 ms, and overflows
    # must be shown. Checked on a small made-up log.
    made_up = [
        "[   1.000] TARGET id=T0 kind=backbuffer size=640x480 fmt=X8R8G8B8 ms=0",
        "[  15.000] FRAMEMAP frames=100 driving=1.00 stages=1 overflow=2",
        "[  15.000] STAGE order=1.00 target=T0 visit=1 kind=backbuffer size=640x480 fmt=X8R8G8B8 ms=0 seen=100.0 draws=5.00 tris=5.00 clears=1.00 copies=0.00 timed=0 in_ms=0.0000 out_ms=0.0000",
        "[  15.000] OVERFLOW labels=3 keys=0 shapes=0 copies=0 stages=2",
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("\n".join(made_up) + "\n")
    as_json = subprocess.run([sys.executable, os.path.join(tools, "gfx-report.py"), f.name, "--json"], capture_output=True, text=True)
    as_text = subprocess.run([sys.executable, os.path.join(tools, "gfx-report.py"), f.name], capture_output=True, text=True)
    os.unlink(f.name)
    expect(as_json.returncode == 0 and as_text.returncode == 0, "gfx-report runs on the made-up log: " + (as_json.stderr + as_text.stderr)[-300:])
    if as_json.returncode == 0:
        made = json.loads(as_json.stdout)
        expect(made["stages"][0]["in_ms"] is None and made["stages"][0]["timed"] == 0, "an untimed stage has no time, got %s" % made["stages"][0])
        expect(len(made["warnings"]) >= 2, "both overflow notices become warnings, got %s" % made["warnings"])
    expect("n/a" in as_text.stdout and "WARNING" in as_text.stdout, "the text report shows n/a and a warning")

    runs = glob.glob(os.path.join(out, "test", "run-*"))
    if not runs:
        expect(False, "run folder exists")
        return
    sheets = os.path.join(out, "sheets")
    result = subprocess.run([sys.executable, os.path.join(tools, "contact-sheet.py"), os.path.join(runs[0], "shots"), "--out", sheets],
                            capture_output=True, text=True)
    expect(result.returncode == 0, "contact-sheet runs: " + result.stderr[-300:])
    made = sorted(glob.glob(os.path.join(sheets, "sheet-*.png")))
    expect(len(made) == 1, "four shots make one sheet, got %d" % len(made))
    if made:
        sheet = Image.open(made[0]).convert("RGB")
        expect(sheet.size == (1920, 384), "sheet of one row is 1920x384, got %s" % (sheet.size,))
        for column in range(4):
            got = sheet.getpixel((column * 480 + 240, 24 + 180))
            expect(all(abs(a - b) <= 2 for a, b in zip(got, (200, 20, 40))), "tile %d centre colour, got %s" % (column + 1, got))
        expect(sheet.getpixel((4 * 480 - 5, 200)) != (0, 0, 0), "fourth tile is filled")

    shaders = sorted(glob.glob(os.path.join(runs[0], "shaders", "*.bin")))
    result = subprocess.run([sys.executable, os.path.join(tools, "fx-inspect.py"), "shader"] + shaders + ["--json"], capture_output=True, text=True)
    expect(result.returncode == 0, "fx-inspect shader runs: " + result.stderr[-300:])
    if result.returncode == 0:
        info = json.loads(result.stdout)
        direct = [s for s in info if [c["name"] for c in s["constants"]] == ["kTestColor"]]
        expect(len(direct) == 1 and direct[0]["version"] == "ps_2_0"
               and direct[0]["constants"][0] == {"name": "kTestColor", "set": "float", "index": 0, "count": 1},
               "the directly created pixel shader expects kTestColor in c0, got %s" % direct)
        named = {c["name"] for s in info for c in s["constants"] + s["preshader"]}
        expect({"g_fExposure", "g_avBig", "g_vTint"} <= named, "the effects' shaders name their settings, got %s" % sorted(named))
    extracted = os.path.join(out, "effects")
    result = subprocess.run([sys.executable, os.path.join(tools, "fx-inspect.py"), "effects", os.path.join(out, "d3d9-frame.exe"), "--out", extracted],
                            capture_output=True, text=True)
    expect(result.returncode == 0, "fx-inspect effects runs: " + result.stderr[-300:])
    here = os.path.dirname(os.path.abspath(__file__))
    for name, source in (("IDI_TESTA_FX", "a.fx"), ("IDI_TESTB_FX", "b.fx"), ("77", "a.fx")):
        path = os.path.join(extracted, name + ".fx")
        expect(os.path.isfile(path) and open(path, "rb").read() == open(os.path.join(here, source), "rb").read(),
               "extracted %s equals %s" % (name, source))


def check_off(out, lines, dxvk):
    text = open(os.path.join(out, "GfxProbe.log"), encoding="utf-8", errors="replace").read()
    expect("device hooks installed" in text, "the probe still loads")
    # TRACE is its own switch ([Trace] TargetWidth, set in the test's .ini), not one of the parts.
    tags = sorted({tag for t, tag, f in lines} - {"TRACE"})
    expect(tags == [], "no part writes anything when all are off, got %s" % tags)
    expect("Panel" not in text, "no panel window or thread when the panel is off")
    expect("Effect import hook" not in text, "the effect import is not patched")
    expect(not glob.glob(os.path.join(out, "test", "run-*")), "no run folder is created")
    expect(len(glob.glob(os.path.join(out, "test", "*.bmp"))) == 1, "the grid capture still works (one BMP)")


def check_panel(out, lines, dxvk):
    from PIL import Image
    t0 = start(lines)
    events = [(round(t - t0), tag, f.get("state")) for t, tag, f in lines if tag == "PANEL"]
    expect([e[2] for e in events] == ["shown", "hidden", "shown"], "panel shown while driving, hidden on pause, shown again, got %s" % events)
    if len(events) == 3:
        expect([e[0] for e in events] == [1, 8, 10], "panel follows driving at 1 s, 8 s and 10 s, got %s" % [e[0] for e in events])
    data = [f for t, tag, f in lines if tag == "PANELDATA"]
    expect(len(data) >= 2, "the panel's numbers are logged at the snapshot and when it hides, got %d lines" % len(data))
    for f in data:
        near(f["draws"], 9, "panel: draws per frame", 0.05)
        near(f["tris"], 14, "panel: triangles per frame", 0.05)
        near(f["effects"], 3, "panel: the two texture stages are 'effects' (3 draws)", 0.05)
        near(f["hud"], 6, "panel: the back buffer stage with 6 draws is 'HUD'", 0.05)
        for job in ("shadows", "reflect", "main", "logic"):
            near(f[job], 0, "panel: no draws for " + job, 0.05)
        parts = sum(float(f[k]) for k in ("shadows_ms", "reflect_ms", "main_ms", "logic_ms", "effects_ms", "hud_ms"))
        expect(float(f["frame_ms"]) > 0 and abs(parts - float(f["frame_ms"])) <= 0.25 * float(f["frame_ms"]) + 0.005,
               "panel: the jobs' times add up to the frame: %.4f vs %s" % (parts, f["frame_ms"]))
    # Timing every frame (EveryNFrames = 1): every counted frame is a timed frame.
    for rep in gfxlog.reports(lines):
        if rep["TIME"]:
            frames, timed = int(rep["FRAMEMAP"]["frames"]), int(rep["TIME"][0]["timed_frames"])
            expect(frames - timed <= 2, "report at %.0f s: every frame timed (%d of %d)" % (rep["t"], timed, frames))
    runs = glob.glob(os.path.join(out, "test", "run-*"))
    path = os.path.join(runs[0], "panel.bmp") if runs else ""
    expect(os.path.isfile(path), "panel snapshot saved: " + path)
    if os.path.isfile(path):
        image = Image.open(path).convert("RGB")
        expect(image.size == (340, 196), "panel is 340x196, got %s" % (image.size,))
        colours = set(image.getdata())
        # Bars start at x=84; row j is at y = 25 + 17*j (rows: shadows, reflect, main, logic, effects, HUD).
        # A job with time has a bar in its colour; one without shows the empty grey track. Labels and
        # graph lines use the job colours too, so the bar itself is sampled.
        bar = lambda job: image.getpixel((86, 25 + 17 * job + 7))
        expect(bar(4) == (208, 112, 79), "the effects bar is drawn in its colour, got %s" % (bar(4),))
        expect(bar(5) == (184, 92, 142), "the HUD bar is drawn in its colour, got %s" % (bar(5),))
        expect(bar(2) == (60, 60, 60), "the main-view bar is empty: the stand-in has no such stage, got %s" % (bar(2),))
        expect((255, 255, 255) in colours, "text is drawn")


def check_tint(out, lines, dxvk):
    """The tint proof beside GfxProbe: in the stand-in effect A is "after" and effect B is "before", so the
    tint lands on the back buffer after its clear and before effect B's quads. What is drawn later (the
    quads, the white triangle, the copy) must be untinted, like the game's HUD."""
    from PIL import Image
    text = open(os.path.join(out, "TintProof.log"), encoding="utf-8", errors="replace").read()
    expect("hooked Present" in text and "'after' effect IDI_TESTA_FX" in text and "'before' effect IDI_TESTB_FX" in text, "the proof found its effects")
    counts = [dict(kv.split("=") for kv in l.split("TINT ")[1].split()) for l in text.splitlines() if " TINT " in l]
    tinted, frames, failed = (sum(int(c[k]) for c in counts[1:]) for k in ("tinted", "frames", "failed"))
    expect(frames > 100 and tinted == frames and failed == 0, "every frame tinted exactly once: %d of %d, %d failed" % (tinted, frames, failed))
    shots = [f for t, tag, f in lines if tag == "SHOT" and os.path.isfile(f.get("path", ""))]
    expect(len(shots) == 4, "GfxProbe still takes its four screenshots beside the proof, got %d" % len(shots))
    for f in shots:
        image = Image.open(f["path"])
        centre, copied, white, quad = (image.getpixel(p) for p in ((320, 240), (40, 40), (560, 410), (600, 40)))
        # (200,20,40) under a quarter-strength magenta (255,0,255): (214,15,94).
        expect(all(abs(a - b) <= 1 for a, b in zip(centre, (214, 15, 94))), "shot %s: the picture is tinted, got %s" % (f["n"], centre))
        expect(copied == (10, 200, 30), "shot %s: the copy made afterwards is not tinted, got %s" % (f["n"], copied))
        expect(white == (255, 255, 255), "shot %s: the triangle drawn afterwards is not tinted, got %s" % (f["n"], white))
        expect(quad[0] < 5 and quad[1] < 5 and quad[2] > 100, "shot %s: effect B still draws blue after the proof's draw, got %s" % (f["n"], quad))
    # GfxProbe keeps counting beside the proof: the tint is one more draw on the back buffer.
    for rep in gfxlog.reports(lines):
        by = stages_by_size(rep)
        if ("backbuffer", "640x480") in by:
            near(by[("backbuffer", "640x480")]["draws"], 7, "report at %.0f s: back buffer draws with the tint" % rep["t"])
            near(by[("texture", "256x256")]["draws"], 3, "report at %.0f s: texture stage untouched" % rep["t"])
    expect(len(gfxlog.reports(lines)) >= 2, "GfxProbe kept reporting")


def check_trace(out, lines, dxvk):
    """[Trace] TargetWidth = 256: when the stand-in switches to its 256x256 target, the probe logs where the call came
    from (the code that called SetRenderTarget and the program's own return addresses found on the stack), each
    address as module+offset; one line per distinct call place, at most [Trace] Max."""
    traces = [f for t, tag, f in lines if tag == "TRACE"]
    expect(bool(traces), "a TRACE line for the 256x256 target")
    expect(all(f.get("target") == "256x256" for f in traces), "traces only for the 256x256 target: %s" % [f.get("target") for f in traces][:4])
    expect(all("d3d9-frame.exe+0x" in f.get("caller", "") for f in traces), "the caller is the stand-in's code: %s" % [f.get("caller") for f in traces][:3])
    expect(len(traces) <= 4, "at most Max (4) lines, got %d" % len(traces))
    expect(all("d3d9-frame.exe+0x" in f.get("stack", "") for f in traces), "the stack lists the stand-in's return addresses: %s" % [f.get("stack") for f in traces][:2])
    expect(len(set(f.get("caller") for f in traces)) == len(traces), "one line per distinct call place")


def check_offnotrace(out, lines, dxvk):
    """Every part off and [Trace] TargetWidth = 0 (as installed in the game): nothing at all is written, TRACE
    included, and the render-target hook is not needed (the review of 2026-10-30, item 11)."""
    text = open(os.path.join(out, "GfxProbe.log"), encoding="utf-8", errors="replace").read()
    expect("device hooks installed" in text, "the probe still loads")
    tags = sorted({tag for t, tag, f in lines})
    expect(tags == [], "nothing written with everything off, TRACE included, got %s" % tags)


CHECKS = {"offnotrace": check_offnotrace, "trace": check_trace, "tint": check_tint, "panel": check_panel, "off": check_off, "tools": check_tools, "dissect": check_dissect, "watch": check_watch, "shots": check_shots, "resources": check_resources, "framemap": check_framemap, "effects": check_effects, "targets-overflow": check_targets_overflow}


def main():
    out = sys.argv[1]
    dxvk = "--dxvk" in sys.argv
    names = [a for a in sys.argv[2:] if not a.startswith("--")]
    if names == ["all"]:
        names = [n for n in CHECKS if n not in ("off", "tint", "offnotrace")]  # "off" is for a run made with run.py --off
    lines = gfxlog.parse(os.path.join(out, "GfxProbe.log"))
    for name in names:
        before = len(failures)
        CHECKS[name](out, lines, dxvk)
        print("%-10s %s" % (name, "ok" if len(failures) == before else "FAILED"))
    print("FAIL\n  " + "\n  ".join(failures) if failures else "PASS")
    sys.exit(1 if failures else 0)


main()
