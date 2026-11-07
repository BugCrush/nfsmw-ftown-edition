"""Shared paths and helpers for the world research tests.

The tests read the game's files read-only and skip when they are missing. Nothing here ever writes inside the game
folder; anything the tests make goes under .superpowers/world/ (git-ignored).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
TOOLS = os.path.dirname(WORLD)
REPO = os.path.dirname(TOOLS)
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
EXE = os.path.join(GAME, "speed.exe")
L2RA = os.path.join(GAME, "TRACKS", "L2RA.BUN")
STREAM = os.path.join(GAME, "TRACKS", "STREAML2RA.BUN")
SYMBOLS = os.path.join(REPO, ".superpowers", "visual-research", "repos", "nfsmw", "config", "SPEED_EXE_1_3",
                       "symbols.json")
OUT = os.path.join(REPO, ".superpowers", "world")


def need(test, *paths):
    for p in paths:
        if not os.path.exists(p):
            raise unittest.SkipTest("missing %s (the game folder or the decompilation is not here)" % p)
