"""Test data for the stand-in's connection variants (ftown/tests/run.py link-*), made with tools/citymap/connector.py's
writers: a test road from the stand-in's junction at render (1045, 2000) north to (2000, 10000), its FTCN data naming
the stand-in's zones (703 the junction's, 726 and 723 north of it, ours 226 from 723's top edge at y 4000 to 9950), its
wall (pack 703: five barriers on render y 2100 from x 995 to 1095), a city wall (pack 0) with no barrier on its line,
and the ramp's face region (pack 703: the stand-in's four faces at render (1040..1050, 2045..2060), z 113; not its two
at z 90).

    .tools/cityenv/Scripts/python ftown/tests/make_test_link.py <out dir>

writes link.bun, link.bin, link-badsize.bin (built with another file size), link-badwall.bin (wall 0 expects 4) and
link-badfaces.bin (the face region expects 3).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

from chunks import write_chunks  # noqa: E402
from tools.citymap import connector as cn  # noqa: E402

JUNCTION = (1045.0, 2000.0)
BOX = [1500.0, 10000.0, 2500.0, 12500.0]
SOURCE = [703, 743, 704, 744, 309, 726]  # the stand-in's 703 list
EXTRA = [1100, 1101, 1102, cn.SECTION]
OURS = [(900.0, 4000.0), (2100.0, 4000.0), (2100.0, 9950.0), (900.0, 9950.0)]
WALL = ((995.0, 2100.0), (1095.0, 2100.0))
FACES = (703, 4, 1005.0, 2052.0, 1085.0, 2052.0, 15.0, 110.0, 116.0)


def main(out):
    p = cn.Path((2000.0, 10000.0), 101.0, 30.0, start=JUNCTION, start_z=113.0, headings=(90.0, 90.0))
    info = {"edge_box": BOX}
    apron = (1985.0, 2015.0)
    data = write_chunks(cn.assemble(*cn.make_parts(p, info, apron, WALL, (111.0, 177.0))))
    with open(os.path.join(out, "link.bun"), "wb") as f:
        f.write(data)

    def connect(size, expect0, faces=FACES[1]):
        walls = [(703, expect0, WALL[0][0], WALL[0][1], WALL[1][0], WALL[1][1], 100.0, 200.0),
                 (0, 0, 5000.0, 5000.0, 5001.0, 5000.0, 0.0, 300.0)]
        return cn.pack_connect(JUNCTION + (113.0,), BOX, (703, 226, 723), (726, 723), SOURCE, EXTRA, OURS, walls, size,
                               faces=[(FACES[0], faces) + FACES[2:]])

    for name, size, expect, faces in (("link.bin", len(data), 5, 4), ("link-badsize.bin", len(data) + 1, 5, 4),
                                      ("link-badwall.bin", len(data), 4, 4), ("link-badfaces.bin", len(data), 5, 3)):
        with open(os.path.join(out, name), "wb") as f:
            f.write(connect(size, expect, faces))
    print("link.bun: %d bytes; road %.0f m" % (len(data), p.length))


if __name__ == "__main__":
    main(sys.argv[1])
