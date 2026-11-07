import os
import tempfile

import patchmap_check

LOG = """EXE speed.exe base=00400000 size=0x678E4E
IMPORT slot=0x008900A0 import=DINPUT8.dll!DirectInput8Create module=InputBridge.asi+0x1234
SECTION name=.text start=0x00401000 size=0x48E2A5 changed=15 import-slot-bytes=0
RANGE start=0x004DF330 len=5 section=.text
TARGET at=0x004DF330 kind=jmp dest=0x10001000 module=MusicBridge.asi+0x1000
OWNER start=0x004DF330 owner=MusicBridge.asi+0x1000
RANGE start=0x0082BFD0 len=5 section=.text
TARGET at=0x0082BFD0 kind=jmp dest=0x20001000 module=X360Stuff.asi+0x1000
OWNER start=0x0082BFD0 owner=X360Stuff.asi+0x1000
RANGE start=0x008C5F58 len=4 section=.rdata
TARGET at=0x008C5F58 kind=ptr dest=0x10002000 module=MusicBridge.asi+0x2000
OWNER start=0x008C5F58 owner=MusicBridge.asi+0x2000
DONE ranges=3 bytes=14 imports=1
"""
OURS = """# address-or-import  module  what
0x4DF330 MusicBridge.asi builder
0x82BFD0 MusicBridge.asi lookup
0x517070 MusicBridge.asi next song
0x8C5F58 MusicBridge.asi play slot
DINPUT8.dll!DirectInput8Create InputBridge.asi DirectInput
"""


def _files():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "PatchMap.log"), "w").write(LOG)
    open(os.path.join(d, "ours.txt"), "w").write(OURS)
    return os.path.join(d, "PatchMap.log"), os.path.join(d, "ours.txt")


def test_verdicts():
    log, ours = _files()
    rows = {r["what"]: r for r in patchmap_check.check(log, ours)}
    assert rows["builder"]["verdict"] == "ours"
    assert rows["lookup"]["verdict"] == "taken by X360Stuff.asi"
    assert rows["next song"]["verdict"] == "not patched"
    assert rows["play slot"]["verdict"] == "ours"
    assert rows["DirectInput"]["verdict"] == "ours"


def test_exit_code_reports_conflicts():
    log, ours = _files()
    assert patchmap_check.main([log, ours]) == 1
    clean = LOG.replace("X360Stuff.asi", "MusicBridge.asi")
    open(log, "w").write(clean)
    assert patchmap_check.main([log, ours]) == 0


def test_address_inside_a_longer_range_counts():
    log, ours = _files()
    open(log, "w").write(LOG.replace("RANGE start=0x004DF330 len=5", "RANGE start=0x004DF32E len=9")
                         .replace("OWNER start=0x004DF330", "OWNER start=0x004DF32E"))
    rows = {r["what"]: r for r in patchmap_check.check(log, ours)}
    assert rows["builder"]["verdict"] == "ours"


def test_a_place_two_of_our_plugins_share():
    # VisualBridge wraps GfxProbe on the D3DX import: "GfxProbe.asi|VisualBridge.asi" accepts either as the owner,
    # and still reports a third module.
    log = LOG.replace("DONE", "IMPORT slot=0x008904C0 import=d3dx9_26.dll!D3DXCreateEffectFromResourceA module=VisualBridge.asi+0x1610\nDONE")
    d = tempfile.mkdtemp()
    open(os.path.join(d, "PatchMap.log"), "w").write(log)
    ours = os.path.join(d, "ours.txt")
    open(ours, "w").write("d3dx9_26.dll!D3DXCreateEffectFromResourceA GfxProbe.asi|VisualBridge.asi effects\n"
                          "0x82BFD0 MusicBridge.asi|InputBridge.asi lookup\n")
    rows = {r["what"]: r for r in patchmap_check.check(os.path.join(d, "PatchMap.log"), ours)}
    assert rows["effects"]["verdict"] == "ours", rows["effects"]
    assert rows["lookup"]["verdict"] == "taken by X360Stuff.asi", rows["lookup"]
