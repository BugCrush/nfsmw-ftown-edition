"""Turns a GfxProbe log into one page you can look at: how a frame is built, in pictures and bars.

    python tools/gfx-visual.py <GfxProbe.log> [--dissect N] [--out <folder>]

It runs gfx-report.py on the log (reports recorded while driving), groups the stages of a frame into the
jobs they do, and writes <out>/index.html with:
  - a bar per job: draws, triangles and processor time per frame;
  - the stages in drawing order, each with the picture the game had drawn when it left that stage
    (from dissected frame N, default 2), its size, draws, and the effects that drew into it;
  - the screenshots taken through the race.
Default <out> is "visual" inside the probe's run folder (git-ignored: the pictures are game content).

The grouping is read off this game's frame (NFS Most Wanted): six-sided targets are the car's reflection,
the one large texture with many draws is the shadow map, the back buffer's first busy visit is the main
view, and the small one- and two-draw stages are the screen effects.
"""
import argparse
import glob
import html
import json
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
COLOURS = {"Game logic (before drawing)": "#8a8f98", "Sky map": "#6aa7d8", "Car reflection (6 faces)": "#c9a227",
           "Shadow map": "#7d5fb2", "Main view": "#3f9d6b", "Screen effects": "#d0704f", "Overlay and HUD": "#b85c8e"}


def job(stage, biggest):
    if stage["kind"] == "cube":
        return "Car reflection (6 faces)"
    if stage["kind"] == "backbuffer":
        if stage["visit"] == 1 and stage["draws"] < 1:
            return "Game logic (before drawing)"
        return "Main view" if stage["draws"] > 300 else "Overlay and HUD"
    if stage["draws"] > 100:
        return "Shadow map" if stage["size"] == biggest else "Other scene pass"
    return "Sky map" if stage["draws"] > 4 else "Screen effects"


def thumb(source, target, width):
    image = Image.open(source).convert("RGB")
    height = max(1, round(width * image.height / image.width))
    image.resize((width, height), Image.LANCZOS).save(target, quality=85)


def bar(value, largest, colour, text):
    share = 100.0 * value / largest if largest else 0
    return ('<div class="bar"><div class="fill" style="width:%.1f%%;background:%s"></div><span>%s</span></div>'
            % (share, colour, html.escape(text)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--dissect", type=int, default=2)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "gfx-report.py"), args.log, "--json"],
                                       capture_output=True, text=True, check=True).stdout)
    stages = report["stages"]
    areas = [s for s in stages if s["kind"] == "texture" and s["draws"] > 100]
    biggest = max(areas, key=lambda s: s["draws"])["size"] if areas else ""
    dissections = {d["n"]: d for d in report["dissections"]}
    chosen = dissections.get(args.dissect) or (list(dissections.values()) or [None])[0]
    run = os.path.dirname(chosen["dir"]) if chosen else os.path.dirname(os.path.abspath(args.log))
    out = args.out or os.path.join(run, "visual")
    os.makedirs(out, exist_ok=True)

    jobs = {}
    for s in stages:
        name = job(s, biggest)
        s["job"] = name
        e = jobs.setdefault(name, {"draws": 0.0, "tris": 0.0, "ms": 0.0, "stages": 0})
        seen = s["seen"] / 100.0
        e["draws"] += s["draws"] * seen
        e["tris"] += s["tris"] * seen
        e["ms"] += ((s["in_ms"] or 0) + (s["out_ms"] or 0)) * seen
        e["stages"] += 1
    total = {k: sum(e[k] for e in jobs.values()) or 1 for k in ("draws", "tris", "ms")}

    page = ["<!doctype html><meta charset='utf-8'><title>How the game builds a frame</title><style>",
            "body{font:15px/1.45 Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1180px;padding:0 16px;color:#1c1f24;background:#f6f7f9}",
            "h1{font-size:24px}h2{font-size:18px;margin-top:34px}table{border-collapse:collapse;width:100%}",
            "td,th{padding:6px 8px;text-align:left;vertical-align:middle;border-bottom:1px solid #dde0e5}th{font-weight:600}",
            ".bar{position:relative;height:22px;background:#e6e8ec;border-radius:3px;min-width:170px}",
            ".fill{position:absolute;inset:0 auto 0 0;border-radius:3px}.bar span{position:relative;padding-left:6px;font-size:13px;line-height:22px}",
            ".stage{display:flex;gap:14px;padding:10px 0;border-bottom:1px solid #dde0e5}.stage img{width:300px;height:auto;background:#000;border-radius:3px}",
            ".tag{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:12px}.small{color:#5b6270;font-size:13px}",
            ".shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:8px}.shots img{width:100%;border-radius:3px}",
            "</style>",
            "<h1>How the game builds a frame</h1>",
            "<p class='small'>%s<br>%.0f draws and %.0f triangles per frame. Bars are shares of the whole frame.</p>"
            % (html.escape(report["basis"]), report["draws_per_frame"], report["tris_per_frame"])]
    for w in report["warnings"]:
        page.append("<p><b>Warning:</b> %s</p>" % html.escape(w))

    page.append("<h2>What the frame's work goes into</h2><table><tr><th>Job</th><th>Draws per frame</th><th>Triangles per frame</th>"
                "<th>Processor time per frame</th></tr>")
    for name, e in sorted(jobs.items(), key=lambda kv: -kv[1]["ms"]):
        colour = COLOURS.get(name, "#777")
        page.append("<tr><td><span class='tag' style='background:%s'>%s</span></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            colour, html.escape(name),
            bar(e["draws"], total["draws"], colour, "%.0f (%.0f%%)" % (e["draws"], 100 * e["draws"] / total["draws"])),
            bar(e["tris"], total["tris"], colour, "%.0f (%.0f%%)" % (e["tris"], 100 * e["tris"] / total["tris"])),
            bar(e["ms"], total["ms"], colour, "%.2f ms (%.0f%%)" % (e["ms"], 100 * e["ms"] / total["ms"]))))
    page.append("</table><p class='small'>Processor time is measured on one frame in 61 and includes the probe's own cost. "
                "Compare the shares, not the milliseconds, with a run made without the probe.</p>")

    images = {}
    if chosen:
        for path in sorted(glob.glob(os.path.join(chosen["dir"], "*.bmp"))):
            parts = os.path.basename(path).split("-")  # 009-stage09-T9-5461x4096.bmp
            images.setdefault(parts[2], []).append(path)
    page.append("<h2>The stages, in drawing order</h2><p class='small'>Pictures are from dissected frame %s: what the game had "
                "drawn into that target when it moved on. A target visited several times shows its visits in order.</p>"
                % (chosen["n"] if chosen else "-"))
    visit_seen = {}
    for s in stages:
        index = visit_seen.get(s["target"], 0)
        visit_seen[s["target"]] = index + 1
        picture = ""
        paths = images.get(s["target"], [])
        if index < len(paths):
            name = "stage-%s-%d.jpg" % (s["target"], index + 1)
            thumb(paths[index], os.path.join(out, name), 600)
            picture = "<img src='%s' loading='lazy'>" % name
        effects = "".join("<br>%s: %.0f draws" % (html.escape(k), v) for k, v in list(s["labels"].items())[:6] if v >= 0.5)
        time = "not timed" if s["in_ms"] is None else "%.2f ms of processor time" % (s["in_ms"] + s["out_ms"])
        page.append("<div class='stage'>%s<div><span class='tag' style='background:%s'>%s</span> <b>%s</b> %s, %s%s<br>"
                    "%.0f draws, %.0f triangles, %s; in %.0f%% of frames<span class='small'>%s</span></div></div>" % (
                        picture or "<div style='width:300px'></div>", COLOURS.get(s["job"], "#777"), html.escape(s["job"]),
                        s["target"] + ("#%d" % s["visit"] if s["visit"] > 1 else ""), s["size"], s["fmt"],
                        ", anti-aliased" if s["ms"] else "", s["draws"], s["tris"], time, s["seen"], effects))

    shots = sorted(glob.glob(os.path.join(run, "shots", "*.bmp")))
    if shots:
        page.append("<h2>Screenshots through the race (%d)</h2><div class='shots'>" % len(shots))
        for path in shots:
            name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
            thumb(path, os.path.join(out, name), 640)
            page.append("<figure style='margin:0'><img src='%s' loading='lazy'><figcaption class='small'>%s</figcaption></figure>"
                        % (name, html.escape(os.path.splitext(name)[0])))
        page.append("</div>")
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(page))
    print(os.path.join(out, "index.html"))
    for name, e in sorted(jobs.items(), key=lambda kv: -kv[1]["ms"]):
        print("%-30s %7.0f draws %9.0f triangles %6.2f ms (%2.0f%% of time)" % (name, e["draws"], e["tris"], e["ms"], 100 * e["ms"] / total["ms"]))


main()
