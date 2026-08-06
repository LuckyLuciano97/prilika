"""Izvedi data/ko_zupanije.csv — županija svake katastarske općine.

Ulaz (oba već u repozitoriju, oba pod Otvorenom dozvolom):
  data/ko_tocke.csv   — 3 496 k.o. s referentnim točkama (DGU INSPIRE)
  data/naselja.csv    — 6 357 naselja sa županijom (DZS Popis 2021)

Dva prolaza:

  1. IME:         naziv k.o. jednoznačno odgovara naselju -> županija naselja,
                  ALI SAMO ako točka k.o. leži ≤ 80 km od središta te županije.
                  Bez te provjere zagrebačka k.o. RESNIK dobije Požeško-slavonsku
                  (jer selo Resnik postoji samo kod Požege), DONJA DUBRAVA dobije
                  Međimursku, a PEŠČENICA Sisačko-moslavačku — ime je jedinstveno,
                  a svejedno pogrešno. Koordinate su sudac.
                  Odbacuje se samo redni nastavak ("NOVALJA I" -> "Novalja");
                  ništa se ne krati drugačije — pouka slučaja "Velika Mlaka".

  2. SUSJEDSTVO:  za nepridružene k.o. glasaju najbliže pridružene k.o.
                  Uvjet: najbliža ≤ 12 km i svih 5 najbližih u ISTOJ županiji.
                  Županije su povezana područja, pa je jednoglasno susjedstvo
                  jak dokaz; uz granicu županija jednoglasnosti nema i k.o.
                  ostaje nepridružena — radije rupa nego pogađanje.

Pokretanje:  python tools/build_ko_zupanije.py
Izlaz:       data/ko_zupanije.csv  (maticni_broj;naziv;zupanija;izvor)
"""
from __future__ import annotations

import csv
import math
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from croatia import COUNTY_CENTROIDS  # noqa: E402

# Imensko pridruženje se odbacuje kad je tvrđena županija VIŠESTRUKO dalja
# od najbliže — apsolutni radijus ne radi: zagrebačka k.o. DONJA DUBRAVA je
# 71 km od Međimurja (premalo za apsolutni prag), a stvarni Mali Lošinj je
# 89 km od središta svoje PGŽ (previše). Omjer razlikuje oba slučaja.
REJECT_RATIO = 2.5
MIN_SUSPECT_KM = 25.0
KO = ROOT / "data" / "ko_tocke.csv"
NAS = ROOT / "data" / "naselja.csv"
OUT = ROOT / "data" / "ko_zupanije.csv"

_ORDINAL = re.compile(r"\s+(?:[IVX]{1,4}|\d{1,2})$")


def fold(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def dist_km(a, b) -> float:
    dlat = (a[0] - b[0]) * 111.0
    dlon = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return (dlat * dlat + dlon * dlon) ** 0.5


def main() -> int:
    kos = list(csv.DictReader(KO.open(encoding="utf-8"), delimiter=";"))
    settlements: dict[str, set[str]] = {}
    # Sekundarni ključ: poredani tokeni. Katastarska imena često obrću red
    # riječi u odnosu na naselje ("MOSLAVINA PODRAVSKA" ↔ "Podravska
    # Moslavina") — isti tokeni, drugi redoslijed. Ista pravila vrijede:
    # jednoznačna županija + prostorna provjera.
    settlements_sorted: dict[str, set[str]] = {}
    for r in csv.DictReader(NAS.open(encoding="utf-8"), delimiter=";"):
        f = fold(r["naselje"])
        settlements.setdefault(f, set()).add(r["zupanija"])
        skey = " ".join(sorted(f.split()))
        settlements_sorted.setdefault(skey, set()).add(r["zupanija"])

    assigned: dict[str, tuple[str, str]] = {}   # code -> (županija, izvor)

    # --- 0. prolaz: jezgra Grada Zagreba ----------------------------------
    # Zagreb je jedini grad čije naselje ("Zagreb") pokriva desetke k.o. s
    # imenima četvrti (Trnje, Peščenica, Resnik...) koja NISU naselja. Bez
    # sidra unutar grada susjedski glas povlači gradsku jezgru u prsten
    # Zagrebačke županije. Zato: k.o. unutar 8 km od središta -> Grad Zagreb.
    # Najbliža naselja Zagrebačke županije počinju tek na ~10 km.
    zg = COUNTY_CENTROIDS["Grad Zagreb"]
    for k in kos:
        pt = (float(k["lat"]), float(k["lon"]))
        if dist_km(pt, zg) <= 8.0:
            assigned[k["maticni_broj"]] = ("Grad Zagreb", "jezgra")
    by_core = len(assigned)
    print(f"jezgra Grada Zagreba (≤ 8 km): {by_core} k.o.")

    # --- 1. prolaz: ime + prostorna provjera ------------------------------
    rejected_far = []
    for k in kos:
        if k["maticni_broj"] in assigned:
            continue
        name = _ORDINAL.sub("", k["naziv"].strip())
        f = fold(name)
        counties = settlements.get(f)
        izvor = "ime"
        if not counties:
            counties = settlements_sorted.get(" ".join(sorted(f.split())))
            izvor = "ime-obrnuto"
        if not counties or len(counties) != 1:
            continue
        county = next(iter(counties))
        centroid = COUNTY_CENTROIDS.get(county)
        pt = (float(k["lat"]), float(k["lon"]))
        if centroid:
            d_claim = dist_km(pt, centroid)
            d_min = min(dist_km(pt, c) for c in COUNTY_CENTROIDS.values())
            if d_claim > MIN_SUSPECT_KM and d_claim > REJECT_RATIO * d_min:
                rejected_far.append((k["naziv"], county, round(d_claim)))
                continue
        assigned[k["maticni_broj"]] = (county, izvor)
    by_name = len(assigned) - by_core
    if rejected_far:
        print(f"odbačeno {len(rejected_far)} imenskih pridruženja čija je županija "
              f"višestruko dalja od najbliže:")
        for n, c, dkm in rejected_far[:8]:
            print(f"    - {n} -> {c} ({dkm} km) — ide na susjedstvo")

    # --- 2. prolaz: susjedstvo, iterativno --------------------------------
    # Više krugova: čim susjedstvo pridruži rubnu k.o., ona u idućem krugu
    # glasa za svoje susjede — tako se čisto gradsko tkivo širi prema rubu.
    for _round in range(5):
        ref = [(k["maticni_broj"], float(k["lat"]), float(k["lon"]))
               for k in kos if k["maticni_broj"] in assigned]
        added = 0
        for k in kos:
            code = k["maticni_broj"]
            if code in assigned:
                continue
            pt = (float(k["lat"]), float(k["lon"]))
            near = sorted(((dist_km(pt, (la, lo)), c) for c, la, lo in ref),
                          key=lambda x: x[0])[:5]
            if len(near) < 5 or near[0][0] > 12.0:
                continue
            counties = {assigned[c][0] for _, c in near}
            if len(counties) == 1:
                assigned[code] = (next(iter(counties)), "susjedstvo")
                added += 1
        if not added:
            break
    by_knn = len(assigned) - by_name

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["maticni_broj", "naziv", "zupanija", "izvor"])
        for k in kos:
            code = k["maticni_broj"]
            if code in assigned:
                zup, izv = assigned[code]
                w.writerow([code, k["naziv"], zup, izv])

    missing = [k["naziv"] for k in kos if k["maticni_broj"] not in assigned]
    print(f"k.o. ukupno: {len(kos):,}")
    print(f"  pridruženo po imenu:      {by_name:,}")
    print(f"  pridruženo susjedstvom:   {by_knn:,}")
    print(f"  NEpridruženo (uz granice/otoci): {len(missing):,}")
    for n in missing[:10]:
        print(f"    - {n}")
    print(f"zapisano u {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
