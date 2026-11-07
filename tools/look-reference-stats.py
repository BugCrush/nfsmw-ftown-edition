"""Measures the four versions shown side by side in the Xbox 360 pack's comparison video, and our own
split-screen screenshots, the same way: brightness (mean, 5% darkest, middle, 5% brightest), near-white
and near-black shares, saturation and warmth. One-off analysis kept for the record; paths are fixed.

Needs the video frames in .superpowers/visual-research/video/compare/ (see docs/visual-notes.md).
"""
import glob, statistics as st
from PIL import Image

def stats(im):
    im = im.convert("RGB").resize((240, 135), Image.BILINEAR)
    px = list(im.getdata()); n = len(px)
    lum = sorted(0.2125*r + 0.7154*g + 0.0721*b for r, g, b in px)
    sat = sum((max(p)-min(p))/max(p) if max(p) else 0 for p in px)/n
    mean = [sum(p[i] for p in px)/n for i in range(3)]
    return {"mean": sum(lum)/n, "p05": lum[int(n*0.05)], "p50": lum[n//2], "p95": lum[int(n*0.95)],
            "white": 100*sum(1 for v in lum if v >= 250)/n, "dark": 100*sum(1 for v in lum if v < 20)/n, "sat": sat,
            "warm": mean[0]-mean[2], "r": mean[0], "g": mean[1], "b": mean[2]}

def avg(rows):
    return {k: st.mean(r[k] for r in rows) for k in rows[0]}

def show(name, s):
    print("%-22s mean %5.1f | dark tail p05 %5.1f | middle p50 %5.1f | bright tail p95 %5.1f | near-white %4.1f%% | near-black %4.1f%% | saturation %.2f | red-blue %+5.1f | RGB %3.0f %3.0f %3.0f" % (
        name, s["mean"], s["p05"], s["p50"], s["p95"], s["white"], s["dark"], s["sat"], s["warm"], s["r"], s["g"], s["b"]))

frames = sorted(glob.glob(".superpowers/visual-research/video/compare/c-*.png"))[2:]   # skip the two menu frames
quads = {"pack 4.0": (0, 0), "real Xbox 360": (960, 0), "pack 3.2": (0, 540), "vanilla PC (video)": (960, 540)}
res = {k: [] for k in quads}
for f in frames:
    im = Image.open(f).convert("RGB")
    if im.size != (1920, 1080):
        im = im.resize((1920, 1080))
    for k, (x, y) in quads.items():
        res[k].append(stats(im.crop((x + 20, y + 60, x + 940, y + 520))))   # inside the quadrant, without its label
print("comparison video, %d moments, four versions of the same moment:" % len(frames))
for k in quads:
    show(k, avg(res[k]))
shots = sorted(glob.glob("gfx-captures/baseline/run-20261014-030130/shots/*.bmp"))
game, ours = [], []
for f in shots:
    im = Image.open(f).convert("RGB"); w, h = im.size
    game.append(stats(im.crop((0, 0, w//2 - 2, h)))); ours.append(stats(im.crop((w//2 + 2, 0, w, h))))
print("our race of 2026-10-14, %d screenshots (the two halves show different parts of the scene):" % len(shots))
show("our game (left half)", avg(game)); show("ours (right half)", avg(ours))
