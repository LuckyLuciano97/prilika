"""Izgradi data/naselja.csv iz službenog DZS popisa stanovništva 2021.

Izvor: Državni zavod za statistiku, "Statistika u nizu: Popis stanovništva 2021",
tablica 1 (Stanovništvo prema starosti i spolu po naseljima).

  dataset:  https://data.gov.hr/ckan/dataset/1edeff82-7518-4ff7-acc0-30e637e01355
  resource: https://podaci.dzs.hr/media/rqybclnx/popis_2021-stanovnistvo_po_naseljima.xlsx
  licenca:  Otvorena dozvola (OD) — license_id "open-license", provjereno u CKAN API

Ovo je jedini razlog zašto se ovaj registar smije koristiti: gradski CSV
(Grad Zagreb) imao je prazan license_id pa je odbijen (v. README).

Pokretanje:  python tools/build_naselja.py
Izlaz:       data/naselja.csv  (naselje;grad_opcina;zupanija)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cache" / "ref" / "dzs_naselja_2021.xlsx"
OUT = ROOT / "data" / "naselja.csv"

# DZS koristi kratka imena županija; pipeline puna. "Grad Zagreb" je poseban.
COUNTY_FULL = {
    "Zagrebačka": "Zagrebačka županija",
    "Krapinsko-zagorska": "Krapinsko-zagorska županija",
    "Sisačko-moslavačka": "Sisačko-moslavačka županija",
    "Karlovačka": "Karlovačka županija",
    "Varaždinska": "Varaždinska županija",
    "Koprivničko-križevačka": "Koprivničko-križevačka županija",
    "Bjelovarsko-bilogorska": "Bjelovarsko-bilogorska županija",
    "Primorsko-goranska": "Primorsko-goranska županija",
    "Ličko-senjska": "Ličko-senjska županija",
    "Virovitičko-podravska": "Virovitičko-podravska županija",
    "Požeško-slavonska": "Požeško-slavonska županija",
    "Brodsko-posavska": "Brodsko-posavska županija",
    "Zadarska": "Zadarska županija",
    "Osječko-baranjska": "Osječko-baranjska županija",
    "Šibensko-kninska": "Šibensko-kninska županija",
    "Vukovarsko-srijemska": "Vukovarsko-srijemska županija",
    "Splitsko-dalmatinska": "Splitsko-dalmatinska županija",
    "Istarska": "Istarska županija",
    "Dubrovačko-neretvanska": "Dubrovačko-neretvanska županija",
    "Međimurska": "Međimurska županija",
    "Grad Zagreb": "Grad Zagreb",
}


def main() -> int:
    if not SRC.exists():
        print(f"GREŠKA: nema {SRC} — preuzmi DZS XLSX najprije.", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(SRC, read_only=True)
    ws = wb["1."]

    # Redak "sv." (svi) nosi ukupno stanovništvo naselja. Stanovništvo je
    # bitno: isto ime naselja zna postojati u više županija (400 slučajeva),
    # a omjer veličina je mjeren, službeni način da se prepozna dominantno
    # ("Dugopolje" kraj Splita ~3 000 ljudi vs. zaselak kraj Gračca).
    seen: dict[tuple[str, str, str], int] = {}
    unknown_counties: set[str] = set()
    for row in ws.iter_rows(min_row=9, max_col=9, values_only=True):
        county_short = (str(row[0]).strip() if row[0] else "")
        town = (str(row[4]).strip() if row[4] else "")
        settlement = (str(row[5]).strip() if row[5] else "")
        sex = (str(row[6]).strip() if row[6] else "")
        if not county_short or not settlement or sex != "sv.":
            continue  # zaglavlja, međuzbrojevi, retci m/ž
        county = COUNTY_FULL.get(county_short)
        if county is None:
            unknown_counties.add(county_short)
            continue
        try:
            pop = int(row[8])
        except (TypeError, ValueError):
            pop = 0
        seen[(settlement, town, county)] = pop

    if unknown_counties:
        print(f"GREŠKA: nepoznata imena županija u izvoru: {sorted(unknown_counties)}",
              file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["naselje", "grad_opcina", "zupanija", "stanovnistvo"])
        for (naselje, grad, zup), pop in sorted(seen.items()):
            w.writerow([naselje, grad, zup, pop])

    counties = {z for _, _, z in seen}
    names = {n for n, _, _ in seen}
    print(f"zapisano {len(seen):,} redaka u {OUT}")
    print(f"  različitih naselja: {len(names):,} · županija: {len(counties)}")
    dup = len(seen) - len(names)
    print(f"  naselja s istim imenom u više jedinica: {dup:,} redaka viška "
          f"(rješava se korovoracijom u normalise.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
