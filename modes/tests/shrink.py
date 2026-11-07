"""How DXVK shrinks a larger back buffer into the window, measured, against an area-average shrink of our own.

    python modes/tests/shrink.py [WxH ...]      (default 2560x1440 2240x1260)

For each size: runs the stand-in (DisplayModes first, DXVK's d3d9.dll, the test pattern of standin.cpp), captures
the screen while it presents (the window covers the screen for about three seconds), and compares
  - "dxvk-model": DXVK v3.1.1's present shader (src/dxvk/shaders/dxvk_present_frag_blit.frag) computed here:
    when shrinking, one bilinear mix of the 2x2 texels at floor(coord), coord = (pixel + 0.5) * scale;
  - "capture": what reached the screen (must match the model, or the model is wrong; at 1920x1080 DXVK copies
    without the shader, so there the model does not apply and the capture must equal the pattern itself);
  - "area": each window pixel the average of the back-buffer area it covers (what a shrink of our own would do).
Numbers, per method (0-255 scale):
  checker   standard deviation over the one-pixel checkerboard: a perfect shrink gives an even grey (0); more is a
            moire pattern, the shimmer of fine detail;
  lines     how much a one-pixel line's total brightness changes with where it falls (max/min of the per-line sums
            over 64 lines at every sub-pixel position): 1.00 = steady, more = it pulses as it moves;
  peak      the brightest pixel of the faintest line (how visible the thinnest detail stays);
  diagonal  the same max/min for the shallow diagonal, per window column (the crawl of a slanted edge).
Each size is run twice: DXVK's shrink ([Shrink] Area = 0) and ours (DisplayModes' area average at Present), and
"ours" must match the area model. Writes modes/tests/out/shrink-<size>-ms<q>-dxvk|ours/ (capture.png, model.png or
area-model.png; numbers.txt in the "ours" folder).
"""
import ctypes
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as runner  # noqa: E402

WIN_W, WIN_H = 1920, 1080


def pattern(w, h):
    y, x = np.mgrid[0:h, 0:w]
    p = np.zeros((h, w), np.float64)
    checker = (x < 400) & (y < 400)
    p[checker] = ((x + y)[checker] & 1) * 255
    v = (y >= 450) & (y < 700) & (x >= 450) & (x < 450 + 13 * 64)
    p[v] = (((x - 450) % 13 == 0)[v]) * 255
    hl = (x >= 1350) & (x < 1700) & (y < 13 * 64)
    p[hl] = ((y % 13 == 0)[hl]) * 255
    d = (y >= 850) & (y < 1050) & (x < 1400)
    p[d] = ((y - 850 == x // 7)[d]) * 255
    return p


def dxvk_model(src, dw, dh):
    sh, sw = src.shape
    cx = (np.arange(dw) + 0.5) * sw / dw
    cy = (np.arange(dh) + 0.5) * sh / dh
    ix, fx = np.floor(cx).astype(int), cx - np.floor(cx)
    iy, fy = np.floor(cy).astype(int), cy - np.floor(cy)
    ix1, iy1 = np.minimum(ix + 1, sw - 1), np.minimum(iy + 1, sh - 1)  # texelFetch past the edge reads 0; edge unused
    top = src[iy][:, ix] * (1 - fx) + src[iy][:, ix1] * fx
    bot = src[iy1][:, ix] * (1 - fx) + src[iy1][:, ix1] * fx
    return top * (1 - fy)[:, None] + bot * fy[:, None]


# dxvk_present_frag_ms_blit.frag: sample positions for 2, 4, 8 samples (16 not needed here)
MS_POS = {2: [(0.25, 0.25), (-0.25, -0.25)],
          4: [(-0.125, -0.375), (0.375, -0.125), (-0.375, 0.125), (0.125, 0.375)],
          8: [(0.0625, -0.1875), (-0.0625, 0.1875), (0.3125, 0.0625), (-0.1875, -0.3125),
              (-0.3125, 0.3125), (-0.4375, -0.0625), (0.1875, 0.4375), (0.4375, -0.4375)]}


def dxvk_ms_model(src, dw, dh, samples):
    """DXVK's shrink of a multisampled back buffer: per sample, texel floor(coord) or the next one, no blending
    (every sample of a pixel holds that pixel's colour in the stand-in)."""
    sh, sw = src.shape
    cx = (np.arange(dw) + 0.5) * sw / dw
    cy = (np.arange(dh) + 0.5) * sh / dh
    ix, fx = np.floor(cx).astype(int), cx - np.floor(cx) - 0.5
    iy, fy = np.floor(cy).astype(int), cy - np.floor(cy) - 0.5
    acc = np.zeros((dh, dw))
    for px, py in MS_POS[samples]:
        ox = np.minimum(ix + (fx - px > 0.5), sw - 1)
        oy = np.minimum(iy + (fy - py > 0.5), sh - 1)
        acc += src[oy][:, ox]
    return acc / samples


def area_weights(n_src, n_dst):
    s = n_src / n_dst
    m = np.zeros((n_dst, n_src))
    for j in range(n_dst):
        a, b = j * s, (j + 1) * s
        for i in range(int(np.floor(a)), min(int(np.ceil(b)), n_src)):
            m[j, i] = max(0.0, min(b, i + 1) - max(a, i))
        m[j] /= m[j].sum()
    return m


def area(src, dw, dh):
    sh, sw = src.shape
    return area_weights(sh, dh) @ src @ area_weights(sw, dw).T


def numbers(img, sw, sh):
    sx, sy = WIN_W / sw, WIN_H / sh
    c = img[2:int(390 * sy), 2:int(390 * sx)]
    out = {"checker": c.std()}
    sums, peaks = [], []
    # vertical lines: per line, the sum across the window columns around it, averaged over the block's rows
    rows = img[int(460 * sy):int(690 * sy)]
    for k in range(64):
        x0 = (450 + 13 * k + 0.5) * sx
        seg = rows[:, int(np.floor(x0 - 3)):int(np.ceil(x0 + 3))]
        sums.append(seg.sum(axis=1).mean())
        peaks.append(seg.max(axis=1).mean())
    # horizontal lines likewise
    cols = img[:, int(1360 * sx):int(1690 * sx)]
    for k in range(1, 64):
        y0 = (13 * k + 0.5) * sy
        seg = cols[int(np.floor(y0 - 3)):int(np.ceil(y0 + 3))]
        sums.append(seg.sum(axis=0).mean())
        peaks.append(seg.max(axis=0).mean())
    out["lines"] = max(sums) / min(sums)
    out["peak"] = min(peaks)
    # diagonal: per window column, the line's total over its band's rows
    band = img[int(850 * sy) - 3:int(1050 * sy) + 3, int(20 * sx):int(1380 * sx)]
    col = band.sum(axis=0)
    out["diagonal"] = col.max() / col.min()
    return out


def capture(size, ms, ours):
    name = "shrink-%s-ms%d-%s" % (size, ms, "ours" if ours else "dxvk")
    runner.VARIANTS[name] = ("first", size, None if ours else "[Shrink]\r\nArea = 0\r\n")
    out = runner.prepare(name, False)
    p = subprocess.Popen([os.path.join(out, "standin.exe"), "order=first", "size=" + size, "hold=3000", "ms=%d" % ms],
                         cwd=out, stdout=subprocess.PIPE, text=True)
    lines = []
    for line in p.stdout:
        lines.append(line.strip())
        if line.strip() == "READY":
            break
    time.sleep(1.0)
    shot = ImageGrab.grab(bbox=(0, 0, WIN_W, WIN_H))
    rest = p.communicate(timeout=30)[0]
    lines += rest.splitlines()
    log = open(os.path.join(out, "DisplayModes.log")).read()
    return out, np.asarray(shot.convert("RGB"))[:, :, 1].astype(np.float64), lines, log


def compare(a, b):
    d = np.abs(a - np.round(b))
    return "mean |diff| %.2f, 99.9th percentile %.1f, max %.0f (0-255)" % (d.mean(), np.percentile(d, 99.9), d.max())


def main():
    ctypes.windll.user32.SetProcessDPIAware()
    sizes = [a for a in sys.argv[1:] if "x" in a] or ["2560x1440", "2240x1260"]
    # ms=Q: the game's back buffer is NONMASKABLE with quality = its FSAA level (0x6BFBA6; g_FSAALevel 3 here), which
    # DXVK makes 2^Q samples; DXVK then shrinks with a different shader
    levels = [int(a[3:]) for a in sys.argv[1:] if a.startswith("ms=")] or [0, 3]
    runner.build()
    report = []
    for size, ms in [(z, q) for z in sizes for q in levels]:
        sw, sh = map(int, size.split("x"))
        src = pattern(sw, sh)
        model = dxvk_ms_model(src, WIN_W, WIN_H, 1 << ms) if ms else dxvk_model(src, WIN_W, WIN_H)
        ar = area(src, WIN_W, WIN_H)
        out, dxvk, lines, _ = capture(size, ms, False)
        out2, ours, lines2, log2 = capture(size, ms, True)
        for folder, name, img in ((out, "capture", dxvk), (out, "model", model), (out2, "capture", ours),
                                  (out2, "area-model", ar)):
            Image.fromarray(np.clip(np.round(img), 0, 255).astype(np.uint8)).save(os.path.join(folder, name + ".png"))
        took = [l for l in log2.splitlines() if "area average" in l]
        text = ["size %s, msaa quality %d -> %dx%d window; stand-in: %s" % (size, ms, WIN_W, WIN_H, " | ".join(
            l for l in lines if l.startswith(("WINDOW", "PRESENT", "MSAA", "DEVICE"))))]
        text.append("ours: %s" % (took[0].split(" ", 1)[1] if took else "NOT USED"))
        text.append("dxvk capture vs dxvk-model: " + compare(dxvk, model))
        text.append("ours capture vs area-model: " + compare(ours, ar))
        for name, img in (("dxvk", dxvk), ("dxvk-model", model), ("ours", ours), ("area-model", ar)):
            n = numbers(img, sw, sh)
            text.append("%-11s checker %6.1f   lines %5.2f   peak %5.1f   diagonal %5.2f"
                        % (name, n["checker"], n["lines"], n["peak"], n["diagonal"]))
        open(os.path.join(out2, "numbers.txt"), "w").write("\n".join(text) + "\n")
        report += text + [""]
    print("\n".join(report))


if __name__ == "__main__":
    main()
