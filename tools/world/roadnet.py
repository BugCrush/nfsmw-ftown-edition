"""The game's road network (the AI's roads: chunk 0x3B800 of L2RA.BUN, UGroup 'CARP' > 'RNgp'): read and write.

Layouts from the decompilation (World/WRoadElem.h) checked over all of Rockport's data
(docs/ftown-traffic-ai-research.md E1); tools/world/tests/test_roadnet.py proves the writer by writing Rockport's own
network again byte for byte. Everything is little-endian; positions are physics (x, y up, z).

    RNhd  WRoadNetworkInfo, 14 B: u16 profiles, nodes, segments, intersections, roads, junctions, 2 pad bytes
    RNpf  WRoadProfile, 64 B: u8 zones, u8 middle zone (lanes at or right of it run forward), 2 pad bytes, 15 lane
          words (type 4 bits, width and offset 14-bit signed each, x 100/8191 m; unused words are filler 0xAA..)
    RNnd  WRoadNode, 32 B: f32 x, y, z, s16 index, s16 profile, u8 segment count, u8 pad, u16 segments[7]
    RNsg  WRoadSegment, 22 B: u16 node a, b, u16 length (x 1000/65535 m), s16 road (-1 in a junction), s16 index,
          u16 flags, u16 end handle length, u16 start handle length (x 500/65535 m), s8 end handle[3] (pointing back
          towards a: GetEndForwardVec uses -1/127), s8 start handle[3]; the curve is the Bezier a, a + start control,
          b + end control, b (WRoadNetwork::BuildSegmentSpline)
    RNrd  WRoad, 8 B: u16 scale, u16 length (x 4000/65535 m), u8 shortcut (255 none), u8 minimum width, u16 speech id

In the file the five items' data follow one another (hd, filler to 16, nd, pf, rd, sg): `rngp_region`.
"""
import math
import struct
from dataclasses import dataclass, field
from typing import List, Tuple

from world import collision

DECISION, NO_TRAFFIC, RACE_FORWARD, INTERSECTION, ENTRANCE, COPS_XOR_TRAFFIC, ONE_WAY, SHORTCUT, CURVED = (
    1, 2, 4, 8, 16, 32, 64, 128, 256)
END_INVERTED, START_INVERTED, IN_RACE = 1 << 9, 1 << 10, 1 << 15
LANE_TRAFFIC, LANE_DRAG, LANE_COP, LANE_COP_RECKLESS = 1, 2, 3, 4
FILL32, FILL16, FILL8 = 0xAAAAAAAA, 0xAAAA, 0xAA
ITEMS = ("RNhd", "RNnd", "RNpf", "RNrd", "RNsg")
SIZES = {"RNnd": 0x20, "RNpf": 0x40, "RNrd": 8, "RNsg": 0x16}


def _bits_signed(v, off, n):
    x = (v << (32 - (off + n))) & 0xFFFFFFFF
    if x & 0x80000000:
        x -= 1 << 32
    return x >> (32 - n)


def lane(word):
    """(type, width m, offset m) of a lane word (WRoadLane)."""
    return word & 0xF, _bits_signed(word, 4, 14) * (100.0 / 8191.0), _bits_signed(word, 18, 14) * (100.0 / 8191.0)


def _q14(v):
    q = int(round(v * 8191.0 / 100.0))
    if not -8192 <= q <= 8191:
        raise ValueError("lane value %.2f m out of range" % v)
    return q & 0x3FFF


def lane_word(t, width, offset):
    return (t & 0xF) | (_q14(width) << 4) | (_q14(offset) << 18)


@dataclass
class Header:
    profiles: int
    nodes: int
    segments: int
    intersections: int
    roads: int
    junctions: int
    pad: bytes = b"\xaa\xaa"


@dataclass
class Profile:
    zones: int
    middle: int
    pad: bytes
    words: List[int]

    @classmethod
    def make(cls, lanes, middle):
        """lanes: [(type, width m, offset m)] left to right; middle: the first forward lane."""
        if not 1 <= len(lanes) <= 15 or not 0 <= middle <= len(lanes):
            raise ValueError("a profile has 1..15 lanes and its middle zone inside them")
        words = [lane_word(*l) for l in lanes] + [FILL32] * (15 - len(lanes))
        return cls(len(lanes), middle, b"\xaa\xaa", words)

    def lanes(self):
        return [lane(w) for w in self.words[:self.zones]]


@dataclass
class Node:
    pos: Tuple[float, float, float]
    index: int
    profile: int
    segments: List[int]
    pad: int = FILL8
    unused: List[int] = None
    count: int = None

    def __post_init__(self):
        if self.count is None:
            self.count = len(self.segments)
        if self.unused is None:
            self.unused = [FILL16] * (7 - len(self.segments))


@dataclass
class Segment:
    nodes: Tuple[int, int]
    nlength: int
    road: int
    index: int
    flags: int
    end_len: int
    start_len: int
    end_handle: Tuple[int, int, int]
    start_handle: Tuple[int, int, int]

    @property
    def length_m(self):
        return self.nlength * 1000.0 / 65535.0

    @staticmethod
    def _dir(v):
        L = math.sqrt(sum(c * c for c in v)) or 1.0
        return tuple(max(-127, min(127, int(round(127.0 * c / L)))) for c in v)

    @classmethod
    def make(cls, a, b, length, road, index, flags, start_dir, end_dir, start_len, end_len):
        """A segment from node a to b; start_dir / end_dir: the curve's forward direction at a and at b (the end
        handle is stored pointing back), handle lengths in metres."""
        q = lambda m, s: int(round(min(m, s * 0.999) * 65535.0 / s))  # noqa: E731
        return cls((a, b), q(length, 1000.0), road, index, flags, q(end_len, 500.0), q(start_len, 500.0),
                   cls._dir(tuple(-c for c in end_dir)), cls._dir(start_dir))

    def start_control(self):
        s = self.start_len * 500.0 / (127.0 * 65535.0)
        return tuple(s * c for c in self.start_handle)

    def end_control(self):
        s = self.end_len * 500.0 / (127.0 * 65535.0)
        return tuple(s * c for c in self.end_handle)


@dataclass
class Road:
    scale: int
    nlength: int
    shortcut: int
    minwidth: int
    speech: int


@dataclass
class Network:
    header: Header
    profiles: List[Profile] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)
    roads: List[Road] = field(default_factory=list)


# ---------------------------------------------------------------- records

def decode_profile(d, o=0):
    return Profile(d[o], d[o + 1], bytes(d[o + 2:o + 4]), list(struct.unpack_from("<15I", d, o + 4)))


def encode_profile(p):
    return struct.pack("<BB2s15I", p.zones, p.middle, p.pad, *p.words)


def decode_node(d, o=0):
    x, y, z, idx, prof, n, pad = struct.unpack_from("<3fhhBB", d, o)
    segs = list(struct.unpack_from("<7H", d, o + 18))
    return Node((x, y, z), idx, prof, segs[:n], pad, segs[n:], n)


def encode_node(n):
    return struct.pack("<3fhhBB7H", *n.pos, n.index, n.profile, n.count, n.pad, *(list(n.segments) + list(n.unused)))


def decode_segment(d, o=0):
    a, b, ln, road, idx, flags, el, sl = struct.unpack_from("<HHHhhHHH", d, o)
    return Segment((a, b), ln, road, idx, flags, el, sl, struct.unpack_from("<3b", d, o + 16),
                   struct.unpack_from("<3b", d, o + 19))


def encode_segment(s):
    return struct.pack("<HHHhhHHH3b3b", s.nodes[0], s.nodes[1], s.nlength, s.road, s.index, s.flags, s.end_len,
                       s.start_len, *s.end_handle, *s.start_handle)


def decode_road(d, o=0):
    return Road(*struct.unpack_from("<HHBBH", d, o))


def encode_road(r):
    return struct.pack("<HHBBH", r.scale, r.nlength, r.shortcut, r.minwidth, r.speech)


def decode(items):
    """A Network from the five items' data {name: bytes}."""
    h = items["RNhd"]
    head = Header(*struct.unpack_from("<6H", h, 0), bytes(h[12:14]))
    net = Network(head)
    for name, size, fn, out in (("RNpf", 0x40, decode_profile, net.profiles), ("RNnd", 0x20, decode_node, net.nodes),
                                ("RNsg", 0x16, decode_segment, net.segments), ("RNrd", 8, decode_road, net.roads)):
        d = items[name]
        if len(d) % size:
            raise ValueError("%s: %d bytes is not a whole number of %d-byte records" % (name, len(d), size))
        out.extend(fn(d, o) for o in range(0, len(d), size))
    return net


def encode(net):
    h = net.header
    return {"RNhd": struct.pack("<6H2s", h.profiles, h.nodes, h.segments, h.intersections, h.roads, h.junctions,
                                h.pad),
            "RNpf": b"".join(encode_profile(p) for p in net.profiles),
            "RNnd": b"".join(encode_node(n) for n in net.nodes),
            "RNsg": b"".join(encode_segment(s) for s in net.segments),
            "RNrd": b"".join(encode_road(r) for r in net.roads)}


# ---------------------------------------------------------------- the track file's group

def _find(g, name):
    if g.name == name:
        return g
    for k in g.groups:
        r = _find(k, name)
        if r:
            return r
    return None


def _rngp(chunk_data, pos):
    d = chunk_data[(-pos) % 16:]
    g = _find(collision.read_ugroup(d, 0), "RNgp")
    if g is None:
        raise ValueError("no RNgp group")
    return d, g


def rngp_items(chunk_data, pos):
    """{name: bytes} of the five RNgp items of a 0x3B800 chunk's data (which starts at `pos` in its file)."""
    _d, g = _rngp(chunk_data, pos)
    items = {u.type: u.data for u in g.data}
    missing = [k for k in ITEMS if k not in items]
    if missing:
        raise ValueError("RNgp lacks %s" % ", ".join(missing))
    return items


def _region_offset(d):
    """Where the RNgp items' data starts in the aligned chunk data (the RNhd UData header's offset)."""
    def walk(g):
        tag, bits, dc, off = struct.unpack_from("<4I", d, g)
        n = bits >> 5
        arr = g + 16 * off
        if tag == 0x524E6770:  # 'RNgp'
            u = arr + 16 * n
            return u + struct.unpack_from("<I", d, u + 12)[0]
        for i in range(n):
            r = walk(arr + 16 * i)
            if r is not None:
                return r
        return None
    return walk(0)


def rngp_region(net, fill=b"\xaa"):
    """The five items' data as the file lays them out: hd, filler to 16 bytes, nd, pf, rd, sg."""
    e = encode(net)
    out = bytearray(e["RNhd"])
    out += fill * ((-len(out)) % 16)
    for k in ("RNnd", "RNpf", "RNrd", "RNsg"):
        out += e[k]
    return bytes(out)


def read_rngp(chunk_data, pos):
    """(Network, the region's bytes as in the file, the region's offset in the aligned chunk data)."""
    d, _g = _rngp(chunk_data, pos)
    items = rngp_items(chunk_data, pos)
    net = decode(items)
    start = _region_offset(d)
    size = len(rngp_region(net))
    return net, bytes(d[start:start + size]), start
