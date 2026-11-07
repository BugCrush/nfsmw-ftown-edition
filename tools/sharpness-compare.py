"""Compare the sharpness of GfxProbe screenshots taken before and after a graphics change.

    python tools/sharpness-compare.py <before-label> <after-label>      e.g.  baseline af16
    python tools/sharpness-compare.py <label>                           measure one set on its own

Screenshots are in gfx-captures/<label>/ (GfxProbe saves three per race, on the grid at race start).
Each "after" image is paired with the most similar "before" image; pairs that don't show the same view
(similarity under 0.90) are reported and skipped, so different spots are never compared.

Sharpness is measured per horizontal band of the frame, because texture filtering acts on surfaces seen
at a shallow angle: the road stretching away, roughly the middle bands of a chase-camera view.
  detail = variance of the Laplacian of the brightness (how much fine detail/edges there are);
           higher = sharper. Reported per band, with after/before as a ratio.
A side-by-side crop of the road band is saved next to the captures for looking at.
"""
import os
import sys

from PIL import Image, ImageFilter, ImageStat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, 'gfx-captures')
BANDS = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80)]
ROAD_BAND = (0.45, 0.70)   # saved as the side-by-side crop
LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


def images(label):
    folder = os.path.join(CAPTURES, label)
    if not os.path.isdir(folder):
        sys.exit(f'No captures in {folder}')
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.bmp', '.png')))
    if not files:
        sys.exit(f'No captures in {folder}')
    return [(f, Image.open(os.path.join(folder, f)).convert('RGB')) for f in files]


def similarity(a, b):
    """Correlation of two views after shrinking to 64x36 greyscale: 1.0 = the same scene."""
    sa, sb = (im.convert('L').resize((64, 36), Image.BILINEAR) for im in (a, b))
    xa, xb = list(sa.getdata()), list(sb.getdata())
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    cov = sum((p - ma) * (q - mb) for p, q in zip(xa, xb))
    var = (sum((p - ma) ** 2 for p in xa) * sum((q - mb) ** 2 for q in xb)) ** 0.5
    return cov / var if var else 0.0


def detail(im, band, x_range=(0.15, 0.85)):
    """Variance of the Laplacian within a band (fractions of height) and the middle of the width."""
    w, h = im.size
    box = (int(w * x_range[0]), int(h * band[0]), int(w * x_range[1]), int(h * band[1]))
    lap = im.convert('L').crop(box).filter(LAPLACIAN)
    # Drop the 1-pixel border, where the kernel sees outside the crop.
    lap = lap.crop((1, 1, lap.size[0] - 1, lap.size[1] - 1))
    return ImageStat.Stat(lap).var[0]


def describe(name, im):
    cells = ' | '.join(f'{detail(im, b):8.1f}' for b in BANDS)
    print(f'  {name:<28} | {cells}')


def main():
    args = sys.argv[1:]
    if not args or len(args) > 2:
        sys.exit(__doc__)
    header = ' | '.join(f'{int(lo * 100)}-{int(hi * 100)}%'.center(8) for lo, hi in BANDS)
    before = images(args[0])
    if len(args) == 1:
        print(f'Detail (variance of Laplacian) by band of frame height, top to bottom: {args[0]}')
        print(f'  {"image":<28} | {header}')
        for name, im in before:
            describe(name, im)
        return

    after = images(args[1])
    print(f'Before: {args[0]} ({len(before)} images)   After: {args[1]} ({len(after)} images)')
    ratios = {b: [] for b in BANDS}
    pair_no = 0
    for name_b, im_b in after:
        name_a, im_a = max(before, key=lambda it: similarity(it[1], im_b))
        sim = similarity(im_a, im_b)
        if sim < 0.90 or im_a.size != im_b.size:
            print(f'\n{name_b}: no matching view in {args[0]} (best {name_a}, similarity {sim:.2f}); skipped')
            continue
        pair_no += 1
        print(f'\nPair {pair_no}: {name_a}  vs  {name_b}   (same view: similarity {sim:.3f})')
        print(f'  {"":<28} | {header}')
        describe('before', im_a)
        describe('after', im_b)
        cells = []
        for b in BANDS:
            da, db = detail(im_a, b), detail(im_b, b)
            r = db / da if da else float('nan')
            ratios[b].append(r)
            cells.append(f'{r:7.2f}x')
        print(f'  {"after / before":<28} | ' + ' | '.join(cells))

        w, h = im_a.size
        box = (int(w * 0.15), int(h * ROAD_BAND[0]), int(w * 0.85), int(h * ROAD_BAND[1]))
        ca, cb = im_a.crop(box), im_b.crop(box)
        sheet = Image.new('RGB', (ca.size[0], ca.size[1] * 2 + 6), (255, 0, 255))
        sheet.paste(ca, (0, 0))
        sheet.paste(cb, (0, ca.size[1] + 6))
        out = os.path.join(CAPTURES, f'compare-{args[0]}-vs-{args[1]}-{pair_no}.png')
        sheet.save(out)
        print(f'  road band saved (before on top, after below): {out}')

    if pair_no:
        print('\nMedian after/before detail ratio per band (1.00 = no change, above 1 = sharper):')
        print('  ' + ' | '.join(f'{int(lo * 100)}-{int(hi * 100)}%: {sorted(v)[len(v) // 2]:.2f}x' for (lo, hi), v in ratios.items()))
    else:
        print('\nNo pair showed the same view. Take both sets at the start of the same race.')


if __name__ == '__main__':
    main()
