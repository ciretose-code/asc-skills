#!/usr/bin/env python3
"""Composite marketing captions onto raw screenshots, inside the same canvas.

  compose_captions.py <raw-dir> <out-dir> --captions captions.json
      [--field 68765B] [--ink F0F0E7] [--font /System/Library/Fonts/SFCompactRounded.ttf]
      [--weight Bold]

App Store screenshot canvases are fixed sizes, so a caption can't be added above
the frame — it has to live *inside* the canvas. Each screenshot is scaled down
onto a flat field colour with the caption set above it, rounded corners and a
soft shadow so it reads as a device. Output keeps the input's pixel size, so a
6.9" capture comes out a valid 6.9" upload (RGB, no alpha).

captions.json maps file stems to captions; a stem with no caption is skipped:

    {"01-reveal": "Where in the world are you?", "02-hero": "Drag. Clear. Uncover."}

Pick the field colour from the app itself (a primary/brand colour), not its
background: a field within a few values of the app's own background makes the
frame dissolve into it.
"""
import argparse
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def hex_rgb(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def wrap(draw, text, font, max_width):
    """Greedy wrap, then rebalance a two-line result.

    Greedy alone orphans the tail ("Three ways to play. One place / a day."),
    which looks like a mistake at this size. When the caption needs exactly two
    lines, pick the split that makes them most even instead.
    """
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    if len(lines) == 2 and len(words) > 2:
        best, best_delta = None, None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            wa, wb = draw.textlength(a, font=font), draw.textlength(b, font=font)
            if max(wa, wb) > max_width:
                continue
            delta = abs(wa - wb)
            if best_delta is None or delta < best_delta:
                best, best_delta = [a, b], delta
        if best:
            lines = best
    return lines


def compose(src: Path, dst: Path, caption: str, opts):
    shot = Image.open(src).convert("RGB")
    W, H = shot.size
    canvas = Image.new("RGB", (W, H), opts.field)
    draw = ImageDraw.Draw(canvas)

    # Proportional so both the tall phone canvas and the squarer iPad canvas
    # get the same visual rhythm.
    side = int(W * 0.085)
    top = int(H * 0.052)
    gap = int(H * 0.024)
    bottom = int(H * 0.038)

    text_side = int(W * 0.055)
    font_size = int(W * 0.066)
    font = ImageFont.truetype(opts.font, font_size)
    # Variable system fonts ship weights as named variations.
    try:
        font.set_variation_by_name(opts.weight)
    except Exception:
        pass

    lines = wrap(draw, caption, font, W - 2 * text_side)
    line_h = int(font_size * 1.22)
    cap_h = line_h * len(lines)

    # Scale the shot into whatever vertical room is left.
    avail_h = H - top - cap_h - gap - bottom
    avail_w = W - 2 * side
    scale = min(avail_w / W, avail_h / H)
    sw, sh = int(W * scale), int(H * scale)
    small = shot.resize((sw, sh), Image.LANCZOS)

    # Rounded corners + a soft drop shadow so the frame reads as a device.
    radius = int(sw * 0.055)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=radius, fill=255)

    x = (W - sw) // 2
    y = top + cap_h + gap

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x, y + int(sh * 0.010), x + sw, y + sh + int(sh * 0.010)],
        radius=radius, fill=(0, 0, 0, 95))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(W * 0.018)))
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB"), (0, 0))

    canvas.paste(small, (x, y), mask)

    # Caption last so it sits cleanly over the flat field.
    draw = ImageDraw.Draw(canvas)
    ty = top
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((W - tw) / 2, ty), line, font=font, fill=opts.ink)
        ty += line_h

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG")
    return canvas.size


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("raw", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--captions", type=Path, required=True)
    parser.add_argument("--field", type=hex_rgb, default=hex_rgb("68765B"))
    parser.add_argument("--ink", type=hex_rgb, default=hex_rgb("F0F0E7"))
    parser.add_argument("--font", default="/System/Library/Fonts/SFCompactRounded.ttf")
    parser.add_argument("--weight", default="Bold")
    opts = parser.parse_args()
    captions = json.loads(opts.captions.read_text())
    for stem, caption in sorted(captions.items()):
        src = next((opts.raw / f"{stem}{ext}" for ext in (".png", ".jpg", ".jpeg")
                    if (opts.raw / f"{stem}{ext}").exists()), None)
        if src is None:
            print(f"  !! missing {opts.raw / stem}.png")
            continue
        size = compose(src, opts.out / f"{stem}.png", caption, opts)
        print(f"  {stem}.png  {size[0]}x{size[1]}  \u201c{caption}\u201d")


if __name__ == "__main__":
    main()
