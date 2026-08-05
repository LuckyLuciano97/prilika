"""Normalizacija: lokacija, površina, vrsta nekretnine, popust, status.

Radi na retku koji je VEĆ prošao `sanitise.py`. Nikad ne dira sirovi CSV
redak — tako slobodni tekst s osobnim podacima ne može zaobići redakciju.

Poštene rezerve
---------------
Očevidnik nema strukturiranu lokaciju (v. docs/source-notes.md §5). Županija
se izvodi u dva koraka:

  1. iz teksta opisa (naziv grada / katastarske općine)  -> pouzdanost "visoka"
  2. iz naziva općinskog suda                            -> pouzdanost "srednja"
  3. iz naziva trgovačkog suda                           -> NE koristi se

Trgovački sud i javni bilježnik namjerno se NE koriste kao izvor lokacije:
stečajna masa može držati nekretnine bilo gdje u RH, pa bi to bila izmišljena
preciznost. Takvi predmeti ostaju "Nepoznato" i broje se u izvještaju.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import croatia
from sanitise import normalise_issuer

# ---------------------------------------------------------------------------
# Osnovni parseri
# ---------------------------------------------------------------------------

_EUR_AMOUNT_RE = re.compile(r"([\d][\d.,\s ]*)\s*(?:EUR|€)", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")

_DIACRITICS = {
    "č": "c", "ć": "c", "đ": "d", "š": "s", "ž": "z",
    "Č": "C", "Ć": "C", "Đ": "D", "Š": "S", "Ž": "Z",
}


def slugify(text: str) -> str:
    """URL slug koji zadržava značenje, ali ne i dijakritiku.

    'Split-Dalmatinska županija' -> 'splitsko-dalmatinska-zupanija'
    Sadržaj stranica ostaje s punom dijakritikom; samo URL je ASCII.
    """
    if not text:
        return ""
    for k, v in _DIACRITICS.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fold(text: str) -> str:
    """Za usporedbu: mala slova bez dijakritike."""
    if not text:
        return ""
    for k, v in _DIACRITICS.items():
        text = text.replace(k, v)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def parse_money(value: str) -> float | None:
    """Iznos u eurima iz stupca koji NIJE dosljedno numerički.

    Izvor miješa najmanje četiri oblika u istom stupcu
    (`Minimalna zakonska cijena`, mjereno nad 11 091 retkom):

        39816.84                          50 670x  točka = decimalna
        59.725,26 EUR (449.999,97 HRK)     1 103x  hrvatski zapis, dvije valute
        30,31 EUR (228,37 HRK)               164x  zarez = decimalni
        3/4, 1/2, 1/4 procijenjene ...        --   proza, uopće nije iznos

    Naivno brisanje zareza pretvara "32.805,00" u 32,805 - tisuću puta
    premalo. Zato:

    1. ako se spominje EUR, uzima se iznos ISPRED "EUR" (ne HRK iz zagrade);
    2. decimalni separator je onaj koji se pojavljuje POSLJEDNJI;
    3. ono što nakon čišćenja nije čisti broj vraća se kao None, ne kao 0.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    m = _EUR_AMOUNT_RE.search(text)
    token = (m.group(1) if m else text).strip()
    for ws in (" ", " ", " ", "	"):
        token = token.replace(ws, "")
    if not token:
        return None

    if "," in token and "." in token:
        # Posljednji separator je decimalni, onaj drugi je tisućica.
        if token.rindex(",") > token.rindex("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    elif token.count(".") > 1:
        # Više točaka može biti samo tisućica ("1.102.500").
        token = token.replace(".", "")

    token = token.rstrip(".")
    if not _NUMERIC_RE.match(token):
        return None
    try:
        f = float(token)
    except ValueError:
        return None
    if f < 0:
        return None
    return quantize_money(f)


def quantize_money(value: float | None) -> float | None:
    """Zaokruži na 2 decimale ISTO kako to radi PostgreSQL NUMERIC(16,2).

    Python `round()` zaokružuje na parno (banker's rounding), PostgreSQL
    zaokružuje pola od nule. Zbog te razlike 32,805 postane 32,80 u Pythonu
    i 32,81 u bazi, pa sljedeće pokretanje to pročita kao promjenu cijene
    koje nije bilo. Kvantizacija ovdje jamči da je pohranjena vrijednost
    jednaka onoj s kojom se uspoređuje.
    """
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Površina
# ---------------------------------------------------------------------------

_AREA_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(m2|m²|m\s*2|čhv|hvati|hvata|ha)\b",
    re.IGNORECASE,
)


def parse_area(opis: str) -> tuple[float | None, str]:
    """Izvuci površinu u m² iz opisa.

    Vraća (m2, izvorna_jedinica). Uzima NAJVEĆU nađenu površinu, jer opis
    često nabraja više čestica, a najveća najbolje opisuje predmet prodaje.
    Konverzije: 1 ha = 10 000 m², 1 čhv (čentimetarski hvat) = 3,5966 m².
    """
    if not opis:
        return None, ""
    best: float | None = None
    unit = ""
    for m in _AREA_RE.finditer(opis):
        num_raw, u = m.group(1), m.group(2).lower().replace(" ", "")
        num = num_raw
        if "." in num and "," in num:
            num = num.replace(".", "").replace(",", ".")
        elif "," in num:
            num = num.replace(",", ".")
        elif re.match(r"^\d{1,3}(\.\d{3})+$", num):
            num = num.replace(".", "")
        try:
            val = float(num)
        except ValueError:
            continue
        if u == "ha":
            val *= 10_000
        elif u in ("čhv", "hvati", "hvata"):
            val *= 3.5966
        if val <= 0 or val > 10_000_000:  # očita greška u unosu
            continue
        if best is None or val > best:
            best, unit = val, m.group(2)
    return (round(best, 2) if best else None), unit


# ---------------------------------------------------------------------------
# Vrsta nekretnine
# ---------------------------------------------------------------------------

# Redoslijed je bitan: provjerava se odozgo prema dolje, pa uže kategorije
# (stan, kuća, poslovni prostor) idu prije općenitog "zemljište".
# Ključne riječi su pisane bez dijakritike jer se uspoređuju nad `fold()`.
PROPERTY_TYPES = [
    ("stan", ("stan ", "stana ", "stanu ", "stan,", "stan.", "apartman", "garsonijer",
              "stambena jedinica", "etazno vlasnistvo stana", "dvosoban", "trosoban",
              "jednosoban", "cetverosoban")),
    ("kuca", ("kuca", "obiteljska kuca", "stambena zgrada", "stambena kuca", "vikendica",
              "kuce", "kucom", "stambeni objekt", "stambena gradevina")),
    ("poslovni-prostor", ("poslovni prostor", "poslovnog prostora", "poslovnom prostoru",
                          "ured", "restoran", "hotel", "skladiste", "trgovina",
                          "ugostitelj", "poslovna zgrada", "poslovni objekt",
                          "proizvodna hala", "hala", "radionica", "pogon", "kamp",
                          "benzinska", "silos", "staja", "klaonica", "mlin")),
    ("gradevinsko-zemljiste", ("gradevinsko zemlj", "gradiliste", "gradjevinsko zemlj",
                               "zemljiste za gradnju", "gradevno zemlj")),
    ("poljoprivredno-zemljiste", ("poljoprivredno zemlj", "oranica", "livada", "vinograd",
                                  "vocnjak", "pasnjak", "njiva", "maslinik", "vrt",
                                  "sljivik", "voćnjak", "bara", "trstik", "ribnjak",
                                  "poljoprivredno")),
    ("sumsko-zemljiste", ("sumsko zemlj", "suma", "sume", "sumom", "sumski")),
    ("garaza", ("garaza", "garazno mjesto", "parkirno mjesto", "parkiralisno",
                "garazni prostor", "parkirno-garazno")),
    ("zemljiste", ("zemljiste", "dvoriste", "cestica", "k.c.", "kc.br", "ckbr",
                   "zemljista", "neplodno")),
]

PROPERTY_TYPE_LABELS = {
    "stan": "Stan",
    "kuca": "Kuća",
    "poslovni-prostor": "Poslovni prostor",
    "gradevinsko-zemljiste": "Građevinsko zemljište",
    "poljoprivredno-zemljiste": "Poljoprivredno zemljište",
    "sumsko-zemljiste": "Šumsko zemljište",
    "garaza": "Garaža / parkirno mjesto",
    "zemljiste": "Zemljište",
    "pokretnina": "Pokretnina",
    "pravo": "Pravo",
    # "Ostalo" je loš naslov stranice i loš SEO. Kad vrsta nije prepoznata,
    # koristi se točan, ali neutralan naziv.
    "ostalo": "Nekretnina",
}

# Naslovi kategorijskih stranica traže množinu.
PROPERTY_TYPE_CATEGORY = {
    "stan": "Stanovi",
    "kuca": "Kuće",
    "poslovni-prostor": "Poslovni prostori",
    "gradevinsko-zemljiste": "Građevinska zemljišta",
    "poljoprivredno-zemljiste": "Poljoprivredna zemljišta",
    "sumsko-zemljiste": "Šumska zemljišta",
    "garaza": "Garaže i parkirna mjesta",
    "zemljiste": "Zemljišta",
    "pokretnina": "Pokretnine",
    "pravo": "Prava",
    "ostalo": "Ostale nekretnine",
}


def classify_property(opis: str, vrsta: str) -> str:
    """Vrsta se izvodi iz opisa — CSV daje samo grubu podjelu (4 vrijednosti).

    Usporedba ide nad `fold()` tekstom (bez dijakritike) jer izvor nije
    dosljedan u pisanju kvačica. Kratke ključne riječi ("vrt", "suma")
    traže se s granicom riječi da ne pogode "vrtić" ili "sumarno".
    """
    v = fold(vrsta)
    if v == "pokretnina":
        return "pokretnina"
    if v == "pravo":
        return "pravo"
    text = fold(opis or "")
    for key, needles in PROPERTY_TYPES:
        for n in needles:
            if len(n.strip()) <= 5 and n.strip().isalpha():
                if re.search(rf"\b{re.escape(n.strip())}\w{{0,3}}\b", text):
                    return key
            elif n in text:
                return key
    return "ostalo"


# ---------------------------------------------------------------------------
# Lokacija
# ---------------------------------------------------------------------------

# "u Rijeci, na adresi ...", "k.o. Trsat-Sušak", "nalazi se u Splitu"
# Naziv katastarske općine je niz VELIKIM slovom pisanih riječi
# ("Trsat-Sušak", "Vela Luka", "Garešnica-Centar"). Ranija, labavija inačica
# hvatala je i tekst koji slijedi, pa su na stranicama završavali naslovi
# poput "Kuća 9 402 m² — Lužan čkbr" i "Gornje Vrapče kao suvlasništvo
# ovršenika". Zato se staje na prvoj riječi malim slovom.
_KO_TOKEN = r"[A-ZČĆĐŠŽ][\wčćđšž]*(?:-[A-ZČĆĐŠŽ][\wčćđšž]*)?"
_KO_RE = re.compile(
    rf"k\.?\s*o\.?\s*:?\s*({_KO_TOKEN}(?:\s+{_KO_TOKEN}){{0,3}})"
)

# Riječi koje su u izvoru pisane velikim slovom, ali nisu dio naziva općine
# ("k.o. Grad Zagreb Zemljišnoknjižnog odjela ...").
_KO_STOPWORDS = {
    "zemljisnoknjiznog", "zemljisnoknjizni", "zemljisnoknjizne", "zemljisnoknjizna",
    "opcinskog", "opcinski", "trgovackog", "trgovacki", "suda", "sud", "odjela",
    "odjel", "sluzbe", "sluzba", "vlasnistvo", "vlasnistvu", "etazno", "upisano",
    "upisane", "upisana", "poslovni", "stambeni", "zgrada", "kuca", "stan",
}


def _trim_ko(name: str) -> str:
    """Odbaci repove koji nisu dio naziva katastarske općine."""
    parts = name.split()
    out: list[str] = []
    for p in parts:
        if fold(p.strip(",.;")) in _KO_STOPWORDS:
            break
        out.append(p)
    return " ".join(out).strip(" ,.;-")
_CITY_CTX_RE = re.compile(
    r"\b(?:u|na|iz|kod|blizu|mjestu|naselju|gradu|općini|opcini)\s+"
    r"([A-ZČĆĐŠŽ][\wčćđšžČĆĐŠŽ\-]+(?:\s+[A-ZČĆĐŠŽ][\wčćđšž\-]+){0,2})"
)

# Lokativ/genitiv -> nominativ za česte gradove (hrvatska deklinacija).
_LOCATIVE_FIX = {
    "rijeci": "Rijeka", "splitu": "Split", "zagrebu": "Zagreb", "osijeku": "Osijek",
    "zadru": "Zadar", "puli": "Pula", "sibeniku": "Šibenik", "dubrovniku": "Dubrovnik",
    "karlovcu": "Karlovac", "varazdinu": "Varaždin", "sisku": "Sisak",
    "bjelovaru": "Bjelovar", "koprivnici": "Koprivnica", "cakovcu": "Čakovec",
    "pozegi": "Požega", "vinkovcima": "Vinkovci", "vukovaru": "Vukovar",
    "gospicu": "Gospić", "virovitici": "Virovitica", "pazinu": "Pazin",
    "porecu": "Poreč", "rovinju": "Rovinj", "umagu": "Umag", "labinu": "Labin",
    "makarskoj": "Makarska", "sinju": "Sinj", "trogiru": "Trogir", "solinu": "Solin",
    "omisu": "Omiš", "kastelima": "Kaštela", "krku": "Krk", "rabu": "Rab",
    "opatiji": "Opatija", "crikvenici": "Crikvenica", "kninu": "Knin",
    "drnisu": "Drniš", "metkovicu": "Metković", "korculi": "Korčula",
    "slavonskom brodu": "Slavonski Brod", "novoj gradiski": "Nova Gradiška",
    "velikoj gorici": "Velika Gorica", "samoboru": "Samobor", "zapresicu": "Zaprešić",
    "kutini": "Kutina", "petrinji": "Petrinja", "ogulinu": "Ogulin",
    "djakovu": "Đakovo", "dakovu": "Đakovo", "nasicama": "Našice",
    "belisću": "Belišće", "belom manastiru": "Beli Manastir", "valpovu": "Valpovo",
    "zupanji": "Županja", "ilok": "Ilok", "prelogu": "Prelog", "senju": "Senj",
    "otoccu": "Otočac", "novalji": "Novalja", "benkovcu": "Benkovac",
    "biogradu": "Biograd na Moru", "vodicama": "Vodice", "plocama": "Ploče",
}

_TOWN_LOOKUP = {fold(t): t for t in croatia.TOWN_COUNTY}


def _canonical_town(name: str | None) -> str | None:
    """Jedan naziv po naselju — inače dvije varijante daju isti URL."""
    if not name:
        return None
    return croatia.TOWN_CANONICAL.get(name, name)


def _resolve_town(candidate: str) -> str | None:
    """Vrati kanonski naziv naselja ako ga prepoznajemo."""
    if not candidate:
        return None
    c = candidate.strip(" ,.;:-")
    f = fold(c)
    if f in _LOCATIVE_FIX:
        return _canonical_town(_LOCATIVE_FIX[f])
    if f in _TOWN_LOOKUP:
        return _canonical_town(_TOWN_LOOKUP[f])
    # probaj bez zadnje riječi (npr. "Splitu Gradu" -> "Splitu")
    parts = c.split()
    if len(parts) > 1:
        f2 = fold(" ".join(parts[:-1]))
        if f2 in _LOCATIVE_FIX:
            return _canonical_town(_LOCATIVE_FIX[f2])
        if f2 in _TOWN_LOOKUP:
            return _canonical_town(_TOWN_LOOKUP[f2])
    return None


def _county_from_court(issuer: str, issuer_type: str) -> str | None:
    """Županija iz naziva SUDA. Samo općinski sudovi — v. docstring modula."""
    if issuer_type != "opcinski_sud":
        return None
    # "Stalna služba u X" je uža i ima prednost pred sjedištem suda.
    m = re.search(r"stalna\s+služba\s+u\s+(.+)$", issuer, re.IGNORECASE)
    tail = m.group(1).strip() if m else None
    if tail:
        for town, county in croatia.COURT_TOWN_COUNTY.items():
            if fold(town) == fold(tail):
                return county
    m2 = re.search(r"sud\s+u\s+([^,]+)", issuer, re.IGNORECASE)
    if m2:
        seat = m2.group(1).strip()
        for town, county in croatia.COURT_TOWN_COUNTY.items():
            if fold(town) == fold(seat):
                return county
    return None


def extract_location(opis: str, issuer: str, issuer_type: str) -> dict:
    """Izvedi (županija, grad/naselje, katastarska općina) + pouzdanost.

    Pouzdanost:
      visoka  — naselje prepoznato u tekstu opisa
      srednja — samo iz nadležnog općinskog suda
      nema    — nije utvrđeno; ostaje 'Nepoznato' i broji se u izvještaju
    """
    result = {
        "county": None,
        "city": None,
        "cadastral_municipality": None,
        "location_confidence": "nema",
        "location_raw": "",
    }
    text = opis or ""

    # Katastarska općina — korisna i kad grad nije prepoznat.
    ko = _KO_RE.search(text)
    if ko:
        ko_name = _trim_ko(ko.group(1).strip(" ,.;-"))
        if ko_name and not ko_name.isdigit() and len(ko_name) >= 3:
            result["cadastral_municipality"] = ko_name[:80]

    # 1. grad iz konteksta u opisu
    candidates: list[str] = []
    for m in _CITY_CTX_RE.finditer(text):
        candidates.append(m.group(1))
    if result["cadastral_municipality"]:
        candidates.append(result["cadastral_municipality"])

    for cand in candidates:
        town = _resolve_town(cand)
        if town and town not in croatia.AMBIGUOUS_TOWNS:
            county = croatia.TOWN_COUNTY.get(town)
            if county:
                result.update(
                    county=county, city=town,
                    location_confidence="visoka", location_raw=cand.strip(),
                )
                return result

    # 2. rezerva: općinski sud
    county = _county_from_court(issuer, issuer_type)
    if county:
        result.update(county=county, location_confidence="srednja", location_raw=issuer)
        return result

    # 3. dvosmisleno naselje bez potvrde — zabilježi sirovo, ne pogađaj županiju
    for cand in candidates:
        town = _resolve_town(cand)
        if town:
            result.update(city=town, location_raw=cand.strip())
            break
    return result


# ---------------------------------------------------------------------------
# Status, popust
# ---------------------------------------------------------------------------

def derive_status(start: datetime | None, end: datetime | None, snapshot: datetime) -> str:
    """Status se izvodi — CSV ga nema (v. docs/source-notes.md §5)."""
    if not start or not end:
        return "bez_termina"
    if snapshot < start:
        return "najavljeno"
    if start <= snapshot <= end:
        return "u_tijeku"
    return "zavrseno"


STATUS_LABELS = {
    "najavljeno": "Najavljeno",
    "u_tijeku": "U tijeku",
    "zavrseno": "Završeno",
    "bez_termina": "Bez termina nadmetanja",
}


def compute_discount(estimated: float | None, opening: float | None) -> float | None:
    """Popust početne cijene u odnosu na procijenjenu vrijednost, u postotku.

    Pozitivno = početna cijena je ispod procjene (prilika).
    Vraća None ako bilo koji ulaz nedostaje — nikad se ne pretpostavlja 0.
    """
    if estimated is None or opening is None or estimated <= 0:
        return None
    return round((estimated - opening) / estimated * 100.0, 2)


# Popust iznad ove granice gotovo sigurno je greška u unosu izvora,
# a ne prilika (recon je našao predmet s procjenom 523 856 € i početnom 0,13 €).
DISCOUNT_SANITY_LIMIT = 99.0


def is_suspicious_discount(estimated: float | None, opening: float | None,
                           discount: float | None) -> bool:
    if discount is None:
        return False
    if discount >= DISCOUNT_SANITY_LIMIT:
        return True
    if opening is not None and opening < 1.0 and (estimated or 0) > 1000:
        return True
    return False


EJD_ORDER = {"Prva": 1, "Druga": 2, "Treća": 3, "Četvrta": 4}


# ---------------------------------------------------------------------------
# Glavni ulaz
# ---------------------------------------------------------------------------

def normalise_item(clean_row: dict, viewing: str = "") -> dict:
    """Pretvori redigirani CSV redak u zapis spreman za bazu."""
    opis = clean_row.get("Opis", "")
    issuer = clean_row.get("Nadležno tijelo", "")
    issuer_type = clean_row.get("_issuer_type") or normalise_issuer(issuer)[0]

    snapshot = parse_dt(clean_row.get("Stanje na dan", "")) or datetime.now()
    start = parse_dt(clean_row.get("Datum i vrijeme početka nadmetanja", ""))
    end = parse_dt(clean_row.get("Datum i vrijeme završetka nadmetanja", ""))

    estimated = parse_money(clean_row.get("Utvrđena vrijednost", ""))
    opening = parse_money(clean_row.get("Početna cijena za nadmetanje", ""))
    minimum = parse_money(
        clean_row.get("Minimalna zakonska cijena ispod koje se predmet prodaje ne može prodati", "")
    )
    deposit = parse_money(clean_row.get("Iznos jamčevine", ""))
    step = parse_money(clean_row.get("Iznos dražbenog koraka", ""))

    area_m2, area_unit = parse_area(opis)
    loc = extract_location(opis, issuer, issuer_type)
    discount = compute_discount(estimated, opening)
    ptype = classify_property(opis, clean_row.get("Vrsta predmeta prodaje", ""))

    case_ref = clean_row.get("Poslovni broj spisa", "").strip()
    auction_id = clean_row.get("ID nadmetanja", "").strip()
    ejd = clean_row.get("Oznaka EJD", "").strip()

    item = {
        "case_ref": case_ref,
        "auction_id": auction_id or None,
        "issuer_type": issuer_type,
        "issuer_name": issuer,
        "description": opis,
        "property_type": ptype,
        "procedure_type": _procedure_from_case_ref(case_ref),
        "sale_method": clean_row.get("Način prodaje", ""),
        "scope": clean_row.get("Složenost PP / opseg imovine", ""),
        "county": loc["county"],
        "city": loc["city"],
        "cadastral_municipality": loc["cadastral_municipality"],
        "location_confidence": loc["location_confidence"],
        "location_raw": loc["location_raw"],
        "estimated_value_eur": estimated,
        "opening_price_eur": opening,
        "minimum_price_eur": minimum,
        "deposit_eur": deposit,
        "bid_step_eur": step,
        # Trenutna ponuda nije u službenom exportu — vidljiva je samo u živoj
        # aplikaciji. Ostaje None; nikad se ne izmišlja. (source-notes.md §5)
        "current_bid_eur": None,
        "discount_pct": discount,
        "discount_suspicious": is_suspicious_discount(estimated, opening, discount),
        "area_m2": area_m2,
        "area_unit_source": area_unit,
        "auction_round": ejd or None,
        "auction_round_no": EJD_ORDER.get(ejd),
        "decision_date": parse_dt(clean_row.get("Datum odluke o prodaji", "")),
        "publish_start": parse_dt(clean_row.get("Datum i vrijeme početka", "")),
        "auction_start": start,
        "auction_end": end,
        "extendable": clean_row.get(
            "Mogućnost produljenja nadmetanja (za dodatnih 10 minuta)", "") == "Da",
        "deposit_value_date": parse_dt(clean_row.get("Datum valute jamčevine", "")),
        "viewing_time": viewing,
        "status": derive_status(start, end, snapshot),
        "snapshot_date": snapshot.date(),
    }
    item["item_key"] = build_item_key(item)
    item["slug"] = build_slug(item)
    return item


def _procedure_from_case_ref(case_ref: str) -> str:
    """Vrsta postupka iz oznake spisa: OVR- = ovrha, ST- = stečaj."""
    c = (case_ref or "").upper()
    if c.startswith("OVR"):
        return "ovrha"
    if c.startswith("ST"):
        return "stecaj"
    if c.startswith("OSIG") or c.startswith("OS-"):
        return "osiguranje"
    if c.startswith("INS"):
        return "insolvencija"
    return "ostalo"


def build_item_key(item: dict) -> str:
    """Stabilan i jedinstven ključ stavke.

    Dva zahtjeva su u napetosti:

    * **stabilnost** — ključ se ne smije mijenjati između pokretanja, inače
      promjena cijene izgleda kao nova stavka i praćenje kroz vrijeme pada;
    * **jedinstvenost** — različite stavke ne smiju dobiti isti ključ, inače
      se tiho gube.

    `ID nadmetanja` sam po sebi nije dovoljan: u exportu postoji 10 slučajeva
    gdje dvije *različite* stavke dijele isti ID (razlikuju se po datumu
    odluke, jamčevini, opsegu). Zato ključ uključuje i nepromjenjive
    činjenice o predmetu — datum odluke o prodaji, procijenjenu vrijednost,
    redni broj dražbe — ali NIKAD podatke koji se legitimno mijenjaju
    (početna cijena, trenutna ponuda, status).
    """
    import hashlib

    basis = "|".join([
        item.get("case_ref") or "",
        item.get("auction_id") or "",
        (item.get("description") or "")[:400],
        str(item.get("estimated_value_eur") or ""),
        str(item.get("auction_round") or ""),
        item["decision_date"].date().isoformat() if item.get("decision_date") else "",
        item["publish_start"].date().isoformat() if item.get("publish_start") else "",
        str(item.get("scope") or ""),
        # Izvor ponekad istu stavku vodi pod dvije vrste ("pravo" vs
        # "nekretnina"); to je stabilna razlika i pripada u ključ.
        str(item.get("property_type") or ""),
    ])
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    if item.get("auction_id"):
        return f"nad-{item['auction_id']}-{digest[:8]}"
    return f"spis-{digest}"


def build_slug(item: dict) -> str:
    bits = [
        PROPERTY_TYPE_LABELS.get(item["property_type"], "nekretnina"),
        item.get("city") or item.get("cadastral_municipality") or "",
    ]
    base = slugify("-".join(b for b in bits if b)) or "nekretnina"
    return f"{base}-{slugify(item['item_key'])}"
