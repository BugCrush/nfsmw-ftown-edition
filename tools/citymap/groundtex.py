"""F-Town's street ground, drawn here (Run I fixes, item 11, docs/ftown-notes.md "Run I fixes: the city side"): the
user found "the street ground looks very dead ... make it different from the road but still road in some cases".
Three tileable textures (numpy, seeded: the same pixels every run; no photo pixels: the photos in ftownphotos/ were
looked at for what north-Indian street ground is made of, nothing more):

- earth (512 px over 16 m): dry soil with grit and pebbles, darker damp patches and lighter dust, tufts of grass in a
  few places, two faint ruts;
- paver (256 px over 4 m): an interlocking paver forecourt (basket weave of 25 x 12.5 cm bricks, grey and dull red,
  dark joints, dirt in the joints, worn patches), in front of shops and hospitals;
- lot (256 px over 8 m): a worn concrete lot (2 m slabs, joints, cracks), asphalt repairs, oil stains, tyre marks.

Mean luminance of each within Rockport's ground range (dirt 62, grass 70, sidewalk 94.6: tools/citymap/
rockport_colours.py), chroma low (the vertex colour is the city's ground grey; along the roads the earth's vertex
colours turn dusty, tiles.DUST_RGB: the unpaved verges).
"""
import numpy as np

SIDES = {"earth": 512, "paver": 256, "lot": 256}
TILE_M = {"earth": (16.0, 16.0), "paver": (4.0, 4.0), "lot": (8.0, 8.0)}


def _noise(rng, n, scale):
    """Tileable noise, unit std: white noise low-passed in the frequency domain (periodic by construction), features
    about `scale` pixels across."""
    f = np.fft.fftfreq(n)
    k = np.hypot(f[:, None], f[None, :])
    spec = np.fft.fft2(rng.standard_normal((n, n))) * np.exp(-(k * scale) ** 2 * 2.0)
    out = np.real(np.fft.ifft2(spec))
    return (out - out.mean()) / (out.std() + 1e-9)


def _specks(rng, img, count, size, rgb, jitter=12.0):
    n = img.shape[0]
    for _ in range(count):
        x, y = rng.integers(0, n, 2)
        r = rng.integers(1, size + 1)
        c = np.array(rgb, float) + rng.uniform(-jitter, jitter)
        ys = (np.arange(y, y + r) % n)[:, None]
        xs = (np.arange(x, x + r) % n)[None, :]
        img[ys, xs] = c


def _ruts(n, rng, count, width, wobble):
    """Tyre tracks: pairs of wrapped wavy bands (whole periods of a sine across the tile), mask 0..1."""
    yy, xx = np.mgrid[0:n, 0:n]
    m = np.zeros((n, n))
    for _ in range(count):
        horiz = rng.random() < 0.5
        u, v = (xx, yy) if horiz else (yy, xx)
        k = int(rng.integers(1, 3))
        y0 = rng.uniform(0, n)
        phase = rng.uniform(0, 2 * np.pi)
        centre = y0 + wobble * np.sin(2 * np.pi * k * u / n + phase)
        for off in (-0.85, 0.85):  # two wheels 1.7 tile-units apart (scaled by the caller's width)
            d = (v - centre - off * width * 3) % n
            d = np.minimum(d, n - d)
            m = np.maximum(m, np.clip(1.0 - d / width, 0, 1))
    return m


def earth(seed=20261105):
    rng = np.random.default_rng(seed)
    n = SIDES["earth"]
    base = np.array([72.0, 65.0, 57.0])
    img = np.empty((n, n, 3))
    img[:] = base
    big, mid, fine = _noise(rng, n, 60), _noise(rng, n, 14), rng.standard_normal((n, n))
    shade = 7.0 * big + 4.0 * mid + 3.0 * fine
    img += shade[..., None]
    damp = np.clip(_noise(rng, n, 40) - 1.0, 0, None)  # darker damp patches
    img *= (1.0 - 0.16 * np.clip(damp, 0, 1))[..., None]
    dust = np.clip(_noise(rng, n, 35) - 0.9, 0, None)  # lighter dust
    img += (14.0 * np.clip(dust, 0, 1))[..., None] * np.array([1.0, 0.95, 0.85])
    grass = np.clip(_noise(rng, n, 30) - 1.25, 0, 1)  # a few places with tufts of grass
    tuft = (rng.random((n, n)) < 0.35 * grass) | (rng.random((n, n)) < 0.02 * (grass > 0))
    img[tuft] = img[tuft] * 0.55 + np.array([52.0, 70.0, 34.0]) * 0.45 + rng.uniform(-6, 6, (tuft.sum(), 1))
    rut = _ruts(n, rng, 1, 5.0, 30.0)
    img *= (1.0 - 0.10 * rut)[..., None]
    _specks(rng, img, 900, 2, (104, 96, 84))  # pebbles and grit
    _specks(rng, img, 700, 2, (46, 40, 34))
    return _out(img)


def paver(seed=20261107):
    """Basket weave: 32 px squares (0.5 m) of two bricks each, horizontal and vertical squares in a checkerboard."""
    rng = np.random.default_rng(seed)
    n = SIDES["paver"]
    yy, xx = np.mgrid[0:n, 0:n]
    sq = 32
    horiz = ((xx // sq) + (yy // sq)) % 2 == 0
    a = np.where(horiz, yy % sq, xx % sq)  # across the bricks
    b = np.where(horiz, xx % sq, yy % sq)  # along them
    joint = (a % 16 < 1) | (b < 1)
    brick_id = (xx // sq) * 7919 + (yy // sq) * 104729 + np.where(horiz, yy % sq // 16, xx % sq // 16)
    pick = (brick_id * 2654435761 % 97) / 97.0
    grey, red = np.array([98.0, 96.0, 92.0]), np.array([112.0, 74.0, 62.0])
    img = np.where((pick < 0.3)[..., None], red, grey) + ((pick - 0.5) * 14)[..., None]
    img = img + (3.0 * rng.standard_normal((n, n)))[..., None]
    img[joint] = (48.0, 46.0, 42.0)
    worn = np.clip(_noise(rng, n, 24) - 0.8, 0, 1)
    img = img * (1.0 - 0.18 * worn)[..., None] + (worn * 8.0)[..., None]
    return _out(img)


def lot(seed=20261108):
    rng = np.random.default_rng(seed)
    n = SIDES["lot"]
    yy, xx = np.mgrid[0:n, 0:n]
    img = np.empty((n, n, 3))
    img[:] = (90.0, 89.0, 85.0)
    img += (5.0 * _noise(rng, n, 25) + 3.0 * rng.standard_normal((n, n)))[..., None]
    joint = (xx % 64 < 1) | (yy % 64 < 1)  # 2 m slabs
    img[joint] *= 0.62
    patch = _noise(rng, n, 30) > 1.7  # asphalt repairs
    img[patch] = np.array([52.0, 52.0, 54.0]) + rng.uniform(-4, 4, (patch.sum(), 1))
    oil = np.clip(_noise(rng, n, 10) - 2.0, 0, 1)
    img *= (1.0 - 0.35 * oil)[..., None]
    tracks = _ruts(n, rng, 2, 4.0, 18.0)
    img *= (1.0 - 0.12 * tracks)[..., None]
    crack = np.abs(_noise(rng, n, 18)) < 0.025
    img[crack] *= 0.7
    return _out(img)


def _out(img):
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def draw():
    """{kind: (side, [(r, g, b)] row by row)} as textures.draw() takes them."""
    out = {}
    for kind, f in (("earth", earth), ("paver", paver), ("lot", lot)):
        a = f()
        out[kind] = (a.shape[0], [tuple(p) for p in a.reshape(-1, 3).tolist()])
    return out
