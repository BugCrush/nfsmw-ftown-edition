"""Own looks Task 4: lived-in houses and markets (facades from the house atlas, muted tints, mumties, water tanks,
balconies, boundary walls with gates and hedges).

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_houses -v
"""
import math
import unittest

import numpy as np
import shapely
from shapely.geometry import Polygon

from tools.citymap.tests import common
from tools.citymap.tests.test_landmark_build import geometry


def _right(p, q):
    L = math.dist(p, q)
    return ((q[1] - p[1]) / L, -(q[0] - p[0]) / L)


class Hedges(unittest.TestCase):
    def test_hedges_closed(self):
        """A hedge is drawn whole (the review of the own looks: a chase camera, a tall cab or a car on a kerb looks
        down onto its 1.95 m top): four sides facing out and a top facing up at BOUNDARY_H + HEDGE_H."""
        from tools.citymap import buildings as bmod
        from tools.citymap import housedetail as H
        from tools.citymap import parts as P
        segs = [((x, 0.0), (x, 20.0)) for x in range(0, 400, 7)]
        res = H.Result()
        parts = H.hedges(segs, res)
        self.assertGreater(len(parts), 5)
        top_z = bmod.BOUNDARY_H + H.HEDGE_H
        for part in parts:
            self.assertEqual(len(part.tris), 10)
            tops = [t for t in part.tris if all(abs(v[2] - top_z) < 1e-9 for v in t)]
            self.assertEqual(len(tops), 2)
            for t in tops:
                self.assertGreater(P.normal(t)[2], 0.99)
            c = np.mean([v for t in part.tris for v in t], 0)
            for t in part.tris:
                if t in tops:
                    continue
                n = P.normal(t)
                m = np.mean(t, 0)
                self.assertGreater(n[0] * (m[0] - c[0]) + n[1] * (m[1] - c[1]), 0)  # facing out


class HouseWalls(unittest.TestCase):
    def test_one_quad_per_house_wall(self):
        """A wall of a house of 2-4 storeys is one quad (the facade block covers the parapet and four storeys); a
        6-storey wall is the block's 13.7 m on top and one quad per storey below it (2 more)."""
        from tools.citymap import tiles
        for storeys, want in ((2, 2), (3, 2), (4, 2), (6, 6)):
            h = storeys * 3.2
            tris, uvs = tiles.house_wall((0, 0), (10, 0), 0.0, h, 0, 3.0)
            self.assertEqual(len(tris), want, storeys)
            self.assertAlmostEqual(max(v[2] for t in tris for v in t), h + 0.9)
            self.assertAlmostEqual(min(v[2] for t in tris for v in t), 0.0)

    def test_facades_read_from_outside(self):
        """On every wall of a counter-clockwise footprint: the faces look out (right-hand normal), u grows to the
        right of a viewer facing the wall, v grows downwards (the texture's top row at the top), and the parapet's
        top is the facade block's first row."""
        from tools.citymap import parts as P
        from tools.citymap import textures as T
        from tools.citymap import tiles
        ring = [(0, 0), (12, 0), (12, 9), (0, 9)]
        for p, q in zip(ring, ring[1:] + ring[:1]):
            tris, uvs = tiles.house_wall(p, q, 0.0, 9.6, 1, 5.0)
            n_out = _right(p, q)
            for t, uv in zip(tris, uvs):
                nn = P.normal(t)
                self.assertGreater(nn[0] * n_out[0] + nn[1] * n_out[1], 0.99)
                # u along the viewer's right (= p -> q for an outward wall), v down
                for (a, ua), (b, ub) in ((x, y) for x in zip(t, uv) for y in zip(t, uv)):
                    along = (b[0] - a[0]) * (q[0] - p[0]) + (b[1] - a[1]) * (q[1] - p[1])
                    if abs(along) > 1e-6 and abs(b[2] - a[2]) < 1e-6:
                        self.assertGreater((ub[0] - ua[0]) * along, 0)
                    if abs(b[2] - a[2]) > 1e-6 and abs(along) < 1e-6:
                        self.assertLess((ub[1] - ua[1]) * (b[2] - a[2]), 0)
            top = [u for t, uv in zip(tris, uvs) for v, u in zip(t, uv) if abs(v[2] - 10.5) < 1e-6]
            self.assertTrue(all(abs(u[1] - T.facade_v(1, 0.0)) < 1e-9 for u in top))

    def test_tints_muted(self):
        """The house tints are muted colours (the user: an actual city, not grey boxes; the city fixes: not too yellow
        or bright): each wall vertex colour (62 x sun shade 0.80..1.05 x tint) within 14 of grey per channel, its
        luminance 40-78, at least eight tints, warm and cool both (the mean tint within 3% of grey)."""
        from tools.citymap import buildings
        T = buildings.HOUSE_TINTS
        self.assertGreaterEqual(len(T), 8)
        for tint in T:
            for sh in (0.80, 1.05):
                c = [62.0 * sh * k for k in tint]
                self.assertLessEqual(max(c) - min(c), 14.0, tint)
                lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
                self.assertTrue(40.0 <= lum <= 78.0, (tint, lum))
        m = np.mean(np.array(T), 0)
        print("\n  mean tint %s" % np.round(m, 3))
        self.assertLessEqual(float(np.abs(m - m.mean()).max()), 0.03 * float(m.mean()))


class Houses(unittest.TestCase):
    def test_counts(self):
        """Every ordinary building wears the house atlas; most houses carry a water tank, many a mumty, a good share a
        balcony on their road front; boundary walls carry hedges here and there."""
        _p, _m, _L, bl, city, _r = geometry()
        hd = city.extras.house_detail
        print("\n  %d blocks: %d mumties, %d tanks, %d balconies, %d hedges" % (
            len(bl.blocks), hd.mumties, hd.tanks, len(hd.balconies), hd.hedges))
        self.assertGreater(hd.tanks, 3000)
        self.assertGreater(hd.mumties, 1500)
        self.assertGreater(len(hd.balconies), 1000)
        self.assertGreater(hd.hedges, 300)

    def test_details_off_lanes(self):
        """No new detail (mumties, tanks, balconies, hedges) below 4.5 m over a carriageway or pavement; a balcony
        whose underside is lower than 4.5 m keeps its footprint 0.3 m clear of the carriageways and pavements (higher
        ones may hang over a ground lane, as in the sector lanes), none over a raised road at any height, and every
        balcony off every other building."""
        _p, _m, L, bl, city, _r = geometry()
        hd = city.extras.house_detail
        lanes = shapely.union_all([L.ground_polygon, L.elevated, city.pav])
        low = []
        for part in hd.parts:
            for t in part.tris:
                if min(v[2] for v in t) < 4.5:
                    low.append(((t[0][0] + t[1][0] + t[2][0]) / 3, (t[0][1] + t[1][1] + t[2][1]) / 3))
        if low:
            a = np.array(low)
            inside = int(shapely.contains_xy(lanes.buffer(-0.05), a[:, 0], a[:, 1]).sum())
        else:
            inside = 0
        clear = lanes.buffer(0.3)
        shapely.prepare(clear)
        on_lane = sum(1 for b in hd.balconies if b.underside < 4.5 and clear.intersects(b.polygon))
        raised = L.elevated.buffer(0.3)
        on_lane += sum(1 for b in hd.balconies if raised.intersects(b.polygon))
        over = sum(1 for b in hd.balconies if clear.intersects(b.polygon))
        print("\n  %d balconies hang over a ground lane from 4.5 m up" % over)
        tree = shapely.STRtree([b.footprint for b in bl.blocks])
        on_block = 0
        for b in hd.balconies:
            for k in tree.query(b.polygon):
                if bl.blocks[k].osm_id != b.osm_id and bl.blocks[k].footprint.intersection(b.polygon).area > 0.01:
                    on_block += 1
        print("\n  %d low detail triangles, %d over a lane; balconies on a lane %d, on another building %d" % (
            len(low), inside, on_lane, on_block))
        self.assertEqual((inside, on_lane, on_block), (0, 0, 0))

    def test_detail_uvs_in_cells(self):
        """Every triangle of the house atlas that reads the cell row keeps its three uvs inside one cell's inset (no
        neighbouring cell bleeds in, nothing reads the cells by wrapping)."""
        from tools.citymap import textures as T
        _p, _m, _L, _bl, city, _r = geometry()
        bad = n = 0
        for (inst, _lv, kind), (tris, uvs, _c) in ((k, v) for Tt in city.tiles.values() for k, v in Tt.groups.g.items()):
            if kind != "houses":
                continue
            for uv in uvs:
                vs = [x[1] for x in uv]
                if max(vs) < 960 / 1024 - 1e-9:
                    continue
                n += 1
                cells = {int(x[0] * 1024 // 64) for x in uv}
                ok = min(vs) >= 964 / 1024 - 1e-9 and max(vs) <= 1020 / 1024 + 1e-9 and len(cells) == 1
                k = cells.pop() if len(cells) == 1 else -1
                ok = ok and all(k * 64 + 4 - 1e-6 <= x[0] * 1024 <= k * 64 + 60 + 1e-6 for x in uv)
                bad += not ok
        print("\n  %d cell triangles, %d outside their cell" % (n, bad))
        self.assertGreater(n, 10000)
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main()
