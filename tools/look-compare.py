"""Before/after sheets and numbers from split-screen screenshots (left half the game, right half ours).

    python tools/look-compare.py <folder> [--out <folder>] [--json]

For every .bmp/.png in the folder (name order) it writes compare-NN.png: the left half and the right half
side by side, each labelled, so the same part of the scene is NOT shown twice; what is shown is the two
treatments in the same frame. Numbers per half: mean brightness (0-255, Rec. 709 weights), share of
pixels at full white (all channels 255) and at black (all 0), mean saturation ((max-min)/max per pixel,
0 for black), mean colour. A 4-pixel strip at the split line is left out.
"""
import argparse
import glob
import json
import os

from PIL import Image, ImageDraw


def measure(image):
    pixels = list(image.getdata())
    n = len(pixels)
    brightness = sum(0.2125 * r + 0.7154 * g + 0.0721 * b for r, g, b in pixels) / n
    white = sum(1 for p in pixels if p == (255, 255, 255)) / n
    black = sum(1 for p in pixels if p == (0, 0, 0)) / n
    saturation = sum((max(p) - min(p)) / max(p) if max(p) else 0.0 for p in pixels) / n
    mean = [round(sum(p[i] for p in pixels) / n, 1) for i in range(3)]
    return {"brightness": round(brightness, 2), "white": round(white, 4), "black": round(black, 4),
            "saturation": round(saturation, 4), "colour": mean}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    out = args.out or args.folder
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in glob.glob(os.path.join(args.folder, "*")) if f.lower().endswith((".bmp", ".png"))
                   and not os.path.basename(f).startswith(("compare-", "sheet-")))
    rows = []
    for number, path in enumerate(files, 1):
        image = Image.open(path).convert("RGB")
        w, h = image.size
        game, ours = image.crop((0, 0, w // 2 - 2, h)), image.crop((w // 2 + 2, 0, w, h))
        # Numbers from every fourth pixel in each direction (nearest sampling keeps them real pixels): fast,
        # and shares of white and black stay counts of actual pixels.
        small = lambda im: im.resize((im.width // 4 or 1, im.height // 4 or 1), Image.NEAREST)
        row = {"file": os.path.basename(path), "game": measure(small(game) if w > 1000 else game),
               "ours": measure(small(ours) if w > 1000 else ours)}
        sheet = Image.new("RGB", (game.width + ours.width + 8, h + 24), (0, 0, 0))
        sheet.paste(game, (0, 24))
        sheet.paste(ours, (game.width + 8, 24))
        draw = ImageDraw.Draw(sheet)
        draw.text((6, 6), "game (left half of the screen)  %s" % row["file"], fill=(255, 255, 255))
        draw.text((game.width + 14, 6), "ours (right half of the screen)", fill=(255, 255, 255))
        row["sheet"] = os.path.join(out, "compare-%02d.png" % number)
        sheet.save(row["sheet"])
        rows.append(row)
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    print("%-24s %21s %21s" % ("", "game", "ours"))
    for row in rows:
        g, o = row["game"], row["ours"]
        print("%-24s bright %5.1f white %4.1f%% sat %.2f   bright %5.1f white %4.1f%% sat %.2f" % (
            row["file"], g["brightness"], g["white"] * 100, g["saturation"], o["brightness"], o["white"] * 100, o["saturation"]))
    print("sheets: %s" % os.path.join(out, "compare-*.png"))


main()
