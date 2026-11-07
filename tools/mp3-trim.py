"""Removes the start of an MP3 without re-encoding it: whole MP3 frames are dropped and the rest is
copied byte for byte. (The first few milliseconds after the cut can decode slightly differently in
principle, because an MP3 frame may borrow data from the one before; check a result with
music/tests/pcm-compare.)

    python tools/mp3-trim.py "<file.mp3>" --start 5            trim in place (a backup is kept)
    python tools/mp3-trim.py "<file.mp3>" --start 5 --out x.mp3
    python tools/mp3-trim.py --test

An MP3 is a chain of frames of 1152 samples (26.1 ms at 44,100 Hz). --start is rounded UP to a
whole frame, so at least that many seconds are removed. Everything before the audio is kept: every
ID3 tag (title, artist, cover; some files have two) and any padding. The encoder's info frame
(Xing/Info, which stores the old length) is dropped; players then work the length out from the file
itself. In-place trimming first copies the original to song-backups/ (git-ignored) under the same
name with a timestamp, checks the copy, writes the result to a temporary file and moves it into place.
MPEG-1 Layer III only (the usual MP3).
"""
import hashlib
import math
import os
import shutil
import sys
import time

BITRATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]  # MPEG-1 Layer III, kbps
RATES = [44100, 48000, 32000, 0]
SAMPLES_PER_FRAME = 1152


def frame_at(data, pos):
    """(length in bytes, sample rate, channel mode) of the MPEG-1 Layer III frame at pos, or None."""
    if pos + 4 > len(data) or data[pos] != 0xFF or (data[pos + 1] & 0xFE) != 0xFA:
        return None
    bitrate = BITRATES[data[pos + 2] >> 4]
    rate = RATES[(data[pos + 2] >> 2) & 3]
    if not bitrate or not rate:
        return None
    padding = (data[pos + 2] >> 1) & 1
    return 144000 * bitrate // rate + padding, rate, data[pos + 3] >> 6


def id3v2_size(data):
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    return 10 + size + (10 if data[5] & 0x10 else 0)


def is_first_frame(data, pos):
    """A frame header at pos that is followed by another frame (or by the end of the file). A lone
    sync-like pattern in padding or tag data is not followed by one."""
    f = frame_at(data, pos)
    if not f:
        return False
    after = pos + f[0]
    return after >= len(data) - 4 or frame_at(data, after) is not None


def parse(data):
    """Returns (start of audio, list of (offset, length) for every frame, sample rate, end of audio).
    Everything before the start of audio (all ID3v2 tags, any padding) is the file's head."""
    pos = 0
    while data[pos:pos + 3] == b"ID3":  # some files have two tags back to back
        pos += id3v2_size(data[pos:])
    while pos < len(data) - 4 and not is_first_frame(data, pos):
        pos += 1
    start = pos
    frames, rate = [], 0
    while True:
        f = frame_at(data, pos)
        if not f or pos + f[0] > len(data):
            break
        frames.append((pos, f[0]))
        rate = f[1]
        pos += f[0]
    return start, frames, rate, pos


def is_info_frame(data, offset, length):
    chunk = data[offset:offset + min(length, 200)]
    return b"Xing" in chunk or b"Info" in chunk or b"VBRI" in chunk


def trim(data, seconds):
    """Returns (new file bytes, seconds removed, frames removed, frames kept)."""
    start, frames, rate, end = parse(data)
    if not frames:
        raise ValueError("no MPEG-1 Layer III frames found: not an MP3 this tool can trim")
    info = 1 if is_info_frame(data, *frames[0]) else 0
    audio = frames[info:]
    drop = math.ceil(seconds * rate / SAMPLES_PER_FRAME)
    if drop >= len(audio):
        raise ValueError("the song is shorter than that")
    keep_from = audio[drop][0]
    return data[:start] + data[keep_from:], drop * SAMPLES_PER_FRAME / rate, drop, len(audio) - drop


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def trim_file(path, seconds, out_path, backups):
    """Trims path. out_path None = in place, after copying the original into `backups` and checking
    the copy. The result is written to a temporary file first and then moved into place, so a failed
    write never leaves a half-written song. Returns 0 on success, 1 if nothing was changed."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        out, removed, dropped, kept = trim(data, seconds)
    except ValueError as error:
        print(f"not trimmed: {error}")
        return 1
    rate = parse(data)[2]
    if out_path is not None and os.path.exists(out_path) and os.path.samefile(path, out_path):
        print("--out is the input file: leave --out off to trim in place (a backup is then kept)")
        return 1
    if out_path is None:
        os.makedirs(backups, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(path))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(backups, f"{stem} (original {stamp}){ext}")
        number = 2
        while os.path.exists(backup):  # never overwrite an earlier backup
            backup = os.path.join(backups, f"{stem} (original {stamp} {number}){ext}")
            number += 1
        shutil.copy2(path, backup)
        if sha256(backup) != hashlib.sha256(data).hexdigest():
            print("the backup does not match the original; nothing changed")
            return 1
        print(f"backup: {backup}")
        out_path = path
    temporary = out_path + ".trimming"
    with open(temporary, "wb") as fh:
        fh.write(out)
    os.replace(temporary, out_path)
    print(f"removed {removed:.3f} s ({dropped} frames); {kept} frames remain = {kept * SAMPLES_PER_FRAME / rate:.3f} s")
    print(f"wrote {out_path} ({len(out)} bytes, was {len(data)})")
    return 0


def parse_args(args):
    """(file, seconds, out or None), or None if the arguments don't make sense. The file is the one
    argument that isn't an option or an option's value, wherever it stands."""
    path = seconds = out = None
    i = 0
    while i < len(args):
        if args[i] in ("--start", "--out") and i + 1 < len(args):
            if args[i] == "--start":
                try:
                    seconds = float(args[i + 1])
                except ValueError:
                    return None
            else:
                out = args[i + 1]
            i += 2
        elif path is None and not args[i].startswith("--"):
            path = args[i]
            i += 1
        else:
            return None
    return (path, seconds, out) if path is not None and seconds is not None else None


def run_test():
    def frame(number, padding=0):
        header = bytes([0xFF, 0xFB, 0xE0 | (padding << 1), 0x40])  # 320 kbps, 44,100 Hz, joint stereo
        length = 144000 * 320 // 44100 + padding
        return header + bytes([number % 251]) * (length - 4)

    tag = b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"T" * 10
    info = bytearray(frame(0))
    info[36:40] = b"Info"
    audio = [frame(i + 1, padding=i % 2) for i in range(400)]
    tail = b"TAG" + b"x" * 125
    data = tag + bytes(info) + b"".join(audio) + tail
    out, removed, dropped, kept = trim(data, 5)
    checks = [
        ("frames removed for 5 s (ceil(5*44100/1152))", dropped, 192),
        ("frames kept", kept, 208),
        ("seconds removed", round(removed, 4), round(192 * 1152 / 44100, 4)),
        ("the ID3v2 tag is kept", out[:len(tag)], tag),
        ("the info frame is gone and audio starts at frame 193", out[len(tag):len(tag) + 5], audio[192][:5]),
        ("everything after is byte for byte the original", out[len(tag):], b"".join(audio[192:]) + tail),
        ("the result parses as 208 frames", len(parse(out)[1]), 208),
    ]
    no_tag = bytes(info) + b"".join(audio)
    checks.append(("a file with no ID3 tag works too", trim(no_tag, 1)[2], math.ceil(44100 / 1152)))
    no_info = tag + b"".join(audio)
    checks.append(("a file with no info frame: its first frame is audio", trim(no_info, 0.01)[3], 399))
    try:
        trim(data, 60)
        too_long = False
    except ValueError:
        too_long = True
    checks.append(("asking for more than the song is refused", too_long, True))
    try:
        trim(b"not an mp3 at all" * 100, 1)
        junk = False
    except ValueError:
        junk = True
    checks.append(("a file that isn't an MP3 is refused", junk, True))

    # Files from some tools carry two ID3v2 tags back to back (six of the user's seven songs do):
    # both must survive.
    tag2 = b"ID3\x04\x00\x00\x00\x00\x00\x14" + b"L" * 20
    two = tag + tag2 + bytes(info) + b"".join(audio) + tail
    out2 = trim(two, 5)[0]
    checks.append(("a second ID3 tag is kept too", out2[:len(tag) + len(tag2)], tag + tag2))
    checks.append(("and the audio after it is the original from frame 193", out2[len(tag) + len(tag2):], b"".join(audio[192:]) + tail))
    padded = tag + b"\x00" * 64 + bytes(info) + b"".join(audio)
    checks.append(("padding between the tag and the audio is kept", trim(padded, 5)[0][:len(tag) + 64], tag + b"\x00" * 64))
    lone = tag + b"\xFF\xFB\xE0\x40" + b"\x01" * 30 + bytes(info) + b"".join(audio)  # a stray sync-like byte run
    checks.append(("a sync pattern not followed by a second frame is not taken for audio", len(parse(lone)[1]), 401))

    # Writing: through a temporary file, with a verified backup, never over the input by accident.
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        song = os.path.join(folder, "Song_Artist.mp3")
        with open(song, "wb") as fh:
            fh.write(data)
        backups = os.path.join(folder, "backups")
        checks.append(("--out equal to the input is refused", trim_file(song, 5, song, backups), 1))
        with open(song, "rb") as fh:
            checks.append(("and the input is untouched", fh.read() == data, True))
        other = os.path.join(folder, "out.mp3")
        checks.append(("--out to another file works", trim_file(song, 5, other, backups), 0))
        with open(other, "rb") as fh:
            checks.append(("with the trimmed content", fh.read() == out, True))
        checks.append(("and makes no backup", os.path.isdir(backups), False))
        checks.append(("in place works", trim_file(song, 5, None, backups), 0))
        with open(song, "rb") as fh:
            checks.append(("the file now holds the trimmed content", fh.read() == out, True))
        kept_backups = os.listdir(backups)
        with open(os.path.join(backups, kept_backups[0]), "rb") as fh:
            checks.append(("the backup is the original, byte for byte", fh.read() == data, True))
        checks.append(("a second trim in the same second gets its own backup",
                       (trim_file(song, 1, None, backups), len(os.listdir(backups))), (0, 2)))
        checks.append(("no temporary file is left behind", sorted(os.listdir(folder)), ["Song_Artist.mp3", "backups", "out.mp3"]))
    checks.append(("the file may come after the options", parse_args(["--start", "5", "a b.mp3"]), ("a b.mp3", 5.0, None)))
    checks.append(("or before them", parse_args(["a b.mp3", "--start", "2.5", "--out", "c.mp3"]), ("a b.mp3", 2.5, "c.mp3")))
    checks.append(("a missing --start is an error", parse_args(["a.mp3"]), None))
    failures = 0
    for name, got, want in checks:
        ok = got == want
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r:.60}, want {want!r:.60}"))
    print(f"{failures} failures")
    return 1 if failures else 0


def main():
    args = sys.argv[1:]
    if "--test" in args:
        return run_test()
    parsed = parse_args(args)
    if not parsed:
        print(__doc__)
        return 2
    path, seconds, out_path = parsed
    backups = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "song-backups")
    return trim_file(path, seconds, out_path, backups)


if __name__ == "__main__":
    sys.exit(main())
