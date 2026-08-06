"""Jednokratna LLM ekstrakcija lokacija za tvrdokorni ostatak.

Pravila lokacije u normalise.py namjerno ne pogađaju: bez fuzzy-matchinga,
bez "vjerojatno je mislio". Cijena te discipline je ostatak stavki čiji opis
lokaciju navodi s tipfelerom ("Kneževci Vinogradi"), slobodnom prozom ili
zemljišnoknjižnom k.o. koje nema u katastarskom registru. Za taj ostatak
model čita opis i PREDLAŽE lokaciju — a prijedlog ulazi u podatke tek kad
ga potvrdi službeni registar:

  * naselje  -> DZS registar naselja (data/naselja.csv, Popis 2021)
  * k.o.     -> DGU registar k.o.   (data/ko_tocke.csv + ko_zupanije.csv)
  * županija -> popis 21 službene županije, i to samo ako je županija
                doslovno spomenuta u opisu (model ne smije ništa izmisliti)

Model predlaže, registri odlučuju. Odbijeni prijedlozi se ispisuju s
razlogom i NE ulaze u podatke — radije rupa nego pogađanje.

Zaštita podataka: modelu se šalje isključivo `description` iz baze, dakle
tekst koji je već prošao redakciju osobnih podataka (sanitise.py). Sirovi
CSV se ovdje ne dira.

Rezultat: data/llm_lokacije.csv (item_key;zupanija;naselje;ko;dokaz;model),
commita se u repozitorij pa dnevni pipeline ostaje determinističan i radi
bez API ključa. croatia.llm_locations() pri učitavanju ponavlja iste
provjere registra — datoteka se ne može ručno "obogatiti" mimo registara.

Pokretanje:  python tools/llm_lokacije.py [--dry-run] [--force]
Preduvjet:   ANTHROPIC_API_KEY u .env (model: Claude Haiku — nekoliko centi)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import croatia  # noqa: E402
import store  # noqa: E402

MODEL = "claude-haiku-4-5"
OUT = ROOT / "data" / "llm_lokacije.csv"
FIELDS = ["item_key", "zupanija", "naselje", "ko", "dokaz", "model"]

_ORDINAL = re.compile(r"\s+(?:[IVX]{1,4}|\d{1,2})$")


def fold(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


# --- registarske provjere ---------------------------------------------------

def _county_official(name: str | None) -> str | None:
    """Točan naziv županije s popisa 21, ili None. Prihvaća i oblik bez
    riječi 'županija' ('Osječko-baranjska')."""
    if not name:
        return None
    f = fold(name.strip())
    for county in croatia.COUNTIES:
        if f == fold(county) or f == fold(county.replace(" županija", "")):
            return county
    return None


def _ko_entries(name: str) -> list[tuple[str, str, float, float]]:
    """Zapisi DGU registra za ime k.o. — ista pravila kao normalise.py:
    redni nastavak, crtica/razmaci kao interpunkcija ("Komarna-Duboka" ↔
    "KOMARNA - DUBOKA"), obrnuti red riječi. Bez prefiksnog pogađanja."""
    by_name = croatia.ko_points()[1]
    f = fold(_ORDINAL.sub("", name.strip(" ,.;:-")))
    entries = by_name.get(f) or []
    if not entries and "-" in f:
        entries = by_name.get(f.replace("-", " ")) or []
    if not entries:
        ck = " ".join(sorted(f.replace("-", " ").split()))
        for ents in by_name.values():
            if " ".join(sorted(fold(ents[0][1]).replace("-", " ").split())) == ck:
                entries = ents
                break
    return entries


def _grounded(name: str, text: str) -> bool:
    """Je li ime doslovno u opisu (granica riječi, crtica ~ razmak)?

    Dokaz koji je i U TEKSTU i U REGISTRU ne ovisi o mišljenju modela —
    model ga je samo pronašao. Tada njegova (možda kriva) tvrdnja o
    županiji ne smije srušiti registarski nalaz: registri odlučuju.
    """
    ftext = fold(text)
    f = fold(name.strip(" ,.;:-"))
    for cand in {f, f.replace("-", " "), f.replace(" ", "-")}:
        if re.search(rf"(?<![a-z0-9]){re.escape(cand)}(?![a-z0-9])", ftext):
            return True
    return False


def validate(sug: dict, text: str) -> tuple[dict | None, str]:
    """(prihvaćeni redak, razlog-odbijanja). Registri odlučuju."""
    naselje = (sug.get("naselje") or "").strip() or None
    ko = (sug.get("ko") or "").strip() or None
    zup = _county_official(sug.get("zupanija"))

    # 1. k.o. protiv DGU registra — najjači dokaz (nosi i koordinate)
    if ko:
        entries = _ko_entries(ko)
        ko_map = croatia.ko_county()
        if len(entries) == 1:
            code, name, _la, _lo = entries[0]
            county = ko_map.get(code)
            if county:
                if zup and zup != county and not _grounded(ko, text):
                    return None, (f"k.o. {name} je u {county}, model tvrdi {zup} "
                                  "— proturječje bez uporišta u tekstu, odbijeno")
                nas_row = _settlement_in(naselje, county) if naselje else None
                if (naselje and not nas_row
                        and _settlement_counties(naselje) - {county}
                        and not _grounded(ko, text)):
                    return None, (f"k.o. {name} ({county}) i naselje {naselje} "
                                  "se ne slažu — odbijeno")
                return {
                    "zupanija": county,
                    "naselje": nas_row or "",
                    "ko": name.title(),
                    "dokaz": f"k.o. {name} (DGU {code})",
                }, ""
        elif len(entries) > 1:
            cands = {croatia.ko_county()[e[0]] for e in entries
                     if e[0] in croatia.ko_county()}
            if zup and zup in cands:
                return {
                    "zupanija": zup,
                    "naselje": _settlement_in(naselje, zup) or "" if naselje else "",
                    "ko": entries[0][1].title(),
                    "dokaz": f"k.o. {entries[0][1]} ×{len(entries)} + županija u opisu",
                }, ""

    # 2. naselje protiv DZS registra
    if naselje:
        counties = _settlement_counties(naselje)
        # Imena poznata kao dvoznačna (Novigrad, Otok...) DZS zna voditi pod
        # jednim zapisom ("Novigrad – Cittanova" vs "Novigrad"), pa registar
        # lažno izgleda jednoznačan. Kurirana lista dvoznačnih imena traži
        # potvrdu županije — bez nje se ne prihvaća.
        _fn = fold(_ORDINAL.sub("", naselje.strip(" ,.;:-")))
        _amb = {fold(t) for t in croatia.AMBIGUOUS_TOWNS}
        if _fn in _amb:
            if zup and zup in counties and not _dgu_conflict(_fn, zup):
                return {
                    "zupanija": zup,
                    "naselje": _settlement_in(naselje, zup),
                    "ko": "",
                    "dokaz": f"naselje {_settlement_in(naselje, zup)} (DZS) "
                             "+ županija (dvoznačno ime)",
                }, ""
            return None, (f"naselje {naselje} je poznato dvoznačno ime — "
                          "bez potvrde županije se ne prihvaća")
        if len(counties) == 1:
            county = next(iter(counties))
            if _dgu_conflict(_fn, county):
                return None, (f"naselje {naselje}: istoimena k.o. postoji u "
                              "drugoj županiji (DGU) — ime nije jednoznačno, "
                              "odbijeno")
            if zup and zup != county and not _grounded(naselje, text):
                return None, (f"naselje {naselje} je u {county}, model tvrdi "
                              f"{zup} — proturječje bez uporišta u tekstu, odbijeno")
            return {
                "zupanija": county,
                "naselje": _settlement_in(naselje, county),
                "ko": "",
                "dokaz": f"naselje {_settlement_in(naselje, county)} (DZS)",
            }, ""
        if len(counties) > 1 and zup in counties and not _dgu_conflict(_fn, zup):
            return {
                "zupanija": zup,
                "naselje": _settlement_in(naselje, zup),
                "ko": "",
                "dokaz": f"naselje {_settlement_in(naselje, zup)} (DZS, ×{len(counties)}) "
                         "+ županija",
            }, ""
        if counties:
            return None, (f"naselje {naselje} postoji u {len(counties)} županija, "
                          "bez presude — odbijeno")
        if not zup:
            return None, f"'{naselje}' nije u DZS registru naselja — odbijeno"

    # 3. samo županija — prihvatljivo jedino uz uporište u samom opisu:
    #    ili je županija izrijekom spomenuta, ili opis doslovno sadrži ime
    #    naselja koje po DZS registru JEDNOZNAČNO pripada toj županiji
    #    ("ZAGREB, DRAGANIĆI" potvrđuje "Grad Zagreb"). Ime mora biti i u
    #    tekstu i u registru — model ga je samo pročitao.
    if zup:
        stem = fold(zup.replace(" županija", ""))
        if stem[:-1] in fold(text):
            return {"zupanija": zup, "naselje": "", "ko": "",
                    "dokaz": f"županija izrijekom u opisu ({zup})"}, ""
        mention = _unique_mention(zup, text)
        if mention:
            return {"zupanija": zup, "naselje": mention, "ko": "",
                    "dokaz": f"mjesto {mention} u opisu (DZS, jednoznačno)"}, ""
        return None, (f"model tvrdi {zup}, ali ni županija ni njoj jednoznačno "
                      "mjesto nisu spomenuti u opisu")

    return None, "model nije prepoznao lokaciju"


_UNIQ_BY_COUNTY: dict[str, list[str]] | None = None


def _unique_mention(county: str, text: str) -> str | None:
    """Službeno ime naselja iz zadane županije koje je doslovno u opisu,
    a u DZS registru postoji SAMO u toj županiji. Kratka imena (<4 znaka,
    Vis/Pag/Krk...) se preskaču — prečesto su dio druge riječi ili slučajna.
    Dvoznačna imena s kurirane liste također ne mogu potvrditi ništa."""
    global _UNIQ_BY_COUNTY
    if _UNIQ_BY_COUNTY is None:
        amb = {fold(t) for t in croatia.AMBIGUOUS_TOWNS}
        by_county: dict[str, list[str]] = {}
        for f, hits in croatia.settlements().items():
            counties = {h[2] for h in hits}
            if len(counties) == 1 and len(f) >= 4 and f not in amb:
                by_county.setdefault(next(iter(counties)), []).append(f)
        _UNIQ_BY_COUNTY = by_county
    ftext = fold(text)
    best: tuple[int, str] | None = None
    for f in _UNIQ_BY_COUNTY.get(county, []):
        if f in ftext and re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", ftext):
            if _dgu_conflict(f, county):
                continue
            if best is None or len(f) > best[0]:
                best = (len(f), f)
    if best is None:
        return None
    hits = croatia.settlements()[best[1]]
    return max(hits, key=lambda h: h[3])[0]


def _settlement_counties(name: str) -> set[str]:
    clean = _ORDINAL.sub("", name.strip(" ,.;:-"))
    return {h[2] for h in croatia.settlements().get(fold(clean), [])}


def _dgu_conflict(fname: str, county: str) -> bool:
    """Vodi li DGU katastar ISTOIMENU k.o. u nekoj drugoj županiji?

    DZS zna biti slijep na dvoznačnost: "Blato" je u registru naselja samo
    korčulansko mjesto, ali katastar vodi i k.o. BLATO u Zagrebu — pa opis
    "k.o. Blato Novo" (zagrebačka zemljišnoknjižna) ne smije završiti na
    Korčuli. Registar protiv registra, bez heuristike: ime koje službeni
    katastar vodi i drugdje nije jednoznačan dokaz za naselje.
    """
    ko_map = croatia.ko_county()
    for code, *_ in croatia.ko_points()[1].get(fname, []):
        c = ko_map.get(code)
        if c and c != county:
            return True
    return False


def _settlement_in(name: str | None, county: str) -> str | None:
    """Službeni DZS zapis imena naselja unutar zadane županije (najveće)."""
    if not name:
        return None
    clean = _ORDINAL.sub("", name.strip(" ,.;:-"))
    hits = [h for h in croatia.settlements().get(fold(clean), []) if h[2] == county]
    return max(hits, key=lambda h: h[3])[0] if hits else None


# --- LLM poziv --------------------------------------------------------------

SYSTEM = (
    "Izvlačiš lokaciju nekretnine iz teksta oglasa sudske dražbe u Hrvatskoj. "
    "Odgovori ISKLJUČIVO JSON objektom, bez ijedne druge riječi:\n"
    '{"naselje": <string|null>, "ko": <string|null>, '
    '"zupanija": <string|null>, "obrazlozenje": <string>}\n\n'
    "Pravila:\n"
    "- naselje: službeno ime naselja/mjesta gdje se NEKRETNINA nalazi, ako je "
    "u tekstu navedeno ili ga sa sigurnošću prepoznaješ. Ispravi očite "
    "tipfelere (npr. 'Kneževci Vinogradi' -> 'Kneževi Vinogradi') — i kad je "
    "tipfeler u imenu k.o., ispravljeno službeno ime naselja upiši u 'naselje'. "
    "Ako je k.o. gradska četvrt ili zemljišnoknjižno ime (npr. 'Vrapče Novo'), "
    "u 'naselje' upiši naselje kojem pripada (npr. 'Zagreb'). Inače null.\n"
    "- ko: ime katastarske općine BEZ prefiksa 'k.o.', ako je navedeno. Inače null.\n"
    "- zupanija: TOČAN naziv s ovog popisa. Uvijek je pokušaj navesti kad "
    "sa sigurnošću znaš gdje je navedeno mjesto ili k.o.; inače null:\n  "
    + "; ".join(croatia.COUNTIES) + "\n"
    "- obrazlozenje: najviše 15 riječi — na kojem dijelu teksta se temelji.\n"
    "- Sjedište suda ili bilježnika NIJE dokaz lokacije nekretnine; "
    "trgovački sudovi pokrivaju cijelu državu.\n"
    "- Ne izmišljaj: ako lokacije u tekstu nema, sva tri polja su null."
)


def ask_model(client, description: str, issuer: str) -> dict | None:
    prompt = (f"{description[:2000]}\n\n"
              f"Nadležno tijelo (oprez, nije dokaz lokacije): {issuer}")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# --- glavni tok -------------------------------------------------------------

def residue(conn) -> list[dict]:
    """Aktivne nekretninske stavke bez utvrđene županije."""
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT item_key, description, issuer_name, status
            FROM items
            WHERE county IS NULL
              AND property_type NOT IN ('pokretnina', 'pravo')
              AND status <> 'zavrseno'
            ORDER BY item_key
            """
        )
        return [dict(r) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="samo ispiši ciljne stavke, bez API poziva")
    ap.add_argument("--force", action="store_true",
                    help="obradi i stavke koje su već u data/llm_lokacije.csv")
    args = ap.parse_args()

    config.load_dotenv()

    done: dict[str, dict] = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                done[row["item_key"]] = row

    with store.connect() as conn:
        items = residue(conn)

    todo = [it for it in items if args.force or it["item_key"] not in done]
    print(f"neriješenih aktivnih nekretninskih stavki: {len(items)}")
    print(f"za obradu (bez već obrađenih): {len(todo)}")
    if args.dry_run:
        for it in todo:
            print(f"  - {it['item_key']}  [{it['status']}]  "
                  f"{(it['description'] or '')[:90]!r}")
        return 0

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nGREŠKA: ANTHROPIC_API_KEY nije postavljen.\n"
              "Dodaj u .env redak:  ANTHROPIC_API_KEY=sk-ant-...\n"
              "(.env je u .gitignore i nikad se ne commita)")
        return 2

    import anthropic
    client = anthropic.Anthropic()

    accepted: list[dict] = []
    rejected: list[tuple[str, str, str]] = []

    for i, it in enumerate(todo, 1):
        key = it["item_key"]
        try:
            sug = ask_model(client, it["description"] or "", it["issuer_name"] or "")
        except anthropic.APIError as e:
            rejected.append((key, "API greška", str(e)[:120]))
            time.sleep(2)
            continue
        if sug is None:
            rejected.append((key, "neispravan JSON iz modela", ""))
            continue
        row, why = validate(sug, it["description"] or "")
        obr = (sug.get("obrazlozenje") or "")[:80]
        if row:
            row["item_key"] = key
            row["model"] = MODEL
            accepted.append(row)
            print(f"[{i}/{len(todo)}] + {key}: {row['zupanija']}"
                  f" — {row['dokaz']}")
        else:
            rejected.append((key, why, obr))
            print(f"[{i}/{len(todo)}] - {key}: {why}")

    # zapiši: postojeći retci + novoprihvaćeni, stabilno sortirano
    merged = {**done, **{r["item_key"]: r for r in accepted}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        for key in sorted(merged):
            w.writerow({f: merged[key].get(f, "") for f in FIELDS})

    print(f"\nprihvaćeno (potvrdio registar): {len(accepted)}")
    print(f"odbijeno:                       {len(rejected)}")
    for key, why, obr in rejected:
        line = f"  - {key}: {why}"
        if obr:
            line += f"  (model: {obr!r})"
        print(line)
    print(f"\nzapisano u {OUT} (ukupno {len(merged)} redaka)")
    print("dalje: python run.py --rebuild-only  &&  python validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
