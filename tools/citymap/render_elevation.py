"""Pictures of the elevation (docs/ftown-notes.md "Elevation (2026-11-04)"), PIL only.

    .tools/cityenv/Scripts/python tools/citymap/render_elevation.py <dem dir> <area dir> <city.bun> <out dir>

<out dir>/elevation-study.png: four maps of the city's box, north up, ground cells only (buildings grey): the
Copernicus ground heights, the fitted plane, and the residual after the plane smoothed at 500 m from Copernicus and
from SRTM side by side (the same colour scale: where the two disagree is the data's noise).
<out dir>/elevation-profiles.png: each event's route as a car follows it on the written city (events.follow), height
against metres along it, the flat city's 100 m line dashed, vertical exaggeration x 50 (the flyovers clipped).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.citymap import elevation, geo, terrain  # noqa: E402


def _ramp(v, lo, hi):
    """A blue-white-red colour for v in lo..hi (numpy array -> (h, w, 3) uint8)."""
    t = np.clip((v - lo) / (hi - lo), 0, 1)
    r = np.where(t < 0.5, 2 * t, 1.0)
    b = np.where(t < 0.5, 1.0, 2 * (1 - t))
    g = 1 - np.abs(2 * t - 1)
    return (np.stack([r, 0.35 + 0.65 * g, b], -1) * 255).astype(np.uint8)


def _panel(Z, mask, lo, hi, title, scale=4):
    img = _ramp(Z, lo, hi)
    img[~mask] = (150, 150, 150)
    im = Image.fromarray(img[::-1]).resize((Z.shape[1] * scale, Z.shape[0] * scale), Image.NEAREST)
    out = Image.new("RGB", (im.width, im.height + 40), (255, 255, 255))
    out.paste(im, (0, 40))
    d = ImageDraw.Draw(out)
    d.text((4, 4), title, fill=(0, 0, 0))
    d.text((4, 20), "%.1f m (blue) .. %.1f m (red)" % (lo, hi), fill=(0, 0, 0))
    return out


def study_png(dem_dir, area_dir, out):
    proj = geo.Projection()
    X, Y, mask = elevation.ground_grid(proj, os.path.join(area_dir, "osm.json"))
    lat, lon = proj.to_latlon(X, Y)
    C = elevation.Copernicus(os.path.join(dem_dir, "copernicus", elevation.COP_TILE + ".tif")).at(lat, lon)
    S = elevation.Terrarium(os.path.join(dem_dir, "terrarium")).at(lat, lon)
    m = terrain.model()
    base = float(np.median(C[mask] - terrain.offsets(X, Y)[mask]))
    P = base + terrain.offsets(X, Y)
    sm = []
    for Z in (C, S):
        gx, gy = X[mask], Y[mask]
        a, b, c = elevation.fit_plane(gx, gy, Z[mask])
        R = Z - (a * X + b * Y + c)
        sm.append(elevation.smooth(R, mask, 500.0 / 2 / elevation.STEP))
    lo, hi = np.percentile(C[mask], 2), np.percentile(C[mask], 98)
    panels = [_panel(C, mask, lo, hi, "Copernicus GLO-30, ground cells"),
              _panel(P, mask, lo, hi, "the plane (%s): %.3f%% uphill" % (m["model"], 100 * terrain.max_grade())),
              _panel(sm[0], mask & ~np.isnan(sm[0]), -2.0, 2.0, "Copernicus after the plane, smoothed 500 m"),
              _panel(sm[1], mask & ~np.isnan(sm[1]), -2.0, 2.0, "SRTM after the plane, smoothed 500 m")]
    W = sum(p.width for p in panels) + 10 * (len(panels) + 1)
    img = Image.new("RGB", (W, max(p.height for p in panels) + 20), (255, 255, 255))
    x = 10
    for p in panels:
        img.paste(p, (x, 10))
        x += p.width + 10
    img.save(os.path.join(out, "elevation-study.png"))


def profiles_png(city, out):
    from tools.citymap import events
    evs = events.read()
    W, ROW, EX = 1600, 170, 50.0
    img = Image.new("RGB", (W + 60, ROW * len(evs) + 20), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for k, ev in enumerate(evs):
        S, Z = events.follow(ev, city)
        y0 = 10 + ROW * k
        ppm = W / max(S[-1], 1.0)
        mid = y0 + ROW / 2

        def py(z):
            return min(y0 + ROW - 5, max(y0 + 20, mid - (z - 100.0) * EX))
        d.line([(40, py(100.0)), (40 + W, py(100.0))], fill=(180, 180, 180))
        pts = [(40 + s * ppm, py(z)) for s, z in zip(S, Z) if not np.isnan(z)]
        d.line(pts, fill=(0, 0, 0), width=2)
        d.text((44, y0 + 2), "%s: %.0f m, height %.2f .. %.2f m (flat city: 100; x %d, flyovers clipped)" % (
            ev["name"], S[-1], float(np.nanmin(Z)), float(np.nanmax(Z)), EX), fill=(0, 0, 0))
    img.save(os.path.join(out, "elevation-profiles.png"))


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 1
    os.makedirs(argv[3], exist_ok=True)
    study_png(argv[0], argv[1], argv[3])
    profiles_png(argv[2], argv[3])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
