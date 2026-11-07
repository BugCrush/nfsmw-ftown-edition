"""FTownEditionInstaller: install, uninstall or check NFSMW F-Town Edition.

    FTownEditionInstaller.exe install   --game <game folder> --downloads <folder> [--downloads <folder> ...]
                                        [--profiles yes|no]   (our controller layout in existing profiles; default yes)
    FTownEditionInstaller.exe uninstall --game <game folder>
    FTownEditionInstaller.exe check     --game <game folder> --downloads <folder>

Run with no arguments, it asks for the two folders and what to do. Exit code 0 done, 2 refused, 1 failed.
"""
import argparse
import sys
import traceback

from . import VERSION, app, gamecheck, journal

REFUSALS = (gamecheck.Refused, journal.Refused)


def _ask():
    print("NFSMW F-Town Edition %s installer" % VERSION)
    print("1 = install, 2 = uninstall, 3 = check my downloads")
    choice = input("Choose 1, 2 or 3: ").strip()
    game = input("Game folder (the one with speed.exe): ").strip().strip('"')
    args = ["install", "uninstall", "check"][int(choice) - 1:int(choice)]
    if not args:
        raise SystemExit("no such choice")
    args += ["--game", game]
    if args[0] != "uninstall":
        args += ["--downloads", input("Downloads folder (the other mods, extracted): ").strip().strip('"')]
    if args[0] == "install":
        print("New profiles get the mod's controller layout (Xbox pad: RT accelerate, LT brake, right stick shifts).")
        answer = input("Put the same layout into your existing profiles too? Each is backed up first. [Y/n]: ")
        args += ["--profiles", "no" if answer.strip().lower() in ("n", "no") else "yes"]
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    interactive = not argv
    if interactive:
        argv = _ask()
    ap = argparse.ArgumentParser(prog="FTownEditionInstaller", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["install", "uninstall", "check"])
    ap.add_argument("--game", required=True)
    ap.add_argument("--downloads", action="append", default=[])
    ap.add_argument("--profiles", choices=["yes", "no"], default="yes")
    args = ap.parse_args(argv)
    code = 0
    try:
        if args.action == "install":
            if not args.downloads:
                ap.error("install needs --downloads")
            done, skipped = app.install(args.game, args.downloads, profiles=args.profiles == "yes")
            print("\nInstalled. %d parts skipped (see above)." % len(skipped) if skipped else "\nInstalled, everything.")
        elif args.action == "uninstall":
            r = app.uninstall(args.game)
            print("Uninstalled: %d files restored, %d removed." % (len(r["restored"]), len(r["removed"])))
            for rel in r["edited_after_install"]:
                print("  note: %s had been changed after the install; the original is back" % rel)
            for rel in r.get("profiles_restored", []):
                print("  profile %s: its controller bindings from before the install are back" % rel.split("/")[-1])
            for rel in r.get("profiles_kept", []):
                print("  profile %s: played since the install, so it is kept as it is; to get the game's own controller"
                      " bindings back, use Restore Defaults in its Controls menu" % rel.split("/")[-1])
        else:
            app.check(args.game, args.downloads)
    except REFUSALS as e:
        print("\nREFUSED: %s" % e)
        code = 2
    except Exception as e:  # a failure: the journal holds what to undo
        traceback.print_exc()
        print("\nFAILED: %s\nNothing is lost: run the installer's uninstall to put the game back as it was." % e)
        code = 1
    if interactive:
        input("\nPress Enter to close.")
    return code


if __name__ == "__main__":
    sys.exit(main())
