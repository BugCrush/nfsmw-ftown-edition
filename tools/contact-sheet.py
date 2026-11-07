"""Tiles a folder of images into labelled sheets, so a whole race can be looked at as a few images.

    python tools/contact-sheet.py <folder> [--out <folder>] [--cols 4] [--rows 3] [--width 1920]

Every .bmp/.png in the folder, in name order, becomes a tile with its file name above it. Sheets are
written as sheet-01.png, sheet-02.png, ... into --out (default: the folder itself); their paths are
printed. A sheet is only as tall as the rows it uses.
"""
import argparse
import glob
import os

from PIL import Image, ImageDraw

LABEL = 24


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--out")
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--width", type=int, default=1920)
    args = parser.parse_args()
    out = args.out or args.folder
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in glob.glob(os.path.join(args.folder, "*")) if f.lower().endswith((".bmp", ".png"))
                   and not os.path.basename(f).startswith("sheet-"))
    per_sheet = args.cols * args.rows
    tile_w = args.width // args.cols
    for number, first in enumerate(range(0, len(files), per_sheet), 1):
        batch = files[first:first + per_sheet]
        images = [Image.open(f).convert("RGB") for f in batch]
        tile_h = max(round(tile_w * im.height / im.width) for im in images)
        rows = (len(batch) + args.cols - 1) // args.cols
        sheet = Image.new("RGB", (args.width, rows * (tile_h + LABEL)), (0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        for i, (path, im) in enumerate(zip(batch, images)):
            x, y = (i % args.cols) * tile_w, (i // args.cols) * (tile_h + LABEL)
            h = round(tile_w * im.height / im.width)
            sheet.paste(im.resize((tile_w, h), Image.LANCZOS), (x, y + LABEL))
            draw.text((x + 4, y + 6), os.path.splitext(os.path.basename(path))[0], fill=(255, 255, 255))
        target = os.path.join(out, "sheet-%02d.png" % number)
        sheet.save(target)
        print(target)


main()
