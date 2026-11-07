"""Picks the game car whose body is closest in size to a new car's, to lend it its collision.

The collision (GlobalB.lzc Collisions) is copied under the new car's name by Binarius (`copy_collection`); a collision
far from the model's size hits in thin air or lets cars sink in. Sizes are the body's box in the model's own frame
(the union of <CAR>_KIT00_BODY_A and <CAR>_BASE_A, found by name hash: the Raptor's solids carry another car's names),
where the collision lives too. The closest car is the one with the smallest largest relative difference over length,
width and height. Only the game's own racers are candidates (the collisions racing cars are made with; the Chiron's
borrowed Ford GT collision works in the game).
"""
from chunks import bstringhash
from geometry import read_geometry

# the game's racers (pvehicle under `racers`), add-ons and the test entry left out
STOCK_RACERS = ("911TURBO", "997S", "A3", "A4", "BMWM3GTR", "BMWM3GTRE46", "CAMARO", "CARRERAGT", "CAYMANS", "CLIO",
                "CLK500", "COBALTSS", "CORVETTE", "CORVETTEC6R", "CTS", "DB9", "ECLIPSEGT", "ELISE", "FORDGT",
                "GALLARDO", "GTI", "GTO", "IMPREZAWRX", "IS300", "LANCEREVO8", "MONARO", "MURCIELAGO", "MUSTANGGT",
                "PUNTO", "RX7", "RX8", "SL500", "SL65", "SLR", "SUPRA", "TT", "VIPER")


def body_box(geometry_path, car):
    """(length, width, height) of the car's body and base at the highest detail."""
    with open(geometry_path, "rb") as f:
        pack = read_geometry(f.read())
    want = {bstringhash("%s_KIT00_BODY_A" % car), bstringhash("%s_BASE_A" % car)}
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for s in pack.solids:
        if s.name_hash not in want:
            continue
        for m in s.meshes():
            for p in s.positions(m):
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
    if lo[0] == float("inf"):
        raise ValueError("%s: no body in %s" % (car, geometry_path))
    return tuple(hi[k] - lo[k] for k in range(3))


def best(target, boxes):
    """(car, largest relative difference) of the box closest to target."""
    def worst(box):
        return max(abs(b - t) / t for b, t in zip(box, target))
    car = min(sorted(boxes), key=lambda c: worst(boxes[c]))
    return car, worst(boxes[car])
