"""Generiraj PNG inačice Prilika znaka iz iste geometrije kao favicon.svg.

Crtano nadmjerno (512 px) pa smanjeno LANCZOS-om radi oštrih rubova.
Apple ikona je namjerno puni kvadrat bez zaobljenih kutova — iOS sam
primjenjuje svoju masku, pa unaprijed zaobljeni kutovi ostave rupe.

Pokretanje:  python tools/build_favicons.py
Izlaz:       site/static/favicon-32.png, site/static/apple-touch-icon.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "static"

GREEN = (11, 107, 67, 255)      # --accent #0b6b43
WHITE = (255, 255, 255, 255)
S = 8                           # 64-koordinate iz SVG-a × 8 = 512 px platno


def draw_mark(rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (64 * S, 64 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, 64 * S, 64 * S], radius=14 * S, fill=GREEN)
    else:
        d.rectangle([0, 0, 64 * S, 64 * S], fill=GREEN)
    # dimnjak + kuća (unija bijelih oblika, kao <g> u SVG-u)
    d.rectangle([41 * S, 17 * S, 47 * S, 27 * S], fill=WHITE)
    d.polygon([(32 * S, 12 * S), (55 * S, 34 * S), (49.5 * S, 34 * S),
               (49.5 * S, 51 * S), (14.5 * S, 51 * S), (14.5 * S, 34 * S),
               (9 * S, 34 * S)], fill=WHITE)
    # vrata u negativnom prostoru
    d.rounded_rectangle([27 * S, 37 * S, 37 * S, 51 * S], radius=2 * S, fill=GREEN)
    return img


def main() -> int:
    mark = draw_mark(rounded=True)
    mark.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    apple = draw_mark(rounded=False)
    apple.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    for name in ("favicon-32.png", "apple-touch-icon.png"):
        print(f"zapisano: {OUT / name}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
