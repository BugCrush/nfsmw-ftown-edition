"""Most Wanted's world files, read only: TRACKS\\L2RA.BUN (the track's permanent file) and TRACKS\\STREAML2RA.BUN
(the region file the streamer reads sections from).

L2RA.BUN (1.4 MB) is read whole with `read_file`. STREAML2RA.BUN (532 MB) is never read whole: `iter_top` seeks from
chunk header to chunk header, `read_range` reads one section's bytes.

Records (decompilation, World/TrackStreamer.hpp and World/VisibleSection.hpp; checked over all records in
tools/world/tests/test_bun.py):

- TrackStreamingSection (0x34110), 0x5C bytes each (TrackStreamer.hpp:47-80): +0x00 name (8), +0x08 s16 number,
  +0x0C status, +0x10 file type (0 permanent, 1 region), +0x14 file offset, +0x18 size, +0x1C compressed size,
  +0x20 perm size, +0x24 priority, +0x28 centre (x, y), +0x30 radius, +0x34 checksum; the rest is run-time state
  (zero in the file). TrackStreamer::Loader (TrackStreamer.cpp:493) takes the count as chunk size / 0x5C.
- VisibleSectionBoundary (0x34152 inside 0x80034150; VisibleSection.hpp:79-131), variable size 0x24 + 8 x points:
  +0x00 bTNode (8 bytes, junk in the file), +0x08 s16 section number, +0x0A s8 point count, +0x0B s8 panorama flag,
  +0x0C bbox min (x, y), +0x14 bbox max, +0x1C centre, +0x24 points (x, y) x count.
"""
import os
import struct
import sys
from dataclasses import dataclass
from typing import Iterator, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CARBUILD = os.path.join(os.path.dirname(HERE), "carbuild")
if CARBUILD not in sys.path:
    sys.path.insert(0, CARBUILD)

from chunks import Chunk, find_one, read_chunks  # noqa: E402

TRACK_STREAMING_SECTIONS = 0x34110
TRACK_STREAMING_INFOS = 0x34111
VISIBLE_SECTION_MANAGER = 0x80034150
VISIBLE_SECTION_BOUNDARIES = 0x34152
DRIVABLE_SCENERY_SECTIONS = 0x34153
SECTION_RECORD = 0x5C


def read_file(path):
    with open(path, "rb") as f:
        return read_chunks(f.read())


def iter_top(path) -> Iterator[Tuple[int, int, int]]:
    """(offset, id, size) of every top-level chunk, by seeking; raises if a header runs past the file."""
    total = os.path.getsize(path)
    with open(path, "rb") as f:
        off = 0
        while off < total:
            f.seek(off)
            head = f.read(8)
            if len(head) < 8:
                raise ValueError("truncated chunk header at 0x%X" % off)
            cid, size = struct.unpack("<II", head)
            if off + 8 + size > total:
                raise ValueError("chunk 0x%08X at 0x%X runs past the file end" % (cid, off))
            yield off, cid, size
            off += 8 + size


def read_range(path, offset, size) -> List[Chunk]:
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(size)
    if len(data) != size:
        raise ValueError("short read at 0x%X: %d of %d bytes" % (offset, len(data), size))
    return read_chunks(data)


def section_name(number):
    """VisibleSection.hpp:16 GetScenerySectionLetter: letter = number / 100 ('A' = 1), then number % 100."""
    return "%s%d" % (chr(number // 100 + ord("A") - 1), number % 100)


LOD_OFFSET = 40  # VisibleSectionManageInfo 0x34151 +0 in L2RA.BUN (read by lod_offset); ScenerySectionLODOffset


def lod_offset(l2ra_path):
    return struct.unpack_from("<i", find_one(read_file(l2ra_path), 0x34151).data, 0)[0]


def is_drivable(number, lod=LOD_OFFSET):
    """VisibleSection.hpp:47 IsScenerySectionDrivable: letters A..T, sub-number 1..LOD offset - 1."""
    letter = chr(number // 100 + ord("A") - 1)
    return "A" <= letter < "U" and 0 < number % 100 < lod


def combined_number(number, present, lod=LOD_OFFSET):
    """TrackStreamer.cpp:684 GetCombinedSectionNumber: a drivable section with no streaming section of its own is
    stored in its LOD section (number + LOD offset). `present` is the set of streaming section numbers."""
    if is_drivable(number, lod) and number not in present and number + lod in present:
        return number + lod
    return number


@dataclass
class Section:
    number: int
    name: str
    offset: int
    size: int
    centre: tuple
    radius: float
    raw: bytes
    file_type: int = 1
    compressed_size: int = 0
    perm_size: int = 0
    priority: int = 0
    checksum: int = 0

    @property
    def letter(self):
        return self.name[0]


def parse_sections(data) -> List[Section]:
    out = []
    for i in range(len(data) // SECTION_RECORD):
        r = data[i * SECTION_RECORD:(i + 1) * SECTION_RECORD]
        name = r[:8].split(b"\0")[0].decode("ascii")
        number, = struct.unpack_from("<h", r, 8)
        _status, ftype, foff, size, csize, perm, prio = struct.unpack_from("<iiiiiii", r, 0x0C)
        cx, cy, radius = struct.unpack_from("<fff", r, 0x28)
        checksum, = struct.unpack_from("<I", r, 0x34)
        out.append(Section(number, name, foff, size, (cx, cy), radius, bytes(r), ftype, csize, perm, prio, checksum))
    return out


def sections(l2ra_path) -> List[Section]:
    return parse_sections(find_one(read_file(l2ra_path), TRACK_STREAMING_SECTIONS).data)


@dataclass
class Boundary:
    number: int
    panorama: int
    bbox_min: tuple
    bbox_max: tuple
    centre: tuple
    points: list


def parse_boundaries(data):
    out = {}
    off = 0
    while off + 0x24 <= len(data):
        number, npts, pano = struct.unpack_from("<hbb", data, off + 8)
        bmin = struct.unpack_from("<2f", data, off + 0x0C)
        bmax = struct.unpack_from("<2f", data, off + 0x14)
        centre = struct.unpack_from("<2f", data, off + 0x1C)
        pts = [struct.unpack_from("<2f", data, off + 0x24 + 8 * k) for k in range(npts)]
        if number in out:
            raise ValueError("boundary for section %d twice" % number)
        out[number] = Boundary(number, pano, bmin, bmax, centre, pts)
        off += 0x24 + 8 * npts
    if off != len(data):
        raise ValueError("boundary records end at %d of %d bytes" % (off, len(data)))
    return out


def boundaries(l2ra_path):
    """{section number: Boundary} from VisibleSectionBoundaries 0x34152."""
    return parse_boundaries(find_one(read_file(l2ra_path), VISIBLE_SECTION_BOUNDARIES).data)


def parse_drivable_sections(data):
    """{section number: [visible section numbers]} from DrivableScenerySections 0x34153 (VisibleSection.hpp:154-206):
    variable-size records, 0xA4 - (72 - max visible) x 2 bytes each (GetMemoryImageSize): +0x00 bTNode (8), +0x08
    boundary pointer (run time), +0x0C s16 section number, +0x0E s8 most visible, +0x0F s8 max visible, +0x10 s16
    visible count, +0x12 s16 visible sections."""
    out = {}
    off = 0
    while off + 0x12 <= len(data):
        number, most, mx, count = struct.unpack_from("<hbbh", data, off + 0x0C)
        out[number] = list(struct.unpack_from("<%dh" % count, data, off + 0x12))
        off += 0xA4 - (72 - mx) * 2
    if off != len(data):
        raise ValueError("drivable section records end at %d of %d bytes" % (off, len(data)))
    return out


def drivable_sections(l2ra_path):
    return parse_drivable_sections(find_one(read_file(l2ra_path), DRIVABLE_SCENERY_SECTIONS).data)


def point_in_poly(p, pts):
    """Even-odd rule, as the game's MyIsPointInPoly (VisibleSection.cpp:271) is used for boundaries."""
    x, y = p
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def dist_to_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return ((p[0] - qx) ** 2 + (p[1] - qy) ** 2) ** 0.5


def distance_outside(p, pts):
    """0 inside the polygon, else the distance to its nearest edge."""
    if point_in_poly(p, pts):
        return 0.0
    return min(dist_to_segment(p, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
