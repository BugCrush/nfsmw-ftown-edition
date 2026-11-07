"""install / uninstall / check, as the command line and the questions in the window call them."""
import json
import os
import shutil
import sys
import time

from . import VERSION, downloads, gamecheck, journal, steps


def payload_dir():
    """The payload folder beside the installer (frozen) or the one given by FTEDITION_PAYLOAD (tests, source runs)."""
    if os.environ.get("FTEDITION_PAYLOAD"):
        return os.environ["FTEDITION_PAYLOAD"]
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    return os.path.join(base, "payload")


def _data(payload, name):
    return os.path.join(payload, "data", name)


def _logger(path):
    f = open(path, "a", encoding="utf-8")

    def log(msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(msg, flush=True)
        f.write(line + "\n")
        f.flush()
    return log, f


def check_game(game, payload, running=gamecheck.game_running):
    sites = json.load(open(_data(payload, "exe-sites.json"), encoding="utf-8"))
    originals = json.load(open(_data(payload, "originals.json"), encoding="utf-8"))
    gamecheck.check(game, sites, originals, running=running)


def find_downloads(payload, roots, work):
    items = downloads.load(_data(payload, "downloads.json"))
    return items, downloads.locate(items, roots, work)


def report_downloads(items, found, log):
    ok = [i for i in items if isinstance(found[i], downloads.Found)]
    log("Downloads found: %d of %d" % (len(ok), len(items)))
    for i in items:
        f = found[i]
        if isinstance(f, downloads.Found):
            log("  ok       %s" % items[i]["name"])
        else:
            log("  MISSING  %s" % f.reason)
    return ok


def check(game, roots, payload=None):
    """Lists what is found and what is missing; changes nothing in the game folder."""
    payload = payload or payload_dir()
    work = os.path.join(os.environ.get("TEMP", game), "ftedition-check-%d" % os.getpid())
    try:
        check_game(game, payload)
        items, found = find_downloads(payload, roots, work)
        report_downloads(items, found, print)
        return found
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install(game, roots, payload=None, running=gamecheck.game_running, log=None):
    game = os.path.abspath(game)
    payload = payload or payload_dir()
    check_game(game, payload, running=running)
    j = journal.Journal.open(game)  # refuses an earlier install
    # The work folder is outside the game folder: the car installer watches the whole game tree for changes, and its
    # own records must not be in it. LOCALAPPDATA is always writable; FTEDITION_WORK overrides it (tests).
    base = os.environ.get("FTEDITION_WORK") or os.path.join(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP", game),
                                                           "FTownEdition")
    work = os.path.join(base, "work-%s" % time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(work, exist_ok=True)
    own_log = None
    if log is None:
        log, own_log = _logger(os.path.join(game, journal.FOLDER, "install.log"))
    try:
        log("NFSMW F-Town Edition %s: installing into %s" % (VERSION, game))
        items, found = find_downloads(payload, roots, work)
        report_downloads(items, found, log)
        ctx = steps.Ctx(game, payload, work, found, j, log)
        all_steps = steps.all_steps(steps.load_cars_order(payload))
        done, skipped = steps.run_all(ctx, all_steps, log)
        j.finish({"version": VERSION, "done": done, "skipped": skipped,
                  "downloads": {i: isinstance(found[i], downloads.Found) for i in items}})
        log("Finished: %d steps done, %d skipped." % (len(done), len(skipped)))
        for sid, why in skipped.items():
            log("  skipped %s: %s" % (sid, why))
        return done, skipped
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if own_log:
            own_log.close()


def uninstall(game, running=gamecheck.game_running):
    game = os.path.abspath(game)
    if running():
        raise gamecheck.Refused("the game (speed.exe) is running: close it first")
    log_copy = os.path.join(game, journal.FOLDER, "install.log")
    kept = None
    if os.path.exists(log_copy):
        kept = os.path.join(os.environ.get("TEMP", game), "FTownEdition-install-%d.log" % os.getpid())
        shutil.copyfile(log_copy, kept)
    report = journal.uninstall(game)
    report["install_log"] = kept
    return report
