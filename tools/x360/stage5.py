"""Stage 5 of the Xbox 360 pack install: the feature switches left off so far (plan part 2, Task 6b), turned on
together and measured in one race, and the menus at full size.

- X360Stuff.ini [VIDEO] FEScalingMode = 0 (with FEScale = 1.0): menus and the title screen fill the screen (1 was the
  Xbox 360's 92% size; the user, 2026-10-19: "its not filling the screen");
- X360Stuff.ini [VIDEO] CarsInAllCubemapFaces = 1: other cars in every face of the car's reflection, not only the
  rear (its note: experimental);
- X360Stuff.ini [ENHANCEMENTS] UseFullLODShaderOnTrafficAndCops = 1: full shading on traffic and police cars;
- NFSMWHDReflections.ini RestoreShadows = 1: real-time shadows in the rear-view mirror;
- NFSMWFEShadows.ini RenderCarShadows = 1: car shadows in garages and shops.

HD Reflections' RestoreCars stays 0: it patches 0x6DE7CA, where X360Stuff already draws cars into the reflection
(PatchMap), so the two would overwrite each other; CarsInAllCubemapFaces is the pack's way to the same result.
Usage: python stage5.py <target folder> [--game]   (--game: refuses while the game runs)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import files  # noqa: E402
import stages  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SETTINGS = {
    r"scripts\X360Stuff.ini": {("VIDEO", "FEScalingMode"): "0", ("VIDEO", "FEScale"): "1.0",
                               ("VIDEO", "CarsInAllCubemapFaces"): "1",
                               ("ENHANCEMENTS", "UseFullLODShaderOnTrafficAndCops"): "1"},
    r"scripts\NFSMWHDReflections.ini": {("GENERAL", "RestoreShadows"): "1"},
    r"scripts\NFSMWFEShadows.ini": {("MAIN", "RenderCarShadows"): "1"},
}


def run(target, record_dir, check_game=True):
    inis = {rel: (files.find(target, rel), values) for rel, values in SETTINGS.items()}
    return stages.install_companion(target, [], inis, record_dir, check_game=check_game)


if __name__ == "__main__":
    record = os.path.join(ROOT, "telemetry", "x360-stage5-record-" + time.strftime("%Y%m%d-%H%M%S"))
    s = run(sys.argv[1], record, check_game="--game" in sys.argv)
    print("%d files added or changed; record in %s" % (len(s["files"]), record))
