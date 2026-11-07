"""What differs between two car stable images (CarStable.defaults.bin, 0x8CC8 bytes; layout in docs/cars-notes.md).

    python tools/cars/stable-diff.py <first.bin> <second.bin>

Cars are matched by VehicleKey and list bits' car (the first record of each VehicleKey). Prints one line per
difference: cars only in one image, changed FEKey / filter bits, customisation bytes that differ, slot order.
"""
import struct
import sys

CUSTOM_OFS, CUSTOM_SIZE = 0xFA0, 0x198


def cars(img):
    out = []
    for slot in range(200):
        handle, fe, vkey, bits, custom, career = struct.unpack_from("<IIIIBB", img, slot * 0x14)
        if handle != 0xFFFFFFFF:
            out.append({"slot": slot, "fe": fe, "vkey": vkey, "bits": bits, "custom": custom})
    return out


def custom_bytes(img, c):
    if c >= 75:
        return None
    return img[CUSTOM_OFS + c * CUSTOM_SIZE:CUSTOM_OFS + c * CUSTOM_SIZE + 0x194]


def differences(a, b):
    ca, cb = cars(a), cars(b)
    first_a, first_b = {}, {}
    for c in ca:
        first_a.setdefault(c["vkey"], c)
    for c in cb:
        first_b.setdefault(c["vkey"], c)
    diffs = []
    for k, c in first_a.items():
        if k not in first_b:
            diffs.append("car 0x%08X: only in first (slot %d)" % (k, c["slot"]))
    for k, c in first_b.items():
        if k not in first_a:
            diffs.append("car 0x%08X: only in second (slot %d)" % (k, c["slot"]))
    for k in first_a:
        if k not in first_b:
            continue
        x, y = first_a[k], first_b[k]
        if x["fe"] != y["fe"]:
            diffs.append("car 0x%08X: FEKey 0x%08X -> 0x%08X" % (k, x["fe"], y["fe"]))
        if x["bits"] != y["bits"]:
            diffs.append("car 0x%08X: filter bits 0x%08X -> 0x%08X" % (k, x["bits"], y["bits"]))
        bx, by = custom_bytes(a, x["custom"]), custom_bytes(b, y["custom"])
        if (bx is None) != (by is None):
            diffs.append("car 0x%08X: customisation only in %s" % (k, "first" if by is None else "second"))
        elif bx is not None and bx != by:
            at = [i for i in range(len(bx)) if bx[i] != by[i]]
            diffs.append("car 0x%08X: customisation differs at +0x%X (%d bytes)" % (k, at[0], len(at)))
    order_a = [c["vkey"] for c in ca]
    order_b = [c["vkey"] for c in cb]
    if order_a != order_b and set(order_a) == set(order_b):
        first = next(i for i in range(min(len(order_a), len(order_b))) if order_a[i] != order_b[i])
        diffs.append("order of cars differs (first at slot %d)" % first)
    tail_a, tail_b = a[0x8CA0:], b[0x8CA0:]
    if tail_a != tail_b:
        diffs.append("sold-history fields differ")
    return diffs


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    a, b = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
    diffs = differences(a, b)
    print("\n".join(diffs) if diffs else "no differences")
    print("%d cars in first, %d in second" % (len(cars(a)), len(cars(b))))


if __name__ == "__main__":
    main()
