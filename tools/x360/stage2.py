"""Stage 2 of the Xbox 360 pack install: HD Reflections and Front-End Shadows, our builds (companions/README.md),
with the settings the pack asks for (CubemapBrightnessFix = 0, whose own note names the Xbox 360 Stuff mod;
RestoreShadows = 1) except RestoreWaterReflections (below), and the authors' defaults otherwise.

Usage: python stage2.py <target folder> [--game]   (--game: refuses while the game runs)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stages  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = {"hd": os.path.join(ROOT, "companions", "NFSHDReflections", "out"),
       "fe": os.path.join(ROOT, "companions", "NFSMWFEShadows", "out")}
# RestoreWaterReflections = 0 (the user, 2026-10-19; the pack asks for 1): 1 makes the game draw the road/water
# reflection every frame, at screen size with AutoRes: about 1,000 draws and 2.1 ms of processor time per frame
# (81.9 -> 66.3 FPS).
# ForceEnableMirror = 0, the user's choice (2026-10-19, repeated 2026-10-20: "i dont want the forced rear view
# mirror"): the mirror only in the bumper and hood views, as in the original game. Not a performance matter (the
# mirror is drawn from the car's reflection and is nearly free); don't turn it back on unasked.
HD_SETTINGS = {("GENERAL", "CubemapBrightnessFix"): "0", ("GENERAL", "RestoreWaterReflections"): "0",
               ("GENERAL", "ForceEnableMirror"): "0"}
FE_SETTINGS = {("MAIN", "RestoreShadows"): "1"}


def run(target, record_dir, check_game=True):
    copies = [(os.path.join(OUT["hd"], "NFSMWHDReflections.asi"), r"scripts\NFSMWHDReflections.asi"),
              (os.path.join(OUT["fe"], "NFSMWFEShadows.asi"), r"scripts\NFSMWFEShadows.asi")]
    inis = {r"scripts\NFSMWHDReflections.ini": (os.path.join(OUT["hd"], "NFSMWHDReflections.ini"), HD_SETTINGS),
            r"scripts\NFSMWFEShadows.ini": (os.path.join(OUT["fe"], "NFSMWFEShadows.ini"), FE_SETTINGS)}
    return stages.install_companion(target, copies, inis, record_dir, check_game=check_game)


if __name__ == "__main__":
    record = os.path.join(ROOT, "telemetry", "x360-stage2-record-" + time.strftime("%Y%m%d-%H%M%S"))
    s = run(sys.argv[1], record, check_game="--game" in sys.argv)
    print("%d files added or changed; record in %s" % (len(s["files"]), record))
