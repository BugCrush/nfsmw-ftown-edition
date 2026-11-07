"""stage4.py's pieces that need no game copy: the 4 GB flag and the list of files."""
import os
import struct

import stage4

GAME = os.path.join(stage4.ROOT, "Need For Speed Most Wanted Black Edition - backup before x360")


def _pe(chars):
    data = bytearray(512)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x80 + 22, chars)
    return bytes(data)


def test_sets_only_the_large_address_flag():
    out = stage4.large_address_aware(_pe(0x010F))
    assert struct.unpack_from("<H", out, 0x80 + 22)[0] == 0x012F
    assert out[:0x80 + 22] == _pe(0x010F)[:0x80 + 22] and out[0x80 + 24:] == _pe(0x010F)[0x80 + 24:]


def test_flag_already_set_changes_nothing():
    assert stage4.large_address_aware(_pe(0x012F)) == _pe(0x012F)


def test_refuses_a_non_pe_file():
    try:
        stage4.large_address_aware(bytes(512))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_the_real_exe_differs_in_one_bit():
    exe = open(os.path.join(GAME, "speed.exe"), "rb").read()
    out = stage4.large_address_aware(exe)
    diff = [i for i in range(len(exe)) if exe[i] != out[i]]
    assert len(diff) == 1 and out[diff[0]] ^ exe[diff[0]] == 0x20


def test_unlocked_files_match_known_ones():
    # the game ships FrontEndMemoryFile.bin already unlocked; the pack's empty cache is Binarius's LongUnlock output
    assert stage4.UNLOCKED == open(os.path.join(GAME, "GLOBAL", "FrontEndMemoryFile.bin"), "rb").read()
    u = stage4.unlocked_memory_files(GAME)
    assert len(u[r"GLOBAL\GlobalMemoryFile.bin"]) == 366
    assert set(u) == {r"GLOBAL\GlobalMemoryFile.bin", r"GLOBAL\FrontEndMemoryFile.bin",
                      r"GLOBAL\InGameMemoryFile.bin", r"GLOBAL\PermanentMemoryFile.bin"}  # no CarHeaders file


def test_copies_cover_music_engines_movies_and_vinyls():
    c = stage4.copies(GAME)
    rels = [r for _, r in c]
    assert len([r for r in rels if r.startswith("SOUND\\PFDATA\\")]) == 2
    assert len([r for r in rels if r.startswith("SOUND\\ENGINE\\")]) == 87
    assert len([r for r in rels if r.startswith("MOVIES\\")]) == 33
    # 45 in the mod; the game has no VINYLS.BIN for BMWM3CSL and SKYLINE, which the mod's script then skips
    assert len([r for r in rels if r.endswith("\\VINYLS.BIN")]) == 43
    assert r"CARS\BMWM3CSL\VINYLS.BIN" not in rels and r"CARS\SKYLINE\VINYLS.BIN" not in rels
    assert r"CARS\TEXTURES.BIN" in rels
    assert all(os.path.isfile(s) for s, _ in c)
    # every replaced file exists in the game under the same name (only eahd_bumper is new)
    missing = [r for r in rels if not os.path.exists(os.path.join(GAME, r))]
    assert missing == [r"MOVIES\eahd_bumper_english_ntsc.vp6"], missing
