"""Shared paths and helpers for the car builder tests.

The tests read the game's own car files read-only and skip when they are missing, so the repo's tests also run on a
machine without the game. Nothing here ever writes inside the game folder.
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(CARBUILD))
if CARBUILD not in sys.path:
    sys.path.insert(0, CARBUILD)

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
CARS = os.path.join(GAME, "CARS")


def car(name, file="GEOMETRY.BIN"):
    return os.path.join(CARS, name, file)


GTI_GEOMETRY = car("GTI")
GTI_TEXTURES = car("GTI", "TEXTURES.BIN")
SEMI_GEOMETRY = car("SEMI")
TRUCK_GEOMETRY = car("LONGNOSECAB")
TRUCK_TEXTURES = car("LONGNOSECAB", "TEXTURES.BIN")
CHALLENGER_GEOMETRY = car("CHALLENGER71")
CHALLENGER_TEXTURES = car("CHALLENGER71", "TEXTURES.BIN")
SHARED_TEXTURES = os.path.join(CARS, "TEXTURES.BIN")


def geometry_files():
    return sorted(glob.glob(os.path.join(CARS, "*", "GEOMETRY.BIN")))


def texture_files():
    """Every per-car TEXTURES.BIN plus the shared CARS/TEXTURES.BIN."""
    out = sorted(glob.glob(os.path.join(CARS, "*", "TEXTURES.BIN")))
    if os.path.exists(SHARED_TEXTURES):
        out.append(SHARED_TEXTURES)
    return out


def car_files():
    return geometry_files() + texture_files()


def read(path):
    with open(path, "rb") as f:
        return f.read()


def need(testcase, *paths):
    for p in paths:
        if not os.path.exists(p):
            testcase.skipTest("game file missing: " + p)


def need_cars(testcase):
    if not geometry_files():
        testcase.skipTest("no game cars at " + CARS)


def is_compressed(data):
    """A pack holding JDLZ blocks (the compressed add-ons) rather than plain chunks."""
    return b"JDLZ" in data[:0x10000] or data[:4] == b"JDLZ"
