"""Izgradi data/ko_tocke.csv — referentne točke svih katastarskih općina.

Izvor: DGU INSPIRE WFS servis za katastarske parcele i katastarske općine,
službeno objavljen kao otvoreni podatak:

  stranica:  https://dgu.gov.hr/otvoreni-podaci/6596
  servis:    https://api.uredjenazemlja.hr/services/inspire/cp/wfs
  sloj:      cp:CadastralZoning (3 496 katastarskih općina)
  licenca:   Otvorena dozvola — na stranici DGU izrijekom uz ovaj servis

Svaka katastarska općina nosi cp:referencePoint u EPSG:4326 — službene
koordinate. To je JEDNOKRATNO preuzimanje (k.o. se ne mijenjaju svaki dan);
rezultat se commita i ne dohvaća ponovno bez potrebe.

Pristojnost: stranice od 200 zapisa, stanka između zahtjeva, eksponencijalni
backoff na grešku (backend zna vratiti ORA-01000 pod opterećenjem), prekid
nakon 6 uzastopnih neuspjeha — nikad čekićanje.

Pokretanje:  python tools/build_ko_tocke.py
Izlaz:       data/ko_tocke.csv  (maticni_broj;naziv;lat;lon)
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ko_tocke.csv"

WFS = "https://api.uredjenazemlja.hr/services/inspire/cp/wfs"
UA = ("PrilikaBot/1.0 (+https://prilika.net; kontakt: support@nexistudio.dev) "
      "jednokratno preuzimanje k.o. referentnih tocaka, INSPIRE otvoreni podaci")

PAGE = 200
PAUSE = 3.0          # s između stranica
MAX_FAILS = 6

MEMBER_RE = re.compile(r"<wfs:member>(.*?)</wfs:member>", re.S)
LABEL_RE = re.compile(r"<cp:label>([^<]+)</cp:label>")
REF_RE = re.compile(r"<cp:nationalCadastalZoningReference>(\d+)</")
POINT_RE = re.compile(
    r"<cp:referencePoint>.*?<gml:pos>([\d.\-]+)\s+([\d.\-]+)</gml:pos>", re.S)
MATCHED_RE = re.compile(r'numberMatched="(\d+)"')


def fetch_page(session: requests.Session, start: int) -> tuple[list[dict], int]:
    url = (f"{WFS}?service=WFS&version=2.0.0&request=GetFeature"
           f"&typeNames=cp:CadastralZoning&srsName=EPSG:4326"
           f"&count={PAGE}&startIndex={start}")
    r = session.get(url, timeout=180)
    r.raise_for_status()
    text = r.text
    if "ExceptionReport" in text[:400]:
        raise RuntimeError(text[:300])
    total = int(MATCHED_RE.search(text).group(1)) if MATCHED_RE.search(text) else -1
    rows = []
    for m in MEMBER_RE.finditer(text):
        blk = m.group(1)
        lab = LABEL_RE.search(blk)
        ref = REF_RE.search(blk)
        pt = POINT_RE.search(blk)
        if not (lab and pt):
            continue
        lon, lat = float(pt.group(1)), float(pt.group(2))
        code = ref.group(1) if ref else lab.group(1).split("-")[0]
        name = lab.group(1).split("-", 1)[1] if "-" in lab.group(1) else lab.group(1)
        rows.append({"maticni_broj": code, "naziv": name.strip(),
                     "lat": round(lat, 7), "lon": round(lon, 7)})
    return rows, total


def main() -> int:
    session = requests.Session()
    session.headers["User-Agent"] = UA

    all_rows: list[dict] = []
    start, fails, total = 0, 0, None
    while True:
        try:
            rows, matched = fetch_page(session, start)
            fails = 0
            if total is None and matched > 0:
                total = matched
                print(f"ukupno k.o. u servisu: {total}")
        except Exception as exc:
            fails += 1
            wait = min(15 * fails, 60)
            print(f"  greška na startIndex={start} ({fails}/{MAX_FAILS}): "
                  f"{str(exc)[:120]} — čekam {wait}s", file=sys.stderr)
            if fails >= MAX_FAILS:
                print("PREKID: previše uzastopnih grešaka. Ne čekićamo tuđi "
                      "servis; pokušaj kasnije.", file=sys.stderr)
                return 1
            time.sleep(wait)
            continue

        if not rows:
            break
        all_rows.extend(rows)
        print(f"  {start:5} +{len(rows):3}  (ukupno {len(all_rows)})")
        start += PAGE
        if total and len(all_rows) >= total:
            break
        time.sleep(PAUSE)

    # dedupe po matičnom broju (sigurnosno)
    seen: dict[str, dict] = {}
    for r in all_rows:
        seen.setdefault(r["maticni_broj"], r)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["maticni_broj", "naziv", "lat", "lon"],
                           delimiter=";")
        w.writeheader()
        for r in sorted(seen.values(), key=lambda x: x["maticni_broj"]):
            w.writerow(r)
    print(f"zapisano {len(seen):,} k.o. točaka u {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
