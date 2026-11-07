"""F-Town's evening lights (docs/ftown-notes.md "Evening (2026-11-05)").

The game's world shader has no self-lit term: colour = (vertex colour x ambient x 4 + shadow x N.L x diffuse) x
texture. So the city's lights are its own pre-lit vertex colours, raised for the evening only. A glowing triangle keeps
its day colour's RGB and carries its class in the colour's alpha byte (0xF0..0xFE; the shader's alpha = texture alpha
x vertex alpha, and Rockport's own roads carry 0x7F, so an alpha just under 1 on an opaque world draw changes nothing
seen). After the city is written, lights_table() lists every such vertex (its file offset, its day colour, its evening
colour, and for a window pane the move from 5 cm behind its wall to 4 cm in front of it); write_lights() puts that list
beside the city as ftown-evening.bin, which FTownLoader applies to its fresh copy of the city file before LoadChunks,
only when F-Town (Evening) is chosen. By day the file is loaded as written: the panes stay hidden behind the walls.

ftown-evening.bin: b"FTEV", u32 version 1, u32 the city file's size, u32 count, u32 0, then count entries
`<I3fII`: the vertex record's file offset (36-byte records: position, normal, colour at +24, uv), the move (dx, dy, dz,
render metres), the day colour (as in the file) and the evening colour.
"""
import os
import struct
import sys
import zlib

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# class: (alpha, evening vertex colour). At dusk the shade is (0.60, 0.76, 1.44) (the pack's dusk_sunny ambient x 4),
# so a full vertex colour on a near-white texel gives about 3.6 x Rockport's ground grey; the colours lean warm because
# the dusk ambient leans blue
CLASSES = {
    "lamp": (0xFE, (255, 215, 105)),     # street lamps' and Mathura Road lights' lanterns, the viaduct's lamps
    "sig_red": (0xFD, (255, 60, 50)),     # one lamp of each traffic signal, both faces
    "sig_amber": (0xFC, (255, 190, 40)),
    "sig_green": (0xFB, (70, 255, 190)),
    "board": (0xFA, (225, 210, 175)),     # billboards' faces (Run I fixes: held under the shop fronts')
    "shop": (0xF9, (255, 225, 160)),      # market shop fronts (boards and the lit shops under them)
    "station": (0xF8, (235, 225, 195)),   # the metro stations' drawn fronts
    "pane": (0xF7, (255, 205, 130)),      # lit window panes (moved in front of their wall)
    # Run J, item 2: the stations' raised names (tools/citymap/station_letters.py, on the near-white FTC_PAINT), lit
    # in their own colours as the drawn fronts round them are lit ("station": the day colour x 235/68)
    "letters_neelam": (0xF6, (36, 44, 104)),
    "letters_bata": (0xF5, (240, 240, 236)),
    "letters_oldfbd": (0xF4, (36, 60, 150)),
}
BY_ALPHA = {a: name for name, (a, _rgb) in CLASSES.items()}
# the review: one step of a 24-bit depth buffer with the game's 0.5 m near plane is about 5.8 cm at 700 m (the far
# switch), so a pane 5 cm behind its wall could win its depth test there; 15 cm keeps 2.5 steps, and in the
# evening 10 cm in front of it 1.7
PANE_IN = 0.15     # m behind the wall by day (hidden by it)
PANE_SHIFT = 0.25  # m along the pane's normal for the evening: 10 cm in front of the wall
PANE_PERCENT = 8  # of the windows a house wall shows (8: Sector 16 Market's view stays in its triangle budget)
VERTEX = 36
VERTICES = 0x134B01
CONTAINER = 0x80000000
HEADER = struct.Struct("<4sIIII")
ENTRY = struct.Struct("<I3fII")


def glow(col, cls):
    """col's RGB with the class's alpha."""
    return (col & 0xFFFFFF) | (CLASSES[cls][0] << 24)


def evening_colour(cls):
    r, g, b = CLASSES[cls][1]
    return 0xFF000000 | r << 16 | g << 8 | b


def _vertex_buffers(data, start=0, end=None):
    """(file offset of the first vertex, vertex count) of every vertex buffer chunk (0x11 run to 128 from the file's
    start: the city's sections are aligned from it)."""
    end = len(data) if end is None else end
    out = []
    off = start
    while off < end:
        cid, size = struct.unpack_from("<II", data, off)
        body = off + 8
        if cid & CONTAINER:
            out += _vertex_buffers(data, body, body + size)
        elif cid == VERTICES:
            run = (-body) % 128
            if data[body:body + run] != b"\x11" * run or (size - run) % VERTEX:
                raise ValueError("vertex buffer at 0x%X: not 0x11-aligned 36-byte records" % off)
            out.append((body + run, (size - run) // VERTEX))
        off = body + size
    return out


def vertex_alphas(data):
    """{alpha: vertices} over the file."""
    out = {}
    for first, n in _vertex_buffers(data):
        for k in range(n):
            a = data[first + k * VERTEX + 27]
            out[a] = out.get(a, 0) + 1
    return out


def lights_table(data):
    """[(offset, dx, dy, dz, day colour, evening colour)] of every glowing vertex, in file order."""
    out = []
    for first, n in _vertex_buffers(data):
        for k in range(n):
            o = first + k * VERTEX
            day = struct.unpack_from("<I", data, o + 24)[0]
            cls = BY_ALPHA.get(day >> 24)
            if cls is None:
                continue
            d = (0.0, 0.0, 0.0)
            if cls == "pane":
                nx, ny, nz = struct.unpack_from("<3f", data, o + 12)
                d = tuple(struct.unpack("<f", struct.pack("<f", c * PANE_SHIFT))[0] for c in (nx, ny, nz))
            out.append((o,) + d + (day, evening_colour(cls)))
    return out


def apply(data, table):
    """The city's bytes with the evening applied (what FTownLoader does to its copy): every entry's day colour checked
    first (ValueError and nothing changed on any mismatch), then each vertex moved and recoloured."""
    for off, _dx, _dy, _dz, day, _eve in table:
        if off + VERTEX > len(data) or struct.unpack_from("<I", data, off + 24)[0] != day:
            raise ValueError("vertex at 0x%X does not hold the day colour 0x%08X" % (off, day))
    out = bytearray(data)
    for off, dx, dy, dz, _day, eve in table:
        x, y, z = struct.unpack_from("<3f", out, off)
        struct.pack_into("<3f", out, off, x + dx, y + dy, z + dz)
        struct.pack_into("<I", out, off + 24, eve)
    return bytes(out)


def write_lights(data, path):
    """Writes ftown-evening.bin for the city bytes `data`; returns {class: vertices}."""
    table = lights_table(data)
    with open(path, "wb") as f:
        f.write(HEADER.pack(b"FTEV", 1, len(data), len(table), 0))
        for e in table:
            f.write(ENTRY.pack(*e))
    counts = {}
    for e in table:
        cls = BY_ALPHA[e[4] >> 24]
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def read_lights(path):
    with open(path, "rb") as f:
        raw = f.read()
    magic, ver, _size, n, _z = HEADER.unpack_from(raw, 0)
    if magic != b"FTEV" or ver != 1 or len(raw) != HEADER.size + n * ENTRY.size:
        raise ValueError("%s is not an F-Town lights file" % path)
    return [ENTRY.unpack_from(raw, HEADER.size + k * ENTRY.size) for k in range(n)]


def wall_panes(p, q, z0, h, block, u_off, key, percent=PANE_PERCENT):
    """(triangles, uvs) of the lit window panes of a house wall p -> q (outward on the right) as tiles.house_wall draws
    it (FTC_HOUSES facade block `block`, its parapet's top at h + PARAPET, u running from u_off metres): one quad in the
    `litwin` cell per chosen window of the facade's top four storeys that lies wholly on the wall above z0, PANE_IN
    behind the wall, facing out. A window is chosen when crc32 of (key, storey, its index along the wall) falls under
    `percent` of 100."""
    import math
    from tools.citymap import buildings as bmod, housetex, parts as P, textures
    L = math.dist(p, q)
    if L < 1.0:
        return [], []
    d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
    n = (d[1], -d[0])  # outward: the right of p -> q
    top = h + bmod.PARAPET
    span = textures.HOUSE_SPAN_M
    shift = u_off % span
    tris, uvs = [], []
    uv = [textures.house_cell_uv("litwin", s, t) for s, t in ((0, 1), (1, 1), (1, 0), (0, 0))]
    for row in range(4):
        st_top = top - bmod.PARAPET - bmod.STOREY * row
        if st_top - bmod.STOREY < z0 - 1e-6:
            break
        for k, (x, y0, w, wh) in enumerate(housetex.window_rects(block, row)):
            m = 0.06  # the glass inside the frame
            s, rep = x - shift, 0
            while s + w <= L:
                if s >= 0.1 and s + w <= L - 0.1:
                    if zlib.crc32(("%s:%d:%d:%d" % (key, row, rep, k)).encode()) % 100 < percent:
                        a, b = s + m, s + w - m
                        zt, zb = st_top - y0 - m, st_top - y0 - wh + m
                        A = (p[0] + d[0] * a - n[0] * PANE_IN, p[1] + d[1] * a - n[1] * PANE_IN)
                        B = (p[0] + d[0] * b - n[0] * PANE_IN, p[1] + d[1] * b - n[1] * PANE_IN)
                        quad = [(A[0], A[1], zb), (B[0], B[1], zb), (B[0], B[1], zt), (A[0], A[1], zt)]
                        t2, u2 = P.quad(quad, uv, (n[0], n[1], 0.0))
                        tris += t2
                        uvs += u2
                s += span
                rep += 1
    return tris, uvs
