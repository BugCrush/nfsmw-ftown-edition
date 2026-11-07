"""Shows how the files in CUSTOM SONGS will appear in the game's EA Trax list.

The naming rule (the same one music/src/SongName.h uses, both checked against
music/tests/name-cases.tsv): "<title>_<artist>.mp3", split at the LAST underscore, spaces trimmed.
A name that doesn't fit becomes the title, with artist "Unknown".

    python tools/songs.py            list the folder
    python tools/songs.py --test     check the rule against music/tests/name-cases.tsv
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "CUSTOM SONGS")
CASES = os.path.join(ROOT, "music", "tests", "name-cases.tsv")


def parse_song_name(file_name):
    stem = file_name[:-4] if file_name.lower().endswith(".mp3") and len(file_name) > 4 else file_name
    title, sep, artist = stem.rpartition("_")
    title, artist = title.strip(" \t"), artist.strip(" \t")
    if not sep or not title or not artist:
        return stem.strip(" \t"), "Unknown"
    return title, artist


def game_text(text):
    """The text as the game will draw it: its font covers Windows-1252 only, other letters become '?'.
    ('$' is drawn as it is: the plugin hands the game '$$', which the game shows as one '$'.)"""
    return text.encode("cp1252", errors="replace").decode("cp1252")


def scan(folder):
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder)
             if f.lower().endswith(".mp3") and len(f) > 4 and os.path.isfile(os.path.join(folder, f))]
    songs = [(f,) + parse_song_name(f) for f in files]
    return sorted(songs, key=lambda s: (s[1].lower(), s[0].lower()))


def run_test():
    failures = cases = 0
    with open(CASES, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            file_name, want_title, want_artist = line.split("\t")
            cases += 1
            got = parse_song_name(file_name)
            if got != (want_title, want_artist):
                failures += 1
                print(f"FAIL {file_name!r}: got {got!r}, want {(want_title, want_artist)!r}")
    print(f"{cases} name cases, {failures} failures")
    return 1 if failures else 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--test" in sys.argv:
        return run_test()
    songs = scan(FOLDER)
    if not songs:
        print(f"No .mp3 files in {FOLDER}")
        return 0
    seen = {}
    print(f"{len(songs)} songs in {FOLDER}, in menu order:\n")
    for file_name, title, artist in songs:
        notes = []
        if artist == "Unknown":
            notes.append("no <title>_<artist> pattern: whole name used as the title")
        for label, text in (("title", title), ("artist", artist)):
            if game_text(text) != text:
                notes.append(f"the game can't draw every letter of the {label}: it will show {game_text(text)!r}"
                             " (a stand-in name if nothing readable is left)")
        key = (title.lower(), artist.lower())
        if key in seen:
            notes.append(f"same title and artist as {seen[key]!r}")
        seen[key] = file_name
        print(f"  {title}  -  {artist}")
        print(f"      file: {file_name}")
        for note in notes:
            print(f"      NOTE: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
