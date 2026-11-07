"""Real elevation for F-Town: fetches two free surface models of the area, measures the ground's real relief against
their noise, and writes what the data supports as the city's terrain model (tools/citymap/terrain.json, read by
tools/citymap/terrain.py). docs/ftown-notes.md "Elevation (2026-11-04)".

    .tools/cityenv/Scripts/python tools/citymap/elevation.py fetch .superpowers/elevation
    .tools/cityenv/Scripts/python tools/citymap/elevation.py study .superpowers/elevation .superpowers/citymap/faridabad

Sources (both git-ignored under .superpowers/elevation/, nothing of them committed but the fitted numbers):
- Copernicus DEM GLO-30 (tile N28 E077, AWS open data copernicus-dem-30m; 1 arc-second, TanDEM-X 2011-2015, a
  surface model: buildings and trees in it). Credit: "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and
  (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights
  reserved". Free licence for any use, derived products allowed with that credit.
- AWS Terrain Tiles (terrarium PNG, zoom 14, elevation-tiles-prod; over India from SRTM 1 arc-second, 2000, NASA,
  public domain; Mapzen's tiles credit "SRTM, NASA" and the tile compilers). An independent sensor (C band, 2000)
  against Copernicus's (X band, 2011-2015): where the two disagree is the data's noise.

The study (ground samples only: every 30 m point over the city's edge box farther than GROUND_KEEP from an OSM
building): a plane fitted to each source; the residuals smoothed at SCALES (Gaussian, sigma = scale / 2); per scale
each source's residual std, the correlation of the two and the std of their difference. A relief beyond the plane is
taken only where it is real by both: correlation over REAL_CORR and difference std under REAL_NOISE x the residual's.
Otherwise the terrain is the plane alone (Copernicus's fit), anchored at the first spawn (offset 0 there).
"""
import glob
import json
import math
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.citymap import geo  # noqa: E402

COP_TILE = "Copernicus_DSM_COG_10_N28_00_E077_00_DEM"
COP_URL = "https://copernicus-dem-30m.s3.amazonaws.com/%s/%s.tif" % (COP_TILE, COP_TILE)
TER_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png"
TER_ZOOM = 14
BBOX = (28.385, 77.305, 28.420, 77.332)  # build_city.BBOX
FETCH_MARGIN = 0.01  # degrees round the box (about 1 km)
STEP = 30.0
GROUND_KEEP = 10.0
SCALES = (250.0, 500.0, 1000.0)
REAL_CORR, REAL_NOISE = 0.8, 0.5
ANCHOR = geo.moved(3231.43, 12846.57)  # the first spawn (the route start, ftown/ftown-city.json): offset 0 there
TERRAIN_JSON = os.path.join(HERE, "terrain.json")
CREDIT = ("Elevation: produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space "
          "GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. Checked "
          "against SRTM 1 arc-second (NASA, public domain) through AWS Terrain Tiles.")


def _tile_xy(lat, lon, z):
    n = 2 ** z
    la = math.radians(lat)
    return ((lon + 180.0) / 360.0 * n, (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n)


def fetch(out):
    """Downloads the Copernicus tile and the terrarium tiles over the box + FETCH_MARGIN into out/copernicus and
    out/terrarium (each skipped when present)."""
    s, w, n, e = BBOX
    os.makedirs(os.path.join(out, "copernicus"), exist_ok=True)
    os.makedirs(os.path.join(out, "terrarium"), exist_ok=True)
    p = os.path.join(out, "copernicus", COP_TILE + ".tif")
    if not os.path.exists(p):
        urllib.request.urlretrieve(COP_URL, p)
    x0, y0 = (int(v) for v in _tile_xy(n + FETCH_MARGIN, w - FETCH_MARGIN, TER_ZOOM))
    x1, y1 = (int(v) for v in _tile_xy(s - FETCH_MARGIN, e + FETCH_MARGIN, TER_ZOOM))
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            p = os.path.join(out, "terrarium", "%d_%d_%d.png" % (TER_ZOOM, x, y))
            if not os.path.exists(p):
                urllib.request.urlretrieve(TER_URL % (TER_ZOOM, x, y), p)


class Copernicus:
    """Bilinear heights from the GLO-30 tile (pixel is point: centres at 77 + c / 3600, 29 - r / 3600)."""

    def __init__(self, path):
        import tifffile
        self.a = tifffile.imread(path).astype(np.float64)

    def at(self, lat, lon):
        r, c = (29.0 - np.asarray(lat)) * 3600.0, (np.asarray(lon) - 77.0) * 3600.0
        r0, c0 = np.floor(r).astype(int), np.floor(c).astype(int)
        fr, fc = r - r0, c - c0
        a = self.a
        return (a[r0, c0] * (1 - fr) * (1 - fc) + a[r0, c0 + 1] * (1 - fr) * fc + a[r0 + 1, c0] * fr * (1 - fc) +
                a[r0 + 1, c0 + 1] * fr * fc)


class Terrarium:
    """Bilinear heights from terrarium tiles (height = R 256 + G + B / 256 - 32768; pixel centres at +0.5)."""

    def __init__(self, folder):
        from PIL import Image
        self.t = {}
        for p in glob.glob(os.path.join(folder, "%d_*.png" % TER_ZOOM)):
            _z, x, y = map(int, os.path.basename(p)[:-4].split("_"))
            with Image.open(p) as im:
                a = np.asarray(im.convert("RGB")).astype(np.float64)
            self.t[(x, y)] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

    def _px(self, X, Y):
        out = np.empty(X.shape)
        for i in range(X.size):
            out.flat[i] = self.t[(X.flat[i] // 256, Y.flat[i] // 256)][Y.flat[i] % 256, X.flat[i] % 256]
        return out

    def at(self, lat, lon):
        fx, fy = np.vectorize(lambda a, b: _tile_xy(a, b, TER_ZOOM))(lat, lon)
        fx, fy = np.asarray(fx) * 256 - 0.5, np.asarray(fy) * 256 - 0.5
        x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
        ax, ay = fx - x0, fy - y0
        return (self._px(x0, y0) * (1 - ax) * (1 - ay) + self._px(x0 + 1, y0) * ax * (1 - ay) +
                self._px(x0, y0 + 1) * (1 - ax) * ay + self._px(x0 + 1, y0 + 1) * ax * ay)


def fit_plane(x, y, z):
    """(dz_dx, dz_dy, z at (0, 0)) by least squares."""
    A = np.c_[x, y, np.ones(len(x))]
    c, *_ = np.linalg.lstsq(A, z, rcond=None)
    return float(c[0]), float(c[1]), float(c[2])


def smooth(grid, mask, sigma_cells):
    """Normalised Gaussian smoothing of grid's values where mask is true (other cells carry no weight)."""
    r = int(math.ceil(3 * sigma_cells))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_cells) ** 2)

    def conv(a):
        a = np.apply_along_axis(lambda v: np.convolve(v, k)[r:r + len(v)], 0, a)
        return np.apply_along_axis(lambda v: np.convolve(v, k)[r:r + len(v)], 1, a)
    w = conv(mask.astype(float))
    return np.where(w > 1e-9, conv(np.where(mask, grid, 0.0)) / np.maximum(w, 1e-9), np.nan)


def ground_grid(proj, osm_path):
    """(X, Y, mask): a STEP grid over the city's edge box in render metres and the ground cells (farther than
    GROUND_KEEP from every OSM building)."""
    import shapely
    from tools.citymap import buildings
    box = buildings.edge_box(proj, BBOX)
    x0, y0, x1, y1 = box.bounds
    X, Y = np.meshgrid(np.arange(x0, x1 + 1e-6, STEP), np.arange(y0, y1 + 1e-6, STEP))
    with open(osm_path, encoding="utf-8") as f:
        osm = json.load(f)
    polys = []
    for e in osm["elements"]:
        if e.get("type") == "way" and e.get("tags", {}).get("building") and len(e.get("geometry", [])) >= 4:
            ring = [proj.to_render(g["lat"], g["lon"]) for g in e["geometry"]]
            pg = shapely.Polygon(ring)
            if pg.is_valid:
                polys.append(pg)
    near = shapely.union_all(polys).buffer(GROUND_KEEP)
    shapely.prepare(near)
    mask = ~shapely.contains_xy(near, X.ravel(), Y.ravel())
    return X, Y, mask.reshape(X.shape)


def study(dem_dir, area_dir):
    """The study's numbers (module doc) as a dict, and the terrain model it supports."""
    proj = geo.Projection()
    X, Y, mask = ground_grid(proj, os.path.join(area_dir, "osm.json"))
    lat, lon = proj.to_latlon(X, Y)
    srcs = {"copernicus": Copernicus(os.path.join(dem_dir, "copernicus", COP_TILE + ".tif")).at(lat, lon),
            "srtm": Terrarium(os.path.join(dem_dir, "terrarium")).at(lat, lon)}
    out = {"grid": list(X.shape), "ground_cells": int(mask.sum()), "cells": int(mask.size), "sources": {}}
    res = {}
    for name, Z in srcs.items():
        gx, gy, gz = X[mask], Y[mask], Z[mask]
        a, b, c = fit_plane(gx - ANCHOR[0], gy - ANCHOR[1], gz)
        R = Z - (a * (X - ANCHOR[0]) + b * (Y - ANCHOR[1]) + c)
        res[name] = R
        g = math.hypot(a, b)
        span = (np.ptp(X) ** 2 + np.ptp(Y) ** 2) ** 0.5
        out["sources"][name] = {"dz_dx": a, "dz_dy": b, "z_at_anchor": c, "grade_pct": 100 * g,
                                "uphill_deg": math.degrees(math.atan2(b, a)), "drop_over_box_m": g * span,
                                "ground_min": float(gz.min()), "ground_max": float(gz.max()),
                                "residual_std": float(R[mask].std())}
    d = (srcs["copernicus"] - srcs["srtm"])[mask]
    out["pointwise_difference_std"] = float(d.std())
    out["scales"] = {}
    real = []
    for s in SCALES:
        sm = {k: smooth(R, mask, s / 2 / STEP) for k, R in res.items()}
        ok = mask & ~np.isnan(sm["copernicus"]) & ~np.isnan(sm["srtm"])
        a, b = sm["copernicus"][ok], sm["srtm"][ok]
        corr = float(np.corrcoef(a, b)[0, 1])
        diff = float((a - b - (a - b).mean()).std())
        rec = {"copernicus_std": float(a.std()), "srtm_std": float(b.std()), "corr": corr, "difference_std": diff,
               "copernicus_range": float(np.ptp(a)), "real": bool(corr > REAL_CORR and diff < REAL_NOISE * a.std())}
        out["scales"][str(int(s))] = rec
        if rec["real"]:
            real.append(s)
    cop, sr = out["sources"]["copernicus"], out["sources"]["srtm"]
    agree = (abs(cop["grade_pct"] - sr["grade_pct"]) < 0.5 * cop["grade_pct"] and
             abs((cop["uphill_deg"] - sr["uphill_deg"] + 180) % 360 - 180) < 45)
    out["plane_agrees"] = bool(agree)
    out["real_scales"] = real
    model = {"model": "plane" if agree else "flat", "dz_dx": round(cop["dz_dx"], 8) if agree else 0.0,
             "dz_dy": round(cop["dz_dy"], 8) if agree else 0.0, "anchor": list(ANCHOR),
             "source": "Copernicus DEM GLO-30 (%s), ground cells only, plane by least squares" % COP_TILE,
             "check": "SRTM 1 arc-second (AWS Terrain Tiles z%d)" % TER_ZOOM, "credit": CREDIT,
             "note": "beyond the plane no scale passed the study (both sources correlate > %.1f, difference under "
                     "%.1f x the relief): see docs/ftown-notes.md 'Elevation (2026-11-04)'" % (REAL_CORR, REAL_NOISE)
             if not real else "scales %s passed but are not modelled" % real}
    return out, model


def main(argv):
    if len(argv) == 2 and argv[0] == "fetch":
        fetch(argv[1])
        return 0
    if len(argv) == 3 and argv[0] == "study":
        out, model = study(argv[1], argv[2])
        print(json.dumps(out, indent=1))
        with open(os.path.join(argv[1], "study.json"), "w", newline="\n") as f:
            json.dump(out, f, indent=1)
        with open(TERRAIN_JSON, "w", newline="\n") as f:
            json.dump(model, f, indent=1)
            f.write("\n")
        print(json.dumps(model, indent=1))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
