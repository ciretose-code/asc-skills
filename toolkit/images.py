#!/usr/bin/env python3
"""Check and fix App Store images locally, before App Store Connect rejects them
with a misleading message.

    images.py check  <files or folders...>              # size, mode, which family it fits
    images.py flatten <files or folders...>             # RGBA -> RGB in place (onto --bg)
    images.py fit --family ipad13 <src> <dst-dir>       # scale + pad onto a canvas
    images.py fit --size 2064x2752 <src> <dst-dir>

`check` exits non-zero if any file has an alpha channel or matches no known
canvas, so it can gate an upload.

`flatten` exists because `xcrun simctl io screenshot` and SwiftUI's
`ImageRenderer` both write RGBA, and App Store Connect refuses an alpha channel
while complaining about the *size*. Captures are fully opaque, so flattening
changes nothing visible.

`fit` is the stopgap for a canvas mismatch — e.g. an iPad set exported at 12.9"
(2048x2732) when 13" (2064x2752) is required. It scales to fit and pads with
--bg rather than stretching, so geometry stays exact. A re-export from the
design file is better when the aspect ratio differs by more than a hair.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("needs Pillow:  python3 -m pip install pillow")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_screenshots import FAMILIES, IMAGE_SUFFIXES  # noqa: E402


def expand(paths) -> list:
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in IMAGE_SUFFIXES)
        elif p.exists():
            out.append(p)
        else:
            sys.exit(f"no such file: {p}")
    return out


def has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


def families_for(size) -> list:
    w, h = size
    return [n for n, f in FAMILIES.items() if (w, h) in f[2] or (h, w) in f[2]]


def parse_bg(text: str):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def flat(im, bg):
    rgba = im.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, bg)
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


def save(im, path: Path) -> None:
    if path.suffix.lower() in (".jpg", ".jpeg"):
        im.save(path, "JPEG", quality=95)
    else:
        im.save(path, "PNG", optimize=True)


def cmd_check(args) -> int:
    bad = 0
    for f in expand(args.paths):
        with Image.open(f) as im:
            fam = families_for(im.size)
            alpha = has_alpha(im)
            flags = []
            if alpha:
                flags.append("ALPHA (flatten it)")
            if not fam:
                flags.append("no known canvas")
            bad += bool(flags)
            print(f"  {'!!' if flags else 'ok'}  {f}  {im.size[0]}x{im.size[1]} {im.mode}  "
                  f"{','.join(fam) or '-'}  {' '.join(flags)}")
    return 1 if bad else 0


def cmd_flatten(args) -> int:
    bg = parse_bg(args.bg)
    for f in expand(args.paths):
        with Image.open(f) as im:
            if not has_alpha(im):
                print(f"  ok       {f}")
                continue
            out = flat(im, bg)
        save(out, f)
        print(f"  flattened {f}")
    return 0


def cmd_fit(args) -> int:
    if args.family:
        w, h = FAMILIES[args.family][2][0]
    else:
        w, h = (int(x) for x in args.size.lower().split("x"))
    bg = parse_bg(args.bg)
    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f in expand([args.src]):
        with Image.open(f) as im:
            src = flat(im, bg) if has_alpha(im) else im.convert("RGB")
        tw, th = (w, h) if (src.width <= src.height) == (w <= h) else (h, w)  # keep orientation
        scale = min(tw / src.width, th / src.height)
        resized = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
        canvas = Image.new("RGB", (tw, th), bg)
        canvas.paste(resized, ((tw - resized.width) // 2, (th - resized.height) // 2))
        out = dst / f.name
        save(canvas, out)
        print(f"  {f.name}: {src.width}x{src.height} -> {tw}x{th}  ({out})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("paths", nargs="+")
    fl = sub.add_parser("flatten")
    fl.add_argument("paths", nargs="+")
    fl.add_argument("--bg", default="FFFFFF", help="hex background for transparent pixels")
    ft = sub.add_parser("fit")
    g = ft.add_mutually_exclusive_group(required=True)
    g.add_argument("--family", choices=sorted(FAMILIES))
    g.add_argument("--size", help="WxH")
    ft.add_argument("--bg", default="FFFFFF", help="hex padding colour")
    ft.add_argument("src")
    ft.add_argument("dst")
    args = parser.parse_args()
    sys.exit({"check": cmd_check, "flatten": cmd_flatten, "fit": cmd_fit}[args.cmd](args))


if __name__ == "__main__":
    main()
