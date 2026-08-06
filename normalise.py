"""Normalizacija: lokacija, površina, vrsta nekretnine, popust, status.

Radi na retku koji je VEĆ prošao `sanitise.py`. Nikad ne dira sirovi CSV
redak — tako slobodni tekst s osobnim podacima ne može zaobići redakciju.

Poštene rezerve
---------------
Očevidnik nema strukturiranu lokaciju (v. docs/source-notes.md §5). Postoje
četiri neovisna pokazatelja, svaki pogrešiv:

  1. naselje izrijekom navedeno u opisu  ("nalazi se u Rijeci")
  2. naziv katastarske općine            ("k.o. Blato Novo")
  3. zemljišnoknjižni odjel              ("Zemljišnoknjižni odjel Pakrac")
  4. sjedište nadležnog OPĆINSKOG suda

Pouzdanost se ne dodjeljuje po tome koji je pokazatelj proradio, nego po tome
slažu li se dva neovisna (v. `extract_location`). Razlog je mjeren: naziv k.o.
i sjedište suda proturječe si u 6,4 % slučajeva, a naziv katastarske općine
nije isto što i naziv naselja — "Blato Novo" je zagrebačka k.o., dok je Blato
mjesto na Korčuli.

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
    # Izvorna vrsta "imovina" zna pokrivati i strojeve, stoku i robu; bez ove
    # provjere krave iz ST-114/2018 završe na stranici kao "nekretnina".
    if v == "imovina" and not re.search(
            r"\bzk\.?\s*ul|\bk\.?\s*[oc]\b|zemlji[sš]t|nekretnin|kč|čest", text):
        if re.search(r"\b(vozil|automobil|stroj|oprem|plovil|brodic|prikolic|"
                     r"vilicar|viličar|goved|krav|junic|telad|svinj|roba|zalih|"
                     r"komada|proizvodnj|marke|udjel|dionic|potrazivanj)", text):
            return "pokretnina"
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
# Izvor piše i "k.o. Ime", "K.O. Ime", "K.O.329525 Ime" (matični broj između
# oznake i imena), pa i punim riječima "Katastarska općina: 335053, Starigrad".
# Prefiks je neosjetljiv na velika slova — ali SAMO prefiks; sam naziv ostaje
# osjetljiv, da se ne proguta obična proza.
# (?<!\w) je nužan: bez granice riječi "KO" unutar "OPĆINSKOG" (verzal!)
# lažno pali prefiks i pojede pravi "K.O. JAKUŠEVEC" dalje u tekstu.
_KO_PREFIX = r"(?<!\w)(?:[Kk]\.?\s*[Oo]\.?|[Kk]atastarsk\w+\s+[Oo]p[cć]in\w*)\s*:?\s*"
_KO_RE = re.compile(
    rf"{_KO_PREFIX}(?:\d{{4,6}}[\s,]+)?({_KO_TOKEN}(?:\s+{_KO_TOKEN}){{0,3}})"
)

# Popustljiva varijanta: prvo slovo smije biti malo ("k.o. sesvete Novo").
# Koristi se SAMO kad stroga ne uhvati ništa, i SAMO uz potvrdu da uhvaćeno
# ime postoji u službenom registru k.o. — v. extract_location.
_KO_TOKEN_L = r"[A-Za-zČĆĐŠŽčćđšž][\wčćđšž]*(?:-[A-Za-zČĆĐŠŽčćđšž][\wčćđšž]*)?"
_KO_RE_LOOSE = re.compile(
    rf"{_KO_PREFIX}(?:\d{{4,6}}[\s,]+)?({_KO_TOKEN_L}(?:\s+{_KO_TOKEN_L}){{0,3}})"
)

# Riječi koje su u izvoru pisane velikim slovom, ali nisu dio naziva općine
# ("k.o. Grad Zagreb Zemljišnoknjižnog odjela ...").
_KO_STOPWORDS = {
    "zemljisnoknjiznog", "zemljisnoknjizni", "zemljisnoknjizne", "zemljisnoknjizna",
    "opcinskog", "opcinski", "trgovackog", "trgovacki", "suda", "sud", "odjela",
    "odjel", "sluzbe", "sluzba", "vlasnistvo", "vlasnistvu", "etazno", "upisano",
    "upisane", "upisana", "poslovni", "stambeni", "zgrada", "kuca", "stan",
    "zk", "ul", "zkul", "kc", "kcbr", "ckbr", "br", "broj", "cest", "cestica",
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
# "na adresi Dugopolje" je doslovna izjava o lokaciji — mora biti u kontekstu.
_CITY_CTX_RE = re.compile(
    r"\b(?:u|na|iz|kod|blizu|mjestu|naselju|gradu|općini|opcini|adresi)\s+"
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


# Katastarske općine često nose redni nastavak ("Novalja I", "Dugo Selo II").
# On se smije odbaciti — riječ je o istom naselju.
_ORDINAL_SUFFIX = re.compile(r"\s+(?:[IVX]{1,4}|\d{1,2})$")

# Niz riječi velikim početnim slovom — za skeniranje spomena mjesta u opisu.
_TOK_TITLE_RE = r"[A-ZČĆĐŠŽ][\wčćđšž]{2,}"

# Matični broj k.o. iz opisa ("k.o. 309656 Garešnica", "K.O.329525 Dugopolje").
_KO_CODE_RE = re.compile(rf"{_KO_PREFIX}(\d{{4,6}})\b")


def _approx_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Gruba udaljenost — dovoljna za pitanje "je li k.o. u toj županiji"."""
    import math
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return (dlat * dlat + dlon * dlon) ** 0.5


def locate_ko_point(description: str, ko_name: str | None,
                    county: str | None) -> tuple[float, float, str] | None:
    """Koordinate referentne točke k.o. iz DGU registra (ako postoji).

    Redoslijed povjerenja:
      1. matični broj k.o. iz opisa -> izravno, jednoznačno;
      2. naziv k.o. jedinstven u registru -> izravno;
      3. naziv postoji više puta -> uzmi kandidata unutar ~90 km od središta
         utvrđene županije; bez županije ili bez jednoznačnog kandidata -> ništa.

    Točka je razina KATASTARSKE OPĆINE (susjedstvo/naselje), ne parcele —
    to se i prikazuje kao takvo.
    """
    by_code, by_name = croatia.ko_points()
    if not by_code:
        return None

    m = _KO_CODE_RE.search(description or "")
    if m and m.group(1) in by_code:
        name, lat, lon = by_code[m.group(1)]
        return lat, lon, f"k.o. {name} (matični broj)"

    if not ko_name:
        return None
    cands = by_name.get(fold(_ORDINAL_SUFFIX.sub("", ko_name.strip()))) or []
    if len(cands) == 1:
        _, name, lat, lon = cands[0]
        return lat, lon, f"k.o. {name}"
    if len(cands) > 1 and county in croatia.COUNTY_CENTROIDS:
        clat, clon = croatia.COUNTY_CENTROIDS[county]
        near = [(c, _approx_km(clat, clon, c[2], c[3])) for c in cands]
        near = [x for x in near if x[1] <= 90]
        if len(near) == 1:
            _, name, lat, lon = near[0][0]
            return lat, lon, f"k.o. {name}"
    return None


def _resolve_town(candidate: str) -> str | None:
    """Vrati kanonski naziv naselja ako ga prepoznajemo.

    Namjerno NE odbacuje zadnju riječ naziva. Ranija inačica je to radila
    kao rezervu i time proizvodila samouvjereno pogrešne županije:

        "Velika Mlaka" -> "Velika"  -> Požeško-slavonska  (a to je Zagrebačka)
        "Blato Novo"   -> "Blato"   -> Dubrovačko-neretv. (a to je Grad Zagreb)
        "Sesvete Novo" -> "Sesvete" -> Grad Zagreb        (a to je Zagrebačka)

    Naziv katastarske općine i naziv naselja nisu ista vrsta podatka; podudarnost
    mora biti potpuna. Jedina dopuštena preinaka je odbacivanje rednog nastavka.
    """
    if not candidate:
        return None
    c = candidate.strip(" ,.;:-")
    for probe in (c, _ORDINAL_SUFFIX.sub("", c)):
        f = fold(probe)
        if f in _LOCATIVE_FIX:
            return _canonical_town(_LOCATIVE_FIX[f])
        if f in _TOWN_LOOKUP:
            return _canonical_town(_TOWN_LOOKUP[f])
    return None


# Zemljišnoknjižni odjel prati lokaciju NEKRETNINE (zemljišna knjiga se vodi
# po katastarskoj općini), pa je bolji pokazatelj od sjedišta suda.
# Pisari pišu "Zemljišnoknjižni odjel X", kraticom "ZK odjel X", pa i sve
# VERZALOM — oznaka je zato neosjetljiva na velika slova, a hvatanje imena
# ostaje ograničeno (ime ide kroz kuriranu tablicu, pa proza ne prolazi).
_ZK_RE = re.compile(
    r"(?i:(?:zemlji[šs]noknji[žz]n\w*|zk\.?)\s+odjel\w*)\s+(?:[Uu]\s+)?"
    r"([A-ZČĆĐŠŽ][\wčćđšž\-]+(?:\s+[A-ZČĆĐŠŽ][\wčćđšž\-]+)?)"
)


def _town_from_land_registry(opis: str) -> str | None:
    m = _ZK_RE.search(opis or "")
    if not m:
        return None
    town = _resolve_town(m.group(1))
    if town and town not in croatia.AMBIGUOUS_TOWNS and croatia.TOWN_COUNTY.get(town):
        return town
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

    Nijedan pojedinačni pokazatelj nije pouzdan sam za sebe, pa se pouzdanost
    ne dodjeljuje po tome KOJI je pokazatelj proradio, nego po tome SLAŽU LI SE
    dva neovisna pokazatelja:

      visoka   — naselje izrijekom navedeno u opisu ("nalazi se u Rijeci"),
                 ili se naziv k.o. slaže sa zemljišnoknjižnim odjelom / sudom
      srednja  — samo jedan pokazatelj, bez potvrde
      niska    — pokazatelji se PROTURJEČE; uzima se zemljišnoknjižni odjel,
                 odnosno sud, jer prate lokaciju nekretnine
      nema     — nije utvrđeno; ostaje 'Nepoznato' i broji se u izvještaju

    Mjereno nad 11 091 retkom, naziv k.o. i sjedište općinskog suda proturječe
    si u 6,4 % slučajeva. Ranija verzija je u takvim slučajevima ipak tvrdila
    „visoka" — dakle bila je samouvjereno pogrešna. Radije se prizna nesigurnost.
    """
    result = {
        "county": None,
        "city": None,
        "cadastral_municipality": None,
        "location_confidence": "nema",
        "location_raw": "",
    }
    text = opis or ""

    # Katastarska općina — korisna i kad grad nije prepoznat. Prolazi se
    # kroz SVE pogotke, ne samo prvi: raniji pogodak zna nakon čišćenja
    # ostati prazan, a pravi "k.o. Ime" tek slijedi.
    for ko in _KO_RE.finditer(text):
        ko_name = _trim_ko(ko.group(1).strip(" ,.;-"))
        if ko_name and not ko_name.isdigit() and len(ko_name) >= 3:
            result["cadastral_municipality"] = ko_name[:80]
            break

    if not result["cadastral_municipality"]:
        # Sudski pisar zna ime napisati malim slovom ("k.o. sesvete Novo") i
        # stroga varijanta ga tada ne uhvati. Popustljiva varijanta hvata i
        # takve zapise, ali kandidat mora POSTOJATI u službenom registru k.o.
        # (potpuno ime, bez prefiksnog pogađanja) — članstvo u registru je
        # jači čuvar od velikog slova, pa obična proza ne prolazi.
        m = _KO_RE_LOOSE.search(text)
        if m:
            cand = _trim_ko(m.group(1).strip(" ,.;-"))
            if cand and not cand.isdigit() and len(cand) >= 3:
                key = fold(_ORDINAL_SUFFIX.sub("", cand))
                hits = croatia.ko_points()[1].get(key) or []
                if hits:
                    result["cadastral_municipality"] = hits[0][1].title()[:80]

    def _candidates(name: str | None) -> dict[str, int]:
        """Županija -> stanovništvo najvećeg istoimenog naselja u njoj.

        Dva izvora: kurirana tablica većih mjesta (pokriva sklonidbene oblike
        poput "u Rijeci") i službeni DZS registar svih 6 357 naselja s
        popisnim stanovništvom (Otvorena dozvola; v. tools/build_naselja.py).
        Ime koje postoji u više županija vraća više kandidata.
        """
        if not name:
            return {}
        out: dict[str, int] = {}
        clean = _ORDINAL_SUFFIX.sub("", name.strip(" ,.;:-"))
        for _, _, county, pop in croatia.settlements().get(fold(clean), []):
            out[county] = max(out.get(county, 0), pop)
        t = _resolve_town(name)
        if t and t not in croatia.AMBIGUOUS_TOWNS:
            c = croatia.TOWN_COUNTY.get(t)
            if c:
                out.setdefault(c, 0)
        return out

    def _dominant(cands: dict[str, int]) -> str | None:
        """Županija čije je istoimeno naselje ≥20× veće od svih ostalih.

        Rješava slučajeve poput "Dugopolje": mjesto kraj Splita (3 248 st.)
        prema zaselku kraj Gračca (17 st.) — omjer 191:1. Ovo je izmjeren
        prag nad službenim popisom, ne dojam; ispod praga se NE pogađa.
        """
        if len(cands) < 2:
            return None
        ranked = sorted(cands.items(), key=lambda kv: -kv[1])
        top, second = ranked[0], ranked[1]
        if top[1] >= 20 * max(second[1], 1):
            return top[0]
        return None

    def _display_name(name: str) -> str:
        """Službeni zapis imena naselja iz DZS registra.

        Izvor isto mjesto piše i "Susak" i "Sušak"; bez normalizacije na
        službeni zapis dvije bi varijante dale dvije stranice s istim URL-om
        (guard protiv prepisivanja to je i uhvatio). Registar je autoritet
        za zapis imena; kod više istoimenih uzima se najmnogoljudnije.
        """
        clean = _ORDINAL_SUFFIX.sub("", name.strip(" ,.;:-"))
        hits = croatia.settlements().get(fold(clean), [])
        if hits:
            return max(hits, key=lambda h: h[3])[0]
        # k.o. registar kao kanonski zapis: izvor isto ime piše i verzalom
        # ("TREŠNJEVKA NOVA") i mješovito ("Trešnjevka Nova") — bez jednog
        # kanonskog oblika dva zapisa daju dvije stranice s istim URL-om.
        ko_hits = croatia.ko_points()[1].get(fold(clean), [])
        if len(ko_hits) == 1:
            return ko_hits[0][1].title()
        return _canonical_town(_resolve_town(clean) or clean)

    zk_town = _town_from_land_registry(text)
    zk_county = croatia.TOWN_COUNTY.get(zk_town) if zk_town else None
    court_county = _county_from_court(issuer, issuer_type)
    anchors = {c for c in (zk_county, court_county) if c}

    def _text_hints() -> set[str]:
        """Županije JEDNOZNAČNIH imena mjesta spomenutih bilo gdje u opisu.

        Pisar zna lokaciju navesti izvan svake formule ("na adresi
        Dicmo-Kraj"). Ovi glasovi NIKAD sami ne određuju županiju — smiju
        samo presuditi između već postojećih kandidata (presjek), pa ulično
        ime poput "Splitska" ne može ništa izmisliti. Složenice se
        razdvajaju i po crtici.
        """
        hints: set[str] = set()
        for m in re.finditer(rf"{_TOK_TITLE_RE}(?:[\s\-]{_TOK_TITLE_RE}){{0,2}}", text):
            frag = m.group(0)
            parts = [frag, frag.replace("-", " ")] + [
                p for p in re.split(r"[\s\-]+", frag) if len(p) >= 5
            ]
            for cand in parts:
                cs = _candidates(cand)
                if len(cs) == 1:
                    hints.add(next(iter(cs)))
        return hints

    hints: set[str] | None = None   # lijeno — treba tek kod dvosmislenih

    def _tiebreak(counties: set[str]) -> str | None:
        """Presudi među kandidatima: prvo sidra, zatim glasovi iz teksta."""
        nonlocal hints
        hit = anchors & counties
        if len(hit) == 1:
            return next(iter(hit))
        if hints is None:
            hints = _text_hints()
        hit = hints & counties
        if len(hit) == 1:
            return next(iter(hit))
        return None

    def _nearest_assigned(lat: float, lon: float) -> str | None:
        """Županija najbliže PRIDRUŽENE k.o. — za k.o. koje su u registru
        koordinata, ali uz granicu županija nisu dobile jednoglasan glas
        (npr. STARIGRAD kod Paklenice). Točka je poznata, susjedstvo
        presuđuje; preko 12 km se ne pogađa."""
        ko_map2 = croatia.ko_county()
        near: list[tuple[float, str]] = []
        for code2, (_n2, la2, lo2) in croatia.ko_points()[0].items():
            c2 = ko_map2.get(code2)
            if not c2:
                continue
            d = _approx_km(lat, lon, la2, lo2)
            if d <= 12.0:
                near.append((d, c2))
        near.sort()
        top3 = {c for _, c in near[:3]}
        # jednoglasnost tri najbliže — pojedinačni najbliži susjed je na
        # kopnenoj granici bacanje novčića, a preko morskog kanala i gore
        return next(iter(top3)) if len(near) >= 3 and len(top3) == 1 else None

    ko_name = result["cadastral_municipality"] or ""

    # Ime k.o. koje JE ime županije ("k.o. GRAD ZAGREB"): zemljišnoknjižne
    # k.o. u Zagrebu ne postoje u katastarskom registru DGU-a, ali samo ime
    # izravno kaže županiju — nema se što dalje izvoditi.
    if ko_name:
        _fko = fold(ko_name)
        for _county in croatia.COUNTY_CENTROIDS:
            if _fko == fold(_county) or _fko == fold(_county.replace(" županija", "")):
                result.update(county=_county, location_confidence="srednja",
                              location_raw=f"k.o. {ko_name} = županija")
                return result

    reg_county = None
    ko_map = croatia.ko_county()
    if ko_map:
        m_code = _KO_CODE_RE.search(text)
        if m_code and m_code.group(1) in ko_map:
            reg_county = ko_map[m_code.group(1)]
        elif m_code and m_code.group(1) in croatia.ko_points()[0]:
            _n, _la, _lo = croatia.ko_points()[0][m_code.group(1)]
            reg_county = _nearest_assigned(_la, _lo)
        elif ko_name:
            _fk = fold(_ORDINAL_SUFFIX.sub("", ko_name.strip()))
            entries = croatia.ko_points()[1].get(_fk) or []
            if not entries and "-" in _fk:
                # "Komarna-Duboka" ↔ registar "KOMARNA DUBOKA"
                entries = croatia.ko_points()[1].get(_fk.replace("-", " ")) or []
            if not entries and " " in _fk:
                # obrnuti red riječi: "Bistra Donja" u opisu, "DONJA BISTRA"
                # u registru — isti tokeni, drugi redoslijed
                _sk = " ".join(sorted(_fk.split()))
                for _ents in croatia.ko_points()[1].values():
                    if " ".join(sorted(fold(_ents[0][1]).split())) == _sk:
                        entries = _ents
                        break
            if len(entries) == 1:
                reg_county = ko_map.get(entries[0][0])
                if reg_county is None:
                    # k.o. postoji u registru koordinata, ali uz granicu nije
                    # dobila jednoglasnu županiju ("Sisak Stari") — točka je
                    # poznata, najbliža pridružena k.o. presuđuje (≤ 12 km)
                    reg_county = _nearest_assigned(entries[0][2], entries[0][3])
            elif len(entries) > 1:
                # istoimene k.o. u više županija ("KRAJ" ×3): županije svih
                # kandidata iz registra, pa presuda sidrom ili spomenom
                # mjesta u opisu ("na adresi Dicmo-Kraj" -> Dicmo -> SD)
                cand_counties = {ko_map[e[0]] for e in entries if e[0] in ko_map}
                if len(cand_counties) == 1:
                    reg_county = next(iter(cand_counties))
                elif len(cand_counties) > 1:
                    reg_county = _tiebreak(cand_counties)


    # --- 1. naselje izrijekom navedeno u opisu ---------------------------
    for m in _CITY_CTX_RE.finditer(text):
        raw = m.group(1).strip()
        cands = _candidates(raw)
        if len(cands) == 1:
            _c = next(iter(cands))
            if reg_county and _c != reg_county:
                # prozni spomen ("u Krajačici" — rudina!) proturječi
                # koordinatno potvrđenoj k.o. — registar je jači, proza se
                # preskače umjesto da samouvjereno odvede u krivu županiju
                continue
            result.update(county=_c, city=_display_name(raw),
                          location_confidence="visoka", location_raw=raw)
            return result
        if len(cands) > 1:
            tb = _tiebreak(set(cands))
            if tb:
                # dvosmisleno ime, ali ga drugi neovisni pokazatelj potvrđuje
                result.update(county=tb, city=_display_name(raw),
                              location_confidence="visoka", location_raw=raw)
                return result
            dom = _dominant(cands)
            if dom:
                # izrijekom navedeno, ime dvoznačno, ali populacijski omjer
                # ≥20:1 — razuman zaključak, označen kao neprovjeren
                result.update(county=dom, city=_display_name(raw),
                              location_confidence="srednja",
                              location_raw=f"{raw} (dominantno naselje)")
                return result

    # --- 2. katastarska općina (registar je izračunat gore, prije proze) --
    if reg_county:
        if not anchors or reg_county in anchors:
            result.update(county=reg_county, city=_display_name(ko_name) if ko_name else None,
                          location_confidence="visoka" if reg_county in anchors
                          else "srednja",
                          location_raw=f"k.o. registar: {ko_name or 'matični broj'}")
            return result
        # sidro se ne slaže s registrom koordinata — koordinate su izravnije
        # od sjedišta suda, ali neslaganje se priznaje
        result.update(county=reg_county, city=_display_name(ko_name) if ko_name else None,
                      location_confidence="niska",
                      location_raw=f"k.o. {ko_name} ≠ {zk_town or issuer}")
        return result

    ko_cands = _candidates(ko_name)

    if len(ko_cands) == 1:
        ko_county = next(iter(ko_cands))
        if not anchors or ko_county in anchors:
            # jedinstveno ime; s potvrdom "visoka", bez sidra "srednja"
            result.update(county=ko_county, city=_display_name(ko_name),
                          location_confidence="visoka" if ko_county in anchors
                          else "srednja",
                          location_raw=ko_name)
            return result
        # 3. proturječje — priznaj ga i uzmi pokazatelj vezan uz nekretninu
        result.update(county=zk_county or court_county, city=zk_town,
                      location_confidence="niska",
                      location_raw=f"k.o. {ko_name} ≠ {zk_town or issuer}")
        return result

    if len(ko_cands) > 1:
        tb = _tiebreak(set(ko_cands))
        if tb:
            # dvosmisleno ime k.o., ali sidro/spomen mjesta bira kandidata
            # -> dva neovisna pokazatelja se slažu
            result.update(county=tb, city=_display_name(ko_name),
                          location_confidence="visoka", location_raw=ko_name)
            return result
        dom = _dominant(ko_cands)
        if dom:
            result.update(county=dom, city=_display_name(ko_name),
                          location_confidence="srednja",
                          location_raw=f"k.o. {ko_name} (dominantno naselje)")
            return result

    # --- 4. jedan pokazatelj bez potvrde ---------------------------------
    if zk_county:
        result.update(county=zk_county, city=zk_town,
                      location_confidence="srednja",
                      location_raw=f"zemljišnoknjižni odjel {zk_town}")
        return result
    if court_county:
        result.update(county=court_county, location_confidence="srednja",
                      location_raw=issuer)
        return result

    # --- 5. ništa se ne da potvrditi — ne pogađa se ----------------------
    if ko_name:
        result.update(location_raw=ko_name)
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

def normalise_item(clean_row: dict, viewing: str = "",
                   as_of: datetime | None = None) -> dict:
    """Pretvori redigirani CSV redak u zapis spreman za bazu.

    `as_of` je trenutak u odnosu na koji se računa status. Zadano je "sada",
    a ne datum snimka: izvor je dnevni snimak, ali status ("najavljeno" ->
    "u tijeku" -> "završeno") ovisi o satu, pa ponovno generiranje stranica
    nekoliko sati kasnije daje točniji status i bez novih podataka.
    `snapshot_date` i dalje bilježi podrijetlo podataka.
    """
    opis = clean_row.get("Opis", "")
    issuer = clean_row.get("Nadležno tijelo", "")
    issuer_type = clean_row.get("_issuer_type") or normalise_issuer(issuer)[0]

    snapshot = parse_dt(clean_row.get("Stanje na dan", "")) or datetime.now()
    now = as_of or datetime.now()
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
        "status": derive_status(start, end, now),
        "snapshot_date": snapshot.date(),
    }
    point = locate_ko_point(opis, loc["cadastral_municipality"], loc["county"])
    item["latitude"], item["longitude"], item["coord_source"] = (
        point if point else (None, None, None))
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
