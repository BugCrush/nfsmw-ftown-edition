"""Known answers found on 2026-10-15 in our GLOBAL\\attributes.bin (names Attribulator holds only as hashes)."""
from vlthash import vlt32


def test_curve_fields():
    assert vlt32("BlackBloomCurve") == 0xAAACCDF3
    assert vlt32("ColourBloomCurve") == 0x1D521C97
    assert vlt32("DetailMapCurve") == 0x51376819


def test_collections():
    assert vlt32("no_vt_overcast") == 0x94ABDFF0
    assert vlt32("no_vt_dusk_overcast") == 0x919B6689
    assert vlt32("brakelight_traffic_inner") == 0xD364E8AC


def test_frontend_fields():
    # the Unlimiter's rims prices (found 2026-10-31 in fe_attrib.bin's frontend class as 0x1002EA65)
    assert vlt32("feCarPartInfo") == 0x1002EA65
