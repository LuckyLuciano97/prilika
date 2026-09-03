"""Preuzmi fotografije s Wikimedia Commonsa i zapiši njihove licence.

Atribucija se NE upisuje rukom: autor, licenca i poveznica na izvornu
stranicu čitaju se iz Commons API-ja i spremaju u data/foto_izvori.json,
koji se commita. Stranica zatim ispod svake fotografije ispisuje upravo te
podatke — pa kredit ne može odlutati od onoga što izvor tvrdi.

Koriste se samo slobodne licence (CC BY / CC BY-SA / javno vlasništvo);
sve ostalo se odbija i ispisuje razlog.

Pokretanje:  python tools/fetch_photos.py
Izlaz:       site/static/photos/*.jpg + data/foto_izvori.json
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "site" / "static" / "photos"
MANIFEST = ROOT / "data" / "foto_izvori.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = "PrilikaBot/1.0 (+https://prilika.net; kontakt: support@nexistudio.dev)"

# Licence koje dopuštaju ponovnu uporabu uz navođenje izvora.
OK_LICENCE = re.compile(r"^(cc[ -]by([ -]sa)?([ -][0-9.]+)?|public domain|cc0|pd)",
                        re.IGNORECASE)

WANTED = [
    # Stvarna mjesta koja su tema teksta. Fotografija prikazuje lokalitet,
    # nikad konkretan predmet prodaje (to stoji i u potpisu ispod slike).
    ("varazdin",    "File:Varaždin - stari grad.jpg"),
    ("zracna-luka", "File:Zagreb Airport Terminal 20170429220324.jpg"),
    ("prokurative", "File:Prokurative, Split.jpg"),
    ("sud",         "File:Općinski i županijski sud Osijek.jpg"),
    ("obala",       "File:Rovinj Old Town.jpg"),
    # Po jedna za svaku od najčešćih županija, da tri spotlight teksta ne
    # dijele istu sliku.
    ("zagreb",      "File:Zagreb - Ban Jelačić Square.JPG"),
    # Namjerno bez Flickr ID-a u nazivu: 11-znamenkasti broj u kreditu
    # detektor osobnih podataka ispravno prijavljuje kao mogući OIB.
    ("split",       "File:Splitska Riva.jpg"),
    ("pula",        "File:Pula Aerial View.jpg"),
    # Slavonsko selo i obradivo polje: teme su jeftine seoske kuće i
    # poljoprivredno zemljište, pa slika mora prikazivati upravo to.
    ("selo",        "File:Đakovo - panoramio.jpg"),
    ("polje",       "File:Field in Brezje Varazdin.jpg"),
]


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def fetch_meta(titles: list[str]) -> dict:
    params = {
        "action": "query", "titles": "|".join(titles), "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": "1400", "format": "json",
    }
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = fetch_meta([t for _, t in WANTED])
    pages = {p["title"]: p for p in data.get("query", {}).get("pages", {}).values()}

    manifest, rejected = {}, []
    for slug, title in WANTED:
        page = pages.get(title)
        if not page or "imageinfo" not in page:
            rejected.append((title, "nema u Commonsu"))
            continue
        ii = page["imageinfo"][0]
        m = ii.get("extmetadata", {})
        licence = _strip(m.get("LicenseShortName", {}).get("value", ""))
        if not OK_LICENCE.match(licence):
            rejected.append((title, f"licenca '{licence}' nije slobodna"))
            continue

        url = ii.get("thumburl") or ii["url"]
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            blob = r.read()
        img = Image.open(io.BytesIO(blob)).convert("RGB")
        # 1200×630 (isti omjer kao og-image), izrez po sredini
        target_w, target_h = 1200, 630
        scale = max(target_w / img.width, target_h / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
        left = (img.width - target_w) // 2
        top = (img.height - target_h) // 3        # gornja trećina: nebo se reže prvo
        img = img.crop((left, top, left + target_w, top + target_h))
        dest = OUT_DIR / f"{slug}.jpg"
        img.save(dest, "JPEG", quality=82, optimize=True, progressive=True)

        manifest[slug] = {
            "naslov": title.removeprefix("File:"),
            "autor": _strip(m.get("Artist", {}).get("value", "")) or "nepoznat autor",
            "licenca": licence,
            "licenca_url": m.get("LicenseUrl", {}).get("value", ""),
            "izvor_url": ii.get("descriptionurl", ""),
            "datoteka": f"/static/photos/{slug}.jpg",
        }
        print(f"  ok  {slug:12s} {licence:14s} {manifest[slug]['autor'][:34]:34s} "
              f"{dest.stat().st_size // 1024} kB")

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\npreuzeto: {len(manifest)} · odbijeno: {len(rejected)}")
    for t, why in rejected:
        print(f"  ODBIJENO {t}: {why}")
    print(f"popis izvora: {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
