"""Generiraj og-image (1200×630) za dijeljenje na društvenim mrežama.

Ista geometrija znaka kao favicon.svg / build_favicons.py, uz wordmark.
Fontovi se traže među sistemskima (Segoe UI pa Arial) — slika se gradi
lokalno na Windowsu, pa je to pouzdano.

Pokretanje:  python tools/build_og_image.py
Izlaz:       site/static/og-image.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "static" / "og-image.png"

GREEN = (11, 107, 67, 255)
MIST = (237, 243, 239, 255)
WHITE = (255, 255, 255, 255)
AMBER = (180, 83, 9, 255)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    names = (["segoeuib.ttf", "arialbd.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def main() -> int:
    img = Image.new("RGBA", (1200, 630), GREEN)
    d = ImageDraw.Draw(img)

    # znak: kuća s dimnjakom na svjetlijoj pločici (geometrija 64-koordinata × s)
    s, ox, oy = 4.4, 140, 150
    d.rounded_rectangle([ox, oy, ox + 64 * s, oy + 64 * s],
                        radius=14 * s, fill=MIST)
    d.rectangle([ox + 41 * s, oy + 17 * s, ox + 47 * s, oy + 27 * s], fill=GREEN)
    d.polygon([(ox + 32 * s, oy + 12 * s), (ox + 55 * s, oy + 34 * s),
               (ox + 49.5 * s, oy + 34 * s), (ox + 49.5 * s, oy + 51 * s),
               (ox + 14.5 * s, oy + 51 * s), (ox + 14.5 * s, oy + 34 * s),
               (ox + 9 * s, oy + 34 * s)], fill=GREEN)
    d.rounded_rectangle([ox + 27 * s, oy + 37 * s, ox + 37 * s, oy + 51 * s],
                        radius=2 * s, fill=MIST)

    # wordmark + slogan
    d.text((480, 205), "Prilika", font=_font(120), fill=WHITE)
    d.text((484, 360), "nekretnine na dražbi u Hrvatskoj",
           font=_font(44, bold=False), fill=MIST)
    d.text((484, 425), "službeni podaci · bez osobnih podataka · svaki dan",
           font=_font(30, bold=False), fill=(143, 191, 171, 255))

    # naglasna crta
    d.rounded_rectangle([484, 330, 900, 340], radius=5, fill=AMBER)

    img.convert("RGB").save(OUT, "PNG")
    print(f"zapisano: {OUT}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
