"""The projection from OpenStreetMap's latitude and longitude to F-Town's render coordinates (metres).

A local equirectangular projection about the area's centre (28.4025 N, 77.3185 E) on a sphere of the mean Earth radius
(6,371,008.8 m): x = east, y = north, the centre at the place outside Rockport: render (2000, 11500) (notes Task 6) moved by
SHIFT, since the connection to Rockport (docs/ftown-connection-research.md "The connection: decisions") 2,432 m south
(19 tiles of 128 m, so every tile cuts as before) to render (2000, 9068), where a 2.6 km road from Rockport's north
highway reaches its Mathura Road. Coordinates written into the builders before the move (viewpoints, waypoints, the
terrain anchor) are in the old frame and pass through moved().
North is render +y and east render +x (true north kept for a later minimap). Over the area (3.9 x 2.6 km) the distances
it gives are within 0.02% of the great-circle (haversine) distance on the same sphere (test_roadmodel); the sphere
itself is about 0.2-0.35% larger than the WGS84 ellipsoid's local radii at this latitude (about 10 m over the 3.9 km
of the area), the same for every road, so shapes and junctions are unaffected.
"""
import math

R = 6371008.8
LAT0, LON0 = 28.4025, 77.3185
PLACE_BEFORE = (2000.0, 11500.0)  # the centre until 2026-11-06
SHIFT = (0.0, -2432.0)  # render metres F-Town moved for the connection (a multiple of the 128 m tile)
ORIGIN = (PLACE_BEFORE[0] + SHIFT[0], PLACE_BEFORE[1] + SHIFT[1])


def moved(x, y):
    """A render point written in the frame before the move (F-Town centred on (2000, 11500)), where it is now."""
    return (x + SHIFT[0], y + SHIFT[1])


class Projection:
    def __init__(self, lat0=LAT0, lon0=LON0, origin=ORIGIN):
        self.lat0, self.lon0, self.origin = lat0, lon0, origin
        self.ky = R * math.pi / 180.0
        self.kx = self.ky * math.cos(math.radians(lat0))

    def to_render(self, lat, lon):
        return (self.origin[0] + (lon - self.lon0) * self.kx, self.origin[1] + (lat - self.lat0) * self.ky)

    def to_latlon(self, x, y):
        return (self.lat0 + (y - self.origin[1]) / self.ky, self.lon0 + (x - self.origin[0]) / self.kx)
