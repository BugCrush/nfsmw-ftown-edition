"""Shared paths for the city builder's tests.

The OSM data is git-ignored (.superpowers/citymap/faridabad/); tests that need it skip when it is missing. The road
model is built once per test process and shared (building it takes a few seconds).
"""
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CITYMAP = os.path.dirname(HERE)
TOOLS = os.path.dirname(CITYMAP)
REPO = os.path.dirname(TOOLS)
AREA = os.path.join(REPO, ".superpowers", "citymap", "faridabad")
OSM = os.path.join(AREA, "osm.json")
ROUTE = os.path.join(AREA, "route_main.json")
SCRATCH = os.path.join(REPO, ".superpowers", "citymap", "test-out")

_cache = {}


def need(*paths):
    for p in paths:
        if not os.path.exists(p):
            raise unittest.SkipTest("missing %s (the OSM download: python tools/citymap/fetch_osm.py ...)" % p)


def osm():
    need(OSM)
    if "osm" not in _cache:
        with open(OSM, encoding="utf-8") as f:
            _cache["osm"] = json.load(f)
    return _cache["osm"]


def proj():
    from tools.citymap import geo
    if "proj" not in _cache:
        _cache["proj"] = geo.Projection()
    return _cache["proj"]


def model():
    from tools.citymap import roadmodel
    if "model" not in _cache:
        _cache["model"] = roadmodel.build(osm(), proj())
    return _cache["model"]


def polys():
    from tools.citymap import surfaces
    if "polys" not in _cache:
        _cache["polys"] = surfaces.road_polygons(model())
    return _cache["polys"]
