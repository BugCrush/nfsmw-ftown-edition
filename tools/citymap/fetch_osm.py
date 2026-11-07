"""Downloads OpenStreetMap data for an area (Overpass API).

    python tools/citymap/fetch_osm.py <south> <west> <north> <east> <out dir>          -> <out dir>/osm.json
    python tools/citymap/fetch_osm.py <south> <west> <north> <east> <out dir> areas    -> <out dir>/areas.json

osm.json: roads and buildings (ways, and building relations by their tags only). areas.json (stage 2's second
download): land use, leisure, natural and amenity areas (ways and relations) and the building relations with their
members' geometry (multipolygon buildings), for the ground's grass and earth and the buildings osm.json can't place.

F-Town's first area (Faridabad Sectors 15 and 16 and the Mathura Road stretch, 2026-11-02):
    python tools/citymap/fetch_osm.py 28.385 77.305 28.420 77.332 .superpowers/citymap/faridabad
    python tools/citymap/fetch_osm.py 28.385 77.305 28.420 77.332 .superpowers/citymap/faridabad areas
The data is OpenStreetMap's (ODbL: credit "(c) OpenStreetMap contributors"); it stays under .superpowers/ (git-ignored).
"""
import os
import sys
import urllib.parse
import urllib.request

UA = "nfsmwbe-research/1.0 (personal project)"


def query(box, what):
    if what == "areas":
        sel = "".join('%s["%s"](%s);' % (t, k, box) for k in ("landuse", "leisure", "natural", "amenity")
                      for t in ("way", "relation"))
        sel += 'relation["building"](%s);' % box
        return "[out:json][timeout:120];(%s);out body geom;" % sel
    return ('[out:json][timeout:90];(way["highway"](%s);way["building"](%s);relation["building"](%s););out tags geom;'
            % (box, box, box))


def main():
    s, w, n, e, out = sys.argv[1:6]
    what = sys.argv[6] if len(sys.argv) > 6 else "roads"
    box = "%s,%s,%s,%s" % (s, w, n, e)
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=urllib.parse.urlencode({"data": query(box, what)}).encode(),
                                 headers={"User-Agent": UA})
    os.makedirs(out, exist_ok=True)
    data = urllib.request.urlopen(req, timeout=240).read()
    name = "areas.json" if what == "areas" else "osm.json"
    open(os.path.join(out, name), "wb").write(data)
    print("%d bytes -> %s" % (len(data), os.path.join(out, name)))


if __name__ == "__main__":
    main()
