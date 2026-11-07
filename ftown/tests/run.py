"""Builds FTownLoader.asi (and WorldProbe.asi for the coexistence variants) and the stand-in, runs every variant and
checks it.

    python ftown/tests/run.py [variant ...]

Each variant runs in ftown/tests/out/<variant>/ (git-ignored) with its own FTownLoader.ini, made from
ftown/FTownLoader.ini (the file that is installed, which names the city: ftown-city.bun and its two spawns) with the
variant's changes, and a copy of ftown/ftown-slab.bun. The stage 1 variants (the slab) set the slab's file and spawn
(SLAB_INI); the city variants use test maps made by make_test_maps.py (three sections and packs, and a 100 MB file).
The stand-in (standin.cpp) prints what the game's functions received: LOADCHUNKS, ADDDYN, HEIGHT, TELEPORT, ORIENT,
VELOCITY, REMOVEDYN, LISTDTOR, FASTFREE, UNLOADCHUNKS, BUFFER FREED, TRACKUNLOAD, GRID BEFORE/AFTER. Exit code 1 if
any check fails.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
INI = os.path.join(ROOT, "ftown", "FTownLoader.ini")
WP_INI = os.path.join(ROOT, "world", "WorldProbe.ini")
MAP = os.path.join(ROOT, "ftown", "ftown-slab.bun")
RELOC = os.path.join(ROOT, ".superpowers", "world", "ftown-reloc.bun")
CITY = os.path.join(ROOT, "ftown", "ftown-city.bun")  # the real city (git-ignored; tools/citymap/build_city.py)
# its collision instances, from the numbers committed beside it (835 for the streets; the landmarks stage's city has
# its own, ftown/ftown-city.json "grid")
try:
    with open(os.path.join(ROOT, "ftown", "ftown-city.json")) as _f:
        CITY_INSTANCES = json.load(_f)["grid"]["instances"]
except (OSError, ValueError, KeyError):
    CITY_INSTANCES = 835
MAPS = os.path.join(HERE, "out", "maps")
CITY3 = os.path.join(MAPS, "city3.bun")
# the breakable poles (FTownSmack.h): city3 with three poles as instances, their spawner file, one of another city, the
# real one (git-ignored; tools/citymap/build_city.py writes it with the city)
CITY3P = os.path.join(MAPS, "city3p.bun")
SMK3 = os.path.join(MAPS, "smk3.bun")
SMK3_BAD = os.path.join(MAPS, "smk3-bad.bun")
REAL_SMK = os.path.join(ROOT, "ftown", "ftown-smackables.bun")
BIG = os.path.join(MAPS, "big.bun")
REAL_BAR = os.path.join(ROOT, "ftown", "ftown-barriers.bun")  # the real barriers (git-ignored; race_barriers.py)
try:
    with open(os.path.join(ROOT, "ftown", "ftown-barriers.json")) as _f:
        BAR_INSTANCES = json.load(_f)["collision_instances"]
except (OSError, ValueError, KeyError):
    BAR_INSTANCES = 72
BAR = os.path.join(MAPS, "bar.bun")  # the race barriers' test file (make_test_maps.py), installed as ftown-barriers.bun
# the stage 1 variants run on the slab: its file and spawn (the shipped ini names the city)
SLAB_INI = {("Map", "File"): "ftown-slab.bun", ("Spawn", "Spawn1"): "2000, 11430, 101, 90", ("Spawn", "Spawn2"): ""}
CITY3_INI = {("Map", "File"): "city3.bun", ("Spawn", "Spawn1"): "2000, 11500, 101, 90",
             ("Spawn", "Spawn2"): "2300, 11500, 101, 0"}
SMK_INI = {**CITY3_INI, ("Map", "File"): "city3p.bun"}
LINK_INI = dict(CITY3_INI)
LINK_WANT = {"map": os.path.join(HERE, "out", "maps", "city3.bun"), "net": "link", "link": "ok"}
SMK_TELEPORT = "TELEPORT -11500.000 101.000 2000.000"
SMK_LOADED = "SMKLOAD packs 2 records 3 models 3 triggers 3 lost 0 past 0 live 3"
SMK_BACK = "SMK ROCKPORT TABLE ptr game count 22340 entries same live 0 flying 0"
SMK_START = "breakable poles: ftown-smackables.bun: 3 poles in 2 packs, override entries 22340.. after Rockport's 22340"
CHECKS = 61 + 9 + 12 + 35 + 16 + 9 + 4 + 15 + 9 + 9 + 5 + 5 + 2 + 11  # (+ Run K: the HUD features 2, the safe house icon 11) (+ Run J: the race start 6 + 3, the drag steering 5, the course line 5) (+ the Run I fixes' race HUD 4, radar 4 + 3, gears 2 + 2, parked cars' input 5 + 4) code sites and vtable slots FTownLoader checks at load (+ the minimap's 9, the events' 7 sites and 5 slots, the menu's 29 sites and 6 slots, the traffic's 16 sites and 9 slots, the evening's 4 sites)
MINIMAP = os.path.join(MAPS, "minimap.bun")  # a test map of 64 chops (tools/citymap/minimap.pack_bytes)
MM_FTOWN = "MINIMAP header FTOWN_MAP calibration -560.0 8940.0 5120.0"
MM_ROCK = "MINIMAP header MINI_MAP_QR_SPRINT1 calibration -1224.9 -1591.1 6659.3"
# the Time Attack's test course (on the slab's test ground: render x 1792..2368 has a face in the stand-in)
# since the events (plan 2026-11-04-ftown-events) the course is the first event of the test events file below (it was
# [TimeAttack] Start / Gate / Finish in the ini): start (2000, 11000) north through three gates 500 m apart to the
# finish at 13000
TA_INI = {}
# the test events (TEST_EVENTS, on the slab's test ground, every course north): 0 the Time Attack (x 2000), 1 the
# Drag (x 2100, a quarter mile), 2 the Speed Trap (x 2200, three cameras), 3 the Sector Sprint (x 1900, two
# checkpoints); each has its own barrier file name (the test barrier file bar.bun under each)
TEST_EVENTS = [
    ("timeattack", "Time Attack", "TIME ATTACK", "timeattack", "Route1", "ftown-barriers.bun", "0x1A091045", 2000.0,
     [("checkpoint", 11500.0), ("checkpoint", 12000.0), ("checkpoint", 12500.0), ("finish", 13000.0)]),
    ("drag", "Drag (DND-KMP Expressway)", "DRAG", "drag", "Drag", "ftown-barriers-drag.bun", "0xAAAB31E9", 2100.0,
     [("finish", 11402.34)]),
    ("speedtrap", "Speed Trap (Mathura Road)", "SPEED TRAP", "speedtrap", "SpeedTrap", "ftown-barriers-speedtrap.bun",
     "0x66C9A7B6", 2200.0, [("camera", 11500.0), ("camera", 12000.0), ("camera", 12500.0), ("finish", 13000.0)]),
    ("sprint", "Sector Sprint", "SECTOR SPRINT", "sprint", "SectorSprint", "ftown-barriers-sprint.bun", "0x2521E5EB",
     1900.0, [("checkpoint", 11600.0), ("checkpoint", 12200.0), ("finish", 12800.0)]),
]
TEST_EVENTS_FILE = os.path.join(HERE, "out", "maps", "events.json")
TEST_EVENTS_BAND = os.path.join(HERE, "out", "maps", "events-band.json")  # Run K item 3
TEST_EVENTS_BADBAND = os.path.join(HERE, "out", "maps", "events-badband.json")
REAL_EVENTS = os.path.join(ROOT, "ftown", "ftown-events.json")
MODES = "SCREEN modeselect options: Free Roam | Time Attack | Drag (DND-KMP Expressway) | Speed Trap (Mathura Road) | " \
        "Sector Sprint"
FE_DRAG = "fe=qr,pick:Bonus Maps,pick:F-Town,pick:Drag (DND-KMP Expressway),start"
FE_TRAP = "fe=qr,pick:Bonus Maps,pick:F-Town,pick:Speed Trap (Mathura Road),start"
FE_SPRINT = "fe=qr,pick:Bonus Maps,pick:F-Town,pick:Sector Sprint,start"
KMH = "1080.0 KM/H"  # 10 m a frame at the stand-in's 30 frames a second
TA_START = "TELEPORT -11000.000 101.000 2000.000"
# Run I item 6: every message asked once (not single frame), as the game asks its race lines
MSG = "HUDMSG prio 3 single 0 script 8AB83EDB icon 0 text "
# the game mode (Task 4): the shipped keys setting (off; every older variant runs with [Keys] Enabled = 1), the menu
# paths to each mode, and the menu's own checks (FTownGame.h kGameSites and kGameSlots)
KEYS_OFF = {("Keys", "Enabled"): "0"}
FE_TA = "fe=qr,pick:Bonus Maps,pick:F-Town,pick:Time Attack,start"
EARLY = {("Game", "StartEarly"): "1"}  # Run I item 12: the shipped value (the older variants run with 0)
FE_FR = "fe=qr,pick:Bonus Maps,pick:F-Town,pick:Free Roam,start"
SLAB = os.path.getsize(MAP)  # bytes of the shipped slab file
# the traffic cars: the test spots (every 40 m along five north-south lines over the slab's test ground; x 1950 and 2050
# flagged as by the Time Attack's route, which runs along x 2000), the real ones, and what must never show
TRAFFIC_SPOTS = os.path.join(MAPS, "traffic.json")
REAL_SPOTS = os.path.join(ROOT, "ftown", "ftown-traffic.json")
TRAFFIC_BAD = ["CALL ON DEAD", "DOUBLE KILL", "INVIEW", "CREATE BAD PARAM", "unknown key", "FIND BAD THIS"]

TELEPORT = "TELEPORT -11430.000 101.000 2000.000"
# the career's connection (FTownConnect.h): make_test_link.py's road and data, the test network with its join, the
# stand-in's drive (link: its zones; from frame 0 the car 1,000 m south of the junction, then north through 703 into
# 726 (F-Town in), on into 723 and our 226, into F-Town's test box, and back south)
LINK_BUN = os.path.join(MAPS, "link.bun")
LINK_BINS = {"ok": os.path.join(MAPS, "link.bin"), "badsize": os.path.join(MAPS, "link-badsize.bin"),
             "badwall": os.path.join(MAPS, "link-badwall.bin"), "badfaces": os.path.join(MAPS, "link-badfaces.bin")}
NET_LINK = os.path.join(MAPS, "net-link.bin")
NET_LINK_BAD = os.path.join(MAPS, "net-link-bad.bin")
LINK_DRIVE = ["link", "glide=0-5:1045,1000:1045,1000", "glide=20-60:1045,1000:1045,2500",
              "glide=60-120:1045,2500:1500,6000", "glide=120-160:1500,6000:2000,11000",
              "glide=200-260:2000,11000:1045,1000"]
LINK_726 = "726 766 703 743 704 744 309 1100 1101 1102 2601"
LINK_723 = "723 763 703 743 704 744 309 726 1100 1101 1102 2601"
LINK_OURS = "703 743 704 744 309 726 723 763 1100 1101 1102 2601"
LINK_LISTS_BACK = "LISTS sections 309 703 723 726 boundaries 309 703 723 726\n"  # (sorted; LINKS BROKEN after: bad)
# moving traffic (FTownRoadNet.h): the test networks (make_test_net.py: a street north along x 2000, a one-way east at
# y 12000; after the stand-in's own Rockport of 3 profiles, 4 nodes, 3 segments, 1 road), the real one, the sites it
# checks, and the stand-in's lines when the network is back as the game had it
NET_TEST = os.path.join(MAPS, "net.bin")
NET_MISMATCH = os.path.join(MAPS, "net-mismatch.bin")
NET_REALCITY = os.path.join(MAPS, "net-realcity.bin")  # the real network after the stand-in's Rockport
REAL_NET = os.path.join(ROOT, "ftown", "ftown-roadnet.bin")  # git-ignored (tools/citymap/roadnet_build.py)
CITYENV = os.path.join(ROOT, ".tools", "cityenv", "Scripts", "python.exe")
NET_CHECKS = 18
# the slab's one collision instance reaches the whole test ground only through a wide margin once its cells are real
NET_GROUND = {("Grid", "MarginMetres"): "2000"}
NET_BACK = ["NET counts 3 4 3 1 pointers game", "ROCKPORT records same", "GRIDNOW cols 92 min x -4800.0"]
# Run I item 13: the menu's icons (git-ignored, built from the user's icons/ by tools/ftownicons/make_icons.py)
ICONS_BUN = os.path.join(ROOT, "ftown", "ftown-icons.bun")
ICON_MORNING, ICON_EVENING, ICON_FREEROAM = "87FC212E", "2F931900", "D9B13185"
# the evening (FTownEvening.h): a lights list for the slab (its first six vertices, moved 0.1 m in x and recoloured), and
# a stale one (each day colour off by one); the stand-in's time of day starts at 0.3 and moves 0.01 a frame
LIGHTS = os.path.join(HERE, "out", "maps", "lights.bin")
LIGHTS_STALE = os.path.join(HERE, "out", "maps", "lights-stale.bin")
LIGHTS_WRAP = os.path.join(HERE, "out", "maps", "lights-wrap.bin")  # one entry at offset 0xFFFFFFE0 (review)
REAL_LIGHTS = os.path.join(ROOT, "ftown", "ftown-evening.bin")  # the real city's (git-ignored; build_city.py)
EVE_KEYS = {("Evening", "Keys"): "1"}
FE_EVE = "fe=qr,pick:Bonus Maps,pick:F-Town (Evening),pick:Free Roam,start"
DAY_TOD = "TOD f=20 t=0.510 rate=1.00 dir=1 head=0"  # the stand-in's own day at frame 20 (nothing held)
HELD = "t=0.950 rate=0.00 dir=1 head=1"
ORDER_LOAD = ["LOADCHUNKS", "ADDDYN cell", "HEIGHT -11430.00 101.00 2000.00", TELEPORT, "ORIENT row2 -1.000 0.000",
              "VELOCITY 0.0 0.0 0.0"]
# review: the cars' and the camera's colliders cache our instances; they are cleared (the game's SetExclusionFlags)
# after the grid removal and before UnloadChunks
ORDER_UNLOAD = ["REMOVEDYN tag 08350000", "LISTDTOR 0 elements left", "FASTFREE 12 bytes", "SETEXCLUSIONFLAGS\n",
                "COLLIDER CLEAR", "UNLOADCHUNKS %d bytes same buffer 1 readable 1 grid clean colliders clean" % SLAB,
                "BUFFER FREED"]
# the return before F7's or a second F8's unload (at F8 the car was at physics (-2400, 113, 1700), heading 36.87
# degrees): while F-Town is still loaded, Rockport streamed in at the saved spot (blocking), a face there, the car put
# back (row 2 = (-0.6, 0, 0.8)), velocity zeroed, the reset cookies replaced by the saved spot; then the unload
ORDER_RETURN = ["SETSTREAM -2400.00 113.00 1700.00 blocking 1 zoneoff 0",
                "HEIGHT -2400.00 114.00 1700.00 rockport -> face",
                "TELEPORT -2400.000 113.000 1700.000", "ORIENT row2 -0.600 0.000 0.800", "VELOCITY 0.0 0.0 0.0",
                "RESETPOS -2400.00 113.00 1700.00 dir -0.600 0.000 0.800"]
CAR_BACK = "colliders clean car rockport\n"

# variant: (ini changes {(section, key): value}, stand-in arguments, checks)
VARIANTS = {
    # the evening (FTownEvening.h, docs/ftown-notes.md "Evening (2026-11-05)"), on the slab with a lights list of six
    # vertices: F8 with [Evening] Keys = 1 lights them in the copy LoadChunks gets, holds the time at 0.95 (rate 0) and
    # forces the headlights while loaded; F7 puts back the time it found (0.40 at frame 10), the rate, the direction
    # and the headlights; the stand-in's own update then moves on from there
    "evening-keys": (EVE_KEYS, ["go=10", "unloadkey=40", "frames=60"],
                     {"lights": "test",
                      "out_has": ["LIGHTS lit 6 day 0 of 6", "TOD f=20 " + HELD, "TOD f=30 " + HELD,
                                  "TOD f=50 t=0.510 rate=1.00 dir=1 head=0"],
                      "order": ["LOADCHUNKS", TELEPORT, "TOD f=20 " + HELD, "UNLOADCHUNKS",
                                "TOD f=50 t=0.510 rate=1.00"],
                      "log_has": ["evening: time 0.95, headlights on; lights file ftown-evening.bin: 6 vertices",
                                  "EVENING LIGHTS: 6 vertices lit",
                                  "EVENING ON: time 0.400 -> 0.950, rate 1.00 -> 0 (held), direction 1; headlights "
                                  "forced on (ForceHeadlightsOn was 0)",
                                  "EVENING OFF (unload key): time 0.400, rate 1.00, direction 1 and ForceHeadlightsOn 0 "
                                  "put back"],
                      "log_not": ["WRONGBYTES", "REFUSED"], "checks_ok": CHECKS}),
    # F8 without [Evening] Keys: the day; the file as written (pristine), nothing of the time touched
    "evening-day": ({}, ["go=10", "frames=30"],
                    {"lights": "test",
                     "out_has": ["LIGHTS lit 0 day 6 of 6", "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB, DAY_TOD],
                     "log_not": ["EVENING ON", "EVENING LIGHTS"]}),
    # a stale list (day colours not in the file): no light applied, the file pristine; the time still held
    "evening-stale": (EVE_KEYS, ["go=10", "frames=30"],
                      {"lights": "stale",
                       "out_has": ["LIGHTS lit 0 day 0 of 6", "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB,
                                   "TOD f=20 " + HELD],
                       "log_has": ["EVENING LIGHTS REFUSED: vertex 0 at", "EVENING ON"]}),
    # review: an entry whose offset + 36 wraps past 2^32 is refused at start, nothing applied
    "evening-wrap": (EVE_KEYS, ["go=10", "frames=30"],
                     {"lights": "wrap", "out_has": ["LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB],
                      "log_has": ["REFUSED: an entry lies outside the city file"]}),
    # review: the AFTER lines report what the game's update (or a wrapper of it) left before our next write: here an
    # update that keeps its own time 0.6
    "evening-after": (EVE_KEYS, ["go=10", "frames=700", "todoverride"],
                      {"lights": "test", "log_has": ["EVENING AFTER 1 s: the update left time 0.600, rate 0.00"]}),
    # no lights file: the evening's time without lights
    "evening-nolights": (EVE_KEYS, ["go=10", "frames=30"],
                         {"out_has": ["LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB, "TOD f=20 " + HELD],
                          "log_has": ["lights file ftown-evening.bin cannot be opened: the evening without lights",
                                      "EVENING ON"]}),
    # SetTimeOfDay's bytes differ: the evening off, F-Town itself loads as by day
    "evening-wrongbytes": (EVE_KEYS, ["go=10", "frames=30", "evewrong"],
                           {"lights": "test",
                            "out_has": ["LIGHTS lit 0 day 6 of 6", TELEPORT, DAY_TOD],
                            "log_has": ["WRONGBYTES 0x007696B0", "WRONGBYTES in the evening's sites: F-Town (Evening) "
                                        "off (the rest works)"],
                            "log_not": ["EVENING ON", "FTownLoader does nothing"]}),
    # a race start sets the time (0.5) while F-Town (Evening) is loaded: held again at the next hook
    "evening-reassert": (EVE_KEYS, ["go=10", "todset=25", "frames=40"],
                         {"lights": "test", "order": ["TODSET 0.500", "TOD f=30 " + HELD]}),
    # the track unloads while loaded: everything put back before the game's unload runs on
    "evening-trackunload": (EVE_KEYS, ["go=10", "trackunload=30", "frames=50"],
                            {"lights": "test",
                             "order": ["TOD f=20 " + HELD, "UNLOADCHUNKS", "TRACKUNLOAD",
                                       "TOD f=40 t=0.510 rate=1.00 dir=1 head=0"],
                             "log_has": ["EVENING OFF (track unloading)"]}),
    # the player gone (the race left another way): put back
    "evening-player-gone": (EVE_KEYS, ["go=10", "gone=20-25", "frames=40"],
                            {"lights": "test", "out_has": ["TOD f=30 t=0.510 rate=1.00 dir=1 head=0"],
                             "log_has": ["EVENING OFF (player gone)"]}),
    # the menu: Bonus Maps lists F-Town and F-Town (Evening); the evening's mode list is titled so; Free Roam loads the
    # lit copy and holds the time
    "menu-evening": (KEYS_OFF, [FE_EVE, "countdown=30", "frames=200"],
                     {"lights": "test",
                      "order": ["SCREEN modeselect options: F-Town | F-Town (Evening)\n", "TITLE F-Town (Evening)",
                                "SCREEN modeselect options: Free Roam", "COUNTDOWN 0", "LOADCHUNKS", "LIGHTS lit 6 day 0 of 6",
                                TELEPORT, "TOD f=150 t=0.950 rate=0.00 dir=-1 head=1"],
                      "log_has": ["game: maps -> modes (F-Town (Evening) chosen)", "EVENING ON"]}),
    # the day's F-Town from the same menu: no lights, the time not touched
    "menu-day": (KEYS_OFF, [FE_FR, "countdown=30", "frames=200"],
                 {"lights": "test", "out_has": ["LIGHTS lit 0 day 6 of 6"],
                  "log_has": ["game: maps -> modes (F-Town chosen)"], "log_not": ["EVENING ON"]}),
    # Enabled = 0: no evening entry in the map list
    "menu-evening-off": ({**KEYS_OFF, ("Evening", "Enabled"): "0"}, ["fe=qr,pick:Bonus Maps", "frames=6"],
                         {"out_has": ["SCREEN modeselect options: F-Town\n"], "log_has": ["evening off ([Evening] Enabled = 0)"]}),
    # all checks ok; F8: LoadChunks with the file's bytes, grid entries, the height found, SetPosition with the spawn,
    # the heading, velocity zeroed, in that order
    "same": ({}, ["go=10"],
             {"out_has": ["HOOK patched", "UNLOADHOOK patched", "LOADCHUNKS %d bytes name FTOWN pristine 1 aligned 1" % SLAB,
                          "SPIN 0.0 0.0 0.0"],
              "out_not": ["DIRTY", "BAD THIS", "NOT FOUND", "UNLOADCHUNKS"],
              "order": ORDER_LOAD,
              "log_has": ["map file ftown-slab.bun: %d bytes, 1 scenery sections (2101), 1 collision packs (2101)" %
                          SLAB,
                          "hooked 0x00663D30 (per frame) and 0x006617E0 (TrackLoader::Unload)",
                          "scenery section 2101 filed: yes", "collision pack 2101 filed: yes",
                          "height at spawn 1: face at 100.00 (spawn 1.00 above)",
                          "TELEPORT from physics (-2400.00, 113.00, 1700.00) to render (2000.00, 11430.00, 101.00) = "
                          "physics (-11430.00, 101.00, 2000.00): set; velocity zeroed (rigid body vtable 0x008AC880)"],
              "log_re": [r"heading 90\.0 deg set: forward physics \(-1\.000, 0\.000, -?0\.000\) = render \(-?0\.000, "
                         r"1\.000, 0\.000\)",
                         r"grid: \d+ instances in 1 packs, \d+ entries in \d+ cells \(\d+ nodes of ours for empty "
                         r"cells\)"],
              "log_not": ["WRONGBYTES", "REFUSED", "NOT TELEPORTED"], "checks_ok": CHECKS}),
    # the height query finds nothing: no SetPosition; the grid entries out, then UnloadChunks, then the buffer freed
    "no-face": ({}, ["go=10", "noface"],
                {"out_not": ["TELEPORT", "VELOCITY", "STILL HAS OUR TAGS"],
                 "order": ["LOADCHUNKS", "ADDDYN cell", "-> none"] + ORDER_UNLOAD,
                 "out_has": ["grid clean"],
                 "log_has": ["NOT TELEPORTED: no face at spawn", "UNLOADED (no face at spawn)"]}),
    # the player goes (the race is left) while loaded: grid entries removed, then UnloadChunks, then the free
    "player-gone": ({}, ["go=10", "gone=20-25"],
                    {"order": [TELEPORT] + ORDER_UNLOAD, "out_has": ["grid clean", "LOADS 1 UNLOADS 1 LISTS 0 ELEMS 0"],
                     "out_not": ["STILL HAS OUR TAGS", "SETSTREAM"],
                     "log_has": ["player gone", "UNLOADED (player gone)"]}),
    # a second F8 while loaded: the car back to Rockport, then unload, not a second load (since the small fixes the
    # return comes first: 2 teleports)
    "double-key": ({}, ["go=10,20"],
                   {"out_has": ["LOADS 1 UNLOADS 1 LISTS 0 ELEMS 0", "grid clean", CAR_BACK],
                    "order": [TELEPORT] + ORDER_RETURN + ORDER_UNLOAD,
                    "log_has": ["UNLOADED (second go key while loaded)"], "teleports": 2}),
    # load, the player goes, comes back, F8: a fresh, pristine buffer is loaded again (the loaders change it in place)
    # review: the file is parsed at start and not kept in memory (40 MB for the city); each F8 reads it from disk
    # again into the fresh buffer: gone or changed after the start, F8 refuses and nothing is loaded
    "file-gone": ({}, ["go=10", "deletemap=5"],
                  {"out_has": ["MAP FILES DELETED"], "out_not": ["LOADCHUNKS", "TELEPORT"],
                   "log_has": ["the parsed copy released", "REFUSED: the map file ftown-slab.bun cannot be read again"]}),
    "file-changed": ({}, ["go=10", "changemap=5"],
                     {"out_has": ["MAP FILES CHANGED"], "out_not": ["LOADCHUNKS", "TELEPORT"],
                      "log_has": ["REFUSED: the map file ftown-slab.bun changed since the game started"]}),
    "restart": ({}, ["go=10,30", "gone=20-25"],
                {"out_has": ["LOADS 2 UNLOADS 1"], "out_not": ["DIRTY", "pristine 0"], "teleports": 2,
                 "count": {"LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB: 2}}),
    # a cell already holding a node of Rockport's (a static and a dynamic element): ours added to it, and after the
    # unload every cell holds exactly what it held before (no leftover lists or elements)
    "grid-restore": ({}, ["go=10", "unloadkey=20", "existingnode"],
                     {"out_has": ["ADDDYN cell 5152 tag", "LOADS 1 UNLOADS 1 LISTS 1 ELEMS 2"],
                      "grid_same": True, "log_has": ["UNLOADED (unload key)"]}),
    # review: something else joins one of our nodes while loaded: the node stays in its cell with that element, and
    # a later load never hands it out again (no node in two cells, the element kept)
    "kept-node": ({}, ["go=10,30", "unloadkey=20", "foreign=15", "frames=50"],
                  {"out_has": ["FOREIGN cell", "LOADS 2 UNLOADS 1", "d0000BEEF/1"], "out_not": ["DUPLICATE NODE"],
                   "log_has": ["some kept (other elements in them)"], "teleports": 3}),
    # the section number is taken: refused, nothing loaded
    "number-taken": ({}, ["go=10", "taken"],
                     {"out_not": ["LOADCHUNKS", "ADDDYN", "TELEPORT"],
                      "log_has": ["REFUSED: scenery section 2101 is taken"]}),
    # one address differs: WRONGBYTES, nothing patched, nothing loaded
    "wrongbytes": ({}, ["go=10", "wrongbytes"],
                   {"out_has": ["HOOK untouched", "UNLOADHOOK untouched"], "out_not": ["LOADCHUNKS", "TELEPORT"],
                    "log_has": ["WRONGBYTES 0x00782B30", "FTownLoader does nothing"], "log_not": ["hooked"]}),
    # F8 while the game window is not in front: nothing
    "background": ({}, ["go=10", "background"],
                   {"out_not": ["LOADCHUNKS", "TELEPORT"], "log_has": ["key ignored: the game window is not in front"]}),
    # the track is unloaded while ours is loaded: ours goes first, then the game's TrackLoader::Unload runs
    "track-unload": ({}, ["go=10", "trackunload=20"],
                     {"order": [TELEPORT] + ORDER_UNLOAD[:-1] + ["TRACKUNLOAD this 0x008F834C"],
                      "out_has": ["grid clean"], "out_not": ["SETSTREAM", "RESETPOS"],
                      "log_has": ["TrackLoader::Unload: the track is being unloaded", "UNLOADED (track unloading)"]}),
    # LoadChunks files nothing: not teleported, unloaded
    "not-filed": ({}, ["go=10", "nofile"],
                  {"out_not": ["TELEPORT", "ADDDYN"], "out_has": ["UNLOADCHUNKS"],
                   "log_has": ["NOT TELEPORTED: the game did not file our chunks"]}),
    # the relocated C9 (Task 5's game data, only where .superpowers/world/ftown-reloc.bun has been built): the same
    # path with a 10 MB file of Rockport's own chunks and its spawn
    "reloc": ({("Map", "File"): "ftown-reloc.bun", ("Spawn", "Spawn1"): "1989.73, 11521.51, 101.00, 0"},
              ["go=10", "unloadkey=20"],
              {"map": RELOC, "out_has": ["LOADCHUNKS 10322720 bytes name FTOWN pristine 1 aligned 1",
                                         "TELEPORT -11521.510 101.000 1989.730", "grid clean colliders clean",
                                         "BUFFER FREED"],
               "log_has": ["1 collision packs (2101) with 43 instances", "scenery section 2101 filed: yes",
                           "height at spawn 1: face at 100.00 (spawn 1.00 above)", "UNLOADED (unload key)"],
               "log_not": ["WRONGBYTES", "REFUSED", "NOT TELEPORTED"]}),
    # small fixes: F7 puts the car back where it was at F8 before F-Town goes (Run E: it fell for ever)
    "return-key": ({}, ["go=10", "unloadkey=20"],
                   {"order": [TELEPORT] + ORDER_RETURN + ORDER_UNLOAD, "out_has": [CAR_BACK], "teleports": 2,
                    "out_not": ["BAD THIS", "WITHOUT GROUND"],
                    "log_has": ["RETURN: Rockport streamed in at the saved spot (Sim::SetStream, blocking)",
                                "face at the saved spot: 112.50",
                                "RETURNED from physics (-11430.00, 101.00, 2000.00) to render (1700.00, 2400.00, "
                                "113.00) = physics (-2400.00, 113.00, 1700.00): set; velocity zeroed",
                                "reset cookies replaced by the saved spot (ResetCar::SetResetPosition)",
                                "UNLOADED (unload key)"],
                    "log_not": ["NOT RETURNED"]}),
    "return-double": ({}, ["go=10,20"],
                      {"order": [TELEPORT] + ORDER_RETURN + ORDER_UNLOAD, "out_has": [CAR_BACK], "teleports": 2}),
    # no face at the saved spot after streaming: nothing unloaded, the car stays on F-Town, the zone byte put back
    "return-noface": ({}, ["go=10", "unloadkey=20", "nohome"],
                      {"out_has": ["SETSTREAM -2400.00 113.00 1700.00 blocking 1 zoneoff 0",
                                   "HEIGHT -2400.00 114.00 1700.00 rockport -> none"],
                       "out_not": ["UNLOADCHUNKS", "RESETPOS", "TELEPORT -2400"], "teleports": 1,
                       "log_has": ["NOT RETURNED: no face at the saved spot after streaming",
                                   "F-Town stays loaded"]}),
    # review: zone switching disabled by the game means a menu or an NIS has borrowed the streamer's memory (the
    # results screen's SillyTextureStreamerManager 0x58E61F and the world map's UITrackMapStreamer 0x55A337 set the
    # byte, then MakeSpaceInPool 0x731040): no stream, no unload, the byte left as it is
    "return-zoneoff": ({}, ["go=10", "unloadkey=20", "zoneoff"],
                       {"out_not": ["SETSTREAM", "UNLOADCHUNKS", "TELEPORT -2400"], "out_has": ["ZONEBYTE 1"],
                        "log_has": ["NOT RETURNED: the game has zone switching disabled (0x9AAC81 = 1",
                                    "F-Town stays loaded"]}),
    # no simulation: no stream, no unload
    "return-nosim": ({}, ["go=10", "unloadkey=20", "nosim"],
                     {"out_not": ["SETSTREAM", "UNLOADCHUNKS"],
                      "log_has": ["NOT RETURNED: the simulation is not running", "F-Town stays loaded"]}),
    # no IResetable found: the car still goes back, the cookies are not replaced (logged), the unload goes on
    "return-noresetable": ({}, ["go=10", "unloadkey=20", "noresetable"],
                           {"out_has": [CAR_BACK], "out_not": ["RESETPOS"],
                            "log_has": ["reset cookies NOT replaced"]}),
    # [Return] Enabled = 0: the unload as before the small fixes (the car left without ground)
    "return-off": ({("Return", "Enabled"): "0"}, ["go=10", "unloadkey=20"],
                   {"order": [TELEPORT] + ORDER_UNLOAD, "out_has": ["colliders clean car ftown"],
                    "out_not": ["SETSTREAM", "RESETPOS"], "teleports": 1}),
    # WorldProbe 2 beside it, loaded before and after: both plugins check ok and run every frame
    "with-worldprobe-before": ({}, ["go=10", "worldprobe=before"],
                               {"out_has": ["HOOK patched", "WPHOOK patched", TELEPORT], "checks_ok": CHECKS,
                                "log_not": ["WRONGBYTES"], "wp": True}),
    "with-worldprobe-after": ({}, ["go=10", "worldprobe=after"],
                              {"out_has": ["HOOK patched", "WPHOOK patched", TELEPORT], "checks_ok": CHECKS,
                               "log_not": ["WRONGBYTES"], "wp": True}),
    # Stage 2: a city of three sections and three packs: every one filed, every pack's instances in the grid (tags
    # pack << 16 | index), the spawn's face found, and on F7 the car back, every entry out, one UnloadChunks
    "city-same": (CITY3_INI, ["go=10", "unloadkey=30"],
                  {"map": CITY3, "out_has": ["LOADCHUNKS 57216 bytes name FTOWN pristine 1 aligned 1",
                                             "tag 044C0000", "tag 044D0000", "tag 044E0003",
                                             "REMOVEDYN tag 044C0000", "REMOVEDYN tag 044E0003",
                                             "TELEPORT -11500.000 101.000 2000.000",
                                             "grid clean colliders clean car rockport", "BUFFER FREED",
                                             "LOADS 1 UNLOADS 1 LISTS 0 ELEMS 0"],
                   "out_not": ["DIRTY", "NOT FOUND", "BAD THIS"],
                   "log_has": ["map file city3.bun: 57216 bytes, 3 scenery sections (1100 1101 1102), 3 collision "
                               "packs (1100 1101 1102) with 12 instances; 2 spawns",
                               "scenery section 1100 filed: yes", "scenery section 1102 filed: yes",
                               "collision pack 1100 filed: yes", "collision pack 1102 filed: yes",
                               "height at spawn 1: face at 100.00 (spawn 1.00 above)", "UNLOADED (unload key)"],
                   "log_re": [r"grid: 12 instances in 3 packs, \d+ entries in \d+ cells \(\d+ nodes of ours for "
                              r"empty cells\), [\d.]+ ms; tags per cell: max \d+, median \d+",
                              r"LOADED city3\.bun: 57216 bytes read in [\d.]+ ms, LoadChunks [\d.]+ ms"],
                   "log_not": ["WRONGBYTES", "REFUSED", "NOT TELEPORTED"], "teleports": 2, "checks_ok": CHECKS}),
    # one of the three numbers is taken: nothing is loaded
    "city-one-taken": (CITY3_INI, ["go=10", "taken=1101"],
                       {"map": CITY3, "out_not": ["LOADCHUNKS", "ADDDYN", "TELEPORT"],
                        "log_has": ["REFUSED: scenery section 1101 is taken"]}),
    # one pack is not filed by the game: everything is unloaded, the car stays
    "city-not-filed": (CITY3_INI, ["go=10", "nofile=1102"],
                       {"map": CITY3, "out_not": ["TELEPORT", "ADDDYN"], "out_has": ["UNLOADCHUNKS 57216 bytes"],
                        "log_has": ["collision pack 1101 filed: yes", "collision pack 1102 filed: NO",
                                    "NOT TELEPORTED: the game did not file our chunks", "UNLOADED (not filed)"]}),
    # F6 (NextSpawn) while loaded: the next spawn, height-checked like the first, round to the first again; before a
    # load it does nothing
    "next-spawn": (CITY3_INI, ["go=10", "next=5,20,30"],
                   {"map": CITY3, "order": ["TELEPORT -11500.000 101.000 2000.000", "HEIGHT -11500.00 101.00 2300.00",
                                            "TELEPORT -11500.000 101.000 2300.000", "HEIGHT -11500.00 101.00 2000.00",
                                            "TELEPORT -11500.000 101.000 2000.000"],
                    "teleports": 3,
                    "log_has": ["next spawn key: nothing loaded", "height at spawn 2: face at 100.00",
                                "NEXT SPAWN 2 from physics (-11500.00, 101.00, 2000.00) to render (2300.00, 11500.00, "
                                "101.00)", "NEXT SPAWN 1 from physics"]}),
    # the next spawn has no face under it: the car stays where it is
    "next-spawn-noface": ({**CITY3_INI, ("Spawn", "Spawn2"): "3500, 11500, 101, 0"}, ["go=10", "next=20"],
                          {"map": CITY3, "teleports": 1,
                           "log_has": ["NOT MOVED: no face at spawn 2 (render 3500.00, 11500.00, 101.00)"]}),
    # a file of more than the city's size (100 MB of padding after city3): it loads; the copy and LoadChunks times
    # are logged
    "big-file": ({**CITY3_INI, ("Map", "File"): "big.bun"}, ["go=10", "unloadkey=30"],
                 {"map": BIG, "out_has": ["LOADCHUNKS 104914824 bytes name FTOWN pristine 1 aligned 1",
                                          "TELEPORT -11500.000 101.000 2000.000", "BUFFER FREED"],
                  "log_re": [r"LOADED big\.bun: 104914824 bytes read in [\d.]+ ms, LoadChunks [\d.]+ ms"],
                  "log_not": ["REFUSED", "NOT TELEPORTED"]}),
    # the real city as built (only where ftown/ftown-city.bun exists), with the shipped ini: parsed, every section and
    # pack filed, its collision instances (CITY_INSTANCES) in the grid, the car on the route start, back on F7
    "city-real": ({}, ["go=10", "unloadkey=30"],
                  {"map": CITY, "out_has": ["name FTOWN pristine 1 aligned 1", "grid clean colliders clean",
                                            "BUFFER FREED", "LOADS 1 UNLOADS 1 LISTS 0 ELEMS 0"],
                   "log_has": ["12 scenery sections (1100 1101 1102 1103 1104 1105 1106 1107 1108 1109 1400 1401)",
                               "with %d instances; 2 spawns" % CITY_INSTANCES, "scenery section 1401 filed: yes",
                               "collision pack 1401 filed: yes", "height at spawn 1: face at 100.00",
                               "UNLOADED (unload key)"],
                   "log_re": [r"grid: %d instances in 12 packs, \d+ entries in \d+ cells" % CITY_INSTANCES],
                   "log_not": ["WRONGBYTES", "REFUSED", "NOT TELEPORTED"], "teleports": 2}),
    # the evening on the real city with its own lights list (ftown/ftown-evening.bin, written by build_city.py with it):
    # every listed vertex lit in the copy LoadChunks gets; the day's load of the same file leaves all of them as built
    "city-real-evening": (EVE_KEYS, ["go=10", "unloadkey=30", "frames=40"],
                          {"map": CITY, "lights": "real", "out_re": [r"LIGHTS lit (\d+) day 0 of \1\n"],
                           "out_has": ["grid clean colliders clean"],
                           "log_has": ["EVENING ON", "EVENING OFF (unload key)"],
                           "log_re": [r"EVENING LIGHTS: \d+ vertices lit, [\d.]+ ms"],
                           "log_not": ["WRONGBYTES", "REFUSED", "NOT TELEPORTED"]}),
    "city-real-day": ({}, ["go=10", "frames=20"],
                      {"map": CITY, "lights": "real", "out_re": [r"LIGHTS lit 0 day (\d+) of \1\n"],
                       "out_has": ["name FTOWN pristine 1"], "log_not": ["EVENING"]}),
    # Task 2 (docs/ftown-race-notes.md R1): F-Town's minimap. On F8 our 64-chop pack is loaded and the current track's
    # calibration and the map header are F-Town's; the HUD finds all four chops around the car in our pack
    "minimap-ftown": ({}, ["go=10", "frames=30"],
                      {"out_has": ["MINIMAPPACK LOAD 1059584 bytes textures 64 aligned 1",
                                   MM_FTOWN + " chops 27 28 35 36 ours 4 rockport 0 missing 0"],
                       "out_not": ["OUT OF RANGE"], "order": [MM_ROCK, TELEPORT, "MINIMAPPACK LOAD", MM_FTOWN],
                       "log_has": ["minimap: F-Town's map in (track 2000: calibration was -1224.9, -1591.1, 6659.3; "
                                   "header was MINI_MAP_QR_SPRINT1)"],
                       "log_re": [r"minimap file ftown-minimap\.bun: 1059584 bytes, one texture pack"]}),
    # without F8 the minimap is Rockport's and nothing of ours is loaded
    "minimap-before": ({}, ["frames=20"],
                       {"out_has": [MM_ROCK + " chops"], "out_not": ["FTOWN_MAP", "MINIMAPPACK", "OUT OF RANGE"]}),
    # F7: the header and calibration back first (the car back in Rockport), our pack unloaded 3 frames later
    "minimap-back": ({}, ["go=10", "unloadkey=20", "frames=40"],
                     {"order": [MM_FTOWN, "UNLOADCHUNKS", MM_ROCK, "MINIMAPPACK UNLOAD same buffer 1"],
                      "out_has": [MM_ROCK + " chops 19 20 27 28 ours 0 rockport 4 missing 0"],
                      "out_not": ["OUT OF RANGE"], "count": {"MINIMAPPACK UNLOAD": 1},
                      "log_has": ["minimap: Rockport's map back (unload key)", "minimap: our pack unloaded"]}),
    # the race left (no player): back and unloaded at once
    "minimap-gone": ({}, ["go=10", "gone=20-25", "frames=35"],
                     {"order": [MM_FTOWN, "MINIMAPPACK UNLOAD same buffer 1", MM_ROCK],
                      "log_has": ["minimap: Rockport's map back (player gone)"]}),
    # review: the game itself moves the car to Rockport within a loop, after our hook and before the HUD (a reset; the
    # pause menu's Restart Race, which does not unload the track: ERestartRace 0x6307F0): F-Town's calibration is
    # still in for that HUD update and the chop numbers are 100+; the bound patched at 0x5673BD skips them
    "minimap-game-moves": ({}, ["go=10", "jump=20:1700,2400", "frames=30"],
                           {"order": [MM_FTOWN, "GAME MOVED THE CAR to render 1700.0 2400.0", MM_ROCK],
                            "out_not": ["OUT OF RANGE"],
                            "log_has": ["minimap: chop numbers bounded to 0..63 (0x5673BD",
                                        "minimap: Rockport's map back (the car left F-Town's map: render 1700, 2400)"]}),
    # the track unloaded (quitting the race, career travel) while F-Town is loaded: back and unloaded before the
    # game's unload runs; a second F8 puts F-Town's in again
    "minimap-trackunload": ({}, ["go=10,30", "trackunload=20", "frames=45"],
                        {"order": [MM_FTOWN, "MINIMAPPACK UNLOAD same buffer 1", "TRACKUNLOAD", "MINIMAPPACK LOAD",
                                   MM_FTOWN],
                         "count": {"MINIMAPPACK LOAD": 2, "MINIMAPPACK UNLOAD": 1}, "out_not": ["OUT OF RANGE"],
                         "log_has": ["minimap: Rockport's map back (track unloading)"]}),
    # the guard: near the map's bottom edge the game would read chop 64+ (no upper bound, R1): Rockport's numbers
    # back while the car is outside the safe box, F-Town's again inside
    "minimap-guard": ({}, ["go=10", "drive=20:2000,9000", "drive=30:2000,11500", "frames=40"],
                      {"order": [MM_FTOWN, "DRIVE to render 2000.0 9000.0", MM_ROCK, "DRIVE to render 2000.0 11500.0",
                                 MM_FTOWN],
                       "out_not": ["OUT OF RANGE"],
                       "log_has": ["minimap: Rockport's map back (the car left F-Town's map: render 2000, 9000)"]}),
    # [Minimap] Enabled = 0: as before Task 2
    "minimap-off": ({("Minimap", "Enabled"): "0"}, ["go=10", "frames=30"],
                    {"out_has": [TELEPORT, MM_ROCK], "out_not": ["MINIMAPPACK", "FTOWN_MAP"]}),
    # the minimap file missing: the city still loads, no minimap
    "minimap-nofile": ({("Minimap", "File"): "nothere.bun"}, ["go=10", "frames=30"],
                       {"out_has": [TELEPORT], "out_not": ["MINIMAPPACK", "FTOWN_MAP"],
                        "log_has": ["minimap file nothere.bun cannot be opened"]}),
    # Task 3: the Time Attack (TA_INI: on the slab's test ground, start (2000, 11000) north through three gates 500 m
    # apart to the finish at 13000). F5 while loaded: the car to the start (height-checked), held through 3-2-1 with
    # the velocity zeroed every frame, GO, shown with the game's HUD message (single frame, priority 3, re-asked
    # every frame)
    "ta-countdown": (TA_INI, ["go=10", "ta=20", "frames=140"],
                     {"order": [TELEPORT, TA_START, MSG + "TIME ATTACK|3\n", MSG + "2\n", MSG + "1\n", MSG + "GO!\n"],
                      "count_min": {"VELOCITY 0.0 0.0 0.0": 88},
                      "log_has": ["TIME ATTACK: the car at the start; 3-2-1"], "out_not": ["BAD THIS"]}),
    # every gate counts at 300 km/h at 30 FPS (2.78 m a frame), and with 25 m a frame (a 0.3 s hitch at that speed):
    # a crossing is the path between two frames crossing the gate line; the time is the simulation's
    "ta-gates": (TA_INI, ["go=10", "ta=20", "route=120:2.78", "unloadkey=895", "frames=900"],
                 {"order": [MSG + "CHECKPOINT 1/3|", MSG + "CHECKPOINT 2/3|", MSG + "CHECKPOINT 3/3|",
                            MSG + "FINISH "],
                  "timer_matches": True, "cost_under_us": 500,
                  "log_has": ["TIME ATTACK: GO", "TIME ATTACK: checkpoint 1/3", "TIME ATTACK: FINISH"]}),
    # Run I item 6 (docs/ftown-race-notes.md "Run I fixes", R13): the stand-in plays the game's GenericMessage (a
    # script of 45 frames, hidden when it runs out or a single-frame message is not asked again); every script start
    # is the text popping in. A whole run (title + 3, 2, 1, GO, 3 checkpoints, the finish: 8 messages) pops in at most
    # 8 times; the old per-frame running line and 3 s / 8 s banners popped in again every 45 frames
    "hud-steady": (TA_INI, ["go=10", "ta=20", "route=120:2.78", "frames=900"],
                   {"order": [MSG + "TIME ATTACK|3\n", MSG + "GO!\n", MSG + "CHECKPOINT 1/3|", MSG + "FINISH "],
                    "starts_max": 8, "out_not": ["text TIME ATTACK|0:"]}),
    # Run I item 7 (R14): the race HUD's COMPLETE % and timer from LocalPlayer::UpdateHud's two calls: 0 and 0:00 before
    # GO, the run's progress (40 % after 800 of 2,000 m) and time, 100 % and the finish time frozen after the finish
    "hud-raceinfo": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=420"],
                     {"out_re": [r"RACEINFO f=100 pct 0 time 0\.00\n", r"RACEINFO f=200 pct (39|40) time (2\.9|3\.0)\d\n",
                                 r"RACEINFO f=350 pct 100 "],
                      "raceinfo_frozen": [350, 410], "log_has": ["race HUD: its timer and COMPLETE % show the running"]}),
    # Rockport's race (F-Town never loaded): the game's values (the stand-in's carrier: 0 %, its own clock)
    "hud-rockport": (TA_INI, ["frames=60"],
                     {"out_re": [r"RACEINFO f=50 pct 0 time 1\.\d\d\n"],
                      "out_has": ["RADAR type 0 range 0.00", "HUDFEATURES raceinfo 1 leaderboard 1 wrongway 1"],
                      "out_not": ["RADAR type 2", "TRANSMISSION 1", "HUDFEATURES raceinfo 0", "HUDFEATURES BAD THIS"]}),
    # Run K item 2: Bonus Maps' Free Roam (a Sprint carrier: the HUD's racing mask) hides the race HUD's timer, COMPLETE %
    # and position (RaceInformation 0x4000000), the leaderboard (0x8) and the wrong-way arrow (0x20), as the game's own
    # free roam; the rest of the mask as the game made it
    "hud-freeroam": ({**KEYS_OFF, **EARLY}, [FE_FR, "countdown=30", "frames=200"],
                     {"out_has": ["HUDFEATURES raceinfo 0 leaderboard 0 wrongway 0 rest 0x339ED4C12"],
                      "out_not": ["HUDFEATURES raceinfo 1", "HUDFEATURES BAD THIS"],
                      "log_has": ["race HUD: Free Roam hides the race HUD's timer, COMPLETE % and position (0x58CA50)",
                                  "race HUD: Free Roam: the timer, COMPLETE %, position and leaderboard hidden"]}),
    # ... and an event keeps them (its own timer and COMPLETE %, R14)
    "hud-event-keeps": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "countdown=30", "route=160:10", "frames=300"],
                        {"out_has": ["HUDFEATURES raceinfo 1 leaderboard 1 wrongway 1"],
                         "out_not": ["HUDFEATURES raceinfo 0"],
                         "log_not": ["race HUD: Free Roam: the timer"]}),
    # Run K item 1: the safe house's icon (the game's SAFEHOUSEINDICATOR image the game left free, placed by its own
    # UpdateElementArt): at the house when in view (150 m east of the car: 150 / 5120 map units), on the rim towards it
    # when out of view (2,000 m north: clamped to 0.06), opaque (the game would fade it to nothing beyond 0.23), never
    # the GPS ring; only on F-Town's map
    "icon-near": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["go=10", "frames=40"],
                  {"order": [TELEPORT, "SAFEHOUSE 3 at 0.0293 0.0000 alpha 255 rot 0 (f="],
                   "out_not": ["GPS RING MOVED", "SAFEHOUSE 3 at 0.0293 0.0000 alpha 255 rot 0 (f=1)"],
                   "log_has": ["safe house icon: the game's safe-house icon at render (2150.0, 11430.0) on F-Town's minimap",
                               "safe house icon: SAFEHOUSEINDICATOR_3 at render (2150.0, 11430.0)"]}),
    "icon-far": ({("Minimap", "SafeHouse"): "2000, 13430"}, ["go=10", "frames=40"],
                 {"out_has": ["SAFEHOUSE 3 at 0.0000 -0.0600 alpha 255 rot 0"], "out_not": ["GPS RING MOVED"]}),
    "icon-rockport": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["frames=40"],
                      {"out_has": ["SAFEHOUSE none"], "out_not": ["SAFEHOUSE 3"],
                       "log_not": ["safe house icon: SAFEHOUSEINDICATOR"]}),
    # the game's own safe houses in every image there is (the career's Rockport ones): ours takes none of them
    "icon-slot-taken": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["go=10", "frames=40", "gameicons=4"],
                        {"out_has": ["SAFEHOUSE 0 at -0.0977 -0.3711 alpha 255 rot 0 1 at -0.0977 -0.3711 alpha 255 rot 0 2 at -0.0977 -0.3711 alpha 255 rot 0 3 at -0.0977 -0.3711"], "out_not": ["0.0293"],
                         "log_has": ["safe house icon: no free SAFEHOUSEINDICATOR image on this HUD: not shown"]}),
    # review: two of the game's own (the career's Rockport safe houses): ours is image 3, the game's 0 and 1 untouched
    "icon-two-taken": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["go=10", "frames=40", "gameicons=2"],
                       {"out_has": ["SAFEHOUSE 0 at -0.0977 -0.3711 alpha 255 rot 0 1 at -0.0977 -0.3711 alpha 255 rot 0 "
                                    "3 at 0.0293 0.0000 alpha 255 rot 0"],
                        "out_not": ["2 at", "GPS RING MOVED"],
                        "log_has": ["safe house icon: SAFEHOUSEINDICATOR_3 at render (2150.0, 11430.0)"]}),
    "icon-off": ({("Minimap", "SafeHouse"): "2150, 11430", ("Minimap", "SafeHouseIcon"): "0"}, ["go=10", "frames=40"],
                 {"out_not": ["SAFEHOUSE 3"], "log_has": ["safe house icon off ([Minimap] SafeHouseIcon = 0"]}),
    "icon-item-off": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["go=10", "frames=40", "iconitemoff"],
                      {"out_not": ["SAFEHOUSE 3"],
                       "log_has": ["safe house icon: the map's safe-house icons are off in the player's settings"]}),
    "icon-wrongbytes": ({("Minimap", "SafeHouse"): "2150, 11430"}, ["go=10", "frames=40", "iconwrong"],
                        {"out_not": ["SAFEHOUSE 3"], "log_has": ["WRONGBYTES in the safe house icon's sites"],
                         "log_count": {"WRONGBYTES": 2, "WRONGBYTES 0x0059DD17": 1}}),
    # Run K item 5: the HUD and the car's ResetCar only some frames after the race's start on F-Town (Run K's log: "the
    # HUD's generic message not found (HUD 0x00000000" and "reset cookies NOT replaced", found 0x00000000): the start's
    # title still shown (the HUD 5 s late: the title's 3 s ran out before it, with the plugin before Run K), the reset
    # spot set when ResetCar is there (before GO, the car still at the start), the checkpoints shown
    "early-late-hud": ({**KEYS_OFF, **TA_INI, **EARLY},
                       [FE_TA, "nis=5-40", "countdown=160", "route=340:10", "hudfrom=150", "resetablefrom=120",
                        "frames=600"],
                       {"order": ["RACE START", TA_START, "RESETPOS -11000.00 101.00 2000.00", "HUDMSG SHOW TIME ATTACK",
                                  "COUNTDOWN 0", MSG + "CHECKPOINT 1/3|", MSG + "FINISH "],
                        "log_has": ["reset cookies NOT replaced yet (TIME ATTACK)",
                                    "reset cookies replaced by TIME ATTACK (ResetCar::SetResetPosition; late:",
                                    "TIME ATTACK: the HUD's generic message not found yet",
                                    "TIME ATTACK: the HUD's generic message there after"],
                        "log_not": ["dropped", "given up"]}),
    "early-late-reset-freeroam": ({**KEYS_OFF, **EARLY}, [FE_FR, "nis=5-40", "countdown=90", "resetablefrom=70",
                                                          "frames=250"],
                                  {"order": ["RACE START", "RESETPOS ",
                                             "COUNTDOWN 0"],
                                   "log_has": ["reset cookies NOT replaced yet (spawn 1)",
                                               "reset cookies replaced by spawn 1 (ResetCar::SetResetPosition; late:"]}),
    # review (Important 1): Free Roam's car is not held before GO and drifts (Run K's log: 10.4 m a second after the
    # spawn); before the game's GO the spot stays pending whatever the distance
    "early-late-reset-drift": ({**KEYS_OFF, **EARLY}, [FE_FR, "nis=5-40", "countdown=90", "jump=60:2000,11440",
                                                       "resetablefrom=70", "frames=250"],
                               {"order": ["GAME MOVED THE CAR", "RESETPOS -11430.00 101.00 2000.00", "COUNTDOWN 0"],
                                "log_has": ["reset cookies replaced by spawn 1 (ResetCar::SetResetPosition; late:"],
                                "log_not": ["given up"]}),
    # review (Important 2): a pending spot goes with its run: the player gone (F-Town unloaded) drops it; nothing is
    # set on the car that comes back
    "late-reset-player-gone": (TA_INI, ["go=10", "ta=20", "resetablefrom=50", "gone=30-35",
                                        "frames=80"],
                               {"out_not": ["RESETPOS -11000.00"],
                                "log_has": ["reset cookies NOT replaced yet (TIME ATTACK)",
                                            "reset cookies for TIME ATTACK dropped (player gone)"],
                                "log_not": ["late:"]}),
    # the car driven away from the start before ResetCar is there: no late spot (the game's own trail is better then)
    "early-late-reset-driven": ({**KEYS_OFF, **TA_INI, **EARLY},
                                [FE_TA, "nis=5-40", "countdown=45", "route=170:10", "resetablefrom=300",
                                 "frames=420"],
                                {"out_not": ["RESETPOS -11000.00"],
                                 "log_has": ["reset cookies NOT replaced yet (TIME ATTACK)",
                                             "reset cookies for TIME ATTACK given up after"]}),
    # Run I item 8 (R15): the Speed Trap (F4 twice): the radar detector shows the next camera within 300 m as the game
    # shows its own (type 2, range = distance / 300, straight ahead: direction 0); nothing in the Time Attack
    "hud-radar": ({}, ["go=10", "nextev=20,30", "route=130:10", "frames=400"],
                  {"event": 2, "order": ["RADAR type 2 range 1.00 dir 0.00", "RADAR type 2 range 0.50 dir 0.00",
                                         "SPEED CAMERA 1/3", "RADAR type 2 range 1.00 dir 0.00"],
                   "log_has": ["SPEED TRAP: radar on camera 1 (", "radar: our speed cameras within 300 m"]}),
    "hud-radar-none": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=400"],
                       {"out_not": ["RADAR type 2"]}),
    # Run I item 9 (R16): the Drag (F4): the player's Transmission manual (1) from its start to its finish, then the
    # value found (automatic, 0) back; quitting mid-run (the track unloading) puts it back too; already manual: kept
    "drag-manual": ({}, ["go=10", "nextev=20", "route=120:10", "frames=250"],
                    {"event": 1, "order": ["TRANSMISSION 0", "TELEPORT -11000.000 101.000 2100.000", "TRANSMISSION 1",
                                           MSG + "FINISH ", "TRANSMISSION 0"],
                     "log_has": ["manual gears on for the Drag (Transmission was 0)",
                                 "manual gears off (the finish): Transmission 0 put back"]}),
    "drag-manual-quit": ({}, ["go=10", "nextev=20", "route=120:10", "trackunload=140", "frames=170"],
                         {"event": 1, "order": ["TRANSMISSION 1", "TRACKUNLOAD", "TRANSMISSION 0"],
                          "log_has": ["manual gears off (track unloading): Transmission 0 put back"]}),
    "drag-manual-already": ({}, ["go=10", "nextev=20", "route=120:10", "manual", "frames=250"],
                            {"event": 1, "count": {"TRANSMISSION ": 1},
                             "log_has": ["manual gears on for the Drag (Transmission was 1)"]}),
    # Run I item 13 (R18): our icon pack handed to the game when the Quick Race menu is first built (once), and the
    # F-Town, F-Town (Evening) and Free Roam options carry its textures; the bonus entry keeps Custom Race's
    "icons": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,pick:F-Town,back,back,qr", "frames=12"],
              {"icons": True, "lights": "test",
               "order": ["ICONPACK LOAD", "SCREEN qr options", "ICONS qr: E6313967 2A49B5E2 2A49B5E2",
                         "ICONS modeselect: %s %s" % (ICON_MORNING, ICON_EVENING), "ICONS modeselect: %s 1A091045"
                         % ICON_FREEROAM],
               "count": {"ICONPACK LOAD 50176 bytes textures 3": 1},
               "log_has": ["icons: ftown-icons.bun: 50176 bytes, one texture pack", "icons: our pack loaded"]}),
    # no icon file: the game's icons, the menu as before
    "icons-nofile": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,pick:F-Town", "frames=8"],
                     {"order": ["ICONS modeselect: 2521E5EB", "ICONS modeselect: E6313967 1A091045"],
                      "out_not": ["ICONPACK"], "log_has": ["icons: ftown-icons.bun cannot be opened"]}),
    # Run I item 12 (R17, [Game] StartEarly = 1, shipped): F-Town and the event's start as soon as the race runs, before
    # the game's countdown (which then counts on F-Town); the reset spot at the start; the car held; no 3-2-1 of ours:
    # the event's clock starts with the game's GO
    "early-ta": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "countdown=30", "route=160:10", "frames=400"],
                 {"order": ["RACE START", "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB,
                            "LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", TA_START, "RESETPOS -11000.00 101.00 2000.00",
                            "HUDMSG SHOW TIME ATTACK\n", "COUNTDOWN 4", "COUNTDOWN 0", MSG + "CHECKPOINT 1/3|",
                            MSG + "FINISH "],
                  "count": {TA_START: 1, "LOADCHUNKS %d bytes name FTOWN" % SLAB: 1},
                  "out_not": [MSG + "TIME ATTACK|3", MSG + "GO!", "BAD THIS"],
                  "log_has": ["game: the race is running: loading F-Town before the game's countdown",
                              "TIME ATTACK: the car at the start, held for the game's countdown",
                              "reset cookies replaced by TIME ATTACK", "TIME ATTACK: GO (the game's GO)",
                              "game: waiting for GO -> playing (the game's GO)"]}),
    # Restart Race: the car back at the start at once, while the game counts down again (F-Town and the barriers stay)
    "early-restart": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "countdown=30", "route=160:10", "restart=300",
                                                       "frames=520"],
                      {"order": [TA_START, "GAME RESTART", "COUNTDOWN 4", TA_START, "COUNTDOWN 0"],
                       "count": {TA_START: 2, "name FTOWNBAR pristine 1": 1,
                                 "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB: 1},
                       "log_has": ["game: the Time Attack begins (the race restarted)", "TIME ATTACK: stopped (the race "
                                   "restarted)"]}),
    # the game keeps putting the car back on its grid before GO: three tries, then the old way at GO (our own 3-2-1)
    "early-gridhold": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "countdown=30", "gridhold=9-40", "frames=300"],
                       {"count": {TA_START: 5},
                        "order": ["GAME HOLDS THE CAR ON ITS GRID", TA_START, "COUNTDOWN 0", TA_START,
                                  MSG + "TIME ATTACK|3"],
                        "log_has": ["game: the game keeps the car on its grid before GO: the mode starts at the game's GO"]}),
    # Free Roam: F-Town and Spawn1 before the countdown; the cars made while it counts down; at GO nothing moves
    # Run J item 7: the course line painted into our minimap's textures at the event's start (the test Time Attack:
    # 2,000 m north, 8 m wide at the test map's 5 m a pixel), erased behind the car, every block back at the finish
    "course-ta": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=400"],
                  {"course_falls": 500, "order": ["MINIMAPPACK LOAD", "COURSE f=", MSG + "FINISH "],
                   "out_has": ["COURSE ORIGINAL yes LOCKS"], "out_not": ["LOCKED AFTER UNLOAD"],
                   "log_has": ["course line: each event's course on the minimap",
                               "course line: TIME ATTACK from 0 to 2000 m", "course line: off (the finish)"]}),
    # the shipped flow (menu, the game's start on F-Town, our race): the line from the event's start
    "course-menu": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "nis=5-40", "countdown=45", "route=170:10", "frames=420"],
                    {"course_falls": 500, "out_has": ["COURSE ORIGINAL yes"]}),
    # Free Roam: never a line
    "course-freeroam": ({**KEYS_OFF, **EARLY}, [FE_FR, "countdown=30", "frames=200"],
                        {"course_max": 0, "log_not": ["course line: TIME"]}),
    # the run stopped (the car moved 300 m in a frame: a reset, the pause menu's restart): every block back
    "course-stop": (TA_INI, ["go=10", "ta=20", "route=120:10", "jump=200:1700,2400", "frames=260"],
                    {"out_has": ["COURSE ORIGINAL yes"], "log_has": ["course line: off (the car was moved"]}),
    # quitting mid-run: every block back before our pack goes, nothing locked after
    "course-unload": (TA_INI, ["go=10", "ta=20", "route=120:10", "trackunload=200", "frames=260"],
                      {"order": ["COURSE f=", "MINIMAPPACK UNLOAD same buffer 1 textures original yes", "TRACKUNLOAD"],
                       "out_not": ["LOCKED AFTER UNLOAD"], "log_has": ["course line: off (track unloading)"]}),
    # a texture that cannot be locked: logged once, no line, the run goes on
    # Run K item 3: the line over the event's band (the road the minimap draws): 40 m wide instead of 8, centred where the
    # band says, erased to nothing at the finish; a band of the wrong length is ignored (the 8 m line)
    "course-band": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=400"],
                    {"events": TEST_EVENTS_BAND, "course_falls": 2500, "out_has": ["COURSE ORIGINAL yes"],
                     "log_has": ["course line: TIME ATTACK from 50 to 2050 m:", "as wide as the road the map draws"]}),
    "course-band-bad": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=400"],
                        {"events": TEST_EVENTS_BADBAND, "course_falls": 500, "course_max": 2000,
                         "log_has": ["course line: TIME ATTACK from 50 to 2050 m:", "WidthMetres wide"]}),
    "course-nolock": (TA_INI, ["go=10", "ta=20", "nolock", "route=120:10", "frames=400"],
                      {"course_max": 0, "order": [MSG + "FINISH "], "log_count": {"cannot be locked": 1}}),
    # Run J item 4: the Drag carried by the game's own drag race ([Game] DragCarrierEvent = 11.7.1, kind 2): its HUD
    # and mechanics the game's; the AI lane steering (road network) skipped while it runs on F-Town, the game's again
    # after the race; no such event: the Sprint carrier; Rockport's own races: the game's steering
    "drag-carrier": ({**KEYS_OFF, **EARLY}, [FE_DRAG, "dragsteer", "nis=5-40", "countdown=45", "trackunload=150",
                                            "frames=200"],
                     {"event": 1,
                      "order": ["DRAGSTEER f=0 ai", "RACEFROMNAME 11.7.1", "ALLOCCUSTOMRACE DRAG", "RACE START racemode 2",
                                "LOADCHUNKS", " skipped", "TRACKUNLOAD", "DRAGSTEER f=151 ai"],
                      "out_not": ["DRAGSTEER f=0 skipped", "lane"],
                      "log_has": ["game: carrier race 11.7.1 set (a drag race: 1 lap, 0 opponents",
                                  "drag steering: the player steers our drag race on F-Town"]}),
    "drag-carrier-missing": ({**KEYS_OFF, **EARLY}, [FE_DRAG, "dragsteer", "nodragcarrier", "countdown=45",
                                                    "frames=120"],
                             {"event": 1, "out_has": ["RACE START racemode 0"], "out_not": [" skipped", "ALLOCCUSTOMRACE DRAG"],
                              "log_has": ["game: the drag carrier 11.7.1 is not in the race database: the Sprint "
                                          "carrier 15.2.1 instead",
                                          "game: carrier race 15.2.1 set (a Sprint: 1 lap, 0 opponents"]}),
    "drag-rockport": ({}, ["dragsteer", "go=10", "frames=40"],
                      {"out_has": ["DRAGSTEER f=0 ai"], "out_not": [" skipped"]}),
    # Run J item 1: the game's own race start (the intro NIS at its origin, then PrepareForRace from the grid, both on
    # the Rockport grid in the stand-in's game) moved to the mode's start: F-Town loaded in the intro's hook (before the
    # NIS places the car), the NIS animates the car there, PrepareForRace puts it on the event's start; never Rockport
    "nis-ftown": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "nis=5-40", "countdown=45", "route=170:10", "frames=420"],
                  {"order": ["RACE START", "LOADCHUNKS %d bytes name FTOWN" % SLAB, "NIS ORIGIN render 2000.0 11000.0",
                             "NIS MOVES THE CAR render 2005.0 11000.0", "PREPARE render 2000.0 11000.0 dir -1.000",
                             "COUNTDOWN 0", MSG + "FINISH "],
                   "count": {"LOADCHUNKS %d bytes name FTOWN" % SLAB: 1, "PREPARE render 2000.0 11000.0": 1},
                   "out_not": ["BAD THIS", "PREPARE render 1700.0"],
                   "log_has": ["race start: the race's intro on F-Town", "race start: F-Town loaded for the intro",
                               "F-Town already loaded (for the race's intro)", "race start: the start grid on F-Town",
                               "TIME ATTACK: GO (the game's GO)"],
                   "log_not": ["the game keeps the car on its grid", "the game put the car back on its grid"]}),
    "nis-freeroam": ({**KEYS_OFF, **EARLY}, [FE_FR, "nis=5-40", "countdown=45", "frames=250"],
                     {"order": ["NIS ORIGIN render 2000.0 11430.0", "PREPARE render 2000.0 11430.0", "COUNTDOWN 0"],
                      "out_not": ["FTOWNBAR", "PREPARE render 1700.0"],
                      "log_not": ["the game put the car back on its grid"]}),
    # Restart Race: PrepareForRace again: on F-Town again
    "nis-restart": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "nis=5-40", "countdown=45", "route=170:10", "restart=300",
                                                     "frames=560"],
                    {"order": ["PREPARE render 2000.0 11000.0", "GAME RESTART", "PREPARE render 2000.0 11000.0"],
                     "count": {"PREPARE render 2000.0 11000.0": 2}, "out_not": ["PREPARE render 1700.0"]}),
    # Rockport's own race (no bonus flow): the intro and the grid the game's
    "nis-rockport": ({}, ["nis=5-40", "frames=80"],
                     {"out_has": ["NIS ORIGIN render 1700.0 2400.0 113.0 dir 0.250", "PREPARE render 1700.0 2400.0"],
                      "log_not": ["race start: the race's intro", "race start: the start grid"],
                      "log_has": ["race start: our races' intro and start grid on F-Town"]}),
    # the world grid not readable when the intro is placed: nothing loaded then and (review) the intro stays the game's
    # (an intro on F-Town with nothing there would be a void); F-Town loads when the race runs, before PrepareForRace
    "nis-before-grid": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "nis=5-40", "nogridat=5", "countdown=45",
                                                         "frames=200"],
                        {"order": ["NIS ORIGIN render 1700.0 2400.0", "LOADCHUNKS %d bytes name FTOWN" % SLAB,
                                   "PREPARE render 2000.0 11000.0"],
                         "out_not": ["NIS ORIGIN render 2000.0"],
                         "log_has": ["race start: F-Town could not be loaded for the intro: the intro stays the "
                                     "game's"]}),
    # review: another NIS (an arrest's) during our race calls StartLocation from elsewhere: left alone
    "nis-other": ({**KEYS_OFF, **TA_INI, **EARLY}, [FE_TA, "nis=5-40", "nisdirect", "countdown=45", "frames=200"],
                  {"out_has": ["NIS ORIGIN render 1700.0 2400.0", "PREPARE render 2000.0 11000.0"],
                   "out_not": ["NIS ORIGIN render 2000.0"], "log_not": ["race start: the race's intro"]}),
    "early-freeroam": ({**KEYS_OFF, **EARLY}, [FE_FR, "countdown=30", "frames=200"],
                      {"order": ["RACE START", "LOADCHUNKS %d bytes name FTOWN" % SLAB, TELEPORT, "CREATE ",
                                 "COUNTDOWN 0"],
                       "count": {"TELEPORT ": 2}, "out_not": ["FTOWNBAR", "HUDMSG prio"],
                       "log_has": ["game: Free Roam goes on (the game's GO)", "reset cookies replaced by spawn 1"]}),
    # Run I item 14 (R19): the stand-in rolls away any car that is not braked ("creep"); held, none moves; [Traffic]
    # Hold = 0 (the old way): they roll, and the plugin's diagnostics say so; a car given gas by something else: logged
    "traffic-held": ({}, ["go=10", "creep", "frames=150"],
                     {"count": {"CREATE ": 16}, "out_not": ["PARKED CAR MOVING"] + TRAFFIC_BAD,
                      "log_has": ["traffic: standing cars held"]}),
    "traffic-unheld": ({("Traffic", "Hold"): "0"}, ["go=10", "creep", "frames=150"],
                       {"out_has": ["PARKED CAR MOVING"], "log_has": ["moved without being pushed"]}),
    "traffic-gas": ({}, ["go=10", "creep", "gasat=60", "frames=100"],
                    {"log_re": [r"traffic: car 0 \(\w+\) had gas 0\.50 \(something else drives it\)"]}),
    "ta-not-manual": (TA_INI, ["go=10", "ta=20", "route=120:10", "frames=400"],
                      {"out_not": ["TRANSMISSION 1"], "log_not": ["manual gears on"]}),
    # the game's own message at priority 5 while ours is due: ours is refused, asked again, shown once the game's is gone
    "hud-refused": (TA_INI, ["go=10", "ta=20", "route=120:2.78", "gamemsg=290", "frames=520"],
                    {"order": ["HUDMSG SHOW GAME MESSAGE", "HUDMSG REFUSED prio 3 (showing 5) text CHECKPOINT 1/3",
                               "HUDMSG SHOW CHECKPOINT 1/3"]}),
    "ta-gates-fast": (TA_INI, ["go=10", "ta=20", "route=120:23.7", "frames=250"],
                      {"order": [MSG + "CHECKPOINT 1/3|", MSG + "CHECKPOINT 2/3|", MSG + "CHECKPOINT 3/3|",
                                 MSG + "FINISH "], "timer_matches": True}),
    # around gate 2: no finish time
    "ta-missed": (TA_INI, ["go=10", "ta=20", "route=120:10", "routeskip=2", "frames=400"],
                  {"order": [MSG + "CHECKPOINT 1/3|", MSG + "MISSED CHECKPOINT 2|F5 TO RESTART"],
                   "out_not": [MSG + "FINISH", "CHECKPOINT 2/3"],
                   "log_has": ["TIME ATTACK: missed checkpoint 2; no time"]}),
    # 100 frames paused while driving: the clock (the simulation's) stops; the finish time is the stand-in's
    # simulation time from GO to the finish
    "ta-pause": (TA_INI, ["go=10", "ta=20", "route=120:10", "pause=200-300", "frames=450"],
                 {"order": [MSG + "CHECKPOINT 1/3|", MSG + "FINISH "], "timer_matches": True}),
    # the best kept: no file at first; a first run, then a faster second: both new bests, the file holds the second
    "ta-best": (TA_INI, ["go=10", "ta=20,400", "route=120:10", "route=500:20", "frames=700"],
                {"count": {"HUDMSG SHOW FINISH": 2}, "log_count": {": NEW BEST ": 2}, "times_file": "last_best", "no_tmp": True,
                 "log_has": ["TIME ATTACK: times file written (FTownTimes.txt.tmp, then renamed)"]}),
    # an earlier best that is not beaten: shown, the file unchanged
    "ta-best-slower": (TA_INI, ["go=10", "ta=20", "route=120:10", "times=1000", "frames=400"],
                       {"out_has": ["|BEST 0:01.00"], "out_not": ["NEW BEST"], "times_file": 1000,
                        "log_has": ["TIME ATTACK: best so far 0:01.00 (FTownTimes.txt)"]}),
    # a crash between writing the new file and renaming it: the previous best survives
    "ta-best-crash": (TA_INI, ["go=10", "ta=20", "route=120:10", "times=999999", "crashwrite", "frames=400"],
                      {"out_has": ["NEW BEST"], "times_file": 999999,
                       "log_has": ["TIME ATTACK: times file NOT renamed (test: a crash before the rename)"]}),
    # F5 without F-Town: nothing
    "ta-off": (TA_INI, ["ta=20", "frames=40"],
               {"out_not": ["TELEPORT", "HUDMSG prio"], "log_has": ["time attack key: F-Town is not loaded"]}),
    # F7 during the countdown: stopped, no more messages, back to Rockport as before
    "ta-unload": (TA_INI, ["go=10", "ta=20", "unloadkey=60", "frames=100"],
                  {"order": [MSG + "TIME ATTACK|3\n", "UNLOADCHUNKS"], "out_not": [MSG + "GO!"],
                   "log_has": ["TIME ATTACK: stopped (unload key)"]}),
    # no generic message on the HUD: the Time Attack runs (log) without showing
    "ta-nohud": (TA_INI, ["go=10", "ta=20", "route=120:25", "nohud", "frames=250"],
                 {"out_not": ["HUDMSG prio"], "log_has": ["TIME ATTACK: FINISH", "the HUD's generic message not found"]}),
    # the real route on the built city with the shipped ini (only where ftown/ftown-city.bun exists): the start's
    # ground found, all 7 checkpoints and the finish, F-Town's minimap all the way (no chop out of range)
    "ta-real": ({}, ["go=10", "ta=20", "route=120:20", "unloadkey=420", "frames=430"],
                {"map": CITY, "order": [MSG + "CHECKPOINT 1/7|", MSG + "CHECKPOINT 7/7|", MSG + "FINISH "],
                 "timer_matches": True, "out_not": ["OUT OF RANGE", "MISSED"], "cost_under_us": 500,
                 "log_has": ["7 checkpoints and the finish", "TIME ATTACK: the car at the start; 3-2-1"]}),
    # the real barriers on the real city with the shipped ini: their numbers free beside the city's, all their collision
    # instances in the grid, the route still driven to the finish (the stand-in does not collide; the builder's
    # test_route_never_closed checks the walls), both unloaded cleanly
    "ta-real-barriers": ({}, ["go=10", "ta=20", "route=120:20", "unloadkey=420", "frames=430"],
                         {"map": CITY, "bar": REAL_BAR,
                          "order": ["name FTOWNBAR pristine 1", MSG + "CHECKPOINT 7/7|", MSG + "FINISH ",
                                    "name FTOWNBAR same buffer 1 readable 1 grid clean colliders clean"],
                          "log_has": ["barriers: grid: %d instances in 1 packs" % BAR_INSTANCES],
                          "log_not": ["REFUSED", "NOT LOADED"]}),
    # review: the car moved by more than 50 m in a frame while running (a reset, the pause menu's restart to Rockport):
    # the run stops, no time is shown over Rockport
    "ta-moved": (TA_INI, ["go=10", "ta=20", "route=120:10", "jump=200:1700,2400", "frames=260"],
                 {"order": [MSG + "CHECKPOINT 1/3|", "GAME MOVED THE CAR"],
                  "out_not": [MSG + "FINISH", "CHECKPOINT 2/3"],
                  "log_has": ["TIME ATTACK: stopped (the car was moved"]}),
    # the game mode's Task 3 (docs/ftown-race-notes.md R7): the race barriers (bar.bun, as ftown-barriers.bun) are loaded
    # when a Time Attack begins, after F-Town and before the car is put at the start, their collision in the grid; F7
    # takes them out first (grid entries, colliders, UnloadChunks with their own buffer), then F-Town
    "ta-barriers": (TA_INI, ["go=10", "ta=20", "unloadkey=60", "frames=100"],
                    {"order": ["LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB, TELEPORT,
                               "LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", "ADDDYN cell", TA_START,
                               "SETEXCLUSIONFLAGS\n", "UNLOADCHUNKS 1280 bytes name FTOWNBAR same buffer 1 readable 1 "
                               "grid clean colliders clean", "UNLOADCHUNKS %d bytes same buffer 1 readable 1 grid clean "
                               "colliders clean" % SLAB],
                     "out_has": ["BUFFER FREED FTOWNBAR", "BARLOADS 1 BARUNLOADS 1", "LOADS 1 UNLOADS 1 LISTS 0 ELEMS 0"],
                     "log_has": ["barriers: map file ftown-barriers.bun: 1280 bytes, 1 scenery sections (1409), 1 "
                                 "collision packs (1409) with 2 instances; the parsed copy released",
                                 "barriers: scenery section 1409 filed: yes", "barriers: collision pack 1409 filed: yes",
                                 "barriers: grid: 2 instances in 1 packs", "barriers: UNLOADED ftown-barriers.bun (unload key)"],
                     "log_not": ["NOT LOADED", "REFUSED"]}),
    # [Barriers] Enabled = 0: a Time Attack without them
    "ta-barriers-off": ({**TA_INI, ("Barriers", "Enabled"): "0"}, ["go=10", "ta=20", "frames=60"],
                        {"out_has": [TA_START], "out_not": ["FTOWNBAR"], "log_has": ["barriers off ([Barriers] Enabled = 0)"]}),
    # F-Town alone (no Time Attack): no barriers
    "barriers-not-in-freeroam": ({}, ["go=10", "unloadkey=40", "frames=60"],
                                 {"out_has": ["BARLOADS 0 BARUNLOADS 0"], "out_not": ["FTOWNBAR"]}),
    # a second F5 restarts the Time Attack: the barriers stay loaded (one load, no unload in between)
    "ta-barriers-restart": (TA_INI, ["go=10", "ta=20,60", "frames=100"],
                            {"count": {"name FTOWNBAR pristine 1": 1, TA_START: 2},
                             "out_has": ["BARLOADS 1 BARUNLOADS 0"]}),
    # leaving the race with a Time Attack running: the barriers, then F-Town, before the game's TrackLoader::Unload
    "ta-barriers-trackunload": (TA_INI, ["go=10", "ta=20", "trackunload=50", "frames=80"],
                                {"order": ["UNLOADCHUNKS 1280 bytes name FTOWNBAR", "UNLOADCHUNKS %d bytes same buffer 1"
                                           % SLAB, "TRACKUNLOAD"],
                                 "out_has": ["BARLOADS 1 BARUNLOADS 1"]}),
    # the game mode's Task 4 (docs/ftown-race-notes.md R5, R6): the way in through the game's menus, keys off (the
    # shipped [Keys] Enabled = 0). The Quick Race menu gets Bonus Maps after the game's two options
    "menu-entry": (KEYS_OFF, ["fe=qr", "frames=6"],
                   {"out_has": ["SCREEN qr options: QUICK PLAY | CUSTOM RACE | Bonus Maps"],
                    "log_has": ["menu: Bonus Maps on the Quick Race menu", "keys off"],
                    "log_not": ["WRONGBYTES"], "checks_ok": CHECKS}),
    # Bonus Maps > F-Town > Time Attack > the game's car select > start: the carrier race (15.2.1, a Sprint: 1 lap, no
    # opponents, traffic or cops) as the startup race; in the race nothing loads before the game's GO; then F-Town,
    # the barriers, the Time Attack's start and its own 3-2-1
    "menu-flow-ta": ({**KEYS_OFF, **TA_INI}, [FE_TA, "countdown=30", "frames=260"],
                     {"order": ["TITLE Bonus Maps", "SCREEN modeselect options: F-Town", "SWITCH MainMenu_Sub.fng",
                                "TITLE F-Town", "SCREEN modeselect options: Free Roam | Time Attack",
                                "RACEFROMNAME 15.2.1", "ALLOCCUSTOMRACE",
                                "FILLCUSTOMRACE laps 1 dir 0 opp 0 skill 0 heat 0 traffic 0 catchup 0 cops 0",
                                "SETSTARTUPRACE ctx 0", "FREECUSTOMRACE", "SWITCH Car_Select.fng", "SCREEN carselect",
                                "RACE START racemode 0", "COUNTDOWN 4", "COUNTDOWN 1", "COUNTDOWN 0",
                                "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB, TELEPORT,
                                "LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", TA_START, MSG + "TIME ATTACK|3\n", MSG + "GO!\n"],
                      "out_not": ["BAD THIS", "BAD RACE", "FE NO OPTION", "(null)", "Track_Select"],
                      "log_has": ["game: idle -> maps (Bonus Maps chosen)", "game: maps -> modes (F-Town chosen)",
                                  "game: modes -> car select (Time Attack chosen)",
                                  "game: car select -> waiting for GO (the race is there: Time Attack)",
                                  "game: waiting for GO -> playing (the game's GO)"]}),
    # Free Roam: F-Town at the GO, the car at Spawn1, no barriers, no Time Attack
    "menu-flow-freeroam": (KEYS_OFF, [FE_FR, "countdown=30", "frames=200"],
                           {"order": ["SWITCH Car_Select.fng", "COUNTDOWN 0", "LOADCHUNKS %d bytes name FTOWN" % SLAB,
                                      TELEPORT],
                            "out_not": ["FTOWNBAR", "TIME ATTACK START", "HUDMSG prio"],
                            "log_has": ["game: modes -> car select (Free Roam chosen)",
                                        "game: Free Roam at spawn 1 (the game's GO)"]}),
    # Back at every step: the map list back to the Quick Race menu (the game's own handler: the mode select bit
    # cleared), the mode list back to the map list, the car select back to the mode list (not Track_Options.fng)
    "menu-back-maps": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,back,qr", "frames=8"],
                       {"order": ["SCREEN modeselect options: F-Town", "SWITCH MainMenu_Sub.fng",
                                  "SCREEN qr options: QUICK PLAY | CUSTOM RACE | Bonus Maps"],
                        "log_has": ["game: maps -> idle (Back from the map list)"]}),
    "menu-back-modes": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,pick:F-Town,back,back", "frames=10"],
                        {"order": ["SCREEN modeselect options: Free Roam | Time Attack", "SWITCH MainMenu_Sub.fng",
                                   "SCREEN modeselect options: F-Town", "SWITCH MainMenu_Sub.fng",
                                   "SCREEN qr options: QUICK PLAY | CUSTOM RACE | Bonus Maps"],
                         "log_has": ["game: modes -> maps (Back from the mode list)"]}),
    "menu-back-car": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,pick:F-Town,pick:Time Attack,back", "frames=10"],
                      {"order": ["SWITCH Car_Select.fng", "SCREEN carselect", "CLEARSTARTUPRACE",
                                 "SWITCH MainMenu_Sub.fng", "SCREEN modeselect options: Free Roam | Time Attack"],
                       "out_not": ["Track_Options"],
                       "log_has": ["game: car select -> modes (Back from the car select)"]}),
    # after backing out of our flow, Custom Race is Rockport's own (five kinds, its title, Track_Select.fng)
    "menu-custom-after": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,back,pick:CUSTOM RACE,pick:CIRCUIT", "frames=10"],
                          {"order": ["SCREEN modeselect options: F-Town", "SCREEN qr options",
                                     "TITLE SELECT MODE",
                                     "SCREEN modeselect options: CIRCUIT | SPRINT | DRAG | KNOCKOUT | SPEEDTRAP",
                                     "SWITCH Track_Select.fng"],
                           "out_not": ["SETSTARTUPRACE", "Car_Select"]}),
    # the Quick Race menu built again while our flow is armed (any way back to it): the flow ends there, so Custom Race
    # afterwards is Rockport's
    "menu-requeue": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,qr,pick:CUSTOM RACE,pick:SPRINT", "frames=10"],
                     {"order": ["SCREEN modeselect options: F-Town", "SCREEN qr options",
                                "SCREEN modeselect options: CIRCUIT | SPRINT | DRAG | KNOCKOUT | SPEEDTRAP"],
                      "log_has": ["game: maps -> idle (the Quick Race menu again)"]}),
    # Rockport's menus without touching ours: Custom Race and Quick Play as before
    "menu-custom-direct": (KEYS_OFF, ["fe=qr,pick:CUSTOM RACE,pick:SPRINT", "frames=8"],
                           {"order": ["TITLE SELECT MODE",
                                      "SCREEN modeselect options: CIRCUIT | SPRINT | DRAG | KNOCKOUT | SPEEDTRAP",
                                      "SWITCH Track_Select.fng"],
                            "out_not": ["SETSTARTUPRACE", "game: "]}),
    "menu-quickplay": (KEYS_OFF, ["fe=qr,pick:QUICK PLAY", "frames=6"],
                       {"out_has": ["SWITCH Quick_Race_Brief.fng"], "log_not": ["game: "]}),
    # the carrier event missing (or not a Sprint): no race set, the mode list again, nothing pending for a race
    "menu-nocarrier": ({**KEYS_OFF, ("Game", "CarrierEvent"): "99.9.9"},
                       ["fe=qr,pick:Bonus Maps,pick:F-Town,pick:Time Attack", "frames=8"],
                       {"count": {"SCREEN modeselect options: Free Roam | Time Attack": 2},
                        "out_not": ["SETSTARTUPRACE", "SWITCH Car_Select.fng"],
                        "log_has": ["game: NO RACE: the carrier event 99.9.9 is not in the race database"]}),
    "menu-carrier-kind": (KEYS_OFF, ["fe=qr,pick:Bonus Maps,pick:F-Town,pick:Free Roam", "carriertype=4", "frames=8"],
                          {"out_not": ["SETSTARTUPRACE", "SWITCH Car_Select.fng"],
                           "log_has": ["is of kind 4, not a Sprint"]}),
    # the pause menu's Restart Race: the car back on the Rockport grid, the countdown again: the Time Attack starts
    # again at the next GO (F-Town and the barriers stay loaded: one load each)
    "game-restart": ({**KEYS_OFF, **TA_INI}, [FE_TA, "countdown=30", "restart=300", "frames=520"],
                     {"order": [TA_START, "GAME RESTART", "COUNTDOWN 4", "COUNTDOWN 0", TA_START],
                      "count": {TA_START: 2, "name FTOWNBAR pristine 1": 1,
                                "LOADCHUNKS %d bytes name FTOWN pristine 1" % SLAB: 1},
                      "log_has": ["game: playing -> waiting for GO (the countdown runs again: the race restarted)",
                                  "TIME ATTACK: stopped"]}),
    # no countdown on the HUD: F-Town after [Game] NoCountdownSeconds (20 s of simulation time, 600 frames)
    "game-nocountdown": (KEYS_OFF, [FE_FR, "nocd", "frames=700"],
                         {"out_has": ["LOADCHUNKS %d bytes name FTOWN" % SLAB],
                          "log_has": ["game: waiting for GO -> playing (no countdown seen)"]}),
    # leaving the race: the barriers, then F-Town, then the game's TrackLoader::Unload; the flow ends
    "game-quit": ({**KEYS_OFF, **TA_INI}, [FE_TA, "countdown=30", "trackunload=250", "frames=270"],
                  {"order": ["UNLOADCHUNKS 1280 bytes name FTOWNBAR", "UNLOADCHUNKS %d bytes same buffer 1" % SLAB,
                             "TRACKUNLOAD"],
                   "log_has": ["game: playing -> idle (the race was left)"]}),
    # a reset to a Rockport spot during Free Roam (the game moves the car off F-Town): back to Spawn1
    "game-offftown": (KEYS_OFF, [FE_FR, "countdown=30", "jump=220:1700,2400", "frames=240"],
                      {"count": {TELEPORT: 2}, "log_has": ["game: Free Roam at spawn 1 (the car was off F-Town)"]}),
    # the shipped ini: the keys do nothing
    "keys-off": (KEYS_OFF, ["go=10", "ta=20", "frames=40"],
                 {"out_not": ["LOADCHUNKS", "TELEPORT"], "log_has": ["keys off"]}),
    # one menu site differs: the menu off, the Quick Race menu as the game's (the rest of the plugin works: menu-wrongbytes
    # logs every other check ok)
    "menu-wrongbytes": (KEYS_OFF, ["fe=qr", "menuwrong", "frames=8"],
                        {"out_has": ["SCREEN qr options: QUICK PLAY | CUSTOM RACE\n"],
                         "log_has": ["WRONGBYTES 0x007C26E8", "WRONGBYTES in the menu's sites"],
                         "out_not": ["Bonus Maps"]}),
    # review: a mismatch in the 63-byte site at 0x7AB4E0: the WRONGBYTES line carries all 63 bytes and the game goes on
    # (the line's text was 100 characters: an overflow of the plugin's stack at the game's start)
    "menu-wrongbytes-long": (KEYS_OFF, ["fe=qr", "menuwronglong", "frames=8"],
                             {"out_has": ["SCREEN qr options: QUICK PLAY | CUSTOM RACE\n"],
                              "log_re": [r"WRONGBYTES 0x007AB4E0 .*: 8B 0D 90 CF 91 00( [0-9A-F]{2}){56} 90\n"],
                              "log_has": ["WRONGBYTES in the menu's sites"]}),
    "menu-off": ({**KEYS_OFF, ("Menu", "Enabled"): "0"}, ["fe=qr", "frames=6"],
                 {"out_has": ["SCREEN qr options: QUICK PLAY | CUSTOM RACE\n"], "log_has": ["menu off ([Menu] Enabled = 0)"]}),
    # [TimeAttack] Enabled = 0: F5 does nothing
    "ta-disabled": ({**TA_INI, ("TimeAttack", "Enabled"): "0"}, ["go=10", "ta=20", "frames=40"],
                    {"out_not": ["HUDMSG prio"], "teleports": 1}),
    # ---- the traffic cars (docs/superpowers/plans/2026-11-04-ftown-traffic-cars.md Task 3; spots: TRAFFIC_SPOTS)
    # Free Roam from the menu: 16 cars made by the game's factory (driver class 4, flags 2, no cache, no customization),
    # 6 of them the add-ons, on the ground; at the quit every car killed before F-Town's chunks go and the track unloads
    "traffic-freeroam": (KEYS_OFF, [FE_FR, "countdown=30", "trackunload=400", "frames=420"],
                         {"count": {"CREATE ": 16, "driver 4 flags 2 cache 0 custom 0 match 0": 16, "KILL ": 16,
                                    "CREATE thar ": 1, "CREATE raptor ": 1, "CREATE challenger71 ": 1,
                                    "CREATE chiron ": 1, "CREATE flipcar ": 1, "CREATE longnosecab ": 1},
                          "count_min": {"-> yes": 16},
                          "order": ["KILL ", "UNLOADCHUNKS %d bytes same buffer 1" % SLAB, "TRACKUNLOAD"],
                          "out_has": ["VEHICLES made 16 alive 0 list 1 refused 0"],
                          "out_not": TRAFFIC_BAD,
                          "log_has": ["traffic: 16 cars standing (6 add-ons)", "traffic: removed 16 cars (track unloading)"],
                          "log_not": ["WRONGBYTES"], "checks_ok": CHECKS}),
    # the Time Attack: no car on a spot by the route (render x 1950 and 2050 in the test spots)
    "traffic-ta-route": ({**KEYS_OFF, **TA_INI}, [FE_TA, "countdown=30", "frames=320"],
                         {"count": {"CREATE ": 16}, "out_not": TRAFFIC_BAD + ["render 1950.0", "render 2050.0"],
                          "log_has": ["traffic: 16 cars standing"]}),
    # Free Roam by F8 (route spots used), then F5's Time Attack: the cars on route spots move off them
    "traffic-ta-after": (TA_INI, ["go=10", "ta=60", "frames=120"],
                         {"out_has": ["render 2050.0"],
                          "log_re": [r"traffic: car \d+ \(\w+\) moved to spot \d+, .*\(off the event's route\)"],
                          "out_not": TRAFFIC_BAD}),
    # the pause menu's Restart Race: the cars hidden during the countdown, placed again at GO; never made twice
    "traffic-restart": (KEYS_OFF, [FE_FR, "countdown=30", "restart=300", "frames=560"],
                        {"count": {"CREATE ": 16}, "count_min": {"DEACTIVATE ": 16, "ACTIVATE ": 16},
                         "order": ["GAME RESTART", "DEACTIVATE ", "COUNTDOWN 0", "ACTIVATE "],
                         "out_not": TRAFFIC_BAD,
                         "log_has": ["traffic: 16 cars hidden (the car is off F-Town)", "traffic: placed again"]}),
    # F7: every car killed before the unload; nothing made afterwards
    "traffic-unloadkey": ({}, ["go=10", "unloadkey=60", "frames=120"],
                          {"count": {"CREATE ": 16, "KILL ": 16}, "order": ["KILL ", "UNLOADCHUNKS"],
                           "out_not": TRAFFIC_BAD, "log_has": ["traffic: removed 16 cars (unload key)"]}),
    # the game deletes one of our cars itself: noticed before any call through it, a new one made in its place
    "traffic-evicted": ({}, ["go=10", "evict=40", "trackunload=100", "frames=110"],
                        {"count": {"CREATE ": 17, "KILL ": 16}, "out_not": TRAFFIC_BAD + ["KILL 1 "],
                         "log_re": [r"traffic: car 1 \(\w+\) is gone \(the game removed it\)"]}),
    # no room in the game's vehicle list: the refusal logged, tried again only at the next update
    "traffic-full": ({}, ["go=10", "trafficfull", "frames=70"],
                     {"count_max": {"CREATE ": 5}, "count_min": {"CREATE ": 2}, "out_not": TRAFFIC_BAD,
                      "log_has": ["NOT made (the game refused it"]}),
    # review: the game refuses one traffic model (its memory): that car takes the next model, the pool fills, the
    # refusal logged once (it was tried again every 0.5 s for good and no car after it was made)
    "traffic-refused": ({}, ["go=10", "refuse=traftaxi", "frames=150"],
                        {"out_has": ["VEHICLES made 16 "], "count": {"CREATE traftaxi ": 1}, "out_not": TRAFFIC_BAD,
                         "log_has": ["traffic: 16 cars standing"], "log_count": {"NOT made": 1}}),
    # car memory for 2 racers only: 4 add-ons refused, their places taken by traffic models
    "traffic-memory": ({}, ["go=10", "racingmem=2", "frames=120"],
                       {"out_has": ["VEHICLES made 16 "], "count": {"-> null (no room": 4},
                        "out_not": TRAFFIC_BAD, "log_has": ["traffic: 16 cars standing (2 add-ons)"]}),
    # driving 1.5 km north: the cars left behind move to spots near the car, none into view in front of it
    "traffic-move": ({}, ["go=10", "drive=80:2000,11900", "drive=110:2000,12400", "drive=140:2000,12900",
                          "frames=200"],
                     {"count": {"CREATE ": 16}, "out_not": TRAFFIC_BAD + ["-> no"],
                      "log_re": [r"traffic: car \d+ \(\w+\) moved to spot \d+"], "moved_min": 8}),
    # a spot without ground: the car killed there, the spot not used again
    "traffic-badspot": ({}, ["go=10", "nofaceat=2150", "frames=80"],
                        {"out_has": ["-> no"], "out_not": TRAFFIC_BAD,
                         "log_re": [r"traffic: car \d+ \(\w+\) has no ground at spot \d+: removed"]}),
    # [Traffic] ToggleSeconds: all hidden and shown again in turn, logged for tools/toggle-compare.py
    "traffic-toggle": ({("Traffic", "ToggleSeconds"): "1"}, ["go=10", "frames=150"],
                       {"count_min": {"DEACTIVATE ": 16}, "out_not": TRAFFIC_BAD,
                        "log_re": [r"\] toggle: traffic off", r"\] toggle: traffic on"]}),
    "traffic-off": ({("Traffic", "Enabled"): "0"}, ["go=10", "frames=40"],
                    {"out_not": ["CREATE "], "log_has": ["traffic off ([Traffic] Enabled = 0)"]}),
    "traffic-wrongbytes": ({}, ["go=10", "trafficwrong", "frames=40"],
                           {"out_not": ["CREATE "], "out_has": ["LOADCHUNKS"],
                            "log_has": ["WRONGBYTES 0x00689853", "WRONGBYTES in the traffic's sites: traffic off"]}),
    "traffic-nofile": ({("Traffic", "File"): "nosuch.json"}, ["go=10", "frames=40"],
                       {"out_not": ["CREATE "], "log_has": ["traffic: no spots (nosuch.json"]}),
    # the real city and the real spots (ftown/ftown-traffic.json) with the shipped ini: 16 cars on the ground at the
    # route start (F8: Free Roam, route spots allowed), killed at F7
    "traffic-real": ({}, ["go=10", "unloadkey=80", "frames=90"],
                     {"map": CITY, "spots": REAL_SPOTS, "count": {"CREATE ": 16, "KILL ": 16},
                      "count_min": {"-> yes": 16}, "out_not": TRAFFIC_BAD + ["-> no"],
                      "log_re": [r"traffic: \d+ spots in ftown-traffic\.json \(\d+ by the events' routes\)"]}),
    # ---- the events (docs/superpowers/plans/2026-11-04-ftown-events.md Task 4; the test events: TEST_EVENTS)
    # the Drag (F4 with the keys on: the next event, the first time the second): its start, its barriers, 3-2-1, a
    # quarter mile at 10 m a frame (300 m/s): the time, the trap speed by the game's GetSpeed (1080.0 km/h), best kept
    "ev-drag": ({}, ["go=10", "nextev=20", "route=120:10", "frames=250"],
                {"event": 1,
                 "order": ["LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", "TELEPORT -11000.000 101.000 2100.000",
                           MSG + "DRAG|3\n", MSG + "GO!\n", "GETSPEED 300.00 m/s", MSG + "FINISH 0:01.", "  TRAP " + KMH + "|NEW BEST"],
                 "timer_matches": True, "out_not": [MSG + "CHECKPOINT", "BAD THIS"],
                 "log_has": ["DRAG: GO", "trap speed 1080.0 km/h", "DRAG: NEW BEST", "barriers: LOADED ftown-barriers-drag.bun",
                             "events: 2 Drag (DND-KMP Expressway) (drag): start render (2100.00, 11000.00, 101.00) heading 90.0, "
                             "the finish; barriers ftown-barriers-drag.bun; best in [Drag]"],
                 "times_has": ["[Drag]\r\nBestMs = ", "TrapKmh = 1080.0\r\n"], "checks_ok": CHECKS}),
    # the Speed Trap (F4 twice): three cameras read the speed where the car crosses them; the score is their sum
    "ev-speedtrap": ({}, ["go=10", "nextev=20,30", "route=120:10", "frames=400"],
                     {"event": 2,
                      "order": ["TELEPORT -11000.000 101.000 2200.000", MSG + "GO!\n",
                                MSG + "SPEED CAMERA 1/3|" + KMH + "  TOTAL " + KMH,
                                MSG + "SPEED CAMERA 2/3|" + KMH + "  TOTAL 2160.0 KM/H",
                                MSG + "SPEED CAMERA 3/3|" + KMH + "  TOTAL 3240.0 KM/H", MSG + "SCORE 3240.0 KM/H|NEW BEST"],
                      "out_not": ["MISSED", "BAD THIS"],
                      "log_has": ["SPEED TRAP: camera 1/3 1080.0 km/h (total 1080.0)", "score 3240.0 km/h",
                                  "SPEED TRAP: NEW BEST score 3240.0 km/h"],
                      "times_has": ["[SpeedTrap]\r\nBestScoreKmh = 3240.0\r\n", "Camera1Kmh = 1080.0\r\n",
                                    "Camera3Kmh = 1080.0\r\n"]}),
    # the Sector Sprint (F4 three times): two checkpoints and the finish
    "ev-sprint": ({}, ["go=10", "nextev=20,30,40", "route=120:10", "frames=400"],
                  {"event": 3,
                   "order": ["TELEPORT -11000.000 101.000 1900.000", MSG + "SECTOR SPRINT|3\n", MSG + "GO!\n",
                             MSG + "CHECKPOINT 1/2|", MSG + "CHECKPOINT 2/2|", MSG + "FINISH "],
                   "timer_matches": True, "log_has": ["SECTOR SPRINT: NEW BEST"],
                   "times_has": ["[SectorSprint]\r\nBestMs = ", "Split1Ms = ", "Split2Ms = "]}),
    # review focus: another event begins while one's barriers are in (same section and pack 1409): the first set out,
    # then the next in, never refused
    "ev-switch-barriers": ({}, ["go=10", "nextev=20,60", "frames=100"],
                           {"order": ["LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", "TELEPORT -11000.000 101.000 2100.000",
                                      "UNLOADCHUNKS 1280 bytes name FTOWNBAR same buffer 1 readable 1 grid clean colliders clean",
                                      "LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1", "TELEPORT -11000.000 101.000 2200.000"],
                            "out_has": ["BARLOADS 2 BARUNLOADS 1"],
                            "log_has": ["barriers: UNLOADED ftown-barriers-drag.bun (another event)",
                                        "barriers: LOADED ftown-barriers-speedtrap.bun"],
                            "log_not": ["REFUSED", "NOT LOADED"]}),
    # review focus: a new best of one event keeps every other event's best and any section that is no event's
    "ev-best-keeps-others": ({}, ["go=10", "times=99999", "timesextra=Drag:BestMs = 88888;Old:Note = kept",
                                  "nextev=20,30", "route=120:10", "frames=400"],
                             {"event": 2, "out_has": [MSG + "SCORE 3240.0 KM/H|NEW BEST"],
                              "times_has": ["[Route1]\r\nBestMs = 99999\r\n", "[Drag]\r\nBestMs = 88888\r\n",
                                            "[SpeedTrap]\r\nBestScoreKmh = 3240.0\r\n", "[Old]\r\nNote"],
                              "log_has": ["SPEED TRAP: no best score yet"]}),
    # the speed shown in mph ([Events] SpeedUnit = mph; the file keeps km/h)
    # review fix: a Speed Trap best read back keeps its TimeMs when another event's new best rewrites the file
    "ev-best-keeps-speedtrap-time": ({}, ["go=10", "times=99999",
                                          "timesextra=SpeedTrap:BestScoreKmh = 5000.0|TimeMs = 12345|Camera1Kmh = 1250.0",
                                          "nextev=20", "route=120:10", "frames=250"],
                                     {"event": 1, "out_has": ["NEW BEST"],
                                      "times_has": ["[SpeedTrap]\r\nBestScoreKmh = 5000.0\r\nTimeMs = 12345\r\n",
                                                    "Camera1Kmh = 1250.0\r\n", "[Drag]\r\nBestMs = "]}),
    # review fix: more than the write buffer of sections that are no event's: the file is cut at the buffer, never
    # written from past it
    "ev-times-big": ({}, ["go=10", "times=99999",
                          "timesextra=" + ";".join("Old%d:Note = %s" % (k, "x" * 3500) for k in range(6)),
                          "nextev=20", "route=120:10", "frames=250"],
                     {"event": 1, "out_has": ["NEW BEST"], "times_max": 16384,
                      "times_has": ["[Route1]\r\nBestMs = 99999\r\n", "[Drag]\r\nBestMs = "]}),
    "ev-mph": ({("Events", "SpeedUnit"): "mph"}, ["go=10", "nextev=20", "route=120:10", "frames=250"],
               {"event": 1, "out_has": ["  TRAP 671.1 MPH|NEW BEST"], "times_has": ["TrapKmh = 1080.0\r\n"]}),
    # review focus: no events file: the events off, the mode list Free Roam alone, F5 nothing; the rest works
    "ev-nofile": ({**KEYS_OFF, ("Events", "File"): "nosuch.json"}, ["fe=qr,pick:Bonus Maps,pick:F-Town", "frames=8"],
                  {"out_has": ["SCREEN modeselect options: Free Roam\n"],
                   "log_has": ["events off: nosuch.json cannot be opened", "menu: Bonus Maps on the Quick Race menu (F-Town: "
                               "Free Roam); carrier race"]}),
    "ev-nofile-keys": ({("Events", "File"): "nosuch.json"}, ["go=10", "ta=20", "nextev=30", "frames=40"],
                       {"out_not": ["START", "HUDMSG prio"], "teleports": 1, "log_has": ["events off: nosuch.json"]}),
    "ev-badjson": ({**KEYS_OFF, ("Events", "File"): "bad.json"}, ["fe=qr,pick:Bonus Maps,pick:F-Town", "frames=8"],
                   {"out_has": ["SCREEN modeselect options: Free Roam\n"],
                    "log_has": ["events off: bad.json is not an events file (the file ends inside a value)"]}),
    # one bad event (an unknown kind): left out, the others offered
    "ev-badevent": ({**KEYS_OFF, ("Events", "File"): "badevent.json"}, ["fe=qr,pick:Bonus Maps,pick:F-Town", "frames=8"],
                    {"out_has": ["SCREEN modeselect options: Free Roam | Time Attack | Speed Trap (Mathura Road) | "
                                 "Sector Sprint\n"],
                     "log_has": ["events: event 2 of badevent.json left out: kind is not timeattack, sprint, drag or "
                                 "speedtrap"]}),
    # the menu: the mode list holds Free Roam and the four events; each event from it, with its own barriers
    "menu-flow-drag": (KEYS_OFF, [FE_DRAG, "countdown=30", "frames=260"],
                       {"order": [MODES, "SWITCH Car_Select.fng", "COUNTDOWN 0", "LOADCHUNKS %d bytes name FTOWN" % SLAB,
                                  TELEPORT, "LOADCHUNKS 1280 bytes name FTOWNBAR pristine 1",
                                  "TELEPORT -11000.000 101.000 2100.000", MSG + "DRAG|3\n", MSG + "GO!\n"],
                        "log_has": ["game: modes -> car select (Drag (DND-KMP Expressway) chosen)",
                                    "game: car select -> waiting for GO (the race is there: Drag (DND-KMP Expressway))",
                                    "game: the Drag (DND-KMP Expressway) begins (the game's GO)",
                                    "barriers: LOADED ftown-barriers-drag.bun",
                                    # Run J item 4: the drag carrier (was the Sprint 15.2.1)
                                    "carrier race 11.7.1 set (a drag race: 1 lap, 0 opponents, no traffic, no cops) for "
                                    "Drag",
                                    "menu: Bonus Maps on the Quick Race menu (F-Town: Free Roam, Time Attack, Drag (DND-KMP "
                                    "Expressway), Speed Trap (Mathura Road), Sector Sprint)"],
                        "out_not": ["BAD THIS", "(null)", "FE NO OPTION"]}),
    "menu-flow-speedtrap": (KEYS_OFF, [FE_TRAP, "countdown=30", "frames=260"],
                            {"order": [MODES, "SWITCH Car_Select.fng", "COUNTDOWN 0", "LOADCHUNKS 1280 bytes name FTOWNBAR",
                                       "TELEPORT -11000.000 101.000 2200.000", MSG + "GO!\n"],
                             "log_has": ["game: modes -> car select (Speed Trap (Mathura Road) chosen)",
                                         "barriers: LOADED ftown-barriers-speedtrap.bun"]}),
    "menu-flow-sprint": (KEYS_OFF, [FE_SPRINT, "countdown=30", "frames=260"],
                         {"order": [MODES, "SWITCH Car_Select.fng", "COUNTDOWN 0", "LOADCHUNKS 1280 bytes name FTOWNBAR",
                                    "TELEPORT -11000.000 101.000 1900.000", MSG + "GO!\n"],
                          "log_has": ["game: modes -> car select (Sector Sprint chosen)",
                                      "barriers: LOADED ftown-barriers-sprint.bun"]}),
    # the pause menu's restart in the Speed Trap: the same event again at the next GO, its barriers loaded once
    "menu-restart-speedtrap": (KEYS_OFF, [FE_TRAP, "countdown=30", "restart=300", "frames=520"],
                               {"count": {"TELEPORT -11000.000 101.000 2200.000": 2, "name FTOWNBAR pristine 1": 1},
                                "log_has": ["SPEED TRAP: stopped (the race restarted)"]}),
    # review focus: traffic in the Drag: no car on the Drag's route spots (x 2050 and 2150: bit 1), the Time Attack's
    # other spots (x 1950: bits 1 and 8) used
    "traffic-ev-mask": (KEYS_OFF, [FE_DRAG, "countdown=30", "frames=320"],
                        {"count": {"CREATE ": 16}, "out_not": TRAFFIC_BAD + ["render 2050.0", "render 2150.0"],
                         "count_min": {"render 1950.0": 1}, "log_has": ["traffic: 16 cars standing"]}),
    # each real event on the real city with its real barriers (only where ftown/ftown-city.bun and the barrier files
    # are built): the start's ground found, every gate and the finish, no chop out of range, the barriers in the grid
    "ev-real-drag": ({}, ["go=10", "nextev=20", "route=120:20", "unloadkey=420", "frames=430"],
                     {"map": CITY, "events": REAL_EVENTS, "event": 1, "bars": "real",
                      "order": ["name FTOWNBAR pristine 1", MSG + "FINISH "],
                      "out_not": ["OUT OF RANGE", "MISSED"],
                      "log_has": ["barriers: LOADED ftown-barriers-drag.bun", "DRAG: the car at the start; 3-2-1",
                                  "DRAG START from",
                                  "trap speed 2160.0 km/h"],
                      "log_re": [r"barriers: grid: \d+ instances in 1 packs"], "log_not": ["REFUSED", "NOT LOADED"]}),
    "ev-real-speedtrap": ({}, ["go=10", "nextev=20,30", "route=120:20", "unloadkey=420", "frames=430"],
                          {"map": CITY, "events": REAL_EVENTS, "event": 2, "bars": "real",
                           "order": [MSG + "SPEED CAMERA 1/4|", MSG + "SPEED CAMERA 4/4|",
                                     MSG + "SCORE 8640.0 KM/H|NEW BEST"],
                           "out_not": ["OUT OF RANGE", "MISSED"],
                           "log_has": ["barriers: LOADED ftown-barriers-speedtrap.bun", "SPEED TRAP START from",
                                       "barriers: UNLOADED ftown-barriers-drag.bun (another event)"],
                           "log_not": ["REFUSED", "NOT LOADED"]}),
    "ev-real-sprint": ({}, ["go=10", "nextev=20,30,40", "route=120:20", "unloadkey=420", "frames=430"],
                       {"map": CITY, "events": REAL_EVENTS, "event": 3, "bars": "real",
                        "order": [MSG + "CHECKPOINT 1/6|", MSG + "CHECKPOINT 6/6|", MSG + "FINISH "],
                        "timer_matches": True, "out_not": ["OUT OF RANGE", "MISSED"],
                        "log_has": ["barriers: LOADED ftown-barriers-sprint.bun", "SECTOR SPRINT START from"],
                        "log_not": ["REFUSED", "NOT LOADED"]}),
    # moving traffic (FTownRoadNet.h, plan 2026-11-05-ftown-moving-traffic): the test network (make_test_net.py)
    # after the stand-in's Rockport (segments 0-2; ours 3-85: 10 on the Time Attack's route, 75 on the one-way east
    # street (45 km/h), 83 the route's straight on at the junction, 84 a turn off the route (an exit)). F8 installs
    # it with the widened grid (the city's collision static in our nodes, no dynamic entries); free roam: every road
    # of ours may spawn traffic, Rockport's the game's rule; the track's unload puts all of it back first
    "net-freeroam": ({}, ["go=10", "spawncheck=20:10", "spawncheck=20:75", "spawncheck=20:84", "spawncheck=20:1",
                          "trackunload=60", "frames=70"],
                     {"net": "test", "checks_ok": CHECKS + NET_CHECKS,
                      "order": ["BMALLOC 110416 flags 0", "LOADCHUNKS", TELEPORT, "SPAWNCHECK f=20 seg 10 -> 1",
                                "SPAWNCHECK f=20 seg 75 -> 1", "SPAWNCHECK f=20 seg 84 -> 1",
                                "SPAWNCHECK f=20 seg 1 -> 0", "BFREE\n", "TRACKUNLOAD"] + NET_BACK +
                               ["BMALLOCS 1 BFREES 1"],
                      "count": {"ADDDYN cell": 0},
                      "log_has": ["moving traffic: road network ftown-roadnet.bin: 2 profiles, 83 nodes, 83 segments, "
                                  "3 roads after Rockport's 3 / 4 / 3 / 1; 38 grid cells",
                                  "moving traffic: INSTALLED", "the network 5 profiles, 87 nodes, 86 segments, 4 roads",
                                  "moving traffic: Rockport's road network back (3 segments; 0 re-marks",
                                  "moving traffic: grid narrowed back (92 columns, min x -4800.0)",
                                  "grid: the city's "],
                      "log_not": ["WRONGBYTES", "REFUSED", "NOT INSTALLED", "NOT TELEPORTED"]}),
    # an event: only its route spawns (InRace), its turn off the route not; its marks cleared when it stops; the
    # barriers' dynamic entries in our nodes freed with the grid
    "net-event": (NET_GROUND, ["go=10", "ta=20", "spawncheck=30:10", "spawncheck=30:83", "spawncheck=30:75",
                       "spawncheck=30:84", "trackunload=60", "frames=70"],
                  {"net": "test", "checks_ok": CHECKS + NET_CHECKS,
                   "out_has": ["SPAWNCHECK f=30 seg 10 -> 1", "SPAWNCHECK f=30 seg 83 -> 1", "SPAWNCHECK f=30 seg 75 -> 0",
                               "SPAWNCHECK f=30 seg 84 -> 0", "LOADCHUNKS 1280 bytes name FTOWNBAR", "LISTS 0 ELEMS 0"]
                              + NET_BACK,
                   "log_has": ["moving traffic: TIME ATTACK's route marked: 69 segments InRace, 2 exits NoTraffic",
                               "moving traffic: TIME ATTACK's route marks cleared"],
                   "log_not": ["WRONGBYTES", "REFUSED", "NOT INSTALLED"]}),
    # a restart's ResetRaceSegments clears every InRace: the route is marked again the next frame
    "net-event-remark": (NET_GROUND, ["go=10", "ta=20", "resetrace=40", "spawncheck=41:10", "trackunload=60", "frames=70"],
                         {"net": "test", "order": ["RESETRACESEGMENTS 86 segments", "SPAWNCHECK f=41 seg 10 -> 1"],
                          "out_has": NET_BACK,
                          "log_has": ["route marked again (the game cleared the race marks)", "1 re-marks"]}),
    # posted speeds: ours by road kind (35 km/h residential, 45 tertiary), Rockport's the game's rule (2 lanes: the
    # street speed 35 mph; 4 lanes: the highway speed 55 mph)
    "net-speed": ({("MovingTraffic", "SpeedSpreadPercent"): "0"},
                  ["go=10", "speedcheck=20:10", "speedcheck=20:75", "speedcheck=20:0", "speedcheck=20:2", "frames=30"],
                  {"net": "test",
                   "out_has": ["SPEEDCHECK f=20 seg 10 -> 9.72", "SPEEDCHECK f=20 seg 75 -> 12.50",
                               "SPEEDCHECK f=20 seg 0 -> 15.65", "SPEEDCHECK f=20 seg 2 -> 24.59"]}),
    "net-speed-spread": ({}, ["go=10", "speedcheck=20:10", "frames=30"],
                         {"net": "test", "log_has": ["speeds x 0.85..1.15 a car"],
                          "out_re": [r"SPEEDCHECK f=20 seg 10 -> (8\.(2[6-9]|[3-9]\d)|9\.\d\d|10\.\d\d|11\.(0\d|1[0-8]))\n"]}),
    # no F-Town in the race (a Rockport race): nothing installed, the game's own rules through our hooks
    "net-rockport": ({}, ["spawncheck=20:1", "speedcheck=20:2", "speedcheck=20:0", "trackunload=30", "frames=40"],
                     {"net": "test", "checks_ok": CHECKS + NET_CHECKS,
                      "out_has": ["SPAWNCHECK f=20 seg 1 -> 0", "SPEEDCHECK f=20 seg 2 -> 24.59",
                                  "SPEEDCHECK f=20 seg 0 -> 15.65", "BMALLOCS 0 BFREES 0"] + NET_BACK,
                      "log_not": ["INSTALLED", "WRONGBYTES"]}),
    # F7 then F8 again: the network and grid stay (installed once), the city's static entries out and in again
    "net-collision": ({}, ["go=10,40", "unloadkey=30", "trackunload=70", "frames=80"],
                      {"net": "test", "count": {"ADDDYN cell": 0, "LOADCHUNKS %d bytes name FTOWN" % SLAB: 2},
                       "log_count": {"moving traffic: INSTALLED": 1, "grid: the city's ": 2},
                       "out_has": ["LISTS 0 ELEMS 0", "BMALLOCS 1 BFREES 1"] + NET_BACK,
                       "log_not": ["REFUSED", "NOT INSTALLED"]}),
    # a file built after another Rockport: nothing installed, F-Town loads as before (dynamic entries)
    "net-mismatch": ({}, ["go=10", "trackunload=40", "frames=50"],
                     {"net": "mismatch", "out_has": [TELEPORT, "ADDDYN cell", "BMALLOCS 0 BFREES 0"] + NET_BACK,
                      "log_has": ["moving traffic: NOT INSTALLED: the game's network has 3 profiles, 4 nodes, 3 "
                                  "segments, 1 roads; the file was built after 710 / 4385 / 6538 / 1308"]}),
    # the review: a file built after another Rockport gives the carrier no traffic either (the game's own network,
    # still in place from the last track, already says it will be refused)
    "net-mismatch-carrier": (KEYS_OFF, [FE_FR, "countdown=30", "frames=200"],
                             {"net": "mismatch",
                              "out_has": ["FILLCUSTOMRACE laps 1 dir 0 opp 0 skill 0 heat 0 traffic 0 catchup 0 cops 0"],
                              "log_has": ["moving traffic: no traffic for the carrier: the game's network has 3 "
                                          "profiles, 4 nodes, 3 segments, 1 roads"]}),
    "net-nofile": ({}, ["go=10", "frames=30"],
                   {"out_has": [TELEPORT, "ADDDYN cell"], "checks_ok": CHECKS,
                    "log_has": ["moving traffic off: no road network file ftown-roadnet.bin"]}),
    "net-wrongbytes": ({}, ["go=10", "netwrong", "frames=30"],
                       {"net": "test", "out_has": [TELEPORT, "ADDDYN cell", "NET counts 3 4 3 1 pointers game"],
                        "log_has": ["WRONGBYTES in the moving traffic's sites: moving traffic off (the rest works)"]}),
    "net-right": ({}, ["go=10", "frames=30"], {"net": "test", "out_has": ["NETPROF zones 2 middle 1 offsets 1.38 1.38"]}),
    "net-left": ({("MovingTraffic", "DriveOn"): "left"}, ["go=10", "frames=30"],
                 {"net": "test", "out_has": ["NETPROF zones 2 middle 1 offsets -1.38 -1.38"],
                  "log_has": ["driving on the LEFT (experiment)"]}),
    # the carrier races: traffic level 3 (50 %) in Free Roam and events; EventTraffic = 0: none in events
    "net-carrier": (KEYS_OFF, [FE_FR, "countdown=30", "frames=200"],
                    {"net": "test",
                     "out_has": ["FILLCUSTOMRACE laps 1 dir 0 opp 0 skill 0 heat 0 traffic 3 catchup 0 cops 0"],
                     "log_has": ["(a Sprint: 1 lap, 0 opponents, traffic level 3 (50 %), no cops) for Free Roam",
                                 "moving traffic: INSTALLED"]}),
    "net-carrier-ta": ({**KEYS_OFF, **TA_INI, **NET_GROUND}, [FE_TA, "countdown=30", "frames=200"],
                       {"net": "test",
                        "out_has": ["FILLCUSTOMRACE laps 1 dir 0 opp 0 skill 0 heat 0 traffic 3 catchup 0 cops 0"],
                        "log_has": ["moving traffic: TIME ATTACK's route marked"]}),
    "net-carrier-ta-off": ({**KEYS_OFF, **TA_INI, **NET_GROUND, ("MovingTraffic", "EventTraffic"): "0"},
                           [FE_TA, "countdown=30", "frames=200"],
                           {"net": "test",
                            "out_has": ["FILLCUSTOMRACE laps 1 dir 0 opp 0 skill 0 heat 0 traffic 0 catchup 0 cops 0"],
                            "log_has": ["(EventTraffic = 0: the carrier has no traffic)"]}),
    # parked cars with moving traffic: only the parking list's spots (the test spots stand off our roads: none)
    "net-parking": (KEYS_OFF, [FE_FR, "countdown=30", "trackunload=300", "frames=320"],
                    {"net": "test", "count": {"CREATE ": 0}, "log_has": ["moving traffic: INSTALLED"]}),
    "net-parking-off": (KEYS_OFF, [FE_FR, "countdown=30", "trackunload=300", "frames=320"],
                        {"count": {"CREATE ": 16}}),
    # the real network (numbered after the stand-in's Rockport) over the real city and its Time Attack: installed, the
    # city's collision in the widened grid's real cells (static), the route driven to the finish, all of it back
    "net-real-city": ({}, ["go=10", "ta=20", "route=120:20", "spawncheck=60:7000", "trackunload=420", "frames=430"],
                      {"map": CITY, "net": "realcity",
                       "order": [MSG + "CHECKPOINT 1/7|", MSG + "CHECKPOINT 7/7|", MSG + "FINISH "],
                       "timer_matches": True, "out_not": ["OUT OF RANGE", "MISSED"] + ["tag %04X" % n for n in list(range(1100, 1110)) + [1400, 1401]], "cost_under_us": 500,
                       "out_has": NET_BACK + ["BMALLOCS 1 BFREES 1"], "out_re": [r"ADDDYN cell \d+ tag 0581"],
                       "log_re": [r"\] grid: \d+ instances in 12 packs, \d+ entries in \d+ cells \(0 nodes of ours"],
                       "log_has": ["moving traffic: INSTALLED", "moving traffic: TIME ATTACK's route marked",
                                   "moving traffic: grid narrowed back"],
                       "log_not": ["NOT INSTALLED", "REFUSED", "NOT TELEPORTED"]}),
    # the real file (tools/citymap/roadnet_build.py) passes every check of the parser (the stand-in's Rockport is not
    # the one it was built for, so it is not installed)
    "net-real": ({}, ["go=10", "frames=30"],
                 {"net": "real",
                  "log_re": [r"moving traffic: road network ftown-roadnet.bin: \d+ profiles, \d{5} nodes, \d{5} segments, "
                             r"\d+ roads after Rockport's 710 / 4385 / 6538 / 1308; \d+ grid cells"],
                  "log_has": ["moving traffic: NOT INSTALLED: the game's network has 3 profiles"]}),
    # the breakable poles (FTownSmack.h, docs/ftown-race-notes.md "Breakable poles (2026-11-05)"): city3 with three
    # poles. F8: the city filed and in the grid, then (the next frame) our override table (Rockport's 22,340 copied,
    # our 3 after them) and the spawners through the game's loader: 3 models, 3 triggers in the grid's nodes
    "smk-load": (SMK_INI, ["go=10", "frames=40"],
                 {"map": CITY3P, "smk": SMK3,
                  "order": ["LOADCHUNKS", SMK_TELEPORT, "SMK TABLE ours count 22343, Rockport's part same", SMK_LOADED],
                  "out_not": ["PAST THE TABLE", "TRIGGER LOST", "BAD THIS"],
                  "log_has": [SMK_START, "breakable poles: LOADED ftown-smackables.bun: 3 poles in 2 packs, 3 scenery "
                              "models made (live smackables 0 -> 3 of 2048); override table 22343 entries"],
                  "log_not": ["REFUSED", "WRONGBYTES"]}),
    # a car drives into a pole: its trigger (in the car's grid cell) fires, the pole flies, the instance hides
    "smk-break": (SMK_INI, ["go=10", "drive=30:2000,11480", "frames=100"],
                  {"map": CITY3P, "smk": SMK3,
                   "order": [SMK_LOADED, "DRIVE to render 2000.0 11480.0", "SMK FIRE uid 20001 at render 2000.0 11480.0: "
                             "the pole flies\n", "SMK LANDED"],
                   "count": {"SMK FIRE": 1}, "out_not": ["PAST THE TABLE"]}),
    # F7 while the pole flies: the spawners out first (the table still ours: the models' entries found), then
    # Rockport's table back, then the city; the flying pole lands afterwards; nothing reads past the table
    "smk-unload-flying": (SMK_INI, ["go=10", "drive=30:2000,11480", "unloadkey=40", "frames=120"],
                          {"map": CITY3P, "smk": SMK3,
                           "order": ["SMK FIRE", "SMKUNLOAD models 3 triggers removed 2 table ours count 22343 live 0",
                                     "SMK AT CITY UNLOAD table rockport count 22340 live 0", "UNLOADCHUNKS",
                                     "SMK LANDED", SMK_BACK],
                           "out_not": ["PAST THE TABLE"],
                           "log_has": ["breakable poles: UNLOADED (unload key)", "breakable poles: Rockport's override "
                                       "table back (22340 entries"]}),
    # the track unloads while loaded: the spawners and the table back before the city and the game's own unload
    "smk-trackunload": (SMK_INI, ["go=10", "trackunload=40", "frames=50"],
                        {"map": CITY3P, "smk": SMK3,
                         "order": [SMK_LOADED, "SMKUNLOAD models 3 triggers removed 3 table ours count 22343 live 0",
                                   "SMK AT CITY UNLOAD table rockport count 22340", "UNLOADCHUNKS", "TRACKUNLOAD",
                                   SMK_BACK],
                         "out_has": ["GRID AFTER"], "grid_same": True, "out_not": ["PAST THE TABLE"]}),
    # F-Town out and in again: a fresh table and fresh spawners each time; Rockport's entries as they were at the end
    "smk-restart": (SMK_INI, ["go=10,50", "unloadkey=30", "trackunload=80", "frames=90"],
                    {"map": CITY3P, "smk": SMK3, "count": {SMK_LOADED: 2, "SMKUNLOAD models 3 ": 2,
                                                           "SMK TABLE ours count 22343, Rockport's part same": 2},
                     "out_has": [SMK_BACK], "log_count": {"breakable poles: LOADED": 2}}),
    # the table is not Rockport's 22,340: refused (the poles stay static), F-Town itself loads
    "smk-wrongcount": (SMK_INI, ["go=10", "smkcount=22339", "trackunload=30", "frames=40"],
                       {"map": CITY3P, "smk": SMK3, "out_has": [SMK_TELEPORT],
                        "out_not": ["SMKLOAD", "SMKUNLOAD"],
                        "log_has": ["breakable poles: REFUSED: the override table has 22339 entries"]}),
    # a site's bytes differ: the poles off, the rest works
    "smk-wrongbytes": (SMK_INI, ["go=10", "smkwrong", "frames=30"],
                       {"map": CITY3P, "smk": SMK3, "out_has": [SMK_TELEPORT], "out_not": ["SMKLOAD"],
                        "log_has": ["WRONGBYTES 0x00723C90", "WRONGBYTES in the breakable poles' sites: breakable "
                                    "poles off (the rest works)"]}),
    "smk-nofile": (SMK_INI, ["go=10", "frames=30"],
                   {"map": CITY3P, "out_has": [SMK_TELEPORT], "out_not": ["SMKLOAD"],
                    "log_has": ["breakable poles off: no file ftown-smackables.bun"]}),
    # a spawner file of another city (one record 1 m off its instance): refused, the table never touched
    "smk-othercity": (SMK_INI, ["go=10", "trackunload=30", "frames=40"],
                      {"map": CITY3P, "smk": SMK3_BAD, "out_has": [SMK_TELEPORT, SMK_BACK], "out_not": ["SMKLOAD"],
                       "log_has": ["the file was built with another city; the poles stay static"]}),
    # Rockport only (no F-Town): the table never touched
    "smk-rockport": (SMK_INI, ["frames=30"],
                     {"map": CITY3P, "smk": SMK3, "out_has": [SMK_BACK], "out_not": ["SMKLOAD", "SMK TABLE ours"],
                      "log_has": [SMK_START]}),
    # no simulation yet: nothing loaded (the game's loader would make nothing); loaded once it exists (the review)
    "smk-nosim": (SMK_INI, ["go=10", "nosim", "simat=25", "trackunload=45", "frames=50"],
                  {"map": CITY3P, "smk": SMK3, "order": [SMK_TELEPORT, "SIMULATION EXISTS", SMK_LOADED, "SMKUNLOAD",
                                                         SMK_BACK],
                   "log_count": {"breakable poles: LOADED": 1}}),
    # the player gone (the race left another way): the spawners out and Rockport's table back (review)
    "smk-player-gone": (SMK_INI, ["go=10", "gone=30-35", "frames=50"],
                        {"map": CITY3P, "smk": SMK3,
                         "order": [SMK_LOADED, "SMKUNLOAD models 3 triggers removed 3 table ours count 22343 live 0",
                                   "SMK AT CITY UNLOAD table rockport count 22340", SMK_BACK],
                         "log_has": ["breakable poles: UNLOADED (player gone)", "breakable poles: buffer freed"]}),
    # Rockport's own spawners fill the game's 2,048 (2,047 live): ours wait until they are gone (the review: past the
    # cap the game hides a pole for good), then load
    "smk-cap": (SMK_INI, ["go=10", "smklive=2047", "trackunload=45", "frames=50"],
                {"map": CITY3P, "smk": SMK3,
                 "order": [SMK_TELEPORT, "ROCKPORT SPAWNERS GONE", SMK_LOADED, SMK_BACK],
                 "log_has": ["breakable poles: waiting: 2047 smackables live, no room for our 3 under the game's 2,048"],
                 "log_count": {"breakable poles: waiting": 1}}),
    # the real city and its spawner file: every pole's model made and its trigger in a node (no moving traffic: the
    # city's own nodes; with it: the widened grid's)
    "smk-real": ({}, ["go=10", "trackunload=40", "frames=50"],
                 {"map": CITY, "smk": REAL_SMK,
                  "out_re": [r"SMKLOAD packs \d+ records (\d+) models \1 triggers \1 lost 0 past 0"],
                  "out_has": [SMK_BACK], "out_not": ["PAST THE TABLE", "TRIGGER LOST"],
                  "log_not": ["REFUSED", "WRONGBYTES"]}),
    "smk-real-net": ({}, ["go=10", "trackunload=40", "frames=50"],
                     {"map": CITY, "smk": REAL_SMK, "net": "realcity",
                      "out_re": [r"SMKLOAD packs \d+ records (\d+) models \1 triggers \1 lost 0 past 0"],
                      "out_has": [SMK_BACK] + NET_BACK, "out_not": ["PAST THE TABLE", "TRIGGER LOST"],
                      "log_has": ["moving traffic: INSTALLED"], "log_not": ["REFUSED", "WRONGBYTES"]}),
    # the career's connection to Rockport (FTownConnect.h, plan 2026-11-06-ftown-rockport-connection Task 5): the
    # stand-in's zones round its junction at render (1045, 2000) (309 south of y 1900, 703, 726, 723 north to y 4000,
    # ours 226 from there to 9950, F-Town's test box from y 10000), make_test_link.py's road and data, the test network
    # with its join (make_test_net.py net-link.bin: Rockport's nodes 1 and 2 get segments 379 and 380). Free roam: on
    # 1,000 m from the junction; F-Town in once the car is in 726; the streamer keeps the junction's sections from the
    # valley and our zone; F-Town out 15 s after the car is back south; off 15 s after it is far
    "link-on": (LINK_INI, LINK_DRIVE + ["glide=800-820:1045,1000:-3000,1000", "nodecheck=150", "segcheck=150:379,380",
                                        "frames=1350"],
                {**LINK_WANT,
                 "order": ["STREAMER f=0 car (1045, 1000) zone 309", "STREAMER f=", "zone 703 list 703 743 704 744 309 726",
                           "zone 726 list " + LINK_726, "zone 723 list " + LINK_723, "zone 226 list " + LINK_OURS,
                           "NODE 1 segs 0 1 379", "NODE 2 segs 1 2 380", "zone 0", "zone 309",
                           LINK_LISTS_BACK, "WALL703 open 0 (traffic 0, cops 0)", "FACES703 flagged 0 (the road below: 0)"],
                 "out_has": ["SEG 379 flags 0x0509", "SEG 380 flags 0x0509",
                             # Run L: the stand-in's barriers collide as the game's GetBarrierList (0x7844F0) decides:
                             # open = the player's collider (mask 0, RigidBody + 0x104) no longer takes them in
                             "zone 703 list 703 743 704 744 309 726; wall 703 open 5; faces 703 flagged 4; traffic "
                             "through 5, cops through 5"],
                 "log_has": ["connection: the player's collision mask 0x00000000 (RigidBody + 0x104"],
                 "out_not": ["STREAMER NULL READ", "SETEXCLUSIONFLAGS"],
                 "log_order": ["zones in: 726 and 723 replaced (lists 11 and 12 sections",
                               "our zone 226 (4 points from 723's edge, list 12)", "road network JOINED",
                               "wall 0 OPEN (5 barriers of pack 703)",
                               "faces 0 FLAGGED (4 faces of pack 703 under the ramp)", "connection: ON",
                               "connection: F-Town IN (the car in zone 726)",
                               "wall 1 OPEN (0 barriers of the city's packs", "the car in zone 226",
                               "the car in zone 0", "the car in zone 309", "UNLOADED (connection: the car is back",
                               "wall 0 closed again (5 barriers; the car is far",
                               "faces 0 back as they were (4 faces; the car is far", "road network unjoined",
                               "zones 726 and 723 back", "our zone 226 out of the game's lists",
                               "the connector UNLOADED", "connection: OFF (the car is far from the junction)"],
                 "log_not": ["REFUSED", "WRONGBYTES", "NOT ON", "NOT OPENED", "NOT FLAGGED"]}),
    # off asked while the streamer is still in our zone (its switching held): our zone stays linked until it leaves
    "link-zone-held": (LINK_INI, LINK_DRIVE[:3] + ["glide=60-80:1045,2500:1500,6000", "racingat=100",
                                                   "glide=100-110:1500,6000:1045,1000", "zonehold=95-400",
                                                   "frames=450"],
                       {**LINK_WANT, "out_not": ["STREAMER NULL READ", "SETEXCLUSIONFLAGS"],
                        "log_order": ["connection: ON", "the car in zone 226", "OFF (not free roam (a race))"],
                        "log_has": ["our zone 226 kept: the streamer is still in it",
                                    "our zone 226 out of the game's lists (pending)"],
                        "out_has": [LINK_LISTS_BACK]}),
    # a race starting while the car is on the connection: nothing goes until the car is back in Rockport
    "link-race-while-on": (LINK_INI, LINK_DRIVE[:3] + ["glide=60-80:1045,2500:1500,6000", "racingat=100",
                                                       "glide=300-320:1500,6000:1045,1000", "frames=360"],
                           {**LINK_WANT, "out_not": ["STREAMER NULL READ"],
                            "log_order": ["connection: ON", "the car in zone 226", "the car in zone 309",
                                          "UNLOADED (not free roam (a race))", "connection: OFF (not free roam (a race))"],
                            "log_count": {"connection: OFF": 1}, "out_has": [LINK_LISTS_BACK]}),
    # the streamer drops Rockport's pack 703 and loads it again: the wall opened in the new object, the old object's
    # bytes never written after it went
    "link-wall-restream": (LINK_INI, LINK_DRIVE[:2] + ["restream703=40", "trackunload=80", "frames=90"],
                           {**LINK_WANT, "out_has": ["PACK703 restreamed (old object kept: open 5)",
                                                     "old object untouched", "WALL703 open 0 (traffic 0, cops 0)",
                                                     "FACES703 flagged 0 (the road below: 0)"],
                            "log_order": ["wall 0 OPEN (5 barriers", "faces 0 FLAGGED (4", "wall 0's pack went",
                                          "wall 0 OPEN (5 barriers", "faces 0's pack went", "faces 0 FLAGGED (4",
                                          "wall 0 closed again", "faces 0 back as they were"]}),
    # another Rockport (703's list one section longer): refused, nothing changed, tried no more
    "link-mismatch": (LINK_INI, LINK_DRIVE[:2] + ["linkbadlist", "frames=60"],
                      {**LINK_WANT, "log_has": ["connection: REFUSED: section 703's visible list is not the one",
                                                "connection: NOT ON"],
                       "log_count": {"connection: REFUSED": 1}, "log_not": ["connection: ON", "zones in"],
                       "out_not": ["SETEXCLUSIONFLAGS"],
                       "out_has": [LINK_LISTS_BACK, "WALL703 open 0 (traffic 0, cops 0)"]}),
    # the Bonus Maps (racing): the connection never turns on
    "link-bonus-untouched": (LINK_INI, LINK_DRIVE[:3] + ["racing", "frames=80"],
                             {**LINK_WANT, "log_has": ["connection: ftown-connector.bun and ftown-connect.bin"],
                              "log_not": ["connection: ON", "zones in", "OPEN"],
                              "out_has": [LINK_LISTS_BACK]}),
    # the track unloads with the car in 723: everything back before the game's unload
    "link-trackunload": (LINK_INI, LINK_DRIVE[:3] + ["glide=60-70:1045,2500:1045,3500", "trackunload=90",
                                                     "frames=100"],
                         {**LINK_WANT, "order": ["zone 723 list", "TRACKUNLOAD"] + NET_BACK + [LINK_LISTS_BACK],
                          "log_order": ["the car in zone 723", "wall 0 closed again", "road network unjoined",
                                        "zones 726 and 723 back", "our zone 226 out of the game's lists",
                                        "the connector UNLOADED", "connection: OFF (track unloading)",
                                        "Rockport's road network back"]}),
    # ... and with the car (and the streamer) in our zone: our zone left linked for the game's unloader
    "link-trackunload-ours": (LINK_INI, LINK_DRIVE[:3] + ["glide=60-80:1045,2500:1500,6000", "trackunload=100",
                                                          "frames=110"],
                              {**LINK_WANT, "out_not": ["STREAMER NULL READ"],
                               "log_has": ["our zone 226 left linked: the streamer is in it"],
                               "out_has": ["LISTS sections 226* 309 703 723 726 boundaries 226 309 703 723 726\n"]}),
    # review: a career race starting with the car at the junction, then the car into G26 (the connector: no road of
    # Rockport's there): F-Town never loads in the race; the connection goes once the car is back in Rockport
    "link-race-in-valley": (LINK_INI, LINK_DRIVE[:2] + ["glide=10-15:1045,1000:1045,2000", "racingat=20",
                                                        "glide=30-60:1045,2000:1045,2700",
                                                        "glide=70-80:1045,2700:1045,1000", "frames=120"],
                            {**LINK_WANT, "log_has": ["connection: OFF (not free roam (a race))"],
                             "log_not": ["F-Town IN", "F-Town wanted"], "out_has": [LINK_LISTS_BACK]}),
    # review: back near the junction while our zone is still linked (the streamer held in it): on again, not "taken"
    "link-reentry": (LINK_INI, LINK_DRIVE[:3] + ["glide=60-80:1045,2500:1500,6000", "racingat=100",
                                                 "glide=100-110:1500,6000:1045,1000", "zonehold=95-400",
                                                 "roamingat=150", "glide=160-170:1045,1000:1045,1500",
                                                 "frames=200"],
                     {**LINK_WANT, "log_count": {"connection: ON in": 2}, "log_not": ["is taken", "NOT ON"],
                      "out_not": ["STREAMER NULL READ"]}),
    "link-wrongbytes": (LINK_INI, LINK_DRIVE[:2] + ["linkwrong", "frames=40"],
                        {**LINK_WANT, "log_has": ["WRONGBYTES in the connection's sites: connection off"],
                         "log_not": ["connection: ON"]}),
    "link-badsize": (LINK_INI, LINK_DRIVE[:2] + ["frames=40"],
                     {**LINK_WANT, "link": "badsize", "log_has": ["connection off: ftown-connector.bun has"],
                      "log_not": ["connection: ON"]}),
    "link-badwall": (LINK_INI, LINK_DRIVE[:2] + ["frames=60"],
                     {**LINK_WANT, "link": "badwall",
                      "log_has": ["wall 0 NOT OPENED: 5 barriers on its line, the data expects 4"],
                      "out_has": ["WALL703 open 0 (traffic 0, cops 0)"]}),
    # the ramp's face region counted against another Rockport (the data expects 3 of the stand-in's 4): none flagged,
    # logged once; the wall opens as before
    "link-badfaces": (LINK_INI, LINK_DRIVE[:2] + ["frames=60"],
                      {**LINK_WANT, "link": "badfaces",
                       "log_has": ["faces 0 NOT FLAGGED: 4 faces in its region, the data expects 3",
                                   "wall 0 OPEN (5 barriers of pack 703)"],
                       "log_count": {"NOT FLAGGED": 1},
                       "out_has": ["; wall 703 open 5; faces 703 flagged 0"]}),
    # the track unloads with the connection on: the faces' flags back before the game's unload
    "link-faces-trackunload": (LINK_INI, LINK_DRIVE[:2] + ["trackunload=40", "frames=50"],
                               {**LINK_WANT, "out_has": ["FACES703 flagged 0 (the road below: 0)"],
                                "log_order": ["faces 0 FLAGGED (4 faces", "faces 0 back as they were (4 faces; track "
                                                                          "unloading"]}),
    # the network without the connection (F8 in a race: moving traffic as before): no join, the link's segments
    # NoTraffic; another Rockport's records: the join refused, the connector stays NoTraffic
    "net-join-off": ({**CITY3_INI, ("Connection", "Enabled"): "0"},
                     ["go=10", "nodecheck=30", "segcheck=30:379,380", "trackunload=40", "frames=50"],
                     {"map": CITY3, "net": "link", "out_has": ["NODE 1 segs 0 1\n", "NODE 2 segs 1 2\n",
                                                               "SEG 379 flags 0x050B", "SEG 380 flags 0x050B"] + NET_BACK,
                      "log_has": ["moving traffic: INSTALLED", "connection off ([Connection] Enabled = 0)"],
                      "log_not": ["JOINED", "WRONGBYTES"]}),
    "net-join-mismatch": (LINK_INI, LINK_DRIVE[:2] + ["nodecheck=40", "trackunload=60", "frames=70"],
                          {**LINK_WANT, "net": "linkbad", "out_has": ["NODE 1 segs 0 1\n"] + NET_BACK,
                           "log_has": ["connection: JOIN REFUSED: Rockport's node 1 has 2 segments",
                                       "NO road network join"]}),
    # the join's cell in Rockport's columns: our road tags in a copy of the cell's node while installed; Rockport's
    # node (and its dynamic list) back after
    "net-rockcells": (LINK_INI, LINK_DRIVE[:2] + ["cellcheck=40:1045,2010", "trackunload=60", "cellcheck=65:1045,2010",
                                                  "frames=70"],
                      {**LINK_WANT, "out_re": [r"CELL \d+,\d+ node other roads [\d ]*\b379\b"],
                       "out_has": NET_BACK + ["no node\n"], "out_not": ["DUPLICATE NODE"],
                       "log_has": ["moving traffic: the connection's", "cells in Rockport's columns back"]}),
}

# the stage 1 variants: the slab's file and spawn under their own changes
for _name, (_changes, _args, _want) in list(VARIANTS.items()):
    if "map" not in _want or _want["map"] == RELOC:
        VARIANTS[_name] = ({**SLAB_INI, **_changes}, _args, _want)


def write_test_lights():
    """LIGHTS and LIGHTS_STALE for the slab (tools/citymap/evening.py's file format)."""
    import struct
    sys.path.insert(0, ROOT)
    from tools.citymap import evening
    with open(MAP, "rb") as f:
        data = f.read()
    first, n = evening._vertex_buffers(data)[0]
    with open(LIGHTS_WRAP, "wb") as f:
        f.write(evening.HEADER.pack(b"FTEV", 1, len(data), 1, 0))
        f.write(evening.ENTRY.pack(0xFFFFFFE0, 0.0, 0.0, 0.0, 0, 0))
    for path, off_by in ((LIGHTS, 0), (LIGHTS_STALE, 1)):
        with open(path, "wb") as f:
            f.write(evening.HEADER.pack(b"FTEV", 1, len(data), 6, 0))
            for k in range(6):
                o = first + k * evening.VERTEX
                day = struct.unpack_from("<I", data, o + 24)[0]
                f.write(evening.ENTRY.pack(o, 0.1, 0.0, 0.0, day ^ off_by, 0xFF112233))


def write_test_events():
    """TEST_EVENTS as an events file (the format of tools/citymap/events.write), a broken one and one with a bad event."""
    os.makedirs(MAPS, exist_ok=True)
    evs = []
    for eid, nm, title, kind, best, bars, icon, x, gates in TEST_EVENTS:
        evs.append({"id": eid, "name": nm, "title": title, "kind": kind, "icon": icon, "best": best, "barriers": bars,
                    "start": [x, 11000.0, 101.0, 90.0], "start_s": 0.0, "length_m": 2000.0,
                    "gates": [{"type": t, "s": y - 11000.0, "x": x, "y": y, "heading": 90.0} for t, y in gates],
                    "route": [[x, 10950.0], [x, 13050.0]], "keys": ["a", "b"]})
    with open(TEST_EVENTS_FILE, "w", newline="\n") as f:
        json.dump({"note": "stand-in test events", "events": evs}, f, indent=1)
    # Run K item 3: the same events, the first with a band (the road the minimap draws: 40 m wide, its centre 10 m east of
    # the course), and one whose band has the wrong length (ignored: the line WidthMetres wide)
    band = json.loads(json.dumps(evs))
    band[0]["band"] = [[p[0] + 10.0, p[1], 20.0] for p in band[0]["route"]]
    # (a route is used with its start_s and finish_s, as events.py writes them: the test events have none, so their line
    # follows the start and the gates; the route from 10,950 starts 50 m before the start)
    band[0]["start_s"], band[0]["finish_s"] = 50.0, band[0]["gates"][-1]["s"] + 50.0
    with open(TEST_EVENTS_BAND, "w", newline="\n") as f:
        json.dump({"note": "stand-in test events with a band", "events": band}, f, indent=1)
    band[0]["band"] = band[0]["band"][:1]
    with open(TEST_EVENTS_BADBAND, "w", newline="\n") as f:
        json.dump({"note": "stand-in test events with a band of the wrong length", "events": band}, f, indent=1)
    with open(os.path.join(MAPS, "bad.json"), "w", newline="\n") as f:
        f.write('{"events": [ {"id": "x", ')
    bad = json.loads(json.dumps(evs))
    bad[1]["kind"] = "rally"
    with open(os.path.join(MAPS, "badevent.json"), "w", newline="\n") as f:
        json.dump({"events": bad}, f)


def make_ini(path, changes, out_path):
    with open(path, "rb") as f:
        data = f.read().decode("ascii")
    section = None
    lines, applied = [], set()
    for line in data.split("\r\n"):
        m = re.match(r"\[(\w+)\]", line)
        if m:
            section = m.group(1)
        k = re.match(r"(\w+)\s*=", line)
        if k and (section, k.group(1)) in changes:
            line = "%s = %s" % (k.group(1), changes[(section, k.group(1))])
            applied.add((section, k.group(1)))
        lines.append(line)
    missing = set(changes) - applied
    if missing:
        raise SystemExit("%s has no key %s: document it there first" % (path, sorted(missing)))
    with open(out_path, "wb") as f:
        f.write("\r\n".join(lines).encode("ascii"))


def check(name, want, result, log, wplog):
    out = result.stdout
    fails = []
    if result.returncode != 0:
        fails.append("stand-in exit %d: %s" % (result.returncode, out[-300:]))
    for t in want.get("out_has", []):
        if t not in out:
            fails.append("output lacks %r" % t)
    for t in want.get("out_not", []):
        if t in out:
            fails.append("output has %r" % t)
    for t in want.get("log_has", []):
        if t not in log:
            fails.append("log lacks %r" % t)
    for t in want.get("log_not", []):
        if t in log:
            fails.append("log has %r" % t)
    for r in want.get("out_re", []):
        if not re.search(r, out):
            fails.append("output lacks /%s/" % r)
    for r in want.get("log_re", []):
        if not re.search(r, log):
            fails.append("log lacks /%s/" % r)
    pos = 0
    for t in want.get("log_order", []):
        k = log.find(t, pos)
        if k < 0:
            fails.append("log lacks %r after position %d (log_order)" % (t, pos))
            break
        pos = k + len(t)
    pos = 0
    for t in want.get("order", []):
        k = out.find(t, pos)
        if k < 0:
            fails.append("output lacks %r after position %d (order)" % (t, pos))
            break
        pos = k + len(t)
    for t, n in want.get("count", {}).items():
        if out.count(t) != n:
            fails.append("%r %d times, want %d" % (t, out.count(t), n))
    if "teleports" in want and out.count("TELEPORT ") != want["teleports"]:
        fails.append("%d teleports, want %d" % (out.count("TELEPORT "), want["teleports"]))
    if "checks_ok" in want and log.count("check ok ") != want["checks_ok"]:
        fails.append("%d check ok lines, want %d" % (log.count("check ok "), want["checks_ok"]))
    if want.get("grid_same"):
        before = re.search(r"GRID BEFORE(.*)", out)
        after = re.search(r"GRID AFTER(.*)", out)
        if not before or not after or before.group(1) != after.group(1):
            fails.append("grid differs: before %r after %r" % (before and before.group(1), after and after.group(1)))
    if want.get("wp"):
        for t in ["WorldProbe 2 loaded", "hooked 0x00663D35", "player found", "WATCH RigidBody::SetPosition (player)"]:
            if t not in wplog:
                fails.append("WorldProbe log lacks %r" % t)
        if "WRONGBYTES" in wplog:
            fails.append("WorldProbe log has WRONGBYTES")
        if wplog.count("check ok ") < 37:
            fails.append("WorldProbe: %d check ok lines, want 37" % wplog.count("check ok "))
        if wplog.count("] POS ") < 3:
            fails.append("WorldProbe: %d POS lines (it did not run every frame)" % wplog.count("] POS "))
    for t, n in want.get("log_count", {}).items():
        if log.count(t) != n:
            fails.append("log has %r %d times, want %d" % (t, log.count(t), n))
    for t, n in want.get("count_max", {}).items():
        if out.count(t) > n:
            fails.append("%r %d times, want at most %d" % (t, out.count(t), n))
    if "moved_min" in want and log.count(" moved to spot ") < want["moved_min"]:
        fails.append("%d cars moved, want at least %d" % (log.count(" moved to spot "), want["moved_min"]))
    for t, n in want.get("count_min", {}).items():
        if out.count(t) < n:
            fails.append("%r %d times, want at least %d" % (t, out.count(t), n))
    if want.get("timer_matches"):
        # the plugin's finish time against the stand-in's simulation time from GO to the finish message
        st = re.search(r"STANDIN TIMER ([\d.]+)", out)
        fin = re.search(r"text FINISH (\d+):(\d+\.\d+)", out)
        if not st or not fin:
            fails.append("no finish (STANDIN TIMER %r, FINISH %r)" % (bool(st), bool(fin)))
        else:
            shown = int(fin.group(1)) * 60 + float(fin.group(2))
            if abs(shown - float(st.group(1))) > 0.05:
                fails.append("finish shows %.2f s, the simulation ran %s s from GO" % (shown, st.group(1)))
    if "cost_under_us" in want:
        m = re.search(r"cost per frame while F-Town was loaded: (\d+) frames, mean ([\d.]+) us, max ([\d.]+) us", log)
        if not m:
            fails.append("log has no cost line")
        elif float(m.group(2)) >= want["cost_under_us"]:
            fails.append("mean cost %s us, want under %d" % (m.group(2), want["cost_under_us"]))
    if "raceinfo_frozen" in want:
        a, b = want["raceinfo_frozen"]
        ma = re.search(r"RACEINFO f=%d pct (\d+) time ([\d.]+)" % a, out)
        mb = re.search(r"RACEINFO f=%d pct (\d+) time ([\d.]+)" % b, out)
        fin = re.search(r"text FINISH (\d+):(\d+\.\d+)", out)
        if not ma or not mb or ma.groups() != mb.groups() or not fin or \
                abs(float(ma.group(2)) - (int(fin.group(1)) * 60 + float(fin.group(2)))) > 0.011:
            fails.append("the HUD's time after the finish: %r / %r, finish %r" % (ma and ma.groups(), mb and mb.groups(),
                                                                                  fin and fin.groups()))
    # Run J item 7: the course line's pixels in our minimap's textures (the stand-in's COURSE lines): drawn (more than
    # course_falls pixels), then only fewer as the car drives, none at the end
    ys = [int(v) for v in re.findall(r"COURSE f=\d+ yellow (\d+)", out)]
    if "course_falls" in want:
        top = ys.index(max(ys)) if ys else 0
        if not ys or max(ys) <= want["course_falls"] or ys[-1] != 0 or \
                any(b > a for a, b in zip(ys[top:], ys[top + 1:])):
            fails.append("the course line's pixels: %r" % ys)
    if "course_max" in want and ys and max(ys) > want["course_max"]:
        fails.append("the course line's pixels: %r, want at most %d" % (ys, want["course_max"]))
    if "starts_max" in want:
        m = re.search(r"HUDMSG POPS (\d+)", out)
        if not m or int(m.group(1)) > want["starts_max"]:
            fails.append("the HUD message popped in %s times, want at most %d" % (m and m.group(1),
                                                                                  want["starts_max"]))
    if want.get("msg_every_frame"):
        # from GO to the end of the run every frame asks for the message (single frame: it would vanish otherwise)
        m = re.search(r"HUDMSG FRAMES (\d+)", out)
        if not m or int(m.group(1)) < 700:
            fails.append("the HUD message was asked for on %s frames" % (m and m.group(1)))
    return fails


def check_files(want, out):
    fails = []
    path = os.path.join(out, "FTownTimes.txt")
    if "times_file" in want:
        text = open(path, encoding="latin-1").read() if os.path.exists(path) else ""
        m = re.search(r"BestMs = (\d+)", text)
        if want["times_file"] == "last_best":
            log = open(os.path.join(out, "FTownLoader.log"), encoding="latin-1").read()
            bests = re.findall(r"NEW BEST (\d+) ms", log)
            if not bests or not m or int(m.group(1)) != int(bests[-1]):
                fails.append("times file %r, the log's last new best %r" % (text, bests[-1:] or None))
        elif not m or int(m.group(1)) != want["times_file"]:
            fails.append("times file %r, want BestMs = %d" % (text, want["times_file"]))
    if want.get("times_has"):
        text = open(path, "rb").read().decode("latin-1") if os.path.exists(path) else ""
        for t in want["times_has"]:
            if t not in text:
                fails.append("times file lacks %r: %r" % (t, text))
    if "times_max" in want and os.path.exists(path) and os.path.getsize(path) > want["times_max"]:
        fails.append("times file %d bytes, more than the write buffer %d" % (os.path.getsize(path), want["times_max"]))
    if want.get("no_tmp") and os.path.exists(path + ".tmp"):
        fails.append("FTownTimes.txt.tmp left behind")
    return fails


def main():
    names = sys.argv[1:] or list(VARIANTS)
    with open(INI, "rb") as f:
        raw = f.read()
    if raw.count(b"\r\n") != raw.count(b"\n"):
        print("ftown/FTownLoader.ini is not CRLF throughout")
        return 1
    subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "ftown", "src", "build.bat"), ZIG])
    if not os.path.exists(BIG) or not os.path.exists(BAR) or not os.path.exists(CITY3P):
        subprocess.check_call([sys.executable, os.path.join(HERE, "make_test_maps.py"), MAPS])
    if not os.path.exists(MINIMAP):
        sys.path.insert(0, ROOT)
        import numpy as np
        from tools.citymap import minimap
        img = np.zeros((1024, 1024, 3), np.uint8)
        img[:, :, 1] = np.arange(1024, dtype=np.uint32)[None, :] // 4
        with open(MINIMAP, "wb") as f:
            f.write(minimap.pack_bytes(img))
    os.makedirs(MAPS, exist_ok=True)
    write_test_events()
    write_test_lights()
    with open(TRAFFIC_SPOTS, "w", newline="\n") as f:
        # bit k: within 50 m of test event k's course (x 2000, 2100, 2200, 1900)
        bits = {1850.0: 8, 1950.0: 1 | 8, 2050.0: 1 | 2, 2150.0: 2 | 4, 2250.0: 4}
        rows = ["  [%.2f, %.2f, 100.00, %.1f, %d, 0]" % (x, y, 90.0, bits[x])
                for y in range(10900, 13101, 40) for x in (1850.0, 1950.0, 2050.0, 2150.0, 2250.0)]
        f.write('{\n "note": "stand-in test spots",\n "spots": [\n' + ",\n".join(rows) + "\n ]\n}\n")
    if any(VARIANTS[n][2].get("net") in ("test", "mismatch") for n in names) and \
            (not os.path.exists(NET_TEST) or os.path.getmtime(NET_TEST) < os.path.getmtime(TRAFFIC_SPOTS)):
        subprocess.check_call([CITYENV, os.path.join(HERE, "make_test_net.py"), MAPS, TRAFFIC_SPOTS])
    if any(VARIANTS[n][2].get("link") for n in names) and (
            not os.path.exists(LINK_BUN) or
            os.path.getmtime(LINK_BUN) < os.path.getmtime(os.path.join(ROOT, "tools", "citymap", "connector.py"))):
        subprocess.check_call([CITYENV, os.path.join(HERE, "make_test_link.py"), MAPS])
    if any(VARIANTS[n][2].get("net") in ("link", "linkbad") for n in names) and not os.path.exists(NET_LINK):
        subprocess.check_call([CITYENV, os.path.join(HERE, "make_test_net.py"), MAPS, TRAFFIC_SPOTS])
    if any(VARIANTS[n][2].get("wp") for n in names):
        subprocess.check_call(["cmd", "/c", os.path.join(ROOT, "world", "src", "build.bat"), ZIG])
    exe = os.path.join(HERE, "standin.exe")
    subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O1", "standin.cpp", "-o", exe, "-w",
                           "-Wl,--image-base=0x300000", "-Wl,--no-dynamicbase"], cwd=HERE)
    failed = 0
    for name in names:
        changes, args, want = VARIANTS[name]
        out = os.path.join(HERE, "out", name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        shutil.copy(exe, out)
        shutil.copy(os.path.join(ROOT, "ftown", "src", "FTownLoader.asi"), out)
        shutil.copy(MAP, out)
        shutil.copy(MINIMAP, os.path.join(out, "ftown-minimap.bun"))
        # the real city's variants run the real events; the others the test events on the slab's ground
        events_file = want.get("events", REAL_EVENTS if want.get("map") == CITY else TEST_EVENTS_FILE)
        if not os.path.exists(events_file):
            print("%-24s SKIP (no %s: tools/citymap/events.py)" % (name, events_file))
            continue
        shutil.copy(events_file, os.path.join(out, "ftown-events.json"))
        shutil.copy(os.path.join(MAPS, "bad.json"), out)
        shutil.copy(os.path.join(MAPS, "badevent.json"), out)
        with open(events_file) as f:
            evs = json.load(f)["events"]
        bar_missing = None
        for ev in evs:
            src = BAR if want.get("bars") != "real" else os.path.join(ROOT, "ftown", ev["barriers"])
            if not os.path.exists(src):
                bar_missing = src
            else:
                shutil.copy(src, os.path.join(out, ev["barriers"]))
        if bar_missing:
            print("%-24s SKIP (no %s: tools/citymap/race_barriers.py)" % (name, bar_missing))
            continue
        # the stand-in drives route.txt: the event's start, then its gates (the test events' straight courses) or, on
        # the real city, the route's own points from the start on (a real route turns between its gates)
        ev = evs[want.get("event", 0)]
        with open(os.path.join(out, "route.txt"), "w") as f:
            f.write("%.2f %.2f %.1f\n" % (ev["start"][0], ev["start"][1], ev["start"][3]))
            if want.get("map") == CITY:
                pts, acc = ev["route"], 0.0
                for a, b in zip(pts, pts[1:]):
                    acc += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                    if acc > ev["start_s"] + 1.0:
                        f.write("%.2f %.2f 0\n" % (b[0], b[1]))
            else:
                for g in ev["gates"]:
                    f.write("%.2f %.2f %.1f\n" % (g["x"], g["y"], g["heading"]))
        spots = want.get("spots", TRAFFIC_SPOTS)
        if not os.path.exists(spots):
            print("%-24s SKIP (no %s: tools/citymap/traffic_spots.py)" % (name, spots))
            continue
        shutil.copy(spots, os.path.join(out, "ftown-traffic.json"))
        if want.get("icons"):
            if not os.path.exists(ICONS_BUN):
                print("%-24s SKIP (no %s: tools/ftownicons/make_icons.py)" % (name, ICONS_BUN))
                continue
            shutil.copy(ICONS_BUN, os.path.join(out, "ftown-icons.bun"))
        if want.get("lights"):
            src = {"stale": LIGHTS_STALE, "real": REAL_LIGHTS, "wrap": LIGHTS_WRAP}.get(want["lights"], LIGHTS)
            if not os.path.exists(src):
                print("%-24s SKIP (no %s: tools/citymap/build_city.py)" % (name, src))
                continue
            shutil.copy(src, os.path.join(out, "ftown-evening.bin"))
        if want.get("net"):
            if want["net"] == "realcity" and os.path.exists(REAL_NET) and os.path.exists(CITY) and                     (not os.path.exists(NET_REALCITY) or os.path.getmtime(NET_REALCITY) < os.path.getmtime(REAL_NET)):
                subprocess.check_call([CITYENV, os.path.join(HERE, "make_test_net.py"), MAPS, "--real"])
            src = {"test": NET_TEST, "mismatch": NET_MISMATCH, "real": REAL_NET, "realcity": NET_REALCITY,
                   "link": NET_LINK, "linkbad": NET_LINK_BAD}[want["net"]]
            if not os.path.exists(src):
                print("%-24s SKIP (no %s: tools/citymap/roadnet_build.py)" % (name, src))
                continue
            shutil.copy(src, os.path.join(out, "ftown-roadnet.bin"))
        if want.get("link"):
            shutil.copy(LINK_BUN, os.path.join(out, "ftown-connector.bun"))
            shutil.copy(LINK_BINS[want["link"]], os.path.join(out, "ftown-connect.bin"))
        if want.get("map"):
            if not os.path.exists(want["map"]):
                print("%-24s SKIP (no %s: build it with tools/world/relocate.py or tools/citymap/build_city.py)"
                      % (name, want["map"]))
                continue
            shutil.copy(want["map"], out)
            shutil.copy(want["map"], os.path.join(out, "map.bun"))
        if want.get("smk"):
            if not os.path.exists(want["smk"]):
                print("%-24s SKIP (no %s: tools/citymap/build_city.py)" % (name, want["smk"]))
                continue
            shutil.copy(want["smk"], os.path.join(out, "ftown-smackables.bun"))
        if want.get("bar"):
            if not os.path.exists(want["bar"]):
                print("%-24s SKIP (no %s: build it with tools/citymap/race_barriers.py)" % (name, want["bar"]))
                continue
            shutil.copy(want["bar"], os.path.join(out, "ftown-barriers.bun"))
        # every older variant runs the game mode as it was before the Run I fixes (F-Town at the game's GO); the early
        # variants (Run I item 12) set StartEarly = 1, the shipped value
        # the older variants run with the 16 parked cars they were written for (the shipped 6 since the moving traffic)
        # the test ground is where F-Town was before the connection's move (render (2000, 11500)): its variants keep the
        # minimap's calibration and the closed box of that place; the real city's variants run the shipped values
        ground = {} if want.get("map") == CITY else {("Minimap", "UpperLeftY"): "8940",
                                                    ("Game", "Box"): "629.6, 9504.1, 3370.4, 13495.9"}
        make_ini(INI, {("Keys", "Enabled"): "1", ("Game", "StartEarly"): "0", ("Traffic", "Count"): "16", **ground,
                       **changes}, os.path.join(out, "FTownLoader.ini"))
        if want.get("wp"):
            shutil.copy(os.path.join(ROOT, "world", "src", "WorldProbe.asi"), out)
            make_ini(WP_INI, {("Log", "IntervalMs"): "20"}, os.path.join(out, "WorldProbe.ini"))
        result = subprocess.run([os.path.join(out, "standin.exe")] + args, cwd=out, capture_output=True, text=True,
                                timeout=60)
        with open(os.path.join(out, "stdout.txt"), "w") as f:
            f.write(result.stdout)
        logp = os.path.join(out, "FTownLoader.log")
        log = open(logp, encoding="latin-1").read() if os.path.exists(logp) else ""
        wpp = os.path.join(out, "WorldProbe.log")
        wplog = open(wpp, encoding="latin-1").read() if os.path.exists(wpp) else ""
        fails = check(name, want, result, log, wplog) + check_files(want, out)
        print("%-24s %s" % (name, "PASS" if not fails else "FAIL"))
        for f in fails:
            print("    " + f)
        failed += bool(fails)
    print("%d/%d variants pass" % (len(names) - failed, len(names)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
