"""Test map files for FTownLoader's stand-in variants (ftown/tests/run.py), written with tools/world's writers.

    python ftown/tests/make_test_maps.py <out dir>

city3.bun: a city-shaped file with three scenery sections and three collision packs (numbers 1100, 1101, 1102, as
tools/citymap/build_city.py numbers its districts), each a 64 m square of flat ground at z 100 centred on render
(1700, 11500), (2000, 11500) and (2300, 11500); in the order build_city writes: the texture pack, the solid lists, the
sceneries (16-aligned), the packs. big.bun: city3.bun followed by a 100 MB padding chunk (id 0, which LoadChunks
skips): the load time of a file of more than the city's size. bar.bun: the race barriers' shape
(tools/citymap/race_barriers.py): one scenery section and one collision pack numbered 1409, two panels of X0's
XO_TRACKBARRIERPLAYER_1B_00 by hash and two walls across render (2040..2060, 11600) and (2040..2060, 12200).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(ROOT, "tools")
for p in (TOOLS, os.path.join(TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import Chunk, bstringhash, chunk_bytes, write_chunks  # noqa: E402
from world import collision_write, scenery_write, solids, texpack  # noqa: E402
from world.collision import to_physics  # noqa: E402

NUMBERS = [1100, 1101, 1102]
CENTRES = [(1700.0, 11500.0), (2000.0, 11500.0), (2300.0, 11500.0)]
BIG = 100 * 1024 * 1024


def square(cx, cy, half=32.0, z=100.0, step=8.0):
    tris = []
    n = int(2 * half / step)
    for i in range(n):
        for j in range(n):
            x0, y0 = cx - half + i * step, cy - half + j * step
            a, b, c, d = (x0, y0, z), (x0 + step, y0, z), (x0 + step, y0 + step, z), (x0, y0 + step, z)
            tris += [(a, b, c), (a, c, d)]
    return tris


# the breakable poles' test (FTownSmack.h): city3p.bun is city3.bun with three poles as instances of their own
# (X0's XO_STREETLIGHTC_1B_00 and XO_TRAFFICLIGHTB_1B_00 by hash, our lantern by its hash), and smk3.bun their spawner
# records (tools/world/smackables.py) and override entries; smk3-bad.bun has one record 1 m off its instance (a
# spawner file of another city)
POLES = [(1101, 2000.0, 11480.0, 0x58496BA8, "XO_StreetLightC_1b_00"),
         (1101, 2010.0, 11520.0, 0xFD8304D7, "XO_LightPoleA_1b_00"),
         (1100, 1700.0, 11490.0, 0x54D438CF, "XO_TrafficLightB_1b_00")]
POLE_FLAGS = 0x40108060


def city3(poles=False):
    tex = texpack.new_texture("FTT_GREY", 8, 8, [(90, 90, 90)] * 64)
    tpack = texpack.new_pack("FTOWN_TEST", "FTown\\FTownTest.tpk", [tex])
    th = bstringhash("FTT_GREY")
    lists, sceneries, packs = [], [], []
    for number, (cx, cy) in zip(NUMBERS, CENTRES):
        tris = square(cx, cy)
        so = solids.make_solid("FTT_SQUARE_%d" % number, tris, [((0, 0), (1, 0), (1, 1))] * len(tris), th)
        lists.append(solids.new_list([so], "FTown_Test_%d.bin" % number))
        ident = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        props = []
        if poles:
            box = (-0.25, -3.14, 0.0, 0.25, 0.24, 8.7)
            props = [("FTB_POLE", (h, 0, 0, 0), 0.0, box, ident[:3] + ((x, y, 100.0, 1.0),), POLE_FLAGS)
                     for s, x, y, h, _n in POLES if s == number]
        sceneries.append(scenery_write.make_section(number, [("FTT_%d" % number, (so.name_hash,) * 3 + (0,), ident)],
                                                    {so.name_hash: so}, props=props))
        packs.append(collision_write.make_pack(number, [tuple(to_physics(p) for p in t) for t in tris], []))
    parts = [("tex", tpack)] + [("solids", x) for x in lists] + [("scenery", x) for x in sceneries] + \
        [("collision", x) for x in packs]
    out, pos = [], 0
    for kind, part in parts:
        if kind == "scenery" and pos % 16:
            gap = (-pos) % 16
            gap += 16 if gap < 8 else 0
            out.append(Chunk(0, bytes(gap - 8)))
            pos += gap
        c = {"tex": texpack.write_pack, "solids": solids.write_list, "scenery": scenery_write.write_section,
             "collision": collision_write.write_pack}[kind](part, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return write_chunks(out)


def bar():
    ident = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
    box = (-4.014, -0.01, 0.234, 4.006, 0.059, 6.043)
    props = [("FTB_TRACKBARRIER", (0x54A4FC3F, 0, 0, 0), 0.0, box, ident + ((2050.0, y, 100.0, 1.0),), 0x8060)
             for y in (11600.0, 12200.0)]
    sc = scenery_write.make_section(1409, [], {}, props=props)
    walls = []
    for y in (11600.0, 12200.0):
        a, b = to_physics((2040.0, y, 0.0)), to_physics((2060.0, y, 0.0))
        walls.append(((a[0], a[2]), (b[0], b[2]), 99.0, 130.0, 0x12))
    pack = collision_write.make_pack(1409, [], walls)
    out, pos = [], 0
    for kind, part in (("scenery", sc), ("collision", pack)):
        c = {"scenery": scenery_write.write_section, "collision": collision_write.write_pack}[kind](part, pos + 8)
        out.append(c)
        pos += len(chunk_bytes(c))
    return write_chunks(out)


def smk3(shift=0.0):
    """The spawner file of city3p.bun's poles (each section's props after its one tile instance: index 1, 2)."""
    from world import smackables
    sys.path.insert(0, os.path.join(TOOLS, "x360"))
    from vlthash import vlt32
    from world.collision import to_physics
    packs, entries, k = [], [], 0
    for number in (1100, 1101):
        recs = []
        first = 20000 + k
        for idx, (s, x, y, _h, name) in enumerate([p for p in POLES if p[0] == number]):
            pos = to_physics((x + (shift if k == 0 else 0.0), y, 100.0))
            recs.append(smackables.make_record(smackables.quaternion(0.0), pos, vlt32(name), vlt32(name),
                                               vlt32("trafficlight"), smackables.ROCKPORT_OVERRIDES + k, 20000 + k))
            entries.append((number, 1 + idx, POLE_FLAGS & 0xFFFF))
            k += 1
        packs.append((number, first, recs))
    return smackables.write_file(packs, entries)


def main(argv):
    out = argv[0]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "city3p.bun"), "wb") as f:
        f.write(city3(poles=True))
    with open(os.path.join(out, "smk3.bun"), "wb") as f:
        f.write(smk3())
    with open(os.path.join(out, "smk3-bad.bun"), "wb") as f:
        f.write(smk3(shift=1.0))
    data = city3()
    with open(os.path.join(out, "city3.bun"), "wb") as f:
        f.write(data)
    with open(os.path.join(out, "big.bun"), "wb") as f:
        f.write(data)
        f.write(struct.pack("<II", 0, BIG))
        f.write(bytes(BIG))
    with open(os.path.join(out, "bar.bun"), "wb") as f:
        f.write(bar())
    print("city3.bun %d bytes, big.bun %d bytes, bar.bun" % (len(data), len(data) + 8 + BIG))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
