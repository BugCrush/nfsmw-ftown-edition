"""A scratch "mini game folder" to rehearse a car install without touching the game or the test copy.

    python tools/carbuild/rehearsal.py [<game dir>] [<mini dir>]

Copies (never links: a write through a hard link would land in the user's files) what tools/cars/install.py and the
car's Binarius script read and write: GLOBAL, FRONTEND, LANGUAGES, scripts, the CARS folder's own files (the shared
TEXTURES.BIN) and the profile save (SAVE/NFS Most Wanted/player/player, for tools/cars/parts.py diff). The mini folder
is rebuilt from scratch each time and must lie under .superpowers/carbuild/ (it is deleted first).
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GAME = os.path.join(REPO, "Need For Speed Most Wanted Black Edition")
MINI = os.path.join(REPO, ".superpowers", "carbuild", "thar", "rehearsal")
RECORDS = os.path.join(REPO, ".superpowers", "carbuild", "thar", "rehearsal-records")
SCRATCH_ROOT = os.path.join(REPO, ".superpowers", "carbuild")
FOLDERS = ("GLOBAL", "FRONTEND", "LANGUAGES", "scripts")
PROFILE = os.path.join("SAVE", "NFS Most Wanted", "player", "player")


def _inside(path, root):
    path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return path.startswith(root + os.sep)


def make(game=GAME, mini=MINI):
    """Rebuilds mini from copies of the game's files; returns mini."""
    if not _inside(mini, SCRATCH_ROOT):
        raise ValueError("the mini folder must be under %s: %s" % (SCRATCH_ROOT, mini))
    if _inside(mini, game) or _inside(game, mini):
        raise ValueError("the mini folder and the game folder overlap")
    if os.path.exists(mini):
        shutil.rmtree(mini)
    os.makedirs(mini)
    for name in FOLDERS:
        # copy_function=shutil.copy2: a new file with the same bytes and times, never a link
        shutil.copytree(os.path.join(game, name), os.path.join(mini, name), copy_function=shutil.copy2)
    os.makedirs(os.path.join(mini, "CARS"))
    cars = os.path.join(game, "CARS")
    for n in os.listdir(cars):
        if os.path.isfile(os.path.join(cars, n)):
            shutil.copy2(os.path.join(cars, n), os.path.join(mini, "CARS", n))
    os.makedirs(os.path.dirname(os.path.join(mini, PROFILE)))
    shutil.copy2(os.path.join(game, PROFILE), os.path.join(mini, PROFILE))
    for dp, _, names in os.walk(mini):
        for n in names:
            if os.stat(os.path.join(dp, n)).st_nlink != 1:
                raise RuntimeError("%s is a link, not a copy" % os.path.join(dp, n))
    return mini


if __name__ == "__main__":
    print(make(*sys.argv[1:3]))
