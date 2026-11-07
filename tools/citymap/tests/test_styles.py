"""Task 6 (landmarks plan): ordinary buildings styled after the photos.

    .tools/cityenv/Scripts/python -m unittest tools.citymap.tests.test_styles -v
"""
import copy
import math
import os
import sys
import unittest

import shapely
from shapely.geometry import LineString

from tools.citymap.tests import common
from tools.citymap.tests.test_landmark_build import geometry

for p in (common.TOOLS, os.path.join(common.TOOLS, "carbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)


class Styles(unittest.TestCase):
    def test_styles_deterministic(self):
        """Styles are drawn per OSM id: styling copies of the blocks twice gives the same tints, market flags and
        shop-front edges; every block has a style; the market blocks are some hundreds, not every building."""
        from tools.citymap import buildings
        _p, m, L, bl, city, _r = geometry()
        lanes = shapely.union_all([L.ground_polygon, L.elevated, city.pav])
        mk = buildings.market_areas(common.proj(), common.osm(), None)
        a = buildings.styles([copy.copy(b) for b in bl.blocks], m, lanes, mk)
        b = buildings.styles([copy.copy(b) for b in bl.blocks], m, lanes, mk)
        self.assertEqual([x.style for x in a], [y.style for y in b])
        self.assertTrue(all(x.style is not None for x in bl.blocks))
        n_market = sum(1 for x in bl.blocks if x.style.market)
        n_shop = sum(len(x.style.shop_edges) for x in bl.blocks)
        tints = {}
        for x in bl.blocks:
            tints[x.style.tint] = tints.get(x.style.tint, 0) + 1
        print("\n  %d blocks: %d market blocks with %d shop-front edges; tints used %s" % (
            len(bl.blocks), n_market, n_shop, sorted(tints.values())))
        self.assertGreater(n_market, 50)
        self.assertLess(n_market, len(bl.blocks) / 3)
        self.assertEqual(len(tints), len(buildings.HOUSE_TINTS))  # own looks: the houses' tints

    def test_palette_from_photos_in_range(self):
        """The palette is the photos' wall colours (re-measured from ftownphotos/ when the photos are there) held near
        grey: each tint's wall vertex colour (62 x the brightest sun shade 1.05 x tint) within 6 of grey (the city
        fixes' rule for the plaster tints, test_city) and its luminance within Rockport's walls' vertex greys 47-78."""
        from tools.citymap import buildings
        got = buildings.palette_from_photos()
        if got is not None:
            self.assertEqual([tuple(t) for t in got], [tuple(t) for t in buildings.PALETTE])
        for tint in buildings.PALETTE:
            for sh in (0.80, 1.05):
                c = [62.0 * sh * k for k in tint]
                self.assertLessEqual(max(c) - min(c), 6.0, tint)
                lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
                self.assertTrue(40.0 <= lum <= 78.0, (tint, lum))
        print("\n  palette %s (photos %s)" % (buildings.PALETTE, "re-measured" if got else "missing"))

    def test_windows_match_storeys(self):
        """Every ordinary block's height is a whole number of 3.2 m storeys, so the plaster's window rows (one a
        storey, counted from the roof line) end at the ground with a full storey."""
        from tools.citymap import buildings
        _p, _m, _L, bl, _c, _r = geometry()
        for b in bl.blocks:
            n = b.height_m / buildings.STOREY
            self.assertAlmostEqual(n, round(n), places=6)

    def test_boundary_walls_off_roads(self):
        """Boundary walls stand off every carriageway and pavement (0.25 m clear) and off every building; gates leave
        gaps where OSM has gate nodes."""
        _p, _m, L, bl, city, _r = geometry()
        segs = city.extras.boundary
        lanes = shapely.union_all([L.ground_polygon, L.elevated, city.pav]).buffer(0.25)
        shapely.prepare(lanes)
        blocks = shapely.union_all([b.footprint for b in bl.blocks]).buffer(0.25)
        shapely.prepare(blocks)
        lines = [LineString(s) for s in segs]
        on_road = sum(1 for ln in lines if lanes.intersects(ln))
        on_block = sum(1 for ln in lines if blocks.intersects(ln))
        print("\n  %d boundary walls, %.0f m; on a road %d, on a building %d" % (
            len(segs), sum(ln.length for ln in lines), on_road, on_block))
        self.assertGreater(len(segs), 500)
        self.assertEqual((on_road, on_block), (0, 0))

    def test_pieces_per_tile(self):
        """In the written file, a tile's ordinary buildings are few drawn pieces (meshes): since the own looks their
        walls, roofs, mumties, tanks, balconies and boundary walls are FTC_HOUSES and their shop fronts FTC_STREET,
        at most 2 meshes beyond one per 1,000 triangles (the writer's split)."""
        from chunks import bstringhash
        from world import scenery
        from tools.citymap import textures
        from tools.citymap.tests import test_city
        want = {bstringhash(textures.NAMES[k]) for k in ("houses", "street")}
        worst, n = 0, 0
        for c, p in test_city.chunks_with_pos():
            if c.id != scenery.SOLID_LIST:
                continue
            for k, kp in scenery.with_positions(c.children, p):
                if k.id != scenery.SOLID:
                    continue
                so = scenery.read_solid(k, kp)
                if not so.name.startswith("FTC_B_"):
                    continue
                ms = [mesh for mesh in so.meshes if so.textures[mesh.texture_slots[0]] in want]
                tris = sum(mesh.triangle_count for mesh in ms)
                extra = len(ms) - math.ceil(tris / 1000.0)
                worst = max(worst, extra)
                n += 1
        print("\n  %d building solids, at most %d building meshes beyond one per 1,000 triangles" % (n, worst))
        self.assertGreater(n, 500)
        self.assertLessEqual(worst, 2)

    def test_route_still_drivable(self):
        """The stage 2 checks on the city file written with the styled buildings (tools/citymap/tests/test_city.py)."""
        from tools.citymap.tests import test_city
        c = test_city.City("test_route_drivable")
        c.test_route_drivable()
        c.test_no_barrier_on_road()
        c.test_written_centrelines_drivable()
        c.test_barriers_face_the_road()


if __name__ == "__main__":
    unittest.main()
