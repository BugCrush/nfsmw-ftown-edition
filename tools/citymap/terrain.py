"""F-Town's ground height: the one height function of the city (docs/ftown-notes.md "Elevation (2026-11-04)").

The city is built flat (every module puts the ground at z 0, tiles.GROUND_Z = 100 in the game) and build_city adds
offset(x, y) to every vertex, collision face, barrier, prop and spawn as it writes them. The model is
tools/citymap/terrain.json, written by tools/citymap/elevation.py's study of two surface models: the real ground here
is a plane (about 0.07%, some 3 m over the city), and nothing smaller in it is above the data's noise. A plane is an
exact shear of the flat city: every height relative to the ground below it (decks over roads, the metro over the
ground, pavements, markings, roofs over their walls' feet) is unchanged, walls stay vertical, and flat faces stay flat.

    offset(x, y)        metres to add at render (x, y); 0 at the model's anchor, the first spawn
    offsets(xs, ys)     the same over numpy arrays
    ground_z(x, y)      the built ground's game z: tiles.GROUND_Z + offset(x, y)
    max_grade()         the steepest grade of the ground (rise over run)

For other data placed on the flat city (routes, gates, barriers, traffic spots): game z = what it was at the flat
city + offset(x, y).
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TERRAIN_JSON = os.path.join(HERE, "terrain.json")
GROUND_Z = 100.0  # tiles.GROUND_Z (not imported: tiles imports this module's users)
_model = None


def model():
    """terrain.json as a dict ({"model": "plane" or "flat", "dz_dx", "dz_dy", "anchor": [x, y], ...})."""
    global _model
    if _model is None:
        with open(TERRAIN_JSON, encoding="utf-8") as f:
            m = json.load(f)
        if m["model"] not in ("plane", "flat"):
            raise ValueError("terrain model %r" % m["model"])
        _model = m
    return _model


def offset(x, y):
    m = model()
    ax, ay = m["anchor"]
    return m["dz_dx"] * (x - ax) + m["dz_dy"] * (y - ay)


def offsets(xs, ys):
    m = model()
    ax, ay = m["anchor"]
    return m["dz_dx"] * (np.asarray(xs, dtype=float) - ax) + m["dz_dy"] * (np.asarray(ys, dtype=float) - ay)


def ground_z(x, y):
    return GROUND_Z + offset(x, y)


def max_grade():
    m = model()
    return math.hypot(m["dz_dx"], m["dz_dy"])
