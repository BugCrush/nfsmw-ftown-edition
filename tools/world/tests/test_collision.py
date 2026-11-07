"""World collision packs: python -m unittest discover -s tools/world/tests -p test_collision.py -v"""
import collections
import os
import sys
import unittest

from common import L2RA, STREAM, TOOLS, need
from world import bun, collision, scenery

sys.path.insert(0, os.path.join(TOOLS, "x360"))
from vlthash import vlt32  # noqa: E402

# SimSurface collection names found by hashing every string of speed.exe and GLOBAL\attributes.bin with the
# attribute database's hash (Task 4); collision.surface_name uses the same list
SURFACES = ["asphalt", "concrete", "grass", "asphalt_no_leaves", "grass_shoulder", "cobble", "wood", "gravel",
            "golf_rough", "metal", "golf_fairway", "dirt", "stone", "sand", "golf_green", "railroad", "glass"]
# the sections with the most drawn road triangles (Task 3), each with its own collision pack
ROAD_SECTIONS = ["G60", "E43", "P70", "G42", "D41", "E42", "E45", "G50", "G46", "Q42"]


def in_tri_2d(p, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def height_in_tri(p, a, b, c):
    """z of the triangle's plane at p's x, y (render coordinates), or None for a vertical triangle."""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    if abs(nz) < 1e-9:
        return None
    return a[2] - (nx * (p[0] - a[0]) + ny * (p[1] - a[1])) / nz


class Grid:
    def __init__(self, tris, cell=8.0):
        self.cell = cell
        self.cells = collections.defaultdict(list)
        for t in tris:
            xs = [p[0] for p in t[:3]]
            ys = [p[1] for p in t[:3]]
            for i in range(int(min(xs) // cell), int(max(xs) // cell) + 1):
                for j in range(int(min(ys) // cell), int(max(ys) // cell) + 1):
                    self.cells[(i, j)].append(t)

    def heights(self, p):
        out = []
        for t in self.cells.get((int(p[0] // self.cell), int(p[1] // self.cell)), []):
            if in_tri_2d(p, t[0], t[1], t[2]):
                z = height_in_tri(p, t[0], t[1], t[2])
                if z is not None:
                    out.append(z)
        return out


class CollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need(cls, L2RA, STREAM)
        cls.sections = bun.sections(L2RA)
        cls.by_name = {s.name: s for s in cls.sections}
        cls.packs = []
        cls.where = collections.Counter()
        for s in cls.sections:
            ps = collision.packs_in(bun.read_range(STREAM, s.offset, s.size))
            cls.where[(s.letter if s.letter in "XYZV" else "regular", len(ps))] += 1
            for p in ps:
                cls.packs.append((s.name, p))

    def test_packs_parse_all(self):
        st = collections.Counter()
        for name, p in self.packs:
            st["packs"] += 1
            self.assertEqual(p.name, str(p.section), name)
            self.assertLessEqual(p.carp_size, 1 << 24)
            self.assertEqual(p.flags, 0)  # unresolved in the file
            st["instances"] += len(p.instances)
            for inst in p.instances:
                self.assertIn(inst.article, p.articles, name)
                self.assertEqual(inst.flags, 0)  # no instance turns its up axis: row 1 is (0, 1, 0)
            for a in p.articles.values():
                nstrips, ssize, nedges, esize, _, nsurf, surfsize, _, _ = a.header
                self.assertEqual(esize, 32 * nedges)
                self.assertEqual(surfsize, 4 * nsurf)
                for s in a.strips:
                    self.assertEqual(len(s.surfaces), len(s.verts) - 2)
                    for i in s.surfaces:
                        self.assertLess(i, max(nsurf, 1))
                for b in a.barriers:
                    self.assertLess(b.surface, max(nsurf, 1))
                st["strips"] += len(a.strips)
                st["triangles"] += sum(len(s.verts) - 2 for s in a.strips)
                st["barriers"] += len(a.barriers)
        print("\n  %s; packs per section kind %s" % (dict(st), dict(self.where)))
        self.assertEqual(st["packs"], 390)

    def test_pack_section_numbers(self):  # each pack is filed under its section number (the drivable one)
        for name, p in self.packs:
            s = self.by_name[name]
            self.assertIn(p.section, (s.number, s.number - bun.LOD_OFFSET), name)

    def test_collision_under_roads(self):
        game = os.path.dirname(os.path.dirname(L2RA))
        from world import world as cli
        lib = cli.library_solids(game)
        results = []
        for name in ROAD_SECTIONS:
            s = self.by_name[name]
            chunks = bun.read_range(STREAM, s.offset, s.size)
            data = scenery.read_section(chunks)
            road = [t for t in scenery.placed_triangles(data, lib) if t[3] == "road"]
            ctris = []
            for p in collision.packs_in(chunks):
                for a, b, c, h, _ in collision.triangles(p):
                    ctris.append((collision.to_render(a), collision.to_render(b), collision.to_render(c)))
            grid = Grid(ctris)
            near = far = none = 0
            for t in road[::3]:
                cen = tuple(sum(p[k] for p in t[:3]) / 3 for k in range(3))
                hs = grid.heights(cen)
                if not hs:
                    none += 1
                elif min(abs(z - cen[2]) for z in hs) <= 0.5:
                    near += 1
                else:
                    far += 1
            results.append((name, near, far, none))
        print("\n  drawn road centroids with a collision face within 0.5 m (near, farther, no face):")
        for r in results:
            print("    %s %d %d %d" % r)
        near = sum(r[1] for r in results)
        total = sum(r[1] + r[2] + r[3] for r in results)
        self.assertGreaterEqual(near / total, 0.9)

    def test_barriers_vertical(self):
        """A barrier is stored as two points: a horizontal segment (x, z of both) with a bottom and a top height
        (WCollisionBarrier::YBot/YTop/GetHeight, WCollision.h:167-200). A sloped barrier cannot be expressed."""
        heights = []
        both_ends = 0
        for _, p in self.packs:
            for a, b, h, s, _ in collision.barriers(p):
                heights.append(h)
                both_ends += 1
        heights.sort()
        n = len(heights)
        print("\n  barriers %d; height min %.2f, 1%% %.2f, median %.2f, 99%% %.2f, max %.2f m; under 0.25 m: %d" %
              (n, heights[0], heights[n // 100], heights[n // 2], heights[n * 99 // 100], heights[-1],
               sum(1 for x in heights if x < 0.25)))
        self.assertGreater(heights[n // 100], 0.25)

    def test_world_grid(self):
        """The static collision grid of L2RA.BUN 0x3B800: its nodes tile the data, its instance tags (section << 16 |
        index) name real pack instances, every pack instance is in some node, and every instance lies in the grid."""
        cs = bun.read_file(L2RA)
        grid = None
        for c, pos in scenery.with_positions(cs, 0):
            if c.id == 0x3B800:
                grid = collision.read_world_grid(c.data, pos)
        self.assertIsNotNone(grid)
        self.assertEqual(grid.consumed, grid.data_size)
        self.assertEqual(len(set(grid.node_indices)), grid.nodes)
        self.assertLess(max(grid.node_indices), grid.rows * grid.cols)
        packs = {p.section: p for _, p in self.packs}
        listed = set()
        types = collections.Counter()
        bad = 0
        for el in grid.elements:
            for t, tag in el:
                types[t] += 1
                if t == 0:
                    sec, ind = tag >> 16, tag & 0xFFFF
                    if sec not in packs or ind >= len(packs[sec].instances):
                        bad += 1
                    listed.add((sec, ind))
        every = {(sec, i) for sec, p in packs.items() for i in range(len(p.instances))}
        outside = 0
        for sec, p in packs.items():
            for inst in p.instances:
                x, _, z = inst.position
                if not (grid.min[0] <= x < grid.max[0] and grid.min[2] <= z < grid.max[1]):
                    outside += 1
        print("\n  grid: min (%.0f, %.0f) physics x, z; %d cols x %d rows of %.0f m (x %.0f..%.0f, z %.0f..%.0f); %d of %d"
              " cells stored; elements by type (0 instance, 1 trigger, 2 object, 3 road segment) %s; instance tags"
              " not found %d; pack instances in no cell %d of %d; outside the grid %d" %
              (grid.min[0], grid.min[2], grid.cols, grid.rows, grid.edge, grid.min[0], grid.max[0], grid.min[2],
               grid.max[1], grid.nodes, grid.rows * grid.cols, dict(types), bad, len(every - listed), len(every),
               outside))
        self.assertEqual(bad, 0)
        self.assertEqual(len(every - listed), 0)
        self.assertEqual(outside, 0)

    def test_surface_names(self):
        names = {vlt32(n): n for n in SURFACES}
        used = collections.Counter()
        for _, p in self.packs:
            for a in p.articles.values():
                for h in a.surfaces:
                    used[names.get(h, "0x%08X" % h)] += 1
        print("\n  surfaces in articles: %s" % used.most_common())
        self.assertIn("asphalt", used)
        unknown = sum(v for k, v in used.items() if k.startswith("0x") and k != "0x00000000")
        self.assertLess(unknown, 10)


if __name__ == "__main__":
    unittest.main()
